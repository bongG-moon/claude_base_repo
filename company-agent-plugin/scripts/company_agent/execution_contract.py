"""Small, literal command contracts; classification is NOT authorization.

Unknown syntax retains the caller's conservative mutation/permission handling.
Only ``safe_permission`` may answer a native PermissionRequest, and it supports
two metadata operations through this exact running Python, not general shells.
Never call it from PreToolUse: explicit native/managed deny rules must prevail.
"""
from __future__ import annotations

import os
import json
from pathlib import Path
import re
import shutil
import shlex
import sys
from typing import Any


def _words(command: str, *, office_paths: bool = False) -> list[str] | None:
    from .state import _literal_command_words

    if not isinstance(command, str) or len(command) > 16_384:
        return None
    value = command.strip()
    if value.startswith("& "):
        value = value[2:].lstrip()
    # Disallow cmd expansion/escaping and shell syntax even within quotes. It
    # may become executable when passed through a Windows .cmd wrapper.
    forbidden = "\r\n\0$`%!^;|<>&{}*?" + ('' if office_paths else '()[]')
    if any(char in value for char in forbidden):
        return None
    # The literal lexer still rejects UNQUOTED parentheses/brackets. This
    # opt-in is only used for the owned Office reader, never auto-permission.
    return _literal_command_words(value)


def _same(value: str, path: Path) -> bool:
    try:
        candidate = Path(value)
        return candidate.is_absolute() and ".." not in candidate.parts and candidate.resolve() == path.resolve()
    except (OSError, ValueError):
        return False


def _absolute(value: str) -> bool:
    try:
        path = Path(value)
        return path.is_absolute() and ".." not in path.parts and len(value) < 2_049
    except (OSError, ValueError):
        return False


def _powershell() -> Path | None:
    if os.name != "nt":
        return None
    # Do not trust a same-named program from PATH or an environment override.
    import ctypes

    buffer = ctypes.create_unicode_buffer(32_768)
    size = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not size or size >= len(buffer):
        return None
    return Path(buffer.value) / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def _office_command_parts(command: str) -> tuple[str, str]:
    """Separate only a terminal stderr merge; the caller must validate the body.

    The literal lexer rejects an unclosed quote, another redirect, a chain or
    a pipe in the remaining body. This is NOT a general shell normalizer and
    is used only for the owned Office command, never automatic permission.
    """
    match = re.search(r'\s+2>&1\s*$', command)
    return (command[:match.start()], command[match.start():]) if match else (command, '')


def _trusted_arguments(command: str, *, office_paths: bool = False) -> list[str] | None:
    from .state import _own_cli_arguments

    if not isinstance(command, str) or len(command) > 16_384:
        return None
    if office_paths:
        command, _ = _office_command_parts(command)
    words = _words(command, office_paths=office_paths)
    if not words:
        return None
    program = words[0]
    scripts = Path(__file__).resolve().parents[1]
    wrapper = scripts.parent / "bin" / "company-agent.cmd"
    if program.casefold() == "company-agent":
        resolved = shutil.which("company-agent")
        if not resolved or not _same(resolved, wrapper):
            return None
    elif _same(program, wrapper) or _same(program, Path(sys.executable)):
        pass
    else:
        powershell = _powershell()
        # A short name is common in Git Bash-generated commands. Resolve it
        # before classification; a same-named PATH shim is not this runtime.
        resolved = shutil.which(program) if program.casefold() == "powershell.exe" else None
        if powershell is None or not (_same(program, powershell) or
                                      (resolved and _same(resolved, powershell))):
            return None
    args = _own_cli_arguments(command)
    return None if office_paths and (not args or args[:2] != ['business', 'office-read']) else args


def office_file_name(value: str) -> bool:
    """An exact filename in the caller's cwd, never a search or path repair."""
    return (isinstance(value, str) and 0 < len(value) < 2049 and value not in {'.', '..'}
            and value[-1] not in ' .' and not any(c in value for c in '\\/:\0\r\n'))


