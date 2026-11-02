"""Datalake removes default byte/time caps while preserving row and consent gates."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
sys.path.insert(0, str(Path(__file__).parent))
from query_core import adapters, core
from query_core.store import Store, read_json
from test_lake_workflow import FakeLakeTransport, FakeLakeConnection, FakeLakeCursor


class RecordingConnection(FakeLakeConnection):
    """Starts with a pre-existing server timeout that belongs to the server."""
    def __init__(self, transport):
        super().__init__(transport)
        self.server_timeout = 777
        self.read_timeout = None
        self.write_timeout = None
        self.main_query_contexts = []

    def cursor(self):
        cursor = RecordingCursor(self.transport, self)
        self.cursors.append(cursor)
        return cursor


class RecordingCursor(FakeLakeCursor):
    def __init__(self, transport, connection):
        super().__init__(transport)
        self.connection = connection
        self.main_query = False

    def execute(self, sql, params=None):
        if sql.startswith('SET query_timeout = '):
            self.connection.server_timeout = int(sql.rsplit(' ', 1)[-1])
        self.main_query = sql.startswith('SELECT')
        if self.main_query:
            self.connection.main_query_contexts.append((self.connection.server_timeout,
                                                       self.connection.read_timeout,
                                                       self.connection.write_timeout))
        super().execute(sql, params)

    def fetchmany(self, count):
        callback = getattr(self.transport, 'on_main_fetch', None)
        if self.main_query and callback is not None:
            self.transport.on_main_fetch = None
            callback()
        return super().fetchmany(count)


class DatalakeUnboundedTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/datalake-unbounded-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'personal')
        self.store.save_profile({'id':'lake', 'name':'가상 Datalake', 'engine':'datalake',
                                 'api_base':'https://fixture.invalid/api/v4', 'cluster':'fixture-cluster',
                                 'allow_cluster_start':True}, {'user_id':'SYNTHETIC', 'token':'DUMMY_TOKEN'})
        self.store.save_query({'name':'필터 조회', 'profile':'lake',
            'sql':'SELECT sample_id FROM samples WHERE sample_id >= :minimum ORDER BY sample_id',
            'parameters':{'minimum':{'type':'integer'}}}, 'datalake')
        self.values = {'minimum':1}

    def execute(self, **kwargs):
        return core.execute(self.store, 'datalake', 1, self.values, confirmed=True, **kwargs)

    def test_default_none_is_datalake_only_and_existing_row_ceilings_remain(self):
        self.assertEqual(core.default_limits('datalake'), {'max_rows':50000, 'max_bytes':None, 'timeout':None})
        for engine in ('oracle', 'ehub'):
            self.assertEqual(core.default_limits(engine), {'max_rows':50000, 'max_bytes':20*1024*1024, 'timeout':60})
        self.assertEqual(core.default_limits('demo'), {'max_rows':10000, 'max_bytes':20*1024*1024, 'timeout':30})
        with self.assertRaises(ValueError): core.limits({'max_rows':1000001}, 'datalake')

    def test_explicit_finite_limits_remove_previous_ceilings_and_reject_unsupported_waits(self):
        largest = 2**53 - 1
        supported_wait = int(threading.TIMEOUT_MAX) - 1
        for options in ({'max_bytes':512*1024*1024+1, 'timeout':1801},
                        {'max_bytes':largest, 'timeout':3601},
                        {'max_bytes':largest, 'timeout':supported_wait},
                        {'max_bytes':1, 'timeout':1},
                        {'max_bytes':None, 'timeout':None}):
            self.assertEqual(core.limits(options, 'datalake'), {'max_rows':50000, **options})
        for field in ('max_bytes', 'timeout'):
            for invalid in (0, -1, True, 1.5, '30', 2**53):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    core.limits({field:invalid}, 'datalake')
            for other in ('oracle', 'ehub', 'demo'):
                with self.assertRaises(ValueError): core.limits({field:None}, other)
                with self.assertRaises(ValueError): core.limits({field:largest}, other)
        for unsupported_wait in (int(threading.TIMEOUT_MAX), largest):
            with self.assertRaises(ValueError): core.limits({'timeout':unsupported_wait}, 'datalake')

    def test_finite_caps_do_not_add_large_approval_but_row_expansion_still_does(self):
        with FakeLakeTransport():
            for options in ({'max_bytes':1,'timeout':1}, {'max_bytes':2**53-1,'timeout':1801},
                            {'max_bytes':2**53-1,'timeout':3601}):
                proposal = core.plan(self.store, 'datalake', 1, self.values, options)
                self.assertFalse(proposal['requiresLargeApproval'])
                self.assertEqual(proposal['limits']['timeout'], options['timeout'])
            expanded = core.plan(self.store, 'datalake', 1, self.values, {'max_rows':60000})
            self.assertTrue(expanded['requiresLargeApproval'])
            self.assertEqual(core.run(self.store, 'datalake', expanded['planId'], confirmed=True)['status'],
                             'large_query_approval_required')

    def test_actual_dummy_jsonl_can_exceed_20mib_without_a_partial_result(self):
        with FakeLakeTransport(row_count=50, value='x'*500000):
            response = self.execute()
        self.assertTrue(response['complete'])
        self.assertEqual(response['savedRows'], 50)
        data = Path(response['dataFile'])
        self.assertGreater(data.stat().st_size, 20*1024*1024)
        self.assertEqual(data.stat().st_size, response['dataBytes'])
        metadata = read_json(data.with_name('metadata.json'))
        self.assertIsNone(metadata['limits']['max_bytes'])
        self.assertIsNone(metadata['limits']['timeout'])
        self.assertLess(len(json.dumps(response)), 1800)

    def test_crossing_30_seconds_does_not_stop_unbounded_rows_or_create_query_timer(self):
        clock = [1000.0]
        original_timer = threading.Timer
        timer_seconds = []
        def timer(seconds, callback, *args, **kwargs):
            timer_seconds.append(seconds)
            return original_timer(seconds, callback, *args, **kwargs)
        with patch('test_lake_workflow.FakeLakeConnection', RecordingConnection), \
             patch.object(adapters.threading, 'Timer', side_effect=timer), \
             patch.object(core.time, 'monotonic', side_effect=lambda:clock[0]), \
             FakeLakeTransport(row_count=501) as transport:
            transport.on_main_fetch = lambda: clock.__setitem__(0, 1045.0)
            response = self.execute()
        self.assertTrue(response['complete'])
        self.assertEqual(response['savedRows'], 501)
        self.assertGreaterEqual(response['elapsedMs'], 45000)
        self.assertEqual(timer_seconds, [5], 'Only the short inspection may install a client timer')
        self.assertEqual(transport.connections[0].main_query_contexts, [(777, None, None)])
        self.assertNotIn(('SET query_timeout = 5', None), transport.sql_calls)
        self.assertNotIn(('SET query_timeout = 60', None), transport.sql_calls)

    def test_inspection_does_not_read_or_mutate_server_timeout_and_connection_preparation_stays_bounded(self):
        with patch('test_lake_workflow.FakeLakeConnection', RecordingConnection), FakeLakeTransport() as transport:
            response = self.execute()
        self.assertTrue(response['complete'])
        self.assertEqual(transport.connections[0].server_timeout, 777)
        self.assertEqual(transport.connections[0].main_query_contexts, [(777, None, None)])
        self.assertFalse(any('query_timeout' in sql.lower() for sql, _ in transport.sql_calls))
        self.assertEqual(len(transport.explains()), 1)
        self.assertEqual(len(transport.selects()), 1)
        self.assertEqual(transport.connect_calls[0]['connection_timeout'], 10)
        self.assertIsNone(transport.connect_calls[0].get('read_timeout'))
        self.assertIsNone(transport.connect_calls[0].get('write_timeout'))
        request_timeouts = transport.http_calls[0][1]['timeout']
        self.assertTrue(all(isinstance(value,(int,float)) and 0 < value <= 15 for value in request_timeouts))

    def test_unbounded_deadline_never_creates_a_background_timer(self):
        with patch.object(adapters.threading, 'Timer') as timer:
            with adapters._deadline(None, lambda:None) as (end, expired):
                self.assertIsNone(end)
                self.assertFalse(expired.is_set())
            timer.assert_not_called()

    def test_explicit_small_byte_limit_still_applies_without_extra_approval(self):
        with FakeLakeTransport(row_count=2, value='long enough') as transport:
            response = self.execute(options={'max_bytes':1})
        self.assertFalse(response['complete'])
        self.assertEqual(response['reason'], 'byte_limit')
        self.assertEqual(response['savedRows'], 0)
        self.assertEqual(len(transport.selects()), 1)

    def test_explicit_time_limit_still_stops_fetch_without_retrying_the_query(self):
        clock = [1000.0]
        with patch('test_lake_workflow.FakeLakeConnection', RecordingConnection), \
             patch.object(core.time, 'monotonic', side_effect=lambda:clock[0]), \
             FakeLakeTransport(row_count=501) as transport:
            transport.on_main_fetch = lambda: clock.__setitem__(0, 1002.0)
            with self.assertRaises(adapters.AdapterError) as caught:
                self.execute(options={'timeout':1})
            self.assertEqual(caught.exception.code, 'query_timeout')
        self.assertEqual(len(transport.selects()), 1)
        self.assertEqual(len(transport.connect_calls), 1)
        self.assertEqual(transport.connections[0].main_query_contexts, [(777, 1, 1)])
        self.assertFalse(any(sql.startswith('SET query_timeout') for sql, _ in transport.sql_calls))
        self.assertTrue(transport.connections[0].closed)

    def test_50001_rows_still_stop_at_50000_despite_unbounded_byte_and_time(self):
        with FakeLakeTransport(row_count=50001):
            response = self.execute()
        self.assertEqual(response['savedRows'], 50000)
        self.assertFalse(response['complete'])
        self.assertEqual(response['reason'], 'row_limit')


if __name__ == '__main__':
    unittest.main()
