"""Maintainer-only export: current skills -> current local platform contract -> ZIPs.

No model calls, profile discovery, installation, publication, or background hooks.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from zipfile import ZipFile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
from platform_skills.package_content import digest, encoded, make_guide, source_files

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / 'scripts/platform_skills'
DEFAULT_STANDARD = ROOT / 'pt_ai_square/static/guides/pt-file-distribution'
SKIP = {'__pycache__', '.git', '.venv', 'node_modules', 'tests', '.pytest_cache'}
TEXT_SUFFIXES = {'.md', '.py', '.js', '.json', '.html', '.txt', '.css', '.ps1',
                 '.cmd', '.bas', '.cls', '.sh', '.toml', '.yaml', '.yml'}
TEXT_NAMES = {'LICENSE', 'SOURCE_LICENSE', 'COPYING', 'NOTICE'}
TEXT_NORMALIZATION = 'utf8-crlf-to-lf'


def package_source_bytes(path):
    """Normalize UTF-8 text CRLF only; preserve BOM, other bytes and source files.

    Git checkout line endings must not change ZIPs or source review fingerprints.
    Unknown formats, font files and existing external ZIPs stay byte-for-byte.
    """
    path = no_links(path)
    raw = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES or path.name.upper() in TEXT_NAMES:
        try:
            raw.decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('배포 텍스트는 UTF-8이어야 합니다: ' + path.name) from error
        if b'\x00' in raw:
            raise ValueError('텍스트 파일에 바이너리 내용이 있습니다: ' + path.name)
        return raw.replace(b'\r\n', b'\n')
    return raw


def no_links(path):
    """Check before resolve; Windows junctions must not lead outside the source."""
    path = Path(os.path.abspath(path))
    for candidate in (path, *path.parents):
        if os.path.lexists(candidate):
            stat = candidate.lstat()
            if candidate.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
                raise ValueError(f'링크·재분석 경로는 배포하지 않습니다: {candidate.name}')
    return path


def read_tree(base, relative):
    target = no_links(base / relative)
    if not target.exists():
        raise ValueError(f'필요한 소스가 없습니다: {relative}')
    result = {}
    paths = [target] if target.is_file() else target.rglob('*')
    for path in paths:
        parts = path.relative_to(base).parts
        if any(p in SKIP or p.startswith('.') for p in parts):
            continue
        no_links(path)
        if path.is_file() and path.suffix not in {'.pyc', '.pyo'}:
            result[path.relative_to(base).as_posix()] = package_source_bytes(path)
    return result


def snapshot(root, metadata=None):
    tree = {}
    for source in ('company-agent-plugin/skills', 'company-agent-plugin/resources/manuals',
                   'company-agent-plugin/licenses', 'company-agent-plugin/THIRD_PARTY_NOTICES.md',
                   'standalone-skills'):
        tree.update(read_tree(root, source))
    # Only explicitly selected, reusable modules are exported, never the launcher,
    # session store or hooks. Read these bytes once for a consistent build snapshot.
    if metadata is None:
        metadata_file = root / 'scripts/platform_skills/catalog-metadata.json'
        metadata = json.loads(metadata_file.read_text(encoding='utf-8-sig')) if metadata_file.is_file() else {}
    for info in metadata.values():
        for name in info.get('packaging', {}).get('runtimeModules', []):
            if not re.fullmatch(r'[a-z_]+\.(?:py|js)', name):
                raise ValueError('잘못된 제작 모듈 경로: ' + name)
            relative = 'company-agent-plugin/scripts/company_agent/' + name
            tree.update(read_tree(root, relative))
    manifest = 'company-agent-plugin/.claude-plugin/plugin.json'
    tree[manifest] = package_source_bytes(root / manifest)
    return tree


def discover(tree, metadata):
    prefix = 'company-agent-plugin/skills/'
    slugs = {p[len(prefix):].split('/')[0] for p in tree
             if p.startswith(prefix) and p[len(prefix):].count('/') == 1 and p.endswith('/SKILL.md')}
    missing = slugs - metadata.keys()
    if missing:
        raise ValueError('새 스킬의 배포 설명·의존성·흐름을 catalog-metadata.json에 추가하세요: ' + ', '.join(sorted(missing)))
    for slug in slugs:
        if metadata[slug].get('distribution') not in {'portable', 'harness-only'}:
            raise ValueError('배포 구분을 portable 또는 harness-only로 명시하세요: ' + slug)
        if metadata[slug].get('distribution') == 'harness-only' and not metadata[slug].get('distributionReason'):
            raise ValueError('하네스 전용 항목의 제외 이유가 필요합니다: ' + slug)
    active = {slug: metadata[slug] for slug in sorted(slugs)
              if metadata[slug].get('distribution') != 'harness-only'}
    for slug, info in active.items():
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
            raise ValueError('지원하지 않는 스킬 이름: ' + slug)
        source = info['sourceDir']
        if source not in {prefix + slug, 'standalone-skills/' + slug}:
            raise ValueError('sourceDir는 해당 스킬의 저장소 상대 경로여야 합니다: ' + slug)
        if source + '/SKILL.md' not in tree:
            raise ValueError('정본 SKILL.md가 없습니다: ' + source)
        if type(info.get('runtimeRequired')) is not bool:
            raise ValueError('runtimeRequired를 명시하세요: ' + slug)
        if info.get('distribution') == 'portable' and info['runtimeRequired']:
            raise ValueError('개별 배포 스킬은 하네스를 요구할 수 없습니다: ' + slug)
        reviewed = info.get('packaging', {}).get('reviewedPluginDigest')
        if reviewed and reviewed != plugin_digest(tree, slug):
            raise ValueError('하네스 지침이 변경되었습니다. 독립판을 함께 검토하고 reviewedPluginDigest를 갱신하세요: ' + slug)
        for extra in info.get('packaging', {}).get('includeAdditionalPaths', []):
            if not extra.startswith(('skills/', 'resources/', 'licenses/')) or '..' in Path(extra).parts or '\\' in extra or ':' in extra:
                raise ValueError('잘못된 참조 경로: ' + extra)
    if not active:
        raise ValueError('배포할 스킬이 없습니다.')
    return active


def plugin_digest(tree, slug):
    prefix = 'company-agent-plugin/skills/' + slug + '/'
    return digest(encoded({p: digest(raw) for p, raw in sorted(tree.items()) if p.startswith(prefix)}))


def standard_files(standard):
    required = ['SKILL.md', 'references/package-format.md', 'assets/INSTALL_GUIDE.template.md',
                'scripts/prepare_package.py', 'scripts/package_contract.py', 'scripts/install_scope.py']
    files = read_tree(standard, '.')
    for name in required:
        if name not in files:
            raise ValueError('최신 플랫폼 배포 스킬이 필요합니다 (--distribution-skill): ' + name)
    return files


def wrapper(slug, info, original):
    # Keep invocation controls from source; do not broaden automatic invocation.
    match = re.match(r'^---\s*\n(.*?)\n---', original, re.S)
    if not match:
        raise ValueError('SKILL.md frontmatter가 없습니다: ' + slug)
    # Preserve full YAML blocks (including multiline lists), except exported name/description.
    controls, keep = [], True
    for line in match.group(1).splitlines():
        key = re.match(r'^([\w-]+):', line)
        if key:
            keep = key.group(1) not in {'name', 'description'}
        if keep:
            controls.append(line)
    controls = '\n'.join(controls)
    if controls:
        controls += '\n'
    entry = f'source/skills/{slug}/SKILL.md'
    need = ('기존 Company Agent 런타임과 원본이 요구하는 세션 문맥이 필요합니다. '
            '없으면 제한을 안내하고 임의 CLI 경로·세션을 만들지 마세요.' if info['runtimeRequired'] else
            'Company Agent 없이 사용 가능합니다. 필요한 Python 등 의존성은 INSTALL.md를 확인하세요.')
    return f'''---
name: {slug}
description: {json.dumps(info['desc'], ensure_ascii=False)}
{controls}---

# {info['displayName']}

실제 지침은 [{slug}]({entry})입니다. 해당 본문을 읽고 요청한 작업만 진행하세요.
상대 링크와 스킬 폴더는 `source/skills/{slug}` 기준입니다. 현재 문맥에서 읽은 동일 본문은 재사용합니다.

{need}

설치·제거는 [INSTALL.md](INSTALL.md)를 참고하세요. Skill 호출만으로 설치기·의존성 설치·플랫폼 게시를 실행하지 않습니다.
'''.encode('utf-8')


def check_zip(path, expected=None):
    with ZipFile(path) as archive:
        if archive.testzip():
            raise ValueError('ZIP 손상: ' + path.name)
        checks = json.loads(archive.read('PACKAGE_CONTENTS.json'))['files']
        if set(archive.namelist()) != set(checks) | {'PACKAGE_CONTENTS.json'}:
            raise ValueError('ZIP 파일 목록 불일치')
        for name, sha in checks.items():
            raw = archive.read(name)
            if digest(raw) != sha or (expected is not None and expected[name] != raw):
                raise ValueError('ZIP 내용 불일치: ' + name)
            if name.endswith(('.md', '.json', '.py', '.ps1', '.html', '.txt')):
                text = raw.decode('utf-8-sig')
                if re.search(r'C:[/\\]+Users[/\\]+(?:qkekt|2069026)', text, re.I) or re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', text):
                    raise ValueError('개인 경로 또는 비밀키를 배포할 수 없습니다: ' + name)
        provenance = json.loads(archive.read('PACKAGE_SOURCE.json'))
        for name, source in provenance['files'].items():
            if digest(archive.read(name)) != source['sha256']:
                raise ValueError('원본 해시 불일치: ' + name)
        for link in provenance['localReferences']:
            if 'source/' + link['to'] not in checks:
                raise ValueError('참조 파일 누락')


def index_html(rows, version, standard_sha, excluded=None):
    e = html.escape
    external = [r for r in rows if r.get('external')]
    rows = [r for r in rows if not r.get('external')]
    external_table = ''.join(f'<tr><td><a href="{e(r["file"])}">{e(r["name"])}</a><small>{e(r["type"])}</small></td><td>{e(r["environment"])}</td><td>{e(r["description"])}</td></tr>' for r in external)
    external_section = (f'<section class="table"><h2>별도 MCP · {len(external)}개</h2><p>스킬과 별도로 설치·연결하는 도구입니다. ZIP 안의 README.md에서 설치 범위를 선택하고 필요한 접속 설정을 준비하세요. 하네스 설치만으로 연결되지 않습니다.</p><table><thead><tr><th>도구 / ZIP</th><th>사용 조건</th><th>설명</th></tr></thead><tbody>{external_table}</tbody></table></section>' if external else '')
    table = ''.join(f'<tr><td><a href="{e(r["file"])}">{e(r["name"])}</a><small>{e(r["slug"])}</small></td><td>{"Company Agent 필요" if r["runtimeRequired"] else "단독 사용"}{" · 이전 이름 호환" if r["legacyAlias"] else ""}</td><td>{e(r["description"])}</td></tr>' for r in rows)
    excluded_table = ''.join(f'<li><strong>{e(r["name"])}</strong> — {e(r["reason"])}</li>' for r in (excluded or []))
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>개별 스킬 · MCP 배포 파일</title><style>
body{{margin:0;background:#f4f6fa;color:#16223a;font:16px/1.7 'Noto Sans KR','Malgun Gothic',sans-serif}}main{{max-width:1120px;margin:auto;padding:40px 24px}}h1{{font-size:32px}}section{{background:white;border:1px solid #e3e7ef;border-radius:16px;padding:24px;margin:20px 0}}a{{color:#245dbe}}table{{border-collapse:collapse;width:100%}}td,th{{padding:15px;text-align:left;border-bottom:1px solid #e5e9f0;vertical-align:top}}small{{display:block;color:#66748a}}.table{{overflow-x:auto}}td:first-child{{min-width:210px}}@media(max-width:640px){{main{{padding:16px}}section{{padding:16px}}h1{{font-size:26px}}}}</style></head><body><main>
<small>P&amp;T AI SQUARE · 등록 준비 파일</small><h1>필요한 스킬을 하나씩 배포하세요.</h1>
<p>개별 사용 스킬 {len(rows)}개 · 별도 MCP {len(external)}개. 다른 하네스에서도 필요한 스킬만 가져다 사용할 수 있습니다.</p>
<section><h2>등록하는 방법</h2><ol><li>아래에서 필요한 ZIP을 선택합니다.</li><li>플랫폼의 도구 등록 화면에 ZIP 자체를 올립니다.</li><li>채워진 설명·사용 조건·동작 흐름을 확인하고 조직·업무 분류·공개 범위를 직접 선택합니다.</li><li>업데이트는 기존 도구의 새 버전 등록을 사용합니다. 플랫폼은 최초 packageId를 유지하며 새 ZIP의 식별자가 달라도 등록할 수 있습니다. ZIP 내부를 수정할 필요가 없습니다.</li></ol><p>여기까지는 파일 준비입니다. 서버 게시나 사용자 PC 설치는 실행하지 않았습니다.</p></section>
<section class="table"><h2>개별 Skill · 작업 방법과 실행 자료</h2><table><thead><tr><th>스킬 / ZIP</th><th>사용 조건</th><th>설명</th></tr></thead><tbody>{table}</tbody></table></section>
{external_section}
<section><h2>하네스에서 사용하는 기능</h2><p>아래 항목은 개별 업무 스킬 ZIP에 포함하지 않습니다. 필요한 경우 하네스를 설치합니다.</p><ul>{excluded_table}</ul></section>
<section><h2>사용하기 전에</h2><p>ZIP 안의 INSTALL.md를 읽고 현재 프로젝트 또는 내 계정 전체 중 설치 범위를 선택합니다. 기존 같은 폴더는 덮어쓰지 않습니다. Company Agent에 이미 있는 기능은 중복 설치할 필요가 없습니다.</p><p>Skill은 AI가 따르는 작업 방법이며 필요한 Python 코드·참고자료를 함께 담았습니다. MCP는 별도 프로세스로 실행해 AI에 기능을 제공하는 연결 서버입니다. 스킬·도구 제작 도우미는 MCP를 만드는 스킬이며 서버 자체가 아닙니다.</p><p>여기 있는 Skill은 Company Harness 없이 사용할 수 있습니다. Python 패키지·Office·메일 연결 등 개별 의존성은 ZIP의 INSTALL.md를 확인하세요. 기억·지식 스킬은 요청 시 파일을 정리하며 상시 자동 학습을 추가하지 않습니다.</p><p>이전 square-company 이름으로 설치했다면 같은 범위에 두 사본을 설치하지 마세요. 설치기는 중복을 알리고 기존 자료를 보존합니다. 출처와 사용 코드 해시는 PACKAGE_SOURCE.json에 있습니다.</p></section>
<section><h2>다시 만들기</h2><p>저장소에서 <code>python -X utf8 scripts/build-skill-packages.py</code>를 실행합니다. <code>--check</code>는 최신 여부만 검사합니다. 같은 입력은 같은 ZIP을 만들며 불필요하게 파일을 다시 쓰지 않습니다.</p><p>로컬 플랫폼 배포 스킬 기준: <code>{e(standard_sha[:16])}</code>. 대화를 상시 감시하지 않습니다. 플랫폼 소스를 다른 위치에서 관리하면 <code>--distribution-skill</code>로 그 스킬 폴더를 지정하세요.</p></section></main></body></html>'''.encode('utf-8')


def external_packages(root, contract):
    """Keep reviewed standalone packages byte-for-byte; never fetch or install."""
    registry = no_links(root / 'scripts/platform_skills/external-packages.json')
    if not registry.exists():
        return [], {}
    config = json.loads(registry.read_text(encoding='utf-8'))
    if config.get('schemaVersion') != 1 or not isinstance(config.get('packages'), list):
        raise ValueError('외부 패키지 등록 형식을 확인하세요.')
    rows, artifacts, ids, slugs = [], {}, set(), set()
    for item in config['packages']:
        name, slug = item['file'], item['slug']
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.zip', name) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
            raise ValueError('외부 패키지 파일명·별칭을 확인하세요.')
        if name in artifacts or slug in slugs or item['packageId'] in ids:
            raise ValueError('외부 패키지 중복 등록입니다.')
        path = no_links(root / 'skills_zip' / name)
        raw = path.read_bytes()
        if digest(raw) != item['sha256']:
            raise ValueError('외부 패키지 해시 불일치: ' + name)
        # Use the current contract without importing a cached module or running package code.
        code = ('import json,sys; from zipfile import ZipFile; '
                'from package_contract import read_package; '
                'z=ZipFile(sys.argv[1]); p=read_package(z); '
                'assert p is not None; assert z.testzip() is None; '
                'print(json.dumps(p,ensure_ascii=False))')
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', code, str(path)],
                                cwd=contract / 'scripts', capture_output=True, text=True,
                                encoding='utf-8', timeout=30)
        if result.returncode:
            raise ValueError('외부 패키지 최신 규격 검사 실패: ' + name + '\n' + result.stderr)
        manifest = json.loads(result.stdout)
        if manifest['packageId'] != item['packageId'] or manifest['type'] != item['type']:
            raise ValueError('외부 패키지 ID·유형 불일치: ' + name)
        artifacts[name] = raw
        ids.add(item['packageId']); slugs.add(slug)
        rows.append(dict(slug=slug, file=name, name=manifest['name'], description=manifest['desc'],
                         packageId=manifest['packageId'], type=manifest['type'], external=True,
                         environment=manifest['environment'], requirements=manifest['requirements'],
                         workflow=manifest['workflow'], sourceProject=item['sourceProject'],
                         sourceArtifact=item['sourceArtifact'], sourceThread=item['sourceThread'],
                         sha256=digest(raw), size=len(raw)))
    return rows, artifacts


def build(root, standard, stage, metadata_path):
    standard = no_links(standard)
    standards = standard_files(standard)
    standard_hashes = {name: digest(raw) for name, raw in sorted(standards.items())}
    standard_sha = digest(encoded(standard_hashes))
    metadata = json.loads(metadata_path.read_text(encoding='utf-8-sig'))
    tree = snapshot(root, metadata)
    active = discover(tree, metadata)
    version = json.loads(tree['company-agent-plugin/.claude-plugin/plugin.json'])['version']
    rows, artifacts = [], {}
    # Run a frozen copy of the selected current contract, not an imported stale module.
    contract = stage / 'standard'
    for name, raw in standards.items():
        path = contract / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    for slug, info in active.items():
        selected, links = source_files(slug, info, tree)
        entry = f'source/skills/{slug}/SKILL.md'
        original = selected[f'skills/{slug}/SKILL.md'][1].decode('utf-8-sig')
        install_name = slug
        files = {'SKILL.md': wrapper(slug, info, original),
                 'INSTALL.md': make_guide(slug, info, install_name, version).encode('utf-8'),
                 'install_skill.py': package_source_bytes(SUPPORT / 'install_skill.py'),
                 'install_scope.py': standards['scripts/install_scope.py']}
        files.update({'source/' + name: raw for name, (_, raw) in selected.items()})
        files['PACKAGE_SOURCE.json'] = encoded({
            'sourceMode': 'working-tree', 'sourceVersion': version, 'primarySkill': slug,
            'sourcePreserved': True, 'textNormalization': TEXT_NORMALIZATION,
            'runtimeRequired': info['runtimeRequired'],
            'distributionStandard': {'sha256': standard_sha, 'files': standard_hashes,
                                     'textNormalization': TEXT_NORMALIZATION},
            'files': {f'source/{p}': {'repoPath': src, 'sha256': digest(raw)} for p, (src, raw) in sorted(selected.items())},
            'localReferences': sorted(links, key=lambda x: (x['from'], x['to']))})
        manifest = dict(schemaVersion=1, packageId='company.skills.' + slug, name=info['displayName'],
                        desc=info['desc'], platform='Claude', type='Skill', entryPoint='SKILL.md', guideFile='INSTALL.md',
                        requiredFiles=[entry, 'install_skill.py', 'install_scope.py', 'PACKAGE_CONTENTS.json', 'PACKAGE_SOURCE.json'],
                        requirements=info['requirements'], workTags=info['workTags'], workflow=info['workflow'],
                        environment='Claude Code · ' + ('Company Agent 필요' if info['runtimeRequired'] else '단독 Skill'),
                        changes=f'하네스 {version} 현재 파일 기준. 원본·상대 참조 보존 및 플랫폼 등록 정보 포함. 실제 게시 번호는 플랫폼에서 부여합니다.')
        files['ai-square.json'] = encoded(manifest)
        files['PACKAGE_CONTENTS.json'] = encoded({'files': {p: digest(raw) for p, raw in sorted(files.items())}})
        package = stage / 'packages' / slug
        for name, raw in sorted(files.items()):
            path = package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            os.utime(path, (946684800, 946684800))
        target = stage / (slug + '.zip')
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(contract / 'scripts/prepare_package.py'),
                                 str(package), str(target)], capture_output=True, text=True, encoding='utf-8', timeout=120)
        if result.returncode:
            raise ValueError(f'{slug}: 최신 플랫폼 규격 검사 실패\n{result.stderr.strip()}\n{result.stdout.strip()}')
        check_zip(target, files)
        artifacts[target.name] = target.read_bytes()
        rows.append(dict(slug=slug, file=target.name, name=info['displayName'], description=info['desc'],
                         packageId=manifest['packageId'], runtimeRequired=info['runtimeRequired'],
                         type='Skill', legacyAlias=False, installName=install_name,
                         sha256=digest(artifacts[target.name]), size=len(artifacts[target.name]), files=len(files)))
    extra_rows, extra_files = external_packages(root, contract)
    if (artifacts.keys() & extra_files.keys() or
            {r['packageId'] for r in rows} & {r['packageId'] for r in extra_rows} or
            {r['slug'] for r in rows} & {r['slug'] for r in extra_rows}):
        raise ValueError('스킬과 외부 패키지 이름·ID가 충돌합니다.')
    rows.extend(extra_rows)
    artifacts.update(extra_files)
    excluded = [dict(slug=slug, name=info['displayName'], reason=info['distributionReason'])
                for slug, info in metadata.items() if info.get('distribution') == 'harness-only'
                and 'company-agent-plugin/skills/' + slug + '/SKILL.md' in tree]
    artifacts['등록_설치_안내.html'] = index_html(rows, version, standard_sha, excluded)
    artifacts['SHA256SUMS.txt'] = ('\n'.join(f'{r["sha256"]}  {r["file"]}' for r in rows) + '\n').encode()
    artifacts['catalog.json'] = encoded(dict(generator='company-platform-skills-v1', sourceMode='working-tree',
        sourceVersion=version, distributionStandard={'sha256': standard_sha, 'files': standard_hashes,
                                                    'textNormalization': TEXT_NORMALIZATION},
        packages=rows, harnessOnly=excluded, managedFiles={name: digest(raw) for name, raw in sorted(artifacts.items())}))
    return artifacts


def reconcile(output, artifacts, check=False):
    output = no_links(output)
    catalog_path = output / 'catalog.json'
    old = {}
    if catalog_path.exists():
        no_links(catalog_path)
        catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
        if catalog.get('generator') != 'company-platform-skills-v1':
            raise ValueError('다른 용도로 만든 catalog.json은 덮어쓰지 않습니다.')
        old = catalog['managedFiles']
    if any('/' in n or '\\' in n or n in {'.', '..'} or ':' in n for n in old):
        raise ValueError('잘못된 관리 파일 목록입니다.')
    changed = [n for n, raw in artifacts.items() if not (output/n).exists() or no_links(output/n).read_bytes() != raw]
    obsolete = sorted(set(old) - artifacts.keys())
    if check:
        return changed + obsolete
    for name in set(old) | set(artifacts):
        target = no_links(output / name)
        if target.exists() and name != 'catalog.json':
            current = digest(target.read_bytes())
            if current != old.get(name) and current != digest(artifacts.get(name, b'')):
                raise ValueError('수정되었거나 다른 파일이 있어 보존합니다: ' + name)
    if not changed and not obsolete:
        return []
    output.mkdir(parents=True, exist_ok=True)
    # Retire removed skills recoverably, only after validating ownership above.
    for name in obsolete:
        target = output / name
        if target.exists():
            retired = no_links(output / '.previous' / old[name] / name)
            if retired.exists():
                raise ValueError('기존 보관 파일이 있습니다: ' + name)
            retired.parent.mkdir(parents=True, exist_ok=True)
            target.rename(retired)
    for name in sorted(changed, key=lambda n: n == 'catalog.json'):
        with tempfile.NamedTemporaryFile(prefix='.package-', dir=output, delete=False) as temp:
            staged = Path(temp.name)
            temp.write(artifacts[name])
        try:
            os.replace(staged, output / name)
        finally:
            if staged.exists():
                staged.unlink()
    return changed + obsolete


def main():
    parser = argparse.ArgumentParser(description='현재 하네스 스킬을 플랫폼 등록용 ZIP으로 생성합니다. 설치·게시하지 않습니다.')
    parser.add_argument('--distribution-skill', type=Path, default=DEFAULT_STANDARD)
    parser.add_argument('--output', type=Path, default=ROOT / 'skills_zip')
    parser.add_argument('--check', action='store_true', help='최신 여부만 검사. 결과 폴더는 변경하지 않음')
    args = parser.parse_args()
    output = no_links(args.output)
    lock = None
    try:
        if output in {ROOT, ROOT.parent, Path.home(), Path(output.anchor)}:
            raise ValueError('전용 배포 폴더를 지정하세요.')
        if (output / '.build.lock').exists():
            raise ValueError('다른 패키지 생성이 진행 중입니다. 종료 여부를 확인하세요.')
        if not args.check:
            output.mkdir(parents=True, exist_ok=True)
            candidate_lock = output / '.build.lock'
            with candidate_lock.open('x', encoding='ascii') as handle:
                handle.write(str(os.getpid()))
            lock = candidate_lock
        temp_root = no_links(ROOT / '.smoke/platform-skills')
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='build-', dir=temp_root) as tmp:
            artifacts = build(ROOT, args.distribution_skill, Path(tmp), SUPPORT / 'catalog-metadata.json')
            changes = reconcile(output, artifacts, args.check)
        count = len(json.loads(artifacts['catalog.json'])['packages'])
        print(json.dumps({'packages': count, 'status': 'stale' if args.check and changes else 'current',
                          'changedFiles': changes, 'installed': False, 'published': False}, ensure_ascii=False))
        return 1 if args.check and changes else 0
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as error:
        print('배포 ZIP 생성 중단: ' + str(error), file=sys.stderr)
        return 2
    finally:
        if lock is not None:
            lock.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
