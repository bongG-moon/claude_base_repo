"""Regression cases from independent real-CLI acceptance reviews."""
import argparse
import json
import os
from email.message import EmailMessage
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from company_agent.state import begin_turn, record_activity, stop_decision, load_session, mark_verified
from company_agent.business import register, dispatch
from company_agent.execution_contract import classify_command, safe_permission


class AcceptanceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        begin_turn("test", tier="SMALL", verification_required=False, reason_codes=[], root=self.root)

    def event(self, **kwargs):
        return record_activity({"session_id": "test", "tool_name": "Bash",
                                "tool_input": {"command": "python unknown.py"}, **kwargs}, self.root)

    def test_host_denial_is_not_a_mutation_and_never_fake_pass(self):
        state = self.event(hook_event_name="PostToolUseFailure",
                           error="Permission for this tool use was denied. The action was NOT performed; do not retry it.")
        self.assertEqual(0, state["mutationCount"])
        self.assertIsNone(state["verification"])
        self.assertNotIn("decision", stop_decision({"session_id": "test"}, self.root))

    def test_denial_does_not_clear_existing_changes_and_resets_next_turn(self):
        self.event(tool_name="Write", tool_input={"file_path": str(self.root / "output.md")})
        self.event(hook_event_name="PostToolUseFailure",
                   error="Permission for this tool use was denied. The action was NOT performed.")
        self.assertEqual(1, load_session("test", self.root)["mutationCount"])
        self.assertNotIn("decision", stop_decision({"session_id": "test"}, self.root))
        state = begin_turn("test", tier="SMALL", verification_required=False, reason_codes=[], root=self.root)
        self.assertFalse(state["approvalUnavailable"])
        self.assertEqual(1, state["mutationCount"])
        self.assertEqual("block", stop_decision({"session_id": "test"}, self.root)["decision"])

    def test_generic_partial_permission_error_still_requires_verification(self):
        for error in ("PermissionError: denied after write", "Permission for this tool use was denied."):
            state = self.event(hook_event_name="PostToolUseFailure", error=error)
            self.assertFalse(state.get("approvalUnavailable"))
        self.assertEqual(2, state["mutationCount"])
        # Tool output cannot impersonate a native rejection.
        state = self.event(hook_event_name="PostToolUse", tool_response={"isError": True,
            "error": "Permission for this tool use was denied. The action was NOT performed."})
        self.assertEqual(3, state["mutationCount"])

    def test_unavailable_verification_ends_without_forging_success(self):
        self.event()
        mark_verified("test", "unavailable", "required checker unavailable", self.root)
        self.assertNotIn("decision", stop_decision({"session_id": "test"}, self.root))
        self.assertEqual("unavailable", load_session("test", self.root)["verification"]["status"])
        self.assertEqual(1, load_session("test", self.root)["mutationCount"])

    def test_eml_public_cli_readonly_but_not_auto_permission(self):
        message = EmailMessage()
        message.set_content("synthetic meeting 14:00")
        source = self.root / "mail.eml"
        source.write_bytes(message.as_bytes())
        parser = argparse.ArgumentParser()
        register(parser.add_subparsers())
        result = dispatch(parser.parse_args(["business", "eml-read", "--file", str(source), "--state-root", str(self.root)]))
        self.assertTrue(result["ok"])
        self.assertIn("14:00", result["body"])
        command = f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}" business eml-read --file "{source}"'
        self.assertEqual("read_only", classify_command(command))
        self.assertIsNone(safe_permission({"hook_event_name": "PermissionRequest", "tool_name": "Bash",
                                         "tool_input": {"command": command}}, self.root))

    def test_readonly_memory_and_help_do_not_trigger_verification(self):
        for suffix in ('memory search "synthetic" --limit 3', 'memory upsert --help'):
            command = f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}" {suffix}'
            self.assertEqual("read_only", classify_command(command))
            state = self.event(tool_input={"command": command})
            self.assertEqual(0, state["mutationCount"])

    def test_plan_receipt_is_internal_but_alternate_state_is_not(self):
        prefix = f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}" business files-plan --folder "{self.root}"'
        state = self.event(tool_input={"command": prefix + f' --state-root "{self.root}"'})
        self.assertEqual(0, state["mutationCount"])
        self.assertNotIn("decision", stop_decision({"session_id": "test"}, self.root))
        state = self.event(tool_input={"command": prefix + f' --state-root "{self.root / "other"}"'})
        self.assertEqual(1, state["mutationCount"])

    def test_no_new_execution_evidence_does_not_repeat_stop(self):
        self.event(tool_name="Write")
        self.assertEqual("block", stop_decision({"session_id": "test"}, self.root)["decision"])
        result = stop_decision({"session_id": "test", "stop_hook_active": True}, self.root)
        self.assertNotIn("decision", result)
        self.assertEqual(1, load_session("test", self.root)["mutationCount"])
        self.assertIsNone(load_session("test", self.root)["verification"])

    def test_literal_percent_in_verified_summary_keeps_the_marker(self):
        from company_agent.state import _is_own_verification_command
        command = f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}" session verify --session test --status pass --summary "9 of 10 (90%) checked" --state-root "{self.root}"'
        self.assertTrue(_is_own_verification_command(command, "test", self.root))
        mark_verified("test", "pass", "9 of 10 checked", self.root)
        state = self.event(tool_input={"command": command})
        self.assertEqual("pass", state["verification"]["status"])
        self.assertFalse(_is_own_verification_command(command + " > result.txt", "test", self.root))
        self.assertFalse(_is_own_verification_command(command.replace(str(sys.executable), str(self.root / "python.exe")), "test", self.root))

    def test_task_reminders_stay_bounded_and_do_not_echo_source_text(self):
        from company_agent.native_runtime import runtime_context, MAX_RUNTIME_CONTEXT_CHARS
        with patch.dict(os.environ, {"COMPANY_AGENT_USER_STATE": str(self.root)}):
            value = runtime_context(SCRIPTS.parent, self.root, "Outlook 정책 DRM 첨부 .eml 기억 PRIVATE-MARKER-DO-NOT-COPY")
        self.assertLessEqual(len(value), MAX_RUNTIME_CONTEXT_CHARS)
        runtime = json.loads(value)["company_agent_runtime"]
        self.assertNotIn("contextStatus", runtime)
        self.assertEqual(4, len(runtime["taskReminders"]))
        self.assertNotIn("PRIVATE-MARKER", value)

    def test_new_verification_evidence_retains_second_correction(self):
        self.event(tool_name="Write")
        self.assertEqual("block", stop_decision({"session_id": "test"}, self.root)["decision"])
        mark_verified("test", "fail", "actual newly completed check failed", self.root)
        result = stop_decision({"session_id": "test", "stop_hook_active": True}, self.root)
        self.assertEqual("block", result["decision"])


if __name__ == "__main__":
    unittest.main()
