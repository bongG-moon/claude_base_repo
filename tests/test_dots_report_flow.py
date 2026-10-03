"""Isolated real CLI report lifecycle; no model, personal profile or network."""
import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'company-agent-plugin/scripts'
sys.path.insert(0, str(SCRIPTS))
from company_agent import business_artifacts, report_design


def synthetic_report():
    rows = [
        ['N01', '2026-03', 100, 100, 2], ['N02', '2026-03', 150, 150, 4],
        ['N03', '2026-03', 150, 150, 4], ['N04', '2026-04', 120, 120, 3],
        ['N05', '2026-04', 130, 125, 4], ['N06', '2026-04', 150, 150, 5],
        ['N07', '2026-05', 100, 100, 2], ['N08', '2026-05', 100, 105, 3],
        ['N09', '2026-05', 100, 100, 2], ['N10', '2026-05', 100, 100, 3],
    ]
    facts = []
    for name, col, expected in [('target', 2, 1200), ('actual', 3, 1200), ('defects', 4, 32)]:
        facts.append({'id': name, 'op': 'sum', 'inputs': [{'table': [2, i, col]} for i in range(10)],
                      'expected': expected, 'unit': '개', 'label': {'target':'목표','actual':'실적','defects':'불량'}[name]})
    facts.append({'id':'rate','label':'달성률','op':'ratio','inputs':[{'fact':'actual'},{'fact':'target'}],
                  'expected':100,'decimals':2,'unit':'%'})
    monthly = []
    for month, indexes, expected in [('03', range(3), [400,400,10]), ('04', range(3,6), [400,395,12]),
                                      ('05', range(6,10), [400,405,10])]:
        for name, col, value in zip(['target','actual','defects'], [2,3,4], expected):
            facts.append({'id':f'{name}{month}','op':'sum','inputs':[{'table':[2,i,col]} for i in indexes], 'expected':value})
        facts.append({'id':f'rate{month}','op':'ratio','inputs':[{'fact':f'actual{month}'},{'fact':f'target{month}'}],
                      'decimals':2,'expected':{'03':100,'04':98.75,'05':101.25}[month]})
        monthly.append([f'2026-{month}', *['{{fact:'+name+month+'}}' for name in ['target','actual','defects']],
                        '{{fact:rate'+month+'}}%'])
    return {'title':'생산실적 월간보고 · 가상 검증 자료', 'subtitle':'2026년 3–5월 · 실제 회사 자료 아님',
            'style':'minimalism','length':'short','mode':'scroll','facts':facts,
            'sections':[
                {'title':'목표 1,200개, 실적 1,200개', 'layout':'cover',
                 'body':'총 달성률은 {{fact:rate}}%입니다. 불량은 {{fact:defects}}개이며 원인은 자료로 확인할 수 없습니다.',
                 'kpis':[{'fact':'actual'},{'fact':'rate'}]},
                {'title':'월별 실적과 목표를 같은 기준으로 비교', 'layout':'table',
                 'table':{'headers':['기간','목표(개)','실적(개)','불량(개)','달성률'], 'rows':monthly}},
                {'title':'집계에 사용한 원자료 10행', 'layout':'table',
                 'table':{'headers':['ID','기간','목표(개)','실적(개)','불량(개)'], 'rows':rows},
                 'source':'합성 CSV의 원본 ID 유지. 데이터 행은 헤더를 제외한 순서입니다.'},
                {'title':'확인할 사항', 'layout':'summary',
                 'body':'실적에 불량이 포함되는지 확인하지 않았습니다. 양품 수량은 임의 계산하지 않았습니다.'},
                {'title':'계산 기준과 검증 범위', 'layout':'summary',
                 'body':'달성률 = 실적 ÷ 목표 × 100. 표시 소수점은 둘째 자리까지이며 원인을 추정하지 않았습니다.'}
            ]}


