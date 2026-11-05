"""Data-only style references. Never render or execute an attached HTML file."""
from collections import Counter
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re

# The bound is for safe local file processing, not a model context limit. The
# parser returns only small validated theme tokens and structural counts.
# Exactly 10 MiB is excluded; this matches the advertised "10 MB 미만" limit.
MAX_REFERENCE_BYTES = 10 * 1024 * 1024


class ReferenceParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.styles = []
        self.in_style = False
        self.counts = Counter()
        # Deliberately retain only counts for recognized structural markers;
        # class values, text and scripts never enter the result.
        self.layout_markers = Counter()
        self.external = False
        self.root_attrs = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('html', 'body'):
            self.root_attrs[tag] = {'classes': set((attrs.get('class') or '').split()), 'id': attrs.get('id') or ''}
        self.counts[tag] += 1
        classes = (attrs.get('class') or '').lower().split()[:64]
        if tag == 'nav' or any(c in ('nav', 'navigation') or c.endswith('-nav') for c in classes):
            self.layout_markers['navigation'] += 1
        if any(c == 'card' or c.endswith('-card') for c in classes):
            self.layout_markers['cards'] += 1
        if any(c == 'grid' or c.endswith('-grid') for c in classes):
            self.layout_markers['grids'] += 1
        if tag in ('ol', 'ul') and any('step' in c or 'workflow' in c for c in classes):
            self.layout_markers['stepLists'] += 1
        if any(c in ('badge', 'ordinal', 'step-number') or c.endswith('-badge') for c in classes):
            self.layout_markers['numberOrBadgeMarkers'] += 1
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


def _global_rules(css: str):
    """Read flat rules only; conditional/nested CSS is not a global theme."""
    start = 0
    depth = 0
    quote = ''
    escaped = False
    nested = False
    selector = ''
    for index, char in enumerate(css):
        if escaped:
            escaped = False
            continue
        if char == '\\':
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ''
            continue
        if char in ('"', "'"):
            quote = char
        elif char == '{':
            if depth == 0:
                selector = css[start:index].strip().lower()
                start = index + 1
                nested = False
            else:
                nested = True
            depth += 1
        elif char == '}' and depth:
            depth -= 1
            if depth == 0:
                if not nested and not selector.startswith('@'):
                    yield selector, css[start:index]
                start = index + 1


