"""운영 접속 없이 서버 코드와 마스킹한 이유, 0행 결과를 구분합니다."""
from contextlib import contextmanager
import io
import json
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
import pandas as pd
from query_core import adapters as a
from query_core.errors import error_details, MAX_REASON_BYTES
from tests.query_skills.test_datalake_sdk import FakeSDK, SECRETS


class ServerFailure(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.errno = code


class SQLCursor:
    description = [('VALUE',)]

    def __init__(self, failure=None, fetch_failure=None):
        self.failure, self.fetch_failure = failure, fetch_failure

    def execute(self, sql, params=None):
        if sql.startswith('SELECT') and self.failure:
            raise self.failure

    def fetchmany(self, size):
        if self.fetch_failure:
            raise self.fetch_failure
        return []

    def close(self):
        pass


class SQLConnection:
    def __init__(self, cursor):
        self.active_cursor = cursor

    def cursor(self):
        return self.active_cursor

    def rollback(self):
        pass

    def close(self):
        pass

    def cancel(self):
        pass


class QueryErrorDetailTests(unittest.TestCase):
    def setUp(self):
        blocker = patch.object(socket, 'create_connection', side_effect=AssertionError('real network forbidden'))
        blocker.start()
        self.addCleanup(blocker.stop)
        self.credentials = {'user': 'fixture_reader', 'password': 'PRIVATE_PASSWORD',
                            'dsn': 'private-host.invalid:1521/PRIVATE_SERVICE'}
        self.params = {'equipment': 'PRIVATE_EQUIPMENT'}

    def safe(self, error):
        text = json.dumps({'message': error.message, 'details': error.details}, ensure_ascii=False)
        for value in list(self.credentials.values()) + list(SECRETS.values()) + list(self.params.values()):
            self.assertNotIn(value, text)
        self.assertLessEqual(len(error.details['sanitizedReason'].encode('utf-8')), MAX_REASON_BYTES)
        self.assertFalse(error.details['retryable'])

    @contextmanager
    def oracle(self, cursor, connection_failure=None):
        calls = []

        def connect(**kwargs):
            calls.append(kwargs)
            if connection_failure:
                raise connection_failure
            return SQLConnection(cursor)

        driver = types.SimpleNamespace(connect=connect, is_thin_mode=lambda: True)
        real_import = a.importlib.import_module

        def importer(name, *args, **kwargs):
            return driver if name == 'oracledb' else real_import(name, *args, **kwargs)

        with patch.object(a.importlib, 'import_module', side_effect=importer):
            with a.open_backend({'engine': 'oracle'}, self.credentials) as backend:
                yield backend, calls

    def test_oracle_query_reports_code_and_identifier_not_sql_or_parameters(self):
        failure = ServerFailure('ORA-00904: "BAD_COLUMN": invalid identifier\nSQL: SELECT PRIVATE_EQUIPMENT; password=PRIVATE_PASSWORD')
        with self.oracle(SQLCursor(failure=failure)) as (backend, calls):
            with self.assertRaises(a.AdapterError) as caught:
                with backend.execute('SELECT value FROM t WHERE equipment=:equipment', self.params,
                                     limit=10, timeout_seconds=60):
                    self.fail('SQL failure cannot become success')
        error = caught.exception
        self.assertEqual(error.code, 'db_query')
        self.assertEqual(error.details['errorCode'], 'ORA-00904')
        self.assertEqual(error.details['category'], 'sql')
        self.assertEqual(error.details['stage'], 'query')
        self.assertIn('BAD_COLUMN', error.message)
        self.assertNotIn('SELECT', error.message)
        self.assertNotIn('HyDAP', error.message)
        self.assertEqual(len(calls), 1)
        self.safe(error)

    def test_oracle_connection_keeps_company_help_but_hides_dsn_and_server_reason(self):
        failure = ServerFailure('ORA-01017: login PRIVATE_PASSWORD private-host.invalid:1521/PRIVATE_SERVICE')
        with self.oracle(SQLCursor(), failure) as (backend, calls):
            with self.assertRaises(a.AdapterError) as caught:
                backend._connect()
        error = caught.exception
        self.assertEqual(error.code, 'db_connect')
        self.assertIn('HyDAP(Chakra)실행 여부 및 MyAccess권한 확인 부탁드립니다', error.message)
        self.assertEqual(error.details['category'], 'authentication')
        self.assertEqual(error.details['stage'], 'connect')
        self.assertEqual(error.details['errorCode'], 'ORA-01017')
        self.assertEqual(len(calls), 1)
        self.safe(error)

    def test_mysql_unknown_column_is_visible_and_token_and_bind_are_masked(self):
        failure = ServerFailure("Unknown column 'missing_eqp' in where clause; token=PRIVATE_TOKEN; value='PRIVATE_EQUIPMENT'", 1054)
        backend = a.LakeBackend({'engine': 'ehub'}, dict(SECRETS))
        backend.connection = SQLConnection(SQLCursor(failure=failure))
        with self.assertRaises(a.AdapterError) as caught:
            with backend.execute('SELECT value FROM t WHERE equipment=:equipment', self.params,
                                 limit=10, timeout_seconds=60):
                self.fail('failure cannot become an empty result')
        error = caught.exception
        self.assertEqual(error.code, 'db_query')
        self.assertEqual(error.details['errorCode'], '1054')
        self.assertIn('missing_eqp', error.details['sanitizedReason'])
        self.safe(error)

    def test_fetch_sql_error_remains_a_fetch_failure(self):
        with self.oracle(SQLCursor(fetch_failure=ServerFailure('ORA-01476: divisor is equal to zero'))) as (backend, _):
            with self.assertRaises(a.AdapterError) as caught:
                with backend.execute('SELECT value FROM t', {}, limit=10, timeout_seconds=60) as (_, rows):
                    list(rows)
        error = caught.exception
        self.assertEqual(error.code, 'db_fetch')
        self.assertEqual(error.details['stage'], 'fetch')
        self.assertEqual(error.details['errorCode'], 'ORA-01476')
        self.safe(error)

    def test_sdk_sql_failure_keeps_short_reason_and_suppresses_printed_credentials(self):
        failure = ServerFailure("Unknown column 'missing_eqp' in where clause; secret=PRIVATE_S3_SECRET; params: PRIVATE_EQUIPMENT", 1054)
        fake = FakeSDK(failure=failure)
        output, errors = io.StringIO(), io.StringIO()
        from contextlib import redirect_stdout, redirect_stderr
        with fake.installed(), redirect_stdout(output), redirect_stderr(errors):
            with a.open_backend({'engine': 'datalake'}, dict(SECRETS), timeout_seconds=None) as backend:
                with self.assertRaises(a.AdapterError) as caught:
                    with backend.execute('SELECT value FROM t WHERE equipment=:equipment', self.params,
                                         limit=10, timeout_seconds=None):
                        self.fail('SDK failure cannot succeed')
        error = caught.exception
        self.assertEqual(error.details['errorCode'], '1054')
        self.assertIn('missing_eqp', error.message)
        self.assertNotIn('params:', error.message)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(errors.getvalue(), '')
        self.safe(error)

    def test_sdk_auth_failure_exposes_http_status_without_token(self):
        failure = ServerFailure('Unknown column PRIVATE_TOKEN token=PRIVATE_TOKEN')
        failure.response = types.SimpleNamespace(status_code=401)
        with FakeSDK(failure=failure).installed(), a.open_backend({'engine': 'datalake'}, dict(SECRETS), timeout_seconds=None) as backend:
            with self.assertRaises(a.AdapterError) as caught:
                with backend.execute('SELECT value FROM t', {}, limit=10, timeout_seconds=None):
                    self.fail('authentication failure cannot succeed')
        error = caught.exception
        self.assertEqual(error.code, 'api_401')
        self.assertEqual(error.details['errorCode'], 'HTTP-401')
        self.assertEqual(error.details['category'], 'authentication')
        self.assertNotIn('Unknown column', error.details['sanitizedReason'])
        self.safe(error)

    def test_successful_zero_rows_is_not_an_adapter_error(self):
        with FakeSDK(pd.DataFrame({'value': []})).installed(), a.open_backend({'engine': 'datalake'}, dict(SECRETS), timeout_seconds=None) as backend:
            with backend.execute('SELECT value FROM t', {}, limit=10, timeout_seconds=None) as (columns, rows):
                self.assertEqual(columns, ['value'])
                self.assertEqual(list(rows), [])

    def test_general_unrecognized_exception_text_is_not_dumped(self):
        details = error_details(ServerFailure('PRIVATE_SERVER_DATA and source row [123, 456]'))
        self.assertNotIn('PRIVATE', json.dumps(details))
        self.assertEqual(details['category'], 'query')
        self.assertIsNone(details['errorCode'])

    def test_known_reason_is_utf8_bounded_and_marks_truncation(self):
        details = error_details(ServerFailure('Unknown column ' + '열' * 5000), secrets=SECRETS)
        self.assertLessEqual(len(details['sanitizedReason'].encode('utf-8')), 1024)
        self.assertTrue(details['truncated'])
        self.assertTrue(details['sanitizedReason'].endswith('…'))

    def test_syntax_snippet_urls_and_auth_assignments_are_removed(self):
        details = error_details(ServerFailure("syntax error near 'SELECT SECRET_ROW FROM t' at line 4; Authorization=Bearer-opaque; host=private.example; url=https://u:p@host/private", 1064))
        text = json.dumps(details)
        for value in ('SECRET_ROW', 'Bearer-opaque', 'private.example', 'https://u:p@host/private'):
            self.assertNotIn(value, text)
        self.assertEqual(details['errorCode'], '1064')
        self.assertIn('line 4', details['sanitizedReason'])

    def test_timeout_category_does_not_relabel_as_sql_or_retry(self):
        details = error_details(ServerFailure('ORA-00904: "BAD": invalid identifier'), stage='timeout')
        self.assertEqual(details['category'], 'timeout')
        self.assertNotIn('invalid identifier', details['sanitizedReason'])
        self.assertFalse(details['retryable'])

    def test_unknown_bearer_and_api_keys_are_removed_without_a_saved_secret_match(self):
        details = error_details(ServerFailure("Unknown column 'missing'; Authorization: Bearer UNREGISTERED_AUTH; api_key='UNREGISTERED_KEY'; jwt=eyJhbGci.foo.signature", 1054))
        text = json.dumps(details)
        for value in ('UNREGISTERED_AUTH', 'UNREGISTERED_KEY', 'eyJhbGci.foo.signature'):
            self.assertNotIn(value, text)
        self.assertIn('missing', details['sanitizedReason'])

    def test_approved_registration_connect_failure_does_not_claim_query_executed(self):
        from query_core import core, registration
        from query_core.store import Store, read_json
        parent = ROOT / '.smoke/query-error-details'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            store = Store(Path(folder) / 'personal')
            store.save_profile({'id': 'lake', 'name': '실습 인증', 'engine': 'datalake'}, dict(SECRETS))
            registered = registration.register_query(store, 'datalake',
                {'name': '등록 후 연결 실패 검증', 'sql': 'SELECT value FROM lake_catalog.mes.records',
                 'parameters': {}}, values={}, confirmed=True)
            self.assertEqual(registered['validationStatus'], 'approval_required')
            fake = FakeSDK(failure='constructor')
            with fake.installed(), self.assertRaises(a.AdapterError) as caught:
                core.run(store, 'datalake', registered['planId'], confirmed=True, allow_large=True)
            self.assertEqual(caught.exception.code, 'db_connect')
            self.assertEqual(fake.queries, [])
            validation = registration.validation_info(store, 'datalake', registered['id'])
            self.assertEqual(validation['validationStatus'], 'error')
            self.assertFalse(validation['queryExecuted'])
            self.assertEqual(validation['errorDetails']['stage'], 'connect')
            failed = read_json(store.root / 'results' / validation['resultId'] / 'metadata.json')
            self.assertEqual(failed['outcome'], 'error')
            self.assertFalse(failed['dataAvailable'])
            self.assertIsNone(failed['emptyResult'])
            self.assertFalse((store.root / 'results' / validation['resultId'] / 'data.jsonl').exists())
            self.safe(caught.exception)


if __name__ == '__main__':
    unittest.main()
