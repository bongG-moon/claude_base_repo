"""Explicit skill intent through runtime selection and preparation, without a model."""
from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

import test_skill_discovery as discovery
import test_skill_execution as execution
from company_agent.skill_registry import inventory_skills, set_skill_preference
from company_agent.skill_task_context import named_choices
from company_agent.skill_workflow import observe, preflight


ORIGINAL_REQUEST = (
    '회사 asset-factory로 크롬 스킬을 만들자. https://lol.ps/ 를 크롬 디버깅 도구로 열고, '
    '팝업이 있으면 닫아줘.'
)
MAKER_DESCRIPTION = '개인 스킬·스크립트·도구·MCP를 만들고 수정·검증하는 제작 스킬입니다.'


class ExplicitSkillIntentTests(unittest.TestCase):
    output = execution.SkillExecutionTests.output
    state = execution.SkillExecutionTests.state

    def setUp(self):
        execution.SkillExecutionTests.setUp(self)
        no_process = patch('subprocess.Popen', side_effect=AssertionError('No process or browser in this test'))
        no_process.start()
        self.addCleanup(no_process.stop)
        no_network = patch('socket.create_connection', side_effect=AssertionError('No network in this test'))
        no_network.start()
        self.addCleanup(no_network.stop)
        self.f.skill('writing-skills', MAKER_DESCRIPTION)

    def inventory(self):
        return inventory_skills(self.f.state, project_root=self.f.project,
                                plugin_root=discovery.PLUGIN, claude_root=self.f.claude)['skills']

    def pre(self, tool, **inputs):
        return preflight(self.f.state, self.f.project, {'session_id': self.f.sid,
                         'tool_name': tool, 'tool_input': inputs})

    def assert_target(self, prompt, source, invocation, path):
        context, text = self.output(prompt)
        plan = context['skillExecution']
        self.assertIn(plan['mode'], {'load', 'reuse'}, plan)
        self.assertEqual('asset-factory', plan['name'])
        self.assertEqual(source, plan['source'])
        self.assertEqual(str(path), plan['path'])
        self.assertEqual({'tool': 'Skill', 'skill': invocation}, plan['load'])
        recorded_plan = self.state()['skillWorkflow']['executionPlan']
        self.assertNotIn('choiceIds', recorded_plan)
        self.assertEqual({}, self.pre('Skill', skill=invocation))
        self.assertNotIn('SECRET-BODY', text)
        observe(self.f.state, self.f.project, {'session_id': self.f.sid, 'hook_event_name': 'PostToolUse',
                'tool_name': 'Skill', 'tool_input': {'skill': invocation}, 'tool_response': {'success': True}})
        selected = self.state()['skillWorkflow']['selected']
        self.assertEqual(str(path), selected['path'])
        self.assertEqual(recorded_plan['id'], selected['id'])
        self.assertEqual({}, self.pre('Write', file_path=str(self.f.project / 'draft.txt')))
        return context

    def test_original_company_asset_factory_request_wins_over_competing_writing_skill(self):
        competing, _ = self.output('크롬 스킬을 만들자')
        self.assertEqual('choose', competing['skillExecution']['mode'])
        candidates = {item['id']: item for item in self.inventory()}
        names = {candidates[item_id]['name'] for item_id in competing['skillExecution']['choiceIds']}
        self.assertIn('asset-factory', names)
        self.assertIn('writing-skills', names)
        context = self.assert_target(ORIGINAL_REQUEST, 'company', 'company-agent:asset-factory',
                                     discovery.PLUGIN / 'skills/asset-factory/SKILL.md')
        self.assertEqual('load', context['skillExecution']['mode'])
        self.assertIn('asset-factory', named_choices(ORIGINAL_REQUEST))

    def test_short_positive_natural_language_selects_the_named_company_skill(self):
        for prompt in ('company-agent:asset-factory로 진행해줘',
                       'asset-factory를 사용해줘',
                       '회사 asset-factory로 크롬 스킬을 만들자',
                       '회사 ASSET-FACTORY로 크롬 스킬을 만들자'):
            with self.subTest(prompt=prompt):
                self.assert_target(prompt, 'company', 'company-agent:asset-factory',
                                   discovery.PLUGIN / 'skills/asset-factory/SKILL.md')

    def test_source_qualified_same_name_uses_the_exact_company_or_personal_candidate(self):
        personal = self.f.skill('asset-factory', MAKER_DESCRIPTION)
        for prompt, source, invocation, path in (
            (ORIGINAL_REQUEST, 'company', 'company-agent:asset-factory',
             discovery.PLUGIN / 'skills/asset-factory/SKILL.md'),
            ('개인 asset-factory로 크롬 스킬을 만들자', 'user', 'asset-factory', personal),
            ('회사 asset-factory를 사용해줘', 'company', 'company-agent:asset-factory',
             discovery.PLUGIN / 'skills/asset-factory/SKILL.md'),
            ('company-agent:asset-factory로 진행해줘', 'company', 'company-agent:asset-factory',
             discovery.PLUGIN / 'skills/asset-factory/SKILL.md'),
        ):
            with self.subTest(prompt=prompt):
                self.assert_target(prompt, source, invocation, path)

    def test_unqualified_same_name_keeps_both_sources_as_a_question(self):
        self.f.skill('asset-factory', MAKER_DESCRIPTION)
        context, _ = self.output('asset-factory를 사용해줘')
        plan = context['skillExecution']
        self.assertEqual('choose', plan['mode'])
        ids = set(plan['choiceIds'])
        expected = {item['id'] for item in self.inventory() if item['name'] == 'asset-factory'}
        self.assertEqual(2, len(expected))
        self.assertTrue(expected <= ids)
        self.assertIsNone(self.state()['skillWorkflow']['selected'])
        self.assertNotIn('requestChoice', self.state()['skillWorkflow'])
        for invocation in ('company-agent:asset-factory', 'asset-factory'):
            with self.subTest(invocation=invocation):
                decision = self.pre('Skill', skill=invocation)['hookSpecificOutput']
                self.assertEqual('deny', decision['permissionDecision'])
                self.assertIn('선택', decision['permissionDecisionReason'])

    def test_current_source_request_overrides_opposite_saved_preference_without_rewriting_it(self):
        self.f.skill('asset-factory', MAKER_DESCRIPTION)
        candidates = {item['source']: item for item in self.inventory() if item['name'] == 'asset-factory'}
        for source, qualifier, opposite in (('company', '회사', 'user'), ('user', '개인', 'company')):
            with self.subTest(source=source):
                preferred = set_skill_preference(self.f.state, 'asset-factory', candidates[opposite]['id'],
                    project_root=self.f.project, plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
                preference_file = Path(preferred['preferencesPath'])
                before = preference_file.read_bytes()
                chosen = candidates[source]
                self.assert_target(f'{qualifier} asset-factory로 크롬 스킬을 만들자',
                                   source, chosen['invocation'], Path(chosen['path']))
                self.assertEqual(before, preference_file.read_bytes())

    def test_compact_retains_explicit_source_over_opposite_preference_but_requires_a_new_body_load(self):
        self.f.skill('asset-factory', MAKER_DESCRIPTION)
        candidates = {item['source']: item for item in self.inventory() if item['name'] == 'asset-factory'}
        for source, qualifier, opposite in (('company', '회사', 'user'), ('user', '개인', 'company')):
            with self.subTest(source=source):
                preferred = set_skill_preference(self.f.state, 'asset-factory', candidates[opposite]['id'],
                    project_root=self.f.project, plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
                preference_file = Path(preferred['preferencesPath'])
                preference_before = preference_file.read_bytes()
                chosen = candidates[source]
                self.assert_target(f'{qualifier} asset-factory로 크롬 스킬을 만들자',
                                   source, chosen['invocation'], Path(chosen['path']))
                before = self.state()['skillWorkflow']
                self.assertTrue(before['readSkills'])
                self.assertTrue(before['nativeLoads'])

                context = self.f.context(prompt='', source='compact')
                hint = context['skillWorkflow']['continuation']
                self.assertEqual({'tool': 'Skill', 'skill': chosen['invocation']}, hint['load'])
                self.assertTrue(hint['bodyRequired'])
                self.assertEqual('previous-selection-not-body', hint['basis'])
                after = self.state()['skillWorkflow']
                self.assertEqual(before['turn'], after['turn'])
                self.assertEqual(before['namedSkillRequests'], after['namedSkillRequests'])
                self.assertEqual(chosen['id'], after['executionPlan']['id'])
                self.assertEqual(source, after['executionPlan']['source'])
                self.assertEqual('load', after['executionPlan']['mode'])
                for receipt in ('readSkills', 'nativeLoads', 'turnLoads'):
                    self.assertEqual({}, after[receipt], receipt)
                self.assertIsNone(after['selected'])
                blocked = self.pre('Write', file_path=str(self.f.project / 'after-compact.txt'))
                self.assertEqual('deny', blocked['hookSpecificOutput']['permissionDecision'])
                self.assertEqual({}, self.pre('Skill', skill=chosen['invocation']))
                observe(self.f.state, self.f.project, {'session_id': self.f.sid, 'hook_event_name': 'PostToolUse',
                    'tool_name': 'Skill', 'tool_input': {'skill': chosen['invocation']},
                    'tool_response': {'success': True}})
                self.assertEqual(chosen['id'], self.state()['skillWorkflow']['selected']['id'])
                self.assertEqual({}, self.pre('Write', file_path=str(self.f.project / 'after-compact.txt')))
                self.assertEqual(preference_before, preference_file.read_bytes())

    def test_negative_explanatory_comparison_installation_and_quoted_names_are_not_selections(self):
        prompts = (
            'asset-factory를 사용하지 마.',
            '회사 asset-factory로 크롬 스킬을 만들지 마.',
            'asset-factory가 무엇인지 설명해줘.',
            'company-agent:asset-factory를 writing-skills와 비교해줘.',
            'asset-factory를 설치해줘.',
            '"회사 asset-factory로 크롬 스킬을 만들자"라는 예문의 뜻을 설명해줘.',
            '예문: `asset-factory를 사용해줘`. 이 문장만 영어로 번역해줘.',
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual([], named_choices(prompt))
                context, _ = self.output(prompt)
                self.assertNotIn(context['skillExecution']['mode'], {'load', 'reuse'})
                route = self.state()['skillWorkflow']
                self.assertEqual([], route.get('namedSkillChoices', []))
                self.assertIsNone(route['selected'])
                self.assertNotIn('requestChoice', route)

    def test_named_choice_parser_respects_contrast_questions_and_single_quoted_examples(self):
        cases = (
            ('asset-factory로 말고 writing-skills로 만들어줘', ['writing-skills']),
            ('asset-factory로 안 만들고 writing-skills로 만들어줘', ['writing-skills']),
            ('Explain how to use company asset-factory', []),
            ('Should I use company asset-factory?', []),
            ("'asset-factory로 만들어줘'라는 예문만 번역해줘", []),
        )
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(expected, named_choices(prompt))

    def test_same_skill_followup_keeps_the_loaded_explicit_source_without_another_choice(self):
        self.f.skill('asset-factory', MAKER_DESCRIPTION)
        candidates = {item['source']: item for item in self.inventory() if item['name'] == 'asset-factory'}
        for source, qualifier, opposite in (('company', '회사', 'user'), ('user', '개인', 'company')):
            with self.subTest(source=source):
                set_skill_preference(self.f.state, 'asset-factory', candidates[opposite]['id'],
                    project_root=self.f.project, plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
                chosen = candidates[source]
                self.assert_target(f'{qualifier} asset-factory로 크롬 스킬을 만들자',
                                   source, chosen['invocation'], Path(chosen['path']))
                before = self.state()['skillWorkflow']
                self.assertEqual(chosen['id'], before['selected']['id'])

                context, _ = self.output('그 스킬로 계속 진행해줘')
                plan = context['skillExecution']
                self.assertIn(plan['mode'], {'load', 'reuse'})
                self.assertEqual(source, plan['source'])
                self.assertEqual(chosen['path'], plan['path'])
                self.assertEqual({'tool': 'Skill', 'skill': chosen['invocation']}, plan['load'])
                after = self.state()['skillWorkflow']
                self.assertNotEqual(before['turn'], after['turn'])
                self.assertEqual(chosen['id'], after['executionPlan']['id'])
                self.assertNotIn('choiceIds', after['executionPlan'])
                self.assertEqual({}, self.pre('Skill', skill=chosen['invocation']))

    def test_unavailable_company_source_never_falls_back_to_personal_same_name(self):
        personal = self.f.skill('private-factory', MAKER_DESCRIPTION)
        for prompt in ('회사 private-factory로 크롬 스킬을 만들자',
                       'company-agent:private-factory로 진행해줘'):
            with self.subTest(prompt=prompt):
                context, _ = self.output(prompt)
                plan = context['skillExecution']
                self.assertNotIn(plan['mode'], {'load', 'reuse'})
                self.assertNotEqual(str(personal), plan.get('path'))
                route = self.state()['skillWorkflow']
                self.assertIsNone(route['selected'])
                self.assertNotIn('requestChoice', route)
                self.assertEqual({}, route['readSkills'])


if __name__ == '__main__':
    unittest.main()
