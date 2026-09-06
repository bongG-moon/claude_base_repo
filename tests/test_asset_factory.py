from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from company_agent.asset_factory import (  # noqa: E402
    activate_mcp,
    activate_script_tool,
    create_asset,
    rebind_mcp_runtime,
    run_script_tool,
    validate_asset,
    validate_mcp_runtime,
    validate_script_tool_runtime,
)
from company_agent import asset_factory as assets  # noqa: E402
from company_agent.paths import ensure_user_layout  # noqa: E402
from company_agent.cli import build_parser  # noqa: E402


class AssetFactoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create_counter(self) -> Path:
        return create_asset(
            {
                "type": "script-tool",
                "name": "row-counter",
                "description": "JSON 행 개수를 센다.",
                "code": (
                    "import json, sys\n"
                    "payload=json.load(sys.stdin)\n"
                    "json.dump({'count': len(payload['rows'])}, sys.stdout)\n"
                ),
                "input_schema": {
                    "type": "object",
                    "required": ["rows"],
                    "properties": {"rows": {"type": "array"}},
                },
                "output_schema": {
                    "type": "object",
                    "required": ["count"],
                    "properties": {"count": {"type": "integer"}},
                },
            },
            self.state,
        )

    def _counter_input(self) -> Path:
        input_path = self.state / "input.json"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text('{"rows":[1,2,3]}', encoding="utf-8")
        return input_path

    def test_personal_skill_is_created_active(self) -> None:
        path = create_asset(
            {
                "type": "skill",
                "name": "daily-summary",
                "description": "매일 업무 요약을 만든다.",
                "instructions": "입력된 업무를 세 문장으로 요약한다.",
                "knowledge_dependencies": ["term.work.summary"],
            },
            self.state,
        )
        self.assertTrue((path / "SKILL.md").exists())
        self.assertTrue(validate_asset(path)["ok"])
        registry = json.loads((self.state / "assets" / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual("active", registry["assets"][0]["status"])

        create_asset(
            {
                "type": "skill",
                "name": "daily-summary",
                "description": "매일 업무 요약을 만든다.",
                "instructions": "입력된 업무를 다섯 문장으로 요약한다.",
            },
            self.state,
        )
        self.assertEqual(1, len(list((self.state / "assets" / "versions").rglob("SKILL.md"))))

    def test_personal_skill_refuses_existing_global_name_collision(self) -> None:
        claude_root = Path(self.temp.name) / "existing-claude"
        existing = claude_root / "skills" / "daily-summary"
        existing.mkdir(parents=True)
        (existing / "SKILL.md").write_text("existing", encoding="utf-8")
        with mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": str(claude_root)}):
            with self.assertRaisesRegex(ValueError, "company-personal-daily-summary"):
                create_asset(
                    {
                        "type": "skill",
                        "name": "daily-summary",
                        "description": "충돌 테스트",
                        "instructions": "테스트",
                    },
                    self.state,
                )

    def test_script_tool_is_candidate_and_compiles(self) -> None:
        path = self._create_counter()
        self.assertEqual("candidate", json.loads((path / "tool.json").read_text(encoding="utf-8"))["status"])
        self.assertTrue(validate_asset(path)["ok"])
        receipt = validate_script_tool_runtime(self.state, "row-counter", self._counter_input(), timeout=5)
        receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual("script-runtime", receipt_payload["receiptType"])
        self.assertIn("assetHash", receipt_payload)
        self.assertNotIn("rows", json.dumps(receipt_payload))
        skill_path = activate_script_tool(self.state, "row-counter", receipt)
        self.assertTrue((skill_path / "SKILL.md").exists())
        result = run_script_tool(self.state, "row-counter", self._counter_input())
        self.assertEqual(3, result["result"]["count"])

    def test_dangerous_dynamic_code_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "security review"):
            create_asset(
                {
                    "type": "script-tool",
                    "name": "unsafe-tool",
                    "description": "unsafe",
                    "code": "eval(input())",
                },
                self.state,
            )

        with self.assertRaisesRegex(ValueError, "process isolation"):
            create_asset(
                {
                    "type": "script-tool",
                    "name": "shell-tool",
                    "description": "unsafe shell",
                    "code": "import os\nos.system('whoami')\n",
                    "reviewed_capabilities": ["shell"],
                },
                self.state,
            )

    def test_risky_process_import_requires_explicit_capability(self) -> None:
        spec = {
            "type": "script-tool",
            "name": "process-tool",
            "description": "process runner",
            "code": "import json, subprocess, sys\njson.dump({'ok': True}, sys.stdout)\n",
        }
        with self.assertRaisesRegex(ValueError, "capability not reviewed"):
            create_asset(spec, self.state)
        spec["reviewed_capabilities"] = ["process"]
        path = create_asset(spec, self.state)
        self.assertEqual(["process"], json.loads((path / "tool.json").read_text(encoding="utf-8"))["reviewedCapabilities"])

    def test_fake_receipt_and_tampered_content_cannot_activate(self) -> None:
        path = self._create_counter()
        with self.assertRaisesRegex(ValueError, "validation receipt"):
            activate_script_tool(self.state, "row-counter", "tests passed")

        receipt_root = path / ".receipts"
        receipt_root.mkdir()
        fake = receipt_root / "fake.json"
        fake.write_text('{"receiptType":"script-runtime","signature":"fake"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "signature"):
            activate_script_tool(self.state, "row-counter", fake)

        receipt = validate_script_tool_runtime(self.state, "row-counter", self._counter_input(), timeout=5)
        (path / "main.py").write_text((path / "main.py").read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed after validation"):
            activate_script_tool(self.state, "row-counter", receipt)

        path = self._create_counter()
        receipt = validate_script_tool_runtime(self.state, "row-counter", self._counter_input(), timeout=5)
        manifest_path = path / "tool.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["description"] = "tampered after validation"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed after validation"):
            activate_script_tool(self.state, "row-counter", receipt)

    def test_names_and_manifest_entrypoints_are_confined(self) -> None:
        self._create_counter()
        with self.assertRaisesRegex(ValueError, "asset name"):
            activate_script_tool(self.state, "../row-counter", "anything")
        with self.assertRaisesRegex(ValueError, "asset name"):
            run_script_tool(self.state, "..\\row-counter", self._counter_input())

        manifest_path = self.state / "tools" / "row-counter" / "tool.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["entrypoint"] = "..\\outside.py"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = validate_asset(manifest_path.parent)
        self.assertFalse(result["ok"])
        self.assertTrue(any("entrypoint" in item for item in result["errors"]))

    def test_runtime_enforces_input_and_output_schema(self) -> None:
        self._create_counter()
        invalid = self.state / "invalid.json"
        invalid.write_text('{"wrong":[]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing required keys"):
            validate_script_tool_runtime(self.state, "row-counter", invalid)

    def test_mcp_requires_protocol_receipt_before_activation(self) -> None:
        path = create_asset(
            {
                "type": "mcp",
                "name": "hello-mcp",
                "description": "로컬 health 도구",
                "reviewed_capabilities": ["third-party-import"],
            },
            self.state,
        )
        self.assertEqual("candidate", json.loads((path / "asset.json").read_text(encoding="utf-8"))["status"])
        with self.assertRaisesRegex(ValueError, "receipt"):
            activate_mcp(self.state, "hello-mcp", "not-a-receipt")
        receipt = validate_mcp_runtime(self.state, "hello-mcp", timeout=10)
        registry_path = activate_mcp(self.state, "hello-mcp", receipt)
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        self.assertIn("hello-mcp", registry["mcpServers"])
        self.assertEqual(str(Path(sys.executable).resolve()), registry["mcpServers"]["hello-mcp"]["command"])

    def test_mcp_rejects_tampered_command(self) -> None:
        path = create_asset(
            {
                "type": "mcp",
                "name": "hello-mcp",
                "description": "로컬 health 도구",
                "reviewed_capabilities": ["third-party-import"],
            },
            self.state,
        )
        manifest_path = path / "asset.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["command"] = "powershell.exe"
        manifest["args"] = ["-Command", "Write-Output hacked"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "approved Company Agent Python"):
            validate_mcp_runtime(self.state, "hello-mcp")

    def _previous_runtime_mcp(self) -> tuple[Path, Path, str]:
        old_command = str(Path(self.temp.name) / "releases" / "old" / "python.exe")
        with mock.patch.object(assets.sys, "executable", old_command):
            path = create_asset({"type": "mcp", "name": "previous-mcp", "description": "Previous runtime fixture",
                                 "reviewed_capabilities": ["third-party-import"]}, self.state)
            receipt = assets._write_receipt(ensure_user_layout(self.state), path, "mcp-protocol", "mcp", "previous-mcp",
                                            assets._asset_content_hash(path, "asset.json"), {"fixture": True})
            activate_mcp(self.state, "previous-mcp", receipt)
        return path, receipt, old_command

    def test_runtime_rebind_requires_old_receipt_and_renews_hash_before_reactivation(self) -> None:
        path, old_receipt, old_command = self._previous_runtime_mcp()
        registry_path = self.state / "mcp" / "registry.json"
        original_registry = registry_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "rebind-mcp-runtime"):
            validate_mcp_runtime(self.state, "previous-mcp")
        with mock.patch.object(assets, "_probe_mcp", new_callable=mock.AsyncMock, return_value={"healthTool": "health"}) as probe, \
                mock.patch.object(assets, "_approved_mcp_sdk_version", return_value="1.26.0"):
            renewed = rebind_mcp_runtime(self.state, "previous-mcp", timeout=7)
        current_command = str(Path(sys.executable).resolve())
        self.assertEqual(current_command, probe.call_args.args[0])
        self.assertEqual([str((path / "server.py").resolve())], probe.call_args.args[1])
        self.assertEqual(7, probe.call_args.args[3])
        self.assertNotEqual(old_receipt, renewed)
        manifest = json.loads((path / "asset.json").read_text(encoding="utf-8"))
        self.assertEqual("candidate", manifest["status"])
        self.assertEqual(current_command, manifest["command"])
        self.assertEqual(old_command, manifest["runtimeRebind"]["previousCommand"])
        self.assertEqual(original_registry, registry_path.read_bytes())
        layout = ensure_user_layout(self.state)
        assets._verify_receipt(layout, path, renewed, "mcp-protocol", "mcp", "previous-mcp", "asset.json")
        with self.assertRaisesRegex(ValueError, "content changed"):
            assets._verify_receipt(layout, path, old_receipt, "mcp-protocol", "mcp", "previous-mcp", "asset.json")
        activate_mcp(self.state, "previous-mcp", renewed)
        self.assertEqual(current_command, json.loads(registry_path.read_text(encoding="utf-8"))["mcpServers"]["previous-mcp"]["command"])
        self.assertTrue(old_receipt.is_file())

    def test_runtime_rebind_probe_and_receipt_failures_preserve_previous_active_state(self) -> None:
        path, _, _ = self._previous_runtime_mcp()
        manifest_path = path / "asset.json"
        original = manifest_path.read_bytes()
        registry_path = self.state / "mcp" / "registry.json"
        registry = registry_path.read_bytes()
        for stage in ("probe", "receipt"):
            with self.subTest(stage=stage), \
                    mock.patch.object(assets, "_approved_mcp_sdk_version", return_value="1.26.0"), \
                    mock.patch.object(assets, "_probe_mcp", new_callable=mock.AsyncMock,
                                      side_effect=ValueError("probe failed") if stage == "probe" else None,
                                      return_value={"healthTool": "health"}), \
                    mock.patch.object(assets, "_write_receipt", side_effect=OSError("receipt unavailable")):
                with self.assertRaises((ValueError, OSError)):
                    rebind_mcp_runtime(self.state, "previous-mcp")
            self.assertEqual(original, manifest_path.read_bytes())
            self.assertEqual(registry, registry_path.read_bytes())

    def test_runtime_rebind_rejects_modified_unsigned_and_reserved_assets_without_execution(self) -> None:
        path, _, _ = self._previous_runtime_mcp()
        manifest_path = path / "asset.json"
        original = manifest_path.read_bytes()
        for alteration in ("command", "receipt"):
            manifest = json.loads(original)
            if alteration == "command":
                manifest["command"] = str(Path(self.temp.name) / "unapproved.exe")
            else:
                manifest.pop("validationReceipt")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            unchanged = manifest_path.read_bytes()
            with self.subTest(alteration=alteration), mock.patch.object(assets, "_probe_mcp", new_callable=mock.AsyncMock) as probe:
                with self.assertRaisesRegex(ValueError, "content changed|receipt"):
                    rebind_mcp_runtime(self.state, "previous-mcp")
                probe.assert_not_called()
            self.assertEqual(unchanged, manifest_path.read_bytes())
        for name in ("corp-db-read", "corp-outlook-self"):
            with self.assertRaisesRegex(ValueError, "managed separately"):
                rebind_mcp_runtime(self.state, name)

    def test_runtime_rebind_does_not_overwrite_concurrent_asset_changes(self) -> None:
        path, _, _ = self._previous_runtime_mcp()
        manifest_path = path / "asset.json"
        original = manifest_path.read_bytes()
        receipt_files = list((path / ".receipts").iterdir())

        async def changed_probe(*args):
            server = path / "server.py"
            server.write_bytes(server.read_bytes() + b"\n# concurrent personal edit\n")
            return {"healthTool": "health"}

        with mock.patch.object(assets, "_probe_mcp", side_effect=changed_probe), \
                mock.patch.object(assets, "_approved_mcp_sdk_version", return_value="1.26.0"):
            with self.assertRaisesRegex(ValueError, "changed during runtime rebind"):
                rebind_mcp_runtime(self.state, "previous-mcp")
        self.assertEqual(original, manifest_path.read_bytes())
        self.assertEqual(receipt_files, list((path / ".receipts").iterdir()))
        self.assertIn(b"concurrent personal edit", (path / "server.py").read_bytes())

    def test_cli_exposes_receipt_based_runtime_validation_flow(self) -> None:
        parser = build_parser()
        tool_args = parser.parse_args(
            [
                "asset",
                "test-tool",
                "--name",
                "row-counter",
                "--input",
                "input.json",
            ]
        )
        self.assertEqual("row-counter", tool_args.name)
        self.assertEqual(30, tool_args.timeout)

        activation_args = parser.parse_args(
            [
                "asset",
                "activate-tool",
                "--name",
                "row-counter",
                "--receipt",
                "receipt.json",
            ]
        )
        self.assertEqual("receipt.json", activation_args.receipt)


if __name__ == "__main__":
    unittest.main()
