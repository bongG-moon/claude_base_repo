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
        if template or spec.get('referenceMode') == 'preserve':
            raise artifacts.ArtifactError('invalid_choice','캡처와 원본 양식 유지 조건을 함께 적용하지 않습니다. 디자인 기준을 확인해 주세요.')
        for path in spec['referenceImages']:
            artifacts._image({'path':path})
        if not spec.get('presentationTheme'):
            raise artifacts.ArtifactError('reference_design_needed', '첨부 캡처를 먼저 보고 색감·글꼴·구성을 해석해 presentationTheme에 반영해 주세요. 캡처를 슬라이드 배경으로 붙이지 않습니다.')
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
    except (presentation_design.DesignError, FactError) as exc:
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
    data['sections']=[{'title':p.get('title',f'{i+1}장'),'body':'','bullets':[]} for i,p in enumerate(plan['pages'])]
    data['presentationPlan']=plan
    return data,{'status':'not_declared','message':'HTML의 수치는 원문대로 옮겼으며 계산 관계는 별도 검증이 필요합니다.'},None,None,False


CSS = """
*{box-sizing:border-box}body{margin:0;background:#edf0f4;color:#243247;font-family:'Malgun Gothic','Segoe UI',sans-serif}
header,footer{max-width:1160px;margin:auto;padding:24px}header h1{margin:0 0 10px;font-size:24px}header p,footer{font-size:14px;line-height:1.7}
.ppt-main{max-width:1160px;margin:auto;padding:0 24px 24px}.ppt-page{container-type:inline-size;margin:0 0 24px;overflow:auto;border:1px solid #d7dfe8;box-shadow:0 6px 25px #17324d12}
.ppt-slide{position:relative;aspect-ratio:var(--pw)/var(--ph);background:var(--paper);color:var(--ink);font-family:var(--font);overflow:hidden}
.ppt-element{position:absolute;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.15;padding:2px 0}
.ppt-table{width:100%;border-collapse:collapse;table-layout:fixed;white-space:normal}.ppt-table th,.ppt-table td{padding:4px 6px;vertical-align:middle;border-bottom:1px solid var(--line);line-height:1.15}
.ppt-table th{background:var(--title);color:var(--paper);font-weight:700}.ppt-table tr:nth-child(2n){background:var(--line)}
.ppt-element figure{margin:0;width:100%;height:100%;display:flex;flex-direction:column}.ppt-element figcaption{display:none}.report-chart{width:100%;height:calc(100% - 22px);flex:1;min-height:0;overflow:visible}
.report-chart text{fill:var(--muted);font:13px 'Malgun Gothic',sans-serif}.report-chart .chart-value{fill:var(--ink);font-weight:700}.gridline{stroke:var(--line);stroke-width:1}
.legend{display:flex;justify-content:center;gap:18px;font-size:12px;white-space:normal}.legend i{display:inline-block;width:9px;height:9px;margin-right:6px}
.ppt-element img{width:100%;height:100%;object-fit:contain}.data-notes{padding:12px 18px;background:#fff;font-size:13px}.data-notes summary{cursor:pointer}.data-notes table{border-collapse:collapse;margin:10px 0}.data-notes td,.data-notes th{padding:5px 15px;text-align:left}
@media print{header,footer,.data-notes{display:none}.ppt-main{max-width:none;padding:0}.ppt-page{break-after:page;box-shadow:none;margin:0;border:0}@page{size:landscape;margin:8mm}}
"""


