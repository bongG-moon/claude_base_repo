"""Offline PPT drafts and reusable, content-free HTML design templates.

HTML and native PPT use the same validated composition. Static source HTML can
be measured by the shipped isolated renderer; source scripts are never executed.
"""
from __future__ import annotations

import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile

from . import business_artifacts as artifacts, ppt_workflow, presentation_design

TEMPLATE_ID = 'company-agent-ppt-template'
SCHEMA = 'company-agent-ppt-template-v1'
SCENE_ID = 'company-agent-ppt-scene'
esc = lambda value: html.escape(str(value), quote=True)


class _TemplateReader(HTMLParser):
    def __init__(self, identity=TEMPLATE_ID):
        super().__init__(convert_charrefs=False)
        self.active = False
        self.payloads = []
        self.identity = identity

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('id') == self.identity:
            if self.active or dict(attrs).get('type') != 'application/json':
                raise ValueError('invalid template metadata')
            self.payloads.append('')
            self.active = True

    def handle_data(self, value):
        if self.active:
            self.payloads[-1] += value

    def handle_endtag(self, tag):
        if tag == 'script':
            self.active = False


def read_template(path):
    """Read only bounded metadata. Foreign scripts/CSS/content are never imported."""
    source = artifacts._source(Path(path), ('.html', '.htm'))
    if source.stat().st_size > 4 * 1024 * 1024:
        raise artifacts.ArtifactError('invalid_ppt_template', '저장한 PPT HTML 대표 양식은 4 MiB 이하이어야 합니다.')
    try:
        reader = _TemplateReader()
        reader.feed(source.read_text(encoding='utf-8-sig'))
        reader.close()
        if reader.active or len(reader.payloads) != 1:
            raise ValueError('missing or duplicate metadata')
        meta = json.loads(reader.payloads[0])
        base={'schema','layoutVersion','presentationTheme','presentationFont','presentationFrame'}
        if (not isinstance(meta, dict) or set(meta) != base | ({'layouts'} if meta.get('layoutVersion')==2 else set())
                or meta['schema'] != SCHEMA or type(meta['layoutVersion']) is not int or meta['layoutVersion'] not in (1,2)):
            raise ValueError('unsupported template')
        # Same font/color/size validation as the native generator, not HTML code.
        sample = {**meta, 'slides':[{'title':'양식 확인','body':'본문'}]}
        data = artifacts._normalize(sample)
        presentation_design.prepare(sample, data)
        frame = frame_size(meta.get('presentationFrame'))
        presentation_design.plan(data, **frame)
        result={k:meta[k] for k in ('presentationTheme','presentationFont','presentationFrame')}
        if meta['layoutVersion']==2:
            from .ppt_scene import elements, ink
            if not isinstance(meta['layouts'],list) or not 1<=len(meta['layouts'])<=60:
                raise ValueError('invalid layouts')
            result['layouts']=[]
            for layout in meta['layouts']:
                if not isinstance(layout,dict) or not isinstance(layout.get('elements'),list) or any(not isinstance(e,dict) or e.get('kind')=='image' for e in layout['elements']):
                    raise ValueError('template images are not allowed')
                checked=elements(layout['elements'],**frame,palette=data['presentationTheme'])
                if any(e['kind']=='image' for e in checked): raise ValueError('image retention is not allowed')
                result['layouts'].append({'elements':checked,'background':ink(layout.get('background','FFFFFF'),data['presentationTheme']),
                    'textSlots':sum(e['kind']=='text' for e in checked)})
        return result
    except (ValueError, KeyError, TypeError, RecursionError):
        raise artifacts.ArtifactError('invalid_ppt_template', 'PPT 대표 양식 메타데이터를 확인하지 못했습니다. 일반 정적 HTML은 --template 대신 job의 htmlSource.path로 지정해 배치를 읽어 주세요.') from None


def frame_size(value=None):
    frame = value if value is not None else {'width':960., 'height':540.}
    if (not isinstance(frame,dict) or set(frame) != {'width','height'}
            or any(type(v) not in (int,float) for v in frame.values())
            or not 600 <= frame['width'] <= 1800 or not 400 <= frame['height'] <= 1100
            or not 1.25 <= frame['width']/frame['height'] <= 2.1):
        raise artifacts.ArtifactError('ppt_frame_invalid', '지원하는 PPT 페이지 크기와 비율을 선택해 주세요.')
    return frame


