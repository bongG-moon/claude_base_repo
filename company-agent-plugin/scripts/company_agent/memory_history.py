"""On-demand, bounded recovery from existing memory snapshots; no model calls."""
from __future__ import annotations

import os
import json
from pathlib import Path
import re
from typing import Any

from .memory import (MEMORY_ID_PATTERN, MEMORY_KINDS, MEMORY_STATUSES, _document_sha256, _memory_layout,
                     _memory_locked, _read_memory_document, _slug, _upsert_memory)
from .resource_scope import safe

MAX_HISTORY_DIRECTORIES = 512
MAX_HISTORY_RESULTS = 20
MAX_INTEGRITY_RECEIPT_BYTES = 2_048
_STAMP = re.compile(r'^[0-9]{8}-[0-9]{6}-[0-9]{6}$')


def _target(root: Path, identifier: str) -> Path:
    if (not isinstance(identifier, str) or not MEMORY_ID_PATTERN.fullmatch(identifier)
            or len(identifier) > 160):
        raise ValueError('invalid memory id')
    return safe(root / 'memory/items' / f'{_slug(identifier)}.md')


def _read(path: Path, identifier: str):
    document = _read_memory_document(path, path.parent)
    revision = document.metadata.get('revision', 1)
    if (document.metadata.get('id') != identifier or type(revision) is not int or revision < 1
            or str(document.metadata.get('kind')) not in MEMORY_KINDS
            or str(document.metadata.get('status')) not in MEMORY_STATUSES):
        raise ValueError('snapshot identity or revision does not match the requested memory')
    return document


def _integrity(path: Path, document) -> str:
    """Detect changes since capture; local hashes are not authenticity signatures."""
    receipt = path.with_suffix('.receipt.json')
    try:
        safe(receipt)
        if not receipt.exists():
            return 'unverified-legacy'
        if not receipt.is_file() or receipt.stat().st_size > MAX_INTEGRITY_RECEIPT_BYTES:
            return 'mismatch'
        with receipt.open('rb') as stream:
            raw = stream.read(MAX_INTEGRITY_RECEIPT_BYTES + 1)
        if len(raw) > MAX_INTEGRITY_RECEIPT_BYTES:
            return 'mismatch'
        value = json.loads(raw.decode('utf-8-sig'))
        expected = {'schemaVersion': 1, 'memoryId': document.metadata['id'],
                    'revision': document.metadata.get('revision', 1), 'sha256': _document_sha256(document)}
        return ('hash-matched' if isinstance(value, dict) and type(value.get('schemaVersion')) is int
                and type(value.get('revision')) is int and value == expected else 'mismatch')
    except (OSError, ValueError, UnicodeError, TypeError):
        return 'mismatch'


def _snapshots(root: Path, identifier: str):
    folder = safe(root / 'memory/versions')
    found, incomplete = [], False
    if not folder.exists():
        return found, incomplete
    with os.scandir(folder) as entries:
        for count, entry in enumerate(entries):
            if count >= MAX_HISTORY_DIRECTORIES:
                incomplete = True
                break
            if not _STAMP.fullmatch(entry.name):
                continue
            path = Path(entry.path) / f'{_slug(identifier)}.md'
            try:
                safe(path)
                if path.is_file():
                    document = _read(path, identifier)
                    found.append((entry.name, document, _integrity(path, document)))
            except (OSError, ValueError, UnicodeError):
                # Report incomplete history instead of selecting an unsafe backup.
                incomplete = True
    return found, incomplete


def _item(document) -> dict[str, Any]:
    return {'id': document.metadata['id'], 'revision': document.metadata.get('revision', 1),
            'status': document.metadata.get('status'),
            'sha256': _document_sha256(document)}


def memory_history(root: Path, identifier: str, limit: int = 10) -> dict[str, Any]:
    """Read no other memories; do not create folders, inspect prompts or retain a query."""
    target = _target(root, identifier)
    current = _read(target, identifier)
    snapshots, incomplete = _snapshots(root, identifier)
    limit = max(0, min(int(limit), MAX_HISTORY_RESULTS))
    entries, seen = [], set()
    for stamp, document, integrity in sorted(snapshots, reverse=True, key=lambda pair: pair[0]):
        key = (document.metadata.get('revision', 1), _document_sha256(document), integrity)
        if key in seen:
            continue
        seen.add(key)
        if len(entries) < limit:
            entries.append({**_item(document), 'integrity': integrity,
                            'restoreAvailable': integrity == 'hash-matched'})
    return {'ok': True, 'operation': 'history', 'id': identifier, 'changed': False,
            'current': _item(current), 'versions': entries,
            'truncated': incomplete or len(seen) > limit,
            'scanLimitReached': incomplete}


def restore_memory(root: Path, identifier: str, revision: int, *,
                   expected_revision: int, expected_sha256: str) -> dict[str, Any]:
    """Restore content/status as a new revision only at this exact existing store."""
    if type(revision) is not int or revision < 1:
        raise ValueError('복원할 revision은 1 이상의 정수여야 합니다.')
    target = _target(root, identifier)
    # Missing targets must not create a second memory in another scope.
    _read(target, identifier)
    _memory_layout(root)
    with _memory_locked(root):
        current = _read(target, identifier)
        snapshots, incomplete = _snapshots(root, identifier)
        if incomplete:
            raise ValueError('복원 이력을 완전히 확인하지 못했습니다. 현재 기억은 변경하지 않았습니다.')
        matches = [(doc, integrity) for _, doc, integrity in snapshots if doc.metadata.get('revision', 1) == revision]
        documents = [doc for doc, _ in matches]
        if current.metadata.get('revision', 1) == revision:
            documents.append(current)
        unique = {_document_sha256(doc): doc for doc in documents}
        if len(unique) != 1:
            raise ValueError('해당 revision의 복원본이 없거나 서로 다릅니다. 현재 기억은 변경하지 않았습니다.')
        if current.metadata.get('revision', 1) != revision and any(integrity != 'hash-matched' for _, integrity in matches):
            raise ValueError('백업 무결성 정보가 없거나 백업이 변경되어 자동 복원하지 않았습니다. '
                             '원본은 보존했습니다. 필요한 내용은 직접 검토한 후 명시적 기억 수정으로 저장하세요.')
        document = next(iter(unique.values()))
        spec = {key: document.metadata[key] for key in ('id', 'kind', 'title', 'status', 'source')
                if key in document.metadata}
        spec['body'] = document.body
        return _upsert_memory(spec, root, expected_revision=expected_revision,
                              expected_sha256=expected_sha256, require_expected=True,
                              operation='restore', restored_from=revision)
