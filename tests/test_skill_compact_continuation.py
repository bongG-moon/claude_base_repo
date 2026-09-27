"""Compact retains an observed task choice, not body or execution receipts."""
import copy
import json
import unittest

import test_skill_discovery as discovery
from company_agent.native_runtime import task_prompt_context
from company_agent.paths import atomic_write_text
from company_agent.skill_registry import inventory_skills
from company_agent.skill_workflow import choose, observe, preflight
from company_agent.state import load_session, record_activity


class SkillCompactContinuationTests(unittest.TestCase):
    def setUp(self):
        self.f = discovery.SkillDiscoveryTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def state(self):
        return load_session(self.f.sid, self.f.state)

    def output(self, prompt='HTML 보고서 만들어줘'):
        context = self.f.context(prompt)
        text = task_prompt_context('{}', json.dumps({'company_agent_runtime': context}, ensure_ascii=False))
        return json.loads(text.splitlines()[-1])['company_agent_runtime']

    def native_load(self, invocation, response=None):
        observe(self.f.state, self.f.project, {
            'session_id': self.f.sid, 'hook_event_name': 'PostToolUse',
            'tool_name': 'Skill', 'tool_input': {'skill': invocation},
            'tool_response': {'success': True} if response is None else response,
        })

    def compact(self):
        return self.f.context(prompt='', source='compact')

    def before_write(self):
        return preflight(self.f.state, self.f.project, {
            'session_id': self.f.sid, 'tool_name': 'Write',
            'tool_input': {'file_path': str(self.f.project / 'report.html'), 'content': '<p>test</p>'},
        })

    def test_same_task_unchanged_native_choice_restores_hint_not_receipts(self):
        self.output()
        self.native_load('company-agent:html-report')
        record_activity({'session_id': self.f.sid, 'tool_name': 'Write',
                         'tool_input': {'file_path': str(self.f.project / 'existing.txt')}}, self.f.state)
        before = copy.deepcopy(self.state())
        route = before['skillWorkflow']
        self.assertTrue(route['readSkills'])
        self.assertTrue(route['nativeLoads'])
        self.assertEqual('html-report', route['selected']['name'])

        context = self.compact()
        self.assertEqual('load-relevant-skill', context['skillWorkflow']['nextAction'])
        self.assertEqual({
            'name': 'html-report',
            'load': {'tool': 'Skill', 'skill': 'company-agent:html-report'},
            'bodyRequired': True,
            'basis': 'previous-selection-not-body',
        }, context['skillWorkflow']['continuation'])
        after = self.state()
        self.assertEqual({}, after['skillWorkflow']['readSkills'])
        self.assertEqual({}, after['skillWorkflow']['nativeLoads'])
        self.assertEqual({}, after['skillWorkflow']['turnLoads'])
        self.assertIsNone(after['skillWorkflow']['selected'])
        self.assertEqual('load', after['skillWorkflow']['executionPlan']['mode'])
        self.assertEqual('not-observed', after['skillWorkflow']['loadObservation']['status'])
        before.pop('skillWorkflow')
        after.pop('skillWorkflow')
        self.assertEqual(before, after)  # mutations/retries/verification were not reset
        self.assertNotIn('Read the request and reuse known answers', json.dumps(context))

    def test_exact_file_read_can_continue_but_needs_fresh_body(self):
        file = self.f.skill('custom-report', 'HTML 보고서 제작')
        self.output('custom-report 스킬로 HTML 보고서 만들어줘')
        self.f.read(file)
        context = self.compact()
        hint = context['skillWorkflow']['continuation']
        self.assertEqual('custom-report', hint['name'])
        self.assertTrue(hint['bodyRequired'])
        self.assertEqual('deny', self.before_write()['hookSpecificOutput']['permissionDecision'])
        self.f.read(file)
        self.assertEqual({}, self.before_write())
        self.assertEqual('custom-report', self.state()['skillWorkflow']['selected']['name'])

    def test_changed_body_has_no_continuation_hint(self):
        file = self.f.skill('custom-report', 'HTML 보고서 제작')
        self.output('custom-report 스킬로 HTML 보고서 만들어줘')
        self.f.read(file)
        atomic_write_text(file, file.read_text(encoding='utf-8') + '\nChanged workflow body\n')
        context = self.compact()
        self.assertNotIn('continuation', context['skillWorkflow'])
        route = self.state()['skillWorkflow']
        self.assertEqual({}, route['readSkills'])
        self.assertEqual({}, route['nativeLoads'])
        self.assertIsNone(route['selected'])

    def test_no_successful_body_load_never_creates_hint(self):
        for response in (None, {'success': False, 'is_error': True}):
            with self.subTest(response=response):
                self.output()
                if response is not None:
                    self.native_load('company-agent:html-report', response)
                context = self.compact()
                self.assertNotIn('continuation', context['skillWorkflow'])
                self.assertEqual({}, self.state()['skillWorkflow']['readSkills'])
                self.assertIsNone(self.state()['skillWorkflow']['selected'])

    def test_startup_and_resume_do_not_claim_compact_continuation(self):
        for source in ('startup', 'resume'):
            with self.subTest(source=source):
                self.output()
                self.native_load('company-agent:html-report')
                context = self.f.context(prompt='', source=source)
                self.assertNotIn('continuation', context['skillWorkflow'])
                route = self.state()['skillWorkflow']
                self.assertEqual({}, route['readSkills'])
                self.assertEqual({}, route['nativeLoads'])
                self.assertIsNone(route['selected'])

    def test_observed_local_choice_is_not_asked_again_but_body_is_required(self):
        file = self.f.skill('team-report', 'HTML 보고서 제작')
        context = self.output()
        self.assertEqual('choose', context['skillExecution']['mode'])
        route = self.state()['skillWorkflow']
        data = inventory_skills(self.f.state, project_root=self.f.project,
                                plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
        item = next(row for row in data['skills'] if row['path'] == str(file))
        options = [row for row in data['skills'] if row['id'] in route['requiredChoiceIds']]
        question = '어떤 스킬을 사용할까요?'
        observe(self.f.state, self.f.project, {
            'session_id': self.f.sid, 'hook_event_name': 'PostToolUse', 'tool_name': 'AskUserQuestion',
            'tool_input': {'questions': [{'question': question, 'header': '스킬 선택',
                'options': [{'label': row['name'] + ' (' + row['source'] + ')',
                             'description': '해당 출처의 제작 방식'} for row in options], 'multiSelect': False}]},
            'tool_response': {'answers': {question: item['name'] + ' (' + item['source'] + ')'}},
        })
        choose(self.f.state, self.f.project, self.f.sid, route['turn'], item['id'])
        self.f.read(file)
        self.assertEqual({}, self.before_write())

        context = self.compact()
        self.assertEqual('team-report', context['skillWorkflow']['continuation']['name'])
        route = self.state()['skillWorkflow']
        self.assertEqual(item['id'], route['turnChoices']['team-report'])
        self.assertNotIn('pendingChoice', route)
        self.assertNotIn('requiredChoiceIds', route)
        self.assertEqual('load', route['executionPlan']['mode'])
        self.assertNotIn('choiceIds', route['executionPlan'])
        denied = self.before_write()['hookSpecificOutput']
        self.assertEqual('deny', denied['permissionDecision'])
        self.assertIn('본문', denied['permissionDecisionReason'])
        self.assertNotIn('어떤 스킬', denied['permissionDecisionReason'])
        self.f.read(file)
        self.assertEqual({}, self.before_write())

    def test_new_request_does_not_inherit_previous_choice_as_continuation(self):
        self.output()
        self.native_load('company-agent:html-report')
        previous_turn = self.state()['turnId']
        self.output('PPT 발표자료 만들어줘')
        self.assertNotEqual(previous_turn, self.state()['turnId'])
        context = self.compact()
        self.assertNotIn('continuation', context['skillWorkflow'])
        self.assertIsNone(self.state()['skillWorkflow']['selected'])

    def test_another_project_cannot_continue_same_session_choice(self):
        self.output()
        self.native_load('company-agent:html-report')
        self.f.project = self.f.root / 'another-project'
        self.f.project.mkdir()
        context = self.compact()
        self.assertNotIn('continuation', context['skillWorkflow'])
        self.assertEqual({}, self.state()['skillWorkflow']['readSkills'])


if __name__ == '__main__':
    unittest.main()