def analyze(path: Path) -> dict:
    from .business_artifacts import _source, ArtifactError
    path = _source(path, ('.html', '.htm'))
    with path.open('rb') as stream:
        # Limit the read even if the file changes while it is being accessed.
        raw = stream.read(MAX_REFERENCE_BYTES)
    if len(raw) >= MAX_REFERENCE_BYTES:
        raise ArtifactError('template_too_large', 'HTML 참고 양식은 10 MiB 미만으로 준비해 주세요.')
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
    variables, root_colors = [], []
    def matched_root(selector):
        """Only simple selectors matching the real root, never execute source CSS."""
        selector = selector.strip()
        if selector == ':root':
            return 10
        match = re.fullmatch(r'(html|body)((?:[.#][\w-]+)*)', selector)
        if not match:
            return None
        attrs = parser.root_attrs.get(match.group(1), {'classes': set(), 'id': ''})
        parts = re.findall(r'([.#])([\w-]+)', match.group(2))
        if any((kind == '.' and name not in attrs['classes']) or (kind == '#' and name != attrs['id']) for kind, name in parts):
            return None
        # A declaration on body wins over an inherited html variable even
        # when the html selector has greater specificity.
        return (1000 if match.group(1) == 'body' else 0) + 1 + sum(100 if kind == '#' else 10 for kind, _ in parts)
    aliases = {'--bg':'bg', '--background':'bg', '--paper':'paper', '--surface':'paper',
               '--ink':'ink', '--text':'ink', '--muted':'muted', '--accent':'accent',
               '--primary':'accent', '--brand':'accent', '--secondary':'secondary', '--line':'line', '--border':'line', '--tint':'tint',
               '--head-fill':'tableHeaderFill', '--row-fill':'tableAlternateFill',
               '--table-head-fill':'tableHeaderFill', '--table-head-text':'tableHeaderText',
               '--table-body-fill':'tableBodyFill', '--table-body-text':'tableBodyText',
               '--table-alternate-fill':'tableAlternateFill', '--table-border':'tableBorder'}
    # Only literal hex colors, a restricted font-family, and bounded px radii
    # cross into our renderer. No raw CSS, HTML, URLs or source text is copied.
    for selector, body in _global_rules(css):
        # A code snippet, icon, state variant, or child selector does not define
        # the page font or every card's radius. This is not a CSS cascade engine.
        selectors = {part.strip() for part in selector.split(',')}
        matches = [score for part in selectors if (score := matched_root(part)) is not None]
        root_scope = bool(matches)
        specificity = max(matches, default=0)
        text_scope = root_scope or bool(selectors & {'main', '.report-main'})
        heading_scope = bool(selectors & {'h1', 'h2', 'h3'})
        panel_scope = bool(selectors & {'section', 'article', '.section', '.card', '.panel'})
        action_scope = bool(selectors & {'button', 'a', '.button', '.btn'})
        table_head = bool(selectors & {'th', 'thead', 'thead th', 'table th', 'table thead th', '.report-data-table thead th'})
        table_body = bool(selectors & {'td', 'tbody', 'tbody td', 'table td', 'table tbody', '.report-data-table tbody'})
        table_alternate = bool(selectors & {'tbody tr:nth-child(even)', 'table tbody tr:nth-child(even)', '.report-data-table tbody tr:nth-child(even)'})
        table_scope = table_head or table_body or bool(selectors & {'table', 'td,th', '.report-data-table'})
        for declaration in body.split(';'):
            prop, separator, value = declaration.partition(':')
            prop, value = prop.strip().lower(), value.strip()
            if not separator or not re.fullmatch(r'[\w-]{1,40}', prop):
                continue
            target = aliases.get(prop) if root_scope else None
            if root_scope and prop in aliases and re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', value):
                variables.append((specificity, len(variables), prop, value.lower()))
            if root_scope and prop in ('background', 'background-color', 'color'):
                variable = re.fullmatch(r'var\(\s*(--[\w-]+)\s*\)', value)
                literal = re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', value)
                if variable or literal:
                    root_colors.append((specificity, len(root_colors), 'ink' if prop == 'color' else 'bg', variable[1] if variable else value.lower()))
            if root_scope and re.fullmatch(r'--series-(?:[0-9]|[12][0-9])', prop):
                target = prop[2:]
            if not target and root_scope:
                target = {'background':'bg', 'background-color':'bg', 'color':'ink'}.get(prop)
            if not target and action_scope:
                target = {'background':'accent', 'background-color':'accent'}.get(prop)
            if not target and table_head:
                target = {'background':'tableHeaderFill', 'background-color':'tableHeaderFill', 'color':'tableHeaderText'}.get(prop)
            if not target and table_body:
                target = {'background':'tableBodyFill', 'background-color':'tableBodyFill', 'color':'tableBodyText'}.get(prop)
            if not target and table_alternate and prop in ('background', 'background-color'):
                target = 'tableAlternateFill'
            if not target and table_scope and prop in ('border-color', 'border-bottom-color'):
                target = 'tableBorder'
            if target and re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', value):
                tokens[target] = value.lower()
            font_target = ('headingFont' if prop == '--heading-font' and root_scope else
                           'font' if prop == '--body-font' and root_scope else
                           'font' if prop == 'font-family' and text_scope else
                           'headingFont' if prop == 'font-family' and heading_scope else None)
            if font_target and re.fullmatch(r"[\w\s,'\"-]{1,160}", value):
                names = [part.strip().strip('\"\'').strip() for part in value.split(',')]
                if names and all(re.fullmatch(r'[\w -]{1,60}', name) for name in names):
                    tokens[font_target] = ','.join(name if name in ('serif','sans-serif','monospace','system-ui') else '"'+name+'"' for name in names)
            radius_scope = prop == '--section-radius' and root_scope or prop == 'border-radius' and panel_scope
            if radius_scope and re.fullmatch(r'\d{1,2}px', value):
                tokens['radius'] = f'{min(int(value[:-2]), 40)}px'
            size_target = ('titleSize' if prop == 'font-size' and heading_scope else
                           'bodySize' if prop == 'font-size' and text_scope else
                           'tableFontSize' if prop == 'font-size' and table_scope else
                           'outer' if prop == 'padding' and panel_scope else
                           'gap' if prop == 'gap' and text_scope else
                           'tablePadding' if prop == 'padding' and table_scope else None)
            if size_target and re.fullmatch(r'\d{1,2}(?:\.\d)?px', value):
                number = float(value[:-2])
                if (8 <= number <= 96 if size_target.endswith('Size') else 0 <= number <= 96):
                    tokens[size_target] = value
            if table_head and prop == 'font-weight' and value in ('normal', 'bold', '400', '500', '600', '700', '800', '900'):
                tokens['tableHeaderWeight'] = {'normal':'400', 'bold':'700'}.get(value, value)
            if table_scope and prop == 'text-align' and value in ('left', 'center', 'right'):
                tokens['tableAlign'] = value
            if table_scope and prop in ('border-width', 'border-bottom-width') and re.fullmatch(r'[0-6](?:\.\d)?px', value) and float(value[:-2]) <= 6:
                tokens['tableBorderWidth'] = value
            if table_scope and prop in ('border', 'border-bottom'):
                border = re.fullmatch(r'([0-6](?:\.\d)?)px\s+solid\s+(#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?)', value)
                if border and float(border[1]) <= 6:
                    tokens['tableBorderWidth'], tokens['tableBorder'] = border[1]+'px', border[2].lower()
    resolved = {}
    for _, _, name, value in sorted(variables):
        resolved[name] = value
        tokens[aliases[name]] = value
    for _, _, target, value in sorted(root_colors):
        if value.startswith('--'):
            value = resolved.get(value)
        if value:
            tokens[target] = value
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'tokens': tokens,
            'structure': {key: parser.counts[key] for key in ('header','main','section','article','table','h1','h2')},
            'layoutHints': {**{key: parser.layout_markers[key] for key in
                               ('navigation','cards','grids','stepLists','numberOrBadgeMarkers')},
                            'collapsibleSections': parser.counts['details']},
            'externalResourcesIgnored': parser.external,
            'warnings': ['첨부 양식의 색상·글꼴·모서리와 구역 구성을 참고합니다. 원본 HTML을 그대로 복제하지 않습니다.',
                         'layoutHints는 HTML 태그와 이름에서 찾은 구조 단서입니다. 실제 CSS 배치나 시각적 유사성을 증명하지 않습니다.',
                         '스크립트·외부 CSS/글꼴·이미지는 실행하거나 가져오지 않습니다. 없는 글꼴은 PC 기본 글꼴로 표시됩니다.',
                         '전체 CSS 계산이 아닙니다. 페이지·제목·주요 구획의 단순 규칙만 참고하며 조건부 CSS와 부분 요소 스타일은 전역 양식으로 쓰지 않습니다.']}


