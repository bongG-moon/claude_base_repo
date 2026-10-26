"""Bounded persistence-invocation evidence, without reading saved bodies.

An invocation is not a successful save. The execution event's result state is
kept separately. This module never reads files, follows a path or runs code.
"""
from __future__ import annotations

import json
import re
import shlex


KINDS = frozenset(('skill', 'memory', 'knowledge'))
BASES = frozenset(('target_path', 'persistence_tool', 'managed_command'))
PERSISTENCE_TOOLS = {
    'save_query_knowledge': 'knowledge', 'save_table_knowledge': 'knowledge',
    'save_column_meaning': 'knowledge', 'save_knowledge': 'knowledge',
    'upsert_knowledge': 'knowledge', 'add_knowledge': 'knowledge',
    'save_memory': 'memory', 'upsert_memory': 'memory', 'add_memory': 'memory',
    'create_memory': 'memory', 'update_memory': 'memory',
}
PENDING_STATES = frozenset(('input_required', 'approval_required', 'needs_confirmation',
    'needs_approval', 'pending', 'cancelled', 'canceled', 'deferred', 'waiting_for_approval',
    'waiting_for_input', 'requires_confirmation', 'user_cancelled', 'skipped'))
FAILED_STATES = frozenset(('failed', 'failure', 'error', 'rejected', 'denied', 'blocked',
    'timeout', 'timed_out', 'unavailable', 'not_supported'))


def _target(value, clean):
    if not isinstance(value, str) or not re.fullmatch(r'[가-힣A-Za-z0-9 ._():-]{1,100}', value):
        return ''
    if re.search(r'(?i)(?:token|secret|password|authorization|api[_ -]?key|credentials|sk-ant-|ghp_|github_pat_|glpat-)', value):
        return ''
    if any(len(word) > 40 or re.fullmatch(r'[a-fA-F0-9]{24,}', word)
           for word in re.findall(r'[A-Za-z0-9_-]+', value)):
        return ''
    return clean(value, 100)


def _evidence(kind, basis, target, clean):
    record = {'kind': kind, 'operation': 'create_or_update', 'basis': basis}
    value = _target(target, clean)
    if value:
        record['target'] = value
    return record


def _path_evidence(value, clean):
    if not isinstance(value, str) or len(value) > 4096 or any(c in value for c in '\x00\r\n'):
        return None
    parts = [part for part in value.replace('\\', '/').split('/') if part and part != '.']
    if not parts or '..' in parts or '://' in value:
        return None
    lower = [part.casefold() for part in parts]
    # A canonical entry file is evidence even if a skill edits it relatively.
    if lower[-1] == 'skill.md':
        return _evidence('skill', 'target_path', parts[-2] if len(parts) > 1 else 'SKILL.md', clean)
    # Supporting files are part of a named skill, not every file named "skill".
    for index, part in enumerate(lower[:-2]):
        if part in ('skills', 'standalone-skills'):
            return _evidence('skill', 'target_path', parts[index + 1], clean)
    # Native auto memory and harness Markdown stores share these conventions.
    # Staging JSON specs and ordinary data files are deliberately not evidence.
    if lower[-1] == 'memory.md':
        return _evidence('memory', 'target_path', parts[-1], clean)
    if lower[-1].endswith('.md'):
        for kind in ('memory', 'knowledge'):
            if kind in lower[:-1]:
                return _evidence(kind, 'target_path', parts[-1], clean)
    return None


def _command_parts(command):
    if not isinstance(command, str) or len(command) > 32768:
        return None
    # No shell evaluation, command chains, substitution or multiline scripts.
    if any(value in command for value in ('`', '$(', '${', '\r', '\n')):
        return None
    command = command.strip()
    if command.startswith('& '):
        command = command[2:].lstrip()
    quote = None
    for char in command:
        if quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char in ';&|<>':
            return None
    if quote:
        return None
    try:
        parts = [part.strip('"\'') for part in shlex.split(command, posix=False)]
    except ValueError:
        return None
    if not parts or any(p.casefold() in ('--help', '-h', '--dry-run', '--preview') for p in parts):
        return None
    return parts


def _managed_evidence(command, clean):
    parts = _command_parts(command)
    if not parts:
        return None
    executable = re.sub(r'\.(?:exe|cmd)$', '', parts[0].replace('\\', '/').rsplit('/', 1)[-1]).casefold()
    if executable == 'company-agent':
        args = parts[1:]
    elif executable in ('powershell', 'pwsh'):
        # Only the known file launcher; never an inline PowerShell command.
        index = 1
        while index < len(parts) and parts[index].casefold() in ('-nologo', '-noprofile', '-executionpolicy'):
            if parts[index].casefold() == '-executionpolicy':
                if index + 1 >= len(parts) or parts[index + 1].casefold() not in ('bypass', 'remotesigned'):
                    return None
                index += 2
            else:
                index += 1
        if index + 3 >= len(parts) or parts[index].casefold() != '-file':
            return None
        if parts[index + 1].replace('\\', '/').rsplit('/', 1)[-1].casefold() != 'invoke-companyagent.ps1':
            return None
        if [p.casefold() for p in parts[index + 2:index + 4]] != ['-mode', 'cli']:
            return None
        args = parts[index + 4:]
    else:
        return None
    if len(args) < 2:
        return None
    pair = tuple(p.casefold() for p in args[:2])
    if pair in (('memory', 'upsert'), ('knowledge', 'upsert')) and '--spec' in args[2:]:
        index = args.index('--spec', 2)
        if index + 1 < len(args) and not args[index + 1].startswith('-'):
            return _evidence(pair[0], 'managed_command', '', clean)
    # "asset create --spec" can create a Skill, script tool or MCP. It is not
    # enough to infer the asset kind without reading another file.
    if pair == ('asset', 'update') and '--name' in args[2:] and '--instructions-file' in args[2:]:
        index = args.index('--name', 2)
        source = args.index('--instructions-file', 2)
        if (index + 1 < len(args) and not args[index + 1].startswith('-')
                and source + 1 < len(args) and not args[source + 1].startswith('-')):
            return _evidence('skill', 'managed_command', args[index + 1], clean)
    return None


