"""One bounded learning submission, independent of business completion."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from company_agent.learning import learning_status, set_learning_enabled, submit_learning, submit_review
from company_agent.memory import search_memory, upsert_memory
from company_agent.paths import atomic_write_json, atomic_write_text
from company_agent.state import begin_turn, load_session, mark_verified, record_activity, session_path, stop_decision
from company_agent.work import checkpoint


class LearningSubmitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "개인 학습"
        self.sid = "learning-submit"
        self.turn = self.new_turn()

    def new_turn(self):
        return begin_turn(self.sid, "MEDIUM", False, [], self.root)["turnId"]

    def session(self):
        return load_session(self.sid, self.root)

    def spec(self, observations=None, **values):
        return {"schemaVersion": 1, "taskType": "report", "outcome": "unknown",
                "summary": "사용자의 지속적인 보고 형식 선호를 확인함",
                "observations": observations or [], "evaluations": [], **values}

    def preference(self, signal="explicit_correction", **values):
        return {"kind": "preference", "key": "report-format", "signal": signal,
                "title": "보고서 형식", "body": "결론을 먼저 제시하고 표로 정리한다.", **values}

    def lesson(self, signal="explicit_correction"):
        return {"kind": "skill", "key": "check-grain", "signal": signal, "title": "집계 기준 확인",
                "body": "집계 전 기간과 기준 단위를 확인한다.", "skillName": "report"}

    def submit(self, spec=None):
        return submit_learning(self.root, self.sid, self.turn, spec or self.spec())

    def skill(self):
        path = self.root / "personal-root/.claude/skills/report/SKILL.md"
        atomic_write_text(path, "---\nname: report\ndescription: Report workflow\n---\n# Work\nCheck results.\n")
        return path

    def read(self, path):
        body = path.read_text(encoding="utf-8")
        return record_activity({"session_id": self.sid, "tool_name": "Read",
            "tool_input": {"file_path": str(path)}, "tool_response": {"file": {
                "content": body, "startLine": 1}}}, self.root)

    def mutate(self):
        return record_activity({"session_id": self.sid, "tool_name": "Write",
            "tool_input": {"file_path": str(self.root.parent / "report.md"), "content": "SOURCE-NOT-STORED"},
            "tool_response": {"success": True}}, self.root)

    def verify(self, status="pass"):
        return mark_verified(self.sid, status, "Current component checked", self.root)

    def cli(self, spec, operation="submit", filename=None):
        file = filename or self.root / "tmp" / f"learning-review-{self.turn}.json"
        atomic_write_json(file, spec)
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "harness_cli.py"), "learning", operation,
            "--session", self.sid, "--turn", self.turn, "--state-root", str(self.root), "--spec", str(file)],
            env={**os.environ, "COMPANY_AGENT_USER_STATE": str(self.root)}, capture_output=True, timeout=30)
        return result.returncode, json.loads(result.stdout or result.stderr), file

    def test_active_preference_is_captured_and_applied_without_checkpoint_or_fake_pass(self):
        before = self.mutate()
        result = self.submit(self.spec([self.preference()]))
        self.assertEqual(("accepted", "captured", 1, 1, 0), tuple(result[k] for k in
            ("status", "captureStatus", "capturedCount", "appliedCount", "deferredCount")))
        after = self.session()
        for key in ("mutationCount", "verification", "stopRetryCount", "verificationRevision"):
            self.assertEqual(before.get(key), after.get(key))
        self.assertEqual("active", after["work"]["status"])
        self.assertFalse(after["work"]["closed"])
        self.assertEqual(1, len(search_memory(self.root, "보고서")))
        self.assertEqual("captured", learning_status(self.root, session=after)["currentSubmission"]["captureStatus"])
        self.assertNotIn("SOURCE-NOT-STORED", (self.root / "learning/state.json").read_text(encoding="utf-8"))

    def test_later_business_activity_preserves_receipt_but_invalidates_verification(self):
        self.verify()
        self.submit(self.spec([self.preference()]))
        receipt = self.session()["learningSubmission"]
        state = self.mutate()
        self.assertIsNone(state["verification"])
        self.assertEqual(receipt, state["learningSubmission"])
        self.assertNotEqual("late-business-activity", state.get("learningDeferredReason"))
        result = self.submit(self.spec([self.preference(body="요약을 마지막에 쓴다.")]))
        self.assertEqual(("duplicate", 0, 0), (result["status"], result["capturedCount"], result["appliedCount"]))
        self.assertEqual(1, learning_status(self.root)["retainedReviews"])
        self.assertEqual(self.preference()["body"], search_memory(self.root, "보고서")[0]["body"])

    def test_empty_accepted_receipt_is_not_never_submitted_or_completed_work(self):
        self.assertEqual("not_observable", learning_status(self.root)["currentSubmission"]["captureStatus"])
        self.assertEqual("not_submitted", learning_status(self.root, session=self.session())["currentSubmission"]["captureStatus"])
        result = self.submit()
        self.assertEqual(("no_candidates", 0, 0), (result["captureStatus"], result["capturedCount"], result["appliedCount"]))
        self.assertEqual(1, learning_status(self.root)["totals"]["emptySubmissions"])
        self.assertEqual("active", self.session()["work"]["status"])
        self.assertEqual({}, stop_decision({"session_id": self.sid}, self.root))
        self.turn = self.new_turn()
        self.assertEqual("not_submitted", learning_status(self.root, session=self.session())["currentSubmission"]["captureStatus"])

    def test_unverified_repeated_choice_is_deferred_without_vote_and_survives_next_turn(self):
        result = self.submit(self.spec([self.preference("repeated_choice")]))
        self.assertEqual(1, result["deferredCount"])
        self.assertEqual(1, len(self.session()["work"]["pending"]))
        self.assertEqual(0, learning_status(self.root)["recentCandidates"][0]["userChoiceTurns"])
        self.turn = self.new_turn()
        self.verify()
        result = self.submit(self.spec(outcome="success"))
        self.assertEqual("observing", result["changes"][0]["status"])
        self.assertEqual(1, learning_status(self.root)["recentCandidates"][0]["userChoiceTurns"])
        self.assertEqual([], self.session()["work"]["pending"])

    def test_two_verified_independent_work_samples_only_not_two_active_turns(self):
        work_id = self.session()["work"]["id"]
        self.verify()
        self.submit(self.spec([self.preference("repeated_choice")], outcome="success"))
        self.turn = self.new_turn()
        self.verify()
        self.submit(self.spec([self.preference("repeated_choice")], outcome="success"))
        self.assertEqual(work_id, self.session()["work"]["id"])
        self.assertEqual(0, learning_status(self.root)["activeChanges"])
        self.assertEqual(1, learning_status(self.root)["recentCandidates"][0]["userChoiceTurns"])
        self.turn = self.new_turn()
        checkpoint(self.root, self.sid, self.turn, "active", new=True)
        self.verify()
        result = self.submit(self.spec([self.preference("repeated_choice")], outcome="success"))
        self.assertEqual(1, result["appliedCount"])
        self.assertEqual("active", self.session()["work"]["status"])

    def test_explicit_completed_sample_can_vote_without_fabricated_verification(self):
        checkpoint(self.root, self.sid, self.turn, "complete")
        result = self.submit(self.spec([self.preference("repeated_choice")]))
        self.assertEqual("observing", result["changes"][0]["status"])
        self.assertIsNone(self.session()["verification"])

    def test_old_complete_flag_after_new_write_or_failed_check_is_not_a_sample(self):
        for status in (None, "fail", "partial", "unavailable"):
            with self.subTest(status=status):
                self.sid = f"completed-sample-{status}"
                self.turn = self.new_turn()
                checkpoint(self.root, self.sid, self.turn, "cancelled")
                checkpoint(self.root, self.sid, self.turn, "active", new=True)
                checkpoint(self.root, self.sid, self.turn, "complete")
                if status is None:
                    self.mutate()
                    self.assertFalse(self.session()["work"]["closed"])
                else:
                    self.verify(status)
                result = self.submit(self.spec([self.preference("repeated_choice")]))
                self.assertEqual(1, result["deferredCount"])
                self.assertEqual(1, len(self.session()["work"]["pending"]))
                self.assertEqual(0, learning_status(self.root)["recentCandidates"][0]["userChoiceTurns"])

    def test_duplicate_changed_input_never_discards_deferred_candidate(self):
        self.submit(self.spec([self.lesson()]))
        pending = self.session()["work"]["pending"]
        changed = {**self.lesson(), "body": "집계 결과를 먼저 설명한다."}
        result = self.submit(self.spec([changed]))
        self.assertEqual("duplicate", result["status"])
        self.assertEqual(pending, self.session()["work"]["pending"])

    def test_old_turn_or_same_turn_previous_work_pass_cannot_promote(self):
        for new_work in (False, True):
            with self.subTest(new_work=new_work):
                self.turn = self.new_turn()
                checkpoint(self.root, self.sid, self.turn, "cancelled")
                checkpoint(self.root, self.sid, self.turn, "active", new=True)
                self.verify()
                if new_work:
                    checkpoint(self.root, self.sid, self.turn, "active", new=True)
                else:
                    self.turn = self.new_turn()
                result = self.submit(self.spec([self.preference("repeated_choice")], outcome="success"))
                self.assertEqual(1, result["deferredCount"])
                self.assertEqual(0, learning_status(self.root)["recentCandidates"][0]["userChoiceTurns"])

    def test_skill_requires_current_pass_success_and_exact_loaded_personal_revision(self):
        file = self.skill()
        original = file.read_bytes()
        self.read(file)
        result = self.submit(self.spec([self.lesson()], outcome="success"))
        self.assertEqual(1, result["deferredCount"])
        self.assertEqual(original, file.read_bytes())
        self.turn = self.new_turn()
        self.verify()
        result = self.submit(self.spec(outcome="partial"))
        self.assertEqual(1, result["deferredCount"])
        self.turn = self.new_turn()
        self.verify()
        self.mutate()
        result = self.submit(self.spec(outcome="success"))
        self.assertEqual(1, result["deferredCount"])
        self.turn = self.new_turn()
        self.verify()
        result = self.submit(self.spec(outcome="success"))
        self.assertEqual(1, result["appliedCount"])
        self.assertEqual([], self.session()["work"]["pending"])
        self.assertIn("company-agent-learning:begin", file.read_text(encoding="utf-8"))
        self.assertEqual("active", self.session()["work"]["status"])

    def test_skill_missing_unread_or_changed_revision_is_deferred_not_created(self):
        self.verify()
        result = self.submit(self.spec([self.lesson()], outcome="success"))
        self.assertEqual(1, result["deferredCount"])
        self.assertFalse((self.root / "personal-root/.claude/skills/report/SKILL.md").exists())
        file = self.skill()
        self.turn = self.new_turn()
        self.verify()
        result = self.submit(self.spec(outcome="success"))
        self.assertEqual(1, result["deferredCount"])
        self.turn = self.new_turn()
        self.read(file)
        atomic_write_text(file, file.read_text(encoding="utf-8") + "Manual addition.\n")
        self.verify()
        result = self.submit(self.spec(outcome="success"))
        self.assertEqual(1, result["deferredCount"])
        self.assertNotIn("company-agent-learning:begin", file.read_text(encoding="utf-8"))

    def test_verified_fix_requires_observed_failure_then_verified_success(self):
        file = self.skill()
        self.read(file)
        self.verify()
        result = self.submit(self.spec([self.lesson("verified_fix")], outcome="success"))
        self.assertEqual(1, result["deferredCount"])
        self.turn = self.new_turn()
        self.verify("fail")
        self.verify()
        result = self.submit(self.spec(outcome="success"))
        self.assertEqual(1, result["appliedCount"])

    def test_unverified_capture_is_not_metric_baseline_or_helpful_assessment(self):
        file = self.skill()
        self.read(file)
        self.submit(self.spec([self.preference()]))
        self.turn = self.new_turn()
        checkpoint(self.root, self.sid, self.turn, "active", new=True)
        self.read(file)
        self.verify()
        self.submit(self.spec([self.lesson()], outcome="success"))
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        self.turn = self.new_turn()
        checkpoint(self.root, self.sid, self.turn, "active", new=True)
        self.read(file)
        result = self.submit(self.spec(evaluations=[{"skillName": "report", "sha256": digest, "verdict": "helpful"}]))
        self.assertEqual("deferred_evidence", result["assessments"][0]["status"])
        self.assertEqual([], learning_status(self.root)["recentAssessments"])
        self.turn = self.new_turn()
        self.verify()
        result = self.submit(self.spec(outcome="success", evaluations=[
            {"skillName": "report", "sha256": digest, "verdict": "helpful"}]))
        self.assertEqual(1, result["assessments"][0]["baselineSamples"])
        self.assertFalse(result["assessments"][0]["causalClaim"])

    def test_reported_harmful_revision_and_exact_prior_correction_keep_safe_rollback(self):
        file = self.skill()
        original = file.read_bytes()
        self.read(file)
        self.verify()
        self.submit(self.spec([self.lesson()], outcome="success"))
        self.turn = self.new_turn()
        self.read(file)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        result = self.submit(self.spec(outcome="failure", evaluations=[
            {"skillName": "report", "sha256": digest, "verdict": "harmful"}]))
        self.assertEqual("rolled_back", result["assessments"][0]["rollback"]["status"])
        self.assertEqual(original, file.read_bytes())
        self.turn = self.new_turn()
        learned = self.submit(self.spec([self.preference()]))
        prior_turn = self.turn
        self.turn = self.new_turn()
        result = self.submit(self.spec(priorFeedback={"turnId": prior_turn, "verdict": "corrected",
            "changeId": learned["changes"][0]["id"]}))
        self.assertEqual("rolled_back", result["assessments"][0]["rollback"]["status"])
        self.assertEqual([], search_memory(self.root, "보고서"))

    def test_legacy_stage_pending_is_consumed_by_unified_submit_without_completion(self):
        checkpoint(self.root, self.sid, self.turn, "active", spec=self.spec([self.preference()]))
        result = self.submit()
        self.assertEqual(1, result["appliedCount"])
        self.assertEqual([], self.session()["work"]["pending"])
        self.assertEqual("active", self.session()["work"]["status"])

    def test_pause_protection_and_human_conflict_preserved(self):
        set_learning_enabled(self.root, False)
        self.assertEqual("disabled", self.submit(self.spec([self.preference()]))["status"])
        self.assertEqual(0, learning_status(self.root)["retainedReviews"])
        set_learning_enabled(self.root, True)
        state = self.session()
        state["protectionRestricted"] = True
        atomic_write_json(session_path(self.sid, self.root), state)
        self.assertEqual("disabled", self.submit(self.spec([self.preference()]))["status"])
        state["protectionRestricted"] = False
        atomic_write_json(session_path(self.sid, self.root), state)
        file = upsert_memory({"id": "memory.preference.report-format", "kind": "preference",
            "title": "보고서 형식", "body": "표 대신 문장으로 설명한다."}, self.root)
        before = file.read_bytes()
        result = self.submit(self.spec([self.preference()]))
        self.assertEqual(1, result["deferredCount"])
        self.assertEqual(before, file.read_bytes())

    def test_cli_single_submit_cleans_canonical_spec_and_safe_malformed_retry(self):
        malformed = self.spec([self.preference(body="password=TOPSECRET")])
        code, result, file = self.cli(malformed)
        self.assertEqual(1, code)
        self.assertFalse(file.exists())
        self.assertTrue(result["needsSpecRewrite"])
        self.assertEqual(0, learning_status(self.root)["retainedReviews"])
        code, result, file = self.cli(self.spec([self.preference()]))
        self.assertEqual(0, code, result)
        self.assertEqual(("accepted", 1, "removed"), (result["status"], result["appliedCount"], result["stagingCleanup"]))
        self.assertFalse(file.exists())
        self.assertNotIn("TOPSECRET", (self.root / "learning/state.json").read_text(encoding="utf-8"))
        self.assertEqual("active", self.session()["work"]["status"])

    def test_wrong_canonical_path_and_stale_turn_do_not_accept(self):
        code, _, file = self.cli(self.spec([self.preference()]), filename=self.root / "tmp/other.json")
        self.assertEqual(1, code)
        self.assertTrue(file.exists())
        old = self.turn
        self.turn = self.new_turn()
        with self.assertRaisesRegex(ValueError, "stale"):
            submit_learning(self.root, self.sid, old, self.spec([self.preference()]))
        self.assertEqual(0, learning_status(self.root)["retainedReviews"])

    def test_duplicate_legacy_review_does_not_close_active_submitted_work(self):
        spec = self.spec([self.preference()])
        self.submit(spec)
        result = submit_review(self.root, self.sid, self.turn, spec)
        self.assertEqual("duplicate", result["status"])
        self.assertEqual("active", self.session()["work"]["status"])
        self.assertFalse(self.session()["work"]["closed"])

    def test_ledger_first_interruption_replays_once_without_false_completion(self):
        from company_agent import learning
        original_write = learning.atomic_write_json
        def interrupted(path, value):
            if path == session_path(self.sid, self.root):
                raise OSError("session receipt interruption")
            return original_write(path, value)
        spec = self.spec([self.preference()])
        with patch.object(learning, "atomic_write_json", side_effect=interrupted):
            with self.assertRaises(OSError):
                self.submit(spec)
        result = self.submit(spec)
        self.assertEqual(("duplicate", 0), (result["status"], result["appliedCount"]))
        self.assertEqual(1, learning_status(self.root)["activeChanges"])
        self.assertEqual(1, self.session()["learningSubmission"]["appliedCount"])
        self.assertEqual("active", self.session()["work"]["status"])


if __name__ == "__main__":
    unittest.main()
