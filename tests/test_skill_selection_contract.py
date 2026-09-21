"""Bounded choice/native-load state machine; no external model or live profile."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_skill_discovery as discovery
import test_skill_list_review as review
from company_agent.paths import atomic_write_json, atomic_write_text
from company_agent.skill_registry import inventory_skills, set_skill_preference
from company_agent.skill_task_context import named_choices
from company_agent.skill_workflow import choose, select, observe


class SelectionContractTests(unittest.TestCase):
    setUp = review.ListReviewTests.setUp
    output = review.ListReviewTests.output
    state = review.ListReviewTests.state
    pre = review.ListReviewTests.pre
    native_skill = review.ListReviewTests.native_skill

    def overlap(self, name='team-report', extra=''):
        file = self.f.skill(name, 'HTML 보고서 제작', extra=extra)
        context, _ = self.output('HTML 보고서 만들어줘')
        route = self.state()['skillWorkflow']
        return file, context, route

    def choice_data(self, file):
        route = self.state()['skillWorkflow']
        data = inventory_skills(self.f.state, project_root=self.f.project,
                                plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
        item = next(x for x in data['skills'] if x['path'] == str(file))
        return route, data, item

    def answer(self, file, *, response=True, value=None, authored=False):
        route, data, item = self.choice_data(file)
        candidates = [x for x in data['skills'] if x['id'] in route.get('requiredChoiceIds', [])]
        options = [{'label': x['name'] + ' (' + x['source'] + ')', 'description': '해당 출처의 작업 방식'} for x in candidates]
        label = item['name'] + ' (' + item['source'] + ')'
        inputs = {'questions': [{'question': '어떤 스킬을 사용할까요?', 'header': '스킬 선택', 'options': options, 'multiSelect': False}]}
        tool_response = {'answers': {'어떤 스킬을 사용할까요?': label if value is None else value}} if response else {}
        if not response or authored:
            inputs['answers'] = {'어떤 스킬을 사용할까요?': label}
        observe(self.f.state, self.f.project, {'session_id': self.f.sid, 'hook_event_name': 'PostToolUse',
            'tool_name': 'AskUserQuestion', 'tool_input': inputs, 'tool_response': tool_response})

    def pick(self, file):
        self.answer(file)
        route, _, item = self.choice_data(file)
        return choose(self.f.state, self.f.project, self.f.sid, route['turn'], item['id'])

    def assert_denied(self):
        result = self.pre('Write')['hookSpecificOutput']
        self.assertEqual('deny', result['permissionDecision'])
        return result['permissionDecisionReason']

    def test_competing_names_require_recorded_choice_not_retry_index_or_arbitrary_body(self):
        file, context, route = self.overlap()
        self.assertEqual('choose', context['skillExecution']['mode'])
        self.assertEqual(2, len(route['executionPlan']['choiceIds']))
        self.assertIn('스킬 선택', self.assert_denied())
        self.assert_denied()
        self.f.read(Path(context['skillSelection']['catalog']['path']))
        self.f.read(file)
        self.assert_denied()
        result = self.pick(file)
        self.assertTrue(result['bodyAlreadyRead'])
        self.assertFalse(result['preferencesChanged'])
        self.assertEqual({}, self.pre('Write'))

    def test_answered_choice_requires_its_body_and_is_not_replaced_by_another_candidate(self):
        file, _, _ = self.overlap()
        self.assertFalse(self.pick(file)['bodyAlreadyRead'])
        self.assert_denied()
        self.native_skill('company-agent:html-report')
        self.assert_denied()
        self.f.read(file)
        self.assertEqual({}, self.pre('Write'))
        self.assertEqual('team-report', self.state()['skillWorkflow']['selected']['name'])

    def test_unique_explicit_choice_wins_over_other_names(self):
        self.overlap()
        for prompt in ('/team-report HTML 보고서를 만들어줘',
                       'team-report 스킬로 HTML 보고서를 만들어줘',
                       'Create an HTML report using the team-report skill'):
            with self.subTest(prompt=prompt):
                context, _ = self.output(prompt)
                self.assertIn(context['skillExecution']['mode'], {'load', 'reuse'})
                self.assertEqual('team-report', context['skillExecution']['name'])
                self.native_skill('team-report')
                self.assertEqual({}, self.pre('Write'))

    def test_negative_or_explanatory_mentions_are_not_explicit_choices(self):
        for prompt in ('team-report 스킬은 쓰지 말고 html-report 스킬로 HTML 만들어줘',
                       'team-report 스킬로 만들지 말고 html-report 스킬로 HTML 만들어줘'):
            self.assertEqual(['html-report'], named_choices(prompt))
        for prompt in ('team-report 스킬은 무엇인지 설명해줘',
                       'Compare the team-report skill with the html-report skill',
                       'Do not use the team-report skill',
                       'team-report 스킬로 무엇을 하는지 설명해줘'):
            self.assertEqual([], named_choices(prompt), prompt)
        self.overlap()
        context, _ = self.output('team-report 스킬은 쓰지 말고 html-report 스킬로 HTML 만들어줘')
        self.assertEqual('html-report', context['skillExecution'].get('name'))

    def test_excluded_skill_and_cancelled_continuation_do_not_force_previous_workflow(self):
        for prompt in ('html-report 스킬은 사용하지 말고 HTML 보고서 만들어줘',
                       'Do not use the html-report skill. Create an HTML report without any skill.',
                       '그 스킬 말고 파이썬으로 2+3 계산해줘',
                       'team-report 스킬 말고 파이썬으로 2+3 계산해줘',
                       'team-report 스킬로는 하지 말고 그냥 텍스트로 해줘'):
            self.overlap()
            context, _ = self.output(prompt)
            self.assertNotIn('choiceIds', self.state()['skillWorkflow']['executionPlan'])
            self.assertNotIn('permissionDecision', self.pre('Write').get('hookSpecificOutput', {}))

    def test_missing_named_host_skill_is_not_replaced_by_mandatory_builtin(self):
        for prompt in ('zz-nonexistent 스킬을 사용해서 HTML 보고서 만들어줘',
                       '/zz-nonexistent HTML 보고서 만들어줘'):
            context, _ = self.output(prompt)
            self.assertEqual('inspect', context['skillExecution']['mode'])
            self.assertEqual('explicit-skill-outside-catalog', context['skillExecution']['reason'])
            self.assertNotIn('permissionDecision', self.pre('Write').get('hookSpecificOutput', {}))

    def test_number_answer_keeps_pending_choice_but_does_not_guess_option(self):
        file, _, first = self.overlap()
        self.assert_denied()
        context, _ = self.output('1번')
        route = self.state()['skillWorkflow']
        self.assertNotEqual(first['turn'], route['turn'])
        self.assertEqual('choose', context['skillExecution']['mode'])
        self.assertIsNone(route['selected'])
        self.assertEqual(first['executionPlan']['choiceIds'], route['executionPlan']['choiceIds'])
        self.assert_denied()
        with self.assertRaises(ValueError):
            choose(self.f.state, self.f.project, self.f.sid, first['turn'], route['executionPlan']['choiceIds'][0])
        with self.assertRaises(ValueError):
            choose(self.f.state, self.f.project, self.f.sid, route['turn'], route['executionPlan']['choiceIds'][0])
        # A bare number has no observed question ordering. A clear name reply
        # supplies real user evidence without guessing the numbered option.
        self.output('개인 team-report로 진행해줘')
        route, _, item = self.choice_data(file)
        choose(self.f.state, self.f.project, self.f.sid, route['turn'], item['id'])
        self.f.read(file)
        self.assertEqual({}, self.pre('Write'))

    def test_named_answer_and_same_skill_continuation_preserve_current_choice(self):
        file, _, _ = self.overlap()
        context, _ = self.output('개인 team-report로 진행해줘')
        self.assertEqual('choose', context['skillExecution']['mode'])
        self.pick(file)
        self.f.read(file)
        context, _ = self.output('그 스킬로 계속 진행해줘')
        self.assertEqual('team-report', context['skillExecution']['name'])
        self.assertEqual('reuse', context['skillExecution']['mode'])
        self.assertEqual({}, self.pre('Write'))

    def test_competing_cli_choice_without_real_answer_or_with_authored_input_answers_is_rejected(self):
        file, _, _ = self.overlap()
        route, _, item = self.choice_data(file)
        for response in (None, False):
            if response is False:
                self.answer(file, response=False)
            with self.assertRaises(ValueError):
                choose(self.f.state, self.f.project, self.f.sid, route['turn'], item['id'])
        for cancelled in ('취소', 'team-report 말고', 'none'):
            self.answer(file, value=cancelled)
            with self.assertRaises(ValueError):
                choose(self.f.state, self.f.project, self.f.sid, route['turn'], item['id'])
        self.answer(file, authored=True)
        with self.assertRaises(ValueError):
            choose(self.f.state, self.f.project, self.f.sid, route['turn'], item['id'])
        self.assert_denied()

    def test_real_question_answer_updates_plan_without_extra_cli_and_cannot_choose_other_candidate(self):
        file, _, _ = self.overlap()
        self.answer(file)
        route, data, item = self.choice_data(file)
        self.assertEqual(item['id'], route['executionPlan']['id'])
        self.assertEqual(item['id'], route['choiceAnswer']['id'])
        other = next(x for x in data['skills'] if x['id'] in route['requiredChoiceIds'] and x['id'] != item['id'])
        with self.assertRaises(ValueError):
            choose(self.f.state, self.f.project, self.f.sid, route['turn'], other['id'])
        self.assert_denied()
        self.f.read(file)
        self.assertEqual({}, self.pre('Write'))
        # Later questions cannot silently change an already answered choice.
        self.answer(Path(other['path']))
        self.assertEqual(item['id'], self.state()['skillWorkflow']['requestChoice']['id'])

    def test_free_text_question_answer_can_name_one_exact_candidate(self):
        file, _, _ = self.overlap()
        self.answer(file, value='team-report')
        self.assertEqual('team-report', self.state()['skillWorkflow']['executionPlan']['name'])
        self.f.read(file)
        self.assertEqual({}, self.pre('Write'))

    def test_new_work_or_similar_name_does_not_inherit_pending_choice(self):
        for prompt in ('PPT 발표자료 만들어줘', '2 더하기 3은?',
                       'team-reporting 기능 확인', 'other-team-report로 진행해줘'):
            with self.subTest(prompt=prompt):
                self.overlap()
                context, _ = self.output(prompt)
                self.assertNotIn('choiceIds', self.state()['skillWorkflow']['executionPlan'])
                self.assertNotIn('pendingChoice', self.state()['skillWorkflow'])
                if prompt.startswith('PPT'):
                    self.assertEqual('presentation', context['skillExecution']['name'])
                else:
                    self.assertNotIn('permissionDecision', self.pre('Write').get('hookSpecificOutput', {}))

    def test_deleted_or_changed_competitor_does_not_force_stale_selection(self):
        for delete in (False, True):
            file, _, _ = self.overlap()
            self.assert_denied()
            if delete:
                file.unlink()
            else:
                atomic_write_text(file, file.read_text(encoding='utf-8') + '\nchanged')
            self.assertEqual({}, self.pre('Write'))

    def test_complementary_phases_and_weak_search_hits_are_not_forced_competition(self):
        self.f.skill('html-reader', 'HTML 문서 읽기 및 요약')
        self.f.skill('vague-report-helper', 'HTML 보고서 참고 지침')
        for prompt in ('HTML 내용을 읽고 HTML 보고서 만들어줘', 'HTML 지침 참고'):
            context, _ = self.output(prompt)
            self.assertNotIn('choiceIds', self.state()['skillWorkflow']['executionPlan'])
            self.assertNotIn('permissionDecision', self.pre('Write').get('hookSpecificOutput', {}))

    def test_no_relevant_fallback_still_allows_general_work(self):
        _, context, _ = self.overlap()
        select(self.f.state, self.f.project, self.f.sid, context['skillWorkflow']['turn'], fallback='no-relevant-skill')
        self.assertEqual({}, self.pre('Write'))

    def test_saved_same_name_preference_resolves_overlap(self):
        file, _, _ = self.overlap(name='html-report')
        data = inventory_skills(self.f.state, project_root=self.f.project,
                                plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
        item = next(x for x in data['skills'] if x['path'] == str(file))
        set_skill_preference(self.f.state, 'html-report', item['id'], project_root=self.f.project,
                             plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
        context, _ = self.output('HTML 보고서 만들어줘')
        self.assertEqual('load', context['skillExecution']['mode'])
        self.assertEqual(str(file), context['skillExecution']['path'])
        self.f.read(file)
        self.assertEqual({}, self.pre('Write'))

    def test_native_semantics_need_current_exact_success_not_read_or_failed_skill(self):
        for extra in ('context: fork\n', 'allowed-tools: Read\n', 'model: haiku\n'):
            with self.subTest(extra=extra):
                file = self.f.skill('native-special', '유일한별도실행', extra=extra)
                context, _ = self.output('/native-special')
                self.assertTrue(context['skillExecution']['nativeRequired'])
                self.f.read(file)
                self.assertEqual('native-load-required', self.state()['skillWorkflow']['loadObservation']['status'])
                self.assertIsNone(self.state()['skillWorkflow']['selected'])
                self.assert_denied()
                self.native_skill('native-special', success=False)
                self.assert_denied()
                self.native_skill('native-special')
                self.assertEqual({}, self.pre('Write'))
                self.output('/native-special')
                self.f.read(file)
                self.assert_denied()
                self.native_skill('native-special')
                self.assertEqual({}, self.pre('Write'))

    def test_dynamic_native_body_is_not_satisfied_by_plain_read(self):
        for token in ('$ARGUMENTS', '${CLAUDE_SKILL_DIR}', '!`printf example`', '$1'):
            file = self.f.skill('dynamic-special', '유일한별도실행')
            atomic_write_text(file, file.read_text(encoding='utf-8') + token)
            self.output('/dynamic-special')
            self.f.read(file)
            self.assert_denied()
            self.native_skill('dynamic-special')
            self.assertEqual({}, self.pre('Write'))

    def test_native_collision_is_an_explicit_limit_not_a_read_fallback(self):
        file = self.f.skill('same-report', '유일한별도실행', extra='context: fork\n')
        self.f.skill('same-report', '유일한별도실행', source='project')
        data = inventory_skills(self.f.state, project_root=self.f.project,
                                plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
        item = next(x for x in data['skills'] if x['path'] == str(file))
        set_skill_preference(self.f.state, 'same-report', item['id'], project_root=self.f.project,
                             plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
        context, text = self.output('/same-report')
        self.assertEqual('native-invocation-unavailable', context['skillExecution']['limitation'])
        self.assertIsNone(context['skillExecution']['load'])
        self.assertIn('호출명 충돌', text)
        self.f.read(file)
        self.assertIn('호출명 충돌', self.assert_denied())
        self.native_skill('same-report')
        self.assertEqual('name-ambiguous', self.state()['skillWorkflow']['loadObservation']['status'])
        self.assert_denied()

    def test_answered_native_choice_returns_skill_and_never_reuses_read_as_native(self):
        file, _, _ = self.overlap(extra='context: fork\n')
        self.f.read(file)
        result = self.pick(file)
        self.assertFalse(result['bodyAlreadyRead'])
        self.assertTrue(result['nativeRequired'])
        self.assertEqual({'tool': 'Skill', 'skill': 'team-report'}, result['load'])
        self.assert_denied()
        with self.assertRaises(ValueError):
            route = self.state()['skillWorkflow']
            select(self.f.state, self.f.project, self.f.sid, route['turn'], name='team-report')
        self.native_skill('team-report')
        self.assertEqual({}, self.pre('Write'))

    def test_native_success_records_validated_personal_load_for_learning(self):
        self.f.claude = self.f.state / 'personal-root/.claude'
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.f.claude)}):
            file = self.f.skill('private-helper', '유일한별도실행')
            self.output('/private-helper')
            self.native_skill('private-helper', success=False)
            self.assertEqual([], self.state()['usedSkills'])
            self.native_skill('private-helper')
            observed = self.state()['usedSkills']
            self.assertEqual([str(file)], [item['path'] for item in observed])
            self.assertEqual([64], [len(item['sha256']) for item in observed])
            self.native_skill('private-helper')
            self.assertEqual(observed, self.state()['usedSkills'])


if __name__ == '__main__':
    unittest.main()
