"""Operational regressions: roles, dense tables, defaults and editable export."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'company-agent-plugin/scripts'))
from company_agent import ppt_html,ppt_preflight,presentation_design,business_artifacts


def chart():
    return {'type':'column','title':'기준일별 생산량', 'categories':['월','화','수'],
            'series':[{'name':'실적','values':[20,24,27]}]}


class PptExecutionFlowTests(unittest.TestCase):
    def test_role_is_not_an_evidence_whitelist(self):
        table={'headers':['구간','수량'],'rows':[['ISMW','12'],['BAY','9']]}
        for role in ('cover','key-message','comparison','workflow','timeline','detail','closing'):
            for visual in ({'chart':chart()},{'table':table},{'chart':chart(),'table':table}):
                with self.subTest(role=role,visual=list(visual)):
                    row={'title':'운영 현황','pageRole':role,'body':'수량과 기준을 함께 확인합니다.',**visual}
                    data=ppt_html.prepare({'slides':[row]})[0]
                    elements=data['presentationPlan']['pages'][0]['elements']
                    self.assertEqual(set(visual),{e['kind'] for e in elements if e['kind'] in visual})
                    self.assertTrue(any(e.get('text')==row['body'] for e in elements))

    def test_explicit_layout_is_honored_without_erasing_role_or_chart(self):
        spec={'slides':[{'title':'현황','pageRole':'comparison','layout':'evidence','chart':chart(),
                         'body':'비교를 위한 실제 근거'}]}
        before=copy.deepcopy(spec)
        data=ppt_html.prepare(spec)[0]
        self.assertEqual(spec,before)
        self.assertEqual('comparison',data['sections'][0]['pageRole'])
        elements=data['presentationPlan']['pages'][0]['elements']
        self.assertTrue(any(e['kind']=='chart' for e in elements))

    def test_eleven_rows_are_preserved_and_measured_pagination_is_reported(self):
        rows=[[f'BAY-{i:02d}',f'장비 {i}',f'{i*13}'] for i in range(1,12)]
        spec={'slides':[{'title':'BAY 전체 현황','pageRole':'detail','body':'ISMW를 포함한 전체 대상입니다.',
                         'source':'가상 자료','table':{'headers':['구간','장비','건수'],'rows':rows}}]}
        before=copy.deepcopy(spec)
        with tempfile.TemporaryDirectory() as directory:
            draft=ppt_html.create_draft(spec,Path(directory)/'draft.html',require_choices=False)
            self.assertTrue(draft['ok'],draft)
            self.assertTrue(draft['pagination']['preservedAllRows'])
            data=ppt_html.prepare(spec)[0]
            self.assertEqual(rows,[r for s in data['sections'] for r in s['table']['rows']])
            self.assertEqual(before,spec)
            from pptx import Presentation
            output=Path(directory)/'deck.pptx'
            counts=presentation_design.render_python(data,output,None)
            deck=Presentation(output)
            actual=[[cell.text for cell in row.cells] for slide in deck.slides
                    for shape in slide.shapes if shape.has_table for row in list(shape.table.rows)[1:]]
            self.assertEqual(rows,actual)
            self.assertEqual(len(data['sections']),counts['tables'])

    def test_eleven_short_rows_can_fit_without_arbitrary_ten_row_gate(self):
        rows=[[str(i),'OK'] for i in range(11)]
        data=ppt_html.prepare({'slides':[{'title':'전체 목록','pageRole':'detail',
                'table':{'headers':['번호','상태'],'rows':rows}}]})[0]
        self.assertEqual(1,len(data['sections']))
        table=next(e for e in data['presentationPlan']['pages'][0]['elements'] if e['kind']=='table')
        self.assertEqual(rows,table['table']['rows'])

    def test_default_annotations_pass_their_own_quality_threshold(self):
        for extra in ({},{'layout':'evidence'},{'pageRole':'closing'}):
            data=ppt_html.prepare({'slides':[{'title':'현황','body':'후속 작업을 확인합니다.',
                    'source':'실제 조회 시각과 기준을 기록합니다.',**extra}]})[0]
            report=ppt_preflight.inspect_plan(data['presentationPlan'])
            self.assertNotIn('small_annotation_text',[i['code'] for i in report['issues']])

    def test_short_comparison_and_closing_do_not_stretch_empty_boxes(self):
        samples=[{'title':'비교','pageRole':'comparison','panels':[
                     {'title':'현재','body':'대기 조건을 따로 확인합니다.'},
                     {'title':'다음','body':'같은 기준으로 비교합니다.'}]},
                 {'title':'결론','pageRole':'closing','body':'조건을 확인하고 작은 범위부터 적용합니다.'}]
        for row in samples:
            with self.subTest(role=row['pageRole']):
                elements=ppt_html.prepare({'slides':[row]})[0]['presentationPlan']['pages'][0]['elements']
                boxes=[e for e in elements if e['kind']=='shape' and e['h']>5]
                self.assertTrue(boxes)
                self.assertTrue(all(e['h']<200 for e in boxes))
                self.assertTrue(all(e['y']>150 for e in boxes))

    def test_timeline_endpoint_dates_stay_outside_wrapped_korean_description(self):
        row={'title':'검토 일정과 완료 기준을 구분합니다','pageRole':'timeline',
             'milestones':[{'date':'2026-11-05','label':'자료 점검','detail':'대상과 기준일 확인'},
                           {'date':'2026-11-10','label':'조건 검토','detail':'담당자와 근거 확보'},
                           {'date':'2026-11-19','label':'제한 적용','detail':'대상 설비 시험'},
                           {'date':'2026-11-26','label':'결과 검토','detail':'확대 여부 판단'}]}
        data=ppt_html.prepare({'presentationProfile':{'density':'presentation'},'slides':[row]})[0]
        plan=data['presentationPlan']
        elements=plan['pages'][0]['elements']
        headings=[e for e in elements if e.get('text','').startswith('자료 점검 /')]
        dates=[e for e in elements if e.get('text')=='2026-11-05']
        self.assertTrue(all(e['x']>=headings[0]['x']+headings[0]['w'] for e in dates))
        self.assertEqual([],ppt_preflight.inspect_plan(plan)['issues'])

    def test_compact_closing_reserves_native_korean_paragraph_height(self):
        body='첫 적용은 한 구간으로 제한합니다.\n처리량과 대기를 같은 기간으로 비교합니다.\n품질 기준을 함께 확인합니다.\n결과에 따라 확대 여부를 결정합니다.'
        data=ppt_html.prepare({'presentationProfile':{'density':'presentation'},
            'slides':[{'title':'결론','pageRole':'closing','body':body}]})[0]
        element=next(e for e in data['presentationPlan']['pages'][0]['elements'] if e.get('text')==body)
        # PowerPoint's Malgun Gothic four-paragraph ink bound was 97.08pt at
        # 18pt, exceeding the old 91.84pt box. Keep the font and content intact.
        self.assertGreater(element['h'],97.08)
        self.assertEqual(18,element['size'])

    def test_large_table_keeps_the_paired_chart_and_all_rows_on_each_continuation(self):
        rows=[[f'항목{i}',str(i)] for i in range(15)]
        spec={'slides':[{'title':'원본 근거','pageRole':'comparison','chart':chart(),
                'table':{'headers':['항목','값'],'rows':rows},'source':'동일 기준 자료'}]}
        data=ppt_html.prepare(spec)[0]
        self.assertGreater(len(data['sections']),1)
        self.assertEqual(rows,[r for s in data['sections'] for r in s['table']['rows']])
        for row,page in zip(data['sections'],data['presentationPlan']['pages']):
            self.assertEqual(chart()['series'],row['chart']['series'])
            self.assertEqual({'table','chart'},set(e['kind'] for e in page['elements'])&{'table','chart'})

    def test_pagination_retains_input_and_output_bounds(self):
        spec={'slides':[{'title':'범위','body':'확인'} for _ in range(59)]+[
            {'title':'큰 표','table':{'headers':['번호'],'rows':[[str(i)] for i in range(100)]}}]}
        before=copy.deepcopy(spec)
        with self.assertRaises(business_artifacts.ArtifactError) as result:
            ppt_html.prepare(spec)
        self.assertIn('60장',str(result.exception))
        self.assertEqual(before,spec)
        spec['slides']=[spec['slides'][-1]]
        spec['slides'][0]['table']['rows'].append(['101'])
        with self.assertRaises(business_artifacts.ArtifactError) as result:
            ppt_html.prepare(spec)
        self.assertEqual('invalid_table',result.exception.code)

    def test_ordered_table_pagination_keeps_summary_below_each_table(self):
        rows=[[str(i),'원본'] for i in range(14)]
        spec={'slides':[{'title':'원본 순서','body':'표 아래의 요약을 유지합니다.',
                'contentOrder':['table','body'],'table':{'headers':['번호','자료'],'rows':rows}}]}
        data=ppt_html.prepare(spec)[0]
        self.assertGreater(len(data['sections']),1)
        self.assertEqual(rows,[r for s in data['sections'] for r in s['table']['rows']])
        for page in data['presentationPlan']['pages']:
            table=next(e for e in page['elements'] if e['kind']=='table')
            body=next(e for e in page['elements'] if e.get('text')==spec['slides'][0]['body'])
            self.assertGreaterEqual(body['y'],table['y']+table['h'])

    def test_operational_thirteen_slide_fixture_keeps_six_charts_and_no_scene_warning(self):
        spec=json.loads((ROOT/'tests/fixtures/presentation_operations_dense.json').read_text(encoding='utf-8'))
        data=ppt_html.prepare(spec)[0]
        self.assertEqual(6,sum(e['kind']=='chart' for p in data['presentationPlan']['pages'] for e in p['elements']))
        original=spec['slides'][1]['table']['rows']
        self.assertEqual(original,[r for s in data['sections'] if s.get('_sourceSlide')==2 for r in s['table']['rows']])
        self.assertEqual([],ppt_preflight.inspect_plan(data['presentationPlan'])['issues'])


if __name__=='__main__': unittest.main()
