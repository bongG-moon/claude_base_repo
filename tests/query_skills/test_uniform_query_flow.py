"""Uniform engine UX with synthetic transports; no operating DB/network/model."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
sys.path.insert(0, str(Path(__file__).parent))
from query_core import adapters, cli, core
from query_core.store import Store
from test_datalake_sdk import FakeSDK, pd, SECRETS
from test_lake_workflow import FakeLakeTransport, FakeLakeCursor


class UniformQueryFlowTests(unittest.TestCase):
    def setUp(self):
        folder = ROOT / '.smoke/uniform-query-tests'
        folder.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store(self.root / 'state')
        self.store.save_profile({'id': 'lake', 'name': '인증', 'engine': 'datalake'}, dict(SECRETS))
        self.store.save_profile({'id': 'hub', 'name': 'E-HUB', 'engine': 'ehub',
            'api_base': 'https://fixture.invalid/api/v4', 'cluster': 'fixture-cluster', 'allow_cluster_start': True},
            {'user_id': 'fixture', 'token': 'PRIVATE-token'})
        self.ids = {}
        for engine, profile in [('datalake', 'lake'), ('ehub', 'hub')]:
            self.ids[engine] = self.store.save_query({'name': '전체 조회', 'profile': profile,
                'sql': 'SELECT sample_id FROM samples', 'parameters': {}}, engine)['id']

    def query(self, engine):
        return core.execute(self.store, engine, self.ids[engine], {}, confirmed=True)

    def test_ehub_counts_only_first_uncertain_scope_and_reuses_connection(self):
        with FakeLakeTransport(row_count=6438) as fake:
            first = self.query('ehub')
            second = self.query('ehub')
        self.assertEqual((first['savedRows'], second['savedRows']), (6438, 6438))
        self.assertNotEqual(first['resultId'], second['resultId'])
        self.assertEqual(len(fake.counts()), 1)
        self.assertEqual(len(fake.selects()), 2)
        self.assertEqual(len(fake.connect_calls), 2)
        self.assertIn('LIMIT 50001', fake.counts()[0][0])
        self.assertIn(('SET query_timeout = 2', None), fake.sql_calls)

    def test_ehub_saturated_count_waits_and_does_not_read_main_result(self):
        with FakeLakeTransport(row_count=90000) as fake:
            result = self.query('ehub')
        self.assertFalse(result['executed'])
        self.assertTrue(result['requiresLargeApproval'])
        self.assertEqual(result['sizeProbe']['count'], 50001)
        self.assertIsNone(result['exactCount'])
        self.assertEqual(len(fake.selects()), 0)

    def test_ehub_timeout_is_not_zero_and_query_error_is_not_empty(self):
        original = FakeLakeCursor.execute
        for code in ('timeout', 'query'):
            def execute(cursor, statement, params=None):
                if statement.startswith('SELECT COUNT'):
                    if code == 'timeout':
                        raise adapters.AdapterError('count_timeout', '가상 시간 초과')
                    raise adapters.AdapterError('db_query', '가상 SQL 오류')
                return original(cursor, statement, params)
            with self.subTest(code=code), FakeLakeTransport() as fake, patch.object(FakeLakeCursor, 'execute', execute):
                if code == 'timeout':
                    result = self.query('ehub')
                    self.assertFalse(result['executed'])
                    self.assertEqual(result['sizeProbe']['status'], 'timeout')
                    self.assertIsNone(result['exactCount'])
                else:
                    with self.assertRaisesRegex(adapters.AdapterError, '가상 SQL 오류'):
                        self.query('ehub')
                self.assertEqual(len(fake.selects()), 0)

    def test_ehub_timer_closes_connection_and_never_calls_main_query(self):
        with FakeLakeTransport() as fake, adapters.open_backend(self.store.profile('hub'), self.store.secrets('hub')) as backend:
            with patch.object(FakeLakeCursor, 'fetchone', side_effect=lambda: (time.sleep(.03), (2,))[1]):
                with self.assertRaises(adapters.AdapterError) as caught:
                    backend.count_bounded('SELECT sample_id FROM samples', {}, limit=50000, timeout_seconds=.01)
            self.assertEqual(caught.exception.code, 'count_timeout')
            self.assertTrue(fake.connections[0].closed)
            self.assertEqual(len(fake.selects()), 0)

    def test_ehub_count_preserves_binds_and_checks_zero_and_invalid_counts(self):
        for value in (0, -1, True, 50002):
            with self.subTest(value=value), FakeLakeTransport() as fake, adapters.open_backend(self.store.profile('hub'), self.store.secrets('hub')) as backend:
                with patch.object(FakeLakeCursor, 'fetchone', return_value=(value,)):
                    if value == 0 and type(value) is int:
                        result = backend.count_bounded('SELECT sample_id FROM samples WHERE id=:id', {'id':'PRIVATE-value'}, limit=50000, timeout_seconds=2)
                        self.assertTrue(result['complete'])
                        self.assertEqual(result['count'], 0)
                        statement, binds = fake.counts()[0]
                        self.assertNotIn('PRIVATE-value', statement)
                        self.assertIn('PRIVATE-value', binds.values())
                    else:
                        with self.assertRaises(adapters.AdapterError):
                            backend.count_bounded('SELECT sample_id FROM samples', {}, limit=50000, timeout_seconds=2)

    def test_sdk_reuses_scope_proof_without_extra_count_or_limits(self):
        with FakeSDK(pd.DataFrame({'sample_id': [1, 2]})).installed() as fake:
            pending = self.query('datalake')
            self.assertFalse(pending['executed'])
            self.assertEqual(fake.queries, [])
            first = core.run(self.store, 'datalake', pending['planId'], confirmed=True, allow_large=True)
            second = self.query('datalake')
        self.assertTrue(first['complete'] and second['complete'])
        self.assertNotEqual(first['resultId'], second['resultId'])
        self.assertEqual(len(fake.queries), 2)
        self.assertFalse(any('COUNT(' in statement.upper() for statement in fake.queries))
        self.assertIsNone(pending['limits']['max_bytes'])
        self.assertIsNone(pending['limits']['timeout'])

    def test_behavior_risks_need_first_approval_but_not_same_scope_reapproval(self):
        for engine in ('datalake', 'ehub'):
            with self.subTest(engine=engine):
                query = self.store.query(self.ids[engine], engine)
                self.store.save_query({'name': '함수 조회', 'profile': query['profile'],
                    'sql': 'SELECT business_fn(sample_id) FROM samples', 'parameters': {}}, engine, query_id=query['id'])
                transport = FakeSDK(pd.DataFrame({'value': [1, 2]})).installed() if engine == 'datalake' else FakeLakeTransport()
                with transport as fake:
                    pending = self.query(engine)
                    self.assertFalse(pending['executed'])
                    core.run(self.store, engine, pending['planId'], confirmed=True, allow_large=True)
                    repeated = self.query(engine)
                    self.assertTrue(repeated['complete'])
                    if engine == 'datalake':
                        self.assertEqual(len(fake.queries), 2)
                    else:
                        self.assertEqual(len(fake.selects()), 2)
                        self.assertEqual(fake.counts(), [])

    def test_cli_defaults_and_explicit_paths_do_not_move_personal_state(self):
        for engine, folder in cli.SKILL_FOLDERS.items():
            with self.subTest(engine=engine), patch.object(Path, 'cwd', return_value=self.root):
                self.assertEqual(cli.output_directory(engine), self.root / folder / 'outputs')
                explicit = self.root / 'chosen'
                self.assertEqual(cli.output_directory(engine, explicit), explicit)
        query = self.store.query(self.ids['datalake'], 'datalake')
        query['sql'] += ' WHERE sample_id>0'
        self.store.save_query({key: query[key] for key in ('name','profile','sql','parameters')}, 'datalake', query_id=query['id'])
        with FakeSDK(pd.DataFrame({'sample_id': [1, 2]})).installed() as fake, patch.object(Path, 'cwd', return_value=self.root):
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = cli.main('datalake', ['--state-root', str(self.store.root), 'execute', '--id', str(query['id'])])
        self.assertEqual(code, 0)
        result = json.loads(stream.getvalue())
        self.assertEqual(Path(result['outputFile']).parent, self.root / 'datalake-query' / 'outputs')
        self.assertEqual(result['deliveryVerification'], 'verified')
        self.assertEqual(len(fake.queries), 1)
        self.assertTrue(Path(result['dataFile']).is_relative_to(self.store.root))
        self.assertFalse((self.root / '.work').exists())
        self.assertEqual(list((self.root / 'datalake-query').iterdir()), [self.root / 'datalake-query' / 'outputs'])

    def test_exact_small_count_does_not_prompt_in_demo_or_real_engine(self):
        for engine in ('datalake','ehub'):
            with self.subTest(engine=engine), patch('query_core.core._using_backend') as opened:
                backend = opened.return_value.__enter__.return_value
                backend.inspect.return_value = {'exact_count': 2, 'estimated_rows': None}
                result = core.plan(self.store, engine, self.ids[engine], {})
                self.assertFalse(result['requiresLargeApproval'])
                backend.count_bounded.assert_not_called()
        demo = Store(self.root / 'demo', demo=True)
        core.demo_init(demo)
        saved = demo.save_query({'name':'작은 전체 조회', 'profile':'production',
            'sql':'SELECT * FROM production_records', 'parameters':{}}, 'demo')
        response = core.execute(demo, 'demo', saved['id'], {}, confirmed=True)
        self.assertTrue(response['complete'])
        self.assertEqual(response['savedRows'], 6)


if __name__ == '__main__':
    unittest.main()
