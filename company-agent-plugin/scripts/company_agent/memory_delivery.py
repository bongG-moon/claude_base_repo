"""Bounded evidence of memory in prepared hook output, not model compliance.

Call only after the prompt-budget pass. Keep one receipt in the existing active
session: no memory body/title/query, new ledger, source-path lookup or model call.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from .memory import (MAX_MEMORY_CONTEXT_CHARS, MAX_MEMORY_RESULTS,
                     MEMORY_CONTEXT_BEGIN, MEMORY_CONTEXT_END, MEMORY_CONTEXT_INSTRUCTION)
from .paths import atomic_write_json
from .state import _locked_session, _safe_local_path, native_session_id

_FIELD = "company_agent_personal_memory_context"
_RECEIPT = "lastMemoryDelivery"
_TURN = re.compile(r"[a-f0-9]{32}\Z")
_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,159}\Z")
_MAX_HOOK_CHARS = 32_768
_STATUSES = {"output-produced", "budget-dropped", "no-matches", "not-observable"}


def _unknown() -> dict[str, Any]:
    return {"status": "not-observable", "count": 0, "items": [],
            "hostReceipt": "not-observable", "modelApplied": "not-observable"}


def _items(values: Any) -> list[dict[str, Any]] | None:
    if not isinstance(values, list) or not 0 < len(values) <= MAX_MEMORY_RESULTS:
        return None
    result = []
    for value in values:
        if not isinstance(value, dict):
            return None
        identifier, revision = value.get("id"), value.get("revision")
        scope = value.get("storageScope", "unknown")
        if (not isinstance(identifier, str) or not _ID.fullmatch(identifier)
                or type(revision) is not int or not 1 <= revision <= 2_147_483_647
                or not isinstance(scope, str) or scope not in {"personal", "project", "unknown"}):
            return None
        # IDs are labels only: never resolve them as file or storage paths.
        result.append({"id": identifier, "revision": revision, "storageScope": scope})
    return result


def _memory_items(context: Any) -> list[dict[str, Any]] | None:
    prefix = MEMORY_CONTEXT_INSTRUCTION + "\n" + MEMORY_CONTEXT_BEGIN + "\n"
    suffix = "\n" + MEMORY_CONTEXT_END
    if (not isinstance(context, str) or len(context) > MAX_MEMORY_CONTEXT_CHARS
            or not context.startswith(prefix) or not context.endswith(suffix)
            or context.count(MEMORY_CONTEXT_BEGIN) != 1 or context.count(MEMORY_CONTEXT_END) != 1):
        return None
    try:
        value = json.loads(context[len(prefix):-len(suffix)])
        return _items(value.get("items")) if isinstance(value, dict) and set(value) == {"items"} else None
    except (ValueError, TypeError, RecursionError):
        return None


def _final_memory(context: Any) -> tuple[bool, Any]:
    """Read the exact route field, not matching text from candidate descriptions."""
    if not isinstance(context, str) or len(context) > _MAX_HOOK_CHARS:
        return True, None
    found = []
    parsed_object = False
    # JSON strings may legally contain U+2028/U+0085. Only the explicit LF
    # between hook envelopes separates records; str.splitlines() would split
    # inside such a string and lose an otherwise valid delivery receipt.
    for line in context.split("\n"):
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except (ValueError, TypeError, RecursionError):
            return True, None
        if isinstance(value, dict):
            parsed_object = True
            if _FIELD in value:
                found.append(value[_FIELD])
    if not parsed_object:
        return True, None
    return (True, found[0] if len(found) == 1 else None) if found else (False, None)


def record_memory_delivery(root: Path, session_id: str, turn_id: str, final_context: str,
                           *, offered_context: str | None = None,
                           retrieval_status: str = "unknown") -> dict[str, Any]:
    """Record only surviving memory metadata for an already-existing exact turn.

    ``offered_context`` is the original rendered route field before budgeting.
    Set retrieval_status to ``no-matches`` only after successful empty retrieval;
    unavailable/corrupt retrieval is unknown, not evidence of no stored memory.
    This prepares local output evidence, not a host delivery acknowledgment.
    Observability failures never block routing or authorize a tool.
    """
    receipt = _unknown()
    try:
        if (not isinstance(session_id, str) or native_session_id(session_id) != session_id
                or not isinstance(turn_id, str) or not _TURN.fullmatch(turn_id)):
            return receipt
        root = Path(root)
        if not root.is_absolute():
            return receipt
        path = root / "sessions" / f"{session_id}.json"
        lock = path.with_suffix(".json.lock")
        if not _safe_local_path(path, root) or not _safe_local_path(lock, root, allow_missing_leaf=True):
            return receipt
        present, context = _final_memory(final_context)
        items = _memory_items(context) if present else None
        if items:
            receipt.update(status="output-produced", count=len(items), items=items)
        elif not present and _memory_items(offered_context):
            receipt["status"] = "budget-dropped"
        elif not present and not offered_context and retrieval_status == "no-matches":
            receipt["status"] = "no-matches"
        with _locked_session(session_id, root) as (state, session_file):
            if (state.get("sessionId") != session_id or state.get("turnId") != turn_id
                    or not _safe_local_path(session_file, root)):
                return _unknown()
            existing = state.get(_RECEIPT)
            # Replayed native prompt events do not amplify evidence or rewrite
            # an unchanged timestamp. This is not a learning progress counter.
            if (isinstance(existing, dict) and existing.get("turnId") == turn_id
                    and all(existing.get(key) == value for key, value in receipt.items())):
                return memory_delivery_status(state)
            receipt.update(turnId=turn_id, at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            state[_RECEIPT] = receipt
            atomic_write_json(session_file, state)
            return memory_delivery_status(state)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return _unknown()


def memory_delivery_status(session: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pure read of the last supplied session; never discover other sessions."""
    result = _unknown()
    if not isinstance(session, dict):
        return result
    receipt = session.get(_RECEIPT)
    if (not isinstance(receipt, dict) or not isinstance(receipt.get("status"), str)
            or receipt["status"] not in _STATUSES):
        return result
    turn, at = receipt.get("turnId"), receipt.get("at")
    if not isinstance(turn, str) or not _TURN.fullmatch(turn) or not isinstance(at, str) or len(at) > 40:
        return result
    try:
        stamp = datetime.fromisoformat(at)
        if stamp.tzinfo is None:
            return result
    except ValueError:
        return result
    items = _items(receipt.get("items")) if receipt["status"] == "output-produced" else []
    if items is None or type(receipt.get("count")) is not int or receipt["count"] != len(items):
        return result
    result.update(status=receipt["status"], count=len(items), items=items, turnId=turn,
                  at=at, currentTurn=turn == session.get("turnId"))
    return result
