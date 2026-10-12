"""Bounded recovery hints, not permissions or evidence of image observation.

Only a blocked image request creates this short-lived record. No source body,
model response, user prompt or credentials are stored. Ordinary reads never
enter here; there is no catalogue/model discovery or background process.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .paths import atomic_write_json

TTL_SECONDS = 300
MAX_RECORD_BYTES = 16_384
MAX_TARGETS = 4


class HandoffAlreadyUsed(Exception):
    """Do not resume a generic worker after a handoff has been dispatched."""


def _path(root: Path, payload: dict[str, Any]) -> Path | None:
    session = payload.get("session_id")
    cwd = payload.get("cwd")
    if not isinstance(session, str) or not session.strip() or not isinstance(cwd, str) or not cwd.strip():
        return None  # Never discover/fabricate a missing conversation identity.
    key = hashlib.sha256(json.dumps([session, cwd.replace("\\", "/").casefold()],
                                   ensure_ascii=False).encode("utf-8")).hexdigest()
    path = root / "tmp" / "vision-handoffs" / (key + ".json")
    return path if path.resolve().is_relative_to(root.resolve()) else None


def _read(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        if path.stat().st_size > MAX_RECORD_BYTES:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != 1:
            return {}
        age = time.time() - float(value["created"])
        if not 0 <= age < TTL_SECONDS or not isinstance(value.get("targets"), list):
            return {}
        if len(value["targets"]) > MAX_TARGETS:
            return {}
        return value
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def reset(root: Path, payload: dict[str, Any]) -> None:
    """Retire recovery at a new user turn, without creating normal-turn state."""
    try:
        path = _path(root, payload)
        if path is not None and path.exists():
            atomic_write_json(path, {"schema": 1, "created": time.time(), "targets": []})
    except (OSError, ValueError):
        pass  # Optional recovery never becomes a new setup/session prerequisite.


def remember(root: Path, payload: dict[str, Any]) -> str:
    """Return a hint for a denied local Read, never for a permission denial."""
    inputs = payload.get("tool_input") or {}
    if not isinstance(inputs, dict) or payload.get("agent_id"):
        return ""  # A late background child must not repopulate a new turn.
    file = inputs.get("file_path")
    if payload.get("tool_name") != "Read" or not isinstance(file, str) or len(file) > 4096:
        return ""
    try:
        path = _path(root, payload)
        if path is None:
            return ""
        state = _read(path) or {"schema": 1, "created": time.time(), "targets": []}
        # Repeated blocked reads do not reset expiry or grant another attempt.
        for target in state["targets"]:
            if isinstance(target, dict) and target.get("file") == file:
                return str(target.get("marker", ""))
        marker = "[company-vision:" + uuid.uuid4().hex + "]"
        state["targets"] = (state["targets"] + [{"file": file, "marker": marker, "used": False}])[-MAX_TARGETS:]
        while len(json.dumps(state, ensure_ascii=False).encode("utf-8")) + 512 > MAX_RECORD_BYTES:
            state["targets"].pop(0)
            if not state["targets"]:
                return ""
        atomic_write_json(path, state)
        return marker
    except (OSError, ValueError, TypeError):
        return ""


def recover(root: Path, payload: dict[str, Any], vision_agent: str) -> dict[str, Any] | None:
    """Repair one explicitly intended vision handoff, not arbitrary agents.

Requires the same session/folder/turn, an exact target, and either our hint or
the exact requested worker name. Explicit other workers, resumes and forks
are never switched. Failure to read/write state simply retains normal rules.
"""
    inputs = payload.get("tool_input") or {}
    if not isinstance(inputs, dict):
        return None
    if (payload.get("agent_id") or payload.get("tool_name") not in {"Agent", "Task"}
            or inputs.get("subagent_type") not in (None, "", "general-purpose")
            or any(inputs.get(key) for key in ("resume", "fork", "isolation", "team_name"))):
        return None
    prompt = inputs.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return None
    try:
        path = _path(root, payload)
        state = _read(path)
        matches = []
        for target in state.get("targets", []):
            if not isinstance(target, dict) or not isinstance(target.get("used"), bool):
                continue
            file, marker = target.get("file"), target.get("marker")
            if not isinstance(file, str) or not isinstance(marker, str) or not marker:
                continue
            # Exact literal or JSON-escaped path. Do not infer targets by basename.
            # Paths must be delimited, not prefixes such as a.jpg.backup or
            # a.jpg-other.png. The named worker must not be a lookalike either.
            paths = (file, json.dumps(file, ensure_ascii=False)[1:-1])
            path_matches = any(re.search(r'(?<![\w/\\.:-])' + re.escape(p) + r'(?![\w/\\.:-])', prompt) for p in paths)
            named_worker = re.search(r'(?<![\w:.-])' + re.escape(vision_agent) + r'(?![\w:-]|\.[\w-])', prompt)
            if path_matches and (marker in prompt or named_worker):
                matches.append(target)
        if len(matches) != 1 or path is None:
            return None
        if matches[0]["used"]:
            raise HandoffAlreadyUsed()
        matches[0]["used"] = True
        atomic_write_json(path, state)
        return {**payload, "tool_input": {**inputs, "subagent_type": vision_agent}}
    except (OSError, ValueError, TypeError):
        return None
