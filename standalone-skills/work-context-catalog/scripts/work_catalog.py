"""On-demand bounded inventory of approved work-context roots; stdlib only."""
from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import stat
import sys

LIMITS = {"files": 1500, "entries": 10000, "depth": 8, "total_bytes": 16 * 1024 * 1024,
          "file_bytes": 512 * 1024, "session_files": 20000, "session_entries": 200000,
          "session_bytes": 2 * 1024 * 1024 * 1024, "line_bytes": 1024 * 1024,
          "session_events": 200000, "catalog_bytes": 256 * 1024 * 1024}
SKIP_DIRS = {'.git', '.svn', 'node_modules', '__pycache__', '.venv', 'venv', 'build', 'dist',
             '.cache', 'cache', 'tool-results', 'logs', 'screenshots', 'images'}
TOPICS = {
    '자료 분석·정리': ('엑셀', 'excel', 'csv', '데이터', '집계', '전처리', '분석', 'query', 'sql'),
    '문서·보고': ('보고서', '리포트', 'ppt', 'presentation', 'slides', '문서', '발표', '요약'),
    '웹·업무 자동화': ('자동화', 'automation', 'browser', 'chrome', '크롬', '브라우저', '웹'),
    '개발·도구 제작': ('개발', '코드', 'python', 'typescript', 'mcp', '도구', '테스트', 'debug'),
    '지식·업무 기준': ('지식', '기억', 'knowledge', 'memory', '규정', '업무 방식', '용어'),
    '소통·일정': ('메일', 'outlook', 'email', '일정', 'calendar', '회의'),
}


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def clean(value, limit=180):
    text = str(value or '')
    text = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|$)', '[개인키 가림]', text)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', '[인증정보 가림]', text)
    text = re.sub(r'(?i)([\"\']?(?:api[_ -]?key|token|password|secret|authorization)[\"\']?\s*[=:]\s*)([\"\'])(.*?)\2', r'\1"[인증정보 가림]"', text)
    text = re.sub(r'(?i)\b(?:sk-ant-|sk-|ghp_|github_pat_|glpat-)[A-Za-z0-9_\-]{8,}', '[인증정보 가림]', text)
    text = re.sub(r'(?i)\b(?:bearer\s+|(?:api[_ -]?key|token|password|secret|authorization)\s*[=:]\s*)[^\s,;]+', '[인증정보 가림]', text)
    text = re.sub(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[메일 가림]', text)
    text = re.sub(r'(?i)https?://[^\s<>"\)]+', '[주소 가림]', text)
    text = re.sub(r'(?i)(?:[A-Z]:[\\/]|/(?:home|Users)/)[^\r\n<>"\t]+', '[경로 가림]', text)
    text = re.sub(r'[A-Za-z0-9+/]{100,}={0,2}', '[긴 인코딩 값 가림]', text)
    return ' '.join(text.replace('\x00', '').split())[:limit]


def topics(text):
    sample = text[:32000].lower()
    return [name for name, terms in TOPICS.items() if any(term in sample for term in terms)] or ['미분류']


def no_links(path):
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('연결 경로 제외')


def location(alias, path, root):
    return {"root": alias, "path": clean(path.relative_to(root).as_posix(), 360)}


def imported_origin(value):
    root, path = str(value.get('root', '')), str(value.get('path', ''))
    # Imported summaries are untrusted. Never turn absolute/traversal paths into links.
    if not re.fullmatch(r'[A-Za-z0-9_/-]{1,100}', root) or path.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:', path) or '..' in path.replace('\\', '/').split('/'):
        return '[원본 경로 가림]'
    return clean(root + '/' + path, 360)


def md_kind(path):
    parts = {p.lower() for p in path.parts}
    name = path.name.lower()
    if name == 'skill.md':
        return 'skill'
    if name in ('claude.md', 'agents.md'):
        return 'instruction'
    if parts & {'memory', 'memories', 'learning'} or name.startswith('memory'):
        return 'memory'
    if parts & {'knowledge', 'knowledge-base', 'knowledge_base'}:
        return 'knowledge'
    return 'reference'


def md_header(text, fallback):
    lines = text[:16000].splitlines()
    metadata = {}
    body = lines
    # Only bounded frontmatter is metadata. A body line saying name/title is data.
    if lines and lines[0].strip() == '---':
        closing = next((i for i, line in enumerate(lines[1:81], 1) if line.strip() == '---'), None)
        if closing is not None:
            frontmatter, body = lines[1:closing], lines[closing + 1:]
            for index, line in enumerate(frontmatter):
                match = re.match(r'^(name|title|description|summary)\s*:\s*(.*)$', line)
                if not match:
                    continue
                key, value = match.groups()
                if value in ('|', '>', '|-', '>-'):
                    continuation = []
                    for next_line in frontmatter[index + 1:]:
                        if next_line and not next_line[0].isspace():
                            break
                        continuation.append(next_line.strip())
                    value = ' '.join(continuation)
                metadata[key] = value.strip().strip('\"\'')
    title = metadata.get('name') or metadata.get('title')
    title = title or next((line.lstrip('# ').strip() for line in body if line.startswith('# ')), fallback)
    description = metadata.get('description') or metadata.get('summary', '')
    return clean(title, 100), clean(description, 180)


class Collector:
    def __init__(self, limits=None, include_sessions=True, include_intents=False):
        self.limits = dict(LIMITS, **(limits or {}))
        self.include_sessions = include_sessions
        self.include_intents = include_intents
        self.roots, self.assets, self.sessions = [], {}, {}
        self.warnings, self.read_bytes, self.file_count, self.entries = Counter(), 0, 0, 0
        self.seen_roots = set()
        self.project_roots = []
        self.session_stats = Counter()
        self.session_skips = Counter()
        self.session_flags = {}
        self.session_bytes = 0
        self.session_event_count = 0
        self.seen_session_files = set()
        self.auto_discovery = False
        self.import_bytes = 0

    def approved_project(self, cwd):
        if not isinstance(cwd, str) or not os.path.isabs(cwd):
            return None
        candidate = os.path.normcase(os.path.normpath(cwd))
        for root, alias in sorted(self.project_roots, key=lambda pair: len(pair[0]), reverse=True):
            try:
                if os.path.commonpath([candidate, root]) == root:
                    return alias
            except ValueError:
                continue
        return None

    def read(self, path, limit, prefix=False):
        remaining = self.limits['total_bytes'] - self.read_bytes
        if remaining <= 0:
            self.warnings['읽기 총량 상한'] += 1
            return None
        no_links(path)
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError('regular file required')
        cap = min(limit, remaining)
        with path.open('rb') as stream:
            payload = stream.read(cap + 1)
        self.read_bytes += min(len(payload), cap)
        if len(payload) > cap:
            self.warnings['파일 크기 또는 읽기 총량 상한'] += 1
            return payload[:cap].rsplit(b'\n', 1)[0] if prefix and b'\n' in payload[:cap] else None
        return payload

    def add_root(self, raw, scope, sessions_only=False, provider=None):
        candidate = Path(raw).expanduser().absolute()
        try:
            no_links(candidate)
            root = candidate.resolve(strict=True)
            if not root.is_dir():
                raise ValueError('폴더 아님')
        except (OSError, ValueError):
            self.warnings['읽을 수 없거나 연결된 시작 폴더'] += 1
            return
        identity = os.path.normcase(str(root))
        if identity in self.seen_roots:
            self.warnings['중복 시작 폴더 제외'] += 1
            return
        self.seen_roots.add(identity)
        alias = f'{scope}-{len(self.roots) + 1:02d}'
        root_info = {'id': alias, 'scope': scope, 'environment': provider or '미확인',
                     'sessions_only': sessions_only}
        self.roots.append(root_info)
        if scope == 'project':
            self.project_roots.append((identity, alias))
        environment = set()
        pending = [(root, 0)]
        while pending:
            folder, depth = pending.pop()
            try:
                no_links(folder)
                with os.scandir(folder) as iterator:
                    for entry in iterator:
                        self.entries += 1
                        entry_cap = self.limits['session_entries'] if self.include_sessions else self.limits['entries']
                        if self.entries > entry_cap:
                            self.warnings['디렉터리 항목 상한'] += 1
                            return
                        path = Path(entry.path)
                        try:
                            no_links(path)
                            if entry.name.lower() in SKIP_DIRS or re.search(r'(?i)(credential|secret|token|password)|^\.env', entry.name):
                                self.warnings['기본 제외 파일·폴더'] += 1
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if depth < self.limits['depth']:
                                    pending.append((path, depth + 1))
                                else:
                                    self.warnings['탐색 깊이 상한'] += 1
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                self.warnings['일반 파일 아닌 항목 제외'] += 1
                                continue
                            suffix = path.suffix.lower()
                            if sessions_only and suffix != '.jsonl':
                                continue
                            managed_json = suffix == '.json' and (scope == 'state' or set(p.lower() for p in path.relative_to(root).parts) & {'memory', 'memories', 'knowledge', 'learning'})
                            if suffix not in ('.md', '.jsonl') and not managed_json and entry.name.lower() not in ('settings.json', 'settings.local.json', '.mcp.json', 'config.toml'):
                                continue
                            if suffix == '.jsonl' and not self.include_sessions:
                                self.warnings['세션 미수집 (--no-sessions)'] += 1
                                continue
                            origin = location(alias, path, root)
                            if suffix == '.jsonl':
                                self.read_session(path, origin)
                                continue
                            if self.entries > self.limits['entries']:
                                self.warnings['자산 탐색 항목 상한 · 세션 탐색은 계속'] += 1
                                continue
                            if self.file_count >= self.limits['files']:
                                self.warnings['후보 파일 상한'] += 1
                                continue
                            self.file_count += 1
                            origin = location(alias, path, root)
                            if '.claude' in path.parts or entry.name.lower() == 'claude.md':
                                environment.add('Claude')
                            if '.codex' in path.parts or entry.name.lower() == 'agents.md':
                                environment.add('Codex/AGENTS')
                            if suffix == '.md':
                                payload = self.read(path, self.limits['file_bytes'])
                                if payload is not None:
                                    text = payload.decode('utf-8-sig')
                                    title, description = md_header(text, path.stem)
                                    key = digest(md_kind(path).encode() + b':' + payload.replace(b'\r\n', b'\n'))
                                    asset = self.assets.setdefault(key, {'id': key, 'kind': md_kind(path), 'title': title,
                                        'description': description, 'topics': topics(title + ' ' + description),
                                        'evidence': 'definition', 'origins': []})
                                    if origin not in asset['origins']:
                                        asset['origins'].append(origin)
                            else:
                                key = digest('configuration:' + identity + ':' + origin['path'])
                                self.assets.setdefault(key, {'id': key, 'kind': 'configuration', 'title': clean(entry.name),
                                    'description': '관리 JSON 존재만 확인. 본문 형식은 미지원·내용 미수집.' if managed_json else '파일 존재만 확인. 설정·비밀값은 읽지 않음.', 'topics': ['미분류'],
                                    'evidence': 'definition', 'origins': []})['origins'].append(origin)
                                if managed_json:
                                    self.warnings['관리 JSON 내용 미수집'] += 1
                        except (OSError, UnicodeError, ValueError, RecursionError):
                            self.warnings['접근 거절·연결 경로·텍스트 형식 오류'] += 1
            except OSError:
                self.warnings['폴더 읽기 실패'] += 1
        root_info['environment'] = provider or ', '.join(sorted(environment)) or ('명시한 프로필' if scope == 'profile' else '일반 파일 기반')

    def read_session(self, path, origin):
        identity = os.path.normcase(str(path.absolute()))
        self.session_stats['files_found'] += 1
        if identity in self.seen_session_files:
            self.session_skips['same_file_already_scanned'] += 1
            return
        if self.session_stats['files_scanned'] >= self.limits['session_files']:
            self.warnings['세션 파일 상한'] += 1
            self.session_skips['file_limit'] += 1
            return
        if self.session_bytes >= self.limits['session_bytes']:
            self.warnings['세션 읽기 총량 상한'] += 1
            self.session_skips['byte_limit'] += 1
            return
        no_links(path)
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError('regular session file required')
        self.seen_session_files.add(identity)
        self.session_stats['files_scanned'] += 1
        session_id, events, intents, labels, tools = None, set(), [], set(), defaultdict(set)
        session_ids = set()
        projects = {origin['root']} if origin['root'].startswith('project-') else set()
        unmatched_cwd = False
        seen_counts = Counter()
        flags = {'meaningful': False, 'ambiguous': False, 'greeting': False, 'context': False}
        file_hash = hashlib.sha256()
        partial = [False]

        def lines(stream):
            # Bounded memory, but not a prefix sample: drain an oversized JSONL row
            # and resume at its next newline so late work is still examined.
            while True:
                remaining = self.limits['session_bytes'] - self.session_bytes
                if remaining <= 0:
                    if stream.tell() < path.stat().st_size:
                        self.warnings['세션 읽기 총량 상한'] += 1
                        partial[0] = True
                    return
                raw = stream.readline(min(self.limits['line_bytes'] + 1, remaining))
                if not raw:
                    return
                self.session_bytes += len(raw)
                file_hash.update(raw)
                self.session_stats['lines_scanned'] += 1
                oversized = len(raw) > self.limits['line_bytes']
                unterminated = not raw.endswith(b'\n') and stream.tell() < path.stat().st_size
                if oversized or unterminated:
                    while not raw.endswith(b'\n') and stream.tell() < path.stat().st_size:
                        remaining = self.limits['session_bytes'] - self.session_bytes
                        if remaining <= 0:
                            break
                        raw = stream.readline(min(65536, remaining))
                        self.session_bytes += len(raw)
                        file_hash.update(raw)
                        if not raw:
                            break
                    self.warnings['세션 한 줄 상한 또는 총량 경계'] += 1
                    self.session_stats['oversized_or_partial_lines'] += 1
                    partial[0] = True
                    continue
                yield raw

        with path.open('rb') as stream:
          for raw in lines(stream):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
                if not isinstance(row, dict):
                    flags['ambiguous'] = True
                    continue
                if row.get('isSidechain') is True:
                    self.warnings['하위 작업자 세션 이벤트 제외'] += 1
                    continue
                if row.get('isMeta') is True:
                    flags['context'] = True
                    continue
                cwd = row.get('cwd')
                if row.get('type') in ('session_meta', 'turn_context') and isinstance(row.get('payload'), dict):
                    cwd = row['payload'].get('cwd', cwd)
                if cwd:
                    project = self.approved_project(cwd)
                    if project:
                        projects.add(project)
                    else:
                        unmatched_cwd = True
                if row.get('type') == 'session_meta':
                    meta = row.get('payload')
                    if isinstance(meta, dict) and isinstance(meta.get('id'), str):
                        session_id = meta['id']
                        if len(session_ids) < 2:
                            session_ids.add(session_id)
                    continue
                if isinstance(row.get('sessionId'), str):
                    session_id = row['sessionId']
                    if len(session_ids) < 2:
                        session_ids.add(session_id)
                event_type, user_text, tool_names = None, '', []
                user_content = None
                message = row.get('message')
                if row.get('type') == 'user' and isinstance(message, dict):
                    event_type = 'user'
                    user_content = message.get('content')
                    user_text = extract_user_text(user_content)
                elif row.get('type') == 'assistant' and isinstance(message, dict):
                    content = message.get('content')
                    if isinstance(content, list):
                        tool_names = [item['name'] for item in content if isinstance(item, dict)
                                      and item.get('type') == 'tool_use' and isinstance(item.get('name'), str)]
                elif row.get('type') == 'response_item' and isinstance(row.get('payload'), dict):
                    item = row['payload']
                    if item.get('type') == 'message' and item.get('role') == 'user':
                        event_type, user_content = 'user', item.get('content')
                        user_text = extract_user_text(user_content)
                    elif item.get('type') in ('function_call', 'custom_tool_call') and isinstance(item.get('name'), str):
                        tool_names = [item['name']]
                    elif item.get('type') in ('function_call_output', 'custom_tool_call_output'):
                        flags['ambiguous'] = True
                    elif item.get('type') not in ('message', 'function_call_output', 'custom_tool_call_output', 'reasoning'):
                        flags['ambiguous'] = True
                if event_type == 'user':
                    original_text = user_text
                    user_text = remove_context_blocks(user_text)
                    if original_text and not user_text:
                        flags['context'] = True
                        self.warnings['주입된 환경·지침 형식의 user 이벤트 제외'] += 1
                    # An image/attachment/unknown user content is not an empty chat.
                    if isinstance(user_content, list) and any(isinstance(i, dict) and i.get('type') not in ('text', 'input_text') for i in user_content):
                        flags['ambiguous'] = True
                    if user_text:
                        flags['greeting' if pure_greeting(user_text) else 'meaningful'] = True
                        labels.update(topics(user_text))
                        if self.include_intents and len(intents) < 3:
                            excerpt = clean(user_text, 160)
                            if excerpt not in intents:
                                intents.append(excerpt)
                if not user_text and not tool_names:
                    known_types = {'session_meta', 'turn_context', 'response_item', 'event_msg', 'user', 'assistant', 'system', 'summary', 'progress', 'file-history-snapshot', 'queue-operation'}
                    if row.get('type') not in known_types:
                        flags['ambiguous'] = True
                    continue
                if any(name.lower() not in ('toolsearch', 'tool_search') for name in tool_names):
                    flags['meaningful'] = True
                # Hash, do not retain tool args/results or unredacted conversation text.
                signature = digest(json.dumps([row.get('timestamp'), row.get('uuid'), event_type, user_text, tool_names], ensure_ascii=False))
                if self.session_event_count >= self.limits['session_events']:
                    self.warnings['세션 이벤트 보관 상한 · 이후 줄 분류는 계속'] += 1
                    partial[0] = True
                    continue
                seen_counts[signature] += 1
                native_id = row.get('uuid')
                if not native_id and isinstance(row.get('payload'), dict):
                    native_id = row['payload'].get('call_id') or row['payload'].get('id')
                event_id = digest('event:' + native_id) if isinstance(native_id, str) else digest(signature + ':' + str(seen_counts[signature]))
                remaining_events = self.limits['session_events'] - self.session_event_count
                event_cost = int(bool(user_text)) + len(tool_names)
                if event_cost > remaining_events:
                    tool_names = tool_names[:max(0, remaining_events - int(bool(user_text)))]
                    partial[0] = True
                    self.warnings['세션 이벤트 보관 상한 · 이후 줄 분류는 계속'] += 1
                self.session_event_count += min(event_cost, remaining_events)
                if user_text:
                    events.add(event_id)
                for index, name in enumerate(tool_names):
                    name = clean(name, 100)
                    if name not in tools and len(tools) >= 500:
                        self.warnings['세션 도구 종류 상한'] += 1
                        partial[0] = True
                        continue
                    if re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}', name):
                        tools[name].add(digest(event_id + ':' + str(index)))
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self.warnings['세션 JSONL 형식 오류'] += 1
                partial[0] = True
        if len(session_ids) > 1:
            self.warnings['한 파일의 복수 세션 ID · 혼합 기록 제외'] += 1
            self.session_skips['mixed_session_ids'] += 1
            return
        flags['ambiguous'] = flags['ambiguous'] or partial[0]
        if partial[0]:
            self.session_stats['partial_files'] += 1
        if any(name.lower() not in ('toolsearch', 'tool_search') for name in tools):
            flags['meaningful'] = True
        if tools and not flags['greeting'] and not flags['meaningful']:
            flags['ambiguous'] = True
        key = digest('session:' + session_id) if session_id else file_hash.hexdigest()
        previous = self.session_flags.setdefault(key, dict.fromkeys(flags, False))
        for name, value in flags.items():
            previous[name] = previous[name] or value
        record = self.sessions.setdefault(key, {'id': key, 'evidence': 'observed_calls', 'origins': [],
            'user_events': [], 'tool_events': {}, 'topics': [], 'intents': [], 'project_roots': [], 'unmapped_project': False})
        if origin not in record['origins']:
            record['origins'].append(origin)
        record['user_events'] = sorted(set(record['user_events']) | events)
        record['topics'] = sorted(set(record['topics']) | labels)
        record['project_roots'] = sorted(set(record['project_roots']) | projects)
        record['unmapped_project'] = record['unmapped_project'] or unmatched_cwd or not projects
        record['intents'] = list(dict.fromkeys(record['intents'] + intents))[:3]
        for name, ids in tools.items():
            record['tool_events'][name] = sorted(set(record['tool_events'].get(name, [])) | ids)

    def add_catalog(self, raw):
        path = Path(raw).absolute()
        old_assets, old_sessions, old_roots = self.assets, self.sessions, self.roots
        old_flags = self.session_flags
        try:
            no_links(path)
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError('regular catalog required')
            remaining = self.limits['catalog_bytes'] - self.import_bytes
            size = path.stat().st_size
            if size > remaining:
                raise ValueError('catalog byte cap')
            with path.open('rb') as stream:
                payload = stream.read(min(size + 1, remaining + 1))
            self.import_bytes += len(payload)
            if len(payload) > remaining or len(payload) != size:
                raise ValueError('catalog byte cap')
            value = json.loads(payload) if payload is not None else None
            if not isinstance(value, dict) or value.get('schema_version') != 1 or value.get('kind') != 'work-context-catalog':
                raise ValueError('invalid catalog')
            # All-or-nothing import: malformed input must not leave partial rows.
            self.assets = json.loads(json.dumps(self.assets))
            self.sessions = json.loads(json.dumps(self.sessions))
            self.roots = list(self.roots)
            self.session_flags = {key: dict(flags) for key, flags in self.session_flags.items()}
            alias = f'import-{len(self.roots) + 1:02d}'
            self.roots.append({'id': alias, 'scope': 'import', 'environment': '검토된 내보내기'})
            for kind, target in (('assets', self.assets), ('sessions', self.sessions)):
                records = value.get(kind, [])
                record_cap = self.limits['session_files'] if kind == 'sessions' else self.limits['files']
                if not isinstance(records, list) or len(records) > record_cap:
                    raise ValueError('invalid records')
                if kind == 'sessions' and not self.include_sessions:
                    if records:
                        self.warnings['재집계 세션 미포함 (--no-sessions)'] += len(records)
                    continue
                for record in records:
                    if not isinstance(record, dict) or not re.fullmatch(r'[a-f0-9]{64}', str(record.get('id', ''))):
                        raise ValueError('invalid record')
                    key = record['id']
                    if not isinstance(record.get('origins', []), list) or not isinstance(record.get('topics', []), list):
                        raise ValueError('invalid provenance')
                    origins = [{'root': alias, 'path': imported_origin(o)}
                               for o in record.get('origins', [])[:20] if isinstance(o, dict)]
                    approved_topics = [label for label in record.get('topics', []) if label in TOPICS or label == '미분류']
                    if kind == 'assets':
                        target.setdefault(key, {'id': key, 'kind': record.get('kind') if record.get('kind') in
                            ('skill', 'instruction', 'knowledge', 'memory', 'reference', 'configuration') else 'reference',
                            'title': clean(record.get('title'), 100), 'description': clean(record.get('description')),
                            'topics': approved_topics, 'evidence': 'definition', 'origins': []})['origins'].extend(origins)
                    else:
                        # Exports contain already retained work. A local greeting-only
                        # copy must not erase substantive evidence in a later export.
                        if key in self.session_flags:
                            self.session_flags[key]['ambiguous'] = True
                        item = target.setdefault(key, {'id': key, 'evidence': 'observed_calls', 'origins': [],
                            'user_events': [], 'tool_events': {}, 'topics': [], 'intents': [], 'project_roots': [], 'unmapped_project': False})
                        item['origins'].extend(origins)
                        item['user_events'] = sorted(set(item['user_events']) | valid_hashes(record.get('user_events'), self.limits['session_events']))
                        item['topics'] = sorted(set(item['topics']) | set(approved_topics))
                        project_ids = record.get('project_roots', [])
                        if not isinstance(project_ids, list):
                            raise ValueError('invalid project aliases')
                        item['project_roots'] = sorted(set(item['project_roots']) | {alias + '/' + clean(p, 80) for p in project_ids[:20] if isinstance(p, str)})
                        item['unmapped_project'] = item['unmapped_project'] or bool(record.get('unmapped_project', True))
                        tool_events = record.get('tool_events', {})
                        if not isinstance(tool_events, dict) or len(tool_events) > 500:
                            raise ValueError('invalid tools')
                        for name, hashes in tool_events.items():
                            if re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}', name):
                                item['tool_events'][name] = sorted(set(item['tool_events'].get(name, [])) | valid_hashes(hashes, self.limits['session_events']))
                        if self.include_intents:
                            if not isinstance(record.get('intents', []), list):
                                raise ValueError('invalid intents')
                            item['intents'] = list(dict.fromkeys(item['intents'] + [clean(s, 160) for s in record.get('intents', [])[:3]]))[:3]
            merged_events = sum(len(s['user_events']) + sum(len(v) for v in s['tool_events'].values()) for s in self.sessions.values())
            if len(self.assets) > self.limits['files'] or len(self.sessions) > self.limits['session_files'] or merged_events > self.limits['session_events']:
                raise ValueError('merged record cap')
            self.warnings['재집계 입력의 수집 한도·누락은 원본 보고서도 확인'] += 1
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
            self.assets, self.sessions, self.roots = old_assets, old_sessions, old_roots
            self.session_flags = old_flags
            self.warnings['재집계 파일 형식·크기·접근 오류'] += 1

    def result(self):
        assets, sessions = list(self.assets.values()), []
        skipped = Counter()
        local_kept, local_skipped_files = 0, 0
        for key, record in self.sessions.items():
            flags = self.session_flags.get(key)
            if flags is not None and not flags['meaningful'] and not flags['ambiguous']:
                skipped['greeting_or_thanks_only' if flags['greeting'] else 'context_only' if flags['context'] else 'empty'] += 1
                local_skipped_files += len([o for o in record['origins'] if not o['root'].startswith('import-')])
                continue
            sessions.append(record)
            local_kept += len([o for o in record['origins'] if not o['root'].startswith('import-')])
        tools = Counter()
        for session in sessions:
            tools.update({name: len(ids) for name, ids in session['tool_events'].items()})
        return {'schema_version': 1, 'kind': 'work-context-catalog', 'generated_at': datetime.now(timezone.utc).isoformat(),
            'roots': self.roots, 'assets': assets, 'sessions': sessions,
            'summary': {'defined_assets': sum(a['kind'] != 'configuration' for a in assets),
                'configuration_locations': sum(a['kind'] == 'configuration' for a in assets),
                'inventory_records': len(assets), 'observed_sessions': len(sessions), 'tool_calls': sum(tools.values()),
                'tools': dict(tools), 'asset_kinds': dict(Counter(a['kind'] for a in assets)),
                'topic_definitions': dict(Counter(t for a in assets if a['kind'] != 'configuration' for t in a['topics'])),
                'topic_sessions': dict(Counter(t for s in sessions for t in s['topics']))},
            'coverage': {'limits': self.limits, 'bytes_read': self.read_bytes, 'candidate_files': self.file_count,
                'entries_seen': self.entries, 'sessions_requested': self.include_sessions, 'intent_excerpts_requested': self.include_intents,
                'auto_session_discovery': self.auto_discovery, 'session_bytes_read': self.session_bytes,
                'session_event_processing_budget_used': self.session_event_count, 'catalog_bytes_read': self.import_bytes,
                'session_scan': dict(self.session_stats, files_kept=local_kept, files_filtered=local_skipped_files,
                    records_kept=len(sessions), records_filtered=sum(skipped.values()),
                    uncertain_records=sum(self.session_flags.get(s['id'], {}).get('ambiguous', False) for s in sessions)),
                'session_skip_reasons': dict(self.session_skips), 'session_filter_reasons': dict(skipped),
                'warnings': dict(self.warnings), 'complete_environment_scan': False,
                'note': '지정 폴더와 확인된 현재 사용자 세션 저장소만 관찰했습니다. PC 전체 탐색이 아니며, 상한·누락은 별도 표시합니다. 정의 발견은 사용·성공 증거가 아니며 분류는 후보입니다.'}}


