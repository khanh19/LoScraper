import unittest
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from textwrap import dedent
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

    def test_manual_scheduled_rehearsal_requires_default_branch_and_explicit_write(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/trending.yml').read_text()
        step = workflow.split('      - id: policy\n', 1)[1].split('      - name: Record scheduled slot', 1)[0]
        script = dedent(step.split('        run: |\n', 1)[1])
        with TemporaryDirectory() as folder:
            for mode in ('full-scheduled', 'refresh-scheduled'):
                for ref, pilot, allowed in (
                    ('refs/heads/main', 'false', True),
                    ('refs/heads/feature', 'false', False),
                    ('refs/tags/main', 'false', False),
                    ('refs/heads/main', 'true', False),
                ):
                    with self.subTest(mode=mode, ref=ref, pilot=pilot):
                        output = Path(folder) / 'outputs'
                        output.write_text('')
                        env = dict(os.environ, EVENT_NAME='workflow_dispatch', MANUAL_MODE=mode,
                                   MANUAL_PILOT=pilot, DEFAULT_BRANCH='main', GITHUB_REF=ref,
                                   GITHUB_OUTPUT=str(output))
                        result = subprocess.run(['bash', '-s'], input=script, env=env,
                                                capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0 if allowed else 1, result.stderr)
                        self.assertEqual(output.read_text(), f'mode={mode}\n' if allowed else '')

    def test_workflow_preflights_use_the_intended_target_and_never_collect(self):
        workflow = Path(__file__).resolve().parents[1] / '.github/workflows/trending.yml'
        step = workflow.read_text().split('- name: Collect and validate\n', 1)[1]
        script = dedent(step.split('        run: |\n', 1)[1].split('\n      #', 1)[0])
        # Fail the preflight in every case. Even a scheduled run must stop before a write.
        recorder = """python() {
          printf '%s\\n' "$DATABASE_URL" "${LO_DISCOVERY_DATABASE_TARGET:-}" "$*"
          return 1
        }
        """
        base_args = '-m trending.coverage --require-verified-tls --check-collector-writes'
        cases = (
            ('workflow_dispatch', 'check-staging', 'stage', '', base_args),
            ('workflow_dispatch', 'inspect-scheduled', 'scheduled', 'pin', base_args),
            ('workflow_dispatch', 'check-scheduled', 'scheduled', 'pin', base_args + ' --require-target-match'),
            ('schedule', 'full', 'scheduled', 'pin', base_args + ' --require-target-match'),
            ('schedule', 'refresh', 'scheduled', 'pin', base_args + ' --require-target-match'),
            ('workflow_dispatch', 'full-scheduled', 'scheduled', 'pin', base_args + ' --require-target-match'),
            ('workflow_dispatch', 'refresh-scheduled', 'scheduled', 'pin', base_args + ' --require-target-match'),
        )
        with TemporaryDirectory() as folder:
            for event, mode, target, pin, args in cases:
                with self.subTest(event=event, mode=mode):
                    summary = Path(folder) / 'summary'
                    if summary.exists():
                        summary.unlink()
                    env = {
                        'PATH': os.environ['PATH'],
                        'EVENT_NAME': event,
                        'MODE': mode,
                        'INPUT_PILOT': 'false',
                        'STAGING_DATABASE_URL': 'stage',
                        'SCHEDULE_DATABASE_URL': 'scheduled',
                        'SCHEDULE_DATABASE_TARGET': 'pin',
                        'GITHUB_STEP_SUMMARY': str(summary),
                    }
                    result = subprocess.run(['bash', '-s'], input=recorder + script, env=env,
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(summary.read_text().splitlines(), [target, pin, args])

    def test_manual_rehearsal_runs_the_same_collection_as_cron_after_preflight(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/trending.yml').read_text()
        step = workflow.split('- name: Collect and validate\n', 1)[1]
        script = dedent(step.split('        run: |\n', 1)[1].split('\n      #', 1)[0])
        recorder = 'python() { printf "%s %s %s\\n" "$DATABASE_URL" "$LO_DISCOVERY_DATABASE_TARGET" "$*"; }\n'
        with TemporaryDirectory() as folder:
            for mode, expected in (
                ('refresh-scheduled', ['-m trending --browser --write-db --refresh-existing']),
                ('full-scheduled', ['-m trending --browser --write-db --refresh-existing',
                                    '-m trending --browser --supplemental --limit 20 --write-db']),
            ):
                with self.subTest(mode=mode):
                    env = dict(os.environ, EVENT_NAME='workflow_dispatch', MODE=mode,
                               INPUT_PILOT='false', INPUT_CITY='all', STAGING_DATABASE_URL='stage',
                               SCHEDULE_DATABASE_URL='scheduled', SCHEDULE_DATABASE_TARGET='pin',
                               SCHEDULE_DATABASE_ROOT_CA='', GITHUB_STEP_SUMMARY=str(Path(folder) / mode))
                    result = subprocess.run(['bash', '-s'], input=recorder + script, env=env,
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.splitlines()[1:], ['scheduled pin ' + cmd for cmd in expected])

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
