from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
import re
import shutil
import stat
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .paths import atomic_write_json, ensure_user_layout, load_json, user_state_root
from .policy import db_operation, is_outlook_send_like_tool, outlook_operation


MUTATING_TOOLS = {"edit", "multiedit", "notebookedit", "write"}
MAX_CORRECTIVE_CONTINUATIONS = 2
MAX_LEARNING_CONTINUATIONS = 2
MAX_OBSERVED_SKILLS = 8
MAX_OBSERVED_SKILL_BYTES = 65_536
_TURN_ID_RE = re.compile(r"^[a-f0-9]{32}$")

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


def _native_prompt_digest(value: Any) -> str | None:
    """Correlate newer Claude hook events without retaining the native ID."""
    if not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", value):
        return None
    return hashlib.sha256(str(uuid.UUID(value)).encode("ascii")).hexdigest()


def _stale_native_prompt(payload: dict[str, Any], state: dict[str, Any]) -> bool:
    incoming = _native_prompt_digest(payload.get("prompt_id"))
    current = state.get("nativePromptSha256")
    return bool(incoming and isinstance(current, str) and re.fullmatch(r"[a-f0-9]{64}", current) and incoming != current)


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
    from .state_compatibility import assert_supported_version
    assert_supported_version(loaded, {1}, "session")
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
    *,
    native_prompt_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(session_id, str) or not session_id.strip() or session_id == "unknown-session":
        raise ValueError("a real session identifier is required to start a turn")
    from .learning import learning_enabled

    enabled = learning_enabled(root or user_state_root())
    native_digest = _native_prompt_digest(native_prompt_id)
    with _locked_session(session_id, root) as (state, path):
        if native_digest and state.get("nativePromptSha256") == native_digest and learning_context(state):
            # A repeated delivery of the same native user prompt must not grant
            # new verification/review budgets or amplify learning observations.
            return state
        previous_turn = state.get("turnId")
        from .work import new_work
        work = state.setdefault("work", new_work())
        if not enabled:
            work["pending"] = []
            work["reviewRequested"] = False
        # Continue the same work until the coordinator explicitly begins a new
        # topic. User replies and compaction must not amplify learning samples.
        if work.get("status") == "complete":
            work["status"] = "active"
            work["reviewRequested"] = False
        outstanding = state.get("mutationCount", 0) and (state.get("verification") or {}).get("status") != "pass"
        obligation = {key: state.get(key) for key in ("mutationCount", "verification", "stopRetryCount",
                      "sameFailureCount", "lastFailureFingerprint")} if outstanding else {}
        state.update(
            {
                "turnId": uuid.uuid4().hex,
                "nativePromptSha256": native_digest,
                "previousTurnId": previous_turn if isinstance(previous_turn, str) and _TURN_ID_RE.fullmatch(previous_turn) else None,
                "learningStatus": "pending" if enabled else "disabled",
                "learningCompletedAt": None,
                "learningDeferredReason": None,
                "learningAttempts": 0,
                "usedSkills": [],
                "taskToolCount": 0,
                "approvalUnavailable": False,
                "lastStopActivityCount": None,
                "taskFailureCount": 0,
                "taskVerificationFailures": 0,
                "turnStartedAt": _now(),
                "route": {
                    "tier": tier,
                    "modelAlias": {"LARGE": "opus", "MEDIUM": "sonnet", "SMALL": "haiku"}.get(tier.upper()),
                    "actualModel": "unverified",
                    "verificationRequired": bool(verification_required),
                    "reasonCodes": list(reason_codes),
                },
                "mutationCount": 0,
                "verification": None,
                "stopRetryCount": 0,
                "sameFailureCount": 0,
                "lastFailureFingerprint": None,
                "recentTools": [],
                "workerExecutions": [],
            }
        )
        state.update(obligation)
        atomic_write_json(path, state)
        return state


def learning_context(state: dict[str, Any]) -> dict[str, Any] | None:
    """Expose bounded lifecycle identifiers, never task text or tool input."""
    turn_id = state.get("turnId")
    if not isinstance(turn_id, str) or not _TURN_ID_RE.fullmatch(turn_id):
        return None
    previous = state.get("previousTurnId")
    from .work import context as work_context
    return {
        "policy": "work-milestone",
        "work": work_context(state),
        "turnId": turn_id,
        "previousTurnId": previous if isinstance(previous, str) and _TURN_ID_RE.fullmatch(previous) else None,
        "status": state.get("learningStatus") if state.get("learningStatus") in {"pending", "disabled", "complete", "deferred"} else "disabled",
        "attempts": min(MAX_LEARNING_CONTINUATIONS, _safe_nonnegative_int(state.get("learningAttempts"))),
    }


