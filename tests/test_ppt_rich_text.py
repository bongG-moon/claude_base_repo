"""Korean inline formatting and bounded preflight use the shared scene."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'company-agent-plugin/scripts'))
from company_agent import business_artifacts as artifacts,ppt_html,ppt_scene,ppt_text,ppt_preflight,ppt_workflow,presentation_design


class RichTextTests(unittest.TestCase):
    def setUp(self):
        parent=ROOT/'.smoke/ppt-enhance/temp'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        self.element={'kind':'text','x':40,'y':50,'w':800,'h':90,'size':24,'font':'Malgun Gothic',
                      'runs':[{'text':'대상 '},{'text':'20건','bold':True,'color':'087F8C'},
                              {'text':'을 확인합니다.','italic':False}]}

    def data(self,element=None):
        return ppt_html.prepare({'slides':[{'title':'부분 강조','elements':[element or self.element]}]})[0]

    def test_inline_korean_text_stays_one_editable_box_with_individual_run_styles(self):
        from pptx import Presentation
        data=self.data()
        self.assertEqual('대상 20건을 확인합니다.',data['presentationPlan']['pages'][0]['elements'][0]['text'])
        target=self.path/'rich.pptx'
        presentation_design.render_python(data,target,None)
        slide=Presentation(target).slides[0]
        self.assertEqual(1,len(slide.shapes))
        runs=slide.shapes[0].text_frame.paragraphs[0].runs
        self.assertEqual('대상 20건을 확인합니다.',''.join(run.text for run in runs))
        self.assertEqual([False,True,False],[run.font.bold for run in runs])
        self.assertEqual('087F8C',str(runs[1].font.color.rgb))
        self.assertTrue(all(run.font.name=='Malgun Gothic' for run in runs))
        self.assertTrue(all('lang="ko-KR"' in run._r.xml and 'a:ea' in run._r.xml for run in runs))

    def test_multiline_and_per_run_font_size_survive_native_export(self):
        from pptx import Presentation
        e={**self.element,'runs':[{'text':'첫 줄\n','size':20},{'text':'둘째 줄','size':26,'font':'맑은 고딕','underline':True}]}
        target=self.path/'lines.pptx'
        presentation_design.render_python(self.data(e),target,None)
        shape=Presentation(target).slides[0].shapes[0]
        self.assertEqual('첫 줄\n둘째 줄',shape.text)
        self.assertEqual('맑은 고딕',shape.text_frame.paragraphs[1].runs[0].font.name)
        self.assertEqual(26,shape.text_frame.paragraphs[1].runs[0].font.size.pt)
        self.assertTrue(shape.text_frame.paragraphs[1].runs[0].font.underline)

    def test_html_uses_same_text_and_emphasis_without_executable_markup(self):
        e={**self.element,'runs':[{'text':'<script>원문</script>'},{'text':' 20건','bold':True,'color':'087F8C'}]}
        document=ppt_html.render(self.data(e))
        self.assertIn('&lt;script&gt;원문&lt;/script&gt;',document)
        self.assertNotIn('<script>원문',document)
        self.assertIn('color:#087F8C;font-weight:700',document)
        self.assertIn('word-break:keep-all',document)

    def test_invalid_or_different_rich_text_is_not_silently_discarded(self):
        for extra in ({'text':'다른 본문'}, {'runs':[]}, {'runs':[{'text':'가','bold':'false'}]},
                      {'runs':[{'text':'가','style':'font-size:0'}]}, {'runs':[{'text':'가','size':0}]}):
            with self.subTest(extra=extra),self.assertRaises(artifacts.ArtifactError):self.data({**self.element,**extra})

    def test_saved_style_does_not_retain_business_text_in_runs(self):
        e={**self.element,'runs':[{'text':'PRIVATE_ACCOUNT_123','bold':True},{'text':' PRIVATE_VALUE_456'}]}
        plan=self.data(e)['presentationPlan']
        layouts=ppt_scene.template_layouts(plan)
        serialized=json.dumps(layouts,ensure_ascii=False)
        self.assertNotIn('PRIVATE_',serialized)
        self.assertEqual('예시',layouts[0]['elements'][0]['text'])

    def test_bare_rich_runs_bind_declared_facts_before_rendering(self):
        e={**self.element,'runs':[{'text':'신청 '},{'text':'{{fact:count}}명','bold':True}]}
        data=ppt_html.prepare({'facts':[{'id':'count','op':'sum','inputs':[12,8]}],
                               'slides':[{'title':'신청 현황','elements':[e]}]})[0]
        result=data['presentationPlan']['pages'][0]['elements'][0]
        self.assertEqual('신청 20명',result['text'])
        self.assertEqual('20명',result['runs'][1]['text'])

    def test_font_measurement_cache_does_not_change_source_text(self):
        class Face:
            def getlength(self,value):return len(value)*32
        original='한글 단어와 20건\n두 번째 줄'
        with patch.object(ppt_text,'_measured_font',return_value=Face()):
            self.assertGreater(ppt_text.estimate_lines(original,50,18),2)
        self.assertEqual('한글 단어와 20건\n두 번째 줄',original)


class PreflightTests(unittest.TestCase):
    def plan(self,rows):return {'width':960,'height':540,'font':'Malgun Gothic','pages':[{'elements':rows}]}
    def text(self,x,y,**extra):return {'kind':'text','x':x,'y':y,'w':200,'h':50,'size':20,'text':'확인할 내용',**extra}

    def test_disconnected_arrow_and_chevron_ink_warning_are_advisory(self):
        plan=self.plan([
            {'kind':'shape','shape':'diamond','x':205.5,'y':250,'w':180,'h':100},
            {'kind':'shape','shape':'roundRect','x':405,'y':120,'w':150,'h':84},
            {'kind':'line','x':385.5,'y':300,'w':94.5,'h':96,'points':[[0,96],[94.5,96],[94.5,0]],'endArrow':'triangle'},
            {'kind':'shape','shape':'chevron','group':'g','x':632,'y':104,'w':288,'h':50},
            self.text(656,104,w=240,h=50,size=14,align='center',group='g',text='4분기  적용 6개 · 운영 인계'),
            self.text(36,512,w=600,h=16,size=9,text='실습용 가상 자료를 기준으로 작성했습니다.'),
        ])
        before=copy.deepcopy(plan)
        issues=ppt_preflight.inspect_plan(plan)['issues']
        self.assertEqual(before,plan)
        for code in ('possible_unconnected_arrow','possible_chevron_text_clipping','small_annotation_text'):
            self.assertIn(code,[row['code'] for row in issues])
        # The same elbow connects the diamond's right edge and the next node's bottom edge after repair.
        plan['pages'][0]['elements'][2]['y']=204
        self.assertNotIn('possible_unconnected_arrow',[row['code'] for row in ppt_preflight.inspect_plan(plan)['issues']])

    def test_overlap_advisory_keeps_source_and_does_not_shrink_text(self):
        plan=self.plan([self.text(40,50),self.text(45,52)])
        before=copy.deepcopy(plan)
        result=ppt_preflight.inspect_plan(plan)
        self.assertIn('possible_text_overlap',[row['code'] for row in result['issues']])
        self.assertEqual(before,plan)
        self.assertFalse(result['automaticTextShrinking'])

    def test_backgrounds_and_explicit_intentional_overlap_are_not_text_errors(self):
        plan=self.plan([{'kind':'shape','x':0,'y':0,'w':960,'h':540},self.text(40,50),self.text(40,50,allowOverlap=True)])
        self.assertEqual([],ppt_preflight.inspect_plan(plan)['issues'])

    def test_pair_and_model_response_budgets_are_bounded(self):
        rows=[self.text((i%20)*40,(i//20)*40,w=20,h=15,size=6,text='가') for i in range(150)]
        result=ppt_preflight.inspect_plan(self.plan(rows))
        self.assertEqual('partial',result['status'])
        self.assertTrue(result['truncated'])
        coverage=[{'slide':i+1,'totalObjects':100,'projectedObjects':90,'groups':2,
                   'unsupported':[{'reason':'unsupported_object_'+str(j)} for j in range(80)]} for i in range(60)]
        summary=ppt_preflight.template_summary(coverage)
        self.assertLess(len(json.dumps(summary,ensure_ascii=False)),6500)
        self.assertGreater(summary['omittedSlides'],0)
        self.assertEqual(60,summary['sourcePages'])


if __name__=='__main__':unittest.main()
