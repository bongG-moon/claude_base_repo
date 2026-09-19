"""Two private resource destinations; company distribution is never writable.

Pure, bounded discovery. No migration, directory creation, subprocess or model.
Installation/session state stays where it was; resource selection is separate.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

LABELS = {'personal': '개인 전체', 'project': '이 프로젝트'}


def safe(path: Path) -> Path:
    from .skill_registry import _no_reparse
    path = path.absolute()
    _no_reparse(path)
    return path


def destinations(root: Path, project: Path, record=None) -> dict:
    root, project = safe(root), safe(project)
    record = record or {}
    scope = record.get('scope') or os.environ.get('COMPANY_AGENT_SCOPE', 'User')
    config = Path(record.get('claudeConfigRoot') or os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude').absolute()
    personal = root if scope != 'Project' else None
    project_state = root if scope == 'Project' else None
    # In a project-only installation we must not invent a user installation or
    # overwrite a custom-path user store. Offer it only when explicitly registered.
    if personal is None:
        registry = record.get('registrationsRoot') or os.environ.get('COMPANY_AGENT_REGISTRATIONS_ROOT')
        if registry:
            try:
                path = safe(Path(registry) / 'user/company-agent-install.json')
                if path.is_file() and path.stat().st_size <= 32768:
                    value = json.loads(path.read_text(encoding='utf-8-sig'))
                    if (isinstance(value, dict) and value.get('schemaVersion') == 1
                            and value.get('scope') == 'User' and value.get('enabled') is not False
                            and isinstance(value.get('claudeConfigRoot'), str)
                            and Path(value['claudeConfigRoot']).is_absolute()
                            and Path(value['claudeConfigRoot']).absolute() == config
                            and isinstance(value.get('userStateRoot'), str)
                            and Path(value['userStateRoot']).is_absolute()):
                        personal = safe(Path(value['userStateRoot']))
            except (OSError, ValueError, TypeError, UnicodeError):
                # An unavailable user registration must not disable a healthy
                # project store or cause a guessed replacement user store.
                personal = None
    if project_state is None:
        key = str(project).casefold() if os.name == 'nt' else str(project)
        project_state = safe(root / 'project-scopes' / hashlib.sha256(key.encode('utf-8')).hexdigest()[:24])
    return {name: {'id': name, 'label': LABELS[name], 'available': path is not None,
                   'stateRoot': str(path) if path is not None else None,
                   'projectRoot': str(project) if name == 'project' else None,
                   'sharing': '나만 사용 · 자동 공유 안 함',
                   'notice': ('사용자 설치 등록을 먼저 확인해야 합니다. 임의 저장소를 만들지 않습니다.' if path is None else
                              '현재 프로젝트에서만 참고합니다. 폴더를 공유해도 이 개인 저장소는 전달되지 않습니다.' if name == 'project' else
                              '같은 사용자 설치를 사용하는 여러 프로젝트에서 참고합니다.')}
            for name, path in (('personal', personal), ('project', project_state))}


def selected_root(root: Path, project: Path, selection: str, record=None) -> Path:
    if selection not in LABELS:
        raise ValueError('저장 범위를 선택하세요: 개인 전체 또는 이 프로젝트. 회사 공통에는 직접 저장하지 않습니다.')
    target = destinations(root, project, record)[selection]
    if not target['available']:
        raise ValueError(target['notice'])
    return Path(target['stateRoot'])


def readable_roots(root: Path, project: Path, record=None):
    """At most two roots, current project first. Never enumerate other projects."""
    found = destinations(root, project, record)
    seen = set()
    for name in ('project', 'personal'):
        value = found[name]
        if value['available'] and value['stateRoot'] not in seen:
            seen.add(value['stateRoot'])
            yield name, Path(value['stateRoot'])


def choice_response():
    return {'ok': False, 'status': 'needs_scope_choice', 'written': False,
            'question': '어디에 저장할까요?',
            'choices': [{'id': k, 'label': v} for k, v in LABELS.items()],
            'next': '사용자가 범위를 정하면 --storage-scope personal 또는 project와 --project-root 절대경로를 붙여 실행하세요.'}


def search_knowledge(root: Path, project: Path, query: str, limit: int):
    from .knowledge import search_catalog
    result, seen = [], set()
    for scope, folder in readable_roots(root, project):
        index = folder / 'knowledge/generated-index'
        if not index.is_dir():
            continue
        for item in search_catalog(index, query, limit):
            key = (item.get('path'), json.dumps(item.get('overlays', []), sort_keys=True))
            if key not in seen:
                result.append({**item, 'storageScope': scope})
                seen.add(key)
    return result[:max(0, min(limit, 10))]
