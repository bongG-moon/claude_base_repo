"""Installed hook regressions for project-local native plugin activation.

Use isolated registration/profile files and the real native_entry/configure_runtime
path. No real Claude profile, image, network or model is accessed.
"""
from __future__ import annotations

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

import native_entry
from company_agent import native_runtime, vision_settings
from company_agent.paths import atomic_write_json

PLUGIN_ID = "company-agent@company-agent-local"


class PluginScopeActivationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="plugin-scope-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = self.root / "isolated-profile"
        self.project = self.root / "프로젝트"
        self.outside = self.root / "other-project"
        self.plugin = self.root / "installed-plugin"
        self.state = self.root / "personal-state"
        self.registrations = self.root / "registrations"
        self.project.mkdir()
        self.outside.mkdir()
        self.identity = {"session_id": "isolated-plugin-session", "cwd": str(self.project)}
        self.env = patch.dict(os.environ, {
            "CLAUDE_CONFIG_DIR": str(self.profile),
            "COMPANY_AGENT_USER_STATE": str(self.state),
            "COMPANY_AGENT_KNOWLEDGE_BASE": str(self.root / "knowledge"),
            "COMPANY_AGENT_PYTHON": sys.executable,
            "ANTHROPIC_MODEL": "unchanged-main-model",
            "ANTHROPIC_AUTH_TOKEN": "synthetic-test-token-not-a-credential",
            "ANTHROPIC_CUSTOM_MODEL_OPTION": "HCP-Vision-Latest",
            "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        atomic_write_json(self.plugin / "company-agent-install.json", {
            "registrationsRoot": str(self.registrations),
        })
        atomic_write_json(self.registrations / "user/company-agent-install.json", {
            "schemaVersion": 1, "scope": "User", "enabled": True,
            "nativeClaudeScope": "user", "pluginId": PLUGIN_ID,
            "claudeConfigRoot": str(self.profile), "claudeConfigDirOverride": True,
            "userStateRoot": str(self.state), "knowledgeBaseRoot": str(self.root / "knowledge"),
        })
        atomic_write_json(self.profile / "plugins/installed_plugins.json", {
            "plugins": {PLUGIN_ID: [{"scope": "user", "installPath": str(self.plugin)}]},
        })
        self.user_settings = self.profile / "settings.json"
        atomic_write_json(self.user_settings, {
            "enabledPlugins": {PLUGIN_ID: True, "unrelated@plugin": True},
            "model": "sonnet", "env": {"ANTHROPIC_MODEL": "unchanged-main-model"},
        })

    def local_enabled(self, enabled):
        atomic_write_json(self.project / ".claude/settings.local.json", {
            "enabledPlugins": {PLUGIN_ID: enabled}, "permissions": {"allow": ["Read"]},
        })

    def call(self, tool="Read", inputs=None, **extra):
        return {**self.identity, "tool_name": tool,
                "tool_input": inputs or {"file_path": str(self.project / "unopened-image.jpg")},
                **extra}

    def run_entry(self, event, payload):
        output = io.StringIO()
        with patch.object(native_entry, "__file__", str(self.plugin / "scripts/native_entry.py")), \
                patch.object(sys, "argv", ["native_entry.py", "--event", event]), \
                patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                contextlib.redirect_stdout(output):
            self.assertEqual(0, native_entry.main())
        return json.loads(output.getvalue())

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def preserved_environment(self):
        return {key: value for key, value in os.environ.items()
                if key.startswith(("ANTHROPIC_", "CLAUDE_", "COMPANY_AGENT_"))
                and key != "COMPANY_AGENT_CWD"}

    def test_disabled_project_hooks_are_silent_and_leave_existing_personal_state_untouched(self):
        config = vision_settings.configure(self.state, "isolated-vision", config_root=self.profile)
        self.local_enabled(False)
        agent = {"subagent_type": "company-agent:vision-worker", "prompt": "Read the exact requested image."}
        managed = {**agent, "subagent_type": config["agent"]}
        events = [
            ("SessionStart", {**self.identity, "source": "startup"}),
            ("UserPromptSubmit", {**self.identity, "prompt": "이미지 확인해줘"}),
            ("PreToolUse", self.call()),
            ("PreToolUse", self.call(inputs={"file_path": str(self.project / "unopened.pdf")})),
            ("PreToolUse", self.call("Agent", agent)),
            ("PreToolUse", self.call("Agent", managed)),
            ("PreToolUse", self.call("Agent", {"prompt": "[company-vision:123] read requested image"})),
            ("PostToolUseFailure", self.call("Agent", agent, error="Agent type company-agent:vision-worker not found")),
            ("PostToolUseFailure", self.call("Agent", managed, tool_use_id="native-model-failure", error=(
                "Agent terminated early due to an API error: not available "
                "(error type model_not_found, HTTP 404, request id fixture, model sent to the API: isolated-vision)"))),
            ("PostToolUse", self.call(agent_id="old-child", agent_type=config["agent"],
                                     tool_response={"type": "image", "file": {"type": "image/png", "base64": "AA=="}})),
        ]
        before_files, before_env = self.snapshot(), self.preserved_environment()
        for event, payload in events:
            with self.subTest(event=event, tool=payload.get("tool_name"), agent=payload.get("tool_input")):
                self.assertEqual({}, self.run_entry(event, payload))
                self.assertEqual(before_files, self.snapshot())
                self.assertEqual(before_env, self.preserved_environment())
        self.assertFalse((self.state / "tmp").exists())

    def test_first_image_while_disabled_creates_no_model_configuration_or_handoff(self):
        self.local_enabled(False)
        before = self.snapshot()
        self.assertEqual({}, self.run_entry("PreToolUse", self.call()))
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.state.exists())
        self.assertFalse((self.profile / "agents").exists())

    def test_reenable_takes_effect_on_next_hook_without_process_cache(self):
        self.local_enabled(False)
        self.assertEqual({}, self.run_entry("PreToolUse", self.call()))
        self.local_enabled(True)
        result = self.run_entry("PreToolUse", self.call())["hookSpecificOutput"]
        self.assertEqual("deny", result["permissionDecision"])
        self.assertIn("이미지 모델 선택", result["permissionDecisionReason"])
        self.assertTrue(native_runtime.configure_runtime(self.plugin, self.project))
        self.local_enabled(False)
        self.assertEqual({}, self.run_entry("PreToolUse", self.call()))
        self.assertFalse(self.state.exists())

    def test_project_disable_does_not_disable_user_plugin_in_other_folder(self):
        self.local_enabled(False)
        self.assertFalse(native_runtime.configure_runtime(self.plugin, self.project))
        self.assertTrue(native_runtime.configure_runtime(self.plugin, self.outside))
        result = self.run_entry("PreToolUse", self.call(cwd=str(self.outside)))["hookSpecificOutput"]
        self.assertIn("이미지 모델 선택", result["permissionDecisionReason"])
        self.assertEqual({}, self.run_entry("PreToolUse", self.call()))

    def test_project_true_overrides_user_false_but_local_false_wins(self):
        atomic_write_json(self.user_settings, {"enabledPlugins": {PLUGIN_ID: False}})
        self.assertFalse(native_runtime.configure_runtime(self.plugin, self.project))
        atomic_write_json(self.project / ".claude/settings.json", {"enabledPlugins": {PLUGIN_ID: True}})
        self.assertTrue(native_runtime.configure_runtime(self.plugin, self.project))
        self.local_enabled(False)
        self.assertFalse(native_runtime.configure_runtime(self.plugin, self.project))

    def test_other_plugin_setting_does_not_hide_enabled_user_plugin(self):
        atomic_write_json(self.project / ".claude/settings.local.json", {
            "enabledPlugins": {"unrelated@plugin": False},
        })
        self.assertTrue(native_runtime.configure_runtime(self.plugin, self.project))

    def test_disabled_project_install_cannot_fall_back_to_user_install(self):
        record = json.loads((self.registrations / "user/company-agent-install.json").read_text(encoding="utf-8"))
        record.update({"scope": "Project", "nativeClaudeScope": "project", "projectRoot": str(self.project)})
        atomic_write_json(self.registrations / "projects/project/company-agent-install.json", record)
        atomic_write_json(self.profile / "plugins/installed_plugins.json", {
            "plugins": {PLUGIN_ID: [{"scope": "user"}, {"scope": "project", "projectPath": str(self.project)}]},
        })
        self.local_enabled(False)
        self.assertFalse(native_runtime.configure_runtime(self.plugin, self.project))
        self.assertEqual({}, self.run_entry("PreToolUse", self.call()))
        self.local_enabled(True)
        self.assertTrue(native_runtime.configure_runtime(self.plugin, self.project))
        self.assertEqual("Project", os.environ["COMPANY_AGENT_SCOPE"])

    def test_invalid_json_or_oversized_local_settings_fail_inactive(self):
        file = self.project / ".claude/settings.local.json"
        self.local_enabled(True)
        for text in ("{ invalid json", " " * (512 * 1024 + 1)):
            with self.subTest(length=len(text)):
                file.write_text(text, encoding="utf-8")
                self.assertFalse(native_runtime.configure_runtime(self.plugin, self.project))
                self.assertEqual({}, self.run_entry("PreToolUse", self.call()))

    def test_ordinary_text_read_bypasses_scope_and_model_settings(self):
        self.local_enabled(False)
        payload = self.call(inputs={"file_path": str(self.project / "instructions.md")})
        before = self.snapshot()
        with patch.object(native_entry, "configure_runtime", side_effect=AssertionError("text must remain fast")), \
                patch.object(vision_settings, "status", side_effect=AssertionError("no model status for text")):
            self.assertEqual({}, self.run_entry("PreToolUse", payload))
        self.assertEqual(before, self.snapshot())

    def test_native_profile_mismatch_stays_inactive_without_switching_profile(self):
        other = self.root / "other-claude-profile"
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(other)}):
            self.assertFalse(native_runtime.configure_runtime(self.plugin, self.project))
            self.assertEqual({}, self.run_entry("PreToolUse", self.call()))
            self.assertEqual(str(other), os.environ["CLAUDE_CONFIG_DIR"])

    def test_enabled_setting_does_not_replace_missing_native_inventory(self):
        atomic_write_json(self.profile / "plugins/installed_plugins.json", {"plugins": {}})
        self.assertFalse(native_runtime.configure_runtime(self.plugin, self.project))
        self.assertEqual({}, self.run_entry("PreToolUse", self.call()))

    def test_invalid_local_settings_do_not_reactivate_user_record(self):
        for value in ("false", 0, None):
            with self.subTest(value=value):
                self.local_enabled(value)
                self.assertFalse(native_runtime.configure_runtime(self.plugin, self.project))


if __name__ == "__main__":
    unittest.main()
