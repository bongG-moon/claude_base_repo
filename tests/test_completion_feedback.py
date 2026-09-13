from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "company-agent-plugin"
SCRIPTS = PLUGIN / "scripts"
sys.path.insert(0, str(SCRIPTS))

from company_agent.completion_feedback import present_stop_feedback
from company_agent.native_runtime import runtime_context
from company_agent.paths import ensure_user_layout
from company_agent.state import begin_turn, record_activity, mark_verified, load_session


class CompletionFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="company-feedback-")
        self.root = Path(self.temp.name)
        ensure_user_layout(self.root)
        self.session = "feedback-test"
        begin_turn(self.session, "MEDIUM", True, (), self.root)

    def tearDown(self):
        self.temp.cleanup()

    def stop(self, active=False):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "stop_feedback_hook.py")],
            input=json.dumps({"session_id": self.session, "stop_hook_active": active}),
            text=True, capture_output=True, encoding="utf-8", check=False,
            env={**os.environ, "COMPANY_AGENT_USER_STATE": str(self.root), "PYTHONUTF8": "1"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        return json.loads(result.stdout)

    def test_read_only_produces_no_notice(self):
        record_activity({"session_id": self.session, "tool_name": "Read"}, self.root)
        self.assertEqual({}, self.stop())
        self.assertEqual(0, load_session(self.session, self.root)["stopRetryCount"])

    def test_pending_change_keeps_gate_but_never_dumps_command_or_ids(self):
        record_activity({"session_id": self.session, "tool_name": "Write"}, self.root)
        result = self.stop()
        self.assertEqual("block", result["decision"])
        self.assertLessEqual(len(result["reason"]), 100)
        for marker in (self.session, str(self.root), "PowerShell", "--session", "--status", "pass/fail"):
            self.assertNotIn(marker, result["reason"])
        self.assertEqual(1, load_session(self.session, self.root)["stopRetryCount"])
        self.assertIsNone(load_session(self.session, self.root)["verification"])

    def test_actual_verification_pass_silences_notice(self):
        record_activity({"session_id": self.session, "tool_name": "Write"}, self.root)
        self.stop()
        mark_verified(self.session, "pass", "actual fixture check", self.root)
        self.assertEqual({}, self.stop(True))

    def test_no_activity_does_not_repeat_correction(self):
        record_activity({"session_id": self.session, "tool_name": "Write"}, self.root)
        self.stop()
        result = self.stop(True)
        self.assertNotIn("decision", result)
        self.assertIn("미검증", result["systemMessage"])
        self.assertIsNone(load_session(self.session, self.root)["verification"])

    def test_unavailable_still_warns_and_does_not_forge_success(self):
        record_activity({"session_id": self.session, "tool_name": "Write"}, self.root)
        mark_verified(self.session, "unavailable", "checker unavailable", self.root)
        result = self.stop()
        self.assertNotIn("decision", result)
        self.assertIn("확인하지 못한", result["systemMessage"])
        state = load_session(self.session, self.root)
        self.assertEqual("unavailable", state["verification"]["status"])
        self.assertEqual(1, state["mutationCount"])

    def test_learning_projection_preserves_real_failure_warning(self):
        decision = {"decision": "block", "reason": "company-agent:self-learning private command details",
                    "systemMessage": "Verification did not pass"}
        result = present_stop_feedback(decision)
        self.assertIn("업무 마무리", result["reason"])
        self.assertNotIn("private", result["reason"])
        self.assertEqual(decision["systemMessage"], result["systemMessage"])
        self.assertIn("private", decision["reason"])

    def test_on_demand_guide_is_discoverable_with_safety_and_exact_commands(self):
        with patch.dict(os.environ, {"COMPANY_AGENT_USER_STATE": str(self.root)}):
            context = json.loads(runtime_context(PLUGIN, self.root))["company_agent_runtime"]
        guide = Path(context["completionGuide"])
        self.assertTrue(guide.is_file())
        body = guide.read_text(encoding="utf-8")
        for marker in ("cliCommand", "company_agent_session_id", "session verify", "learning review",
                       "unavailable", "partial", "2,000", "not conversation", "transcripts"):
            self.assertIn(marker, body)
        self.assertIn("Read completionGuide", context["instructions"])
        self.assertNotIn(body, context["instructions"])


if __name__ == "__main__":
    unittest.main()
