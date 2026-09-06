from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))

from company_agent.cli import main
from company_agent.memory import upsert_memory
from company_agent.native_runtime import session_start
from company_agent.paths import atomic_write_json, ensure_user_layout
from company_agent.state import begin_turn
from company_agent.state_compatibility import check_state_compatibility
from unittest.mock import patch


class StateCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "state"

    def tearDown(self):
        self.temp.cleanup()

    def test_check_missing_legacy_state_is_read_only(self):
        result = check_state_compatibility(self.root)
        self.assertTrue(result["legacyUnmarked"])
        self.assertFalse(self.root.exists())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, main(["state", "check", "--state-root", str(self.root)]))
        self.assertFalse(self.root.exists())

    def test_supported_markers_are_not_rewritten(self):
        marker = self.root / "state-format.json"
        atomic_write_json(marker, {"schemaVersion": 1})
        before = marker.read_bytes()
        for config in ({"custom": True}, {"schemaVersion": 1}, {"schemaVersion": 2}):
            atomic_write_json(self.root / "config" / "user.json", config)
            self.assertTrue(check_state_compatibility(self.root)["ok"])
        self.assertEqual(before, marker.read_bytes())

    def test_unknown_or_invalid_marker_blocks_before_layout_creation(self):
        marker = self.root / "state-format.json"
        for value in ({"schemaVersion": 99}, {"schemaVersion": True}, {}, [], {"schemaVersion": "1"}):
            atomic_write_json(marker, value)
            before = marker.read_bytes()
            with self.assertRaises(ValueError):
                ensure_user_layout(self.root)
            self.assertEqual(before, marker.read_bytes())
            self.assertFalse((self.root / "memory").exists())

    def test_corrupt_config_does_not_leak_or_reset(self):
        config = self.root / "config" / "user.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"token":"fixture-private-value"', encoding="utf-8")
        before = config.read_bytes()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            result = main(["state", "check", "--state-root", str(self.root)])
        self.assertEqual(1, result)
        self.assertNotIn("fixture-private-value", errors.getvalue())
        self.assertEqual(before, config.read_bytes())

    def test_future_format_blocks_memory_writes_and_startup(self):
        path = upsert_memory({"title": "Report format", "body": "Conclusion first."}, self.root)
        before = path.read_bytes()
        atomic_write_json(self.root / "state-format.json", {"schemaVersion": 99})
        with self.assertRaises(ValueError):
            upsert_memory({"title": "Report format", "body": "Evidence first."}, self.root)
        with patch.dict("os.environ", {"COMPANY_AGENT_USER_STATE": str(self.root)}):
            with self.assertRaises(ValueError):
                session_start(ROOT / "company-agent-plugin", ROOT)
        self.assertEqual(before, path.read_bytes())

    def test_future_user_config_blocks_initializer_without_rewrite(self):
        path = self.root / "config" / "user.json"
        atomic_write_json(path, {"schemaVersion": 99, "personal": {"keep": True}})
        before = path.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(1, main(["init-user", "--state-root", str(self.root)]))
        self.assertEqual(before, path.read_bytes())

    def test_initializer_preserves_extra_settings_and_legacy_version(self):
        path = self.root / "config" / "user.json"
        existing = {"schemaVersion": 2, "personal": {"reportStyle": "short"}, "display_name": "Fixture"}
        atomic_write_json(path, existing)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, main(["init-user", "--state-root", str(self.root)]))
        result = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(2, result["schemaVersion"])
        self.assertEqual(existing["personal"], result["personal"])
        self.assertEqual("Fixture", result["display_name"])

    def test_future_session_is_not_overwritten_on_new_turn(self):
        layout = ensure_user_layout(self.root)
        path = layout["sessions"] / "fixture.json"
        atomic_write_json(path, {"schemaVersion": 99, "mutationCount": 7})
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            begin_turn("fixture", "SMALL", False, [], self.root)
        self.assertEqual(before, path.read_bytes())
