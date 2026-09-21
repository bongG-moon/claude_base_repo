"""Current-task workflow preparation and genuine load evidence, not a blacklist."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_skill_execution as execution
import test_skill_discovery as discovery
from company_agent.paths import atomic_write_json, atomic_write_text
from company_agent.skill_workflow import observe, preflight, select, choose, _discovery_command
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
        self.assertLess(len(first['permissionDecisionReason']), 250)
        self.assertNotIn(str(self.state()['skillWorkflow']['catalog']), first['permissionDecisionReason'])
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
        self.assertNotIn('permissionDecision', first['hookSpecificOutput'])
        self.assertNotIn('office-reader', first['hookSpecificOutput']['additionalContext'])
        self.assertEqual('advised', self.state()['skillWorkflow']['reviewCheckpoint']['status'])
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

    def test_retry_without_loading_does_not_bypass_definite_workflow(self):
        self.output()
        self.assertEqual('deny', self.pre()['hookSpecificOutput']['permissionDecision'])
        for tool in ('Bash', 'Write', 'Edit', 'Bash'):
            self.assertEqual('deny', self.pre(tool)['hookSpecificOutput']['permissionDecision'])
        route = self.state()['skillWorkflow']
        self.assertEqual('redirected', route['reviewCheckpoint']['status'])
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
        self.assertIn('폴더 조회·일반 목록 비교는 차단하지 않습니다', startup['instructions'])
        ctx, _ = self.output()
        self.assertIn('[스킬 확인]', ctx['instructions'])
        self.assertIn('이번 작업의 본문', ctx['instructions'])
        self.assertIn('도구 미실행', ctx['instructions'])

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
        self.assertNotIn('permissionDecision', self.pre()['hookSpecificOutput'])
        self.assertFalse(self.state()['skillWorkflow']['indexRead'])

    def test_removed_hint_does_not_force_a_nonexistent_skill(self):
        file = self.f.skill('unique-helper', 'uniquetask')
        self.output('uniquetask')
        file.unlink()
        self.assertEqual({}, self.pre())
        ctx, _ = self.output('uniquetask')
        self.assertEqual('review', ctx['skillExecution']['mode'])
        self.assertNotIn('unique-helper', self.pre()['hookSpecificOutput']['additionalContext'])

    def test_reported_initial_listing_never_blocks_or_consumes_skill_correction(self):
        command = 'ls -la "claude-code-starter-main/" 2>/dev/null || ls -la claude-code-starter-main/ 2>/dev/null; pwd'
        for prompt in ('이 폴더를 확인해줘', 'PPT 읽어줘'):
            self.output(prompt)
            self.assertEqual({}, self.pre(command=command))
            self.assertNotIn('reviewCheckpoint', self.state()['skillWorkflow'])
            self.assertIsNone(self.state()['skillWorkflow']['selected'])
        # Listing does not load the relevant Skill or exempt a subsequent reader.
        self.assertEqual('deny', self.pre(command='python reader.py')['hookSpecificOutput']['permissionDecision'])

    def test_general_write_does_not_require_redundant_catalog_read(self):
        self.output('이 폴더에 온도 변환 코드를 작성해줘')
        first = self.pre('Write', file_path=str(self.f.project / 'convert.py'))['hookSpecificOutput']
        self.assertNotIn('permissionDecision', first)
        self.assertLess(len(first['additionalContext']), 230)
        with patch('company_agent.skill_workflow._snapshot', side_effect=AssertionError('must not rescan')):
            self.assertEqual({}, self.pre('Write'))
        route = self.state()['skillWorkflow']
        self.assertEqual('advised', route['reviewCheckpoint']['status'])
        self.assertFalse(route['indexRead'])
        self.assertEqual({}, route['readSkills'])

    def test_literal_discovery_exemption_never_matches_execution_or_output_writes(self):
        for command in ('pwd && ls -la "한글 폴더/"', 'ls -la', 'git status --short',
                        'Get-ChildItem -LiteralPath "C:/한글 폴더" -Name; Get-Location'):
            self.assertTrue(_discovery_command(command), command)
        for command in ('ls; python read.py', 'ls || unzip -p file.pptx', 'ls > output.txt',
                        'ls &> output.txt', 'ls $(python read.py)', 'ls `whoami`',
                        'ls | cat', 'ls 2> errors.txt', 'ls; rm file', 'ls &', 'ls "unterminated',
                        'ls --block-size=1; python script.py', 'pwd\npython read.py'):
            self.assertFalse(_discovery_command(command), command)

    def test_definite_ppt_html_and_custom_workflows_need_their_real_body(self):
        for prompt in ('PPT 읽기', 'HTML 보고서 만들기', '유일한새작업'):
            if prompt == '유일한새작업':
                self.f.skill('new-helper', '유일한새작업')
            self.output(prompt)
            self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])
            self.assertEqual('deny', self.pre('Bash')['hookSpecificOutput']['permissionDecision'])

    def test_exact_html_followup_needs_html_body_despite_earlier_catalogue_and_office_load(self):
        ctx, _ = self.output('@AI_CAMP_지원현황.xlsx 여기 파일 내용읽고 어떤 정보들 있는지 확인해줘')
        self.f.read(Path(ctx['skillSelection']['catalog']['path']))
        self.native_skill('company-agent:office-reader')
        self.assertEqual({}, self.pre())
        ctx, _ = self.output('위 내용을 바탕으로 신청자 현황과 강사 현황을 볼 수 있는 html을 만들고싶어')
        self.assertEqual('load', ctx['skillExecution']['mode'])
        self.assertEqual('html-report', ctx['skillExecution']['name'])
        self.assertTrue(self.state()['skillWorkflow']['indexRead'])
        for _ in range(2):
            result = self.pre('Write', file_path=str(self.f.project / 'report.html'))['hookSpecificOutput']
            self.assertEqual('deny', result['permissionDecision'])
            self.assertIn('company-agent:html-report', result['permissionDecisionReason'])
        # Reloading the previous workflow (or just the index) is not HTML preparation.
        self.native_skill('company-agent:office-reader')
        self.f.read(Path(ctx['skillSelection']['catalog']['path']))
        self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])
        self.native_skill('company-agent:html-report')
        self.assertEqual({}, self.pre('Write'))
        self.assertEqual({}, stop_decision({'session_id': self.f.sid}, self.f.state))

    def test_native_skill_not_in_catalogue_cannot_replace_definite_html_workflow(self):
        self.output('HTML 보고서를 만들어줘')
        self.native_skill('native-unrelated-helper')
        self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])

    def test_explicit_native_skill_outside_catalogue_is_not_overridden(self):
        self.output('/native-html-helper HTML 보고서를 만들어줘')
        self.native_skill('native-html-helper')
        self.assertEqual({}, self.pre('Write'))

    def test_naturally_named_host_skill_is_respected_only_after_current_native_success(self):
        for prompt in ('HTML 보고서를 만들어줘. 사용 가능한 native-report-builder 스킬로 해줘',
                       'Create an HTML report using the native-report-builder skill'):
            with self.subTest(prompt=prompt):
                self.output(prompt)
                self.native_skill('native-report-builder', success=False)
                self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])
                self.native_skill('native-report-builder')
                self.assertEqual({}, self.pre('Write'))
                self.output('새 HTML 보고서를 만들어줘')
                self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])

    def test_negated_and_diagnostic_workflow_mentions_are_advisory_not_mandatory(self):
        for prompt in ('HTML 보고서는 필요 없고 이 폴더에 온도 변환 코드를 작성해줘',
                       'PPT 읽는 코드에서 AttributeError가 나는데 버그를 고쳐줘',
                       'Do not create an HTML report; write a temperature converter instead',
                       'Fix the AttributeError in the PPT reading code',
                       '엑셀 오류 확인 후 html 만들어줘'):
            with self.subTest(prompt=prompt):
                self.output(prompt)
                for _ in range(2):
                    result = self.pre('Write', file_path=str(self.f.project / 'main.py'))
                    self.assertNotIn('permissionDecision', result.get('hookSpecificOutput', {}))
                serialized = json.dumps(self.state(), ensure_ascii=False)
                self.assertNotIn(prompt, serialized)

    def test_preservation_and_no_external_api_constraints_keep_real_workflow(self):
        for prompt, name in (('@자료.xlsx 원본은 수정하지 말고 내용 읽어줘', 'office-reader'),
                             ('Read the XLSX file without changing the original', 'office-reader'),
                             ('HTML 보고서를 외부 API 없이 만들어줘', 'html-report'),
                             ('Create an HTML report without external APIs', 'html-report')):
            with self.subTest(prompt=prompt):
                ctx, _ = self.output(prompt)
                self.assertEqual('load', ctx['skillExecution']['mode'])
                self.assertEqual(name, ctx['skillExecution']['name'])
                self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])

    def test_parallel_retry_cannot_treat_the_first_reminder_as_body_load(self):
        self.output('HTML 보고서를 만들어줘')
        before = self.state()
        self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])
        with patch('company_agent.skill_workflow.load_session', return_value=before):
            self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])

    def test_unchanged_correct_body_is_reused_without_catalogue_reread(self):
        self.output('HTML 보고서를 만들어줘')
        self.native_skill('company-agent:html-report')
        ctx, _ = self.output('새로운 HTML 보고서를 만들어줘')
        self.assertEqual('reuse', ctx['skillExecution']['mode'])
        self.assertEqual({}, self.pre('Write'))
        self.assertFalse(self.state()['skillWorkflow']['indexRead'])

    def test_support_target_can_complete_without_replacing_business_selection(self):
        file = self.f.skill('unique-support', '유일한개발조언', extra='company-agent-role: support\n')
        ctx, _ = self.output('유일한개발조언')
        self.assertEqual('load', ctx['skillExecution']['mode'])
        self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])
        self.f.read(file)
        self.assertIsNone(self.state()['skillWorkflow']['selected'])
        self.assertEqual({}, self.pre('Write'))
        self.output('HTML 보고서를 만들어줘')
        self.f.read(file)
        self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])

    def test_support_load_does_not_erase_a_fresh_host_checked_workflow_receipt(self):
        self.output('HTML 보고서를 만들어줘')
        self.native_skill('company-agent:html-report')
        atomic_write_json(self.f.claude / 'settings.json', {'permissions': {'ask': ['Skill']}})
        ctx, _ = self.output('HTML 보고서를 만들어줘')
        self.assertEqual('host-loading-rules', ctx['skillExecution']['reason'])
        self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])
        self.native_skill('company-agent:html-report')
        self.native_skill('company-agent:karpathy-guidelines')
        self.assertEqual('html-report', self.state()['skillWorkflow']['selected']['name'])
        self.assertEqual({}, self.pre('Write'))
        self.output('HTML 보고서를 만들어줘')
        self.assertEqual({}, self.state()['skillWorkflow']['turnLoads'])
        self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])

    def test_explicit_current_choice_and_no_relevant_fallback_are_respected(self):
        file = self.f.skill('user-chosen-helper', '사용자가 직접 지정한 업무')
        ctx, _ = self.output('HTML 보고서를 만들어줘')
        route = self.state()['skillWorkflow']
        from company_agent.skill_workflow import _snapshot
        data = _snapshot(self.f.state, self.f.project, route)
        item = next(x for x in data['skills'] if x['path'] == str(file))
        choose(self.f.state, self.f.project, self.f.sid, route['turn'], item['id'])
        self.assertEqual('deny', self.pre('Write')['hookSpecificOutput']['permissionDecision'])
        self.f.read(file)
        self.assertEqual({}, self.pre('Write'))
        ctx, _ = self.output('HTML 보고서를 만들어줘')
        select(self.f.state, self.f.project, self.f.sid, ctx['skillWorkflow']['turn'], fallback='no-relevant-skill')
        self.assertEqual({}, self.pre('Write'))

    def test_successful_observe_returns_only_validated_loaded_item(self):
        self.output('HTML 보고서를 만들어줘')
        payload = {'session_id': self.f.sid, 'hook_event_name': 'PostToolUse',
                   'tool_name': 'Skill', 'tool_input': {'skill': 'company-agent:html-report'},
                   'tool_response': {'success': True}}
        item = observe(self.f.state, self.f.project, payload)
        self.assertEqual('html-report', item['name'])
        self.assertEqual('company', item['source'])
        self.assertIsNone(observe(self.f.state, self.f.project, {**payload, 'tool_response': {'success': False}}))
        self.assertIsNone(observe(self.f.state, self.f.project, {**payload, 'agent_id': 'worker'}))

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
