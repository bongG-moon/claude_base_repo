"""Beginner query flow with real CLI parsing and isolated dummy databases."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
from query_core import cli, core
from query_core.inputs import read_cli_params, InputError
from query_core.registration import parameter_review
from query_core.store import Store


class EasyQueryTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT / '.smoke/query-easy-tests'; folder.mkdir(parents=True, exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=folder); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=Store(self.root/'state',demo=True); core.demo_init(self.store)
        self.spec={'name':'고정 조건', 'profile':'production',
                   'sql':"SELECT * FROM production_records WHERE process='WB'",'parameters':{}}
        self.spec_file=self.root/'register.json'
        self.spec_file.write_text(json.dumps(self.spec),encoding='utf-8')

    def call(self,*args):
        output=io.StringIO()
        with redirect_stdout(output):
            code=cli.main('demo',['--state-root',str(self.store.root),*map(str,args)])
        return code,json.loads(output.getvalue())

    def test_literal_candidate_defers_registration_and_db_access(self):
        before=self.store.queries('demo')
        with patch('query_core.adapters.open_backend') as connect:
            code,result=self.call('queries','register','--spec',self.spec_file)
        self.assertEqual(code,0); self.assertEqual(result['status'],'parameter_review_required')
        self.assertEqual(result['candidates'][0]['column'],'process')
        self.assertEqual(result['candidates'][0]['currentValues'],['WB'])
        self.assertEqual(before,self.store.queries('demo')); connect.assert_not_called()

    def test_explicit_keep_fixed_registers_and_tests_once(self):
        code,result=self.call('queries','register','--spec',self.spec_file,'--parameters-reviewed')
        self.assertEqual(code,0); self.assertTrue(result['registered'])
        self.assertEqual(result['validationStatus'],'success_with_rows')
        self.assertIn("process = 'WB'",self.store.query(result['id'],'demo')['sql'])
        self.assertEqual(self.store.query(result['id'],'demo')['parameters'],{})

    def test_already_parameterized_spec_has_no_extra_choice(self):
        spec=dict(self.spec,sql='SELECT * FROM production_records WHERE process=:process',parameters={'process':'text'})
        self.spec_file.write_text(json.dumps(spec),encoding='utf-8')
        code,result=self.call('queries','register','--spec',self.spec_file,'--param','process=WB')
        self.assertEqual(code,0); self.assertEqual(result['validationStatus'],'success_with_rows')

    def test_select_literals_and_join_columns_are_not_condition_candidates(self):
        for sql in ("SELECT 'sample' AS label FROM dual", 'SELECT a.id FROM t a JOIN t b ON a.id=b.id WHERE a.id=:id'):
            result=parameter_review(self.store,'demo',dict(self.spec,sql=sql))
            self.assertEqual(result['candidates'],[])

    def test_multiple_conditions_one_review_and_no_mass_parameterization(self):
        result=parameter_review(self.store,'demo',dict(self.spec,sql="SELECT quantity*100 FROM production_records WHERE process='WB' AND quantity BETWEEN 1 AND 100"))
        self.assertEqual(result['candidateCount'],2)
        self.assertEqual({c['column'] for c in result['candidates']},{'process','quantity'})

    def test_date_function_formats_are_never_parameter_values(self):
        cases = [
            ("trunc(event_date,'DD') = DATE '2026-11-03'", ['2026-11-03']),
            ("event_date >= to_date('20261103','YYYYMMDD')", ['20261103']),
            ("to_char(event_date, 'YYYYMMDD') = '20261103'", ['20261103']),
            ("DATE '2026-11-03' <= trunc(event_date,'DD')", ['2026-11-03']),
            ("event_date BETWEEN to_date('20261101','YYYYMMDD') AND to_date('20261103','YYYYMMDD')", ['20261101','20261103']),
            ("trunc(event_date,'DD') = :day", []),
            ("year = 2026 + 1", []),
            ("quantity = -1", ['-1']),
        ]
        for predicate, expected in cases:
            with self.subTest(predicate=predicate):
                result=parameter_review(self.store,'demo',dict(self.spec,sql='SELECT * FROM t WHERE '+predicate))
                values=[value for candidate in result['candidates'] for value in candidate['currentValues']]
                self.assertEqual(values,expected)

    def test_pair_values_preserve_identifiers_spaces_case_and_equals(self):
        self.assertEqual(read_cli_params(pairs=['code=00123','fac_id=CjPkg','name=WB TEST','value=a=b']),
                         {'code':'00123','fac_id':'CjPkg','name':'WB TEST','value':'a=b'})
        for values in (['code=A','code=B'],['wrong'],['=bad']):
            with self.assertRaises(InputError): read_cli_params(pairs=values)
        with self.assertRaises(InputError): read_cli_params('{}',['code=A'])

    def test_query_and_csv_in_one_call_no_prompt_or_payload(self):
        args=('execute','--id',1,'--param','start_date=2026-10-01','--param','end_date=2026-11-01','--param','process=WB','--output-dir',self.root/'outputs')
        with patch('query_core.results.list_candidates') as cleanup:
            code,a=self.call(*args); code2,b=self.call(*args)
        self.assertEqual((code,code2),(0,0)); cleanup.assert_not_called()
        self.assertNotEqual(a['resultId'],b['resultId']); self.assertNotEqual(a['outputFile'],b['outputFile'])
        self.assertEqual([x.suffix for x in (self.root/'outputs').iterdir()],['.csv','.csv'])
        self.assertNotIn('rows',a); self.assertEqual(a['dataRowsReturned'],0)
        self.assertFalse((self.root/'_work').exists())

    def test_export_failure_keeps_query_result_and_does_not_retry(self):
        with patch('query_core.core.export_csv',side_effect=OSError('fixture')):
            code,result=self.call('execute','--id',1,'--param','start_date=2026-10-01','--param','end_date=2026-11-01','--param','process=WB','--output-dir',self.root/'outputs')
        self.assertEqual(code,0); self.assertEqual(result['exportStatus'],'failed')
        self.assertTrue(Path(result['dataFile']).exists()); self.assertEqual(result['savedRows'],1)

    def test_large_request_still_waits_without_confirm_flag(self):
        code,result=self.call('execute','--id',5,'--max-rows',20000)
        self.assertEqual(code,0); self.assertFalse(result['executed']); self.assertTrue(result['requiresLargeApproval'])
        self.assertFalse((self.store.root/'results').exists())
        code, completed=self.call('run','--plan',result['planId'],'--confirm','--allow-large',
                                  '--output-dir',self.root/'outputs')
        self.assertEqual(code,0); self.assertTrue(completed['complete'])
        self.assertEqual(completed['savedRows'],12005)
        self.assertTrue(Path(completed['outputFile']).is_file())

    def test_invalid_pairs_fail_before_connect(self):
        with patch('query_core.adapters.open_backend') as connect:
            code,result=self.call('execute','--id',1,'--param','not-a-pair')
        self.assertEqual(code,2); self.assertEqual(result['status'],'params_invalid_pair'); connect.assert_not_called()

    @unittest.skipUnless(shutil.which('powershell.exe'),'Windows PowerShell 5.1 unavailable')
    def test_actual_windows_powershell_passes_repeat_scalar_arguments(self):
        runner=self.root/'runner.py'
        runner.write_text('import sys\nsys.path.insert(0,'+repr(str(ROOT/'scripts/query_skills'))+')\nfrom query_core.cli import main\nraise SystemExit(main("demo"))\n',encoding='utf-8')
        quote=lambda p: "'"+str(p).replace("'","''")+"'"
        command='& '+quote(sys.executable)+' -X utf8 -B '+quote(runner)+' --state-root '+quote(self.store.root)+' execute --id 1 --param start_date=2026-10-01 --param end_date=2026-11-01 --param process=WB'
        done=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-Command',command],capture_output=True,encoding='utf-8',timeout=30)
        self.assertEqual(done.returncode,0,done.stderr)
        result=json.loads(done.stdout); self.assertEqual(result['savedRows'],1)
