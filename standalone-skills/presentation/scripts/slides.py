"""Bundle newly authored HTML slides with an offline editor using only stdlib.

This path does not render a JSON layout or execute any source JavaScript.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET


ASSETS = Path(__file__).resolve().parents[1] / 'assets'
MAX_HTML = 20 * 1024 * 1024
MAX_ASSET = 10 * 1024 * 1024
VOID = set('area br col hr img input link meta param source track wbr'.split())
FORBIDDEN = set('base iframe frame frameset canvas form object embed applet portal fencedframe'.split())
SVG_TAGS = set(('svg g defs symbol use rect circle ellipse line polyline polygon path text tspan textpath '
                'title desc lineargradient radialgradient stop clippath mask pattern marker image filter '
                'fegaussianblur feoffset femerge femergenode feblend fecolormatrix fecomponenttransfer '
                'fefunca fefuncr fefuncg fefuncb feflood fecomposite fedropshadow').split())
EDIT_TAGS = set('h1 h2 h3 h4 h5 h6 p th td li figcaption blockquote dt dd'.split())
INLINE_TEXT = set('span strong em b i u s small mark sub sup br abbr code'.split())
ATTR = re.compile(r'''([^\s=/>]+)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?''')
CSS_URL = re.compile(r'''url\(\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|([^)]*))\s*\)''', re.I)
IMAGE_TYPES = {'.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.gif':'image/gif',
               '.webp':'image/webp', '.avif':'image/avif', '.svg':'image/svg+xml', '.ico':'image/x-icon'}
FONT_TYPES = {'.woff2':'font/woff2', '.woff':'font/woff', '.ttf':'font/ttf', '.otf':'font/otf'}
NAMESPACES = {'http://www.w3.org/2000/svg', 'http://www.w3.org/1999/xlink', 'http://www.w3.org/1999/xhtml'}


class BuildError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def fail(code, message):
    raise BuildError(code, message)


class Node:
    def __init__(self, tag='', attrs=(), original=None):
        self.tag = tag
        self.original = original or tag
        self.attrs = list(attrs)
        self.children = []
        self.parent = None

    def get(self, key, default=None):
        return next((v for k, v in self.attrs if k.lower() == key), default)

    def has(self, key):
        return any(k.lower() == key for k, _ in self.attrs)

    def set(self, key, value):
        for i, (k, _) in enumerate(self.attrs):
            if k.lower() == key:
                self.attrs[i] = (k, value)
                return
        self.attrs.append((key, value))

    def append(self, item):
        if isinstance(item, Node):
            item.parent = self
        self.children.append(item)

    def nodes(self):
        for item in self.children:
            if isinstance(item, Node):
                yield item
                yield from item.nodes()

    def render(self):
        content = ''.join(item.render() if isinstance(item, Node) else item for item in self.children)
        if not self.tag:
            return content
        if self.tag == 'style':
            # A local CSS file can contain this literal in a string/comment.
            # Keep its CSS value while preventing an HTML raw-text breakout.
            content = re.sub(r'</style', lambda m: '\\3c ' + m.group()[1:], content, flags=re.I)
        attrs = ''.join(' ' + k + ('' if v is None else '="' + html.escape(v, quote=True) + '"') for k, v in self.attrs)
        start = '<' + self.original + attrs + '>'
        return start if self.tag in VOID else start + content + '</' + self.original + '>'


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.root = Node()
        self.stack = [self.root]
        self.count = 0
        self.feed(source)
        self.close()
        if len(self.stack) != 1:
            fail('invalid_html', '닫지 않은 HTML 태그가 있습니다: ' + self.stack[-1].tag)

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > 50000 or len(self.stack) > 128:
            fail('html_too_complex', 'HTML 개체 수 또는 중첩 깊이가 너무 큽니다.')
        if len({k for k, _ in attrs}) != len(attrs):
            fail('invalid_html', '같은 속성을 중복한 HTML 태그가 있습니다.')
        raw = self.get_starttag_text()
        match = re.match(r'<\s*([^\s/>]+)', raw)
        names = [m.group(1) for m in ATTR.finditer(raw[match.end():].rstrip('>/'))]
        if len(names) != len(attrs) or any(a.lower() != b for a, (b, _) in zip(names, attrs)):
            fail('invalid_html', 'HTML 속성을 해석하지 못했습니다. 속성 값에 따옴표를 사용하세요.')
        node = Node(tag, [(name, value) for name, (_, value) in zip(names, attrs)], match.group(1))
        self.stack[-1].append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in VOID or len(self.stack) < 2 or self.stack[-1].tag != tag:
            fail('invalid_html', 'HTML 태그의 시작과 끝을 맞춰 주세요: ' + tag)
        self.stack.pop()

    def handle_data(self, data):
        self.stack[-1].append(data if self.stack[-1].tag in {'style', 'script'} else html.escape(data, quote=False))

    def handle_entityref(self, name):
        self.stack[-1].append('&' + name + ';')

    def handle_charref(self, name):
        self.stack[-1].append('&#' + name + ';')

    def handle_comment(self, data):
        if '--' in data:
            fail('invalid_html', '비표준 HTML 주석은 지원하지 않습니다.')
        self.stack[-1].append('<!--' + data + '-->')

    def handle_decl(self, decl):
        if decl.lower() != 'doctype html':
            fail('invalid_html', 'HTML5 doctype만 지원합니다.')

    def handle_pi(self, data):
        fail('invalid_html', 'HTML 처리 명령은 지원하지 않습니다.')

    def unknown_decl(self, data):
        fail('invalid_html', '외부 선언은 지원하지 않습니다.')


def local_path(value):
    raw = str(value)
    if not raw or '\x00' in raw or raw.startswith(('\\\\', '//')) or re.match(r'^[a-zA-Z]+://', raw):
        fail('unsafe_path', '명시한 로컬 파일 경로만 사용합니다.')
    path = Path(value).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or item.exists() and getattr(item.lstat(), 'st_file_attributes', 0) & 0x400:
            fail('unsafe_path', '연결 폴더 또는 심볼릭 링크는 사용하지 않습니다.')
    if any(':' in part for part in path.parts[1:]):
        fail('unsafe_path', '장치 경로나 대체 데이터 스트림은 사용하지 않습니다.')
    return path.resolve()


def read_bounded(path, limit, *, asset=False):
    if not path.is_file():
        fail('missing_asset' if asset else 'missing_source', '파일이 없습니다: ' + path.name)
    size = path.stat().st_size
    over_limit = size >= limit if asset else size > limit
    if over_limit:
        fail('asset_too_large' if asset else 'html_too_large', '자원은 각각 10MB 미만, HTML은 20MB 이하로 준비해 주세요.')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    over_limit = len(raw) >= limit if asset else len(raw) > limit
    if over_limit:
        fail('asset_too_large' if asset else 'html_too_large', '파일 크기 한도를 초과했습니다.')
    return raw


def css_unescape(value):
    value = re.sub(r'\\(?:\r\n|\r|\n|\f)', '', value)
    return re.sub(r'\\([0-9a-fA-F]{1,6})[ \t\r\n\f]?|\\([^\r\n\f])',
                  lambda m: chr(min(int(m.group(1), 16), 0x10ffff)) if m.group(1) else m.group(2), value)


class Resources:
    def __init__(self, root):
        self.root = root
        self.dependencies = set()

    def path(self, value, base):
        value = unquote(value.strip())
        url = urlsplit(value)
        if url.scheme or url.netloc or value.startswith(('/', '\\')) or '\\' in value or url.query or url.fragment:
            fail('external_resource', '외부 주소, 절대 자원 경로 또는 질의 문자열은 지원하지 않습니다.')
        path = local_path(base / url.path)
        if not path.is_relative_to(self.root):
            fail('resource_outside_source', '자원은 원본 HTML 폴더 안에서 명시한 파일만 사용합니다.')
        self.dependencies.add(path)
        return path

    def svg(self, raw):
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            fail('unsafe_svg', 'SVG 외부 선언은 지원하지 않습니다.')
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            fail('unsafe_svg', 'SVG 자원을 읽지 못했습니다.')
        for node in root.iter():
            tag = node.tag.rsplit('}', 1)[-1].lower()
            if tag not in SVG_TAGS:
                fail('unsafe_svg', 'SVG에 실행 또는 외부 콘텐츠 요소가 있습니다.')
            for key, value in node.attrib.items():
                name = key.rsplit('}', 1)[-1].lower()
                if name.startswith('on') or name in {'src', 'base'}:
                    fail('unsafe_svg', 'SVG의 실행 또는 외부 자원 속성은 지원하지 않습니다.')
                if name == 'href' and not value.startswith('#'):
                    fail('unsafe_svg', 'SVG 파일 내부의 외부 참조는 지원하지 않습니다.')
                if 'url' in css_unescape(value).lower() or name == 'style':
                    self.css(value, self.root, internal_only=True)

    def uri(self, value, base, *, kinds=None):
        value = value.strip()
        if value.startswith('#'):
            if re.search(r'[\s"\'<>\\()]', value):
                fail('unsafe_fragment', '내부 도형 참조의 id를 확인하세요.')
            return value
        if value.lower().startswith('data:'):
            match = re.fullmatch(r'data:([^;,]+);base64,([A-Za-z0-9+/=\s]+)', value, re.I)
            if not match or match.group(1).lower() not in set(IMAGE_TYPES.values()) | set(FONT_TYPES.values()):
                fail('unsafe_data_url', '이미지와 글꼴의 base64 data URL만 지원합니다.')
            mime = match.group(1).lower()
            if kinds and mime not in kinds:
                fail('unsafe_data_url', '이 요소에 맞는 이미지 또는 글꼴 자원이 필요합니다.')
            try:
                raw = base64.b64decode(re.sub(r'\s+', '', match.group(2)), validate=True)
            except ValueError:
                fail('unsafe_data_url', '올바른 base64 자원이 아닙니다.')
            if len(raw) >= MAX_ASSET:
                fail('asset_too_large', '각 이미지와 글꼴은 10MB 미만이어야 합니다.')
        else:
            path = self.path(value, base)
            mime = {**IMAGE_TYPES, **FONT_TYPES}.get(path.suffix.lower())
            if not mime or kinds and mime not in kinds:
                fail('unsupported_asset', '지원하는 로컬 이미지 또는 글꼴 파일을 지정하세요.')
            raw = read_bounded(path, MAX_ASSET, asset=True)
        if mime == 'image/svg+xml':
            self.svg(raw)
        return 'data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii')

    def css(self, value, base, *, internal_only=False):
        normalized = css_unescape(re.sub(r'/\*.*?\*/', '', value, flags=re.S))
        if re.search(r'@\s*import\b|expression\s*\(|(?:-moz-binding|behavior)\s*:|(?:-webkit-)?image-set\s*\(', normalized, re.I):
            fail('unsafe_css', 'CSS import, 실행 표현식 또는 image-set은 지원하지 않습니다.')
        matches = list(CSS_URL.finditer(value))
        if len(re.findall(r'url\s*\(', normalized, re.I)) != len(matches):
            fail('unsafe_css', 'CSS 자원은 일반 url(...) 표기로 작성하세요.')
        remainder = CSS_URL.sub('', normalized)
        if re.search(r'(?:https?|ftp|file|javascript|vbscript)\s*:|["\']\s*//', remainder, re.I):
            fail('external_resource', 'CSS의 외부 주소를 사용하지 않습니다.')
        def replace(match):
            url = css_unescape(next(v for v in match.groups() if v is not None).strip())
            if internal_only and not url.startswith('#'):
                fail('unsafe_svg', 'SVG 자원은 내부 도형 참조만 지원합니다.')
            return 'url("' + self.uri(url, base) + '")'
        return CSS_URL.sub(replace, value)


def validate_document(root, resources, base, warnings):
    for node in list(root.nodes()):
        if node.tag in FORBIDDEN:
            fail('unsafe_element', '실행 또는 외부 콘텐츠 요소는 지원하지 않습니다: ' + node.tag)
        parent = node.parent
        in_svg = node.tag == 'svg'
        while parent:
            in_svg = in_svg or parent.tag == 'svg'
            parent = parent.parent
        if in_svg and node.tag not in SVG_TAGS:
            fail('unsafe_svg', '지원하지 않는 SVG 요소입니다: ' + node.tag)
        for key, value in list(node.attrs):
            name = key.lower()
            value = value or ''
            if name.startswith('on') or name in {'srcdoc', 'ping', 'action', 'formaction', 'manifest', 'codebase', 'archive', 'srcset'}:
                fail('unsafe_attribute', '실행 또는 자동 자원 요청 속성은 지원하지 않습니다: ' + name)
            if name.startswith('xmlns'):
                if value not in NAMESPACES:
                    fail('unsafe_attribute', '지원하지 않는 XML 네임스페이스입니다.')
            elif name == 'style':
                node.set(name, resources.css(value, base))
            elif name in {'href', 'xlink:href', 'src', 'background', 'poster'}:
                if node.tag == 'link' and name == 'href':
                    continue
                if node.tag in {'img', 'image'}:
                    node.set(name, resources.uri(value, base, kinds=set(IMAGE_TYPES.values())))
                elif not value.startswith('#'):
                    fail('external_resource', '문서 링크는 내부 #장번호 참조만 지원합니다.')
            elif in_svg and 'url' in css_unescape(value).lower():
                node.set(name, resources.css(value, base, internal_only=True))
        if node.tag == 'script':
            if node.get('type', '').lower() != 'application/json' or node.has('src'):
                fail('source_script', '원본 스크립트는 실행하지 않습니다. 작성 HTML에는 application/json 데이터만 넣으세요.')
            try:
                json.loads(''.join(node.children), parse_constant=lambda _: fail('invalid_json', 'JSON 상수는 표준 형식이어야 합니다.'))
            except (ValueError, TypeError, RecursionError):
                fail('invalid_json', 'application/json 내용이 올바른 JSON이 아닙니다.')
        elif node.tag == 'style':
            node.children = [resources.css(''.join(node.children), base)]
        elif node.tag == 'link':
            if node.get('rel', '').lower() != 'stylesheet' or not node.get('href'):
                fail('unsupported_link', 'link 요소는 같은 폴더의 stylesheet만 지원합니다.')
            path = resources.path(node.get('href'), base)
            if path.suffix.lower() != '.css':
                fail('unsupported_asset', '스타일 자원은 CSS 파일이어야 합니다.')
            css = resources.css(read_bounded(path, MAX_ASSET, asset=True).decode('utf-8-sig'), path.parent)
            node.tag = node.original = 'style'
            node.attrs = [(k, v) for k, v in node.attrs if k.lower() in {'media', 'title'}]
            node.children = [css]
        elif node.tag == 'meta' and node.has('http-equiv'):
            if node.get('http-equiv', '').lower() != 'content-security-policy':
                fail('unsafe_meta', '자동 이동 또는 HTTP 동작을 지정한 meta는 지원하지 않습니다.')
            node.parent.children.remove(node)
            warnings.append('원본 CSP는 오프라인 편집기용 제한 정책으로 교체했습니다.')


def text_content(node):
    return ''.join(text_content(v) if isinstance(v, Node) else html.unescape(v) for v in node.children)


def prepare_structure(document):
    roots = [v for v in document.root.children if isinstance(v, Node)]
    if len(roots) != 1 or roots[0].tag != 'html':
        fail('invalid_document', 'html, head, body를 포함한 작성 HTML 파일을 사용하세요.')
    root = roots[0]
    bodies = [v for v in root.children if isinstance(v, Node) and v.tag == 'body']
    heads = [v for v in root.children if isinstance(v, Node) and v.tag == 'head']
    if len(bodies) != 1 or len(heads) > 1:
        fail('invalid_document', 'HTML에는 body 하나와 head 하나가 필요합니다.')
    body = bodies[0]
    head = heads[0] if heads else Node('head')
    if not heads:
        head.parent = root
        root.children.insert(0, head)
    root.set('lang', root.get('lang') or 'ko')
    all_nodes = list(root.nodes())
    identifiers = [v.get('id') for v in all_nodes if v.has('id')]
    if len(identifiers) != len(set(identifiers)):
        fail('duplicate_id', 'HTML id는 문서 안에서 서로 달라야 합니다.')
    decks = [v for v in all_nodes if v.get('id') == 'deck']
    slides = [v for v in body.nodes() if v.tag == 'section' and 'slide' in v.get('class', '').split()]
    if not slides:
        fail('missing_slides', 'section.slide 장이 없습니다.')
    if decks:
        deck = decks[0]
        if deck.tag != 'main' or any(v.parent is not deck for v in slides):
            fail('invalid_deck', '모든 section.slide를 main#deck 바로 안에 배치하세요.')
    else:
        parent = slides[0].parent
        if any(v.parent is not parent for v in slides):
            fail('invalid_deck', 'section.slide들은 같은 부모 아래에 배치하세요.')
        deck = Node('main', [('id', 'deck')])
        first = parent.children.index(slides[0])
        for slide in slides:
            parent.children.remove(slide)
            deck.append(slide)
        deck.parent = parent
        parent.children.insert(first, deck)
    ids = set(identifiers)
    for index, slide in enumerate(slides, 1):
        if not slide.get('id'):
            identity = f'slide-{index:03d}'
            while identity in ids:
                identity += '-slide'
            slide.set('id', identity)
            ids.add(identity)
        if re.search(r'\s', slide.get('id')):
            fail('invalid_slide_id', '장 id에는 공백을 넣지 마세요.')
    # Respect explicit edit scopes. Otherwise add text scopes per slide without
    # replacing authored markup, inline emphasis or SVG text geometry.
    for slide in slides:
        if any(v.has('data-edit') for v in (slide, *slide.nodes())):
            continue
        candidates = [v for v in slide.nodes() if v.tag in EDIT_TAGS and text_content(v).strip()
                      and all(child.tag in INLINE_TEXT for child in v.nodes())]
        for index, node in enumerate(candidates, 1):
            node.set('data-edit', f'{slide.get("id")}-text-{index}')
    return root, head, body, slides


def default_output():
    work = Path.cwd()
    if work.name in {'.work', 'outputs'} and work.parent.name == 'presentation':
        work = work.parent
    if work.name != 'presentation':
        work /= 'presentation'
    return work / 'outputs' / '발표본.html'


def build(source, output=None, *, font=None, width=1280, height=None):
    source = local_path(source)
    target = local_path(output if output is not None else default_output())
    if source.suffix.lower() not in {'.html', '.htm'} or target.suffix.lower() not in {'.html', '.htm'}:
        fail('invalid_extension', '원본과 출력은 HTML 파일이어야 합니다.')
    if target.exists() or source == target:
        fail('output_exists', '기존 파일을 보존했습니다. 새 출력 파일명을 지정하세요.')
    if not isinstance(width, int) or isinstance(width, bool) or not 320 <= width <= 7680:
        fail('invalid_size', '발표 폭은 320~7680 정수로 지정하세요.')
    height = width * 9 / 16 if height is None else height
    if type(height) not in (int, float) or height * 16 != width * 9:
        fail('invalid_size', '발표 크기는 16:9 비율로 지정하세요.')
    if font is not None and (not font.strip() or len(font) > 120 or re.search(r'[\x00-\x1f{};<>\\]', font)):
        fail('invalid_font', '명시할 글꼴 이름을 확인하세요.')
    warnings = []
    raw = read_bounded(source, MAX_HTML).decode('utf-8-sig')
    document = Document(raw)
    resources = Resources(source.parent)
    validate_document(document.root, resources, source.parent, warnings)
    root, head, body, slides = prepare_structure(document)
    editor_js = read_bounded(local_path(ASSETS / 'html-deck-editor.js'), MAX_ASSET, asset=True).decode('utf-8-sig')
    editor_css = read_bounded(local_path(ASSETS / 'html-deck-editor.css'), MAX_ASSET, asset=True).decode('utf-8-sig')
    editor_js = re.sub('</script', r'<\\/script', editor_js, flags=re.I)
    digest = base64.b64encode(hashlib.sha256(editor_js.encode('utf-8')).digest()).decode('ascii')
    policy = (f"default-src 'none'; script-src 'sha256-{digest}'; style-src 'unsafe-inline'; "
              "img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")
    defaults = (f':root{{--slide-width:{width}px;--slide-height:{height:g}px;'
                '--deck-font:"Pretendard","Malgun Gothic","맑은 고딕",sans-serif;}\n'
                'body{margin:0;font-family:var(--deck-font);}\n'
                '#deck>section.slide{position:relative;box-sizing:border-box;width:var(--slide-width);height:var(--slide-height);}\n')
    font_path = ASSETS / 'fonts' / 'PretendardVariable.woff2'
    if font_path.is_file():
        font_raw = read_bounded(local_path(font_path), MAX_ASSET, asset=True)
        defaults = ('@font-face{font-family:"Pretendard";font-style:normal;font-weight:100 900;font-display:swap;src:url("data:font/woff2;base64,'
                    + base64.b64encode(font_raw).decode('ascii') + '") format("woff2");}\n' + defaults)
    else:
        warnings.append('번들 Pretendard 글꼴이 없어 설치된 글꼴과 기본 대체 글꼴을 사용합니다.')
    prefix = [Node('meta', [('charset', 'utf-8')]), Node('meta', [('http-equiv', 'Content-Security-Policy'), ('content', policy)])]
    if not any(v.tag == 'meta' and v.get('name', '').lower() == 'viewport' for v in head.nodes()):
        prefix.append(Node('meta', [('name', 'viewport'), ('content', 'width=device-width, initial-scale=1')]))
    base_style = Node('style', [('data-html-deck-base', '')]); base_style.children = [defaults]
    editor_style = Node('style', [('data-html-deck-editor', '')]); editor_style.children = [editor_css]
    prefix.extend([base_style, editor_style])
    head.children = prefix + [v for v in head.children if not isinstance(v, Node) or not v.has('charset')]
    if font is not None:
        override = Node('style', [('data-html-deck-font-override', '')])
        override.children = [':root{--deck-font:' + json.dumps(font.strip(), ensure_ascii=False) + ',"Malgun Gothic","맑은 고딕",sans-serif!important;}']
        body.append(override)
    trusted = Node('script', [('data-html-deck-editor', '')]); trusted.children = [editor_js]; body.append(trusted)
    result = ('<!doctype html>\n' + root.render()).encode('utf-8')
    if len(result) > MAX_HTML:
        fail('html_too_large', '자원을 포함한 HTML이 20MB를 넘습니다. 이미지 크기를 줄여 주세요.')
    if target in resources.dependencies:
        fail('output_is_resource', '원본 자원을 출력 경로로 사용하지 않습니다.')
    target.parent.mkdir(parents=True, exist_ok=True)
    local_path(target)
    try:
        with target.open('xb') as stream:
            stream.write(result)
    except FileExistsError:
        fail('output_exists', '다른 파일이 생성되어 보존했습니다. 새 출력 파일명을 지정하세요.')
    return {'ok':True, 'outputPath':str(target), 'previewLink':f'[{target.name}]({target.as_posix()})',
            'slideCount':len(slides), 'visualReview':'not_verified', 'renderer':'free-html', 'warnings':warnings}


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='새로 작성한 자유 HTML 발표본에 오프라인 편집 기능을 넣습니다.')
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('build')
    command.add_argument('--source', type=Path, required=True)
    command.add_argument('--output', type=Path)
    command.add_argument('--font')
    command.add_argument('--width', type=int, default=1280)
    command.add_argument('--height', type=int)
    args = parser.parse_args(argv)
    try:
        result = build(args.source, args.output, font=args.font, width=args.width, height=args.height)
    except (BuildError, OSError, UnicodeError) as exc:
        result = {'ok':False, 'code':getattr(exc, 'code', 'file_error'), 'message':str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