def render(data, *, metadata=None, preserve=False):
    from .report_design import svg_chart
    plan = data['presentationPlan']
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
        for e in page['elements']:
            position = ';'.join(f'{prop}:{e[key]/plan[dimension]*100:.6f}%'
                                for prop,key,dimension in [('left','x','width'),('top','y','height'),('width','w','width'),('height','h','height')])
            kind = e['kind']
            if kind == 'text':
                position += f";font-size:{e['size']}px;font-size:{e['size']/plan['width']*100:.6f}cqw;color:{color(e['color'])};font-weight:{700 if e['bold'] else 400}"
                inner = esc(e['text'])
                if 'wrap' in e:
                    position+=f';padding:0;line-height:{e.get("lineSpacing",1.15)};text-align:{e.get("align","left")};white-space:{"pre-wrap" if e["wrap"] else "pre"}'
                    face=''.join(c for c in e.get('font','') if c.isalnum() or c in ' -_')
                    if face: position+=f";font-family:'{face}',sans-serif"
                    if e.get('italic'): position+=';font-style:italic'
                    if e.get('underline'): position+=';text-decoration:underline'
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
                table = e.get('table',row.get('table'))
                columns = ''.join(f'<col style="width:{w/e["w"]*100:.6f}%">' for w in e['columnWidths'])
                rows = []
                for ri,cells in enumerate([table['headers'],*table['rows']]):
                    tag = 'th' if ri == 0 else 'td'
                    rows.append(f'<tr style="height:{e["rowHeights"][ri]/plan["width"]*100:.6f}cqw">'+''.join(f'<{tag}>{esc(v)}</{tag}>' for v in cells)+'</tr>')
                inner = '<table class="ppt-table"><colgroup>'+columns+'</colgroup>'+''.join(rows)+'</table>'
                position += f';font-size:{e.get("size",16)/plan["width"]*100:.6f}cqw'
            elif kind == 'chart':
                inner = svg_chart(e.get('chart',row.get('chart')), index)
            elif kind == 'image':
                im = e.get('image',row.get('image'))
                fit={'contain':'contain','cover':'cover','stretch':'fill'}[e.get('fit','contain')]
                position+=';padding:0'
                inner = f'<img style="object-fit:{fit}" src="data:{im["mime"]};base64,{im["data"]}" alt="{esc(im["alt"])}">'
            else:
                raise artifacts.ArtifactError('invalid_ppt_element', '지원하지 않는 배치 요소입니다.')
            content.append(f'<div class="ppt-element" data-kind="{kind}" style="{esc(position)}">{inner}</div>')
        notes = ''
        if row.get('chart'):
            chart = row['chart']
            rows = [[c]+[s['values'][i] for s in chart['series']] for i,c in enumerate(chart['categories'])]
            notes = '<details class="data-notes"><summary>차트 수치 확인</summary>'+artifacts._html_table(['항목']+[s['name'] for s in chart['series']],rows)+'</details>'
        pages.append(f'<section class="ppt-page" id="slide-{index}" aria-label="{index}장 {esc(row["title"])}"><div class="ppt-slide" style="background:{color(page.get("background","background"))}">'+''.join(content)+'</div>'+notes+'</section>')
    notice = ('재사용 대표 양식 · 아래는 가상 예시입니다. 원래 업무 내용·캡처·경로는 저장하지 않았습니다.' if metadata else
              'HTML 초안 · 전체 슬라이드를 확인한 뒤 대화에서 제작을 승인해 주세요. HTML을 직접 수정하지 말고 수정 내용을 알려 주세요.')
    notice += ' PPT의 글꼴 줄바꿈·차트 세부 모양은 최종 렌더링에서 다시 확인합니다.'
    if preserve:
        notice += ' 기존 양식의 교체 대상 위치·내용만 표시합니다. 고정 개체·배경·마스터의 실제 모양은 이 초안에서 재현하지 않습니다.'
    meta = ''
    if metadata:
        payload = json.dumps(metadata,ensure_ascii=True,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
        meta = f'<script id="{TEMPLATE_ID}" type="application/json">{payload}</script>'
    elif plan.get('source'):
        payload=json.dumps(plan,ensure_ascii=True,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
        meta=f'<script id="{SCENE_ID}" type="application/json">{payload}</script>'
    csp = "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="Content-Security-Policy" content="{esc(csp)}"><title>{esc(data["title"])}</title><style>{CSS}</style>{meta}</head>'
            f'<body data-ppt-draft="1" style="{esc(variables)}"><header><h1>{esc(data["title"])}</h1><p>{esc(notice)}</p></header>'
            '<main class="ppt-main">'+''.join(pages)+'</main><footer>텍스트·표·차트는 최종 PPT에서 네이티브 개체로 제작합니다. 사진·그림 자체는 이미지입니다.</footer></body></html>')


def _write(document, output):
    output = artifacts._target(Path(output), '.html')
    with tempfile.TemporaryDirectory(prefix='company-ppt-html-') as temp:
        draft = Path(temp)/'draft.html'
        draft.write_text(document, encoding='utf-8')
        artifacts._publish(draft, output)
    return output


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
        if digest != ppt_workflow.design_digest(spec, template):
            raise artifacts.ArtifactError('design_review_changed','HTML 초안 준비 중 참고 자료가 변경되었습니다. 다시 확인해 주세요.')
        output = _write(document, output)
        return {'ok':True,'status':'created','outputPath':str(output),'previewOnly':True,'stage':'design_confirm',
                'slides':len(data['sections']),'outline':[row['title'] for row in data['sections']],
                'engine':'offline-html','offline':True,'officeStarted':False,
                'designReview':{'specSha256':digest,'previewPath':str(output.resolve()),
                                'previewSha256':hashlib.sha256(output.read_bytes()).hexdigest(),'confirmed':False},
                'validation':{'arithmetic':arithmetic,'visualReview':'required','nativePptValidation':'after-approval'},
                'warnings':data['presentationPlan'].get('warnings',[])+['HTML과 PPT는 같은 배치·수치를 사용하지만 브라우저와 PowerPoint의 렌더링은 다를 수 있습니다.']+
                           (['기존 양식의 고정 개체·배경·마스터는 HTML에서 생략됩니다. 원본 양식과 최종 PPT에서 별도로 확인하세요.'] if preserve else [])}
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
        scene_layout=bool(spec.get('htmlSource') or any('elements' in r for r in data['sections']))
        # Deliberately never retain original values, captions, references or images.
        sample = {**metadata,'title':'PPT 대표 양식', 'slides':[
            {'title':'발표 제목','body':'발표의 목적과 핵심 내용을 입력합니다.'},
            {'title':'주요 지표 비교','chart':{'type':'column','categories':['항목 A','항목 B','항목 C'],
                'series':[{'name':'계획','values':[100,100,100]},{'name':'결과','values':[90,110,120]}]}},
            {'title':'상세 내용','table':{'headers':['항목','내용','상태'],'rows':[['예시 A','확인할 내용','검토'],['예시 B','후속 조치','예정']]}}]}
        if scene_layout:
            from .ppt_scene import template_layouts
            metadata.update(layoutVersion=2,layouts=template_layouts(plan))
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
