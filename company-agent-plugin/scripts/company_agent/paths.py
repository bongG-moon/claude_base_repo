from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def _windows_env_path(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else fallback


def user_state_root() -> Path:
    override = os.environ.get("COMPANY_AGENT_USER_STATE")
    if override:
        return Path(override).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "CompanyAgent"
    return Path.home() / ".company-agent"


def knowledge_base_root() -> Path | None:
    value = os.environ.get("COMPANY_AGENT_KNOWLEDGE_BASE")
    return Path(value).expanduser() if value else None


def ensure_user_layout(root: Path | None = None) -> dict[str, Path]:
    base = root or user_state_root()
    from .state_compatibility import check_state_compatibility
    check_state_compatibility(base)
    paths = {
        "root": base,
        "config": base / "config",
        "knowledge": base / "knowledge",
        "entries": base / "knowledge" / "entries",
        "overlays": base / "knowledge" / "overlays",
        "versions": base / "knowledge" / "versions",
        "conflicts": base / "knowledge" / "conflicts",
        "index": base / "knowledge" / "generated-index",
        "exports": base / "knowledge" / "exports",
        "sessions": base / "sessions",
        "personal_root": base / "personal-root",
        "personal_skills": base / "personal-root" / ".claude" / "skills",
        "tools": base / "tools",
        "mcp": base / "mcp",
        "memory": base / "memory",
        "memory_items": base / "memory" / "items",
        "memory_versions": base / "memory" / "versions",
        "memory_index": base / "memory" / "index",
        "tmp": base / "tmp",
        "ledger": base / "ledger",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows scanners can momentarily hold the destination without sharing
        # delete access. Retry this SAME atomic replace only; never change ACL,
        # clear attributes, delete the destination, or fall back to truncation.
        for attempt in range(4):
            try:
                os.replace(temp_name, path)
                break
            except OSError as exc:
                if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 3:
                    raise
                time.sleep(0.025 * (2 ** attempt))
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)