def asset_change(tool, args, clean):
    """Return a safe persistence signal from actual invocation fields only."""
    if isinstance(args, str) and len(args) <= 65536:
        try:
            args = json.loads(args)
        except (ValueError, TypeError, RecursionError):
            return None
    args = args if isinstance(args, dict) else {}
    name = tool.rsplit('.', 1)[-1].casefold()
    if name in ('write', 'write_file', 'edit', 'multiedit'):
        return _path_evidence(args.get('file_path', args.get('path')), clean)
    leaf = name.rsplit('__', 1)[-1]
    if leaf in PERSISTENCE_TOOLS:
        return _evidence(PERSISTENCE_TOOLS[leaf], 'persistence_tool', '', clean)
    if name in ('mcp__memory__create_entities', 'mcp__memory__add_observations'):
        return _evidence('memory', 'persistence_tool', '', clean)
    if name in ('bash', 'powershell', 'exec_command', 'shell_command', 'shell'):
        return _managed_evidence(args.get('command', args.get('cmd')), clean)
    return None


def normalize_asset_change(record, clean):
    """Validate imported metadata; do not trust extra provenance or bodies."""
    if record is None:
        return None
    if (not isinstance(record, dict) or record.get('kind') not in KINDS
            or record.get('operation') != 'create_or_update' or record.get('basis') not in BASES):
        raise ValueError('invalid asset change evidence')
    if 'target' in record and (not isinstance(record['target'], str) or len(record['target']) > 100):
        raise ValueError('invalid asset change target')
    return _evidence(record['kind'], record['basis'], record.get('target', ''), clean)


def compatible_asset_change(tool, record):
    """Do not let an imported Read/Skill event become a claimed save call."""
    if not record:
        return True
    name = tool.rsplit('.', 1)[-1].casefold()
    if record['basis'] == 'target_path':
        return name in ('write', 'write_file', 'edit', 'multiedit')
    if record['basis'] == 'managed_command':
        return name in ('bash', 'powershell', 'exec_command', 'shell_command', 'shell')
    expected = PERSISTENCE_TOOLS.get(name.rsplit('__', 1)[-1])
    if name in ('mcp__memory__create_entities', 'mcp__memory__add_observations'):
        expected = 'memory'
    return expected == record['kind']


def persistence_result(payload):
    """Read only a bounded complete JSON response envelope, not prose mentions.

    None means no explicit non-save evidence. It never means a verified save.
    The caller separately retains transport errors and whether a response exists.
    """
    if not isinstance(payload, dict):
        return None
    value = payload.get('structuredContent', payload.get('output', payload.get('content', payload)))
    if isinstance(value, list):
        if len(value) > 8 or any(not isinstance(part, dict) or part.get('type') != 'text'
                                 or not isinstance(part.get('text'), str) for part in value):
            return None
        # Avoid concatenating large result bodies merely to inspect status.
        if sum(len(part['text']) for part in value) > 65536:
            return None
        value = ''.join(part['text'] for part in value)
    if isinstance(value, str):
        if len(value) > 65536 or not value.lstrip().startswith('{'):
            return None
        try:
            value = json.loads(value)
        except (ValueError, TypeError, RecursionError):
            return None
    if not isinstance(value, dict):
        return None
    code = value.get('exit_code')
    if (value.get('is_error') is True or value.get('isError') is True
            or isinstance(code, int) and not isinstance(code, bool) and code != 0):
        return 'failed'
    state = value.get('status')
    state = state.casefold().replace('-', '_') if isinstance(state, str) and len(state) <= 64 else ''
    if state in PENDING_STATES:
        return 'pending'
    if state in FAILED_STATES or value.get('ok') is False or value.get('success') is False:
        return 'failed'
    if value.get('saved') is False:
        return 'pending'
    return None


def merge_asset_change(previous, incoming):
    """Legacy absence may be enriched; disagreeing save evidence stays unknown."""
    old, new = previous.get('asset_change'), incoming.get('asset_change')
    if previous.get('asset_change_conflict') or incoming.get('asset_change_conflict') or (old and new and old != new):
        previous.pop('asset_change', None)
        previous['asset_change_conflict'] = True
    elif not old and new:
        previous['asset_change'] = dict(new)
