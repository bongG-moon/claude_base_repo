import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "company-agent-plugin/scripts"
sys.path.insert(0, str(SCRIPTS))
from company_agent.handoff import create_handoff, read_handoff
from company_agent.cli import main


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "report.md").write_text("synthetic", encoding="utf-8")
        (self.root / "sessions").mkdir()
        self.path = self.root / "sessions/session-one.json"
        self.path.write_text(json.dumps({"sessionId": "session-one", "mutationCount": 2,
            "stopRetryCount": 2, "verification": {"status": "fail"}, "unresolvedChanges": [{}]}), encoding="utf-8")
        self.spec = {"goal": "보고서 작성", "summary": "초안 작성, 숫자 미확인", "constraints": ["원본 수정 금지"],
                     "nextActions": ["합계 대조"], "artifacts": ["report.md"]}

    def test_export_read_does_not_clear_failure_or_change_session(self):
        before = self.path.read_bytes()
        result = create_handoff(self.root, self.project, "session-one", self.spec)
        restored = read_handoff(self.root, self.project, result["id"])
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual("fail", restored["currentSourceState"]["verificationStatus"])
        self.assertEqual(2, restored["currentSourceState"]["stopRetryCount"])
        self.assertTrue(restored["untrusted"])
        self.assertNotIn("synthetic", Path(result["file"]).read_text(encoding="utf-8"))

    def test_foreign_project_missing_artifact_and_tampering_rejected(self):
        result = create_handoff(self.root, self.project, "session-one", self.spec)
        with self.assertRaises(ValueError):
            read_handoff(self.root, self.root, result["id"])
        with self.assertRaises(ValueError):
            read_handoff(self.root, self.project, "../../escape")
        (self.project / "report.md").unlink()
        with self.assertRaises(ValueError):
            read_handoff(self.root, self.project, result["id"])

    def test_raw_unknown_and_unsafe_specs_rejected_before_write(self):
        for change in ({"password": "value"}, {"summary": "password=secret-value"},
                       {"artifacts": ["../sessions/session-one.json"]}, {"artifacts": ["https://example.com"]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                create_handoff(self.root, self.project, "session-one", {**self.spec, **change})
        self.assertFalse((self.root / "handoffs").exists())

    def test_protected_source_and_stale_source_are_not_silently_resumed(self):
        result = create_handoff(self.root, self.project, "session-one", self.spec)
        value = json.loads(self.path.read_text())
        value["protectionRestricted"] = True
        self.path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            read_handoff(self.root, self.project, result["id"])
        with self.assertRaises(ValueError):
            create_handoff(self.root, self.project, "session-one", self.spec)

    def test_cli_round_trip_is_ascii_safe(self):
        spec = self.root / "spec.json"
        spec.write_text(json.dumps(self.spec), encoding="utf-8")
        base = [sys.executable, str(SCRIPTS / "harness_cli.py"), "handoff"]
        result = subprocess.run(base + ["create", "--spec", str(spec), "--project", str(self.project),
            "--session", "session-one", "--state-root", str(self.root)], cwd=SCRIPTS, capture_output=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        created = json.loads(result.stdout.decode("ascii"))
        result = subprocess.run(base + ["read", "--id", created["id"], "--project", str(self.project),
            "--state-root", str(self.root)], cwd=SCRIPTS, capture_output=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["requiresRevalidation"])

    def test_cli_validates_raw_state_path_before_resolving(self):
        for command, guard in (("handoff", "company_agent.handoff.safe_path"),
                               ("setup-helper", "company_agent.setup_helper._safe_path")):
            raw = str(self.root / "redirect" / ".." / "raw-state")
            with patch(guard, side_effect=ValueError("redirect rejected")) as checked:
                arguments = [command, "create", "--state-root", raw, "--spec", str(self.root / "spec.json")]
                if command == "handoff":
                    arguments += ["--project", str(self.project), "--session", "session-one"]
                self.assertEqual(1, main(arguments))
                self.assertEqual(Path(raw), checked.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
