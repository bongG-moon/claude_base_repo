"""Compute Skill locations from the current profile/project, never registry paths.

New CLI Skills use Claude's native folders. Existing private managed Skills stay
where they are. This module neither creates directories nor changes settings.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
import re
from pathlib import Path

from .paths import load_json
from .skill_registry import (MAX_SKILL_BYTES, _canonical, _frontmatter_field, _metadata, _no_reparse,
                             _project_directories, _read)

# Known built-ins are protected, not an assertion that every CLI version has
# exactly this list. Namespace-qualified company/plugin commands are separate.
RESERVED_NAMES = frozenset('''add-dir agents anthropic-skills auth auto bashes branch bug clear color compact config context copy cost
desktop diff doctor effort exit export extra-usage feedback fork help hooks init install-github-app keybindings
login logout mcp memory model output-style passes permissions plan plugin plugins privacy pr-comments release-notes
reload-skills remote-control rename resume review rewind sandbox security-review skills stats status statusline stickers stop
sync synced synched tasks terminal-setup theme todos usage vim voice'''.split())


@dataclass(frozen=True)
class SkillLocation:
    state_root: Path
    storage_scope: str
    storage_kind: str
    directory: Path
    project_root: Path | None
    claude_root: Path
    factory_owned: bool = False
    expected_sha256: str | None = None
    factory_registration_id: str | None = None

    @property
    def file(self) -> Path:
        return self.directory / 'SKILL.md'


def _absolute(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(label + '은 유효한 절대경로여야 합니다.')
    path = path.absolute()
    _no_reparse(path)
    return path


def config_root(claude_root: Path | None = None) -> Path:
    value = claude_root if claude_root is not None else os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude'
    root = _absolute(value, 'Claude 설정 폴더')
    if root.exists() and not root.is_dir():
        raise ValueError('Claude 설정 경로가 폴더가 아닙니다.')
    return root


def check_snapshot_tree(directory: Path) -> None:
    """Do not follow existing user Skill links into unrelated backup content."""
    pending, count, size = [directory] if directory.is_dir() else [], 0, 0
    while pending:
        folder = pending.pop()
        _no_reparse(folder)
        for child in folder.iterdir():
            _no_reparse(child)
            count += 1
            if count > 4096:
                raise ValueError('스킬 백업 항목 수가 안전 확인 한도를 넘었습니다.')
            if child.is_dir():
                pending.append(child)
            elif child.is_file():
                size += child.stat().st_size
                if size > 64 * 1024 * 1024:
                    raise ValueError('스킬 백업 크기가 안전 확인 한도를 넘었습니다.')
            else:
                raise ValueError('일반 파일이 아닌 스킬 항목은 백업하지 않습니다: ' + str(child))


def native_document(raw: bytes, name: str) -> tuple[dict, str]:
    """Inspect common fields without flattening or restricting native YAML."""
    text = raw.decode('utf-8-sig')
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        raise ValueError('SKILL.md frontmatter is missing')
    closing = next((index for index in range(1, len(lines)) if lines[index].strip() == '---'), None)
    if closing is None:
        raise ValueError('SKILL.md closing frontmatter is missing')
    declared, description, invalid = _metadata(raw, name)
    if invalid or declared != name:
        raise ValueError('SKILL.md name does not match its selected native name')
    return {'name': declared, 'description': description,
            'user-invocable': _frontmatter_field(raw, 'user-invocable').casefold() != 'false'}, ''.join(lines[closing + 1:]).strip() + '\n'


def render_native_document(raw: bytes | None, name: str, description: str, body: str, *,
                           preserve_description: bool = False) -> str:
    if raw is None:
        from .frontmatter import dump_frontmatter
        return dump_frontmatter({'name': name, 'description': description}, body)
    native_document(raw, name)
    lines = raw.decode('utf-8-sig').splitlines(keepends=True)
    closing = next(index for index in range(1, len(lines)) if lines[index].strip() == '---')
    header = lines[:closing]
    if not preserve_description:
        rewritten, skipping, inserted = [], False, False
        for line in header:
            if re.match(r'^description\s*:', line):
                rewritten.append('description: ' + json.dumps(description, ensure_ascii=False) + '\n')
                skipping, inserted = True, True
                continue
            if skipping and (line[:1].isspace() or not line.strip()):
                continue
            skipping = False
            rewritten.append(line)
        if not inserted:
            rewritten.append('description: ' + json.dumps(description, ensure_ascii=False) + '\n')
        header = rewritten
    return ''.join(header) + '---\n\n' + body.strip() + '\n'


def _record(state: Path, name: str) -> dict:
    file = state / 'assets/registry.json'
    _no_reparse(file)
    value = load_json(file, {}) or {}
    if not isinstance(value, dict) or not isinstance(value.get('assets', []), list):
        raise ValueError('스킬 등록 목록 형식을 확인하세요.')
    return next((item for item in value.get('assets', [])
                 if isinstance(item, dict) and item.get('type') == 'skill' and item.get('name') == name), {})


def _directory(state: Path, project: Path | None, config: Path, name: str, kind: str) -> Path:
    from .asset_factory import _validate_name
    _validate_name(name)
    if kind == 'managed':
        base = state / 'personal-root/.claude/skills'
    elif kind == 'native-personal':
        base = config / 'skills'
    elif kind == 'native-project' and project is not None:
        base = project / '.claude/skills'
    else:
        raise ValueError('지원하지 않는 스킬 저장 위치입니다.')
    directory = base / name
    _no_reparse(directory)
    if base.exists() and not base.is_dir():
        raise ValueError('스킬 저장 경로가 폴더가 아닙니다: ' + str(base))
    if directory.exists() and not directory.is_dir():
        raise ValueError('스킬 이름의 경로가 폴더가 아닙니다: ' + str(directory))
    _no_reparse(directory / 'SKILL.md')
    return directory


def validate_location(location: SkillLocation, name: str) -> SkillLocation:
    state = _absolute(location.state_root, '개인 상태 저장소')
    config = config_root(location.claude_root)
    project = _absolute(location.project_root, '프로젝트') if location.project_root is not None else None
    if project is not None and not project.is_dir():
        raise ValueError('현재 프로젝트 폴더를 찾을 수 없습니다.')
    if location.storage_scope not in {'personal', 'project'}:
        raise ValueError('스킬 저장 범위를 확인하세요.')
    if location.storage_kind == 'native-project' and location.storage_scope != 'project':
        raise ValueError('프로젝트 스킬의 저장 범위가 일치하지 않습니다.')
    if location.storage_kind == 'native-personal' and location.storage_scope != 'personal':
        raise ValueError('개인 스킬의 저장 범위가 일치하지 않습니다.')
    expected = _directory(state, project, config, name, location.storage_kind)
    if _canonical(expected) != _canonical(location.directory):
        raise ValueError('스킬 경로가 현재 사용자/프로젝트의 정해진 위치와 다릅니다.')
    return replace(location, state_root=state, directory=expected, project_root=project, claude_root=config)


def _matches_record(location: SkillLocation, record: dict) -> bool:
    if not isinstance(record.get('path'), str) or not Path(record['path']).is_absolute():
        return False
    if record.get('effectivePath') is not None and not isinstance(record['effectivePath'], str):
        return False
    expected_kind = record.get('storageKind', 'managed')
    return (expected_kind == location.storage_kind
            and _canonical(record.get('path', '')) == _canonical(location.directory)
            and (not record.get('effectivePath') or _canonical(record['effectivePath']) == _canonical(location.file))
            and (location.storage_kind == 'managed' or
                 (record.get('storageScope') == location.storage_scope
                  and isinstance(record.get('claudeConfigRoot'), str)
                  and _canonical(record.get('claudeConfigRoot', '')) == _canonical(location.claude_root)
                  and (location.storage_kind != 'native-project' or
                       (isinstance(record.get('projectRoot'), str)
                        and _canonical(record['projectRoot']) == _canonical(location.project_root))))))


def _registration_id(record: dict) -> str | None:
    value = record.get('factoryRegistrationId')
    return value if isinstance(value, str) and re.fullmatch(r'[a-f0-9]{32}', value) else None


def registered_location(state_root: Path, name: str, project: Path | None = None,
                        claude_root: Path | None = None) -> SkillLocation | None:
    """Resolve a pointer within an ALREADY selected store; never hash it again."""
    state, config = _absolute(state_root, '개인 상태 저장소'), config_root(claude_root)
    record = _record(state, name)
    if not record:
        return None
    kind = record.get('storageKind', 'managed')
    scope = record.get('storageScope', 'personal')
    current = _absolute(project, '프로젝트') if project is not None else None
    if kind == 'native-project' and current is None:
        return None
    directory = _directory(state, current, config, name, kind)
    location = SkillLocation(state, scope, kind, directory, current, config,
                             record.get('factoryOwned') is True if kind != 'managed' else True,
                             factory_registration_id=_registration_id(record))
    return validate_location(location, name) if _matches_record(location, record) else None


def _locations(root: Path, project: Path, name: str, config: Path) -> list[SkillLocation]:
    from .resource_scope import readable_roots
    found = []
    for scope, state in readable_roots(root, project, {'claudeConfigRoot': str(config)}):
        for kind in ('managed', 'native-personal' if scope == 'personal' else 'native-project'):
            directory = _directory(state, project, config, name, kind)
            record = _record(state, name)
            location = SkillLocation(state, scope, kind, directory, project, config)
            owned = _matches_record(location, record) and (kind == 'managed' or record.get('factoryOwned') is True)
            raw = _read(location.file, MAX_SKILL_BYTES)
            digest = hashlib.sha256(raw).hexdigest() if raw is not None else None
            found.append(replace(location, factory_owned=owned, expected_sha256=digest,
                                 factory_registration_id=_registration_id(record) if owned else None))
    return found


def _native_conflicts(project: Path, config: Path, name: str, allowed: Path) -> list[Path]:
    warnings: list[str] = []
    lineage = _project_directories(project, config, warnings)
    if warnings:
        raise ValueError('프로젝트 스킬 충돌 확인을 완료하지 못했습니다: ' + '; '.join(warnings))
    roots = [config, *(directory / '.claude' for directory in lineage)]
    conflicts, visited = [], set()
    for root in roots:
        if _canonical(root) in visited:
            continue
        visited.add(_canonical(root))
        skills = root / 'skills'
        _no_reparse(skills)
        if skills.is_dir():
            entries = list(skills.iterdir())
            if len(entries) > 1024:
                raise ValueError('기존 스킬이 많아 이름 충돌 확인을 완료하지 못했습니다.')
            for directory in entries:
                _no_reparse(directory)
                file = directory / 'SKILL.md'
                _no_reparse(file)
                if not file.is_file() or _canonical(directory) == _canonical(allowed):
                    continue
                if file.stat().st_size > 262144:
                    raise ValueError('기존 스킬 크기가 충돌 검사 한도를 넘었습니다: ' + str(file))
                declared, _, _ = _metadata(file.read_bytes(), directory.name)
                if name.casefold() in {declared.casefold(), directory.name.casefold()}:
                    conflicts.append(file)
        commands = root / 'commands'
        _no_reparse(commands)
        pending = [commands] if commands.is_dir() else []
        examined = 0
        while pending:
            folder = pending.pop()
            for file in folder.iterdir():
                examined += 1
                if examined > 1024:
                    raise ValueError('기존 command가 많아 이름 충돌 확인을 완료하지 못했습니다.')
                _no_reparse(file)
                if file.is_dir():
                    pending.append(file)
                elif file.suffix.casefold() == '.md' and file.stem.casefold() == name.casefold():
                    conflicts.append(file)
    return conflicts


def locate_skill(root: Path, project: Path, name: str, scope: str | None = None, *,
                 for_create: bool = False, claude_root: Path | None = None) -> SkillLocation:
    root, project, config = _absolute(root, '개인 상태 저장소'), _absolute(project, '프로젝트'), config_root(claude_root)
    if not project.is_dir():
        raise ValueError('현재 프로젝트 폴더를 찾을 수 없습니다.')
    # A prior inspect result may supply its selected stateRoot. Recognize only
    # the exact current-project hash; never trust a registry-provided base path.
    if root.parent.name == 'project-scopes' and os.environ.get('COMPANY_AGENT_SCOPE') != 'Project':
        from .resource_scope import selected_root
        base = root.parent.parent
        if selected_root(base, project, 'project', {'claudeConfigRoot': str(config)}) == root:
            root = base
    if scope is not None and scope not in {'personal', 'project'}:
        raise ValueError('스킬 저장 범위를 확인하세요.')
    locations = _locations(root, project, name, config)
    existing = [item for item in locations if item.file.is_file()]
    selected = [item for item in existing if scope is None or item.storage_scope == scope]
    if not for_create:
        if not selected:
            raise ValueError('현재 프로젝트와 개인 전체에서 기존 스킬을 찾지 못했습니다.')
        if len(selected) != 1:
            raise ValueError('같은 이름의 스킬이 여러 저장 위치에 모두 있습니다. 기존 범위와 실제 원본을 확인하세요.')
        return selected[0]
    if scope is None:
        raise ValueError('새 스킬의 저장 범위를 선택하세요.')
    if len(selected) > 1 or any(item.storage_scope != scope for item in existing):
        raise ValueError('같은 이름의 기존 스킬이 있습니다. 새 사본을 만들지 말고 기존 범위에서 update하세요.')
    if selected and selected[0].storage_kind == 'managed':
        return selected[0]
    target = next((item for item in locations if item.storage_scope == scope and item.storage_kind != 'managed'), None)
    if target is None:
        raise ValueError('선택한 사용자 저장소를 사용할 수 없습니다. 기존 설치 범위를 확인하세요.')
    if name.casefold() in RESERVED_NAMES:
        raise ValueError('Claude 기본 명령과 겹치는 이름입니다. 다른 스킬 이름을 선택하세요: ' + name)
    conflicts = _native_conflicts(project, config, name, target.directory)
    if conflicts:
        raise ValueError('기존 native 스킬/command와 이름이 겹칩니다: ' + ', '.join(str(item) for item in conflicts))
    if target.directory.exists():
        record = _record(target.state_root, name)
        if not target.file.is_file() or not target.factory_owned or not _matches_record(target, record):
            raise ValueError('기존 스킬/폴더를 create로 덮어쓰지 않습니다. 실제 원본을 확인한 뒤 update하세요.')
        if record.get('sha256') != target.expected_sha256:
            raise ValueError('기존 스킬이 생성 후 변경되었습니다. 원본을 읽고 update하세요.')
        return target
    return replace(target, factory_owned=True, factory_registration_id=None)
