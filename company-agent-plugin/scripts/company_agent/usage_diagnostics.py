"""Opt-in bounded transcript statistics. Never export prompts, paths or bodies.

Only explicitly selected UTF-8 JSONL files are opened. No session-directory
guessing, price fallback, model calls, network access or persistent cache.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path

MAX_BYTES = 32 * 1024 * 1024
MAX_LINE = 1024 * 1024
MAX_RECORDS = 50_000
METRICS = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')
TOOLS = frozenset({'Read', 'Write', 'Edit', 'Bash', 'PowerShell', 'Glob', 'Grep', 'Skill', 'Agent', 'Task', 'AskUserQuestion'})


def _count(value):
    return value if type(value) is int and 0 <= value <= 10**12 else None


def analyze_usage(paths: list[Path]) -> dict:
    result = {'status': 'not-requested', 'filesRead': 0, 'recordsRead': 0, 'skippedRecords': 0,
              'usageRecordsWithoutId': 0, 'tokens': {key: None for key in METRICS},
              'missingUsageFields': {key: 0 for key in METRICS}, 'toolCalls': {},
              'sameRangeReads': None, 'observedSpanMs': None, 'cost': None,
              'costReason': '사내 모델 단가 미설정. 다른 모델 단가로 대체하지 않습니다.',
              'notice': '관찰 구간에는 사용자 대기가 포함됩니다. 같은 범위 재읽기가 모두 낭비인 것은 아닙니다. 원문·경로·명령은 보고서에 포함하지 않습니다.'}
    if not paths:
        return result
    if len(paths) > 8:
        raise ValueError('select at most 8 usage logs')
    messages, models, calls, failures, reads, times, seen_files = {}, {}, {}, set(), Counter(), [], set()
    total_bytes = 0
    limited = False
    from .skill_registry import _no_reparse
    for path in paths:
        path = Path(path).absolute()
        _no_reparse(path)
        resolved = path.resolve()
        if resolved in seen_files:
            continue
        seen_files.add(resolved)
        if path.suffix.casefold() != '.jsonl':
            raise ValueError('usage logs must be JSONL')
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('usage log exceeds read limit')
        with path.open('rb') as stream:
            result['filesRead'] += 1
            while line := stream.readline(MAX_LINE + 1):
                total_bytes += len(line)
                if total_bytes > MAX_BYTES or len(line) > MAX_LINE or result['recordsRead'] >= MAX_RECORDS:
                    limited = True
                    break
                result['recordsRead'] += 1
                try:
                    rec = json.loads(line.decode('utf-8-sig'))
                except (UnicodeError, ValueError, RecursionError):
                    result['skippedRecords'] += 1
                    continue
                if not isinstance(rec, dict):
                    result['skippedRecords'] += 1
                    continue
                timestamp = rec.get('timestamp')
                if isinstance(timestamp, str) and len(timestamp) < 50:
                    try:
                        value = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        if value.tzinfo is not None:
                            times.append(value.timestamp())
                    except (ValueError, OverflowError, OSError):
                        pass
                msg = rec.get('message')
                if rec.get('type') == 'user' and isinstance(msg, dict) and isinstance(msg.get('content'), list):
                    for block in msg['content']:
                        if isinstance(block, dict) and block.get('type') == 'tool_result' and block.get('is_error') is True:
                            tool_id = block.get('tool_use_id')
                            if isinstance(tool_id, str) and 0 < len(tool_id) <= 200:
                                failures.add(tool_id)
                if rec.get('type') != 'assistant' or not isinstance(msg, dict):
                    continue
                usage, mid = msg.get('usage'), msg.get('id')
                valid_id = isinstance(mid, str) and 0 < len(mid) <= 200
                # Retain the ID even when this message has no usage fields.
                # A later streaming record can fill them; otherwise mark gaps.
                if valid_id:
                    messages.setdefault(mid, {})
                    model = msg.get('model')
                    if isinstance(model, str) and 0 < len(model) <= 160:
                        models.setdefault(mid, model)
                if isinstance(usage, dict):
                    if valid_id:
                        # Native streaming may repeat a message's cumulative usage.
                        # Missing IDs are not safely deduplicable; expose that gap.
                        stored = messages.setdefault(mid, {})
                        for key in METRICS:
                            value = _count(usage.get(key))
                            if value is not None:
                                stored[key] = max(stored.get(key, 0), value)
                    else:
                        result['usageRecordsWithoutId'] += 1
                content = msg.get('content', [])
                if not isinstance(content, list):
                    continue
                for item in content:
                    if not isinstance(item, dict) or item.get('type') != 'tool_use':
                        continue
                    call_id = item.get('id')
                    if not isinstance(call_id, str) or not 0 < len(call_id) <= 200 or call_id in calls:
                        continue
                    name = item.get('name')
                    calls[call_id] = name if isinstance(name, str) and name in TOOLS else 'Other'
                    inp = item.get('input')
                    if name == 'Read' and isinstance(inp, dict) and isinstance(inp.get('file_path'), str):
                        # Keep only an in-memory digest; different pages aren't repeats.
                        key = json.dumps([inp['file_path'], inp.get('offset'), inp.get('limit')], sort_keys=True)
                        reads[hashlib.sha256(key.encode('utf-8')).hexdigest()] += 1
        if limited:
            break
    for key in METRICS:
        values = [usage[key] for usage in messages.values() if key in usage]
        result['tokens'][key] = sum(values) if values else None
        result['missingUsageFields'][key] = len(messages) - len(values)
    result.update(status='partial' if limited or result['skippedRecords'] or result['usageRecordsWithoutId'] or
                  any(result['missingUsageFields'].values()) else 'observed' if messages else 'unavailable',
                  uniqueUsageMessages=sum(bool(usage) for usage in messages.values()), toolCalls=dict(Counter(calls.values())),
                  sameRangeReads=sum(max(0, count - 1) for count in reads.values()), limited=limited)
    groups = {}
    for mid, usage in messages.items():
        model = models.get(mid, 'unavailable')
        group = groups.setdefault(model, {'model': model, 'messages': 0, 'tokens': {key: None for key in METRICS}})
        group['messages'] += 1
        for key, value in usage.items():
            group['tokens'][key] = (group['tokens'][key] or 0) + value
    result['byModel'] = list(groups.values())
    result['observedToolErrors'] = len(failures)
    result['retryCount'] = None  # Repeated calls alone do not establish a retry.
    if times:
        result['observedSpanMs'] = round((max(times) - min(times)) * 1000)
    return result


def inspect_office_timing(path: Path) -> dict:
    from .routing_diagnostics import read_object, mapping
    from .office_progress import LABELS
    data = read_object(path)
    progress = mapping(mapping(data.get('diagnostics')).get('progress'))
    timings = mapping(progress.get('stageMs'))
    stages = {name: value for name, value in timings.items()
              if name in {*LABELS, 'bootstrap'} and _count(value) is not None}
    return {'status': 'observed' if stages else 'unavailable', 'stageMs': stages,
            'nativeApprovalWaitMs': None,
            'notice': '선택한 Office 결과에 기록된 실행 시간입니다. 현재 문서 읽기는 Claude 대화에서 승인받으며 사용자 응답 대기는 이 결과에 포함되지 않습니다. 이전 버전 결과의 확인 창 준비·응답 대기는 별도로 표시합니다.'}
