from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
import re
import shlex
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


def native_session_id(value):
    """Normalize a supplied native conversation ID; never invent a missing ID."""
    if not isinstance(value, str) or not value.strip():
        return ''
    normalized = safe_session_id(value)
    placeholders = {'unknown-session', 'company_agent_session_id', 'session_id',
                    'session', 'none', 'null', 'undefined'}
    return normalized if (re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', normalized)
                          and normalized.casefold() not in placeholders) else ''


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

# Shell accounting is a conservative observation, not a permission boundary or
# a parser for every shell dialect. Inline code has no .js/.py filename to match.
_INLINE_RUNTIMES = {"node", "nodejs", "bun", "deno", "ruby", "perl"}
_GIT_WRITES = {
    "add", "apply", "checkout", "clean", "commit", "mv", "push", "reset",
    "restore", "stash", "switch", "tag", "branch", "merge", "rebase",
    "cherry-pick", "revert", "rm", "fetch", "pull", "init", "clone",
}
_EXTRA_EXECUTION_PATTERN = re.compile(
    r'''(?:^|[;&|])\s*(?:&\s*)?["']?(?:[^\r\n"';&|]*[\\/])?'''
    r'''(?:node|nodejs|bun|deno|ruby|perl)(?:\.exe)?(?=["'\s]|$)'''
    r'''|\bgit(?:\.exe)?\s+(?:tag|branch|merge|rebase|cherry-pick|revert|rm|fetch|pull|init|clone)\b''',
    re.IGNORECASE,
)


def _git_reference_query(operation: str, arguments: list[str]) -> bool:
    """Recognize small literal tag/branch query forms; other forms may write."""
    if not arguments:
        return True
    listing = False
    flags = {"--no-color", "--color=never"}
    if operation == 'branch':
        flags |= {"-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose", "--show-current"}
    for value in arguments:
        if value in {'-l', '--list'}:
            listing = True
        elif value in flags or (operation == 'tag' and re.fullmatch(r'-n[0-9]*', value)):
            continue
        elif value.startswith('-') or not listing:
            return False
    return True


