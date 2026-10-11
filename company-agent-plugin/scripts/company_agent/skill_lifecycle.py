"""Canonical native/private Skill inspection and in-place updates.

The selected SKILL.md is the live source. AssetSpec files are authoring inputs,
not watched copies. No model, external process or user's Claude settings here.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .frontmatter import parse_frontmatter_text
from .paths import atomic_write_json, atomic_write_text, load_json
from .skill_registry import _no_reparse

OWNED_FILES = '.asset-skill-files.json'


class SkillSavePartialError(OSError):
    """Actual Skill bytes changed, but the remaining save could not finish."""

    def __init__(self, destination: Path, backup_path: str | None, cause: Exception):
        file = destination / 'SKILL.md'
        try:
            digest = _hash(file.read_bytes())
        except OSError:
            digest = None
        self.result = {
            'ok': False, 'status': 'partial', 'written': True, 'type': 'skill',
            'name': destination.name, 'path': str(destination), 'effectivePath': str(file),
            'backupPath': backup_path, 'sha256': digest, 'registryStatus': 'not-confirmed',
            'bodyIncluded': False, 'validation': {'status': 'save-incomplete', 'execution': 'not-tested'},
            'error': '스킬 파일은 변경되었지만 저장 마무리를 완료하지 못했습니다: ' + str(cause),
            'recovery': ('현재 effectivePath와 backupPath를 비교하세요. 변경을 유지하려면 원인을 해결한 뒤 '
                         '실제 본문으로 같은 스킬을 다시 저장하고, 되돌리려면 백업의 해당 변경 파일만 복원하세요.'
                         if backup_path else '새 스킬 파일은 effectivePath에 남아 있습니다. 원인을 해결한 뒤 같은 이름과 범위로 저장을 다시 완료하세요.'),
        }
        super().__init__(self.result['error'])


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def reference_plan(destination: Path, spec: dict) -> dict | None:
    """Only an explicit references field replaces generated references."""
    if 'references' not in spec:
        return None
    references = spec['references']
    if not isinstance(references, list) or any(not isinstance(item, str) for item in references):
        raise ValueError('references must be an array of text strings')
    marker = destination / OWNED_FILES
    _no_reparse(marker)
    previous = load_json(marker, {}) or {}
    if not isinstance(previous, dict) or (previous and (previous.get('schemaVersion') != 1
                                                       or not isinstance(previous.get('files'), dict))):
        raise ValueError('Invalid generated Skill file ownership record')
    desired = {f'references/reference-{index}.md': text.strip() + '\n'
               for index, text in enumerate(references, 1)}
    removed, preserved = {}, []
    for relative, digest in previous.get('files', {}).items():
        # A modified ownership record must never authorize arbitrary deletion.
        if not isinstance(relative, str) or not re.fullmatch(r'references/reference-[1-9][0-9]*\.md', relative):
            raise ValueError('Invalid generated Skill reference path')
        target = destination / relative
        _no_reparse(target)
        if relative not in desired and target.is_file():
            if isinstance(digest, str) and _hash(target.read_bytes()) == digest:
                removed[relative] = digest
            else:
                preserved.append(relative)
    expected = {}
    for relative in desired:
        target = destination / relative
        _no_reparse(target)
        if target.exists() and not target.is_file():
            raise ValueError('참조 파일 위치에 다른 종류의 항목이 있습니다: ' + relative)
        expected[relative] = _hash(target.read_bytes()) if target.is_file() else None
    return {'desired': desired, 'expected': expected, 'removed': removed, 'preserved': preserved}


def _reference_unchanged(destination: Path, relative: str, expected: str | None) -> None:
    target = destination / relative
    _no_reparse(target)
    unchanged = not target.exists() if expected is None else target.is_file() and _hash(target.read_bytes()) == expected
    if not unchanged:
        raise ValueError('참조 파일이 수정 준비 중 변경되었습니다. 다시 읽고 변경 내용을 합쳐 주세요: ' + relative)


def check_reference_plan(destination: Path, plan: dict | None) -> None:
    if plan is not None:
        for relative, expected in plan['expected'].items():
            _reference_unchanged(destination, relative, expected)


def write_references(destination: Path, plan: dict | None, backup_path: Path | None = None) -> None:
    if plan is None:
        return
    for relative, content in plan['desired'].items():
        _reference_unchanged(destination, relative, plan['expected'][relative])
        atomic_write_text(destination / relative, content)
    removed = []
    for relative, digest in plan['removed'].items():
        target = destination / relative
        _no_reparse(target)
        if target.is_file() and _hash(target.read_bytes()) == digest:
            target.unlink()
            removed.append(relative)
        elif target.exists():
            plan['preserved'].append(relative)
    _no_reparse(destination / OWNED_FILES)
    atomic_write_json(destination / OWNED_FILES, {
        'schemaVersion': 1,
        'files': {relative: _hash(content.encode('utf-8')) for relative, content in plan['desired'].items()},
        'preservedReferences': plan['preserved'],
        'removedReferences': removed,
        'backupPath': str(backup_path) if backup_path else None,
    })


def inspect_skill(state_root: Path, name: str, *, location=None) -> dict:
    """Read actual bytes without layout creation, compilation or catalogue writes."""
    from .asset_factory import _confined_child
    if location is not None:
        from .native_skill_storage import validate_location
        location = validate_location(location, name)
        if location.state_root != Path(state_root).absolute():
            raise ValueError('스킬 저장소와 선택 범위가 일치하지 않습니다.')
        destination = location.directory
    else:
        _no_reparse(state_root / 'personal-root/.claude/skills' / name)
        destination = _confined_child(state_root / 'personal-root/.claude/skills', name)
    native = location is not None and location.storage_kind != 'managed'
    file = destination / 'SKILL.md'
    _no_reparse(file)
    if not file.is_file():
        raise ValueError(f'기존 스킬을 찾지 못했습니다: {file}')
    if native:
        from .skill_registry import MAX_SKILL_BYTES, _read
        raw = _read(file, MAX_SKILL_BYTES)
        if raw is None:
            raise ValueError('조회 중 스킬 파일이 사라졌습니다. 실제 원본을 다시 확인하세요.')
    else:
        raw = file.read_bytes()
    errors = []
    metadata, body = {}, ''
    try:
        if native:
            from .native_skill_storage import native_document
            metadata, body = native_document(raw, name)
        else:
            metadata, body = parse_frontmatter_text(raw.decode('utf-8-sig'), str(file))
        if metadata.get('name') != name:
            errors.append('SKILL.md name does not match its managed name')
        if not native and (not isinstance(metadata.get('description'), str) or not metadata['description'].strip()):
            errors.append('SKILL.md description is missing')
        if not body.strip():
            errors.append('SKILL.md instructions are missing')
    except (ValueError, UnicodeError) as exc:
        errors.append(str(exc))
    from .native_skill_storage import _record, _matches_record, registered_location
    record = _record(state_root, name)
    if ((location is not None and not _matches_record(location, record))
            or (location is None and record.get('path') != str(destination))):
        record = {}
    registered = registered_location(state_root, name, location.project_root, location.claude_root) if native and record else None
    _no_reparse(destination / OWNED_FILES)
    marker = load_json(destination / OWNED_FILES, {}) or {}
    from .skill_workflow import _native_semantics
    native_required = _native_semantics(raw)
    user_invocable = metadata.get('user-invocable', True) is not False
    return {
        'ok': not errors, 'type': 'skill', 'name': name, 'path': str(destination),
        'effectivePath': str(file), 'stateRoot': str(state_root), 'sha256': _hash(raw),
        'storageKind': location.storage_kind if location is not None else 'managed',
        'storageScope': location.storage_scope if location is not None else record.get('storageScope'),
        'projectRoot': str(location.project_root) if location is not None and location.storage_scope == 'project' else None,
        'factoryOwned': bool(registered and registered.factory_owned) if native else True,
        'factoryRegistrationId': registered.factory_registration_id if registered else None,
        'sharing': ('프로젝트 폴더와 함께 공유될 수 있습니다.' if native and location.storage_scope == 'project'
                    else '현재 Claude 설정 프로필에서 사용합니다.' if native else '개인 상태 저장소에 보관하며 자동 공유하지 않습니다.'),
        'bodyIncluded': False, 'hashCovers': 'effectivePath UTF-8 file bytes',
        'description': metadata.get('description', ''),
        'sourceOfTruth': 'effectivePath',
        'authoringSource': {'path': record.get('sourceSpecPath'), 'synchronized': False,
                            'note': 'AssetSpec은 생성 입력입니다. 실제 적용 원본은 effectivePath이며 자동 동기화하지 않습니다.'},
        'validation': {'status': 'structure-valid' if not errors else 'structure-invalid',
                       'errors': errors, 'execution': 'not-tested'},
        'activationRequired': False,
        'usage': {'mode': 'native-skill' if native else 'native-invocation-required' if native_required else 'company-agent-read',
                  'nativeInvocation': name if native else None, 'nativeRequired': native_required,
                  'userInvocable': user_invocable, 'hostDiscovery': 'not-verified',
                  'currentSessionReady': None, 'refreshRequired': None if native else False,
                  'refreshIfMissing': '/reload-skills 또는 새 대화' if native else None,
                  'ready': not errors and (native or not native_required),
                  'instruction': f'{name} 스킬 실행해줘',
                  'command': f'/{name}' if native and user_invocable else None if native else f'/company-agent:skills {name} 실행',
                  'limitation': ('user-invocable: false 설정으로 직접 /명령 호출이 비활성화되어 있습니다.' if native and not user_invocable
                                 else '이 스킬의 실행 옵션이나 동적 치환에는 실제 native Skill 호출이 필요합니다. 개인 파일 읽기로 대신 실행하지 마세요.'
                                 if native_required and not native else None),
                  'refresh': ('Claude의 native 스킬 폴더에 저장했습니다. 현재 세션의 발견/호출 성공은 미확인입니다. '
                              '목록에 없으면 /reload-skills 또는 새 대화로 확인하세요.' if native else
                              '변경한 본문은 다음 요청에서 다시 확인합니다. 기존 private 스킬은 별도 /명령으로 등록되지 않습니다.')},
        'lastReferenceUpdate': {key: marker.get(key, [] if key != 'backupPath' else None)
                                for key in ('preservedReferences', 'removedReferences', 'backupPath')},
    }


def resolve_existing_skill(root: Path, project: Path, name: str, selection: str | None = None) -> tuple[Path, str]:
    """Keep an existing asset's store; never silently choose between namesakes."""
    from .asset_factory import _confined_child
    from .resource_scope import readable_roots, selected_root
    candidates = ([(selection, selected_root(root, project, selection))] if selection
                  else list(readable_roots(root, project)))
    found = []
    for scope, state in candidates:
        _no_reparse(state / 'personal-root/.claude/skills' / name)
        file = _confined_child(state / 'personal-root/.claude/skills', name) / 'SKILL.md'
        _no_reparse(file)
        if file.is_file():
            found.append((state, scope))
    if not found:
        raise ValueError('현재 프로젝트와 개인 전체 저장소에서 기존 스킬을 찾지 못했습니다. 새 이름으로 만들지 말고 실제 경로를 확인하세요.')
    if len(found) != 1:
        raise ValueError('같은 이름의 스킬이 개인 전체와 이 프로젝트에 모두 있습니다. --storage-scope personal 또는 project로 기존 대상을 선택하세요.')
    return found[0]


