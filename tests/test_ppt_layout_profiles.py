"""Opt-in Korean slide compositions preserve content and explicit topology."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'company-agent-plugin/scripts'))
from company_agent import ppt_layouts

PALETTE={'title':'17324D','accent':'087F8C','text':'30465B','muted':'52667C',
         'background':'FFFFFF','tint':'EEF4F7'}


class PptRoleCompositionTests(unittest.TestCase):
    def test_semantic_payload_cannot_be_silently_hidden_by_another_layout(self):
        from company_agent import ppt_html,business_artifacts
        samples=[row for row in ppt_layouts.examples() if row['pageRole'] in ('workflow','timeline','comparison')]
        for row in samples:
            for extra in ({'elements':[{'kind':'text','x':40,'y':40,'w':500,'h':60,'size':24,'text':'직접 배치'}]},
                          {'contentOrder':['body'],'body':'직접 순서'}, {'imageLayout':'full-slide'}):
                with self.subTest(role=row['pageRole'],extra=extra),self.assertRaises(business_artifacts.ArtifactError):
                    ppt_html.prepare({'slides':[{**copy.deepcopy(row),**extra}]})
            without_role={k:v for k,v in row.items() if k!='pageRole'}
            with self.subTest(role=row['pageRole'],missing=True),self.assertRaises(business_artifacts.ArtifactError):
                ppt_html.prepare({'slides':[without_role]})

    def page(self,row,width=960,height=540,custom=None):
        p=ppt_layouts.profile({'presentationProfile':custom or {}},width,height)
        return ppt_layouts.compose(row,1,width,height,PALETTE,'Malgun Gothic',p)

    def test_all_seven_examples_have_distinct_content_bearing_plans(self):
        examples=ppt_layouts.examples()
        self.assertEqual(set(ppt_layouts.ROLES),{row['pageRole'] for row in examples})
        signatures=[]
        for row in examples:
            before=copy.deepcopy(row)
            page=self.page(row)
            self.assertEqual(before,row,'Role selection must not mutate source content')
            self.assertEqual(row['pageRole'],page['pageRole'])
            self.assertTrue(any(e.get('text')==row['title'] for e in page['elements']))
            signature=[(e['kind'],round(e['x']),round(e['y']),round(e['w']),round(e['h']))
                       for e in page['elements']]
            signatures.append(repr(signature))
            for e in page['elements']:
                self.assertGreaterEqual(min(e['x'],e['y']),0)
                self.assertLessEqual(e['x']+e['w'],960.5)
                self.assertLessEqual(e['y']+e['h'],540.5)
        self.assertEqual(7,len(set(signatures)))

    def test_legacy_and_explicit_geometry_have_no_automatic_role_override(self):
        self.assertIsNone(self.page({'title':'기존','body':'기존 본문'}))
        for extra in ({'elements':[]},{'contentOrder':['body']},{'imageLayout':'full-slide'}):
            self.assertIsNone(self.page({'pageRole':'comparison','title':'기존','body':'본문',**extra}))

    def test_body_bullets_sources_and_takeaway_are_retained(self):
        row={'pageRole':'closing','title':'후속 확인','body':'제공된 본문',
             'bullets':['첫 항목','둘째 항목'],'source':'원자료 출처','takeaway':'미확인 효과는 추정하지 않음'}
        page=self.page(row)
        content='\n'.join(e.get('text','') for e in page['elements'])
        for value in (row['title'],row['body'],*row['bullets'],row['source'],row['takeaway']):
            self.assertIn(value,content)

    def test_explicit_kpis_preserve_label_value_and_unit_without_recalculation(self):
        page=self.page({'pageRole':'key-message','title':'확인된 수치',
                        'kpis':[{'label':'신청 인원','value':'25','unit':'명'},
                                {'label':'검토 완료','value':'8','unit':'건'}],
                        'body':'관찰한 값만 표시합니다.'})
        content=[e.get('text') for e in page['elements']]
        for value in ('신청 인원','25 명','검토 완료','8 건','관찰한 값만 표시합니다.'):
            self.assertIn(value,content)
        self.assertEqual(2,len({e.get('group') for e in page['elements'] if e.get('group')}))

    def test_workflow_preserves_explicit_fork_and_merge(self):
        row=next(row for row in ppt_layouts.examples() if row['pageRole']=='workflow')
        page=self.page(row)
        lines=[e for e in page['elements'] if e['kind']=='line']
        self.assertEqual(4,len(lines))
        self.assertTrue(all(e['endArrow']=='triangle' for e in lines))
        node_boxes=[e for e in page['elements'] if e['kind']=='shape']
        self.assertEqual(4,len(node_boxes))
        self.assertEqual(3,len({e['x'] for e in node_boxes}))
        middle=sorted(node_boxes,key=lambda e:(e['x'],e['y']))[1:3]
        self.assertEqual(middle[0]['x'],middle[1]['x'])
        self.assertNotEqual(middle[0]['y'],middle[1]['y'])

    def test_parallel_nodes_without_edges_are_never_made_sequential(self):
        page=self.page({'pageRole':'workflow','title':'병렬 검토',
                        'workflow':{'nodes':[{'id':'a','title':'현장'},{'id':'b','title':'기술'}],'edges':[]}})
        self.assertFalse(any(e['kind']=='line' for e in page['elements']))
        boxes=[e for e in page['elements'] if e['kind']=='shape']
        self.assertEqual(boxes[0]['x'],boxes[1]['x'])

    def test_explicit_workflow_contour_is_preserved_with_readable_inside_text(self):
        row={'pageRole':'workflow','title':'분기 기준',
             'workflow':{'nodes':[{'id':'check','title':'권한 확인','shape':'diamond'},
                                  {'id':'next','title':'처리 진행','shape':'chevron'}],
                         'edges':[{'from':'check','to':'next'}]}}
        page=self.page(row)
        boxes=[e for e in page['elements'] if e['kind']=='shape']
        self.assertEqual(['diamond','chevron'],[e['shape'] for e in boxes])
        label=next(e for e in page['elements'] if e.get('text')=='권한 확인')
        self.assertGreater(label['x'],boxes[0]['x'])
        self.assertLess(label['x']+label['w'],boxes[0]['x']+boxes[0]['w'])

    def test_invalid_workflow_relationships_and_cycles_are_not_repaired_silently(self):
        nodes=[{'id':'a','title':'준비'},{'id':'b','title':'검토'}]
        cases=[{'nodes':nodes,'edges':[{'from':'a','to':'missing'}]},
               {'nodes':nodes,'edges':[{'from':'a','to':'b'},{'from':'b','to':'a'}]},
               {'nodes':nodes,'edges':[{'from':'a','to':'b'},{'from':'a','to':'b'}]},
               {'nodes':nodes+[{'id':'a','title':'중복'}],'edges':[]}]
        for flow in cases:
            with self.subTest(flow=flow),self.assertRaises(ppt_layouts.LayoutError):
                self.page({'pageRole':'workflow','title':'업무 흐름','workflow':flow})

    def test_timeline_uses_actual_day_intervals_and_sorts_dates(self):
        rows=[{'label':'마지막','date':'2027-01-31'}, {'label':'처음','date':'2027-01-01'},
              {'label':'중간','date':'2027-01-11'}]
        before=copy.deepcopy(rows)
        page=self.page({'pageRole':'timeline','title':'실제 날짜','milestones':rows})
        dots=[e for e in page['elements'] if e['kind']=='shape' and e.get('shape')=='ellipse']
        xs=[e['x'] for e in dots]
        self.assertEqual(3,len(xs))
        self.assertAlmostEqual((xs[1]-xs[0])/(xs[2]-xs[0]),1/3)
        self.assertEqual(before,rows)

    def test_same_day_milestones_have_same_time_position_and_separate_rows(self):
        page=self.page({'pageRole':'timeline','title':'같은 날 두 업무',
                        'milestones':[{'label':'현장 검토','date':'2027-01-01'},
                                      {'label':'기술 검토','date':'2027-01-01'}]})
        dots=[e for e in page['elements'] if e['kind']=='shape' and e.get('shape')=='ellipse']
        self.assertEqual(dots[0]['x'],dots[1]['x'])
        self.assertNotEqual(dots[0]['y'],dots[1]['y'])

    def test_non_iso_or_impossible_dates_are_not_guessed(self):
        for value in ('20270101','내일','2027-02-30','2027-13-01'):
            with self.subTest(value=value),self.assertRaises(ppt_layouts.LayoutError):
                self.page({'pageRole':'timeline','title':'날짜 확인','milestones':[
                    {'label':'첫째','date':value},{'label':'둘째','date':'2027-03-01'}]})

    def test_native_detail_table_is_full_width_and_preserves_cells(self):
        row=next(row for row in ppt_layouts.examples() if row['pageRole']=='detail')
        page=self.page(row)
        table=next(e for e in page['elements'] if e['kind']=='table')
        self.assertEqual(row['table'],table['table'])
        self.assertEqual(864,table['w'])
        self.assertAlmostEqual(table['w'],sum(table['columnWidths']))
        self.assertAlmostEqual(table['h'],sum(table['rowHeights']))

    def test_excessive_content_is_rejected_without_font_shrink_or_truncation(self):
        for row in ({'pageRole':'cover','title':'한글 제목 '*80,'body':'필수 본문'},
                    {'pageRole':'closing','title':'결론','body':'전체 내용을 보존해야 합니다. '*100},
                    {'pageRole':'detail','title':'상세 표','table':{'headers':['항목','내용'],
                     'rows':[['대상','매우 긴 한글 설명입니다. '*12] for _ in range(10)]}}):
            original=copy.deepcopy(row)
            with self.subTest(role=row['pageRole']),self.assertRaises(ppt_layouts.LayoutError):
                self.page(row)
            self.assertEqual(original,row)

    def test_unrendered_data_is_not_silently_dropped(self):
        bad=[{'pageRole':'cover','title':'표지','body':'설명','table':{'headers':['자료'],'rows':[['보존']]}},
             {'pageRole':'closing','title':'결론','body':'설명','panels':[{'title':'대상','body':'보존'}]},
             {'pageRole':'comparison','title':'비교','body':'설명','milestones':[{'label':'시점','date':'2027-01-01'}]}]
        for row in bad:
            with self.subTest(role=row['pageRole']),self.assertRaises(ppt_layouts.LayoutError):self.page(row)

    def test_role_geometry_supports_4_3_and_16_9(self):
        for width,height in ((960,540),(720,540)):
            for row in ppt_layouts.examples():
                with self.subTest(width=width,role=row['pageRole']):
                    page=self.page(row,width,height)
                    self.assertTrue(page['elements'])


class PptCompactProfileTests(unittest.TestCase):
    def test_reference_profile_uses_observed_styles_and_available_fonts_only(self):
        pages=[{'shapes':[{'shapeId':1,'name':'제목 상자'}, {'shapeId':2,'name':'본문'}],
                'declaredTextStyles':[{'shapeId':1,'sz':2190,'ea':'맑은 고딕'},
                                      {'shapeId':2,'sz':1350,'ea':'맑은 고딕'},
                                      {'shapeId':2,'sz':1350,'ea':'맑은 고딕'},
                                      {'shapeId':2,'sz':1000,'ea':'없는 글꼴'}]}]
        before=copy.deepcopy(pages)
        with patch('company_agent.ppt_workflow.font_available',side_effect=lambda face,inventory: face=='맑은 고딕'):
            result=ppt_layouts.reference_profile(pages,['맑은 고딕'])
        self.assertEqual({'titleSize':21.9,'titleFont':'맑은 고딕','bodySize':13.5,
                          'bodyFont':'맑은 고딕','density':'reading','annotationSize':10.0},result)
        self.assertEqual(before,pages)

    def test_reference_profile_does_not_invent_missing_style_or_use_unavailable_font(self):
        self.assertEqual({},ppt_layouts.reference_profile([],[]))
        with patch('company_agent.ppt_workflow.font_available',return_value=False):
            result=ppt_layouts.reference_profile([{'shapes':[],
                   'declaredTextStyles':[{'sz':1800,'ea':'미설치 서체'}, {'sz':'알 수 없음'}]}],[])
        self.assertEqual({'bodySize':18,'density':'presentation','annotationSize':18},result)

    def test_profile_is_compact_and_keeps_explicit_source_role_values(self):
        spec={'presentationFont':'Malgun Gothic','presentationProfile':{
            'titleSize':21.9,'bodySize':13.5,'annotationSize':10,'tableSize':14,'margin':32.4,'gap':18}}
        original=copy.deepcopy(spec)
        result=ppt_layouts.profile(spec)
        for key,value in spec['presentationProfile'].items():self.assertEqual(value,result[key])
        self.assertEqual(original,spec)
        self.assertLessEqual(len(result),10)

    def test_invalid_profile_values_and_unknown_fields_are_rejected(self):
        for raw in ({'titleSize':True},{'bodySize':float('nan')},{'gap':0},{'density':'ultra'},
                    {'madeUp':True},{'titleFont':''}):
            with self.subTest(raw=raw),self.assertRaises(ppt_layouts.LayoutError):
                ppt_layouts.profile({'presentationProfile':raw})

    def test_custom_font_names_need_actual_inventory_without_rewriting_names(self):
        with patch('company_agent.ppt_workflow.font_available',return_value=True) as available:
            result=ppt_layouts.profile({'presentationProfile':{'titleFont':'맑은 고딕'}})
            self.assertEqual('맑은 고딕',result['titleFont'])
            available.assert_called_once_with('맑은 고딕')
        with patch('company_agent.ppt_workflow.font_available',return_value=False):
            with self.assertRaises(ppt_layouts.LayoutError):
                ppt_layouts.profile({'presentationProfile':{'titleFont':'설치되지 않은 글꼴'}})


if __name__=='__main__':unittest.main()
