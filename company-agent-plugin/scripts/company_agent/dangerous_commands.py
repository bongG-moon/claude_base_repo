"""Deny a small set of literal destructive shell commands before execution.

Pure and bounded: no files, subprocesses, model calls or permission grants.
This is an accident guard, not a shell parser or sandbox. Dynamic expansion,
scripts, aliases/functions and encoded/obfuscated commands remain subject to
Claude's existing permissions and the operating system's controls.
"""
from __future__ import annotations

import re

MAX_COMMAND_CHARS = 16_384
MAX_TOKENS = 2_048
MAX_WRAPPER_DEPTH = 2
_REASON = '안전 보호: 되돌리기 어려운 삭제·강제 변경 명령은 실행하지 않았습니다. 필요한 경우 명령과 대상을 직접 검토한 뒤 수동으로 실행해 주세요.'


def _segments(command: str) -> list[list[str]]:
    """Read literal words and statement boundaries, keeping quoted data whole.

    Do not inspect text inside an ordinary argument as another command. Only
    known interpreter -c/-Command payloads are re-tokenized below. Unclosed
    quotes and token overflow are unknown, not a claim that execution is safe.
    """
    segments: list[list[str]] = [[]]
    token: list[str] = []
    quote = ''
    count = 0
    index = 0

    def word():
        nonlocal count
        if token:
            segments[-1].append(''.join(token))
            token.clear()
            count += 1

    while index < len(command):
        char = command[index]
        if quote:
            if char == quote:
                # PowerShell's doubled single quote is one literal apostrophe.
                if quote == "'" and index + 1 < len(command) and command[index + 1] == "'":
                    token.append("'")
                    index += 1
                else:
                    quote = ''
            elif char == '\\' and quote == '"' and index + 1 < len(command) and command[index + 1] == '"':
                token.append('"')
                index += 1
            else:
                token.append(char)
        elif char in "\"'":
            quote = char
        elif char == '#' and not token:
            # A comment is not a command (nor a reference example to block).
            word()
            end = command.find('\n', index)
            if end == -1:
                break
            segments.append([])
            index = end
        elif char in ';&|\r\n':
            word()
            if segments[-1]:
                segments.append([])
        elif char.isspace():
            word()
        else:
            token.append(char)
        if count > MAX_TOKENS:
            return []
        index += 1
    if quote:
        return []
    word()
    return [part for part in segments if part] if count <= MAX_TOKENS else []


def _program(word: str) -> str:
    name = re.split(r'[/\\]', word)[-1].casefold()
    return name[:-4] if name.endswith(('.exe', '.cmd')) else name


def _git(args: list[str]) -> bool:
    # Skip only known global options, never guess whether an unknown option
    # consumes the next word. Values such as -c alias.note='reset --hard' are data.
    values = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--config-env'}
    flags = {'--no-pager', '--paginate', '-p', '--bare', '--no-optional-locks', '--literal-pathspecs',
             '--no-literal-pathspecs', '--glob-pathspecs', '--noglob-pathspecs', '--icase-pathspecs'}
    index = 0
    while index < len(args) and args[index].startswith('-'):
        word = args[index]
        if word in values:
            index += 2
        elif word in flags or any(word.startswith(flag + '=') for flag in values if flag.startswith('--')):
            index += 1
        elif word.startswith(('-C', '-c')) and len(word) > 2:
            index += 1
        else:
            return False
    if index >= len(args):
        return False
    operation, rest = args[index], args[index + 1:]
    options = rest[:rest.index('--')] if '--' in rest else rest
    if operation == 'reset':
        return '--hard' in options
    if operation == 'clean':
        flags_only = []
        index = 0
        while index < len(options):
            if options[index] in {'-e', '--exclude'}:
                index += 2
                continue
            flags_only.append(options[index])
            index += 1
        short = ''.join(w[1:] for w in flags_only if re.fullmatch(r'-[fdxXienq]+', w))
        return ('--force' in flags_only or 'f' in short) and not ('--dry-run' in flags_only or 'n' in short)
    if operation != 'push':
        return False
    positionals = []
    forced = dry_run = False
    remote_option = False
    index = 0
    while index < len(rest):
        word = rest[index]
        if word == '--':
            positionals.extend(rest[index + 1:])
            break
        if word in {'-o', '--push-option', '--repo', '--receive-pack', '--exec'}:
            remote_option = remote_option or word == '--repo'
            index += 2
            continue
        if word.startswith('--repo='):
            remote_option = True
        if word in {'--force', '--force-with-lease', '--mirror'} or word.startswith('--force-with-lease='):
            forced = True
        if word == '--dry-run':
            dry_run = True
        if re.fullmatch(r'-[fuvqn]+', word):
            forced = forced or 'f' in word[1:]
            dry_run = dry_run or 'n' in word[1:]
        if not word.startswith('-'):
            positionals.append(word)
        index += 1
    # --repo supplies the remote separately; every positional is then a refspec.
    # A leading plus asks Git to force that update, even without --force.
    refspecs = positionals if remote_option else positionals[1:]
    return not dry_run and (forced or any(word.startswith('+') and len(word) > 1 for word in refspecs))


