"""Datalake SDK defaults and local-file limits, using real pandas and fake SDK only."""
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
from query_core import adapters, core, sdk_adapter
from query_core.store import Store, read_json
from test_lake_workflow import FakeLakeConnection, FakeLakeCursor
from test_datalake_sdk import FakeSDK, pd, SECRETS


class RecordingConnection(FakeLakeConnection):
    """Shared E-HUB fixture imported by test_query_timeout_defaults."""
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
                                 'lake_type':'prod'}, SECRETS)
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

    def test_local_byte_limit_has_no_old_ceiling_and_numeric_inputs_remain_validated(self):
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

    def test_local_byte_caps_do_not_add_large_approval_but_row_expansion_still_does(self):
        fake = FakeSDK()
        with fake.installed():
            for options in ({'max_bytes':1}, {'max_bytes':2**53-1}, {'max_bytes':None}):
                proposal = core.plan(self.store, 'datalake', 1, self.values, options)
                self.assertFalse(proposal['requiresLargeApproval'])
                self.assertIsNone(proposal['limits']['timeout'])
                self.assertEqual(proposal['limits']['max_bytes'], options['max_bytes'])
            expanded = core.plan(self.store, 'datalake', 1, self.values, {'max_rows':60000})
            self.assertTrue(expanded['requiresLargeApproval'])
            self.assertEqual(core.run(self.store, 'datalake', expanded['planId'], confirmed=True)['status'],
                             'large_query_approval_required')
        self.assertEqual(fake.imports, [])
        self.assertEqual(fake.constructors, [])
        self.assertEqual(fake.queries, [])

    def test_actual_dummy_jsonl_can_exceed_20mib_without_a_partial_result(self):
        with FakeSDK(pd.DataFrame({'sample_id':['x'*500000]*50})).installed():
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

    def test_45_seconds_completes_without_any_application_timer_or_sdk_timeout_argument(self):
        clock = [1000.0]
        fake = FakeSDK(pd.DataFrame({'sample_id':range(501)}), on_execute=lambda:clock.__setitem__(0,1045.0))
        with patch.object(adapters.threading, 'Timer', side_effect=AssertionError('SDK must not install a timer')) as timer, \
             patch.object(core.time, 'monotonic', side_effect=lambda:clock[0]), \
             fake.installed():
            response = self.execute()
        self.assertTrue(response['complete'])
        self.assertEqual(response['savedRows'], 501)
        self.assertGreaterEqual(response['elapsedMs'], 45000)
        timer.assert_not_called()
        self.assertEqual(fake.constructors, [{**SECRETS, 'type':'prod', 'spark':False}])
        self.assertEqual(len(fake.queries), 1)
        self.assertTrue(fake.queries[0].startswith('SELECT'))
        self.assertNotIn('query_timeout', fake.queries[0])

    def test_inspection_is_unknown_and_offline_then_run_uses_one_sdk_query(self):
        fake = FakeSDK()
        with fake.installed():
            proposal = core.plan(self.store, 'datalake', 1, self.values)
            self.assertIsNone(proposal['exactCount'])
            self.assertIsNone(proposal['estimatedRows'])
            self.assertEqual(fake.imports, [])
            self.assertEqual(fake.constructors, [])
            self.assertEqual(fake.queries, [])
            response = core.run(self.store, 'datalake', proposal['planId'], confirmed=True)
        self.assertTrue(response['complete'])
        self.assertEqual(len(fake.queries), 1)
        self.assertEqual(len(fake.constructors), 1)
        self.assertEqual(fake.closed, 1)
        metadata = read_json(Path(response['dataFile']).with_name('metadata.json'))
        self.assertEqual(metadata['limits'], {'max_rows':50000, 'max_bytes':None, 'timeout':None})

    def test_empty_dataframe_saves_complete_empty_result_with_none_limits(self):
        with FakeSDK(pd.DataFrame({'sample_id':[]})).installed():
            response = self.execute()
        self.assertTrue(response['complete'])
        self.assertEqual(response['savedRows'], 0)
        self.assertEqual(Path(response['dataFile']).read_bytes(), b'')
        metadata = read_json(Path(response['dataFile']).with_name('metadata.json'))
        self.assertIsNone(metadata['limits']['timeout'])
        self.assertIsNone(metadata['limits']['max_bytes'])

    def test_explicit_small_byte_limit_applies_only_to_local_file_after_sdk_dataframe_received(self):
        fake = FakeSDK(pd.DataFrame({'sample_id':['long enough']*2}))
        with fake.installed():
            response = self.execute(options={'max_bytes':1})
        self.assertFalse(response['complete'])
        self.assertEqual(response['reason'], 'byte_limit')
        self.assertEqual(response['savedRows'], 0)
        self.assertEqual(len(fake.queries), 1)
        self.assertTrue(fake.queries[0].endswith('LIMIT 50001'))
        self.assertEqual(len(fake.frame), 2)
        self.assertEqual(Path(response['dataFile']).stat().st_size, 0)
        self.assertEqual(fake.constructors, [{**SECRETS, 'type':'prod', 'spark':False}])

    def test_finite_timeout_is_rejected_before_sdk_execution_without_claiming_server_cancellation(self):
        fake = FakeSDK()
        with fake.installed():
            for seconds in (1, 60, 1801, 3601):
                with self.subTest(seconds=seconds), self.assertRaisesRegex(ValueError, 'SDK|sdk'):
                    self.execute(options={'timeout':seconds})
            backend = sdk_adapter.LakeHouseSDKBackend({'lake_type':'prod'}, SECRETS)
            with self.assertRaises(adapters.AdapterError) as caught:
                with backend.execute('SELECT 1', {}, limit=1, timeout_seconds=1):
                    pass
            self.assertEqual(caught.exception.code, 'sdk_timeout_unsupported')
            backend.close()
        self.assertEqual(fake.imports, [])
        self.assertEqual(fake.constructors, [])
        self.assertEqual(fake.queries, [])
        self.assertEqual(list((self.store.root/'results').rglob('data.jsonl')), [])

    def test_50001_rows_still_stop_at_50000_despite_unbounded_byte_and_time(self):
        with FakeSDK(pd.DataFrame({'sample_id':range(50001)})).installed():
            response = self.execute()
        self.assertEqual(response['savedRows'], 50000)
        self.assertFalse(response['complete'])
        self.assertEqual(response['reason'], 'row_limit')


if __name__ == '__main__':
    unittest.main()
