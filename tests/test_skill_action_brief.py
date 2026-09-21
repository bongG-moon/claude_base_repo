"""Observable selection hints and receipts, not assertions of model obedience."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_skill_discovery as discovery
from company_agent.skill_task_context import load_target, skill_brief, MAX_SKILL_BRIEF_CHARS
from company_agent.native_runtime import task_prompt_context, MAX_HOOK_CONTEXT_CHARS, worker_runtime_input
from company_agent.hook_diagnostics import record_hook
from company_agent.skill_workflow import observe, preflight
from company_agent.skill_registry import set_skill_preference
from company_agent.state import load_session


class SkillActionBriefTests(unittest.TestCase):
    def setUp(self):
        self.f = discovery.SkillDiscoveryTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_native_load_action_precedes_route_and_contains_no_body(self):
        context = self.f.context()
        candidate = next(c for g in context['taskSkills']['groups'] if g['name'] == 'html-report' for c in g['candidates'])
        self.assertEqual({'tool': 'Skill', 'skill': 'company-agent:html-report'}, candidate['load'])
        result = task_prompt_context('{"company_agent_route":{"tier":"MEDIUM"}}', json.dumps({'company_agent_runtime': context}, ensure_ascii=False, separators=(',', ':')))
        self.assertLess(result.index('company-agent:html-report'), result.index('company_agent_route'))
        self.assertLessEqual(len(result), MAX_HOOK_CONTEXT_CHARS)
        self.assertNotIn('This overrides the helper-first preparation below.', result)
        self.assertEqual({}, load_session(self.f.sid, self.f.state)['skillWorkflow']['readSkills'])

    def test_native_precedence_cannot_override_selected_project_file(self):
        self.f.skill('custom-reader', '기존 PPT 읽기')
        file = self.f.skill('custom-reader', '기존 PPT 읽기', source='project')
        context = self.f.context('custom-reader 기존 PPT 읽기')
        group = next(g for g in context['taskSkills']['groups'] if g['name'] == 'custom-reader')
        self.assertEqual('unresolved', group['resolution'])
        self.assertTrue(all(c['load']['tool'] == 'Read' for c in group['candidates']))
        chosen = next(c for c in group['candidates'] if c['source'] == 'project')
        set_skill_preference(self.f.state, 'custom-reader', chosen['id'], project_root=self.f.project,
                             plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
        context = self.f.context('custom-reader 기존 PPT 읽기')
        group = next(g for g in context['taskSkills']['groups'] if g['name'] == 'custom-reader')
        self.assertEqual([{'tool': 'Read', 'file_path': str(file)}], [c['load'] for c in group['candidates']])

    def test_personal_registry_file_is_not_invented_native_invocation(self):
        row = {'name': 'reader', 'source': 'personal', 'path': 'C:/personal/reader/SKILL.md', 'invocation': 'reader'}
        self.assertEqual({'tool': 'Read', 'file_path': row['path']}, load_target(row, [row]))

    def test_large_conflict_is_never_presented_as_single_option(self):
        candidates = [{'name': 'reader', 'source': f'source{i}', 'path': 'C:/' + 'a' * 350 + '/SKILL.md',
                       'description': 'description ' * 50} for i in range(10)]
        brief = skill_brief({'taskSkills': {'groups': [{'resolution': 'unresolved', 'candidates': candidates}]}})
        self.assertLessEqual(len(brief), MAX_SKILL_BRIEF_CHARS)
        self.assertNotIn('source0', brief)
        self.assertIn('목록', brief)

    def test_unknown_keyword_is_not_no_skills_and_manual_only_stays_explicit(self):
        self.f.skill('manual-reader', 'PPT 읽기', extra='disable-model-invocation: true\n')
        ctx = self.f.context('PPT 읽기')
        self.assertNotIn('manual-reader', skill_brief(ctx))
        ctx = self.f.context('/manual-reader PPT 읽기')
        self.assertIn('"explicitOnly":true', skill_brief(ctx))
        ctx = self.f.context('zxqv983')
        self.assertIn('목록 준비 실패는 스킬 부재와 다릅니다', skill_brief(ctx))

    def test_successful_load_not_hint_or_failed_tool_records_body(self):
        self.f.context()
        payload = {'hook_event_name': 'PostToolUse', 'session_id': self.f.sid, 'tool_name': 'Skill',
                   'tool_input': {'skill': 'company-agent:html-report'}}
        observe(self.f.state, self.f.project, {**payload, 'tool_response': {'success': False}})
        self.assertNotIn('lastBodyLoad', load_session(self.f.sid, self.f.state)['skillWorkflow'])
        observe(self.f.state, self.f.project, {**payload, 'tool_response': {'success': True}})
        receipt = load_session(self.f.sid, self.f.state)['skillWorkflow']['lastBodyLoad']
        self.assertEqual('Skill', receipt['tool'])
        self.assertEqual('html-report', receipt['name'])
        self.assertEqual(64, len(receipt['sha256']))
        worker = worker_runtime_input(discovery.PLUGIN, self.f.project, {'session_id': self.f.sid,
                     'tool_input': {'subagent_type': 'company-agent:medium-worker', 'prompt': 'HTML 보고서 만들어줘'}})
        worker_text = worker['hookSpecificOutput']['updatedInput']['prompt']
        self.assertTrue(worker_text.startswith('먼저 부모가 선택한'))
        self.assertIn('html-report', worker_text)
        self.assertNotIn('"skillIndex"', worker_text)

    def test_diagnostics_are_bounded_private_and_never_host_acknowledgement(self):
        context = self.f.context()
        context['secret'] = 'DO-NOT-STORE-DOCUMENT'
        text = json.dumps({'company_agent_runtime': context})
        for _ in range(3):
            record_hook(self.f.state, self.f.sid, 'SessionStart', 'started', 0)
            record_hook(self.f.state, self.f.sid, 'SessionStart', 'output-produced', 41, runtime_text=text)
            record_hook(self.f.state, self.f.sid, 'UserPromptSubmit', 'failed', 12, error_type='ValueError')
        state = load_session(self.f.sid, self.f.state)
        diag = state['hookDiagnostics']
        self.assertEqual(2, len(diag))
        self.assertEqual('not-observable', diag['SessionStart']['hostReceipt'])
        self.assertEqual('not-observable', diag['SessionStart']['modelApplied'])
        self.assertEqual('ValueError', diag['UserPromptSubmit']['errorType'])
        self.assertNotIn('DO-NOT-STORE', json.dumps(state))
        self.assertEqual(0, state['mutationCount'])
        with patch('company_agent.hook_diagnostics._locked_session', side_effect=OSError('private details')):
            record_hook(self.f.state, self.f.sid, 'SessionStart', 'started', 0)  # no exception to real work

    def test_preparation_remains_advisory_at_most_once(self):
        self.f.context()
        payload = {'session_id': self.f.sid, 'tool_name': 'Bash', 'tool_input': {'command': 'python arbitrary.py'}}
        result = preflight(self.f.state, self.f.project, payload)
        self.assertNotIn('permissionDecision', result['hookSpecificOutput'])
        self.assertEqual({}, preflight(self.f.state, self.f.project, payload))


if __name__ == '__main__':
    unittest.main()