def theme_css(reference: dict) -> str:
    # Called only with a fresh analyze() result, never arbitrary job fields.
    mapping = {'bg':['bg'], 'paper':['paper','surface','cell','cover'], 'ink':['ink'],
               'muted':['muted'], 'accent':['accent'], 'secondary':['secondary'], 'line':['line'],
               'tint':['tint','head-fill','row-fill'], 'font':[], 'headingFont':[],
               'radius':['section-radius','cell-radius'],
               'tableHeaderFill':['table-head-fill'], 'tableHeaderText':['table-head-text'],
               'tableBodyFill':['table-body-fill'], 'tableBodyText':['table-body-text'],
               'tableAlternateFill':['table-alternate-fill'], 'tableBorder':['table-border'],
               'tableHeaderWeight':['table-head-weight'], 'tableFontSize':['table-font-size'],
               'tablePadding':['table-padding'], 'tableAlign':['table-align'], 'tableBorderWidth':['table-border-width']}
    tokens = reference['tokens']
    declarations = [f'--{variable}:{value}' for key, value in tokens.items()
                    for variable in ([key] if re.fullmatch(r'series-(?:[0-9]|[12][0-9])', key) else mapping.get(key, []))]
    if 'accent' in tokens and 'series-0' not in tokens:
        declarations.append('--series-0:'+tokens['accent'])
    if 'secondary' in tokens and 'series-1' not in tokens:
        declarations.append('--series-1:'+tokens['secondary'])
    if tokens.get('bg') and 'paper' not in tokens:
        declarations.extend('--'+key+':#ffffff' for key in ('paper','surface','cell','cover'))
    if 'font' in tokens:
        declarations.append('font-family:'+tokens['font'])
    if tokens.get('headingFont') or tokens.get('font'):
        declarations.append('--heading-font:'+(tokens.get('headingFont') or tokens['font']))
    # Same specificity as the built-in theme, emitted after it. Otherwise the
    # reference tokens exist in HTML but lose in the browser's CSS cascade.
    css = ':is(body,.style-preview)[data-style]{'+';'.join(declarations)+'}'
    if 'font' in tokens:
        css += '\nbody[data-style] :is(button,input,select,textarea,svg text){font-family:inherit}'
    root = 'body[data-style][data-reference-style]'
    if 'titleSize' in tokens:
        css += '\n'+root+' .section h2{font-size:'+tokens['titleSize']+'}'
    if 'bodySize' in tokens:
        css += '\n'+root+' .text{font-size:'+tokens['bodySize']+'}'
    if 'outer' in tokens:
        css += '\n'+root+' .section{padding:'+tokens['outer']+'}'
    if 'gap' in tokens:
        css += '\n'+root+' :is(.report-main,.section-content){gap:'+tokens['gap']+'}'
    if 'secondary' in tokens:
        css += '\n'+root+' .takeaway{border-color:var(--secondary)}'
    local = ['--'+key+':'+tokens[key] for key in ('ink','muted','accent','line') if key in tokens]
    if local:
        css += '\n'+root+' .kpi{'+';'.join(local)+'}'
    if 'paper' in tokens:
        css += '\n'+root+' :is(.kpi,.report-masthead){background:var(--paper)}'
    if 'ink' in tokens:
        css += '\n'+root+' .report-masthead{color:var(--ink)}'
    if 'muted' in tokens:
        css += '\n'+root+' .report-masthead .subtitle{color:var(--muted)}'
    return css


