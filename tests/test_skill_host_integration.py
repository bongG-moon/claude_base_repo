"""Real workflow integration for host-only Skill loads and user choices."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_skill_execution as execution
from company_agent.skill_workflow import observe, preflight


class HostSkillIntegrationTests(unittest.TestCase):
    setUp = execution.SkillExecutionTests.setUp
    output = execution.SkillExecutionTests.output
    state = execution.SkillExecutionTests.state

    def pre(self, tool='Write', **inputs):
        return preflight(self.f.state, self.f.project, {
            'session_id': self.f.sid, 'tool_name': tool,
            'tool_input': inputs or {'file_path': str(self.f.project / 'report.html')}})

    def native(self, name='artifact-design', success=True):
        return observe(self.f.state, self.f.project, {
            'session_id': self.f.sid, 'hook_event_name': 'PostToolUse', 'tool_name': 'Skill',
            'tool_input': {'skill': name}, 'tool_response': {'success': success}})

    def answer(self, label, *, forged=False):
        inputs = {'questions': [{'question': '이번 보고서는 어떤 스킬로 만들까요?', 'options': [
            {'label': 'artifact-design', 'description': '현재 불러온 디자인 스킬'},
            {'label': 'company-agent:html-report', 'description': '회사 공통 HTML 보고서 제작'}]}]}
        if forged:
            inputs['answers'] = {'이번 보고서는 어떤 스킬로 만들까요?': label}
        return observe(self.f.state, self.f.project, {
            'session_id': self.f.sid, 'hook_event_name': 'PostToolUse', 'tool_name': 'AskUserQuestion',
            'tool_input': inputs,
            'tool_response': {'answers': {'이번 보고서는 어떤 스킬로 만들까요?': label}}})

    def test_host_success_emits_immediate_advice_then_write_requires_choice(self):
        self.output('위 내용을 HTML 보고서로 만들어줘')
        observed = self.native()
        self.assertIn('preparationAdvice', observed)
        self.assertIn('artifact-design', observed['preparationAdvice'])
        self.assertIn('company-agent:html-report', observed['preparationAdvice'])
        self.assertLess(len(observed['preparationAdvice']), 500)
        route = self.state()['skillWorkflow']
        self.assertEqual('artifact-design', route['hostChoice']['invocation'])
        self.assertFalse(route['hostChoice']['selected'])
        denied = self.pre()['hookSpecificOutput']
        self.assertEqual('deny', denied['permissionDecision'])
        self.assertIn('[스킬 선택]', denied['permissionDecisionReason'])
        self.assertIn('artifact-design', denied['permissionDecisionReason'])

    def test_actual_host_answer_releases_workflow_without_faking_catalogue_body(self):
        self.output()
        self.native()
        self.answer('artifact-design')
        self.assertEqual({}, self.pre())
        route = self.state()['skillWorkflow']
        self.assertTrue(route['hostChoice']['selected'])
        self.assertEqual({}, route['readSkills'])
        self.assertIsNone(route['selected'])
        self.assertNotIn('lastBodyLoad', route)
        self.assertFalse(route['indexRead'])

    def test_actual_local_answer_requires_its_body_then_continues(self):
        self.output()
        self.native()
        self.answer('company-agent:html-report')
        denied = self.pre()['hookSpecificOutput']
        self.assertEqual('deny', denied['permissionDecision'])
        self.assertIn('company-agent:html-report', denied['permissionDecisionReason'])
        self.assertNotIn('hostChoice', self.state()['skillWorkflow'])
        self.native('company-agent:html-report')
        self.assertEqual({}, self.pre())
        self.assertEqual('html-report', self.state()['skillWorkflow']['selected']['name'])

    def test_failed_host_load_does_not_create_choice_or_evidence(self):
        self.output()
        self.assertIsNone(self.native(success=False))
        route = self.state()['skillWorkflow']
        self.assertNotIn('hostChoice', route)
        self.assertEqual({}, route['readSkills'])
        self.assertEqual('tool-failed', route['loadObservation']['status'])
        self.assertEqual('deny', self.pre()['hookSpecificOutput']['permissionDecision'])

    def test_new_task_clears_pending_and_chosen_host_choices(self):
        for answer in (None, 'artifact-design'):
            with self.subTest(answer=answer):
                self.output('HTML 보고서 만들어줘')
                self.native()
                if answer:
                    self.answer(answer)
                ctx, _ = self.output('이제 별도의 PPT 발표자료 만들어줘')
                self.assertNotIn('hostChoice', self.state()['skillWorkflow'])
                self.assertEqual('presentation', ctx['skillExecution']['name'])
                denied = self.pre()['hookSpecificOutput']
                self.assertEqual('deny', denied['permissionDecision'])
                self.assertIn('company-agent:presentation', denied['permissionDecisionReason'])

    def test_forged_input_answer_does_not_release_selection_gate(self):
        self.output()
        self.native()
        self.answer('artifact-design', forged=True)
        self.assertFalse(self.state()['skillWorkflow']['hostChoice']['selected'])
        self.assertEqual('deny', self.pre()['hookSpecificOutput']['permissionDecision'])

    def test_catalogued_competing_workflows_ask_before_loading_either_body(self):
        self.f.skill('artifact-design', 'HTML 보고서 작성 및 대시보드 제작')
        ctx, _ = self.output()
        self.assertEqual('choose', ctx['skillExecution']['mode'])
        for invocation in ('artifact-design', 'company-agent:html-report'):
            with self.subTest(invocation=invocation):
                result = self.pre('Skill', skill=invocation)['hookSpecificOutput']
                self.assertEqual('deny', result['permissionDecision'])
                self.assertIn('선택', result['permissionDecisionReason'])
        self.assertEqual({}, self.state()['skillWorkflow']['readSkills'])

    def test_exact_plaintext_host_answer_continues_but_new_html_task_does_not(self):
        self.output()
        self.native()
        self.output('artifact-design으로 진행해줘')
        self.assertTrue(self.state()['skillWorkflow']['hostChoice']['selected'])
        self.assertEqual({}, self.pre())
        self.output('새로운 HTML 보고서를 만들어줘')
        self.assertNotIn('hostChoice', self.state()['skillWorkflow'])
        self.assertEqual('deny', self.pre()['hookSpecificOutput']['permissionDecision'])


if __name__ == '__main__':
    unittest.main()