def update_skill(state_root: Path, name: str, instructions: str, *, description: str | None = None,
                 expected_sha256: str | None = None, location=None) -> dict:
    from .asset_factory import create_asset
    before = inspect_skill(state_root, name, location=location)
    if not before['ok']:
        raise ValueError('기존 SKILL.md 형식을 먼저 확인하세요: ' + '; '.join(before['validation']['errors']))
    if expected_sha256 and expected_sha256 != before['sha256']:
        raise ValueError('스킬이 조회 후 변경되었습니다. 실제 원본을 다시 읽고 변경 내용을 합쳐 주세요.')
    try:
        document = json.loads(instructions)
    except ValueError:
        document = None
    if (isinstance(document, dict) and isinstance(document.get('type'), str)
            and document['type'] in {'skill', 'script-tool', 'mcp'}
            and 'name' in document and any(key in document for key in ('instructions', 'code', 'server_code', 'tools_code'))):
        raise ValueError('AssetSpec JSON 대신 수정할 스킬 본문만 --instructions-file에 넣으세요.')
    # The new text is the authored body, not a second nested SKILL.md document.
    try:
        nested_metadata, _ = parse_frontmatter_text(instructions)
    except ValueError:
        nested_metadata = {}
    if 'name' in nested_metadata or 'description' in nested_metadata:
        raise ValueError('--instructions-file에는 frontmatter 없는 스킬 본문을 넣으세요.')
    registry = load_json(state_root / 'assets/registry.json', {}) or {}
    previous = next((item for item in registry.get('assets', [])
                     if item.get('type') == 'skill' and item.get('name') == name), {})
    spec = {'type': 'skill', 'name': name,
            'description': (before['description'] or name) if description is None else description,
            'instructions': instructions, 'reason': '사용자 요청으로 기존 스킬 수정',
            'knowledge_dependencies': previous.get('knowledgeDependencies', [])}
    try:
        create_asset(spec, state_root, expected_skill_sha256=before['sha256'], skill_location=location,
                     preserve_native_description=description is None)
    except SkillSavePartialError as exc:
        return {**exc.result, 'operation': 'partial-update', 'previousSha256': before['sha256']}
    return {**inspect_skill(state_root, name, location=location), 'operation': 'updated', 'previousSha256': before['sha256']}
