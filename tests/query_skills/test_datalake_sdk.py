"""사내 SDK를 설치하거나 운영 접속하지 않는 LakeHouse 프로토콜 검증."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from datetime import date, datetime
from decimal import Decimal
import importlib
import io
import json
import logging
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
import pandas as pd
from query_core import adapters, core, sdk_adapter
from query_core.sql import compile_for_sdk, sdk_metadata_sql
from query_core.store import Store

SECRETS = {'user_id': 'PRIVATE_USER', 'token': 'PRIVATE_TOKEN',
           's3_access_key': 'PRIVATE_S3_ACCESS', 's3_secret_key': 'PRIVATE_S3_SECRET'}


class FakeSDK:
    def __init__(self, frame=None, failure=None, on_execute=None, close_available=True):
        self.frame = frame if frame is not None else pd.DataFrame({'value': [1, 2, 3]})
        self.failure, self.on_execute = failure, on_execute
        self.close_available = close_available
        self.constructors, self.queries = [], []
        self.closed = 0
        self.imports = []

    def constructor(self, **kwargs):
        self.constructors.append(kwargs)
        self.noise()
        if self.failure == 'constructor':
            raise RuntimeError('PRIVATE_TOKEN constructor failed')
        result = types.SimpleNamespace(execute_pd=self.execute_pd)
        if self.close_available:
            result.close = self.close
        return result

    @staticmethod
    def noise():
        print('PRIVATE_TOKEN SDK stdout')
        print('PRIVATE_S3_SECRET SDK stderr', file=sys.stderr)
        logging.getLogger('lakes').warning('PRIVATE_TOKEN pre-existing log handler')

    def execute_pd(self, *, query):
        self.queries.append(query)
        self.noise()
        if isinstance(self.failure, Exception):
            raise self.failure
        if self.on_execute:
            self.on_execute()
        match = re.search(r'LIMIT (\d+)\s*$', query)
        return self.frame.iloc[:int(match[1])] if match else self.frame

    def close(self):
        self.closed += 1
        self.noise()

    @contextmanager
    def installed(self):
        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == 'lakes.client':
                self.imports.append(name)
                self.noise()
                if self.failure == 'import':
                    raise ImportError('PRIVATE import diagnostic')
                return types.SimpleNamespace(LakeHouse=self.constructor)
            if name in ('requests', 'mysql.connector', 'oracledb'):
                raise AssertionError('unexpected transport')
            return real_import(name, *args, **kwargs)
        with patch.object(sdk_adapter.importlib, 'import_module', side_effect=fake_import), \
                patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
            yield self


class SDKSQLTests(unittest.TestCase):
    def test_scalar_literals_preserve_types_precision_quotes_and_comment_placeholders(self):
        statement = compile_for_sdk("SELECT ':ignored' x, :name n, :amount a, :day d, :stamp s FROM records WHERE id=:number -- :fake\n",
            {'name': "O'Reilly'; DROP TABLE x; --", 'amount': Decimal('123.000000000000000001'),
             'day': date(2026, 11, 2), 'stamp': datetime(2026, 11, 2, 1, 2, 3, 123456), 'number': 7})
        self.assertIn("'O''Reilly''; DROP TABLE x; --'", statement)
        self.assertIn('123.000000000000000001', statement)
        self.assertIn("CAST('2026-11-02' AS DATE)", statement)
        self.assertIn("CAST('2026-11-02 01:02:03.123456' AS DATETIME)", statement)
        self.assertIn("':ignored'", statement)
        self.assertNotIn(':fake', statement)
        self.assertIn('id = 7', statement)

    def test_list_values_repeat_safely_and_null_is_supported(self):
        sql = 'SELECT :missing x FROM t WHERE name IN (:names) OR other IN (:names)'
        statement = compile_for_sdk(sql, {'missing': None, 'names': ["A'B", 'x); DELETE FROM t;--']})
        self.assertIn('NULL', statement)
        self.assertEqual(statement.count("'A''B'"), 2)
        self.assertEqual(statement.count("'x); DELETE FROM t;--'"), 2)

    def test_backslash_control_and_unsupported_values_are_rejected_without_echo(self):
        for value in ('PRIVATE\\value', 'PRIVATE\nvalue', 'PRIVATE\x7fvalue', 'PRIVATE\x85value',
                      True, 1.5, Decimal('NaN'), datetime.fromisoformat('2026-11-02T00:00:00+09:00'), object()):
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError) as error:
                compile_for_sdk('SELECT :key', {'key': value})
            self.assertNotIn('PRIVATE', str(error.exception))
        for sql, values in [('SELECT :key', {'key': ['a']}), ('SELECT * FROM t WHERE x IN (:key, 1)', {'key': ['a']}),
                            ('SELECT :key', {}), ('SELECT :key', {'key': 1, 'other': 2})]:
            with self.assertRaises(ValueError):
                compile_for_sdk(sql, values)

    def test_readonly_guard_cannot_be_disabled_by_environment(self):
        with patch.dict(os.environ, {'LAKEHOUSE_ALLOW_WRITES': 'true', 'ALLOW_WRITES': 'true'}):
            for sql in ('DELETE FROM t', 'SELECT 1; DELETE FROM t', 'SELECT * FROM t FOR UPDATE',
                        "SELECT * FROM t INTO OUTFILE '/tmp/x'", 'SELECT SLEEP(1)', 'SET query_timeout=0'):
                with self.subTest(sql=sql), self.assertRaises(ValueError):
                    compile_for_sdk(sql, {})

    def test_metadata_has_explicit_command_shapes_and_readonly_explain(self):
        cases = [('SHOW TABLES FROM cat.db LIKE \'A%\'', 'tables'),
                 ('SHOW CREATE TABLE `cat`.`db`.`table`', 'create_table'),
                 ('DESC cat.db.table_name', 'describe'), ('DESCRIBE db.table_name', 'describe'),
                 ('EXPLAIN SELECT * FROM t WHERE id=1', 'explain')]
        for sql, kind in cases:
            with self.subTest(sql=sql):
                self.assertEqual(sdk_metadata_sql(sql)[1], kind)
        for sql in ('SHOW VARIABLES', 'SHOW GRANTS', 'SHOW CREATE USER admin', 'SET x=1',
                    'SHOW TABLES FROM db; DELETE FROM t', 'SHOW CREATE TABLE t INTO OUTFILE \'x\'',
                    'DESC t; SELECT 1', 'EXPLAIN DELETE FROM t', 'EXPLAIN ANALYZE SELECT 1',
                    'EXPLAIN SELECT SLEEP(1)', 'SHOW TABLES FROM db -- comment'):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                sdk_metadata_sql(sql)


class SDKBackendTests(unittest.TestCase):
    def backend(self, **profile):
        return sdk_adapter.LakeHouseSDKBackend({'engine': 'datalake', **profile}, SECRETS)

    @contextmanager
    def no_sdk_import(self):
        real_import = importlib.import_module
        def guarded(name, *args, **kwargs):
            if name == 'lakes.client':
                raise AssertionError('no SDK import')
            return real_import(name, *args, **kwargs)
        with patch.object(sdk_adapter.importlib, 'import_module', side_effect=guarded):
            yield

    def test_inspect_never_imports_sdk_connects_or_executes_count(self):
        with self.no_sdk_import():
            result = self.backend().inspect('SELECT * FROM records WHERE id=:key', {'key': 1})
        self.assertIsNone(result['estimated_rows'])
        self.assertIsNone(result['exact_count'])
        self.assertIn('DataFrame', ' '.join(result['notes']))

    def test_constructor_credentials_type_and_spark_contract_reuses_one_client(self):
        for environment in ('prod', 'dev'):
            fake = FakeSDK()
            with fake.installed():
                backend = self.backend(lake_type=environment, prefer_external=True)
                for _ in range(2):
                    with backend.execute('SELECT value FROM records WHERE id=:key', {'key': 1}, limit=2, timeout_seconds=None) as (columns, rows):
                        self.assertEqual(columns, ['value'])
                        self.assertEqual(list(rows), [(1,), (2,), (3,)])
                backend.close()
                backend.close()
            self.assertEqual(fake.constructors, [{**SECRETS, 'type': environment, 'spark': False}])
            self.assertEqual(len(fake.queries), 2)
            self.assertTrue(all(q.endswith('LIMIT 3') for q in fake.queries))
            self.assertEqual(fake.closed, 1)

    def test_missing_credentials_environment_and_finite_timeout_fail_before_sdk_import(self):
        for missing in SECRETS:
            with self.no_sdk_import():
                backend = sdk_adapter.LakeHouseSDKBackend({}, {k: v for k, v in SECRETS.items() if k != missing})
                with self.assertRaises(adapters.AdapterError) as error:
                    with backend.execute('SELECT 1', {}, limit=1, timeout_seconds=None):
                        pass
                self.assertEqual(error.exception.code, 'auth_config')
                with self.assertRaises(adapters.AdapterError) as inspection:
                    backend.inspect('SELECT 1', {})
                self.assertEqual(inspection.exception.code, 'auth_config')
                self.assertIn('LAKEHOUSE_S3_SECRET_KEY', str(inspection.exception))
                self.assertIn(sdk_adapter.TOKEN_PAGE, str(inspection.exception))
        for backend, timeout, code in [(self.backend(lake_type='wrong'), None, 'lakehouse_type'),
                                       (self.backend(), 60, 'sdk_timeout_unsupported')]:
            with self.no_sdk_import():
                with self.assertRaises(adapters.AdapterError) as error:
                    with backend.execute('SELECT 1', {}, limit=1, timeout_seconds=timeout):
                        pass
            self.assertEqual(error.exception.code, code)

    def test_sdk_output_and_existing_logging_handlers_are_discarded_and_state_restored(self):
        out, err, logged = io.StringIO(), io.StringIO(), io.StringIO()
        handler = logging.StreamHandler(logged)
        logger = logging.getLogger('lakes')
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        old_disable, old_env = logging.root.manager.disable, dict(os.environ)
        with FakeSDK().installed(), redirect_stdout(out), redirect_stderr(err):
            backend = self.backend()
            with backend.execute('SELECT 1', {}, limit=1, timeout_seconds=None) as (_, rows):
                list(rows)
            backend.close()
        self.assertEqual(out.getvalue() + err.getvalue() + logged.getvalue(), '')
        self.assertEqual(logging.root.manager.disable, old_disable)
        self.assertEqual(dict(os.environ), old_env)

    def test_dependency_auth_and_query_errors_are_sanitized(self):
        auth = RuntimeError('PRIVATE_TOKEN request rejected')
        auth.response = types.SimpleNamespace(status_code=401)
        forbidden = RuntimeError('403 PRIVATE_S3_SECRET')
        cases = [('import', 'dependency_missing'), ('constructor', 'db_connect'),
                 (auth, 'api_401'), (forbidden, 'api_403'), (RuntimeError('PRIVATE query text'), 'db_query')]
        for failure, code in cases:
            with self.subTest(code=code), FakeSDK(failure=failure).installed():
                backend = self.backend()
                with self.assertRaises(adapters.AdapterError) as error:
                    with backend.execute('SELECT 1', {}, limit=1, timeout_seconds=None):
                        pass
                backend.close()
            self.assertEqual(error.exception.code, code)
            self.assertNotIn('PRIVATE', str(error.exception))
            if code.startswith('api_'):
                self.assertIn(sdk_adapter.TOKEN_PAGE, str(error.exception))
            if code == 'dependency_missing':
                self.assertIn('Nexus', str(error.exception))

    def test_missing_pandas_is_dependency_error_before_query_execution(self):
        fake = FakeSDK()
        real_import = importlib.import_module
        def fake_import(name, *args, **kwargs):
            if name == 'lakes.client':
                return types.SimpleNamespace(LakeHouse=fake.constructor)
            if name == 'pandas':
                raise ImportError('PRIVATE import failure')
            return real_import(name, *args, **kwargs)
        with patch.object(sdk_adapter.importlib, 'import_module', side_effect=fake_import):
            backend = self.backend()
            with self.assertRaises(adapters.AdapterError) as error:
                with backend.execute('SELECT 1', {}, limit=1, timeout_seconds=None):
                    pass
            backend.close()
        self.assertEqual(error.exception.code, 'dependency_missing')
        self.assertEqual(fake.queries, [])
        self.assertNotIn('PRIVATE', str(error.exception))

    def test_pandas_nullable_scalars_dates_decimals_and_duplicate_columns_survive(self):
        frame = pd.DataFrame([[pd.NA, pd.NaT, float('nan'), Decimal('0.12345678901234567890'),
                               pd.Timestamp('2026-11-02T01:02:03.123456789'), 42]], columns=['x', 'x', 'n', 'd', 't', 'i'])
        with FakeSDK(frame).installed():
            backend = self.backend()
            with backend.execute('SELECT * FROM t', {}, limit=1, timeout_seconds=None) as (columns, rows):
                row = list(rows)[0]
                self.assertEqual(row[:3], (None, None, None))
                self.assertEqual(str(row[3]), '0.12345678901234567890')
                self.assertEqual(row[4].isoformat(), '2026-11-02T01:02:03.123456789')
                self.assertEqual(columns[:2], ['x', 'x'])
            backend.close()

    def test_numpy_object_datetime_preserves_nanoseconds_nat_and_rejects_duration(self):
        numpy = importlib.import_module('numpy')
        frame = pd.DataFrame({'ts': pd.Series([
            numpy.datetime64('2026-11-02T01:02:03.123456789', 'ns'),
            numpy.datetime64('NaT', 'ns'),
        ], dtype=object)})
        with FakeSDK(frame).installed():
            backend = self.backend()
            with backend.execute('SELECT ts FROM t', {}, limit=2, timeout_seconds=None) as (_, rows):
                normalized = [[core._cell(value) for value in row] for row in rows]
            backend.close()
        self.assertEqual(normalized, [['2026-11-02T01:02:03.123456789'], [None]])
        self.assertEqual(json.loads(json.dumps(normalized)), normalized)
        duration = pd.DataFrame({'elapsed': pd.Series([numpy.timedelta64(123456789, 'ns')], dtype=object)})
        with FakeSDK(duration).installed():
            backend = self.backend()
            with self.assertRaises(adapters.AdapterError) as error:
                with backend.execute('SELECT elapsed FROM t', {}, limit=1, timeout_seconds=None) as (_, rows):
                    list(rows)
            backend.close()
        self.assertEqual(error.exception.code, 'sdk_format')
        self.assertIn('기간', str(error.exception))
        self.assertNotIn('123456789', str(error.exception))

    def test_metadata_is_bounded_and_does_not_execute_rejected_commands(self):
        fake = FakeSDK(pd.DataFrame({'name': range(105)}), close_available=False)
        with fake.installed():
            backend = self.backend()
            result = backend.metadata('SHOW TABLES FROM db')
            self.assertEqual(len(result['rows']), 100)
            self.assertFalse(result['complete'])
            self.assertEqual(result['kind'], 'tables')
            with self.assertRaises(ValueError):
                backend.metadata('SHOW VARIABLES')
            self.assertEqual(len(fake.queries), 1)
            backend.close()

    def test_consumer_failure_is_preserved(self):
        with FakeSDK().installed():
            backend = self.backend()
            with self.assertRaisesRegex(ValueError, 'consumer error'):
                with backend.execute('SELECT 1', {}, limit=1, timeout_seconds=None):
                    raise ValueError('consumer error')
            backend.close()

    def test_metadata_redacts_known_secrets_and_unknown_sensitive_properties(self):
        ddl = '''CREATE TABLE t (id INT) PROPERTIES ("s3.access_key"="ANOTHER_ACCESS", 'password'='ANOTHER_PASSWORD', token='ANOTHER_TOKEN', "s3.secret_key"='escaped''SECRET', "comment"="PRIVATE_USER PRIVATE_TOKEN PRIVATE_S3_ACCESS PRIVATE_S3_SECRET", "replication_num"="3")'''
        with FakeSDK(pd.DataFrame({'DDL': [ddl]})).installed():
            backend = self.backend()
            result = backend.metadata('SHOW CREATE TABLE db.t')
            rendered = result['rows'][0][0]
            self.assertIn('"replication_num"="3"', rendered)
            self.assertNotIn('PRIVATE', rendered)
            self.assertNotIn('ANOTHER', rendered)
            self.assertNotIn('escaped', rendered)
            self.assertGreaterEqual(rendered.count('[REDACTED]'), 8)
            backend.close()


class SDKCoreIntegrationTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke' / 'sdk-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name), demo=False)
        self.store.save_profile({'id': 'lake', 'name': 'SDK fixture', 'engine': 'datalake', 'lake_type': 'prod'})
        self.store.write_secrets('lake', SECRETS)
        self.query = self.store.save_query({'name': 'SDK query', 'profile': 'lake',
            'sql': 'SELECT value FROM records WHERE value >= :minimum',
            'parameters': {'minimum': {'type': 'int'}}}, 'datalake')

    def test_single_request_has_one_sdk_query_no_count_and_50001_rows_are_partial(self):
        fake = FakeSDK(pd.DataFrame({'value': range(50001)}))
        with fake.installed():
            result = core.execute(self.store, 'datalake', self.query['id'], {'minimum': 0}, confirmed=True)
        self.assertEqual(result['savedRows'], 50000)
        self.assertEqual(result['reason'], 'row_limit')
        self.assertEqual(len(fake.queries), 1)
        self.assertEqual(len(fake.constructors), 1)
        self.assertEqual(fake.closed, 1)
        self.assertTrue(fake.queries[0].endswith('LIMIT 50001'))
        self.assertNotIn('COUNT', fake.queries[0])
        self.assertLess(len(json.dumps(result)), 1800)

    def test_more_than_20mib_and_45_seconds_complete_without_timer(self):
        clock = [1000.0]
        fake = FakeSDK(pd.DataFrame({'value': ['x' * 500000] * 50}), on_execute=lambda: clock.__setitem__(0, 1045.0))
        with fake.installed(), patch.object(core.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(adapters.threading, 'Timer', side_effect=AssertionError('no SDK timer')):
            result = core.execute(self.store, 'datalake', self.query['id'], {'minimum': 0}, confirmed=True)
        self.assertTrue(result['complete'])
        self.assertEqual(result['savedRows'], 50)
        self.assertGreater(result['dataBytes'], 20 * 1024 * 1024)
        self.assertEqual(Path(result['dataFile']).stat().st_size, result['dataBytes'])
        self.assertGreaterEqual(result['elapsedMs'], 45000)

    def test_row_expansion_still_requires_approval_before_any_sdk_query(self):
        fake = FakeSDK()
        with fake.installed():
            proposal = core.execute(self.store, 'datalake', self.query['id'], {'minimum': 0},
                                    {'max_rows': 60000}, confirmed=True)
            self.assertTrue(proposal['requiresLargeApproval'])
            self.assertEqual(fake.constructors, [])
            denied = core.run(self.store, 'datalake', proposal['planId'], confirmed=True)
            self.assertEqual(denied['status'], 'large_query_approval_required')
            result = core.run(self.store, 'datalake', proposal['planId'], confirmed=True, allow_large=True)
        self.assertTrue(result['complete'])
        self.assertEqual(len(fake.queries), 1)
        self.assertTrue(fake.queries[0].endswith('LIMIT 60001'))


if __name__ == '__main__':
    unittest.main()
