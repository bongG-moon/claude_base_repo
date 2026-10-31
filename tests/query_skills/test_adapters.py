"""운영 서버에 접속하지 않는 조회 어댑터 시험."""
import importlib
import json
from pathlib import Path
import socket
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
from query_core import adapters as a


class Cursor:
    def __init__(self, rows=((1,), (2,), (3,)), fail=None, delay=0):
        self.rows = list(rows)
        self.calls = []
        self.description = [('VALUE',)]
        self.closed = False
        self.fail = fail
        self.delay = delay
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if self.delay and sql.startswith('SELECT'):
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError(self.fail)
    def fetchmany(self, n):
        result, self.rows = self.rows[:n], self.rows[n:]
        return result
    def close(self):
        self.closed = True


class Connection:
    def __init__(self, rows=((1,), (2,), (3,)), delay=0):
        self.rows = rows
        self.delay = delay
        self.cursors = []
        self.closed = False
        self.cancelled = False
        self.rollbacks = 0
    def cursor(self):
        cursor = Cursor(self.rows, delay=self.delay)
        self.cursors.append(cursor)
        return cursor
    def rollback(self):
        self.rollbacks += 1
    def cancel(self):
        self.cancelled = True
    def close(self):
        self.closed = True


class Response:
    def __init__(self, body, status=200):
        self.status_code = status
        self.payload = json.dumps(body).encode() if not isinstance(body, bytes) else body
        self.closed = False
    def iter_content(self, size):
        for i in range(0, len(self.payload), size):
            yield self.payload[i:i+size]
    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False
        self.trust_env = True
    def __enter__(self): return self
    def __exit__(self, *args): self.closed = True
    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if not self.responses:
            raise RuntimeError('PRIVATE_SERVER_ERROR')
        return self.responses.pop(0)


RUNNING = {'name': 'chosen', 'status': 'RUNNING', 'isDefault': True,
           'endpoints': {'jdbc-internal': 'internal.test:9030', 'jdbc-external': 'external.test:9031'}}
LAKE_PROFILE = {'engine': 'datalake', 'api_base': 'https://lake.test/api/v4', 'allow_cluster_start': True}
SECRETS = {'user_id': 'PRIVATE_ID', 'token': 'PRIVATE_TOKEN'}
REAL_IMPORT = importlib.import_module


