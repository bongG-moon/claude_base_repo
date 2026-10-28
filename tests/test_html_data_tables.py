"""Data-report behavior, including export scope and safe spreadsheet text."""
import csv
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent.business_artifacts import create_html, _normalize, ArtifactError
from company_agent.report_tables import CORE_JS, render


class HtmlDataTableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / '보고서.html'

    def spec(self, count=137):
        return {'title': '가상 교육 현황', 'style': 'bento-grid', 'length': 'detailed',
                'mode': 'scroll', 'fontChoice': 'pretendard', 'sections': [{
                    'title': '부서별 신청 원자료', 'table': {'headers': ['ID', '부서', '신청 수', '설명'],
                    'rows': [[f'ID-{i:03}', ['생산', '품질', '기술'][i % 3], i - 5, '담당자가 확인할 내용 ' * 8] for i in range(count)]}}]}

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for pure controller tests')
    def test_search_filter_sort_and_csv_share_complete_result_not_page(self):
        checks = r'''
const rows=Array.from({length:137},(_,i)=>({index:i,values:[String(i),['생산','품질',''][i%3],String(i-50)],kinds:['text','text','number']}));
const state={query:'',filterColumn:1,filterValue:'품질',sortColumn:2,direction:-1};
const found=reportTableRows(rows,state), csv=reportTableCsv(['ID','부서','수량'],found);
if(found.length!==46||found[0].values[2]!=='86'||found[45].values[2]!=='-49')throw Error('filter/numeric sort');
if(csv.split('\r\n').length!==47)throw Error('export lost non-page rows');
if(reportTableRows(rows,{...state,filterValue:''}).length!==45)throw Error('empty filter confused with all');
if(reportTableRows(rows,{...state,filterValue:null}).length!==137)throw Error('all filter');
if(reportTableRows(rows,{...state,query:'없는자료'}).length!==0)throw Error('no results');
if(rows[0].index!==0||rows[136].index!==136)throw Error('mutated source');
console.log(JSON.stringify({count:found.length,csv}));
'''
        result = subprocess.run([shutil.which('node'), '-e', CORE_JS + checks], capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(46, output['count'])
        self.assertTrue(output['csv'].startswith('\ufeff'))
        parsed = list(csv.reader(io.StringIO(output['csv'].lstrip('\ufeff'))))
        self.assertEqual(47, len(parsed))
        self.assertEqual('-49', parsed[-1][2])

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for pure controller tests')
    def test_filter_candidates_require_repeated_short_categories_not_unique_ids(self):
        checks = r'''
for(const count of [13,30]) {
  const rows=Array.from({length:count},(_,i)=>['ID-'+i,['생산','품질'][i%2]]);
  const candidates=[0,1].filter(col=>reportTableCanFilter(new Set(rows.map(row=>row[col])),rows.length));
  if(JSON.stringify(candidates)!=='[1]')throw Error('unique IDs became filter candidates at '+count+' rows');
}
if(reportTableCanFilter(new Set(['같은 값']),13))throw Error('constant column became a filter');
if(reportTableCanFilter(new Set(['설명'.repeat(41),'짧은 설명']),13))throw Error('long prose became a filter');
'''
        result = subprocess.run([shutil.which('node'), '-e', CORE_JS + checks], capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for pure controller tests')
    def test_large_integer_and_decimal_sort_keeps_exact_values(self):
        values = ['9007199254740993', '9007199254740992', '-9007199254740993',
                  '-9007199254740992', '1.01e2', '100.99', '0', '-0.0', '1e-20', '-1e-20']
        command = CORE_JS + '\nconst values=' + json.dumps(values) + ';console.log(JSON.stringify(values.sort(reportTableNumberCompare)));'
        result = subprocess.run([shutil.which('node'), '-e', command], capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['-9007199254740993', '-9007199254740992', '-1e-20', '0', '-0.0', '1e-20',
                          '100.99', '1.01e2', '9007199254740992', '9007199254740993'], json.loads(result.stdout))

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for pure controller tests')
    def test_generated_fact_cells_keep_numeric_values_through_sort_and_csv(self):
        spec = {'facts': [
            {'id': 'two', 'op': 'value', 'inputs': [-2]},
            {'id': 'ten', 'op': 'value', 'inputs': [-10]},
            {'id': 'large', 'op': 'value', 'inputs': [-1200.375], 'decimals': 2},
        ], 'sections': [{'table': {'headers': ['계산', '단위 포함 설명'], 'rows': [
            ['{{fact:two}}', '{{fact:two}}명'],
            ['{{fact:ten}}', '{{fact:ten}}명'],
            ['{{fact:large}}', '{{fact:large}}명'],
        ]}}]}
        result = create_html(spec, self.output)
        self.assertTrue(result['ok'], result)
        source = self.output.read_text(encoding='utf-8')
        table = ET.fromstring(re.search(r'<table\b.*?</table>', source, re.S).group())
        rows = []
        for index, row in enumerate(table.findall('./tbody/tr')):
            rows.append({'index': index, 'values': [c.text or '' for c in row],
                         'kinds': [c.get('data-kind', 'text') for c in row],
                         'numbers': [c.get('data-number') for c in row]})
        self.assertEqual('-1,200.38', rows[2]['values'][0])
        self.assertEqual('-1200.375', rows[2]['numbers'][0])
        self.assertEqual(['number', 'text'], rows[0]['kinds'])
        command = CORE_JS + '\nconst rows=' + json.dumps(rows) + r''';
const found=reportTableRows(rows,{query:'',filterColumn:-1,filterValue:null,sortColumn:0,direction:1});
console.log(JSON.stringify({order:found.map(r=>r.numbers[0]),csv:reportTableCsv(['계산','설명'],found)}));'''
        process = subprocess.run([shutil.which('node'), '-e', command], capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(0, process.returncode, process.stderr)
        outcome = json.loads(process.stdout)
        self.assertEqual(['-1200.375', '-10', '-2'], outcome['order'])
        parsed = list(csv.reader(io.StringIO(outcome['csv'].lstrip('\ufeff'))))
        self.assertEqual(['-1200.375', '-10', '-2'], [row[0] for row in parsed[1:]])
        self.assertEqual("'-2명", parsed[-1][1])

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for pure controller tests')
    def test_csv_quotes_korean_newlines_and_formula_text_are_safe(self):
        payload = {'headers': ['=formula', '수량'], 'rows': [
            {'values': ['  =HYPERLINK("http://invalid")', '-12'], 'kinds': ['text', 'number']},
            {'values': ['한글,"인용"\n두 줄', '@SUM(A1)'], 'kinds': ['text', 'text']},
            {'values': ['\t+cmd', '-not-a-number'], 'kinds': ['text', 'text']},
        ]}
        command = CORE_JS + '\nconst data=' + json.dumps(payload) + ';console.log(JSON.stringify(reportTableCsv(data.headers,data.rows)));'
        result = subprocess.run([shutil.which('node'), '-e', command], capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)
        parsed = list(csv.reader(io.StringIO(json.loads(result.stdout).lstrip('\ufeff'))))
        self.assertEqual("'=formula", parsed[0][0])
        self.assertTrue(parsed[1][0].startswith("'  ="))
        self.assertEqual('-12', parsed[1][1])
        self.assertEqual('한글,"인용"\n두 줄', parsed[2][0])
        self.assertEqual("'@SUM(A1)", parsed[2][1])
        self.assertEqual("'\t+cmd", parsed[3][0])

    def test_all_source_rows_preserved_for_no_javascript_with_typed_numbers(self):
        result = create_html(self.spec(), self.output)
        self.assertTrue(result['ok'], result)
        source = self.output.read_text(encoding='utf-8')
        self.assertEqual(138, source.count('<tr>'))
        self.assertIn('ID-136', source)
        self.assertIn('data-kind="number" class="numeric">-5', source)
        self.assertEqual('bento-grid', result['style'])
        self.assertIn('data-panel', source)
        self.assertIn('beforeprint', source)
        self.assertNotIn('<script src=', source)
        self.assertNotIn('innerHTML', source)

    def test_text_only_report_adds_no_table_runtime(self):
        result = create_html({'sections': [{'title': '간단한 안내', 'body': '설명만 있습니다.'}]}, self.output)
        self.assertTrue(result['ok'], result)
        self.assertNotIn('function reportTableRows', self.output.read_text(encoding='utf-8'))

    def test_empty_data_is_explicit_and_strings_are_escaped(self):
        result = create_html(self.spec(0), self.output)
        self.assertTrue(result['ok'], result)
        self.assertIn('데이터가 없습니다.', self.output.read_text(encoding='utf-8'))
        text = render(['</script>'], [['<img src=x onerror=alert(1)>']])
        self.assertNotIn('<img', text)
        self.assertNotIn('</script>', text)

    def test_wide_html_table_does_not_expand_ppt_normalizer_limits(self):
        spec = {'sections': [{'table': {'headers': ['열'] * 40, 'rows': [[1] * 40 for _ in range(120)]}}]}
        self.assertTrue(create_html(spec, self.output)['ok'])
        with self.assertRaises(ArtifactError):
            _normalize(spec)

    def test_explicit_static_table_and_limits(self):
        spec = self.spec(3);spec['sections'][0]['table']['interactive'] = False
        result = create_html(spec, self.output)
        self.assertTrue(result['ok'], result)
        self.assertIn('data-report-table="static"', self.output.read_text(encoding='utf-8'))
        for table in ({'headers': ['a'], 'rows': [[1]] * 5001},
                      {'headers': ['a'], 'rows': [[float('inf')]]},
                      {'headers': ['a'], 'rows': [[1]], 'interactive': 'yes'}):
            self.assertFalse(create_html({'sections': [{'table': table}]}, self.output.with_name('bad.html'))['ok'])


if __name__ == '__main__':
    unittest.main()
