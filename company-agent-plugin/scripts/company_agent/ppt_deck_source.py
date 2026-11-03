"""Read text edits from our own offline deck, preserving its native chart scene.

Only declarative JSON and the marked text slots are read. Source scripts, CSS,
URLs and image paths are never executed or opened. This is the explicit native
deck route for edits made with the generated UI, not arbitrary HTML conversion.
"""
from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re

from .business_artifacts import ArtifactError, _source
from . import ppt_scene

SCENE_ID = 'company-agent-ppt-scene'
FORMAT = 'editable-scene-v1'
LIMIT = 16 * 1024 * 1024
_THEME_KEYS = {'title', 'accent', 'text', 'muted', 'background', 'tint'}


def _invalid(message):
    raise ArtifactError('invalid_native_deck', message)


def _text(value, limit=12000):
    if not isinstance(value, str) or len(value) > limit:
        _invalid('발표 HTML의 문구 길이와 형식을 확인해 주세요.')
    return value


class _DeckReader(HTMLParser):
    void = set('area base br col embed hr img input link meta param source track wbr'.split())
    inline = set('span b strong i em u s small sub sup br div p'.split())

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.payloads = []
        self.script = None
        self.format_count = 0
        self.body_count = 0
        self.slides = []
        self.slide = None
        self.active = None
        self.edits = {}
        self.title_slots = set()

    def handle_starttag(self, tag, attrs):
        if len(attrs) != len({key for key, _ in attrs}):
            _invalid('중복된 HTML 속성이 있습니다. 기본 발표본에서 다시 저장해 주세요.')
        values = dict(attrs)
        if self.active and tag not in self.inline:
            _invalid('문구 편집 영역에 지원하지 않는 요소가 있습니다. 발표본의 문구 편집으로 저장해 주세요.')
        if tag == 'meta' and values.get('name') == 'ppt-deck-format':
            if values.get('content') != FORMAT:
                _invalid('지원하지 않는 발표 HTML 형식입니다.')
            self.format_count += 1
        if tag == 'body':
            if values.get('data-ppt-deck') != '1':
                _invalid('이 파일은 편집 가능한 기본 발표 HTML이 아닙니다.')
            self.body_count += 1
        if tag == 'script':
            self.script = values.get('id') == SCENE_ID
            if self.script:
                if values.get('type') != 'application/json':
                    _invalid('발표 배치 기록은 JSON이어야 합니다.')
                self.payloads.append('')
        classes = (values.get('class') or '').split()
        if 'ppt-slide' in classes:
            if self.slide is not None:
                _invalid('발표 장이 중첩되어 있습니다.')
            self.slide = (len(self.stack), len(self.slides))
            self.slides.append(values.get('data-slide'))
        identity = values.get('data-edit')
        if identity is not None:
            if self.active or self.slide is None or not re.fullmatch(r'p\d+-e\d+(?:-r\d+|-c\d+-\d+)?', identity):
                _invalid('발표 문구의 편집 위치가 올바르지 않습니다.')
            if identity in self.edits:
                _invalid('중복된 발표 문구 편집 위치가 있습니다.')
            self.edits[identity] = {'parts': [], 'slide': self.slide[1], 'block_break': False}
            self.active = (len(self.stack), identity)
            if values.get('data-deck-title') == 'true':
                self.title_slots.add(identity)
        elif self.active and tag in ('br', 'div', 'p'):
            edit = self.edits[self.active[1]]
            parts = edit['parts']
            if tag == 'br' or (parts and not parts[-1].endswith('\n')):
                parts.append('\n')
            edit['block_break'] = False
        if tag not in self.void:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in self.void:
            return
        if not self.stack or self.stack[-1] != tag:
            _invalid('발표 HTML의 요소 구조가 맞지 않습니다. 브라우저에서 수정본 저장으로 다시 저장해 주세요.')
        depth = len(self.stack) - 1
        if self.active:
            if depth == self.active[0]:
                self.active = None
            elif tag in ('div', 'p'):
                # A block boundary separates following text; its closing tag
                # alone must not append a phantom final line to edited text.
                self.edits[self.active[1]]['block_break'] = True
        if self.slide and depth == self.slide[0]:
            self.slide = None
        if tag == 'script':
            self.script = None
        self.stack.pop()

    def handle_data(self, value):
        if self.script is True:
            self.payloads[-1] += value
        elif self.active:
            edit = self.edits[self.active[1]]
            parts = edit['parts']
            if value and edit['block_break'] and parts and not parts[-1].endswith('\n'):
                parts.append('\n')
            edit['block_break'] = False
            parts.append(value)