def _collect_learning_observations(state: dict[str, Any], root: Path) -> bool:
    """A paused observation gap cannot be resumed as a complete task sample.

    Existing business verification remains independent. Only a genuinely new
    user turn can enable collection again after this turn encountered a pause.
    """
    if not learning_context(state) or state.get("learningStatus") == "disabled":
        return False
    from .learning import learning_enabled

    if not learning_enabled(root):
        state["learningStatus"] = "disabled"
        state["learningDeferredReason"] = "paused-during-turn"
        return False
    return True


def mark_learning_complete(session_id: str, turn_id: str, root: Path | None = None) -> dict[str, Any]:
    """A successful review can complete only the exact still-current turn.

    Verification evidence and its budgets are never changed here. Repeating a
    successful CLI call is harmless; an old worker cannot complete a newer turn.
    """
    if not session_id or session_id == "unknown-session" or not _TURN_ID_RE.fullmatch(turn_id or ""):
        raise ValueError("valid session and turn identifiers are required")
    with _locked_session(session_id, root) as (state, path):
        if state.get("turnId") != turn_id:
            raise ValueError("learning review does not belong to the current turn")
        if state.get("learningDeferredReason") == "late-business-activity":
            raise ValueError("work continued after this turn's review; do not mark the earlier review as current")
        if state.get("learningStatus") not in {"pending", "deferred", "complete"}:
            raise ValueError("learning is not enabled for this turn")
        if state.get("learningStatus") != "complete":
            state["learningStatus"] = "complete"
            state["learningCompletedAt"] = _now()
            atomic_write_json(path, state)
        return state