def _known_shell_mutation(command: str) -> bool | None:
    """Account for known inline runtimes and Git writes without executing them.

    Only an entire literal version/listing command gets a query exemption. A
    chain, redirection, expansion, or unrecognized form keeps conservative
    handling. This never returns an execution permission or validates results.
    """
    words = _literal_command_words(command)
    if not words:
        return True if _EXTRA_EXECUTION_PATTERN.search(command) else None
    name = words[0].replace('\\', '/').rsplit('/', 1)[-1].casefold()
    if name.endswith('.exe'):
        name = name[:-4]
    if name in _INLINE_RUNTIMES:
        return words[1:] not in (["--version"], ["-v"])
    probe_arguments = words[1:]
    if name == "py" and probe_arguments[:1] in (["-3"], ["-3.11"], ["-3.12"], ["-3.13"], ["-3.14"]):
        probe_arguments = probe_arguments[1:]
    while name in {"python", "python3", "py"} and probe_arguments:
        if probe_arguments[0] in {"-I", "-B", "-u", "-Xutf8"}:
            probe_arguments = probe_arguments[1:]
        elif probe_arguments[:2] == ["-X", "utf8"]:
            probe_arguments = probe_arguments[2:]
        else:
            break
    if (name in {"python", "python3", "py"} and probe_arguments in (["--version"], ["-V"])
            and _known_runtime(words[0], {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"})):
        # An exact runtime version probe does not modify a business result.
        # Extra arguments, scripts, redirections and shell expansions retain
        # conservative accounting; this is never an execution permission.
        return False
    if name != 'git':
        return None
    index = 1
    while index < len(words):
        value = words[index]
        if value in {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--config-env'}:
            index += 2
        elif value in {'--no-pager', '--paginate', '--literal-pathspecs', '--no-optional-locks'} or value.startswith(
                ('--git-dir=', '--work-tree=', '--namespace=', '--config-env=')):
            index += 1
        else:
            break
    if index >= len(words):
        return None
    operation = words[index]
    if operation in {'tag', 'branch'}:
        return not _git_reference_query(operation, words[index + 1:])
    return True if operation in _GIT_WRITES else None


def _read_only_shell_observation(command: str, tool_name: str) -> bool:
    """Completion accounting only; never an execution permission decision."""
    from .completion_readonly import is_read_only_observation
    return is_read_only_observation(command, tool_name)


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
        "verificationStopReason": None,
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
                      "sameFailureCount", "lastFailureFingerprint", "verificationStopReason")} if outstanding else {}
        state.update(
            {
                "turnId": uuid.uuid4().hex,
                "nativePromptSha256": native_digest,
                "previousTurnId": previous_turn if isinstance(previous_turn, str) and _TURN_ID_RE.fullmatch(previous_turn) else None,
                "learningStatus": "pending" if enabled else "disabled",
                "learningCompletedAt": None,
                "learningDeferredReason": None,
                "learningAttempts": 0,
                "learningProgressRevision": 0,
                "lastLearningProgressRevision": None,
                "usedSkills": [],
                "learningReadReceipts": {},
                "taskToolCount": 0,
                "approvalUnavailable": False,
                "pendingInput": None,
                "lastStopMutationCount": None,
                "lastStopVerificationRevision": None,
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
                "verificationStopReason": None,
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
        "policy": "evidence-triggered",
        "submission": "learning submit",
        "maxSubmissionsPerTurn": 1,
        "stopContinuation": False,
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
    # Only the accepted bare names or an exact absolute runtime path can match.
    # Ordinary commands (pwd, git, etc.) cannot pass _same_absolute_path, so do
    # not repeatedly walk PATH for every bookkeeping classification of them.
    if not Path(value).is_absolute():
        return False
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
        while arguments:
            if arguments[0] in {"-I", "-B", "-u", "-Xutf8"}:
                arguments.pop(0)
            elif arguments[:2] == ["-X", "utf8"]:
                arguments = arguments[2:]
            else:
                break
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
    submission = state.get("learningSubmission") or {}
    current_submission = isinstance(submission, dict) and submission.get("turnId") == turn_id
    if (not isinstance(turn_id, str) or not _TURN_ID_RE.fullmatch(turn_id)
            or (state.get("learningStatus") != "pending" and not current_submission)):
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


def _is_ppt_choices_spec_write(tool_name: str, tool_input: dict, root: Path) -> bool:
    """Only bounded temporary choice metadata, never jobs or output slides."""
    import json
    if tool_name.casefold() not in {'write', 'edit'}:
        return False
    value,content=tool_input.get('file_path'),tool_input.get('content')
    if not isinstance(value,str):
        return False
    path=Path(value)
    if (path.parent!=root.absolute()/'tmp' or not re.fullmatch(r'ppt-choices-[a-zA-Z0-9_-]{1,80}\.json',path.name)
            or not _safe_local_path(path,root,allow_missing_leaf=True)):
        return False
    try:
        if tool_name.casefold() == 'edit':
            # Called only after success: classify the entire resulting choice
            # file, never an arbitrary replacement fragment or failed edit.
            with path.open('rb') as stream:
                raw = stream.read(8193)
            if len(raw) > 8192:
                return False
            content = raw.decode('utf-8-sig')
        if not isinstance(content, str) or len(content.encode('utf-8')) > 8192:
            return False
        spec=json.loads(content)
        if not isinstance(spec,dict) or set(spec)-{'creationMode','referenceMode','purpose','audience','slideCount','designPreset','referenceImages'}:
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
                raw = stream.read(8193)
            if len(raw) > 8192:
                return False
            content = raw.decode('utf-8-sig')
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
    if len(arguments) != 8 or arguments[0] != "learning" or arguments[1] not in {"review", "stage", "submit"}:
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


def _personal_skill_identity(value: Any, root: Path) -> tuple[str, Path] | None:
    """Only directly owned personal Skill files can be automatic learning targets."""
    if not isinstance(value, str) or len(value) > 2_048:
        return None
    path = Path(value)
    try:
        relative = path.relative_to(root.absolute() / "personal-root" / ".claude" / "skills")
    except ValueError:
        return None
    if len(relative.parts) != 2 or relative.name != "SKILL.md":
        return None
    name = relative.parts[0]
    return (name, path) if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", name) else None


def _remember_personal_skill_load(state: dict[str, Any], item: dict, root: Path) -> None:
    """Record an already validated full load, not proof of applying the workflow.

    Called inside the existing state/Skill observation transaction. No source
    body, new file scan, model call or separate session write is needed.
    """
    identity = _personal_skill_identity(item.get("path"), root)
    digest = item.get("sha256")
    if (not identity or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or state.get("protectionRestricted") or not _collect_learning_observations(state, root)):
        return
    name, path = identity
    observed = {"name": name, "path": str(path), "sha256": digest}
    skills = [s for s in state.get("usedSkills", []) if isinstance(s, dict) and s.get("name") != name]
    state["usedSkills"] = (skills + [observed])[-MAX_OBSERVED_SKILLS:]
    work = state.get("work")
    if isinstance(work, dict):
        skills = [s for s in work.get("usedSkills", []) if isinstance(s, dict) and s.get("name") != name]
        work["usedSkills"] = (skills + [observed])[-MAX_OBSERVED_SKILLS:]


def _observed_personal_skill(tool_name: str, tool_input: dict[str, Any], root: Path,
                             response: Any, state: dict[str, Any]) -> dict[str, str] | None:
    if tool_name.casefold().strip() != "read":
        return None
    if (not isinstance(response, dict) or not isinstance(response.get("file"), dict)
            or not isinstance(response["file"].get("content"), str)):
        return None
    identity = _personal_skill_identity(tool_input.get("file_path"), root)
    if not identity:
        return None
    name, path = identity
    skills_root = root.absolute() / "personal-root" / ".claude" / "skills"
    try:
        if not _safe_local_path(path, skills_root) or path.stat().st_size > MAX_OBSERVED_SKILL_BYTES:
            return None
        with path.open("rb") as stream:
            data = stream.read(MAX_OBSERVED_SKILL_BYTES + 1)
        if len(data) > MAX_OBSERVED_SKILL_BYTES:
            return None
        # Use the same exact-response/range validator as workflow preparation.
        # Disk existence/hash alone is not evidence that the model saw a body.
        from .skill_workflow import _record_read
        receipts = state.get("learningReadReceipts")
        if not isinstance(receipts, dict):
            receipts = state["learningReadReceipts"] = {}
        if not _record_read(receipts, name, response, data):
            return None
        # Hash and ranges only. No body, response, other paths or search query.
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
        known = _known_shell_mutation(command)
        if known is not None:
            return known
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
            or payload.get("tool_name") not in {"Bash", "PowerShell", "Write", "Edit", "Read", "Glob", "Grep"}):
        return False
    error = payload.get("error")
    return (isinstance(error, str)
            and error.startswith("Permission for this tool use was denied.")
            and "The action was NOT performed" in error)


def _html_choice_wait(payload: dict[str, Any], root: Path) -> bool:
    """Observe an exact metadata helper's wait, never arbitrary assistant text.

    This only suspends the current turn's completion check. It does not verify
    older changes, authorize a tool, or reset a retry budget.
    """
    import json

    if (payload.get('hook_event_name') != 'PostToolUse' or payload.get('agent_id')
            or payload.get('tool_name') not in {'Bash', 'PowerShell'}):
        return False
    inputs = payload.get('tool_input')
    response = payload.get('tool_response')
    if not isinstance(inputs, dict) or not isinstance(response, dict):
        return False
    if response.get('interrupted') is True or any(
            key in response and (type(response[key]) is not int or response[key] != 0)
            for key in ('exitCode', 'exit_code')):
        return False
    from .execution_contract import _trusted_arguments, _fields, _same
    args = _trusted_arguments(inputs.get('command') or inputs.get('cmd') or '')
    if not args or args[:2] != ['business', 'html-choices']:
        return False
    fields = _fields(args[2:], {'--spec', '--state-root'})
    if fields is None or ('--state-root' in fields and not _same(fields['--state-root'], root)):
        return False
    stdout = response.get('stdout')
    if not isinstance(stdout, str) or len(stdout) > 32_768:
        return False
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate choice result field')
            result[key] = value
        return result
    try:
        result = json.loads(stdout, object_pairs_hook=unique_object)
    except (ValueError, RecursionError):
        return False
    return (isinstance(result, dict) and result.get('ok') is False
            and result.get('status') == 'input_required'
            and result.get('code') == 'report_choices_required'
            and result.get('stage') == 'design_detail' and result.get('missing') == ['style']
            and result.get('waitForUser') is True)


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
        learning_progress = False
        if tool_name.casefold().strip() in {"bash", "powershell"}:
            command = str(tool_input.get("command") or tool_input.get("cmd") or "")
            learning_command = _is_own_learning_command(command, session_id, state, root or user_state_root())
            if learning_command and not not_performed:
                arguments = _own_cli_arguments(command) or []
                learning_progress = arguments[:2] in (["learning", "review"], ["learning", "stage"], ["learning", "submit"])
            bookkeeping = bookkeeping or (
                _is_own_verification_command(command, session_id, root or user_state_root())
                or _is_own_context_audit(command)
                or learning_command
            )
        learning_spec = _is_learning_spec_write(tool_name, tool_input, state, root or user_state_root())
        learning_progress = learning_progress or (learning_spec and not failed and not not_performed)
        bookkeeping = bookkeeping or learning_spec
        bookkeeping = bookkeeping or _is_mail_search_spec_write(tool_name, tool_input, root or user_state_root())
        bookkeeping = bookkeeping or (not failed and _is_html_choices_spec_write(tool_name, tool_input, root or user_state_root()))
        bookkeeping = bookkeeping or (not failed and _is_ppt_choices_spec_write(tool_name, tool_input, root or user_state_root()))
        # The memory writer checks its exact persisted item. Observe that
        # receipt locally; never mark unrelated business mutations verified.
        from .memory_activity import spec_write as memory_spec_write, checked_change as checked_memory_change
        memory_receipt = None
        if not failed and not not_performed:
            bookkeeping = bookkeeping or memory_spec_write(tool_name, tool_input, root or user_state_root())
            memory_receipt = checked_memory_change(payload, root or user_state_root())
            if memory_receipt is not None:
                bookkeeping = True
                state['lastVerifiedMemory'] = memory_receipt
        if tool_name.casefold().strip() in {"bash", "powershell"}:
            command = str(tool_input.get("command") or tool_input.get("cmd") or "")
            from .execution_contract import classify_command, internal_plan_command
            classification = classify_command(command, tool=tool_name)
            if classification == "read_only" or _read_only_shell_observation(command, tool_name):
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
            submitted = state.get("learningSubmission") or {}
            if (state.get("learningStatus") == "complete"
                    and (not isinstance(submitted, dict) or submitted.get("turnId") != state.get("turnId"))):
                # Legacy milestone reviews describe an outcome snapshot. A new
                # submit captures a lesson, not work completion: subsequent work
                # cannot undo that receipt or grant another submission budget.
                state["learningStatus"] = "deferred"
                state["learningDeferredReason"] = "late-business-activity"
            if not failed and not payload.get("agent_id"):
                observed = _observed_personal_skill(tool_name, tool_input, root or user_state_root(), response, state)
                if observed:
                    _remember_personal_skill_load(state, observed, root or user_state_root())
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
        if learning_progress:
            state["learningProgressRevision"] = _safe_nonnegative_int(state.get("learningProgressRevision")) + 1
        # A later tool event clears the earlier wait unless it reports the same
        # exact waiting helper again. Merely reading files is not a fresh wait.
        state['pendingInput'] = None
        if not failed and not not_performed and not mutated and _html_choice_wait(payload, root or user_state_root()):
            state['pendingInput'] = {'kind': 'html-report-style', 'turn': state.get('turnId'),
                'mutationCount': _safe_nonnegative_int(state.get('mutationCount')),
                'verificationRevision': _safe_nonnegative_int(state.get('verificationRevision'))}
        event = {"at": at, "tool": tool_name[:120], "success": not failed, "mutation": mutated}
        if memory_receipt is not None:
            event['checkedChange'] = 'memory-item'
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
            state["verificationStopReason"] = None
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
            "turnId": state.get("turnId"),
            "workId": (state.get("work") or {}).get("id"),
            "summary": compact_summary,
        }
        state["verificationRevision"] = _safe_nonnegative_int(state.get("verificationRevision")) + 1
        state["verificationStopReason"] = None
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
    # Stop is not a semantic learning trigger. Never prolong an otherwise
    # finished answer to elicit candidates, even for a legacy review checkpoint.
    # Keep pending candidates and business verification untouched. A real later
    # correction/check can submit once with current context; Stop cannot infer it.
    return completion


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
        pending = state.get('pendingInput')
        if (isinstance(pending, dict) and pending.get('kind') == 'html-report-style'
                and state.get('turnId') and pending.get('turn') == state.get('turnId')
                and pending.get('mutationCount') == _safe_nonnegative_int(state.get('mutationCount'))
                and pending.get('verificationRevision') == _safe_nonnegative_int(state.get('verificationRevision'))):
            # The user must choose before more work is possible. Preserve all
            # previous completion obligations and the two-correction ceiling.
            return {}
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
            return _failure_message("same-failure")

        retry_count = _safe_nonnegative_int(state.get("stopRetryCount"))
        if retry_count >= retry_budget:
            return _failure_message("budget")

        if (retry_count > 0
                and state.get("lastStopMutationCount") == _safe_nonnegative_int(state.get("mutationCount"))
                and state.get("lastStopVerificationRevision") == _safe_nonnegative_int(state.get("verificationRevision"))):
            # Reading settings or listing hooks is activity, not progress on
            # the actual business result. Some hosts also omit stop_hook_active.
            # Preserve obligations; never call learning or fabricate a pass.
            if state.get("verificationStopReason") != "no-progress":
                state["verificationStopReason"] = "no-progress"
                atomic_write_json(path, state)
            return {"systemMessage": "추가 실행 증거가 없어 반복 보정을 종료합니다. 완료한 결과와 남은 미검증 사항만 간단히 알리세요. 성공 기록을 만들거나 사용자에게 내부 기록 명령 실행을 떠넘기지 마세요."}

        # `stop_hook_active` means this is a corrective continuation. It must
        # not disable the second bounded attempt; the persisted counter is the
        # loop guard for both initial and active Stop events.
        state["stopRetryCount"] = retry_count + 1
        state["lastStopMutationCount"] = _safe_nonnegative_int(state.get("mutationCount"))
        state["lastStopVerificationRevision"] = _safe_nonnegative_int(state.get("verificationRevision"))
        atomic_write_json(path, state)

    from .native_runtime import cli_command
    command_prefix = cli_command(Path(__file__).resolve().parents[2])
    failed_check = isinstance(verification, dict) and verification.get("status") == "fail"
    reason = (
        ("실제 결과 검사 실패가 기록되어 있습니다. 실패한 검사와 수정 범위만 재확인하세요. " if failed_check else
         "업무 변경의 검증 기록이 아직 없습니다. 이것만으로 결과물 오류를 뜻하지 않습니다. 이미 수행한 검사 근거는 재사용하세요. ")
        + "필요한 검사만 수행하세요: 코드=관련 테스트, 문서=생성·구조, 파일 이동=실제 경로·이동 기록. "
        "아래 명령은 최신 변경 뒤 실제 검사에 성공했을 때만 1회 실행하세요. 실패했다면 --status fail, 일부만 확인했으면 --status partial, 승인·환경 제한이면 --status unavailable로 바꾸세요. "
        "검사하지 않은 결과를 pass로 기록하지 마세요.\n"
        f'{command_prefix} session verify --state-root {shlex.quote(str((root or user_state_root()).absolute()))} '
        f'--session "{safe_session_id(session_id)}" --status pass --summary "실제 확인 내용 또는 제한"\n'
        "설정·후크·환경변수·세션을 재탐색하지 마세요. 기록 명령도 실행할 수 없으면 내부 기록만 보류하고 확인된 결과와 한계를 전달하세요. "
        "원래 업무·외부 전송을 재실행하거나 승인 거절을 우회하지 마세요. 내부 기록을 사용자에게 떠넘기거나 최종 답변에 중계하지 마세요."
    )
    return {"decision": "block", "reason": reason}
