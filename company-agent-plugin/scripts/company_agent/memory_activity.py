"""Observe bounded memory preparation and the exact writer's checked receipt.

This is completion accounting, not permission. No CLI/model call, directory
scan, or extra verification turn. Never discharges other outstanding changes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate memory field')
        result[key] = value
    return result


def spec_write(tool: str, inputs: dict, root: Path) -> bool:
    """Only a typed, compact spec at the exact disposable staging location."""
    if tool.casefold() != 'write':
        return False
    value, content = inputs.get('file_path'), inputs.get('content')
    if not isinstance(value, str) or not isinstance(content, str) or len(content.encode('utf-8')) > 8192:
        return False
    from .resource_scope import safe
    from .memory import (ALLOWED_SPEC_KEYS, MEMORY_KINDS, MEMORY_STATUSES,
                         MEMORY_ID_PATTERN, SOURCE_PATTERN, _contains_raw_artifact,
                         MAX_MEMORY_BODY_CHARS, MAX_MEMORY_TITLE_CHARS, SECRET_PATTERNS)
    try:
        path = Path(value)
        if (path.parent != root.absolute() / 'tmp' or
                not re.fullmatch(r'memory-[A-Za-z0-9_-]{1,80}\.json', path.name)):
            return False
        safe(path)
        spec = json.loads(content, object_pairs_hook=_object)
        if not isinstance(spec, dict) or set(spec) - ALLOWED_SPEC_KEYS:
            return False
        if spec.get('kind', 'preference') not in MEMORY_KINDS or spec.get('status', 'active') not in MEMORY_STATUSES:
            return False
        for key, limit in (('title', MAX_MEMORY_TITLE_CHARS), ('body', MAX_MEMORY_BODY_CHARS)):
            if not isinstance(spec.get(key), str) or not 0 < len(spec[key].strip()) <= limit:
                return False
        if 'id' in spec and (not isinstance(spec['id'], str) or len(spec['id']) > 160 or
                             not MEMORY_ID_PATTERN.fullmatch(spec['id'])):
            return False
        if 'source' in spec and (not isinstance(spec['source'], str) or not SOURCE_PATTERN.fullmatch(spec['source'])):
            return False
        if 'reason' in spec and (not isinstance(spec['reason'], str) or len(spec['reason']) > 200):
            return False
        text = spec['title'] + '\n' + spec['body']
        return not _contains_raw_artifact(text) and not any(pattern.search(text) for pattern in SECRET_PATTERNS)
    except (OSError, ValueError, TypeError, RecursionError):
        return False


def checked_change(payload: dict, root: Path) -> dict | None:
    """Accept only this CLI's success, at its resolved scope and current hash."""
    if (payload.get('hook_event_name') != 'PostToolUse' or
            payload.get('tool_name') not in {'Bash', 'PowerShell'} or
            payload.get('error') or payload.get('tool_error')):
        return None
    inputs, response = payload.get('tool_input'), payload.get('tool_response')
    if not isinstance(inputs, dict) or not isinstance(response, dict):
        return None
    if any(response.get(key) is True for key in ('interrupted', 'isError', 'is_error')):
        return None
    if any(key in response and (type(response[key]) is not int or response[key] != 0)
           for key in ('exitCode', 'exit_code')):
        return None
    from .execution_contract import _trusted_arguments, _fields, _same
    args = _trusted_arguments(inputs.get('command') or inputs.get('cmd') or '')
    if not args or args[:2] not in (['memory', 'upsert'], ['memory', 'restore']):
        return None
    operation = args[1]
    common = {'--state-root', '--storage-scope', '--project-root', '--expected-revision', '--expected-sha256'}
    required = {'--state-root', '--storage-scope', '--project-root'}
    allowed = common | ({'--spec'} if operation == 'upsert' else {'--id', '--revision'})
    required |= {'--spec'} if operation == 'upsert' else {'--id', '--revision', '--expected-revision', '--expected-sha256'}
    fields = _fields(args[2:], allowed, required)
    if fields is None or not _same(fields['--state-root'], root):
        return None
    scope = fields['--storage-scope']
    if scope not in {'personal', 'project'}:
        return None
    if ('--expected-revision' in fields) != ('--expected-sha256' in fields):
        return None
    for key in ('--expected-revision', '--revision'):
        if key in fields and not re.fullmatch(r'[1-9][0-9]{0,9}', fields[key]):
            return None
    if '--expected-sha256' in fields and not re.fullmatch(r'[a-f0-9]{64}', fields['--expected-sha256']):
        return None
    stdout = response.get('stdout')
    if not isinstance(stdout, str) or len(stdout.encode('utf-8')) > 16384:
        return None
    from .resource_scope import selected_root, scope_metadata, safe
    from .memory import _read_memory_document, _document_sha256, _slug, MEMORY_ID_PATTERN
    try:
        result = json.loads(stdout, object_pairs_hook=_object)
        if not isinstance(result, dict) or result.get('ok') is not True or result.get('operation') != operation:
            return None
        if result.get('verification') != {'status': 'persisted-content-verified', 'scope': 'memory-item-only'}:
            return None
        identifier = result.get('id')
        if (not isinstance(identifier, str) or len(identifier) > 160 or not MEMORY_ID_PATTERN.fullmatch(identifier)
                or result.get('memoryId') != identifier or type(result.get('revision')) is not int
                or result['revision'] < 1 or type(result.get('changed')) is not bool):
            return None
        project = safe(Path(fields['--project-root']))
        if not project.is_dir():
            return None
        metadata = scope_metadata(scope, project)
        if any(result.get(key) != value for key, value in metadata.items()):
            return None
        target = selected_root(root, project, scope) / 'memory/items' / (_slug(identifier) + '.md')
        if not isinstance(result.get('path'), str) or not _same(result['path'], target):
            return None
        if operation == 'restore' and (fields['--id'] != identifier or
                                      result.get('restoredFrom') != int(fields['--revision'])):
            return None
        document = _read_memory_document(target, target.parent)
        if (document.metadata.get('id') != identifier or document.metadata.get('revision') != result['revision']
                or document.metadata.get('status') != result.get('status')
                or _document_sha256(document) != result.get('sha256')):
            return None
        digest = hashlib.sha256(f'{target.absolute()}\0{result["revision"]}\0{result["sha256"]}'.encode('utf-8')).hexdigest()[:32]
        if digest != result.get('changeId'):
            return None
        return {key: result[key] for key in ('id', 'revision', 'sha256', 'changed', 'operation', 'storageScope', 'changeId')}
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return None
