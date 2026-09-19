"""Typed, on-demand UI facade over existing personal-state services. No LLM calls.

Registration, not browser input, chooses state/knowledge/policy. Plans never write;
explicit apply uses scope + content hashes. No global CLAUDE/config mutation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone
import uuid

from .paths import atomic_write_json, atomic_write_text
from .frontmatter import parse_frontmatter_text
from .skill_registry import _no_reparse

MAX_FILE = 128 * 1024
MAX_ITEMS = 100
BRIEF = Path('.claude/rules/company-workspace-brief.md')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def bounded(path: Path, maximum=MAX_FILE) -> bytes:
    _no_reparse(path)
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('확인 범위를 넘는 큰 파일입니다. 원본은 변경하지 않았습니다.')
    return raw


def read_json(path: Path, default):
    _no_reparse(path)
    return json.loads(bounded(path).decode('utf-8-sig')) if path.exists() else default


def clean_text(value, label, maximum=2000):
    from .knowledge import SECRET_PATTERNS
    from .memory import _contains_raw_artifact
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\x00' in value:
        raise ValueError(f'{label}: 1~{maximum}자로 입력해 주세요.')
    if _contains_raw_artifact(value) or any(p.search(value) for p in SECRET_PATTERNS):
        raise ValueError('대화·도구 원문이나 자격증명은 기억/지침에 저장하지 않습니다.')
    return value.strip()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,159}', value):
        raise ValueError('유효한 항목 ID가 아닙니다.')
    return value


class WorkspaceService:
    def __init__(self, record, project: Path, plugin: Path):
        self.record = record
        self.project, self.plugin = project.absolute(), plugin.absolute()
        self.root = Path(record['userStateRoot']).absolute()
        self.config = Path(record['claudeConfigRoot']).absolute()
        for path in (self.root, self.project, self.config, self.plugin):
            _no_reparse(path)
        if record.get('scope') not in {'User', 'Project'}:
            raise ValueError('설치 범위를 확인하지 못했습니다.')
        binding = [str(p).casefold() if os.name == 'nt' else str(p)
                   for p in (self.root, self.config)] + [record['scope'], record.get('projectRoot') or '']
        self.scope_id = digest(json.dumps(binding).encode())

    def scope(self):
        return {'id': self.scope_id, 'kind': self.record['scope'], 'stateRoot': str(self.root),
                'projectRoot': self.record.get('projectRoot'), 'coreVersion': self.record.get('coreVersion'),
                'label': '이 프로젝트의 개인 자료' if self.record['scope'] == 'Project' else '사용자 설치의 개인 자료',
                'notice': '프로젝트 설치가 따로 있는 폴더의 기억과 자동 합쳐지지 않습니다.'}

    def document(self, path):
        raw = bounded(path)
        meta, body = parse_frontmatter_text(raw.decode('utf-8-sig'), str(path))
        return meta, body.strip(), digest(raw)

    def _record_roots(self, category):
        if category == 'memory':
            return {'memory': self.root / 'memory/items'}
        if category != 'knowledge':
            raise ValueError('지원하지 않는 목록입니다.')
        roots = {'entries': self.root / 'knowledge/entries', 'overlays': self.root / 'knowledge/overlays'}
        base = self.record.get('knowledgeBaseRoot')
        if base:
            roots['company'] = Path(base)
        return roots

    def _record_paths(self, category):
        """Bounded metadata-only enumeration. Bodies are read for one page only."""
        result, warnings, limited = [], [], False
        for prefix, root in self._record_roots(category).items():
            pending, visited = [(root, 0)], 0
            while pending and visited < 100 and len(result) < 1000:
                folder, depth = pending.pop(0)
                visited += 1
                try:
                    _no_reparse(folder)
                    if not folder.is_dir():
                        continue
                    with os.scandir(folder) as stream:
                        for i, entry in enumerate(stream):
                            if i >= 1000 or len(result) >= 1000:
                                limited = True
                                break
                            path = Path(entry.path)
                            if entry.is_file(follow_symlinks=False) and entry.name.endswith('.md'):
                                _no_reparse(path)
                                stat = entry.stat(follow_symlinks=False)
                                key = prefix + '/' + path.relative_to(root).as_posix()
                                result.append((key, stat.st_size, stat.st_mtime_ns))
                            elif prefix == 'company' and entry.is_dir(follow_symlinks=False):
                                if entry.name not in {'templates','generated','generated-index','versions','exports'} and not entry.name.startswith('.'):
                                    if depth < 3 and len(pending) < 100:
                                        pending.append((path, depth + 1))
                                    else:
                                        limited = True
                except (ValueError, OSError):
                    warnings.append('일부 목록을 확인하지 못했습니다. 원본은 보존했습니다.')
            limited = limited or bool(pending)
        return sorted(result), limited, list(dict.fromkeys(warnings))

    def detail(self, category, key):
        roots = self._record_roots(category)
        if not isinstance(key, str) or len(key) > 2048 or '\\' in key or ':' in key:
            raise ValueError('올바른 항목 키가 아닙니다.')
        parts = key.split('/')
        if len(parts) < 2 or parts[0] not in roots or any(p in {'', '.', '..'} or p.startswith('.') for p in parts[1:]):
            raise ValueError('현재 목록에 속한 항목만 열 수 있습니다.')
        if (parts[0] != 'company' and len(parts) != 2) or len(parts) > 5 or not parts[-1].endswith('.md'):
            raise ValueError('올바른 항목 경로가 아닙니다.')
        if set(parts[1:-1]) & {'templates','generated','generated-index','versions','exports'}:
            raise ValueError('현재 목록에 속한 항목만 열 수 있습니다.')
        path = roots[parts[0]].joinpath(*parts[1:])
        raw = bounded(path)
        text = raw.decode('utf-8-sig')
        if not text.startswith('---'):
            raise ValueError('구조화된 기억·지식 항목이 아닙니다.')
        meta, body = parse_frontmatter_text(text, str(path))
        body = body.strip()
        if category == 'memory':
            mid = identifier(meta.get('id'))
            if path.name != mid + '.md':
                raise ValueError('기억 ID가 파일과 다릅니다.')
        else:
            from .knowledge import KNOWLEDGE_KINDS
            if meta.get('kind') not in KNOWLEDGE_KINDS or not meta.get('id'):
                raise ValueError('구조화된 지식 항목이 아닙니다.')
        clean_text(body, '내용', 2000 if category == 'memory' else 12000)
        item = {key: str(meta[key])[:400] if meta.get(key) is not None else None
                for key in ('id','kind','title','status','source','revision','updated_at','extends')}
        review = meta.get('workspace_review')
        item.update(body=body, sha256=digest(raw), entryKey=key, applied='not-observable',
                    ownership='company' if parts[0] == 'company' else 'personal',
                    pathKey=path.name if parts[0] != 'company' else None,
                    review={k:str(review[k])[:400] for k in ('reference','reviewedAt','reviewAfter') if review.get(k)} if isinstance(review, dict) else {})
        return item

    def listing(self, category, cursor=None, *, include_body=False, limit=20):
        paths, limited, warnings = self._record_paths(category)
        revision = digest(json.dumps([self.scope_id, category, paths], ensure_ascii=False).encode())
        offset = 0
        if cursor is not None:
            if (not isinstance(cursor, dict) or set(cursor) != {'offset','revision'} or cursor.get('revision') != revision
                    or type(cursor.get('offset')) is not int or not 0 <= cursor['offset'] <= len(paths)):
                raise ValueError('목록이나 설치 범위가 변경되었습니다. 새로고침해 주세요.')
            offset = cursor['offset']
        result = []
        for key, _, _ in paths[offset:offset+limit]:
            try:
                item = self.detail(category, key)
                if not include_body:
                    item.pop('body')
                result.append(item)
            except (ValueError, OSError, UnicodeError, TypeError):
                # Untyped company navigation is not a broken knowledge record.
                if not (category == 'knowledge' and key.startswith('company/') and key.split('/')[-1].lower() == 'readme.md'):
                    warnings.append('읽을 수 없는 항목이 있습니다. 원본은 보존했습니다.')
        next_offset = offset + limit
        return {'items': result, 'limited': limited, 'warnings': list(dict.fromkeys(warnings)),
                'nextCursor': {'offset':next_offset, 'revision':revision} if next_offset < len(paths) else None}

    def memories(self):
        return self.listing('memory', include_body=True, limit=MAX_ITEMS)

    def knowledge(self):
        return self.listing('knowledge', include_body=True, limit=MAX_ITEMS)

    def snapshot(self, view='checks'):
        from .learning import learning_status
        from .company_policy import inspect_policy
        from .context_audit import audit_context
        from .skill_registry import inventory_skills
        result = {'apiVersion': 2, 'scope': self.scope(),
                  'notice': '목록 발견·지침 존재는 실제 실행/결과 정확성의 증거가 아닙니다.'}
        if view in {'guide', 'usage'}:
            return result
        if view == 'brief':
            return {**result, 'brief': self.brief()}
        if view == 'knowledge':
            policy = inspect_policy(Path(self.record['managedConfigPath'])) if self.record.get('managedConfigPath') else {'status':'not-configured','rules':[]}
            return {**result, 'policy':policy, 'knowledge':self.listing('knowledge')}
        if view == 'memory':
            try:
                learning = learning_status(self.root)
            except (ValueError, OSError, TypeError, KeyError):
                learning = {'status':'unavailable','notice':'학습 이력을 확인하지 못했습니다. 초기화하지 않습니다.'}
            return {**result, 'memory':self.listing('memory'), 'learning':learning}
        if view != 'checks':
            raise ValueError('지원하지 않는 관리 화면입니다.')
        inv = inventory_skills(self.root, project_root=self.project, claude_root=self.config,
                               plugin_root=self.plugin,
                               knowledge_root=Path(self.record['knowledgeBaseRoot']) if self.record.get('knowledgeBaseRoot') else None,
                               metadata_cache=False)
        skills = [{key: c.get(key) for key in ('id', 'name', 'source', 'description', 'invocation', 'explicitOnly')}
                  for c in inv.get('skills', [])[:100]]
        policy = inspect_policy(Path(self.record['managedConfigPath'])) if self.record.get('managedConfigPath') else {'status': 'not-configured', 'rules': []}
        context = audit_context(self.project, config_root=self.config)
        checks = [
            {'id': 'installation', 'label': '현재 폴더의 설치 등록', 'status': 'ready'},
            {'id': 'skills', 'label': '사용 가능한 스킬 목록', 'status': 'ready' if inv.get('complete') else 'check', 'count': len(skills)},
            {'id': 'policy', 'label': '회사 업무 기준', 'status': 'ready' if policy['status'] == 'available' else 'check'},
            {'id': 'context', 'label': '업무 지침 분량', 'status': 'check' if context['overBudgetCount'] else 'ready', 'count': context['overBudgetCount']},
            {'id': 'office', 'label': '실제 Office 열기·읽기', 'status': 'unverified'},
            {'id': 'model', 'label': '실제 모델 업무 정확성', 'status': 'unverified'}]
        return {**result, 'skills': skills, 'checks': checks,
                'skillWarnings': inv.get('warnings', []), 'skillConflicts': len(inv.get('conflicts', [])),
                'skillsLimited': len(inv.get('skills', [])) > 100,
                'policy': policy, 'context': context}

    def memory_path(self, mid):
        path = self.root / 'memory/items' / (identifier(mid) + '.md')
        _no_reparse(path)
        return path

    def brief(self):
        path = self.project / BRIEF
        raw = bounded(path) if path.exists() else None
        body = raw.decode('utf-8-sig') if raw is not None else ''
        owner = read_json(self.root / 'workspace' / ('brief-' + digest(str(self.project).encode()) + '.json'), {})
        sha = digest(raw) if raw is not None else None
        return {'path': str(path), 'body': body, 'sha256': sha,
                'owned': bool(body and owner.get('sha256') == sha),
                'notice': '이 폴더의 짧은 업무 지침입니다. 기존 CLAUDE.md와 회사 정책은 바꾸지 않습니다.'}

    def plan(self, request):
        if not isinstance(request, dict):
            raise ValueError('변경할 내용을 올바른 형식으로 입력해 주세요.')
        kind = request.get('kind')
        if kind == 'memory':
            mid = identifier(request.get('itemId') or ('memory.preference.' + uuid.uuid4().hex))
            path = self.memory_path(mid)
            old = self.document(path) if path.exists() else None
            if old and request.get('expectedSha256') != old[2]:
                raise ValueError('기억이 바뀌었습니다. 새로고침한 뒤 변경안을 다시 확인하세요.')
            spec = {'id': mid, 'kind': request.get('memoryKind', old[0]['kind'] if old else 'preference'),
                    'title': clean_text(request.get('title'), '제목', 200),
                    'body': clean_text(request.get('body'), '기억'), 'status': request.get('status', 'active'),
                    'source': 'explicit_workspace_request'}
            from .memory import MEMORY_KINDS, MEMORY_STATUSES
            if spec['kind'] not in MEMORY_KINDS or spec['status'] not in MEMORY_STATUSES:
                raise ValueError('지원하지 않는 기억 유형/상태입니다.')
            expected = old[2] if old else None
        elif kind == 'brief':
            current = self.brief()
            if current['sha256'] and (not current['owned'] or current['sha256'] != request.get('expectedSha256')):
                raise ValueError('기존 또는 직접 수정한 업무 지침은 덮어쓰지 않습니다. 내용을 별도로 검토해 주세요.')
            spec = {k: clean_text(request.get(k), k, 600) for k in ('goal', 'inputs', 'outputs', 'checks')}
            expected = current['sha256']
        elif kind == 'knowledge':
            kid = identifier(request.get('itemId') or ('personal.term.' + uuid.uuid4().hex))
            path = self.root / 'knowledge/entries' / (kid + '.md')
            old = self.document(path) if path.exists() else None
            if old and (request.get('expectedSha256') != old[2] or old[0].get('kind') != 'term' or old[0].get('scope') != 'personal'):
                raise ValueError('변경된 지식 또는 다른 유형의 지식은 이 화면에서 덮어쓰지 않습니다.')
            status = request.get('status', 'draft')
            if status not in {'draft', 'active', 'deprecated'}:
                raise ValueError('지원하지 않는 지식 상태입니다.')
            spec = {'id': kid, 'kind': 'term', 'mode': 'personal-new',
                    'title': clean_text(request.get('title'), '제목', 200),
                    'body': clean_text(request.get('body'), '지식', 6000), 'status': status,
                    'source': 'explicit_workspace_request',
                    'metadata': {**(old[0] if old else {}), 'workspace_review': {'reference': clean_text(request.get('reference'), '출처', 400),
                        'confirmation': 'user-reviewed', 'reviewedAt': datetime.now(timezone.utc).isoformat(),
                        'reviewAfter': request.get('reviewAfter') or None}}}
            if spec['metadata']['workspace_review']['reviewAfter']:
                from datetime import date
                date.fromisoformat(spec['metadata']['workspace_review']['reviewAfter'])
            expected = old[2] if old else None
        else:
            raise ValueError('지원하지 않는 변경 유형입니다.')
        return {'schemaVersion': 1, 'operationId': uuid.uuid4().hex, 'scopeId': self.scope_id,
                'project': str(self.project), 'kind': kind, 'expectedSha256': expected, 'spec': spec}

    def versions(self, mid):
        path = self.memory_path(mid)
        result, root = [], self.root / 'memory/versions'
        _no_reparse(root)
        if root.is_dir():
            # Bound directories before sorting; no full-profile or recursive search.
            entries = []
            with os.scandir(root) as stream:
                for i, entry in enumerate(stream):
                    if i >= 500:
                        break
                    if re.fullmatch(r'\d{8}-\d{6}-\d{6}', entry.name):
                        entries.append(entry.name)
            for name in sorted(entries, reverse=True):
                candidate = root / name / path.name
                if candidate.is_file():
                    meta, body, sha = self.document(candidate)
                    result.append({'version': name, 'title': meta.get('title'), 'body': body, 'sha256': sha,
                                   'kind': meta.get('kind'), 'status': meta.get('status')})
                if len(result) >= 10:
                    break
        return {'versions': result, 'notice': '최근 확인 가능한 최대 10개입니다. 현재 내용과 비교 후 적용하세요.'}

    def apply(self, plan):
        if not isinstance(plan, dict) or plan.get('scopeId') != self.scope_id or plan.get('project') != str(self.project):
            raise ValueError('설치 범위가 바뀌었습니다. 변경안을 다시 확인하세요.')
        if plan.get('schemaVersion') != 1 or not isinstance(plan.get('spec'), dict):
            raise ValueError('지원하지 않는 변경안입니다.')
        opid = plan.get('operationId')
        if not isinstance(opid, str) or not re.fullmatch(r'[a-f0-9]{32}', opid):
            raise ValueError('변경 요청 식별자가 없습니다.')
        meta_root = self.root / 'workspace'
        _no_reparse(meta_root)
        from .state import _interprocess_lock, _thread_lock_for
        lock = meta_root / 'changes.lock'
        with _thread_lock_for(lock), _interprocess_lock(lock):
            receipts = read_json(meta_root / 'changes.json', [])
            fingerprint = digest(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode())
            previous = next((r for r in receipts if r['id'] == opid), None)
            if previous:
                if previous['requestHash'] != fingerprint:
                    raise ValueError('같은 ID의 다른 요청은 실행하지 않습니다.')
                return {**previous['result'], 'reused': True}
            kind, spec = plan.get('kind'), plan.get('spec')
            if kind == 'memory':
                from .memory import upsert_memory
                path = self.memory_path(spec['id'])
                current = digest(bounded(path)) if path.exists() else None
                if current != plan['expectedSha256']:
                    raise ValueError('미리보기 이후 기억이 변경되었습니다. 현재 내용을 보존했습니다.')
                for relative in ('memory/versions', 'memory/index', 'ledger'):
                    _no_reparse(self.root / relative)
                path = upsert_memory(spec, self.root)
            elif kind == 'knowledge':
                from .knowledge import upsert_personal
                path = self.root / 'knowledge/entries' / (identifier(spec['id']) + '.md')
                _no_reparse(path)
                current = digest(bounded(path)) if path.exists() else None
                if current != plan['expectedSha256']:
                    raise ValueError('미리보기 이후 지식이 변경되었습니다. 현재 내용을 보존했습니다.')
                if spec.get('mode') != 'personal-new' or spec.get('kind') != 'term' or spec.get('extends'):
                    raise ValueError('이 화면에서는 독립된 개인 지식만 편집합니다.')
                for relative in ('knowledge/versions', 'knowledge/generated-index', 'ledger'):
                    _no_reparse(self.root / relative)
                path = upsert_personal(spec, self.root, Path(self.record['knowledgeBaseRoot']) if self.record.get('knowledgeBaseRoot') else None)
            elif kind == 'brief':
                current = self.brief()
                if current['sha256'] != plan['expectedSha256'] or (current['sha256'] and not current['owned']):
                    raise ValueError('미리보기 이후 업무 지침이 변경되었습니다. 덮어쓰지 않았습니다.')
                path = self.project / BRIEF
                _no_reparse(path)
                if current['body']:
                    backup = meta_root / 'brief-versions' / (opid + '.md')
                    _no_reparse(backup)
                    atomic_write_text(backup, current['body'])
                headings = {'goal': '목표', 'inputs': '입력 자료', 'outputs': '결과물', 'checks': '완료 확인 기준'}
                body = '# 이 폴더의 업무 안내\n\n회사 필수 기준과 원본·개인 자료를 보존합니다. 이 파일은 회사 정책이 아닙니다.\n'
                body += ''.join('\n## ' + headings[k] + '\n\n' + clean_text(spec[k], k, 600) + '\n' for k in headings)
                atomic_write_text(path, body)
                atomic_write_json(meta_root / ('brief-' + digest(str(self.project).encode()) + '.json'), {'sha256': digest(bounded(path))})
            else:
                raise ValueError('지원하지 않는 변경 유형입니다.')
            result = {'ok': True, 'scope': self.scope(), 'path': str(path), 'sha256': digest(bounded(path)),
                      'status': 'saved', 'appliedInFutureWork': 'not-observable'}
            receipts.append({'id': opid, 'requestHash': fingerprint, 'result': result})
            atomic_write_json(meta_root / 'changes.json', receipts[-100:])
            return result

    def dispatch(self, request):
        if not isinstance(request, dict):
            raise ValueError('올바른 요청 형식이 아닙니다.')
        operation = request.get('operation')
        if operation == 'snapshot':
            return self.snapshot(request.get('view', 'checks'))
        if operation == 'list':
            return self.listing(request.get('category'), request.get('cursor'))
        if operation == 'detail':
            return self.detail(request.get('category'), request.get('entryKey'))
        if operation == 'plan':
            return self.plan(request.get('data', {}))
        if operation == 'apply':
            if request.get('confirmed') is not True:
                raise ValueError('변경안을 확인해 주세요.')
            return self.apply(request.get('plan'))
        if operation == 'versions':
            return self.versions(request.get('itemId'))
        if operation in {'learning', 'rollback', 'share'} and request.get('confirmed') is not True:
            raise ValueError('이 변경을 확인해 주세요.')
        if operation == 'learning':
            from .learning import set_learning_enabled
            return set_learning_enabled(self.root, request.get('enabled'))
        if operation == 'rollback':
            from .learning import rollback_change
            return rollback_change(self.root, request.get('changeId'))
        if operation == 'share':
            from .knowledge import export_knowledge
            ids = request.get('itemIds')
            if not isinstance(ids, list) or not 1 <= len(ids) <= 10:
                raise ValueError('개인 지식 1~10개만 선택해 주세요.')
            for value in ids:
                identifier(value)
            path = self.root / 'knowledge/exports' / ('review-' + uuid.uuid4().hex + '.zip')
            _no_reparse(path)
            export_knowledge(self.root, ids, path)
            return {'path': str(path), 'status': 'review-candidate', 'notice': '로컬 공유 후보입니다. 외부 전송/회사 반영은 하지 않았습니다. 공유 전 민감 내용을 직접 검토하세요.'}
        if operation == 'usage':
            from .usage_diagnostics import analyze_usage, inspect_office_timing
            paths = request.get('paths', [])
            if not isinstance(paths, list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in paths):
                raise ValueError('사용자가 선택한 로그의 절대 경로가 필요합니다.')
            result = analyze_usage([Path(p) for p in paths])
            office = request.get('officeResult')
            if office:
                if not isinstance(office, str) or not Path(office).is_absolute():
                    raise ValueError('Office 결과의 절대 경로를 입력해 주세요.')
                result['officeTiming'] = inspect_office_timing(Path(office))
            return result
        raise ValueError('지원하지 않는 업무 관리 요청입니다.')


def command(args):
    import sys
    from .native_runtime import resolve_registration
    project = Path(args.project).resolve(strict=True)
    config = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')
    registrations = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'CompanyAgent/installations'
    record = resolve_registration(registrations, project, claude_root=config)
    if not record:
        raise ValueError('현재 폴더와 설정에 활성 Company Agent 설치 등록이 없습니다. 임의 저장소로 대체하지 않습니다.')
    raw = sys.stdin.buffer.read(64 * 1024 + 1)
    if len(raw) > 64 * 1024:
        raise ValueError('요청 크기를 줄여 주세요.')
    request = json.loads(raw.decode('utf-8-sig'))
    service = WorkspaceService(record, project, Path(__file__).resolve().parents[2])
    print(json.dumps(service.dispatch(request), ensure_ascii=True))
    return 0
