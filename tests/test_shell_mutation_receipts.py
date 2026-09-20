"""Completion accounting only: no shell commands in these tests are executed."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent.state import begin_turn, record_activity, stop_decision


class ShellMutationReceiptTests(unittest.TestCase):
    def check_event(self, command, expected, *, tool='Bash', failed=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            begin_turn('shell-audit', 'MEDIUM', False, (), root)
            payload = {'session_id': 'shell-audit', 'tool_name': tool,
                       'hook_event_name': 'PostToolUseFailure' if failed else 'PostToolUse',
                       'tool_input': {'command': command},
                       'tool_response': {'stdout': '', 'exitCode': 1 if failed else 0}}
            if failed:
                payload['error'] = 'Script failed after a possible partial write'
            state = record_activity(payload, root)
            self.assertEqual(int(expected), state['mutationCount'], command)
            stop = stop_decision({'session_id': 'shell-audit'}, root)
            self.assertEqual('block' if expected else None, stop.get('decision'), command)
            self.assertIsNone(state['verification'])

    def test_inline_runtimes_need_verification_even_without_a_script_extension(self):
        for command in [
            'node -e "require(\'fs\').writeFileSync(\'report.md\',\'changed\')"',
            'nodejs -e "process.exit(0)"',
            'bun -e "await Bun.write(\'report.md\',\'changed\')"',
            'deno eval "Deno.writeTextFileSync(\'report.md\',\'changed\')"',
            'ruby -e "File.write(\'report.md\',\'changed\')"',
            'perl -e "unlink q(report.md)"',
            '"C:\\Program Files\\nodejs\\node.exe" -e "process.exit(0)"',
            'node --version && node -e "process.exit(0)"',
        ]:
            with self.subTest(command=command):
                self.check_event(command, True)

    def test_runtime_queries_and_literal_mentions_do_not_create_false_obligations(self):
        for command in ['node --version', 'nodejs -v', 'bun --version', 'deno --version',
                        'ruby -v', 'perl -v', 'echo node', 'echo "node --version"',
                        'git status --short', 'ls -la']:
            with self.subTest(command=command):
                self.check_event(command, False)

    def test_git_reference_writes_differ_from_queries(self):
        for command in ['git tag v9.9.9', 'git tag -d old', 'git branch feature',
                        'git branch -D old', 'git -C "C:/project" tag v9.9.9',
                        'git merge feature', 'git rebase main', 'git cherry-pick abc123',
                        'git revert abc123', 'git rm old.txt']:
            with self.subTest(command=command):
                self.check_event(command, True)
        for command in ['git tag', 'git tag --list "v*"', 'git tag -l "v1*"',
                        'git branch', 'git branch -a', 'git branch --show-current',
                        'git branch --list "feature/*"', 'git -C "C:/project" branch -v']:
            with self.subTest(command=command):
                self.check_event(command, False)

    def test_possible_partial_runtime_failure_and_powershell_call_keep_obligation(self):
        self.check_event('node -e "process.exit(1)"', True, failed=True)
        self.check_event('& "C:/Program Files/nodejs/node.exe" -e "process.exit(0)"',
                         True, tool='PowerShell')

    def test_powershell_native_rejection_is_not_a_write_but_preserves_earlier_changes(self):
        for prior_write in (False, True):
            with self.subTest(prior_write=prior_write), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                begin_turn('powershell-denied', 'MEDIUM', False, (), root)
                if prior_write:
                    record_activity({'session_id': 'powershell-denied', 'hook_event_name': 'PostToolUse',
                                     'tool_name': 'Write', 'tool_input': {'file_path': 'earlier.md'}}, root)
                state = record_activity({
                    'session_id': 'powershell-denied', 'hook_event_name': 'PostToolUseFailure',
                    'tool_name': 'PowerShell', 'tool_input': {'command': 'Set-Content result.md changed'},
                    'error': 'Permission for this tool use was denied. The action was NOT performed.',
                }, root)
                self.assertEqual(int(prior_write), state['mutationCount'])
                self.assertTrue(state['approvalUnavailable'])
                self.assertFalse(state['recentTools'][-1]['mutation'])
                self.assertIsNone(state['verification'])
                stop = stop_decision({'session_id': 'powershell-denied'}, root)
                self.assertNotIn('decision', stop)
                self.assertIn('미검증', stop['systemMessage'])

    def test_generic_powershell_permission_error_may_follow_a_partial_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            begin_turn('powershell-partial', 'MEDIUM', False, (), root)
            state = record_activity({
                'session_id': 'powershell-partial', 'hook_event_name': 'PostToolUseFailure',
                'tool_name': 'PowerShell', 'tool_input': {'command': 'Set-Content result.md changed'},
                'error': 'PermissionError: access to another file was denied',
            }, root)
            self.assertEqual(1, state['mutationCount'])
            self.assertFalse(state['approvalUnavailable'])
            self.assertEqual('block', stop_decision({'session_id': 'powershell-partial'}, root)['decision'])


if __name__ == '__main__':
    unittest.main()