def _deletion(name: str, args: list[str], shell: str) -> bool:
    options = args[:args.index('--')] if '--' in args else args
    lower = {word.casefold() for word in options}
    if name == 'remove-item' or shell == 'powershell' and name in {'rm', 'ri', 'rmdir', 'rd'}:
        lower = set()
        index = 0
        while index < len(options):
            word = options[index].casefold()
            if word in {'-literalpath', '-path', '-filter', '-include', '-exclude'}:
                index += 2
                continue
            lower.add(word)
            index += 1
        recursive = any(re.fullmatch(r'-(?:r|re|rec|recu|recur|recurs|recurse)(?::\$true)?', word) for word in lower)
        force = any(re.fullmatch(r'-(?:f|fo|for|forc|force)(?::\$true)?', word) for word in lower)
        return bool(recursive and force) and not (lower & {'-whatif', '-whatif:$true'})
    if name in {'rmdir', 'rd'}:
        return '/s' in lower and '/q' in lower
    if name != 'rm':
        return False
    short = ''.join(word[1:] for word in options if re.fullmatch(r'-[rRfivd]+', word))
    return ('--recursive' in options or bool(set(short) & {'r', 'R'})) and ('--force' in options or 'f' in short)


def _dangerous(command: str, shell: str, depth: int = 0) -> bool:
    for words in _segments(command):
        # Literal shell assignments can prefix an executable in Bash.
        if shell == 'bash':
            while words and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*', words[0], re.S):
                words = words[1:]
        if not words:
            continue
        if words[0] in {'command', 'exec'} and len(words) > 1:
            words = words[1:]
        name, args = _program(words[0]), words[1:]
        if name == 'git' and _git(args) or _deletion(name, args, shell):
            return True
        if depth >= MAX_WRAPPER_DEPTH:
            continue
        wrappers = {'powershell': ({'-command', '-c'}, 'powershell'), 'pwsh': ({'-command', '-c'}, 'powershell'),
                    'bash': ({'-c', '-lc'}, 'bash'), 'sh': ({'-c'}, 'bash'), 'cmd': ({'/c'}, 'cmd')}
        if name in wrappers:
            switches, nested_shell = wrappers[name]
            for index, word in enumerate(args):
                if word.casefold() in switches and index + 1 < len(args):
                    # An interpreter's following literal argument is code;
                    # ordinary echo/grep/Read arguments are never reinterpreted.
                    nested = args[index + 1] if nested_shell == 'bash' else ' '.join(args[index + 1:])
                    if _dangerous(nested, nested_shell, depth + 1):
                        return True
                    break
    return False


def preflight(payload: dict) -> dict:
    if payload.get('tool_name') not in {'Bash', 'PowerShell'}:
        return {}
    inputs = payload.get('tool_input')
    if not isinstance(inputs, dict):
        return {}
    command = inputs.get('command', inputs.get('cmd'))
    if not isinstance(command, str) or not command or len(command) > MAX_COMMAND_CHARS or '\0' in command:
        return {}
    if not _dangerous(command, payload['tool_name'].casefold()):
        return {}
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                  'permissionDecisionReason': _REASON}}
