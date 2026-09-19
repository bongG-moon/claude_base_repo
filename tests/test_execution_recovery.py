"""Regression for failed Write -> nested shells -> regex traceback recovery."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent.paths import atomic_write_text
from company_agent.runtime_diagnostics import failure_hint, recovery_hint_once
from company_agent.state import begin_turn, load_session
from company_agent.text_encoding import SCRIPT_EXECUTION_RULE, WINDOWS_TEXT_RULE


class ExecutionRecoveryTests(unittest.TestCase):
    def payload(self, **values):
        return {'hook_event_name': 'PostToolUseFailure', 'tool_name': 'Bash',
                'session_id': 'recovery', 'error': 'Traceback (most recent call last):\n'
                    're.error: unterminated character set at position 0', **values}

    def test_regex_error_and_incomplete_python311_trace_are_distinct(self):
        self.assertEqual('python_regex_error', failure_hint(self.payload())['category'])
        trace = 'Traceback (most recent call last):\n  File "C:\\Python311\\Lib\\re\\__init__.py", line 227, in compile\n    return _compile(pattern, flags)'
        hint = failure_hint(self.payload(error=trace))
        self.assertEqual('python_regex_trace_incomplete', hint['category'])
        self.assertIn('마지막 예외 문장', hint['message'])
        self.assertIn('단정하지', hint['instruction'])
        self.assertEqual('failed_partial_effects_unknown', hint['executionState'])
        self.assertIn('re.escape', hint['instruction'])
        self.assertLess(len(hint['message'] + hint['instruction']), 500)

    def test_permission_denials_cancellation_and_success_are_not_retry_advice(self):
        for changes in ({'error': 'Permission denied'}, {'error': '사용자가 실행을 거절했습니다'},
                        {'is_interrupt': True}, {'error': 'cancelled'}, {'error': 'not approved'},
                        {'hook_event_name': 'PostToolUse'}, {'tool_name': 'Read'}):
            self.assertIsNone(failure_hint(self.payload(**changes)))
        for error in ('Permission denied', '권한 오류', ''):
            self.assertIsNone(failure_hint(self.payload(tool_name='Write', error=error)))

    def test_failed_write_checks_exact_path_not_nested_inline_retry(self):
        hint = failure_hint(self.payload(tool_name='Write', error='File path does not exist'))
        self.assertEqual('write_failed', hint['category'])
        for text in ('절대경로', '해당 파일만 Read', '단정하지', '인라인으로 전환하지', '성공한 기존 쓰기는 반복하지'):
            self.assertIn(text, hint['instruction'])

    def test_recovery_is_once_per_turn_without_retaining_source_or_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            begin_turn('recovery', 'MEDIUM', False, [], root)
            payload = self.payload(error=self.payload()['error'] + ' PRIVATE_REGEX',
                                   tool_input={'command': 'PRIVATE_COMMAND'})
            hint = failure_hint(payload)
            self.assertIs(hint, recovery_hint_once(payload, hint, root))
            self.assertIsNone(recovery_hint_once(payload, hint, root))
            state = load_session('recovery', root)
            self.assertNotIn('PRIVATE_', json.dumps(state))
            self.assertIsNone(state['verification'])
            begin_turn('recovery', 'MEDIUM', False, [], root)
            self.assertIs(hint, recovery_hint_once(payload, hint, root))

    def test_utf8_script_file_preserves_korean_and_regex_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / '한글 폴더' / '문자 검색.py'
            atomic_write_text(script, 'import re\nvalue = "한글 [제품](A)+? $100"\n'
                              'pattern = re.compile(re.escape(value))\nassert pattern.fullmatch(value)\nprint(value)\n')
            result = subprocess.run([sys.executable, '-X', 'utf8', str(script)],
                                    capture_output=True, encoding='utf-8', timeout=15,
                                    env={**os.environ, 'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'utf-8'})
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual('한글 [제품](A)+? $100', result.stdout.strip())

    def test_prevention_is_small_and_shared(self):
        self.assertIn(SCRIPT_EXECUTION_RULE, WINDOWS_TEXT_RULE)
        self.assertLess(len(SCRIPT_EXECUTION_RULE), 400)
        for text in ('Write 실패', '절대경로', '.py/.ps1', 'Read 확인', 'Python -X utf8', 'PowerShell -File', 're.escape'):
            self.assertIn(text, SCRIPT_EXECUTION_RULE)

    @unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows PowerShell required')
    def test_powershell51_file_keeps_unicode_without_nested_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / '한글 폴더' / '확인.ps1'
            atomic_write_text(script, '\ufeff[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)\n'
                              '$value = "한글 [제품](A)+?"\n'
                              'if ($value -notmatch [regex]::Escape($value)) { exit 2 }\n'
                              '[Console]::WriteLine($value)\n')
            result = subprocess.run([shutil.which('powershell.exe'), '-NoLogo', '-NoProfile', '-File', str(script)],
                                    capture_output=True, encoding='utf-8', timeout=15)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual('한글 [제품](A)+?', result.stdout.strip())


if __name__ == '__main__':
    unittest.main()
