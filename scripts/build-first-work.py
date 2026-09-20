"""Refresh the offline guide's course section from the UI's single JSON source."""
from __future__ import annotations
import html
import base64
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RESOURCE = ROOT / 'company-agent-plugin/resources'


def embed_manual_font(page: str) -> str:
    """Use the same offline subset as the integrated guide, with no font install."""
    folder = ROOT / 'scripts/assets/manual-font'
    font = (folder / 'NotoSansKR-guide.woff').read_bytes()
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256(font).hexdigest() != manifest['sha256']:
        raise ValueError('Manual font hash mismatch')
    license_text = (folder / 'OFL.txt').read_text(encoding='utf-8').replace('--', '—')
    page = re.sub(r'<!-- manual-font:start -->[\s\S]*?<!-- manual-font:end -->\n?', '', page)
    css = "@font-face{font-family:'Noto Sans KR';font-style:normal;font-weight:400 700;font-display:swap;src:url(data:font/woff;base64," + base64.b64encode(font).decode('ascii') + ") format('woff')}"
    css += "body,button,textarea,code{font-family:'Noto Sans KR','Malgun Gothic',sans-serif}textarea{font-size:14px;line-height:1.9}body{word-break:keep-all;overflow-wrap:anywhere}"
    fragment = '<!-- manual-font:start -->\n<!-- Noto Sans KR subset.\n' + license_text + '\n-->\n<style>' + css + '</style>\n<!-- manual-font:end -->\n'
    if 'font-src data:' not in page:
        page = page.replace("style-src 'unsafe-inline';", "style-src 'unsafe-inline'; font-src data:;")
    page = page.replace('</head>', fragment + '</head>')
    visible = html.unescape(re.sub(r'<style>[\s\S]*?</style>|<script>[\s\S]*?</script>|<!--[\s\S]*?-->|<[^>]+>', '', page))
    missing = {c for c in visible if c.isprintable()} - set(manifest['characters'])
    if missing:
        raise ValueError('Refresh manual font subset for: ' + ''.join(sorted(missing)))
    return page


def render():
    course = json.loads((RESOURCE / 'onboarding-course.json').read_text(encoding='utf-8'))
    shell = (RESOURCE / 'first-work.html').read_text(encoding='utf-8')
    # Keep the existing offline shell, security policy and clipboard fallback.
    before = shell.split('<nav aria-label="첫 업무 선택">', 1)[0]
    after = '<section id="help">' + shell.split('<section id="help">', 1)[1]
    esc, parts = html.escape, []
    nav = ''.join('<a href="#' + s['id'] + '">' + esc(s['title']) + '</a>' for s in course['steps'])
    parts.append('<nav aria-label="첫 업무 선택">' + nav + '</nav><p id="status" role="status" aria-live="polite"></p>')
    parts.append('<section id="onboarding-start"><h2>시작하기</h2>'
                 '<p>처음에는 가상 자료를 만들고 읽는 연습부터 해보세요. 회사 자료나 참고 파일은 필요 없습니다.</p>'
                 '<nav aria-label="사용 설명서"><a href="manuals/Company-Agent-Guide.html">통합 가이드 · 준비물 없이 시작하기</a>'
                 '<a href="manuals/README.md">Markdown 안내서 · 목차</a></nav>'
                 '<p class="muted">이미 익숙하다면 아래에서 필요한 예문을 골라 사용하세요.</p></section>')
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
    return embed_manual_font(before + '\n'.join(parts) + '\n' + after)


if __name__ == '__main__':
    (RESOURCE / 'first-work.html').write_text(render(), encoding='utf-8', newline='\n')
