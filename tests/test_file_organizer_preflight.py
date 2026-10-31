"""Synthetic parent-path conflicts before planning, approval and individual moves."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin/scripts"))
from company_agent import business_files

SPEC = importlib.util.spec_from_file_location("standalone_organizer", ROOT / "standalone-skills/file-organizer/scripts/organize.py")
organizer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(organizer)


class OrganizerFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "files"
        self.folder.mkdir()
        for name in ("a.txt", "b.png", "c.csv"):
            (self.folder / name).write_bytes(("synthetic " + name).encode("utf-8"))
        self.original = self.hashes()

    def hashes(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.folder.iterdir() if p.is_file() and p.name != "이미지"}

    def block(self):
        (self.folder / "이미지").write_bytes(b"regular file")

    def assert_unchanged(self):
        self.assertEqual(self.original, self.hashes())
        self.assertFalse((self.folder / "문서").exists())
        self.assertFalse((self.folder / "표자료").exists())


class StandalonePreflightTests(OrganizerFixture):
    def test_plan_marks_parent_conflict_and_blocks_other_moves(self):
        self.block()
        plan = organizer.plan(self.folder)
        self.assertEqual(["b.png"], [row["name"] for row in plan["blocked"]])
        self.assertIn("폴더가 아닙니다", plan["blocked"][0]["reason"])
        result = organizer.execute(plan, self.root / "receipt.json")
        self.assertEqual(([], "preflight", 2), (result["moves"], result["phase"], result["notAttemptedCount"]))
        self.assert_unchanged()

    def test_parent_changes_after_plan_before_first_move(self):
        plan = organizer.plan(self.folder)
        plan.pop("blocked")  # Previously saved plans do not have this field.
        self.block()
        with patch.object(organizer, "move_one") as move:
            result = organizer.execute(plan, self.root / "receipt.json")
        move.assert_not_called()
        self.assertEqual(["b.png"], [row["name"] for row in result["failures"]])
        self.assertEqual(2, result["notAttemptedCount"])
        self.assert_unchanged()

    def test_destination_appears_after_plan_before_first_move(self):
        plan = organizer.plan(self.folder)
        destination = self.folder / "이미지/b.png"
        destination.parent.mkdir()
        destination.write_bytes(b"keep")
        result = organizer.execute(plan, self.root / "receipt.json")
        self.assertEqual([], result["moves"])
        self.assertEqual(b"keep", destination.read_bytes())
        self.assert_unchanged()

    def test_execution_parent_change_stops_and_receipt_undo_restores(self):
        plan = organizer.plan(self.folder)
        original_move = organizer.move_one
        def changed_after_first(source, destination, expected):
            original_move(source, destination, expected)
            if source.name == "a.txt":
                self.block()
        with patch.object(organizer, "move_one", side_effect=changed_after_first):
            result = organizer.execute(plan, self.root / "receipt.json")
        self.assertEqual((1, 1, 1, "execution"), (len(result["moves"]), len(result["failures"]), result["notAttemptedCount"], result["phase"]))
        self.assertEqual(result, json.loads((self.root / "receipt.json").read_text(encoding="utf-8")))
        undone = organizer.execute(result, self.root / "undo.json", undo=True)
        self.assertEqual((1, [], 0), (len(undone["moves"]), undone["failures"], undone["notAttemptedCount"]))
        self.assertEqual(self.original, self.hashes())

    def test_blocked_plan_requires_new_plan_even_if_conflict_removed(self):
        self.block()
        plan = organizer.plan(self.folder)
        (self.folder / "이미지").unlink()
        result = organizer.execute(plan, self.root / "receipt.json")
        self.assertEqual([], result["moves"])
        self.assert_unchanged()


@unittest.skipUnless(os.name == "nt", "Harness execution preserves Windows no-overwrite rename semantics")
class HarnessPreflightTests(OrganizerFixture):
    def make_plan(self):
        return business_files.create_plan(self.root / "state", self.folder)

    def run_plan(self, plan, undo=False):
        return business_files.run_plan(self.root / "state", plan["planId"], undo=undo)

    def test_plan_marks_parent_conflict_without_approval_or_moves(self):
        self.block()
        plan = self.make_plan()
        self.assertEqual("destination_parent_not_directory", plan["blocked"][0]["code"])
        with patch.object(business_files, "confirm_action") as confirm:
            result = self.run_plan(plan)
        confirm.assert_not_called()
        self.assertEqual((0, "preflight", 2), (result["changedCount"], result["phase"], result["notAttemptedCount"]))
        self.assert_unchanged()

    def test_parent_changes_after_plan_before_approval(self):
        plan = self.make_plan()
        self.block()
        with patch.object(business_files, "confirm_action") as confirm:
            result = self.run_plan(plan)
        confirm.assert_not_called()
        self.assertEqual((0, 1, 2), (result["changedCount"], len(result["failures"]), result["notAttemptedCount"]))
        self.assert_unchanged()

    def test_parent_changes_while_existing_approval_is_open(self):
        plan = self.make_plan()
        def approve(*args):
            self.block()
            return True
        with patch.object(business_files, "confirm_action", side_effect=approve) as confirm:
            result = self.run_plan(plan)
        self.assertEqual(1, confirm.call_count)
        self.assertEqual((0, "preflight"), (result["changedCount"], result["phase"]))
        self.assert_unchanged()

    def test_execution_parent_change_stops_and_undo_restores(self):
        plan = self.make_plan()
        rename = Path.rename
        def changed_after_first(source, destination):
            result = rename(source, destination)
            if source.name == "a.txt":
                self.block()
            return result
        with patch.object(business_files, "confirm_action", return_value=True), patch.object(Path, "rename", changed_after_first):
            result = self.run_plan(plan)
        self.assertEqual((1, 1, 1, "execution"), (result["changedCount"], len(result["failures"]), result["notAttemptedCount"], result["phase"]))
        saved = json.loads(business_files._job(self.root / "state", plan["planId"]).read_text(encoding="utf-8"))
        self.assertEqual(["a.txt"], [op["source"] for op in saved["completed"]])
        with patch.object(business_files, "confirm_action", return_value=True):
            undone = self.run_plan(plan, undo=True)
        self.assertEqual((1, [], 0), (undone["changedCount"], undone["failures"], undone["notAttemptedCount"]))
        self.assertEqual(self.original, self.hashes())


if __name__ == "__main__":
    unittest.main()
