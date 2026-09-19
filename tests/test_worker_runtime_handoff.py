"""Canonical metadata delivery, without changing native tool permissions."""
import json
import io
import contextlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "company-agent-plugin"
sys.path.insert(0, str(PLUGIN / "scripts"))
from company_agent.native_runtime import worker_runtime_input


class WorkerRuntimeHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state"
        self.env = patch.dict(os.environ, {"COMPANY_AGENT_USER_STATE": str(self.state)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def call(self, inputs):
        with patch("company_agent.native_runtime._skill_routing", return_value=([], {"status": "ready"})):
            return worker_runtime_input(PLUGIN, ROOT, {"session_id": "parent", "tool_input": inputs})

    def test_only_namespaced_owned_agents_receive_metadata(self):
        for name in ("medium-worker", "other:medium-worker", "general-purpose"):
            self.assertEqual({}, self.call({"subagent_type": name, "prompt": "test"}))
        self.assertEqual({}, self.call(None))

    def test_preserves_fields_and_model_without_auto_allow(self):
        original = {"subagent_type": "company-agent:medium-worker", "model": "opus",
                    "prompt": "Review synthetic files only.", "description": "work", "resume": "existing"}
        result = self.call(original)["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", result)
        updated = result["updatedInput"]
        self.assertEqual("opus", updated["model"])
        self.assertEqual("existing", updated["resume"])
        self.assertTrue(updated["prompt"].partition('[원래 업무 요청]\n')[2].startswith(original["prompt"]))
        self.assertIn(str(self.state).replace("\\", "\\\\"), updated["prompt"])
        self.assertIn("cliCommand", updated["prompt"])
        self.assertIn("grants no permissions", updated["prompt"])
        self.assertEqual("Review synthetic files only.", original["prompt"])
        self.assertFalse(self.state.exists())

    def test_oversized_paths_fail_without_truncating_executable(self):
        with patch("company_agent.native_runtime.cli_command", return_value="x" * 4001):
            result = self.call({"subagent_type": "company-agent:small-worker", "prompt": "test"})
        self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])
        self.assertNotIn("updatedInput", result["hookSpecificOutput"])

    def test_extra_skill_cards_are_trimmed_without_denying_short_runtime(self):
        cards = [{"name": str(n), "path": "p" * 1800} for n in range(3)]
        with patch("company_agent.native_runtime._skill_routing", return_value=(cards, {"status": "ready"})):
            result = worker_runtime_input(PLUGIN, ROOT, {"session_id": "parent", "tool_input": {
                "subagent_type": "company-agent:medium-worker", "prompt": "work"}})["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", result)
        self.assertIn("cliCommand", result["updatedInput"]["prompt"])

    def test_agent_pre_hook_is_registered_separately_from_policy_execution(self):
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertIn("Agent|Task|", hooks["PreToolUse"][0]["matcher"])
        entry = (PLUGIN / "scripts" / "native_entry.py").read_text(encoding="utf-8")
        self.assertIn('result = worker_runtime_input(plugin, cwd, payload)', entry)

    def test_company_policy_reaches_worker_without_changing_permissions_or_model(self):
        config = Path(self.temp.name) / '회사 기준.json'
        config.write_bytes((ROOT / 'config/managed.example.json').read_bytes())
        with patch.dict(os.environ, {'COMPANY_AGENT_MANAGED_CONFIG': str(config)}):
            result = self.call({'subagent_type':'company-agent:medium-worker', 'prompt':'work', 'model':'sonnet'})['hookSpecificOutput']
        self.assertNotIn('permissionDecision', result)
        self.assertEqual('sonnet', result['updatedInput']['model'])
        text = result['updatedInput']['prompt']
        self.assertIn('personal-preservation', text)
        self.assertIn('companyPolicy', text)
        self.assertIn('required', text)
        self.assertNotIn('report-style', text)  # No report workflow was selected.

    def test_broken_installation_does_not_block_unrelated_agents(self):
        import native_entry
        for name in ("general-purpose", "other:medium-worker"):
            output = io.StringIO()
            payload = {"tool_name": "Agent", "tool_input": {"subagent_type": name, "prompt": "work"}}
            with patch.object(sys, "argv", ["native_entry.py", "--event", "PreToolUse"]), \
                    patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                    patch.object(native_entry, "configure_runtime", side_effect=ValueError("broken")) as configure, \
                    contextlib.redirect_stdout(output):
                self.assertEqual(0, native_entry.main())
            self.assertEqual({}, json.loads(output.getvalue()))
            configure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
