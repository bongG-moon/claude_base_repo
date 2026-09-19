"""Refresh the offline guide's course section from the UI's single JSON source."""
from __future__ import annotations
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOURCE = ROOT / 'company-agent-plugin/resources'


def render():
    course = json.loads((RESOURCE / 'onboarding-course.json').read_text(encoding='utf-8'))
    shell = (RESOURCE / 'first-work.html').read_text(encoding='utf-8')
    # Keep the existing offline shell, security policy and clipboard fallback.
    before = shell.split('<nav aria-label="첫 업무 선택">', 1)[0]
    after = '<section id="help">' + shell.split('<section id="help">', 1)[1]
    esc, parts = html.escape, []
    nav = ''.join('<a href="#' + s['id'] + '">' + esc(s['title']) + '</a>' for s in course['steps'])
    parts.append('<nav aria-label="첫 업무 선택">' + nav + '</nav><p id="status" role="status" aria-live="polite"></p>')
    parts.append('<section id="onboarding-start"><h2>처음이라면 전체 코스부터</h2>'
                 '<p>준비하기 → 자료 읽기 → 결과 만들기 → 수정 → 내 방식 저장 → 새 업무에서 재사용 순서로 따라 해보세요. '
                 '각 단계에 요청 예문, 성공 확인 기준, 막혔을 때의 방법이 있습니다. 저장 단계는 선택입니다.</p>'
                 '<p>회사 공통 / 개인 전체 / 이 프로젝트를 먼저 구분합니다. 각 범위 안에서 기억·지식과 업무 구성을 확인합니다. 새 기억·스킬 저장은 개인 전체 또는 이 프로젝트를 선택합니다.</p>'
                 '<p>더 익숙해지면 전체 코스의 6–8단계에서 공통·내 기억 비교, 공통·내 하네스와 폴더 적용 범위의 차이, '
                 '개인 스킬·계산 도구 만들기도 실습할 수 있습니다. 확장 실습은 선택입니다.</p>'
                 '<nav aria-label="사용 설명서"><a href="manuals/Company-Agent-Guide.html">통합 가이드 · 준비물 없이 시작하기</a></nav>'
                 '<p class="muted">읽기만 해도 됩니다. 안내서를 여는 것만으로 AI 호출·설정 변경·업무 실행은 하지 않습니다. '
                 '이미 익숙하다면 아래 필요한 예문부터 바로 사용하세요.</p></section>')
    parts.append('<p>' + esc(course['intro']) + ' 저장 요청은 동의할 때만 보내세요.</p>')
    for step in course['steps']:
        body = '<section id="' + step['id'] + '"><h2>' + esc(step['title']) + '</h2><p>' + esc(step['concept']) + '</p>'
        for key, label in [('prompt', '요청 복사'), ('alternativePrompt', '다른 방법으로 연습')]:
            if key not in step:
                continue
            field = 'prompt-' + step['id'] + ('-alternative' if key != 'prompt' else '')
            body += '<label for="' + field + '">' + esc(step['title'] + ' · ' + label) + '</label>'
            body += '<textarea id="' + field + '" readonly>' + esc(step[key]) + '</textarea><button data-copy="' + field + '">' + label + '</button>'
        body += '<p class="check">확인할 것 · ' + esc(step['check']) + '</p><details><summary>잘 안될 때</summary><p>' + esc(step['recovery']) + '</p></details></section>'
        parts.append(body)
    return before + '\n'.join(parts) + '\n' + after


if __name__ == '__main__':
    (RESOURCE / 'first-work.html').write_text(render(), encoding='utf-8', newline='\n')
