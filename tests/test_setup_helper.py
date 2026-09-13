from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"))
from company_agent import setup_helper as helper


class SetupHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.spec = {"name": "report-setup", "title": "보고서 설정",
                     "steps": [{"id": "report-style", "label": "보고서 형식", "kind": "choice",
                                "required": True, "choices": ["간단히", "자세히"]},
                               {"id": "report-folder", "label": "자료 폴더", "kind": "path", "required": True}]}

    def create(self):
        return Path(helper.create_setup_helper(self.root, self.spec)["directory"])

    def run_input(self, directory, answers):
        entries = iter(answers)
        with mock.patch.object(helper.sys, "platform", "win32"):
            return helper.run_helper(directory, input_fn=lambda _: next(entries), output_fn=lambda _: None)

    def test_creation_standalone_and_no_overwrite(self):
        directory = self.create()
        self.assertEqual(helper.validate_spec(self.spec), json.loads((directory / "spec.json").read_text(encoding="utf-8")))
        self.assertIn("def main()", (directory / "helper.py").read_text(encoding="utf-8"))
        with self.assertRaises(FileExistsError):
            self.create()

    def test_strict_schema_rejects_code_secrets_duplicates_and_path_names(self):
        invalid = []
        for field in ("command", "code", "imports", "network"):
            case = copy.deepcopy(self.spec)
            case[field] = "arbitrary"
            invalid.append(case)
        for field in ("api-key", "password", "TOKEN", "private-key", "credential", "../escape"):
            case = copy.deepcopy(self.spec)
            case["steps"][0]["id"] = field
            invalid.append(case)
        case = copy.deepcopy(self.spec)
        case["steps"][0]["label"] = "비밀번호"
        invalid.append(case)
        case = copy.deepcopy(self.spec)
        case["steps"][1]["id"] = "report-style"
        invalid.append(case)
        case = copy.deepcopy(self.spec)
        case["steps"][1]["required"] = "true"
        invalid.append(case)
        for case in invalid:
            with self.subTest(case=case), self.assertRaises(ValueError):
                helper.create_setup_helper(self.root, case)
        self.assertFalse((self.root / "setup-helpers").exists())

    def test_retry_save_resume_explicit_change_and_cancel_preserves(self):
        directory = self.create()
        result = self.run_input(directory, ["9", "1", "relative", str(self.root), "1"])
        self.assertEqual("saved", result["status"])
        self.assertEqual("간단히", json.loads((directory / "answers.json").read_text(encoding="utf-8"))["report-style"])
        result = self.run_input(directory, ["2", "2", "1", "1"])
        self.assertEqual("saved", result["status"])
        before = (directory / "answers.json").read_bytes()
        self.assertIn("자세히", before.decode("utf-8"))
        result = self.run_input(directory, ["/cancel"])
        self.assertEqual("cancelled", result["status"])
        self.assertEqual(before, (directory / "answers.json").read_bytes())

    def test_cancel_eof_and_unconfirmed_answers_never_saved(self):
        directory = self.create()
        result = self.run_input(directory, ["1", str(self.root), "2"])
        self.assertEqual("cancelled", result["status"])
        self.assertFalse((directory / "answers.json").exists())
        with mock.patch.object(helper.sys, "platform", "win32"):
            result = helper.run_helper(directory, input_fn=mock.Mock(side_effect=EOFError), output_fn=lambda _: None)
        self.assertEqual("cancelled", result["status"])
        self.assertFalse((directory / "answers.json").exists())

    def test_runtime_preflight_and_tampered_spec(self):
        directory = self.create()
        with mock.patch.object(helper.sys, "platform", "linux"), self.assertRaises(ValueError):
            helper.run_helper(directory, check=True)
        with mock.patch.object(helper.sys, "version_info", (3, 10)), self.assertRaises(ValueError):
            helper.run_helper(directory, check=True)
        with mock.patch.object(helper.sys, "platform", "win32"):
            self.assertEqual("ready", helper.run_helper(directory, check=True)["status"])
        # Write fixtures explicitly; production never accepts executable spec properties.
        (directory / "spec.json").write_text('{"command":"launch"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            helper.run_helper(directory, check=True)

    def test_sensitive_values_and_unc_paths_rejected(self):
        step = {"kind": "text", "required": True}
        for value in ("sk-" + "a" * 25, "Bearer abcdef", "password=hello", "hello\x1b[0m"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                helper._answer(step, value)
        with self.assertRaises(ValueError):
            helper._safe_path(Path(r"\\server\share\folder"))

    def test_reparse_guard(self):
        fake = mock.Mock(st_mode=0, st_file_attributes=0x400)
        with mock.patch.object(Path, "lstat", return_value=fake), self.assertRaises(ValueError):
            helper.create_setup_helper(self.root, self.spec)

    def test_invalid_previous_folder_can_be_reentered_and_cancel_preserves_file(self):
        directory = self.create()
        previous = {"report-style": "간단히", "report-folder": str(self.root / "deleted-folder")}
        result_file = directory / "answers.json"
        result_file.write_text(json.dumps(previous), encoding="utf-8")
        before = result_file.read_bytes()
        with mock.patch.object(helper.sys, "platform", "win32"):
            check = helper.run_helper(directory, check=True)
        self.assertEqual("ready_with_reentry", check["status"])
        self.assertEqual(["report-folder"], check["reentryFields"])
        self.assertEqual(before, result_file.read_bytes())
        result = self.run_input(directory, ["1", "/cancel"])
        self.assertEqual("cancelled", result["status"])
        self.assertEqual(before, result_file.read_bytes())
        result = self.run_input(directory, ["1", str(self.root), "1"])
        self.assertEqual("saved", result["status"])
        self.assertEqual(str(self.root), json.loads(result_file.read_text(encoding="utf-8"))["report-folder"])

    def test_secret_previous_value_never_displayed_and_requires_reentry(self):
        directory = self.create()
        secret = "Bearer confidential-value"
        (directory / "answers.json").write_text(json.dumps({"report-style": secret}), encoding="utf-8")
        output = []
        entries = iter(["2", str(self.root), "1"])
        with mock.patch.object(helper.sys, "platform", "win32"):
            check = helper.run_helper(directory, check=True)
            result = helper.run_helper(directory, input_fn=lambda _: next(entries), output_fn=output.append)
        self.assertEqual(["report-style"], check["reentryFields"])
        self.assertNotIn(secret, json.dumps(check))
        self.assertNotIn(secret, "\n".join(output))
        self.assertEqual("saved", result["status"])
        self.assertEqual("자세히", json.loads((directory / "answers.json").read_text(encoding="utf-8"))["report-style"])

    def test_unselectable_sensitive_choices_rejected_at_creation(self):
        for value in ("token", "password", "비밀번호", "Bearer confidential-value", "ghp_" + "a" * 20):
            with self.subTest(value=value):
                spec = copy.deepcopy(self.spec)
                spec["steps"][0]["choices"][0] = value
                with self.assertRaises(ValueError):
                    helper.create_setup_helper(self.root, spec)
        self.assertFalse((self.root / "setup-helpers").exists())

    def test_real_standalone_check_and_scripted_input(self):
        directory = self.create()
        command = [sys.executable, str(directory / "helper.py")]
        checked = subprocess.run(command + ["--check"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        if sys.platform != "win32":
            self.assertEqual(1, checked.returncode)
            self.assertIn('"status": "error"', checked.stdout)
            return
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        self.assertIn('"status": "ready"', checked.stdout)
        entered = subprocess.run(command, input="1\n" + str(self.root) + "\n1\n", capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=20)
        self.assertEqual(0, entered.returncode, entered.stdout + entered.stderr)
        self.assertIn("답변을 저장했습니다", entered.stdout)
        self.assertNotIn('"status": "saved"', entered.stdout)
        self.assertTrue((directory / "answers.json").exists())
        cancelled = subprocess.run(command, input="/cancel\n", capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=20)
        self.assertEqual(2, cancelled.returncode)
        self.assertIn("저장하지 않고 종료했습니다", cancelled.stdout)


if __name__ == "__main__":
    unittest.main()
