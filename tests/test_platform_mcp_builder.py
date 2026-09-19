"""Company skill discovery and portable starter behavior; no profile changes."""
from __future__ import annotations

import ast
import asyncio
from datetime import timedelta
import hashlib
import importlib.util
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "company-agent-plugin"
SKILL = PLUGIN / "skills/platform-mcp-builder"
sys.path.insert(0, str(PLUGIN / "scripts"))
from company_agent.skill_registry import inventory_skills
from company_agent.skill_task_context import task_candidates

spec = importlib.util.spec_from_file_location("platform_starter", SKILL / "scripts/create_project.py")
starter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(starter)

try:
    sdk = tuple(int(part) for part in version("mcp").split(".")[:2])
    HAS_SDK = sdk[0] == 1 and sdk >= (1, 28) and bool(version("uvicorn"))
except (PackageNotFoundError, ValueError):
    HAS_SDK = False


class PlatformMcpBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="company-platform-mcp-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "한글 개발 폴더"

    def make_project(self):
        return starter.create_project(self.project)

    def run_python(self, *args, timeout=30):
        return subprocess.run([sys.executable, "-X", "utf8", "-B", *args], cwd=self.project,
                              capture_output=True, text=True, encoding="utf-8", timeout=timeout)

    def test_registered_as_common_skill_and_found_without_explicit_invocation(self):
        inventory = inventory_skills(self.root / "state", claude_root=self.root / "claude",
                                     plugin_root=PLUGIN)
        self.assertTrue(inventory["complete"])
        items = [x for x in inventory["skills"] if x["name"] == "platform-mcp-builder"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "company")
        self.assertEqual(items[0]["invocation"], "company-agent:platform-mcp-builder")
        self.assertFalse(items[0]["explicitOnly"])
        for prompt in ("전사 표준 MCP tools.py register_tools 형식으로 개발해줘",
                       "로컬에서 만든 MCP 도구를 회사 플랫폼에 제출하고 싶어"):
            groups = task_candidates(inventory, prompt)["groups"]
            self.assertIn("platform-mcp-builder", [g["name"] for g in groups])
        for prompt in ("기존 PPT 내용 읽고 요약해줘", "이 폴더에 온도 변환 코드를 작성해줘",
                       "개인 스킬 만들어줘"):
            groups = task_candidates(inventory, prompt)["groups"]
            self.assertNotIn("platform-mcp-builder", [g["name"] for g in groups])
        self.assertFalse((self.root / "state").exists())
        self.assertFalse((self.root / "claude").exists())

    def test_scaffold_copies_only_portable_source_and_local_support(self):
        result = self.make_project()
        self.assertFalse(result["registered"])
        self.assertFalse(result["platformVerified"])
        self.assertEqual({p.relative_to(self.project).as_posix() for p in self.project.rglob("*") if p.is_file()},
                         set(starter.FILES))
        for name in starter.FILES:
            path = self.project / name
            self.assertEqual(path.read_bytes(), (starter.TEMPLATE / name).read_bytes())
            if path.suffix == ".py":
                ast.parse(path.read_text(encoding="utf-8"))
        tools = ast.parse((self.project / "src/mcp/tools.py").read_text(encoding="utf-8"))
        register = next(n for n in tools.body if isinstance(n, ast.FunctionDef) and n.name == "register_tools")
        self.assertEqual([a.arg for a in register.args.args], ["mcp"])
        names = {n.name for n in register.body if isinstance(n, ast.AsyncFunctionDef)}
        self.assertEqual(names, {"echo", "get_server_info", "get_current_time"})
        for node in ast.walk(tools):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn("company_agent", node.module or "")
        # Two distinct destinations get identical business source, no embedded PC path.
        second = self.root / "another project"
        starter.create_project(second)
        self.assertEqual((second / "src/mcp/tools.py").read_bytes(), (self.project / "src/mcp/tools.py").read_bytes())

    def test_existing_folder_and_files_are_never_overwritten(self):
        self.make_project()
        tools = self.project / "src/mcp/tools.py"
        tools.write_text("# user changes\n", encoding="utf-8")
        before = {p.relative_to(self.project): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        with self.assertRaises(FileExistsError):
            self.make_project()
        self.assertEqual(before, {p.relative_to(self.project): p.read_bytes() for p in self.project.rglob("*") if p.is_file()})
        file = self.root / "existing.txt"
        file.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            starter.create_project(file)
        self.assertEqual(file.read_text(), "keep")

    def test_missing_parent_relative_and_incomplete_template_fail_before_creation(self):
        with self.assertRaises(ValueError):
            starter.create_project(Path("relative"))
        with self.assertRaises(FileNotFoundError):
            starter.create_project(self.root / "missing" / "child")
        self.assertFalse((self.root / "missing").exists())
        with patch.object(starter, "FILES", (*starter.FILES, "absent.py")):
            with self.assertRaises(FileNotFoundError):
                self.make_project()
        self.assertFalse(self.project.exists())

    def test_entrypoint_and_contract_remain_on_demand(self):
        body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertLess(len(body), 4000)
        self.assertLess(len(body.splitlines()), 70)
        self.assertLess(len((SKILL / "references/platform-contract.md").read_text(encoding="utf-8").splitlines()), 45)
        hooks = (PLUGIN / "hooks/hooks.json").read_text(encoding="utf-8")
        self.assertNotIn("platform-mcp-builder", hooks)

    def test_local_sdk_preflight_explains_missing_or_incompatible_environment(self):
        server = starter.TEMPLATE / "local_server.py"
        for installed in ("1.20.0", "2.0.0"):
            with patch("importlib.metadata.version", return_value=installed):
                with self.assertRaisesRegex(RuntimeError, "환경을 자동 변경하지 않습니다"):
                    runpy.run_path(str(server), run_name="local_preflight_test")
        with patch("importlib.metadata.version", side_effect=PackageNotFoundError("mcp")):
            with self.assertRaisesRegex(RuntimeError, "승인된 Python 환경"):
                runpy.run_path(str(server), run_name="local_preflight_test")

    @unittest.skipUnless(HAS_SDK, "Approved MCP SDK 1.28+ (<2) and uvicorn are needed for execution tests")
    def test_generated_project_passes_real_http_protocol_and_input_tests(self):
        self.make_project()
        result = self.run_python("-m", "unittest", "-v", "test_tools")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Ran 2 tests", result.stderr)
        self.assertNotIn("skipped", result.stderr)

    @unittest.skipUnless(HAS_SDK, "Approved MCP SDK 1.28+ (<2) is needed for the platform contract test")
    def test_same_tools_file_loads_with_platform_supplied_config(self):
        self.make_project()
        tools = self.project / "src/mcp/tools.py"
        before = hashlib.sha256(tools.read_bytes()).hexdigest()
        # Simulate the supplied platform import boundary, not its unavailable deployment.
        code = """
import asyncio, json, sys, types
from mcp.server.fastmcp import FastMCP
config = types.ModuleType('config')
config.cfg = types.SimpleNamespace(SERVICE_NAME='전사 테스트 fixture')
sys.modules['config'] = config
from src.mcp.tools import register_tools
server = FastMCP('platform-fixture', stateless_http=True)
register_tools(server)
async def check():
    names = {t.name for t in await server.list_tools()}
    assert names == {'echo', 'get_server_info', 'get_current_time'}
    value = await server.call_tool('get_server_info', {})
    content = value[0] if isinstance(value, tuple) else value
    assert json.loads(content[0].text)['name'] == config.cfg.SERVICE_NAME
    assert 'company_agent' not in sys.modules
asyncio.run(check())
"""
        result = self.run_python("-c", code)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(hashlib.sha256(tools.read_bytes()).hexdigest(), before)

    @unittest.skipUnless(HAS_SDK, "Approved MCP SDK 1.28+ (<2) and uvicorn are needed for localhost tests")
    def test_local_server_real_socket_and_owned_process_shutdown(self):
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        self.make_project()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-B", "local_server.py", "--port", str(port)],
            cwd=self.project, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            url = f"http://127.0.0.1:{port}"
            with httpx.Client(trust_env=False, timeout=0.5) as client:
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    self.assertIsNone(process.poll(), "Local server exited before health check")
                    try:
                        if client.get(url + "/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    self.fail("Local server did not become healthy")

            async def round_trip():
                async with (
                    asyncio.timeout(10),
                    httpx.AsyncClient(trust_env=False, timeout=5) as client,
                    streamable_http_client(url + "/mcp", http_client=client) as (read, write, _),
                    ClientSession(read, write, read_timeout_seconds=timedelta(seconds=5)) as session,
                ):
                    await session.initialize()
                    listing = await session.list_tools()
                    self.assertIn("echo", {t.name for t in listing.tools})
                    result = await session.call_tool("echo", {"message": "실제 로컬 연결"})
                    self.assertFalse(result.isError)
                    self.assertEqual(result.content[0].text, "실제 로컬 연결")

            asyncio.run(round_trip())
        finally:
            # Only terminate the exact process started by this test, never a port owner.
            if process.poll() is None:
                process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
        self.assertIsNotNone(process.returncode)


if __name__ == "__main__":
    unittest.main()
