"""Lab tooling checks use only fresh temporary files, never real Claude profiles."""
from collections import Counter
from email import policy
from email.parser import BytesParser
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


REPO = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


builder = module("lab_builder", REPO / "scripts" / "build-test-lab.py")
lab = module("lab_checks", REPO / "scripts" / "test-lab" / "lab.py")


class TestLab(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="company-agent-lab-test-")
        self.root = Path(self.tmp.name) / "Lab 공백 한글"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def fixtures(self):
        work = self.root / "workspace"
        builder.make_fixtures(work)
        organize = work / "01-folder-organize"
        builder.write_json(self.root / "operator" / "baseline.json", {
            "organizer": {p.relative_to(organize).as_posix(): lab.sha(p) for p in organize.rglob("*") if p.is_file()},
            "inputs": {p.relative_to(work).as_posix(): lab.sha(p) for p in work.rglob("*") if p.is_file() and not p.is_relative_to(organize)},
        })
        return work

    def test_original_locations_and_content(self):
        work = self.fixtures()
        result = lab.fixture_check(self.root)
        self.assertTrue(result["originalLocations"])
        self.assertTrue(result["sameContentsAndCount"])
        self.assertEqual(result["differentInputFiles"], [])
        self.assertFalse((work / "CA_TEST_NO_SUCH_FILE_20260910_7F9A.txt").exists())
        self.assertFalse((self.root / "personal-state").exists())
        self.assertFalse((work / ".claude").exists())

    def test_move_undo_and_changed_data_are_distinct(self):
        work = self.fixtures()
        folder = work / "01-folder-organize"
        original = folder / "안내.txt"
        destination = folder / "문서" / original.name
        destination.parent.mkdir()
        original.rename(destination)
        moved = lab.fixture_check(self.root)
        self.assertFalse(moved["originalLocations"])
        self.assertTrue(moved["sameContentsAndCount"])
        destination.rename(original)
        self.assertTrue(lab.fixture_check(self.root)["originalLocations"])
        original.write_text("Changed fixture", encoding="utf-8")
        changed = lab.fixture_check(self.root)
        self.assertFalse(changed["sameContentsAndCount"])

    def test_missing_or_extra_duplicate_detected(self):
        work = self.fixtures()
        folder = work / "01-folder-organize"
        (folder / "extra.txt").write_bytes((folder / "안내.txt").read_bytes())
        self.assertFalse(lab.fixture_check(self.root)["sameContentsAndCount"])

    def test_modified_input_detected(self):
        work = self.fixtures()
        (work / "02-report-input" / "monthly-results.json").write_text("{}", encoding="utf-8")
        self.assertEqual(lab.fixture_check(self.root)["differentInputFiles"], ["02-report-input/monthly-results.json"])

    def test_eml_samples_are_parseable_synthetic_files(self):
        work = self.fixtures()
        messages = [BytesParser(policy=policy.default).parsebytes(p.read_bytes()) for p in (work / "04-mail-samples").glob("*.eml")]
        self.assertEqual(len(messages), 3)
        self.assertEqual(sum("CA-PILOT-ONLY" in str(m["Subject"]) for m in messages), 2)
        self.assertTrue(all("example.invalid" in m["To"] for m in messages))
        self.assertEqual(sum(len(list(m.iter_attachments())) for m in messages), 1)
        self.assertTrue(all("가상" in m.get_body(preferencelist=("plain",)).get_content() for m in messages))

    def test_all_questions_and_lab_variant(self):
        cases = builder.lab_cases((REPO / "docs" / "VALIDATION_CHAT_SET.md").read_text(encoding="utf-8-sig"))
        self.assertEqual(len(cases), 35)
        self.assertEqual(sum(len(c["prompts"]) for c in cases), 55)
        self.assertTrue(all(c["prompts"] for c in cases))
        self.assertTrue(all(len(c["stages"]) == len(c["prompts"]) for c in cases))
        self.assertIn("새 대화", " ".join(cases[4]["stages"]))
        self.assertIn("새 폴더나 파일을 만들지 말고", cases[8]["prompts"][0])
        self.assertNotIn("CSV", " ".join(cases[8]["prompts"]))
        self.assertIn("07-project-factory", cases[21]["prompts"][0])
        self.assertEqual(cases[-1]["id"], "L01")

    def test_invalid_case_set_rejected(self):
        with self.assertRaises(ValueError):
            builder.lab_cases("## T01 Only one\n```text\nHello\n```\n")

    def test_existing_directory_not_overwritten(self):
        marker = self.root / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            builder.build(self.root, self.root / "nonexistent.zip")
        self.assertEqual(marker.read_text(), "keep")

    def test_package_tampering_detected(self):
        archive = self.root / "installer" / "bundle.zip"
        archive.parent.mkdir()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("deploy/setup.ps1", "original")
        (archive.parent / "package" / "deploy").mkdir(parents=True)
        script = archive.parent / "package" / "deploy" / "setup.ps1"
        script.write_text("original", encoding="utf-8")
        meta = {"bundleName": archive.name, "bundleSha256": lab.sha(archive)}
        self.assertTrue(lab.package_check(self.root, meta)["ok"])
        script.write_text("changed", encoding="utf-8")
        self.assertFalse(lab.package_check(self.root, meta)["ok"])
        archive.write_bytes(b"changed archive")
        self.assertFalse(lab.package_check(self.root, meta)["ok"])

    def fake_registration(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        local = self.root / "fake-local"
        config = self.root / "fake-profile" / ".claude"
        key = hashlib.sha256(str(workspace).upper().encode("utf-8")).hexdigest()[:16]
        record_path = local / "CompanyAgent" / "installations" / "projects" / key / "company-agent-install.json"
        record = {"schemaVersion": 1, "scope": "Project", "nativeClaudeScope": "local",
                  "projectRoot": str(workspace), "userStateRoot": str(self.root / "personal-state"),
                  "coreVersion": "1.3.0", "claudeConfigRoot": str(config), "claudeConfigDirOverride": False}
        builder.write_json(record_path, record)
        builder.write_json(workspace / ".claude" / "settings.local.json", {"enabledPlugins": {"company-agent@company-agent-local": True}})
        installed = self.root / "fake-plugin"
        builder.write(installed / "hooks" / "hooks.json", "{}")
        inventory = {"plugins": {"company-agent@company-agent-local": [{"scope": "local", "projectPath": str(workspace), "version": "1.3.0", "installPath": str(installed)}]}}
        builder.write_json(config / "plugins" / "installed_plugins.json", inventory)
        return local, config, record_path, record

    @patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": ""})
    def test_local_native_scope_and_isolated_state_required(self):
        local, config, record_path, record = self.fake_registration()
        self.assertTrue(lab.registration_check(self.root, {"coreVersion": "1.3.0"}, local, config)["ready"])
        record["userStateRoot"] = str(self.root / "real-personal-state")
        record_path.write_text(json.dumps(record), encoding="utf-8")
        self.assertFalse(lab.registration_check(self.root, {"coreVersion": "1.3.0"}, local, config)["ready"])

    @patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": ""})
    def test_stale_or_disabled_registration_not_ready(self):
        local, config, record_path, record = self.fake_registration()
        self.assertFalse(lab.registration_check(self.root, {"coreVersion": "1.4.0"}, local, config)["ready"])
        record["enabled"] = False
        record_path.write_text(json.dumps(record), encoding="utf-8")
        self.assertFalse(lab.registration_check(self.root, {"coreVersion": "1.3.0"}, local, config)["ready"])

    def test_no_registration_never_falls_back_to_user(self):
        result = lab.registration_check(self.root, {"coreVersion": "1.3.0"}, self.root / "empty-local")
        self.assertFalse(result["ready"])
        self.assertEqual(result["code"], "not_installed")

    def test_dashboard_no_external_dependencies_or_auto_pass(self):
        source = (builder.TEMPLATES / "dashboard.html").read_text(encoding="utf-8")
        self.assertNotIn("https://", source)
        self.assertNotIn("localStorage", source)
        self.assertIn("아직 Claude 업무 시험을 실행한 것은 아닙니다", source)
        self.assertIn("미실행", source)
        self.assertIn("connect-src 'none'", source)

    def test_first_work_is_optional_offline_and_links_to_existing_lab(self):
        source = (REPO / 'company-agent-plugin/resources/first-work.html').read_text(encoding='utf-8')
        self.assertEqual(7, source.count('data-copy='))
        self.assertIn("connect-src 'none'", source)
        for forbidden in ('https://', 'fetch(', 'localStorage', 'XMLHttpRequest'):
            self.assertNotIn(forbidden, source)
        self.assertIn('복사 버튼은 업무를 실행하거나 개인 정보를 저장하지 않습니다', source)
        self.assertIn('동의할 때만', source)
        self.assertIn('00_FIRST_WORK.html', (builder.TEMPLATES / 'dashboard.html').read_text(encoding='utf-8'))


if __name__ == "__main__":
    unittest.main()