def _fields(arguments: list[str], allowed: set[str], required: set[str] | None = None, *,
            template_suffixes: tuple[str, ...] = ('.pptx',), allow_file_name: bool = False) -> dict[str, str] | None:
    if len(arguments) % 2:
        return None
    fields: dict[str, str] = {}
    for index in range(0, len(arguments), 2):
        key, value = arguments[index:index + 2]
        if key not in allowed or key in fields or not value or value.startswith("-"):
            return None
        fields[key] = value
    if not (required or set()).issubset(fields):
        return None
    for name in ("--state-root", "--spec", "--project", "--project-root", "--base", "--index", "--file", "--template"):
        if name in fields and not _absolute(fields[name]):
            if name == '--file' and allow_file_name and office_file_name(fields[name]):
                continue
            return None
    if "--spec" in fields and Path(fields["--spec"]).suffix.casefold() != ".json":
        return None
    if '--template' in fields and Path(fields['--template']).suffix.casefold() not in template_suffixes:
        return None
    if "--session" in fields and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", fields["--session"]):
        return None
    return fields


def _literal_listing(command: str) -> bool:
    words = _words(command)
    expected = _powershell()
    if not words or expected is None or not _same(words[0], expected):
        return False
    args = words[1:]
    # Require NoProfile; only one non-recursive literal directory-list command.
    if not args or args.pop(0).casefold() != "-noprofile":
        return False
    while args and args[0].casefold() in {"-noninteractive", "-nologo"}:
        args.pop(0)
    if len(args) != 2 or args[0].casefold() != "-command":
        return False
    inner = _words(args[1])
    if not inner or len(inner) < 3 or inner[0].casefold() != "get-childitem" or inner[1].casefold() != "-literalpath":
        return False
    if not _absolute(inner[2]):
        return False
    flags = [flag.casefold() for flag in inner[3:]]
    if len(flags) != len(set(flags)) or not set(flags).issubset({"-name", "-directory", "-file", "-force"}):
        return False
    try:
        return Path(inner[2]).is_dir()  # file listing must not become a content reader
    except OSError:
        return False


def _skill_lookup(arguments: list[str]) -> bool:
    """Literal read-only Skill grammar, including scoped discovery/preview.

    Do not accept preference writes or shell syntax; this classifies activity,
    never grants native permission. Mirror the public CLI's discovery options.
    """
    operation, *rest = arguments
    if operation not in {"list", "inventory", "conflicts", "search", "resolve"}:
        return False
    paths = {"--state-root", "--base", "--project-root", "--claude-root",
             "--plugin-root", "--incoming-plugin", "--incoming-skill"}
    seen: set[str] = set()
    positionals: list[str] = []
    index = 0
    while index < len(rest):
        word = rest[index]
        if not word.startswith("-"):
            positionals.append(word)
            index += 1
            continue
        if word in seen:
            return False
        seen.add(word)
        if word == "--no-project":
            index += 1
            continue
        if word not in paths and not (word == "--limit" and operation == "search"):
            return False
        if index + 1 >= len(rest):
            return False
        value = rest[index + 1]
        if word in paths and not _absolute(value):
            return False
        if word == "--limit" and (not re.fullmatch(r"[1-9][0-9]?", value) or int(value) > 50):
            return False
        index += 2
    if {"--project-root", "--no-project"}.issubset(seen):
        return False
    return len(positionals) == (1 if operation in {"search", "resolve"} else 0)


def discovery_command(command: str, *, tool: str = 'Bash') -> bool:
    """Literal listings only; neither a permission grant nor proof of a load.

    Reject substitutions, content readers, output files and mixed executable
    chains. No filesystem scans/subprocesses. Reused by preparation and result
    accounting so stderr-to-null does not cause a false mutation/Stop failure.
    """
    if not command or len(command) > 4096 or any(c in command for c in '\r\n\0$`(){}'):
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|<>')
        lexer.whitespace_split = True
        lexer.commenters = ''
        words = list(lexer)
    except ValueError:
        return False
    segments: list[list[str]] = [[]]
    index = 0
    while index < len(words):
        word = words[index]
        if word in {';', '&&', '||'}:
            if not segments[-1]:
                return False
            segments.append([])
        elif words[index:index + 3] == ['2', '>', '/dev/null'] and tool.casefold() == 'bash':
            index += 2  # In PowerShell this could be a real output file.
        elif re.fullmatch(r'[;&|<>]+', word):
            return False
        else:
            segments[-1].append(word)
        index += 1
    for args in segments:
        if not args:
            return False
        name, flags = args[0].casefold(), args[1:]
        if name in {'pwd', 'get-location'}:
            if flags:
                return False
        elif name == 'ls':
            if any(x.startswith('-') and not re.fullmatch(r'-[laAdhF]+|--', x) for x in flags):
                return False
        elif name == 'get-childitem':
            if any(x.startswith('-') and x.casefold() not in {'-literalpath', '-path', '-name', '-file', '-directory', '-force'} for x in flags):
                return False
        elif args not in (['git', 'status'], ['git', 'status', '--short']):
            return False
    return True


