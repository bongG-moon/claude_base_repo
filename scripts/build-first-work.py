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
