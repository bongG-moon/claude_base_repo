"""On-demand, bounded local observations; never initialize or alter user state.

Only an exact native project transcript directory and the selected state root's
immediate sessions directory are inspected. Exported values are counts, fixed
enums, UTC times and opaque keys, never conversation content or source paths.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import re
import stat

from .usage_diagnostics import METRICS, TOOLS, _count

MAX_BYTES = 32 * 1024 * 1024
MAX_LINE = 1024 * 1024
MAX_STATE_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 50_000
MAX_CANDIDATES = 200
MAX_LOGS = 100
MAX_STATES = 100
LOAD_STATUSES = frozenset({
    'not-observed', 'loaded', 'tool-failed', 'body-provided', 'catalog-unavailable',
    'read-path-unrecognized', 'skill-path-unmatched', 'response-unrecognized',
    'name-ambiguous', 'skill-name-unmatched', 'choice-unresolved',
    'body-unavailable-or-explicit-only', 'partial-read',
    'read-response-unrecognized', 'native-skill-outside-catalog',
})
CONSTRAINTS = (
    '현재 프로젝트와 연결된 기본 대화 기록만 읽습니다. 하위 에이전트 기록과 다른 프로젝트는 포함하지 않습니다.',
    '기록의 실제 시각이 조회 기간 안에 있는 항목만 집계합니다. 시각이 없거나 확인되지 않는 항목은 제외합니다.',
    '상태와 Hook 수치는 최근에 수정된 파일의 최신 스냅샷입니다. 수정 시각은 실행 시각이 아니며 기간 전체의 이력이 아닙니다.',
    '관찰 구간에는 사용자 대기와 도구 실행이 포함됩니다. 모델 응답 시간이나 업무 절감 시간으로 해석하지 않습니다.',
    '질문 대기는 질문 호출과 결과가 모두 기간 안에서 연결된 구간만 포함하며 전체 승인 대기 시간을 뜻하지 않습니다.',
    '동일 입력의 실패 후 호출, 같은 질문과 같은 범위 읽기는 재검토 후보입니다. 불필요한 재시도나 낭비로 단정하지 않습니다.',
    '토큰은 메시지별 기록의 최대값을 중복 제거해 합산합니다. 누락 필드는 미확인이며 비용과 숨은 재시도는 추정하지 않습니다.',
    '원문, 질문, 경로, 명령, 본문, 오류 메시지와 세션 식별자는 내보내지 않습니다. 파일 수와 읽기 용량 제한으로 일부 기록이 빠질 수 있습니다.',
)
WARNINGS = {
    'missing': '선택한 위치에 읽을 수 있는 기록이 없습니다.',
    'read': '일부 파일을 안전하게 읽지 못해 제외했습니다.',
    'limit': '파일 수, 줄 크기, 기록 수 또는 읽기 용량 제한에 도달해 일부 기록을 제외했습니다.',
    'malformed': '형식을 확인할 수 없는 기록을 제외했습니다.',
    'time': '실제 기록 시각을 확인할 수 없는 항목을 제외했습니다.',
    'project': '현재 프로젝트 연결이 없거나 다른 프로젝트가 섞인 파일을 제외했습니다.',
    'usage': '일부 메시지의 사용량 또는 중복 제거 식별자가 없어 토큰 집계가 부분적입니다.',
    'identity': '일부 요청의 중복 제거 식별자가 없어 여러 파일 사이의 중복 여부를 확인하지 못했습니다.',
    'changed': '읽는 동안 변경된 파일은 일관된 스냅샷을 확인할 수 없어 제외했습니다.',
    'no-data': '현재 프로젝트의 조회 기간에 해당하는 대화 관찰 자료를 확인하지 못했습니다. 사용량이 없거나 성공했다는 뜻은 아닙니다.',
}


def _warn(coverage, kind):
    message = WARNINGS[kind]
    if message not in coverage['warnings']:
        coverage['warnings'].append(message)


def _limited(coverage):
    coverage['truncated'] = True
    _warn(coverage, 'limit')


def _time(value):
    if not isinstance(value, str) or not 0 < len(value) < 50:
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def _iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec='milliseconds')


def _identity(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or '\x00' in value:
        return None
    path = Path(value)
    if not path.is_absolute():
        return None
    # Lexical comparison does not follow a recorded path into another project.
    return os.path.normcase(os.path.abspath(value))


def _key(path):
    return hashlib.sha256(os.fsencode(os.path.normcase(str(path.absolute())))).hexdigest()[:12]


def _digest(value):
    try:
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                         separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError, RecursionError):
        return None


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _human_request(record):
    if record.get('type') != 'user' or record.get('isMeta') is True or record.get('isCompactSummary') is True:
        return False
    content = _mapping(record.get('message')).get('content')
    if isinstance(content, str):
        return bool(content.strip())
    blocks = content if isinstance(content, list) else []
    return not any(isinstance(block, dict) and block.get('type') == 'tool_result' for block in blocks) and any(
        isinstance(block, dict) and block.get('type') in ('text', 'image', 'document') for block in blocks)


@contextmanager
def _open_checked(path):
    """Reject reparse paths and compare opened file identity before consuming it."""
    from .skill_registry import _no_reparse
    path = path.absolute()
    _no_reparse(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('unsafe source')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        _no_reparse(path)
        current = path.stat()
        if (not stat.S_ISREG(opened.st_mode) or
                (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or
                (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)):
            raise ValueError('changed source')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            yield stream, opened
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unchanged(path, stream, before):
    from .skill_registry import _no_reparse
    _no_reparse(path)
    after, current = os.fstat(stream.fileno()), path.stat()
    fields = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    return fields(before) == fields(after) == fields(current)


def _candidates(folder, suffix, coverage):
    """Bound directory enumeration itself, including nonmatching entries."""
    from .skill_registry import _no_reparse
    candidates = []
    try:
        _no_reparse(folder)
        with os.scandir(folder) as entries:
            for entry in entries:
                if coverage['candidateEntries'] >= MAX_CANDIDATES:
                    _limited(coverage)
                    break
                coverage['candidateEntries'] += 1
                if not entry.name.casefold().endswith(suffix):
                    continue
                info = entry.stat(follow_symlinks=False)
                if (not stat.S_ISREG(info.st_mode) or
                        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
                    coverage['filesSkipped'] += 1
                    _warn(coverage, 'read')
                    continue
                candidates.append((info.st_mtime_ns, Path(entry.path)))
    except FileNotFoundError:
        _warn(coverage, 'missing')
    except (OSError, ValueError):
        _warn(coverage, 'read')
    return [path for _, path in sorted(candidates, key=lambda item: (-item[0], str(item[1])))]


class _Transcript:
    def __init__(self, path):
        self.row = {'key': _key(path), 'requests': 0, 'toolCalls': 0, 'toolErrors': 0,
                    'toolCounts': {}, 'repeatedFailedCalls': 0, 'questionCalls': 0,
                    'repeatedQuestions': 0, 'sameRangeReads': 0,
                    'tokens': {key: None for key in METRICS}, 'usageMessages': 0,
                    'usageMissing': True, 'observedSpanMs': None, 'questionWaitMs': None,
                    'questionPairs': 0}
        self.calls, self.messages, self.request_ids = {}, {}, set()
        self.failed, self.questions, self.reads, self.errors, self.answers = {}, set(), set(), set(), set()
        self.message_times, self.request_times, self.result_times, self.waits = {}, {}, {}, {}
        self.anonymous_request_times = []
        self.anonymous_message_times = []
        self.tool_counts = Counter()
        self.first = self.last = None
        self.request = 0
        self.without_usage_id = 0

    def boundary(self):
        self.request += 1
        self.failed.clear()
        self.questions.clear()
        self.reads.clear()

    def span(self, timestamp):
        self.first = min(self.first, timestamp) if self.first else timestamp
        self.last = max(self.last, timestamp) if self.last else timestamp

    def observe(self, record, timestamp):
        if record.get('type') not in ('user', 'assistant') or not isinstance(record.get('message'), dict):
            return
        self.span(timestamp)
        message = _mapping(record.get('message'))
        content = message.get('content')
        blocks = content if isinstance(content, list) else []
        results = [block for block in blocks if isinstance(block, dict) and block.get('type') == 'tool_result']
        if record.get('type') == 'user':
            if _human_request(record):
                rid = record.get('uuid')
                if not isinstance(rid, str) or not rid or rid not in self.request_ids:
                    if isinstance(rid, str) and 0 < len(rid) <= 200:
                        self.request_ids.add(rid)
                        self.request_times[rid] = timestamp
                    else:
                        self.anonymous_request_times.append(timestamp)
                    self.boundary()
                    self.row['requests'] += 1
            for block in results:
                call_id = block.get('tool_use_id')
                if not isinstance(call_id, str):
                    continue
                call = self.calls.get(call_id)
                if not call:
                    continue
                self.result_times[call_id] = max(self.result_times.get(call_id, timestamp), timestamp)
                if block.get('is_error') is True and call_id not in self.errors and timestamp >= call['time']:
                    self.errors.add(call_id)
                    self.row['toolErrors'] += 1
                    if call['request'] == self.request and self.request and call['fingerprint']:
                        self.failed[call['fingerprint']] = timestamp
                elif (block.get('is_error') is not True and call['request'] == self.request
                        and call['fingerprint'] and timestamp >= call['time']):
                    self.failed.pop(call['fingerprint'], None)
                if (call['name'] == 'AskUserQuestion' and call_id not in self.answers
                        and block.get('is_error') is not True and call['request'] == self.request
                        and timestamp >= call['time']):
                    self.answers.add(call_id)
                    self.row['questionPairs'] += 1
                    self.waits[call_id] = int((timestamp - call['time']).total_seconds() * 1000)
                    self.row['questionWaitMs'] = (self.row['questionWaitMs'] or 0) + self.waits[call_id]
            return
        if record.get('type') != 'assistant' or not message:
            return
        mid = message.get('id')
        if isinstance(mid, str) and 0 < len(mid) <= 200:
            usage = self.messages.setdefault(mid, {})
            times = self.message_times.setdefault(mid, [timestamp, timestamp])
            times[0], times[1] = min(times[0], timestamp), max(times[1], timestamp)
            for metric in METRICS:
                value = _count(_mapping(message.get('usage')).get(metric))
                if value is not None:
                    usage[metric] = max(usage.get(metric, 0), value)
        else:
            self.without_usage_id += 1
            self.anonymous_message_times.append(timestamp)
        for block in blocks:
            if not isinstance(block, dict) or block.get('type') != 'tool_use':
                continue
            call_id = block.get('id')
            if not isinstance(call_id, str) or not 0 < len(call_id) <= 200 or call_id in self.calls:
                continue
            raw_name = block.get('name')
            name = raw_name if isinstance(raw_name, str) and raw_name in TOOLS else 'Other'
            inp = block.get('input')
            fingerprint = _digest([raw_name, inp]) if isinstance(inp, dict) else None
            call = {'name': name, 'fingerprint': fingerprint, 'request': self.request, 'time': timestamp,
                    'message': mid if isinstance(mid, str) and 0 < len(mid) <= 200 else None,
                    'repeatFailed': 0, 'repeatQuestion': 0, 'sameRead': 0}
            self.calls[call_id] = call
            self.tool_counts[name] += 1
            if self.request and fingerprint and fingerprint in self.failed and timestamp >= self.failed[fingerprint]:
                self.row['repeatedFailedCalls'] += 1
                call['repeatFailed'] = 1
            if name == 'AskUserQuestion':
                self.row['questionCalls'] += 1
                if self.request and fingerprint:
                    call['repeatQuestion'] = int(fingerprint in self.questions)
                    self.row['repeatedQuestions'] += call['repeatQuestion']
                    self.questions.add(fingerprint)
            if name == 'Read' and self.request and isinstance(inp, dict) and isinstance(inp.get('file_path'), str):
                read_key = _digest([inp['file_path'], inp.get('offset'), inp.get('limit'), inp.get('pages')])
                if read_key:
                    call['sameRead'] = int(read_key in self.reads)
                    self.row['sameRangeReads'] += call['sameRead']
                    self.reads.add(read_key)

    def finish(self):
        self.row['toolCounts'] = dict(sorted(self.tool_counts.items()))
        self.row['toolCalls'] = sum(self.tool_counts.values())
        self.row['usageMessages'] = len(self.messages)
        self.row['usageMissing'] = bool(self.without_usage_id or not self.messages or any(
            metric not in usage for usage in self.messages.values() for metric in METRICS))
        for metric in METRICS:
            values = [usage[metric] for usage in self.messages.values() if metric in usage]
            self.row['tokens'][metric] = sum(values) if values and len(values) == len(self.messages) and not self.without_usage_id else None
        if self.first is not None and self.last != self.first:
            self.row['observedSpanMs'] = int((self.last - self.first).total_seconds() * 1000)
        return self.row


def _read_transcript(path, project_key, since, until, coverage):
    observed, bound, mismatch, complete = _Transcript(path), False, False, True
    try:
        with _open_checked(path) as (stream, info):
            if info.st_size > MAX_BYTES - coverage['bytesRead']:
                _limited(coverage)
                return None
            coverage['filesRead'] += 1
            remaining = info.st_size
            while remaining:
                if coverage['recordsRead'] >= MAX_RECORDS or coverage['bytesRead'] >= MAX_BYTES:
                    _limited(coverage)
                    complete = False
                    break
                line = stream.readline(min(MAX_LINE + 1, remaining, MAX_BYTES - coverage['bytesRead']))
                if not line:
                    complete = False
                    _warn(coverage, 'changed')
                    break
                remaining -= len(line)
                coverage['bytesRead'] += len(line)
                coverage['recordsRead'] += 1
                if len(line) > MAX_LINE:
                    _limited(coverage)
                    complete = False
                    break
                try:
                    record = json.loads(line.decode('utf-8-sig'))
                    if not isinstance(record, dict):
                        raise ValueError('record shape')
                except (UnicodeError, ValueError, RecursionError):
                    coverage['skippedRecords'] += 1
                    _warn(coverage, 'malformed')
                    # An unreadable record may contain a request boundary.
                    observed.boundary()
                    continue
                if 'cwd' in record:
                    same = _identity(record.get('cwd')) == project_key
                    bound = bound or same
                    mismatch = mismatch or not same
                if record.get('isSidechain') is True:
                    mismatch = True
                timestamp = _time(record.get('timestamp'))
                if timestamp is None:
                    coverage['skippedRecords'] += 1
                    coverage['unknownTimeRecords'] += 1
                    _warn(coverage, 'time')
                    if _human_request(record):
                        observed.boundary()
                elif not since <= timestamp <= until:
                    coverage['skippedRecords'] += 1
                    coverage['outsideWindowRecords'] += 1
                    if _human_request(record):
                        observed.boundary()
                else:
                    observed.observe(record, timestamp)
            if not _unchanged(path, stream, info):
                _warn(coverage, 'changed')
                return None
    except (OSError, ValueError, OverflowError):
        _warn(coverage, 'read')
        return None
    if not bound or mismatch:
        coverage['projectExcludedFiles'] += 1
        _warn(coverage, 'project')
        return None
    if not complete or observed.first is None:
        return None
    return observed


def _merge_transcript(observed, shared, coverage):
    """Commit IDs only after a whole file passed bounds and project checks.

    Forks may contain the same history. Each logical message, request and call
    belongs to its first accepted source; later cumulative usage updates that
    owner. Local replay still establishes request boundaries for genuinely new
    calls in the fork, without counting its shared prefix a second time.
    """
    observed.first = observed.last = None
    observed.tool_counts.clear()
    for field in ('requests', 'toolErrors', 'repeatedFailedCalls', 'questionCalls',
                  'repeatedQuestions', 'sameRangeReads', 'questionPairs'):
        observed.row[field] = 0
    observed.row['questionWaitMs'] = None
    fresh = bool(observed.without_usage_id or observed.anonymous_request_times)
    for timestamp in observed.anonymous_message_times:
        observed.span(timestamp)
    for timestamp in observed.anonymous_request_times:
        observed.row['requests'] += 1
        observed.span(timestamp)
        _warn(coverage, 'identity')
    for rid, timestamp in observed.request_times.items():
        if rid not in shared['requests']:
            shared['requests'].add(rid)
            observed.row['requests'] += 1
            observed.span(timestamp)
            fresh = True
    for mid, usage in list(observed.messages.items()):
        if mid in shared['messages']:
            owner = shared['messages'][mid]
            for metric, value in usage.items():
                owner.messages[mid][metric] = max(owner.messages[mid].get(metric, 0), value)
            del observed.messages[mid]
        else:
            owner = observed
            shared['messages'][mid] = owner
            fresh = True
        for timestamp in observed.message_times[mid]:
            owner.span(timestamp)
    for call_id, call in observed.calls.items():
        if call_id in shared['calls']:
            continue
        owner = shared['messages'].get(call['message'], observed)
        shared['calls'][call_id] = owner
        fresh = fresh or owner is observed
        owner.span(call['time'])
        owner.tool_counts[call['name']] += 1
        owner.row['repeatedFailedCalls'] += call['repeatFailed']
        owner.row['repeatedQuestions'] += call['repeatQuestion']
        owner.row['sameRangeReads'] += call['sameRead']
        owner.row['questionCalls'] += int(call['name'] == 'AskUserQuestion')
    for call_id, timestamp in observed.result_times.items():
        if call_id in shared['calls']:
            shared['calls'][call_id].span(timestamp)
    for call_id in observed.errors:
        if call_id not in shared['errors'] and call_id in shared['calls']:
            shared['errors'].add(call_id)
            owner = shared['calls'][call_id]
            owner.row['toolErrors'] += 1
            owner.span(observed.result_times[call_id])
    for call_id, elapsed in observed.waits.items():
        if call_id not in shared['answers'] and call_id in shared['calls']:
            shared['answers'].add(call_id)
            owner = shared['calls'][call_id]
            owner.row['questionPairs'] += 1
            owner.row['questionWaitMs'] = (owner.row['questionWaitMs'] or 0) + elapsed
            owner.span(observed.result_times[call_id])
    if not fresh:
        coverage['duplicateTranscriptFiles'] += 1
    return fresh


def _read_state(path, project_key, since, until, coverage):
    try:
        with _open_checked(path) as (stream, info):
            updated = datetime.fromtimestamp(info.st_mtime, timezone.utc)
            if not since <= updated <= until:
                coverage['outsideWindowStates'] += 1
                return None
            if info.st_size > min(MAX_STATE_BYTES, MAX_BYTES - coverage['bytesRead']) or coverage['recordsRead'] >= MAX_RECORDS:
                _limited(coverage)
                return None
            body = stream.read(info.st_size)
            coverage['filesRead'] += 1
            coverage['bytesRead'] += len(body)
            coverage['recordsRead'] += 1
            if len(body) != info.st_size or not _unchanged(path, stream, info):
                _warn(coverage, 'changed')
                return None
        data = json.loads(body.decode('utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError('state shape')
    except (OSError, ValueError, UnicodeError, RecursionError, OverflowError):
        coverage['skippedRecords'] += 1
        _warn(coverage, 'read')
        return None
    workflow = _mapping(data.get('skillWorkflow'))
    bindings = [data[key] for key in ('cwd', 'projectRoot') if key in data]
    if 'project' in workflow:
        bindings.append(workflow['project'])
    if not bindings or any(_identity(value) != project_key for value in bindings):
        coverage['projectExcludedFiles'] += 1
        _warn(coverage, 'project')
        return None
    verification = _mapping(data.get('verification')).get('status')
    observation = _mapping(workflow.get('loadObservation'))
    load = observation.get('status') if data.get('turnId') and observation.get('turn') == data.get('turnId') else None
    hooks = []
    for event in ('SessionStart', 'UserPromptSubmit'):
        source = _mapping(_mapping(data.get('hookDiagnostics')).get(event))
        if source:
            status = source.get('status')
            hooks.append({'event': event, 'status': status if isinstance(status, str) and status in {'started', 'output-produced', 'failed'} else 'not-observed',
                          'elapsedMs': _count(source.get('elapsedMs')), 'contextChars': _count(source.get('contextChars'))})
    return {'key': _key(path), 'taskToolCount': _count(data.get('taskToolCount')),
            'taskFailureCount': _count(data.get('taskFailureCount')),
            'verification': verification if isinstance(verification, str) and verification in {'pass', 'fail', 'partial', 'unavailable', 'not_applicable'} else 'unknown',
            'loadStatus': load if isinstance(load, str) and load in LOAD_STATUSES else 'unknown',
            'hooks': hooks, 'updatedAt': _iso(updated)}


def collect(project: Path, state_root: Path | None, claude_root: Path | None, *, days=7, logs=(), now=None) -> dict:
    """Read selected local sources once; no writes, network or runtime startup."""
    if type(days) is not int or not 1 <= days <= 30:
        raise ValueError('조회 기간은 1일부터 30일까지 지정해야 합니다.')
    until = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(until, datetime) or until.tzinfo is None:
        raise ValueError('조회 기준 시각에는 시간대가 있어야 합니다.')
    until = until.astimezone(timezone.utc)
    since = until - timedelta(days=days)
    project = Path(project).absolute()
    project_key = _identity(str(project))
    coverage = {'status': 'no-data', 'filesRead': 0, 'recordsRead': 0, 'skippedRecords': 0,
                'bytesRead': 0, 'filesSkipped': 0, 'candidateEntries': 0, 'projectExcludedFiles': 0,
                'outsideWindowRecords': 0, 'unknownTimeRecords': 0, 'outsideWindowStates': 0,
                'transcriptFiles': 0, 'stateFiles': 0, 'truncated': False, 'warnings': [],
                'duplicateTranscriptFiles': 0,
                'stateSnapshotBasis': 'file-mtime-latest-state'}
    report = {'window': {'since': _iso(since), 'until': _iso(until), 'days': days},
              'coverage': coverage, 'transcripts': [], 'states': [], 'constraints': list(CONSTRAINTS)}
    from .skill_registry import _no_reparse
    try:
        _no_reparse(project)
    except (OSError, ValueError):
        _warn(coverage, 'read')
        _warn(coverage, 'no-data')
        return report
    explicit = list(islice(iter(logs), MAX_LOGS + 1))
    if explicit:
        candidates = [Path(path).absolute() for path in explicit[:min(MAX_LOGS, MAX_CANDIDATES)]]
        coverage['candidateEntries'] += len(candidates)
        if len(explicit) > min(MAX_LOGS, MAX_CANDIDATES):
            _limited(coverage)
    else:
        config = Path(claude_root) if claude_root is not None else Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')
        encoded = re.sub(r'[^A-Za-z0-9]', '-', str(project))
        candidates = _candidates(config / 'projects' / encoded, '.jsonl', coverage)
        if len(candidates) > MAX_LOGS:
            _limited(coverage)
        candidates = candidates[:MAX_LOGS]
    seen = set()
    transcripts = []
    shared = {'requests': set(), 'messages': {}, 'calls': {}, 'errors': set(), 'answers': set()}
    for path in candidates:
        identity = _identity(str(path.absolute()))
        if identity in seen:
            continue
        seen.add(identity)
        if path.suffix.casefold() != '.jsonl':
            coverage['filesSkipped'] += 1
            _warn(coverage, 'read')
            continue
        observed = _read_transcript(path, project_key, since, until, coverage)
        if observed is not None:
            coverage['transcriptFiles'] += 1
            if _merge_transcript(observed, shared, coverage):
                transcripts.append(observed)
        else:
            coverage['filesSkipped'] += 1
    report['transcripts'] = [observed.finish() for observed in transcripts]
    if any(row['usageMissing'] for row in report['transcripts']):
        _warn(coverage, 'usage')
    if state_root is not None:
        state_candidates = _candidates(Path(state_root) / 'sessions', '.json', coverage)
        if len(state_candidates) > MAX_STATES:
            _limited(coverage)
        for path in state_candidates[:MAX_STATES]:
            row = _read_state(path, project_key, since, until, coverage)
            if row is not None:
                report['states'].append(row)
                coverage['stateFiles'] += 1
            else:
                coverage['filesSkipped'] += 1
    if report['transcripts'] or report['states']:
        coverage['status'] = 'partial' if coverage['warnings'] or not report['transcripts'] else 'observed'
    if not report['transcripts']:
        _warn(coverage, 'no-data')
    return report