def classify_command(command: str, *, tool: str = 'Bash') -> str:
    """Return read_only/internal/mutation/unknown for exact known invocations.

    Internal review/verification requires the existing current-session/path
    guards in state.py. Those calls deliberately remain unknown here: syntax
    alone cannot grant a bookkeeping exemption for arbitrary personal writes.
    ``mail-read`` also remains unknown because body-access permission matters.
    """
    if discovery_command(command, tool=tool) or _literal_listing(command):
        return "read_only"
    args = _trusted_arguments(command) or _trusted_arguments(command, office_paths=True)
    if not args:
        return "unknown"
    head = tuple(args[:2])
    if head == ("handoff", "read"):
        fields = _fields(args[2:], {"--id", "--project", "--state-root"}, {"--id", "--project"})
        return "read_only" if fields is not None and re.fullmatch(r"[a-f0-9]{32}", fields["--id"]) else "unknown"
    if len(args) >= 2 and args[0] == "skill":
        return "read_only" if _skill_lookup(args[1:]) else "unknown"
    if head == ("asset", "check-skill"):
        fields = _fields(args[2:], {"--name", "--state-root", "--project-root"}, {"--name"})
        return "read_only" if fields is not None and re.fullmatch(r"[a-z][a-z0-9-]{1,62}", fields["--name"]) else "unknown"
    # Exact help calls must be handled before missing-storage-scope questions.
    # Neither form performs a save or creates a completion obligation.
    if args[-1:] == ["--help"] and head in {
        ("memory", "search"), ("memory", "upsert"), ("session", "verify"),
        ("work", "checkpoint"), ("learning", "stage"), ("learning", "review"),
        ("business", "eml-read"), ("business", "files-plan"),
    } and len(args) == 3:
        return "read_only"
    if head in {('memory', 'upsert'), ('knowledge', 'upsert'), ('asset', 'create')} and '--storage-scope' not in args:
        # These commands now return needs_scope_choice before opening the spec
        # or creating state. A question must not create a false Stop obligation.
        fields = _fields(args[2:], {'--spec', '--state-root', '--project-root', '--base'}, {'--spec'})
        return 'read_only' if fields is not None else 'unknown'
    if head in {("memory", "search"), ("knowledge", "search")} and len(args) >= 3 and not args[2].startswith("-"):
        allowed = {"--limit", "--state-root", "--storage-scope", "--project-root"}
        if head[0] == 'knowledge':
            allowed.add('--index')
        fields = _fields(args[3:], allowed)
        if (fields is not None and fields.get('--storage-scope', 'personal') in {'personal', 'project'}
                and ("--limit" not in fields or re.fullmatch(r"[1-9][0-9]{0,2}", fields["--limit"]))):
            return "read_only"
        return "unknown"
    allowed: set[str]
    required: set[str] = set()
    if head == ('business', 'html-designs') and '--open' in args:
        if args.count('--open') != 1:
            return 'unknown'
        # Viewing the fixed shipped picker is not a business artifact change.
        # This classification does not grant native execution permission.
        args = [value for value in args if value != '--open']
    if head in {("business", "doctor"), ("business", "runtime-check"), ("business", "mail-capabilities"), ("business", "ppt-capabilities"), ("business", "html-designs")}:
        allowed = {"--state-root"}
    elif head == ('business','office-read'):
        allowed = {'--state-root','--spec'} if '--spec' in args else {'--state-root','--file','--start','--end','--sheet','--range','--max-chars','--expected-count'}
        allowed.add('--session')
        required = {'--spec'} if '--spec' in args else {'--file'}
    elif head in {("business", "mail-search"), ("business", "html-choices")}:
        allowed, required = {"--state-root", "--spec"}, {"--spec"}
    elif head == ('business','ppt-choices'):
        allowed, required = {'--state-root','--spec','--template'}, {'--spec'}
    elif head in {('business','ppt-analyze'),('business','ppt-inspect'),('business','html-template')}:
        allowed, required = {'--state-root','--template'}, {'--template'}
    elif head == ("business", "eml-read"):
        allowed, required = {"--state-root", "--file"}, {"--file"}
    elif head == ("session", "status"):
        allowed, required = {"--state-root", "--session"}, {"--session"}
    elif head == ("learning", "status"):
        allowed = {"--state-root", "--session"}
    elif head == ("context", "audit"):
        allowed = {"--project"}
    elif head == ("context", "map"):
        # Metadata-only form. --output creates a real artifact and deliberately
        # remains unknown/mutating; this classification grants no permission.
        allowed = {"--project", "--session"}
    else:
        return "unknown"
    suffixes = ('.html', '.htm') if head == ('business', 'html-template') else ('.pptx', '.html', '.htm') if head in {('business','ppt-choices'),('business','ppt-analyze')} else ('.pptx',)
    return "read_only" if _fields(args[2:], allowed, required, template_suffixes=suffixes,
                                 allow_file_name=head == ('business', 'office-read')) is not None else "unknown"


