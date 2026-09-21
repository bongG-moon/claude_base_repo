"""Exact skill-local launch and cwd filenames; no path search or consent bypass."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'company-agent-plugin'
sys.path.insert(0, str(PLUGIN / 'scripts'))
from company_agent import office_reader
from company_agent.business import dispatch
from company_agent.cli import build_parser
from company_agent.execution_contract import bind_office_context, classify_command, _trusted_arguments, safe_permission
from company_agent.native_runtime import cli_command
from company_agent.state import _own_cli_arguments


class OfficeEntryPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.project = self.base / '과정 LIST 정리'
        self.project.mkdir()
        self.source = self.project / 'AI_과정구분.xlsx'
        self.source.write_bytes(b'synthetic; must not open before consent')
        self.state = self.base / 'state'
        self.saved_cwd = Path.cwd()
        os.chdir(self.project)
        self.addCleanup(os.chdir, self.saved_cwd)

    def prefix(self, local=False):
        command = cli_command(PLUGIN)
        return command.replace('/scripts/Invoke-CompanyAgent.ps1', '/skills/office-reader/scripts/Invoke-CompanyAgent.ps1') if local else command

    def payload(self, command):
        return {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'session_id': 'entry-session',
                'cwd': str(self.project), 'tool_input': {'command': command, 'timeout': 120000}}

    def test_filename_stays_in_current_folder_and_absolute_wrong_path_is_not_repaired(self):
        for source, expected in ((self.source.name, 'office_read_consent'),
                                 (str(self.base / self.source.name), 'source_not_found'),
                                 ('../' + self.source.name, 'invalid_office_path'),
                                 ('subdir/' + self.source.name, 'invalid_office_path')):
            args = build_parser().parse_args(['business', 'office-read', '--file', source,
                                             '--session', 'entry-session', '--state-root', str(self.state)])
            with patch.object(office_reader, '_invoke') as helper:
                result = dispatch(args)
            helper.assert_not_called()
            self.assertEqual(expected, result['code'])
            self.assertFalse(result['sourceOpened'])
            if expected == 'office_read_consent':
                self.assertIn(str(self.source), result['questions'][0]['question'])
            elif expected == 'source_not_found':
                self.assertEqual(source, result['diagnostics']['requestedFile'])

    def test_filename_not_present_is_not_searched_in_other_folders(self):
        other = self.base / 'empty'
        other.mkdir()
        os.chdir(other)
        args = build_parser().parse_args(['business', 'office-read', '--file', self.source.name])
        result = dispatch(args)
        self.assertEqual('source_not_found', result['code'])
        self.assertEqual(str(other / self.source.name), result['diagnostics']['requestedFile'])

    def test_spec_keeps_absolute_source_contract(self):
        spec = self.project / 'spec.json'
        spec.write_text(json.dumps({'file': self.source.name}), encoding='utf-8')
        result = dispatch(build_parser().parse_args(['business', 'office-read', '--spec', str(spec)]))
        self.assertEqual('invalid_office_path', result['code'])

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell contracts')
    def test_only_own_office_entry_gets_context_and_no_permission_grant(self):
        for local in (False, True):
            command = self.prefix(local) + f' business office-read --file "{self.source.name}" 2>&1'
            payload = self.payload(command)
            output = bind_office_context(payload, self.state)['hookSpecificOutput']
            self.assertEqual({'hookEventName', 'updatedInput'}, set(output))
            args = _trusted_arguments(output['updatedInput']['command'], office_paths=True)
            self.assertEqual(self.source.name, args[args.index('--file') + 1])
            self.assertEqual('entry-session', args[args.index('--session') + 1])
            self.assertEqual('read_only', classify_command(command))
            self.assertIsNone(safe_permission({**payload, 'hook_event_name': 'PermissionRequest'}, self.state))
        for suffix in ('business doctor', 'business ppt --spec "C:/fixture/spec.json"', 'session verify --session entry-session'):
            command = self.prefix(True) + ' ' + suffix
            self.assertIsNone(_own_cli_arguments(command))
            self.assertEqual({}, bind_office_context(self.payload(command), self.state))
        for filename in ('../source.xlsx', 'subdir/source.xlsx', r'subdir\source.xlsx', 'C:source.xlsx'):
            command = self.prefix(True) + f' business office-read --file "{filename}"'
            self.assertEqual('unknown', classify_command(command))
            self.assertEqual({}, bind_office_context(self.payload(command), self.state))
        foreign = self.prefix(True).replace('office-reader/scripts', 'other-reader/scripts') + f' business office-read --file "{self.source}"'
        self.assertIsNone(_own_cli_arguments(foreign))
        self.assertEqual({}, bind_office_context(self.payload(foreign), self.state))
        self.assertEqual('unknown', classify_command(self.prefix() + f' business eml-read --file "mail.eml"'))

    @unittest.skipUnless(os.name == 'nt' and Path('C:/Program Files/Git/bin/bash.exe').is_file(), 'Windows Git Bash required')
    def test_real_skill_local_path_and_filename_reach_consent_on_first_call(self):
        command = self.prefix(True) + f' business office-read --file "{self.source.name}" 2>&1'
        updated = bind_office_context(self.payload(command), self.state)['hookSpecificOutput']['updatedInput']['command']
        env = {**os.environ, 'COMPANY_AGENT_USER_STATE': str(self.state), 'PYTHONUTF8': '1'}
        completed = subprocess.run(['C:/Program Files/Git/bin/bash.exe', '--noprofile', '--norc', '-c', updated],
                                   cwd=self.project, env=env, capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        result = json.loads(completed.stdout[completed.stdout.index('{'):])
        self.assertEqual('office_read_consent', result['code'])
        self.assertFalse(result['sourceOpened'])
        self.assertIn(str(self.source), result['questions'][0]['question'])
        self.assertNotIn('application', result['diagnostics']['progress']['stageMs'])
        # One central launch/probe, not a second runtime discovered by the shim.
        self.assertEqual(1, completed.stdout.count('Python 준비 완료'))

    @unittest.skipUnless(os.name == 'nt', 'Windows skill-local launcher')
    def test_local_launcher_rejects_non_office_command_without_running_cli(self):
        script = PLUGIN / 'skills/office-reader/scripts/Invoke-CompanyAgent.ps1'
        result = subprocess.run(['powershell.exe', '-NoProfile', '-File', str(script), '-Mode', 'Cli', 'business', 'doctor'],
                                capture_output=True, encoding='utf-8', timeout=15)
        self.assertEqual(2, result.returncode)
        self.assertNotIn('environment', result.stdout)


if __name__ == '__main__':
    unittest.main()
