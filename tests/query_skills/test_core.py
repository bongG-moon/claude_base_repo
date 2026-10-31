"""실제 계정 없이 같은 조회 경로의 조건, 승인, 결과 파일 계약을 검증합니다."""
from contextlib import contextmanager, redirect_stdout
import datetime as dt
import decimal
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'query_skills'))
from query_core import core, cli
from query_core.store import Store, read_json
from query_core.adapters import AdapterError


class QueryFlowTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/query-core-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'demo', demo=True)
        core.demo_init(self.store)
        self.values = {'start_date':'2026-10-01','end_date':'2026-11-01','process':'WB'}

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, query_id=1, values=None, **options):
        return core.plan(self.store, 'demo', query_id, self.values if values is None else values, options)

    def run_plan(self, proposal, **flags):
        return core.run(self.store, 'demo', proposal['planId'], confirmed=True, **flags)

    def test_display_registered_db_name_and_persistence(self):
        items = self.store.queries('demo')
        self.assertEqual(items[0]['display'], '1. 생산실적조회 — 생산DB')
        self.assertEqual(items[1]['display'], '2. 생산실적조회 — 품질DB')
        reopened = Store(self.store.root, demo=True)
        core.demo_init(reopened)
        self.assertEqual(items, reopened.queries('demo'))

    def test_normal_filtered_ordering_needs_only_conditions_confirmation(self):
        proposal = self.plan()
        self.assertFalse(proposal['requiresLargeApproval'])
        self.assertEqual(proposal['exactCount'], 1)
        self.assertEqual(proposal['conditions'], self.values)
        receipt = self.run_plan(proposal)
        self.assertTrue(receipt['complete'])
        self.assertEqual(receipt['savedRows'], 1)
        self.assertEqual(list(core.load_result_rows(receipt['dataFile'])), [['2026-10-01','WB',160,'LOT006']])
        self.assertNotIn('LOT006', json.dumps(receipt))
        self.assertEqual(receipt['dataRowsReturned'], 0)

    def test_conditions_change_actual_result_and_db_choice(self):
        changed = dict(self.values, start_date='2026-09-01', end_date='2026-10-01', process='DA')
        production = self.run_plan(self.plan(values=changed))
        quality = self.run_plan(self.plan(query_id=2, values=changed))
        self.assertEqual([r[2] for r in core.load_result_rows(production['dataFile'])], [100,130])
        self.assertEqual([r[2] for r in core.load_result_rows(quality['dataFile'])], [200,260])

    def test_three_engines_use_same_demo_flow(self):
        for query_id in (1,3,4):
            with self.subTest(query_id=query_id):
                result = self.run_plan(self.plan(query_id))
                self.assertEqual(result['savedRows'], 1)
                self.assertTrue(result['demo'])

    def test_large_query_approval_and_raised_limit_succeed(self):
        initial = self.plan(5, {})
        self.assertEqual(initial['exactCount'],12005)
        self.assertTrue(initial['requiresLargeApproval'])
        self.assertEqual(self.run_plan(initial)['status'], 'large_query_approval_required')
        self.assertEqual(self.run_plan(initial,allow_large=True)['status'], 'larger_limit_required')
        self.assertFalse((self.store.root / 'results').exists())
        enlarged = self.plan(5, {}, max_rows=20000)
        self.assertEqual(self.run_plan(enlarged)['status'], 'large_query_approval_required')
        result = self.run_plan(enlarged, allow_large=True)
        self.assertTrue(result['complete'])
        self.assertEqual(result['savedRows'],12005)
        self.assertLess(len(json.dumps(result)),1800)
        with self.assertRaisesRegex(ValueError,'이미'):
            self.run_plan(enlarged,allow_large=True)

    def test_wide_date_window_can_be_approved(self):
        proposal = self.plan(values=dict(self.values,start_date='2026-01-01'))
        self.assertTrue(proposal['requiresLargeApproval'])
        self.assertTrue(self.run_plan(proposal,allow_large=True)['complete'])

    def test_confirm_missing_does_not_consume_plan(self):
        proposal = self.plan()
        with self.assertRaisesRegex(ValueError,'확인'):
            core.run(self.store,'demo',proposal['planId'])
        self.assertTrue(self.run_plan(proposal)['complete'])

    def test_expired_plan(self):
        proposal = self.plan()
        with patch('query_core.core.time.time',return_value=10**12):
            with self.assertRaisesRegex(ValueError,'15분'):
                self.run_plan(proposal)

    def test_sql_change_invalidates_old_plan(self):
        proposal = self.plan()
        query = self.store.query(1,'demo')
        for key in ('id','updated'): query.pop(key)
        query['sql'] = query['sql'].replace('quantity,', 'quantity * 2 AS quantity,')
        self.store.save_query(query,'demo',query_id=1)
        with self.assertRaisesRegex(ValueError,'바뀌'):
            self.run_plan(proposal)

    def test_connection_change_invalidates_plan(self):
        proposal = self.plan()
        with patch.object(self.store,'secrets',return_value={'token':'changed'}):
            with self.assertRaisesRegex(ValueError,'접속 정보'):
                self.run_plan(proposal)

    def test_profile_change_invalidates_plan(self):
        proposal = self.plan()
        profile = self.store.profile('production')
        profile['name'] = '새 생산DB'
        self.store.save_profile(profile,replace=True)
        with self.assertRaisesRegex(ValueError,'바뀌'):
            self.run_plan(proposal)

    def test_empty_result_is_complete(self):
        result = self.run_plan(self.plan(values=dict(self.values,process='없는 공정')))
        self.assertTrue(result['complete'])
        self.assertEqual(result['savedRows'],0)

    def test_missing_or_invalid_values_rejected_before_adapter(self):
        for values in ({},{'start_date':'not-a-date', 'end_date':'2026-11-01','process':'WB'}):
            with patch('query_core.adapters.open_backend') as backend:
                with self.assertRaises(ValueError): self.plan(values=values)
                backend.assert_not_called()

    def test_parameter_text_is_bound_not_sql(self):
        result = self.run_plan(self.plan(values=dict(self.values,process="WB' OR 1=1 --")))
        self.assertEqual(result['savedRows'],0)

    def test_decimal_filter_works_in_demo(self):
        self.store.save_query({'name':'숫자 조건','profile':'production',
            'sql':'SELECT quantity FROM production_records WHERE quantity > :minimum',
            'parameters':{'minimum':{'type':'decimal'}}},'demo')
        result = self.run_plan(self.plan(6,{'minimum':'250.50'}))
        self.assertEqual(list(core.load_result_rows(result['dataFile'])),[[300]])

    def test_partial_byte_limit_not_complete(self):
        result = self.run_plan(self.plan(max_bytes=1))
        self.assertFalse(result['complete'])
        self.assertEqual(result['reason'],'byte_limit')
        self.assertEqual(result['savedRows'],0)

    def fake_backend(self, rows, columns=('VALUE',), observation=None):
        class Backend:
            def inspect(self,*args):
                return observation or {'estimated_rows':None, 'exact_count':None, 'notes':[]}
            @contextmanager
            def execute(self,*args,**kwargs):
                yield columns, iter(rows)
        @contextmanager
        def opened(*args,**kwargs): yield Backend()
        return patch('query_core.adapters.open_backend',opened)

    def test_unknown_count_and_overflow_explicit(self):
        with self.fake_backend([(1,),(2,),(3,)]):
            proposal = self.plan(max_rows=2)
            self.assertIsNone(proposal['exactCount'])
            result = self.run_plan(proposal)
        self.assertFalse(result['complete'])
        self.assertEqual(result['reason'],'row_limit')
        self.assertEqual(result['savedRows'],2)

    def test_duplicate_columns_and_decimal_preserved(self):
        with self.fake_backend([(decimal.Decimal('1.20'),'00123',dt.date(2026,10,31))],('x','x','date')):
            result = self.run_plan(self.plan())
        self.assertEqual(list(core.load_result_rows(result['dataFile'])),[['1.20','00123','2026-10-31']])
        meta = read_json(Path(result['dataFile']).with_name('metadata.json'))
        self.assertEqual(meta['columns'],['x','x','date'])

    def test_wide_metadata_can_be_reopened_and_exported(self):
        columns = [('긴열이름'*50)+str(i) for i in range(500)]
        with self.fake_backend([tuple(range(500))],columns):
            result = self.run_plan(self.plan())
        self.assertGreater(Path(result['dataFile']).with_name('metadata.json').stat().st_size,100_000)
        self.assertTrue(core.result_info(self.store,result['resultId'])['complete'])
        self.assertTrue(core.export_csv(self.store,result['resultId'],self.root / 'wide.csv')['ok'])

    def test_failed_query_discards_incomplete_data(self):
        def rows():
            yield (1,)
            raise AdapterError('query_timeout','시간이 지났습니다.')
        with self.fake_backend(rows()):
            with self.assertRaises(AdapterError): self.run_plan(self.plan())
        self.assertEqual(list((self.store.root / 'results').rglob('data.jsonl')),[])
        meta = next((self.store.root / 'results').rglob('metadata.json'))
        self.assertEqual(read_json(meta)['status'],'failed')

    def test_csv_explicit_preserves_raw_and_special_strings(self):
        self.store.save_query({'name':'문자열','profile':'production', 'sql':'SELECT id,label,quantity FROM special_values WHERE id > 0 ORDER BY id','parameters':{}},'demo')
        result = self.run_plan(self.plan(6,{}))
        before = Path(result['dataFile']).read_bytes()
        output = self.root / '결과.csv'
        core.export_csv(self.store,result['resultId'],output)
        self.assertIn("'=1+1",output.read_text(encoding='utf-8-sig'))
        self.assertEqual(before,Path(result['dataFile']).read_bytes())
        with self.assertRaises(FileExistsError): core.export_csv(self.store,result['resultId'],output)

    def test_demo_never_opens_network_or_credentials(self):
        with patch('socket.socket',side_effect=AssertionError('network forbidden')), \
             patch('os.environ.get',side_effect=AssertionError('env forbidden')):
            self.assertEqual(self.store.secrets('production'),{})
            self.assertTrue(self.run_plan(self.plan())['complete'])

    def test_mode_and_engine_isolation(self):
        with self.assertRaises(ValueError): Store(self.store.root,demo=False)
        with self.assertRaises(ValueError): self.store.query(1,'ehub')
        proposal = self.plan()
        with self.assertRaises(ValueError): core.run(self.store,'oracle',proposal['planId'],confirmed=True)

    def test_limits_and_duplicate_db_names(self):
        for options in ({'max_rows':0},{'max_rows':True},{'timeout':1801},{'max_bytes':-1}):
            with self.assertRaises(ValueError): core.limits(options)
        with self.assertRaisesRegex(ValueError,'같은 DB 이름'):
            self.store.save_profile({'id':'another','name':'생산DB','engine':'oracle'})

    def test_secret_env_roundtrip_multiline_and_no_catalog_leak(self):
        store = Store(self.root / 'personal')
        secrets = {'user':'person','password':'pw="$# complex\\value','dsn':'(DESCRIPTION=\n (CONNECT_DATA=(SERVICE_NAME=DEMO)))'}
        profile = {'id':'db1','name':'보고서DB','engine':'oracle'}
        response = store.save_profile(profile,secrets)
        self.assertEqual(store.secrets('db1'),secrets)
        self.assertNotIn('password',json.dumps(response))
        self.assertNotIn('password',json.dumps(store.profile('db1')))
        with patch.dict(os.environ,{'DATAQUERY_DB1_PASSWORD':'override'}):
            self.assertEqual(store.secrets('db1')['password'],'override')

    def test_cli_receipt_only_and_safe_connection_error(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli.main('demo',['--state-root',str(self.store.root),'queries','list'])
        self.assertEqual(code,0)
        self.assertIn('생산DB',output.getvalue())
        with patch('query_core.cli.execute',side_effect=AdapterError('db_connect','연결을 확인해 주세요.')):
            output = io.StringIO()
            with redirect_stdout(output): code = cli.main('demo',['demo-init'])
            self.assertEqual(code,2)
            self.assertEqual(json.loads(output.getvalue())['status'],'db_connect')

    def test_long_conditions_stay_local_with_explicit_preview(self):
        query = {'name':'목록','profile':'production','sql':'SELECT lot_id FROM production_records WHERE lot_id IN (:ids)',
                 'parameters':{'ids':{'type':'list','item_type':'text'}}}
        self.store.save_query(query,'demo')
        proposal = self.plan(6,{'ids':['long-item-'+str(i).zfill(4)*10 for i in range(200)]})
        self.assertTrue(proposal['conditionsTruncated'])
        self.assertLess(len(json.dumps(proposal)),4500)
        self.assertEqual(len(read_json(proposal['conditionReviewFile'])['ids']),200)


if __name__ == '__main__':
    unittest.main()
