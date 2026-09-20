from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from company_agent.execution_contract import classify_command, safe_permission, _powershell
from company_agent.state import begin_turn, record_activity, stop_decision


class ExecutionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cli = f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}"'

    def tearDown(self) -> None:
        self.temp.cleanup()

    def permission(self, command: str, **extra: object) -> dict | None:
        payload = {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "tool_input": {"command": command}}
        payload.update(extra)
        return safe_permission(payload, self.root)

    def test_known_read_only_cli_contracts(self) -> None:
        for arguments in (
            "business doctor", "business mail-capabilities", "business html-designs", "learning status",
            "session status --session abc-123", "skill inventory", "skill list",
            "skill conflicts", "context audit",
            f'business mail-search --spec "{self.root / "request.json"}"',
            f'business html-choices --spec "{self.root / "request.json"}"',
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual("read_only", classify_command(f"{self.cli} {arguments}"))

    def test_scope_question_is_not_mutation_or_permission_grant(self):
        for head in ('memory upsert','knowledge upsert','asset create'):
            cmd=f'{self.cli} {head} --spec "{self.root / "not-written.json"}" --state-root "{self.root}"'
            self.assertEqual('read_only',classify_command(cmd))
            self.assertIsNone(self.permission(cmd))
            self.assertEqual('unknown',classify_command(cmd+' --storage-scope personal'))
            self.assertEqual('unknown',classify_command(cmd+' --storage-scope=project'))
            self.assertEqual('unknown',classify_command(cmd+'; echo changed'))
            begin_turn('scope-choice','SMALL',False,[],self.root)
            state=record_activity({'session_id':'scope-choice','hook_event_name':'PostToolUse',
                'tool_name':'Bash','tool_input':{'command':cmd},
                'tool_response':{'stdout':'{"status":"needs_scope_choice","written":false}'}},self.root)
            self.assertEqual(0,state['mutationCount'])
            self.assertEqual({},stop_decision({'session_id':'scope-choice'},self.root))

    def test_bound_skill_check_is_read_only_without_auto_permission_or_clearing_old_work(self):
        cmd = f'{self.cli} asset check-skill --name sample-report --state-root "{self.root}" --project-root "{self.root}"'
        self.assertEqual('read_only', classify_command(cmd))
        self.assertIsNone(self.permission(cmd))
        for extra in (' --output out.json', '; echo changed', ' --name other', ' --storage-scope personal'):
            self.assertEqual('unknown', classify_command(cmd + extra))
        begin_turn('dependency-check', 'SMALL', False, [], self.root)
        event = {'session_id': 'dependency-check', 'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                 'tool_input': {'command': cmd}, 'tool_response': {'stdout': '{"ok":true}'}}
        self.assertEqual(0, record_activity(event, self.root)['mutationCount'])
        self.assertEqual({}, stop_decision({'session_id': 'dependency-check'}, self.root))
        record_activity({'session_id': 'dependency-check', 'tool_name': 'Write',
                         'tool_input': {'file_path': str(self.root / 'existing-work.md')}}, self.root)
        self.assertEqual(1, record_activity(event, self.root)['mutationCount'])
        self.assertEqual('block', stop_decision({'session_id': 'dependency-check'}, self.root)['decision'])

    def test_exact_help_precedes_scope_question_without_granting_permission(self):
        cmd = f'{self.cli} memory upsert --help'
        self.assertEqual('read_only', classify_command(cmd))
        self.assertIsNone(self.permission(cmd))
        for suffix in (' > help.txt', '; echo changed', ' --unexpected value'):
            self.assertEqual('unknown', classify_command(cmd + suffix))
            self.assertIsNone(self.permission(cmd + suffix))

    def test_harness_map_query_is_readonly_but_html_export_is_not(self):
        cmd = f'{self.cli} context map --project "{self.root}" --session current-123'
        self.assertEqual('read_only', classify_command(cmd))
        self.assertIsNone(self.permission(cmd))
        for suffix in (' --output map.html', ' > map.json', '; echo changed', ' --other x'):
            self.assertEqual('unknown', classify_command(cmd + suffix))
            self.assertIsNone(self.permission(cmd + suffix))
        begin_turn('map-read', 'SMALL', False, [], self.root)
        state = record_activity({'session_id':'map-read','hook_event_name':'PostToolUse',
            'tool_name':'Bash','tool_input':{'command':cmd},'tool_response':{'stdout':'{}'}}, self.root)
        self.assertEqual(0, state['mutationCount'])
        self.assertEqual({}, stop_decision({'session_id':'map-read'}, self.root))

    def test_scoped_search_does_not_create_verification_or_permission(self):
        for kind in ('memory','knowledge'):
            cmd=f'{self.cli} {kind} search "가상" --storage-scope project --project-root "{self.root}"'
            self.assertEqual('read_only',classify_command(cmd))
            self.assertIsNone(self.permission(cmd))
            self.assertEqual('unknown',classify_command(cmd+' --output result.json'))

    def test_listing_stderr_to_null_does_not_create_mutation_or_auto_permission(self):
        command = 'ls -la "claude-code-starter-main/" 2>/dev/null || ls -la claude-code-starter-main/ 2>/dev/null; pwd'
        self.assertEqual('read_only', classify_command(command))
        self.assertEqual('unknown', classify_command(command, tool='PowerShell'))
        self.assertIsNone(self.permission(command))
        begin_turn('listing', 'SMALL', False, [], self.root)
        state = record_activity({'session_id': 'listing', 'hook_event_name': 'PostToolUse',
                                'tool_name': 'Bash', 'tool_input': {'command': command},
                                'tool_response': {'stdout': 'folder'}}, self.root)
        self.assertEqual(0, state['mutationCount'])
        self.assertEqual({}, stop_decision({'session_id': 'listing'}, self.root))
        for cmd in ('ls > report.txt', 'ls; python reader.py', 'ls 2> error.txt',
                    'ls | python read.py', 'ls &> report.txt', 'ls; rm file'):
            self.assertEqual('unknown', classify_command(cmd), cmd)

    def test_handoff_read_is_not_mutation_or_permission_grant(self):
        args = f'handoff read --id {"a" * 32} --project "{self.root}" --state-root "{self.root}"'
        self.assertEqual("read_only", classify_command(f"{self.cli} {args}"))
        self.assertIsNone(self.permission(f"{self.cli} {args}"))
        for extra in (' --id bad', ' && echo unsafe'):
            self.assertEqual("unknown", classify_command(f"{self.cli} {args}{extra}"))

    def test_short_powershell_resolves_to_system_runtime_without_permission_grant(self):
        shell = self.root / "WindowsPowerShell" / "powershell.exe"
        command = (f'powershell.exe -NoLogo -NoProfile -File "{SCRIPTS / "Invoke-CompanyAgent.ps1"}"'
                   f' -Mode Cli business html-choices --spec "{self.root / "choices.json"}"')
        with patch("company_agent.execution_contract._powershell", return_value=shell):
            with patch("shutil.which", return_value=str(shell)):
                self.assertEqual("read_only", classify_command(command))
                self.assertIsNone(self.permission(command))
                for suffix in (' > result.json', ' && echo changed', '; echo changed'):
                    self.assertEqual("unknown", classify_command(command + suffix))
            for resolved in (None, str(self.root / "fake" / "powershell.exe")):
                with patch("shutil.which", return_value=resolved):
                    self.assertEqual("unknown", classify_command(command))

    def test_design_picker_copy_is_not_classified_as_read_only_or_auto_approved(self):
        command = f'{self.cli} business html-designs --output "{self.root / "picker.html"}"'
        self.assertEqual('unknown', classify_command(command))
        self.assertIsNone(self.permission(command))
        self.assertIsNone(self.permission(f'{self.cli} business html-designs'))

    def test_design_preview_does_not_create_work_verification_or_auto_permission(self):
        command = f'{self.cli} business html-designs --open'
        self.assertEqual('read_only', classify_command(command))
        self.assertIsNone(self.permission(command))
        for extra in (' --open', ' --output out.html', '; python unexpected.py'):
            self.assertEqual('unknown', classify_command(command+extra))
        reference = f'{self.cli} business html-template --template "{self.root / "form.html"}"'
        self.assertEqual('read_only', classify_command(reference))
        self.assertIsNone(self.permission(reference))
        self.assertEqual('unknown', classify_command(reference+' --output preview.html'))

    def test_html_choice_helper_never_widens_permissions(self):
        command=f'{self.cli} business html-choices --spec "{self.root / "choices.json"}"'
        self.assertEqual('read_only',classify_command(command))
        self.assertIsNone(self.permission(command))
        for suffix in (' --output result.html',' > result.json',' && echo changed',' --spec other.json'):
            self.assertEqual('unknown',classify_command(command+suffix))
            self.assertIsNone(self.permission(command+suffix))

    def test_ppt_helpers_and_diagnostic_do_not_widen_permissions(self):
        for args in ('business runtime-check',
                     f'business ppt-choices --spec "{self.root / "s.json"}"',
                     f'business ppt-choices --spec "{self.root / "s.json"}" --template "{self.root / "saved.html"}"',
                     f'business ppt-analyze --template "{self.root / "ref.pptx"}"'):
            command=f'{self.cli} {args}'
            self.assertEqual('read_only',classify_command(command))
            self.assertIsNone(self.permission(command))
        command=f'{self.cli} business ppt-preview --template "{self.root / "ref.pptx"}" --output "{self.root / "preview"}"'
        self.assertEqual('unknown',classify_command(command))
        self.assertIsNone(self.permission(command))

    def test_ppt_html_draft_and_template_exports_are_not_permission_exempt(self):
        for action in ('ppt-design-preview','ppt-template'):
            command=f'{self.cli} business {action} --spec "{self.root / "job.json"}" --output "{self.root / "out.html"}"'
            self.assertEqual('unknown',classify_command(command))
            self.assertIsNone(self.permission(command))

    def test_artifact_workspace_is_bookkeeping_not_permission_and_preserves_older_debt(self):
        from company_agent.execution_contract import internal_plan_command
        from company_agent.state import load_session
        command = f'{self.cli} business artifact-start --output "{self.root / "final.pptx"}" --state-root "{self.root}"'
        self.assertTrue(internal_plan_command(command,self.root))
        self.assertIsNone(self.permission(command))
        for extra in (' --output other.html', '; echo changed', f' --state-root "{self.root / "other"}"'):
            self.assertFalse(internal_plan_command(command+extra,self.root))
        begin_turn('artifact-start','MEDIUM',False,[],self.root)
        event = {'session_id':'artifact-start','hook_event_name':'PostToolUse',
                 'tool_name':'Bash','tool_input':{'command':command}}
        record_activity(event,self.root)
        self.assertEqual(0,load_session('artifact-start',self.root)['mutationCount'])
        self.assertEqual({},stop_decision({'session_id':'artifact-start'},self.root))
        record_activity({'session_id':'artifact-start','tool_name':'Write',
                         'tool_input':{'file_path':str(self.root/'existing-work.md')}},self.root)
        record_activity(event,self.root)
        self.assertEqual(1,load_session('artifact-start',self.root)['mutationCount'])
        self.assertEqual('block',stop_decision({'session_id':'artifact-start'},self.root)['decision'])
        for action in ('html','ppt','ppt-design-preview','ppt-template','artifact-publish'):
            cmd = f'{self.cli} business {action} --work "{self.root / "work.json"}"'
            self.assertFalse(internal_plan_command(cmd,self.root))
            self.assertEqual('unknown',classify_command(cmd))
            self.assertIsNone(self.permission(cmd))

    def test_permission_only_exact_metadata_and_current_root(self) -> None:
        for operation in ("doctor", "mail-capabilities"):
            command = f"{self.cli} business {operation}"
            self.assertEqual({"behavior": "allow"}, self.permission(command))
            self.assertEqual({"behavior": "allow"}, self.permission(f'{command} --state-root "{self.root}"'))
            self.assertIsNone(self.permission(f'{command} --state-root "{self.root / "other"}"'))
            self.assertIsNone(self.permission(command, hook_event_name="PreToolUse"))
            self.assertIsNone(self.permission(command, tool_name="PowerShell"))

    def test_scoped_skill_discovery_preview_search_and_resolution_are_read_only(self):
        common = (f'--state-root "{self.root / "state"}" --base "{self.root / "base"}" '
                  f'--claude-root "{self.root / "claude"}" --plugin-root "{self.root / "plugin"}" '
                  f'--incoming-skill "{self.root / "incoming"}" --incoming-plugin "{self.root / "preview"}"')
        for operation in ("inventory", "list", "conflicts", 'search "보고서" --limit 50', 'resolve "html-report"'):
            for scope in (f'--project-root "{self.root}"', "--no-project"):
                command = f"{self.cli} skill {operation} {scope} {common}"
                self.assertEqual("read_only", classify_command(command), command)
                self.assertIsNone(self.permission(command))

    def test_skill_mutations_and_malformed_scope_keep_conservative_checks(self):
        for arguments in (
            'prefer --name x --candidate y --scope default', 'prefer-incoming --scope default',
            'order --sources company user', 'reset --name x',
            f'inventory --project-root "{self.root}" --no-project',
            'inventory --project-root relative', 'inventory --project-root',
            'inventory --no-project --no-project', 'inventory --no-project extra',
            'inventory --limit 5', 'search x --limit 51', 'search x --limit 0',
            'search x y', 'resolve', 'inventory --scope default', 'inventory --project-ro x',
            f'inventory --project-root "{self.root}" ; echo changed',
            f'inventory --project-root "{self.root}" > output.json',
        ):
            self.assertEqual("unknown", classify_command(f"{self.cli} skill {arguments}"), arguments)

    def test_real_incident_two_scoped_queries_do_not_trigger_stop_or_learning(self):
        from company_agent.state import begin_turn, record_activity, load_session, stop_decision
        begin_turn("lookup", "MEDIUM", False, [], self.root)
        prefixes = [self.cli]
        shell = _powershell()
        if shell:
            prefixes.append(f'"{shell}" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "{SCRIPTS / "Invoke-CompanyAgent.ps1"}" -Mode Cli')
        for prefix in prefixes:
            for operation in ("inventory", "conflicts"):
                record_activity({"session_id": "lookup", "hook_event_name": "PostToolUse",
                                 "tool_name": "Bash", "tool_input": {"command":
                                     f'{prefix} skill {operation} --project-root "{self.root}"'}}, self.root)
        state = load_session("lookup", self.root)
        self.assertEqual(0, state["mutationCount"])
        self.assertIsNone(state["verification"])
        self.assertEqual([], state["work"]["pending"])
        self.assertEqual({}, stop_decision({"session_id": "lookup"}, self.root))
        # A later lookup does not erase a real, unresolved file change.
        record_activity({"session_id": "lookup", "tool_name": "Write",
                         "tool_input": {"file_path": str(self.root / "report.md")}}, self.root)
        record_activity({"session_id": "lookup", "tool_name": "Bash", "tool_input": {
            "command": f'{self.cli} skill inventory --no-project'}}, self.root)
        self.assertEqual(1, load_session("lookup", self.root)["mutationCount"])
        self.assertEqual("block", stop_decision({"session_id": "lookup"}, self.root)["decision"])

    def test_model_generated_specs_and_sensitive_operations_never_auto_allowed(self) -> None:
        for command in (
            f'business mail-search --spec "{self.root / "request.json"}"',
            f'business mail-read --spec "{self.root / "request.json"}"',
            "learning status", "session status --session abc", "context audit",
            "skill inventory", "memory compact", "learning pause", "learning resume",
            "business files-execute --plan anything", "business mail-send", "policy-check --payload anything",
        ):
            with self.subTest(command=command):
                self.assertIsNone(self.permission(f"{self.cli} {command}"))

    def test_review_verification_and_mutation_need_existing_state_guards(self) -> None:
        for command in (
            'session verify --session abc --status pass --summary "checks passed"',
            f'learning review --session abc --turn {"a" * 32} --spec "{self.root / "review.json"}"',
            "memory compact", "asset run-tool --name malicious", "business files-execute --plan plan",
            "learning rollback --change whatever",
        ):
            self.assertEqual("unknown", classify_command(f"{self.cli} {command}"))

    def test_shell_chains_expansions_and_quotes_fail_closed(self) -> None:
        for suffix in (
            " ; Remove-Item file", " && echo yes", " | python x.py", " > output",
            '\npython x.py', ' --state-root "$HOME"', ' --state-root "%USERPROFILE%"',
            ' --state-root "!root!"', ' --state-root "a^&evil"', ' --state-root "a;evil"',
            ' --state-root "unterminated', " --state-root $(whoami)", " --state-root `whoami`",
        ):
            command = f"{self.cli} business doctor{suffix}"
            with self.subTest(suffix=suffix):
                self.assertEqual("unknown", classify_command(command))
                self.assertIsNone(self.permission(command))

    def test_exact_option_grammar_no_duplicates_abbreviations_or_extra_args(self) -> None:
        for args in (
            "business doctor --state-root relative", "business doctor --state-ro x",
            f'business doctor --state-root "{self.root}" --state-root "{self.root}"',
            "business doctor extra", "business doctor --output file", "business doctor --state-root",
            "business mail-search", "business mail-search --spec relative.json",
            f'business mail-search --spec "{self.root / "secrets.env"}"',
            "session status --session ../other", "learning list", "session show --session abc",
        ):
            with self.subTest(args=args):
                self.assertEqual("unknown", classify_command(f"{self.cli} {args}"))

    def test_program_aliases_and_path_hijacks_are_not_trusted(self) -> None:
        for program in ("python", "python3", "py", "powershell", "pwsh", f'"{self.root / "python.exe"}"'):
            command = f'{program} "{SCRIPTS / "harness_cli.py"}" business doctor'
            self.assertEqual("unknown", classify_command(command))
            self.assertIsNone(self.permission(command))
        for command in (
            f'"{sys.executable}" -c "print(1)"',
            f'"{sys.executable}" "{self.root / "harness_cli.py"}" business doctor',
            'learning review --session abc',
        ):
            self.assertEqual("unknown", classify_command(command))
        with patch("shutil.which", return_value=str(self.root / "company-agent.cmd")):
            self.assertEqual("unknown", classify_command("company-agent business doctor"))
        with patch("shutil.which", return_value=str(SCRIPTS.parent / "bin" / "company-agent.cmd")):
            self.assertEqual("read_only", classify_command("company-agent business doctor"))
            self.assertIsNone(self.permission("company-agent business doctor"))

    def test_pending_prompt_does_not_accept_background_or_extra_tool_fields(self) -> None:
        for extra in ({"run_in_background": True}, {"dangerouslyDisableSandbox": True}, {"command_override": "evil"}):
            tool_input = {"command": f"{self.cli} business doctor", **extra}
            self.assertIsNone(self.permission("unused", tool_input=tool_input))
        for value in (None, 2, {}, ["business doctor"]):
            self.assertIsNone(self.permission("unused", tool_input={"command": value}))

    def test_windows_literal_listing_is_read_only_not_permission_override(self) -> None:
        powershell = _powershell()
        if os.name != "nt":
            self.assertIsNone(powershell)
            return
        self.assertIsNotNone(powershell)
        command = f'"{powershell}" -NoProfile -Command "Get-ChildItem -LiteralPath \'{self.root}\' -Name"'
        self.assertEqual("read_only", classify_command(command))
        self.assertIsNone(self.permission(command))
        for changed in (
            command.replace("-NoProfile ", ""), command.replace("Get-ChildItem", "Get-Content"),
            command.replace("-Name", "-Recurse"), command.replace("-LiteralPath", "-Path"),
            command.replace(str(powershell), str(self.root / "powershell.exe")),
            command.replace("-Name", "; Remove-Item x"),
        ):
            self.assertEqual("unknown", classify_command(changed))


if __name__ == "__main__":
    unittest.main()
