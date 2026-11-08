import unittest
from unittest.mock import Mock, patch
from bs4 import BeautifulSoup
from trending.http import PublicClient, FetchError
from trending.adapters import VnExpress, load_sources

class WebsiteFetching(unittest.TestCase):
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
        for code in ['http_403','http_404','host_not_allowed','page_too_large']:
            with patch.object(client,'_get_once',side_effect=FetchError(code)) as fetch:
                with self.assertRaises(FetchError):client.get('https://vnexpress.net/',{'vnexpress.net'})
                self.assertEqual(fetch.call_count,1)

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
