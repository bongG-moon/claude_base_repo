from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'company-agent-plugin/scripts'))
from company_agent.runtime_diagnostics import classifier_unavailable, failure_hint, inspect_runtime
from company_agent.state import begin_turn, record_activity, stop_decision


class RuntimeDiagnosticsTests(unittest.TestCase):
    def payload(self):
        return {'session_id':'approval-test','hook_event_name':'PostToolUseFailure','tool_name':'Bash',
                'tool_input':{'command':'python ppt_com.py'},
                'error':'HCP-LLM-Latest[1m] is temporarily unavailable (timed out), so auto mode cannot determine the safety of Bash right now. Wait a moment and then try this action again.'}

    def test_exact_classifier_failure_is_not_a_business_change_or_learning_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            begin_turn('approval-test','MEDIUM',False,[],root)
            state=record_activity(self.payload(),root)
            self.assertEqual(0,state['mutationCount'])
            self.assertEqual(0,state['taskFailureCount'])
            self.assertEqual(0,state['taskToolCount'])
            self.assertTrue(state['approvalUnavailable'])
            self.assertNotEqual('block',stop_decision({'session_id':'approval-test'},root).get('decision'))
            self.assertNotIn('HCP-LLM',json.dumps(state))
            record_activity({'session_id':'approval-test','tool_name':'Write',
                             'tool_input':{'file_path':str(root/'report.md')}},root)
            state=record_activity(self.payload(),root)
            self.assertEqual(1,state['mutationCount'])
            self.assertIsNone(state['verification'])

    def test_does_not_reclassify_arbitrary_timeout_or_tool_output(self):
        for changes in ({'error':'PowerPoint operation timed out'}, {'error':'Permission denied'},
                        {'hook_event_name':'PostToolUse'}, {'tool_name':'Read'},
                        {'error':'Quoted log: '+self.payload()['error']}):
            self.assertFalse(classifier_unavailable({**self.payload(),**changes}))

    def test_notice_is_concise_and_never_authorizes_bypass(self):
        result=failure_hint(self.payload())
        self.assertLess(len(result['message']),80)
        self.assertIn('never for a denial',result['instruction'])
        self.assertIn('Native UI errors cannot be hidden',result['instruction'])

    def test_launcher_root_cause_remains_unconfirmed(self):
        result=failure_hint({**self.payload(),'error':'인덱스가 배열 범위를 벗어났습니다.'})
        self.assertEqual('unknown',result['executionState'])
        self.assertIn('Root cause is not confirmed',result['instruction'])

    def test_runtime_inspector_reads_paths_without_running_claude(self):
        if sys.platform!='win32':
            return
        result=inspect_runtime()
        self.assertTrue(result['ok'],result)
        self.assertFalse(result['settingsChanged'])
        self.assertFalse(result['claudeProcessesLaunched'])
        self.assertIsInstance(result['candidates'],list)


if __name__=='__main__': unittest.main()
