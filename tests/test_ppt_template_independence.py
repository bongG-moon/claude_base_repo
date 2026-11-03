"""New documents never read the vendor's disk default.pptx template."""
import builtins
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'company-agent-plugin/scripts'))
from company_agent import ppt_html, presentation_design, ppt_reference, ppt_office_reference, business_artifacts


class TemplateIndependenceTests(unittest.TestCase):
    def test_complex_editable_deck_never_reads_default_pptx(self):
        from pptx import Presentation
        from pptx.exc import PackageNotFoundError
        def checked(original):
            def open_checked(file, *args, **kwargs):
                if isinstance(file,(str,Path)) and str(file).replace('\\','/').endswith('/templates/default.pptx'):
                    raise PermissionError('Synthetic enterprise wrapping of library template')
                return original(file,*args,**kwargs)
            return open_checked
        spec={'creationMode':'new','designPreset':'business','title':'한글 복합 구조','slides':[
            {'title':'업무 흐름','elements':[
                {'kind':'shape','group':'업무','x':40,'y':60,'w':380,'h':220,'fill':'EEEEEE'},
                {'kind':'text','group':'업무','text':'조회 → 정리 → 보고','x':60,'y':90,'w':330,'h':90,'size':24,'bold':True,'color':'173B5E'},
                {'kind':'table','x':450,'y':60,'w':450,'h':120,'table':{'headers':['단계','책임'],'rows':[['조회','담당자'],['확인','검토자']]}}]},
            {'title':'성과 추이','chart':{'type':'column','categories':['1월','2월'], 'series':[{'name':'건수','values':[12,21]}]},'body':'가상 수치'}]}
        with tempfile.TemporaryDirectory() as temp, patch('builtins.open',side_effect=checked(builtins.open)), patch('io.open',side_effect=checked(io.open)):
            with self.assertRaises((PermissionError,PackageNotFoundError)):
                Presentation()
            data=ppt_html.prepare(spec)[0]
            target=Path(temp)/'result.pptx'
            counts=presentation_design.render_python(data,target,None)
            deck=Presentation(target)
            self.assertEqual(len(deck.slides),2)
            self.assertEqual(counts['groups'],1)
            self.assertEqual(counts['tables'],1)
            self.assertEqual(counts['charts'],1)
            self.assertEqual(deck.slides[0].shapes[0].shapes[1].text,'조회 → 정리 → 보고')
            deck.slides[0].shapes[0].shapes[1].text='수정 가능'
            deck.save(target)
            self.assertEqual(Presentation(target).slides[0].shapes[0].shapes[1].text,'수정 가능')

    def test_unreadable_reference_does_not_claim_xml_or_specific_vendor(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'reference.pptx'; path.write_bytes(b'<DOCUMENT SAFER synthetic>')
            result=ppt_reference.prepare_reference({'file':str(path)})
            self.assertEqual(result['code'],'reference_format_unreadable')
            self.assertFalse(result['restrictionConfirmed'])
            self.assertEqual(len(result['availableRoutes']),2)
            self.assertIn('specific_drm_vendor',result['doNotInfer'])
            self.assertFalse(result['captured'])

    def test_generated_output_wrapping_is_separate_from_template_read_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'result.pptx'
            def wrapped(data,draft,template):
                draft.write_bytes(b'<DOCUMENT SAFER synthetic output>')
                return {'text':1}
            with patch.object(business_artifacts,'_python_ppt',side_effect=wrapped), patch.object(business_artifacts,'_office',return_value={'ok':False}):
                result=business_artifacts.create_ppt({'title':'가상 출력','slides':[{'title':'요약','body':'본문'}]},output)
            self.assertEqual(result['code'],'generated_ppt_unreadable',result)
            self.assertFalse(output.exists())


class OfficeReferenceTests(unittest.TestCase):
    def run_mock(self, response, selection=None, write_images=True):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.source=self.root/'wrapped.pptx'
        self.source.write_bytes(b'<DOCUMENT SAFER synthetic>')
        def process(args,**kwargs):
            request=json.loads(Path(args[-1]).read_text())
            self.assertEqual(request['file'],str(self.source))
            if response.get('ok') and write_images:
                for n in response['slides']:
                    (Path(request['output'])/f'slide-{n:03d}.png').write_bytes(b'\x89PNG\r\n\x1a\nsynthetic')
            return subprocess.CompletedProcess(args,0,json.dumps(response).encode(),b'')
        with patch.object(ppt_office_reference,'_windows_powershell',return_value='powershell.exe'), patch.object(ppt_office_reference.subprocess,'run',side_effect=process):
            return ppt_office_reference.render_reference(self.source,self.root/'previews',selection)

    def test_office_receipt_preserves_slide_order_and_original(self):
        result=self.run_mock({'ok':True,'slides':[3,1],'slideCount':5},[3,1])
        self.assertTrue(result['ok'],result)
        self.assertEqual([v['slide'] for v in result['previews']],[3,1])
        self.assertEqual(result['method'],'powerpoint-native-export')
        self.assertEqual(result['visualReview'],'not_performed')
        self.assertEqual(self.source.read_bytes(),b'<DOCUMENT SAFER synthetic>')

    def test_permission_denial_does_not_publish_or_claim_render(self):
        result=self.run_mock({'ok':False,'code':'reference_permission_restricted'})
        self.assertFalse(result['ok']); self.assertFalse(result['retryAllowed'])
        self.assertFalse((self.root/'previews').exists())

    def test_missing_slide_never_publishes_partial_folder(self):
        result=self.run_mock({'ok':True,'slides':[1,2],'slideCount':2},write_images=False)
        self.assertEqual(result['code'],'reference_export_incomplete')
        self.assertFalse((self.root/'previews').exists())

    def test_existing_open_source_requests_screen_route_without_closing_it(self):
        result=self.run_mock({'ok':False,'code':'source_already_open'})
        self.assertFalse(result['ok']); self.assertIn('닫지 않았습니다',result['message'])


if __name__=='__main__':
    unittest.main()
