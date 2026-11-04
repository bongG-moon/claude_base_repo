"""Actual shipped table controller on a synthetic DOM; no browser/network."""
import csv
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent.report_tables import JS, CSS
from company_agent.business_artifacts import create_html


@unittest.skipUnless(shutil.which('node'), 'Node needed for controller test')
class HtmlTableToolbarTests(unittest.TestCase):
    def test_small_and_large_tables_search_sort_columns_download_and_reset(self):
        fixture = (ROOT / 'tests/fixtures/report_table_dom_fixture.js').read_text(encoding='utf-8')
        checks = r'''
const assert=require('node:assert/strict');
const getButton=(f,label)=>f.root.querySelectorAll('button').find(b=>b.textContent===label);
const search=f=>f.root.querySelectorAll('input').find(i=>i.type==='search');
const boxes=f=>f.root.querySelectorAll('input').filter(i=>i.type==='checkbox');
const small=fixtures[0],large=fixtures[1];
assert.equal(small.body.rows.length,4);assert.equal(large.body.rows.length,25);
assert.ok(search(small));assert.equal(getButton(small,'초기화').disabled,true);
assert.ok(small.root.querySelector('.table-status').textContent.includes('3개 열'));
getButton(large,'다음').click();assert.equal(large.body.rows[0].cells[0].textContent,'ID-25');
search(large).value='품질';search(large).handlers.input();assert.equal(large.body.rows[0].cells[0].textContent,'ID-1');
assert.ok(large.root.querySelector('.table-count').textContent.includes('60건 중 30건'));
large.headers[2].querySelector('button').click();assert.equal(large.body.rows[0].cells[2].textContent,'1');
assert.equal(large.headers[2].attrs['aria-sort'],'ascending');
getButton(large,'표시 열 3/3').click();assert.equal(large.root.querySelector('.table-column-panel').hidden,false);
boxes(large)[0].checked=false;boxes(large)[0].handlers.change();
assert.equal(large.headers[0].hidden,true);assert.equal(large.body.rows[0].cells[0].hidden,true);
assert.equal(large.table.style['--columns'],'2');
getButton(large,'현재 조건 CSV').click();getButton(large,'전체 CSV').click();
for(const fn of events.beforeprint)fn();assert.equal(large.body.rows.length,30);
for(const fn of events.afterprint)fn();assert.equal(large.body.rows.length,25);
// Keep at least one column. A reset must restore all data, order and columns.
boxes(large)[1].checked=false;boxes(large)[1].handlers.change();assert.equal(boxes(large)[2].disabled,true);
getButton(large,'초기화').click();assert.equal(search(large).value,'');assert.equal(large.headers[0].hidden,false);
assert.equal(large.body.rows[0].cells[0].textContent,'ID-0');assert.equal(large.headers[2].attrs['aria-sort'],undefined);
assert.equal(getButton(large,'초기화').disabled,true);
search(small).value='없는 결과';search(small).handlers.input();assert.ok(small.body.textContent.includes('조건에 맞는 데이터가 없습니다'));
assert.equal(getButton(small,'현재 조건 CSV').disabled,true);assert.equal(getButton(small,'전체 CSV').disabled,false);
getButton(small,'초기화').click();assert.equal(small.body.rows.length,4);
Promise.all(downloads.map(b=>b.text())).then(csv=>console.log(JSON.stringify({csv})));
'''
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'toolbar-test.js'
            path.write_text(fixture + '\n' + JS + '\n' + checks, encoding='utf-8')
            result = subprocess.run([shutil.which('node'), str(path)], capture_output=True,
                                    text=True, encoding='utf-8', timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        exports = json.loads(result.stdout)['csv']
        selected = list(csv.reader(io.StringIO(exports[0].lstrip('\ufeff'))))
        complete = list(csv.reader(io.StringIO(exports[1].lstrip('\ufeff'))))
        self.assertEqual(['부서', '수량'], selected[0])
        self.assertEqual(31, len(selected))
        self.assertEqual(['품질', '1'], selected[1])
        self.assertEqual(61, len(complete))
        self.assertEqual(['ID', '부서', '수량'], complete[0])

    def test_two_designs_reuse_theme_fonts_and_same_toolbar_without_extra_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            for style in ('minimalism', 'bento-grid'):
                target = Path(folder) / (style + '.html')
                result = create_html({'style': style, 'length': 'standard', 'mode': 'scroll',
                    'fontChoice': 'pretendard', 'fontSource': 'system', 'sections': [{
                    'table': {'headers': ['ID', '기준월', '수량'], 'rows': [['L-01', '2026-11', 120]]}}]}, target)
                self.assertTrue(result['ok'], result)
                html = target.read_text(encoding='utf-8')
                self.assertIn(JS, html)
                self.assertIn(CSS, html)
                self.assertIn(f'data-style="{style}"', html)
                self.assertEqual('Pretendard', result['typography']['family'])
                self.assertNotIn('<script src=', html)
                self.assertIn('data-column-kind="period"', html)
        self.assertIn('background:var(--ink);color:var(--paper)', CSS)
        self.assertIn('line-height:1.5', CSS)


if __name__ == '__main__':
    unittest.main()
