from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"))
from company_agent.state import begin_turn, record_activity, load_session, mark_verified, stop_decision
from company_agent.work import checkpoint
from company_agent.learning import submit_review, learning_status
from company_agent.memory import search_memory


class WorkMilestoneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "state"
        self.session = "work-test"

    def begin(self):
        return begin_turn(self.session, "MEDIUM", False, [], self.root)["turnId"]

    def mark(self, turn, status, **kw):
        return checkpoint(self.root, self.session, turn, status, **kw)

    def stop(self):
        return stop_decision({"session_id": self.session}, self.root)

    def activity(self, name="Read", **kw):
        return record_activity({"session_id": self.session, "tool_name": name,
                                "tool_input": kw}, self.root)

    def spec(self, signal="explicit_correction", observations=True):
        return {"schemaVersion": 1, "taskType": "weekly-report", "outcome": "success",
                "summary": "Report formatting was checked.", "evaluations": [],
                "observations": [{"kind": "preference", "key": "format", "signal": signal,
                                  "title": "Report format", "body": "Start reports with conclusions."}] if observations else []}

    def test_lookup_choices_and_waiting_have_no_review_or_false_fail(self):
        for _ in range(4):
            turn = self.begin()
            self.activity()
            self.assertEqual({}, self.stop())
            state = load_session(self.session, self.root)
            self.assertEqual(0, state["learningAttempts"])
            self.assertIsNone(state["verification"])
        self.mark(turn, "waiting", spec=self.spec())
        self.assertEqual({}, self.stop())
        self.assertEqual(0, learning_status(self.root)["totals"]["reviews"])

    def test_stage_survives_turns_then_one_milestone_applies_memory(self):
        first = self.begin()
        work_id = self.mark(first, "active", spec=self.spec())["workId"]
        self.assertEqual([], search_memory(self.root, "Report"))
        self.assertEqual({}, self.stop())
        second = self.begin()
        self.assertEqual(work_id, self.mark(second, "complete")["workId"])
        self.assertIn("-Mode Cli learning review", self.stop()["reason"])
        result = submit_review(self.root, self.session, second, self.spec(observations=False))
        self.assertEqual("accepted", result["status"])
        self.assertTrue(search_memory(self.root, "Report"))
        self.assertEqual({}, self.stop())
        self.assertEqual(1, learning_status(self.root)["totals"]["reviews"])
        self.assertEqual([], load_session(self.session, self.root)["work"]["pending"])

    def test_no_evidence_complete_does_not_request_empty_review(self):
        turn = self.begin()
        self.mark(turn, "complete")
        self.assertEqual({}, self.stop())
        self.assertEqual(0, learning_status(self.root)["totals"]["reviews"])

    def test_work_completion_never_clears_business_verification(self):
        turn = self.begin()
        self.activity("Write", file_path="business.md")
        self.mark(turn, "complete", learn=True)
        self.assertNotIn("self-learning", self.stop()["reason"])
        with self.assertRaises(ValueError):
            mark_verified(self.session, "not_applicable", "no code", self.root)
        next_turn = self.begin()
        self.assertEqual(1, load_session(self.session, self.root)["mutationCount"])
        with self.assertRaises(ValueError):
            self.mark(next_turn, "active", new=True)
        mark_verified(self.session, "pass", "artifact opened and contents checked", self.root)
        self.mark(next_turn, "complete", learn=True)
        self.assertIn("self-learning", self.stop()["reason"])

    def test_not_applicable_readonly_is_not_fail(self):
        self.begin()
        mark_verified(self.session, "not_applicable", "lookup only", self.root)
        self.assertEqual({}, self.stop())
        self.assertEqual(0, load_session(self.session, self.root)["taskVerificationFailures"])

    def test_repeated_feedback_same_work_is_not_independent_evidence(self):
        first = self.begin()
        self.mark(first, "complete", learn=True)
        submit_review(self.root, self.session, first, self.spec("repeated_choice"))
        second = self.begin()
        self.mark(second, "complete", learn=True)
        submit_review(self.root, self.session, second, self.spec("repeated_choice"))
        self.assertEqual([], search_memory(self.root, "Report"))
        third = self.begin()
        self.mark(third, "active", new=True)
        self.mark(third, "complete", learn=True)
        submit_review(self.root, self.session, third, self.spec("repeated_choice"))
        self.assertTrue(search_memory(self.root, "Report"))

    def test_latest_explicit_correction_can_restore_previous_value_in_same_work(self):
        work_ids = set()
        for body in ("Start reports with conclusions.", "Start reports with background.",
                     "Start reports with conclusions."):
            turn = self.begin()
            spec = self.spec()
            spec["observations"][0]["body"] = body
            work_ids.add(self.mark(turn, "complete", spec=spec)["workId"])
            result = submit_review(self.root, self.session, turn, self.spec(observations=False))
            self.assertEqual("active", result["changes"][0]["status"])
            self.assertEqual(body, search_memory(self.root, "Report")[0]["body"])
        self.assertEqual(1, len(work_ids))

    def test_repeated_identical_explicit_correction_does_not_create_new_change(self):
        for _ in range(2):
            turn = self.begin()
            self.mark(turn, "complete", spec=self.spec())
            result = submit_review(self.root, self.session, turn, self.spec(observations=False))
            self.assertEqual("active", result["changes"][0]["status"])
        self.assertEqual(1, learning_status(self.root)["activeChanges"])
        self.assertEqual(1, len(learning_status(self.root)["recentChanges"]))

    def test_stale_checkpoint_and_new_work_cannot_discard_pending(self):
        first = self.begin()
        self.mark(first, "active", spec=self.spec())
        second = self.begin()
        with self.assertRaises(ValueError):
            self.mark(first, "complete")
        with self.assertRaises(ValueError):
            self.mark(second, "active", new=True)
        self.mark(second, "cancelled")
        self.assertEqual([], load_session(self.session, self.root)["work"]["pending"])
        self.mark(second, "active", new=True)

    def test_stage_rejects_raw_input_and_sensitive_fields(self):
        turn = self.begin()
        spec = self.spec()
        spec["transcript"] = "PRIVATE-RAW"
        with self.assertRaises(ValueError):
            self.mark(turn, "active", spec=spec)
        self.assertNotIn("PRIVATE-RAW", json.dumps(load_session(self.session, self.root)))

    def test_review_engine_rejects_active_and_waiting_without_storing(self):
        turn = self.begin()
        for status in ("active", "waiting"):
            self.mark(turn, status)
            with self.assertRaisesRegex(ValueError, "completed work milestone"):
                submit_review(self.root, self.session, turn, self.spec())
        self.assertEqual(0, learning_status(self.root)["totals"]["reviews"])

    def test_empty_review_skips_ledger_and_same_turn_retries_are_harmless(self):
        turn = self.begin()
        self.mark(turn, "complete", learn=True)
        result = submit_review(self.root, self.session, turn, self.spec(observations=False))
        self.assertEqual("skipped", result["status"])
        self.assertEqual(0, learning_status(self.root)["totals"]["reviews"])
        self.assertEqual({}, self.stop())

    def test_pending_limit_preserves_existing_and_explicit_revision_supersedes(self):
        turn = self.begin()
        spec = self.spec()
        spec["observations"] = [dict(spec["observations"][0], key=f"format-{i}") for i in range(4)]
        self.mark(turn, "active", spec=spec)
        other = self.spec()
        other["observations"] = [dict(other["observations"][0], key=f"format-{i}") for i in range(4, 8)]
        with self.assertRaisesRegex(ValueError, "five pending"):
            self.mark(turn, "active", spec=other)
        pending = load_session(self.session, self.root)["work"]["pending"]
        self.assertEqual(4, len(pending))
        revised = self.spec()
        revised["observations"][0].update(key="format-0", body="Use a short conclusion followed by details.")
        self.mark(turn, "active", spec=revised)
        pending = load_session(self.session, self.root)["work"]["pending"]
        self.assertEqual(4, len(pending))
        self.assertEqual(revised["observations"][0]["body"], pending[0]["body"])
        self.mark(turn, "complete")
        self.assertEqual("accepted", submit_review(self.root, self.session, turn, self.spec(observations=False))["status"])

    def test_exhausted_work_can_change_topic_without_faking_pass(self):
        turn = self.begin()
        self.activity("Write", file_path="artifact.md")
        self.stop()
        self.stop()
        self.mark(turn, "cancelled")
        next_turn = self.begin()
        self.mark(next_turn, "active", new=True)
        state = load_session(self.session, self.root)
        self.assertEqual(0, state["mutationCount"])
        self.assertEqual("unverified", state["unresolvedChanges"][0]["verificationStatus"])
        self.assertEqual(1, state["unresolvedChanges"][0]["mutationCount"])

    def test_completed_exhausted_work_boundary_survives_next_turn_and_can_be_resolved(self):
        from company_agent.work import resolve_unfinished
        turn = self.begin()
        self.activity("Write", file_path="artifact.md")
        self.stop()
        self.stop()
        old_id = self.mark(turn, "complete")["workId"]
        next_turn = self.begin()
        self.mark(next_turn, "active", new=True)
        with self.assertRaises(ValueError):
            resolve_unfinished(self.root, self.session, next_turn, old_id)
        mark_verified(self.session, "pass", "Inspected the prior artifact and verified its repaired result", self.root)
        resolved = resolve_unfinished(self.root, self.session, next_turn, old_id)
        self.assertEqual(0, resolved["unresolvedWorkCount"])
        state = load_session(self.session, self.root)
        self.assertEqual(old_id, state["resolvedChanges"][0]["workId"])
        self.assertEqual("unverified", state["resolvedChanges"][0]["verificationStatus"])

    def test_windows_atomic_replace_retries_only_bounded_same_target(self):
        from company_agent.paths import atomic_write_text
        import os
        path = self.root / "sample.md"
        atomic_write_text(path, "before")
        failure = PermissionError("temporary sharing denial")
        failure.winerror = 5
        original = os.replace
        with patch("company_agent.paths.os.replace", side_effect=[failure, failure, None]) as replace, patch("company_agent.paths.time.sleep"):
            # Simulated success does not actually replace; inspect exact args.
            atomic_write_text(path, "after")
            self.assertEqual(3, replace.call_count)
            self.assertEqual(1, len({call.args for call in replace.call_args_list}))
        with patch("company_agent.paths.os.replace", side_effect=failure) as replace, patch("company_agent.paths.time.sleep"):
            with self.assertRaises(PermissionError):
                atomic_write_text(path, "must not truncate")
            self.assertEqual(4, replace.call_count)
        self.assertEqual("before", path.read_text())

    def test_search_spec_write_is_internal_but_arbitrary_tmp_write_is_not(self):
        self.begin()
        content = json.dumps({"account_smtp": "test@example.com", "store_ids": ["AABBCCDD"], "query": "ax", "limit": 20})
        self.activity("Write", file_path=str(self.root / "tmp" / "mail-search-fixture.json"), content=content)
        self.assertEqual(0, load_session(self.session, self.root)["mutationCount"])
        self.activity("Write", file_path=str(self.root / "tmp" / "other.json"), content=content)
        self.assertEqual(1, load_session(self.session, self.root)["mutationCount"])

    def test_worker_evidence_never_claims_actual_model_from_alias(self):
        self.begin()
        self.activity("Agent", subagent_type="company-agent:medium-worker", model="sonnet", prompt="PRIVATE-TASK")
        state = load_session(self.session, self.root)
        self.assertEqual("sonnet", state["workerExecutions"][0]["requestedAlias"])
        self.assertEqual("unverified", state["workerExecutions"][0]["actualModel"])
        self.assertNotIn("PRIVATE-TASK", json.dumps(state))

    def test_current_work_command_is_bookkeeping_but_injection_is_not(self):
        turn = self.begin()
        from company_agent import state
        cmd = f'"{sys.executable}" -B "{Path(state.__file__).parents[1] / "harness_cli.py"}" work checkpoint --session "{self.session}" --turn "{turn}" --status complete --learn no'
        self.activity("Bash", command=cmd)
        self.assertEqual(0, load_session(self.session, self.root)["mutationCount"])
        self.activity("Bash", command=cmd + ' ; python alter.py')
        self.assertEqual(1, load_session(self.session, self.root)["mutationCount"])


if __name__ == "__main__":
    unittest.main()
