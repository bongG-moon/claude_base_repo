"""Read-only compatibility checks before a Core writes existing personal state.

This is a version guard, not a migration engine. Unmarked legacy state remains
supported; newer writers must declare incompatible layouts in state-format.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SUPPORTED_STATE_FORMAT = 1
SUPPORTED_USER_CONFIG = {1, 2}  # native and legacy machine initializer
MAX_METADATA_BYTES = 65_536


def _read_metadata(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("Personal state metadata must not be redirected by a link.")
    if not path.exists():
        return None
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_METADATA_BYTES + 1)
        if len(data) > MAX_METADATA_BYTES:
            raise ValueError("metadata too large")
        value = json.loads(data.decode("utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("metadata is not an object")
        return value
    except (OSError, ValueError, UnicodeError) as exc:
        # Never expose config contents or parser excerpts (may include secrets).
        raise ValueError(
            f"Personal state {path.name} cannot be read safely. Files were not reset. "
            "Use a compatible Core or restore reviewed metadata from a backup."
        ) from exc


def assert_supported_version(value: dict[str, Any], supported: set[int], label: str,
                             *, allow_unmarked: bool = True) -> int | None:
    version = value.get("schemaVersion")
    if "schemaVersion" not in value and allow_unmarked:
        return None
    if type(version) is not int or version not in supported:
        raise ValueError(
            f"Unsupported personal {label} schema. Existing data was not converted or reset. "
            "Install a compatible Core; do not delete or change the version marker to bypass this check."
        )
    return version


def check_state_compatibility(root: Path) -> dict[str, Any]:
    """Do not create folders, rewrite metadata, or enumerate private documents."""
    for directory in (root, root / "config"):
        if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)():
            raise ValueError("Personal state metadata folders must not be redirected by a link.")
    marker = _read_metadata(root / "state-format.json")
    config = _read_metadata(root / "config" / "user.json")
    format_version = None if marker is None else assert_supported_version(
        marker, {SUPPORTED_STATE_FORMAT}, "layout", allow_unmarked=False,
    )
    config_version = None if config is None else assert_supported_version(
        config, SUPPORTED_USER_CONFIG, "user configuration",
    )
    return {"ok": True, "stateRoot": str(root), "stateFormatVersion": format_version,
            "userConfigVersion": config_version, "legacyUnmarked": marker is None,
            "migrationPerformed": False}
