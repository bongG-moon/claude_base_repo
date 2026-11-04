"""New documents never read the vendor's disk default.pptx template."""
import builtins
import base64
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
        with patch.object(ppt_office_reference,'_windows_powershell',return_value='powershell.exe'), patch.object(ppt_office_reference.subprocess,'run',side_effect=process) as run:
            result = ppt_office_reference.render_reference(self.source,self.root/'previews',selection)
        run.assert_called_once()
        return result

    def test_office_receipt_preserves_slide_order_and_original(self):
        result=self.run_mock({'ok':True,'slides':[3,1],'slideCount':5},[3,1])
        self.assertTrue(result['ok'],result)
        self.assertEqual([v['slide'] for v in result['previews']],[3,1])
        self.assertEqual(result['method'],'powerpoint-native-export')
        self.assertEqual(result['visualReview'],'not_performed')
        self.assertEqual(self.source.read_bytes(),b'<DOCUMENT SAFER synthetic>')

    def test_permission_denial_does_not_publish_or_claim_render(self):
        permission={'status':'reported','enabled':True}
        result=self.run_mock({'ok':False,'code':'reference_permission_restricted','permission':permission})
        self.assertFalse(result['ok']); self.assertFalse(result['retryAllowed'])
        self.assertEqual(result['status'],'blocked')
        self.assertEqual(result['permission'],permission)
        self.assertFalse((self.root/'previews').exists())

    def test_unavailable_permission_getter_keeps_successful_normal_export(self):
        permission={'status':'unknown','enabled':None}
        result=self.run_mock({'ok':True,'slides':[1],'slideCount':1,'permission':permission},[1])
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['permission'],permission)
        self.assertTrue(Path(result['previews'][0]['path']).is_file())
        self.assertEqual(self.source.read_bytes(),b'<DOCUMENT SAFER synthetic>')

    def test_unknown_getter_does_not_override_open_or_export_failure(self):
        for status in ('not_checked','unknown'):
            with self.subTest(permission=status):
                permission={'status':status,'enabled':None}
                result=self.run_mock({'ok':False,'code':'office_reference_failed','permission':permission})
                self.assertFalse(result['ok']); self.assertFalse(result['retryAllowed'])
                self.assertFalse(result['rendered'])
                self.assertEqual(result['permission'],permission)
                self.assertFalse((self.root/'previews').exists())
                self.assertEqual(self.source.read_bytes(),b'<DOCUMENT SAFER synthetic>')

    def test_missing_slide_never_publishes_partial_folder(self):
        result=self.run_mock({'ok':True,'slides':[1,2],'slideCount':2},write_images=False)
        self.assertEqual(result['code'],'reference_export_incomplete')
        self.assertFalse((self.root/'previews').exists())

    def test_existing_open_source_requests_screen_route_without_closing_it(self):
        result=self.run_mock({'ok':False,'code':'source_already_open'})
        self.assertFalse(result['ok']); self.assertIn('닫지 않았습니다',result['message'])


class OfficePermissionGetterTests(unittest.TestCase):
    def test_production_permission_check_distinguishes_unknown_false_and_true(self):
        shell=ppt_office_reference._windows_powershell()
        if not shell:
            self.skipTest('PowerShell is needed for the getter-only fixture; Office is not used')
        # Execute the production check against in-memory properties, never a COM
        # application or a document. An explicit true must escape its catch.
        script = r'''
$ErrorActionPreference='Stop'
function Check-Getter($deck) {
  try {
__CHECK__
    return @{continued=$true;permission=$permission}
  } catch {
    return @{continued=$false;code=$_.Exception.Message;permission=$permission}
  }
}
$enabledFailure=[pscustomobject]@{}
$enabledFailure | Add-Member -MemberType ScriptProperty -Name Enabled -Value {throw 'getter unavailable'}
$permissionFailure=[pscustomobject]@{}
$permissionFailure | Add-Member -MemberType ScriptProperty -Name Permission -Value {throw 'getter unavailable'}
@{
  enabledUnavailable=(Check-Getter ([pscustomobject]@{Permission=$enabledFailure}))
  permissionUnavailable=(Check-Getter $permissionFailure)
  missing=(Check-Getter ([pscustomobject]@{}))
  unrestricted=(Check-Getter ([pscustomobject]@{Permission=[pscustomobject]@{Enabled=$false}}))
  restricted=(Check-Getter ([pscustomobject]@{Permission=[pscustomobject]@{Enabled=$true}}))
} | ConvertTo-Json -Depth 5 -Compress
'''.replace('__CHECK__',ppt_office_reference._PERMISSION_CHECK)
        encoded=base64.b64encode(script.encode('utf-16le')).decode('ascii')
        process=subprocess.run([shell,'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                               capture_output=True,timeout=20,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(process.returncode,0,process.stderr.decode(errors='replace'))
        result=json.loads(process.stdout.decode('utf-8-sig'))
        for name in ('enabledUnavailable','permissionUnavailable','missing'):
            self.assertTrue(result[name]['continued'],result[name])
            self.assertEqual(result[name]['permission'],{'status':'unknown','enabled':None})
        self.assertTrue(result['unrestricted']['continued'])
        self.assertEqual(result['unrestricted']['permission'],{'status':'reported','enabled':False})
        self.assertFalse(result['restricted']['continued'])
        self.assertEqual(result['restricted']['code'],'reference_permission_restricted')
        self.assertEqual(result['restricted']['permission'],{'status':'reported','enabled':True})


if __name__=='__main__':
    unittest.main()
