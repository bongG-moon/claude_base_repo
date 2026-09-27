"""Metadata routing checks, not claims of model adherence or visual QA."""
import copy
import unittest
from unittest.mock import patch

import test_skill_discovery as discovery
import test_skill_execution as execution
from company_agent.skill_decision import decide_preparation
from company_agent.skill_registry import inventory_skills
from company_agent.skill_task_context import _features, task_candidates


class ExplanationSkillRoutingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = discovery.SkillDiscoveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture
        self.inventory = inventory_skills(
            self.f.state, project_root=self.f.project, plugin_root=discovery.PLUGIN,
            claude_root=self.f.claude)
        self.html = next(row for row in self.inventory['skills'] if row['name'] == 'html-report')

    def decision(self, prompt, inventory=None):
        inventory = inventory or self.inventory
        hints = task_candidates(inventory, prompt)
        return hints, decide_preparation(hints, inventory['skills'], [])

    def test_followup_relation_requests_find_existing_html_owner(self):
        for prompt in (
            '방금 작업한 흐름을 그림으로 보여줘',
            '방금 작업한 구조를 정리해줘',
            '작업 흐름을 설명해줘',
            '구조를 정리해줘',
            'Explain the workflow we just finished',
            'Show the structure of the work we just completed',
        ):
            with self.subTest(prompt=prompt):
                hints, decision = self.decision(prompt)
                self.assertIn(self.html['id'], hints.get('strongIds', []))
                self.assertEqual(('load', self.html['id']), (decision.mode, decision.candidate_id))

    def test_plain_summaries_and_text_only_requests_do_not_force_visual_work(self):
        for prompt in (
            '방금 작업 정리해줘',
            '작업 끝났어',
            '방금 작업한 흐름을 글로만 설명해줘',
            '구조를 텍스트로만 정리해줘',
            '작업 흐름을 도표 없이 설명해줘',
            '작업 흐름을 그림 없이 보여줘',
            '작업 흐름을 설명해줘. 그리지 마',
            '방금 작업한 구조를 정리해줘. 다이어그램은 그리지마',
            'Explain the workflow without diagrams',
            'Explain the structure in words only',
            "Explain the workflow, don't draw diagrams",
        ):
            with self.subTest(prompt=prompt):
                self.assertNotIn('explanation', _features(prompt)[0])
                hints, decision = self.decision(prompt)
                self.assertNotIn(self.html['id'], hints.get('strongIds', []))
                self.assertNotEqual(('load', self.html['id']), (decision.mode, decision.candidate_id))

    def test_lifecycle_source_reading_and_code_changes_are_not_explanations(self):
        for prompt in (
            'diagram-design 스킬 설치해줘',
            '작업 흐름을 다이어그램으로 설명하는 스킬을 설치해줘',
            'diagram-design 스킬과 html-report 스킬 차이를 설명해줘',
            '코드 구조를 수정해줘',
            '코드 구조를 정리해줘',
            '방금 작업한 흐름에서 버그를 고쳐줘',
            '구조를 정리하고 버그를 수정해줘',
            '원자료 CSV를 읽고 분석해줘',
            '이 데이터 구조를 읽고 확인해줘',
            'Refactor the code structure',
        ):
            with self.subTest(prompt=prompt):
                self.assertNotIn('explanation', _features(prompt)[0])
                hints, decision = self.decision(prompt)
                self.assertNotIn(self.html['id'], hints.get('strongIds', []))
                self.assertNotEqual(('load', self.html['id']), (decision.mode, decision.candidate_id))

    def test_regular_reports_keep_regular_html_capability(self):
        for prompt in ('HTML 보고서 만들어줘', 'Create an HTML report'):
            with self.subTest(prompt=prompt):
                self.assertEqual(({'html'}, {'make'}), _features(prompt))
                _, decision = self.decision(prompt)
                self.assertEqual(self.html['id'], decision.candidate_id)
        self.assertNotIn('explanation', _features('실적 보고서 만들어줘')[0])

    def test_capability_is_metadata_based_and_alternatives_remain_choices(self):
        inventory = copy.deepcopy(self.inventory)
        renamed = next(row for row in inventory['skills'] if row['id'] == self.html['id'])
        renamed.update(name='existing-business-output', invocation='company:existing-business-output')
        _, decision = self.decision('작업 흐름을 설명해줘', inventory)
        self.assertEqual(renamed['id'], decision.candidate_id)
        alternative = dict(renamed, id='user:explanation-alternative', name='another-explainer',
                           invocation='another-explainer', source='user')
        inventory['skills'].append(alternative)
        hints, decision = self.decision('작업 흐름을 설명해줘', inventory)
        self.assertEqual('choose', decision.mode)
        self.assertEqual({renamed['id'], alternative['id']}, set(hints['competingIds']))

    def test_hint_computation_never_reads_bodies_or_runs_work(self):
        before = copy.deepcopy(self.inventory)
        with patch('pathlib.Path.open', side_effect=AssertionError('no source/session scan')), \
             patch('subprocess.run', side_effect=AssertionError('no work rerun')):
            self.decision('방금 작업한 흐름을 그림으로 보여줘')
        self.assertEqual(before, self.inventory)

    def test_runtime_fixture_has_existing_skill_load_not_a_new_hook(self):
        context, _ = execution.SkillExecutionTests.output(self, '방금 작업한 흐름을 그림으로 보여줘')
        self.assertEqual('html-report', context['skillExecution']['name'])
        self.assertEqual({'tool': 'Skill', 'skill': 'company-agent:html-report'},
                         context['skillExecution']['load'])


if __name__ == '__main__':
    unittest.main()
