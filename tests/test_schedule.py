import unittest
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys
from unittest.mock import patch, Mock
from bs4 import BeautifulSoup
from trending.schedule import FULL_CRON, REFRESH_CRON, scheduled_collection
from trending.adapters import collect_source
from trending.store import Store
from test_trending import candidate, NOW

class ScheduleTests(unittest.TestCase):
    def test_vietnam_start_and_weekdays(self):
        cases = [
            ('2026-11-29', REFRESH_CRON, 'disabled'),
            ('2026-11-30', FULL_CRON, 'full'),
            ('2026-12-01', REFRESH_CRON, 'refresh'),
            ('2026-12-02', REFRESH_CRON, 'refresh'),
            ('2026-12-03', FULL_CRON, 'full'),
            ('2026-12-04', REFRESH_CRON, 'refresh'),
            ('2026-12-05', REFRESH_CRON, 'refresh'),
            ('2026-12-06', REFRESH_CRON, 'refresh'),
            ('2026-12-07', FULL_CRON, 'full'),
        ]
        for day, cron, expected in cases:
            with self.subTest(day=day, cron=cron):
                now = datetime.fromisoformat(day + 'T23:00:00+00:00')
                mode, due = scheduled_collection(now, cron)
                self.assertEqual((mode, due), (expected, now))
                self.assertEqual(due.hour, 6)
        with self.assertRaisesRegex(ValueError, 'timezone_required'):
            scheduled_collection(datetime(2026, 12, 1), FULL_CRON)
        with self.assertRaisesRegex(ValueError, 'unknown_collection_cron'):
            scheduled_collection(datetime(2026, 12, 1, tzinfo=timezone.utc), '0 23 * * *')

    def test_delayed_cron_keeps_its_mode_and_original_start_gate(self):
        now = datetime.fromisoformat('2026-12-02T00:15:00+07:00')
        mode, due = scheduled_collection(now, FULL_CRON)
        self.assertEqual(mode, 'full')
        self.assertEqual(due.isoformat(), '2026-12-01T06:00:00+07:00')
        now = datetime.fromisoformat('2026-12-01T12:30:00+07:00')
        mode, due = scheduled_collection(now, REFRESH_CRON)
        self.assertEqual(mode, 'disabled')
        self.assertEqual(due.isoformat(), '2026-11-30T06:00:00+07:00')

    def test_schedule_cli_uses_original_run_time_and_rejects_missing_or_naive_time(self):
        command = [sys.executable, '-m', 'trending.schedule', '--cron', FULL_CRON]
        root = Path(__file__).resolve().parents[1]
        for created_at, expected in (
            ('2026-11-26T23:02:01Z', 'mode=disabled\ndue=2026-11-27T06:00:00+07:00\n'),
            ('2026-11-30T23:02:01Z', 'mode=full\ndue=2026-12-01T06:00:00+07:00\n'),
        ):
            with self.subTest(created_at=created_at):
                result = subprocess.run(command + ['--triggered-at', created_at], cwd=root,
                                        capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, expected)
        for options in ([], ['--triggered-at', '2026-11-30T23:02:01'], ['--triggered-at', 'null']):
            with self.subTest(options=options):
                result = subprocess.run(command + options, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')

    def test_workflow_declares_each_recognized_trigger(self):
        workflow = Path(__file__).resolve().parents[1] / '.github/workflows/trending.yml'
        self.assertEqual(set(re.findall(r"^\s+- cron: '([^']+)'$", workflow.read_text(), re.M)),
                         {FULL_CRON, REFRESH_CRON})

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
            execute.reset_mock()
            store.cleanup()
            self.assertEqual(execute.call_count, 2)
            self.assertFalse(any('discovery_provider_jobs' in call.args[0] for call in execute.call_args_list))

            execute.reset_mock()
            store.cleanup(include_provider_jobs=True)
            self.assertEqual(sum('discovery_provider_jobs' in call.args[0] for call in execute.call_args_list), 1)
