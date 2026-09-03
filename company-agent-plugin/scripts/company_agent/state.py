from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .paths import atomic_write_json, ensure_user_layout, load_json, user_state_root
from .policy import db_operation, is_outlook_send_like_tool, outlook_operation


MUTATING_TOOLS = {"edit", "multiedit", "notebookedit", "write"}
MAX_CORRECTIVE_CONTINUATIONS = 2

_MCP_TOOL_RE = re.compile(
    r"^mcp__(?P<server>[a-z0-9][a-z0-9_.:-]*)__+(?P<operation>[a-z0-9][a-z0-9_.:-]*)$",
    re.IGNORECASE,
)
_READ_ONLY_MCP_OPERATION_PREFIXES = {
    "count",
    "describe",
    "fetch",
    "get",
    "health",
    "inspect",
    "list",
    "lookup",
    "metadata",
    "ping",
    "query",
    "read",
    "search",
    "select",
    "show",
}
_MUTATING_MCP_OPERATION_WORDS = {
    "add",
    "apply",
    "archive",
    "cancel",
    "clean",
    "create",
    "delete",
    "edit",
    "execute",
    "forward",
    "insert",
    "move",
    "patch",
    "post",
    "publish",
    "remove",
    "reply",
    "restore",
    "run",
    "send",
    "set",
    "submit",
    "update",
    "upload",
    "write",
}

