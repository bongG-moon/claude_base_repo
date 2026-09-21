"""Missing model-supplied identity must not require a second model tool round trip."""
import contextlib
import io
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent.execution_contract import bind_office_context, office_read_command, runtime_probe_context, classify_command, _trusted_arguments, _words, safe_permission
from company_agent import office_reader, office_consent
from company_agent.state import begin_turn, load_session, record_activity, stop_decision
from company_agent.cli import build_parser
from company_agent.business import run


class OfficeContextBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '개인 상태'
        self.project = Path(self.temp.name) / '업무'
        self.project.mkdir()
        self.source = self.project / '자료.xlsx'
        self.source.write_bytes(b'synthetic source; never opened by Office')
        self.command = (f'"{sys.executable}" -B "{ROOT / "company-agent-plugin/scripts/harness_cli.py"}" '
                        f'business office-read --file "{self.source}" --sheet 1 --range A1:F50')
        self.payload = {'hook_event_name': 'PreToolUse', 'session_id': 'current-session',
                        'cwd': str(self.project), 'tool_name': 'Bash',
                        'tool_input': {'command': self.command, 'timeout': 120000, 'description': '문서 읽기'}}

    def bound(self, payload=None):
        return bind_office_context(payload or self.payload, self.root)

    def test_fill_context_only_and_preserve_all_tool_fields(self):
        result = self.bound()['hookSpecificOutput']
        self.assertEqual({'hookEventName', 'updatedInput'}, set(result))
        expected = _trusted_arguments(self.command) + ['--session', 'current-session', '--state-root', self.root.as_posix()]
        updated = result['updatedInput']
        self.assertEqual(expected, _trusted_arguments(updated['command']))
        for key in ('timeout', 'description'):
            self.assertEqual(self.payload['tool_input'][key], updated[key])
        self.assertEqual({}, self.bound({**self.payload, 'tool_input': updated}))
        self.assertIsNone(safe_permission({**self.payload, 'hook_event_name': 'PermissionRequest', 'tool_input': updated}, self.root))

    def test_explicit_parent_scope_and_alternate_root_are_never_rewritten(self):
        for suffix in (' --session approved-parent', f' --state-root "{self.project}"',
                       ' --session unknown-session', ' --session bad/session'):
            with self.subTest(suffix=suffix):
                self.assertEqual({}, self.bound({**self.payload, 'tool_input': {'command': self.command + suffix}}))
        result = self.bound({**self.payload, 'tool_input': {'command': self.command + ' --session current-session'}})
        args = _trusted_arguments(result['hookSpecificOutput']['updatedInput']['command'])
        self.assertEqual(1, args.count('--session'))
        self.assertEqual(self.root.as_posix(), args[-1])

    def test_missing_invalid_identity_and_wrong_events_do_not_guess(self):
        for session in ('', ' ', 'unknown-session', 'company_agent_session_id', 'SESSION', None, 7):
            self.assertEqual({}, self.bound({**self.payload, 'session_id': session}))
        for change in ({'hook_event_name': 'PostToolUse'}, {'tool_name': 'Read'},
                       {'tool_input': None}, {'tool_input': {'command': self.command, 'run_in_background': True}}):
            self.assertEqual({}, self.bound({**self.payload, **change}))

    def test_untrusted_complex_or_different_commands_unchanged(self):
        commands = [self.command + suffix for suffix in ('; echo x', ' | head -40', ' 2>&1',
                    ' && echo x', ' --approved true', ' --session x --session y', ' --help')]
        commands += [self.command.replace('harness_cli.py', 'other_cli.py'),
                     self.command.replace('office-read', 'ppt'),
                     'python -c "import zipfile"',
                     self.command.replace('A1:F50', '$(echo x)')]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual({}, self.bound({**self.payload, 'tool_input': {'command': command}}))

    def test_ready_command_uses_native_context_not_environment_and_preserves_scope(self):
        cli = f'"{sys.executable}" -B "{ROOT / "company-agent-plugin/scripts/harness_cli.py"}"'
        with patch.dict(os.environ, {'company_agent_session_id': 'wrong-environment-session'}), \
             patch('company_agent.state.load_session', side_effect=AssertionError('no session discovery')):
            command = office_read_command(cli, self.root, 'current-session')
        self.assertEqual(['business', 'office-read', '--session', 'current-session', '--state-root', self.root.as_posix()],
                         _trusted_arguments(command))
        for value in ('', 'unknown-session', 'company_agent_session_id', 'SESSION', None):
            self.assertEqual('', office_read_command(cli, self.root, value))
        self.assertEqual('', office_read_command('other-cli', self.root, 'current-session'))

    def test_env_probe_gets_factual_current_context_without_replacing_output_or_permission(self):
        command = 'echo %company_agent_session_id% 2>nul & powershell -NoProfile -Command "Test-Path env:company_agent_session_id"'
        payload = {**self.payload, 'hook_event_name': 'PostToolUse', 'tool_input': {'command': command},
                   'tool_response': {'stdout': 'NOT SET'}}
        with patch.dict(os.environ, {'company_agent_session_id': 'wrong-env'}), \
             patch('company_agent.state.load_session', side_effect=AssertionError('no state search')):
            notice = runtime_probe_context(payload, self.root)
        self.assertIn('"company_agent_session_id":"current-session"', notice)
        self.assertNotIn('wrong-env', notice)
        self.assertEqual({'stdout': 'NOT SET'}, payload['tool_response'])
        self.assertFalse(self.root.exists())
        self.assertEqual('', runtime_probe_context({**payload, 'tool_name': 'Read'}, self.root))
        self.assertEqual('', runtime_probe_context({**payload, 'tool_input': {'command': 'echo %PATH%'}}, self.root))
        self.assertEqual('', runtime_probe_context({**payload, 'hook_event_name': 'PreToolUse'}, self.root))
        self.assertNotIn('e3b0c44298fc1c149afbf4c8996fb924', runtime_probe_context({**payload, 'session_id': ''}, self.root))

    def test_missing_context_or_placeholder_is_not_a_document_access_verdict(self):
        for value in ('', 'unknown-session', 'company_agent_session_id', 'SESSION', None):
            with self.subTest(value=value), patch.object(office_reader, '_invoke') as reader:
                result = office_reader.read_office({'file': str(self.source)}, state_root=self.root,
                                                  session_id=value, cwd=self.project)
            reader.assert_not_called()
            self.assertEqual('conversation_session_required', result['code'])
            self.assertEqual('conversation_context', result['failureKind'])
            self.assertEqual('not_checked', result['documentAccess'])
            self.assertFalse(result['sourceOpened'])
            self.assertNotIn('questions', result)
        self.assertFalse((self.root / 'sessions').exists())

    def test_native_identity_normalization_matches_real_answer_observation(self):
        native_id = 'route/session with spaces'
        canonical = office_consent.native_session_id(native_id)
        begin_turn(native_id, 'MEDIUM', False, [], self.root)
        bound = self.bound({**self.payload, 'session_id': native_id})['hookSpecificOutput']['updatedInput']['command']
        args = _trusted_arguments(bound)
        self.assertEqual(canonical, args[args.index('--session') + 1])
        request = office_reader.normalize({'file': str(self.source)})
        result = office_consent.authorize(request, root=self.root, session_id=canonical, cwd=self.project)
        event = {**self.payload, 'session_id': native_id, 'tool_name': 'AskUserQuestion',
                 'tool_use_id': 'canonical-question', 'tool_input': {'questions': result['questions']}}
        office_consent.observe(self.root, self.project, event)
        notice = office_consent.observe(self.root, self.project, {**event, 'hook_event_name': 'PostToolUse',
            'tool_response': {'answers': {result['questions'][0]['question']: office_consent.APPROVE}}})
        self.assertTrue(notice)
        self.assertIsNone(office_consent.authorize(request, root=self.root, session_id=canonical, cwd=self.project))

    def test_quoted_office_path_delimiters_do_not_break_binding_or_create_mutation(self):
        source = self.project / '자료 (최종) [1].xlsx'
        command = self.command.replace(str(self.source), str(source))
        updated = self.bound({**self.payload, 'tool_input': {'command': command}})['hookSpecificOutput']['updatedInput']
        args = _trusted_arguments(updated['command'], office_paths=True)
        self.assertEqual(str(source), args[args.index('--file') + 1])
        self.assertEqual('read_only', classify_command(updated['command']))
        begin_turn('current-session', 'MEDIUM', False, [], self.root)
        state = record_activity({**self.payload, 'hook_event_name': 'PostToolUse', 'tool_input': updated}, self.root)
        self.assertEqual(0, state['mutationCount'])
        self.assertIsNone(safe_permission({**self.payload, 'hook_event_name': 'PermissionRequest', 'tool_input': updated}, self.root))
        # This small parser exception must not enable shell syntax or other CLIs.
        for bad in (command.replace('"' + str(source) + '"', str(source)),
                    command + '; echo x', command.replace('(최종)', '$(echo x)'),
                    command.replace('office-read', 'ppt'), command.replace('harness_cli.py', 'foreign.py')):
            self.assertEqual({}, self.bound({**self.payload, 'tool_input': {'command': bad}}))
            self.assertEqual('unknown', classify_command(bad))

    def test_two_sessions_get_their_own_id_without_loading_any_other_state(self):
        with patch('company_agent.state.load_session', side_effect=AssertionError('no session search')):
            for session in ('one', 'two'):
                result = self.bound({**self.payload, 'session_id': session})
                args = _trusted_arguments(result['hookSpecificOutput']['updatedInput']['command'])
                self.assertEqual(session, args[args.index('--session') + 1])

    def test_powershell_cmd_field_preserved(self):
        payload = {**self.payload, 'tool_name': 'PowerShell', 'tool_input': {'cmd': self.command}}
        result = self.bound(payload)['hookSpecificOutput']['updatedInput']
        self.assertIn('cmd', result)
        self.assertNotIn('command', result)

    def test_native_pretool_binding_and_existing_deny_wins(self):
        import native_entry
        for preparation in ({}, {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                               'permissionDecision': 'deny', 'permissionDecisionReason': 'pending skill'}}):
            with patch.dict(os.environ, {'COMPANY_AGENT_USER_STATE': str(self.root)}), \
                 patch.object(native_entry, 'configure_runtime', return_value=True), \
                 patch('company_agent.skill_workflow.preflight', return_value=preparation), \
                 patch.object(sys, 'argv', ['native_entry.py', '--event', 'PreToolUse']), \
                 patch.object(sys, 'stdin', io.StringIO(json.dumps(self.payload))):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(0, native_entry.main())
                result = json.loads(out.getvalue())['hookSpecificOutput']
            if preparation:
                self.assertEqual('deny', result['permissionDecision'])
                self.assertNotIn('updatedInput', result)
            else:
                self.assertIn('--session "current-session"', result['updatedInput']['command'])
                self.assertNotIn('permissionDecision', result)

    def test_native_post_probe_adds_context_without_a_new_gate(self):
        import native_entry
        begin_turn('current-session', 'MEDIUM', False, [], self.root)
        payload = {**self.payload, 'hook_event_name': 'PostToolUse',
                   'tool_input': {'command': 'echo %company_agent_session_id%'},
                   'tool_response': {'stdout': 'NOT SET'}}
        with patch.dict(os.environ, {'COMPANY_AGENT_USER_STATE': str(self.root)}), \
             patch.object(native_entry, 'configure_runtime', return_value=True), \
             patch.object(sys, 'argv', ['native_entry.py', '--event', 'PostToolUse']), \
             patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(0, native_entry.main())
        result = json.loads(out.getvalue())['hookSpecificOutput']
        self.assertIn('"company_agent_session_id":"current-session"', result['additionalContext'])
        self.assertNotIn('permissionDecision', result)
        self.assertNotIn('updatedInput', result)
        self.assertEqual(0, load_session('current-session', self.root)['mutationCount'])

    @unittest.skipUnless(os.name == 'nt', 'Windows installed wrapper')
    def test_real_wrapper_missing_session_is_bound_before_first_invocation(self):
        from company_agent.native_runtime import cli_command
        command = cli_command(ROOT / 'company-agent-plugin') + f' business office-read --file "{self.source}"'
        payload = {**self.payload, 'tool_input': {'command': command}}
        result = self.bound(payload)['hookSpecificOutput']
        env = {**os.environ, 'COMPANY_AGENT_USER_STATE': str(self.root)}
        completed = subprocess.run(_words(result['updatedInput']['command']), cwd=self.project, env=env,
                                   capture_output=True, timeout=30, encoding='utf-8')
        self.assertEqual(0, completed.returncode, completed.stderr)
        data = json.loads(completed.stdout)
        self.assertEqual('input_required', data['status'])
        self.assertNotEqual('conversation_session_required', data.get('code'))
        self.assertFalse(data['sourceOpened'])
        self.assertIn('questions', data)
        self.assertNotIn('application', data['diagnostics']['progress']['stageMs'])

    def test_missing_session_reaches_question_in_first_call_and_read_only_after_answer(self):
        session = self.payload['session_id']
        begin_turn(session, 'MEDIUM', False, [], self.root)
        updated = self.bound()['hookSpecificOutput']['updatedInput']
        args = build_parser().parse_args(_trusted_arguments(updated['command']))
        old_cwd = Path.cwd()
        self.addCleanup(os.chdir, old_cwd)
        os.chdir(self.project)
        with patch.object(office_reader, '_invoke') as helper:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(0, run(args))
            helper.assert_not_called()
        result = json.loads(out.getvalue())
        self.assertEqual('input_required', result['status'])
        self.assertNotEqual('conversation_session_required', result.get('code'))
        self.assertFalse(result['sourceOpened'])
        self.assertIn('A1:F50', result['questions'][0]['question'])
        question = {**self.payload, 'tool_name': 'AskUserQuestion', 'tool_use_id': 'question-one',
                    'tool_input': {'questions': result['questions']}}
        office_consent.observe(self.root, self.project, question)
        office_consent.observe(self.root, self.project, {**question, 'hook_event_name': 'PostToolUse',
            'tool_response': {'answers': {result['questions'][0]['question']: office_consent.APPROVE}}})
        with patch.object(office_reader, '_invoke', return_value={'ok': True, 'items': [], 'coverage': {'total': 1}}) as helper:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(0, run(args))
            helper.assert_called_once()
        record_activity({**self.payload, 'hook_event_name': 'PostToolUse', 'tool_input': updated,
                         'tool_response': {'stdout': out.getvalue()}}, self.root)
        self.assertEqual(0, load_session(session, self.root)['mutationCount'])
        self.assertNotEqual('block', stop_decision({'session_id': session}, self.root).get('decision'))


if __name__ == '__main__':
    unittest.main()
