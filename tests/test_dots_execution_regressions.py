"""Offline DOTS regressions: observed readiness is not execution or permission.

These synthetic hooks do not reproduce the external host's permission engine,
or establish a cause for the report's option-dependent move results.
"""
import json
import unittest

import test_skill_execution as execution
import test_skill_discovery as discovery
from company_agent import native_runtime
from company_agent.paths import atomic_write_json
from company_agent.skill_workflow import observe, preflight


class DotsExecutionRegressions(unittest.TestCase):
    setUp = execution.SkillExecutionTests.setUp
    output = execution.SkillExecutionTests.output
    state = execution.SkillExecutionTests.state

    def prewrite(self):
        return preflight(self.f.state, self.f.project, {
            'session_id': self.f.sid, 'tool_name': 'Write',
            'tool_input': {'file_path': str(self.f.project / 'report.html')},
        })

    def native_load(self, name='company-agent:html-report', success=True):
        observe(self.f.state, self.f.project, {
            'session_id': self.f.sid, 'hook_event_name': 'PostToolUse',
            'tool_name': 'Skill', 'tool_input': {'skill': name},
            'tool_response': {'success': success},
        })

    def test_unchanged_html_body_is_reused_after_design_answer_without_reload(self):
        for load in (lambda: self.f.read(discovery.PLUGIN / 'skills/html-report/SKILL.md'), self.native_load):
            with self.subTest(load=load.__name__):
                self.f.context(source='startup')
                self.output('HTML 보고서를 만들어줘')
                load()
                old_load = self.state()['skillWorkflow']['lastBodyLoad']
                ctx, _ = self.output('같은 HTML 보고서를 깔끔한 업무형, 한 페이지로 만들어줘')
                self.assertEqual('reuse', ctx['skillExecution']['mode'])
                self.assertEqual('observed-body-load', ctx['skillExecution']['basis'])
                self.assertEqual({}, self.state()['skillWorkflow']['turnLoads'])
                self.assertEqual(old_load, self.state()['skillWorkflow']['lastBodyLoad'])
                self.assertEqual({}, self.prewrite())  # No allow: host permissions still apply.

    def test_terse_design_answer_keeps_body_receipt_without_forcing_reload(self):
        self.output()
        self.native_load()
        old_reads = self.state()['skillWorkflow']['readSkills']
        ctx, _ = self.output('깔끔한 업무형, 한 페이지로 진행해줘')
        self.assertNotEqual('load', ctx['skillExecution']['mode'])
        self.assertEqual(old_reads, self.state()['skillWorkflow']['readSkills'])
        self.assertNotIn('permissionDecision', self.prewrite().get('hookSpecificOutput', {}))

    def test_preparation_block_is_unexecuted_not_a_file_permission_failure(self):
        self.output()
        for _ in range(2):
            result = self.prewrite()['hookSpecificOutput']
            self.assertEqual('deny', result['permissionDecision'])
            self.assertIn('아직 실행하지 않았습니다', result['permissionDecisionReason'])
            self.assertIn('권한 오류가 아닙니다', result['permissionDecisionReason'])
        self.assertFalse((self.f.project / 'report.html').exists())
        self.assertEqual({}, self.state()['skillWorkflow']['readSkills'])
        self.assertEqual(0, self.state()['mutationCount'])

    def test_old_doctor_denial_is_not_an_html_load_or_execution_receipt(self):
        self.output()
        before = self.state()['skillWorkflow']['readSkills']
        observe(self.f.state, self.f.project, {
            'session_id': self.f.sid, 'hook_event_name': 'PostToolUseFailure',
            'tool_name': 'Bash', 'tool_input': {'command': 'business doctor'},
            'tool_response': {'isError': True, 'error': 'Permission denied'},
        })
        self.assertEqual(before, self.state()['skillWorkflow']['readSkills'])
        self.assertEqual('deny', self.prewrite()['hookSpecificOutput']['permissionDecision'])
        self.native_load()
        self.assertEqual({}, self.prewrite())
        self.assertFalse((self.f.project / 'report.html').exists())
        self.assertEqual(0, self.state()['mutationCount'])

    def test_host_rule_reload_acknowledges_prior_body_without_bypassing_failed_load(self):
        self.output()
        self.native_load()
        atomic_write_json(self.f.claude / 'settings.json', {'permissions': {'ask': ['Skill']}})
        ctx, _ = self.output('같은 HTML 보고서를 만들어줘')
        self.assertEqual('host-loading-rules', ctx['skillExecution']['reason'])
        result = self.prewrite()['hookSpecificOutput']
        self.assertEqual('deny', result['permissionDecision'])
        self.assertIn('같은 본문을 읽은 기록', result['permissionDecisionReason'])
        self.assertIn('현재 로드 권한 규칙', result['permissionDecisionReason'])
        self.native_load(success=False)
        self.assertEqual('deny', self.prewrite()['hookSpecificOutput']['permissionDecision'])
        self.native_load()
        self.assertEqual({}, self.prewrite())
        self.output('같은 HTML 보고서를 만들어줘')
        self.assertEqual('deny', self.prewrite()['hookSpecificOutput']['permissionDecision'])

    def test_native_semantics_need_current_invocation_not_just_prior_body(self):
        self.f.skill('native-special', 'uniquevalue', extra='context: fork\n')
        self.output('/native-special uniquevalue')
        self.native_load('native-special')
        ctx, _ = self.output('/native-special uniquevalue')
        self.assertEqual('native-skill-semantics', ctx['skillExecution']['reason'])
        result = self.prewrite()['hookSpecificOutput']
        self.assertEqual('deny', result['permissionDecision'])
        self.assertIn('같은 본문을 읽은 기록', result['permissionDecisionReason'])
        self.assertIn('이번 요청의 native 호출', result['permissionDecisionReason'])
        self.native_load('native-special')
        self.assertEqual({}, self.prewrite())

    def test_compact_still_requires_new_body_evidence(self):
        self.output()
        self.native_load()
        self.f.context(source='compact')
        ctx, _ = self.output('같은 HTML 보고서를 만들어줘')
        self.assertEqual('load', ctx['skillExecution']['mode'])
        result = self.prewrite()['hookSpecificOutput']
        self.assertEqual('deny', result['permissionDecision'])
        self.assertNotIn('같은 본문을 읽은 기록', result['permissionDecisionReason'])

    def assert_evidence_guidance(self, text):
        self.assertIn('미시도/실행 전 차단/실행 후 실패/완료 확인', text)
        self.assertIn('다른 명령의 거절을 아직 시도하지 않은 작업', text)
        self.assertIn('동일 대상·효과는 옵션만 바꾸거나', text)
        self.assertIn('추가 진단·권한 시험은 하지 마세요', text)

    def test_startup_prompt_and_worker_deliver_command_scoped_evidence_guidance(self):
        self.assert_evidence_guidance(self.f.context(source='startup')['instructions'])
        ctx, text = self.output()
        self.assert_evidence_guidance(ctx['instructions'])
        self.assertLessEqual(len(text), execution.MAX_REQUEST_CONTEXT_CHARS)
        worker = native_runtime.worker_runtime_input(discovery.PLUGIN, self.f.project, {
            'session_id': self.f.sid, 'tool_name': 'Agent',
            'tool_input': {'subagent_type': next(iter(native_runtime.COMPANY_WORKERS)), 'prompt': 'HTML 보고서를 만들어줘'},
        })
        self.assert_evidence_guidance(worker['hookSpecificOutput']['updatedInput']['prompt'])
        self.assertNotIn('permissionDecision', worker['hookSpecificOutput'])

    def test_minimal_context_preserves_evidence_without_increasing_budget(self):
        # Exercise the real fallback encoder with fixed synthetic metadata.
        minimal = None
        for padding in range(1000, 3501, 250):
            runtime = {'instructions': 'x' * 8000, 'knowledgeMatches': [], 'personalSkills': [],
                       'project': 'p' * padding, 'stateRoot': 'synthetic-state'}
            encoded = native_runtime._encode_base_runtime(runtime)
            delivered = json.loads(encoded)['company_agent_runtime']
            self.assertLessEqual(len(encoded), native_runtime.MAX_RUNTIME_BASE_CHARS)
            if delivered.get('guidanceMinimal') and not delivered.get('contextStatus'):
                minimal = delivered
                break
        self.assertIsNotNone(minimal)
        self.assert_evidence_guidance(minimal['instructions'])


if __name__ == '__main__':
    unittest.main()