def prepare(spec, template=None):
    """Shared normalization and composition for HTML and editable PPT export."""
    from .report_facts import FactError
    from .ppt_layouts import LayoutError as PptLayoutError
    if not isinstance(spec, dict):
        raise artifacts.ArtifactError('invalid_spec', '작업 내용은 JSON 객체로 전달해 주세요.')
    if 'referenceStyle' in spec:
        from . import reference_style
        try:
            spec = reference_style.apply(spec, 'ppt')
        except ValueError as exc:
            raise artifacts.ArtifactError('invalid_reference_style', str(exc)) from None
    # Import/preserve routes must not bypass the shared per-page contract.
    # Reject before reading a source or taking the HTML import fast path.
    if 'contentOrder' in spec or 'contentLayout' in spec:
        raise artifacts.ArtifactError('invalid_content_layout', 'contentOrder와 contentLayout은 전체 문서가 아닌 각 sections/slides 항목 안에 지정하세요.')
    ordered = any(isinstance(row,dict) and ('contentOrder' in row or 'contentLayout' in row)
                  for row in (spec.get('sections',spec.get('slides',[])) or []))
    if ordered and (spec.get('htmlSource') or spec.get('referenceMode') == 'preserve'):
        raise artifacts.ArtifactError('content_layout_unsupported','HTML 원본 변환·기존 개체 유지에는 contentOrder를 추가하지 않습니다. 실제 승인할 원본 배치를 수정해 주세요.')
    for key in ('slides', 'sections'):
        rows = spec.get(key)
        if isinstance(rows, list) and any(isinstance(row, dict) and 'diagram' in row for row in rows):
            raise artifacts.ArtifactError('diagram_html_only', '설명 도표는 현재 HTML 출력용입니다. 편집 가능한 PPT로 자동 변환하거나 내용을 생략하지 않았습니다.')
    native_template = template
    effective = dict(spec)
    if spec.get('htmlSource'):
        return prepare_import(spec,template)
    if template and Path(template).suffix.lower() in ('.html','.htm'):
        if spec.get('referenceMode') == 'preserve':
            raise artifacts.ArtifactError('invalid_choice','HTML 양식은 디자인 참고용입니다. 원본 개체 유지에는 PPTX가 필요합니다.')
        defaults = read_template(template)
        effective = {**defaults, **spec}
        effective['presentationTheme'] = {**defaults['presentationTheme'], **spec.get('presentationTheme', {})}
        if defaults.get('layouts'):
            effective=apply_layouts(effective,defaults['layouts'])
        native_template = None
    if spec.get('referenceImages'):
        if spec.get('referenceMode') == 'preserve':
            raise artifacts.ArtifactError('invalid_choice','캡처와 원본 양식 유지 조건을 함께 적용하지 않습니다. 디자인 기준을 확인해 주세요.')
        if (not isinstance(spec['referenceImages'], list) or len(spec['referenceImages']) > 60
                or any(not isinstance(path, str) or not Path(path).is_absolute() for path in spec['referenceImages'])):
            raise artifacts.ArtifactError('invalid_choice','참고 이미지는 실제 로컬 절대경로 목록으로 최대 60개 지정해 주세요.')
        for path in spec['referenceImages']:
            ppt_workflow.reference_image_digest(path)
        profile = spec.get('referenceStyle', {})
        # A visual observation can be a font or layout rule even when the
        # source colors could not be determined. Evidence alone does not carry
        # design information and must not bypass this checkpoint.
        observed = any(
            isinstance(value, (int, float, bool)) or
            isinstance(value, str) and bool(value.strip()) or
            isinstance(value, list) and bool(value)
            for section in ('colors', 'typography', 'spacing', 'table', 'chart', 'patterns')
            for value in profile.get(section, {}).values()
        ) if isinstance(profile, dict) else False
        if not spec.get('presentationTheme') and not observed:
            raise artifacts.ArtifactError('reference_design_needed', '첨부 캡처를 먼저 보고 확인할 수 있는 색감·글꼴·구성을 referenceStyle 또는 presentationTheme에 반영해 주세요. 캡처를 슬라이드 배경으로 붙이지 않습니다.')
    data = artifacts._normalize(effective)
    if 'slideCount' in spec and spec['slideCount'] != len(data['sections']):
        raise artifacts.ArtifactError('slide_count_mismatch', '생성할 장수가 선택한 장수와 다릅니다. 몰래 늘리거나 줄이지 않았습니다.')
    inspected = artifacts.inspect_template(native_template) if native_template else None
    if inspected and not inspected.get('ok'):
        raise artifacts.ArtifactError(inspected.get('code','template_invalid'), inspected['message'], inspected['status'])
    if inspected and inspected['hasExternalRelationships']:
        raise artifacts.ArtifactError('external_template_links', '외부 연결이 있는 양식은 자동 제작하지 않습니다.')
    size = inspected.get('sizeEmu', {}) if inspected else {}
    frame = frame_size({'width':size['width']/12700, 'height':size['height']/12700} if size else effective.get('presentationFrame'))
    preserve = bool(native_template and spec.get('referenceMode') == 'preserve')
    try:
        arithmetic = presentation_design.prepare(effective, data)
        artifacts._fit_preflight(data)
        data['presentationPlan'] = presentation_design.plan(data, **frame) if not preserve else {}
    except (presentation_design.DesignError, PptLayoutError, FactError) as exc:
        raise artifacts.ArtifactError('ppt_design_invalid', str(exc)) from None
    return data, arithmetic, inspected, native_template, preserve


