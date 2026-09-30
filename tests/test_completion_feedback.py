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

    def test_pending_change_keeps_gate_and_exact_recovery_context(self):
        record_activity({"session_id": self.session, "tool_name": "Write"}, self.root)
        result = self.stop()
        self.assertEqual("block", result["decision"])
        # A short UI-only message previously erased the only actionable
        # recovery instruction. Keep one bounded command with current scope.
        self.assertLessEqual(len(result["reason"]), 2400)
        for marker in (self.session, str(self.root), "session verify", "--state-root", "--status",
                       "partial", "unavailable"):
            self.assertIn(marker, result["reason"])
        self.assertNotIn("결과물을 확인하고 있습니다.", result["reason"])
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

    def test_settings_lookup_does_not_restart_native_stop_feedback(self):
        record_activity({"session_id": self.session, "tool_name": "Write"}, self.root)
        self.assertEqual("block", self.stop()["decision"])
        # Synthetic event only: never open the user's settings or hooks.
        record_activity({"session_id": self.session, "tool_name": "Read",
                         "tool_input": {"file_path": ".claude/settings.local.json"}}, self.root)
        result = self.stop(True)
        self.assertNotIn("decision", result)
        state = load_session(self.session, self.root)
        self.assertEqual(1, state["stopRetryCount"])
        self.assertEqual(1, state["mutationCount"])
        self.assertIsNone(state["verification"])

    def test_unavailable_still_warns_and_does_not_forge_success(self):
        record_activity({"session_id": self.session, "tool_name": "Write"}, self.root)
        mark_verified(self.session, "unavailable", "checker unavailable", self.root)
        result = self.stop()
        self.assertNotIn("decision", result)
        self.assertIn("확인하지 못한", result["systemMessage"])
        state = load_session(self.session, self.root)
        self.assertEqual("unavailable", state["verification"]["status"])
        self.assertEqual(1, state["mutationCount"])

    def test_learning_projection_preserves_next_action_and_warning(self):
        reason = ('company-agent:self-learning: use current session/turn; '
                  'company-agent learning submit --session current --turn current-turn --spec current.json')
        decision = {"decision": "block", "reason": reason,
                    "systemMessage": "Verification did not pass"}
        result = present_stop_feedback(decision)
        self.assertEqual(reason, result["reason"])
        self.assertEqual(decision["systemMessage"], result["systemMessage"])
        self.assertEqual(reason, decision["reason"])

    def test_localization_does_not_change_gate_or_its_next_action(self):
        decision = {"decision": "block", "reason": "exact next action",
                    "systemMessage": "Report the unverified changes and the required next action honestly."}
        result = present_stop_feedback(decision)
        self.assertEqual("block", result["decision"])
        self.assertEqual("exact next action", result["reason"])
        self.assertIn("확인하지 못한 변경", result["systemMessage"])
        self.assertNotEqual(decision["systemMessage"], result["systemMessage"])

    def test_on_demand_guide_is_discoverable_with_safety_and_exact_commands(self):
        with patch.dict(os.environ, {"COMPANY_AGENT_USER_STATE": str(self.root)}):
            context = json.loads(runtime_context(PLUGIN, self.root))["company_agent_runtime"]
        guide = Path(context["completionGuide"])
        self.assertTrue(guide.is_file())
        body = guide.read_text(encoding="utf-8")
        for marker in ("cliCommand", "company_agent_session_id", "session verify", "learning submit",
                       "unavailable", "partial", "2,000", "not conversation", "transcripts"):
            self.assertIn(marker, body)
        self.assertRegex(context["instructions"], r"Read completionGuide|변경한 업무만 completionGuide를 읽고")
        self.assertNotIn(body, context["instructions"])


if __name__ == "__main__":
    unittest.main()
