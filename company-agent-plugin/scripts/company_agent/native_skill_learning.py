"""Exact-target learning for factory-owned native skills, not general file access.

Registration and current native roots are revalidated before every read/write.
The ledger pins ownership identity; old managed ledgers never follow a new skill.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re


def _absolute(value) -> Path:
    if not isinstance(value, str) or not value or len(value) > 2048 or not Path(value).is_absolute():
        raise ValueError('invalid native learning target path')
    return Path(value).absolute()


def recorded_path(target: dict, name: str) -> Path:
    """Schema check only: never use a stored path for I/O without resolve()."""
    if (not isinstance(target, dict) or set(target) != {'kind', 'scope', 'path', 'project', 'stateRoot', 'registrationId'}
            or target['kind'] not in {'native-personal', 'native-project'}
            or target['scope'] != {'native-personal': 'personal', 'native-project': 'project'}[target['kind']]
            or not isinstance(target['registrationId'], str)
            or not re.fullmatch(r'[a-f0-9]{32}', target['registrationId'])):
        raise ValueError('invalid native learning target identity')
    path = _absolute(target['path'])
    if target['kind'] == 'native-project':
        _absolute(target['project'])
    elif target['project'] is not None:
        raise ValueError('personal native learning identity must not bind a project')
    _absolute(target['stateRoot'])
    if path.name.casefold() != 'skill.md' or path.parent.name != name:
        raise ValueError('native learning target name mismatch')
    return path


def _identity(location, project: Path | None) -> dict:
    from .skill_registry import _canonical
    return {'kind': location.storage_kind, 'scope': location.storage_scope,
            'path': _canonical(location.directory / 'SKILL.md'),
            'project': _canonical(project) if location.storage_kind == 'native-project' else None,
            'stateRoot': _canonical(location.state_root), 'registrationId': location.factory_registration_id}


def resolve(root: Path, name: str, target: dict) -> Path:
    from .native_skill_storage import config_root, locate_skill, registered_location
    path = recorded_path(target, name)
    project = _absolute(target['project']) if target['kind'] == 'native-project' else None
    if project is not None:
        location = locate_skill(root, project, name)
    else:
        # A personal skill must outlive and work outside its creation project.
        # Derive the selected same-profile personal store, never accept a
        # stored registry/config path as an authority or rehash a project store.
        from .resource_scope import destinations
        destination = destinations(root, root, {'claudeConfigRoot': str(config_root())})['personal']
        location = (registered_location(Path(destination['stateRoot']), name)
                    if destination['available'] else None)
    if (location is None or not location.factory_owned or location.storage_kind not in {'native-personal', 'native-project'}
            or _identity(location, project) != target
            or location.directory / 'SKILL.md' != path):
        raise ValueError('native skill ownership or location changed; existing content preserved')
    return path


def observe(root: Path, project: Path, path: Path, digest: str | None = None) -> dict:
    """An ownership descriptor, not evidence that a model loaded the body."""
    from .native_skill_storage import locate_skill
    location = locate_skill(root, project, path.parent.name)
    if (not location.factory_owned or location.storage_kind not in {'native-personal', 'native-project'}
            or location.directory / 'SKILL.md' != path.absolute()):
        raise ValueError('only newly factory-owned native skills are automatic learning targets')
    target = _identity(location, project)
    resolve(root, path.parent.name, target)
    if digest is not None and hashlib.sha256(read(root, path.parent.name, target).encode('utf-8')).hexdigest() != digest:
        raise ValueError('native skill changed after body load')
    return target


def read(root: Path, name: str, target: dict) -> str:
    from .learning import _read
    path = resolve(root, name, target)
    return _read(path, path.parent)


def write(root: Path, name: str, target: dict, content: str) -> None:
    from .learning import _write
    path = resolve(root, name, target)
    # Exact SKILL.md only. This does not widen the general learning boundary.
    _write(path, path.parent, content)
