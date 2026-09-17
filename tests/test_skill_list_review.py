"""List use, not a PPT blacklist: bounded correction and genuine load evidence."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_skill_execution as execution
import test_skill_discovery as discovery
from company_agent.paths import atomic_write_json, atomic_write_text
from company_agent.skill_workflow import observe, preflight
from company_agent.state import stop_decision


class ListReviewTests(unittest.TestCase):
    setUp = execution.SkillExecutionTests.setUp
    output = execution.SkillExecutionTests.output
    state = execution.SkillExecutionTests.state

    def pre(self, tool='Bash', **inputs):
        return preflight(self.f.state, self.f.project, {'session_id': self.f.sid,
            'tool_name': tool, 'tool_input': inputs or {'command': 'unzip -p document.pptx'}})

    def native_skill(self, name, success=True):
        observe(self.f.state, self.f.project, {'session_id': self.f.sid, 'hook_event_name': 'PostToolUse',
            'tool_name': 'Skill', 'tool_input': {'skill': name}, 'tool_response': {'success': success}})

    def test_ignored_list_redirects_once_then_native_skill_resumes(self):
        self.output()
        first = self.pre()['hookSpecificOutput']
        self.assertEqual('deny', first['permissionDecision'])
        self.assertIn('아직 실행하지 않았습니다', first['permissionDecisionReason'])
        self.assertIn('company-agent:office-reader', first['permissionDecisionReason'])
        self.assertNotIn('permissionDecision', self.pre('Skill', skill='company-agent:office-reader'))
        self.native_skill('company-agent:office-reader')
        self.assertEqual({}, self.pre())
        self.assertEqual('skill-loaded', self.state()['skillWorkflow']['reviewCheckpoint']['status'])
        self.assertEqual({}, stop_decision({'session_id': self.f.sid}, self.f.state))

    def test_happy_path_loads_only_skill_not_entire_catalogue(self):
        self.output()
        self.native_skill('company-agent:office-reader')
        self.assertEqual({}, self.pre())
        route = self.state()['skillWorkflow']
        self.assertFalse(route['indexRead'])
        self.assertNotIn('reviewCheckpoint', route)
        self.assertEqual('office-reader', route['selected']['name'])

    def test_unrelated_keyword_miss_can_find_other_skill_from_full_list(self):
        file = self.f.skill('thermal-helper', 'Convert temperatures between Celsius and Fahrenheit')
        ctx, _ = self.output('섭씨를 화씨로 바꿔줘')
        self.assertEqual('review', ctx['skillExecution']['mode'])
        first = self.pre('Write', file_path=str(self.f.project / 'temperature.txt'))
        self.assertEqual('deny', first['hookSpecificOutput']['permissionDecision'])
        self.assertNotIn('office-reader', first['hookSpecificOutput']['permissionDecisionReason'])
        self.f.read(Path(ctx['skillSelection']['catalog']['path']))
        self.f.read(file)
        self.assertEqual('thermal-helper', self.state()['skillWorkflow']['selected']['name'])
        self.assertEqual({}, self.pre('Write', file_path=str(self.f.project / 'temperature.txt')))

    def test_no_relevant_skill_after_list_read_needs_no_extra_command(self):
        ctx, _ = self.output('2 더하기 3')
        self.f.read(Path(ctx['skillSelection']['catalog']['path']))
        self.assertEqual({}, self.pre())
        self.assertIsNone(self.state()['skillWorkflow']['selected'])
        ctx, _ = self.output('이번에는 4 더하기 5')
        self.assertTrue(ctx['skillExecution']['catalogReviewed'])
        self.assertEqual({}, self.pre('Write', file_path=str(self.f.project / 'answer.txt')))

    def test_ignored_correction_does_not_deadlock_or_claim_success(self):
        self.output()
        self.assertEqual('deny', self.pre()['hookSpecificOutput']['permissionDecision'])
        for tool in ('Bash', 'Write', 'Edit', 'Bash'):
            self.assertEqual({}, self.pre(tool))
        route = self.state()['skillWorkflow']
        self.assertEqual('unconfirmed-limit-reached', route['reviewCheckpoint']['status'])
        self.assertIsNone(route['selected'])
        self.assertFalse(route['indexRead'])
        self.assertEqual({}, route['readSkills'])
        self.assertEqual({}, stop_decision({'session_id': self.f.sid}, self.f.state))

    def test_recovery_reads_and_questions_are_never_blocked(self):
        self.output()
        for tool in ('Read', 'Skill', 'Glob', 'Grep', 'AskUserQuestion'):
            self.assertEqual({}, self.pre(tool))
        self.assertNotIn('reviewCheckpoint', self.state()['skillWorkflow'])

    def test_startup_and_prompt_do_not_describe_a_denied_tool_as_executed(self):
        startup = self.f.context(source='startup')
        self.assertNotIn('Preparation advice never blocks execution', startup['instructions'])
        self.assertIn('tool did NOT run', startup['instructions'])
        ctx, _ = self.output()
        self.assertIn('[스킬 목록 확인 1회]는 도구 미실행', ctx['instructions'])

    def test_empty_actual_catalogue_never_forces_a_skill(self):
        plugin = self.f.root / 'empty-plugin'
        atomic_write_json(plugin / '.claude-plugin/plugin.json', {'name': 'empty-plugin', 'version': '1.0.0'})
        with patch.object(discovery, 'PLUGIN', plugin):
            ctx, text = self.output()
        self.assertEqual('general', ctx['skillExecution']['mode'])
        self.assertEqual(0, ctx['skillSelection']['catalog']['count'])
        self.assertNotIn('company-agent:office-reader', text)
        self.assertEqual({}, self.pre())

    def test_manual_only_catalogue_not_automatically_executed(self):
        plugin = self.f.root / 'empty-plugin'
        atomic_write_json(plugin / '.claude-plugin/plugin.json', {'name': 'empty-plugin', 'version': '1.0.0'})
        self.f.skill('manual-ppt', 'Read PPT files', extra='disable-model-invocation: true\n')
        with patch.object(discovery, 'PLUGIN', plugin):
            ctx, _ = self.output()
        self.assertEqual('general', ctx['skillExecution']['mode'])
        self.assertEqual({}, self.pre())
        self.assertIsNone(self.state()['skillWorkflow']['selected'])

    def test_failed_skill_is_not_selection_and_does_not_force_unknown_name(self):
        self.output()
        self.native_skill('company', success=False)
        self.assertEqual('tool-failed', self.state()['skillWorkflow']['loadObservation']['status'])
        first = self.pre()['hookSpecificOutput']
        self.assertEqual('deny', first['permissionDecision'])
        self.assertIn('company-agent:office-reader', first['permissionDecisionReason'])
        self.assertNotIn('"skill":"company"', first['permissionDecisionReason'])

    def test_host_native_skill_outside_local_catalogue_is_respected(self):
        self.output('그림을 설명해줘')
        self.native_skill('native-drawing-helper')
        self.assertEqual({}, self.pre())
        route = self.state()['skillWorkflow']
        self.assertEqual('native-skill-outside-catalog', route['loadObservation']['status'])
        self.assertIsNone(route['selected'])
        self.assertEqual({}, route['readSkills'])
        ctx, _ = self.output('이제 PPT 내용 읽기')
        self.assertEqual('load', ctx['skillExecution']['mode'])

    def test_partial_or_failed_read_is_not_full_list_review(self):
        ctx, _ = self.output('관련 없는 질문')
        file = Path(ctx['skillSelection']['catalog']['path'])
        observe(self.f.state, self.f.project, {'session_id': self.f.sid, 'hook_event_name': 'PostToolUse',
            'tool_name': 'Read', 'tool_input': {'file_path': str(file)},
            'tool_response': {'file': {'content': file.read_text(encoding='utf-8').splitlines()[0], 'startLine': 1}}})
        self.assertFalse(self.state()['skillWorkflow']['indexRead'])
        self.assertEqual('deny', self.pre()['hookSpecificOutput']['permissionDecision'])

    def test_removed_hint_does_not_force_a_nonexistent_skill(self):
        file = self.f.skill('unique-helper', 'uniquetask')
        self.output('uniquetask')
        file.unlink()
        self.assertEqual({}, self.pre())
        ctx, _ = self.output('uniquetask')
        self.assertEqual('review', ctx['skillExecution']['mode'])
        self.assertNotIn('unique-helper', self.pre()['hookSpecificOutput']['permissionDecisionReason'])

    def test_one_corrective_action_for_ppt_html_and_custom_skills(self):
        for prompt in ('PPT 읽기', 'HTML 보고서 만들기', '유일한새작업'):
            if prompt == '유일한새작업':
                self.f.skill('new-helper', '유일한새작업')
            self.output(prompt)
            self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])
            self.assertEqual({}, self.pre('Bash'))

    def test_selection_evidence_is_invalidation_safe(self):
        file = self.f.skill('unique-helper', 'uniquetask')
        self.output('uniquetask')
        self.f.read(file)
        self.assertEqual({}, self.pre())
        atomic_write_text(file, file.read_text(encoding='utf-8') + '\nchanged')
        ctx, _ = self.output('uniquetask')
        self.assertEqual('load', ctx['skillExecution']['mode'])
        self.assertIsNone(self.state()['skillWorkflow']['selected'])
        self.assertEqual('deny', self.pre()['hookSpecificOutput']['permissionDecision'])

    def test_no_raw_prompt_command_or_body_is_persisted_by_correction(self):
        self.output('PPT 읽어줘 PRIVATE_REQUEST_TEXT')
        self.pre(command='python -c "PRIVATE_TOOL_INPUT"')
        serialized = json.dumps(self.state(), ensure_ascii=False)
        self.assertNotIn('PRIVATE_REQUEST_TEXT', serialized)
        self.assertNotIn('PRIVATE_TOOL_INPUT', serialized)
        self.assertNotIn('Presentations.Open', serialized)


if __name__ == '__main__':
    unittest.main()