def apply_layouts(spec,layouts):
    """Explicit slot mapping avoids silently retaining synthetic or previous content."""
    from copy import deepcopy
    spec=deepcopy(spec)
    for row in spec.get('sections',spec.get('slides',[])):
        if 'elements' in row:
            continue
        index=row.get('layoutIndex')
        if type(index) is not int or not 1<=index<=len(layouts):
            raise artifacts.ArtifactError('template_layout_required','저장한 양식의 layoutIndex(1부터)와 texts를 지정하세요. ppt-analyze로 슬롯 개수를 확인할 수 있습니다.')
        layout=deepcopy(layouts[index-1]); values=row.get('texts')
        if not isinstance(values,list) or len(values)!=layout['textSlots']:
            raise artifacts.ArtifactError('template_text_slots_required',f'선택한 양식은 texts {layout["textSlots"]}개가 필요합니다. 빈 문구는 빈 문자열로 지정하세요.')
        slots=iter(values)
        charts=iter(row.get('charts',[])); tables=iter(row.get('tables',[]))
        try:
            for e in layout['elements']:
                if e['kind']=='text': e['text']=next(slots)
                elif e['kind']=='chart': e['chart']=next(charts)
                elif e['kind']=='table': e['table']=next(tables)
        except StopIteration:
            raise artifacts.ArtifactError('template_data_slots_required','양식의 chart/table 개수에 맞는 charts/tables 데이터를 지정하세요.') from None
        if list(charts) or list(tables):
            raise artifacts.ArtifactError('template_data_slots_required','양식보다 많은 charts/tables 데이터를 생략하지 않았습니다. 개수를 맞춰 주세요.')
        row['elements']=layout['elements']
        row['background']=layout.get('background','FFFFFF')
    return spec


def prepare_import(spec,template=None):
    from . import ppt_scene, ppt_html_import
    if template or spec.get('referenceImages') or spec.get('referenceMode')=='preserve' or spec.get('slides') or spec.get('sections'):
        raise artifacts.ArtifactError('invalid_html_source','HTML 직접 변환에는 다른 양식이나 slides 본문을 함께 지정하지 마세요.')
    sample={**spec,'slides':[{'title':'HTML 배치','body':'배치 확인'}]}
    data=artifacts._normalize(sample)
    presentation_design.prepare(sample,data)
    plan=None
    if isinstance(spec.get('designReview'),dict):
        # Use the approved measured scene, not a second browser render. Both HTML
        # source/dependencies and the review file must still have the same hash.
        ppt_workflow.verify_design_review(spec,template)
        reader=_TemplateReader(SCENE_ID)
        reader.feed(Path(spec['designReview']['previewPath']).read_text(encoding='utf-8'))
        if len(reader.payloads)==1:
            plan=json.loads(reader.payloads[0])
            frame=frame_size({k:plan[k] for k in ('width','height')})
            if not isinstance(plan.get('pages'),list) or not 1<=len(plan['pages'])<=60:
                raise artifacts.ArtifactError('invalid_html_scene','HTML 배치 기록이 올바르지 않습니다.')
            for page in plan['pages']:
                page['elements']=ppt_scene.elements(page['elements'],**frame,palette=data['presentationTheme'],embedded=True)
                page['background']=ppt_scene.ink(page.get('background','FFFFFF'),data['presentationTheme'])
    if plan is None:
        plan=ppt_html_import.capture(spec['htmlSource'],data['presentationTheme'],data['presentationFont'])
    if spec.get('slideCount',len(plan['pages']))!=len(plan['pages']):
        raise artifacts.ArtifactError('slide_count_mismatch','HTML 장수와 요청 장수가 다릅니다. 내용을 생략하지 않았습니다.')
    data['sections']=[{'title':p.get('title',f'{i+1}장'),'body':'','bullets':[],
                       'notes':p.get('notes',''),'source':p.get('source','')} for i,p in enumerate(plan['pages'])]
    data['presentationPlan']=plan
    return data,{'status':'not_declared','message':'HTML의 수치는 원문대로 옮겼으며 계산 관계는 별도 검증이 필요합니다.'},None,None,False


