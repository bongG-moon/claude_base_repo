"""Saving an honest limitation is successful bookkeeping, not a failed tool."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from company_agent.state import begin_turn, load_session, record_activity, stop_decision


class SessionVerificationCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="company-verify-cli-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "한글 개인 상태"
        self.session = "verification-cli"
        self.env = {**os.environ, "COMPANY_AGENT_USER_STATE": str(self.root),
                    "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        begin_turn(self.session, "SMALL", False, [], self.root)

    def changed(self):
        record_activity({"session_id": self.session, "tool_name": "Write",
                         "tool_input": {"file_path": str(self.root / "synthetic.md")}}, self.root)

    def verify(self, status):
        arguments = [sys.executable, "-B", str(SCRIPTS / "harness_cli.py"),
                     "session", "verify", "--session", self.session,
                     "--state-root", str(self.root), "--status", status,
                     "--summary", "fixture 검사 결과"]
        result = subprocess.run(arguments, env=self.env, capture_output=True,
                                text=True, encoding="utf-8", timeout=20, check=False)
        return result, arguments

    def test_saved_limitations_are_not_tool_failures_and_preserve_obligations(self):
        for status in ("partial", "unavailable"):
            with self.subTest(status=status):
                self.changed()
                before = load_session(self.session, self.root)["mutationCount"]
                result, arguments = self.verify(status)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("", result.stderr)
                receipt = json.loads(result.stdout)
                self.assertTrue(receipt["ok"])
                self.assertEqual(status, receipt["verification"]["status"])
                self.assertEqual(self.session, receipt["session"])
                # The successful marker's own native activity cannot erase it.
                state = record_activity({"session_id": self.session, "tool_name": "Bash",
                                         "hook_event_name": "PostToolUse",
                                         "tool_input": {"command": subprocess.list2cmdline(arguments)}}, self.root)
                self.assertEqual(before, state["mutationCount"])
                self.assertEqual(status, state["verification"]["status"])
                self.assertNotIn("decision", stop_decision({"session_id": self.session}, self.root))

    def test_actual_failed_check_retains_nonzero_status_and_obligation(self):
        self.changed()
        result, _ = self.verify("fail")
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual("fail", json.loads(result.stdout)["verification"]["status"])
        state = load_session(self.session, self.root)
        self.assertEqual(1, state["mutationCount"])
        self.assertEqual("fail", state["verification"]["status"])
        self.assertEqual("block", stop_decision({"session_id": self.session}, self.root)["decision"])

    def test_not_applicable_is_successful_only_without_recorded_changes(self):
        result, _ = self.verify("not_applicable")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("not_applicable", json.loads(result.stdout)["verification"]["status"])
        self.changed()
        result, _ = self.verify("not_applicable")
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(json.loads(result.stderr)["ok"])
        state = load_session(self.session, self.root)
        self.assertEqual(1, state["mutationCount"])
        self.assertIsNone(state["verification"])

    def test_pass_keeps_existing_success_contract(self):
        self.changed()
        result, _ = self.verify("pass")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("pass", json.loads(result.stdout)["verification"]["status"])
        self.assertEqual({}, stop_decision({"session_id": self.session}, self.root))


if __name__ == "__main__":
    unittest.main()
