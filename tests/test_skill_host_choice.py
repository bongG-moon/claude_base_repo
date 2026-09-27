from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent import skill_host_choice as host


class HostSkillChoiceTests(unittest.TestCase):
    def setUp(self):
        self.item = {'id': 'company:html', 'name': 'html-report',
                     'invocation': 'company-agent:html-report', 'sha256': 'hash'}
        self.data = {'skills': [self.item]}
        self.route = {'turn': 'turn1', 'revision': 'rev1',
                      'executionPlan': {'mode': 'load', **self.item}, 'readSkills': {}}
        self.inputs = {'questions': [{'question': '어떤 스킬을 사용할까요?', 'options': [
            {'label': 'artifact-design', 'description': '이미 불러온 디자인 스킬'},
            {'label': 'company-agent:html-report', 'description': '공통 HTML 보고서 제작'}]}]}

    def register(self):
        return host.register(self.route, 'artifact-design', self.data)

    def answer(self, label, **response):
        return host.observe_answer(self.route, self.data, self.inputs,
                                   {'answers': {'어떤 스킬을 사용할까요?': label}, **response})

    def test_unknown_success_prompts_once_then_current_host_choice_releases_workflow_only(self):
        self.assertIn('[스킬 선택]', self.register())
        self.assertEqual({'invocation', 'targetId', 'turn', 'revision', 'selected'}, set(self.route['hostChoice']))
        self.assertIsNone(self.register())
        self.assertEqual('deny', host.checkpoint(self.route, self.data)['hookSpecificOutput']['permissionDecision'])
        self.assertEqual({'kind': 'host'}, self.answer('artifact-design'))
        self.assertTrue(host.chosen(self.route))
        self.assertIsNone(host.checkpoint(self.route, self.data))
        self.assertNotIn('selected', self.route)
        self.assertEqual({}, self.route['readSkills'])
        self.route['turn'] = 'new-turn'
        self.assertFalse(host.chosen(self.route))

    def test_real_local_answer_returns_id_for_existing_apply_choice(self):
        self.register()
        self.assertEqual({'kind': 'local', 'id': 'company:html'}, self.answer('company-agent:html-report'))
        self.assertFalse(host.chosen(self.route))

    def test_forged_failed_ambiguous_or_negative_answers_stay_pending(self):
        self.register()
        for label in ('취소', 'artifact-design 말고', 'both artifact-design and html-report', '1', '없는스킬',
                      'artifact-design을 사용할지 모르겠어', 'Could artifact-design work here?'):
            with self.subTest(label=label):
                self.assertIsNone(self.answer(label))
        for response in ({'success': False}, {'isError': True}, {'is_error': True}):
            self.assertIsNone(self.answer('artifact-design', **response))
        self.inputs['answers'] = {}
        self.assertIsNone(self.answer('artifact-design'))
        self.assertFalse(host.chosen(self.route))

    def test_both_observed_options_must_have_distinct_known_identities(self):
        self.register()
        question = self.inputs['questions'][0]
        question['options'][1]['label'] = '없는스킬'
        self.assertIsNone(self.answer('artifact-design'))
        question['options'][1]['label'] = 'artifact-design'
        self.assertIsNone(self.answer('artifact-design'))
        question['options'].append({'label': 'html-report'})
        self.assertIsNone(self.answer('artifact-design'))

    def test_explicit_host_selection_does_not_create_a_question(self):
        for field in ('explicit', 'namedSkillChoices'):
            with self.subTest(field=field):
                self.route[field] = ['artifact-design']
                self.assertIsNone(self.register())
                self.assertNotIn('hostChoice', self.route)
                del self.route[field]

    def test_prepared_local_workflow_allows_optional_supplement_without_forcing_dual_use(self):
        self.route['selected'] = deepcopy(self.item)
        self.route['readSkills'][self.item['id']] = 'hash'
        self.assertIn('필요한 보조', self.register())
        self.assertNotIn('hostChoice', self.route)

    def test_explicit_local_choice_keeps_existing_target_without_another_question(self):
        for field in ('explicit', 'namedSkillChoices'):
            with self.subTest(field=field):
                self.route[field] = ['company-agent:html-report']
                self.assertIn('필요한 보조', self.register())
                self.assertNotIn('hostChoice', self.route)
                del self.route[field]

    def test_explicit_prepared_alternative_workflow_is_preserved(self):
        other = {'id': 'user:report', 'name': 'my-report', 'sha256': 'other-hash'}
        self.data['skills'].append(other)
        self.route['selected'] = other
        self.route['readSkills'][other['id']] = other['sha256']
        self.route['turnChoices'] = {'my-report': other['id']}
        self.assertIn('필요한 보조', self.register())
        self.assertNotIn('hostChoice', self.route)

    def test_unrelated_loaded_body_does_not_suppress_workflow_choice(self):
        other = {'id': 'user:reader', 'name': 'document-reader', 'sha256': 'reader-hash'}
        self.data['skills'].append(other)
        self.route['selected'] = other
        self.route['readSkills'][other['id']] = other['sha256']
        self.assertIn('[스킬 선택]', self.register())
        self.assertFalse(self.route['hostChoice']['selected'])

    def test_invalid_unknown_no_target_known_invocation_or_changed_catalog_add_no_evidence(self):
        self.assertIsNone(host.register(self.route, 'bad skill\n', self.data))
        self.assertIsNone(host.register(self.route, 'company-agent:html-report', self.data))
        self.route['executionPlan']['mode'] = 'general'
        self.assertIsNone(self.register())
        self.assertNotIn('hostChoice', self.route)
        self.route['executionPlan']['mode'] = 'load'
        self.register()
        self.assertIsNone(host.checkpoint(self.route, {'skills': []}))
        self.route['revision'] = 'changed'
        self.assertIsNone(self.answer('artifact-design'))
        self.assertFalse(host.chosen(self.route))

    def test_pending_choice_cannot_be_replaced_by_another_automatic_native_load(self):
        self.register()
        saved = deepcopy(self.route['hostChoice'])
        self.assertIsNone(host.register(self.route, 'unrelated-api', self.data))
        self.assertEqual(saved, self.route['hostChoice'])

    def test_short_exact_plaintext_continuation_only(self):
        self.register()
        continued = host.continuation(self.route, 'artifact-design으로 진행해줘', 'turn2', 'rev1')
        self.assertTrue(continued['selected'])
        self.assertEqual('turn2', continued['turn'])
        self.assertFalse(host.continuation(self.route, 'html-report로 해줘', 'turn2', 'rev1')['selected'])
        for prompt in ('1번', '그걸로 해줘', 'artifact-design 말고', 'artifact-design으로 새로운 ppt 만들어줘'):
            self.assertIsNone(host.continuation(self.route, prompt, 'turn2', 'rev1'))
        self.assertIsNone(host.continuation(self.route, 'artifact-design', 'turn2', 'rev2'))


if __name__ == '__main__':
    unittest.main()