CSS = """
*{box-sizing:border-box}body{margin:0;background:#edf0f4;color:#243247;font-family:'Malgun Gothic','Segoe UI',sans-serif}
header,footer{max-width:1160px;margin:auto;padding:24px}header h1{margin:0 0 10px;font-size:24px}header p,footer{font-size:14px;line-height:1.7}
.ppt-main{max-width:1160px;margin:auto;padding:0 24px 24px}.ppt-page{container-type:inline-size;margin:0 0 24px;overflow:auto;border:1px solid #d7dfe8;box-shadow:0 6px 25px #17324d12}
.ppt-slide{position:relative;aspect-ratio:var(--pw)/var(--ph);background:var(--paper);color:var(--ink);font-family:var(--font);overflow:hidden}
.ppt-element{position:absolute;white-space:pre-wrap;overflow-wrap:anywhere;word-break:keep-all;line-height:1.15;padding:2px 0}
.ppt-element[data-kind="table"]{padding:0}
.ppt-table{width:100%;border-collapse:collapse;table-layout:fixed;white-space:normal}.ppt-table th,.ppt-table td{padding:4px 6px;vertical-align:middle;border-bottom:1px solid var(--line);line-height:1.15}
.ppt-table th{background:var(--title);color:var(--paper);font-weight:700}.ppt-table tr:nth-child(2n){background:var(--line)}
.ppt-element figure{margin:0;width:100%;height:100%;display:flex;flex-direction:column}.ppt-element figcaption{display:none}.report-chart{width:100%;height:calc(100% - 22px);flex:1;min-height:0;overflow:visible}
.report-chart text{fill:var(--muted);font:13px 'Malgun Gothic',sans-serif}.report-chart .chart-value{fill:var(--ink);font-weight:700}.gridline{stroke:var(--line);stroke-width:1}
.legend{display:flex;justify-content:center;gap:18px;font-size:12px;white-space:normal}.legend i{display:inline-block;width:9px;height:9px;margin-right:6px}
.ppt-element img{width:100%;height:100%;object-fit:contain}.data-notes{padding:12px 18px;background:#fff;font-size:13px}.data-notes summary{cursor:pointer}.data-notes table{border-collapse:collapse;margin:10px 0}.data-notes td,.data-notes th{padding:5px 15px;text-align:left}
@media print{header,footer,.data-notes{display:none}.ppt-main{max-width:none;padding:0}.ppt-page{break-after:page;box-shadow:none;margin:0;border:0}@page{size:landscape;margin:8mm}}
"""


