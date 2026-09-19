from __future__ import annotations

import ast
import asyncio
import hashlib
import hmac
import importlib.metadata
import json
import os
import py_compile
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import atomic_write_json, atomic_write_text, ensure_user_layout, load_json


NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
ASSET_TYPES = {"skill", "script-tool", "mcp"}
VALIDATOR_VERSION = 1
MAX_RUNTIME_TIMEOUT = 120
MAX_JSON_INPUT_BYTES = 2 * 1024 * 1024
MAX_JSON_OUTPUT_BYTES = 4 * 1024 * 1024
MCP_REQUIREMENT = ">=1.20,<2"

REVIEWABLE_CAPABILITIES = {
    "filesystem-read",
    "filesystem-write",
    "network",
    "process",
    "third-party-import",
}
PROHIBITED_CAPABILITIES = {
    "destructive-filesystem",
    "dynamic-code",
    "native-code",
    "shell",
}
KNOWN_CAPABILITIES = REVIEWABLE_CAPABILITIES | PROHIBITED_CAPABILITIES

SAFE_IMPORT_ROOTS = {
    "__future__", "argparse", "ast", "asyncio", "base64", "collections", "csv",
    "dataclasses", "datetime", "decimal", "enum", "functools", "hashlib", "hmac",
    "io", "itertools", "json", "logging", "math", "operator", "os", "pathlib",
    "random", "re", "secrets", "statistics", "string", "sys", "tempfile",
    "textwrap", "time", "typing", "uuid",
}
NETWORK_IMPORT_ROOTS = {
    "aiohttp", "ftplib", "http", "requests", "smtplib", "socket", "telnetlib",
    "urllib", "webbrowser",
}
PROCESS_IMPORT_ROOTS = {"multiprocessing", "subprocess"}
NATIVE_IMPORT_ROOTS = {"ctypes"}

_MUTABLE_MANIFEST_FIELDS = {
    "activatedAt", "status", "validationEvidence", "validationReceipt",
}


@dataclass(frozen=True)
class CodeRisk:
    capability: str
    detail: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_name(name: str) -> None:
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError("asset name must match ^[a-z][a-z0-9-]{1,62}$")


def _assert_no_external_skill_collision(name: str, destination: Path) -> None:
    config_value = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    claude_root = Path(config_value).expanduser() if config_value else (Path.home() / ".claude")
    external_skill = (claude_root / "skills" / name).resolve(strict=False)
    if external_skill == destination.resolve(strict=False):
        return
    if external_skill.exists():
        raise ValueError(
            f"personal skill name '{name}' conflicts with an existing Claude skill at "
            f"{external_skill}; choose a unique name such as 'company-personal-{name}'"
        )


