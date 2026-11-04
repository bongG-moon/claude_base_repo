"""Bounded Oracle row probes use a fake driver; no DB or credentials are read."""
from contextlib import contextmanager
from pathlib import Path
import socket
import sys
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
from query_core import adapters as a

REAL_IMPORT = a.importlib.import_module
SECRETS = {'user': 'fixture_reader', 'password': 'PRIVATE-password', 'dsn': 'PRIVATE-dsn'}


class Cursor:
    description = [('VALUE',)]

    def __init__(self, connection):
        self.connection = connection
        self.calls = []
        self.closed = False
        self.rows = [(1,), (2,)]

    def execute(self, statement, params=None):
        self.calls.append((statement, params))
        if statement.startswith('SET TRANSACTION'):
            if self.connection.transaction:
                raise RuntimeError('ORA-01453: SET TRANSACTION must be first statement')
            self.connection.transaction = True
        elif statement.startswith('SELECT COUNT'):
            if self.connection.delay:
                time.sleep(self.connection.delay)
            if self.connection.error:
                raise self.connection.error

    def fetchone(self):
        return self.connection.count_row

    def fetchmany(self, limit):
        rows, self.rows = self.rows[:limit], self.rows[limit:]
        return rows

    def close(self):
        self.closed = True


class Connection:
    def __init__(self, count=6438, error=None, delay=0):
        self.count_row = (count,)
        self.error, self.delay = error, delay
        self.cursors, self.rollbacks = [], 0
        self.transaction = self.cancelled = self.closed = False

    def cursor(self):
        cursor = Cursor(self)
        self.cursors.append(cursor)
        return cursor

    def rollback(self):
        self.transaction = False
        self.rollbacks += 1

    def cancel(self):
        self.cancelled = True

    def close(self):
        self.closed = True


