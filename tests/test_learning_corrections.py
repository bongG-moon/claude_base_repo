"""Corrections update current owned state; history is not an activation receipt."""
import unittest
from unittest.mock import patch

import test_learning as fixtures
from company_agent import learning
from company_agent.memory import search_memory
from company_agent.paths import atomic_write_json


class LearningCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.LearningTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def preference(self, body):
        return self.f.submit(self.f.turn(), self.f.spec([self.f.preference("explicit_correction", body)]))

    def lesson(self, path, body, key="report-language"):
        observation = {**self.f.lesson("explicit_correction", body), "key": key}
        return self.f.submit(self.f.turn(used=self.f.used(path)), self.f.spec([observation]))

    def test_preference_a_b_a_reactivates_actual_memory(self):
        first = self.preference("Conclusion first.")
        self.preference("Background first.")
        third = self.preference("Conclusion first.")
        self.assertEqual("active", third["changes"][0]["status"])
        self.assertNotEqual(first["changes"][0]["id"], third["changes"][0]["id"])
        memories = search_memory(self.f.root, "report")
        self.assertEqual(["Conclusion first."], [m["body"] for m in memories])
        self.assertEqual(3, memories[0]["revision"])
        self.preference("Conclusion first.")
        self.assertEqual(3, search_memory(self.f.root, "report")[0]["revision"])

    def test_stale_candidate_cannot_overwrite_manual_preference_edit(self):
        self.preference("Conclusion first.")
        self.preference("Background first.")
        path = next((self.f.root / "memory/items").glob("*.md"))
        path.write_text(path.read_text(encoding="utf-8") + "\nManual addition.\n", encoding="utf-8")
        before = path.read_bytes()
        result = self.preference("Conclusion first.")
        self.assertEqual("deferred", result["changes"][0]["status"])
        self.assertEqual(before, path.read_bytes())

    def test_superseded_repeated_choice_needs_fresh_independent_evidence(self):
        for _ in range(2):
            self.f.submit(self.f.turn(), self.f.spec([self.f.preference("repeated_choice", "Conclusion first.")]))
        self.preference("Background first.")
        result = self.f.submit(self.f.turn(), self.f.spec([self.f.preference("repeated_choice", "Conclusion first.")]))
        self.assertEqual("observing", result["changes"][0]["status"])
        self.assertEqual("Background first.", search_memory(self.f.root, "report")[0]["body"])
        result = self.f.submit(self.f.turn(), self.f.spec([self.f.preference("repeated_choice", "Conclusion first.")]))
        self.assertEqual("active", result["changes"][0]["status"])
        self.assertEqual("Conclusion first.", search_memory(self.f.root, "report")[0]["body"])

    def test_skill_correction_replaces_same_key_and_preserves_other_lessons(self):
        path = self.f.skill()
        self.lesson(path, "Write every report in Korean.")
        self.lesson(path, "Check the reporting period.", key="report-period")
        self.lesson(path, "Write every report in English.")
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("Write every report in Korean.", text)
        self.assertIn("Write every report in English.", text)
        self.assertIn("Check the reporting period.", text)
        self.assertEqual(2, len(learning._checklist_lines(learning._block(text))))
        self.assertIn("Keep original content.", text)

    def test_skill_a_b_a_and_rollback_restore_exact_prior_owned_section(self):
        path = self.f.skill()
        self.lesson(path, "Write every report in Korean.")
        self.lesson(path, "Write every report in English.")
        before = path.read_bytes()
        third = self.lesson(path, "Write every report in Korean.")
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("Write every report in English.", text)
        self.assertEqual(1, text.count("Write every report in Korean."))
        self.assertEqual("rolled_back", learning.rollback_change(self.f.root, third["changes"][0]["id"])["status"])
        self.assertEqual(before, path.read_bytes())

    def test_correction_preserves_manual_outer_text_but_refuses_owned_edits(self):
        path = self.f.skill()
        self.lesson(path, "Write every report in Korean.")
        path.write_text(path.read_text(encoding="utf-8").replace("Keep original content.", "Human instructions."), encoding="utf-8")
        changed = self.lesson(path, "Write every report in English.")
        self.assertEqual("active", changed["changes"][0]["status"])
        self.assertIn("Human instructions.", path.read_text(encoding="utf-8"))
        path.write_text(path.read_text(encoding="utf-8").replace("Write every report in English.", "Human checklist edit."), encoding="utf-8")
        before = path.read_bytes()
        result = self.lesson(path, "Write every report in Korean.")
        self.assertEqual("deferred", result["changes"][0]["status"])
        self.assertEqual(before, path.read_bytes())

    def legacy_conflicting_skill(self):
        """Recreate the pre-fix append format with no per-entry key metadata."""
        path = self.f.skill()
        self.lesson(path, "Write every report in Korean.")
        first_text = learning._read(path, self.f.root)
        self.lesson(path, "Write every report in English.")
        data = learning._load(self.f.root)
        active = data["changes"][-1]
        current = learning._read(path, self.f.root)
        legacy_block = active["beforeBlock"].replace(
            "\n\n" + learning.END,
            "\n" + learning._checklist_lines(active["afterBlock"])[0] + "\n\n" + learning.END)
        legacy_text = current.replace(active["afterBlock"], legacy_block)
        path.write_text(legacy_text, encoding="utf-8", newline="\n")
        active["afterBlock"] = legacy_block
        active["afterSha256"] = learning._hash(legacy_text)
        self.assertEqual(learning._hash(first_text), active["beforeSha256"])
        for change in data["changes"]:
            change.pop("skillEntryKeys", None)
        atomic_write_json(self.f.root / "learning/state.json", data)
        return path

    def test_legacy_conflicting_same_key_entries_are_replaced_together(self):
        path = self.legacy_conflicting_skill()
        result = self.lesson(path, "Write every report in Korean.")
        self.assertEqual("active", result["changes"][0]["status"])
        text = path.read_text(encoding="utf-8")
        self.assertEqual(1, len(learning._checklist_lines(learning._block(text))))
        self.assertIn("Write every report in Korean.", text)
        self.assertNotIn("Write every report in English.", text)

    def test_legacy_unknown_keys_defer_without_discarding_existing_lessons(self):
        path = self.legacy_conflicting_skill()
        data = learning._load(self.f.root)
        data["changes"] = data["changes"][-1:]
        atomic_write_json(self.f.root / "learning/state.json", data)
        before = path.read_bytes()
        result = self.lesson(path, "Write every report in German.")
        self.assertEqual("deferred", result["changes"][0]["status"])
        self.assertIn("identity is unavailable", result["changes"][0]["reason"])
        self.assertEqual(before, path.read_bytes())

    def test_entry_keys_survive_history_trimming(self):
        path = self.f.skill()
        with patch.object(learning, "MAX_CHANGES", 1):
            self.lesson(path, "Write every report in Korean.")
            self.lesson(path, "Check the reporting period.", key="report-period")
            self.assertEqual(1, len(learning._load(self.f.root)["changes"]))
            self.lesson(path, "Write every report in English.")
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("Write every report in Korean.", text)
        self.assertIn("Write every report in English.", text)
        self.assertIn("Check the reporting period.", text)


if __name__ == "__main__":
    unittest.main()
