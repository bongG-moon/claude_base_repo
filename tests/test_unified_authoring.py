"""Real MCP tests in isolated state, never the user's Claude profile or company service."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin/scripts"))
from company_agent import asset_factory as assets, native_mcp
from company_agent.cli import build_parser
from company_agent.paths import atomic_write_json, ensure_user_layout, load_json
from company_agent.platform_assets import FORMAT, validate_cases, validate_tools_source
from company_agent.skill_tool_dependencies import check_skill_dependencies

TOOLS = '''import json
from mcp.server.fastmcp import FastMCP
from pydantic import StrictInt

def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def sum_values(values: list[StrictInt]) -> str:
        """Sum at most ten synthetic integers."""
        if not 1 <= len(values) <= 10:
            raise ValueError("provide 1..10 integers")
        return json.dumps({"total": sum(values)}, ensure_ascii=False)
'''
CASES = [
    {"tool": "sum_values", "arguments": {"values": [1, 2]}, "expect": {"json": {"total": 3}}},
    {"tool": "sum_values", "arguments": {}, "is_error": True},
    {"tool": "sum_values", "arguments": {"values": []}, "is_error": True},
]


class UnifiedAuthoringTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="company-tools-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "한글 폴더"
        self.root.mkdir()
        self.state = self.root / "state"
        self.project = self.root / "project"
        self.project.mkdir()
        env = patch.dict(os.environ, {
            "CLAUDE_CONFIG_DIR": str(self.root / "isolated-claude"), "COMPANY_AGENT_SCOPE": "User",
            "COMPANY_AGENT_USER_STATE": str(self.state), "COMPANY_AGENT_PROJECT_ROOT": "",
        })
        env.start()
        self.addCleanup(env.stop)

    def spec(self, **changes):
        return {"type": "mcp", "format": FORMAT, "name": "sample-tools", "description": "가상 합계",
                "tools_code": TOOLS, "tool_tests": CASES,
                "reviewed_capabilities": ["third-party-import"], **changes}

    def active(self, **changes):
        spec = self.spec(**changes)
        path = assets.create_asset(spec, self.state)
        receipt = assets.validate_mcp_runtime(self.state, spec["name"], timeout=15)
        assets.activate_mcp(self.state, spec["name"], receipt)
        return path, receipt

    def skill(self, **changes):
        return assets.create_asset({"type": "skill", "name": "sample-report", "description": "합계 설명",
            "instructions": "합계 도구를 호출하고 결과만 설명한다.",
            "tool_dependencies": [{"server": "sample-tools", "tools": ["sum_values"]}], **changes}, self.state)

    def register_fixture(self, local=False):
        desired = load_json(self.state / "mcp/registry.json")["mcpServers"]["sample-tools"]
        document = {"mcpServers": {"unrelated": {"command": "keep"}, "sample-tools": desired}}
        if local:
            document = {"projects": {str(self.project): document}}
        atomic_write_json(native_mcp._config_file(), document)
        return document

    def test_default_legacy_is_preserved_and_platform_source_is_portable(self):
        path = assets.create_asset(self.spec(), self.state)
        manifest = load_json(path / "asset.json")
        self.assertEqual(FORMAT, manifest["format"])
        self.assertEqual(">=1.28,<2", manifest["mcpRequirement"])
        self.assertEqual(TOOLS, (path / "src/mcp/tools.py").read_text(encoding="utf-8"))
        self.assertTrue(assets.validate_asset(path)["ok"])
        self.assertNotIn("company_agent", (path / "src/mcp/tools.py").read_text())
        self.assertNotIn("http", (path / "server.py").read_text())
        legacy = assets.create_asset({"type": "mcp", "name": "old-tools", "description": "legacy",
            "reviewed_capabilities": ["third-party-import"]}, self.state)
        self.assertNotIn("format", load_json(legacy / "asset.json"))
        before = (path / "asset.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "format is preserved"):
            assets.create_asset({"type": "mcp", "name": "sample-tools", "description": "legacy"}, self.state)
        self.assertEqual(before, (path / "asset.json").read_bytes())

    def test_real_protocol_business_checks_and_read_only_bound_skill(self):
        path, receipt = self.active()
        details = load_json(receipt)["details"]
        self.assertEqual(3, details["businessTestCount"])
        self.assertEqual(["sum_values"], details["businessTools"])
        self.assertIn("values", details["toolSchemas"]["sum_values"]["required"])
        self.assertNotIn('"total": 3', receipt.read_text())
        skill = self.skill()
        self.assertIn("asset check-skill", (skill / "SKILL.md").read_text(encoding="utf-8"))
        self.assertTrue(assets.validate_asset(skill)["ok"])
        original = self.register_fixture()
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch.object(assets, "_probe_mcp") as probe, patch.object(native_mcp.subprocess, "run") as child:
            result = check_skill_dependencies(self.state, "sample-report", self.project)
        self.assertTrue(result["ok"], result)
        self.assertEqual("not-checked", result["liveConnection"])
        probe.assert_not_called()
        child.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.assertEqual(original, load_json(native_mcp._config_file()))

    def test_business_test_failure_produces_no_receipt_or_active_entry(self):
        path = assets.create_asset(self.spec(tool_tests=[{**CASES[0], "expect": {"json": {"total": 99}}}, CASES[1]]), self.state)
        with self.assertRaises(ValueError):
            assets.validate_mcp_runtime(self.state, "sample-tools", timeout=15)
        self.assertEqual([], list(path.glob(".receipts/*.json")))
        self.assertEqual("candidate", load_json(path / "asset.json")["status"])
        self.assertNotIn("sample-tools", load_json(self.state / "mcp/registry.json", {}).get("mcpServers", {}))

    def test_missing_invalid_input_or_unknown_business_case_cannot_pass(self):
        for cases in ([CASES[0]], [{**CASES[0], "tool": "absent"}, CASES[1]]):
            with self.subTest(cases=cases):
                assets.create_asset(self.spec(tool_tests=cases), self.state)
                with self.assertRaises(ValueError):
                    assets.validate_mcp_runtime(self.state, "sample-tools", timeout=15)

    def test_health_only_receipt_cannot_activate_platform_tool(self):
        path = assets.create_asset(self.spec(), self.state)
        receipt = assets._write_receipt(ensure_user_layout(self.state), path, "mcp-protocol", "mcp", "sample-tools",
                                        assets._asset_content_hash(path, "asset.json"), {"healthTool": "health"})
        with self.assertRaisesRegex(ValueError, "business test evidence"):
            assets.activate_mcp(self.state, "sample-tools", receipt)

    def test_missing_inactive_and_wrong_tool_names_do_not_create_skill(self):
        for setup in (False, True):
            if setup:
                assets.create_asset(self.spec(), self.state)
            with self.assertRaises((ValueError, FileNotFoundError)):
                self.skill()
        self.active()
        with self.assertRaisesRegex(ValueError, "missing from validated schemas"):
            self.skill(tool_dependencies=[{"server": "sample-tools", "tools": ["absent"]}])
        self.assertFalse((self.state / "personal-root/.claude/skills/sample-report").exists())

    def test_missing_native_conflict_and_project_scope_do_not_claim_connected(self):
        self.active()
        self.skill()
        result = check_skill_dependencies(self.state, "sample-report", self.project)
        self.assertFalse(result["ok"])
        self.assertEqual("not-registered", result["dependencies"][0]["nativeRegistration"])
        self.register_fixture(local=True)
        self.assertTrue(check_skill_dependencies(self.state, "sample-report", self.project)["ok"])
        elsewhere = self.root / "other-project"
        elsewhere.mkdir()
        self.assertFalse(check_skill_dependencies(self.state, "sample-report", elsewhere)["ok"])
        self.register_fixture()
        atomic_write_json(self.project / ".mcp.json", {"mcpServers": {"sample-tools": {"command": "other"}}})
        self.assertFalse(check_skill_dependencies(self.state, "sample-report", self.project)["ok"])

    def test_source_change_invalidates_then_retest_requires_explicit_skill_rebind(self):
        path, _ = self.active()
        skill = self.skill()
        original = (skill / "tool-dependencies.json").read_bytes()
        assets.create_asset({"type": "skill", "name": "sample-report", "description": "문구 수정",
            "instructions": "요약만 한다."}, self.state)
        self.assertEqual(original, (skill / "tool-dependencies.json").read_bytes())
        source = path / "src/mcp/tools.py"
        source.write_text(TOOLS + "\n# reviewed change\n", encoding="utf-8")
        self.assertFalse(check_skill_dependencies(self.state, "sample-report")["ok"])
        renewed = assets.validate_mcp_runtime(self.state, "sample-tools", timeout=15)
        assets.activate_mcp(self.state, "sample-tools", renewed)
        self.assertFalse(check_skill_dependencies(self.state, "sample-report")["ok"])
        with self.assertRaisesRegex(ValueError, "explicitly review"):
            assets.create_asset({"type": "skill", "name": "sample-report", "description": "수정",
                "instructions": "도구는 그대로 사용한다."}, self.state)
        self.skill()
        self.assertTrue(check_skill_dependencies(self.state, "sample-report")["ok"])
        self.assertNotEqual(original, (skill / "tool-dependencies.json").read_bytes())

    def test_launcher_registry_and_explicit_dependency_removal(self):
        self.active()
        skill = self.skill()
        with patch.dict(os.environ, {"COMPANY_AGENT_SCOPE": "Machine"}):
            result = check_skill_dependencies(self.state, "sample-report", self.project)
        self.assertTrue(result["ok"])
        self.assertEqual("launcher-registry", result["dependencies"][0]["nativeRegistration"])
        self.skill(tool_dependencies=[])
        self.assertFalse((skill / "tool-dependencies.json").exists())
        self.assertNotIn("asset check-skill", (skill / "SKILL.md").read_text(encoding="utf-8"))

    def test_dependency_validation_has_bounded_names_and_malformed_settings_fail_closed(self):
        for dependencies in ([{"server": None, "tools": ["sum_values"]}],
                             [{"server": "sample-tools", "tools": ["health"]}],
                             [{"server": "../outside", "tools": ["sum_values"]}],
                             [{"server": "sample-tools", "tools": ["sum_values"]}] * 9):
            with self.subTest(dependencies=dependencies), self.assertRaises(ValueError):
                self.skill(tool_dependencies=dependencies)
        atomic_write_json(native_mcp._config_file(), {"projects": []})
        with self.assertRaisesRegex(ValueError, "JSON object"):
            native_mcp.registration_status("sample-tools", {}, self.project)

    def test_invalid_specs_are_rejected_without_overwriting_existing_source(self):
        path = assets.create_asset(self.spec(), self.state)
        before = (path / "src/mcp/tools.py").read_bytes()
        for changes in ({"tools_code": "def wrong(): pass"}, {"tools_code": TOOLS + "\neval('1')"},
                        {"server_code": "ignored"}, {"tool_tests": []}, {"reviewed_capabilities": []}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                assets.create_asset(self.spec(**changes), self.state)
            self.assertEqual(before, (path / "src/mcp/tools.py").read_bytes())
        for code in (TOOLS.replace("sum_values", "health"), TOOLS.replace("@mcp.tool()", '@mcp.tool(name="health")'),
                     TOOLS.replace("@mcp.tool()", '@mcp.tool("health")'),
                     TOOLS + "\nimport company_agent.cli\n"):
            with self.assertRaises(ValueError):
                validate_tools_source(code)
        for cases in ([], [CASES[0]] * 33, [{**CASES[0], "tool": "health"}], [{**CASES[0], "arguments": "bad"}]):
            with self.assertRaises(ValueError):
                validate_cases(cases)

    def test_inspection_of_missing_skill_never_creates_state(self):
        missing = self.root / "absent"
        self.assertFalse(check_skill_dependencies(missing, "sample-report", self.project)["ok"])
        self.assertFalse(missing.exists())
        args = build_parser().parse_args(["asset", "check-skill", "--name", "sample-report",
                                         "--state-root", str(missing), "--project-root", str(self.project)])
        self.assertEqual(str(self.project), args.project_root)

    def test_platform_sdk_version_rejected_without_server_or_install(self):
        assets.create_asset(self.spec(), self.state)
        with patch.object(assets, "_approved_mcp_sdk_version", return_value="1.26.0"), \
                patch.object(assets, "_probe_mcp") as probe:
            with self.assertRaisesRegex(ValueError, "1.28"):
                assets.validate_mcp_runtime(self.state, "sample-tools")
            probe.assert_not_called()

    def test_generated_business_source_registers_without_harness_in_http_host(self):
        path = assets.create_asset(self.spec(), self.state)
        code = '''import asyncio, json, sys
from mcp.server.fastmcp import FastMCP
from src.mcp.tools import register_tools
server = FastMCP('independent-http', stateless_http=True)
register_tools(server)
app = server.streamable_http_app()
async def check():
    assert [t.name for t in await server.list_tools()] == ['sum_values']
    result = await server.call_tool('sum_values', {'values':[2,4]})
    content = result[0] if isinstance(result, tuple) else result
    assert json.loads(content[0].text) == {'total':6}
    assert 'company_agent' not in sys.modules
asyncio.run(check())
'''
        result = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", code], cwd=path,
                                capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)

    @unittest.skipUnless(os.environ.get("COMPANY_AGENT_TEST_REAL_CLAUDE") == "1", "Opt-in isolated native CLI workflow")
    def test_cli_project_workflow_from_creation_through_native_registration_and_skill_binding(self):
        from company_agent.resource_scope import selected_root
        native_mcp._claude_argv()
        scoped = selected_root(self.state, self.project, "project")
        spec_file = self.root / "도구 입력.json"
        atomic_write_json(spec_file, self.spec())
        scope = ["--state-root", str(self.state), "--storage-scope", "project", "--project-root", str(self.project)]
        env = {**os.environ, "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1", "DISABLE_AUTOUPDATER": "1"}

        def cli(*args):
            completed = subprocess.run([sys.executable, "-X", "utf8", "-B",
                str(ROOT / "company-agent-plugin/scripts/harness_cli.py"), "asset", *args],
                cwd=self.project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            return json.loads(completed.stdout)

        created = cli("create", "--spec", str(spec_file), *scope)
        self.assertTrue(Path(created["path"]).is_relative_to(scoped))
        checked = cli("test-mcp", "--name", "sample-tools", "--timeout", "15", *scope)
        connected = cli("activate-mcp", "--name", "sample-tools", "--receipt", checked["receipt"], *scope)
        self.assertEqual("local", connected["nativeRegistration"]["scope"])
        self.assertTrue(connected["nativeRegistration"]["restartRequired"])
        atomic_write_json(spec_file, {"type": "skill", "name": "sample-report", "description": "가상 합계",
            "instructions": "sum_values 결과를 설명한다.",
            "tool_dependencies": [{"server": "sample-tools", "tools": ["sum_values"]}]})
        cli("create", "--spec", str(spec_file), *scope)
        verified = cli("check-skill", "--name", "sample-report", "--state-root", str(scoped),
                       "--project-root", str(self.project))
        self.assertTrue(verified["ok"], verified)
        self.assertEqual("not-checked", verified["liveConnection"])
        self.assertFalse((self.project / ".mcp.json").exists())
        self.assertFalse((self.state / "mcp/servers/sample-tools").exists())


if __name__ == "__main__":
    unittest.main()