def valid_hashes(value, cap=200000):
    if not isinstance(value, list) or len(value) > cap:
        raise ValueError('invalid events')
    return {s for s in value if isinstance(s, str) and re.fullmatch(r'[a-f0-9]{64}', s)}


def extract_user_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(item.get('text', '') for item in content
                        if isinstance(item, dict) and item.get('type') in ('text', 'input_text')
                        and isinstance(item.get('text'), str))
    return ''


def pure_greeting(text):
    # Exact phrases only: a short approval, question, failed task or greeting
    # followed by real work is retained, never judged by topic-keyword presence.
    normalized = re.sub(r'[\s!.,?~。！…]+', '', text.casefold())
    return normalized in {'안녕', '안녕하세요', '안녕하십니까', '반갑습니다', '고마워', '고마워요',
        '고맙습니다', '감사합니다', '감사해요', '수고했어요', '수고하셨습니다', 'hello', 'hi',
        'hey', 'thanks', 'thankyou', 'thankyouverymuch'}


def remove_context_blocks(text):
    text = re.sub(r'<(environment_context|permissions instructions|system-reminder|turn_aborted)>[\s\S]*?</\1>', '', text).strip()
    if text.startswith('# AGENTS.md instructions for'):
        # Known context-only message, unless an explicit user-request boundary exists.
        for marker in ('## My request', '## User request', '<user_request>'):
            if marker in text:
                return text.split(marker, 1)[1].strip()
        match = re.fullmatch(r'#[^\n]*\n\s*<INSTRUCTIONS>[\s\S]*?</INSTRUCTIONS>\s*', text)
        return '' if match else text
    return text


