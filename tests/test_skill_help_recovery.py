"""Trusted Skill help unblocks preparation without granting execution rights."""
from __future__ import annotations

import contextlib
import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'company-agent-plugin' / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from company_agent.cli import build_parser
from company_agent.execution_contract import (
    _powershell, classify_command, safe_permission, skill_help_command,
)
from company_agent.state import begin_turn, record_activity, stop_decision
from company_agent import skill_workflow


HELP_ARGS = ('skill --help',) + tuple(
    f'skill {operation} --help'
    for operation in ('choose', 'route', 'list', 'inventory', 'conflicts', 'search', 'resolve')
)


class SkillHelpRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cli = f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}"'

    def permission(self, command, event='PermissionRequest', tool='Bash'):
        return safe_permission({'hook_event_name': event, 'tool_name': tool,
                                'tool_input': {'command': command}}, self.root)

    def assert_rejected(self, command):
        self.assertFalse(skill_help_command(command), command)
        self.assertEqual('unknown', classify_command(command), command)
        self.assertIsNone(self.permission(command), command)

    def test_exact_help_matches_cli_and_remains_without_permission_allow(self):
        parser = build_parser()
        for arguments in HELP_ARGS:
            with self.subTest(arguments=arguments):
                command = f'{self.cli} {arguments}'
                self.assertTrue(skill_help_command(command))
                for tool in ('Bash', 'PowerShell'):
                    self.assertEqual('read_only', classify_command(command, tool=tool))
                    self.assertIsNone(self.permission(command, tool=tool))
                    self.assertIsNone(self.permission(command, event='PreToolUse', tool=tool))
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
                    parser.parse_args(arguments.split())
                self.assertEqual(0, result.exception.code)

    def test_installed_wrapper_and_system_powershell_keep_narrow_contract(self):
        prefixes = [f'"{SCRIPTS.parent / "bin/company-agent.cmd"}"']
        shell = _powershell()
        if shell is not None:
            prefixes.append(f'& "{shell}" -NoLogo -NoProfile -ExecutionPolicy Bypass '
                            f'-File "{SCRIPTS / "Invoke-CompanyAgent.ps1"}" -Mode Cli')
        for prefix in prefixes:
            for arguments in HELP_ARGS:
                with self.subTest(prefix=prefix, arguments=arguments):
                    command = f'{prefix} {arguments}'
                    self.assertTrue(skill_help_command(command))
                    self.assertEqual('read_only', classify_command(command))
                    self.assertIsNone(self.permission(command))
                    self.assert_rejected(command + ' > help.txt')

    def test_short_wrapper_must_resolve_to_this_installed_wrapper(self):
        command = 'company-agent skill choose --help'
        with patch('shutil.which', return_value=str(SCRIPTS.parent / 'bin/company-agent.cmd')):
            self.assertTrue(skill_help_command(command))
            self.assertEqual('read_only', classify_command(command))
            self.assertIsNone(self.permission(command))
        for resolved in (None, str(self.root / 'company-agent.cmd')):
            with self.subTest(resolved=resolved), patch('shutil.which', return_value=resolved):
                self.assert_rejected(command)

    def test_help_with_state_choice_or_output_arguments_is_not_exempt(self):
        for arguments in HELP_ARGS:
            for suffix in (' --help', f' --state-root "{self.root}"',
                           ' --session session-1 --turn turn-1 --candidate candidate-1',
                           ' --candidate candidate-1', ' --fallback no-relevant-skill',
                           ' --output result.json', ' --scope project', ' extra'):
                with self.subTest(arguments=arguments, suffix=suffix):
                    self.assert_rejected(f'{self.cli} {arguments}{suffix}')
        for arguments in ('skill choose --candidate candidate-1 --help',
                          'skill search query --help', 'skill resolve sample --help',
                          'skill unknown --help', 'skill prefer --help',
                          'skill reset --help', 'skill --help choose'):
            with self.subTest(arguments=arguments):
                self.assert_rejected(f'{self.cli} {arguments}')

    def test_shell_composition_and_other_executables_are_not_help(self):
        command = f'{self.cli} skill choose --help'
        for suffix in ('; echo changed', ' && echo changed', ' | more', ' > help.txt',
                       ' 2>/dev/null', '\nwhoami', ' $(whoami)', ' `whoami`'):
            with self.subTest(suffix=suffix):
                self.assert_rejected(command + suffix)
        for command in (
            f'python "{SCRIPTS / "harness_cli.py"}" skill choose --help',
            f'"{self.root / "python.exe"}" "{SCRIPTS / "harness_cli.py"}" skill choose --help',
            f'"{sys.executable}" "{self.root / "harness_cli.py"}" skill choose --help',
            f'"{sys.executable}" -c "print(1)" skill choose --help',
            f'"{self.root / "company-agent.cmd"}" skill choose --help',
        ):
            with self.subTest(command=command):
                self.assert_rejected(command)

    def test_help_creates_no_mutation_obligation_and_preserves_existing_work(self):
        session = 'skill-help-recovery'
        begin_turn(session, 'SMALL', False, [], self.root)
        payload = {'session_id': session, 'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                   'tool_input': {'command': f'{self.cli} skill choose --help'},
                   'tool_response': {'stdout': 'usage: skill choose'}}
        self.assertEqual(0, record_activity(payload, self.root)['mutationCount'])
        self.assertEqual({}, stop_decision({'session_id': session}, self.root))
        record_activity({'session_id': session, 'tool_name': 'Write',
                         'tool_input': {'file_path': str(self.root / 'synthetic-work.md')}}, self.root)
        self.assertEqual(1, record_activity(payload, self.root)['mutationCount'])

    def test_conflict_preflight_allows_help_without_selecting_or_loading_a_skill(self):
        state = {'turnId': 'turn-1', 'skillWorkflow': {
            'turn': 'turn-1', 'revision': 'revision-1', 'reviewProtocol': 1,
            'executionPlan': {'mode': 'choose', 'choiceIds': ['company-a', 'plugin-b']},
            'turnChoices': {}, 'selected': None,
        }}
        before = copy.deepcopy(state)
        with patch.object(skill_workflow, 'load_session', return_value=state), \
                patch.object(skill_workflow, '_snapshot', side_effect=AssertionError('Help needs no catalogue read')), \
                patch.object(skill_workflow, '_locked_session', side_effect=AssertionError('Help must not record a choice')):
            for tool in ('Bash', 'PowerShell'):
                for arguments in HELP_ARGS:
                    with self.subTest(tool=tool, arguments=arguments):
                        result = skill_workflow.preflight(self.root, self.root, {
                            'session_id': 'help-session', 'hook_event_name': 'PreToolUse',
                            'tool_name': tool, 'tool_input': {'command': f'{self.cli} {arguments}'},
                        })
                        self.assertEqual({}, result)  # No permission allow either.
        self.assertEqual(before, state)


if __name__ == '__main__':
    unittest.main()
