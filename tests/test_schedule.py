import unittest
from datetime import datetime, timezone
from unittest.mock import patch, Mock
from bs4 import BeautifulSoup
from trending.schedule import scheduled_mode
from trending.adapters import collect_source
from trending.store import Store
from test_trending import candidate, NOW

class ScheduleTests(unittest.TestCase):
    def test_vietnam_start_and_weekdays(self):
        cases={
            '2026-11-29T23:00:00+00:00':'disabled',
            '2026-11-30T23:00:00+00:00':'full',
            '2026-12-01T23:00:00+00:00':'refresh',
            '2026-12-03T23:00:00+00:00':'full',
            '2026-12-04T23:00:00+00:00':'refresh',
            '2026-12-06T23:00:00+00:00':'refresh',
            '2026-12-07T23:00:00+00:00':'full',
        }
        for at,expected in cases.items():
            self.assertEqual(scheduled_mode(datetime.fromisoformat(at)),expected)
        with self.assertRaises(ValueError):scheduled_mode(datetime(2026,12,1))

    def test_existing_checks_skip_listings_and_followup_discovery(self):
        config={'seeds':['https://example.com/list'],'hosts':['example.com']}
        adapter=Mock(spec=['fetch','parse_many','links'])
        adapter.fetch.return_value=BeautifulSoup('<article></article>','html.parser')
        adapter.parse_many.return_value=[candidate()]
        metrics={}
        with patch.dict('trending.adapters.CLASSES',{'danangfantasticity':Mock(return_value=adapter)}):
            rows,errors=collect_source('danangfantasticity',config,Mock(),NOW,200,
                ['https://example.com/known'],metrics=metrics,existing_only=True)
        self.assertEqual(len(rows),1);self.assertEqual(errors,[])
        self.assertEqual(metrics['listing_pages'],0)
        adapter.links.assert_not_called()
        self.assertEqual(adapter.fetch.call_args.args[1],'https://example.com/known')

    def test_empty_existing_set_is_not_collection_failure(self):
        metrics={}
        rows,errors=collect_source('ticketbox',{'seeds':['https://ticketbox.vn'],'hosts':['ticketbox.vn']},
            Mock(),NOW,metrics=metrics,existing_only=True)
        self.assertEqual((rows,errors),([],[]))
        self.assertEqual(metrics['detail_pages'],0)

    def test_website_cleanup_does_not_touch_provider_reservations(self):
        with patch('trending.store.psycopg.connect') as connect:
            store = Store('test-only')
            execute = connect.return_value.execute
            store.cleanup()
            self.assertEqual(execute.call_count, 2)
            self.assertFalse(any('discovery_provider_jobs' in call.args[0] for call in execute.call_args_list))

            execute.reset_mock()
            store.cleanup(include_provider_jobs=True)
            self.assertEqual(sum('discovery_provider_jobs' in call.args[0] for call in execute.call_args_list), 1)