def discover_session_roots(collector, environ=None, home=None):
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    collector.auto_discovery = True
    for provider, variable, default, children in (
            ('Claude 세션', 'CLAUDE_CONFIG_DIR', home / '.claude', ('projects',)),
            ('Codex 세션', 'CODEX_HOME', home / '.codex', ('sessions', 'archived_sessions'))):
        value = environ.get(variable)
        base = Path(value) if value is not None else default
        # A configured root supersedes that provider's default even if unusable.
        # Never silently inspect another profile after an override is rejected.
        try:
            if not base.is_absolute() or str(base).startswith(('\\\\', '//')) or base == Path(base.anchor) or base == home or base in home.parents:
                raise ValueError('broad or nonlocal configured path')
            no_links(base)
        except (OSError, ValueError):
            collector.warnings[provider + ' 저장소 없음 또는 안전하지 않은 설정 경로'] += 1
            continue
        for child in children:
            target = base / child
            if not target.exists():
                collector.warnings[provider + ' 알려진 저장소 없음'] += 1
                continue
            collector.add_root(target, 'profile', sessions_only=True, provider=provider)


def render(report):
    esc = lambda value: html.escape(str(value), quote=True)
    font = Path(__file__).resolve().parents[1] / 'assets/NotoSansKR-Variable.woff'
    font_css = ''
    font_license = ''
    if font.is_file():
        font_css = "@font-face{font-family:'Noto Sans KR';font-style:normal;font-weight:100 900;src:url(data:font/woff;base64," + base64.b64encode(font.read_bytes()).decode() + ") format('woff')}"
        license_path = font.with_name('OFL.txt')
        if not license_path.is_file():
            raise ValueError('Bundled font license missing')
        font_license = '<details><summary>글꼴 라이선스</summary><pre style="white-space:pre-wrap">' + esc(license_path.read_text(encoding='utf-8')) + '</pre></details>'
    counts = report['summary']
    rows = ''.join('<tr><td><strong>' + esc(asset['title']) + '</strong><small>' + esc(asset['description']) + '</small></td><td>'
        + esc({'skill':'스킬','instruction':'업무 지침','memory':'기억','knowledge':'지식','reference':'참고 문서','configuration':'설정 위치'}.get(asset['kind'], asset['kind']))
        + '</td><td>' + esc(', '.join(asset['topics'])) + '</td><td>'
        + '<br>'.join(esc(o['root'] + '/' + o['path']) for o in asset['origins']) + '</td></tr>' for asset in report['assets'])
    topic_rows = ''.join('<tr><td>' + esc(name) + '</td><td>' + str(counts['topic_definitions'].get(name, 0)) + '</td><td>'
        + str(counts['topic_sessions'].get(name, 0)) + '</td></tr>' for name in [*TOPICS, '미분류'])
    session_rows = ''.join('<tr><td>' + esc(s['id'][:12]) + '<small>' + esc(', '.join(s.get('project_roots', [])) or '프로젝트 미연결') + (' · 미연결 범위 있음' if s.get('unmapped_project') else '') + '</small></td><td>' + str(len(s['user_events'])) + '</td><td>'
        + esc(', '.join(name + ' ' + str(len(ids)) + '회' for name, ids in s['tool_events'].items()) or '호출 없음')
        + '</td><td>' + esc(' / '.join(s['intents']) or '질문 원문 미포함') + '</td></tr>' for s in report['sessions'])
    warning_rows = ''.join('<li>' + esc(reason) + ' · ' + str(count) + '건</li>' for reason, count in report['coverage']['warnings'].items()) or '<li>명시한 한도 안에서 별도 읽기 경고 없음</li>'
    scan = report['coverage'].get('session_scan', {})
    filter_labels = {'greeting_or_thanks_only':'인사·감사만 있는 대화', 'context_only':'환경 지침만 있는 기록', 'empty':'빈 대화'}
    scan_text = '세션 파일 발견 {files_found} · 읽기 {files_scanned} · 읽은 줄 {lines_scanned} · 포함 파일 {files_kept} · 단순 대화 제외 파일 {files_filtered} · 부분 읽기 파일 {partial_files}'.format(**{k: scan.get(k, 0) for k in ('files_found','files_scanned','lines_scanned','files_kept','files_filtered','partial_files')})
    filter_text = ' / '.join(filter_labels.get(k, k) + ' ' + str(v) + '개' for k, v in report['coverage'].get('session_filter_reasons', {}).items()) or '단순 대화 제외 없음'
    skip_labels = {'same_file_already_scanned': '이미 확인한 같은 파일', 'file_limit': '파일 수 한도로 미확인',
                   'byte_limit': '읽기 용량 한도로 미확인', 'mixed_session_ids': '서로 다른 세션이 섞인 기록'}
    omitted_text = ' / '.join(skip_labels.get(k, '기타 제외') + ': ' + str(v) for k, v in report['coverage'].get('session_skip_reasons', {}).items())
    roots = ''.join('<div class="root"><b>' + esc(r['id']) + '</b><span>'
        + esc({'project':'프로젝트','profile':'개인 AI 설정','state':'관리형 상태 저장소','import':'검토한 내보내기'}.get(r['scope'], r['scope']))
        + '</span><span>' + esc(r['environment']) + '</span></div>' for r in report['roots'])
    return '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; font-src data:; base-uri 'none'; form-action 'none'">
