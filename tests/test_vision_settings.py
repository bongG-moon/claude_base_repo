from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from company_agent import vision_settings as settings


class VisionSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "state"
        self.config = self.base / "claude"

    def configure(self, model="local/vision-large"):
        return settings.configure(self.root, model, config_root=self.config)

    def test_missing_status_does_not_create_directories(self):
        self.assertEqual(settings.read_settings(self.root), {})
        self.assertEqual(settings.status(self.root)["status"], "needs_setup")
        self.assertFalse(self.root.exists())

    def test_first_choice_creates_one_owned_native_agent(self):
        result = self.configure()
        agent_path = Path(result["agentPath"])
        text = agent_path.read_text(encoding="utf-8")
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["restartMayBeRequired"])
        self.assertTrue(result["nextRequestRequired"])
        self.assertTrue(result["restartRequired"])
        self.assertIn("modelUpdatedAt", result)
        self.assertEqual(agent_path.parent, self.config / "agents")
        self.assertIn('model: "local/vision-large"', text)
        self.assertIn("disallowedTools: Write, Edit, MultiEdit, NotebookEdit, Bash, PowerShell, Agent, Task", text)
        self.assertNotIn("company-agent:vision-worker", text)
        self.assertNotIn("HCP-Vision-Latest", text)
        receipt = settings.read_settings(self.root)
        self.assertEqual(receipt["sha256"], hashlib.sha256(agent_path.read_bytes()).hexdigest())
        self.assertEqual(settings.status(self.root)["agent"], result["agent"])

    def test_existing_agent_directory_does_not_request_restart(self):
        (self.config / "agents").mkdir(parents=True)
        self.assertFalse(self.configure()["restartMayBeRequired"])

    def test_model_change_reuses_same_file_and_preserves_other_settings(self):
        self.config.mkdir()
        unrelated = self.config / "settings.json"
        unrelated.write_text('{"model":"sonnet","mcpServers":{"keep":{}}}', encoding="utf-8")
        before = unrelated.read_bytes()
        first = self.configure()
        personal = self.config / "agents" / "my-worker.md"
        personal.write_text("my own content", encoding="utf-8")
        second = self.configure("my-company/vision:v2[1m]")
        self.assertEqual(first["agentPath"], second["agentPath"])
        self.assertEqual(first["agent"], second["agent"])
        self.assertFalse(second["restartMayBeRequired"])
        self.assertTrue(second["nextRequestRequired"])
        self.assertTrue(second["restartRequired"])
        self.assertEqual(len(list((self.config / "agents").glob("company-harness-vision-*.md"))), 1)
        self.assertEqual(personal.read_text(encoding="utf-8"), "my own content")
        self.assertEqual(unrelated.read_bytes(), before)

    def test_hcp_is_an_explicit_valid_choice(self):
        result = self.configure(settings.DEFAULT_MODEL)
        self.assertEqual(result["model"], settings.DEFAULT_MODEL)
        self.assertEqual(result["backupModel"], settings.DEFAULT_MODEL)
        self.assertIn('model: "HCP-Vision-Latest"', Path(result["agentPath"]).read_text(encoding="utf-8"))

    def test_same_choice_does_not_rewrite(self):
        self.configure()
        with patch.object(settings, "atomic_write_text") as text_write, patch.object(settings, "atomic_write_json") as json_write:
            result = self.configure()
        text_write.assert_not_called()
        json_write.assert_not_called()
        self.assertFalse(result["nextRequestRequired"])
        self.assertFalse(result["restartRequired"])

    def test_invalid_model_does_not_touch_disk(self):
        for model in ("", None, 12, "a" * 161, " v1", "v1 ", "v1\nmodel: other", "모델", "https://example/token", "http:secret", "../model", "org/../model", "org//model", "a\\b", "a?api_key=secret", "a#comment", "a b"):
            with self.subTest(model=model), self.assertRaises(ValueError):
                self.configure(model)
        self.assertFalse(self.root.exists())
        self.assertFalse(self.config.exists())

    def test_foreign_agent_collision_is_preserved(self):
        expected = self.config / "agents" / (settings._agent_name(self.root) + ".md")
        expected.parent.mkdir(parents=True)
        expected.write_text("foreign personal file", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "개인 작업자"):
            self.configure()
        self.assertEqual(expected.read_text(encoding="utf-8"), "foreign personal file")
        self.assertFalse(self.root.exists())

    def test_directly_edited_owned_file_is_preserved(self):
        result = self.configure()
        path = Path(result["agentPath"])
        path.write_text(path.read_text(encoding="utf-8") + "\nmanual edit", encoding="utf-8")
        expected = path.read_bytes()
        for action in (lambda: self.configure("another-vlm"), lambda: settings.status(self.root)):
            with self.assertRaisesRegex(ValueError, "직접 수정"):
                action()
        self.assertEqual(path.read_bytes(), expected)

    def test_marker_is_required_even_with_matching_hash(self):
        result = self.configure()
        path = Path(result["agentPath"])
        path.write_text("---\nname: foreign\n---\n", encoding="utf-8")
        receipt_path = self.root / "config" / "vision-model.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "직접 수정"):
            self.configure()

    def test_changed_config_root_does_not_duplicate_agent(self):
        result = self.configure()
        other = self.base / "other-profile"
        with self.assertRaisesRegex(ValueError, "중복"):
            settings.configure(self.root, "other-model", config_root=other)
        self.assertTrue(Path(result["agentPath"]).exists())
        self.assertFalse(other.exists())

    def test_missing_agent_can_be_recreated_without_copies(self):
        result = self.configure()
        Path(result["agentPath"]).unlink()
        self.assertEqual(settings.status(self.root)["reason"], "agent_missing")
        self.assertEqual(self.configure()["agentPath"], result["agentPath"])
        self.assertEqual(settings.status(self.root)["status"], "ready")

    def test_absent_old_agent_allows_profile_change(self):
        result = self.configure()
        Path(result["agentPath"]).unlink()
        other = self.base / "other-profile"
        changed = settings.configure(self.root, "other-model", config_root=other)
        self.assertEqual(Path(changed["agentPath"]).parent, other / "agents")
        self.assertFalse(Path(result["agentPath"]).exists())

    def test_default_config_root_respects_existing_environment(self):
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.config)}):
            result = settings.configure(self.root, "my-model")
        self.assertEqual(Path(result["agentPath"]).parent, self.config / "agents")

    def test_oversized_and_malformed_settings_are_not_replaced(self):
        path = self.root / "config" / "vision-model.json"
        path.parent.mkdir(parents=True)
        for text in ("{}", "[]", "not json", "x" * 16385):
            path.write_text(text, encoding="utf-8")
            with self.subTest(length=len(text)), self.assertRaises(ValueError):
                self.configure()
            self.assertEqual(path.read_text(encoding="utf-8"), text)
        self.assertFalse(self.config.exists())

    def test_receipt_cannot_point_to_unrelated_filename(self):
        result = self.configure()
        path = self.root / "config" / "vision-model.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["agentPath"] = str(self.config / "agents" / "personal.md")
        path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaises(ValueError):
            settings.status(self.root)
        self.assertTrue(Path(result["agentPath"]).exists())

    def test_receipt_contains_metadata_only(self):
        self.configure()
        receipt = settings.read_settings(self.root)
        self.assertEqual(set(receipt), {"schemaVersion", "model", "agent", "agentPath", "sha256", "modelUpdatedAt"})

    def test_relative_and_parent_navigation_roots_are_rejected(self):
        for path in (Path("relative"), self.base / "nested" / ".." / "state"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                settings.configure(path, "model", config_root=self.config)

    def test_symlink_ancestor_is_rejected(self):
        target = self.base / "target"
        target.mkdir()
        link = self.base / "linked"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            self.skipTest("Symlink creation is unavailable: " + str(exc))
        with self.assertRaisesRegex(ValueError, "연결된"):
            settings.configure(self.root, "model", config_root=link / "claude")
        self.assertEqual(list(target.iterdir()), [])

    def test_windows_reparse_attribute_is_rejected(self):
        original = Path.lstat
        for guarded in (
            self.root, self.root / "config", self.root / "config" / "vision-model.json",
            self.config, self.config / "agents",
            self.config / "agents" / (settings._agent_name(self.root) + ".md"),
        ):
            def fake_lstat(path):
                if path == guarded:
                    class ReparseInfo:
                        st_mode = stat.S_IFDIR | 0o700
                        st_file_attributes = 0x400
                    return ReparseInfo()
                return original(path)

            with self.subTest(path=guarded), patch.object(Path, "lstat", fake_lstat), self.assertRaisesRegex(ValueError, "연결된"):
                self.configure()
        self.assertFalse(self.root.exists())

    def test_settings_parent_is_not_allowed_to_be_a_file(self):
        self.root.mkdir()
        (self.root / "config").write_text("personal data", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.configure()
        self.assertEqual((self.root / "config").read_text(encoding="utf-8"), "personal data")
        self.assertFalse(self.config.exists())

    def test_invalid_timestamp_is_rejected_without_overwrite(self):
        self.configure()
        path = self.root / "config" / "vision-model.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        for timestamp in (None, 1, "not a timestamp", "2026-10-14T12:00:00"):
            receipt["modelUpdatedAt"] = timestamp
            path.write_text(json.dumps(receipt), encoding="utf-8")
            before = path.read_bytes()
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                self.configure()
            self.assertEqual(path.read_bytes(), before)

    def test_changed_agent_between_preparation_and_write_is_not_overwritten(self):
        result = self.configure()
        agent_path = Path(result["agentPath"])
        original = settings._read_file
        calls = 0

        def racing_read(path, limit):
            nonlocal calls
            if path == agent_path:
                calls += 1
                if calls == 3:
                    agent_path.write_text("new user contents", encoding="utf-8")
            return original(path, limit)

        with patch.object(settings, "_read_file", racing_read), self.assertRaisesRegex(ValueError, "설정 중 파일"):
            self.configure("other-model")
        self.assertEqual(agent_path.read_text(encoding="utf-8"), "new user contents")

    def test_failed_receipt_save_restores_old_agent(self):
        result = self.configure()
        path = Path(result["agentPath"])
        before = path.read_bytes()
        receipt_before = (self.root / "config" / "vision-model.json").read_bytes()
        with patch.object(settings, "atomic_write_json", side_effect=OSError("disk failure")), self.assertRaises(OSError):
            self.configure("changed-model")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((self.root / "config" / "vision-model.json").read_bytes(), receipt_before)
        self.assertEqual(settings.status(self.root)["model"], "local/vision-large")

    def test_failed_first_receipt_save_does_not_leave_orphan_agent(self):
        with patch.object(settings, "atomic_write_json", side_effect=OSError("disk failure")), self.assertRaises(OSError):
            self.configure()
        self.assertEqual(list((self.config / "agents").iterdir()), [])
        self.assertEqual(settings.read_settings(self.root), {})


if __name__ == "__main__":
    unittest.main()
