"""조건 입력, 등록 시험, 새 조회와 정상 0건을 모의 SDK로 검증합니다."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
import pandas as pd
from query_core import cli, core
from query_core.inputs import InputError, read_params
from query_core.registration import validation_info
from query_core.store import Store, read_json
from tests.query_skills.test_datalake_sdk import FakeSDK, SECRETS


class QueryInputValidationTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / '.smoke/query-input-validation-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        working = patch.object(Path, "cwd", return_value=self.root)
        working.start(); self.addCleanup(working.stop)
        self.store = Store(self.root / 'personal')
        self.store.save_profile({'id': 'lake', 'name': 'Data Lake', 'engine': 'datalake'}, dict(SECRETS))
        self.spec = {'name': '장비 할당 현황', 'sql': 'SELECT value FROM lake_catalog.mes.records WHERE id>=:record_id',
                     'parameters': {'record_id': {'type': 'int'}}}
        self.source = self.root / 'spec.json'
        self.write_spec()
        self.saved = self.store.save_query(dict(self.spec, name='기존 조회'), 'datalake')

    def write_spec(self):
        self.source.write_text(json.dumps(self.spec, ensure_ascii=False), encoding='utf-8')

    def call(self, *args, fake=None):
        fake = fake or FakeSDK()
        output, errors = io.StringIO(), io.StringIO()
        with fake.installed(), redirect_stdout(output), redirect_stderr(errors):
            code = cli.main('datalake', ['--state-root', str(self.store.root), *map(str, args)])
        self.assertEqual(errors.getvalue(), '')
        for secret in SECRETS.values():
            self.assertNotIn(secret, output.getvalue())
        return code, json.loads(output.getvalue()), fake

    def register(self, *args, fake=None):
        return self.call('queries', 'register', '--spec', self.source, *args, fake=fake)

    def test_inline_json_and_json_file_execute_the_same_conditions(self):
        params = self.root / 'params.json'
        params.write_text('{"record_id": 7}', encoding='utf-8')
        sql = []
        for value in ('{"record_id": 7}', params):
            code, result, fake = self.call('execute', '--id', self.saved['id'], '--params', value, '--confirm')
            self.assertEqual(code, 0)
            self.assertEqual(result['savedRows'], 3)
            sql.append(fake.queries[0])
        self.assertEqual(sql[0], sql[1])

    def test_missing_params_file_is_input_error_and_never_contacts_sdk(self):
        code, result, fake = self.call('execute', '--id', self.saved['id'], '--params', self.root / 'missing.json', '--confirm')
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'params_file_not_found')
        self.assertEqual(result['failureStage'], 'input')
        self.assertFalse(result['queryExecuted'])
        self.assertEqual(fake.imports, [])

    def test_invalid_json_does_not_echo_values_or_blame_sdk(self):
        code, result, fake = self.call('execute', '--id', self.saved['id'], '--params', '{"PRIVATE_VALUE": }', '--confirm')
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'params_invalid_json')
        self.assertNotIn('PRIVATE_VALUE', json.dumps(result))
        self.assertEqual(fake.queries, [])

    def test_duplicate_keys_nonfinite_arrays_and_oversize_rejected_before_query(self):
        for value, expected in [('{"x":1,"x":2}', 'params_duplicate_key'), ('{"x":NaN}', 'params_invalid_json'),
                                ('[]', 'params_not_object'), ('{"x":"' + '가'*40_000 + '"}', 'params_too_large')]:
            with self.subTest(expected=expected), self.assertRaises(InputError) as failed:
                read_params(value)
            self.assertEqual(failed.exception.code, expected)

    def test_registration_runs_once_at_most_ten_rows_and_keeps_original_sql(self):
        fake = FakeSDK(frame=pd.DataFrame({'value': range(40)}))
        code, result, fake = self.register('--params', '{"record_id":0}', '--confirm', fake=fake)
        self.assertEqual(code, 0)
        self.assertEqual(result['validationStatus'], 'success_with_rows')
        self.assertTrue(result['registered'])
        self.assertTrue(result['queryExecuted'])
        self.assertEqual(result['testResult']['savedRows'], 10)
        self.assertFalse(result['testResult']['complete'])
        self.assertEqual(result['dataRowsReturned'], 0)
        self.assertNotIn('rows', result)
        self.assertEqual(len(fake.queries), 1)
        self.assertIn('LIMIT 11', fake.queries[0])
        self.assertNotIn('LIMIT', self.store.query(result['id'], 'datalake')['sql'])
        self.assertEqual(validation_info(self.store, 'datalake', result['id'])['validationStatus'], 'success_with_rows')

    def test_empty_registration_is_successful_sql_with_zero_data_not_an_error(self):
        code, result, fake = self.register('--params', '{"record_id": 1}', '--confirm', fake=FakeSDK(frame=pd.DataFrame({'value': []})))
        self.assertEqual(code, 0)
        self.assertEqual(result['validationStatus'], 'success_empty')
        self.assertEqual(result['testResult']['outcome'], 'empty')
        self.assertTrue(result['testResult']['emptyResult'])
        self.assertTrue(result['testResult']['complete'])
        self.assertEqual(len(fake.queries), 1)

    def test_registration_sql_error_is_saved_but_failed_with_safe_diagnostic(self):
        failure = RuntimeError("errCode = 1054, Unknown column 'wrong_column'")
        code, result, fake = self.register('--params', '{"record_id": 1}', '--confirm', fake=FakeSDK(failure=failure))
        self.assertEqual(code, 2)
        self.assertTrue(result['registered'])
        self.assertEqual(result['validationStatus'], 'error')
        self.assertEqual(result['errorDetails']['errorCode'], '1054')
        self.assertIn('wrong_column', result['message'])
        self.assertEqual(self.store.query(result['id'], 'datalake')['name'], self.spec['name'])
        stored = core.result_info(self.store, result['resultId'])
        self.assertEqual(stored['outcome'], 'error')
        self.assertIsNone(stored['emptyResult'])
        self.assertFalse(stored['dataAvailable'])
        self.assertNotIn('dataFile', stored)
        self.assertEqual(len(fake.queries), 1)

    def test_missing_conditions_saves_pending_without_guessing_or_sdk_call(self):
        code, result, fake = self.register('--confirm')
        self.assertEqual(code, 0)
        self.assertEqual(result['validationStatus'], 'parameters_required')
        self.assertFalse(result['queryExecuted'])
        self.assertEqual(fake.imports, [])

    def test_explicit_save_only_saves_without_sdk_call(self):
        code, result, fake = self.register('--params', '{"record_id":1}', '--save-only')
        self.assertEqual(code, 0)
        self.assertEqual(result['validationStatus'], 'not_tested')
        self.assertFalse(result['executed'])
        self.assertEqual(fake.imports, [])

    def test_registration_tests_by_default_without_extra_confirmation_flag(self):
        code, result, fake = self.register('--params', '{"record_id":1}')
        self.assertEqual(code, 0)
        self.assertTrue(result['queryExecuted'])
        self.assertEqual(result['validationStatus'], 'success_with_rows')
        self.assertEqual(len(fake.queries), 1)

    def test_save_only_does_not_require_query_conditions_or_sdk(self):
        code, result, fake = self.register('--save-only')
        self.assertEqual(code, 0)
        self.assertEqual(result['validationStatus'], 'not_tested')
        self.assertFalse(result['queryExecuted'])
        self.assertEqual(fake.imports, [])

    def test_query_without_parameters_needs_no_conditions_question(self):
        self.spec['sql'] = 'SELECT dummy FROM dual'
        self.spec['parameters'] = {}
        self.write_spec()
        code, result, fake = self.register('--confirm')
        self.assertEqual(code, 0)
        self.assertEqual(result['validationStatus'], 'success_with_rows')
        self.assertEqual(len(fake.queries), 1)

    def test_edited_query_does_not_inherit_prior_success(self):
        code, result, _ = self.register('--params', '{"record_id":1}', '--confirm')
        self.assertEqual(code, 0)
        updated = dict(self.spec, sql='SELECT another FROM lake_catalog.mes.records WHERE id>=:record_id')
        self.store.save_query(updated, 'datalake', query_id=result['id'])
        self.assertEqual(validation_info(self.store, 'datalake', result['id'])['validationStatus'], 'stale')

    def test_approval_wait_and_manual_run_update_registration_validation(self):
        self.spec['sql'] = 'SELECT value FROM lake_catalog.mes.records'
        self.spec['parameters'] = {}
        self.write_spec()
        code, result, fake = self.register('--confirm')
        self.assertEqual(code, 0)
        self.assertEqual(result['validationStatus'], 'approval_required')
        self.assertFalse(result['queryExecuted'])
        self.assertEqual(fake.imports, [])
        code, completed, fake = self.call('run', '--plan', result['planId'], '--confirm', '--allow-large')
        self.assertEqual(code, 0)
        self.assertTrue(completed['complete'])
        self.assertNotIn('validationLinkWarning', completed)
        checked = validation_info(self.store, 'datalake', result['id'])
        self.assertEqual(checked['validationStatus'], 'success_with_rows')
        self.assertEqual(checked['resultId'], completed['resultId'])

    def test_same_realtime_query_is_fresh_each_execution(self):
        ids = []
        fake = FakeSDK()
        for _ in range(2):
            code, result, _ = self.call('execute', '--id', self.saved['id'], '--params', '{"record_id":1}', '--confirm', fake=fake)
            self.assertEqual(code, 0)
            ids.append(result['resultId'])
        self.assertNotEqual(ids[0], ids[1])
        self.assertEqual(len(fake.queries), 2)
        code, saved, _ = self.call('result', '--id', ids[0])
        self.assertEqual(code, 0)
        self.assertEqual(saved['retrievalMode'], 'saved_result')
        self.assertFalse(saved['isFreshQuery'])
        self.assertEqual(saved['reusePermission'], 'not_granted')

    def test_direct_zero_and_error_receipts_remain_distinct(self):
        code, empty, _ = self.call('execute', '--id', self.saved['id'], '--params', '{"record_id":1}', '--confirm', fake=FakeSDK(frame=pd.DataFrame({'value': []})))
        self.assertEqual(code, 0)
        self.assertEqual(empty['outcome'], 'empty')
        code, error, _ = self.call('execute', '--id', self.saved['id'], '--params', '{"record_id":1}', '--confirm', fake=FakeSDK(failure=RuntimeError("Unknown column 'invalid_name'")))
        self.assertEqual(code, 2)
        self.assertIn('errorDetails', error)
        self.assertIn('resultId', error)
        self.assertNotIn('savedRows', error)
        metadata = read_json(self.store.root / 'results' / error['resultId'] / 'metadata.json')
        self.assertEqual(metadata['outcome'], 'error')
        self.assertIsNone(metadata['emptyResult'])


if __name__ == '__main__':
    unittest.main()