<title>업무 맥락 현황</title><style>''' + font_css + '''
*{box-sizing:border-box}body{margin:0;background:#f4f6f8;color:#1c3043;font-family:'Noto Sans KR',sans-serif;line-height:1.65}main{max-width:1160px;margin:auto;padding:48px 24px}header{border-top:5px solid #207b78;padding:28px 0}h1{font-size:36px;letter-spacing:-1px;margin:10px 0}h2{font-size:22px;margin:0 0 18px}p{max-width:780px;color:#526579}section{background:white;border:1px solid #dce3e8;border-radius:18px;margin:20px 0;padding:26px}.eyebrow{color:#207b78;font-weight:700}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.metric{padding:24px;border-radius:14px;background:#e8f1f0}.metric strong{display:block;font-size:34px;color:#185d5b}.metric span{font-size:14px}.roots{display:flex;gap:12px;flex-wrap:wrap}.root{padding:14px 18px;border:1px solid #dce3e8;border-radius:12px;min-width:180px}.root span,small{display:block;color:#64758a;font-size:12px}.table{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}th{text-align:left;background:#f1f5f8;font-weight:600}th,td{padding:13px 14px;border-bottom:1px solid #e2e9ed;vertical-align:top;overflow-wrap:anywhere}td:first-child{min-width:150px}td:last-child{max-width:380px}ul{padding-left:20px}.notice{border-left:4px solid #c98b30;background:#fff9ec;padding:16px 20px;color:#765622}footer{font-size:13px;color:#64758a}@media(max-width:650px){main{padding:24px 14px}h1{font-size:28px}section{padding:18px}.metrics{grid-template-columns:1fr}.metric{padding:14px 20px}.metric strong{font-size:28px}}@media print{body{background:white}main{padding:0}section{break-inside:avoid}.table{overflow:visible}th,td{font-size:10px;padding:6px}}
</style></head><body><main><header><div class="eyebrow">업무 자산과 실제 활용 흔적</div><h1>업무 맥락 현황</h1><p>어떤 업무 기준과 재사용 자산이 있는지, 허용한 세션에서 어떤 도구가 호출됐는지를 구분해 봅니다. 파일이 있다는 이유만으로 사용 중이거나 업무가 성공했다고 판단하지 않습니다.</p></header>
<div class="metrics"><div class="metric"><strong>''' + str(counts['defined_assets']) + '''</strong><span>발견한 정의 · 중복 내용 합산 제외</span></div><div class="metric"><strong>''' + str(counts['observed_sessions']) + '''</strong><span>관찰 세션 · 전체 사용량 아님</span></div><div class="metric"><strong>''' + str(counts['tool_calls']) + '''</strong><span>관찰 도구 호출 · 성공 여부 미판정</span></div></div>
<section><h2>확인한 저장 영역</h2><div class="roots">''' + roots + '''</div><p>전체 경로는 내보내지 않습니다. 별칭 아래의 상대 위치로 출처를 구분합니다.</p></section>
<section><h2>업무 유형별 분류 후보</h2><p>제목·설명과 허용된 질문의 키워드로 분류한 후보입니다. 여러 유형에 중복 포함될 수 있으며 업무량·개인 성과를 뜻하지 않습니다.</p><div class="table"><table><thead><tr><th>업무 유형</th><th>정의 발견</th><th>세션 관찰</th></tr></thead><tbody>''' + topic_rows + '''</tbody></table></div></section>
<section><h2>스킬·지식·기억의 출처</h2><div class="table"><table><thead><tr><th>자산</th><th>종류</th><th>분류 후보</th><th>출처</th></tr></thead><tbody>''' + (rows or '<tr><td colspan="4">수집 범위에서 자산을 찾지 못했습니다.</td></tr>') + '''</tbody></table></div></section>
<section><h2>세션의 업무 흔적</h2><p>인사·감사만 있는 대화와 빈·환경 지침 전용 기록은 제외합니다. 짧거나 실패한 업무, 의미가 불명확한 기록은 보존합니다. 세션을 읽더라도 대화 원문은 기본 내보내지 않습니다.</p><div class="table"><table><thead><tr><th>익명 세션 식별</th><th>사용자 역할 이벤트</th><th>도구 호출</th><th>선택 발췌</th></tr></thead><tbody>''' + (session_rows or '<tr><td colspan="4">수집하지 않았거나 포함할 업무 흔적이 없습니다. 아래 범위를 확인하세요.</td></tr>') + '''</tbody></table></div></section>
<section><h2>수집 범위와 누락</h2><p>''' + esc(scan_text) + '</p><p>' + esc(filter_text) + '</p><p>' + esc(omitted_text) + '''</p><ul>''' + warning_rows + '''</ul><div class="notice">지정 폴더와 확인된 현재 사용자 세션 저장소의 관찰이며 PC 전체 탐색은 아닙니다. 상한·누락은 위에 표시됩니다. 자동 가림이 모든 기밀·개인정보를 제거하지는 않습니다. 공유 전에 제목·설명·출처·발췌를 확인하세요.</div></section><footer>로컬 생성 · 원본 수정 및 업로드 없음 · 재집계 자료: catalog.json''' + font_license + '''</footer></main></body></html>'''


def main(argv=None):
    parser = argparse.ArgumentParser(description='업무 자산과 현재 사용자 세션 저장소를 로컬 집계합니다. 대화 원문은 기본 내보내지 않습니다.')
    parser.add_argument('--root', action='append', default=[])
    parser.add_argument('--profile-root', action='append', default=[])
    parser.add_argument('--state-root', action='append', default=[])
    parser.add_argument('--catalog', action='append', default=[])
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--include-sessions', dest='include_sessions', action='store_true', help='세션 포함 (기본값·이전 명령 호환)')
    selection.add_argument('--no-sessions', dest='include_sessions', action='store_false', help='세션 읽기와 자동 발견 모두 생략')
    parser.set_defaults(include_sessions=True)
    parser.add_argument('--no-auto-sessions', action='store_true', help='지정한 폴더만 사용; 알려진 프로필도 자동 발견하지 않음')
    for option, key in (('files', 'session_files'), ('bytes', 'session_bytes'), ('line-bytes', 'line_bytes'),
                        ('events', 'session_events'), ('entries', 'session_entries')):
        parser.add_argument('--max-session-' + option, type=int, default=LIMITS[key], dest=key)
    parser.add_argument('--max-catalog-bytes', type=int, default=LIMITS['catalog_bytes'], dest='catalog_bytes')
    parser.add_argument('--include-intents', action='store_true')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    local_collection = bool(args.root or args.profile_root or args.state_root) or not args.catalog
    automatic = local_collection and args.include_sessions and not args.no_auto_sessions and not args.profile_root
    if not any((args.root, args.profile_root, args.state_root, args.catalog)) and not automatic:
        parser.error('읽을 폴더 또는 검토한 catalog.json을 지정하세요.')
    if args.include_intents and not args.include_sessions:
        parser.error('--include-intents와 --no-sessions는 함께 사용할 수 없습니다.')
    keys = ('session_files', 'session_bytes', 'line_bytes', 'session_events', 'session_entries', 'catalog_bytes')
    if any(getattr(args, key) <= 0 for key in keys):
        parser.error('수집 상한은 1 이상의 정수로 지정하세요.')
    output = Path(args.output).absolute()
    if output.exists() or output.is_symlink():
        parser.error('기존 결과는 덮어쓰지 않습니다. 새 결과 폴더를 지정하세요.')
    no_links(output.parent)
    collector = Collector({key: getattr(args, key) for key in keys}, include_sessions=args.include_sessions, include_intents=args.include_intents)
    for scope, roots in (('project', args.root), ('profile', args.profile_root), ('state', args.state_root)):
        for root in roots:
            collector.add_root(root, scope)
    if automatic:
        discover_session_roots(collector)
    for path in args.catalog:
        collector.add_catalog(path)
    result = collector.result()
    page = render(result)
    output.mkdir()
    (output / 'catalog.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / '업무현황.html').write_text(page, encoding='utf-8')
    print(json.dumps({'status': 'created', 'defined_assets': result['summary']['defined_assets'],
        'observed_sessions': result['summary']['observed_sessions'], 'warning_categories': len(collector.warnings),
        'topic_definitions': result['summary']['topic_definitions'],
        'topic_sessions': result['summary']['topic_sessions'],
        'session_scan': result['coverage']['session_scan'],
        'session_filter_reasons': result['coverage']['session_filter_reasons'],
        'asset_examples': [{'title': a['title'], 'description': a['description'][:120], 'kind': a['kind']}
                           for a in result['assets'] if a['kind'] != 'configuration'][:8],
        'examples_are_partial': result['summary']['defined_assets'] > 8,
        'report': str(output / '업무현황.html'), 'catalog': str(output / 'catalog.json')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
