from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))

from company_agent import asset_factory as assets  # noqa: E402
from company_agent import native_mcp as native  # noqa: E402
from company_agent.paths import atomic_write_json, ensure_user_layout, load_json  # noqa: E402


class NativeMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "한글 MCP test"
        self.root.mkdir()
        self.state = self.root / "state"
        self.config = self.root / "claude-config"
        self.project = self.root / "project"
        self.project.mkdir()
        self.env = patch.dict(os.environ, {
            "COMPANY_AGENT_SCOPE": "User", "COMPANY_AGENT_PROJECT_ROOT": "",
            "CLAUDE_CONFIG_DIR": str(self.config), "ANTHROPIC_AUTH_TOKEN": "DO-NOT-PRINT-CREDENTIAL",
        })
        self.env.start()
        self.name = "personal-report"
        self.asset = assets.create_asset({"type": "mcp", "name": self.name, "description": "Personal report test",
                                          "reviewed_capabilities": ["third-party-import"]}, self.state)
        layout = ensure_user_layout(self.state)
        # Fixture receipt stands in for the separate MCP protocol validator.
        # No server is run by native config registration.
        receipt = assets._write_receipt(layout, self.asset, "mcp-protocol", "mcp", self.name,
                                        assets._asset_content_hash(self.asset, "asset.json"), {"fixture": True})
        assets.activate_mcp(self.state, self.name, receipt)
        self.desired = load_json(self.state / "mcp" / "registry.json")["mcpServers"][self.name]

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def fake_add(self, argv, **kwargs):
        self.assertFalse(kwargs["shell"])
        self.assertEqual(subprocess.DEVNULL, kwargs["stdin"])
        self.assertEqual(["mcp", "add-json", self.name], argv[-6:-3])
        config = native._config_file()
        document = load_json(config, {})
        destination = document
        if argv[-1] == "local":
            destination = document.setdefault("projects", {}).setdefault(str(self.project).replace("\\", "/"), {})
        destination.setdefault("mcpServers", {})[self.name] = json.loads(argv[-3])
        atomic_write_json(config, document)
        return subprocess.CompletedProcess(argv, 0, b"DO-NOT-PRINT-CHILD-OUTPUT", b"")

    def test_user_registration_and_owned_repeat_are_idempotent_without_connecting(self) -> None:
        with patch.object(native, "_claude_argv", return_value=["claude.exe"]), patch.object(native.subprocess, "run", side_effect=self.fake_add) as child:
            first = native.sync_native_mcp(self.state, self.name)
            second = native.sync_native_mcp(self.state, self.name)
        self.assertEqual("registered", first["status"])
        self.assertEqual("already-registered", second["status"])
        self.assertTrue(first["restartRequired"])
        self.assertEqual(1, child.call_count)
        self.assertEqual(self.desired, load_json(native._config_file())["mcpServers"][self.name])
        self.assertNotIn("DO-NOT-PRINT", json.dumps(first))

    def test_project_registration_uses_local_scope_and_exact_registered_root(self) -> None:
        with patch.dict(os.environ, {"COMPANY_AGENT_SCOPE": "Project", "COMPANY_AGENT_PROJECT_ROOT": str(self.project)}), \
                patch.object(native.Path, "cwd", return_value=self.project / "src"), \
                patch.object(native, "_claude_argv", return_value=["claude.exe"]), \
                patch.object(native.subprocess, "run", side_effect=self.fake_add) as child:
            result = native.sync_native_mcp(self.state, self.name)
        self.assertEqual("local", result["scope"])
        self.assertEqual(str(self.project), child.call_args.kwargs["cwd"])
        self.assertEqual("local", child.call_args.args[0][-1])
        self.assertFalse((self.project / ".mcp.json").exists())

    def test_external_same_name_and_cross_scope_collisions_are_preserved(self) -> None:
        for document in (
            {"mcpServers": {self.name: self.desired}},
            {"projects": {str(self.project): {"mcpServers": {self.name: self.desired}}}},
        ):
            atomic_write_json(native._config_file(), document)
            with patch.object(native.subprocess, "run") as child, self.assertRaisesRegex(ValueError, "existing"):
                native.sync_native_mcp(self.state, self.name)
            child.assert_not_called()
            self.assertEqual(document, load_json(native._config_file()))

    def test_changed_owned_entry_and_reserved_names_are_never_replaced(self) -> None:
        with patch.object(native, "_claude_argv", return_value=["claude.exe"]), patch.object(native.subprocess, "run", side_effect=self.fake_add):
            native.sync_native_mcp(self.state, self.name)
        changed = {**self.desired, "args": ["external-server.py"]}
        atomic_write_json(native._config_file(), {"mcpServers": {self.name: changed}})
        with patch.object(native.subprocess, "run") as child:
            with self.assertRaisesRegex(ValueError, "changed"):
                native.sync_native_mcp(self.state, self.name)
            for name in ("corp-db-read", "corp-outlook-self"):
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "reserved"):
                    native.sync_native_mcp(self.state, name)
        child.assert_not_called()
        self.assertEqual(changed, load_json(native._config_file())["mcpServers"][self.name])

    def test_stale_receipt_and_registry_tampering_cannot_register(self) -> None:
        server = self.asset / "server.py"
        original = server.read_bytes()
        server.write_bytes(original + b"\n# changed after protocol validation\n")
        with patch.object(native.subprocess, "run") as child:
            with self.assertRaisesRegex(ValueError, "content changed"):
                native.sync_native_mcp(self.state, self.name)
            server.write_bytes(original)
            atomic_write_json(self.state / "mcp" / "registry.json", {"mcpServers": {self.name: {**self.desired, "env": {"SECRET": "unsafe"}}}})
            with self.assertRaisesRegex(ValueError, "registry differs"):
                native.sync_native_mcp(self.state, self.name)
        child.assert_not_called()

    def test_runtime_rebind_reports_owned_old_runtime_without_removing_native_settings(self) -> None:
        with patch.object(native, "_claude_argv", return_value=["claude.exe"]), patch.object(native.subprocess, "run", side_effect=self.fake_add):
            native.sync_native_mcp(self.state, self.name)
        old_native = native._config_file().read_bytes()
        next_runtime = str(self.root / "releases" / "next" / "python.exe")
        with patch.object(assets.sys, "executable", next_runtime), \
                patch.object(assets, "_approved_mcp_sdk_version", return_value="1.26.0"), \
                patch.object(assets, "_probe_mcp", new_callable=AsyncMock, return_value={"healthTool": "health"}):
            renewed = assets.rebind_mcp_runtime(self.state, self.name)
            assets.activate_mcp(self.state, self.name, renewed)
            with patch.object(native.subprocess, "run") as child, self.assertRaisesRegex(ValueError, "previously validated") as caught:
                native.sync_native_mcp(self.state, self.name)
            child.assert_not_called()
            self.assertIn("sync-mcp --name " + self.name, str(caught.exception))
            self.assertEqual(old_native, native._config_file().read_bytes())
            self.assertNotIn("DO-NOT-PRINT", str(caught.exception))

            # Emulate the user's explicit removal of ONLY this personal entry;
            # sync then uses the newly validated runtime without any health probe.
            document = load_json(native._config_file())
            document["mcpServers"].pop(self.name)
            document["mcpServers"]["other-personal"] = {"command": "untouched.exe"}
            atomic_write_json(native._config_file(), document)
            with patch.object(native, "_claude_argv", return_value=["claude.exe"]), \
                    patch.object(native.subprocess, "run", side_effect=self.fake_add) as add:
                report = native.sync_native_mcp(self.state, self.name)
                self.assertEqual("registered", report["status"])
                self.assertEqual(1, add.call_count)
            registered = load_json(native._config_file())["mcpServers"]
            self.assertEqual(next_runtime, registered[self.name]["command"])
            self.assertEqual({"command": "untouched.exe"}, registered["other-personal"])

    def test_registration_failure_never_echoes_sensitive_output_or_claims_success(self) -> None:
        failure = subprocess.CompletedProcess([], 1, b"DO-NOT-PRINT-CREDENTIAL", b"DO-NOT-PRINT-CREDENTIAL")
        with patch.object(native, "_claude_argv", return_value=["claude.exe"]), patch.object(native.subprocess, "run", return_value=failure):
            with self.assertRaises(ValueError) as caught:
                native.sync_native_mcp(self.state, self.name)
        self.assertNotIn("DO-NOT-PRINT", str(caught.exception))
        pending = load_json(self.state / "mcp" / "native-registrations.json")
        self.assertEqual("pending", next(iter(pending["entries"].values()))["status"])
        self.assertEqual("active", load_json(self.asset / "asset.json")["status"])

    def test_timeout_after_config_write_can_be_retried_without_duplicate_registration(self) -> None:
        def interrupted_add(argv, **kwargs):
            self.fake_add(argv, **kwargs)
            raise subprocess.TimeoutExpired(argv, 30)
        with patch.object(native, "_claude_argv", return_value=["claude.exe"]), patch.object(native.subprocess, "run", side_effect=interrupted_add):
            with self.assertRaisesRegex(ValueError, "pending"):
                native.sync_native_mcp(self.state, self.name)
        with patch.object(native.subprocess, "run") as child:
            result = native.sync_native_mcp(self.state, self.name)
        child.assert_not_called()
        self.assertEqual("already-registered", result["status"])
        ownership = load_json(self.state / "mcp" / "native-registrations.json")
        self.assertEqual("registered", next(iter(ownership["entries"].values()))["status"])

    def test_npm_shim_resolves_only_official_package_bin_without_a_shell(self) -> None:
        npm = self.root / "npm"
        package = npm / "node_modules" / "@anthropic-ai" / "claude-code"
        executable = package / "bin" / "claude.exe"
        executable.parent.mkdir(parents=True)
        executable.touch()
        atomic_write_json(package / "package.json", {"name": "@anthropic-ai/claude-code", "bin": {"claude": "bin/claude.exe"}})
        with patch.dict(os.environ, {"COMPANY_AGENT_CLAUDE_COMMAND": str(npm / "claude.cmd")}), \
                patch.object(native.shutil, "which", return_value=None):
            self.assertEqual([str(executable.resolve())], native._claude_argv())
            atomic_write_json(package / "package.json", {"name": "not-the-official-package", "bin": {"claude": "bin/claude.exe"}})
            with self.assertRaisesRegex(ValueError, "unavailable"):
                native._claude_argv()

    @unittest.skipUnless(os.name == "nt" and os.environ.get("COMPANY_AGENT_TEST_REAL_CLAUDE") == "1", "Opt-in isolated real Claude configuration check")
    def test_real_claude_add_json_uses_isolated_config_and_correct_scope(self) -> None:
        # add-json only writes configuration. Never use get/list here because
        # those commands may connect to the generated MCP server.
        native._claude_argv()
        for scope in ("User", "Project"):
            with self.subTest(scope=scope), patch.dict(os.environ, {
                "CLAUDE_CONFIG_DIR": str(self.root / ("isolated-" + scope)),
                "COMPANY_AGENT_SCOPE": scope, "COMPANY_AGENT_PROJECT_ROOT": str(self.project),
                "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1", "DISABLE_AUTOUPDATER": "1",
            }), patch.object(native.Path, "cwd", return_value=self.project):
                report = native.sync_native_mcp(self.state, self.name)
                self.assertTrue(report["ok"])
                self.assertEqual("registered", report["status"])
                self.assertTrue(native._config_file().is_file())
                report = native.sync_native_mcp(self.state, self.name)
                self.assertEqual("already-registered", report["status"])


if __name__ == "__main__":
    unittest.main()
