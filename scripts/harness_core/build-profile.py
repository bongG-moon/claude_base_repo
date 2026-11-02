"""Build the personal harness from an explicit, reviewed file manifest.

Source-only functional Skills and engines remain available for individual ZIPs.
This builder never reads a user profile or copies an unlisted source file.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil


PROFILE = 'personal-harness'
MARKER = 'resources/core-install.json'


def relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('Profile paths must be repository-relative POSIX file paths')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {'', '.', '..'} for part in value.split('/')):
        raise ValueError('Unsafe profile path: ' + value)
    return value


def no_links(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for candidate in (path, *path.parents):
        if os.path.lexists(candidate):
            info = candidate.lstat()
            if candidate.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Profile paths cannot contain a symlink or reparse point')
    return path


def selected_files(root: Path, manifest: Path) -> dict[str, Path]:
    root = no_links(root)
    document = json.loads(no_links(manifest).read_text(encoding='utf-8-sig'))
    if document.get('schemaVersion') != 1 or document.get('profile') != PROFILE:
        raise ValueError('Unsupported harness core manifest')
    entries = document.get('files')
    if not isinstance(entries, list) or not entries:
        raise ValueError('A core profile must explicitly list its files')
    result: dict[str, Path] = {}
    seen = {MARKER.casefold()}
    for entry in entries:
        if isinstance(entry, str):
            target = relative_path(entry)
            source = 'company-agent-plugin/' + target
        elif isinstance(entry, dict) and set(entry) == {'path', 'source'}:
            target = relative_path(entry['path'])
            source = relative_path(entry['source'])
        else:
            raise ValueError('Each profile entry must name one file, with an optional source override')
        if target.casefold() in seen:
            raise ValueError('Duplicate or reserved profile destination: ' + target)
        seen.add(target.casefold())
        path = no_links(root / source)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Required core source file is missing: ' + source)
        if path.suffix.casefold() in {'.pyc', '.pyo', '.exe', '.dll', '.pyd', '.so', '.dylib'}:
            raise ValueError('A core source profile cannot include binaries or bytecode: ' + source)
        result[target] = path
    return result


def marker_bytes() -> bytes:
    return (json.dumps({'schemaVersion': 1, 'profile': PROFILE}, indent=2) + '\n').encode('utf-8')


def build(root: Path, manifest: Path, destination: Path, *, check: bool = False,
          validate_python: bool = False) -> dict:
    selected = selected_files(root, manifest)
    destination = no_links(destination)
    # Installation state must never be used as a staging directory. The caller
    # supplies a fresh owned directory; an existing result is read-only checked.
    if check:
        actual = {}
        for path in destination.rglob('*'):
            no_links(path)
            if path.is_file():
                actual[path.relative_to(destination).as_posix()] = path
        if set(actual) != set(selected) | {MARKER}:
            raise ValueError('Core payload file set does not match the explicit manifest')
        if actual[MARKER].read_bytes() != marker_bytes():
            raise ValueError('Core profile marker does not match')
        for target, source in selected.items():
            if actual[target].read_bytes() != source.read_bytes():
                raise ValueError('Core payload differs from its declared source: ' + target)
    else:
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            raise ValueError('Core staging destination must be new or empty')
        destination.mkdir(parents=True, exist_ok=True)
        for target, source in selected.items():
            output = destination / target
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, output)
        output = destination / MARKER
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(marker_bytes())
    if validate_python:
        # Syntax validation in memory avoids bytecode writes and Windows path
        # expansion from PYTHONPYCACHEPREFIX when staging paths are long.
        for relative in selected:
            if relative.endswith('.py'):
                compile((destination / relative).read_bytes(), relative, 'exec')
    return {'ok': True, 'profile': PROFILE, 'files': len(selected) + 1,
            'checked': check, 'pythonSyntaxValidated': validate_python}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--validate-python', action='store_true')
    args = parser.parse_args()
    root = args.source_root.absolute()
    result = build(root, args.manifest or root / 'deploy/harness-core-manifest.json',
                   args.destination, check=args.check, validate_python=args.validate_python)
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
