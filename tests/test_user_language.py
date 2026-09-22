"""Question UI translation preserves choice meaning, identifiers and permissions."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import user_language
from company_agent.state import begin_turn, load_session


class QuestionDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session = 'question-display'
        self.turn()

    def turn(self, prompt='작업을 진행해줘'):
        begin_turn(self.session, 'MEDIUM', False, [], self.root)
        self.prepare(prompt)

    def prepare(self, prompt):
        user_language.prepare_questions(self.root, {'session_id': self.session, 'prompt': prompt})

    def payload(self, questions=None, **fields):
        return {'session_id': self.session, 'tool_name': 'AskUserQuestion', 'tool_input': {
            'questions': questions if questions is not None else [{
                'question': '어떤 방식으로 진행할까요?', 'header': 'Scope',
                'options': [{'label': 'Continue (Recommended)', 'description': '계속 진행합니다.'},
                            {'label': 'Cancel', 'description': '현재 작업을 취소합니다.'}],
            }], **fields}}

    def preflight(self, payload):
        return user_language.question_preflight(self.root, payload)

    def test_common_short_choices_translate_without_retry_or_permission_grant(self):
        payload = self.payload()
        before = copy.deepcopy(payload)
        result = self.preflight(payload)['hookSpecificOutput']
        self.assertNotIn('permissionDecision', result)
        question = result['updatedInput']['questions'][0]
        self.assertEqual('범위', question['header'])
        self.assertEqual(['계속 (추천)', '취소'], [option['label'] for option in question['options']])
        self.assertEqual(before, payload)
        self.assertFalse(load_session(self.session, self.root)['questionLanguage']['repairUsed'])
        self.assertEqual({}, self.preflight({**payload, 'tool_input': result['updatedInput']}))
        self.assertEqual(result, self.preflight(payload)['hookSpecificOutput'])

    def test_multiple_questions_keep_native_answer_keys_and_all_metadata(self):
        questions = [{
            'question': '설정을 어떻게 적용할까요?', 'header': 'Options', 'multiSelect': False,
            'id': 'settings-choice', 'options': [
                {'label': 'Use existing', 'description': 'Keep the current settings',
                 'id': 'keep_current', 'value': 'Continue', 'preview': 'Use existing'},
                {'label': 'Create new', 'description': '새 설정을 만듭니다.', 'value': 'new'},
            ],
        }, {
            'question': '어떤 모델을 쓸까요?', 'header': 'Mode', 'multiSelect': True,
            'options': [{'label': 'Claude Code (Recommended)', 'description': '`claude --model opus`'},
                        {'label': 'Python', 'description': 'Python 사용'}],
        }]
        payload = self.payload(questions, metadata={'source': 'terminal'}, permissionMode='default')
        result = self.preflight(payload)['hookSpecificOutput']['updatedInput']
        self.assertEqual([q['question'] for q in questions], [q['question'] for q in result['questions']])
        self.assertEqual('기존 항목 사용', result['questions'][0]['options'][0]['label'])
        self.assertEqual('현재 설정 유지', result['questions'][0]['options'][0]['description'])
        self.assertEqual('Claude Code (추천)', result['questions'][1]['options'][0]['label'])
        expected = copy.deepcopy(payload['tool_input'])
        for q_old, q_new in zip(expected['questions'], result['questions']):
            q_old['header'] = q_new['header']
            for old, new in zip(q_old['options'], q_new['options']):
                for key in ('label', 'description'):
                    old[key] = new[key]
        self.assertEqual(expected, result)
        # Returned native answers use the unchanged question plus visible label.
        answer = {questions[0]['question']: result['questions'][0]['options'][0]['label']}
        answered = {**payload, 'tool_input': {**result, 'answers': answer}}
        self.assertEqual({}, self.preflight(answered))
        self.assertEqual(answer, answered['tool_input']['answers'])

    def test_storage_scope_and_cleanup_choices_are_korean_without_changing_values(self):
        payload = self.payload([{'question': '적용 범위를 골라 주세요.', 'header': 'Scope',
            'options': [{'label': 'Personal (Recommended)', 'description': '개인 범위입니다.', 'value': 'personal'},
                        {'label': 'This project', 'description': '현재 프로젝트 범위입니다.', 'value': 'project'}]},
            {'question': '어떻게 처리할까요?', 'header': 'Confirmation',
             'options': [{'label': 'Keep', 'value': 'keep'},
                         {'label': 'Move to trash', 'value': 'trash'},
                         {'label': 'Delete permanently', 'value': 'delete'}]}])
        result = self.preflight(payload)['hookSpecificOutput']
        self.assertNotIn('permissionDecision', result)
        questions = result['updatedInput']['questions']
        self.assertEqual(['개인 (추천)', '이 프로젝트'], [o['label'] for o in questions[0]['options']])
        self.assertEqual(['유지', '휴지통으로 이동', '영구 삭제'], [o['label'] for o in questions[1]['options']])
        self.assertEqual(['keep', 'trash', 'delete'], [o['value'] for o in questions[1]['options']])

    def test_identifiers_paths_code_names_and_quoted_labels_are_preserved(self):
        names = ['Python', 'React', 'Claude Code', 'Visual Studio Code', 'Noto Sans KR', 'gpt-5.4',
                 'mcp__corp-db-read__query', 'AskUserQuestion', 'Read', 'Write', 'Edit',
                 'company-agent:small-worker', 'team-report (project)', 'report.pptx',
                 r'C:\Users\A User\report draft.pptx', '/tmp/my-report.md',
                 r'C:\Users\A User\draft (Recommended)', '/tmp/draft (Recommended)',
                 '`Continue`', '`npm run build`', 'https://example.com/Continue']
        for name in names:
            with self.subTest(name=name):
                payload = self.payload([{'question': '사용할 항목을 골라 주세요.', 'header': '선택',
                                         'options': [{'label': name, 'description': '이 항목 사용'}]}])
                self.assertEqual({}, self.preflight(payload))

    def test_unknown_short_prose_is_repaired_once_including_mixed_korean(self):
        for text in ('Advanced settings', 'Which format?', '두 가지 중 Choose carefully', 'Advanced', 'Faster'):
            with self.subTest(text=text):
                self.turn()
                payload = self.payload([{'question': '무엇을 쓸까요?', 'header': '선택',
                                         'options': [{'label': text}, {'label': '직접 입력'}]}])
                self.assertEqual('deny', self.preflight(payload)['hookSpecificOutput']['permissionDecision'])
                self.prepare('같은 입력이 다시 전달됨')
                self.assertEqual({}, self.preflight(payload))

    def test_translation_does_not_consume_unknown_prose_repair_budget(self):
        self.preflight(self.payload())
        unknown = self.payload([{'question': 'Which format?', 'header': '선택',
                                 'options': [{'label': 'Python'}, {'label': 'React'}]}])
        self.assertEqual('deny', self.preflight(unknown)['hookSpecificOutput']['permissionDecision'])
        self.assertEqual({}, self.preflight(unknown))
        self.turn()
        self.assertEqual('deny', self.preflight(unknown)['hookSpecificOutput']['permissionDecision'])

    def test_label_collisions_are_never_rewritten_into_ambiguous_answers(self):
        for labels in (['Continue', '계속'], ['Yes', 'yes'], ['Continue (Recommended)', '계속 (추천)']):
            with self.subTest(labels=labels):
                self.turn()
                payload = self.payload([{'question': '어느 쪽을 쓸까요?', 'header': '선택',
                                         'options': [{'label': label} for label in labels]}])
                self.assertEqual('deny', self.preflight(payload)['hookSpecificOutput']['permissionDecision'])
                self.assertEqual({}, self.preflight(payload))
                self.assertEqual(labels, [o['label'] for o in payload['tool_input']['questions'][0]['options']])

    def test_explicit_ui_languages_leave_whole_input_unchanged(self):
        for prompt in ('질문은 영어로 해줘', '질문과 선택지는 일본어로 해줘', '영어로 질문해줘',
                       '질문은 반드시 영어로 해줘',
                       'Please ask in English', 'Please ask me questions in English',
                       'Keep questions and options in English', 'Use English for all questions',
                       'All terminal choices should be in English',
                       'Please respond in Japanese'):
            with self.subTest(prompt=prompt):
                self.turn(prompt)
                self.assertTrue(load_session(self.session, self.root)['questionLanguage']['otherRequested'])
                self.assertEqual({}, self.preflight(self.payload()))

    def test_deliverable_language_does_not_change_question_language(self):
        for prompt in ('영어로 보고서를 작성해줘', '영어로 보고서 작성하고 질문해줘',
                       '질문에 쓸 영어 보고서를 작성해줘', 'Write an English email and ask me which format.',
                       '영어로 보고서를 작성하고 질문과 피드백은 한국어로 해줘',
                       '질문은 영어로 하지 말아줘', '영어로 질문하지 마',
                       "Please don't respond in English", "Don't ask in English"):
            with self.subTest(prompt=prompt):
                self.turn(prompt)
                self.assertFalse(load_session(self.session, self.root)['questionLanguage']['otherRequested'])
                self.assertIn('updatedInput', self.preflight(self.payload())['hookSpecificOutput'])

    def test_explicit_not_korean_is_not_overridden_by_default_translation(self):
        for prompt in ('한국어로 질문하지 마', "Don't ask in Korean"):
            with self.subTest(prompt=prompt):
                self.turn(prompt)
                self.assertTrue(load_session(self.session, self.root)['questionLanguage']['otherRequested'])
                self.assertEqual({}, self.preflight(self.payload()))

    def test_only_ask_user_question_and_unanswered_inputs_are_eligible(self):
        for changes in ({'tool_name': 'PermissionRequest'}, {'tool_name': 'Bash'}, {'session_id': ''},
                        {'tool_input': None}, {'tool_input': {'questions': 'Continue'}},
                        {'tool_input': {'questions': [], 'answers': {'Q': 'Yes'}}}):
            with self.subTest(changes=changes):
                self.assertEqual({}, self.preflight({**self.payload(), **changes}))

    def test_language_state_does_not_retain_prompt_or_question_text(self):
        self.turn('비공개 메모 12345. 영어로 보고서 작성해줘')
        self.preflight(self.payload())
        stored = json.dumps(load_session(self.session, self.root)['questionLanguage'], ensure_ascii=False)
        self.assertNotIn('12345', stored)
        self.assertNotIn('어떤 방식', stored)


if __name__ == '__main__':
    unittest.main()