def _normalize_capabilities(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("reviewed_capabilities must be a JSON string array")
    capabilities = sorted(set(item.strip() for item in value if item.strip()))
    unknown = sorted(set(capabilities) - KNOWN_CAPABILITIES)
    if unknown:
        raise ValueError("unsupported reviewed capability: " + ", ".join(unknown))
    forbidden = sorted(set(capabilities) & PROHIBITED_CAPABILITIES)
    if forbidden:
        raise ValueError(
            "these capabilities require process isolation that Company Agent does not provide: "
            + ", ".join(forbidden)
        )
    return capabilities


def _qualified_name(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value, aliases)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _analyze_code(code: str) -> list[CodeRisk]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [CodeRisk("dynamic-code", f"invalid Python syntax at line {exc.lineno or '?'}")]

    aliases: dict[str, str] = {}
    risks: set[CodeRisk] = set()

    def add(capability: str, detail: str) -> None:
        risks.add(CodeRisk(capability, detail))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                aliases[alias.asname or root] = alias.name
                if root in NETWORK_IMPORT_ROOTS:
                    add("network", f"network import {alias.name}")
                elif root in PROCESS_IMPORT_ROOTS:
                    add("process", f"process import {alias.name}")
                elif root in NATIVE_IMPORT_ROOTS:
                    add("native-code", f"native-code import {alias.name}")
                elif root not in SAFE_IMPORT_ROOTS:
                    add("third-party-import", f"non-standard import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{module}.{alias.name}".strip(".")
            if root in NETWORK_IMPORT_ROOTS:
                add("network", f"network import {module}")
            elif root in PROCESS_IMPORT_ROOTS:
                add("process", f"process import {module}")
            elif root in NATIVE_IMPORT_ROOTS:
                add("native-code", f"native-code import {module}")
            elif root and root not in SAFE_IMPORT_ROOTS:
                add("third-party-import", f"non-standard import {module}")

    destructive_calls = {
        "os.remove", "os.removedirs", "os.rmdir", "os.unlink", "shutil.rmtree",
        "pathlib.Path.rmdir", "pathlib.Path.unlink",
    }
    write_methods = {"mkdir", "rename", "replace", "touch", "write_bytes", "write_text"}
    network_call_prefixes = tuple(f"{name}." for name in NETWORK_IMPORT_ROOTS)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _qualified_name(node.func, aliases)
        leaf = name.rsplit(".", 1)[-1]
        if name in {"eval", "exec", "compile", "__import__", "builtins.eval", "builtins.exec"}:
            add("dynamic-code", f"dynamic code call {name}")
        if name in {"os.system", "os.popen"}:
            add("shell", f"shell call {name}")
        if name.startswith("subprocess.") or name.startswith("multiprocessing."):
            add("process", f"process call {name}")
        if name in destructive_calls or leaf in {"rmtree", "unlink", "rmdir"}:
            add("destructive-filesystem", f"destructive filesystem call {name or leaf}")
        elif leaf in write_methods or name.startswith("shutil.copy") or name == "shutil.move":
            add("filesystem-write", f"filesystem write call {name or leaf}")
        if name == "open":
            mode = "r"
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            for keyword in node.keywords:
                if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                    mode = str(keyword.value.value)
            capability = "filesystem-write" if any(flag in mode for flag in "wax+") else "filesystem-read"
            add(capability, f"open(mode={mode!r})")
        if name.startswith(network_call_prefixes):
            add("network", f"network call {name}")
        for keyword in node.keywords:
            if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                add("shell", "subprocess shell=True")

    return sorted(risks, key=lambda item: (item.capability, item.detail))


def _check_code(code: str, reviewed_capabilities: list[str] | None = None) -> list[str]:
    reviewed = set(reviewed_capabilities or [])
    unresolved = []
    for risk in _analyze_code(code):
        if risk.capability in PROHIBITED_CAPABILITIES:
            unresolved.append(f"{risk.capability}: {risk.detail} (no process isolation available)")
        elif risk.capability not in reviewed:
            unresolved.append(f"{risk.capability}: {risk.detail} (capability not reviewed)")
    return unresolved


def _confined_child(base: Path, name: str) -> Path:
    _validate_name(name)
    base_resolved = base.resolve()
    candidate = (base / name).resolve(strict=False)
    if not candidate.is_relative_to(base_resolved):
        raise ValueError("asset path escapes its managed state directory")
    return candidate


def _confined_entrypoint(asset_root: Path, value: Any, expected_name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("asset manifest entrypoint is missing")
    raw = Path(value)
    if raw.is_absolute() or raw.name != value or raw.name != expected_name:
        raise ValueError(f"asset entrypoint must be exactly {expected_name}")
    root_resolved = asset_root.resolve()
    entrypoint = (asset_root / raw).resolve(strict=True)
    if not entrypoint.is_relative_to(root_resolved) or not entrypoint.is_file():
        raise ValueError("asset entrypoint escapes its asset directory")
    return entrypoint


def _registry_path(layout: dict[str, Path]) -> Path:
    return layout["root"] / "assets" / "registry.json"


def _load_registry(layout: dict[str, Path]) -> dict[str, Any]:
    default = {"schemaVersion": 1, "assets": []}
    return load_json(_registry_path(layout), default) or default


def _record_asset(layout: dict[str, Path], record: dict[str, Any]) -> None:
    registry = _load_registry(layout)
    assets = [
        item for item in registry.get("assets", [])
        if not (item.get("type") == record["type"] and item.get("name") == record["name"])
    ]
    assets.append(record)
    registry["assets"] = sorted(assets, key=lambda item: (str(item.get("type")), str(item.get("name"))))
    atomic_write_json(_registry_path(layout), registry)
    ledger = layout["ledger"] / "assets.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _snapshot_existing(layout: dict[str, Path], asset_type: str, name: str, destination: Path) -> None:
    if not destination.exists():
        return
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    snapshot = layout["root"] / "assets" / "versions" / timestamp / asset_type / name
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(destination, snapshot)


def create_asset(spec: dict[str, Any], state_root: Path) -> Path:
    layout = ensure_user_layout(state_root)
    asset_type = str(spec.get("type", ""))
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"unsupported asset type: {asset_type}")
    name = str(spec.get("name", ""))
    _validate_name(name)
    description = str(spec.get("description", "")).strip()
    if not description:
        raise ValueError("description is required")

    if asset_type == "skill":
        destination = _create_skill(layout, name, description, spec)
        status = "active"
    elif asset_type == "script-tool":
        destination = _create_script_tool(layout, name, description, spec)
        status = "candidate"
    else:
        destination = _create_mcp(layout, name, description, spec)
        status = "candidate"

    record = {
        "type": asset_type,
        "name": name,
        "description": description,
        "path": str(destination),
        "status": status,
        "createdAt": _now(),
        "knowledgeDependencies": list(spec.get("knowledge_dependencies", [])),
        "reason": str(spec.get("reason", "사용자 요청으로 생성"))[:500],
    }
    _record_asset(layout, record)
    return destination


def _create_skill(layout: dict[str, Path], name: str, description: str, spec: dict[str, Any]) -> Path:
    destination = _confined_child(layout["personal_skills"], name)
    _assert_no_external_skill_collision(name, destination)
    instructions = str(spec.get("instructions", "")).strip()
    if not instructions:
        raise ValueError("instructions are required for a skill")
    _snapshot_existing(layout, "skill", name, destination)
    destination.mkdir(parents=True, exist_ok=True)
    frontmatter = ["---", f"name: {name}", f"description: {json.dumps(description, ensure_ascii=False)}", "---", ""]
    atomic_write_text(destination / "SKILL.md", "\n".join(frontmatter) + instructions + "\n")
    if spec.get("references"):
        references = destination / "references"
        references.mkdir(exist_ok=True)
        for index, item in enumerate(spec["references"], start=1):
            atomic_write_text(references / f"reference-{index}.md", str(item).strip() + "\n")
    return destination


def _validate_schema_definition(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    return value


def _create_script_tool(layout: dict[str, Path], name: str, description: str, spec: dict[str, Any]) -> Path:
    destination = _confined_child(layout["tools"], name)
    reviewed = _normalize_capabilities(spec.get("reviewed_capabilities"))
    code = str(spec.get("code", "")).strip()
    if not code:
        code = (
            "from __future__ import annotations\n\nimport json\nimport sys\n\n"
            "def main() -> int:\n"
            "    payload = json.load(sys.stdin)\n"
            "    json.dump({'ok': True, 'input': payload}, sys.stdout, ensure_ascii=False)\n"
            "    return 0\n\n"
            "if __name__ == '__main__':\n    raise SystemExit(main())\n"
        )
    warnings = _check_code(code, reviewed)
    if warnings:
        raise ValueError("generated tool requires security review: " + "; ".join(warnings))
    input_schema = _validate_schema_definition(spec.get("input_schema", {"type": "object"}), "input_schema")
    output_schema = _validate_schema_definition(spec.get("output_schema", {}), "output_schema")

    _snapshot_existing(layout, "script-tool", name, destination)
    destination.mkdir(parents=True, exist_ok=True)
    atomic_write_text(destination / "main.py", code.rstrip() + "\n")
    py_compile.compile(str(destination / "main.py"), doraise=True)
    manifest = {
        "schemaVersion": 1,
        "type": "script-tool",
        "name": name,
        "description": description,
        "entrypoint": "main.py",
        "inputSchema": input_schema,
        "outputSchema": output_schema,
        "reviewedCapabilities": reviewed,
        "status": "candidate",
        "securityReview": {"staticScan": "passed", "runtimeTest": "required", "osSandbox": False},
    }
    atomic_write_json(destination / "tool.json", manifest)
    return destination


def _create_mcp(layout: dict[str, Path], name: str, description: str, spec: dict[str, Any]) -> Path:
    destination = _confined_child(layout["mcp"] / "servers", name)
    reviewed = _normalize_capabilities(spec.get("reviewed_capabilities"))
    server_code = str(spec.get("server_code", "")).strip()
    if not server_code:
        server_code = f'''from mcp.server.fastmcp import FastMCP\n\nmcp = FastMCP({name!r})\n\n@mcp.tool()\ndef health() -> dict[str, object]:\n    """Return local server health."""\n    return {{"ok": True, "server": {name!r}}}\n\nif __name__ == "__main__":\n    mcp.run(transport="stdio")\n'''
    warnings = _check_code(server_code, reviewed)
    if warnings:
        raise ValueError("generated MCP requires security review: " + "; ".join(warnings))

    _snapshot_existing(layout, "mcp", name, destination)
    destination.mkdir(parents=True, exist_ok=True)
    server_path = destination / "server.py"
    atomic_write_text(server_path, server_code.rstrip() + "\n")
    py_compile.compile(str(server_path), doraise=True)
    atomic_write_text(
        destination / "pyproject.toml",
        f'''[project]\nname = "personal-mcp-{name}"\nversion = "0.1.0"\ndescription = {json.dumps(description)}\nrequires-python = ">=3.11"\ndependencies = ["mcp{MCP_REQUIREMENT}"]\n''',
    )
    manifest = {
        "schemaVersion": 1,
        "type": "mcp",
        "name": name,
        "description": description,
        "status": "candidate",
        "command": str(Path(sys.executable).resolve()),
        "args": [str(server_path.resolve())],
        "entrypoint": "server.py",
        "mcpRequirement": MCP_REQUIREMENT,
        "reviewedCapabilities": reviewed,
        "securityReview": {"staticScan": "passed", "protocolTest": "required", "osSandbox": False},
    }
    atomic_write_json(destination / "asset.json", manifest)
    return destination


def _load_manifest(path: Path, filename: str) -> dict[str, Any]:
    try:
        manifest = load_json(path / filename)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {filename}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"{filename} must contain one JSON object")
    return manifest


def _validate_tool_manifest(tool_root: Path, expected_name: str) -> tuple[dict[str, Any], Path]:
    _validate_name(expected_name)
    manifest = _load_manifest(tool_root, "tool.json")
    if manifest.get("type") != "script-tool" or manifest.get("name") != expected_name:
        raise ValueError("tool manifest type/name does not match the requested asset")
    entrypoint = _confined_entrypoint(tool_root, manifest.get("entrypoint"), "main.py")
    _normalize_capabilities(manifest.get("reviewedCapabilities"))
    _validate_schema_definition(manifest.get("inputSchema", {}), "inputSchema")
    _validate_schema_definition(manifest.get("outputSchema", {}), "outputSchema")
    return manifest, entrypoint


def _validate_mcp_definition(server_root: Path, expected_name: str, manifest: dict[str, Any]) -> Path:
    """Validate server metadata; callers must separately authorize its runtime."""
    _validate_name(expected_name)
    if manifest.get("type") != "mcp" or manifest.get("name") != expected_name:
        raise ValueError("MCP manifest type/name does not match the requested asset")
    entrypoint = _confined_entrypoint(server_root, manifest.get("entrypoint"), "server.py")
    args = manifest.get("args")
    if not isinstance(args, list) or len(args) != 1 or not isinstance(args[0], str):
        raise ValueError("MCP args must contain only its server.py entrypoint")
    if str(Path(args[0]).resolve()) != str(entrypoint):
        raise ValueError("MCP args were changed or escape the managed server directory")
    if manifest.get("mcpRequirement") != MCP_REQUIREMENT:
        raise ValueError(f"MCP requirement must remain pinned to {MCP_REQUIREMENT}")
    _normalize_capabilities(manifest.get("reviewedCapabilities"))
    return entrypoint


def _validate_mcp_manifest(server_root: Path, expected_name: str) -> tuple[dict[str, Any], Path]:
    _validate_name(expected_name)
    manifest = _load_manifest(server_root, "asset.json")
    command = manifest.get("command")
    expected_python = str(Path(sys.executable).resolve())
    if not isinstance(command, str) or str(Path(command).resolve()) != expected_python:
        raise ValueError(
            "MCP command must be the approved Company Agent Python interpreter. "
            f"After a Core runtime change, run company-agent asset rebind-mcp-runtime --name {expected_name}; "
            "this repair requires the unchanged asset and its previous signed protocol receipt."
        )
    entrypoint = _validate_mcp_definition(server_root, expected_name, manifest)
    return manifest, entrypoint


def validate_asset(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_dir():
        return {"ok": False, "errors": ["path does not exist or is not a directory"], "warnings": []}
    errors: list[str] = []
    warnings: list[str] = []
    reviewed: list[str] = []
    try:
        if (path / "tool.json").exists():
            raw_manifest = _load_manifest(path, "tool.json")
            manifest, _ = _validate_tool_manifest(path, str(raw_manifest.get("name", "")))
            reviewed = _normalize_capabilities(manifest.get("reviewedCapabilities"))
        elif (path / "asset.json").exists():
            raw_manifest = _load_manifest(path, "asset.json")
            manifest, _ = _validate_mcp_manifest(path, str(raw_manifest.get("name", "")))
            reviewed = _normalize_capabilities(manifest.get("reviewedCapabilities"))
        elif (path / "SKILL.md").exists():
            content = (path / "SKILL.md").read_text(encoding="utf-8-sig")
            if not content.startswith("---\n") and not content.startswith("---\r\n"):
                errors.append("SKILL.md frontmatter is missing")
            sections = content.split("---", 2)
            if len(sections) < 3 or "description:" not in sections[1]:
                errors.append("SKILL.md description is missing")
        else:
            errors.append("no supported asset manifest was found")
    except (OSError, ValueError) as exc:
        errors.append(str(exc))

    source_errors, source_warnings = _scan_asset_sources(path, reviewed)
    errors.extend(source_errors)
    warnings.extend(source_warnings)
    return {
        "ok": not errors and not warnings,
        "errors": errors,
        "warnings": warnings,
        "reviewedCapabilities": reviewed,
        "osSandbox": False,
    }


def _scan_asset_sources(path: Path, reviewed: list[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for script in path.rglob("*.py"):
        if "__pycache__" in script.parts or ".receipts" in script.parts:
            continue
        try:
            py_compile.compile(str(script), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(str(exc))
            continue
        try:
            code = script.read_text(encoding="utf-8-sig")
            warnings.extend(f"{script.name}: {item}" for item in _check_code(code, reviewed))
        except (OSError, UnicodeError) as exc:
            errors.append(str(exc))
    return errors, warnings


def _canonical_manifest_bytes(path: Path) -> bytes:
    return _canonical_manifest_value(_load_manifest(path.parent, path.name))


def _canonical_manifest_value(value: dict[str, Any]) -> bytes:
    normalized = {key: item for key, item in value.items() if key not in _MUTABLE_MANIFEST_FIELDS}
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _asset_content_hash(asset_root: Path, manifest_name: str, *, manifest_override: dict[str, Any] | None = None) -> str:
    digest = hashlib.sha256()
    for path in sorted(asset_root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or ".receipts" in path.parts or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(asset_root).as_posix()
        if relative == manifest_name:
            content = _canonical_manifest_value(manifest_override) if manifest_override is not None else _canonical_manifest_bytes(path)
        else:
            content = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def _receipt_key(layout: dict[str, Path]) -> bytes:
    path = layout["config"] / "validation-receipt.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w", encoding="ascii", newline="\n") as stream:
                stream.write(secrets.token_hex(32) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
    try:
        value = bytes.fromhex(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError) as exc:
        raise ValueError("validation receipt key is missing or invalid") from exc
    if len(value) != 32:
        raise ValueError("validation receipt key is missing or invalid")
    return value


def _receipt_signature(payload: dict[str, Any], key: bytes) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def _write_receipt(
    layout: dict[str, Path], asset_root: Path, receipt_type: str, asset_type: str,
    name: str, asset_hash: str, details: dict[str, Any],
) -> Path:
    payload = {
        "schemaVersion": 1,
        "validatorVersion": VALIDATOR_VERSION,
        "receiptType": receipt_type,
        "assetType": asset_type,
        "assetName": name,
        "assetHash": asset_hash,
        "testedAt": _now(),
        "nonce": secrets.token_hex(16),
        "details": details,
    }
    payload["signature"] = _receipt_signature(payload, _receipt_key(layout))
    receipt_root = asset_root / ".receipts"
    receipt_root.mkdir(parents=True, exist_ok=True)
    path = receipt_root / f"{receipt_type}-{payload['nonce']}.json"
    atomic_write_json(path, payload)
    return path


def _resolve_receipt_path(asset_root: Path, value: str | Path) -> Path:
    if not str(value).strip():
        raise ValueError("a harness-created validation receipt path is required")
    receipt_root = (asset_root / ".receipts").resolve()
    raw = Path(value)
    candidate = (receipt_root / raw).resolve(strict=True) if not raw.is_absolute() else raw.resolve(strict=True)
    if not candidate.is_relative_to(receipt_root) or not candidate.is_file():
        raise ValueError("validation receipt must be a file under this asset's .receipts directory")
    return candidate


def _verify_receipt(
    layout: dict[str, Path], asset_root: Path, receipt_value: str | Path, expected_type: str,
    asset_type: str, name: str, manifest_name: str,
) -> tuple[Path, dict[str, Any]]:
    try:
        path = _resolve_receipt_path(asset_root, receipt_value)
        receipt = load_json(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid validation receipt: {exc}") from exc
    if not isinstance(receipt, dict):
        raise ValueError("invalid validation receipt: expected one JSON object")
    signature = receipt.pop("signature", None)
    expected_signature = _receipt_signature(receipt, _receipt_key(layout))
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected_signature):
        raise ValueError("validation receipt signature is invalid")
    expected = {
        "schemaVersion": 1,
        "validatorVersion": VALIDATOR_VERSION,
        "receiptType": expected_type,
        "assetType": asset_type,
        "assetName": name,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError(f"validation receipt {key} does not match the asset")
    if receipt.get("assetHash") != _asset_content_hash(asset_root, manifest_name):
        raise ValueError("asset content changed after validation; run validation again")
    receipt["signature"] = signature
    return path, receipt


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return type(value).__name__


def _validate_json_value(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    expected = schema.get("type")
    if expected:
        allowed = [expected] if isinstance(expected, str) else expected
        if not isinstance(allowed, list) or any(not isinstance(item, str) for item in allowed):
            raise ValueError(f"invalid JSON schema type at {path}")
        actual = _json_type(value)
        if actual not in allowed and not (actual == "integer" and "number" in allowed):
            raise ValueError(f"JSON value at {path} must be {allowed}; got {actual}")
    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise ValueError(f"invalid required list at {path}")
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError(f"JSON value at {path} is missing required keys: {', '.join(map(str, missing))}")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError(f"invalid properties map at {path}")
        for key, child_schema in properties.items():
            if key in value:
                if not isinstance(child_schema, dict):
                    raise ValueError(f"invalid schema for {path}.{key}")
                _validate_json_value(value[key], child_schema, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        item_schema = schema["items"]
        if not isinstance(item_schema, dict):
            raise ValueError(f"invalid items schema at {path}")
        for index, item in enumerate(value):
            _validate_json_value(item, item_schema, f"{path}[{index}]")


def _bounded_timeout(timeout: int) -> int:
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= MAX_RUNTIME_TIMEOUT:
        raise ValueError(f"timeout must be between 1 and {MAX_RUNTIME_TIMEOUT} seconds")
    return timeout


def _load_json_input(input_path: Path) -> tuple[Any, str]:
    try:
        if input_path.stat().st_size > MAX_JSON_INPUT_BYTES:
            raise ValueError(f"tool input exceeds {MAX_JSON_INPUT_BYTES} bytes")
        raw = input_path.read_text(encoding="utf-8-sig")
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("tool input must contain one valid JSON value") from exc
    digest = f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"
    return value, digest


def _execute_json_tool(entrypoint: Path, payload: Any, cwd: Path, timeout: int) -> Any:
    timeout = _bounded_timeout(timeout)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            completed = subprocess.run(
                [sys.executable, str(entrypoint)], input=data, stdout=stdout_file, stderr=stderr_file,
                cwd=str(cwd), env=environment, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"script tool exceeded the {timeout}-second validation timeout") from exc
        stdout_file.seek(0, os.SEEK_END)
        stdout_size = stdout_file.tell()
        stderr_file.seek(0, os.SEEK_END)
        stderr_size = stderr_file.tell()
        if stdout_size > MAX_JSON_OUTPUT_BYTES:
            raise ValueError(f"script tool output exceeds {MAX_JSON_OUTPUT_BYTES} bytes")
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read(MAX_JSON_OUTPUT_BYTES + 1).decode("utf-8", errors="strict")
        stderr = stderr_file.read(min(stderr_size, 4096)).decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise ValueError(f"script tool failed with exit {completed.returncode}: {stderr[:500]}")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("script tool output must contain exactly one valid JSON value") from exc


def validate_script_tool_runtime(state_root: Path, name: str, input_path: Path, timeout: int = 30) -> Path:
    _validate_name(name)
    layout = ensure_user_layout(state_root)
    tool_root = _confined_child(layout["tools"], name)
    manifest, entrypoint = _validate_tool_manifest(tool_root, name)
    validation = validate_asset(tool_root)
    if not validation["ok"]:
        raise ValueError("tool validation failed: " + "; ".join(validation["errors"] + validation["warnings"]))
    payload, input_hash = _load_json_input(input_path)
    _validate_json_value(payload, manifest.get("inputSchema", {}))
    asset_hash = _asset_content_hash(tool_root, "tool.json")
    with tempfile.TemporaryDirectory(prefix=f"company-agent-{name}-", dir=str(layout["tmp"])) as run_dir:
        result = _execute_json_tool(entrypoint, payload, Path(run_dir), timeout)
    _validate_json_value(result, manifest.get("outputSchema", {}))
    if _asset_content_hash(tool_root, "tool.json") != asset_hash:
        raise ValueError("script tool modified its own validated asset files")
    return _write_receipt(
        layout, tool_root, "script-runtime", "script-tool", name, asset_hash,
        {"inputHash": input_hash, "outputType": _json_type(result), "timeoutSeconds": timeout},
    )


def _parse_version(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", value)
    if not match:
        raise ValueError(f"cannot parse installed MCP SDK version: {value}")
    return tuple(int(item or 0) for item in match.groups())  # type: ignore[return-value]


def _health_response_ok(health: Any) -> bool:
    structured = getattr(health, "structuredContent", None)
    candidates: list[Any] = [structured] if structured is not None else []
    for item in getattr(health, "content", []) or []:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            try:
                candidates.append(json.loads(text))
            except json.JSONDecodeError:
                continue
    for candidate in candidates:
        if isinstance(candidate, dict):
            if candidate.get("ok") is True:
                return True
            result = candidate.get("result")
            if isinstance(result, dict) and result.get("ok") is True:
                return True
    return False


async def _probe_mcp(command: str, args: list[str], cwd: Path, timeout: int) -> dict[str, Any]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise ValueError(
            "approved MCP SDK is unavailable; install the pinned wheel from the company offline wheelhouse. "
            "Company Agent will not install packages from the internet."
        ) from exc

    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    parameters = StdioServerParameters(command=command, args=args, cwd=cwd, env=environment, encoding="utf-8")

    async def run_probe() -> dict[str, Any]:
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as error_log:
            async with stdio_client(parameters, errlog=error_log) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    tools = [str(item.name) for item in listed.tools]
                    if "health" not in tools:
                        raise ValueError("MCP server must expose a no-argument health tool")
                    health = await session.call_tool("health", {})
                    if getattr(health, "isError", False):
                        raise ValueError("MCP health tool returned an error")
                    if not _health_response_ok(health):
                        raise ValueError("MCP health tool must return JSON with ok=true")
                    return {"toolCount": len(tools), "healthTool": "health"}

    try:
        return await asyncio.wait_for(run_probe(), timeout=timeout)
    except TimeoutError as exc:
        raise ValueError(f"MCP protocol validation exceeded {timeout} seconds") from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"MCP protocol/import/health validation failed: {type(exc).__name__}: {exc}") from exc


def _approved_mcp_sdk_version() -> str:
    try:
        installed_version = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError(
            "approved MCP SDK is unavailable; install mcp>=1.20,<2 from the company offline wheelhouse. "
            "No internet installation was attempted."
        ) from exc
    parsed = _parse_version(installed_version)
    if not ((1, 20, 0) <= parsed < (2, 0, 0)):
        raise ValueError(f"installed MCP SDK {installed_version} does not satisfy {MCP_REQUIREMENT}")
    return installed_version


def validate_mcp_runtime(state_root: Path, name: str, timeout: int = 30) -> Path:
    _validate_name(name)
    timeout = _bounded_timeout(timeout)
    layout = ensure_user_layout(state_root)
    server_root = _confined_child(layout["mcp"] / "servers", name)
    manifest, _ = _validate_mcp_manifest(server_root, name)
    validation = validate_asset(server_root)
    if not validation["ok"]:
        raise ValueError("MCP validation failed: " + "; ".join(validation["errors"] + validation["warnings"]))
    installed_version = _approved_mcp_sdk_version()

    asset_hash = _asset_content_hash(server_root, "asset.json")
    with tempfile.TemporaryDirectory(prefix=f"company-agent-mcp-{name}-", dir=str(layout["tmp"])) as run_dir:
        details = asyncio.run(_probe_mcp(manifest["command"], list(manifest["args"]), Path(run_dir), timeout))
    if _asset_content_hash(server_root, "asset.json") != asset_hash:
        raise ValueError("MCP server modified its own validated asset files")
    details.update({"mcpSdkVersion": installed_version, "requirement": MCP_REQUIREMENT, "timeoutSeconds": timeout})
    return _write_receipt(layout, server_root, "mcp-protocol", "mcp", name, asset_hash, details)


def rebind_mcp_runtime(state_root: Path, name: str, timeout: int = 30) -> Path:
    """Explicitly re-test a previously validated personal MCP after a Core update.

    An exact signed receipt authenticates the OLD manifest before any runtime
    exception is considered. Only the CURRENT approved interpreter is executed.
    Native Claude entries and the local active registry are never modified here;
    the caller must activate the returned new receipt and reconcile native state.
    """
    _validate_name(name)
    if name.casefold() in {"corp-db-read", "corp-outlook-self"}:
        raise ValueError("Corporate MCPs are managed separately; runtime rebind is for personal MCPs only.")
    timeout = _bounded_timeout(timeout)
    layout = ensure_user_layout(state_root)
    server_root = _confined_child(layout["mcp"] / "servers", name)
    manifest_path = server_root / "asset.json"
    original_bytes = manifest_path.read_bytes()
    manifest = _load_manifest(server_root, "asset.json")
    receipt_path, previous_receipt = _verify_receipt(
        layout, server_root, manifest.get("validationReceipt", ""), "mcp-protocol", "mcp", name, "asset.json"
    )
    entrypoint = _validate_mcp_definition(server_root, name, manifest)
    previous_command = manifest.get("command")
    if not isinstance(previous_command, str) or not Path(previous_command).is_absolute():
        raise ValueError("Previously validated MCP runtime must be an absolute interpreter path.")
    current_command = str(Path(sys.executable).resolve())
    if str(Path(previous_command).resolve()) == current_command:
        return validate_mcp_runtime(state_root, name, timeout)

    reviewed = _normalize_capabilities(manifest.get("reviewedCapabilities"))
    errors, warnings = _scan_asset_sources(server_root, reviewed)
    if errors or warnings:
        raise ValueError("MCP validation failed: " + "; ".join(errors + warnings))
    installed_version = _approved_mcp_sdk_version()
    original_hash = previous_receipt["assetHash"]
    with tempfile.TemporaryDirectory(prefix=f"company-agent-mcp-rebind-{name}-", dir=str(layout["tmp"])) as run_dir:
        details = asyncio.run(_probe_mcp(current_command, [str(entrypoint)], Path(run_dir), timeout))

    def require_unchanged() -> None:
        if manifest_path.read_bytes() != original_bytes or _asset_content_hash(server_root, "asset.json") != original_hash:
            raise ValueError("MCP asset changed during runtime rebind; no manifest or activation was replaced.")

    require_unchanged()
    transition = {"previousCommand": previous_command, "currentCommand": current_command,
                  "previousAssetHash": original_hash, "previousReceipt": receipt_path.name}
    updated = {**manifest, "command": current_command, "status": "candidate", "runtimeRebind": transition}
    updated.pop("activatedAt", None)
    updated.pop("validationReceipt", None)
    details.update({"mcpSdkVersion": installed_version, "requirement": MCP_REQUIREMENT,
                    "timeoutSeconds": timeout, "runtimeRebind": transition})
    # Stage the signed receipt first. Until the one atomic manifest replacement,
    # it is inert (its hash does not match the old asset). A failed probe/receipt
    # write therefore cannot invalidate the previously active asset or registry.
    new_hash = _asset_content_hash(server_root, "asset.json", manifest_override=updated)
    renewed = _write_receipt(layout, server_root, "mcp-protocol", "mcp", name, new_hash, details)
    require_unchanged()
    updated["validationReceipt"] = renewed.name
    atomic_write_json(manifest_path, updated)
    return renewed


def activate_mcp(state_root: Path, name: str, validation_receipt: str | Path) -> Path:
    _validate_name(name)
    layout = ensure_user_layout(state_root)
    server_root = _confined_child(layout["mcp"] / "servers", name)
    manifest, entrypoint = _validate_mcp_manifest(server_root, name)
    validation = validate_asset(server_root)
    if not validation["ok"]:
        raise ValueError("MCP validation failed: " + "; ".join(validation["errors"] + validation["warnings"]))
    receipt_path, _ = _verify_receipt(
        layout, server_root, validation_receipt, "mcp-protocol", "mcp", name, "asset.json"
    )

    registry_path = layout["mcp"] / "registry.json"
    registry = load_json(registry_path, {"mcpServers": {}}) or {"mcpServers": {}}
    if not isinstance(registry, dict) or not isinstance(registry.get("mcpServers", {}), dict):
        raise ValueError("personal MCP registry is invalid")
    registry.setdefault("mcpServers", {})[name] = {
        "type": "stdio", "command": str(Path(sys.executable).resolve()), "args": [str(entrypoint)],
    }
    atomic_write_json(registry_path, registry)
    manifest["status"] = "active"
    manifest["activatedAt"] = _now()
    manifest["validationReceipt"] = receipt_path.name
    atomic_write_json(server_root / "asset.json", manifest)
    assets_registry = _load_registry(layout)
    for item in assets_registry.get("assets", []):
        if item.get("type") == "mcp" and item.get("name") == name:
            item["status"] = "active"
            item["activatedAt"] = manifest["activatedAt"]
    atomic_write_json(_registry_path(layout), assets_registry)
    return registry_path


def activate_script_tool(state_root: Path, name: str, validation_receipt: str | Path) -> Path:
    _validate_name(name)
    layout = ensure_user_layout(state_root)
    tool_root = _confined_child(layout["tools"], name)
    manifest, _ = _validate_tool_manifest(tool_root, name)
    validation = validate_asset(tool_root)
    if not validation["ok"]:
        raise ValueError("tool validation failed: " + "; ".join(validation["errors"] + validation["warnings"]))
    receipt_path, _ = _verify_receipt(
        layout, tool_root, validation_receipt, "script-runtime", "script-tool", name, "tool.json"
    )

    manifest["status"] = "active"
    manifest["activatedAt"] = _now()
    manifest["validationReceipt"] = receipt_path.name
    atomic_write_json(tool_root / "tool.json", manifest)

    skill_root = _confined_child(layout["personal_skills"], name)
    _assert_no_external_skill_collision(name, skill_root)
    skill_root.mkdir(parents=True, exist_ok=True)
    skill_text = f'''---
name: {name}
description: {json.dumps(str(manifest["description"]), ensure_ascii=False)}
---

# Personal script tool: {name}

This tool belongs to `{state_root.absolute().as_posix()}`. Use that exact bound
state root below, not a different hook/session store. It is already resolved;
do not add --storage-scope again. Reuse the current runtime's exact cliCommand prefix.

1. Convert the requested input to a JSON object and save it to a new temporary file under `{(state_root.absolute() / 'tmp').as_posix()}`.
2. Append `asset run-tool --name {name} --input "<input.json>" --state-root "{state_root.absolute().as_posix()}"` to cliCommand.
3. Parse the returned JSON and explain the result in the user's language.
4. Do not add shell operators or invoke the underlying script directly.
'''
    atomic_write_text(skill_root / "SKILL.md", skill_text)
    assets_registry = _load_registry(layout)
    for item in assets_registry.get("assets", []):
        if item.get("type") == "script-tool" and item.get("name") == name:
            item["status"] = "active"
            item["activatedAt"] = manifest["activatedAt"]
    atomic_write_json(_registry_path(layout), assets_registry)
    return skill_root


def run_script_tool(state_root: Path, name: str, input_path: Path, timeout: int = 60) -> dict[str, Any]:
    _validate_name(name)
    timeout = _bounded_timeout(timeout)
    layout = ensure_user_layout(state_root)
    tool_root = _confined_child(layout["tools"], name)
    manifest, entrypoint = _validate_tool_manifest(tool_root, name)
    if manifest.get("status") != "active":
        raise ValueError(f"script tool is not active: {name}")
    receipt_value = manifest.get("validationReceipt")
    if not isinstance(receipt_value, str):
        raise ValueError("active script tool has no validation receipt")
    _verify_receipt(layout, tool_root, receipt_value, "script-runtime", "script-tool", name, "tool.json")
    payload, _ = _load_json_input(input_path)
    _validate_json_value(payload, manifest.get("inputSchema", {}))
    with tempfile.TemporaryDirectory(prefix=f"company-agent-{name}-", dir=str(layout["tmp"])) as run_dir:
        result = _execute_json_tool(entrypoint, payload, Path(run_dir), timeout)
    _validate_json_value(result, manifest.get("outputSchema", {}))
    return {"ok": True, "tool": name, "result": result}
