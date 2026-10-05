"""Small hash receipts: host answers, stale replies and replay, without IO."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent import skill_question_receipts as receipts


class SkillQuestionReceiptTests(unittest.TestCase):
    def setUp(self):
        self.route = {'turn': 'turn-1', 'revision': 'rev-1', 'catalog': 'catalog-1',
                      'executionPlan': {'choiceIds': ['first', 'second']}}
        self.state = {'turnId': 'turn-1', 'nativePromptSha256': 'prompt-1'}
        self.input = {'questions': [{'question': '어떤 스킬을 쓸까요?', 'header': '선택',
                       'options': [{'label': '첫 번째'}, {'label': '두 번째'}]}]}
        self.pre = {'hook_event_name': 'PreToolUse', 'tool_use_id': 'ask-1', 'tool_input': self.input}
        self.answers = {'어떤 스킬을 쓸까요?': '첫 번째'}

    def prepare(self, payload=None, language=None):
        return receipts.prepare(self.state, self.route, payload or self.pre, language or {})

    def post(self, *, updated=True, **extra):
        inputs = deepcopy(self.input)
        if updated:
            inputs['answers'] = deepcopy(self.answers)
        return {'hook_event_name': 'PostToolUse', 'tool_use_id': 'ask-1', 'tool_input': inputs,
                'tool_response': {'answers': deepcopy(self.answers)}, **extra}

    def consume(self, payload=None):
        return receipts.consume(self.state, self.route, payload or self.post())

    def test_sdk_and_cli_shapes_preserve_original_input_and_store_no_text(self):
        for updated in (True, False):
            self.setUp()
            self.assertTrue(self.prepare())
            post = self.post(updated=updated)
            before = deepcopy(post)
            self.assertEqual(self.input, self.consume(post))
            self.assertEqual(before, post)
            stored = json.dumps(self.state, ensure_ascii=False)
            self.assertNotIn('어떤 스킬', stored)
            self.assertNotIn('첫 번째', stored)
            self.assertNotIn('ask-1', stored)

    def test_language_result_and_repeated_host_pre_keep_original_receipt(self):
        shown = deepcopy(self.input)
        shown['questions'][0]['header'] = '스킬 선택'
        self.prepare(language={'hookSpecificOutput': {'updatedInput': shown}})
        saved = deepcopy(self.state)
        shown['answers'] = self.answers
        self.assertFalse(self.prepare({**self.pre, 'tool_input': shown}))
        self.assertEqual(saved, self.state)
        self.assertEqual({'questions': shown['questions']}, self.consume(self.post(tool_input=shown)))

    def test_authored_answers_cannot_be_removed_or_replaced_to_rearm(self):
        for answers in ({}, self.answers):
            self.setUp()
            self.prepare({**self.pre, 'tool_input': {**self.input, 'answers': answers}})
            self.assertFalse(self.prepare())
            self.assertIsNone(self.consume(self.post(updated=False)))

    def test_failure_is_consumed_and_repeated_pre_cannot_rearm_or_enable_legacy(self):
        for extra in ({'hook_event_name': 'PostToolUseFailure'}, {'error': 'cancel'},
                      {'is_interrupt': True}, {'tool_error': 'failed'},
                      {'tool_response': {'success': False, 'answers': self.answers}},
                      {'tool_response': {'isError': True, 'answers': self.answers}},
                      {'tool_response': {'is_error': True, 'answers': self.answers}},
                      {'tool_input': ['invalid']},
                      {'tool_response': {'success': True}}):
            self.setUp()
            self.prepare()
            self.assertIsNone(self.consume(self.post(**extra)), extra)
            self.assertFalse(self.prepare())
            self.assertIsNone(self.consume())
            self.assertIsNone(self.consume(self.post(updated=False)))

    def test_turn_revision_prompt_catalog_and_questions_are_bound(self):
        for target, key in (('state', 'turnId'), ('state', 'nativePromptSha256'),
                            ('route', 'turn'), ('route', 'revision'), ('route', 'catalog')):
            self.setUp()
            self.prepare()
            getattr(self, target)[key] = 'different'
            self.assertIsNone(self.consume(), key)
        self.setUp()
        self.prepare()
        original = deepcopy(self.state)
        changed = deepcopy(self.pre)
        changed['tool_input']['questions'][0]['question'] = '다른 질문'
        self.prepare(changed)
        self.assertEqual(original, self.state)
        self.assertIsNone(self.consume(self.post(tool_input=changed['tool_input'])))

    def test_missing_or_changed_call_and_conflicting_response_never_select(self):
        for extra in ({'tool_use_id': None}, {'tool_use_id': 'other'},
                      {'tool_response': {'answers': {'어떤 스킬을 쓸까요?': '두 번째'}}},
                      {'tool_response': {'questions': [], 'answers': self.answers}}):
            self.setUp()
            self.prepare()
            self.assertIsNone(self.consume(self.post(**extra)), extra)

    def test_legacy_without_ids_only_accepts_result_answers(self):
        pre = {**self.pre, 'tool_use_id': None}
        self.assertFalse(self.prepare(pre))
        self.assertNotIn(receipts.KEY, self.state)
        self.assertEqual(self.input, self.consume(self.post(updated=False, tool_use_id=None)))
        self.assertIsNone(self.consume())

    def test_ordinary_questions_do_not_activate_receipts_and_host_choices_do(self):
        self.route['executionPlan'] = {'mode': 'load'}
        self.assertFalse(self.prepare())
        self.assertNotIn(receipts.KEY, self.state)
        self.route['hostChoice'] = {'turn': 'turn-1', 'revision': 'rev-1', 'targetId': 'local', 'selected': False}
        self.assertTrue(self.prepare())
        self.assertEqual(self.input, self.consume())

    def test_receipts_are_bounded_and_eviction_never_falls_back_to_legacy(self):
        for number in range(8):
            self.prepare({**self.pre, 'tool_use_id': 'ask-' + str(number)})
        self.assertEqual(receipts.MAX_RECEIPTS, len(self.state[receipts.KEY]['calls']))
        self.assertIsNone(self.consume(self.post(updated=False)))
        self.assertLess(len(json.dumps(self.state)), 2200)

    def test_malformed_receipts_do_not_block_new_question_or_trust_old_answer(self):
        for book in (None, [], {}, {'version': 1, 'calls': []}, {'version': 0, 'calls': {}}):
            self.setUp()
            self.state[receipts.KEY] = book
            self.assertIsNone(self.consume(self.post(updated=False)))
            self.assertTrue(self.prepare())
            self.assertEqual(self.input, self.consume())

    def test_denied_or_oversized_question_is_not_validated(self):
        self.assertFalse(self.prepare(language={'hookSpecificOutput': {'permissionDecision': 'deny'}}))
        self.assertNotIn(receipts.KEY, self.state)
        self.input['questions'][0]['question'] = '긴 질문' * 10000
        self.prepare()
        self.assertIsNone(self.consume())

    def test_bad_question_encoding_is_rejected_without_raising(self):
        self.input['questions'][0]['question'] = '\ud800'
        self.prepare()
        self.assertIsNone(self.consume())
        self.setUp()
        self.pre['tool_use_id'] = '\ud800'
        self.assertFalse(self.prepare())


if __name__ == '__main__':
    unittest.main()
