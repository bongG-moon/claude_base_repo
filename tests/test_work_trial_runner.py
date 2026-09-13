"""Trial runner boundaries and genuine native resume, without model calls."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "test-lab" / "work-trial.py"
spec = importlib.util.spec_from_file_location("work_trial", SOURCE)
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class WorkTrialRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "worker-one"
        self.root.mkdir()
        self.patch = patch.object(trial, "TRIALS", self.base)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_only_owned_named_roots(self):
        self.assertEqual(self.root, trial.boundary(self.root))
        for path in [self.base, self.base / "other", self.root / "nested"]:
            with self.assertRaises(ValueError):
                trial.boundary(path)

    def test_initialize_preserves_operator_work_and_refresh_keeps_state(self):
        (self.root / "workspace").mkdir()
        source = self.root / "workspace" / "input.md"
        source.write_text("synthetic work", encoding="utf-8")
        trial.initialize(self.root)
        self.assertEqual("synthetic work", source.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            trial.initialize(self.root)
        state = self.root / "state" / "existing.md"
        state.write_text("personal trial state", encoding="utf-8")
        trial.refresh(self.root)
        self.assertEqual("personal trial state", state.read_text(encoding="utf-8"))
        self.assertTrue((self.root / "plugin").is_dir())
        self.assertNotEqual(self.root / "plugin", trial.selected_plugin(self.root, trial.read(self.root / "trial.json")))

    def test_no_blanket_permissions_and_only_scoped_edit_rules(self):
        allow = trial.rules(self.root, self.root / "plugin")
        self.assertNotIn("Bash", allow)
        self.assertNotIn("Agent", allow)
        self.assertIn("Agent(company-agent:medium-worker)", allow)
        self.assertNotIn("Edit", allow)
        self.assertFalse(any(x.startswith("Write(") for x in allow))
        self.assertFalse(any("business mail-send" in x for x in allow))
        self.assertTrue(any("session verify" in x for x in allow))
        trial.save(self.root / "operator" / "approved-commands.json", ["python *"])
        with self.assertRaises(ValueError):
            trial.rules(self.root, self.root / "plugin")

    def test_plugin_cannot_escape_snapshot(self):
        for name in ("../other", str(self.base), "plugin/other", "plugin-invalid"):
            with self.assertRaises(ValueError):
                trial.selected_plugin(self.root, {"plugin": name})

    def test_native_resume_retains_same_session_without_history_injection(self):
        trial.initialize(self.root)
        prompt = self.root / "operator" / "request.txt"
        prompt.write_text("Please work on the supplied synthetic files.", encoding="utf-8")
        calls = []

        class Process:
            returncode = 0
            def __init__(self, args, **kwargs):
                calls.append(args)
                flag = "--resume" if "--resume" in args else "--session-id"
                sid = args[args.index(flag) + 1]
                for event in [{"type": "system", "subtype": "init", "session_id": sid},
                              {"type": "result", "subtype": "success", "result": "Synthetic response"}]:
                    kwargs["stdout"].write((json.dumps(event) + "\n").encode())
            def communicate(self, *args, **kwargs):
                pass

        with patch.object(trial.subprocess, "Popen", Process), patch.object(trial, "hashes", return_value={}):
            trial.run(self.root, prompt, "main", 30)
            trial.run(self.root, prompt, "main", 30)
        self.assertIn("--session-id", calls[0])
        self.assertIn("--resume", calls[1])
        sid = calls[0][calls[0].index("--session-id") + 1]
        self.assertEqual(sid, calls[1][calls[1].index("--resume") + 1])
        for args in calls:
            self.assertNotIn("--no-session-persistence", args)
            self.assertNotIn("--dangerously-skip-permissions", args)


if __name__ == "__main__":
    unittest.main()
