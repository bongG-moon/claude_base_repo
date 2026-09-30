"""Learning receipts distinguish historical identity, deactivation and restoration."""
import hashlib
import os
import unittest
from unittest.mock import patch

import test_learning as fixtures
from company_agent import learning
from company_agent.frontmatter import load_markdown
from company_agent.memory import search_memory


class LearningReceiptTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.LearningTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def preference(self, body="Conclusion first."):
        return self.f.submit(self.f.turn(), self.f.spec([
            self.f.preference("explicit_correction", body)]))["changes"][0]

    def test_created_preference_receipt_identifies_owned_memory_and_undo_meaning(self):
        change = self.preference()
        path = self.f.root / "memory/items" / (change["memoryId"] + ".md")
        self.assertEqual("automatic_learning", change["historySource"])
        self.assertEqual("deactivate_preference", change["rollbackOperation"])
        self.assertFalse(change["rollbackRestoresPreviousContent"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), change["recordedAfterSha256"])
        self.assertFalse(change["currentRevisionChecked"])
        for key in ("beforeContent", "afterContent", "body", "targetPath"):
            self.assertNotIn(key, change)

    def test_preference_rollback_deactivates_latest_value_without_restoring_older_text(self):
        original = self.preference("Conclusion first.")
        latest = self.preference("Background first.")
        result = learning.rollback_change(self.f.root, latest["id"])
        self.assertEqual(original["memoryId"], result["memoryId"])
        self.assertEqual(("deactivate_preference", "preference_deactivated", True),
                         (result["operation"], result["effect"], result["changed"]))
        self.assertFalse(result["previousContentRestored"])
        path = self.f.root / "memory/items" / (result["memoryId"] + ".md")
        document = load_markdown(path)
        self.assertEqual("inactive", document.metadata["status"])
        self.assertEqual("Background first.", document.body.strip())
        self.assertEqual([], search_memory(self.f.root, "report"))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), result["resultSha256"])

    def test_repeated_rollback_does_not_claim_new_deactivation_or_current_revision_check(self):
        change = self.preference()
        learning.rollback_change(self.f.root, change["id"])
        result = learning.rollback_change(self.f.root, change["id"])
        self.assertEqual((False, "no_change"), (result["changed"], result["effect"]))
        self.assertEqual("deactivate_preference", result["operation"])
        self.assertFalse(result["previousContentRestored"])
        self.assertNotIn("resultSha256", result)

    def test_conflict_keeps_manual_edit_and_does_not_claim_restore(self):
        change = self.preference()
        path = self.f.root / "memory/items" / (change["memoryId"] + ".md")
        path.write_text(path.read_text(encoding="utf-8") + "\nHuman addition.\n", encoding="utf-8")
        before = path.read_bytes()
        result = learning.rollback_change(self.f.root, change["id"])
        self.assertEqual(("blocked_conflict", "conflict_preserved", False),
                         (result["status"], result["effect"], result["changed"]))
        self.assertFalse(result["previousContentRestored"])
        self.assertNotIn("resultSha256", result)
        self.assertEqual(before, path.read_bytes())

    def test_skill_rollback_reports_owned_checklist_restore_not_business_file_undo(self):
        path = self.f.skill()
        before = path.read_bytes()
        change = self.f.submit(self.f.turn(used=self.f.used(path), failure=1, verification="pass"),
                               self.f.spec([self.f.lesson()]))["changes"][0]
        self.assertEqual("restore_owned_checklist", change["rollbackOperation"])
        result = learning.rollback_change(self.f.root, change["id"])
        self.assertEqual("owned_checklist_restored", result["effect"])
        self.assertTrue(result["previousContentRestored"])
        self.assertEqual(before, path.read_bytes())
        self.assertNotIn("memoryId", result)

    def test_status_returns_recorded_hash_without_reading_target_or_claiming_unchanged(self):
        change = self.preference()
        path = self.f.root / "memory/items" / (change["memoryId"] + ".md")
        path.write_text(path.read_text(encoding="utf-8") + "\nLater human change.\n", encoding="utf-8")
        with patch.object(learning, "_read", wraps=learning._read) as reads:
            summary = learning.learning_status(self.f.root)["recentChanges"][-1]
        self.assertEqual(change["recordedAfterSha256"], summary["recordedAfterSha256"])
        self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(), summary["recordedAfterSha256"])
        self.assertFalse(summary["currentRevisionChecked"])
        self.assertFalse(any(call.args[0] == path for call in reads.call_args_list))

    def test_scope_is_reported_only_for_exact_configured_installation_root(self):
        for configured_scope, expected in (("User", "personal"), ("Project", "project"),
                                           ("Unknown", "not_observable")):
            with self.subTest(scope=configured_scope), patch.dict(os.environ, {
                    "COMPANY_AGENT_USER_STATE": str(self.f.root), "COMPANY_AGENT_SCOPE": configured_scope}):
                receipt = learning.learning_status(self.f.root)["storage"]
                self.assertEqual(expected, receipt["storageScope"])
                self.assertEqual(str(self.f.root.absolute()), receipt["stateRoot"])
        with patch.dict(os.environ, {"COMPANY_AGENT_USER_STATE": str(self.f.root.parent / "other"),
                                    "COMPANY_AGENT_SCOPE": "User"}):
            self.assertEqual("not_observable", learning.learning_status(self.f.root)["storage"]["storageScope"])
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual("not_observable", learning.learning_status(self.f.root)["storage"]["storageScope"])
        self.assertFalse(self.f.root.exists())

    def test_current_submit_preserves_runtime_root_and_provides_storage_receipt(self):
        turn = self.f.turn()
        with patch.dict(os.environ, {"COMPANY_AGENT_USER_STATE": str(self.f.root), "COMPANY_AGENT_SCOPE": "Project"}):
            result = learning.submit_learning(self.f.root, self.f.session, turn,
                                             self.f.spec([self.f.preference("explicit_correction")]))
        self.assertEqual("project", result["storage"]["storageScope"])
        self.assertEqual(str(self.f.root.absolute()), result["storage"]["stateRoot"])
        self.assertEqual(1, result["appliedCount"])
        self.assertFalse((self.f.root / "project-scopes").exists())

    def test_schema_does_not_accept_arbitrary_scope_or_existing_manual_target(self):
        for field, value in (("storageScope", "project"), ("targetMemoryId", "memory.preference.explicit"),
                             ("targetRoot", "arbitrary")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                learning._validate(self.f.spec([{**self.f.preference("explicit_correction"), field: value}]))
        self.assertFalse(self.f.root.exists())


if __name__ == "__main__":
    unittest.main()
