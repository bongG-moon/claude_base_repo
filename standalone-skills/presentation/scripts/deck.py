"""고정 한글 발표 양식에 내용만 채웁니다. 외부 통신이나 모델 호출은 없습니다."""
from __future__ import annotations
import argparse
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys

TEMPLATE = Path(__file__).resolve().parents[1] / 'assets/korean-report-deck.html'
TAGS = {'div', 'span', 'p', 'h2', 'h3', 'h4', 'strong', 'b', 'i', 'br', 'table',
        'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'ul', 'ol', 'li', 'blockquote'}
CLASSES = set('columns equal ratio-45 ratio-52 ratio-40 ratio-55 column region-title smaller '
              'context-line dark gray down-arrow eyebrow soft-note left matrix comparison '
              'p01-body top-comparison starting-panel build-step number boundary-cards boundary-card '
              'boundary-no flow-cell problem-flow flow-break break-symbol continuity-summary '
              'agent-diagram agent-user double-arrow agent-core asset-links asset-cards asset-card solid '
              'expansion-cards expansion-card result expansion-bottom emphasis-line phase-cards '
              'phase-card reuse-return output-row arrow local-access'.split())


class Body(HTMLParser):
    """허용한 컴포넌트와 텍스트만 출력하고 편집 표시를 자동으로 붙입니다."""
    def __init__(self, slide_id):
        super().__init__(convert_charrefs=True)
        self.slide_id, self.parts, self.stack, self.number = slide_id, [], [], 10

    def handle_starttag(self, tag, attrs):
        if tag not in TAGS:
            raise ValueError(f'본문에 허용하지 않는 태그입니다: {tag}')
        clean = []
        for key, value in attrs:
            if key == 'class' and value and set(value.split()) <= CLASSES:
                clean.append(('class', value))
            elif key in ('colspan', 'rowspan') and tag in ('td', 'th') and value and re.fullmatch(r'[1-9]|[1-2][0-9]|30', value):
                clean.append((key, value))
            elif key == 'aria-hidden' and value in ('true', 'false'):
                clean.append((key, value))
            else:
                raise ValueError(f'본문에 허용하지 않는 속성 또는 클래스입니다: {key}')
        self.parts.append('<' + tag + ''.join(' '+k+'="'+escape(v, quote=True)+'"' for k,v in clean) + '>')
        if tag != 'br':
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise ValueError('본문 태그의 시작과 끝을 맞춰 주세요.')
        self.parts.append('</' + tag + '>')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != 'br':
            self.handle_endtag(tag)

    def handle_data(self, data):
        if not data.strip():
            self.parts.append(escape(data))
            return
        if self.stack and self.stack[-1] in ('table', 'thead', 'tbody', 'tfoot', 'tr'):
            raise ValueError('표의 텍스트는 th 또는 td 안에 작성해 주세요.')
        self.number += 1
        self.parts.append(f'<span data-edit="{self.slide_id}-{self.number:03d}">{escape(data)}</span>')

    def handle_comment(self, data):
        raise ValueError('본문에는 주석 대신 실제 내용만 작성해 주세요.')

    def handle_decl(self, decl):
        raise ValueError('본문에는 문서 선언을 넣지 않습니다.')

    def unknown_decl(self, data):
        raise ValueError('본문에는 문서 선언을 넣지 않습니다.')


def text(row, key, limit=6000, required=False):
    value = row.get(key, '')
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'{key}: 비어 있지 않은 문자열과 길이를 확인해 주세요.')
    return value


