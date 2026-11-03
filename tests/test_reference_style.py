import copy,sys,tempfile,unittest,zipfile
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
    def test_page_background_is_not_replaced_by_a_different_panel_surface(self):
        profile={'colors':{'bg':'FFFFFF','surface':'E8E8E8','text':'222222','muted':'555555'}}
        spec={'referenceStyle':profile,'slides':[{'title':'배경','body':'내용'}]}
        data=ppt_html.prepare(spec)[0]
        self.assertEqual('FFFFFF',data['presentationPlan']['theme']['background'])
        # Surface still has a separate role for table bodies.
        self.assertEqual('E8E8E8',data['tableStyle']['bodyFill'])
        result=reference_style.apply({**spec,'presentationTheme':{'background':'FAFAFA'}},'ppt')
        self.assertEqual('FAFAFA',result['presentationTheme']['background'])
        fallback=reference_style.apply({'referenceStyle':{'colors':{'surface':'E8E8E8'}}},'ppt')
        self.assertEqual('E8E8E8',fallback['presentationTheme']['background'])
    def test_neutral_reference_without_primary_keeps_chart_in_observed_colors(self):
        profile={'colors':{'bg':'FFFFFF','text':'333333','muted':'666666'}}
        spec={'referenceStyle':profile,'slides':[{'title':'현황','chart':{
            'type':'column','categories':['가','나'],
            'series':[{'name':'현재','values':[1,2]},{'name':'목표','values':[2,3]}]}}]}
        data=ppt_html.prepare(spec)[0]
        chart=next(e for e in data['presentationPlan']['pages'][0]['elements'] if e['kind']=='chart')
        self.assertEqual(['333333','666666'],chart['chartStyle']['seriesColors'])
        html=ppt_html.render(data)
        self.assertIn('#333333',html)
        self.assertIn('#666666',html)
        from company_agent import presentation_design
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'neutral.pptx'
            presentation_design.render_python(data,output,None)
            with zipfile.ZipFile(output) as deck:
                native=deck.read('ppt/charts/chart1.xml').decode('utf-8')
        self.assertIn('333333',native)
        self.assertIn('666666',native)
        self.assertNotIn('B05C32',native)
        explicit=reference_style.apply({**spec,'chartStyle':{'seriesColors':['FF0000']}},'ppt')
        self.assertEqual(['FF0000'],explicit['chartStyle']['seriesColors'])
    def test_neutral_reference_does_not_introduce_default_accent_or_panel_tint(self):
        profile={'colors':{'bg':'FFFFFF','surface':'EEEEEE','text':'333333','muted':'666666'}}
        spec={'referenceStyle':profile,'slides':[{'title':'제목','elements':[
            {'kind':'shape','shape':'rect','x':40,'y':120,'w':400,'h':100,'fill':'tint'},
            {'kind':'text','text':'강조','x':60,'y':140,'w':300,'h':40,'size':20,'color':'accent'}]}]}
        data=ppt_html.prepare(spec)[0]
        theme=data['presentationPlan']['theme']
        self.assertEqual('333333',theme['accent'])
        self.assertEqual('EEEEEE',theme['tint'])
        scene=data['presentationPlan']['pages'][0]['elements']
        self.assertEqual('EEEEEE',scene[0]['fill'])
        self.assertEqual('333333',scene[1]['color'])
        from company_agent import presentation_design
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'neutral.pptx'
            presentation_design.render_python(data,output,None)
            with zipfile.ZipFile(output) as deck:
                native=deck.read('ppt/slides/slide1.xml').decode('utf-8')
        self.assertIn('EEEEEE',native)
        self.assertIn('333333',native)
        self.assertNotIn('087F8C',native)
    def test_neutral_reference_preserves_chosen_preset_and_explicit_or_observed_theme(self):
        profile={'colors':{'bg':'FFFFFF','surface':'EEEEEE','text':'333333','muted':'666666'}}
        slide=[{'title':'제목','body':'본문'}]
        chosen=ppt_html.prepare({'referenceStyle':profile,'designPreset':'business','slides':slide})[0]
        self.assertEqual('087F8C',chosen['presentationPlan']['theme']['accent'])
        self.assertEqual('EEF4F7',chosen['presentationPlan']['theme']['tint'])
        observed=copy.deepcopy(profile)
        observed['colors'].update(primary='444444',tint='F0F0F0')
        data=ppt_html.prepare({'referenceStyle':observed,'designPreset':'business','slides':slide})[0]
        self.assertEqual('444444',data['presentationPlan']['theme']['accent'])
        self.assertEqual('F0F0F0',data['presentationPlan']['theme']['tint'])
        explicit=ppt_html.prepare({'referenceStyle':observed,'slides':slide,
                    'presentationTheme':{'accent':'224466','tint':'F3F3F3'}})[0]
        self.assertEqual('224466',explicit['presentationPlan']['theme']['accent'])
        self.assertEqual('F3F3F3',explicit['presentationPlan']['theme']['tint'])
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
