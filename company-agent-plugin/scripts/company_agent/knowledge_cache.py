"""Disposable startup index cache; source bytes are still checked on every run.

Only hashes and reconciliation diagnostics are persisted. This is not a source
of execution authority or a replacement for validation after source changes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from .paths import atomic_write_json
from .skill_registry import _no_reparse

IGNORED_DIRECTORIES = frozenset({
    'templates', 'generated', 'generated-index', '.claude', '.git', 'versions', 'exports',
})
CACHE_VERSION = 1
MAX_CACHE_BYTES = 1_048_576
INDEX_FILES = ('catalog.json', 'catalog.tsv', 'INDEX.md', 'manifest.json')


def signature(path: Path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError(f'Knowledge link or reparse path skipped: {path}')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class SourceSnapshot:
    """One text read per Markdown file, shared by reconciliation and rebuilding."""

    def __init__(self):
        self.texts = {}
        self.errors = []
        self.stamps = {}
        self.directories = {}

    @staticmethod
    def _names(entries):
        return frozenset(entry.name for entry in entries
                         if entry.name.casefold() not in IGNORED_DIRECTORIES
                         and (entry.name.casefold().endswith('.md') or entry.is_dir(follow_symlinks=False)))

    def capture(self, root: Path):
        root = root.absolute()
        try:
            _no_reparse(root)
            if not root.exists():
                self.stamps[root] = None
                return
            pending = [root]
            while pending:
                folder = pending.pop()
                self.stamps[folder] = signature(folder)
                with os.scandir(folder) as stream:
                    entries = sorted(stream, key=lambda item: item.name.casefold())
                self.directories[folder] = self._names(entries)
                for entry in entries:
                    path = Path(entry.path)
                    try:
                        # Prune generated/history trees before entering them.
                        if entry.name.casefold() in IGNORED_DIRECTORIES:
                            continue
                        if not entry.name.casefold().endswith('.md') and not entry.is_dir(follow_symlinks=False):
                            # Unrelated attachments do not participate in the index.
                            continue
                        stamp = signature(path)
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(path)
                        elif entry.name.casefold().endswith('.md'):
                            if not entry.is_file(follow_symlinks=False):
                                raise ValueError('Knowledge Markdown must be a regular file')
                            raw = path.read_text(encoding='utf-8-sig')
                            if signature(path) != stamp:
                                raise ValueError('Knowledge source changed while being read')
                            self.stamps[path] = stamp
                            self.texts[path] = raw
                    except (OSError, ValueError, UnicodeError) as exc:
                        self.errors.append((str(exc), str(path)))
        except (OSError, ValueError) as exc:
            self.errors.append((str(exc), str(root)))

    def pack(self, root: Path):
        path = root.absolute() / 'pack.json'
        _no_reparse(path)
        try:
            stamp = signature(path)
        except FileNotFoundError:
            self.stamps[path] = None
            return root.name, ''
        raw = path.read_text(encoding='utf-8-sig')
        if signature(path) != stamp:
            raise ValueError('Knowledge pack changed while being read')
        self.stamps[path] = stamp
        metadata = json.loads(raw) or {}
        return str(metadata.get('version', root.name)), hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def current(self):
        if self.errors:
            return False
        try:
            for path, previous in self.stamps.items():
                if previous is None:
                    if path.exists():
                        return False
                else:
                    latest = signature(path)
                    if latest == previous:
                        continue
                    if path not in self.directories or latest[:2] != previous[:2]:
                        return False
                    # Our own generated JSON writes or an atomic overlay update
                    # can change a directory stamp without changing discovery.
                    # Re-enumerate just that directory to detect added Markdown
                    # or subdirectories instead of ignoring directory changes.
                    with os.scandir(path) as stream:
                        if self._names(stream) != self.directories[path]:
                            return False
            return True
        except (OSError, ValueError):
            return False

    def revision(self, base: Path, personal: Path, pack_hash: str):
        value = {
            'version': CACHE_VERSION, 'base': str(base.absolute()),
            'personal': str(personal.absolute()), 'pack': pack_hash,
            'files': [(str(path), hashlib.sha256(raw.encode('utf-8')).hexdigest())
                      for path, raw in sorted(self.texts.items())],
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()


def _digest(path: Path):
    _no_reparse(path)
    before = signature(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if signature(path) != before:
        raise ValueError('Generated knowledge file changed during cache check')
    return digest.hexdigest()


def cached_report(index: Path, revision: str):
    """Corrupt, missing or modified derived files always force normal rebuilding."""
    try:
        path = index / 'startup-cache.json'
        _no_reparse(path)
        if path.stat().st_size > MAX_CACHE_BYTES:
            return None
        with path.open('rb') as stream:
            raw = stream.read(MAX_CACHE_BYTES + 1)
        if len(raw) > MAX_CACHE_BYTES:
            return None
        cache = json.loads(raw)
        report = cache.get('report')
        if (cache.get('version') != CACHE_VERSION or cache.get('revision') != revision
                or not isinstance(report, dict)
                or set(report) != {'baseVersion', 'compatible', 'rebased', 'conflicts', 'detached', 'indexIssues'}
                or not isinstance(report['baseVersion'], str)
                or any(not isinstance(report[key], list) for key in ('compatible', 'rebased', 'conflicts', 'detached', 'indexIssues'))
                or report['rebased'] or report['conflicts'] or report['indexIssues']
                or any(not isinstance(item, str) for key in ('compatible', 'detached') for item in report[key])
                or set(cache.get('files', {})) != set(INDEX_FILES)):
            return None
        for name in INDEX_FILES:
            if cache['files'][name] != _digest(index / name):
                return None
        if cache.get('reportHash') != _digest(index.parent / 'conflicts/report.json'):
            return None
        return cache['report']
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def save_report(index: Path, revision: str, report: dict, catalog: dict):
    try:
        expected = (json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
        files = {name: _digest(index / name) for name in INDEX_FILES}
        if files['catalog.json'] != hashlib.sha256(expected).hexdigest():
            return  # Another startup/build published a different snapshot.
        cache = {'version': CACHE_VERSION, 'revision': revision, 'report': report,
                 'files': files,
                 'reportHash': _digest(index.parent / 'conflicts/report.json')}
        if len(json.dumps(cache, ensure_ascii=False, indent=2).encode('utf-8')) + 1 > MAX_CACHE_BYTES:
            return
        path = index / 'startup-cache.json'
        _no_reparse(path)
        atomic_write_json(path, cache)
    except (OSError, ValueError):
        pass  # Losing a disposable optimization must not block normal startup.
