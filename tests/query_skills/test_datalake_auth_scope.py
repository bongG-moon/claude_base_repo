"""한 번 설정한 인증정보로 서로 다른 테이블 경로를 조회합니다. 사내 접속은 없습니다."""
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
from query_core import cli, core
from query_core.store import Store
from tests.query_skills.test_datalake_sdk import FakeSDK, SECRETS


class DatalakeAuthScopeTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / '.smoke/datalake-auth-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'personal')
        self.profile = {'id': 'existing_lake', 'name': '기존 인증 별칭', 'engine': 'datalake', 'lake_type': 'prod'}
        self.store.save_profile(self.profile, dict(SECRETS))

    def spec(self, table='lake_catalog.mes.production_records', name='생산실적조회'):
        return {'name': name, 'sql': 'SELECT value FROM ' + table + ' WHERE id=:record_id',
                'parameters': {'record_id': {'type': 'int'}}}

    def env_file(self):
        source = self.root / '.env'
        source.write_text('\n'.join('LAKEHOUSE_' + key.upper() + '=' + json.dumps(value)
                                    for key, value in SECRETS.items()), encoding='utf-8')
        return source

    def call(self, *args, fake=None):
        fake = fake or FakeSDK()
        output, errors = io.StringIO(), io.StringIO()
        with fake.installed(), redirect_stdout(output), redirect_stderr(errors):
            status = cli.main('datalake', ['--state-root', str(self.store.root), *map(str, args)])
        self.assertEqual(errors.getvalue(), '')
        return status, json.loads(output.getvalue()), fake

    def test_one_auth_reused_for_two_schemas_and_no_database_registration(self):
        one = self.store.save_query(self.spec(), 'datalake')
        two = self.store.save_query(self.spec('lake_catalog.fdc.sensor_records', '설비센서조회'), 'datalake')
        fake = FakeSDK()
        with fake.installed():
            for query in (one, two):
                receipt = core.execute(self.store, 'datalake', query['id'], {'record_id': 1}, confirmed=True)
                self.assertTrue(receipt['complete'])
                self.assertEqual(receipt['savedRows'], 3)
                self.assertEqual(receipt['dataRowsReturned'], 0)
                self.assertEqual(self.store.query(query['id'], 'datalake')['profile'], 'existing_lake')
        self.assertEqual(len(self.store.profiles('datalake')), 1)
        self.assertEqual(len(fake.constructors), 2)
        self.assertIn('lake_catalog.mes.production_records', fake.queries[0])
        self.assertIn('lake_catalog.fdc.sensor_records', fake.queries[1])
        self.assertEqual(fake.constructors[0], fake.constructors[1])
        self.assertEqual(set(fake.constructors[0]), {'user_id', 'token', 's3_access_key', 's3_secret_key', 'type', 'spark'})

    def test_discovery_uses_only_auth_when_profile_omitted(self):
        status, result, fake = self.call('discover', 'describe', '--table', 'lake_catalog.mes.production_records')
        self.assertEqual(status, 0)
        self.assertEqual(result['dataRowsReturned'], 0)
        self.assertEqual(fake.queries, ['DESCRIBE `lake_catalog`.`mes`.`production_records`'])

    def test_query_registration_cli_does_not_require_profile(self):
        source = self.root / 'query.json'
        source.write_text(json.dumps(self.spec(), ensure_ascii=False), encoding='utf-8')
        status, result, fake = self.call('queries', 'register', '--spec', source)
        self.assertEqual(status, 0)
        self.assertEqual(self.store.query(result['id'], 'datalake')['profile'], 'existing_lake')
        self.assertEqual(fake.imports, [])

    def test_import_without_profile_updates_single_auth_and_preserves_queries(self):
        query = self.store.save_query(self.spec(), 'datalake')
        self.env_file()
        with patch.object(Path, 'cwd', return_value=self.root):
            status, result, fake = self.call('auth', 'import-env')
        self.assertEqual(status, 0)
        self.assertFalse(result['connected'])
        self.assertEqual(result['profile']['id'], 'existing_lake')
        self.assertEqual(len(self.store.profiles('datalake')), 1)
        self.assertEqual(self.store.query(query['id'], 'datalake')['name'], '생산실적조회')
        self.assertEqual(fake.imports, [])

    def test_empty_store_import_creates_one_auth_without_db_fields(self):
        empty = Store(self.root / 'empty')
        self.env_file()
        with patch.object(Path, 'cwd', return_value=self.root):
            created = empty.import_datalake_env()
            updated = empty.import_datalake_env()
        self.assertEqual(created['profile']['id'], updated['profile']['id'])
        self.assertEqual(len(empty.profiles('datalake')), 1)
        saved = empty.profile(created['profile']['id'])
        self.assertFalse(set(saved) & {'api_base', 'cluster', 'dsn'})

    def test_no_auth_gives_setup_instruction_without_sdk(self):
        empty = Store(self.root / 'empty')
        with self.assertRaisesRegex(ValueError, 'auth setup'):
            empty.save_query(self.spec(), 'datalake')
        self.assertEqual(empty.profiles('datalake'), [])

    def test_multiple_legacy_accounts_are_not_silently_reassigned(self):
        self.store.save_profile({'id': 'other_lake', 'name': '다른 인증', 'engine': 'datalake'}, dict(SECRETS))
        with self.assertRaisesRegex(ValueError, '인증정보가 여러 개'):
            self.store.save_query(self.spec(), 'datalake')
        status, result, fake = self.call('discover', 'describe', '--table', 'lake_catalog.mes.records')
        self.assertEqual(status, 2)
        self.assertEqual(fake.imports, [])
        self.env_file()
        with patch.object(Path, 'cwd', return_value=self.root), self.assertRaisesRegex(ValueError, '인증정보가 여러 개'):
            self.store.import_datalake_env()
        self.assertEqual(len(self.store.profiles('datalake')), 2)

    def test_existing_query_edit_keeps_original_auth_among_legacy_accounts(self):
        saved = self.store.save_query(self.spec(), 'datalake')
        self.store.save_profile({'id': 'other_lake', 'name': '다른 인증', 'engine': 'datalake'}, dict(SECRETS))
        self.store.save_query(self.spec('lake_catalog.cms.status_records'), 'datalake', query_id=saved['id'])
        self.assertEqual(self.store.query(saved['id'], 'datalake')['profile'], 'existing_lake')

    def test_explicit_legacy_auth_still_supported_and_other_engine_rejected(self):
        self.store.save_profile({'id': 'oracle_one', 'name': '운영DB', 'engine': 'oracle'},
                                {'user': 'fixture', 'password': 'fixture', 'dsn': 'fixture.invalid'})
        saved = self.store.save_query(dict(self.spec(), profile='existing_lake'), 'datalake')
        self.assertEqual(self.store.query(saved['id'], 'datalake')['profile'], 'existing_lake')
        with self.assertRaisesRegex(ValueError, '다른 서비스'):
            self.store.datalake_profile('oracle_one')
        with self.assertRaises(ValueError):
            self.store.save_query(self.spec(), 'oracle')

    def test_auth_setup_routes_to_local_gui_and_has_no_oracle_parser_alias(self):
        with patch('query_core.setup_ui.show', return_value={'ok': True, 'connected': False}) as setup:
            status, result, fake = self.call('auth', 'setup')
        self.assertEqual(status, 0)
        self.assertEqual(setup.call_args.args[1:], ('datalake', None))
        self.assertFalse(result['connected'])
        self.assertEqual(fake.imports, [])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.parser('oracle').parse_args(['auth', 'setup'])

    def test_start_explains_table_target_without_network(self):
        status, result, fake = self.call('start')
        self.assertEqual(status, 0)
        self.assertEqual(result['targetSelection'], 'table-path')
        self.assertIn('테이블마다 DB를 등록하지 않습니다', result['credentialHelp']['message'])
        self.assertEqual(fake.imports, [])


if __name__ == '__main__':
    unittest.main()