def validate_review_metadata(review: dict) -> None:
    from .business_artifacts import ArtifactError
    if (not isinstance(review, dict) or set(review) != {'templateSha256', 'previewPath', 'previewSha256', 'confirmed'}
            or type(review.get('confirmed')) is not bool
            or any(not isinstance(review.get(key), str) or not re.fullmatch('[a-f0-9]{64}', review[key])
                   for key in ('templateSha256', 'previewSha256'))
            or not isinstance(review.get('previewPath'), str) or len(review['previewPath']) > 2048
            or not Path(review['previewPath']).is_absolute() or Path(review['previewPath']).suffix.lower() != '.html'):
        raise ArtifactError('invalid_choice', '첨부 양식 미리보기의 확인 정보를 다시 준비해 주세요.')


def review_stage(spec: dict) -> str | None:
    """Template-only checkpoint. Confirmed means a recorded user answer, not proof of viewing."""
    from .business_artifacts import ArtifactError, _source
    review = spec.get('templateReview')
    if review is None:
        return 'template_preview'
    validate_review_metadata(review)
    reference = analyze(Path(spec['htmlTemplate']['path']))
    if reference['sha256'] != spec['htmlTemplate']['sha256'] or reference['sha256'] != review['templateSha256']:
        raise ArtifactError('template_changed', '첨부 양식이 변경되었습니다. 새 미리보기를 보여주고 다시 확인해 주세요.', 'input_required')
    preview = _source(Path(review['previewPath']), ('.html',))
    with preview.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    marker = ('<meta name="company-agent-template-sha256" content="'+reference['sha256']+'">').encode()
    if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != review['previewSha256'] or marker not in raw:
        raise ArtifactError('template_preview_changed', '미리보기 파일이 달라졌습니다. 다시 생성하고 확인해 주세요.', 'input_required')
    return None if review['confirmed'] else 'template_confirm'


