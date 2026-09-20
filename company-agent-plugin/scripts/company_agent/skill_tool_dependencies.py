"""Bounded, read-only dependency checks; no server startup or model request."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .paths import load_json


def _definitions(value) -> list[dict]:
    from .asset_factory import _validate_name
    from .platform_assets import TOOL_NAME
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("tool_dependencies must contain at most eight server definitions")
    seen = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"server", "tools"}:
            raise ValueError("tool_dependencies fields are server and tools")
        if not isinstance(item["server"], str):
            raise ValueError("Dependency server must be a registered asset name")
        _validate_name(item["server"])
        tools = item["tools"]
        if (item["server"] in seen or not isinstance(tools, list) or not 1 <= len(tools) <= 32
                or any(not isinstance(t, str) or not TOOL_NAME.fullmatch(t) for t in tools)
                or len(set(tools)) != len(tools) or "health" in tools):
            raise ValueError("Duplicate or invalid business tool dependency")
        seen.add(item["server"])
    return value


def _binding(root: Path, definition: dict) -> dict:
    from .asset_factory import _confined_child, _validate_mcp_manifest, _verify_receipt
    server = definition["server"]
    path = _confined_child(root / "mcp/servers", server)
    manifest, _ = _validate_mcp_manifest(path, server)
    if manifest.get("status") != "active":
        raise ValueError("Required MCP is not active: " + server)
    if not (root / "config/validation-receipt.key").is_file():
        raise ValueError("Required MCP has no validation key: " + server)
    _, receipt = _verify_receipt({"root": root, "config": root / "config"}, path,
                                manifest.get("validationReceipt", ""), "mcp-protocol", "mcp", server, "asset.json")
    schemas = receipt.get("details", {}).get("toolSchemas", {})
    if any(t not in schemas for t in definition["tools"]):
        raise ValueError("Required tools are missing from validated schemas; re-test MCP: " + server)
    if manifest.get("format") == "platform-tools-v1":
        tested = receipt.get("details", {}).get("businessTools", [])
        if any(t not in tested for t in definition["tools"]):
            raise ValueError("Required tools have no business test evidence: " + server)
    selected = {t: schemas[t] for t in definition["tools"]}
    digest = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"server": server, "tools": definition["tools"], "assetHash": receipt["assetHash"], "schemaHash": digest}


def prepare_dependencies(root: Path, destination: Path, spec: dict) -> list[dict]:
    previous = destination / "tool-dependencies.json"
    if "tool_dependencies" not in spec and previous.is_file():
        existing = load_json(previous)
        if not isinstance(existing, dict) or existing.get("schemaVersion") != 1:
            raise ValueError("Invalid existing skill dependencies")
        # Preserve an existing binding; an ordinary text update cannot silently rebind changed tools.
        check = check_skill_dependencies(root, destination.name)
        if not check["ok"]:
            raise ValueError("Existing skill dependency changed; explicitly review tool_dependencies")
        return existing["dependencies"]
    definitions = _definitions(spec.get("tool_dependencies", []))
    return [_binding(root, item) for item in definitions]


def dependency_instructions(root: Path, name: str, bindings: list[dict]) -> str:
    if not bindings:
        return ""
    names = "; ".join(item["server"] + ": " + ", ".join(item["tools"]) for item in bindings)
    return ("## 연결 도구 확인\n\n"
            f"필요한 MCP 도구: {names}.\n"
            "현재 대화에서 최초 사용하거나 도구가 바뀌면 company_agent_runtime.cliCommand 뒤에 "
            f'`asset check-skill --name {name} --state-root "{root.absolute().as_posix()}" '
            '--project-root "<현재 프로젝트 절대 경로>"`를 붙여 확인합니다. '
            "이 저장소는 이미 선택되어 있으므로 --storage-scope를 다시 붙이지 않습니다. "
            "같은 대화에서 변경 없는 확인 결과만 재사용합니다.\n"
            "ok=false이면 호출을 멈추고 실패한 연결/검증만 설명합니다. "
            "검사 통과는 현재 세션 연결 성공 증거가 아닙니다. 세션에 실제 표시된 서버·도구명과 입력 형식을 "
            "확인한 다음 해당 MCP 도구를 호출합니다. 호출명을 추측하거나 tools.py를 직접 실행하지 않습니다. "
            "도구가 없으면 연결/재시작 필요를 안내하고 임의 코드로 대체하거나 재설치하지 않습니다. "
            "호출 실패·권한 거절은 결과 성공으로 처리하지 않습니다. 외부 쓰기 승인은 별도 유지합니다.\n\n")


def check_skill_dependencies(root: Path, name: str, project: Path | None = None) -> dict:
    from .asset_factory import _confined_child
    from .native_mcp import registration_status
    destination = _confined_child(root / "personal-root/.claude/skills", name)
    if not (destination / "SKILL.md").is_file():
        return {"ok": False, "status": "missing-skill", "dependencies": []}
    file = destination / "tool-dependencies.json"
    if not file.exists():
        return {"ok": True, "status": "no-tool-dependencies", "dependencies": []}
    if file.stat().st_size > 64 * 1024 or not file.resolve().is_relative_to(destination.resolve()):
        raise ValueError("Invalid skill dependency file")
    stored = load_json(file)
    if not isinstance(stored, dict) or stored.get("schemaVersion") != 1 or not isinstance(stored.get("dependencies"), list):
        raise ValueError("Invalid skill dependency document")
    bindings = stored["dependencies"]
    if not all(isinstance(item, dict) for item in bindings):
        raise ValueError("Invalid skill dependency entries")
    _definitions([{k: item.get(k) for k in ("server", "tools")} for item in bindings])
    rows = []
    for expected in bindings:
        try:
            actual = _binding(root, expected)
            if actual != expected:
                raise ValueError("Tool source or schema changed; re-test and review this skill binding")
            path = root / "mcp/servers" / expected["server"]
            manifest = load_json(path / "asset.json")
            desired = {"type": "stdio", "command": manifest["command"], "args": manifest["args"]}
            registry = load_json(root / "mcp/registry.json", {})
            if not isinstance(registry, dict) or not isinstance(registry.get("mcpServers", {}), dict):
                raise ValueError("Active MCP registry must contain a server object")
            if registry.get("mcpServers", {}).get(expected["server"]) != desired:
                raise ValueError("Required MCP is not present in the active registry")
            if os.environ.get("COMPANY_AGENT_SCOPE", "").casefold() == "machine":
                native = "launcher-registry"  # Launcher supplies the validated registry, not native settings.
            else:
                native = registration_status(expected["server"], desired, project) if project is not None else "not-checked"
            ok = native in {"registered", "not-checked", "launcher-registry"}
            rows.append({"server": expected["server"], "tools": expected["tools"], "ok": ok,
                         "status": "verified" if ok else "native-registration-required", "nativeRegistration": native})
        except (OSError, ValueError, KeyError) as exc:
            rows.append({"server": expected["server"], "ok": False, "status": "needs-review", "reason": str(exc)})
    return {"ok": all(item["ok"] for item in rows), "dependencies": rows, "liveConnection": "not-checked"}
