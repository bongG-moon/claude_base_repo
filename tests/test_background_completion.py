import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'company-agent-plugin/scripts'))
from company_agent.state import begin_turn, record_activity, stop_decision, load_session, mark_verified
from company_agent.background_work import is_running


class BackgroundCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.session='background-test'
        begin_turn(self.session,'MEDIUM',True,(),self.root)
        self.activity('Write',{'file_path':'report-job.json'})

    def activity(self,tool,inputs=None,response=None,**extra):
        return record_activity({'session_id':self.session,'hook_event_name':'PostToolUse',
            'tool_name':tool,'tool_input':inputs or {},'tool_response':response,**extra},self.root)

    def stop(self,**extra):
        return stop_decision({'session_id':self.session,**extra},self.root)

    def start_worker(self):
        self.activity('Agent',{'run_in_background':True}, {'isAsync':True,'agentId':'worker-1'})

    def test_running_registry_does_not_spend_retries_or_forge_success(self):
        before=load_session(self.session,self.root)
        for _ in range(4):
            self.assertEqual({},self.stop(background_tasks=[{'id':'worker-1','type':'subagent','status':'running'}],stop_hook_active=True))
        after=load_session(self.session,self.root)
        self.assertEqual(before,after)
        self.assertIsNone(after['verification'])
        self.assertEqual('block',self.stop(background_tasks=[])['decision'])

    def test_legacy_launch_timeout_then_completion_requires_real_check(self):
        self.start_worker()
        self.assertEqual({},self.stop())
        self.activity('TaskOutput',{'task_id':'worker-1'},{'retrieval_status':'timeout','task':{'status':'running'}})
        self.assertEqual({},self.stop(stop_hook_active=True))
        self.assertEqual(0,load_session(self.session,self.root)['stopRetryCount'])
        self.activity('TaskOutput',{'task_id':'worker-1'},{'task':{'status':'completed'}})
        self.assertEqual('block',self.stop()['decision'])
        mark_verified(self.session,'pass','fixture content checked',self.root)
        self.assertEqual({},self.stop())

    def test_terminal_failure_is_not_success(self):
        self.start_worker()
        self.activity('TaskOutput',{'task_id':'worker-1'},{'task':{'status':'failed'}})
        self.assertEqual('block',self.stop()['decision'])
        self.assertIsNone(load_session(self.session,self.root)['verification'])

    def test_current_empty_registry_overrides_old_receipt(self):
        self.start_worker()
        self.assertEqual('block',self.stop(background_tasks=[])['decision'])

    def test_running_after_first_correction_preserves_budget(self):
        self.stop()
        self.start_worker()
        for _ in range(3): self.assertEqual({},self.stop(stop_hook_active=True))
        self.assertEqual(1,load_session(self.session,self.root)['stopRetryCount'])

    def test_old_receipts_monitors_and_malformed_fields_do_not_defer(self):
        self.assertFalse(is_running({}, {'backgroundWork':{'old':time.time()-1801}}))
        for tasks in ([{'id':'m','type':'monitor','status':'running'}],
                      [{'id':'a','type':'subagent','status':'completed'}],
                      [{'id':'a','type':{},'status':[]}], [None]):
            self.assertFalse(is_running({'background_tasks':tasks},{}))

    def test_failed_launch_does_not_create_wait_receipt(self):
        self.activity('Agent',{'run_in_background':True},{'agentId':'worker-1'},error='prompt is required')
        self.assertEqual('block',self.stop()['decision'])

    def test_no_worker_prompt_or_output_is_saved(self):
        self.activity('Agent',{'prompt':'PRIVATE PROMPT','run_in_background':True},
                      {'isAsync':True,'agentId':'worker-1','content':'PRIVATE RESULT'})
        state=load_session(self.session,self.root)
        self.assertNotIn('PRIVATE',json.dumps(state))
        self.assertEqual(['worker-1'],list(state['backgroundWork']))


if __name__=='__main__': unittest.main()
