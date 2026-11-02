import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'company-agent-plugin/scripts'))
from company_agent import reference_style
from company_agent import ppt_html

class ReferenceStyleTests(unittest.TestCase):
    def test_invalid_explicit_ppt_override_is_a_controlled_input_error(self):
        from company_agent.business_artifacts import ArtifactError
        for field in ('presentationTheme','presentationProfile','tableStyle','chartStyle'):
            for value in (None,[],True,'not an object'):
                with self.subTest(field=field,value=value),self.assertRaises(ArtifactError) as error:
                    ppt_html.prepare({'referenceStyle':self.profile(),field:value,'slides':[{'title':'확인'}]})
                self.assertEqual('invalid_reference_style',error.exception.code)
    def test_ppt_prepare_uses_observations_for_real_scene_without_mutating_job(self):
        profile=self.profile()
        profile['typography']={'bodyFont':'Malgun Gothic','titleSize':30,'bodySize':16,'captionSize':10}
        spec={'referenceStyle':profile,'slides':[
            {'title':'새로운 표','table':{'headers':['항목','값'],'rows':[['신규',10]]}},
            {'title':'새로운 차트','chart':{'type':'column','categories':['신규'],
             'series':[{'name':'실적','values':[10]},{'name':'목표','values':[12]}]}}]}
        before=copy.deepcopy(spec)
        data=ppt_html.prepare(spec)[0]
        tables=[e for page in data['presentationPlan']['pages'] for e in page['elements'] if e['kind']=='table']
        charts=[e for page in data['presentationPlan']['pages'] for e in page['elements'] if e['kind']=='chart']
        self.assertEqual('134E4A',tables[0]['tableStyle']['headerFill'])
        self.assertEqual(['134E4A','C8892E','8F6A77'],charts[0]['chartStyle']['seriesColors'])
        self.assertEqual('right',charts[0]['chartStyle']['legendPosition'])
        self.assertEqual(spec,before)
    def profile(self):
        return {'colors':{'primary':'#134e4a','secondary':'C8892E','surface':'FFFFFF','text':'222222','series':['134e4a','c8892e','8f6a77']},
                'typography':{'headingFont':'맑은 고딕','bodyFont':'Malgun Gothic','bodySize':16},
                'table':{'headerFill':'134E4A'},'chart':{'legendPosition':'right'},
                'evidence':[{'source':'첨부 4장','scope':'1~4장','observed':['진녹색과 황토색 조합'],'uncertain':['폰트 이름은 시각 추정']}],
                'patterns':{'tables':'헤더는 진녹색, 중요 열은 옅은 황토색'}}
    def test_palette_and_component_styles_reach_both_targets_without_mutation(self):
        job={'referenceStyle':self.profile()};before=copy.deepcopy(job)
        ppt=reference_style.apply(job,'ppt');html=reference_style.apply(job,'html')
        self.assertEqual(['134E4A','C8892E','8F6A77'],ppt['chartStyle']['seriesColors'])
        self.assertEqual('134E4A',ppt['tableStyle']['headerFill'])
        self.assertEqual('right',ppt['chartStyle']['legendPosition'])
        self.assertEqual('C8892E',html['themeOverrides']['colors']['secondary'])
        self.assertNotIn('evidence',html['themeOverrides'])
        self.assertEqual(before,job)
    def test_explicit_settings_win_by_field_not_entire_profile(self):
        job={'referenceStyle':self.profile(),'presentationFont':'Noto Sans KR','presentationTheme':{'accent':'333333'},
             'presentationProfile':{'bodySize':20},'chartStyle':{'legendPosition':'top'}}
        result=reference_style.apply(job,'ppt')
        self.assertEqual('333333',result['presentationTheme']['accent'])
        self.assertEqual('Noto Sans KR',result['presentationProfile']['titleFont'])
        self.assertEqual(20,result['presentationProfile']['bodySize'])
        self.assertEqual('top',result['chartStyle']['legendPosition'])
        self.assertEqual(['134E4A','C8892E','8F6A77'],result['chartStyle']['seriesColors'])
        result=reference_style.apply({'referenceStyle':self.profile(),'themeOverrides':{'colors':{'primary':'111111'}}},'html')
        self.assertEqual('111111',result['themeOverrides']['colors']['primary'])
        self.assertEqual('C8892E',result['themeOverrides']['colors']['secondary'])
    def test_empty_legacy_job_unchanged(self):
        job={'slides':[{'title':'기존','body':'내용'}]}
        self.assertEqual(job,reference_style.apply(job,'ppt'))
        self.assertEqual(job,reference_style.apply(job,'html'))
    def test_unsafe_invalid_unbounded_input_rejected(self):
        for raw in ({'css':'body{}'},{'colors':{'primary':'url(secret)'}},{'typography':{'bodyFont':"A';color:red"}},
                    {'spacing':{'gap':float('nan')}},{'chart':{'showGrid':'false'}},{'chart':{'seriesColors':['123456']*13}},
                    {'evidence':[{'source':'x','observed':['full transcript']*13}]}):
            with self.subTest(raw=raw),self.assertRaises(ValueError):reference_style.normalize(raw)

if __name__=='__main__':unittest.main()
