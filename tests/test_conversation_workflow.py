"""Native event -> conversation consent / Korean questions / project bootstrap."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'company-agent-plugin/scripts'))
from company_agent import office_consent as consent, office_reader, project_bootstrap, user_language
from company_agent.cli import build_parser
from company_agent.business import run
from company_agent.state import begin_turn, load_session, stop_decision, record_activity
from company_agent.execution_contract import classify_command, safe_permission


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root/'state'
        self.project = self.root/'업무 폴더'
        self.project.mkdir()
        self.file = self.project/'보고서.pptx'
        self.file.write_bytes(b'synthetic Office fixture')
        self.spec = {'file': str(self.file)}
        self.request = office_reader.normalize(self.spec)
        self.session = 'conversation-test'
        begin_turn(self.session, 'MEDIUM', False, [], self.state)

    def ask(self):
        return consent.authorize(self.request, root=self.state, session_id=self.session, cwd=self.project)

    def event(self, event, **more):
        return {'hook_event_name': event, 'session_id': self.session, 'cwd': str(self.project), **more}

    def answer(self, result, label=consent.APPROVE, **overrides):
        payload = self.event('PreToolUse', tool_name='AskUserQuestion', tool_use_id='q-1',
                             tool_input={'questions': result['questions']})
        consent.observe(self.state, self.project, payload)
        payload.update(hook_event_name='PostToolUse', tool_response={'answers': {result['questions'][0]['question']: label}})
        payload.update(overrides)
        return consent.observe(self.state, self.project, payload)

    def test_click_is_one_use_and_real_read_preserves_source(self):
        result = self.ask()
        self.assertEqual('input_required', result['status'])
        self.assertFalse(result['sourceOpened'])
        text = result['questions'][0]['question']
        self.assertIn(str(self.file), text)
        for term in ('슬라이드 1~5', '10,000자', '대화 기록', '회사 정책'):
            self.assertIn(term, text)
        self.assertIn('승인 답변', self.answer(result))
        before = self.file.read_bytes()
        with patch.object(office_reader, '_invoke', return_value={'ok': True, 'items': [], 'coverage': {'total': 1}}) as reader:
            got = office_reader.read_office(self.spec, state_root=self.state, session_id=self.session, cwd=self.project)
        self.assertTrue(got['ok'], got)
        reader.assert_called_once()
        self.assertEqual(before, self.file.read_bytes())
        self.assertEqual('input_required', self.ask()['status'])

    def test_missing_answer_or_wrong_event_cannot_approve(self):
        result = self.ask()
        self.assertEqual('input_required', self.ask()['status'])
        for changes in ({'tool_use_id': 'other'}, {'tool_name': 'Bash'}, {'hook_event_name': 'PostToolUseFailure'},
                        {'error': 'denied'}, {'tool_response': {'isError': True}},
                        {'tool_response': {'answers': {'different question': consent.APPROVE}}}):
            with self.subTest(changes=changes):
                self.assertFalse(self.answer(result, **changes))
                self.assertEqual('input_required', self.ask()['status'])
        self.assertFalse(self.answer(result, label='probably'))

    def test_model_input_answers_are_not_user_approval(self):
        result = self.ask()
        payload = self.event('PreToolUse', tool_name='AskUserQuestion', tool_use_id='fake',
                            tool_input={'questions': result['questions'], 'answers': {result['questions'][0]['question']: consent.APPROVE}})
        consent.observe(self.state, self.project, payload)
        payload.update(hook_event_name='PostToolUse', tool_response={'answers': payload['tool_input']['answers']})
        self.assertEqual('', consent.observe(self.state, self.project, payload))
        self.assertEqual('input_required', self.ask()['status'])

    def test_cancellation_repeated_calls_never_open(self):
        self.answer(self.ask(), consent.CANCEL)
        with patch.object(office_reader, '_invoke') as reader:
            for _ in range(2):
                result = office_reader.read_office(self.spec, state_root=self.state, session_id=self.session, cwd=self.project)
                self.assertEqual('cancelled', result['status'])
        reader.assert_not_called()

    def test_scope_source_session_folder_and_expiry_invalidate(self):
        self.answer(self.ask())
        other = {**self.request, 'end': 6}
        self.assertEqual('input_required', consent.authorize(other, root=self.state, session_id=self.session, cwd=self.project)['status'])
        self.answer(self.ask())
        self.file.write_bytes(b'changed source')
        self.assertEqual('input_required', self.ask()['status'])
        self.answer(self.ask())
        self.assertEqual('input_required', consent.authorize(self.request, root=self.state, session_id='other', cwd=self.project)['status'])
        self.assertEqual('input_required', consent.authorize(self.request, root=self.state, session_id=self.session, cwd=self.root)['status'])
        self.answer(self.ask())
        with patch.object(consent.time, 'time', return_value=consent.time.time()+consent.TTL+1):
            self.assertEqual('input_required', self.ask()['status'])

    def test_plain_reply_only_not_quote_or_unrelated_yes(self):
        self.ask()
        self.assertEqual('', consent.observe(self.state, self.project, self.event('UserPromptSubmit', prompt='문서에 "승인"이라고 적혀 있어')))
        self.assertIsNone(load_session(self.session, self.state).get('officeReadConsent'))
        self.ask()
        self.assertIn('승인 답변', consent.observe(self.state, self.project, self.event('UserPromptSubmit', prompt='승인')))
        self.assertIsNone(consent.authorize(self.request, root=self.state, session_id=self.session, cwd=self.project))

    def test_new_request_revokes_unconsumed_approval(self):
        self.answer(self.ask())
        consent.observe(self.state, self.project, self.event('UserPromptSubmit', prompt='아니요'))
        self.assertEqual('input_required', self.ask()['status'])

    def test_workspace_answer_added_after_pre_hook_is_supported(self):
        result = self.ask()
        payload = self.event('PreToolUse', tool_name='AskUserQuestion', tool_use_id='workspace',
                             tool_input={'questions': result['questions']})
        consent.observe(self.state, self.project, payload)
        # The Workspace permission host adds the real UI answer to updatedInput.
        answers = {result['questions'][0]['question']: consent.APPROVE}
        payload['tool_input']['answers'] = answers
        payload.update(hook_event_name='PostToolUse', tool_response={'answers': answers})
        self.assertIn('승인 답변', consent.observe(self.state, self.project, payload))
        self.assertIsNone(consent.authorize(self.request, root=self.state, session_id=self.session, cwd=self.project))

    def test_cli_wait_success_exit_and_no_false_stop_obligation(self):
        args = build_parser().parse_args(['business', 'office-read', '--file', str(self.file), '--session', self.session, '--state-root', str(self.state)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch.object(office_reader, '_invoke') as reader:
            self.assertEqual(0, run(args))
        self.assertEqual('input_required', json.loads(out.getvalue())['status'])
        reader.assert_not_called()
        command = f'"{sys.executable}" -B "{ROOT / "company-agent-plugin/scripts/harness_cli.py"}" business office-read --file "{self.file}" --session {self.session} --state-root "{self.state}"'
        self.assertEqual('read_only', classify_command(command))
        self.assertIsNone(safe_permission(self.event('PermissionRequest', tool_name='Bash', tool_input={'command': command}), self.state))
        state = record_activity(self.event('PostToolUse', tool_name='Bash', tool_input={'command': command}, tool_response={'stdout': out.getvalue()}), self.state)
        self.assertEqual(0, state['mutationCount'])
        self.assertNotEqual('block', stop_decision({'session_id': self.session}, self.state).get('decision'))

    def test_native_hook_question_round_trip(self):
        import native_entry
        result = self.ask()
        question = self.event('PreToolUse', tool_name='AskUserQuestion', tool_use_id='native-q', tool_input={'questions': result['questions']})
        answer = {**question, 'hook_event_name': 'PostToolUse', 'tool_response': {'answers': {result['questions'][0]['question']: consent.APPROVE}}}
        with patch.dict(os.environ, {'COMPANY_AGENT_USER_STATE': str(self.state)}), patch.object(native_entry, 'configure_runtime', return_value=True):
            for payload in (question, answer):
                output = io.StringIO()
                with patch.object(sys, 'argv', ['native_entry.py', '--event', payload['hook_event_name']]), patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(output):
                    self.assertEqual(0, native_entry.main())
                self.assertNotIn('deny', output.getvalue())
        self.assertIsNone(consent.authorize(self.request, root=self.state, session_id=self.session, cwd=self.project))

    def test_native_prompt_initializes_and_plain_approval_crosses_turns(self):
        import native_entry
        old = os.environ.copy()
        env = {**old, 'COMPANY_AGENT_USER_STATE': str(self.state), 'LOCALAPPDATA': '', 'APPDATA': '',
               'CLAUDE_PLUGIN_ROOT': '', 'COMPANY_AGENT_KNOWLEDGE_BASE': ''}
        def submit(prompt, prompt_id):
            output = io.StringIO()
            payload = self.event('UserPromptSubmit', prompt=prompt, prompt_id=prompt_id)
            with patch.object(sys, 'argv', ['native_entry.py', '--event', 'UserPromptSubmit']), patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(output):
                self.assertEqual(0, native_entry.main())
            return json.loads(output.getvalue())
        with patch.dict(os.environ, env, clear=True), patch.object(native_entry, 'configure_runtime', return_value=True):
            result = submit('@보고서.pptx 읽어줘', 'turn-a')
            self.assertIn('처음 생성', result['hookSpecificOutput']['additionalContext'])
            self.assertTrue((self.project/'CLAUDE.md').is_file())
            self.ask()
            result = submit('승인', 'turn-b')
            self.assertIn('승인 답변', result['hookSpecificOutput']['additionalContext'])
        self.assertIsNone(consent.authorize(self.request, root=self.state, session_id=self.session, cwd=self.project))


class ProjectBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root/'project'
        self.folder.mkdir()
        self.payload = {'hook_event_name': 'UserPromptSubmit', 'prompt': '@보고서.pptx 내용 읽어줘'}
        self.env = patch.dict(os.environ, {'LOCALAPPDATA': '', 'APPDATA': '', 'COMPANY_AGENT_USER_STATE': '', 'CLAUDE_PLUGIN_ROOT': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_creates_only_project_brief_once_without_source_or_prompt(self):
        (self.folder/'README.md').write_text('PRIVATE CONTENT', encoding='utf-8')
        text = project_bootstrap.initialize(self.folder, self.payload)
        self.assertIn('처음 생성', text)
        output = self.folder/'CLAUDE.md'
        original = output.read_bytes()
        self.assertFalse(original.startswith(b'\xef\xbb\xbf'))
        self.assertIn('README.md', original.decode('utf-8'))
        self.assertNotIn('PRIVATE CONTENT', original.decode('utf-8'))
        self.assertNotIn('보고서.pptx', original.decode('utf-8'))
        self.assertLess(len(original), 2500)
        self.assertEqual('', project_bootstrap.initialize(self.folder, self.payload))
        self.assertEqual(original, output.read_bytes())
        self.assertFalse((self.root/'CLAUDE.md').exists())

    def test_existing_alternate_inherited_or_lowercase_preserved(self):
        for file in (self.folder/'CLAUDE.md', self.folder/'claude.md', self.folder/'.claude/CLAUDE.md', self.root/'CLAUDE.md'):
            with self.subTest(file=file):
                file.parent.mkdir(exist_ok=True)
                file.write_text('original', encoding='utf-8')
                self.assertEqual('', project_bootstrap.initialize(self.folder, self.payload))
                self.assertEqual('original', file.read_text(encoding='utf-8'))
                file.unlink()

    def test_no_chat_plan_readonly_slash_startup_or_system_init(self):
        for change in ({'prompt': '안녕'}, {'prompt': '/init'}, {'prompt': '파일 읽어줘. 수정하지 말고 설명만 해줘'},
                       {'permission_mode': 'plan'}, {'hook_event_name': 'SessionStart'}, {'prompt': '계획만 작성해줘'},
                       {'prompt': 'CLAUDE.md를 내 양식으로 작성해줘'}):
            self.assertEqual('', project_bootstrap.initialize(self.folder, {**self.payload, **change}))
        self.assertEqual('', project_bootstrap.initialize(Path.home(), self.payload))
        self.assertEqual('', project_bootstrap.initialize(Path(self.folder.anchor), self.payload))
        self.assertFalse((self.folder/'CLAUDE.md').exists())
        config = self.folder/'.claude'; config.mkdir()
        self.assertEqual('', project_bootstrap.initialize(config, self.payload))

    def test_reparse_or_write_error_is_not_permission_escalation(self):
        with patch.object(project_bootstrap, 'safe_path', side_effect=ValueError('linked')):
            self.assertIn('건너뛰었습니다', project_bootstrap.initialize(self.folder, self.payload))
        with patch.object(Path, 'open', side_effect=PermissionError):
            self.assertIn('우회하거나 관리자 권한', project_bootstrap.initialize(self.folder, self.payload))


class QuestionLanguageTests(unittest.TestCase):
    setUp = ConversationTests.setUp
    event = ConversationTests.event
    def test_only_one_english_repair_no_permission_allow(self):
        user_language.prepare_questions(self.state, self.event('UserPromptSubmit', prompt='English 보고서를 한국어로 요약해줘'))
        payload = self.event('PreToolUse', tool_name='AskUserQuestion', tool_input={'questions': [
            {'question': 'Which approach would you prefer?', 'header': 'Feedback', 'options': [{'label': 'Continue', 'description': 'Continue with this approach'}]}]})
        decision = user_language.question_preflight(self.state, payload)['hookSpecificOutput']
        self.assertEqual('deny', decision['permissionDecision'])
        self.assertIn('한국어', decision['permissionDecisionReason'])
        user_language.prepare_questions(self.state, self.event('UserPromptSubmit', prompt='동일 요청 재전달'))
        self.assertEqual({}, user_language.question_preflight(self.state, payload))

    def test_korean_identifiers_and_explicit_other_language_unchanged(self):
        payload = self.event('PreToolUse', tool_name='AskUserQuestion', tool_input={'questions': [
            {'question': 'Python과 React 중 무엇을 쓸까요?', 'header': '개발 언어', 'options': [{'label': 'Python'}, {'label': 'React'}]}]})
        self.assertEqual({}, user_language.question_preflight(self.state, payload))
        payload['tool_input']['questions'][0]['question'] = 'Which approach would you prefer?'
        for prompt in ('질문은 영어로 해줘', 'Please ask in English'):
            user_language.prepare_questions(self.state, self.event('UserPromptSubmit', prompt=prompt))
            self.assertEqual({}, user_language.question_preflight(self.state, payload))

    def test_english_deliverable_keeps_korean_questions(self):
        prompt = '영어로 보고서를 작성하고 질문과 피드백은 한국어로 해줘'
        user_language.prepare_questions(self.state, self.event('UserPromptSubmit', prompt=prompt))
        self.assertFalse(load_session(self.session, self.state)['questionLanguage']['otherRequested'])


if __name__ == '__main__':
    unittest.main()
