"""Bound size uncertainty within one execution; never infer function safety."""
from contextlib import contextmanager, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
from query_core import cli, core
from query_core.adapters import AdapterError
from query_core.store import Store


class AutoScopeTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/query-auto-scope'; parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.store = Store(self.folder / 'state')
        self.store.save_profile({'id':'sample', 'engine':'oracle', 'name':'GMS'})
        self.save_sql('SELECT value FROM samples')
        self.count = 6438; self.calls = []; self.count_error = None
        owner = self
        class Backend:
            def inspect(self, *args):
                return {'estimated_rows':None, 'exact_count':None, 'notes':[]}
            def count_bounded(self, sql, binds, *, limit, timeout_seconds):
                owner.calls.append(('count', limit, timeout_seconds))
                if owner.count_error: raise owner.count_error
                count = min(owner.count, limit + 1)
                return {'count':count, 'cap':limit+1, 'complete':count < limit+1, 'elapsedMs':1}
            @contextmanager
            def execute(self, sql, binds, *, limit, timeout_seconds):
                owner.calls.append(('execute', limit, timeout_seconds))
                yield [f'열{i}' for i in range(17)], ([i] + ['가상자료'] * 16 for i in range(min(owner.count, limit+1)))
        @contextmanager
        def opened(*args, **kwargs):
            yield Backend()
        backend = patch('query_core.adapters.open_backend', opened); backend.start(); self.addCleanup(backend.stop)
        secrets = patch.object(Store, 'secrets', return_value={'user':'fixture-only'})
        secrets.start(); self.addCleanup(secrets.stop)

    def save_sql(self, sql):
        return self.store.save_query({'name':'UPH 가상조회','profile':'sample','sql':sql,'parameters':{}},
                                     'oracle', query_id=1 if hasattr(self, 'count') else None)

    def execute(self, **options):
        return core.execute(self.store, 'oracle', 1, {}, options or None, confirmed=True)

    def test_6438_rows_one_cli_call_then_same_request_skips_probe(self):
        outputs = []
        for _ in range(2):
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = cli.main('oracle', ['--state-root',str(self.store.root), 'execute','--id','1',
                                          '--output-dir',str(self.folder / 'outputs')])
            self.assertEqual(code, 0, stream.getvalue())
            result = json.loads(stream.getvalue()); outputs.append(result['outputFile'])
            self.assertTrue(result['complete'])
            self.assertEqual(result['savedRows'], 6438)
            self.assertEqual(result['columnCount'], 17)
            self.assertEqual(result['deliveryVerification'], 'verified')
            self.assertEqual(result['exportedRows'], 6438)
            self.assertEqual(Path(result['outputFile']).stat().st_size, result['outputBytes'])
            self.assertEqual(result['dataRowsReturned'], 0)
            self.assertNotIn('planId', result)
        self.assertNotEqual(*outputs)
        self.assertEqual([call[0] for call in self.calls], ['count','execute','execute'])
        self.assertLess(self.calls[1][2], 60)

    def test_normal_query_does_not_add_count(self):
        self.save_sql('SELECT value FROM samples WHERE value > 0')
        self.assertTrue(self.execute()['complete'])
        self.assertEqual([c[0] for c in self.calls], ['execute'])

    def test_over_limit_is_lower_bound_and_never_executes_main_query(self):
        self.count = 90000
        result = self.execute()
        self.assertFalse(result['executed'])
        self.assertIsNone(result['exactCount'])
        self.assertEqual(result['sizeProbe']['count'], 50001)
        self.assertFalse(result['sizeProbe']['complete'])
        self.assertEqual([c[0] for c in self.calls], ['count'])

    def test_count_timeout_asks_once_without_main_query_or_automatic_retry(self):
        self.count_error = AdapterError('count_timeout','가상 크기 확인 시간 초과')
        result = self.execute()
        self.assertFalse(result['executed'])
        self.assertEqual(result['sizeProbe']['status'], 'timeout')
        self.assertEqual([c[0] for c in self.calls], ['count'])
        self.count_error = None
        core.run(self.store, 'oracle', result['planId'], confirmed=True, allow_large=True)
        self.assertTrue(self.execute()['complete'])
        self.assertEqual([c[0] for c in self.calls], ['count','execute','execute'])

    def test_count_sql_error_is_not_an_empty_result_or_approval(self):
        self.count_error = AdapterError('db_query','ORA-00904: 가상 잘못된 열')
        with self.assertRaisesRegex(AdapterError, 'ORA-00904'):
            self.execute()
        self.assertEqual([c[0] for c in self.calls], ['count'])

    def test_behavior_join_and_enlarged_limits_do_not_get_counted(self):
        for sql in ('SELECT business_fn(1) FROM dual',
                    'SELECT a.id FROM a CROSS JOIN b'):
            with self.subTest(sql=sql):
                self.save_sql(sql)
                self.assertFalse(self.execute()['executed'])
                self.assertEqual(self.calls, [])
        self.save_sql('SELECT value FROM samples')
        self.assertFalse(self.execute(max_rows=60000)['executed'])
        self.assertEqual(self.calls, [])

    def test_registration_ten_row_sample_is_not_counted_or_whole_result_evidence(self):
        result = self.execute(max_rows=10)
        self.assertFalse(result['executed'])
        self.assertEqual(self.calls, [])
        sample = core.run(self.store, 'oracle', result['planId'], confirmed=True, allow_large=True)
        self.assertFalse(sample['complete'])
        self.assertTrue(self.execute()['complete'])
        self.assertEqual([c[0] for c in self.calls], ['execute','count','execute'])


if __name__ == '__main__':
    unittest.main()
