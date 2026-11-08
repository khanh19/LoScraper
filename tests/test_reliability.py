import unittest
from unittest.mock import Mock, patch

from trending.adapters import collect_source
from trending.progress import Progress
from test_trending import NOW


class CollectionFailures(unittest.TestCase):
    def test_parser_exception_does_not_stop_remaining_pages_and_heartbeats(self):
        adapter=Mock()
        adapter.links.return_value=['https://example.org/bad','https://example.org/good']
        adapter.parse.side_effect=[RuntimeError('private detail'),object()]
        adapter.enrich.side_effect=lambda c,*args:c
        beat=Mock()
        with patch.dict('trending.adapters.CLASSES',{'test':Mock(return_value=adapter)}):
            candidates, failures=collect_source('test',{'seeds':['https://example.org']},Mock(),NOW,heartbeat=beat)
        self.assertEqual(len(candidates),1)
        self.assertEqual(failures,[{'stage':'detail','reason':'RuntimeError'}])
        self.assertEqual(beat.call_count,6)

    def test_reconnect_failure_stops_persistence_but_not_local_progress(self):
        import psycopg
        store=Mock();store.db.closed=True
        store.upsert.side_effect=psycopg.OperationalError('secret')
        store.reconnect.side_effect=psycopg.OperationalError('secret')
        p=Progress(store,['ticketbox'],['hanoi']);p.start_source('ticketbox')
        self.assertFalse(p.call('upsert',object(),NOW)[0])
        self.assertFalse(p.call('upsert',object(),NOW)[0])
        p.count('failed','hanoi',['candidate_write_failed'])
        p.finish_source();p.heartbeat(final=True)
        self.assertEqual(store.reconnect.call_count,1)
        self.assertEqual(store.upsert.call_count,1)
        self.assertEqual(p.status(),'failed')
        self.assertNotIn('secret',str(p.errors))

    def test_rejections_alone_are_complete(self):
        p=Progress(None,['ticketbox'],['hanoi']);p.start_source('ticketbox')
        p.count('rejected','hanoi',['no_upcoming_occurrence']);p.finish_source()
        self.assertEqual(p.status(),'complete')

    def test_initial_connection_has_one_bounded_retry(self):
        import psycopg
        from trending.store import Store
        with patch('trending.store.psycopg.connect',side_effect=[psycopg.OperationalError('secret'),Mock()]) as connect:
            store=Store('not-logged')
        self.assertEqual(connect.call_count,2)
        p=Progress(store,['ticketbox'],['hanoi'])
        self.assertTrue(p.reconnect_attempted)

    def test_ambiguous_initial_receipt_is_not_retried(self):
        import psycopg
        store=Mock();store.db.closed=True
        store.start_run.side_effect=psycopg.OperationalError('secret')
        p=Progress(store,['ticketbox'],['hanoi'])
        self.assertEqual(store.start_run.call_count,1)
        self.assertEqual(store.reconnect.call_count,1)
        self.assertFalse(p.available)
        self.assertFalse(p.call('upsert',object(),NOW)[0])
        self.assertEqual(p.status(),'failed')

    def test_cli_exit_codes(self):
        from trending.__main__ import main
        import sys
        for status,code in [('complete',0),('partial',2),('failed',1)]:
            with self.subTest(status=status),patch.object(sys,'argv',['trending']),\
                 patch('trending.__main__.run',return_value={'status':status}),\
                 self.assertRaises(SystemExit) as raised:
                main()
            self.assertEqual(raised.exception.code,code)