def internal_plan_command(command: str, root: Path) -> bool:
    """A known plan writes only its internal receipt, never moves source files.

    This is a bookkeeping classification, NOT an approval or a blanket tmp-write
    exemption. Explicit alternate state roots remain business changes.
    """
    args = _trusted_arguments(command)
    if not args or args[:2] not in (["business", "files-plan"], ["business", "artifact-start"]):
        return False
    key = '--output' if args[1] == 'artifact-start' else '--folder'
    fields = _fields(args[2:], {key, "--state-root"}, {key})
    return bool(fields is not None and _absolute(fields[key])
                and (key != '--output' or Path(fields[key]).suffix.lower() in {'.pptx','.html'})
                and ("--state-root" not in fields or _same(fields["--state-root"], root)))


def safe_permission(payload: dict[str, Any], root: Path) -> dict[str, str] | None:
    """Native pending-prompt decision for exact local metadata commands only.

    No arbitrary spec, body access, state override, general file read or writes.
    Wrappers are excluded: their selected Python may differ from this process.
    This is not an OS sandbox and assumes the installed core/runtime is trusted.
    """
    if payload.get("hook_event_name") != "PermissionRequest" or payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict) or set(tool_input) - {"command", "description", "timeout", "run_in_background"}:
        return None
    if tool_input.get("run_in_background") is True:
        return None
    command = tool_input.get("command")
    words = _words(command)
    if not words or not _same(words[0], Path(sys.executable)):
        return None
    args = _trusted_arguments(command)
    if not args or tuple(args[:2]) not in {("business", "doctor"), ("business", "mail-capabilities")}:
        return None
    fields = _fields(args[2:], {"--state-root"})
    if fields is None or ("--state-root" in fields and not _same(fields["--state-root"], root)):
        return None
    return {"behavior": "allow"}


def runtime_probe_context(payload: dict[str, Any], root: Path) -> str:
    """Correct a metadata/env confusion after a probe; never change its result.

    Pure current-hook metadata only: no env lookup, state scan, command execution,
    permission grant, or fabricated replacement for the tool's actual output.
    """
    if payload.get('hook_event_name') not in {'PostToolUse', 'PostToolUseFailure'} or payload.get('tool_name') not in {'Bash', 'PowerShell'}:
        return ''
    inputs = payload.get('tool_input')
    command = (inputs.get('command') or inputs.get('cmd')) if isinstance(inputs, dict) else None
    if not isinstance(command, str) or len(command) > 16_384:
        return ''
    name = r'(?:company_agent_session_id|stateRoot|cliCommand)'
    if not re.search(r'%' + name + r'%|\$(?:env:)?' + name + r'\b|\benv:' + name +
                     r'\b|\bcompany_agent_runtime\.(?:officeReadCommand|cliCommand|stateRoot)\b', command, re.I):
        return ''
    from .office_consent import native_session_id
    session = native_session_id(payload.get('session_id'))
    values = {'company_agent_session_id': session, 'stateRoot': str(root)} if session else {}
    if session:
        from .native_runtime import cli_command
        cli = cli_command(Path(__file__).resolve().parents[2])
        if re.search(r'\bcompany_agent_runtime\.officeReadCommand\b', command, re.I):
            ready = office_read_command(cli, root, session)
            if ready:
                values['officeReadCommand'] = ready
        else:
            values['cliCommand'] = cli  # Other tasks do not acquire an Office workflow.
    return ('company_agent_runtime.*는 실행할 명령어가 아니라 후크 JSON의 항목 이름입니다. '
            '환경변수 NOT SET으로 문서 권한·DRM·읽기 불가를 판정하지 마세요. '
            '현재 후크 정보: ' + json.dumps(values, ensure_ascii=False, separators=(',', ':')) +
            '. 전달된 officeReadCommand/cliCommand와 선택한 스킬로 계속하며 환경변수 탐색·대체 파서는 사용하지 마세요. '
            '정보가 비어 있으면 실제 연결 누락만 알리세요. 이 안내는 승인·권한을 부여하지 않으며 실제 거절은 유지합니다.')