def render(data, *, metadata=None, preserve=False, fragment=False, id_prefix=''):
    from copy import deepcopy
    from .report_design import svg_chart
    plan = deepcopy(data['presentationPlan'])
    palette = plan['theme']
    color = lambda key: '#' + palette.get(key, key)
    font = plan['font']
    # Font is an installed name but still must never become CSS syntax.
    safe_font = ''.join(c for c in font if c.isalnum() or c in ' -_')
    variables = ';'.join(f'--{key}:{color(value)}' for key,value in
                         [('paper','background'),('ink','text'),('title','title'),('muted','muted'),('line','tint'),
                          ('series-0','accent'),('series-1','title'),('series-2','52667C'),('series-3','B05C32')])
    variables += f";--pw:{plan['width']};--ph:{plan['height']};--font:'{safe_font}',sans-serif"
    pages = []
    for index,(row,page) in enumerate(zip(data['sections'],plan['pages']),1):
        content = []
        page['notes'] = row.get('notes', '')
        page['source'] = row.get('source', '')
        page['title'] = row['title']
        title_marked = False
        for ei, e in enumerate(page['elements']):
            edit_id = f'p{index-1}-e{ei}'
            edit_attrs = ''
            position = ';'.join(f'{prop}:{e[key]/plan[dimension]*100:.6f}%'
                                for prop,key,dimension in [('left','x','width'),('top','y','height'),('width','w','width'),('height','h','height')])
            kind = e['kind']
            if kind == 'text':
                if not fragment and not e.get('runs'):
                    edit_attrs = f' data-edit="{edit_id}"'
                if not title_marked and e.get('text') == row['title']:
                    edit_attrs += ' data-deck-title="true"'
                    title_marked = True
                position += f";font-size:{e['size']}px;font-size:{e['size']/plan['width']*100:.6f}cqw;color:{color(e['color'])};font-weight:{700 if e['bold'] else 400}"
                inner = esc(e['text'])
                if e.get('runs'):
                    from .ppt_text import html_runs
                    inner = html_runs(e,plan['width'], edit_id if not fragment else '', title='data-deck-title' in edit_attrs)
                if 'wrap' in e:
                    position+=f';padding:0;line-height:{e.get("lineSpacing",1.15)};text-align:{e.get("align","left")};white-space:{"pre-wrap" if e["wrap"] else "pre"}'
                    face=''.join(c for c in e.get('font','') if c.isalnum() or c in ' -_')
                    if face: position+=f";font-family:'{face}',sans-serif"
                    if e.get('italic'): position+=';font-style:italic'
                    if e.get('underline'): position+=';text-decoration:underline'
                if e.get('verticalAlign') in ('middle','bottom'):
                    position+=';display:flex;flex-direction:column;justify-content:'+('center' if e['verticalAlign']=='middle' else 'flex-end')
                    inner='<div'+edit_attrs+'>'+inner+'</div>'
                    edit_attrs=''
            elif kind in ('line','path') or (kind == 'shape' and e.get('shape') not in ('rect','roundRect','ellipse')):
                from .ppt_primitives import render_primitive_html
                position+=';padding:0;overflow:visible'
                inner=render_primitive_html(e,plan)
            elif kind == 'shape':
                from .ppt_scene import ink
                fill=ink(e.get('fill'),palette,transparent=True)
                position+=';padding:0'
                if fill:
                    r,g,b=[int(fill[i:i+2],16) for i in (0,2,4)]
                    position+=f';background:rgba({r},{g},{b},{e.get("opacity",1)})'
                if e.get('border') and e.get('borderWidth'):
                    position+=f';border:{e["borderWidth"]/plan["width"]*100}cqw solid {color(e["border"])}'
                radius=50 if e.get('shape')=='ellipse' else e.get('radius',0)/plan['width']*100
                position+=f';border-radius:{radius}{"%" if e.get("shape")=="ellipse" else "cqw"}'
                if e.get('shadow'):
                    s=e['shadow']; r,g,b=[int(s['color'][i:i+2],16) for i in (0,2,4)]
                    position+=';box-shadow:'+ ' '.join(f'{s[k]/plan["width"]*100}cqw' for k in ('x','y','blur'))+f' rgba({r},{g},{b},{s["opacity"]})'
                inner=''
            elif kind == 'table':
                from .ppt_component_styles import table_style, table_cell_css
                table = e.get('table',row.get('table'))
                e['table'] = deepcopy(table)
                style = table_style(e, palette) if 'tableStyle' in e else None
                columns = ''.join(f'<col style="width:{w/e["w"]*100:.6f}%">' for w in e['columnWidths'])
                rows = []
                for ri,cells in enumerate([table['headers'],*table['rows']]):
                    tag = 'th' if ri == 0 else 'td'
                    cell_css = f' style="{table_cell_css(style,ri,plan["width"])}"' if style else ''
                    cells_html = ''.join(f'<{tag}'+(f' data-edit="{edit_id}-c{ri}-{ci}"' if not fragment else '')+
                                         f'{cell_css}>{esc(v)}</{tag}>' for ci,v in enumerate(cells))
                    rows.append(f'<tr style="height:{e["rowHeights"][ri]/plan["width"]*100:.6f}cqw">'+cells_html+'</tr>')
                inner = '<table class="ppt-table"><colgroup>'+columns+'</colgroup>'+''.join(rows)+'</table>'
                position += f';font-size:{e.get("size",16)/plan["width"]*100:.6f}cqw'
            elif kind == 'chart':
                e['chart'] = deepcopy(e.get('chart',row.get('chart')))
                if 'chartStyle' in e:
                    from .ppt_component_styles import styled_chart_html
                    inner = styled_chart_html(e.get('chart',row.get('chart')), f'{id_prefix}{index}', e, palette, plan['width'], font)
                else:
                    inner = svg_chart(e.get('chart',row.get('chart')), f'{id_prefix}{index}')
            elif kind == 'image':
                im = e.get('image',row.get('image'))
                e['image'] = deepcopy(im)
                fit={'contain':'contain','cover':'cover','stretch':'fill'}[e.get('fit','contain')]
                position+=';padding:0'
                inner = f'<img style="object-fit:{fit}" src="data:{im["mime"]};base64,{im["data"]}" alt="{esc(im["alt"])}">'
            else:
                raise artifacts.ArtifactError('invalid_ppt_element', '지원하지 않는 배치 요소입니다.')
            content.append(f'<div class="ppt-element" data-kind="{kind}"{edit_attrs} style="{esc(position)}">{inner}</div>')
        notes = ''
        if row.get('chart'):
            chart = row['chart']
            rows = [[c]+[s['values'][i] for s in chart['series']] for i,c in enumerate(chart['categories'])]
            notes = '<details class="data-notes"><summary>차트 수치 확인</summary>'+artifacts._html_table(['항목']+[s['name'] for s in chart['series']],rows)+'</details>'
        pages.append(f'<section class="ppt-page" id="{esc(id_prefix)}slide-{index}" style="{esc(variables)}" aria-label="{index}장 {esc(row["title"])}"><div class="ppt-slide" data-slide="P{index:02d}" data-title="{esc(row["title"])}" style="background:{color(page.get("background","background"))}">'+''.join(content)+'</div>'+notes+'</section>')
    if fragment:
        return f'<div style="{esc(variables)}">'+''.join(pages)+'</div>'
    coverage = plan.get('coverage',[])
    coverage_html = ''
    if coverage:
        details=[]
        for row in coverage:
            unsupported=row.get('unsupported',[])
            approximations=row.get('approximations',[])
            details.append(f'<li>{row["slide"]}장: 원본 개체 {row.get("totalObjects",0)}개 중 {row.get("projectedObjects",0)}개를 투영했습니다.'+
                           (' 미지원: '+', '.join(esc(item.get('reason',item.get('kind','미확인'))) for item in unsupported[:8]) if unsupported else '')+
                           (' 근사 표현: '+', '.join(esc(item.get('reason',item.get('kind','미확인'))) for item in approximations[:8]) if approximations else '')+'</li>')
        coverage_html='<details class="data-notes"><summary>참고 양식의 미리보기 확인 범위</summary><ul>'+''.join(details)+'</ul><p>개체 투영 검사이며 실제 PowerPoint와의 화면 일치를 검증한 결과는 아닙니다.</p></details>'
    notice = ('재사용 대표 양식: 가상 예시이며 원래 업무 내용과 캡처, 경로는 저장하지 않았습니다.' if metadata else
              '편집 가능한 HTML 발표본입니다. 문구 편집 후 수정본을 저장할 수 있습니다. PPTX가 필요하면 현재 HTML로 변환을 요청하세요.')
    notice += ' PPT의 글꼴 줄바꿈·차트 세부 모양은 최종 렌더링에서 다시 확인합니다.'
    if preserve:
        notice += ' 기존 양식의 고정 개체와 교체 내용을 함께 표시합니다. 지원하지 않는 효과나 상속 서식은 아래 확인 범위를 참고하고 원본 및 최종 PPT와 비교하세요.'
    meta = ''
    if metadata:
        payload = json.dumps(metadata,ensure_ascii=True,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
        meta = f'<script id="{TEMPLATE_ID}" type="application/json">{payload}</script>'
    # Declarative scene data is carried with the editable document so that text
    # edits can be reimported without flattening native charts into SVG images.
    payload=json.dumps(plan,ensure_ascii=True,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    meta+=f'<script id="{SCENE_ID}" type="application/json">{payload}</script>'
    from .ppt_deck_shell import render_shell
    deck_notes={f'P{i:02d}':{'text':row.get('notes','') or notice,'source':row.get('source','')}
                for i,row in enumerate(data['sections'],1)}
    if coverage:
        deck_notes['P01']['text'] += '\n기존 개체의 투영 범위와 미지원 효과는 초안 생성 결과의 templatePreview를 확인하세요.'
    return render_shell(title=data['title'], slides_html=''.join(pages),
                        width=plan['width'], height=plan['height'], notes=deck_notes,
                        extra_head='<meta name="ppt-deck-format" content="editable-scene-v1">',
                        metadata_html=meta, design_css=CSS)


def _write(document, output):
    output = artifacts._target(Path(output), '.html')
    with tempfile.TemporaryDirectory(prefix='company-ppt-html-') as temp:
        draft = Path(temp)/'draft.html'
        draft.write_text(document, encoding='utf-8')
        artifacts._publish(draft, output)
    return output


def create_design_gallery(output):
    """Optional offline samples. No user files, Office, model or approval record."""
    try:
        from .ppt_layouts import examples
        samples = examples()
        panels = []
        for key, (name, description, _) in ppt_workflow.DESIGNS.items():
            data, *_ = prepare({'title':name, 'designPreset':key,
                                'compositionMode':'content-led', 'slides':samples})
            panel = render(data, fragment=True, id_prefix=key+'-')
            panels.append(f'<article id="{key}" class="gallery-style"><h2>{esc(name)}</h2>'
                          f'<p>{esc(description)}</p><p class="choose">'+
                          f'대화에서 “{esc(name)}으로 해줘”라고 알려 주세요.</p>'+panel+'</article>')
        csp = "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"
        navigation = ''.join(f'<a href="#{key}">{esc(row[0])}</a>' for key,row in ppt_workflow.DESIGNS.items())
        css = (CSS + '\n.gallery-main{max-width:1120px;margin:auto;padding:0 24px 48px}'
               '.gallery-style{padding-top:24px;scroll-margin-top:16px}.gallery-style h2{margin:0 0 8px;font-size:25px}'
               '.gallery-style>p{line-height:1.6}.choose{color:#52667c;font-size:14px}'
               '.gallery-nav{display:flex;gap:10px;flex-wrap:wrap}.gallery-nav a{padding:10px 14px;border:1px solid #cad5df;'
               'border-radius:10px;color:#17324d;text-decoration:none;background:#fff}.gallery-nav a:focus-visible{outline:3px solid #087f8c}'
               '.gallery-style .ppt-page{margin-top:18px}.gallery-style .data-notes{display:none}'
               '@media print{.gallery-main{padding:0}.gallery-style>h2,.gallery-style>p{display:none}}')
        document = ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                    f'<meta http-equiv="Content-Security-Policy" content="{esc(csp)}"><title>PPT 양식 비교</title><style>{css}</style></head>'
                    '<body><header><h1>PPT 양식을 골라 보세요</h1><p>표지, 핵심 메시지, 비교, 업무 흐름, 일정, 상세 표와 결론의 서로 다른 일곱 배치를 가상 자료로 비교합니다. '
                    '색감과 장별 배치를 함께 비교하세요. 실제 초안이나 제작 승인이 아닙니다.</p>'
                    f'<nav class="gallery-nav" aria-label="양식 바로가기">{navigation}</nav>'
                    '<p>기존 PPT나 이미지를 참고하거나, 내용에 맞게 추천받거나, 원하는 느낌을 직접 알려 주셔도 됩니다.</p></header>'
                    '<main class="gallery-main">'+''.join(panels)+'</main></body></html>')
        target = _write(document, output)
        return {'ok':True,'status':'created','outputPath':str(target), 'sampleOnly':True,
                'designs':list(ppt_workflow.DESIGNS), 'sampleSlidesPerDesign':len(samples),
                'offline':True, 'officeStarted':False, 'approvalGranted':False}
    except Exception as exc:
        return artifacts._failure(exc)


def create_draft(spec, output, template=None, *, require_choices=True):
    try:
        from .business_safety import blocked_input
        if (blocked := blocked_input(spec)) is not None:
            return blocked
        selected = ppt_workflow.choices(spec, template, for_preview=True)
        if require_choices and not selected.get('ok'):
            return selected
        digest = ppt_workflow.design_digest(spec, template)
        # A correction always measures the current input, not the previous review.
        data, arithmetic, _, native_template, preserve = prepare({k:v for k,v in spec.items() if k!='designReview'}, template)
        if preserve:
            import importlib.util
            if not importlib.util.find_spec('pptx'):
                raise artifacts.ArtifactError('template_engine_unavailable','기존 양식의 개체 배치를 확인할 라이브러리가 없습니다. 자동 설치하지 않습니다.')
            data['presentationPlan'] = ppt_workflow.fill_template(data, None, native_template, spec.get('templateSlides'), html_only=True)
        document = render(data, preserve=preserve)
        from .ppt_preflight import inspect_plan, template_summary
        preflight = inspect_plan(data['presentationPlan'])
        from .content_layout import check_plan, LayoutError
        try:
            layout_check = check_plan(data) if not preserve else {'status':'not-requested'}
        except LayoutError as exc:
            raise artifacts.ArtifactError('layout_validation_failed', str(exc)) from None
        if digest != ppt_workflow.design_digest(spec, template):
            raise artifacts.ArtifactError('design_review_changed','HTML 초안 준비 중 참고 자료가 변경되었습니다. 다시 확인해 주세요.')
        output = _write(document, output)
        return {'ok':True,'status':'created','outputPath':str(output),'previewOnly':True,'stage':'design_confirm',
                'format':'editable-html-deck','previewUrl':output.resolve().as_uri(),
                'previewLink':f'[{output.name}]({output.resolve().as_posix()})',
                'htmlReady':True,'pptxOptional':True,
                'editability':{'text':True,'tableCells':True,'layout':'authoring-spec','chartData':'authoring-spec'},
                'slides':len(data['sections']),'outline':[row['title'] for row in data['sections']],
                **({'pagination':data['slidePagination']} if 'slidePagination' in data else {}),
                'engine':'offline-html','offline':True,'officeStarted':False,
                'contentLayoutValidation':layout_check,
                'scenePreflight':preflight,
                **({'templatePreview':template_summary(data['presentationPlan']['coverage'])} if preserve else {}),
                'designReview':{'specSha256':digest,'previewPath':str(output.resolve()),
                                'previewSha256':hashlib.sha256(output.read_bytes()).hexdigest(),'confirmed':False},
                'validation':{'arithmetic':arithmetic,'visualReview':'required','nativePptValidation':'after-approval'},
                'warnings':data['presentationPlan'].get('warnings',[])+['HTML과 PPT는 같은 배치·수치를 사용하지만 브라우저와 PowerPoint의 렌더링은 다를 수 있습니다.']+
                           (['기존 양식은 판독 가능한 고정 개체를 함께 표시했습니다. 미지원 요소와 근사 범위는 templatePreview 및 원본 양식에서 확인하세요.'] if preserve else [])}
    except Exception as exc:
        return artifacts._failure(exc)


def save_template(spec, output, template=None):
    """User chooses the destination; never auto-publish into company/personal roots."""
    try:
        from .business_safety import blocked_input
        if (blocked := blocked_input(spec)) is not None:
            return blocked
        selected = ppt_workflow.choices(spec, template)
        if not selected.get('ok'):
            return selected
        ppt_workflow.verify_design_review(spec, template)
        data, _, _, _, preserve = prepare(spec, template)
        if preserve:
            raise artifacts.ArtifactError('preserved_template_not_portable','원본 개체·마스터 유지 양식은 PPTX 원본이 필요합니다. HTML 대표 양식으로 따로 저장하려면 디자인 참고 방식으로 전환할지 먼저 확인해 주세요.')
        plan = data['presentationPlan']
        metadata = {'schema':SCHEMA,'layoutVersion':1,'presentationTheme':plan['theme'],
                    'presentationFont':plan['font'],'presentationFrame':{'width':plan['width'],'height':plan['height']}}
        scene_layout=bool(spec.get('htmlSource') or any('elements' in r or 'contentOrder' in r or r.get('pageRole')
                          or r.get('layout', 'auto') != 'auto' for r in data['sections']))
        # Deliberately never retain original values, captions, references or images.
        sample = {**metadata,'title':'PPT 대표 양식', 'slides':[
            {'title':'발표 제목','body':'발표의 목적과 핵심 내용을 입력합니다.'},
            {'title':'주요 지표 비교','chart':{'type':'column','categories':['항목 A','항목 B','항목 C'],
                'series':[{'name':'계획','values':[100,100,100]},{'name':'결과','values':[90,110,120]}]}},
            {'title':'상세 내용','table':{'headers':['항목','내용','상태'],'rows':[['예시 A','확인할 내용','검토'],['예시 B','후속 조치','예정']]}}]}
        if scene_layout:
            from .ppt_scene import template_layouts
            from copy import deepcopy
            template_plan = deepcopy(plan)
            for row, page in zip(data['sections'], template_plan['pages']):
                for e in page['elements']:
                    if e['kind'] in ('table','chart') and e['kind'] not in e:
                        e[e['kind']] = deepcopy(row[e['kind']])
            metadata.update(layoutVersion=2,layouts=template_layouts(template_plan))
            sample={**metadata,'title':'PPT 대표 양식','slides':[{'title':f'배치 {i+1}','elements':p['elements'],'background':p.get('background','FFFFFF')} for i,p in enumerate(metadata['layouts'])]}
        sample_data, _, _, _, _ = prepare(sample)
        document = render(sample_data, metadata=metadata)
        ppt_workflow.verify_design_review(spec, template)
        output = _write(document, output)
        return {'ok':True,'status':'created','outputPath':str(output),'format':'html',
                'businessContentStored':False,'referenceImagesStored':False,'companyPolicyChanged':False,
                'reuse':'business ppt-design-preview --spec NEW_JOB.json --template SAVED.html --work WORK_FILE',
                'layoutCount':len(metadata.get('layouts',[])),
                'message':'디자인·글꼴·페이지 규격과 공통 배치 버전을 가상 예시 HTML로 저장했습니다. 저장 위치는 다른 사용자·프로젝트에 자동 적용되지 않습니다.'}
    except Exception as exc:
        return artifacts._failure(exc)
