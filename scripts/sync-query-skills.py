"""조회 스킬의 공통 실행 코드를 각 독립 배포 원본과 동기화합니다.

개발할 때만 실행합니다. 개인 설정, 데이터베이스와 사용자 설치 폴더는
읽지 않으며, --check는 작업 파일을 바꾸지 않고 차이만 확인합니다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ('oracle-query', 'datalake-query', 'ehub-query', 'data-query-demo')
MANIFEST = 'query-runtime-source.json'


def safe_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for node in (path, *path.parents):
        if os.path.lexists(node):
            info = node.lstat()
            if node.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('링크나 재분석 경로는 동기화하지 않습니다.')
    return path


def sync(root: Path, *, check: bool = False) -> list[str]:
    root = safe_path(root)
    source = safe_path(root / 'scripts/query_skills/query_core')
    if not source.is_dir():
        raise ValueError('공통 조회 실행 코드가 없습니다.')
    modules = {}
    for path in source.glob('*.py'):
        safe_path(path)
        if not re.fullmatch(r'[a-z_][a-z0-9_]*\.py', path.name):
            raise ValueError('공통 조회 모듈 이름을 확인하세요.')
        modules[path.name] = path.read_bytes().replace(b'\r\n', b'\n')
    if '__init__.py' not in modules or 'cli.py' not in modules:
        raise ValueError('공통 조회 실행 코드의 필수 진입점이 없습니다.')
    manifest = {'schemaVersion': 1, 'source': 'scripts/query_skills/query_core',
                'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(modules.items())}}
    manifest_raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    changed = []
    for slug in SKILLS:
        skill = safe_path(root / 'standalone-skills' / slug)
        if not (skill / 'SKILL.md').is_file():
            raise ValueError('독립 스킬의 SKILL.md가 없습니다: ' + slug)
        target = safe_path(skill / 'scripts/query_core')
        record = safe_path(skill / MANIFEST)
        prior = {}
        if record.exists():
            parsed = json.loads(record.read_text(encoding='utf-8-sig'))
            if parsed.get('schemaVersion') != 1 or not isinstance(parsed.get('files'), dict):
                raise ValueError('이전 조회 코드 기록을 확인하세요.')
            prior = parsed['files']
            if any(not re.fullmatch(r'[a-z_][a-z0-9_]*\.py', name) for name in prior):
                raise ValueError('이전 조회 코드 기록에 잘못된 경로가 있습니다.')
        # 기록에 없는 파일은 지우거나 덮어쓰지 않습니다.
        if target.exists():
            for path in target.iterdir():
                safe_path(path)
                if path.name == '__pycache__' and path.is_dir():
                    continue
                if not path.is_file() or path.name not in prior:
                    raise ValueError('관리 기록에 없는 조회 파일을 보존했습니다: ' + slug + '/' + path.name)
        updates = [(name, raw) for name, raw in sorted(modules.items())
                   if not (target / name).is_file() or (target / name).read_bytes().replace(b'\r\n', b'\n') != raw]
        obsolete = sorted(set(prior) - set(modules))
        if updates or obsolete or not record.is_file() or record.read_bytes().replace(b'\r\n', b'\n') != manifest_raw:
            changed.append(slug)
            if not check:
                target.mkdir(parents=True, exist_ok=True)
                for name, raw in updates:
                    safe_path(target / name).write_bytes(raw)
                for name in obsolete:
                    path = safe_path(target / name)
                    if path.exists():
                        path.unlink()  # 고정 배포 폴더 안의 이전 관리 파일 한 개만 삭제합니다.
                record.write_bytes(manifest_raw)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description='독립 조회 스킬의 실행 코드 동기화')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        changed = sync(ROOT, check=args.check)
    except (ValueError, OSError, TypeError, json.JSONDecodeError):
        print('조회 스킬 동기화 중단: 정본, 경로와 관리 기록을 확인하세요.', file=sys.stderr)
        return 2
    print(json.dumps({'skills': len(SKILLS), 'status': 'stale' if args.check and changed else 'current',
                      'changedSkills': changed, 'installed': False}, ensure_ascii=False))
    return 1 if args.check and changed else 0


if __name__ == '__main__':
    raise SystemExit(main())
