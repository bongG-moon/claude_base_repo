"""Disposable discovery metadata, never Skill bodies or execution authority.

Only runtime discovery opts in. Explicit inventory/installation remains read-only
and uncached. Directories, plugin activation and preferences are still inspected
each time; only unchanged SKILL.md parsing/hashing is reused. Actual body loads
are checked independently by skill_workflow.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import time

MAX_BYTES = 2_097_152
MAX_ENTRIES = 512
MAX_AGE_SECONDS = 300


class SkillMetadataCache:
    def __init__(self, state: Path):
        from .skill_registry import _read
        self.path = state / 'cache' / 'skill-metadata-v1.json'
        self.now = time.time()
        self.previous = {}
        self.used = {}
        try:
            raw = _read(self.path, MAX_BYTES)
            data = json.loads(raw) if raw else {}
            if data.get('schemaVersion') == 1 and isinstance(data.get('entries'), dict) and len(data['entries']) <= MAX_ENTRIES:
                self.previous = data['entries']
        except (OSError, ValueError, TypeError, AttributeError):
            pass  # A disposable cache must not make discovery unavailable.

    @staticmethod
    def signature(path: Path):
        from .skill_registry import _no_reparse, MAX_SKILL_BYTES
        _no_reparse(path)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SKILL_BYTES:
            raise ValueError('Not a bounded regular Skill file')
        return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]

    def metadata(self, path: Path):
        from .skill_registry import _canonical, _read, _metadata, _frontmatter_field, _name, MAX_SKILL_BYTES
        key = _canonical(path)
        try:
            before = self.signature(path)
        except FileNotFoundError:
            return None
        old = self.previous.get(key)
        if isinstance(old, dict):
            meta = old.get('metadata')
            stamp = old.get('checkedAt')
            valid = (old.get('signature') == before and type(stamp) in (float, int)
                     and 0 <= self.now - stamp < MAX_AGE_SECONDS and isinstance(meta, dict)
                     and set(meta) == {'name', 'description', 'invalid', 'explicitOnly', 'sha256'}
                     and isinstance(meta.get('description'), str) and len(meta['description']) <= 600
                     and type(meta.get('invalid')) is bool and type(meta.get('explicitOnly')) is bool
                     and isinstance(meta.get('sha256'), str) and len(meta['sha256']) == 64
                     and all(c in '0123456789abcdef' for c in meta['sha256']))
            if valid:
                try:
                    _name(meta.get('name'))
                    self.used[key] = old
                    return dict(meta)
                except ValueError:
                    pass
        raw = _read(path, MAX_SKILL_BYTES)
        if raw is None:
            return None
        name, description, invalid = _metadata(raw, path.parent.name)
        meta = {'name': name, 'description': description, 'invalid': invalid,
                'explicitOnly': _frontmatter_field(raw, 'disable-model-invocation').casefold() == 'true',
                'sha256': hashlib.sha256(raw).hexdigest()}
        if self.signature(path) != before:
            raise ValueError('Skill changed during discovery; retry on the next request')
        self.used[key] = {'signature': before, 'checkedAt': self.now, 'metadata': meta}
        return dict(meta)

    def save(self):
        if self.used == self.previous:
            return
        from .skill_registry import _no_reparse
        from .state_compatibility import check_state_compatibility
        from .paths import atomic_write_text
        data = json.dumps({'schemaVersion': 1, 'entries': self.used}, ensure_ascii=False, separators=(',', ':'))
        if len(self.used) > MAX_ENTRIES or len(data.encode('utf-8')) > MAX_BYTES:
            return
        try:
            check_state_compatibility(self.path.parent.parent)
            _no_reparse(self.path)
            atomic_write_text(self.path, data)
        except (OSError, ValueError):
            pass  # Cache persistence failure cannot block normal work.
