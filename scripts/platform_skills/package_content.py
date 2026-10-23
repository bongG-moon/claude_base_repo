"""Formatting and dependency closure for platform Skill packages."""
from __future__ import annotations
import hashlib
import json
import posixpath
import re
from pathlib import Path, PurePosixPath

EXTRAS = {
    'presentation': ['skills/company-agent/references/business-protection.md', 'skills/company-agent/references/output-delivery.md'],
    'html-report': ['skills/company-agent/references/business-protection.md', 'skills/company-agent/references/output-delivery.md', 'skills/presentation/references/image-review.md', 'skills/presentation/references/reference-inputs.md'],
    'file-organizer': ['skills/company-agent/references/business-protection.md'],
    'platform-mcp-builder': ['skills/asset-factory'],
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def source_files(slug, info, tree):
    source = info['sourceDir'].replace('\\', '/')
    if Path(source).is_absolute():
        raise ValueError("sourceDir must be repo-relative")
    prefix = source.rstrip('/') + '/'
    # Original paths remain unchanged inside source/, so sibling references work.
    available = {p.removeprefix('company-agent-plugin/'): (p, b)
                 for p, b in tree.items() if p.startswith('company-agent-plugin/')}
    for p, raw in tree.items():
        if p.startswith(prefix):
            available[f'skills/{slug}/' + p[len(prefix):]] = (p, raw)
    selected = {}

    def add(path):
        matches = [p for p in available if p == path or p.startswith(path.rstrip('/') + '/')]
        if not matches:
            raise ValueError('Missing dependency: ' + path)
        for p in matches:
            parts = PurePosixPath(p).parts
            if any(x.startswith('.') or x in {'__pycache__', 'tests'} for x in parts):
                continue
            if p.endswith(('runtime-source.json', '시험안내.md', '.pyc')):
                continue
            selected[p] = available[p]

    add('skills/' + slug)
    for extra in EXTRAS.get(slug, []) + info.get('packaging', {}).get('includeAdditionalPaths', []):
        add(extra)
    add('THIRD_PARTY_NOTICES.md')
    add('licenses')
    # Follow actual local Markdown/backtick references recursively. Runtime command
    # names and illustrative paths that do not exist in Git are not invented.
    scanned = set()
    resolved = []
    while pending := [p for p in selected if p.endswith('.md') and p not in scanned]:
        for p in pending:
            scanned.add(p)
            text = selected[p][1].decode('utf-8-sig')
            refs = re.findall(r'\]\(([^)]+)\)', text)
            refs += re.findall(r'`([^`\n]+)`', text)
            for ref in refs:
                ref = ref.split('#')[0].strip().strip('<>')
                if not ref or '://' in ref or '<' in ref or re.search(r'\s', ref):
                    continue
                path = posixpath.normpath(posixpath.join(posixpath.dirname(p), ref))
                if path in available:
                    add(path)
                    resolved.append({'from': p, 'to': path})
    return selected, resolved


def make_guide(slug, info, install_name, version):
    dependency = ('Company Agent 하네스 없이 사용합니다. 아래 의존성은 별도로 필요합니다.'
                  if not info['runtimeRequired'] else
                  f'Company Agent {version} 소스를 기준으로 작성했습니다. 해당 기능을 제공하는 기존 설치와 활성 세션이 필요합니다. 이 ZIP은 하네스·후크·작업자·MCP 연결을 설치하지 않습니다. 일반 Claude에 ZIP만 복사해도 모든 기능이 동작하는 독립 도구가 아닙니다.')
    return f'''# {info['displayName']} — 설치와 사용

{info['desc']}

## 사용 환경
{dependency}
''' + '\n'.join('- ' + r for r in info['requirements']) + f'''
- 포함된 설치 도우미는 Python 3.11 이상과 표준 라이브러리만 사용합니다.

## 먼저 설치 범위 선택
1. ZIP을 별도의 폴더에 압축 해제합니다. 설치기를 실행한다고 자동으로 전역 설치되지 않습니다.
2. **현재 프로젝트** 또는 **내 계정 전역** 중 직접 선택합니다. 전역은 모든 PC 사용자가 아니라 본인 계정입니다.
3. PowerShell에서 실제 업무 폴더로 이동한 뒤 아래 명령에서 압축 해제한 설치기의 경로를 넣습니다.

```powershell
python -X utf8 "압축해제폴더/install_skill.py"
```

프로그램이 설치 범위와 실제 대상 경로를 보여줍니다. 빈 선택은 전역 설치로 처리하지 않으며 q로 취소할 수 있습니다. 프로젝트 위치를 명시하려면 다음처럼 실행합니다.

```powershell
python -X utf8 "압축해제폴더/install_skill.py" --scope project --project-dir "업무폴더의 절대경로"
```

실행 전에 경로만 확인하려면 `--dry-run`을 더합니다. 비대화형 실행은 `--scope project` 또는 `--scope user`와 `--yes`를 모두 직접 지정해야 합니다. 의존성 설치, Claude 설정·모델·MCP·후크 변경은 하지 않습니다.

## 수동 설치도 가능
- 프로젝트 선택: `<업무폴더>/.claude/skills/{install_name}/`를 새로 만들고 ZIP의 모든 파일을 그 안에 복사합니다.
- 내 계정 전역 선택: `~/.claude/skills/{install_name}/`에 복사합니다. `CLAUDE_CONFIG_DIR`를 사용하는 환경은 해당 설정 폴더의 `skills/{install_name}/`를 사용합니다.
- `SKILL.md` 하나만 복사하지 마세요. `source/`의 Python 코드·참고자료·리소스가 함께 있어야 합니다.
- 같은 이름의 설치 폴더가 이미 있으면 덮어쓰지 말고 기존 폴더를 별도 백업한 뒤 새 패키지를 설치합니다. 플러그인 캐시와 개인 기억·지식 저장소는 변경하지 않습니다.

## 실행
Claude Code에서 해당 프로젝트를 열고 새 대화를 시작한 뒤 `/{install_name}`와 함께 할 일을 적습니다. 실제 본문은 `source/skills/{slug}/SKILL.md`에 있습니다. 그 본문에서 말하는 스킬 폴더는 해당 하위 폴더입니다.
{('이 항목은 이전 이름 호환용입니다. 신규 사용자는 스킬·도구 제작 도우미(asset-factory)를 우선 사용하세요.' if slug == 'platform-mcp-builder' else '')}

## 새 버전 및 제거
P&T AI SQUARE의 같은 도구에서 새 버전을 등록합니다. `packageId`는 그대로 유지하고 파일·안내·흐름을 새 내용으로 갱신합니다. 플랫폼이 배포 번호를 부여합니다. 이 패키지에는 아직 게시 후의 도구 ID나 배포 번호가 없으므로 자동 버전 조회를 연결했다고 표시하지 않습니다.
제거는 위에서 본인이 선택한 `skills/{install_name}` 폴더만 삭제합니다. 설치 도우미가 추가로 설정한 항목은 없습니다.

## 플랫폼 등록
도구 등록 → 파일 선택에서 이 ZIP 자체를 선택합니다. 이름·설명·프로그램 Claude·유형 Skill·업무 태그·설치 안내·동작 흐름이 배포 정보에서 읽힙니다. 조직·업무 분류와 공개/승인 필요 여부는 등록자가 화면에서 선택합니다. 이 ZIP을 만든 작업은 서버 게시나 실제 PC 설치를 수행하지 않습니다.

설치 위치 참고: https://code.claude.com/docs/en/skills
'''
