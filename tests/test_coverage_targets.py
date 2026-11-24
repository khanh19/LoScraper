from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from psycopg.errors import InsufficientPrivilege

from trending.coverage import collector_write_blocker, main, markdown_coverage, platform, summarize
from trending.store import (
    DatabaseTargetError, IMAGE_PERMISSION_UPSERT, OBSERVATION_UPSERT, Store,
    WEBSITE_COLLECTION_PLANS, database_target,
)


def row(identity,reason='eligible',section='weekly',urls=()):
    return dict(item_id=identity,reason=reason,payload={
        'section':section,'category':'culture','sources':[{'url':u} for u in urls]})


def connected_feed(**overrides):
    defaults = dict(host='pool.example', port=5432, dbname='lo_feed', user='collector.project-one')
    db = MagicMock()
    db.info = SimpleNamespace(**(defaults | overrides))
    return db


class CoverageTargets(unittest.TestCase):
    def test_distinct_items_not_source_counts(self):
        r=row('a',urls=['https://www.instagram.com/p/a','https://www.tiktok.com/@a/video/1'])
        result=summarize([r,r,row('held','unverified'),row('b',section='planning')],'hanoi')
        self.assertEqual(result['eligible_unique_items'],2)
        self.assertEqual(result['shortfall'],19)
        self.assertEqual(result['missing_social_platforms'],[])
        self.assertEqual(result['sections'],{'weekly':1,'planning':1})

    def test_empty_and_met_targets(self):
        self.assertEqual(summarize([],'danang')['shortfall'],17)
        self.assertFalse(summarize([row(str(i)) for i in range(25)],'hcmc')['target_met'])
        balanced=[row(str(i)) for i in range(18)]+[row('p'+str(i),section='planning') for i in range(7)]
        self.assertTrue(summarize(balanced,'hcmc')['target_met'])
        self.assertEqual(summarize(balanced,'hcmc')['section_shortfalls'],{'weekly':0,'planning':0})
        self.assertEqual(platform('https://instagram.com.evil.example/p/a'),'web')

    def test_summary_reports_section_shortfalls_without_source_urls(self):
        now = datetime(2026, 11, 23, tzinfo=timezone.utc)
        rows = [row(str(i)) for i in range(25)] + [
            row('fresh', urls=['https://instagram.com/p/a', 'https://tiktok.com/@a/video/1']),
            row('held', 'unverified', 'planning', ['https://instagram.com/p/private-preview']),
        ]
        result = markdown_coverage({'hcmc': summarize(rows, 'hcmc')}, now)
        self.assertIn('| hcmc | 26 / 18 | 0 / 7 | 1 | 1 | Below target |', result)
        self.assertNotIn('https://', result)

    def test_preflight_rejects_unverified_tls_before_connecting(self):
        for sslmode in ('', '?sslmode=require', '?sslmode=verify-ca'):
            with self.subTest(sslmode=sslmode):
                output = StringIO()
                env = {'DATABASE_URL': 'postgresql://test:fixture@db.example/feed' + sslmode}
                with (patch.dict('os.environ', env, clear=True),
                      patch('sys.argv', ['coverage', '--require-verified-tls']),
                      patch('psycopg.connect') as connect,
                      redirect_stdout(output),
                      self.assertRaises(SystemExit) as error):
                    main()
                self.assertEqual(error.exception.code, 1)
                self.assertIn('verify_full_required', output.getvalue())
                self.assertNotIn('fixture', output.getvalue())
                connect.assert_not_called()

    def test_target_identity_tracks_endpoint_and_login_but_not_credentials(self):
        target = database_target(connected_feed())
        self.assertRegex(target, r'^[a-f0-9]{64}$')
        equivalent = connected_feed(host='POOL.example.', password='rotated')
        self.assertEqual(database_target(equivalent), target)
        for changed in (dict(host='other.example'), dict(port=6543), dict(dbname='lo_qa'),
                        dict(user='collector.project-two')):
            with self.subTest(changed=changed):
                self.assertNotEqual(database_target(connected_feed(**changed)), target)

    def test_scheduled_preflight_requires_a_valid_target_before_connecting(self):
        for held, reason in (('', 'missing_database_target'), ('malformed', 'invalid_database_target')):
            env = {'DATABASE_URL': 'postgresql://name:password@pool.example/feed?sslmode=verify-full',
                   'LO_DISCOVERY_DATABASE_TARGET': held}
            output = StringIO()
            with (patch.dict('os.environ', env, clear=True),
                  patch('sys.argv', ['coverage', '--require-verified-tls', '--require-target-match']),
                  patch('psycopg.connect') as connect,
                  redirect_stdout(output), self.assertRaises(SystemExit)):
                main()
            self.assertIn(reason, output.getvalue())
            connect.assert_not_called()

    def test_wrong_target_stops_preflight_before_queries(self):
        expected = database_target(connected_feed())
        db = connected_feed(user='collector.project-two')
        env = {'DATABASE_URL': 'postgresql://name:password@pool.example/feed?sslmode=verify-full',
               'LO_DISCOVERY_DATABASE_TARGET': expected}
        output = StringIO()
        with (patch.dict('os.environ', env, clear=True),
              patch('sys.argv', ['coverage', '--check-collector-writes', '--require-target-match']),
              patch('psycopg.connect') as connect, redirect_stdout(output), self.assertRaises(SystemExit) as error):
            connect.return_value.__enter__.return_value = db
            main()
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(output.getvalue(), 'Discovery target check failed (database_target_mismatch).\n')
        db.execute.assert_not_called()

    def test_writer_rejects_an_unapproved_reconnect(self):
        approved = connected_feed()
        redirected = connected_feed(user='collector.project-two')
        with patch('psycopg.connect', side_effect=[approved, redirected]):
            store = Store('fixture', expected_target=database_target(approved))
            with self.assertRaisesRegex(DatabaseTargetError, 'database_target_mismatch'):
                store.reconnect()
        approved.execute.assert_called_once()
        approved.close.assert_called_once()
        redirected.execute.assert_not_called()
        redirected.close.assert_called_once()

    def test_preflight_explains_the_website_statements_without_executing_them(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = {'replica': False, 'read_only': False}

        self.assertIsNone(collector_write_blocker(db))

        calls = db.execute.call_args_list
        self.assertEqual(calls[1].args, ('SET TRANSACTION READ ONLY',))
        self.assertEqual(
            [call.args for call in calls[2:]],
            [('EXPLAIN (COSTS OFF) ' + query, (None,) * query.count('%s'))
             for _, query in WEBSITE_COLLECTION_PLANS],
        )

    def test_preflight_reports_missing_permissions_for_website_writes(self):
        for stage, statement in (
            ('image_permission_upsert', IMAGE_PERMISSION_UPSERT),
            ('observation_upsert', OBSERVATION_UPSERT),
        ):
            with self.subTest(stage=stage):
                db = MagicMock()
                state = {'replica': False, 'read_only': False}
                db.execute.return_value.fetchone.return_value = state

                def execute(query, *args):
                    if query == 'EXPLAIN (COSTS OFF) ' + statement:
                        raise InsufficientPrivilege('fixture permission denial')
                    return db.execute.return_value

                db.execute.side_effect = execute
                self.assertEqual(collector_write_blocker(db), stage + '_forbidden')
