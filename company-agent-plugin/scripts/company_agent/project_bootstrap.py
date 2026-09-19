"""Create a small project-only CLAUDE.md on a work request, never overwrite.

This is a deterministic starting brief, not a nested CLI /init invocation or a
claim that the codebase has been analysed. No recursive scan or model call.
"""
from __future__ import annotations

import os
from pathlib import Path
import re

from .business_safety import safe_path

_WORK = re.compile(r'(만들어|고쳐|읽어|(?:작성|생성|구현|수정|분석|요약|정리|파악|테스트|검증|실행)\s*(?:해|진행|부탁))|\b(read|create|write|implement|fix|test|analyze|analyse|summarize|make|build|run)\b.{0,100}\b(file|project|code|report|test|document|app|folder|ppt|pptx|xlsx|docx)\b', re.I)
_NO_WRITE = re.compile(r'(만들|생성|작성|수정|변경|저장|실행|편집).{0,15}(하지\s*마|금지|말고|말아)|읽기\s*전용|(?:계획|설명|방법|검토)만|\b(read.only|plan.only|do not (?:write|create|modify|change)|don.t (?:write|create|modify|change))\b', re.I)
_ENTRY_POINTS = ('README.md', 'AGENTS.md', 'package.json', 'pyproject.toml', 'requirements.txt', 'Makefile', 'pom.xml', 'Cargo.toml', 'go.mod')


def initialize(cwd, payload):
    prompt = payload.get('prompt', payload.get('user_prompt', ''))
    if (payload.get('hook_event_name') != 'UserPromptSubmit' or payload.get('permission_mode') == 'plan'
            or not isinstance(prompt, str) or prompt.lstrip().startswith('/')
            or re.search(r'(?<![A-Za-z0-9])claude(?:\.local)?\.md(?![A-Za-z0-9])', prompt, re.I)
            or not _WORK.search(prompt[:12000]) or _NO_WRITE.search(prompt[:12000])):
        return ''
    try:
        folder = safe_path(cwd, exists=True)
        home = Path.home().absolute()
        if not folder.is_dir() or folder == Path(folder.anchor) or folder in {home, home/'Desktop', home/'Documents', home/'Downloads'}:
            return ''
        if {p.casefold() for p in folder.parts} & {'.claude', '.codex', '.git', 'node_modules', '.venv'}:
            return ''
        for key in ('WINDIR', 'ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA', 'APPDATA',
                    'CLAUDE_CONFIG_DIR', 'COMPANY_AGENT_USER_STATE', 'COMPANY_AGENT_KNOWLEDGE_BASE', 'CLAUDE_PLUGIN_ROOT'):
            value = os.environ.get(key)
            if value and folder.is_relative_to(Path(value).absolute()):
                return ''
        # Check fixed names only; no recursive or unrestricted directory listing.
        target = safe_path(folder/'CLAUDE.md')
        if target.exists() or safe_path(folder/'claude.md').exists() or safe_path(folder/'.claude/CLAUDE.md').exists():
            return ''
        # An inherited project brief already describes this nested folder.
        for ancestor in folder.parents:
            if ancestor in {home, Path(folder.anchor)}:
                break
            if (ancestor/'CLAUDE.md').exists() or (ancestor/'claude.md').exists() or (ancestor/'.claude/CLAUDE.md').exists():
                return ''
        entries = [name for name in _ENTRY_POINTS if safe_path(folder/name).is_file()]
        text = ('# 프로젝트 작업 안내\n\n'
                '<!-- Company Agent: 작업 시작 시 최초 1회 생성한 기본 안내. 프로젝트 분석 완료를 뜻하지 않습니다. -->\n\n'
                '## 적용 범위\n\n'
                '- 이 폴더의 작업 방법만 기록합니다. 회사 공통 정책이나 개인 전체 설정을 바꾸지 않습니다.\n'
                '- 개인 기억·스킬은 개인 영역, 이 프로젝트에서만 쓸 항목은 프로젝트 영역에 저장합니다. 저장 전 범위를 확인합니다.\n\n'
                '## 기본 작업 방식\n\n'
                '- 질문·선택지·피드백·진행 안내는 기본 한국어로 작성합니다. 명시적으로 요청한 다른 언어는 해당 범위에만 적용합니다.\n'
                '- 사용 가능한 스킬의 용도를 먼저 확인하고, 맞는 스킬이 있으면 본문을 읽어 적용합니다. 없으면 일반 작업을 진행합니다.\n'
                '- 기존 파일과 사용자 변경을 보존합니다. 파괴적 작업·외부 전송·보호 자료 처리는 적용 중인 승인과 회사 정책을 따릅니다.\n'
                '- 실제로 확인한 결과와 미확인 범위를 구분합니다. 원문·비밀·개인정보를 이 파일에 저장하지 않습니다.\n\n'
                '## 프로젝트별 확인 사항\n\n')
        text += ('먼저 확인할 기존 파일: ' + ', '.join(f'`{name}`' for name in entries) + '.\n\n') if entries else ''
        text += '실행·검증 명령과 프로젝트 고유 규칙은 아직 확인하지 않았습니다. 작업 중 실제로 확인한 내용만 사용자 요청에 따라 보완합니다. 자동 학습은 이 파일을 덮어쓰지 않습니다.\n'
        # Exclusive creation: a competing initializer/user write wins unchanged.
        with target.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
        return f'작업 폴더에 기본 CLAUDE.md를 처음 생성했습니다: {target}. 프로젝트 전체 분석이나 /init 실행은 아닙니다. 이 파일을 한 번 읽고 적용하되 초기화 명령을 중복 실행하지 마세요. 기존 회사·개인·프로젝트 지침을 보존하세요.'
    except FileExistsError:
        return ''
    except (OSError, ValueError):
        return '기본 CLAUDE.md 자동 생성을 건너뛰었습니다. 경로·쓰기 제한을 우회하거나 관리자 권한을 요청하지 말고 허용된 원래 작업만 진행하세요.'