def fake_module(expected, replacement):
    return lambda name, *args: replacement if name == expected else REAL_IMPORT(name, *args)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        # 실제 TCP 연결이 생기면 즉시 실패한다.
        self.socket_patch = patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden'))
        self.socket_patch.start()
        self.addCleanup(self.socket_patch.stop)

    def test_demo_condition_and_database_change_results(self):
        values = []
        for database, day in [('production', '2026-09-01'), ('production', '2026-09-02'), ('quality', '2026-09-02')]:
            with a.open_backend({'engine': 'oracle', 'demo_database': database}, {}, demo=True) as backend:
                query = 'SELECT quantity FROM production_records WHERE work_date = :day AND process = :process'
                binds = {'day': day, 'process': 'WB'}
                self.assertEqual(backend.inspect(query, binds)['exact_count'], 1)
                with backend.execute(query, binds, limit=10, timeout_seconds=5) as (columns, rows):
                    self.assertEqual(columns, ['quantity'])
                    values.append(list(rows)[0][0])
        self.assertEqual(values, [200, 300, 600])

    def test_demo_all_three_engines_and_limit_plus_one(self):
        for engine in ('oracle', 'datalake', 'ehub'):
            with a.open_backend({'engine': engine}, {}, demo=True) as backend:
                self.assertEqual(backend.inspect('SELECT id FROM large_records', {})['exact_count'], 12005)
                with backend.execute('SELECT id FROM large_records ORDER BY id', {}, limit=10000, timeout_seconds=5) as (_, rows):
                    result = list(rows)
                    self.assertEqual(len(result), 10001)
                    self.assertEqual(result[-1], (10001,))

    def test_demo_empty_and_injection_like_bound_value(self):
        with a.open_backend({'engine': 'oracle'}, {}, demo=True) as backend:
            with backend.execute('SELECT * FROM production_records WHERE process=:p',
                    {'p': "WB' OR 1=1 --"}, limit=10, timeout_seconds=5) as (_, rows):
                self.assertEqual(list(rows), [])

    def test_demo_preserves_caller_error_and_closes_cursor(self):
        with a.open_backend({'engine': 'oracle'}, {}, demo=True) as backend:
            with self.assertRaisesRegex(ValueError, 'output limit'):
                with backend.execute('SELECT * FROM production_records', {}, limit=10, timeout_seconds=5):
                    raise ValueError('output limit')
            self.assertEqual(backend.inspect('SELECT * FROM production_records', {})['exact_count'], 6)

    def test_invalid_demo_profile_and_engine_do_not_fallback(self):
        for profile in ({'engine': 'wrong'}, {'engine': 'oracle', 'demo_database': 'not-found'}):
            with self.assertRaises(a.AdapterError):
                with a.open_backend(profile, {}, demo=True): pass

    def test_oracle_inspection_is_unknown_without_connect_or_count(self):
        def inspect_import(name, *args):
            if name == 'oracledb': raise AssertionError('no driver import')
            return REAL_IMPORT(name, *args)
        with patch.object(a.importlib, 'import_module', side_effect=inspect_import):
            with a.open_backend({'engine': 'oracle'}, {}) as backend:
                result = backend.inspect('SELECT quantity FROM production_records WHERE process=:p', {'p': 'WB'})
                self.assertIsNone(result['estimated_rows'])
                self.assertIsNone(result['exact_count'])

    def test_oracle_readonly_bind_bounded_stream_and_cleanup(self):
        connection = Connection()
        calls = []
        driver = types.SimpleNamespace(is_thin_mode=lambda: True, connect=lambda **kw: (calls.append(kw) or connection))
        with patch.object(a.importlib, 'import_module', side_effect=fake_module('oracledb', driver)):
            with a.open_backend({'engine': 'oracle'}, {'user': 'u', 'password': 'PRIVATE', 'dsn': '(DESCRIPTION=...)'}) as backend:
                with backend.execute('SELECT value FROM source WHERE key=:k', {'k': '001'}, limit=2, timeout_seconds=5) as (columns, rows):
                    self.assertEqual(columns, ['VALUE'])
                    self.assertEqual(list(rows), [(1,), (2,), (3,)])
        cursor = connection.cursors[0]
        self.assertEqual(cursor.calls[0][0], 'SET TRANSACTION READ ONLY')
        self.assertEqual(cursor.calls[1][1], {'k': '001'})
        self.assertNotIn('001', cursor.calls[1][0])
        self.assertIn('3', cursor.calls[1][0])
        self.assertTrue(connection.closed and cursor.closed)
        self.assertGreaterEqual(connection.rollbacks, 1)
        self.assertFalse(connection.autocommit)
        self.assertEqual(calls[0]['dsn'], '(DESCRIPTION=...)')
        self.assertIs(cursor.outputtypehandler,a._oracle_number_handler)

    def test_oracle_number_fetch_uses_decimal_without_float_roundtrip(self):
        number = object()
        driver = types.SimpleNamespace(DB_TYPE_NUMBER=number)
        calls = []
        cursor = types.SimpleNamespace(arraysize=500,var=lambda kind, **kw: (calls.append((kind,kw)) or kind))
        with patch.object(a.importlib,'import_module',side_effect=fake_module('oracledb',driver)):
            kind = a._oracle_number_handler(cursor,types.SimpleNamespace(type_code=number))
            value = kind('0.12345678901234567890123456789012345678')
            self.assertEqual(str(value),'0.12345678901234567890123456789012345678')
            self.assertEqual(calls,[(Decimal,{'arraysize':500})])
            self.assertIsNone(a._oracle_number_handler(cursor,types.SimpleNamespace(type_code=object())))

    def test_oracle_total_deadline_requests_cancel(self):
        connection = Connection(delay=.05)
        driver = types.SimpleNamespace(is_thin_mode=lambda: True, connect=lambda **kw: connection)
        with patch.object(a.importlib, 'import_module', side_effect=fake_module('oracledb', driver)):
            with a.open_backend({'engine': 'oracle'}, {'user': 'u', 'password': 'p', 'dsn': 'd'}) as backend:
                with self.assertRaises(a.AdapterError) as caught:
                    with backend.execute('SELECT value FROM source', {}, limit=2, timeout_seconds=.01) as (_, rows):
                        list(rows)
        self.assertEqual(caught.exception.code, 'query_timeout')
        self.assertTrue(connection.cancelled)

    def test_oracle_connection_failure_is_safe_and_never_demo(self):
        def failed(**kwargs): raise RuntimeError('PRIVATE_TOKEN PASSWORD HOST')
        driver = types.SimpleNamespace(is_thin_mode=lambda: True, connect=failed)
        with patch.object(a.importlib, 'import_module', side_effect=fake_module('oracledb', driver)):
            with a.open_backend({'engine': 'oracle'}, {'user': 'u', 'password': 'p', 'dsn': 'd'}) as backend:
                with self.assertRaises(a.AdapterError) as caught:
                    with backend.execute('SELECT 1 FROM dual', {}, limit=1, timeout_seconds=1): pass
        self.assertEqual(caught.exception.code, 'db_connect')
        self.assertNotIn('PRIVATE', str(caught.exception))

    def test_lake_requires_start_consent_and_http_setting(self):
        for profile, code in [({'engine': 'datalake'}, 'cluster_start_confirmation_required'),
                ({**LAKE_PROFILE, 'api_base': 'http://lake.test/api'}, 'http_confirmation_required')]:
            with self.assertRaises(a.AdapterError) as caught:
                a.LakeBackend(profile, SECRETS)._prepare_cluster()
            self.assertEqual(caught.exception.code, code)

    def test_lake_cluster_shape_endpoints_and_request_contract(self):
        response = Response({'content': [RUNNING]})
        session = Session([response])
        with patch.object(a.importlib, 'import_module', return_value=types.SimpleNamespace(Session=lambda: session)):
            endpoints = a.LakeBackend(LAKE_PROFILE, SECRETS)._prepare_cluster()
        self.assertEqual(endpoints, [('internal.test', 9030), ('external.test', 9031)])
        args, options = session.calls[0]
        self.assertTrue(args[0].endswith('/runtime/cluster/starrocks/running'))
        self.assertEqual(options['params'], {'name': 'None'})
        self.assertEqual(options['headers']['Authorization'], 'Bearer PRIVATE_TOKEN')
        self.assertFalse(options['allow_redirects'])
        self.assertTrue(options['verify'])
        self.assertFalse(session.trust_env)
        self.assertTrue(response.closed and session.closed)

    def test_lake_auth_invalid_json_redirect_and_large_body(self):
        cases = [(Response({}, 401), 'api_401'), (Response({}, 403), 'api_403'),
                 (Response({}, 302), 'api_response'), (Response(b'not-json'), 'api_format'),
                 (Response(b'x' * 1_048_577), 'api_limit')]
        for response, code in cases:
            session = Session([response])
            with patch.object(a.importlib, 'import_module', return_value=types.SimpleNamespace(Session=lambda: session)):
                with self.assertRaises(a.AdapterError) as caught:
                    a.LakeBackend(LAKE_PROFILE, SECRETS)._prepare_cluster()
            self.assertEqual(caught.exception.code, code)
            self.assertTrue(response.closed)

    def test_lake_multiple_clusters_require_exact_name(self):
        first = {**RUNNING, 'name': 'one'}
        second = {**RUNNING, 'name': 'two'}
        for name, expected in [('', 'cluster_ambiguous'), ('two', None)]:
            session = Session([Response({'content': [first, second]})])
            with patch.object(a.importlib, 'import_module', return_value=types.SimpleNamespace(Session=lambda: session)):
                backend = a.LakeBackend({**LAKE_PROFILE, 'cluster': name}, SECRETS)
                if expected:
                    with self.assertRaises(a.AdapterError) as caught: backend._prepare_cluster()
                    self.assertEqual(caught.exception.code, expected)
                else:
                    self.assertEqual(len(backend._prepare_cluster()), 2)

    def test_lake_pending_cluster_respects_prepare_timeout(self):
        response = Response({**RUNNING, 'status': 'STARTING'})
        session = Session([response])
        with patch.object(a.importlib, 'import_module', return_value=types.SimpleNamespace(Session=lambda: session)):
            with self.assertRaises(a.AdapterError) as caught:
                a.LakeBackend({**LAKE_PROFILE, 'prepare_timeout': .02}, SECRETS)._prepare_cluster()
        self.assertEqual(caught.exception.code, 'cluster_timeout')

    def test_lake_tls_and_internal_external_fallback(self):
        connection, calls = Connection(), []
        def connect(**kw):
            calls.append(kw)
            if len(calls) == 1: raise RuntimeError('PRIVATE_ERROR')
            return connection
        with patch.object(a.importlib, 'import_module', return_value=types.SimpleNamespace(connect=connect)):
            with patch.object(a.LakeBackend, '_prepare_cluster', return_value=[('internal.test', 9030), ('external.test', 9031)]):
                backend = a.LakeBackend({**LAKE_PROFILE, 'tls_ca': 'approved-ca.pem'}, SECRETS)
                self.assertIs(backend._connect(), connection)
                backend.close()
        self.assertEqual(len(calls), 2)
        for options in calls:
            self.assertFalse(options['allow_local_infile'])
            self.assertFalse(options['ssl_disabled'])
            self.assertTrue(options['ssl_verify_cert'] and options['ssl_verify_identity'])
            self.assertEqual(options['ssl_ca'], 'approved-ca.pem')
        self.assertEqual(connection.cursors[0].calls[0][0], "SET CATALOG = 'lake_catalog'")
        self.assertTrue(connection.closed)

    def test_lake_execute_binds_and_limit_and_caller_errors(self):
        connection = Connection()
        backend = a.LakeBackend(LAKE_PROFILE, SECRETS)
        backend.connection = connection
        with backend.execute('SELECT value FROM source WHERE name=:name', {'name': 'PRIVATE_VALUE'}, limit=2, timeout_seconds=5) as (_, rows):
            self.assertEqual(len(list(rows)), 3)
        calls = connection.cursors[0].calls
        self.assertEqual(calls[0][0], 'SET query_timeout = 5')
        self.assertIn('%(name)s', calls[1][0])
        self.assertNotIn('PRIVATE_VALUE', calls[1][0])
        self.assertEqual(calls[1][1], {'name': 'PRIVATE_VALUE'})
        with self.assertRaisesRegex(ValueError, 'output limit'):
            with backend.execute('SELECT 1', {}, limit=1, timeout_seconds=1):
                raise ValueError('output limit')

    def test_lake_plan_never_count_or_analyze_and_no_plan_text_returned(self):
        connection = Connection(rows=[('cardinality: 9000 PRIVATE_TABLE PRIVATE_LITERAL',)])
        backend = a.LakeBackend(LAKE_PROFILE, SECRETS)
        backend.connection = connection
        result = backend.inspect('SELECT * FROM source WHERE name=:name', {'name': 'PRIVATE_VALUE'})
        self.assertEqual(result['plan_max_rows'], 9000)
        self.assertIsNone(result['estimated_rows'])
        self.assertIsNone(result['exact_count'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        statement = connection.cursors[0].calls[1][0]
        self.assertTrue(statement.startswith('EXPLAIN COSTS '))
        self.assertNotIn('ANALYZE', statement)

    def test_endpoints_are_validated_and_ipv6_supported(self):
        self.assertEqual(a._endpoint('[::1]:9030'), ('::1', 9030))
        for value in ('host', 'http://host:9030', 'user@host:9030', 'host:0', 'host:99999', 'host:abc', 'host:9030/path'):
            with self.assertRaises(a.AdapterError): a._endpoint(value)

    def test_plan_scientific_notation_is_not_understated(self):
        backend = a.LakeBackend(LAKE_PROFILE, SECRETS)
        backend.connection = Connection(rows=[('cardinality: 1.2e+07',), ('cardinality: -1',)])
        self.assertEqual(backend.inspect('SELECT * FROM source', {})['plan_max_rows'], 12000000)

    def test_fetch_failure_is_sanitized(self):
        cursor = Cursor()
        cursor.fetchmany = lambda n: (_ for _ in ()).throw(RuntimeError('PRIVATE_SECRET'))
        with self.assertRaises(a.AdapterError) as caught:
            list(a._rows(cursor, 3, time.monotonic() + 3, threading.Event()))
        self.assertEqual(caught.exception.code, 'db_fetch')
        self.assertNotIn('PRIVATE', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