def _mcp_operation_is_read_only(operation: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", operation.casefold()).strip("_")
    words = {word for word in normalized.split("_") if word}
    if words.intersection(_MUTATING_MCP_OPERATION_WORDS):
        return False
    first_word = normalized.split("_", 1)[0] if normalized else ""
    return first_word in _READ_ONLY_MCP_OPERATION_PREFIXES


def _literal_command_words(command: str, *, allow_percent: bool = False) -> list[str] | None:
    """Accept only literal command words, never shell programs or expansions."""

    if any(character in command for character in ("\r\n\0$`" if allow_percent else "\r\n\0$`%")):
        return None
    value = command.strip()
    # PowerShell's call operator is safe only before the one literal command.
    if value.startswith("& "):
        value = value[2:].lstrip()
    words: list[str] = []
    current: list[str] = []
    quote = ""
    started = False
    for character in value:
        if quote:
            if character == quote:
                # Backslash-escaped quotes have different shell semantics.
                if current and current[-1] == "\\":
                    return None
                quote = ""
            else:
                current.append(character)
        elif character in "\"'":
            quote = character
            started = True
        elif character.isspace():
            if started:
                words.append("".join(current))
                current = []
                started = False
        elif character in ";|<>&(){}[]":
            return None
        else:
            current.append(character)
            started = True
    if quote:
        return None
    if started:
        words.append("".join(current))
    return words


def _same_absolute_path(value: str, expected: Path) -> bool:
    try:
        path = Path(value)
        return path.is_absolute() and path.resolve() == expected.resolve()
    except (OSError, ValueError):
        return False


def _known_runtime(value: str, names: set[str]) -> bool:
    if value.casefold() in names:
        return True
    # An arbitrary path named python.exe/powershell.exe is not trusted merely
    # because its filename matches. Accept only a runtime resolved locally.
    expected = [Path(sys.executable)] if "python" in names else []
    if "python" in names and os.environ.get("COMPANY_AGENT_PYTHON"):
        expected.append(Path(os.environ["COMPANY_AGENT_PYTHON"]))
    for name in names:
        resolved = shutil.which(name)
        if resolved and Path(resolved).suffix.casefold() == ".exe":
            expected.append(Path(resolved))
    return any(_same_absolute_path(value, path) for path in expected)


def _own_cli_arguments(command: str) -> list[str] | None:
    """Identify literal arguments to this installed CLI, not an arbitrary script.

    This is a narrow bookkeeping exception, not a permission rule. Every
    unrecognized/compound invocation retains conservative mutation detection.
    """

    words = _literal_command_words(command)
    if not words and "%" in command:
        # A literal percentage in a summary is not an expansion for a directly
        # invoked trusted .exe. Never extend this to cmd/batch/PATH wrappers.
        candidate = _literal_command_words(command, allow_percent=True)
        if candidate and Path(candidate[0]).is_absolute() and Path(candidate[0]).suffix.casefold() == ".exe":
            if (_known_runtime(candidate[0], {"python", "python.exe"})
                    or _known_runtime(candidate[0], {"powershell", "powershell.exe", "pwsh", "pwsh.exe"})):
                words = candidate
    if not words:
        return None
    program, *arguments = words
    scripts = Path(__file__).resolve().parents[1]
    if program.casefold() == "company-agent" or _same_absolute_path(
        program, scripts.parent / "bin" / "company-agent.cmd"
    ):
        pass
    elif _known_runtime(program, {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}):
        while arguments and arguments[0].casefold() in {"-noprofile", "-noninteractive", "-nologo"}:
            arguments.pop(0)
        if len(arguments) >= 2 and arguments[0].casefold() == "-executionpolicy":
            if arguments[1].casefold() not in {"bypass", "remotesigned"}:
                return None
            arguments = arguments[2:]
        if len(arguments) < 4 or arguments[0].casefold() != "-file":
            return None
        if not _same_absolute_path(arguments[1], scripts / "Invoke-CompanyAgent.ps1"):
            return None
        if arguments[2].casefold() != "-mode" or arguments[3].casefold() != "cli":
            return None
        arguments = arguments[4:]
    elif _known_runtime(program, {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}):
        if arguments and arguments[0] in {"-3", "-3.11", "-3.12", "-3.13", "-3.14"}:
            arguments.pop(0)
        while arguments and arguments[0] in {"-I", "-B", "-u"}:
            arguments.pop(0)
        if not arguments or not _same_absolute_path(arguments[0], scripts / "harness_cli.py"):
            return None
        arguments = arguments[1:]
    else:
        return None
    return arguments


def _is_own_context_audit(command: str) -> bool:
    arguments = _own_cli_arguments(command)
    if arguments == ["context", "audit"]:
        return True
    return bool(arguments and len(arguments) == 4 and arguments[:3] == ["context", "audit", "--project"]
                and Path(arguments[3]).is_absolute())


def _is_own_verification_command(command: str, session_id: str, root: Path | None = None) -> bool:
    """Do not invalidate a verification marker while recording its own call."""
    arguments = _own_cli_arguments(command)
    if not arguments:
        return False
    if arguments[:2] != ["session", "verify"]:
        return False
    arguments = arguments[2:]
    if len(arguments) not in {6, 8}:
        return False
    fields: dict[str, str] = {}
    for index in range(0, len(arguments), 2):
        key, value = arguments[index:index + 2]
        if key not in {"--session", "--status", "--summary", "--state-root"} or key in fields or not value:
            return False
        fields[key] = value
    return (bool(fields.get("--summary")) and fields.get("--session") == safe_session_id(session_id)
            and fields.get("--status") in {"pass", "fail", "not_applicable", "partial", "unavailable"}
            and ("--state-root" not in fields or (root is not None and _same_absolute_path(fields["--state-root"], root))))


def _is_own_work_command(command: str, session_id: str, state: dict, root: Path) -> bool:
    args = _own_cli_arguments(command)
    if not args or len(args) < 2 or args[0] != "work" or args[1] not in {"checkpoint", "resolve"}:
        return False
    words = _literal_command_words(command)
    if words and words[0] == "company-agent":
        resolved = shutil.which("company-agent")
        if not resolved or not _same_absolute_path(resolved, Path(__file__).resolve().parents[2] / "bin" / "company-agent.cmd"):
            return False
    values = {}
    tail = args[2:]
    if len(tail) % 2:
        return False
    for key, value in zip(tail[::2], tail[1::2]):
        allowed = {"--session", "--turn", "--work-id", "--state-root"} if args[1] == "resolve" else {"--session", "--turn", "--status", "--learn", "--new", "--state-root"}
        if key in values or key not in allowed:
            return False
        values[key] = value
    if args[1] == "resolve":
        return (values.get("--session") == safe_session_id(session_id) and values.get("--turn") == state.get("turnId")
                and any(item.get("workId") == values.get("--work-id") for item in state.get("resolvedChanges", []) + state.get("unresolvedChanges", []))
                and ("--state-root" not in values or _same_absolute_path(values["--state-root"], root)))
    return (values.get("--session") == safe_session_id(session_id) and values.get("--turn") == state.get("turnId")
            and values.get("--status") in {"active", "waiting", "complete", "cancelled"}
            and values.get("--learn", "no") in {"yes", "no"} and values.get("--new", "no") in {"yes", "no"}
            and ("--state-root" not in values or _same_absolute_path(values["--state-root"], root)))


def _safe_local_path(path: Path, boundary: Path, *, allow_missing_leaf: bool = False) -> bool:
    """Reject redirected paths before observing skills or exempting a write."""
    try:
        if not path.is_absolute() or len(str(path)) > 2_048 or ".." in path.parts:
            return False
        boundary = boundary.absolute()
        path.relative_to(boundary)
        if path.resolve() != path.absolute():
            return False
        for component in (path, *path.parents):
            try:
                metadata = component.lstat()
            except FileNotFoundError:
                if allow_missing_leaf and component == path:
                    continue
                return False
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                return False
        return True
    except (OSError, ValueError):
        return False


def _learning_spec_path(root: Path, turn_id: str) -> Path:
    return root.absolute() / "tmp" / f"learning-review-{turn_id}.json"


def _is_learning_spec_write(tool_name: str, tool_input: dict[str, Any], state: dict[str, Any], root: Path) -> bool:
    if tool_name.casefold().strip() != "write":
        return False
    turn_id = state.get("turnId")
    if not isinstance(turn_id, str) or not _TURN_ID_RE.fullmatch(turn_id) or state.get("learningStatus") != "pending":
        return False
    value = tool_input.get("file_path")
    if not isinstance(value, str):
        return False
    path = Path(value)
    return path == _learning_spec_path(root, turn_id) and _safe_local_path(path, root, allow_missing_leaf=True)


def _is_mail_search_spec_write(tool_name: str, tool_input: dict, root: Path) -> bool:
    """A typed disposable search request is not a business artifact change.

    Classification only, NOT file write permission. No arbitrary tmp exception.
    """
    import json
    if tool_name.casefold() != "write":
        return False
    value, content = tool_input.get("file_path"), tool_input.get("content")
    if not isinstance(value, str) or not isinstance(content, str) or len(content.encode("utf-8")) > 32768:
        return False
    path = Path(value)
    if (path.parent != root.absolute() / "tmp" or
            not re.fullmatch(r"mail-search-[a-zA-Z0-9_-]{1,80}\.json", path.name) or
            not _safe_local_path(path, root, allow_missing_leaf=True)):
        return False
    try:
        from .business_mail import _normalize_spec
        _normalize_spec("search", json.loads(content))
        return True
    except (ValueError, TypeError, OSError, OverflowError):
        return False


def _is_office_read_spec_write(tool_name: str, tool_input: dict, root: Path) -> bool:
    """Only the bounded source-selection request, never arbitrary tmp content."""
    import json
    if tool_name.casefold() != 'write':
        return False
    value, content = tool_input.get('file_path'), tool_input.get('content')
    if not isinstance(value,str) or not isinstance(content,str) or len(content.encode('utf-8'))>32768:
        return False
    path=Path(value)
    if (path.parent != root.absolute()/'tmp' or not re.fullmatch(r'office-read-[a-zA-Z0-9_-]{1,80}\.json',path.name)
            or not _safe_local_path(path,root,allow_missing_leaf=True)):
        return False
    try:
        from .office_reader import normalize
        normalize(json.loads(content))
        return True
    except (ValueError,TypeError,OSError):
        return False


def _is_ppt_choices_spec_write(tool_name: str, tool_input: dict, root: Path) -> bool:
    """Only bounded temporary choice metadata, never jobs or output slides."""
    import json
    if tool_name.casefold()!='write':
        return False
    value,content=tool_input.get('file_path'),tool_input.get('content')
    if not isinstance(value,str) or not isinstance(content,str) or len(content.encode('utf-8'))>8192:
        return False
    path=Path(value)
    if (path.parent!=root.absolute()/'tmp' or not re.fullmatch(r'ppt-choices-[a-zA-Z0-9_-]{1,80}\.json',path.name)
            or not _safe_local_path(path,root,allow_missing_leaf=True)):
        return False
    try:
        spec=json.loads(content)
        if not isinstance(spec,dict) or set(spec)-{'creationMode','referenceMode','purpose','audience','slideCount','designPreset'}:
            return False
        from .ppt_workflow import choices
        result=choices(spec)
        return result.get('status') in {'input_required','preview_required'} and 'code' not in result
    except (ValueError,TypeError,OSError):
        return False


def _is_html_choices_spec_write(tool_name: str, tool_input: dict, root: Path) -> bool:
    """Disposable design choices only; not report jobs, artifacts or permission."""
    import json
    if tool_name.casefold() not in {"write", "edit"}:
        return False
    value, content = tool_input.get("file_path"), tool_input.get("content")
    if not isinstance(value, str):
        return False
    path = Path(value)
    if (path.parent != root.absolute() / "tmp"
            or not re.fullmatch(r"html-choices-[a-zA-Z0-9_-]{1,80}\.json", path.name)
            or not _safe_local_path(path, root, allow_missing_leaf=True)):
        return False
    try:
        if tool_name.casefold() == 'edit':
            # PostToolUse only: validate the complete resulting metadata, not
            # an arbitrary replacement fragment. Never exempt jobs or reports.
            with path.open('rb') as stream:
                content = stream.read(8193).decode('utf-8-sig')
        if not isinstance(content, str) or len(content.encode('utf-8')) > 8192:
            return False
        spec = json.loads(content)
        from .business_artifacts import html_choice_selection, ArtifactError
        try:
            html_choice_selection(spec, metadata_only=True)
        except ArtifactError:
            return False
        return True
    except (ValueError, TypeError, OSError):
        return False


def _is_own_learning_command(command: str, session_id: str, state: dict[str, Any], root: Path) -> bool:
    arguments = _own_cli_arguments(command)
    if not arguments:
        return False
    if "--state-root" in arguments:
        index = arguments.index("--state-root")
        if (arguments.count("--state-root") != 1 or index + 1 >= len(arguments)
                or not _same_absolute_path(arguments[index + 1], root)):
            return False
        arguments = arguments[:index] + arguments[index + 2:]
    words = _literal_command_words(command)
    if words and words[0].casefold() == "company-agent":
        # A similarly named program on PATH must not bypass business checks.
        installed_bin = Path(__file__).resolve().parents[2] / "bin" / "company-agent.cmd"
        resolved = shutil.which("company-agent")
        if not resolved or not _same_absolute_path(resolved, installed_bin):
            return False
    if arguments == ["learning", "status"] or arguments == ["learning", "status", "--session", safe_session_id(session_id)]:
        return True
    if len(arguments) != 8 or arguments[0] != "learning" or arguments[1] not in {"review", "stage"}:
        return False
    fields: dict[str, str] = {}
    for index in range(2, len(arguments), 2):
        key, value = arguments[index:index + 2]
        if key not in {"--session", "--turn", "--spec"} or key in fields or not value:
            return False
        fields[key] = value
    turn_id = state.get("turnId")
    if not isinstance(turn_id, str) or not _TURN_ID_RE.fullmatch(turn_id):
        return False
    if fields.get("--session") != safe_session_id(session_id) or fields.get("--turn") != turn_id:
        return False
    path = Path(fields.get("--spec", ""))
    return path == _learning_spec_path(root, turn_id) and _safe_local_path(path, root, allow_missing_leaf=True)


def _observed_personal_skill(tool_name: str, tool_input: dict[str, Any], root: Path) -> dict[str, str] | None:
    if tool_name.casefold().strip() != "read":
        return None
    value = tool_input.get("file_path")
    if not isinstance(value, str) or len(value) > 2_048:
        return None
    path = Path(value)
    skills_root = root.absolute() / "personal-root" / ".claude" / "skills"
    try:
        relative = path.relative_to(skills_root)
        if len(relative.parts) != 2 or relative.name != "SKILL.md":
            return None
        name = relative.parts[0]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", name):
            return None
        if not _safe_local_path(path, skills_root) or path.stat().st_size > MAX_OBSERVED_SKILL_BYTES:
            return None
        with path.open("rb") as stream:
            data = stream.read(MAX_OBSERVED_SKILL_BYTES + 1)
        if len(data) > MAX_OBSERVED_SKILL_BYTES:
            return None
        # Hash only. The read body, other paths and search query never persist.
        return {"name": name, "path": str(path), "sha256": hashlib.sha256(data).hexdigest()}
    except (OSError, ValueError):
        return None


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
        # Existing Claude MCP sources and additive Harness registries may both
        # be visible. Any non-corporate MCP operation that is not explicitly
        # read-only is therefore conservatively treated as potentially mutating.
        return not _mcp_operation_is_read_only(mcp_match.group("operation"))
    return False


def _native_action_not_performed(payload: dict[str, Any]) -> bool:
    """Recognize the host's explicit pre-execution rejection, not tool failures.

    A generic PermissionError can follow partial writes. Never exempt those.
    Only metadata is retained, and existing unverified changes stay outstanding.
    """
    if (payload.get("hook_event_name") != "PostToolUseFailure"
            or payload.get("tool_name") not in {"Bash", "Write", "Edit", "Read", "Glob", "Grep"}):
        return False
    error = payload.get("error")
    return (isinstance(error, str)
            and error.startswith("Permission for this tool use was denied.")
            and "The action was NOT performed" in error)


def record_activity(
    payload: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    session_id = str(payload.get("session_id") or "unknown-session")
    tool_name = str(payload.get("tool_name") or "unknown")
    tool_input = (
        payload.get("tool_input")
        if isinstance(payload.get("tool_input"), dict)
        else {}
    )
    mutated = _tool_mutated(tool_name, tool_input)
    not_performed = _native_action_not_performed(payload)
    from .runtime_diagnostics import classifier_unavailable
    approval_timeout = classifier_unavailable(payload)
    not_performed = not_performed or approval_timeout
    response = payload.get("tool_response")
    failed = (
        str(payload.get("hook_event_name") or "").casefold()
        == "posttoolusefailure"
        or bool(payload.get("tool_error"))
        or bool(payload.get("error"))
        or (isinstance(response, dict) and (response.get("isError") is True or response.get("is_error") is True))
    )
    at = _now()
    with _locked_session(session_id, root) as (state, path):
        if _stale_native_prompt(payload, state):
            return state
        from .workflow_evidence import observe_business_result
        try:
            observe_business_result(state, payload, not_performed=not_performed)
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            pass  # Optional diagnostics cannot block work or alter permissions.
        from .background_work import observe as observe_background
        observe_background(state, payload, failed)
        if not_performed:
            mutated = False
            state["approvalUnavailable"] = True
        from .business_safety import protection_notice
        if protection_notice(payload):
            # Metadata only. Never preserve the offending response/document.
            state["protectionRestricted"] = True
            if isinstance(state.get("verification"), dict):
                state["verification"]["summary"] = "보호 제한 항목이 있어 상세 검증 설명은 보존하지 않습니다."
        collect_learning = _collect_learning_observations(state, root or user_state_root())
        bookkeeping = approval_timeout
        if tool_name.casefold().strip() in {"bash", "powershell"}:
            command = str(tool_input.get("command") or tool_input.get("cmd") or "")
            bookkeeping = bookkeeping or (
                _is_own_verification_command(command, session_id, root or user_state_root())
                or _is_own_context_audit(command)
                or _is_own_learning_command(command, session_id, state, root or user_state_root())
            )
        bookkeeping = bookkeeping or _is_learning_spec_write(tool_name, tool_input, state, root or user_state_root())
        bookkeeping = bookkeeping or _is_mail_search_spec_write(tool_name, tool_input, root or user_state_root())
        bookkeeping = bookkeeping or _is_office_read_spec_write(tool_name, tool_input, root or user_state_root())
        bookkeeping = bookkeeping or (not failed and _is_html_choices_spec_write(tool_name, tool_input, root or user_state_root()))
        bookkeeping = bookkeeping or _is_ppt_choices_spec_write(tool_name, tool_input, root or user_state_root())
        if tool_name.casefold().strip() in {"bash", "powershell"}:
            command = str(tool_input.get("command") or tool_input.get("cmd") or "")
            from .execution_contract import classify_command, internal_plan_command
            classification = classify_command(command, tool=tool_name)
            if classification == "read_only":
                mutated = False
            if internal_plan_command(command, root or user_state_root()):
                bookkeeping = True
            from .skill_workflow import internal_command
            if internal_command(command, session_id, state, root or user_state_root()):
                bookkeeping = True
            # Only exact current-session lifecycle commands are bookkeeping.
            if _is_own_work_command(command, session_id, state, root or user_state_root()):
                bookkeeping = True
        if bookkeeping:
            mutated = False
        elif collect_learning:
            state["taskToolCount"] = _safe_nonnegative_int(state.get("taskToolCount")) + 1
            if failed:
                state["taskFailureCount"] = _safe_nonnegative_int(state.get("taskFailureCount")) + 1
            if state.get("learningStatus") == "complete":
                state["learningStatus"] = "deferred"
                state["learningDeferredReason"] = "late-business-activity"
            if not failed:
                observed = _observed_personal_skill(tool_name, tool_input, root or user_state_root())
                if observed:
                    skills = [item for item in state.get("usedSkills", []) if isinstance(item, dict) and item.get("name") != observed["name"]]
                    state["usedSkills"] = (skills + [observed])[-MAX_OBSERVED_SKILLS:]
            work = state.get("work")
            if isinstance(work, dict):
                work["toolCount"] = min(1_000_000, work.get("toolCount", 0) + 1)
                work["failures"] = min(1_000_000, work.get("failures", 0) + int(failed))
                work["revision"] = work.get("revision", 0) + 1
                work["usedSkills"] = list({item["name"]: item for item in
                    work.get("usedSkills", []) + state.get("usedSkills", [])}.values())[-MAX_OBSERVED_SKILLS:]
                if state.get("protectionRestricted"):
                    work["pending"] = []
                    work["reviewRequested"] = False
        event = {"at": at, "tool": tool_name[:120], "success": not failed, "mutation": mutated}
        if tool_name in {"Agent", "Task"}:
            worker = tool_input.get("subagent_type")
            if worker in {"company-agent:small-worker", "company-agent:medium-worker", "company-agent:large-worker"}:
                alias = tool_input.get("model")
                executions = state.get("workerExecutions", [])
                state["workerExecutions"] = (executions + [{"agent": worker,
                    "requestedAlias": alias if alias in {"haiku", "sonnet", "opus"} else "agent-default",
                    "toolSucceeded": not failed, "actualModel": "unverified"}])[-8:]
        recent = list(state.get("recentTools", []))[-19:]
        recent.append(event)
        state["recentTools"] = recent
        state["lastActivityAt"] = at
        state["activityCount"] = _safe_nonnegative_int(state.get("activityCount")) + 1
        if mutated:
            if isinstance(state.get("work"), dict):
                state["work"]["closed"] = False
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
    if status not in {"pass", "fail", "not_applicable", "partial", "unavailable"}:
        raise ValueError("invalid verification status")
    compact_summary = summary.strip()[:500]

    with _locked_session(session_id, root) as (state, path):
        if status == "not_applicable" and state.get("mutationCount", 0):
            raise ValueError("not_applicable cannot clear recorded business changes")
        collect_learning = _collect_learning_observations(state, root or user_state_root())
        if state.get("protectionRestricted"):
            compact_summary = "보호 제한 항목을 제외한 범위의 검증 상태만 기록했습니다."
        state["verification"] = {
            "status": status,
            "at": _now(),
            "summary": compact_summary,
        }
        state["verificationRevision"] = _safe_nonnegative_int(state.get("verificationRevision")) + 1
        if status == "pass":
            state["stopRetryCount"] = 0
            state["sameFailureCount"] = 0
            state["lastFailureFingerprint"] = None
        elif status == "fail":
            if collect_learning:
                state["taskVerificationFailures"] = _safe_nonnegative_int(state.get("taskVerificationFailures")) + 1
                if isinstance(state.get("work"), dict):
                    state["work"]["verificationFailures"] = min(1_000_000, state["work"].get("verificationFailures", 0) + 1)
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


def _learning_stop(
    state: dict[str, Any], path: Path, session_id: str, root: Path,
    completion: dict[str, Any],
) -> dict[str, Any]:
    context = learning_context(state)
    # Stopping a response is not completing a business task. No empty review,
    # no continuation for lookups, choices or waiting. Verification is separate.
    work = state.get("work") or {}
    if work.get("status") != "complete" or not work.get("reviewRequested"):
        return completion
    if context and context["status"] == "deferred" and state.get("learningDeferredReason") == "late-business-activity":
        return completion
    if not context or context["status"] != "pending":
        return completion
    from .learning import learning_enabled

    if not learning_enabled(root):
        state["learningStatus"] = "disabled"
        atomic_write_json(path, state)
        return completion
    attempts = _safe_nonnegative_int(state.get("learningAttempts"))
    if attempts >= MAX_LEARNING_CONTINUATIONS:
        state["learningStatus"] = "deferred"
        state["learningDeferredReason"] = "attempts-exhausted"
        atomic_write_json(path, state)
        warning = (
            "Company Agent could not finish this turn's automatic learning after two attempts. "
            "The review is deferred; do not claim that memory or skills were improved. "
            "Report the task outcome and any remaining verification failure honestly."
        )
        return {"systemMessage": " ".join(filter(None, [completion.get("systemMessage"), warning]))}
    state["learningAttempts"] = attempts + 1
    atomic_write_json(path, state)
    turn_id = context["turnId"]
    spec_path = _learning_spec_path(root, turn_id)
    from .native_runtime import cli_command
    prefix = cli_command(Path(__file__).resolve().parents[2])
    reason = (
        "완료 표시된 업무의 새 피드백만 company-agent:self-learning Skill로 조용히 검토하십시오. "
        "사용자가 '기억해줘'라고 하지 않았어도 적용합니다. 대화 원문·비밀·일회성 업무값은 저장하지 마십시오. "
        "근거 없는 선호를 확정하거나 검사 실패를 성공으로 바꾸지 마십시오. 학습 accepted/관찰 없음 등 내부 상태를 최종 답변에 나열하지 마십시오. "
        f'현재 session은 "{safe_session_id(session_id)}", turn은 "{turn_id}"입니다. '
        f'Skill의 양식에 맞춘 검토 JSON을 "{spec_path}"에 Write로 저장한 뒤, 설치된 CLI로 '
        f'{prefix} learning review --session "{safe_session_id(session_id)}" --turn "{turn_id}" --spec "{spec_path}"를 실행하십시오. '
        "검토를 위해 업무 파일을 더 수정하거나 외부 전송을 다시 실행하지 마십시오. "
        f"학습 처리 기회는 최대 {MAX_LEARNING_CONTINUATIONS}회이며 실패하면 완료했다고 주장하지 마십시오."
    )
    if completion.get("systemMessage"):
        reason = str(completion["systemMessage"]) + " " + reason
    return {**completion, "decision": "block", "reason": reason}


def stop_decision(
    payload: dict[str, Any],
    root: Path | None = None,
    max_retries: int = MAX_CORRECTIVE_CONTINUATIONS,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("session_id"), str) or not payload["session_id"].strip() or payload["session_id"] == "unknown-session":
        return {}
    session_id = str(payload.get("session_id") or "unknown-session")
    # A caller may reduce the budget for tests or stricter deployments, but
    # never raise it above the fixed production ceiling of two continuations.
    retry_budget = min(
        MAX_CORRECTIVE_CONTINUATIONS,
        _safe_nonnegative_int(max_retries),
    )

    with _locked_session(session_id, root) as (state, path):
        if _stale_native_prompt(payload, state):
            return {}
        from .background_work import is_running
        if is_running(payload, state):
            # This Stop yields to a native background completion, not a failed
            # verification. Keep obligations, evidence and budgets untouched.
            return {}
        if state.get("approvalUnavailable"):
            return {"systemMessage": "승인되지 않아 실행하지 못한 항목과 이미 변경한 것 중 미검증 내용을 간단히 알리고 가능한 결과를 전달하세요. 같은 작업이나 학습 기록을 반복 요청하지 마세요."}
        if _safe_nonnegative_int(state.get("mutationCount")) == 0:
            return _learning_stop(state, path, session_id, root or user_state_root(), {})
        verification = state.get("verification")
        if (
            isinstance(verification, dict) and verification.get("status") in {"unavailable", "partial"}
        ):
            # End honestly, without a fake pass or a futile correction loop.
            # Keep the outstanding mutation obligation for a later user turn.
            return {"systemMessage": "완료한 결과와 확인하지 못한 부분만 간단히 안내하세요. 승인/검증 제한을 성공으로 기록하거나 같은 작업을 반복하지 마세요."}
        if (
            isinstance(verification, dict)
            and verification.get("status") == "pass"
        ):
            return _learning_stop(state, path, session_id, root or user_state_root(), {})
        if (
            isinstance(verification, dict)
            and verification.get("status") == "fail"
            and _safe_nonnegative_int(state.get("sameFailureCount"))
            >= MAX_CORRECTIVE_CONTINUATIONS
        ):
            return _learning_stop(state, path, session_id, root or user_state_root(), _failure_message("same-failure"))

        retry_count = _safe_nonnegative_int(state.get("stopRetryCount"))
        if retry_count >= retry_budget:
            return _learning_stop(state, path, session_id, root or user_state_root(), _failure_message("budget"))

        if (payload.get("stop_hook_active") is True and retry_count > 0
                and state.get("lastStopActivityCount") == state.get("activityCount", 0)
                and state.get("lastStopVerificationRevision") == state.get("verificationRevision", 0)):
            # Some Claude versions emit no activity hook for a permission
            # rejection. With no new tool evidence, repeating Stop cannot help.
            # Do not infer why it stopped, clear changes, or fabricate a pass.
            return {"systemMessage": "추가 실행 증거가 없어 반복 보정을 종료합니다. 완료한 결과와 남은 미검증 사항만 간단히 알리세요. 성공 기록을 만들거나 사용자에게 내부 기록 명령 실행을 떠넘기지 마세요."}

        # `stop_hook_active` means this is a corrective continuation. It must
        # not disable the second bounded attempt; the persisted counter is the
        # loop guard for both initial and active Stop events.
        state["stopRetryCount"] = retry_count + 1
        state["lastStopActivityCount"] = state.get("activityCount", 0)
        state["lastStopVerificationRevision"] = state.get("verificationRevision", 0)
        atomic_write_json(path, state)

    from .native_runtime import cli_command
    command_prefix = cli_command(Path(__file__).resolve().parents[2])
    reason = (
        "기록된 업무 변경에 대한 결과 확인이 남아 있습니다. 코드면 관련 테스트, 문서면 생성/구조 확인, 파일 이동이면 이동 기록/실제 경로를 확인하십시오. 단순 조회를 코드 검증 실패라고 보고하지 마십시오. 확인 후 다음 명령으로 기록하세요: "
        f'{command_prefix} session verify --session "{safe_session_id(session_id)}" --status pass --summary "검증 내용". '
        "검증에 실패하면 status fail로 기록하고 원인을 수정하십시오. "
        "필수 명령이 승인 대기/거절 또는 환경 제약으로 실행되지 못했다면 검증 실패와 구분해 status unavailable(일부만 확인했으면 partial)을 기록하고 그 작업만 대기하십시오. 승인 없는 대체 실행이나 같은 확인 반복을 하지 마십시오. "
        "이 기록은 내부 절차입니다. 성공·실패·대기 어느 경우에도 pass/fail/unavailable/partial 기록 등의 상태 보고를 출력하지 마십시오. 원래 요청의 산출물·업무 결과 또는 '실행 승인 대기'처럼 사용자가 해결할 사항만 일상 언어로 전달하십시오. "
        f"보정 기회는 최대 {MAX_CORRECTIVE_CONTINUATIONS}회이며, 이후에는 실패를 성공으로 표현하지 말고 남은 위험을 명확히 보고하십시오."
    )
    if isinstance(verification, dict) and verification.get("status") == "fail":
        reason += (
            " 실패한 worker를 resume하지 말고 새 worker에 목표·제약·현재 파일 경로·실패한 검사와 관찰 사실만 2,000자 이내로 전달하십시오. "
            "실패 대화 전체나 추측은 복사하지 마십시오. 기존 모델 등급을 낮추지 말고 현재 파일부터 재확인하십시오. "
            "이는 대화 rewind나 파일 rollback이 아닙니다. 메일 발송 등 외부 변경은 실행 여부를 조회하기 전 재실행하지 마십시오. "
            "새 worker도 남은 동일 재시도 예산을 공유합니다."
        )
    return {"decision": "block", "reason": reason}
