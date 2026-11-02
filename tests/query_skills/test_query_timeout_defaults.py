"""60-second Oracle/E-HUB execution contracts, using a clock and fake drivers."""
import importlib
from pathlib import Path
import socket
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
sys.path.insert(0, str(Path(__file__).parent))
from query_core import adapters, core
from query_core.store import Store
from test_adapters import Connection, Cursor
from test_datalake_unbounded import RecordingConnection
from test_lake_workflow import FakeLakeTransport


class TimedOracleConnection(Connection):
    def __init__(self, clock, elapsed):
        super().__init__(rows=((1,), (2,), (3,)))
        self.clock, self.elapsed = clock, elapsed

    def cursor(self):
        cursor = TimedOracleCursor(self.rows, self.clock, self.elapsed)
        self.cursors.append(cursor)
        return cursor


class TimedOracleCursor(Cursor):
    def __init__(self, rows, clock, elapsed):
        super().__init__(rows)
        self.clock, self.elapsed, self.advanced = clock, elapsed, False

    def fetchmany(self, count):
        if not self.advanced:
            self.advanced = True
            self.clock[0] += self.elapsed
        return super().fetchmany(count)


class QueryTimeoutDefaultTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/query-timeout-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'personal')
        self.ids = {}
        for engine in ('oracle', 'ehub'):
            profile = {'id':engine, 'name':'가상 ' + engine, 'engine':engine}
            secrets = {'user':'SYNTHETIC', 'password':'DUMMY', 'dsn':'fixture.invalid'}
            if engine == 'ehub':
                profile.update(api_base='https://fixture.invalid/api/v4', cluster='fixture-cluster', allow_cluster_start=True)
                secrets = {'user_id':'SYNTHETIC', 'token':'DUMMY'}
            self.store.save_profile(profile, secrets)
            query = self.store.save_query({'name':'필터 조회', 'profile':engine,
                'sql':'SELECT sample_id FROM samples WHERE sample_id >= :minimum ORDER BY sample_id',
                'parameters':{'minimum':{'type':'integer'}}}, engine)
            self.ids[engine] = query['id']
        self.values = {'minimum':1}

    def ehub(self, elapsed):
        clock = [1000.0]
        timer_seconds = []
        original_timer = threading.Timer
        def timer(seconds, callback, *args, **kwargs):
            timer_seconds.append(seconds)
            return original_timer(seconds, callback, *args, **kwargs)
        with patch('test_lake_workflow.FakeLakeConnection', RecordingConnection), \
             patch.object(core.time, 'monotonic', side_effect=lambda:clock[0]), \
             patch.object(adapters.threading, 'Timer', side_effect=timer), \
             FakeLakeTransport(row_count=501) as transport:
            transport.on_main_fetch = lambda:clock.__setitem__(0, 1000.0+elapsed)
            if elapsed < 60:
                response = core.execute(self.store, 'ehub', self.ids['ehub'], self.values, confirmed=True)
                self.assertTrue(response['complete'])
                self.assertEqual(response['savedRows'], 501)
                self.assertGreaterEqual(response['elapsedMs'], elapsed*1000)
            else:
                with self.assertRaises(adapters.AdapterError) as caught:
                    core.execute(self.store, 'ehub', self.ids['ehub'], self.values, confirmed=True)
                self.assertEqual(caught.exception.code, 'query_timeout')
        self.assertEqual(timer_seconds, [5, 60])
        self.assertEqual(transport.connect_calls[0]['read_timeout'], 60)
        self.assertEqual(transport.connect_calls[0]['write_timeout'], 60)
        self.assertEqual(transport.connections[0].main_query_contexts, [(60, 60, 60)])
        self.assertIn(('SET query_timeout = 60', None), transport.sql_calls)
        self.assertEqual(len(transport.connect_calls), 1)
        self.assertEqual(len(transport.selects()), 1)
        self.assertTrue(transport.connections[0].closed)

    def test_ehub_45_seconds_completes_with_server_client_and_timer_at_60(self):
        self.ehub(45)

    def test_ehub_61_seconds_stops_without_retrying_or_leaving_partial_data(self):
        self.ehub(61)
        self.assertEqual(list((self.store.root / 'results').rglob('data.jsonl')), [])

    def test_oracle_call_timeout_60000_allows_45_seconds_and_stops_at_61(self):
        real_import = importlib.import_module
        original_timer = threading.Timer
        for elapsed in (45, 61):
            with self.subTest(elapsed=elapsed):
                clock, timers, connects = [1000.0], [], []
                connection = TimedOracleConnection(clock, elapsed)
                def timer(seconds, callback, *args, **kwargs):
                    timers.append(seconds)
                    return original_timer(seconds, callback, *args, **kwargs)
                def connect(**kwargs):
                    connects.append(kwargs)
                    return connection
                driver = types.SimpleNamespace(is_thin_mode=lambda:True, connect=connect)
                def imported(name, *args, **kwargs):
                    return driver if name == 'oracledb' else real_import(name, *args, **kwargs)
                before = set((self.store.root / 'results').rglob('data.jsonl'))
                with patch.object(adapters.importlib, 'import_module', side_effect=imported), \
                     patch.object(core.time, 'monotonic', side_effect=lambda:clock[0]), \
                     patch.object(adapters.threading, 'Timer', side_effect=timer), \
                     patch.object(socket, 'socket', side_effect=AssertionError('live Oracle forbidden')):
                    if elapsed == 45:
                        response = core.execute(self.store, 'oracle', self.ids['oracle'], self.values, confirmed=True)
                        self.assertTrue(response['complete'])
                        self.assertEqual(response['savedRows'], 3)
                        self.assertEqual(response['elapsedMs'], 45000)
                    else:
                        with self.assertRaises(adapters.AdapterError) as caught:
                            core.execute(self.store, 'oracle', self.ids['oracle'], self.values, confirmed=True)
                        self.assertEqual(caught.exception.code, 'query_timeout')
                        self.assertEqual(before, set((self.store.root / 'results').rglob('data.jsonl')))
                self.assertEqual(connection.call_timeout, 60000)
                self.assertEqual(timers, [60])
                self.assertEqual(len(connects), 1)
                self.assertTrue(connection.closed)
                self.assertGreaterEqual(connection.rollbacks, 1)
                self.assertEqual(sum(sql.startswith('SELECT') for cursor in connection.cursors for sql, _ in cursor.calls), 1)

    def test_45_second_option_is_within_default_and_61_second_option_needs_approval(self):
        for engine in ('oracle', 'ehub'):
            with self.subTest(engine=engine), FakeLakeTransport():
                normal = core.plan(self.store, engine, self.ids[engine], self.values, {'timeout':45})
                expanded = core.plan(self.store, engine, self.ids[engine], self.values, {'timeout':61})
                self.assertFalse(normal['requiresLargeApproval'])
                self.assertTrue(expanded['requiresLargeApproval'])


if __name__ == '__main__':
    unittest.main()
