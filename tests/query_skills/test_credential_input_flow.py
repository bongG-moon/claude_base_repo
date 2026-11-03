"""로컬 인증창 안내를 검증합니다. 개인 설정, 운영 접속과 실제 브라우저는 사용하지 않습니다."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
from query_core import adapters, cli, credentials, manager_ui, setup_ui
from query_core.credentials import (CredentialInputUnavailable, CredentialSetupRequired,
                                    input_guidance)
from query_core.store import Store
from tests.query_skills.test_datalake_sdk import FakeSDK, SECRETS


class CredentialInputFlowTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/credential-flow-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'personal')

    def profile(self, engine, secrets=None):
        identity = {'oracle': 'production', 'datalake': 'lake', 'ehub': 'hub'}[engine]
        profile = {'id': identity, 'name': engine + ' fixture', 'engine': engine}
        if engine == 'ehub':
            profile.update(api_base='https://fixture.invalid', allow_cluster_start=True)
        self.store.save_profile(profile, secrets)
        return identity

    def query(self, engine, identity):
        return self.store.save_query({'name': '조회 동작', 'profile': identity,
            'sql': 'SELECT value FROM fixtures WHERE id=:item',
            'parameters': {'item': {'type': 'int'}}}, engine)['id']

    def call(self, engine, *args, fake=None):
        fake = fake or FakeSDK()
        output, errors = io.StringIO(), io.StringIO()
        with fake.installed(), redirect_stdout(output), redirect_stderr(errors):
            code = cli.main(engine, ['--state-root', str(self.store.root), *map(str, args)])
        self.assertEqual(errors.getvalue(), '')
        for secret in SECRETS.values():
            self.assertNotIn(secret, output.getvalue())
        return code, json.loads(output.getvalue()), fake

    def assert_local(self, guidance, engine, identity):
        self.assertEqual(guidance['method'], 'local_browser')
        self.assertFalse(guidance['chatInputAllowed'])
        self.assertFalse(guidance['retryAutomatically'])
        self.assertEqual(guidance['profileId'], identity)
        self.assertEqual(guidance['nextAction'], 'open_local_input')
        command = ['auth', 'setup'] if engine == 'datalake' else ['profiles', 'setup']
        self.assertEqual(guidance['setupArgs'], command + (['--profile', identity] if identity else []))

    def test_each_engine_has_one_local_input_route_and_no_secret_values(self):
        for engine in ('oracle', 'datalake', 'ehub'):
            with self.subTest(engine=engine):
                guidance = input_guidance(engine, 'existing')
                self.assert_local(guidance, engine, 'existing')
                self.assertIn('채팅에 보내지 말고', guidance['beforeOpenMessage'])
                self.assertIn('입력창', guidance['beforeOpenMessage'])
                self.assertTrue(guidance['requiredFields'])
                self.assertFalse(set(guidance) & {'password', 'token', 's3_access_key', 's3_secret_key'})

    def test_finished_or_cancelled_input_never_requests_secrets_again(self):
        for status in ('saved', 'cancelled', 'expired', 'unavailable'):
            with self.subTest(status=status):
                guidance = input_guidance('oracle', 'production', status=status)
                self.assertFalse(guidance['chatInputAllowed'])
                self.assertFalse(guidance['retryAutomatically'])
                self.assertIsNone(guidance['setupArgs'])
                self.assertEqual(guidance['requiredFields'], [])
                self.assertEqual(guidance['nextAction'], 'continue_work' if status == 'saved' else 'wait_for_user')

    def test_demo_does_not_request_real_credentials_or_open_a_form(self):
        guidance = input_guidance('demo')
        self.assertEqual(guidance['method'], 'not_required')
        self.assertEqual(guidance['nextAction'], 'continue_work')
        self.assertNotIn('setupArgs', guidance)
        with patch('query_core.manager_ui.show') as opening, self.assertRaisesRegex(ValueError, '인증정보가 필요하지 않습니다'):
            setup_ui.show(self.store, 'demo')
        opening.assert_not_called()

    def test_guidance_only_accepts_existing_profile_identifier_syntax(self):
        for value in ('bad id', '../secret', 'id;echo', 3):
            with self.subTest(value=value), self.assertRaises(ValueError):
                input_guidance('oracle', value)

    def test_cli_action_uses_actual_skill_wrapper_and_preserves_state_root_without_values(self):
        script_dir = self.root / 'installed skill' / 'scripts'
        module = script_dir / 'query_core' / 'credentials.py'
        module.parent.mkdir(parents=True)
        module.write_text('# module location fixture', encoding='utf-8')
        wrapper = script_dir / 'query.py'
        wrapper.write_text('# actual wrapper fixture; never executed', encoding='utf-8')
        state = self.root / 'selected personal state'
        result = {'ok': False, 'credentialInput': input_guidance('datalake', 'lake')}
        with patch.object(credentials, '__file__', str(module)):
            returned = credentials.attach_cli_action(result, state)
        self.assertIs(returned, result)
        self.assertEqual(result['credentialInput']['commandArgv'], [sys.executable, '-X', 'utf8', '-B',
            str(wrapper.resolve()), '--state-root', str(state.absolute()), 'auth', 'setup', '--profile', 'lake'])
        for secret in SECRETS.values():
            self.assertNotIn(secret, json.dumps(result))
        wrapper.unlink()
        absent = {'credentialInput': input_guidance('datalake', 'lake')}
        with patch.object(credentials, '__file__', str(module)):
            credentials.attach_cli_action(absent, state)
        self.assertNotIn('commandArgv', absent['credentialInput'])

    def test_cli_action_does_not_probe_files_or_add_commands_after_save_or_cancel(self):
        values = [{'ok': True}, {'credentialInput': input_guidance('oracle', 'production', status='saved')},
                  {'credentialInput': input_guidance('oracle', 'production', status='cancelled')}]
        for value in values:
            with self.subTest(status=value.get('credentialInput', {}).get('status')):
                before = json.loads(json.dumps(value))
                with patch.object(credentials, 'Path', side_effect=AssertionError('no filesystem probe')) as paths:
                    returned = credentials.attach_cli_action(value, self.root / 'state')
                self.assertIs(returned, value)
                self.assertEqual(value, before)
                self.assertNotIn('commandArgv', value.get('credentialInput', {}))
                paths.assert_not_called()

    def test_missing_credential_file_returns_exact_setup_args_without_opening_browser(self):
        for engine in ('oracle', 'datalake', 'ehub'):
            with self.subTest(engine=engine):
                identity = self.profile(engine)
                query = self.query(engine, identity)
                with patch('query_core.manager_ui.webbrowser.open') as opening:
                    code, result, fake = self.call(engine, 'execute', '--id', query,
                                                   '--params', '{"item":1}', '--confirm')
                self.assertEqual(code, 2)
                self.assertEqual(result['status'], 'credentials_required')
                self.assertFalse(result['queryExecuted'])
                self.assert_local(result['credentialInput'], engine, identity)
                self.assertEqual(fake.imports, [])
                opening.assert_not_called()

    def test_first_datalake_use_requires_auth_window_not_database_registration(self):
        source = self.root / 'query.json'
        source.write_text(json.dumps({'name': '첫 조회',
            'sql': 'SELECT value FROM lake_catalog.mes.records WHERE id=1', 'parameters': {}}), encoding='utf-8')
        code, result, fake = self.call('datalake', 'queries', 'register', '--spec', source, '--parameters-reviewed')
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'credentials_required')
        self.assert_local(result['credentialInput'], 'datalake', None)
        self.assertEqual(fake.imports, [])
        self.assertEqual(self.store.profiles('datalake'), [])

    def test_backend_authentication_errors_keep_engine_and_known_profile(self):
        for engine in ('oracle', 'datalake', 'ehub'):
            with self.subTest(engine=engine):
                profile = {'id': 'existing', 'engine': engine}
                error = adapters.AdapterError('auth_config', '인증정보가 필요합니다.')
                with self.assertRaises(adapters.AdapterError):
                    with adapters.open_backend(profile, {}) as backend:
                        raise error
                self.assert_local(error.credential_input, engine, 'existing')

    def test_expired_sdk_authentication_returns_update_route_without_values(self):
        identity = self.profile('datalake', dict(SECRETS))
        query = self.query('datalake', identity)
        failure = RuntimeError('401 PRIVATE_TOKEN')
        failure.status_code = 401
        code, result, fake = self.call('datalake', 'execute', '--id', query,
            '--params', '{"item":1}', '--confirm', fake=FakeSDK(failure=failure))
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'api_401')
        self.assertEqual(result['credentialInput']['status'], 'update_required')
        self.assert_local(result['credentialInput'], 'datalake', identity)
        self.assertEqual(len(fake.queries), 1)

    def test_sql_error_is_not_misreported_as_a_request_for_new_credentials(self):
        error = adapters.AdapterError('db_query', 'SQL 컬럼을 확인해 주세요.', {'category': 'sql'})
        with self.assertRaises(adapters.AdapterError):
            with adapters.open_backend({'id': 'existing', 'engine': 'oracle'}, {}):
                raise error
        self.assertFalse(hasattr(error, 'credential_input'))

    def test_successful_query_neither_opens_browser_nor_returns_setup_request(self):
        identity = self.profile('datalake', dict(SECRETS))
        query = self.query('datalake', identity)
        with patch('query_core.manager_ui.webbrowser.open') as opening, patch('query_core.credentials.input_guidance') as guidance:
            code, result, fake = self.call('datalake', 'execute', '--id', query,
                                           '--params', '{"item":1}', '--confirm')
        self.assertEqual(code, 0)
        self.assertTrue(result['complete'])
        self.assertNotIn('credentialInput', result)
        self.assertEqual(len(fake.queries), 1)
        opening.assert_not_called()
        guidance.assert_not_called()

    def test_registration_missing_s3_values_returns_local_route_without_asking_chat(self):
        identity = self.profile('datalake', {'user_id': SECRETS['user_id'], 'token': SECRETS['token']})
        source = self.root / 'query.json'
        source.write_text(json.dumps({'name': '등록 시험', 'profile': identity,
            'sql': 'SELECT value FROM fixtures WHERE id=1', 'parameters': {}}), encoding='utf-8')
        code, result, fake = self.call('datalake', 'queries', 'register', '--spec', source, '--parameters-reviewed')
        self.assertEqual(code, 2)
        self.assertTrue(result['registered'])
        self.assertEqual(result['validationStatus'], 'error')
        self.assertEqual(result['errorCode'], 'auth_config')
        self.assertFalse(result['queryExecuted'])
        self.assert_local(result['credentialInput'], 'datalake', identity)
        self.assertEqual(fake.imports, [])

    def test_saved_cancelled_and_expired_setup_return_distinct_no_retry_states(self):
        for status in ('saved', 'closed', 'expired'):
            with self.subTest(status=status):
                response = {'ok': True, 'status': status, 'connected': False}
                if status == 'saved':
                    response['profile'] = {'id': 'production', 'name': '생산 DB', 'engine': 'oracle'}
                with patch('query_core.manager_ui.show', return_value=response) as opening:
                    result = setup_ui.show(self.store, 'oracle', 'production')
                opening.assert_called_once_with(self.store, 'oracle', 'production', start_view='connection')
                guidance = result['credentialInput']
                self.assertEqual(guidance['status'], 'cancelled' if status == 'closed' else status)
                self.assertIsNone(guidance['setupArgs'])
                self.assertFalse(guidance['retryAutomatically'])
                self.assertEqual(guidance['nextAction'], 'continue_work' if status == 'saved' else 'wait_for_user')
                self.assertNotIn('password', result)

    def test_browser_refusal_or_exception_stops_server_and_has_no_chat_fallback(self):
        for failure in (False, RuntimeError('PRIVATE browser diagnostic')):
            with self.subTest(failure=type(failure).__name__):
                server = SimpleNamespace(url='http://127.0.0.1:1/fixture/', closed=threading.Event(),
                    serve_forever=Mock(), shutdown=Mock(), server_close=Mock())
                opener = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
                output = io.StringIO()
                with patch.object(manager_ui, 'ManagerServer', return_value=server), \
                        patch.object(manager_ui.webbrowser, 'open', **opener), \
                        redirect_stdout(output), redirect_stderr(output), \
                        self.assertRaises(CredentialInputUnavailable) as failed:
                    manager_ui.show(self.store, 'oracle', 'production', start_view='connection')
                self.assertTrue(server.closed.is_set())
                server.shutdown.assert_called_once()
                server.server_close.assert_called_once()
                self.assertEqual(output.getvalue(), '')
                guidance = failed.exception.credential_input
                self.assertEqual(guidance['status'], 'unavailable')
                self.assertFalse(guidance['chatInputAllowed'])
                self.assertIsNone(guidance['setupArgs'])
                self.assertNotIn('PRIVATE', str(failed.exception))

    def test_missing_credentials_can_be_completed_in_form_without_new_profile_or_query(self):
        identity = self.profile('datalake')
        query = self.query('datalake', identity)
        server = object.__new__(manager_ui.ManagerServer)
        server.store, server.engine = self.store, 'datalake'
        server.saved_count, server.saved_profile = 0, None
        detail = server.dispatch({'action': 'profile', 'id': identity})['profile']
        self.assertFalse(detail['tokenSaved'])
        self.assertFalse(detail['s3AccessKeySaved'])
        self.assertFalse(detail['s3SecretKeySaved'])
        saved = server.dispatch({'action': 'save', 'id': identity, 'name': '내 인증', 'lake_type': 'prod', **SECRETS})
        self.assertEqual(saved['profile']['id'], identity)
        self.assertFalse(saved['connected'])
        self.assertEqual(self.store.secrets(identity), SECRETS)
        self.assertEqual(len(self.store.profiles('datalake')), 1)
        self.assertEqual(self.store.query(query, 'datalake')['profile'], identity)
        for secret in SECRETS.values():
            self.assertNotIn(secret, json.dumps(saved))

    def test_corrupted_credential_file_is_not_silently_replaced_by_form(self):
        identity = self.profile('datalake', dict(SECRETS))
        source = self.store.root / 'connections' / (identity + '.env')
        source.write_text('UNSUPPORTED_SETTING=PRIVATE-fixture', encoding='utf-8')
        before = source.read_bytes()
        server = object.__new__(manager_ui.ManagerServer)
        server.store, server.engine = self.store, 'datalake'
        server.saved_count, server.saved_profile = 0, None
        with self.assertRaises(ValueError):
            server.dispatch({'action': 'profile', 'id': identity})
        with self.assertRaises(ValueError):
            server.dispatch({'action': 'save', 'id': identity, 'name': '내 인증', 'lake_type': 'prod', **SECRETS})
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(server.saved_count, 0)


if __name__ == '__main__':
    unittest.main()