class OracleBoundedCountTests(unittest.TestCase):
    def setUp(self):
        denied = patch.object(socket, 'create_connection', side_effect=AssertionError('live DB forbidden'))
        denied.start()
        self.addCleanup(denied.stop)

    @contextmanager
    def driver(self, connection=None, connect_error=None):
        calls = []
        def connect(**kwargs):
            calls.append(kwargs)
            if connect_error:
                raise connect_error
            return connection
        driver = types.SimpleNamespace(is_thin_mode=lambda: True, connect=connect)
        def importer(name, *args, **kwargs):
            return driver if name == 'oracledb' else REAL_IMPORT(name, *args, **kwargs)
        with patch.object(a.importlib, 'import_module', side_effect=importer):
            yield calls

    def test_small_probe_binds_cap_and_reuses_connection_for_main_query(self):
        connection = Connection()
        with self.driver(connection) as connects, a.open_backend({'engine': 'oracle'}, SECRETS) as backend:
            result = backend.count_bounded('SELECT value FROM samples WHERE fac_id=:fac ORDER BY value',
                                          {'fac': 'PRIVATE-condition'}, limit=50_000, timeout_seconds=2)
            self.assertEqual(result['count'], 6438)
            self.assertEqual(result['cap'], 50001)
            self.assertTrue(result['complete'])
            self.assertGreaterEqual(result['elapsedMs'], 0)
            cursor = connection.cursors[0]
            statement, binds = cursor.calls[1]
            self.assertTrue(statement.startswith('SELECT COUNT(*) FROM (SELECT * FROM ('))
            self.assertIn('ROWNUM <= 50001', statement)
            self.assertIn('ORDER BY', statement)
            self.assertEqual(binds, {'fac': 'PRIVATE-condition'})
            self.assertNotIn('PRIVATE', statement)
            self.assertEqual(connection.call_timeout, 2000)
            self.assertTrue(cursor.closed)
            self.assertFalse(connection.closed or connection.transaction)
            self.assertEqual(connection.rollbacks, 1)
            with backend.execute('SELECT value FROM samples WHERE fac_id=:fac', {'fac': 'PRIVATE-condition'},
                                 limit=50_000, timeout_seconds=60) as (_, rows):
                self.assertEqual(list(rows), [(1,), (2,)])
            self.assertEqual(len(connects), 1)
            self.assertEqual(connection.call_timeout, 60000)

    def test_zero_boundary_and_saturated_count_have_honest_completeness(self):
        for count in (0, 49999, 50000, 50001):
            with self.subTest(count=count):
                connection = Connection(count)
                with self.driver(connection), a.open_backend({'engine': 'oracle'}, SECRETS) as backend:
                    result = backend.count_bounded('SELECT value FROM samples', {}, limit=50000, timeout_seconds=2)
                self.assertEqual(result['count'], count)
                self.assertEqual(result['complete'], count < 50001)

    def test_invalid_probe_inputs_do_not_connect(self):
        for limit, timeout in ((50001, 2), (True, 2), (0, 2), (50000, 3), (50000, 0)):
            with self.subTest(limit=limit, timeout=timeout), self.driver(Connection()) as calls:
                backend = a.OracleBackend({'engine': 'oracle'}, SECRETS)
                with self.assertRaises(a.AdapterError):
                    backend.count_bounded('SELECT value FROM samples', {}, limit=limit, timeout_seconds=timeout)
                self.assertEqual(calls, [])

    def test_invalid_count_response_is_not_empty_or_success(self):
        for row in (None, (True,), (-1,), (50002,), (1.5,), (2, 3)):
            with self.subTest(row=row):
                connection = Connection()
                connection.count_row = row
                with self.driver(connection), a.open_backend({'engine': 'oracle'}, SECRETS) as backend:
                    with self.assertRaises(a.AdapterError) as caught:
                        backend.count_bounded('SELECT value FROM samples', {}, limit=50000, timeout_seconds=2)
                self.assertEqual(caught.exception.code, 'count_result')
                self.assertTrue(connection.cursors[0].closed)
                self.assertEqual(connection.rollbacks, 2)

    def test_timer_expiry_requests_cancel_without_main_query_or_retry(self):
        connection = Connection(delay=.04)
        with self.driver(connection) as connects, a.open_backend({'engine': 'oracle'}, SECRETS) as backend:
            with self.assertRaises(a.AdapterError) as caught:
                backend.count_bounded('SELECT value FROM samples', {}, limit=50000, timeout_seconds=.01)
            self.assertEqual(caught.exception.code, 'count_timeout')
            self.assertTrue(connection.cancelled)
            self.assertEqual(len(connects), 1)
            self.assertEqual(len(connection.cursors), 1)
            self.assertEqual(sum(sql.startswith('SELECT') for sql, _ in connection.cursors[0].calls), 1)

    def test_driver_timeout_is_distinct_from_sql_error(self):
        for text, expected in (('DPY-4024: call timeout PRIVATE-password', 'count_timeout'),
                               ('ORA-00904: invalid identifier PRIVATE-password', 'db_query')):
            with self.subTest(code=expected):
                connection = Connection(error=RuntimeError(text))
                with self.driver(connection), a.open_backend({'engine': 'oracle'}, SECRETS) as backend:
                    with self.assertRaises(a.AdapterError) as caught:
                        backend.count_bounded('SELECT value FROM samples', {}, limit=50000, timeout_seconds=2)
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn('PRIVATE', caught.exception.message)
                self.assertTrue(connection.cursors[0].closed)

    def test_auth_error_retains_company_help_and_is_not_probe_timeout(self):
        with self.driver(connect_error=RuntimeError('ORA-01017: PRIVATE-password')) as connects:
            backend = a.OracleBackend({'engine': 'oracle'}, SECRETS)
            with self.assertRaises(a.AdapterError) as caught:
                backend.count_bounded('SELECT value FROM samples', {}, limit=50000, timeout_seconds=2)
        self.assertEqual(caught.exception.code, 'db_connect')
        self.assertIn('HyDAP(Chakra)', caught.exception.message)
        self.assertNotIn('PRIVATE', caught.exception.message)
        self.assertEqual(len(connects), 1)


if __name__ == '__main__':
    unittest.main()
