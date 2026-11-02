"""Lake/E-HUB workflows through real adapters with local fake transport only."""
from contextlib import ExitStack
import importlib
import itertools
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
sys.path.insert(0, str(Path(__file__).parent))
from query_core import adapters, cli, core, results
from query_core.store import Store, atomic_json, read_json
from test_datalake_sdk import FakeSDK, pd


class FakeLakeTransport:
    """Exercises LakeBackend HTTP/SQL code; no network or live driver is used."""
    def __init__(self, *, row_count=2, cardinality=2, value=None, on_explain=None):
        self.row_count, self.cardinality, self.value = row_count, cardinality, value
        self.on_explain = on_explain
        self.http_calls, self.connect_calls, self.sql_calls, self.connections = [], [], [], []

    def __enter__(self):
        self.stack = ExitStack()
        real_import = importlib.import_module
        transport = self
        class Response:
            status_code = 200
            def iter_content(self, size):
                yield json.dumps({'content':[{'name':'fixture-cluster', 'status':'RUNNING', 'isDefault':True,
                                             'endpoints':{'jdbc-internal':'fixture.invalid:9030'}}]}).encode()
            def close(self): pass
        class Session:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def get(self, url, **kwargs):
                transport.http_calls.append((url, kwargs))
                return Response()
        def connect(**kwargs):
            transport.connect_calls.append(kwargs)
            connection = FakeLakeConnection(transport)
            transport.connections.append(connection)
            return connection
        def imported(name, *args, **kwargs):
            if name == 'requests': return types.SimpleNamespace(Session=Session)
            if name == 'mysql.connector': return types.SimpleNamespace(connect=connect)
            if name == 'oracledb': raise AssertionError('Oracle driver is outside these synthetic Lake cases')
            return real_import(name, *args, **kwargs)
        self.stack.enter_context(patch.object(adapters.importlib, 'import_module', side_effect=imported))
        self.stack.enter_context(patch.object(socket, 'socket', side_effect=AssertionError('live network forbidden')))
        self.stack.enter_context(patch.object(socket, 'create_connection', side_effect=AssertionError('live network forbidden')))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def selects(self):
        return [entry for entry in self.sql_calls if entry[0].startswith('SELECT')]

    def explains(self):
        return [entry for entry in self.sql_calls if entry[0].startswith('EXPLAIN COSTS')]


class FakeLakeConnection:
    def __init__(self, transport):
        self.transport, self.closed, self.cursors = transport, False, []
    def cursor(self):
        cursor = FakeLakeCursor(self.transport)
        self.cursors.append(cursor)
        return cursor
    def close(self): self.closed = True


class FakeLakeCursor:
    def __init__(self, transport):
        self.transport, self.closed = transport, False
        self.rows = iter(())
        self.description = [('VALUE',)]
    def execute(self, sql, params=None):
        self.transport.sql_calls.append((sql, params))
        if sql.startswith('EXPLAIN COSTS'):
            self.rows = iter([(f'cardinality: {self.transport.cardinality} PRIVATE_PLAN_TEXT',)])
            if self.transport.on_explain:
                callback, self.transport.on_explain = self.transport.on_explain, None
                callback()
        elif sql.startswith('SELECT'):
            limits = re.findall(r'\bLIMIT\s+(\d+)', sql, re.I)
            count = min(self.transport.row_count, int(limits[-1])) if limits else self.transport.row_count
            self.rows = ((self.transport.value if self.transport.value is not None else i,) for i in range(count))
    def fetchmany(self, count): return list(itertools.islice(self.rows, count))
    def close(self): self.closed = True


class LakeWorkflowTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/lake-workflow-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'personal')
        self.ids = {}
        for engine in ('datalake', 'ehub'):
            secrets = {'user_id':'SYNTHETIC_USER', 'token':'SYNTHETIC_TOKEN_' + engine}
            if engine == 'datalake':
                secrets.update(s3_access_key='SYNTHETIC_ACCESS', s3_secret_key='SYNTHETIC_SECRET')
            self.store.save_profile({'id':engine, 'name':'가상 ' + engine, 'engine':engine,
                                     'api_base':'https://fixture.invalid/api/v4', 'cluster':'fixture-cluster',
                                     'allow_cluster_start':True},
                                    secrets)
            query = self.store.save_query({'name':'같은 조회', 'profile':engine,
                'sql':'SELECT sample_id FROM samples WHERE sample_id >= :minimum ORDER BY sample_id',
                'parameters':{'minimum':{'type':'integer'}}}, engine)
            self.ids[engine] = query['id']
        self.values = {'minimum':1}

    def execute(self, engine, **kwargs):
        return core.execute(self.store, engine, self.ids[engine], self.values, confirmed=True, **kwargs)

    def transport(self, engine, *, row_count=2, value=None):
        if engine == 'datalake':
            frame = pd.DataFrame({'sample_id': range(row_count) if value is None else [value] * row_count})
            return FakeSDK(frame).installed()
        return FakeLakeTransport(row_count=row_count, value=value)

    @staticmethod
    def query_count(transport):
        return len(transport.queries) if isinstance(transport, FakeSDK) else len(transport.selects())

    def old(self, response, *, legacy=False):
        folder = Path(response['dataFile']).parent
        metadata = read_json(folder / 'metadata.json')
        stamp = time.time() - 25*3600
        if legacy:
            metadata.pop('engine')
            metadata.pop('createdAt')
            metadata.pop('dataSha256')
            os.utime(folder / 'data.jsonl', (stamp-1, stamp-1))
        else:
            metadata['createdAt'] = stamp
        atomic_json(folder / 'metadata.json', metadata)
        if legacy:
            os.utime(folder / 'metadata.json', (stamp, stamp))
        return folder

    def test_all_live_defaults_are_50000_but_demo_remains_10000(self):
        for engine in ('oracle', 'datalake', 'ehub'):
            expected = {'max_rows':50000, 'max_bytes':None, 'timeout':None} if engine == 'datalake' else {'max_rows':50000, 'max_bytes':20*1024*1024, 'timeout':60}
            self.assertEqual(core.default_limits(engine), expected)
        self.assertEqual(core.default_limits('demo')['max_rows'], 10000)

    def test_ehub_execute_reuses_one_cluster_request_and_connection(self):
        for engine in ('ehub',):
            with self.subTest(engine=engine), FakeLakeTransport(row_count=50000, cardinality=50000) as transport:
                response = self.execute(engine)
                self.assertTrue(response['complete'])
                self.assertEqual(response['savedRows'], 50000)
                self.assertLess(len(json.dumps(response)), 1800)
                self.assertEqual(len(transport.http_calls), 1)
                self.assertEqual(len(transport.connect_calls), 1)
                self.assertEqual(len(transport.explains()), 1)
                self.assertEqual(len(transport.selects()), 1)
                self.assertTrue(all(c.closed for c in transport.connections))
                self.assertTrue(all(cursor.closed for c in transport.connections for cursor in c.cursors))
                self.assertNotIn('COUNT(', ' '.join(sql for sql, _ in transport.sql_calls).upper())
                self.assertNotIn('PRIVATE_PLAN_TEXT', json.dumps(response))
                sql, binds = transport.selects()[0]
                self.assertIn('50001', sql)
                self.assertEqual(binds, self.values)
                self.assertIn(('SET query_timeout = 60', None), transport.sql_calls)

    def test_explicit_plan_then_run_closes_for_user_wait_and_does_not_reinspect(self):
        for engine in ('ehub',):
            with self.subTest(engine=engine), FakeLakeTransport() as transport:
                plan = core.plan(self.store, engine, self.ids[engine], self.values)
                self.assertFalse(plan['requiresLargeApproval'])
                self.assertEqual(plan['limits']['max_rows'], 50000)
                self.assertTrue(transport.connections[0].closed)
                self.assertEqual(len(transport.selects()), 0)
                response = core.run(self.store, engine, plan['planId'], confirmed=True)
                self.assertTrue(response['complete'])
                self.assertEqual(len(transport.http_calls), 2)
                self.assertEqual(len(transport.connect_calls), 2)
                self.assertEqual(len(transport.explains()), 1)
                self.assertEqual(len(transport.selects()), 1)

    def test_50001_overflow_is_partial_and_expansion_requires_large_approval(self):
        for engine in ('datalake', 'ehub'):
            with self.subTest(engine=engine), self.transport(engine, row_count=50001) as transport:
                response = self.execute(engine)
                self.assertEqual((response['savedRows'], response['reason'], response['complete']), (50000, 'row_limit', False))
                proposal = core.plan(self.store, engine, self.ids[engine], self.values, {'max_rows':60000})
                self.assertTrue(proposal['requiresLargeApproval'])
                before = self.query_count(transport)
                self.assertEqual(core.run(self.store, engine, proposal['planId'], confirmed=True)['status'], 'large_query_approval_required')
                self.assertEqual(before, self.query_count(transport))
                approved = core.run(self.store, engine, proposal['planId'], confirmed=True, allow_large=True)
                self.assertEqual(approved['savedRows'], 50001)
                self.assertTrue(approved['complete'])

    def test_default_byte_policy_is_unbounded_only_for_datalake_and_receipts_stay_small(self):
        for engine in ('datalake', 'ehub'):
            with self.subTest(engine=engine), self.transport(engine, row_count=50, value='x'*500000):
                response = self.execute(engine)
                if engine == 'datalake':
                    self.assertTrue(response['complete'])
                    self.assertEqual(response['savedRows'], 50)
                    self.assertGreater(response['dataBytes'], 20*1024*1024)
                else:
                    self.assertEqual(response['reason'], 'byte_limit')
                    self.assertFalse(response['complete'])
                    self.assertLessEqual(response['dataBytes'], 20*1024*1024)
                    self.assertGreater(response['dataBytes'], 19*1024*1024)
                self.assertLess(len(json.dumps(response)), 1800)
                metadata = read_json(Path(response['dataFile']).with_name('metadata.json'))
                self.assertEqual(metadata['limits'], core.default_limits(engine))

    def test_large_plan_closes_connection_and_runs_only_after_separate_confirmation(self):
        for engine in ('ehub',):
            with self.subTest(engine=engine), FakeLakeTransport(cardinality=50001) as transport:
                response = self.execute(engine)
                self.assertEqual(response['status'], 'confirmation_required')
                self.assertTrue(response['requiresLargeApproval'])
                self.assertFalse(response['executed'])
                self.assertEqual(len(transport.selects()), 0)
                self.assertEqual(len(transport.connect_calls), 1)
                self.assertTrue(transport.connections[0].closed)
                self.assertEqual(core.run(self.store, engine, response['planId'], confirmed=True)['status'], 'large_query_approval_required')
                self.assertEqual(len(transport.connect_calls), 1)
                approved = core.run(self.store, engine, response['planId'], confirmed=True, allow_large=True)
                self.assertTrue(approved['complete'])
                self.assertEqual(len(transport.connect_calls), 2)
                self.assertEqual(len(transport.explains()), 1)

    def test_changed_token_or_profile_invalidates_prepared_plan_without_select(self):
        for engine in ('datalake', 'ehub'):
            for changed in ('token', 'profile'):
                with self.subTest(engine=engine, changed=changed), self.transport(engine) as transport:
                    proposal = core.plan(self.store, engine, self.ids[engine], self.values)
                    if changed == 'token':
                        secrets = self.store.secrets(engine)
                        secrets['token'] = 'CHANGED_' + engine
                        self.store.write_secrets(engine, secrets)
                    else:
                        profile = self.store.profile(engine)
                        if engine == 'datalake':
                            profile['lake_type'] = 'dev'
                        else:
                            profile['api_base'] += '/changed'
                        self.store.save_profile(profile, replace=True)
                    with self.assertRaises(ValueError):
                        core.run(self.store, engine, proposal['planId'], confirmed=True)
                    self.assertEqual(self.query_count(transport), 0)
                    if engine == 'datalake':
                        self.assertEqual(transport.constructors, [])
                    else:
                        self.assertEqual(len(transport.connect_calls), 1)

    def test_token_change_during_inspection_cannot_reuse_stale_authenticated_connection(self):
        for engine in ('ehub',):
            callback = lambda: self.store.write_secrets(engine, {'user_id':'SYNTHETIC_USER', 'token':'REPLACED_' + engine})
            with self.subTest(engine=engine), FakeLakeTransport(on_explain=callback) as transport:
                with self.assertRaises(ValueError):
                    self.execute(engine)
                self.assertEqual(len(transport.selects()), 0)
                self.assertTrue(transport.connections[0].closed)

    def test_startup_cleanup_and_legacy_used_plan_mapping_are_engine_isolated(self):
        receipts, folders = {}, {}
        for engine in ('datalake', 'ehub'):
            with self.transport(engine):
                receipts[engine] = self.execute(engine)
            folders[engine] = self.old(receipts[engine], legacy=True)
        catalog = self.store.db.read_bytes()
        secrets_before = {p.name:p.read_bytes() for p in (self.store.root / 'connections').iterdir()}
        for engine in ('datalake', 'ehub'):
            with patch.object(socket, 'socket', side_effect=AssertionError('startup must be offline')):
                startup = cli.startup(self.store, engine)
            self.assertEqual(startup['profileCount'], 1)
            self.assertEqual(startup['queryCount'], 1)
            self.assertFalse(startup['connected'])
            self.assertEqual(startup['previousResults']['count'], 1)
            self.assertEqual(startup['cleanup']['resultIds'], [receipts[engine]['resultId']])
            self.assertTrue(startup['previousResults']['results'][0]['timeApproximate'])
            other = 'ehub' if engine == 'datalake' else 'datalake'
            with self.assertRaises(ValueError):
                results.delete_cleanup(self.store, other, startup['cleanup']['planId'], confirmed=True)
            self.assertTrue(folders[engine].exists())
            report = results.delete_cleanup(self.store, engine, startup['cleanup']['planId'], confirmed=True)
            self.assertEqual(report['deletedIds'], [receipts[engine]['resultId']])
            self.assertFalse(folders[engine].exists())
        self.assertEqual(catalog, self.store.db.read_bytes())
        self.assertEqual(secrets_before, {p.name:p.read_bytes() for p in (self.store.root / 'connections').iterdir()})

    def test_repeated_queries_preserve_ids_conditions_and_previous_file_bytes(self):
        for engine in ('datalake', 'ehub'):
            with self.subTest(engine=engine), self.transport(engine):
                first = self.execute(engine)
                original = {p.name:p.read_bytes() for p in Path(first['dataFile']).parent.iterdir()}
                second = self.execute(engine)
                self.assertNotEqual(first['resultId'], second['resultId'])
                self.assertNotEqual(first['label'], second['label'])
                self.assertEqual(original, {p.name:p.read_bytes() for p in Path(first['dataFile']).parent.iterdir()})
                for receipt in (first, second):
                    metadata = read_json(Path(receipt['dataFile']).with_name('metadata.json'))
                    self.assertEqual(metadata['dbId'], engine)
                    self.assertEqual(metadata['queryId'], self.ids[engine])
                    self.assertEqual(metadata['engine'], engine)
                    self.assertEqual(metadata['params'], self.values)
                    self.assertTrue(metadata['executedAt'])
                    self.assertEqual(metadata['limits']['max_rows'], 50000)
                    self.assertEqual(receipt['dataRowsReturned'], 0)
                    self.assertNotIn('SYNTHETIC_TOKEN', json.dumps(receipt))

    def test_unconfirmed_execute_does_not_open_adapter(self):
        for engine in ('datalake', 'ehub'):
            with self.subTest(engine=engine), self.transport(engine) as transport:
                with self.assertRaises(ValueError):
                    core.execute(self.store, engine, self.ids[engine], self.values)
                if engine == 'datalake':
                    self.assertEqual(transport.queries, [])
                    self.assertEqual(transport.constructors, [])
                else:
                    self.assertEqual(transport.http_calls, [])
                    self.assertEqual(transport.connect_calls, [])


if __name__ == '__main__':
    unittest.main()
