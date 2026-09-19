from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts" / "harness_cli.py"
ENCODINGS = ("cp949:strict", "ascii:strict", "utf-8:strict")
UNICODE_TEXT = "한국어 업무 — 결과 😀"


class CliEncodingTests(unittest.TestCase):
    """Exercise real redirected child-process streams, not StringIO substitutes."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "사용자 — 😀"
        self.state = self.root / "개인 상태"
        self.claude = self.root / "Claude 설정"
        self.project = self.root / "프로젝트  — 😀"
        self.plugin = self.root / "회사 플러그인"
        self.project.mkdir(parents=True)
        manifest = self.plugin / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"name": "company-agent", "version": "1.0.0"}), encoding="utf-8")
        self.user_skill = self.write_skill(self.claude / "skills" / "report")
        self.company_skill = self.write_skill(self.plugin / "skills" / "report")
        self.environment_before = dict(os.environ)
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith("COMPANY_AGENT_"):
                self.env.pop(key)
        self.env.update({
            "CLAUDE_CONFIG_DIR": str(self.claude),
            "COMPANY_AGENT_USER_STATE": str(self.state),
            "PYTHONUTF8": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        })

    def tearDown(self):
        self.assertEqual(self.environment_before, dict(os.environ), "CLI tests must not change the parent environment")

    def write_skill(self, directory):
        directory.mkdir(parents=True)
        path = directory / "SKILL.md"
        path.write_text("---\nname: report\ndescription: " + UNICODE_TEXT + "\n---\nPrivate body.\n", encoding="utf-8")
        return path

    def run_cli(self, encoding, *arguments, expected=0):
        env = {**self.env, "PYTHONIOENCODING": encoding}
        result = subprocess.run(
            [sys.executable, "-B", str(CLI), *arguments],
            cwd=self.project,
            env=env,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(expected, result.returncode, repr(result.stdout) + repr(result.stderr))
        self.assertNotIn(b"Traceback", result.stderr)
        self.assertNotIn(b"UnicodeEncodeError", result.stderr)
        return result

    def skill_cli(self, encoding, operation, *arguments, expected=0):
        result = self.run_cli(
            encoding, "skill", operation,
            "--state-root", str(self.state), "--claude-root", str(self.claude),
            "--plugin-root", str(self.plugin), "--project-root", str(self.project),
            *arguments, expected=expected,
        )
        # Successful JSON and structured errors are intentionally ASCII-safe;
        # decoding JSON must restore the exact Unicode, not replacement glyphs.
        selected = result.stdout if expected == 0 else result.stderr
        parsed = json.loads(selected.decode("ascii"))
        self.assertEqual(b"", result.stderr if expected == 0 else result.stdout)
        return parsed

    def test_inventory_roundtrips_unicode_paths_and_descriptions_in_legacy_pipes(self):
        snapshots = {path: path.read_bytes() for path in (self.user_skill, self.company_skill)}
        for encoding in ENCODINGS:
            with self.subTest(encoding=encoding):
                inventory = self.skill_cli(encoding, "inventory")
                self.assertTrue(inventory["complete"])
                self.assertEqual(2, len(inventory["skills"]))
                self.assertEqual({str(self.user_skill), str(self.company_skill)}, {s["path"] for s in inventory["skills"]})
                self.assertEqual({UNICODE_TEXT}, {s["description"] for s in inventory["skills"]})
                self.assertEqual([], inventory["warnings"])
                self.assertFalse(self.state.exists(), "read-only inventory must not initialize personal state")
        self.assertEqual(snapshots, {path: path.read_bytes() for path in snapshots})

    def test_preference_outputs_and_saved_unicode_project_survive_all_pipe_encodings(self):
        snapshots = {path: path.read_bytes() for path in (self.user_skill, self.company_skill)}
        for encoding in ENCODINGS:
            with self.subTest(encoding=encoding):
                inventory = self.skill_cli(encoding, "inventory")
                candidate = next(item for item in inventory["skills"] if item["source"] == "company")
                choice = self.skill_cli(encoding, "prefer", "--name", "report", "--candidate", candidate["id"], "--scope", "project")
                self.assertTrue(choice["ok"])
                self.assertEqual(str(self.state / "config" / "skill-preferences.json"), choice["preferencesPath"])
                resolved = self.skill_cli(encoding, "resolve", "report")
                self.assertEqual(candidate["id"], resolved["resolution"]["selectedId"])
                persisted = json.loads((self.state / "config" / "skill-preferences.json").read_text(encoding="utf-8"))
                self.assertEqual([str(self.project)], [value["projectRoot"] for value in persisted["projects"].values()])
        self.assertEqual(snapshots, {path: path.read_bytes() for path in snapshots})

    def test_unicode_metadata_error_is_valid_json_without_secondary_encoding_error(self):
        preferences = self.state / "config" / "skill-preferences.json"
        preferences.parent.mkdir(parents=True)
        preferences.write_text("malformed JSON — 😀", encoding="utf-8")
        original = preferences.read_bytes()
        for encoding in ENCODINGS:
            with self.subTest(encoding=encoding):
                error = self.skill_cli(encoding, "inventory", expected=1)
                self.assertFalse(error["ok"])
                self.assertEqual("Invalid JSON metadata: " + str(preferences), error["error"])
                self.assertEqual(original, preferences.read_bytes())

    def test_unicode_os_error_is_valid_json_and_does_not_create_personal_state(self):
        missing = self.root / "없는 파일 — 😀.json"
        for encoding in ENCODINGS:
            with self.subTest(encoding=encoding):
                result = self.run_cli(encoding, "asset", "create", "--state-root", str(self.state), "--storage-scope", "personal", "--project-root", str(self.root), "--spec", str(missing), expected=1)
                self.assertEqual(b"", result.stdout)
                error = json.loads(result.stderr.decode("ascii"))
                self.assertFalse(error["ok"])
                # OSError renders paths with repr(), including escaped Windows separators.
                self.assertIn(repr(str(missing)), error["error"])
                self.assertFalse(self.state.exists())

    def test_argparse_unicode_usage_error_stays_readable_without_traceback(self):
        for encoding in ENCODINGS:
            with self.subTest(encoding=encoding):
                result = self.run_cli(encoding, "skill", "없는명령—😀", expected=2)
                self.assertEqual(b"", result.stdout)
                diagnostic = result.stderr.decode(encoding.split(":", 1)[0])
                self.assertIn("invalid choice", diagnostic)
                self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
