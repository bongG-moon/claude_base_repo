import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'company-agent-plugin/scripts'))
from company_agent import office_reader as reader
from company_agent.execution_contract import classify_command, safe_permission


class OfficeReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.file=self.root/'한글 문서.xlsx'; self.file.write_bytes(b'synthetic fixture, not a real office file')
        self.spec={'file':str(self.file),'sheet':1,'range':'A1:F50'}

    def response(self):
        return {'ok':True,'items':[{'location':'R1C1','text':'한글 실적 123'}],
                'truncated':False,'coverage':{'kind':'selected-cell-values'}}

    def test_normalize_range_and_document_choices(self):
        self.assertEqual('excel',reader.normalize(self.spec)['kind'])
        self.assertEqual(10000,reader.normalize(self.spec)['maxChars'])
        for suffix,kind,end in (('.csv','excel',None),('.pptx','powerpoint',5),('.docx','word',20)):
            file=self.root/('source'+suffix); file.write_bytes(b'fixture')
            result=reader.normalize({'file':str(file)})
            self.assertEqual(kind,result['kind'])
            if end: self.assertEqual(end,result['end'])

    def test_reject_unbounded_or_executable_specs(self):
        for changes in ({'range':'A1:Z500'},{'range':'A1:B9999999'},{'range':'A1:B0'},
                        {'range':'B2:A1'},{'range':'A1:B2;write-host hacked'},
                        {'file':'relative.xlsx'},{'sheet':True},{'maxChars':20001},
                        {'approved':True},{'command':'anything'},{'start':1}):
            with self.subTest(changes=changes),self.assertRaises((ValueError,TypeError)):
                reader.normalize({**self.spec,**changes})

    def test_protection_refusal_never_opens_or_prompts(self):
        for protection in ('protected','blocked','unknown'):
            with patch.object(reader,'_invoke') as invoke,patch.object(reader,'confirm_action') as confirm:
                result=reader.read_office({**self.spec,'protection':protection})
            self.assertEqual('blocked',result['status']); invoke.assert_not_called(); confirm.assert_not_called()

    def test_cancel_does_not_open_document(self):
        with patch.object(reader,'confirm_action',return_value=False),patch.object(reader,'_invoke') as invoke:
            result=reader.read_office(self.spec)
        self.assertEqual('cancelled',result['status']); invoke.assert_not_called()

    def test_confirmed_read_unicode_no_file_changes_and_no_permission_claim(self):
        before=self.file.read_bytes()
        with patch.object(reader,'confirm_action',return_value=True) as confirm,patch.object(reader,'_invoke',return_value=self.response()):
            result=reader.read_office(self.spec)
        self.assertEqual('read',result['status']); self.assertEqual('한글 실적 123',result['items'][0]['text'])
        self.assertIn('대화 기록',confirm.call_args.args[1])
        self.assertFalse(result['bypassSupported']); self.assertFalse(result['rawContentStored'])
        self.assertEqual('not_proven_by_office_success',result['drmAuthorization'])
        self.assertEqual(before,self.file.read_bytes()); self.assertEqual([self.file],list(self.root.iterdir()))

    def test_protected_or_unknown_helper_result_drops_partial_text(self):
        for code in ('protected_input','protection_unknown','office_read_failed'):
            with patch.object(reader,'confirm_action',return_value=True),patch.object(reader,'_invoke',return_value={'ok':False,'code':code,'items':self.response()['items']}):
                result=reader.read_office(self.spec)
            self.assertFalse(result['ok']); self.assertNotIn('한글 실적',json.dumps(result,ensure_ascii=False))
            self.assertFalse(result['retryAllowed'])

    def test_timeout_never_tries_another_reader(self):
        with patch.object(reader,'confirm_action',return_value=True),patch.object(reader,'_invoke',side_effect=subprocess.TimeoutExpired('fixed reader',60)) as invoke:
            result=reader.read_office(self.spec)
        self.assertEqual('office_timeout',result['code']); invoke.assert_called_once()

    def test_window_start_timeout_never_opens_office(self):
        from company_agent.office_progress import Progress
        reporter = Progress(enabled=False)
        def timeout(*args, **kwargs):
            kwargs['progress'].failure_code = 'confirmation_start_timeout'
            return False
        with patch.object(reader, 'confirm_action', side_effect=timeout), patch.object(reader, '_invoke') as invoke:
            result = reader.read_office(self.spec, progress=reporter)
        invoke.assert_not_called()
        self.assertEqual('confirmation_start_timeout', result['code'])
        self.assertEqual('confirmation_start', result['diagnostics']['progress']['lastStage'])
        self.assertNotIn('dependencies', result['diagnostics']['progress']['stageMs'])

    def test_helper_close_timeout_does_not_claim_a_successful_read(self):
        def timeout(request, *, progress):
            progress.begin('read')
            progress.begin('close')
            raise subprocess.TimeoutExpired('fixed reader', 60)
        with patch.object(reader, 'confirm_action', return_value=True), patch.object(reader, '_invoke', side_effect=timeout):
            result = reader.read_office(self.spec)
        self.assertEqual('office_timeout', result['code'])
        self.assertEqual('close', result['stage'])
        self.assertNotIn('items', result)

    def test_changed_source_discards_response(self):
        def changed(request, **kwargs):
            self.file.write_bytes(b'changed by fixture')
            return self.response()
        with patch.object(reader,'confirm_action',return_value=True),patch.object(reader,'_invoke',side_effect=changed):
            result=reader.read_office(self.spec)
        self.assertEqual('source_changed',result['code']); self.assertNotIn('items',result)

    def test_read_command_not_mutation_but_never_auto_approved(self):
        cmd=f'"{sys.executable}" -B "{ROOT / "company-agent-plugin/scripts/harness_cli.py"}" business office-read --spec "{self.root / "request.json"}"'
        self.assertEqual('read_only',classify_command(cmd))
        self.assertIsNone(safe_permission({'hook_event_name':'PermissionRequest','tool_name':'Bash','tool_input':{'command':cmd}},self.root))
        self.assertEqual('unknown',classify_command(cmd+' --approved true'))

    def test_helper_transport_is_utf8_fixed_and_bounded(self):
        proc=subprocess.CompletedProcess([],0,json.dumps(self.response(),ensure_ascii=False).encode('utf-8'),b'')
        with patch.object(reader, 'run_helper',return_value=proc) as run:
            result=reader._invoke(reader.normalize(self.spec))
        self.assertEqual('한글 실적 123',result['items'][0]['text'])
        command=run.call_args.args[0]
        self.assertTrue(command[-1].endswith('Read-CompanyExcel.py'))
        self.assertIn('-E',command)
        self.assertIn('-P',command)
        self.assertNotIn('-Command',command)
        self.assertEqual(60,run.call_args.kwargs['timeout'])
        self.assertEqual('excel',json.loads(run.call_args.args[1])['kind'])

    def test_helper_rejects_bad_request_before_any_office_launch(self):
        script=ROOT/'company-agent-plugin/scripts/Read-CompanyOffice.py'
        proc=subprocess.run([sys.executable,'-E','-P',str(script)],
                            input=b'{"command":"invalid"}',capture_output=True,timeout=10)
        self.assertEqual(0,proc.returncode,proc.stderr)
        self.assertEqual('invalid_request',json.loads(proc.stdout.decode('utf-8-sig'))['code'])

    def test_skill_is_reading_only_and_preserves_other_workflows(self):
        text=(ROOT/'company-agent-plugin/skills/office-reader/SKILL.md').read_text(encoding='utf-8')
        self.assertIn('not a replacement',text)
        self.assertIn('Use the shipped bounded reader and its supported options',text)
        self.assertIn('Reading alone needs no',text)

    def test_typed_spec_and_read_do_not_create_verification_work(self):
        from company_agent.state import begin_turn,record_activity,stop_decision
        root=self.root/'state'; (root/'tmp').mkdir(parents=True)
        begin_turn('read-doc','MEDIUM',False,[],root)
        state=record_activity({'session_id':'read-doc','tool_name':'Write','tool_input':{
            'file_path':str(root/'tmp/office-read-preview.json'),'content':json.dumps(self.spec)}},root)
        self.assertEqual(0,state['mutationCount'])
        self.assertNotEqual('block',stop_decision({'session_id':'read-doc'},root).get('decision'))
        state=record_activity({'session_id':'read-doc','tool_name':'Write','tool_input':{
            'file_path':str(root/'tmp/office-read-preview.json'),'content':json.dumps({**self.spec,'body':'not metadata'})}},root)
        self.assertEqual(1,state['mutationCount'])


if __name__=='__main__': unittest.main()
