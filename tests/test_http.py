import unittest
from unittest.mock import Mock, patch
from bs4 import BeautifulSoup
from trending.http import PublicClient, FetchError
from trending.adapters import VnExpress, load_sources

class WebsiteFetching(unittest.TestCase):
    def test_redirect_lookup_does_not_follow_or_read_the_target(self):
        client = PublicClient()
        short = 'https://vt.tiktok.com/share/'
        post = 'https://www.tiktok.com/@venue/video/123'
        response = Mock(is_redirect=True, headers={'Location': post})
        with patch('trending.http.public_url', side_effect=lambda url: url) as checked, patch.object(
            client.session, 'get'
        ) as request:
            request.return_value.__enter__.return_value = response
            self.assertEqual(client.get(short, {'vt.tiktok.com', 'www.tiktok.com'}, redirect_only=True), post)
            self.assertEqual(client.get(short, {'vt.tiktok.com', 'www.tiktok.com'}, redirect_only=True), post)
            with self.assertRaisesRegex(FetchError, 'redirect_not_allowed'):
                client.get(short, {'vt.tiktok.com'}, redirect_only=True)
        self.assertEqual(request.call_count, 2)
        self.assertEqual({call.args[0] for call in checked.call_args_list}, {short})
        self.assertTrue(all(not call.kwargs['allow_redirects'] for call in request.call_args_list))
        response.iter_content.assert_not_called()

    def test_transient_failure_retries_once_and_never_caches_failure(self):
        client=PublicClient()
        soup=BeautifulSoup('<h3 class="title-news">Bài viết</h3>','html.parser')
        with patch.object(client,'_get_once',side_effect=[FetchError('http_503'),soup]) as fetch, patch('trending.http.time.sleep'):
            self.assertIs(client.get('https://vnexpress.net/du-lich/am-thuc',{'vnexpress.net'}),soup)
            self.assertEqual(fetch.call_count,2)
        with patch.object(client,'_get_once',side_effect=FetchError('http_503')) as fetch, patch('trending.http.time.sleep'):
            with self.assertRaisesRegex(FetchError,'http_503'):client.get('https://vnexpress.net/',{'vnexpress.net'})
            self.assertEqual(fetch.call_count,2)
        self.assertEqual(client.cache,{})

    def test_permanent_failure_not_retried(self):
        client=PublicClient()
        for code in ['http_403','http_404','host_not_allowed','page_too_large','tls_handshake_failed']:
            with patch.object(client,'_get_once',side_effect=FetchError(code)) as fetch:
                with self.assertRaises(FetchError):client.get('https://vnexpress.net/',{'vnexpress.net'})
                self.assertEqual(fetch.call_count,1)

    def test_browser_navigation_preserves_only_the_transport_code(self):
        client = PublicClient(browser=True)
        client._browser = Mock()
        page = client._browser.new_page.return_value
        page.goto.side_effect = RuntimeError(
            'Page.goto: net::ERR_SSL_PROTOCOL_ERROR at https://example.org/?token=private\nCall log: private')
        with self.assertRaises(FetchError) as caught:
            client._render('https://example.org/', {'example.org'})
        self.assertEqual(str(caught.exception), 'browser_err_ssl_protocol_error')
        page.close.assert_called_once()

    def test_listing_renderer_accepts_article_headings_and_checks_status(self):
        client=PublicClient(browser=True);page=Mock();client._browser=Mock();client._browser.new_page.return_value=page
        page.goto.return_value.status=200
        page.content.return_value='<h3 class="title-news"><a href="https://vnexpress.net/quan-ca-phe-1234567.html">Cà phê</a></h3>'
        soup=client._render('https://vnexpress.net/du-lich/am-thuc',{'vnexpress.net'})
        self.assertIn('h3.title-news',page.wait_for_selector.call_args.args[0])
        self.assertEqual(len(list(VnExpress('vnexpress',load_sources()['vnexpress']).links(soup,'https://vnexpress.net/du-lich/am-thuc'))),1)
        page.goto.return_value.status=503
        with self.assertRaisesRegex(FetchError,'http_503'):client._render('https://vnexpress.net/',{'vnexpress.net'})
        self.assertEqual(page.close.call_count,2)
