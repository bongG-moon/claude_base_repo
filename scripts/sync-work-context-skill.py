"""Sync the portable work inventory skill at build time, never in hooks."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'standalone-skills/work-context-catalog'
DEST = ROOT / 'company-agent-plugin/skills/work-context-catalog'
FILES = ('SKILL.md', 'scripts/work_catalog.py', 'references/collection.md',
         'assets/NotoSansKR-Variable.woff', 'assets/OFL.txt', 'assets/SOURCE.json')


def expected_files():
    expected = {}
    for name in FILES:
        content = (SOURCE / name).read_bytes()
        expected[name] = content if name.endswith('.woff') else content.replace(b'\r\n', b'\n')
    manifest = {'source': str(SOURCE.relative_to(ROOT)).replace('\\', '/'),
                'generatedBy': 'scripts/sync-work-context-skill.py',
                'files': {n: hashlib.sha256(b).hexdigest() for n,b in expected.items()}}
    expected['runtime-source.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    changed = []
    for name, content in expected_files().items():
        target = DEST / name
        current = target.read_bytes() if target.is_file() else None
        if current is not None and not name.endswith('.woff'):
            current = current.replace(b'\r\n', b'\n')
        if current != content:
            changed.append(name)
            if not args.check:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
    if args.check and changed:
        print('Work context skill is stale: '+', '.join(changed))
        return 1
    print('Work context skill sources match.' if args.check else f'Work context skill synchronized: {len(changed)} files.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
