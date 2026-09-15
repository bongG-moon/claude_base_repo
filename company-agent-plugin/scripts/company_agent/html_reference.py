"""Data-only style references. Never render or execute an attached HTML file."""
from collections import Counter
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re


class ReferenceParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.styles = []
        self.in_style = False
        self.counts = Counter()
        self.external = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.counts[tag] += 1
        if tag == 'style':
            self.in_style = True
        if 'style' in attrs:
            self.styles.append(tag + '{' + attrs['style'] + '}')
        if tag == 'link' or attrs.get('src') or attrs.get('href'):
            self.external = True

    def handle_endtag(self, tag):
        if tag == 'style':
            self.in_style = False

    def handle_data(self, value):
        if self.in_style:
            self.styles.append(value)


def analyze(path: Path) -> dict:
    from .business_artifacts import _source, ArtifactError
    path = _source(path, ('.html', '.htm'))
    with path.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ArtifactError('template_too_large', 'HTML 참고 양식은 1 MB 이하로 준비해 주세요.')
    for encoding in ('utf-8-sig', 'cp949'):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            pass
    else:
        raise ArtifactError('template_encoding', 'HTML 양식을 UTF-8로 저장해 주세요.')
    if not re.search(r'<(?:html|body|main|section|div|table)\b', text, re.I):
        raise ArtifactError('invalid_template', '읽을 수 있는 HTML 양식인지 확인해 주세요.')
    parser = ReferenceParser()
    parser.feed(text)
    css = '\n'.join(parser.styles)
    chunks, position = [], 0
    while True:
        start = css.find('/*', position)
        if start < 0:
            chunks.append(css[position:])
            break
        chunks.append(css[position:start])
        end = css.find('*/', start + 2)
        if end < 0:
            break
        position = end + 2
    css = ''.join(chunks)
    tokens = {}
    aliases = {'--bg':'bg', '--background':'bg', '--paper':'paper', '--surface':'paper',
               '--ink':'ink', '--text':'ink', '--muted':'muted', '--accent':'accent',
               '--primary':'accent', '--brand':'accent', '--line':'line', '--tint':'tint'}
    # Only literal hex colors, a restricted font-family, and bounded px radii
    # cross into our renderer. No raw CSS, HTML, URLs or source text is copied.
    for block in css.split('}'):
        if '{' not in block:
            continue
        selector, body = block.rsplit('{', 1)
        selector = selector.strip().lower()
        for declaration in body.split(';'):
            prop, separator, value = declaration.partition(':')
            prop, value = prop.strip().lower(), value.strip()
            if not separator or not re.fullmatch(r'[\w-]{1,40}', prop):
                continue
            target = aliases.get(prop)
            if not target and re.search(r'\b(body|html)\b', selector):
                target = {'background':'bg', 'background-color':'bg', 'color':'ink'}.get(prop)
            if not target and re.search(r'\b(button|a)\b', selector):
                target = {'background':'accent', 'background-color':'accent'}.get(prop)
            if target and re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', value):
                tokens[target] = value.lower()
            if prop in ('font-family', '--heading-font') and re.fullmatch(r"[\w\s,'\"-]{1,160}", value):
                names = [part.strip().strip('\"\'').strip() for part in value.split(',')]
                if names and all(re.fullmatch(r'[\w -]{1,60}', name) for name in names):
                    tokens['font'] = ','.join(name if name in ('serif','sans-serif','monospace','system-ui') else '"'+name+'"' for name in names)
            if prop in ('border-radius', '--section-radius') and re.fullmatch(r'\d{1,2}px', value):
                tokens['radius'] = f'{min(int(value[:-2]), 40)}px'
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'tokens': tokens,
            'structure': {key: parser.counts[key] for key in ('header','main','section','article','table','h1','h2')},
            'externalResourcesIgnored': parser.external,
            'warnings': ['첨부 양식의 색상·글꼴·모서리와 구역 구성을 참고합니다. 원본 HTML을 그대로 복제하지 않습니다.',
                         '스크립트·외부 CSS/글꼴·이미지는 실행하거나 가져오지 않습니다. 없는 글꼴은 PC 기본 글꼴로 표시됩니다.']}


def theme_css(reference: dict) -> str:
    # Called only with a fresh analyze() result, never arbitrary job fields.
    mapping = {'bg':['bg'], 'paper':['paper','surface','cell','cover'], 'ink':['ink'],
               'muted':['muted'], 'accent':['accent','series-0'], 'line':['line'],
               'tint':['tint','head-fill','row-fill'], 'font':['heading-font'],
               'radius':['section-radius','cell-radius']}
    tokens = reference['tokens']
    declarations = [f'--{variable}:{value}' for key, value in tokens.items() for variable in mapping[key]]
    if tokens.get('bg') and 'paper' not in tokens:
        declarations.extend('--'+key+':#ffffff' for key in ('paper','surface','cell','cover'))
    if 'font' in tokens:
        declarations.append('font-family:'+tokens['font'])
    # Same specificity as the built-in theme, emitted after it. Otherwise the
    # reference tokens exist in HTML but lose in the browser's CSS cascade.
    return ':is(body,.style-preview)[data-style]{'+';'.join(declarations)+'}'


def inspect_template(path: Path, output: Path | None = None, *, open_preview: bool = False) -> dict:
    from .business_artifacts import _failure, create_html, open_local_preview, ArtifactError
    try:
        if open_preview and output is None:
            raise ArtifactError('preview_output_required', '새 미리보기 파일의 저장 위치를 지정해 주세요.', 'input_required')
        reference = analyze(path)
        result = {'ok': True, 'status': 'template_analyzed', 'reference': reference,
                  'htmlTemplate': {key: reference[key] for key in ('path','sha256')}}
        if output:
            preview = create_html({'title':'첨부 양식 참고 미리보기', 'subtitle':'가상 예시 · 원본의 완전한 복제 아님',
                'htmlTemplate':result['htmlTemplate'], 'style':'minimalism','mode':'scroll','length':'short',
                'sections':[{'title':'핵심 내용을 한눈에', 'layout':'cover','body':'첨부 양식에서 확인한 색상과 글꼴을 적용한 예시입니다.'},
                            {'title':'실적 비교 · 예시 자료','layout':'table',
                             'table':{'headers':['항목','목표','실적'],'rows':[['예시 A',100,110],['예시 B',80,90]]}}]}, output)
            if not preview.get('ok'):
                return preview
            result['outputPath'] = preview['outputPath']
            if open_preview:
                result.update(open_local_preview(Path(preview['outputPath'])))
        return result
    except Exception as exc:
        return _failure(exc)
