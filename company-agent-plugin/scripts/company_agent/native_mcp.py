"""Register receipt-validated personal MCPs in native Claude without a shell.

`mcp add-json` writes configuration; unlike `mcp get/list`, it does not probe
server health. Existing unowned names and changed native configurations are
never overwritten. No Claude config content or child output is returned.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from typing import Any

from .asset_factory import (
    _confined_child, _validate_name, _validate_mcp_manifest, _verify_receipt,
    validate_asset,
)
from .paths import atomic_write_json, ensure_user_layout


_RESERVED = {"corp-db-read", "corp-outlook-self"}
_MAX_CONFIG_BYTES = 16 * 1024 * 1024


def _no_reparse(path: Path) -> None:
    for item in [*reversed(path.parents), path]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Native MCP registration cannot use symlink/junction paths.")


def _read_object(path: Path) -> dict[str, Any]:
    _no_reparse(path)
    if not path.exists():
        return {}
    if not path.is_file() or path.stat().st_size > _MAX_CONFIG_BYTES:
        raise ValueError("Native MCP configuration is not a bounded regular JSON file.")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("Native MCP configuration could not be read. Repair the configuration before retrying.") from None
    if not isinstance(value, dict):
        raise ValueError("Native MCP configuration must be a JSON object.")
    return value


def _config_file() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    directory = Path(override).expanduser() if override else Path.home()
    if not directory.is_absolute():
        raise ValueError("CLAUDE_CONFIG_DIR must be an absolute directory for native MCP registration.")
    return directory / ".claude.json"


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _same_project(value: str, expected: Path) -> bool:
    try:
        return Path(value).is_absolute() and Path(value).resolve() == expected.resolve()
    except (OSError, ValueError):
        return False


def _server_map(value: dict[str, Any]) -> dict[str, Any]:
    servers = value.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("Native MCP server collection must be a JSON object.")
    return servers


def _native_entries(config_file: Path, scope: str, project: Path | None, name: str) -> tuple[Any, list[str]]:
    document = _read_object(config_file)
    user = _server_map(document)
    target = user.get(name) if scope == "user" else None
    conflicts = []
    if scope != "user" and name in user:
        conflicts.append("user")
    projects = document.get("projects", {})
    if not isinstance(projects, dict):
        raise ValueError("Native Claude projects configuration must be a JSON object.")
    for key, value in projects.items():
        if not isinstance(value, dict):
            continue
        servers = _server_map(value)
        if name not in servers:
            continue
        if scope == "local" and project and _same_project(key, project):
            if target is not None:
                raise ValueError("Duplicate native project MCP entries require manual reconciliation.")
            target = servers[name]
        elif scope == "user":
            conflicts.append("another local project")
    directory = project or Path.cwd()
    for parent in [directory, *directory.parents]:
        if name in _server_map(_read_object(parent / ".mcp.json")):
            conflicts.append("shared project")
    return target, conflicts


def _claude_argv() -> list[str]:
    """Resolve a native binary or the official npm package bin, not a shim."""
    candidates = [os.environ.get("COMPANY_AGENT_CLAUDE_COMMAND", ""), shutil.which("claude.exe"), shutil.which("claude")]
    for value in candidates:
        if not value:
            continue
        # npm version managers commonly expose their installed runtime through
        # a junction. Resolve that read-only executable location first; writes
        # to state/config still reject reparse paths above.
        path = Path(value).expanduser().resolve()
        if path.suffix.casefold() == ".exe" and path.is_file():
            return [str(path)]
        package = path.parent / "node_modules" / "@anthropic-ai" / "claude-code"
        metadata = _read_object(package / "package.json")
        if metadata.get("name") != "@anthropic-ai/claude-code":
            continue
        bins = metadata.get("bin", {})
        entry = bins.get("claude") if isinstance(bins, dict) else bins
        if not isinstance(entry, str) or not entry:
            continue
        binary = (package / entry).resolve()
        if not binary.is_relative_to(package.resolve()) or not binary.is_file():
            continue
        if binary.suffix.casefold() == ".exe":
            return [str(binary)]
        node = shutil.which("node.exe")
        if binary.suffix.casefold() in {".js", ".cjs", ".mjs"} and node:
            return [str(Path(node).resolve()), str(binary)]
    raise ValueError("Native Claude executable is unavailable. Repair the existing Claude installation and retry MCP registration.")


def sync_native_mcp(state_root: Path, name: str, *, storage_scope: str | None = None,
                    project_root: Path | None = None) -> dict[str, Any]:
    _validate_name(name)
    if name.casefold() in _RESERVED:
        raise ValueError("Corporate MCP names are reserved; choose a unique personal MCP name.")
    selected = os.environ.get("COMPANY_AGENT_SCOPE", "")
    if selected not in {"User", "Project"}:
        raise ValueError("Native MCP sync requires a User or Project Company Agent installation; use the launcher for launcher-only installations.")
    if storage_scope is not None:
        if storage_scope not in {'personal', 'project'}:
            raise ValueError('Invalid resource storage scope.')
        selected = 'User' if storage_scope == 'personal' else 'Project'
    project = None
    if selected == "Project":
        raw_project = str(project_root) if project_root is not None else os.environ.get("COMPANY_AGENT_PROJECT_ROOT", "")
        project = Path(raw_project).expanduser()
        if not raw_project or not project.is_absolute() or not project.is_dir():
            raise ValueError("Project MCP registration requires the installed absolute project folder.")
        _no_reparse(project)
        if not Path.cwd().resolve().is_relative_to(project.resolve()):
            raise ValueError("Run MCP registration from the installed project folder.")
    scope = "user" if selected == "User" else "local"
    _no_reparse(state_root)
    layout = ensure_user_layout(state_root)
    server_root = _confined_child(layout["mcp"] / "servers", name)
    _no_reparse(server_root)
    manifest, entrypoint = _validate_mcp_manifest(server_root, name)
    if manifest.get("status") != "active":
        raise ValueError("Activate this MCP with a valid protocol receipt before native registration.")
    validation = validate_asset(server_root)
    if not validation["ok"]:
        raise ValueError("Personal MCP validation failed; validate and activate it again before native registration.")
    _verify_receipt(layout, server_root, manifest.get("validationReceipt", ""), "mcp-protocol", "mcp", name, "asset.json")
    desired = {"type": "stdio", "command": manifest["command"], "args": [str(entrypoint)]}
    if _server_map(_read_object(layout["mcp"] / "registry.json")).get(name) != desired:
        raise ValueError("Personal MCP registry differs from the validated asset; activate it again before native registration.")

    config_file = _config_file()
    current, conflicts = _native_entries(config_file, scope, project, name)
    if conflicts:
        raise ValueError("An existing MCP with this name is already registered in another Claude scope. Choose a unique personal name.")
    ownership_file = layout["mcp"] / "native-registrations.json"
    ownership = _read_object(ownership_file)
    if ownership and ownership.get("schemaVersion") != 1:
        raise ValueError("Unsupported native MCP ownership record.")
    entries = ownership.setdefault("entries", {})
    if not isinstance(entries, dict):
        raise ValueError("Invalid native MCP ownership record.")
    identity = {"name": name, "scope": scope, "projectRoot": str(project.resolve()) if project else None,
                "claudeConfigFile": str(config_file.resolve())}
    key = _fingerprint(identity)
    expected_hash = _fingerprint(desired)
    owned = entries.get(key)
    if current is not None:
        if not isinstance(owned, dict) or owned.get("configHash") != _fingerprint(current):
            raise ValueError("An existing native MCP entry is unowned or changed. It was preserved; choose a new personal name or resolve the entry in Claude.")
        if current != desired:
            transition = manifest.get("runtimeRebind", {})
            if (isinstance(transition, dict) and transition.get("currentCommand") == desired["command"]
                    and isinstance(transition.get("previousCommand"), str)
                    and current == {**desired, "command": transition["previousCommand"]}):
                raise ValueError(
                    "This owned native MCP still uses the previously validated Company Agent runtime. "
                    "Its settings were preserved; no entry was removed or replaced. "
                    f"Remove only personal MCP '{name}' from Claude's '{scope}' scope, then run "
                    f"company-agent asset sync-mcp --name {name} and restart Claude. "
                    "Do not remove other personal or corporate MCP entries."
                )
            raise ValueError("An existing native MCP entry differs from the validated asset. It was preserved; choose a new personal name or resolve the entry in Claude.")
        if owned.get("status") != "registered":
            entries[key] = {**identity, "configHash": expected_hash, "status": "registered"}
            atomic_write_json(ownership_file, ownership)
        return {"ok": True, "name": name, "scope": scope, "status": "already-registered", "restartRequired": True}

    argv = [*_claude_argv(), "mcp", "add-json", name, json.dumps(desired, ensure_ascii=False, separators=(",", ":")), "--scope", scope]
    # Persist our exact intent before Claude writes. A timeout or interrupted
    # response can then be retried without adopting an unrelated same-name MCP.
    entries[key] = {**identity, "configHash": expected_hash, "status": "pending"}
    ownership["schemaVersion"] = 1
    atomic_write_json(ownership_file, ownership)
    try:
        result = subprocess.run(argv, cwd=str(project) if project else None, env=os.environ.copy(),
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=30, check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Personal MCP is active locally but native registration is pending. Retry MCP sync after checking Claude installation.") from None
    if result.returncode != 0:
        raise ValueError("Personal MCP is active locally but Claude refused native registration. Existing entries were preserved; resolve the conflict and retry MCP sync.")
    registered, conflicts = _native_entries(config_file, scope, project, name)
    if conflicts or registered != desired:
        raise ValueError("Claude registration did not match the validated MCP. Native registration remains unverified; inspect it in Claude before retrying.")
    entries[key] = {**identity, "configHash": expected_hash, "status": "registered"}
    ownership["schemaVersion"] = 1
    atomic_write_json(ownership_file, ownership)
    return {"ok": True, "name": name, "scope": scope, "status": "registered", "restartRequired": True}