# This is intentionally conservative. A command that can execute an arbitrary
# script or redirect output may have changed files before a failed tool result
# arrives, so it creates a verification obligation.
_MUTATING_COMMAND_PATTERN = re.compile(
    r"""
    (?:^|[;&|]\s*)
    (?:
        rm|del|erase|move|mv|cp|copy|mkdir|rmdir|
        new-item|set-content|add-content|out-file|remove-item|move-item|copy-item|
        python(?:3(?:\.\d+)?)?|py|powershell|pwsh|cmd|wscript|cscript|bash|sh|
        git\s+(?:add|apply|checkout|clean|commit|mv|push|reset|restore|stash|switch)|
        npm\s+(?:install|uninstall)|pip(?:3)?\s+install
    )\b
    |
    \b(?:set-content|add-content|out-file|new-item|remove-item|move-item|copy-item)\b
    |
    \b(?:python(?:3(?:\.\d+)?)?|py|powershell|pwsh|cmd|wscript|cscript|bash|sh)\b
    |
    \bgit\s+(?:add|apply|checkout|clean|commit|mv|push|reset|restore|stash|switch)\b
    |
    (?<![<>=])(?:\d*>>?|&>)(?![=>])
    |
    \.(?:ps1|py|cmd|bat|vbs|js)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()
_LOCK_TIMEOUT_SECONDS = 10.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def safe_session_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]", "-", value).strip("-.")
    if normalized:
        return normalized[:100]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def session_path(session_id: str, root: Path | None = None) -> Path:
    layout = ensure_user_layout(root or user_state_root())
    return layout["sessions"] / f"{safe_session_id(session_id)}.json"


def _default_session(session_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "sessionId": safe_session_id(session_id),
        "mutationCount": 0,
        "verification": None,
        "stopRetryCount": 0,
        "sameFailureCount": 0,
        "lastFailureFingerprint": None,
        "recentTools": [],
    }


def _thread_lock_for(path: Path) -> threading.Lock:
    key = os.path.normcase(str(path.absolute()))
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def _interprocess_lock(lock_path: Path) -> Iterator[None]:
    """Take a one-byte advisory lock supported by native Windows Python."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stream = lock_path.open("a+b")
    locked = False
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()

        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out locking session state: {lock_path.name}")
                time.sleep(0.01)
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _load_session_unlocked(path: Path, session_id: str) -> dict[str, Any]:
    loaded = load_json(path, _default_session(session_id))
    if not isinstance(loaded, dict):
        raise ValueError("session state must be a JSON object")
    state = _default_session(session_id)
    state.update(loaded)
    return state


@contextmanager
def _locked_session(
    session_id: str,
    root: Path | None,
) -> Iterator[tuple[dict[str, Any], Path]]:
    path = session_path(session_id, root)
    thread_lock = _thread_lock_for(path)
    with thread_lock:
        with _interprocess_lock(path.with_suffix(path.suffix + ".lock")):
            yield _load_session_unlocked(path, session_id), path


def load_session(session_id: str, root: Path | None = None) -> dict[str, Any]:
    with _locked_session(session_id, root) as (state, _):
        return state


def begin_turn(
    session_id: str,
    tier: str,
    verification_required: bool,
    reason_codes: list[str] | tuple[str, ...],
    root: Path | None = None,
) -> dict[str, Any]:
    with _locked_session(session_id, root) as (state, path):
        state.update(
            {
                "turnStartedAt": _now(),
                "route": {
                    "tier": tier,
                    "verificationRequired": bool(verification_required),
                    "reasonCodes": list(reason_codes),
                },
                "mutationCount": 0,
                "verification": None,
                "stopRetryCount": 0,
                "sameFailureCount": 0,
                "lastFailureFingerprint": None,
                "recentTools": [],
            }
        )
        atomic_write_json(path, state)
        return state


def _mcp_operation_is_read_only(operation: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", operation.casefold()).strip("_")
    words = {word for word in normalized.split("_") if word}
    if words.intersection(_MUTATING_MCP_OPERATION_WORDS):
        return False
    first_word = normalized.split("_", 1)[0] if normalized else ""
    return first_word in _READ_ONLY_MCP_OPERATION_PREFIXES


def _tool_mutated(tool_name: str, tool_input: dict[str, Any]) -> bool:
    normalized = tool_name.casefold().strip()
    if is_outlook_send_like_tool(normalized):
        return True
    if db_operation(normalized) is not None:
        return False
    managed_outlook_operation = outlook_operation(normalized)
    if managed_outlook_operation is not None:
        return not _mcp_operation_is_read_only(managed_outlook_operation)

    short_name = normalized.rsplit("__", 1)[-1]
    if short_name in MUTATING_TOOLS:
        return True
    if short_name in {"bash", "powershell"}:
        command = str(tool_input.get("command") or tool_input.get("cmd") or "")
        return bool(_MUTATING_COMMAND_PATTERN.search(command))

    mcp_match = _MCP_TOOL_RE.fullmatch(normalized)
    if mcp_match:
        # Launch uses --strict-mcp-config with managed + personal registries.
        # Any non-corporate MCP operation that is not explicitly read-only is
        # therefore conservatively treated as potentially mutating.
        return not _mcp_operation_is_read_only(mcp_match.group("operation"))
    return False


def record_activity(
    payload: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown-session")
    tool_name = str(payload.get("tool_name") or "unknown")
    tool_input = (
        payload.get("tool_input")
        if isinstance(payload.get("tool_input"), dict)
        else {}
    )
    mutated = _tool_mutated(tool_name, tool_input)
    failed = (
        str(payload.get("hook_event_name") or "").casefold()
        == "posttoolusefailure"
        or bool(payload.get("tool_error"))
        or bool(payload.get("error"))
    )
    at = _now()
    event = {
        "at": at,
        "tool": tool_name,
        "success": not failed,
        "mutation": mutated,
    }

    with _locked_session(session_id, root) as (state, path):
        recent = list(state.get("recentTools", []))[-19:]
        recent.append(event)
        state["recentTools"] = recent
        state["lastActivityAt"] = at
        if mutated:
            previous_verification = state.get("verification")
            state["mutationCount"] = _safe_nonnegative_int(
                state.get("mutationCount")
            ) + 1
            state["lastMutationAt"] = at
            state["verification"] = None
            if (
                isinstance(previous_verification, dict)
                and previous_verification.get("status") == "pass"
            ):
                state["stopRetryCount"] = 0
                state["sameFailureCount"] = 0
                state["lastFailureFingerprint"] = None
        atomic_write_json(path, state)
        return state


def mark_verified(
    session_id: str,
    status: str,
    summary: str,
    root: Path | None = None,
) -> dict[str, Any]:
    if status not in {"pass", "fail"}:
        raise ValueError("verification status must be pass or fail")
    compact_summary = summary.strip()[:500]

    with _locked_session(session_id, root) as (state, path):
        state["verification"] = {
            "status": status,
            "at": _now(),
            "summary": compact_summary,
        }
        if status == "pass":
            state["stopRetryCount"] = 0
            state["sameFailureCount"] = 0
            state["lastFailureFingerprint"] = None
        else:
            fingerprint = hashlib.sha256(
                compact_summary.casefold().encode("utf-8")
            ).hexdigest()[:16]
            if state.get("lastFailureFingerprint") == fingerprint:
                state["sameFailureCount"] = _safe_nonnegative_int(
                    state.get("sameFailureCount")
                ) + 1
            else:
                state["sameFailureCount"] = 1
            state["lastFailureFingerprint"] = fingerprint
        atomic_write_json(path, state)
        return state


def _failure_message(kind: str) -> dict[str, Any]:
    if kind == "same-failure":
        message = (
            "Company Agent stopped after the same verification failure repeated. "
            "Verification did not pass; do not treat this run as successful. "
            "Report the failure evidence and the required next action honestly."
        )
    else:
        message = (
            "Company Agent stopped after two corrective verification attempts. "
            "Verification did not pass; do not treat this run as successful. "
            "Report the unverified changes and the required next action honestly."
        )
    return {"systemMessage": message}


def stop_decision(
    payload: dict[str, Any],
    root: Path | None = None,
    max_retries: int = MAX_CORRECTIVE_CONTINUATIONS,
) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown-session")
    # A caller may reduce the budget for tests or stricter deployments, but
    # never raise it above the fixed production ceiling of two continuations.
    retry_budget = min(
        MAX_CORRECTIVE_CONTINUATIONS,
        _safe_nonnegative_int(max_retries),
    )

    with _locked_session(session_id, root) as (state, path):
        if _safe_nonnegative_int(state.get("mutationCount")) == 0:
            return {}
        verification = state.get("verification")
        if (
            isinstance(verification, dict)
            and verification.get("status") == "pass"
        ):
            return {}
        if (
            isinstance(verification, dict)
            and verification.get("status") == "fail"
            and _safe_nonnegative_int(state.get("sameFailureCount"))
            >= MAX_CORRECTIVE_CONTINUATIONS
        ):
            return _failure_message("same-failure")

        retry_count = _safe_nonnegative_int(state.get("stopRetryCount"))
        if retry_count >= retry_budget:
            return _failure_message("budget")

        # `stop_hook_active` means this is a corrective continuation. It must
        # not disable the second bounded attempt; the persisted counter is the
        # loop guard for both initial and active Stop events.
        state["stopRetryCount"] = retry_count + 1
        atomic_write_json(path, state)

    reason = (
        "변경 사항에 대한 검증 성공 기록이 없습니다. 관련 테스트나 정적 검사를 실행한 뒤 다음 명령으로 결과를 기록하세요: "
        f'company-agent session verify --session "{safe_session_id(session_id)}" --status pass --summary "검증 내용". '
        "검증에 실패하면 status fail로 기록하고 원인을 수정하십시오. "
        f"보정 기회는 최대 {MAX_CORRECTIVE_CONTINUATIONS}회이며, 이후에는 실패를 성공으로 표현하지 말고 남은 위험을 명확히 보고하십시오."
    )
    return {"decision": "block", "reason": reason}
