"""Offline recovery hints: no real images, credentials, profiles or model calls."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin/scripts"))
from company_agent import vision_handoff as handoff

VISION_AGENT = "company-agent:vision-worker"
TARGET = r"C:\업무\전략 자료\2026-10-12 12 59 43.jpg"


class VisionHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="company-vision-handoff-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.read = {
            "session_id": "test-session-a", "cwd": r"C:\업무\전략 자료",
            "tool_name": "Read", "tool_input": {"file_path": TARGET},
        }

    def call(self, *, path=TARGET, mention=VISION_AGENT, **inputs):
        return {**self.read, "tool_name": "Agent", "tool_input": {
            "description": "이미지 전사", "prompt": f'Use {mention} to read "{path}" and transcribe.',
            **inputs,
        }}

    def record(self):
        files = list((self.root / "tmp/vision-handoffs").glob("*.json"))
        self.assertEqual(1, len(files))
        return files[0]

    def test_exact_agent_name_repairs_missing_type_without_mutating_caller(self):
        handoff.remember(self.root, self.read)
        payload = self.call()
        original = copy.deepcopy(payload)
        result = handoff.recover(self.root, payload, VISION_AGENT)
        self.assertEqual(VISION_AGENT, result["tool_input"]["subagent_type"])
        self.assertEqual(payload, original)
        self.assertEqual(original["tool_input"]["prompt"], result["tool_input"]["prompt"])

    def test_marker_repairs_general_purpose_and_task_alias(self):
        for tool in ("Agent", "Task"):
            with self.subTest(tool=tool):
                handoff.reset(self.root, self.read)
                marker = handoff.remember(self.root, self.read)
                payload = self.call(mention=marker, subagent_type="general-purpose")
                payload["tool_name"] = tool
                result = handoff.recover(self.root, payload, VISION_AGENT)
                self.assertEqual(VISION_AGENT, result["tool_input"]["subagent_type"])
                self.assertEqual(tool, result["tool_name"])

    def test_json_escaped_full_path_is_a_target(self):
        handoff.remember(self.root, self.read)
        payload = self.call()
        payload["tool_input"]["prompt"] = VISION_AGENT + " " + json.dumps(
            {"file_path": TARGET}, ensure_ascii=False)
        self.assertIsNotNone(handoff.recover(self.root, payload, VISION_AGENT))

    def test_intent_without_exact_target_does_not_repair(self):
        marker = handoff.remember(self.root, self.read)
        for target in ("", Path(TARGET.replace("\\", "/")).name, r"C:\other\x.jpg"):
            with self.subTest(target=target):
                self.assertIsNone(handoff.recover(self.root, self.call(path=target, mention=marker), VISION_AGENT))

    def test_target_without_vision_intent_does_not_repair(self):
        handoff.remember(self.root, self.read)
        self.assertIsNone(handoff.recover(self.root, self.call(mention="image reading worker"), VISION_AGENT))

    def test_filename_prefix_is_not_an_exact_target(self):
        for target in (TARGET + ".bak", TARGET + "2", TARGET + "/child.png", "X" + TARGET):
            with self.subTest(target=target):
                handoff.reset(self.root, self.read)
                handoff.remember(self.root, self.read)
                self.assertIsNone(handoff.recover(self.root, self.call(path=target), VISION_AGENT))

    def test_worker_name_prefix_is_not_explicit_vision_intent(self):
        for mention in (VISION_AGENT + "-other", "other:" + VISION_AGENT):
            with self.subTest(mention=mention):
                handoff.reset(self.root, self.read)
                handoff.remember(self.root, self.read)
                self.assertIsNone(handoff.recover(self.root, self.call(mention=mention), VISION_AGENT))

    def test_recovery_is_consumed_once_even_after_repeated_denied_read(self):
        marker = handoff.remember(self.root, self.read)
        payload = self.call(mention=marker)
        self.assertIsNotNone(handoff.recover(self.root, payload, VISION_AGENT))
        with self.assertRaises(handoff.HandoffAlreadyUsed):
            handoff.recover(self.root, payload, VISION_AGENT)
        self.assertEqual(marker, handoff.remember(self.root, self.read))
        with self.assertRaises(handoff.HandoffAlreadyUsed):
            handoff.recover(self.root, payload, VISION_AGENT)

    def test_late_child_cannot_repopulate_new_turn(self):
        handoff.remember(self.root, self.read)
        handoff.reset(self.root, self.read)
        self.assertEqual('', handoff.remember(self.root, {**self.read, 'agent_id': 'old-child'}))
        self.assertIsNone(handoff.recover(self.root, self.call(), VISION_AGENT))

    def test_malformed_agent_type_does_not_trigger_recovery(self):
        handoff.remember(self.root, self.read)
        for kind in ([], {}, 1):
            self.assertIsNone(handoff.recover(self.root, self.call(subagent_type=kind), VISION_AGENT))

    def test_other_sessions_folders_and_children_do_not_recover(self):
        handoff.remember(self.root, self.read)
        for changes in ({"session_id": "test-session-b"}, {"cwd": r"C:\other"},
                        {"agent_id": "general-child"}):
            with self.subTest(changes=changes):
                self.assertIsNone(handoff.recover(self.root, {**self.call(), **changes}, VISION_AGENT))
        self.assertIsNotNone(handoff.recover(self.root, self.call(), VISION_AGENT))

    def test_new_turn_reset_retires_previous_hint_without_creating_normal_state(self):
        handoff.reset(self.root, self.read)
        self.assertEqual([], list(self.root.rglob("*.json")))
        marker = handoff.remember(self.root, self.read)
        handoff.reset(self.root, self.read)
        self.assertIsNone(handoff.recover(self.root, self.call(mention=marker), VISION_AGENT))
        new_marker = handoff.remember(self.root, self.read)
        self.assertNotEqual(marker, new_marker)
        self.assertIsNone(handoff.recover(self.root, self.call(mention=marker), VISION_AGENT))
        self.assertIsNotNone(handoff.recover(self.root, self.call(mention=new_marker), VISION_AGENT))

    def test_reset_does_not_retire_another_session(self):
        handoff.remember(self.root, self.read)
        handoff.reset(self.root, {**self.read, "session_id": "other-session"})
        self.assertIsNotNone(handoff.recover(self.root, self.call(), VISION_AGENT))

    def test_expired_and_future_dated_hints_do_not_recover(self):
        with patch.object(handoff.time, "time", return_value=1_000):
            handoff.remember(self.root, self.read)
        for now in (999, 1_000 + handoff.TTL_SECONDS, 2_000):
            with self.subTest(now=now), patch.object(handoff.time, "time", return_value=now):
                self.assertIsNone(handoff.recover(self.root, self.call(), VISION_AGENT))

    def test_repeated_read_does_not_extend_ttl(self):
        with patch.object(handoff.time, "time", return_value=1_000):
            marker = handoff.remember(self.root, self.read)
        with patch.object(handoff.time, "time", return_value=1_050):
            self.assertEqual(marker, handoff.remember(self.root, self.read))
        self.assertEqual(1_000, json.loads(self.record().read_text(encoding="utf-8"))["created"])

    def test_missing_session_or_cwd_never_creates_a_record(self):
        for key in ("session_id", "cwd"):
            for value in (None, "", " ", 12):
                with self.subTest(key=key, value=value):
                    payload = {**self.read, key: value}
                    self.assertEqual("", handoff.remember(self.root, payload))
                    self.assertIsNone(handoff.recover(self.root, {**self.call(), key: value}, VISION_AGENT))
        self.assertEqual([], list(self.root.rglob("*.json")))

    def test_explicit_other_agents_resumes_and_forks_are_unchanged(self):
        handoff.remember(self.root, self.read)
        choices = [{"subagent_type": kind} for kind in (
            "company-agent:medium-worker", "other:vision-worker", VISION_AGENT)]
        choices += [{key: "present"} for key in ("resume", "fork", "isolation", "team_name")]
        for choice in choices:
            with self.subTest(choice=choice):
                payload = self.call(**choice)
                original = copy.deepcopy(payload)
                self.assertIsNone(handoff.recover(self.root, payload, VISION_AGENT))
                self.assertEqual(original, payload)

    def test_non_agent_tools_and_no_prior_handoff_do_not_recover(self):
        self.assertIsNone(handoff.recover(self.root, self.call(), VISION_AGENT))
        handoff.remember(self.root, self.read)
        for tool in ("SendMessage", "Read", "Bash", "ToolSearch"):
            with self.subTest(tool=tool):
                self.assertIsNone(handoff.recover(self.root, {**self.call(), "tool_name": tool}, VISION_AGENT))

    def test_record_is_bounded_and_does_not_contain_prompt_source_or_credentials(self):
        sensitive = "NEVER_STORE_SOURCE_OR_CREDENTIAL_SENTINEL"
        payload = {**self.read, "prompt": sensitive, "tool_response": sensitive,
                   "env": {"ANTHROPIC_AUTH_TOKEN": sensitive}, "source_body": sensitive}
        handoff.remember(self.root, payload)
        for i in range(handoff.MAX_TARGETS + 2):
            handoff.remember(self.root, {**self.read, "tool_input": {"file_path": f"C:/work/{i}.jpg"}})
        text = self.record().read_text(encoding="utf-8")
        self.assertNotIn(sensitive, text)
        self.assertNotIn("test-session-a", text)
        self.assertEqual(handoff.MAX_TARGETS, len(json.loads(text)["targets"]))
        self.assertLessEqual(self.record().stat().st_size, handoff.MAX_RECORD_BYTES)
        self.assertIsNone(handoff.recover(self.root, self.call(), VISION_AGENT))

    def test_long_unicode_paths_remain_within_byte_budget(self):
        for i in range(handoff.MAX_TARGETS):
            path = "C:/" + "가" * 1_500 + str(i) + ".jpg"
            handoff.remember(self.root, {**self.read, "tool_input": {"file_path": path}})
        self.assertLessEqual(self.record().stat().st_size, handoff.MAX_RECORD_BYTES)

    def test_ambiguous_multiple_targets_do_not_recover(self):
        handoff.remember(self.root, self.read)
        second = r"C:\work\second.jpg"
        handoff.remember(self.root, {**self.read, "tool_input": {"file_path": second}})
        payload = self.call()
        payload["tool_input"]["prompt"] += f' Also read "{second}".'
        self.assertIsNone(handoff.recover(self.root, payload, VISION_AGENT))

    def test_corrupt_or_oversized_cache_does_not_block_and_can_be_replaced(self):
        for text in ("{broken", "[]", '{"schema":2}', " " * (handoff.MAX_RECORD_BYTES + 1)):
            with self.subTest(text=text[:30]):
                handoff.remember(self.root, self.read)
                self.record().write_text(text, encoding="utf-8")
                self.assertIsNone(handoff.recover(self.root, self.call(), VISION_AGENT))
                self.assertTrue(handoff.remember(self.root, self.read))

    def test_cache_read_and_write_errors_do_not_block_or_consume_recovery(self):
        handoff.remember(self.root, self.read)
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            self.assertIsNone(handoff.recover(self.root, self.call(), VISION_AGENT))
        with patch.object(handoff, "atomic_write_json", side_effect=PermissionError("denied")):
            self.assertIsNone(handoff.recover(self.root, self.call(), VISION_AGENT))
            handoff.reset(self.root, self.read)
            self.assertEqual("", handoff.remember(self.root, {
                **self.read, "tool_input": {"file_path": "C:/work/new.jpg"}}))
        self.assertIsNotNone(handoff.recover(self.root, self.call(), VISION_AGENT))

    def test_malformed_inputs_are_optional_hints_not_hook_failures(self):
        handoff.remember(self.root, self.read)
        for inputs in ([], ["unexpected"], "unexpected", 17, {"prompt": None}):
            with self.subTest(inputs=inputs, helper="remember"):
                self.assertEqual("", handoff.remember(self.root, {**self.read, "tool_input": inputs}))
            with self.subTest(inputs=inputs, helper="recover"):
                self.assertIsNone(handoff.recover(self.root, {**self.call(), "tool_input": inputs}, VISION_AGENT))


if __name__ == "__main__":
    unittest.main()