def preview_delivery(path: Path) -> dict:
    """Return a usable local destination, without claiming a browser was opened."""
    target = path.resolve()
    return {'previewPath': str(target), 'previewUrl': target.as_uri(),
            'previewLink': '[양식 미리보기 열기](<' + target.as_posix() + '>)',
            'previewMessage': '양식 미리보기 파일: ' + str(target) +
                '\n채팅의 링크로 열거나 파일 탐색기에서 이 HTML을 두 번 클릭하세요. 원본의 완전한 복제가 아닌 정적 스타일 예시입니다.'}


def inspect_template(path: Path, output: Path | None = None, *, open_preview: bool = False) -> dict:
    from .business_artifacts import _failure, create_html, open_local_preview, ArtifactError
    try:
        if open_preview and output is None:
            raise ArtifactError('preview_output_required', '새 미리보기 파일의 저장 위치를 지정해 주세요.', 'input_required')
        reference = analyze(path)
        result = {'ok': True, 'status': 'template_analyzed', 'reference': reference,
                  'htmlTemplate': {key: reference[key] for key in ('path','sha256')},
                  'previewCreated': False,
                  'message': '양식 특징만 분석했습니다. 미리보기가 필요하면 새 HTML 저장 경로를 지정해 실행하세요.'}
        if output:
            preview = create_html({'title':'첨부 양식 참고 미리보기', 'subtitle':'가상 예시 · 원본의 완전한 복제 아님',
                'htmlTemplate':result['htmlTemplate'], 'style':'minimalism','mode':'scroll','length':'short',
                'sections':[{'title':'핵심 내용을 한눈에', 'layout':'cover','body':'첨부 양식에서 확인한 색상과 글꼴을 적용한 예시입니다.'},
                            {'title':'실적 비교 · 예시 자료','layout':'table',
                             'table':{'headers':['항목','목표','실적'],'rows':[['예시 A',100,110],['예시 B',80,90]]}}]}, output, template_preview=True)
            if not preview.get('ok'):
                return preview
            result['outputPath'] = preview['outputPath']
            result.update(preview_delivery(Path(preview['outputPath'])))
            result.update(previewCreated=True, message='양식 미리보기를 생성했습니다. previewLink와 previewPath를 사용자에게 보여 주세요.')
            result['templateReview'] = {'templateSha256': reference['sha256'], 'previewPath': preview['outputPath'],
                                        'previewSha256': hashlib.sha256(Path(preview['outputPath']).read_bytes()).hexdigest(),
                                        'confirmed': False}
            if open_preview:
                opened = open_local_preview(Path(preview['outputPath']))
                # Keep the actual destination visible even when opening fails.
                result['previewMessage'] += '\n' + opened.pop('previewMessage', '')
                result.update(opened)
        return result
    except Exception as exc:
        return _failure(exc)