def office_read_command(cli: str, root: Path, session: str) -> str:
    """Ready prefix from native context, not environment discovery or consent."""
    from .office_consent import _session
    if not _session(session):
        return ''
    command = cli + ' business office-read --session "' + session + '" --state-root "' + root.resolve().as_posix() + '"'
    expected = ['business', 'office-read', '--session', session, '--state-root', root.resolve().as_posix()]
    # No probing processes, shell expansion, model-provided source or state scan.
    return command if _trusted_arguments(command, office_paths=True) == expected else ''


def office_load_context(plugin: Path, root: Path, payload: dict[str, Any], loaded: dict | None) -> str:
    """One copy-ready command after an observed company reader load.

    No discovery, body re-read, model call or consent. A similarly named
    personal skill must retain its own execution contract.
    """
    if (payload.get('hook_event_name') != 'PostToolUse' or not isinstance(loaded, dict)
            or loaded.get('source') != 'company' or loaded.get('name') != 'office-reader'
            or not _same(str(loaded.get('path', '')), plugin / 'skills/office-reader/SKILL.md')):
        return ''
    from .office_consent import native_session_id
    from .native_runtime import cli_command
    command = office_read_command(cli_command(plugin), root, native_session_id(payload.get('session_id')))
    if not command:
        return ''
    return ('Office 읽기: 아래 officeReadCommand의 실제 문자열 뒤에 --file "현재 폴더의 정확한 파일명 또는 확인한 절대경로"와 요청한 범위만 붙이세요. '
            '항목 이름을 실행하거나 세션·설치 경로를 다시 찾지 마세요. 반환된 승인 질문은 그대로 받습니다.\n' +
            json.dumps({'officeReadCommand': command}, ensure_ascii=False, separators=(',', ':')))


def bind_office_context(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    """Fill omitted context on one literal installed Office reader invocation.

    Only the current native hook supplies identity; never inspect other session
    files, infer a latest session, grant permission, or answer a consent question.
    Explicit context (including a delegated parent's session) is not rewritten.
    All original tool fields and source/range arguments survive unchanged.
    """
    if payload.get('hook_event_name') != 'PreToolUse' or payload.get('tool_name') not in {'Bash', 'PowerShell'}:
        return {}
    inputs = payload.get('tool_input')
    if not isinstance(inputs, dict) or inputs.get('run_in_background'):
        return {}
    key = 'command' if 'command' in inputs else 'cmd'
    command = inputs.get(key)
    if not isinstance(command, str):
        return {}
    args = _trusted_arguments(command, office_paths=True)
    if not args or args[:2] != ['business', 'office-read'] or classify_command(command) != 'read_only':
        return {}
    fields = dict(zip(args[2::2], args[3::2]))  # Already validated by classify_command.
    from .office_consent import native_session_id
    session = native_session_id(payload.get('session_id'))
    if not session:
        return {}
    if '--session' in fields and fields['--session'] != session:
        return {}  # A worker may carry its parent's approved scope.
    if '--state-root' in fields and not _same(fields['--state-root'], root):
        return {}  # Never silently redirect an explicit state scope.
    additions = []
    if '--session' not in fields:
        additions.extend(['--session', session])
    if '--state-root' not in fields:
        additions.extend(['--state-root', root.resolve().as_posix()])
    if not additions:
        return {}
    # Literal double-quoted values work in both PowerShell and Git Bash. Reject
    # shell metacharacters via the same strict grammar after construction.
    suffix = ''.join(' ' + flag + ' "' + value + '"' for flag, value in zip(additions[::2], additions[1::2]))
    body, redirect = _office_command_parts(command)
    updated = body.rstrip() + suffix + redirect
    if _trusted_arguments(updated, office_paths=True) != args + additions:
        return {}
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                                  'updatedInput': {**inputs, key: updated}}}
