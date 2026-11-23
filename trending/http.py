"""Bounded public-page fetching. No proxy or paid browser fallback."""
from __future__ import annotations

import json
import ipaddress
import os
import re
import socket
import time
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from .model import ICT, canonical


class FetchError(Exception):
    pass


def fetch_failure_reason(error: Exception) -> str:
    if isinstance(error, FetchError):
        reason = str(error)
        if re.fullmatch(r'[A-Za-z_0-9]{1,64}', reason):
            return reason
    return type(error).__name__


def public_url(url: str) -> str:
    # Identity normalization strips a trailing slash; HTTP navigation must preserve it.
    original_path = urlsplit(url).path or '/'
    parts = urlsplit(canonical(url))
    url = urlunsplit(parts._replace(path=original_path))
    host = urlsplit(url).hostname
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FetchError("dns_failed") from exc
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise FetchError("non_public_address")
    return url


class PublicClient:
    def __init__(self, browser=False, delay=1.0):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "LoDiscoveryBot/1.0 (+https://www.lodiscover.com/)", "Accept-Language": "vi,en;q=0.7"})
        self.browser_enabled = browser
        self.delay = max(1.0, delay)
        self.last_fetch = {}
        self.cache = {}
        self._playwright = self._browser = None

    def get(self, url: str, allowed_hosts: set[str], render=False, json_response=False, redirect_only=False):
        # Exactly one retry for transient failures. Only successful parses are cached.
        for attempt in range(2):
            try:
                return self._get_once(url, allowed_hosts, render, json_response, redirect_only)
            except FetchError as exc:
                if attempt or str(exc) not in {'http_408','http_429','http_500','http_502','http_503','http_504','Timeout','ReadTimeout','ConnectTimeout','ConnectionError','TimeoutError'}:
                    raise
                time.sleep(2)
        raise FetchError('retry_exhausted')

    def _get_once(self, url: str, allowed_hosts: set[str], render=False, json_response=False, redirect_only=False):
        url = public_url(url)
        if urlsplit(url).hostname not in allowed_hosts:
            raise FetchError("host_not_allowed")
        key = (url, render, json_response, redirect_only, frozenset(allowed_hosts))
        if key in self.cache:
            return self.cache[key]
        host = urlsplit(url).hostname
        time.sleep(max(0, self.delay - (time.monotonic() - self.last_fetch.get(host, 0))))
        self.last_fetch[host] = time.monotonic()
        if render:
            if not self.browser_enabled:
                raise FetchError("browser_disabled")
            soup = self._render(url, allowed_hosts)
        else:
            try:
                for _ in range(4):
                    with self.session.get(url, timeout=(10, 25), allow_redirects=False, stream=True) as response:
                        if response.is_redirect:
                            from urllib.parse import urljoin
                            target = urljoin(url, response.headers["Location"])
                            if redirect_only:
                                # Identity lookup must not open the destination or fetch media.
                                if urlsplit(canonical(target)).hostname not in allowed_hosts:
                                    raise FetchError("redirect_not_allowed")
                                self.cache[key] = target
                                return target
                            url = public_url(target)
                            if urlsplit(url).hostname not in allowed_hosts:
                                raise FetchError("redirect_not_allowed")
                            continue
                        if response.status_code != 200:
                            raise FetchError(f"http_{response.status_code}")
                        if redirect_only:
                            raise FetchError("redirect_expected")
                        formats = ("json",) if json_response else ("html", "xml")
                        if not any(t in response.headers.get("Content-Type", "") for t in formats):
                            raise FetchError("unsupported_content")
                        data = bytearray()
                        for chunk in response.iter_content(65536):
                            data.extend(chunk)
                            if len(data) > 4_000_000:
                                raise FetchError("page_too_large")
                        soup = json.loads(data) if json_response else BeautifulSoup(bytes(data), "html.parser")
                        break
                else:
                    raise FetchError("redirect_limit")
            except requests.RequestException as exc:
                # Do not log exception URLs or response bodies.
                if isinstance(exc, requests.exceptions.SSLError):
                    raise FetchError('tls_handshake_failed') from None
                raise FetchError(type(exc).__name__) from None
        self.cache[key] = soup
        return soup

    def _render(self, url, allowed_hosts):
        if self._browser is None:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            options = {"headless": True}
            if os.environ.get("LO_BROWSER_CHANNEL"):
                options["channel"] = os.environ["LO_BROWSER_CHANNEL"]
            self._browser = self._playwright.chromium.launch(**options)
        page = self._browser.new_page(locale="vi-VN", timezone_id=ICT.key, service_workers="block")

        def route(request_route):
            request = request_route.request
            if request.resource_type in {"image", "media", "font"}:
                return request_route.abort()
            try:
                public_url(request.url)
                if request.is_navigation_request() and urlsplit(request.url).hostname not in allowed_hosts:
                    raise FetchError("navigation_not_allowed")
                request_route.continue_()
            except (ValueError, FetchError):
                request_route.abort()

        page.route("**/*", route)
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=40000)
            if response is None or response.status != 200:
                raise FetchError(f"http_{response.status}" if response else "no_response")
            # VnExpress food listings use title-news headings, not h1/main.
            page.wait_for_selector("h1,main,h2.title-news,h3.title-news,.title_news,.fck_detail", timeout=15000)
            # Public hydrated event schedules may arrive after the shell.
            page.wait_for_timeout(1500)
            content = page.content()
            if len(content) > 4_000_000:
                raise FetchError("page_too_large")
            return BeautifulSoup(content, "html.parser")
        except FetchError:
            raise
        except Exception as exc:
            transport = re.match(r'Page\.goto: net::(ERR_[A-Z0-9_]{1,48})(?=\s|$)', str(exc))
            if transport:
                raise FetchError('browser_' + transport[1].lower()) from None
            raise FetchError(type(exc).__name__) from None
        finally:
            page.close()

    def close(self):
        self.session.close()
        if self._browser:
            self._browser.close()
            self._playwright.stop()