def run_cli_report(destination):
    destination.mkdir(parents=True, exist_ok=True)
    state = destination / 'state'
    project = destination / 'project'
    project.mkdir()
    # Prevent the CLI from consulting the real user's config even on error paths.
    config = destination / 'config'
    config.mkdir()
    env = {**os.environ, 'CLAUDE_CONFIG_DIR':str(config), 'PYTHONIOENCODING':'utf-8',
           'PYTHONDONTWRITEBYTECODE':'1'}
    spec = synthetic_report()
    source = project / 'production_normal.csv'
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(spec['sections'][2]['table']['headers'])
    writer.writerows(spec['sections'][2]['table']['rows'])
    source.write_text(stream.getvalue(), encoding='utf-8')
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    calls = []

    def call(args, expected=0):
        started = time.perf_counter()
        result = subprocess.run([sys.executable, '-X','utf8','-B',str(SCRIPTS/'harness_cli.py'),
                                 'business',*args,'--state-root',str(state)],
                                capture_output=True, text=True, encoding='utf-8', env=env,
                                cwd=project, timeout=30)
        assert result.returncode == expected, (args, result.stdout, result.stderr)
        body = json.loads(result.stdout)
        calls.append({'command':args[0], 'ms':round((time.perf_counter()-started)*1000, 1),
                      'exitCode':result.returncode, 'status':body.get('status')})
        return body

    final = project / '생산실적_월간보고.html'
    work = call(['artifact-start','--output',str(final)])
    assert work['ok'], work
    assert not final.exists()
    Path(work['jobPath']).write_text(json.dumps(spec,ensure_ascii=False), encoding='utf-8')
    made = call(['html','--spec',work['jobPath'],'--work',work['workFile']])
    assert made['ok'], made
    assert made['validation']['arithmetic'] == 'checked', made
    assert not final.exists()
    published = call(['artifact-publish','--work',work['workFile']])
    assert published['ok'], published
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original
    assert set(p.name for p in project.iterdir()) == {source.name, final.name}
    contents = final.read_text(encoding='utf-8')
    assert '{{fact:' not in contents
    for value in ['98.75%', '101.25%', 'N01', 'N10', '1,200', '32']:
        assert value in contents, value
    assert not list(config.iterdir())
    return {'calls':calls, 'cliMs':round(sum(c['ms'] for c in calls),1),
            'outputPath':str(final),'facts':made['validation']['facts'],
            'sourcePreserved':True,'finalFiles':1,'modelCalls':0,'personalConfigUnchanged':True,
            'basis':'real local CLI with synthetic input; not natural-language model execution'}


class DotsReportFlowTests(unittest.TestCase):
    def test_real_cli_three_steps_preserve_source_and_one_final(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_cli_report(Path(temp))
            self.assertEqual(['artifact-start','html','artifact-publish'], [c['command'] for c in result['calls']])
            self.assertEqual(16,result['facts'])

    def test_compact_spacing_is_opt_in_and_never_truncates_rows(self):
        for length, mode, reference, enabled in [('short','scroll',False,True),('standard','scroll',False,False),
                                               ('short','slides',False,False),('short','scroll',True,False)]:
            raw = {**synthetic_report(), 'length':length, 'mode':mode}
            data = business_artifacts._normalize(raw)
            if reference:
                data['referenceCss'] = '.section{padding:50px}'
            rendered = report_design.render(data, business_artifacts._CSS, business_artifacts._JS,
                                            business_artifacts._html_table)
            self.assertEqual(enabled, 'Compact spacing, never truncate' in rendered)
            self.assertEqual(5, rendered.count('<section class="section '))
            for number in range(1,11):
                self.assertIn(f'N{number:02d}', rendered)

    def test_guidance_reuses_identified_issues_and_disambiguates_page(self):
        ref = (ROOT/'company-agent-plugin/skills/html-report/references/design-and-numbers.md').read_text(encoding='utf-8')
        for phrase in ('같은 이상 항목 목록', '데이터 12행(헤더 제외)', '여러 줄 CSV 셀', '인쇄 A4 한 장은 다릅니다'):
            self.assertIn(phrase, ref)

    def test_actual_generator_keeps_cover_and_scopes_compact_decorations(self):
        # _normalize alone does not carry layout; exercise the production path.
        with tempfile.TemporaryDirectory() as temp:
            for style in business_artifacts.STYLES:
                for length, mode in [('short', 'scroll'), ('standard', 'scroll'), ('short', 'slides')]:
                    with self.subTest(style=style, length=length, mode=mode):
                        spec = {'title': '짧은 표지 검증', 'style': style, 'length': length, 'mode': mode,
                                'sections': [{'title': '요약', 'layout': 'cover', 'body': '짧은 표지입니다.'},
                                             {'title': '다음 내용', 'body': '이 내용이 가려지면 안 됩니다.'}]}
                        output = Path(temp) / f'{style}-{length}-{mode}.html'
                        result = business_artifacts.create_html(spec, output)
                        self.assertTrue(result['ok'], result)
                        rendered = output.read_text(encoding='utf-8')
                        self.assertIn('class="section layout-cover"', rendered)
                        self.assertIn('이 내용이 가려지면 안 됩니다.', rendered)
                        self.assertIn('body[data-style][data-view] .theme-art{position:relative', rendered)
                        self.assertIn('body[data-style][data-view] .layout-cover{padding-right:22px}', rendered)
                        self.assertEqual(length == 'short' and mode == 'scroll',
                                         'Compact spacing, never truncate' in rendered)
                        if length == 'short' and mode == 'scroll':
                            self.assertIn('[data-length=short][data-view=scroll] .theme-art{display:none}', rendered)
                            self.assertIn('.layout-cover{padding-right:22px}', rendered)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--evidence':
        print(json.dumps(run_cli_report(Path(sys.argv[2]).resolve()), ensure_ascii=False, indent=2))
    else:
        unittest.main()
