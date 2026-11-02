"""실제 SDK 설치나 사내 연결 없이 Datalake CLI와 탐색 결과 계약을 검증합니다."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from decimal import Decimal
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
import pandas as pd
from query_core import cli
from query_core.store import Store
from tests.query_skills.test_datalake_sdk import FakeSDK, SECRETS


class SDKCliDiscoveryTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/sdk-cli-discovery-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'state')
        self.profile = {'id': 'lake_test', 'name': '테스트 데이터', 'engine': 'datalake', 'lake_type': 'prod'}
        self.store.save_profile(self.profile, dict(SECRETS))

    def call(self, *arguments, fake=None):
        fake = fake if fake is not None else FakeSDK()
        output, errors = io.StringIO(), io.StringIO()
        with fake.installed(), redirect_stdout(output), redirect_stderr(errors):
            code = cli.main('datalake', ['--state-root', str(self.store.root), *map(str, arguments)])
        self.assertEqual(errors.getvalue(), '')
        text = output.getvalue()
        for secret in SECRETS.values():
            self.assertNotIn(secret, text)
        return code, json.loads(text), fake

    def discovery(self, operation, *arguments, fake=None):
        return self.call('discover', operation, '--profile', self.profile['id'], *arguments, fake=fake)

    def env_file(self):
        source = self.root / '.env'
        source.write_text('\n'.join('LAKEHOUSE_' + key.upper() + '=' + json.dumps(value)
                                    for key, value in SECRETS.items()) + '\n', encoding='utf-8')
        return source

    def saved_query(self):
        info = self.store.save_query({'name': '조회 조건 검증', 'profile': self.profile['id'],
            'sql': 'SELECT value FROM records WHERE id=:key',
            'parameters': {'key': {'type': 'int', 'required': True}}}, 'datalake')
        params = self.root / 'params.json'
        params.write_text('{"key": 1}', encoding='utf-8')
        return info['id'], params

    def test_import_parser_dispatches_explicit_options_to_store(self):
        source = self.root / '.env'
        with patch.object(Store, 'import_datalake_env', autospec=True,
                          return_value={'ok': True, 'connected': False}) as imported:
            code, result, fake = self.call('profiles', 'import-env', '--file', source,
                                           '--profile', self.profile['id'], '--name', '새 별칭')
        self.assertEqual(code, 0)
        self.assertFalse(result['connected'])
        imported.assert_called_once()
        self.assertEqual(imported.call_args.args[1], source)
        self.assertEqual(imported.call_args.kwargs, {'name': '새 별칭', 'profile_id': self.profile['id']})
        self.assertEqual(fake.imports, [])

    def test_import_current_directory_env_preserves_source_query_and_existing_alias(self):
        query_id, _ = self.saved_query()
        source = self.env_file()
        before = source.read_bytes()
        with patch.object(Path, 'cwd', return_value=self.root):
            code, result, fake = self.call('profiles', 'import-env', '--profile', self.profile['id'])
        self.assertEqual(code, 0)
        self.assertFalse(result['connected'])
        self.assertFalse(result['executed'])
        self.assertEqual(self.store.profile(self.profile['id'])['name'], self.profile['name'])
        self.assertEqual(self.store.secrets(self.profile['id']), SECRETS)
        self.assertEqual(self.store.query(query_id, 'datalake')['id'], query_id)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(fake.imports, [])

    def test_import_rejects_other_directory_without_changing_saved_credentials(self):
        outside = self.root / 'other'
        outside.mkdir()
        source = outside / '.env'
        source.write_text('LAKEHOUSE_TOKEN=OTHER_SYNTHETIC_TOKEN', encoding='utf-8')
        with patch.object(Path, 'cwd', return_value=self.root):
            code, result, fake = self.call('profiles', 'import-env', '--file', source,
                                           '--profile', self.profile['id'])
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'input_required')
        self.assertEqual(self.store.secrets(self.profile['id']), SECRETS)
        self.assertEqual(fake.imports, [])

    def test_start_returns_four_credential_labels_and_key_page_without_sdk(self):
        code, result, fake = self.call('start')
        self.assertEqual(code, 0)
        self.assertEqual(result['credentialHelp']['requiredFields'],
                         ['사번', 'JWT Token', 'S3 Access Key', 'S3 Secret Key'])
        self.assertEqual(result['credentialHelp']['keyPage'], 'https://lake.skhynix.com/myprofile/mykey')
        self.assertFalse(result['connected'])
        self.assertEqual(result['dataRowsReturned'], 0)
        self.assertEqual(fake.imports, [])

    def test_missing_credentials_are_actionable_without_sdk_import(self):
        self.store.write_secrets(self.profile['id'], {'user_id': SECRETS['user_id'], 'token': SECRETS['token']})
        code, result, fake = self.discovery('tables', '--schema', 'mes', '--like', '%lot%')
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'auth_config')
        self.assertEqual(result['credentialHelp']['keyPage'], 'https://lake.skhynix.com/myprofile/mykey')
        self.assertEqual(result['dataRowsReturned'], 0)
        self.assertEqual(fake.imports, [])

    def test_401_and_403_are_sanitized_and_return_key_page(self):
        for status in (401, 403):
            with self.subTest(status=status):
                error = RuntimeError('PRIVATE_TOKEN rejected')
                error.response = types.SimpleNamespace(status_code=status)
                code, result, fake = self.discovery('tables', '--schema', 'mes', '--like', '%lot%',
                                                    fake=FakeSDK(failure=error))
                self.assertEqual(code, 2)
                self.assertEqual(result['status'], 'api_' + str(status))
                self.assertEqual(result['credentialHelp']['keyPage'], 'https://lake.skhynix.com/myprofile/mykey')
                self.assertEqual(len(fake.queries), 1)
                self.assertEqual(fake.closed, 1)

    def test_discovery_commands_reach_only_the_expected_sdk_metadata_query(self):
        sql_file = self.root / 'explain.sql'
        sql_file.write_text('SELECT value FROM records WHERE id=1', encoding='utf-8')
        cases = [
            ('tables', ['--schema', 'mes', '--like', "%O'Reilly%"],
             "SHOW TABLES FROM `lake_catalog`.`mes` LIKE '%O''Reilly%'", 'tables'),
            ('describe', ['--table', 'lake_catalog.mes.records'],
             'DESCRIBE `lake_catalog`.`mes`.`records`', 'describe'),
            ('show-create', ['--table', 'lake_catalog.mes.records'],
             'SHOW CREATE TABLE `lake_catalog`.`mes`.`records`', 'create_table'),
            ('explain', ['--sql-file', sql_file],
             'EXPLAIN SELECT value FROM records WHERE id = 1', 'explain'),
        ]
        for operation, arguments, expected, kind in cases:
            with self.subTest(operation=operation):
                fake = FakeSDK(pd.DataFrame({'metadata': ['known-schema']}))
                code, result, fake = self.discovery(operation, *arguments, fake=fake)
                self.assertEqual(code, 0)
                self.assertEqual(fake.queries, [expected])
                self.assertEqual(result['kind'], kind)
                self.assertEqual(result['dataRowsReturned'], 0)
                self.assertEqual(result['metadataRowsReturned'], 1)
                self.assertTrue(Path(result['metadataFile']).is_file())
                self.assertEqual(fake.closed, 1)

    def test_identifier_injection_and_wrong_catalog_fail_before_sdk(self):
        cases = [('tables', '--schema', 'mes;DROP TABLE x', '--like', '%'),
                 ('describe', '--table', 'lake_catalog.mes.t;DELETE FROM x'),
                 ('show-create', '--table', 'other_catalog.mes.t'),
                 ('describe', '--table', 'lake_catalog.mes.`t`')]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                code, result, fake = self.discovery(*arguments)
                self.assertEqual(code, 2)
                self.assertEqual(result['status'], 'input_required')
                self.assertEqual(fake.imports, [])

    def test_explain_requires_one_unbound_readonly_select_before_sdk(self):
        source = self.root / 'query.sql'
        for sql in ('DELETE FROM records', 'SELECT 1; DROP TABLE records',
                    'SELECT * FROM records WHERE id=:key', 'SELECT SLEEP(1)',
                    'EXPLAIN ANALYZE SELECT * FROM records'):
            with self.subTest(sql=sql):
                source.write_text(sql, encoding='utf-8')
                code, result, fake = self.discovery('explain', '--sql-file', source)
                self.assertEqual(code, 2)
                self.assertEqual(result['status'], 'input_required')
                self.assertEqual(fake.imports, [])

    def test_table_limit_is_one_to_one_hundred_and_truncation_is_explicit(self):
        for limit in ('0', '101'):
            with self.subTest(limit=limit):
                code, result, fake = self.discovery('tables', '--schema', 'mes', '--like', '%', '--limit', limit)
                self.assertEqual(code, 2)
                self.assertEqual(fake.imports, [])
        fake = FakeSDK(pd.DataFrame({'name': ['table_' + str(i) for i in range(101)]}))
        code, result, _ = self.discovery('tables', '--schema', 'mes', '--like', '%', fake=fake)
        self.assertEqual(code, 0)
        self.assertEqual(result['metadataRowsReturned'], 100)
        self.assertFalse(result['complete'])
        self.assertTrue(result['previewTruncated'])
        self.assertEqual(result['dataRowsReturned'], 0)

    def test_explicit_small_limit_does_not_return_additional_metadata_rows(self):
        fake = FakeSDK(pd.DataFrame({'name': ['a', 'b', 'c']}))
        code, result, _ = self.discovery('tables', '--schema', 'mes', '--like', '%', '--limit', '2', fake=fake)
        self.assertEqual(code, 0)
        self.assertEqual(result['rows'], [['a'], ['b']])
        self.assertFalse(result['complete'])

    def test_long_ddl_is_saved_locally_and_shortened_preview_is_explicit(self):
        ddl = 'CREATE TABLE t (value INT) COMMENT "' + '설명' * 6000 + '"'
        code, result, _ = self.discovery('show-create', '--table', 'lake_catalog.mes.records',
                                         fake=FakeSDK(pd.DataFrame({'Create Table': [ddl]})))
        self.assertEqual(code, 0)
        self.assertEqual(result['metadataRowsReturned'], 1)
        self.assertLess(len(result['rows'][0][0]), len(ddl))
        self.assertTrue(ddl.startswith(result['rows'][0][0].rstrip('…')))
        self.assertTrue(result['previewTruncated'])
        self.assertFalse(result['complete'])
        self.assertLess(len(json.dumps(result, ensure_ascii=False)), 8000)
        saved = json.loads(Path(result['metadataFile']).read_text(encoding='utf-8'))
        self.assertEqual(saved['rows'], [[ddl]])

    def test_many_metadata_rows_obey_preview_budget_and_keep_local_rows(self):
        rows = ['설명 ' + str(i) + ' x' * 300 for i in range(40)]
        code, result, _ = self.discovery('describe', '--table', 'lake_catalog.mes.records',
                                         fake=FakeSDK(pd.DataFrame({'description': rows})))
        self.assertEqual(code, 0)
        self.assertLess(result['metadataRowsReturned'], len(rows))
        self.assertTrue(result['previewTruncated'])
        self.assertLessEqual(len(json.dumps({'columns': result['columns'], 'rows': result['rows']},
                                           ensure_ascii=False)), 8000)
        saved = json.loads(Path(result['metadataFile']).read_text(encoding='utf-8'))
        self.assertEqual(saved['rows'], [[row] for row in rows])

    def test_metadata_redaction_applies_to_preview_and_saved_file(self):
        ddl = ('CREATE TABLE t (id INT) PROPERTIES ("s3.access_key"="OTHER_ACCESS", '
               '"password"="OTHER_PASSWORD", "comment"="' + ' '.join(SECRETS.values()) + '")')
        code, result, _ = self.discovery('show-create', '--table', 'lake_catalog.mes.records',
                                         fake=FakeSDK(pd.DataFrame({'Create Table': [ddl]})))
        self.assertEqual(code, 0)
        saved = Path(result['metadataFile']).read_text(encoding='utf-8')
        text = json.dumps(result, ensure_ascii=False) + saved
        for secret in (*SECRETS.values(), 'OTHER_ACCESS', 'OTHER_PASSWORD'):
            self.assertNotIn(secret, text)
        self.assertIn('REDACTED', text)

    def test_metadata_dates_and_decimal_values_remain_json_serializable(self):
        frame = pd.DataFrame([[date(2026, 11, 2), Decimal('123.000000000000000001')]], columns=['day', 'amount'])
        code, result, _ = self.discovery('describe', '--table', 'lake_catalog.mes.records', fake=FakeSDK(frame))
        self.assertEqual(code, 0)
        self.assertEqual(result['rows'], [['2026-11-02', '123.000000000000000001']])
        saved = json.loads(Path(result['metadataFile']).read_text(encoding='utf-8'))
        self.assertEqual(saved['rows'], result['rows'])

    def test_large_column_names_are_saved_and_short_preview_is_marked(self):
        columns = ['column_' + str(i) + '_' + 'x' * 190 for i in range(60)]
        frame = pd.DataFrame([list(range(60))], columns=columns)
        code, result, _ = self.discovery('describe', '--table', 'lake_catalog.mes.records', fake=FakeSDK(frame))
        self.assertEqual(code, 0)
        self.assertTrue(result['previewTruncated'])
        self.assertFalse(result['complete'])
        self.assertLess(len(json.dumps(result, ensure_ascii=False)), 9000)
        saved = json.loads(Path(result['metadataFile']).read_text(encoding='utf-8'))
        self.assertEqual(saved['columns'], columns)
        self.assertEqual(saved['rows'], [list(range(60))])

    def test_finite_timeout_plan_and_execute_fail_without_sdk_import(self):
        query_id, params = self.saved_query()
        for command in ('plan', 'execute'):
            arguments = [command, '--id', query_id, '--params', params, '--timeout', '60']
            if command == 'execute':
                arguments.append('--confirm')
            with self.subTest(command=command):
                code, result, fake = self.call(*arguments)
                self.assertEqual(code, 2)
                self.assertEqual(result['status'], 'input_required')
                self.assertIn('--timeout', result['message'])
                self.assertEqual(fake.imports, [])


if __name__ == '__main__':
    unittest.main()
