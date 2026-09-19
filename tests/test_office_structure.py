import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'company-agent-plugin/scripts'))
sys.path.insert(0,str(ROOT/'scripts'))
from company_agent.office_structure import extract_document
from company_agent import office_reader, native_runtime
import office_read_test as kit


def collection(values):
    return NS(Count=len(values),Item=lambda i:values[i-1])


def text_shape(text):
    return NS(Type=17,Left=30,Top=40,Width=300,Height=50,HasTable=0,HasTextFrame=-1,
              TextFrame=NS(TextRange=NS(Text=text)))


class StructureTests(unittest.TestCase):
    def test_shared_extractor_has_no_standalone_drift(self):
        shared=(ROOT/'company-agent-plugin/scripts/company_agent/office_structure.py').read_text(encoding='utf-8').strip()
        self.assertIn(shared,(ROOT/'scripts/office_read_test.py').read_text(encoding='utf-8'))

    def test_four_slides_and_group_coordinates(self):
        group=NS(Type=6,GroupItems=collection([text_shape('그룹 안의 글자')]))
        doc=NS(Slides=collection([NS(Shapes=collection([group,text_shape(str(i))])) for i in range(4)]))
        result=extract_document(doc,{'kind':'powerpoint','start':1,'end':4,'maxChars':10000})
        self.assertEqual(4,result['coverage']['total'])
        self.assertFalse(result['truncated'])
        self.assertEqual({1,2,3,4},{i['structure']['slide'] for i in result['items']})
        self.assertEqual(30,result['items'][0]['structure']['bounds']['left'])
        self.assertIn('/group:1',result['items'][0]['location'])

    def test_partial_range_continuation_not_whole_document(self):
        doc=NS(Slides=collection([NS(Shapes=collection([text_shape(str(i))])) for i in range(4)]))
        result=extract_document(doc,{'kind':'powerpoint','start':1,'end':2,'maxChars':10000})
        self.assertTrue(result['truncated'])
        self.assertEqual(3,result['coverage']['nextStart'])
        self.assertEqual(2,result['coverage']['completeThrough'])
        result=extract_document(doc,{'kind':'powerpoint','start':1,'end':4,'maxChars':1})
        self.assertEqual(1,result['coverage']['nextStart'])
        self.assertTrue(result['coverage']['limitReached'])

    def test_word_table_coordinates_and_heading(self):
        cell=NS(RowIndex=2,ColumnIndex=3,Range=NS(Tables=collection([NS(Range=NS(Start=42))])))
        area=NS(Text='실적 100\r',Start=58,Information=lambda code:2 if code==3 else True,Cells=collection([cell]))
        doc=NS(Paragraphs=collection([NS(Range=area,OutlineLevel=2)]))
        result=extract_document(doc,{'kind':'word','start':1,'end':1,'maxChars':10000})
        self.assertEqual({'type':'table-cell','paragraph':1,'characterStart':58,'page':2,'headingLevel':2,
                          'row':2,'column':3,'table':'table-at:42'},result['items'][0]['structure'])

    def test_layout_permission_denial_is_not_swallowed(self):
        class Denied:
            @property
            def Left(self): raise PermissionError('sensitive')
        doc=NS(Slides=collection([NS(Shapes=collection([Denied()]))]))
        with self.assertRaises(PermissionError):
            extract_document(doc,{'kind':'powerpoint','start':1,'end':1,'maxChars':100})

    def test_word_end_marker_without_cell_does_not_break_read(self):
        area=NS(Text='\r',Information=lambda code:True,Cells=collection([]))
        result=extract_document(NS(Paragraphs=collection([NS(Range=area)])),
                                {'kind':'word','start':1,'end':1,'maxChars':100})
        self.assertTrue(result['ok'])

    def test_direct_command_has_no_request_file_and_remains_read_only(self):
        from company_agent.cli import build_parser
        from company_agent.business import dispatch
        from company_agent.execution_contract import classify_command
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.pptx'; path.write_bytes(b'synthetic')
            args=build_parser().parse_args(['business','office-read','--file',str(path),'--end','4','--expected-count','4'])
            with patch.object(office_reader,'read_office',return_value={'ok':True}) as read:
                dispatch(args)
            self.assertEqual({'file':str(path),'end':4,'expectedCount':4},read.call_args.args[0])
            self.assertEqual([path],list(Path(folder).iterdir()))
            prefix=f'"{sys.executable}" -B "{ROOT / "company-agent-plugin/scripts/harness_cli.py"}"'
            self.assertEqual('read_only',classify_command(prefix+f' business office-read --file "{path}" --end 4'))
            self.assertEqual('unknown',classify_command(prefix+f' business office-read --file "{path}" --approved true'))

    def test_module_cli_really_runs_from_scripts_directory(self):
        env={**os.environ,'PYTHONIOENCODING':'cp949:strict'}
        result=subprocess.run([sys.executable,'-B','-m','company_agent.cli','business','office-read','--help'],
                              cwd=ROOT/'company-agent-plugin/scripts',env=env,capture_output=True,timeout=15)
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertIn(b'--file',result.stdout)

    def test_runtime_guidance_cannot_erase_cli(self):
        runtime={'cliCommand':'powershell -File C:/installed/run.ps1 -Mode Cli','stateRoot':'C:/state',
                 'knowledgeMatches':[],'personalSkills':[],'instructions':'a'*10000}
        result=json.loads(native_runtime._encode_runtime(runtime))['company_agent_runtime']
        self.assertEqual('C:/state',result['stateRoot'])
        self.assertIn('cliCommand',result)
        self.assertTrue(result['guidanceCondensed'])

    def test_count_mismatch_is_partial_not_drm_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.pptx'; path.write_bytes(b'synthetic')
            output={'ok':True,'items':[],'truncated':False,'coverage':{'total':1}}
            with patch.object(office_reader,'authorize',return_value=None),patch.object(office_reader,'_invoke',return_value=output):
                result=office_reader.read_office({'file':str(path),'expectedCount':4})
            self.assertEqual('partial',result['status'])
            self.assertTrue(result['diagnostics']['countMismatch'])
            self.assertIn('단정할 수 없습니다',result['message'])

    def test_pdf_non_pdf_and_stream_error_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.pdf'; path.write_bytes(b'not a pdf')
            result=kit.read_once(path)
            self.assertFalse(result['pdfDiagnostics']['pdfHeaderFound'])
            self.assertIn('헤더',result['message'])
            path.write_bytes(b'%PDF-1.7\nmalformed')
            result=kit.read_once(path)
            self.assertFalse(result['ok'])
            self.assertTrue(result['pdfDiagnostics']['pdfHeaderFound'])
            self.assertFalse(result['pdfDiagnostics']['eofMarkerFound'])
            self.assertIn('PDF 내부 구조',result['message'])
            self.assertNotIn('parts',result)


if __name__=='__main__': unittest.main()
