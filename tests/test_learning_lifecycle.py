from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import uuid
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from company_agent.paths import atomic_write_json, atomic_write_text
from company_agent.state import (
    begin_turn, learning_context, load_session, mark_learning_complete,
    mark_verified, record_activity, stop_decision,
)
from company_agent.work import checkpoint


class LearningLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "personal state"
        self.session = "learning-session"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def begin(self) -> dict:
        return begin_turn(self.session, "MEDIUM", False, [], self.root)

    def state(self) -> dict:
        return load_session(self.session, self.root)

    def activity(self, tool: str, arguments: dict | None = None, *, failed: bool = False) -> dict:
        response = None
        path = Path((arguments or {}).get("file_path", ""))
        if tool == "Read" and not failed and path.is_file():
            response = {"file": {"content": path.read_text(encoding="utf-8"), "startLine": 1}}
        return record_activity({
            "session_id": self.session, "tool_name": tool, "tool_input": arguments or {},
            "hook_event_name": "PostToolUseFailure" if failed else "PostToolUse",
            "tool_response": response,
        }, self.root)

    def stop(self) -> dict:
        return stop_decision({"session_id": self.session, "stop_hook_active": True}, self.root)

    def complete_work(self) -> None:
        checkpoint(self.root, self.session, self.state()["turnId"], "complete", learn=True)

    def cli(self, arguments: str) -> str:
        return f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}" {arguments}'

    def review_command(self, turn: str) -> str:
        spec = self.root / "tmp" / f"learning-review-{turn}.json"
        return self.cli(f'learning review --session "{self.session}" --turn "{turn}" --spec "{spec}"')

    def skill(self, name: str, body: str = "Reusable private workflow") -> Path:
        path = self.root / "personal-root" / ".claude" / "skills" / name / "SKILL.md"
        atomic_write_text(path, body)
        return path

    def test_read_only_and_no_tool_turns_do_not_review_until_work_milestone(self) -> None:
        started = self.begin()
        self.assertEqual("pending", started["learningStatus"])
        self.assertRegex(started["turnId"], r"^[a-f0-9]{32}$")
        self.assertEqual(0, started["mutationCount"])
        self.assertEqual({}, self.stop())
        self.assertEqual(0, self.state()["learningAttempts"])
        self.activity("Read", {"file_path": str(self.root / "general.md")})
        self.assertEqual({}, self.stop())
        self.complete_work()
        result = self.stop()
        self.assertEqual("block", result["decision"])
        self.assertIn("company-agent:self-learning", result["reason"])
        self.assertIn(started["turnId"], result["reason"])
        self.assertEqual(1, self.state()["learningAttempts"])
        self.assertEqual(0, self.state()["stopRetryCount"])

    def test_completion_is_compare_guarded_idempotent_and_preserves_verification(self) -> None:
        turn = self.begin()["turnId"]
        self.activity("Write")
        mark_verified(self.session, "pass", "Actual task check passed", self.root)
        self.complete_work()
        self.assertEqual("block", self.stop()["decision"])
        before = self.state()
        with self.assertRaises(ValueError):
            mark_learning_complete(self.session, "f" * 32, self.root)
        mark_learning_complete(self.session, turn, self.root)
        completed = self.state()
        self.assertEqual(before["verification"], completed["verification"])
        self.assertEqual(before["mutationCount"], completed["mutationCount"])
        self.assertEqual(completed, mark_learning_complete(self.session, turn, self.root))
        self.assertEqual({}, self.stop())

    def test_verification_runs_first_and_failure_still_gets_honest_review(self) -> None:
        turn = self.begin()["turnId"]
        self.activity("Write")
        self.complete_work()
        for _ in range(2):
            result = self.stop()
            self.assertEqual("block", result["decision"])
            self.assertNotIn("company-agent:self-learning", result["reason"])
            # Each corrective attempt has new evidence. With no execution at
            # all (for example approval unavailable), Stop now ends early.
            self.activity("Read")
        review = self.stop()
        self.assertEqual("block", review["decision"])
        self.assertIn("company-agent:self-learning", review["reason"])
        self.assertIn("Verification did not pass", review["systemMessage"])
        mark_learning_complete(self.session, turn, self.root)
        ended = self.stop()
        self.assertNotIn("decision", ended)
        self.assertIn("Verification did not pass", ended["systemMessage"])
        self.assertIsNone(self.state()["verification"])

    def test_same_failure_exhaustion_never_fabricates_success(self) -> None:
        turn = self.begin()["turnId"]
        self.activity("Write", failed=True)
        for _ in range(2):
            mark_verified(self.session, "fail", "same actual failing assertion", self.root)
        self.complete_work()
        self.assertEqual("block", self.stop()["decision"])
        before = self.state()
        mark_learning_complete(self.session, turn, self.root)
        ended = self.stop()
        self.assertIn("same verification failure", ended["systemMessage"])
        self.assertEqual(before["verification"], self.state()["verification"])
        self.assertEqual(2, self.state()["taskVerificationFailures"])
        self.assertEqual(1, self.state()["taskFailureCount"])

    def test_learning_failure_is_bounded_separately_from_verification(self) -> None:
        turn = self.begin()["turnId"]
        self.activity("Write")
        mark_verified(self.session, "pass", "business result verified", self.root)
        self.complete_work()
        verified = self.state()["verification"]
        for _ in range(2):
            self.assertEqual("block", self.stop()["decision"])
            self.activity("Bash", {"command": self.review_command(turn)}, failed=True)
            self.assertEqual("pending", self.state()["learningStatus"])
            self.assertEqual(verified, self.state()["verification"])
        ended = self.stop()
        self.assertNotIn("decision", ended)
        self.assertIn("review is deferred", ended["systemMessage"])
        self.assertEqual("deferred", self.state()["learningStatus"])
        self.assertEqual(2, self.state()["learningAttempts"])
        self.assertEqual(0, self.state()["taskFailureCount"])
        self.assertEqual({}, self.stop())

    def test_turn_ids_reset_only_on_new_user_turn(self) -> None:
        first = self.begin()
        self.activity("Read", {"file_path": str(self.root / "not-a-skill.md")}, failed=True)
        self.stop()
        self.assertEqual(first["turnId"], self.state()["turnId"])
        self.assertEqual(1, self.state()["taskFailureCount"])
        second = self.begin()
        self.assertNotEqual(first["turnId"], second["turnId"])
        self.assertEqual(first["turnId"], second["previousTurnId"])
        self.assertEqual(0, second["learningAttempts"])
        self.assertEqual(0, second["taskFailureCount"])
        self.assertEqual([], second["usedSkills"])
        with self.assertRaises(ValueError):
            mark_learning_complete(self.session, first["turnId"], self.root)

    def test_verification_pass_does_not_erase_task_failure_history(self) -> None:
        self.begin()
        self.activity("Bash", {"command": "python failed_task.py"}, failed=True)
        mark_verified(self.session, "fail", "failed", self.root)
        mark_verified(self.session, "pass", "fixed and verified", self.root)
        state = self.state()
        self.assertEqual(1, state["taskFailureCount"])
        self.assertEqual(1, state["taskVerificationFailures"])
        self.assertEqual(0, state["sameFailureCount"])

    def test_review_bookkeeping_preserves_verification_and_business_counts(self) -> None:
        turn = self.begin()["turnId"]
        self.activity("Write")
        mark_verified(self.session, "pass", "business check", self.root)
        before = self.state()
        spec = self.root / "tmp" / f"learning-review-{turn}.json"
        self.activity("Bash", {"command": self.cli(f'learning status --session "{self.session}"')})
        self.activity("Write", {"file_path": str(spec), "content": "PRIVATE-REVIEW-JSON"})
        mark_learning_complete(self.session, turn, self.root)
        self.activity("Bash", {"command": self.review_command(turn)})
        after = self.state()
        self.assertEqual(before["verification"], after["verification"])
        self.assertEqual(before["mutationCount"], after["mutationCount"])
        self.assertEqual(before["taskToolCount"], after["taskToolCount"])
        self.assertEqual("complete", after["learningStatus"])
        self.assertNotIn("PRIVATE-REVIEW-JSON", json.dumps(after))

    def test_bookkeeping_exception_rejects_compound_and_wrong_scope_commands(self) -> None:
        cases = [
            lambda t: self.review_command(t) + " ; python business.py",
            lambda t: self.review_command(t) + " > business.txt",
            lambda t: self.review_command(t).replace(self.session, "other-session"),
            lambda t: self.review_command(t).replace(t, "0" * 32),
            lambda t: self.review_command(t).replace(f"learning-review-{t}.json", "business.json"),
            lambda t: self.cli("learning rollback --change change-1"),
            lambda t: self.cli("learning pause"),
            lambda t: f'python "{self.root / "fake" / "harness_cli.py"}" learning status',
        ]
        for make_command in cases:
            with self.subTest(command=make_command.__code__.co_firstlineno):
                turn = self.begin()["turnId"]
                prior_mutations = self.state()["mutationCount"]
                mark_verified(self.session, "pass", "prior business check", self.root)
                state = self.activity("Bash", {"command": make_command(turn)})
                self.assertIsNone(state["verification"])
                self.assertEqual(prior_mutations + 1, state["mutationCount"])
                self.assertEqual(1, state["taskToolCount"])

    def test_only_exact_pending_review_write_is_bookkeeping(self) -> None:
        for tool, leaf in [("Write", "other.json"), ("Edit", "current"), ("Write", "../outside.json")]:
            with self.subTest(tool=tool, leaf=leaf):
                turn = self.begin()["turnId"]
                prior_mutations = self.state()["mutationCount"]
                spec = self.root / "tmp" / (f"learning-review-{turn}.json" if leaf == "current" else leaf)
                mark_verified(self.session, "pass", "prior check", self.root)
                state = self.activity(tool, {"file_path": str(spec)})
                self.assertIsNone(state["verification"])
                self.assertEqual(prior_mutations + 1, state["mutationCount"])

    def test_other_session_status_is_read_only_but_not_a_review_write_exception(self) -> None:
        self.begin()
        mark_verified(self.session, "pass", "prior business check", self.root)
        before = self.state()
        state = self.activity("Bash", {"command": self.cli("learning status --session other-session")})
        self.assertEqual(before["verification"], state["verification"])
        self.assertEqual(before["mutationCount"], state["mutationCount"])
        self.assertEqual({}, self.stop())

    def test_successful_private_skill_read_captures_hash_not_body(self) -> None:
        self.begin()
        body = "PRIVATE-SKILL-BODY-DO-NOT-COPY"
        path = self.skill("report-helper", body)
        state = self.activity("Read", {"file_path": str(path), "query": "PRIVATE-QUERY"})
        self.assertEqual([{"name": "report-helper", "path": str(path), "sha256": hashlib.sha256(body.encode()).hexdigest()}], state["usedSkills"])
        self.assertNotIn(body, json.dumps(state))
        self.assertNotIn("PRIVATE-QUERY", json.dumps(state))
        outside = self.root.parent / "PRIVATE-OTHER-FILE.md"
        self.activity("Read", {"file_path": str(outside)})
        self.assertNotIn(str(outside), json.dumps(self.state()))
        self.assertEqual(1, len(self.state()["usedSkills"]))

    def test_failed_nested_oversized_and_redirected_reads_are_not_skill_evidence(self) -> None:
        self.begin()
        path = self.skill("safe-skill")
        self.activity("Read", {"file_path": str(path)}, failed=True)
        self.activity("Read", {"file_path": str(path.parent / "references" / "SKILL.md")})
        oversized = self.skill("oversized", "x" * 65_537)
        self.activity("Read", {"file_path": str(oversized)})
        original_lstat = Path.lstat
        def redirected(candidate, *args, **kwargs):
            if candidate == path.parent:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return original_lstat(candidate, *args, **kwargs)
        with patch.object(Path, "lstat", redirected):
            self.activity("Read", {"file_path": str(path)})
        self.assertEqual([], self.state()["usedSkills"])
        self.assertEqual(1, self.state()["taskFailureCount"])

    def test_read_observations_are_bounded_and_deduplicated(self) -> None:
        self.begin()
        for number in range(10):
            self.activity("Read", {"file_path": str(self.skill(f"helper-{number}"))})
        last = self.skill("helper-9", "updated body")
        self.activity("Read", {"file_path": str(last)})
        self.assertEqual(8, len(self.state()["usedSkills"]))
        self.assertEqual(1, sum(item["name"] == "helper-9" for item in self.state()["usedSkills"]))

    def test_mcp_error_result_counts_failure_without_retaining_response(self) -> None:
        self.begin()
        for field in ("isError", "is_error"):
            record_activity({
                "session_id": self.session, "tool_name": "mcp__corp-db-read__select",
                "hook_event_name": "PostToolUse", "tool_input": {"query": "PRIVATE-QUERY"},
                "tool_response": {field: True, "content": "PRIVATE-ERROR-RESULT"},
            }, self.root)
        state = self.state()
        self.assertEqual(2, state["taskFailureCount"])
        self.assertEqual(0, state["mutationCount"])
        self.assertNotIn("PRIVATE-", json.dumps(state))

    def test_disabled_and_unknown_sessions_never_create_learning_loop(self) -> None:
        atomic_write_json(self.root / "config" / "learning.json", {"schemaVersion": 1, "enabled": False})
        self.assertEqual("disabled", self.begin()["learningStatus"])
        self.assertEqual({}, self.stop())
        self.assertIsNone(learning_context(load_session("old-session", self.root)))
        self.assertEqual({}, stop_decision({"session_id": "old-session"}, self.root))
        for payload in [{}, {"session_id": None}, {"session_id": "unknown-session"}, [], "not-an-object"]:
            self.assertEqual({}, stop_decision(payload, self.root))
        self.assertEqual({}, record_activity([], self.root))
        atomic_write_json(self.root / "config" / "learning.json", {"schemaVersion": 1, "enabled": True})
        self.begin()
        self.complete_work()
        atomic_write_json(self.root / "config" / "learning.json", {"schemaVersion": 1, "enabled": False})
        self.assertEqual({}, self.stop())
        self.assertEqual("disabled", self.state()["learningStatus"])

    def test_business_work_after_review_defers_stale_learning_and_reopens_verification(self) -> None:
        turn = self.begin()["turnId"]
        mark_verified(self.session, "pass", "previous outcome", self.root)
        mark_learning_complete(self.session, turn, self.root)
        state = self.activity("Write", {"file_path": str(self.root.parent / "business.md")})
        self.assertIsNone(state["verification"])
        self.assertEqual("deferred", state["learningStatus"])
        self.assertEqual("late-business-activity", state["learningDeferredReason"])
        self.assertNotIn("company-agent:self-learning", self.stop()["reason"])
        mark_verified(self.session, "pass", "final business outcome", self.root)
        ended = self.stop()
        self.assertNotIn("decision", ended)
        self.assertEqual({}, ended)  # Internal stale-review state is quiet.
        self.assertEqual("late-business-activity", self.state()["learningDeferredReason"])
        with self.assertRaises(ValueError):
            mark_learning_complete(self.session, turn, self.root)

    def test_prompt_hook_emits_current_lifecycle_without_raw_prompt(self) -> None:
        env = dict(os.environ, COMPANY_AGENT_USER_STATE=str(self.root), PYTHONIOENCODING="cp949:strict", PYTHONUTF8="0")
        contexts = []
        for _ in range(2):
            completed = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "model_route_hook.py")],
                input=json.dumps({"session_id": self.session, "prompt": "PRIVATE-PROMPT-DO-NOT-STORE"}).encode("ascii"),
                capture_output=True, check=True, env=env,
            )
            self.assertEqual(b"", completed.stderr)
            self.assertNotIn(b"PRIVATE-PROMPT", completed.stdout)
            output = json.loads(completed.stdout)
            contexts.append(json.loads(output["hookSpecificOutput"]["additionalContext"])["company_agent_learning"])
        self.assertEqual(contexts[0]["turnId"], contexts[1]["previousTurnId"])
        self.assertEqual("pending", contexts[1]["status"])
        self.assertNotIn("PRIVATE-PROMPT", json.dumps(self.state()))

    def test_native_prompt_duplicate_does_not_reset_turn_or_learning_budget(self) -> None:
        native = str(uuid.uuid4())
        first = begin_turn(self.session, "MEDIUM", False, [], self.root, native_prompt_id=native)
        self.complete_work()
        self.stop()
        before = self.state()
        repeated = begin_turn(self.session, "MEDIUM", False, [], self.root, native_prompt_id=native.upper())
        self.assertEqual(before, repeated)
        self.assertEqual(first["turnId"], repeated["turnId"])
        self.assertEqual(1, repeated["learningAttempts"])
        self.assertNotIn(native, json.dumps(repeated))
        self.assertEqual(hashlib.sha256(native.encode("ascii")).hexdigest(), repeated["nativePromptSha256"])

    def test_stale_native_tool_and_stop_events_cannot_change_new_turn(self) -> None:
        first_native, next_native = str(uuid.uuid4()), str(uuid.uuid4())
        first = begin_turn(self.session, "MEDIUM", False, [], self.root, native_prompt_id=first_native)
        current = begin_turn(self.session, "MEDIUM", False, [], self.root, native_prompt_id=next_native)
        self.assertEqual(first["turnId"], current["previousTurnId"])
        before_bytes = (self.root / "sessions" / f"{self.session}.json").read_bytes()
        payload = {"session_id": self.session, "prompt_id": first_native, "agent_id": "old-worker",
                   "tool_name": "Write", "hook_event_name": "PostToolUseFailure",
                   "tool_input": {"content": "PRIVATE-STALE-WORK"}}
        self.assertEqual(current, record_activity(payload, self.root))
        self.assertEqual({}, stop_decision({"session_id": self.session, "prompt_id": first_native}, self.root))
        self.assertEqual(before_bytes, (self.root / "sessions" / f"{self.session}.json").read_bytes())
        payload["prompt_id"] = next_native
        record_activity(payload, self.root)
        self.assertEqual(1, self.state()["taskFailureCount"])
        self.assertEqual(1, self.state()["mutationCount"])
        self.assertNotIn("PRIVATE-STALE-WORK", json.dumps(self.state()))

    def test_legacy_and_malformed_native_prompt_fields_keep_bounded_fallback(self) -> None:
        native = str(uuid.uuid4())
        begin_turn(self.session, "MEDIUM", False, [], self.root, native_prompt_id=native)
        # Old Claude events have no prompt_id; they still provide observations.
        self.activity("Write")
        self.assertEqual(1, self.state()["mutationCount"])
        for malformed in (None, "PRIVATE-NOT-A-UUID", {"secret": "PRIVATE-VALUE"}, "x" * 10_000):
            with self.subTest(kind=type(malformed).__name__):
                begun = begin_turn(self.session, "SMALL", False, [], self.root, native_prompt_id=malformed)
                self.assertIsNone(begun["nativePromptSha256"])
                payload = {"session_id": self.session, "prompt_id": malformed, "tool_name": "Read"}
                record_activity(payload, self.root)
                self.assertEqual(1, self.state()["taskToolCount"])
                self.assertNotIn("PRIVATE-", json.dumps(self.state()))

    def test_prompt_hook_forwards_native_id_as_hash_only_and_is_idempotent(self) -> None:
        native = str(uuid.uuid4())
        env = dict(os.environ, COMPANY_AGENT_USER_STATE=str(self.root), PYTHONIOENCODING="utf-8")
        seen = []
        for _ in range(2):
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "model_route_hook.py")],
                                    input=json.dumps({"session_id": self.session, "prompt_id": native,
                                                      "prompt": "PRIVATE-USER-CONTENT"}).encode("ascii"),
                                    capture_output=True, check=True, env=env)
            seen.append(json.loads(json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])["company_agent_learning"])
            self.assertNotIn(native.encode(), result.stdout)
            self.assertNotIn(b"PRIVATE-USER-CONTENT", result.stdout)
        self.assertEqual(seen[0], seen[1])
        self.assertNotIn(native, json.dumps(self.state()))

    def test_disabled_learning_collects_no_skill_or_learning_counts_but_verifies_work(self) -> None:
        atomic_write_json(self.root / "config" / "learning.json", {"schemaVersion": 1, "enabled": False})
        self.begin()
        self.activity("Read", {"file_path": str(self.skill("paused-helper"))})
        self.activity("Write", failed=True)
        mark_verified(self.session, "fail", "actual business failure", self.root)
        state = self.state()
        self.assertEqual([], state["usedSkills"])
        self.assertEqual(0, state["taskToolCount"])
        self.assertEqual(0, state["taskFailureCount"])
        self.assertEqual(0, state["taskVerificationFailures"])
        self.assertEqual(1, state["mutationCount"])
        self.assertEqual("fail", state["verification"]["status"])
        self.assertEqual(1, state["sameFailureCount"])
        self.assertEqual("block", self.stop()["decision"])
        mark_verified(self.session, "pass", "actual business fix verified", self.root)
        self.assertEqual({}, self.stop())
        self.assertEqual("disabled", self.state()["learningStatus"])

    def test_midturn_pause_freezes_learning_until_next_genuine_user_turn(self) -> None:
        first = self.begin()
        self.activity("Read", {"file_path": str(self.skill("before-pause"))})
        self.activity("Write", failed=True)
        mark_verified(self.session, "fail", "failure before pause", self.root)
        before = self.state()
        atomic_write_json(self.root / "config" / "learning.json", {"schemaVersion": 1, "enabled": False})
        self.activity("Read", {"file_path": str(self.skill("during-pause"))})
        self.activity("Write", failed=True)
        mark_verified(self.session, "fail", "business failure during pause", self.root)
        paused = self.state()
        self.assertEqual("disabled", paused["learningStatus"])
        self.assertEqual("paused-during-turn", paused["learningDeferredReason"])
        for key in ("usedSkills", "taskToolCount", "taskFailureCount", "taskVerificationFailures"):
            self.assertEqual(before[key], paused[key], key)
        self.assertEqual(before["mutationCount"] + 1, paused["mutationCount"])
        self.assertEqual("business failure during pause", paused["verification"]["summary"])
        atomic_write_json(self.root / "config" / "learning.json", {"schemaVersion": 1, "enabled": True})
        after_resume = self.skill("after-resume")
        self.activity("Read", {"file_path": str(after_resume)})
        mark_verified(self.session, "pass", "final business outcome verified", self.root)
        self.assertEqual({}, self.stop())
        self.assertEqual("disabled", self.state()["learningStatus"])
        self.assertEqual(before["usedSkills"], self.state()["usedSkills"])
        self.assertEqual(before["taskToolCount"], self.state()["taskToolCount"])
        next_turn = self.begin()
        self.assertNotEqual(first["turnId"], next_turn["turnId"])
        self.assertEqual("pending", next_turn["learningStatus"])
        self.activity("Read", {"file_path": str(after_resume)})
        self.assertEqual(1, self.state()["taskToolCount"])
        self.assertEqual(["after-resume"], [item["name"] for item in self.state()["usedSkills"]])


if __name__ == "__main__":
    unittest.main()
