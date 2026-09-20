"""Portable business tools with a small local stdio adapter, not a new runtime."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re

FORMAT = "platform-tools-v1"
REQUIREMENT = ">=1.28,<2"
TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
MAX_CASE_BYTES = 64 * 1024

DEFAULT_TOOLS = '''"""Portable business code; the platform supplies the MCP server."""
from mcp.server.fastmcp import FastMCP

def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def echo(message: str) -> str:
        """Return a synthetic message of at most 4096 characters."""
        if len(message) > 4096:
            raise ValueError("message exceeds 4096 characters")
        return message
'''


def validate_tools_source(code: str) -> None:
    tree = ast.parse(code)
    definitions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "register_tools"]
    if len(definitions) != 1 or [a.arg for a in definitions[0].args.args] != ["mcp"]:
        raise ValueError("tools_code must define register_tools(mcp: FastMCP) -> None")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "tool":
                    positional = decorator.args[0].value if decorator.args and isinstance(decorator.args[0], ast.Constant) else node.name
                    published = next((k.value.value for k in decorator.keywords
                                      if k.arg == "name" and isinstance(k.value, ast.Constant)), positional)
                    if published == "health":
                        raise ValueError("health is reserved for the local adapter")
        modules = ([n.name for n in node.names] if isinstance(node, ast.Import)
                   else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        if any(m == "company_agent" or m.startswith("company_agent.") for m in modules):
            raise ValueError("Portable tools must not import Company Agent runtime modules")


def validate_cases(value: object) -> list[dict]:
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        raise ValueError("tool_tests needs 1..32 explicit synthetic business test cases")
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_CASE_BYTES:
        raise ValueError("tool_tests exceeds the 64 KiB limit")
    for case in value:
        if not isinstance(case, dict) or set(case) - {"tool", "arguments", "expect", "is_error"}:
            raise ValueError("Invalid tool_tests case fields")
        if not isinstance(case.get("tool"), str) or not TOOL_NAME.fullmatch(case["tool"]) or case["tool"] == "health":
            raise ValueError("tool_tests must name a business tool, not health")
        if not isinstance(case.get("arguments"), dict) or not isinstance(case.get("is_error", False), bool):
            raise ValueError("tool_tests arguments must be an object and is_error a boolean")
        if not case.get("is_error", False):
            expected = case.get("expect")
            if not isinstance(expected, dict) or len(expected) != 1 or not set(expected) <= {"text", "json", "json_schema"}:
                raise ValueError("Successful tool_tests need one expect: text, json, or json_schema")
            if "text" in expected and not isinstance(expected["text"], str):
                raise ValueError("Expected text must be a string")
            if "json_schema" in expected:
                from .asset_factory import _validate_schema_definition
                _validate_schema_definition(expected["json_schema"], "tool_tests json_schema")
            if "json" in expected:
                from .asset_factory import _validate_json_literal
                _validate_json_literal(expected['json'], 'tool_tests json')
    return value


def platform_files(spec: dict, name: str) -> dict[str, str]:
    code = spec.get("tools_code", DEFAULT_TOOLS)
    if not isinstance(code, str) or not code.strip():
        raise ValueError("tools_code must be nonempty Python source")
    validate_tools_source(code)
    defaults = [
        {"tool": "echo", "arguments": {"message": "한글 연결 시험"}, "expect": {"text": "한글 연결 시험"}},
        {"tool": "echo", "arguments": {}, "is_error": True},
    ]
    cases = validate_cases(spec.get("tool_tests", defaults if "tools_code" not in spec else None))
    server = f'''"""Local adapter only; submit src/mcp/tools.py, not this file."""
import os
from importlib.metadata import version
from mcp.server.fastmcp import FastMCP
from src.mcp.tools import register_tools

sdk = tuple(int(x) for x in version("mcp").split(".")[:2])
if not (sdk[0] == 1 and sdk >= (1, 28)):
    raise RuntimeError("Approved mcp>=1.28,<2 is required; no packages were installed")
server = FastMCP({name!r})
register_tools(server)

@server.tool()
def health() -> dict:
    """Local connection check only, not a business test."""
    return {{"ok": True}}

if __name__ == "__main__":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    server.run(transport="stdio")
'''
    return {
        "server.py": server,
        "src/__init__.py": "",
        "src/mcp/__init__.py": "",
        "src/mcp/tools.py": code.rstrip() + "\n",
        "config.py": '"""Local synthetic config, never an enterprise credential store."""\n'
                     'from types import SimpleNamespace\ncfg = SimpleNamespace(SERVICE_NAME=' + repr(name) + ')\n',
        "tool-tests.json": json.dumps(cases, ensure_ascii=False, indent=2) + "\n",
        "requirements-local.txt": "# Use approved offline packages; do not install automatically.\nmcp>=1.28,<2\n",
    }


def platform_cases(root: Path, manifest: dict) -> list[dict] | None:
    if manifest.get("format") != FORMAT:
        return None
    for relative in ("src/__init__.py", "src/mcp/__init__.py", "src/mcp/tools.py", "config.py", "tool-tests.json"):
        target = root / relative
        if not target.resolve().is_relative_to(root.resolve()) or not target.is_file():
            raise ValueError("Platform MCP file missing or outside its asset: " + relative)
    path = root / "tool-tests.json"
    if path.stat().st_size > MAX_CASE_BYTES:
        raise ValueError("tool-tests.json exceeds the 64 KiB limit")
    validate_tools_source((root / "src/mcp/tools.py").read_text(encoding="utf-8"))
    return validate_cases(json.loads(path.read_text(encoding="utf-8")))


async def test_business_tools(session, listed, cases: list[dict]) -> dict:
    """Only call explicitly specified synthetic cases; never probe arbitrary tools."""
    from .asset_factory import _validate_json_value, _validate_json_literal, _json_equal, MAX_JSON_OUTPUT_BYTES
    tools = {str(item.name): item for item in listed.tools if item.name != "health"}
    if not tools or set(c["tool"] for c in cases) - tools.keys():
        raise ValueError("Business tests reference missing tools or no business tools were listed")
    for name, tool in tools.items():
        matched = [c for c in cases if c["tool"] == name]
        if not any(not c.get("is_error", False) for c in matched):
            raise ValueError("A successful business test is required for " + name)
        if tool.inputSchema.get("required") and not any(c.get("is_error", False) for c in matched):
            raise ValueError("An invalid-input business test is required for " + name)
    for index, case in enumerate(cases):
        result = await session.call_tool(case["tool"], case["arguments"])
        if bool(result.isError) != case.get("is_error", False):
            raise ValueError(f"Business test {index + 1}: unexpected success/error state")
        if result.isError:
            continue
        text = "\n".join(block.text for block in result.content if getattr(block, "type", "") == "text")
        if len(text.encode("utf-8")) > MAX_JSON_OUTPUT_BYTES:
            raise ValueError("Business test response exceeds the output limit")
        expected = case["expect"]
        if "text" in expected:
            matches = text == expected["text"]
        else:
            try:
                value = json.loads(text)
            except ValueError:
                raise ValueError(f"Business test {index + 1}: invalid JSON result") from None
            matches = True
            if "json" in expected:
                _validate_json_literal(value, 'business result')
                matches = _json_equal(value, expected["json"])
            else:
                _validate_json_value(value, expected["json_schema"])
        if not matches:
            raise ValueError(f"Business test {index + 1}: result differs from expected value")
    return {"businessTestCount": len(cases), "businessTools": sorted(tools), "schemaValidationVersion": 1}


def verify_business_receipt(root: Path, manifest: dict, receipt: dict) -> None:
    if manifest.get("format") != FORMAT:
        return
    cases = platform_cases(root, manifest)
    details = receipt.get("details", {})
    expected = sorted({c["tool"] for c in cases})
    if (details.get("businessTestCount") != len(cases) or details.get("businessTools") != expected
            or any(t not in details.get("toolSchemas", {}) for t in expected)):
        raise ValueError("Platform MCP needs current business test evidence, not only a health check")
    if any(set(c.get('expect', {})) & {'json', 'json_schema'} for c in cases) and details.get('schemaValidationVersion') != 1:
        raise ValueError("JSON business tests need a current validation receipt; re-test MCP")
