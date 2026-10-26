"""Small, redacted execution traces for on-demand work analysis.

Read only invocation metadata and explicit result flags. No command, prompt,
source text, tool output, image, credential or assistant reasoning is retained.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
from work_purpose import explain_purpose, normalize_purpose
from work_asset_evidence import (asset_change, compatible_asset_change, merge_asset_change,
                                 normalize_asset_change, persistence_result)

MAX_EXECUTIONS = 400
MAX_REQUEST_LINKS = 96
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_.:-]{0,99}')
HASH = re.compile(r'[a-f0-9]{64}')
OPERATIONS = {
    'read': '파일 내용 읽기', 'write': '파일 작성', 'edit': '파일 수정',
    'search': '자료·파일 검색', 'skill': '스킬 불러오기', 'delegate': '하위 작업자 호출',
    'question': '사용자에게 확인 요청', 'python': 'Python 코드 실행',
    'test': '검증 명령 실행', 'shell': '명령 실행', 'browser': '브라우저 도구 호출',
    'connected': '연결 도구 호출', 'other': '도구 호출',
}


def hashed(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def safe_target(value, clean, *, basename=False):
    if not isinstance(value, str) or len(value) > 4096:
        return ''
    if value in ('[민감 대상 가림]', '[긴 식별자 가림]'):
        return value
    if basename:
        value = value.replace('\\', '/').rstrip('/').rsplit('/', 1)[-1]
    if not value or value in ('.', '..'):
        return ''
    if re.search(r'(?i)(?:token|secret|password|authorization|api[_ -]?key|\.env\b|credentials|sk-ant-|ghp_|github_pat_|glpat-)|@|https?://', value):
        return '[민감 대상 가림]'
    if not re.fullmatch(r'[가-힣A-Za-z0-9 ._():-]{1,100}', value):
        return ''
    if any(len(word) > 40 or re.fullmatch(r'[a-fA-F0-9]{24,}', word)
           for word in re.findall(r'[A-Za-z0-9_-]+', value)):
        return '[긴 식별자 가림]'
    return clean(value, 100)


def shell_kind(command):
    """Classify a simple executable invocation, never words inside its data."""
    if not isinstance(command, str) or len(command) > 65536:
        return 'shell'
    quote = None
    for char in command:
        if quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char in ';&|\r\n':
            return 'shell'
    if quote:
        return 'shell'
    try:
        parts = [part.strip('"\'') for part in shlex.split(command, posix=False)]
    except ValueError:
        return 'shell'
    if not parts:
        return 'shell'
    executable = parts[0].replace('\\', '/').rsplit('/', 1)[-1].lower()
    executable = re.sub(r'\.(?:exe|cmd)$', '', executable)
    if executable in ('pytest', 'py.test'):
        return 'test'
    if executable in ('npm', 'pnpm', 'yarn') and (parts[1:2] == ['test'] or parts[1:3] == ['run', 'test']):
        return 'test'
    if not re.fullmatch(r'python(?:3(?:\.\d+)?)?|py', executable):
        return 'shell'
    index = 1
    while index < len(parts):
        value = parts[index]
        if value == '-m':
            return 'test' if parts[index+1:index+2] in (['pytest'], ['unittest']) else 'python'
        if value in ('-X', '-W'):
            index += 2
        elif value in ('-I', '-B', '-u', '-S', '-E', '-s', '-O', '-OO', '-q') or re.fullmatch(r'-3(?:\.\d+)?', value):
            index += 1
        else:
            break
    return 'python'


def shell_script_target(command, clean):
    if shell_kind(command) != 'python':
        return ''
    parts = [part.strip('"\'') for part in shlex.split(command, posix=False)]
    index = 1
    while index < len(parts):
        value = parts[index]
        if value in ('-X', '-W'):
            index += 2
        elif value in ('-I', '-B', '-u', '-S', '-E', '-s', '-O', '-OO', '-q') or re.fullmatch(r'-3(?:\.\d+)?', value):
            index += 1
        elif value.startswith('-'):
            return ''
        else:
            return safe_target(value, clean, basename=True) if value.lower().endswith('.py') else ''
    return ''


def describe(tool, args, clean):
    """Only allowlisted metadata leaves this function; command text stays local."""
    if isinstance(args, str) and len(args) <= 65536:
        try:
            args = json.loads(args)
        except (ValueError, TypeError, RecursionError):
            args = {}
    args = args if isinstance(args, dict) else {}
    name = tool.rsplit('.', 1)[-1].lower()
    target = ''
    if name in ('read', 'read_file', 'view_image'):
        kind = 'read'
    elif name in ('write', 'write_file'):
        kind = 'write'
    elif name in ('edit', 'multiedit', 'apply_patch'):
        kind = 'edit'
    elif name in ('glob', 'grep', 'toolsearch', 'tool_search', 'search', 'search_query'):
        kind = 'search'
    elif name == 'skill':
        kind = 'skill'
        target = safe_target(args.get('skill'), clean)
    elif name in ('agent', 'task', 'spawn_agent'):
        kind = 'delegate'
        target = safe_target(args.get('subagent_type'), clean)
    elif name in ('askuserquestion', 'request_user_input', 'request_user_input_async'):
        kind = 'question'
    elif name in ('bash', 'powershell', 'exec_command', 'shell_command', 'shell'):
        command = args.get('command', args.get('cmd', ''))
        kind = shell_kind(command)
        if kind == 'python':
            target = shell_script_target(command, clean)
    elif 'browser_' in name or 'playwright' in tool.lower() or 'chrome-devtools' in tool.lower():
        kind = 'browser'
    elif tool.lower().startswith(('mcp_', 'mcp.')):
        kind = 'connected'
    else:
        kind = 'other'
    if kind in ('read', 'write', 'edit'):
        target = safe_target(args.get('file_path', args.get('path', '')), clean, basename=True)
    return OPERATIONS[kind], target


def result_state(payload):
    """An observed response is never a claim that the business task succeeded."""
    if not isinstance(payload, dict):
        return 'returned'
    if payload.get('is_error') is True or payload.get('isError') is True:
        return 'error'
    value = payload.get('output', payload)
    if isinstance(value, str) and len(value) <= 65536 and value.lstrip().startswith('{'):
        try:
            value = json.loads(value)
        except (ValueError, TypeError, RecursionError):
            value = None
    if isinstance(value, dict):
        if value.get('is_error') is True or value.get('isError') is True:
            return 'error'
        code = value.get('exit_code')
        if isinstance(code, int) and not isinstance(code, bool) and code != 0:
            return 'error'
        metadata = value.get('metadata')
        code = metadata.get('exit_code') if isinstance(metadata, dict) else None
        if isinstance(code, int) and not isinstance(code, bool) and code != 0:
            return 'error'
    return 'returned'


def tool_records(row):
    """Yield calls/results only from official conversation record envelopes."""
    message = row.get('message')
    if row.get('type') in ('assistant', 'user') and isinstance(message, dict):
        content = message.get('content')
        for item in content if isinstance(content, list) else []:
            if not isinstance(item, dict):
                continue
            if row['type'] == 'assistant' and item.get('type') == 'tool_use':
                yield ('call', item.get('id'), item.get('name'), item.get('input'))
            elif row['type'] == 'user' and item.get('type') == 'tool_result':
                yield ('result', item.get('tool_use_id'), None, item)
    elif row.get('type') == 'response_item' and isinstance(row.get('payload'), dict):
        item = row['payload']
        if item.get('type') in ('function_call', 'custom_tool_call'):
            yield ('call', item.get('call_id'), item.get('name'), item.get('arguments', item.get('input')))
        elif item.get('type') in ('function_call_output', 'custom_tool_call_output'):
            yield ('result', item.get('call_id'), None, item)


class ExecutionTrace:
    def __init__(self, clean, cap=MAX_EXECUTIONS):
        self.clean, self.cap = clean, min(cap, MAX_EXECUTIONS)
        self.events, self.by_call, self.context = {}, {}, []
        self.ordinal, self.partial = 0, False

    def set_requests(self, request_ids):
        self.context = list(request_ids)[:MAX_REQUEST_LINKS]
        self.partial |= len(request_ids) > MAX_REQUEST_LINKS

    def observe(self, row, row_key, allow_calls=True, max_calls=MAX_EXECUTIONS):
        calls = 0
        for index, (kind, native_id, name, payload) in enumerate(tool_records(row)):
            valid_native = isinstance(native_id, str) and 0 < len(native_id) <= 1024
            call_key = hashed('call:' + native_id) if valid_native else None
            if kind == 'result':
                event = self.by_call.get(call_key) if call_key else None
                if event is not None:
                    status = result_state(payload)
                    asset_result = persistence_result(payload) if event.get('asset_change') else None
                    if asset_result == 'failed':
                        status = 'error'
                    elif asset_result == 'pending' and status != 'error':
                        status = 'unconfirmed'
                    if asset_result:
                        event['asset_result'] = ('failed' if event.get('asset_result') == 'failed'
                            or status == 'error' else asset_result)
                    # Duplicated logs cannot clear an explicitly observed failure.
                    if event['status'] != 'error':
                        event['status'] = ('unconfirmed' if status != 'error'
                            and event.get('asset_result') == 'pending' else status)
                    event['result_observed'] = True
                continue
            if not isinstance(name, str) or not NAME.fullmatch(name) or self.clean(name, 100) != name:
                self.partial = True
                continue
            calls += 1
            event_id = call_key or hashed('event:' + row_key + ':' + str(index))
            if event_id in self.events:
                operation, target = describe(name, payload, self.clean)
                previous = self.events[event_id]
                if (previous['tool'], previous['operation'], previous['target']) != (name, operation, target):
                    self.partial = True
                    previous.pop('asset_change', None)
                    previous['asset_change_conflict'] = True
                else:
                    _merge_purpose(previous, {'purpose': explain_purpose(name, payload, self.clean, target)})
                    change = asset_change(name, payload, self.clean)
                    # Both raw invocations were observed here: a changed path
                    # is a disagreement, unlike an older catalog missing metadata.
                    merge_asset_change(previous, {'asset_change': change,
                        'asset_change_conflict': previous.get('asset_change') != change})
                    if previous.get('purpose_conflict'):
                        self.partial = True
                    if previous.get('asset_change_conflict'):
                        self.partial = True
                continue
            if not allow_calls or calls > max_calls or len(self.events) >= self.cap:
                self.partial = True
                continue
            self.ordinal += 1
            operation, target = describe(name, payload, self.clean)
            event = {'id': event_id, 'request_ids': list(self.context), 'ordinal': self.ordinal,
                     'tool': name, 'operation': operation, 'target': target,
                     'status': 'unconfirmed', 'evidence': 'tool_call', 'result_observed': False,
                     'request_group_ambiguous': len(self.context) > 1}
            purpose = explain_purpose(name, payload, self.clean, target)
            if purpose:
                event['purpose'] = purpose
            change = asset_change(name, payload, self.clean)
            if change:
                event['asset_change'] = change
            self.events[event_id] = event
            if call_key:
                self.by_call[call_key] = event


def sanitize_execution(record, clean, request_ids):
    if not isinstance(record, dict) or not HASH.fullmatch(str(record.get('id', ''))):
        raise ValueError('invalid execution id')
    ordinal = record.get('ordinal')
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
        raise ValueError('invalid execution order')
    tool = record.get('tool')
    if not isinstance(tool, str) or not NAME.fullmatch(tool) or clean(tool, 100) != tool:
        raise ValueError('invalid execution tool')
    operation = record.get('operation')
    if operation not in OPERATIONS.values():
        raise ValueError('invalid execution operation')
    linked = record.get('request_ids')
    if not isinstance(linked, list) or len(linked) > MAX_REQUEST_LINKS or any(
            not isinstance(rid, str) or rid not in request_ids for rid in linked):
        raise ValueError('invalid execution request link')
    linked = list(dict.fromkeys(linked))
    status, observed = record.get('status'), record.get('result_observed')
    if status not in ('returned', 'error', 'unconfirmed') or not isinstance(observed, bool):
        raise ValueError('invalid execution outcome')
    asset_result = record.get('asset_result')
    pending_response = asset_result == 'pending' and status == 'unconfirmed' and observed
    if ((status == 'unconfirmed') == observed and not pending_response) or record.get('evidence') != 'tool_call':
        raise ValueError('inconsistent execution outcome')
    normalized = {'id': record['id'], 'request_ids': linked, 'ordinal': ordinal, 'tool': tool,
            'operation': operation, 'target': safe_target(record.get('target', ''), clean),
            'status': status, 'evidence': 'tool_call', 'result_observed': observed,
            'request_group_ambiguous': len(linked) > 1}
    conflict = record.get('purpose_conflict', False)
    if not isinstance(conflict, bool):
        raise ValueError('invalid execution purpose conflict')
    purpose = normalize_purpose(record.get('purpose'), clean)
    if conflict:
        normalized['purpose_conflict'] = True
    elif purpose:
        normalized['purpose'] = purpose
    conflict = record.get('asset_change_conflict', False)
    if not isinstance(conflict, bool):
        raise ValueError('invalid asset change conflict')
    change = normalize_asset_change(record.get('asset_change'), clean)
    if not compatible_asset_change(tool, change):
        raise ValueError('asset change does not match invocation')
    if asset_result is not None:
        if (asset_result not in ('pending', 'failed') or not (change or conflict) or not observed
                or (asset_result == 'failed' and status != 'error')
                or (asset_result == 'pending' and status not in ('unconfirmed', 'error'))):
            raise ValueError('invalid asset result evidence')
        normalized['asset_result'] = asset_result
    if conflict:
        normalized['asset_change_conflict'] = True
    elif change:
        normalized['asset_change'] = change
    return normalized


def _merge_purpose(previous, incoming):
    """Missing legacy metadata may be enriched, conflicting prose stays unknown."""
    old, new = previous.get('purpose'), incoming.get('purpose')
    if previous.get('purpose_conflict') or incoming.get('purpose_conflict') or (old and new and old != new):
        previous.pop('purpose', None)
        previous['purpose_conflict'] = True
    elif not old and new:
        previous['purpose'] = dict(new)


def merge_executions(existing, incoming):
    """Merge duplicate source copies, preserving explicit errors conservatively."""
    records = {record['id']: dict(record) for record in existing}
    for record in incoming:
        previous = records.get(record['id'])
        if previous is None:
            records[record['id']] = dict(record)
            continue
        stable = ('request_ids', 'tool', 'operation', 'target', 'evidence')
        if any(previous[key] != record[key] for key in stable):
            raise ValueError('conflicting execution evidence')
        if record['status'] == 'error' or previous['status'] == 'error':
            previous['status'] = 'error'
        elif record.get('asset_result') == 'pending' or previous.get('asset_result') == 'pending':
            previous['status'] = 'unconfirmed'
        elif record['status'] == 'returned' or previous['status'] == 'returned':
            previous['status'] = 'returned'
        if record.get('asset_result') == 'failed' or previous.get('asset_result') == 'failed':
            previous['asset_result'] = 'failed'
        elif record.get('asset_result') == 'pending' or previous.get('asset_result') == 'pending':
            previous['asset_result'] = 'pending'
        previous['result_observed'] |= record['result_observed']
        previous['ordinal'] = min(previous['ordinal'], record['ordinal'])
        _merge_purpose(previous, record)
        merge_asset_change(previous, record)
    if len(records) > MAX_EXECUTIONS:
        raise ValueError('merged execution cap')
    return sorted(records.values(), key=lambda item: (item['ordinal'], item['id']))