def _scene(raw, palette):
    from .ppt_html import frame_size
    if not isinstance(raw, dict):
        _invalid('발표 배치 기록을 확인하지 못했습니다.')
    frame = frame_size({key: raw.get(key) for key in ('width', 'height')})
    theme = raw.get('theme', palette)
    if not isinstance(theme, dict) or set(theme) != _THEME_KEYS:
        _invalid('발표 색상 기록을 확인하지 못했습니다.')
    theme = {key: ppt_scene.ink(value, {}) for key, value in theme.items()}
    font = _text(raw.get('font', 'Malgun Gothic'), 80)
    if not font.strip():
        _invalid('발표 글꼴 이름이 비어 있습니다.')
    pages = raw.get('pages')
    if not isinstance(pages, list) or not 1 <= len(pages) <= 60:
        _invalid('발표 HTML에는 1~60장이 있어야 합니다.')
    checked = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get('elements'), list):
            _invalid('발표 장의 배치 기록을 확인하지 못했습니다.')
        for element in page['elements']:
            if isinstance(element, dict) and element.get('kind') == 'image':
                value = element.get('image')
                if not isinstance(value, dict) or not isinstance(value.get('data'), str) or 'path' in value:
                    _invalid('발표 HTML의 이미지는 내장 자료여야 합니다. 외부 파일을 읽지 않았습니다.')
        checked.append({
            'title': _text(page.get('title', ''), 500),
            'background': ppt_scene.ink(page.get('background', 'FFFFFF'), theme),
            'elements': ppt_scene.elements(page['elements'], **frame, palette=theme, embedded=True),
            'notes': _text(page.get('notes', ''), 8000),
            'source': _text(page.get('source', ''), 1000),
        })
    return {**frame, 'font': font, 'theme': theme, 'pages': checked}


def read_deck(path, palette):
    """Return the validated scene plus current UI text, without a browser call.

    Native chart data and shape geometry remain those authored by the generator.
    External CSS/geometry edits are outside this explicit route. The caller must
    fingerprint this entire HTML and create a fresh review before PPT export.
    """
    source = _source(Path(path), ('.html', '.htm'))
    if source.stat().st_size > LIMIT:
        raise ArtifactError('html_too_large', '편집 발표 HTML은 16 MiB 이하로 나누어 주세요.')
    try:
        with source.open('rb') as stream:
            raw = stream.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ArtifactError('html_too_large', '편집 발표 HTML은 16 MiB 이하로 나누어 주세요.')
        reader = _DeckReader()
        reader.feed(raw.decode('utf-8-sig'))
        reader.close()
        if reader.stack or reader.active or reader.script is not None or reader.body_count != 1 or reader.format_count != 1 or len(reader.payloads) != 1:
            _invalid('발표 HTML의 편집 기록이 없거나 중복되어 있습니다. 기본 발표본의 수정본 저장을 사용해 주세요.')
        plan = _scene(json.loads(reader.payloads[0]), palette)
        if reader.slides != [f'P{i+1:02d}' for i in range(len(plan['pages']))]:
            _invalid('실제 HTML 장수나 순서가 배치 기록과 다릅니다.')
        expected = {}
        title_values = {}
        for pi, page in enumerate(plan['pages']):
            for ei, element in enumerate(page['elements']):
                prefix = f'p{pi}-e{ei}'
                if element['kind'] == 'text':
                    if element.get('runs'):
                        for ri, run in enumerate(element['runs']):
                            expected[f'{prefix}-r{ri}'] = (pi, run, 'text')
                    else:
                        expected[prefix] = (pi, element, 'text')
                elif element['kind'] == 'table':
                    table = element['table']
                    for ri, cells in enumerate([table['headers'], *table['rows']]):
                        for ci in range(len(cells)):
                            expected[f'{prefix}-c{ri}-{ci}'] = (pi, cells, ci)
        if set(reader.edits) != set(expected):
            _invalid('편집 문구가 추가되거나 빠졌습니다. 기존 배치로 임의 변환하지 않았습니다.')
        total = 0
        for identity, (pi, target, key) in expected.items():
            edit = reader.edits[identity]
            if edit['slide'] != pi:
                _invalid('문구가 다른 장으로 이동했습니다. 배치 수정은 다시 설계해 주세요.')
            value = _text(''.join(edit['parts']))
            total += len(value)
            target[key] = value
            if identity in reader.title_slots:
                title_values.setdefault(pi, []).append(value)
        if total > 200000:
            _invalid('전체 발표 문구가 너무 큽니다. 발표본을 나누어 주세요.')
        for pi, page in enumerate(plan['pages']):
            if pi in title_values:
                page['title'] = _text(''.join(title_values[pi]), 500)
            for element in page['elements']:
                if element.get('runs'):
                    element['text'] = ''.join(run['text'] for run in element['runs'])
            # Revalidate edited text/table sizes and the run/text relationship.
            page['elements'] = ppt_scene.elements(page['elements'], plan['width'], plan['height'], plan['theme'], embedded=True)
        plan['warnings'] = ['발표본의 문구 편집 내용을 반영했습니다. 도형 배치와 차트 데이터는 원래 설계를 유지하며 외부에서 변경한 CSS는 이 경로에 반영하지 않습니다.']
        return plan
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError):
        raise ArtifactError('invalid_native_deck', '발표 HTML의 배치와 문구 기록을 읽지 못했습니다. 기본 발표본의 수정본 저장으로 다시 준비해 주세요.') from None
