"""Local-only query latency contracts: no source rows or real DB connections."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
from query_core import cli, core, results, sql
from query_core.adapters import AdapterError
from query_core.store import Store, atomic_json, read_json


class QueryLatencyTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / '.smoke/query-latency-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'oracle')
        self.store.save_profile({'id':'fixture', 'name':'가상 DB', 'engine':'oracle'})
        self.secret = patch.object(self.store, 'secrets', return_value={'user':'fixture-user'})
        self.secret.start(); self.addCleanup(self.secret.stop)
        self.store.save_query({'name':'작은 전체 조회', 'profile':'fixture',
                              'sql':'SELECT sample_id FROM samples', 'parameters':{}}, 'oracle')
        self.rows = [(1,), (2,)]
        self.observation = {'estimated_rows':None, 'exact_count':None, 'notes':[]}
        self.query_error = False
        self.opens = self.selects = 0
        owner = self
        class Backend:
            def inspect(self, *args):
                return owner.observation
            @contextmanager
            def execute(self, *args, **kwargs):
                owner.selects += 1
                if owner.query_error:
                    raise AdapterError('db_query', '가상 조회 오류')
                yield ['VALUE'], iter(owner.rows)
        @contextmanager
        def opened(*args, **kwargs):
            self.opens += 1
            yield Backend()
        self.backend = patch('query_core.adapters.open_backend', opened)
        self.backend.start(); self.addCleanup(self.backend.stop)

    def execute(self, values=None, options=None):
        return core.execute(self.store, 'oracle', 1, values or {}, options, confirmed=True)

    def verified_small(self):
        proposal = self.execute()
        self.assertFalse(proposal['executed'])
        return core.run(self.store, 'oracle', proposal['planId'], confirmed=True, allow_large=True)

    def test_small_result_reuses_only_approval_evidence_and_queries_again(self):
        first = self.verified_small()
        self.rows = [(3,), (4,), (5,)]
        second = self.execute()
        self.assertEqual(self.selects, 2)
        self.assertNotEqual(first['resultId'], second['resultId'])
        self.assertEqual(second['savedRows'], 3)
        self.assertEqual(list(core.load_result_rows(second['dataFile'])), [[3], [4], [5]])

    def test_evidence_survives_new_work_and_stores_no_params_or_credentials(self):
        self.verified_small()
        reopened = Store(self.store.root)
        with patch.object(reopened, 'secrets', return_value={'user':'fixture-user'}):
            result = core.execute(reopened, 'oracle', 1, {}, confirmed=True)
        self.assertTrue(result['complete'])
        with self.store.connect() as conn:
            rows = conn.execute('SELECT * FROM query_size_evidence').fetchall()
        self.assertEqual(len(rows), 1)
        text = repr([tuple(row) for row in rows])
        self.assertNotIn('fixture-user', text)
        self.assertNotIn('SELECT', text)
        self.assertNotIn('params', text)

    def test_empty_complete_result_is_valid_evidence(self):
        self.rows = []
        self.verified_small()
        result = self.execute()
        self.assertTrue(result['complete'])
        self.assertEqual(result['savedRows'], 0)

    def test_ordinary_query_does_not_create_approval_evidence(self):
        self.store.save_query({'name':'조건 조회', 'profile':'fixture',
                              'sql':'SELECT sample_id FROM samples WHERE sample_id=1',
                              'parameters':{}}, 'oracle', query_id=1)
        self.assertTrue(self.execute()['complete'])
        self.assertTrue(self.execute()['complete'])
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM query_size_evidence').fetchone()[0], 0)

    def test_seven_day_expiry_does_not_reuse_previous_approval(self):
        self.verified_small()
        with self.store.connect() as conn:
            conn.execute('UPDATE query_size_evidence SET checked=?', (time.time()-core.SIZE_EVIDENCE_SECONDS-1,))
        self.assertFalse(self.execute()['executed'])

    def test_changed_definition_credentials_and_increased_limits_wait(self):
        self.verified_small()
        self.assertFalse(self.execute(options={'max_rows':60000})['executed'])
        with patch.object(self.store, 'secrets', return_value={'user':'another-fixture'}):
            self.assertFalse(self.execute()['executed'])
        query = self.store.query(1, 'oracle')
        spec = {key:query[key] for key in ('name', 'profile', 'sql', 'parameters')}
        self.store.save_query(dict(spec, sql='SELECT sample_id + 1 FROM samples'), 'oracle', query_id=1)
        self.assertFalse(self.execute()['executed'])

    def test_changed_date_conditions_need_their_own_evidence(self):
        self.store.save_query({'name':'기간 조회', 'profile':'fixture',
            'sql':'SELECT sample_id FROM samples WHERE day >= :first AND day < :last',
            'parameters':{'first':'date', 'last':'date'}}, 'oracle', query_id=1)
        values = {'first':'2026-01-01', 'last':'2026-03-01'}
        proposal = self.execute(values)
        core.run(self.store, 'oracle', proposal['planId'], confirmed=True, allow_large=True)
        self.assertTrue(self.execute(values)['complete'])
        self.assertFalse(self.execute(dict(values, last='2026-04-01'))['executed'])

    def test_new_large_estimate_invalidates_earlier_small_receipt(self):
        self.verified_small()
        self.observation = dict(self.observation, estimated_rows=100000)
        self.assertFalse(self.execute()['executed'])
        self.observation = dict(self.observation, estimated_rows=None)
        self.assertFalse(self.execute()['executed'])

    def test_partial_or_error_invalidates_earlier_evidence(self):
        for variant in ('partial', 'error'):
            with self.subTest(variant=variant):
                self.rows = [(1,), (2,)]; self.query_error = False
                self.verified_small()
                if variant == 'partial':
                    self.rows = [(n,) for n in range(50001)]
                    result = self.execute()
                    self.assertEqual(result['reason'], 'row_limit')
                    self.assertEqual(result['savedRows'], 50000)
                else:
                    self.query_error = True
                    with self.assertRaises(AdapterError): self.execute()
                self.rows = [(1,)]; self.query_error = False
                self.assertFalse(self.execute()['executed'])

    def test_small_function_result_reuses_explicit_approval_only_for_same_scope(self):
        self.store.save_query({'name':'함수 조회', 'profile':'fixture',
                              'sql':'SELECT business_fn(1) FROM dual', 'parameters':{}}, 'oracle', query_id=1)
        self.verified_small()
        self.assertTrue(self.execute()['complete'])
        self.assertTrue(self.execute()['complete'])
        with patch.object(self.store, 'secrets', return_value={'user':'another-fixture'}):
            self.assertFalse(self.execute()['executed'])

    def test_small_function_result_without_explicit_behavior_evidence_waits(self):
        self.store.save_query({'name':'함수 조회', 'profile':'fixture',
                              'sql':'SELECT business_fn(1) FROM dual', 'parameters':{}}, 'oracle', query_id=1)
        self.verified_small()
        with self.store.connect() as conn:
            row = conn.execute('SELECT id,body FROM query_size_evidence').fetchone()
            body = json.loads(row['body']); body.pop('behaviorApproved')
            conn.execute('UPDATE query_size_evidence SET body=? WHERE id=?', (json.dumps(body), row['id']))
        self.assertFalse(self.execute()['executed'])

    def test_preparation_connection_and_inspection_errors_invalidate_evidence(self):
        for entry in ('execute_open', 'execute_inspect', 'plan_open', 'plan_inspect'):
            with self.subTest(entry=entry):
                self.verified_small()
                before = self.selects
                @contextmanager
                def failing_backend(*args, **kwargs):
                    if entry.endswith('open'):
                        raise AdapterError('db_connect', '가상 연결 오류')
                    class FailingInspection:
                        def inspect(self, *args):
                            raise AdapterError('auth_failed', '가상 인증 오류')
                    yield FailingInspection()
                with patch('query_core.core._using_backend', failing_backend):
                    with self.assertRaisesRegex(AdapterError, '가상'):
                        if entry.startswith('execute'):
                            self.execute()
                        else:
                            core.plan(self.store, 'oracle', 1, {})
                self.assertEqual(self.selects, before)
                with self.store.connect() as conn:
                    self.assertEqual(conn.execute('SELECT COUNT(*) FROM query_size_evidence').fetchone()[0], 0)
                self.assertFalse(self.execute()['executed'])

    def test_prepared_repeat_requires_approval_if_later_evidence_is_invalidated(self):
        self.verified_small()
        proposal = core.plan(self.store, 'oracle', 1, {})
        self.assertTrue(proposal['sizeEvidenceReused'])
        with self.store.connect() as conn:
            conn.execute('DELETE FROM query_size_evidence')
        before = self.selects
        response = core.run(self.store, 'oracle', proposal['planId'], confirmed=True)
        self.assertEqual(response['status'], 'large_query_approval_required')
        self.assertEqual(self.selects, before)
        self.assertTrue(core.run(self.store, 'oracle', proposal['planId'], confirmed=True, allow_large=True)['complete'])

    def test_one_execute_parses_once_and_rechecks_changed_definitions(self):
        self.verified_small()
        before = self.opens
        with patch('query_core.sql.analyze_sql', wraps=sql.analyze_sql) as analyze:
            result = self.execute()
        self.assertTrue(result['complete'])
        self.assertEqual(analyze.call_count, 1)
        self.assertEqual(self.opens-before, 1)
        original = self.store.query
        calls = []
        def changing(*args, **kwargs):
            value = original(*args, **kwargs)
            calls.append(1)
            if len(calls) > 1:
                value['sql'] = 'SELECT dangerous_fn(1) FROM dual'
            return value
        before = self.selects
        with patch.object(self.store, 'query', side_effect=changing):
            with self.assertRaisesRegex(ValueError, '바뀌'):
                self.execute()
        self.assertEqual(before, self.selects)

    def test_start_does_not_read_data_and_confirm_still_checks_original_hash(self):
        result = self.verified_small()
        folder = Path(result['dataFile']).parent
        metadata = read_json(folder/'metadata.json')
        metadata['createdAt'] = time.time()-25*3600
        atomic_json(folder/'metadata.json', metadata)
        real_open = Path.open
        def metadata_only(path, *args, **kwargs):
            if path.suffix in {'.jsonl', '.csv'}:
                raise AssertionError('start read saved data')
            return real_open(path, *args, **kwargs)
        with patch.object(Path, 'open', metadata_only):
            startup = cli.startup(self.store, 'oracle')
        proposal = startup['cleanup']
        self.assertEqual(proposal['resultIds'], [result['resultId']])
        data = Path(result['dataFile'])
        before = data.stat()
        data.write_bytes(data.read_bytes().replace(b'[1]', b'[9]'))
        os.utime(data, ns=(before.st_atime_ns, before.st_mtime_ns))
        report = results.delete_cleanup(self.store, 'oracle', proposal['planId'], confirmed=True)
        self.assertEqual(report['deletedIds'], [])
        self.assertTrue(data.exists())


if __name__ == '__main__':
    unittest.main()
