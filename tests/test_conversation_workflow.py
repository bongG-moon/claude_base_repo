"""Native events, pending business choices, Korean questions and project bootstrap."""
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
from company_agent import project_bootstrap, user_language
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
        self.session = 'conversation-test'
        begin_turn(self.session, 'MEDIUM', False, [], self.state)

    def event(self, event, **more):
        return {'hook_event_name': event, 'session_id': self.session, 'cwd': str(self.project), **more}

    def test_cli_wait_success_exit_and_no_false_stop_obligation(self):
        choices = self.project / 'choices.json'
        choices.write_text('{}', encoding='utf-8')
        args = build_parser().parse_args(['business', 'html-choices', '--spec', str(choices), '--state-root', str(self.state)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(0, run(args))
        self.assertEqual('input_required', json.loads(out.getvalue())['status'])
        command = f'"{sys.executable}" -B "{ROOT / "company-agent-plugin/scripts/harness_cli.py"}" business html-choices --spec "{choices}" --state-root "{self.state}"'
        self.assertEqual('read_only', classify_command(command))
        self.assertIsNone(safe_permission(self.event('PermissionRequest', tool_name='Bash', tool_input={'command': command}), self.state))
        state = record_activity(self.event('PostToolUse', tool_name='Bash', tool_input={'command': command}, tool_response={'stdout': out.getvalue()}), self.state)
        self.assertEqual(0, state['mutationCount'])
        self.assertNotEqual('block', stop_decision({'session_id': self.session}, self.state).get('decision'))

    def test_native_hook_question_round_trip(self):
        import native_entry
        question_text = '어떤 보고서 분량으로 작성할까요?'
        questions = [{'header': '보고서 분량', 'question': question_text,
                      'options': [{'label': '핵심'}, {'label': '상세'}]}]
        question = self.event('PreToolUse', tool_name='AskUserQuestion', tool_use_id='native-q', tool_input={'questions': questions})
        answer = {**question, 'hook_event_name': 'PostToolUse', 'tool_response': {'answers': {question_text: '핵심'}}}
        with patch.dict(os.environ, {'COMPANY_AGENT_USER_STATE': str(self.state)}), patch.object(native_entry, 'configure_runtime', return_value=True):
            for payload in (question, answer):
                output = io.StringIO()
                with patch.object(sys, 'argv', ['native_entry.py', '--event', payload['hook_event_name']]), patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(output):
                    self.assertEqual(0, native_entry.main())
                self.assertNotIn('deny', output.getvalue())
        self.assertEqual(0, load_session(self.session, self.state)['mutationCount'])

    def test_native_prompt_initializes_project_and_next_turn_preserves_brief(self):
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
            result = submit('HTML 보고서 만들어줘', 'turn-a')
            self.assertIn('처음 생성', result['hookSpecificOutput']['additionalContext'])
            self.assertTrue((self.project/'CLAUDE.md').is_file())
            brief = (self.project/'CLAUDE.md').read_bytes()
            first_turn = load_session(self.session, self.state)['turnId']
            result = submit('HTML 보고서 구성을 설명해줘', 'turn-b')
            self.assertNotIn('처음 생성', result['hookSpecificOutput']['additionalContext'])
            self.assertNotEqual(first_turn, load_session(self.session, self.state)['turnId'])
            self.assertEqual(brief, (self.project/'CLAUDE.md').read_bytes())


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
