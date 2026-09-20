"""Only parse command strings; never execute any destructive command."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent.dangerous_commands import MAX_COMMAND_CHARS, MAX_TOKENS, _dangerous, preflight
import native_entry


class DangerousCommandTests(unittest.TestCase):
    def event(self, command, tool='Bash'):
        return {'tool_name': tool, 'tool_input': {'command': command}, 'session_id': 'audit-string-only'}

    def test_literal_destructive_git_commands_are_denied(self):
        commands = [
            'git reset --hard', 'git -C "C:/한글 폴더" reset --hard HEAD',
            'git -c core.autocrlf=false --no-pager reset --hard',
            'git --git-dir=C:/repo/.git reset --hard', 'git -CC:/repo reset --hard',
            'git clean -fdx', 'git clean -f', 'git clean --force -d',
            'git clean -e --dry-run -f',
            'git push --force origin main', 'git push -f origin main',
            'git push --force-with-lease', 'git push --force-with-lease=main:old origin main',
            'git push origin +HEAD:main', 'git push --mirror origin',
            'git push -o --dry-run --force origin main',
            'git status && git reset --hard', 'git status; git clean -ffdx',
            'printf "hello" | git reset --hard', 'git status\ngit reset --hard',
            'command git reset --hard', 'MODE=test git reset --hard',
            '"C:/Program Files/Git/bin/git.exe" reset --hard',
            'powershell.exe -NoProfile -Command "git reset --hard"',
            'bash -lc \'git -C "/tmp/repo" clean -fdx\'',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual('deny', preflight(self.event(command))['hookSpecificOutput']['permissionDecision'])

    def test_recursive_forced_deletion_and_powershell_invocation(self):
        for tool, command in [
            ('Bash', 'rm -rf /tmp/example'), ('Bash', 'rm --recursive --force "/tmp/example dir"'),
            ('PowerShell', 'Remove-Item -LiteralPath C:/example -Recurse -Force'),
            ('PowerShell', 'rm -r -fo C:/example'),
            ('PowerShell', 'Remove-Item -Recurse:$true -Force:$true C:/example'),
            ('PowerShell', 'Remove-Item C:/example -Recurse -Force -WhatIf:$false'),
            ('PowerShell', 'Remove-Item -LiteralPath "-WhatIf" -Recurse -Force'),
            ('PowerShell', '& "C:/Program Files/Git/bin/git.exe" reset --hard'),
            ('Bash', 'powershell -NoProfile -Command "Remove-Item C:/example -Recurse -Force"'),
            ('Bash', 'cmd.exe /c "rmdir /s /q C:/example"'),
        ]:
            with self.subTest(command=command):
                self.assertEqual('deny', preflight(self.event(command, tool))['hookSpecificOutput']['permissionDecision'])

    def test_repo_option_keeps_force_refspec_in_scope_without_blocking_safe_values(self):
        for command in ('git push --repo origin +HEAD:main', 'git push --repo=origin +HEAD:main'):
            with self.subTest(command=command):
                self.assertEqual('deny', preflight(self.event(command))['hookSpecificOutput']['permissionDecision'])
        for command in ('git push --repo origin --dry-run +HEAD:main',
                        'git push --repo=origin -n +HEAD:main',
                        'git push --repo +example main', 'git push --repo=+example main',
                        'git push --push-option --repo origin main'):
            with self.subTest(command=command):
                self.assertEqual({}, preflight(self.event(command)))

    def test_readonly_examples_search_and_dry_runs_are_not_blocked(self):
        commands = [
            'git status', 'git diff', 'git reset --soft HEAD~1', 'git reset file.txt',
            'git clean -ndx', 'git clean --dry-run --force -d', 'git push origin main',
            'git push --dry-run --force origin main', 'git push -nf origin main',
            'git push --force-if-includes origin main', 'git push --push-option force origin main',
            'git -c alias.note="reset --hard" status',
            'echo "git reset --hard"', "printf '%s' 'rm -rf /tmp/example'",
            'rg -n "git reset --hard|Remove-Item -Recurse -Force" docs',
            'grep "git clean -fdx" README.md', 'Write-Output "git reset --hard"',
            'echo "example; git reset --hard"', '# git reset --hard\ngit status',
            'rm -- -rf', 'rm -f example.txt', 'rmdir empty-directory',
            'powershell -Command \'Write-Output "git reset --hard"\'',
            'bash -c \'echo "git reset --hard"\'',
            'git push --repo +example main',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual({}, preflight(self.event(command)))
        self.assertEqual({}, preflight(self.event('Remove-Item C:/example -Recurse -Force -WhatIf', 'PowerShell')))
        self.assertEqual({}, preflight(self.event('Remove-Item C:/example -Recurse -Force -WhatIf:$true', 'PowerShell')))

    def test_unknown_inputs_have_no_allow_and_do_not_claim_safety(self):
        for payload in ({}, {'tool_name':'Read','tool_input':{'command':'git reset --hard'}},
                        {'tool_name':'Bash','tool_input':None}, self.event('x' * (MAX_COMMAND_CHARS + 1)),
                        self.event('echo "unclosed'), self.event('git reset --hard\0')):
            self.assertEqual({}, preflight(payload))
        self.assertEqual({}, preflight(self.event(('x ' * (MAX_TOKENS + 1)) + '; git reset --hard')))
        # Beyond the documented wrapper limit, a command is unknown: no allow
        # is emitted and normal permissions remain in charge.
        self.assertFalse(_dangerous('bash -c "git reset --hard"', 'bash', depth=2))

    def test_deny_reason_does_not_echo_command_path_or_private_values(self):
        result = preflight(self.event('git -C C:/PRIVATE-PROJECT reset --hard SECRET-BRANCH'))
        encoded = json.dumps(result)
        self.assertNotIn('PRIVATE-PROJECT', encoded)
        self.assertNotIn('SECRET-BRANCH', encoded)
        self.assertNotIn('allow', encoded)

    def test_native_guard_precedes_runtime_and_skill_gate_without_io(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['native_entry.py','--event','PreToolUse']), \
                patch.object(sys, 'stdin', io.StringIO(json.dumps(self.event('git reset --hard')))), \
                patch.object(native_entry, 'configure_runtime', side_effect=AssertionError('runtime must not run')), \
                patch('company_agent.skill_workflow.preflight', side_effect=AssertionError('skill scan must not run')), \
                patch('company_agent.hook_diagnostics.record_hook', side_effect=AssertionError('no record write')), \
                contextlib.redirect_stdout(output):
            self.assertEqual(0, native_entry.main())
        self.assertEqual('deny', json.loads(output.getvalue())['hookSpecificOutput']['permissionDecision'])


if __name__ == '__main__':
    unittest.main()
