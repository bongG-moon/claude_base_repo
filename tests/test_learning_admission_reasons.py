"""Admission explanations preserve decisions, old records and read-only status."""
import unittest

import test_learning as fixtures
from company_agent import learning
from company_agent.learning_explanation import explain_learning
from company_agent.memory import search_memory, upsert_memory
from company_agent.paths import atomic_write_json
from company_agent.work import checkpoint


class LearningAdmissionReasonTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.LearningTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def state_path(self):
        return self.f.root / "learning/state.json"

    def test_repeated_choice_applied_and_already_active_keep_distinct_reasons(self):
        spec = self.f.spec([self.f.preference()])
        first = self.f.submit(self.f.turn(), spec)
        self.assertEqual(("observing", "independent_work_samples_required"),
                         tuple(first["changes"][0][k] for k in ("status", "reasonCode")))
        self.assertEqual([], search_memory(self.f.root, "보고서"))
        second = self.f.submit(self.f.turn(), spec)
        self.assertEqual("applied", second["changes"][0]["reasonCode"])
        memory = search_memory(self.f.root, "보고서")[0]
        third = self.f.submit(self.f.turn(), spec)
        self.assertEqual("already_active", third["changes"][0]["reasonCode"])
        self.assertNotIn("id", third["changes"][0])
        self.assertEqual(memory, search_memory(self.f.root, "보고서")[0])
        self.assertEqual("already_active", learning.learning_status(self.f.root)["recentCandidates"][0]["reasonCode"])
        self.assertEqual(1, len(learning._load(self.f.root)["changes"]))

    def test_rollback_rejection_is_explained_without_reactivation(self):
        spec = self.f.spec([self.f.preference("explicit_correction")])
        first = self.f.submit(self.f.turn(), spec)
        learning.rollback_change(self.f.root, first["changes"][0]["id"])
        self.assertEqual("rejected_reapplication",
                         learning.learning_status(self.f.root)["recentCandidates"][0]["reasonCode"])
        path = next((self.f.root / "memory/items").glob("*.md"))
        before = path.read_bytes()
        result = self.f.submit(self.f.turn(), spec)
        self.assertEqual(("rejected", "rejected_reapplication"),
                         tuple(result["changes"][0][k] for k in ("status", "reasonCode")))
        self.assertEqual(before, path.read_bytes())
        self.assertEqual([], search_memory(self.f.root, "보고서"))

    def test_legacy_review_verified_fix_names_missing_evidence(self):
        path = self.f.skill()
        result = self.f.submit(self.f.turn(used=self.f.used(path), verification="pass"),
                               self.f.spec([self.f.lesson()]))
        self.assertEqual(("observing", "verified_fix_requires_observed_failure_then_pass"),
                         tuple(result["changes"][0][k] for k in ("status", "reasonCode")))
        self.assertNotIn(learning.BEGIN, path.read_text(encoding="utf-8"))

    def test_target_conflict_keeps_original_reason_and_manual_memory(self):
        path = upsert_memory({"id": "manual", "kind": "preference", "title": "보고서 형식",
                              "body": "짧은 문장으로 작성한다."}, self.f.root)
        before = path.read_bytes()
        result = self.f.submit(self.f.turn(), self.f.spec([self.f.preference("explicit_correction")]))
        change = result["changes"][0]
        self.assertEqual("target_validation_deferred", change["reasonCode"])
        self.assertIn("human preference", change["reason"])
        self.assertEqual(before, path.read_bytes())

    def test_submit_receipt_and_duplicate_preserve_reason_without_extra_votes(self):
        turn = self.f.turn()
        spec = self.f.spec([self.f.preference()])
        first = learning.submit_learning(self.f.root, self.f.session, turn, spec)
        code = "independent_work_sample_not_ready"
        self.assertEqual(code, first["changes"][0]["reasonCode"])
        self.assertEqual(code, first["observationResults"][0]["reasonCode"])
        before = self.state_path().read_bytes()
        again = learning.submit_learning(self.f.root, self.f.session, turn, spec)
        self.assertEqual("duplicate", again["status"])
        self.assertEqual(first["observationResults"], again["observationResults"])
        self.assertEqual(before, self.state_path().read_bytes())
        self.assertEqual(0, learning.learning_status(self.f.root)["recentCandidates"][0]["userChoiceTurns"])

    def test_old_active_records_and_receipts_read_without_migration_or_new_claim(self):
        turn = self.f.turn()
        spec = self.f.spec([self.f.preference("explicit_correction")])
        learning.submit_learning(self.f.root, self.f.session, turn, spec)
        data = learning._load(self.f.root)
        for candidate in data["candidates"].values():
            candidate.pop("reasonCode")
        for review in data["reviews"]:
            for item in review.get("observationResults", []):
                item.pop("reasonCode")
        atomic_write_json(self.state_path(), data)
        before = self.state_path().read_bytes()
        status = learning.learning_status(self.f.root)
        self.assertEqual("active_recorded", status["recentCandidates"][0]["reasonCode"])
        explanation = explain_learning(status)
        self.assertIn("현재 파일을 다시 확인한 결과는 아닙니다", explanation["recentCandidates"][0]["reason"])
        replay = learning.submit_learning(self.f.root, self.f.session, turn, spec)
        self.assertEqual("active_recorded", replay["observationResults"][0]["reasonCode"])
        self.assertEqual(before, self.state_path().read_bytes())
        self.assertEqual(1, learning.learning_status(self.f.root)["activeChanges"])

    def test_old_observing_receipt_uses_unknown_detail_not_invented_signal(self):
        turn = self.f.turn()
        checkpoint(self.f.root, self.f.session, turn, "complete")
        spec = self.f.spec([self.f.preference()])
        learning.submit_learning(self.f.root, self.f.session, turn, spec)
        data = learning._load(self.f.root)
        for review in data["reviews"]:
            for item in review.get("observationResults", []):
                item.pop("reasonCode")
        atomic_write_json(self.state_path(), data)
        before = self.state_path().read_bytes()
        replay = learning.submit_learning(self.f.root, self.f.session, turn, spec)
        self.assertEqual("evidence_required", replay["observationResults"][0]["reasonCode"])
        self.assertEqual(before, self.state_path().read_bytes())
        self.assertEqual(1, learning.learning_status(self.f.root)["recentCandidates"][0]["userChoiceTurns"])


if __name__ == "__main__":
    unittest.main()
