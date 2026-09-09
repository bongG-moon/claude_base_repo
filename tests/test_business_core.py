from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))
from company_agent import business, business_files, business_safety
from company_agent.cli import main
from company_agent.learning import submit_review
from company_agent.paths import atomic_write_json
from company_agent.state import begin_turn, load_session, record_activity, mark_verified


class BusinessCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.folder = self.root / "업무 — 자료"
        self.folder.mkdir()
        (self.folder / "보고서.txt").write_text("검증 자료", encoding="utf-8")
        (self.folder / "sample.exe").write_bytes(b"do not execute")

    def plan(self):
        return business_files.create_plan(self.state, self.folder)

    def args(self, action, **kwargs):
        return argparse.Namespace(business_action=action, state_root=str(self.state), **kwargs)

    def test_preview_does_not_move_and_excludes_executable(self):
        result = self.plan()
        self.assertEqual(1, len(result["operations"]))
        self.assertTrue((self.folder / "보고서.txt").exists())
        self.assertFalse((self.folder / "문서").exists())

    def test_cancel_no_mutations(self):
        plan = self.plan()
        with patch.object(business_files, "confirm_action", return_value=False):
            result = business_files.run_plan(self.state, plan["planId"])
        self.assertEqual("cancelled", result["status"])
        self.assertTrue((self.folder / "보고서.txt").exists())

    def test_move_and_explicit_undo(self):
        plan = self.plan()
        with patch.object(business_files, "confirm_action", return_value=True):
            result = business_files.run_plan(self.state, plan["planId"])
            self.assertEqual(1, result["changedCount"])
            self.assertTrue((self.folder / "문서" / "보고서.txt").is_file())
            restored = business_files.run_plan(self.state, plan["planId"], undo=True)
        self.assertEqual("undone", restored["status"])
        self.assertTrue((self.folder / "보고서.txt").is_file())

    def test_changed_file_is_not_moved(self):
        plan = self.plan()
        (self.folder / "보고서.txt").write_text("changed", encoding="utf-8")
        with patch.object(business_files, "confirm_action", return_value=True):
            result = business_files.run_plan(self.state, plan["planId"])
        self.assertEqual("partial", result["status"])
        self.assertEqual(0, result["changedCount"])

    def test_destination_is_never_overwritten(self):
        plan = self.plan()
        dest = self.folder / "문서" / "보고서.txt"
        dest.parent.mkdir()
        dest.write_text("keep", encoding="utf-8")
        with patch.object(business_files, "confirm_action", return_value=True):
            result = business_files.run_plan(self.state, plan["planId"])
        self.assertEqual("partial", result["status"])
        self.assertEqual("keep", dest.read_text(encoding="utf-8"))

    def test_plan_cannot_escape_selected_folder(self):
        plan = self.plan()
        plan["operations"][0]["destination"] = "../../outside.txt"
        path = business_files._job(self.state, plan["planId"])
        atomic_write_json(path, plan)
        with patch.object(business_files, "confirm_action") as confirm:
            with self.assertRaises(ValueError):
                business_files.run_plan(self.state, plan["planId"])
            confirm.assert_not_called()

    def test_same_plan_not_rerun(self):
        plan = self.plan()
        with patch.object(business_files, "confirm_action", return_value=True):
            business_files.run_plan(self.state, plan["planId"])
            with self.assertRaises(ValueError):
                business_files.run_plan(self.state, plan["planId"])

    def test_crash_between_move_and_receipt_can_be_reconciled_for_undo(self):
        plan = self.plan()
        original = Path.rename
        def interrupted(source, dest):
            original(source, dest)
            raise KeyboardInterrupt("synthetic interruption")
        with patch.object(business_files, "confirm_action", return_value=True), patch.object(Path, "rename", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                business_files.run_plan(self.state, plan["planId"])
        self.assertFalse((self.folder / "보고서.txt").exists())
        with patch.object(business_files, "confirm_action", return_value=True):
            result = business_files.run_plan(self.state, plan["planId"], undo=True)
        self.assertEqual("undone", result["status"])
        self.assertTrue((self.folder / "보고서.txt").exists())

    def test_document_text_drm_is_not_a_protection_signal(self):
        self.assertEqual("", business_safety.protection_notice({"tool_response": {"body": "DRM 도입 계획"}}))
        self.assertEqual("", business_safety.protection_notice({"tool_input": {"command": "review drm docs"}}))

    def test_malformed_code_does_not_crash(self):
        for code in ({}, [], None):
            self.assertEqual("", business_safety.protection_notice({"tool_response": {"code": code}}))

    def test_partial_nested_code_is_detected_and_raw_text_not_echoed(self):
        payload = {"tool_response": {"items": [{"body": "PRIVATE"}, {"code": "protection_blocked"}]}}
        notice = business_safety.protection_notice(payload)
        self.assertIn("첨부 내용은 제외", notice)
        self.assertNotIn("PRIVATE", notice)

    def test_large_korean_mail_result_preserves_restriction_signal(self):
        response = json.dumps({"items": [{"body": "한글본문" * 4000}, {"code": "protection_blocked"}]}, ensure_ascii=True)
        self.assertGreater(len(response), 24000)
        self.assertTrue(business_safety.protection_notice({"tool_response": {"stdout": response}}))

    def test_concurrent_plan_execution_is_rejected_before_approval(self):
        plan = self.plan()
        with business_files._plan_lock(self.state, plan["planId"]), patch.object(business_files, "confirm_action") as confirm:
            with self.assertRaises(ValueError):
                business_files.run_plan(self.state, plan["planId"])
            confirm.assert_not_called()

    def test_confirmation_does_not_truncate_hidden_operations(self):
        from subprocess import CompletedProcess
        details = "full operation list\n" * 10000
        with patch.object(business_safety, "windows_powershell", return_value=Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")), patch.object(business_safety.subprocess, "run", return_value=CompletedProcess([], 0, '{"approved":true}')) as process:
            self.assertTrue(business_safety.confirm_action("confirm", details))
        self.assertEqual(details, json.loads(process.call_args.kwargs["input"])["details"])

    def test_exception_text_not_exposed(self):
        result = business_safety.failure_result(PermissionError("PRIVATE ADDRESS access denied"))
        self.assertEqual("permission_denied", result["code"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_mail_body_json_flag_cannot_skip_actual_user_confirmation(self):
        spec = self.root / "mail.json"
        atomic_write_json(spec, {"include_body": True, "body_access_approved": True, "account_smtp": "person@example.test"})
        with patch.object(business, "confirm_action", return_value=False), patch("company_agent.business_mail.read_mail") as read:
            result = business.dispatch(self.args("mail-read", spec=str(spec)))
            read.assert_not_called()
        self.assertEqual("cancelled", result["status"])

    def test_mail_body_approval_inserted_only_after_user_confirmation(self):
        spec = self.root / "mail.json"
        atomic_write_json(spec, {"include_body": True, "account_smtp": "person@example.test"})
        with patch.object(business, "confirm_action", return_value=True), patch("company_agent.business_mail.read_mail", return_value={"ok": True}) as read:
            business.dispatch(self.args("mail-read", spec=str(spec)))
        self.assertIs(True, read.call_args.args[0]["body_access_approved"])

    def test_known_protected_source_is_stopped_before_adapter(self):
        spec = self.root / "mail.json"
        atomic_write_json(spec, {"include_body": True, "protection": "protected"})
        with patch("company_agent.business_mail.read_mail") as read:
            result = business.dispatch(self.args("mail-read", spec=str(spec)))
            read.assert_not_called()
        self.assertEqual("protection_blocked", result["code"])

    def test_protection_turn_cannot_write_free_text_learning(self):
        session = begin_turn("business-test", "MEDIUM", False, [], self.state)
        record_activity({"session_id": "business-test", "tool_name": "mcp__test__read",
                         "tool_response": {"code": "protection_blocked"}}, self.state)
        self.assertTrue(load_session("business-test", self.state)["protectionRestricted"])
        mark_verified("business-test", "pass", "PRIVATE_SOURCE_947", self.state)
        result = submit_review(self.state, "business-test", session["turnId"], {
            "schemaVersion": 1, "taskType": "mail-summary", "outcome": "partial", "summary": "PRIVATE_SOURCE_947",
            "observations": [{"kind": "preference", "key": "report-layout", "signal": "repeated_choice",
                              "title": "Private title", "body": "PRIVATE_SOURCE_947"}], "evaluations": []})
        self.assertEqual([], result["changes"])
        for file in self.state.rglob("*.json"):
            self.assertNotIn("PRIVATE_SOURCE_947", file.read_text(encoding="utf-8"))

    def test_cli_json_is_cp949_safe(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["business", "files-plan", "--state-root", str(self.state), "--folder", str(self.folder)])
        self.assertEqual(0, result)
        output.getvalue().encode("cp949")
        self.assertTrue(json.loads(output.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
