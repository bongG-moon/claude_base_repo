from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"))
from company_agent.state import begin_turn, load_session
from company_agent.work import checkpoint, context
from company_agent.learning import submit_review, learning_status
from company_agent.paths import atomic_write_json


class LearningTaskIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "state"
        self.session = "task-identity"

    def begin(self):
        return begin_turn(self.session, "MEDIUM", False, [], self.root)["turnId"]

    def spec(self, task="borayeon-report", observations=True):
        return {"schemaVersion": 1, "taskType": task, "outcome": "success", "summary": "Synthetic scoped preference reviewed.",
                "observations": [{"kind": "preference", "key": "decision-first", "signal": "explicit_correction",
                                  "title": "Practice report order", "body": "Practice reports put the decision before background."}] if observations else [], "evaluations": []}

    def stage(self, turn):
        return checkpoint(self.root, self.session, turn, "active", spec=self.spec())

    def test_staged_identity_survives_next_turn_and_is_exposed(self):
        first = self.begin()
        self.assertEqual("borayeon-report", self.stage(first)["taskType"])
        self.begin()
        current = load_session(self.session, self.root)
        self.assertEqual("borayeon-report", current["work"]["taskType"])
        self.assertEqual("borayeon-report", context(current)["taskType"])
        self.assertEqual("borayeon-report", learning_status(self.root, session=current)["workTaskType"])

    def test_stage_mismatch_is_rejected_without_losing_candidates(self):
        turn = self.begin()
        self.stage(turn)
        path = self.root / "sessions" / f"{self.session}.json"
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "use taskType 'borayeon-report'"):
            checkpoint(self.root, self.session, turn, "active", spec=self.spec("borayeon-practice-report"))
        self.assertEqual(before, path.read_bytes())

    def test_review_mismatch_has_no_ledger_or_state_side_effects(self):
        turn = self.begin()
        self.stage(turn)
        checkpoint(self.root, self.session, turn, "complete")
        before = load_session(self.session, self.root)
        with self.assertRaisesRegex(ValueError, "taskType mismatch"):
            submit_review(self.root, self.session, turn, self.spec("borayeon-practice-report", False))
        self.assertEqual(before, load_session(self.session, self.root))
        self.assertEqual(0, learning_status(self.root)["totals"]["reviews"])
        result = submit_review(self.root, self.session, turn, self.spec(observations=False))
        self.assertEqual("accepted", result["status"])
        current = load_session(self.session, self.root)
        self.assertEqual([], current["work"]["pending"])
        self.assertEqual("borayeon-report", current["work"]["taskType"])

    def test_new_work_resets_identity_only_after_cancellation(self):
        turn = self.begin()
        self.stage(turn)
        with self.assertRaises(ValueError):
            checkpoint(self.root, self.session, turn, "active", new=True, spec=self.spec("other-report"))
        checkpoint(self.root, self.session, turn, "cancelled")
        next_turn = self.begin()
        result = checkpoint(self.root, self.session, next_turn, "active", new=True, spec=self.spec("other-report"))
        self.assertEqual("other-report", result["taskType"])

    def test_legacy_untyped_pending_is_not_discarded(self):
        turn = self.begin()
        self.stage(turn)
        path = self.root / "sessions" / f"{self.session}.json"
        current = load_session(self.session, self.root)
        del current["work"]["taskType"]
        atomic_write_json(path, current)
        checkpoint(self.root, self.session, turn, "complete")
        result = submit_review(self.root, self.session, turn, self.spec(observations=False))
        self.assertEqual("accepted", result["status"])
        self.assertEqual("borayeon-report", load_session(self.session, self.root)["work"]["taskType"])

    def test_malformed_stored_identity_not_echoed_or_silently_replaced(self):
        turn = self.begin()
        self.stage(turn)
        path = self.root / "sessions" / f"{self.session}.json"
        current = load_session(self.session, self.root)
        current["work"]["taskType"] = "PRIVATE RAW CONTENT / not slug"
        atomic_write_json(path, current)
        with self.assertRaises(ValueError) as caught:
            checkpoint(self.root, self.session, turn, "active", spec=self.spec())
        self.assertNotIn("PRIVATE RAW", str(caught.exception))

    def test_interrupted_first_review_cannot_be_relabelled(self):
        turn = self.begin()
        checkpoint(self.root, self.session, turn, "complete", learn=True)
        with patch("company_agent.learning._assess", side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError):
                submit_review(self.root, self.session, turn, self.spec())
        with self.assertRaisesRegex(ValueError, "use taskType 'borayeon-report'"):
            submit_review(self.root, self.session, turn, self.spec("other-report"))
        result = submit_review(self.root, self.session, turn, self.spec())
        self.assertEqual("deferred", result["status"])
        self.assertEqual("borayeon-report", load_session(self.session, self.root)["work"]["taskType"])


if __name__ == "__main__":
    unittest.main()
