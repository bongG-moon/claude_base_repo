"""Oracle 연결 실패와 조회 실패의 안내를 더미 드라이버로 구분합니다."""
from contextlib import contextmanager
from pathlib import Path
import socket
import sys
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
from query_core import adapters as a


HELP = 'HyDAP(Chakra)실행 여부 및 MyAccess권한 확인 부탁드립니다'
CREDENTIALS = {'user': 'fixture_reader', 'password': 'PRIVATE-password', 'dsn': 'PRIVATE-dsn'}
REAL_IMPORT = a.importlib.import_module


class Cursor:
    description = [('VALUE',)]

    def __init__(self, failure=None, fetch_failure=None):
        self.failure = failure
        self.fetch_failure = fetch_failure

    def execute(self, statement, params=None):
        if statement.startswith('SELECT') and self.failure:
            raise self.failure

    def fetchmany(self, size):
        if self.fetch_failure:
            raise self.fetch_failure
        return []

    def close(self):
        pass


class Connection:
    def __init__(self, cursor=None):
        self.active_cursor = cursor or Cursor()

    def cursor(self):
        return self.active_cursor

    def rollback(self):
        pass

    def cancel(self):
        pass

    def close(self):
        pass


class OracleConnectionHelpTests(unittest.TestCase):
    def setUp(self):
        blocked = patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden'))
        blocked.start()
        self.addCleanup(blocked.stop)

    def driver(self, connection=None, error=None, init_error=None):
        calls = []

        def connect(**kwargs):
            calls.append(kwargs)
            if error:
                raise error
            return connection or Connection()

        def initialize(**kwargs):
            if init_error:
                raise init_error

        driver = types.SimpleNamespace(connect=connect, is_thin_mode=lambda: True,
                                       init_oracle_client=initialize)
        return driver, calls

    @contextmanager
    def installed(self, driver):
        def importer(name, *args, **kwargs):
            if name == 'oracledb':
                return driver
            return REAL_IMPORT(name, *args, **kwargs)
        with patch.object(a.importlib, 'import_module', side_effect=importer):
            yield

    def assert_safe(self, error):
        self.assertNotIn('PRIVATE', error.message)

    def test_connect_failure_has_company_guidance_once_without_credentials(self):
        driver, calls = self.driver(error=RuntimeError('PRIVATE-server-diagnostic'))
        with self.installed(driver), a.open_backend({'engine': 'oracle'}, CREDENTIALS) as backend:
            with self.assertRaises(a.AdapterError) as failed:
                with backend.execute('SELECT 1 FROM dual', {}, limit=1, timeout_seconds=60):
                    self.fail('connection must fail')
        self.assertEqual(failed.exception.code, 'db_connect')
        self.assertEqual(failed.exception.message.count(HELP), 1)
        self.assertEqual(len(calls), 1)
        self.assert_safe(failed.exception)

    def test_missing_credentials_and_driver_do_not_claim_connection_failure(self):
        for credentials, missing_driver, expected in (({}, False, 'auth_config'),
                                                       (CREDENTIALS, True, 'dependency_missing')):
            with self.subTest(expected=expected):
                def importer(name, *args):
                    if name == 'oracledb':
                        if missing_driver:
                            raise ImportError('PRIVATE')
                        raise AssertionError('driver import not needed')
                    return REAL_IMPORT(name, *args)
                with patch.object(a.importlib, 'import_module', side_effect=importer):
                    with a.open_backend({'engine': 'oracle'}, credentials) as backend:
                        with self.assertRaises(a.AdapterError) as failed:
                            backend._connect()
                self.assertEqual(failed.exception.code, expected)
                self.assertNotIn(HELP, failed.exception.message)
                self.assert_safe(failed.exception)

    def test_client_initialization_and_invalid_timeout_keep_existing_diagnostics(self):
        for profile in ({'engine': 'oracle', 'mode': 'thick'},
                        {'engine': 'oracle', 'connect_timeout': -1}):
            driver, calls = self.driver(init_error=RuntimeError('PRIVATE-client-missing'))
            with self.installed(driver), a.open_backend(profile, CREDENTIALS) as backend:
                with self.assertRaises(a.AdapterError) as failed:
                    backend._connect()
            self.assertNotIn(HELP, failed.exception.message)
            self.assertEqual(calls, [])
            self.assert_safe(failed.exception)

    def test_successful_connection_does_not_add_guidance_to_result(self):
        driver, calls = self.driver()
        with self.installed(driver), a.open_backend({'engine': 'oracle'}, CREDENTIALS) as backend:
            with backend.execute('SELECT 1 FROM dual', {}, limit=1, timeout_seconds=60) as (columns, rows):
                self.assertEqual(columns, ['VALUE'])
                self.assertEqual(list(rows), [])
        self.assertEqual(len(calls), 1)

    def test_sql_and_fetch_failures_are_not_connection_failures(self):
        for cursor, code in ((Cursor(failure=RuntimeError('PRIVATE-sql')), 'db_query'),
                             (Cursor(fetch_failure=RuntimeError('PRIVATE-fetch')), 'db_fetch')):
            with self.subTest(code=code):
                driver, calls = self.driver(connection=Connection(cursor))
                with self.installed(driver), a.open_backend({'engine': 'oracle'}, CREDENTIALS) as backend:
                    with self.assertRaises(a.AdapterError) as failed:
                        with backend.execute('SELECT 1 FROM dual', {}, limit=1, timeout_seconds=60) as (_, rows):
                            list(rows)
                self.assertEqual(failed.exception.code, code)
                self.assertNotIn(HELP, failed.exception.message)
                self.assertEqual(len(calls), 1)
                self.assert_safe(failed.exception)

    def test_query_timeout_remains_timeout_after_successful_connection(self):
        driver, calls = self.driver(connection=Connection(Cursor(failure=RuntimeError('PRIVATE-cancelled'))))

        @contextmanager
        def expired_deadline(seconds, cancel):
            event = threading.Event()
            event.set()
            yield None, event

        with self.installed(driver), patch.object(a, '_deadline', side_effect=expired_deadline):
            with a.open_backend({'engine': 'oracle'}, CREDENTIALS) as backend:
                with self.assertRaises(a.AdapterError) as failed:
                    with backend.execute('SELECT 1 FROM dual', {}, limit=1, timeout_seconds=60):
                        self.fail('query must fail')
        self.assertEqual(failed.exception.code, 'query_timeout')
        self.assertNotIn(HELP, failed.exception.message)
        self.assertEqual(len(calls), 1)
        self.assert_safe(failed.exception)


if __name__ == '__main__':
    unittest.main()