def render(spec):
    if not isinstance(spec, dict) or set(spec) - {'title', 'slides'}:
        raise ValueError('내용은 title과 slides를 가진 JSON 객체여야 합니다.')
    title = text(spec, 'title', 200, True)
    slides = spec.get('slides')
    if not isinstance(slides, list) or not 1 <= len(slides) <= 60:
        raise ValueError('슬라이드는 1~60장으로 작성해 주세요.')
    sections, notes, nav = [], {}, []
    for i, row in enumerate(slides, 1):
        if not isinstance(row, dict) or set(row) - {'title', 'kicker', 'hero', 'bodyHtml', 'takeaway', 'notes', 'source', 'reportStyle'}:
            raise ValueError(f'{i}장: 지원하는 내용 필드만 작성해 주세요.')
        sid = f'P{i:02d}'
        heading, hero, takeaway = (text(row, k, 300, True) for k in ('title', 'hero', 'takeaway'))
        body = Body(sid)
        body.feed(text(row, 'bodyHtml', 60000, True))
        body.close()
        if body.stack:
            raise ValueError(f'{i}장: 닫지 않은 본문 태그가 있습니다.')
        report_style = row.get('reportStyle', i > 1)
        if type(report_style) is not bool:
            raise ValueError('reportStyle은 true 또는 false여야 합니다.')
        sections.append(f'<section class="slide slide-p{i:02d}' + (' report-style' if report_style else '') +
            f'" data-slide="{sid}" data-kind="main"><header class="slide-header">'
            f'<h1 data-edit="{sid}-001">{escape(heading)}</h1><span class="kicker" data-edit="{sid}-002">{escape(text(row,"kicker",160))}</span></header>'
            f'<div class="hero" data-edit="{sid}-003">{escape(hero)}</div><div class="slide-body">' + ''.join(body.parts) + '</div>'
            f'<div class="takeaway" data-edit="{sid}-004">{escape(takeaway)}</div>'
            f'<footer class="page-number-only"><b>{i:02d} <span>/ {len(slides):02d}</span></b></footer></section>')
        notes[sid] = {'title': heading, 'html': '<p>'+escape(text(row,'notes')).replace('\n','<br>')+'</p>', 'source': text(row,'source',1000)}
        nav.append(f'<button data-goto="{sid}" aria-label="{i}페이지">{i}</button>')
    template = TEMPLATE.read_text(encoding='utf-8')
    template = template.replace('<!-- 각 슬라이드 section을 이 영역에 넣는다 -->', '\n'.join(sections))
    template = template.replace('<title>발표자료 | HTML 발표본</title>', '<title>'+escape(title)+' | HTML 발표본</title>')
    template = template.replace('<span class="chrome-title">발표자료</span>', '<span class="chrome-title">'+escape(title)+'</span>')
    template = re.sub(r'(<div class="nav-numbers"[^>]*>).*?(</div>)', lambda m: m[1]+''.join(nav)+m[2], template, count=1, flags=re.S)
    template = template.replace('1 / 3</span>', f'1 / {len(slides)}</span>').replace('본문 3장</h2>', f'본문 {len(slides)}장</h2>')
    # JSON의 </script> 문자열이 HTML 스크립트 태그를 닫지 못하도록 처리합니다.
    encoded = json.dumps(notes, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return re.sub(r'(<script id="deck-notes"[^>]*>).*?(</script>)', lambda m: m[1]+encoded+m[2], template, count=1, flags=re.S)


def main():
    parser = argparse.ArgumentParser(description='기존 한글 발표 양식을 유지하고 내용만 채워 HTML 만들기')
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        with args.spec.open('rb') as stream:
            raw = stream.read(2*1024*1024+1)
        if len(raw) > 2*1024*1024:
            raise ValueError('입력 JSON은 2MiB 이하로 나누어 주세요.')
        rendered = render(json.loads(raw.decode('utf-8-sig')))
        output = args.output.resolve()
        if output.suffix.lower() != '.html':
            raise ValueError('결과 파일은 .html이어야 합니다.')
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(rendered)
        result = {'ok': True, 'outputPath': str(output), 'previewUrl': output.as_uri(),
                  'previewLink': '[HTML 발표본 열기](<'+output.as_posix()+'>)',
                  'message': '발표본 링크를 사용자에게 보여 주세요. 실제 화면의 잘림과 내용 확인 후 승인본을 PPT로 변환합니다.',
                  'visualReview': 'not_verified', 'sourceTemplatePreserved': True}
    except (ValueError, OSError) as exc:
        result = {'ok': False, 'message': str(exc)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
