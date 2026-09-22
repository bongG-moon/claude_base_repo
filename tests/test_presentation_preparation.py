"""Choice preparation is not an artifact failure, permission grant or mutation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'
sys.path.insert(0, str(SCRIPTS))
from company_agent.execution_contract import classify_command, safe_permission
from company_agent.state import begin_turn, load_session, record_activity, stop_decision
from company_agent.runtime_diagnostics import failure_hint, recovery_hint_once


class PresentationPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '한글 상태'
        self.cli = f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}"'
        self.sid = 'ppt-preparation'

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-X', 'utf8', '-B', str(SCRIPTS / 'harness_cli.py'),
                               'business', *args, '--state-root', str(self.root)],
                              capture_output=True, encoding='utf-8', timeout=20,
                              env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})

    def choices(self):
        return {'creationMode': 'new', 'purpose': '보고', 'audience': '부서장',
                'slideCount': 3, 'designPreset': 'business'}

    def payload(self, tool, inputs, **extra):
        return {'session_id': self.sid, 'hook_event_name': 'PostToolUse',
                'tool_name': tool, 'tool_input': inputs, **extra}

    def test_initial_questions_need_no_spec_file_or_state_write(self):
        for action in ('ppt-choices', 'html-choices'):
            with self.subTest(action=action):
                result = self.run_cli(action)
                self.assertEqual(0, result.returncode, result.stderr + result.stdout)
                self.assertEqual('input_required', json.loads(result.stdout)['status'])
                self.assertFalse(self.root.exists())

    def test_preview_required_is_successful_preparation_not_a_shell_error(self):
        spec = Path(self.temp.name) / '선택.json'
        spec.write_text(json.dumps(self.choices(), ensure_ascii=False), encoding='utf-8')
        result = self.run_cli('ppt-choices', '--spec', str(spec))
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        body = json.loads(result.stdout)
        self.assertEqual('preview_required', body['status'])
        self.assertTrue(body['choicesReady'])
        self.assertEqual('prepare_full_job', body['nextAction'])
        self.assertFalse(self.root.exists())
        self.assertEqual([spec], list(Path(self.temp.name).iterdir()))

    def test_choice_file_errors_are_actionable_without_echoing_content(self):
        spec = Path(self.temp.name) / '잘못된 선택.json'
        for content in ('{"PRIVATE_SOURCE": ', '[]'):
            spec.write_text(content, encoding='utf-8')
            result = self.run_cli('ppt-choices', '--spec', str(spec))
            self.assertEqual(1, result.returncode)
            body = json.loads(result.stdout)
            self.assertEqual('invalid_choice_spec', body['code'])
            self.assertEqual('repair_choice_spec', body['nextAction'])
            self.assertNotIn('PRIVATE_SOURCE', result.stdout)
            self.assertFalse(self.root.exists())
        result = self.run_cli('html-choices', '--spec', str(spec.with_name('없는 선택.json')))
        self.assertEqual('invalid_choice_spec', json.loads(result.stdout)['code'])
        self.assertIn('선택 파일이 없습니다', json.loads(result.stdout)['message'])
        self.assertFalse(self.root.exists())

    def test_utf8_bom_cannot_hide_oversize_or_unread_metadata_tail(self):
        from company_agent.state import _is_ppt_choices_spec_write, _is_html_choices_spec_write
        folder = self.root / 'tmp'
        folder.mkdir(parents=True)
        for kind, validator in (('ppt', _is_ppt_choices_spec_write), ('html', _is_html_choices_spec_write)):
            file = folder / f'{kind}-choices-over.json'
            # The first 8193 bytes would decode to 8190 chars and valid JSON
            # if the byte limit were checked only after removing the BOM.
            file.write_bytes(b'\xef\xbb\xbf{}' + b' ' * 8188 + b'{"slides":[{"title":"hidden"}]}')
            self.assertFalse(validator('Edit', {'file_path': str(file)}, self.root))
            file.write_bytes(b'\xef\xbb\xbf{}')
            self.assertTrue(validator('Edit', {'file_path': str(file)}, self.root))

    def test_preparation_and_exact_help_are_readonly_not_auto_approved(self):
        for leaf in ('ppt-choices', 'html-choices'):
            for suffix in ('', ' --help', f' --state-root "{self.root}"'):
                command = f'{self.cli} business {leaf}{suffix}'
                self.assertEqual('read_only', classify_command(command))
                self.assertIsNone(safe_permission({'hook_event_name': 'PermissionRequest',
                    'tool_name': 'Bash', 'tool_input': {'command': command}}, self.root))
                for extra in (' > result.json', '; echo changed', ' --bogus value'):
                    self.assertEqual('unknown', classify_command(command + extra))
        for leaf in ('ppt', 'ppt-design-preview', 'html', 'artifact-start', 'artifact-publish'):
            self.assertEqual('read_only', classify_command(f'{self.cli} business {leaf} --help'))
            self.assertEqual('unknown', classify_command(f'{self.cli} business {leaf} --help --output output.pptx'))

    def test_successful_ppt_choice_edits_and_queries_do_not_trigger_stop(self):
        begin_turn(self.sid, 'MEDIUM', False, [], self.root)
        file = self.root / 'tmp/ppt-choices-one.json'
        file.parent.mkdir(parents=True, exist_ok=True)
        for choices in ({}, {'creationMode': 'new'}, self.choices()):
            text = json.dumps(choices, ensure_ascii=False)
            file.write_text(text, encoding='utf-8')
            for tool in ('Write', 'Edit'):
                before = load_session(self.sid, self.root)['taskToolCount']
                inputs = {'file_path': str(file), 'content': text} if tool == 'Write' else {
                    'file_path': str(file), 'old_string': 'new', 'new_string': 'new'}
                state = record_activity(self.payload(tool, inputs), self.root)
                self.assertEqual(0, state['mutationCount'])
                self.assertEqual(before, state['taskToolCount'])
            for args in ('', ' --help', f' --spec "{file}"'):
                state = record_activity(self.payload('Bash', {
                    'command': f'{self.cli} business ppt-choices{args}'}), self.root)
                self.assertEqual(0, state['mutationCount'])
            self.assertEqual({}, stop_decision({'session_id': self.sid}, self.root))

    def test_metadata_exception_cannot_clear_existing_changes_or_hide_job(self):
        begin_turn(self.sid, 'MEDIUM', False, [], self.root)
        file = self.root / 'tmp/ppt-choices-one.json'
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(self.choices()), encoding='utf-8')
        record_activity(self.payload('Write', {'file_path': str(self.root / 'report.md')}), self.root)
        state = record_activity(self.payload('Edit', {'file_path': str(file)}), self.root)
        self.assertEqual(1, state['mutationCount'])
        self.assertEqual('block', stop_decision({'session_id': self.sid}, self.root)['decision'])
        file.write_text(json.dumps({**self.choices(), 'slides': [{'title': '실제 자료'}]}), encoding='utf-8')
        state = record_activity(self.payload('Edit', {'file_path': str(file)}), self.root)
        self.assertEqual(2, state['mutationCount'])
        file.write_text(json.dumps(self.choices()), encoding='utf-8')
        state = record_activity(self.payload('Edit', {'file_path': str(file)},
            hook_event_name='PostToolUseFailure', error='partial write failed'), self.root)
        self.assertEqual(3, state['mutationCount'])

    def test_classifier_outage_suggests_one_retry_then_stops_without_faking_success(self):
        begin_turn(self.sid, 'MEDIUM', False, [], self.root)
        payload = self.payload('Bash', {'command': 'PRIVATE_COMMAND'},
            hook_event_name='PostToolUseFailure',
            error='HCP-LLM-Latest[1m] is temporarily unavailable (timed out), so auto mode cannot determine the safety of Bash right now.')
        hint = failure_hint(payload)
        record_activity(payload, self.root)
        self.assertIs(hint, recovery_hint_once(payload, hint, self.root))
        second = recovery_hint_once(payload, hint, self.root)
        self.assertIn('재시도는 끝났습니다', second['instruction'])
        self.assertIsNone(recovery_hint_once(payload, hint, self.root))
        self.assertNotIn('decision', stop_decision({'session_id': self.sid}, self.root))
        state = load_session(self.sid, self.root)
        self.assertIsNone(state['verification'])
        self.assertNotIn('PRIVATE_COMMAND', json.dumps(state))
        begin_turn(self.sid, 'MEDIUM', False, [], self.root)
        self.assertIs(hint, recovery_hint_once(payload, hint, self.root))


if __name__ == '__main__':
    unittest.main()
