"""Shared, bounded slide composition for Python and Office. No generated code.

Coordinates are points on the actual page, not browser pixels. Conservative text
estimates reject dense input instead of truncating it or shrinking body text.
Estimates are not a substitute for rendering and inspecting every slide.
"""
from __future__ import annotations

import math
import re
import unicodedata
from . import report_facts


class DesignError(ValueError):
    pass


def _text(value, limit=200):
    if not isinstance(value, str) or len(value) > limit:
        raise DesignError("슬라이드의 제목·설명 길이와 형식을 확인해 주세요.")
    return value


def prepare(spec, data):
    from .ppt_component_styles import normalize as component_style
    for kind in ('table', 'chart'):
        key = kind + 'Style'
        if key in spec:
            data[key] = component_style(kind, spec[key])
    composition = spec.get('compositionMode', 'classic')
    if composition not in ('classic', 'content-led'):
        raise DesignError('장별 자동 구성은 compositionMode: content-led 또는 classic으로 지정해 주세요.')
    facts, validation = report_facts.resolve(spec, data['sections'])
    bind = lambda s: report_facts.bind(s, facts)
    for key in ('title', 'subtitle'):
        data[key] = bind(data[key])
    raw_rows = spec.get('sections', spec.get('slides'))
    for raw, row in zip(raw_rows, data['sections']):
        for kind in ('table', 'chart'):
            key = kind + 'Style'
            if key in data or key in raw:
                row[key] = {**data.get(key, {}), **component_style(kind, raw.get(key, {}))}
        for key in ('title', 'body'):
            row[key] = bind(row[key])
        row['bullets'] = [bind(s) for s in row['bullets']]
        if 'table' in row:
            row['table']['headers'] = [bind(s) for s in row['table']['headers']]
            row['table']['rows'] = [[bind(s) for s in r] for r in row['table']['rows']]
        row['eyebrow'] = bind(_text(raw.get('eyebrow', ''), 70))
        row['takeaway'] = bind(_text(raw.get('takeaway', ''), 160))
        row['source'] = bind(_text(raw.get('source', ''), 180))
        row['notes'] = bind(_text(raw.get('notes', ''), 8000))
        # Page roles and design anchors are optional; legacy jobs stay unchanged.
        from copy import deepcopy
        for field in ('pageRole','workflow','milestones','panels'):
            if field in raw:
                row[field] = deepcopy(raw[field])
        semantic = [field for field in ('workflow','milestones','panels') if field in raw]
        if semantic:
            if ('elements' in raw or 'contentOrder' in row or raw.get('imageLayout')=='full-slide'):
                raise DesignError('업무 흐름, 일정과 비교 항목을 자유 배치나 contentOrder, 전체 이미지와 섞지 마세요. pageRole로 구성하거나 모든 내용을 elements에 담아 주세요.')
            if not raw.get('pageRole'):
                raise DesignError('workflow, milestones와 panels에는 해당 pageRole을 지정해 주세요. 내용을 생략하지 않았습니다.')
        for field in ('panels','milestones'):
            if isinstance(row.get(field),list):
                for item in row[field]:
                    if isinstance(item,dict):
                        for key in ('title','body','label','detail'):
                            if isinstance(item.get(key),str): item[key]=bind(item[key])
                        if isinstance(item.get('bullets'),list):
                            item['bullets']=[bind(value) for value in item['bullets']]
        if isinstance(row.get('workflow'),dict):
            for field in ('nodes','edges'):
                if isinstance(row['workflow'].get(field),list):
                    for item in row['workflow'][field]:
                        if isinstance(item,dict):
                            for key in ('title','body','label'):
                                if isinstance(item.get(key),str): item[key]=bind(item[key])
        if 'elements' in raw:
            if 'contentOrder' in row:
                raise DesignError('자유 배치 elements에는 contentOrder를 섞지 마세요. 승인할 elements 좌표에서 본문 순서를 직접 지정하세요.')
            if any(raw.get(k) for k in ('body','bullets','image','chart','table','kpis')):
                raise DesignError('자유 배치 elements와 자동 본문 배치를 한 장에 섞지 마세요. 모든 내용을 elements에 담아 주세요.')
            from copy import deepcopy
            row['elements'] = deepcopy(raw['elements'])
            if isinstance(row['elements'],list):
                for e in row['elements']:
                    if isinstance(e,dict) and e.get('kind')=='text':
                        if isinstance(e.get('text'),str): e['text']=bind(e['text'])
                        if isinstance(e.get('runs'),list):
                            for run in e['runs']:
                                if isinstance(run,dict) and isinstance(run.get('text'),str):
                                    run['text']=bind(run['text'])
            from .ppt_scene import ink
            # Keep omission distinct until the active theme is resolved below.
            if 'background' in raw:
                row['background']=ink(raw['background'],{})
        if raw.get('imageLayout') == 'full-slide':
            if 'contentOrder' in row:
                raise DesignError('전체 화면 이미지와 contentOrder를 함께 지정하지 마세요.')
            if any(raw.get(k) for k in ('body','bullets','chart','table','kpis')) or not row.get('image'):
                raise DesignError('전체 화면 이미지는 image만 있는 장에서 사용합니다. 텍스트 편집 가능 슬라이드로 설명하지 마세요.')
            row['imageLayout'] = 'full-slide'
        row['imageFit'] = raw.get('imageFit','contain')
        if row['imageFit'] not in ('contain','cover','stretch'):
            raise DesignError('이미지 맞춤은 contain, cover, stretch입니다.')
        row['layout'] = raw.get('layout', 'auto')
        if (composition == 'content-led' and 'layout' not in raw and 'contentOrder' not in row
                and 'elements' not in row and row.get('imageLayout') != 'full-slide'):
            visuals = [key for key in ('chart', 'table', 'image') if row.get(key)]
            row['layout'] = ('comparison' if len(visuals) > 1 else
                             'actions' if visuals == ['table'] else
                             'evidence' if visuals else 'summary')
        if row['layout'] not in ('auto', 'summary', 'evidence', 'comparison', 'actions'):
            raise DesignError("PPT 구성은 auto, summary, evidence, comparison, actions 중 선택해 주세요.")
        kpis = raw.get('kpis', [])
        if not isinstance(kpis, list) or len(kpis) > 3:
            raise DesignError("한 장의 핵심 지표는 3개 이하로 나누어 주세요.")
        row['kpis'] = []
        for item in kpis:
            if not isinstance(item, dict) or not isinstance(item.get('fact'), str) or item['fact'] not in facts:
                raise DesignError("핵심 지표는 계산한 공통 수치의 fact ID로 연결해 주세요.")
            fact = facts[item['fact']]
            row['kpis'].append({'label': _text(fact['label'], 32), 'value': fact['display'],
                                'unit': _text(fact['unit'], 12)})
        if 'chart' in row:
            row['chart']['title'] = bind(_text(raw['chart'].get('title', ''), 90))
            row['chart']['categories'] = [bind(value) for value in row['chart']['categories']]
            for series in row['chart']['series']:
                series['name'] = bind(series['name'])
            if len(row['chart']['categories']) > 12 or len(row['chart']['series']) > 4:
                raise DesignError("PPT 차트는 항목 12개·계열 4개 이하로 나누어 주세요.")
            if any(len(s) > 22 for s in row['chart']['categories']) or any(len(s['name']) > 24 for s in row['chart']['series']):
                raise DesignError("차트의 항목명과 범례를 짧게 정리해 주세요.")
    # Explicit theme tokens allow an inspected template's palette to be followed.
    # They do not claim exact reconstruction of arbitrary masters or layouts.
    tokens = {'title': '17324D', 'accent': '087F8C', 'text': '30465B',
              'muted': '52667C', 'background': 'FFFFFF', 'tint': 'EEF4F7'}
    if 'designPreset' in spec:
        from .ppt_workflow import DESIGNS
        if spec['designPreset'] not in DESIGNS:
            raise DesignError('지원하는 PPT 디자인을 선택해 주세요.')
        tokens.update(DESIGNS[spec['designPreset']][2])
    custom = spec.get('presentationTheme', {})
    if not isinstance(custom, dict) or set(custom) - set(tokens):
        raise DesignError("PPT 색상 설정 항목을 확인해 주세요.")
    for key, value in custom.items():
        if not isinstance(value, str) or not re.fullmatch('[0-9A-Fa-f]{6}', value):
            raise DesignError("PPT 색상은 # 없이 여섯 자리 색상값으로 지정해 주세요.")
        tokens[key] = value.upper()
    def luminance(value):
        channels = [int(value[i:i+2], 16)/255 for i in (0, 2, 4)]
        linear = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in channels]
        return sum(v*w for v, w in zip(linear, (.2126,.7152,.0722)))
    for front, back in (('text','background'), ('text','tint'), ('title','background'), ('muted','background'), ('accent','background')):
        a, b = sorted((luminance(tokens[front]), luminance(tokens[back])))
        if (b+.05)/(a+.05) < 4.5:
            raise DesignError("글자와 배경 색상이 너무 비슷합니다. 읽기 쉬운 대비의 색상을 선택해 주세요.")
    data['presentationTheme'] = tokens
    font = spec.get('presentationFont', 'Malgun Gothic')
    if not isinstance(font,str) or not font.strip() or len(font)>80:
        raise DesignError('글꼴 이름을 확인해 주세요.')
    if font != 'Malgun Gothic':
        from .ppt_workflow import font_available
        if not font_available(font):
            raise DesignError('양식의 글꼴을 이 PC에서 확인하지 못했습니다. 설치된 글꼴을 선택해 주세요. 자동 다운로드하지 않습니다.')
    data['presentationFont'] = font
    if 'presentationProfile' in spec or any(row.get('pageRole') for row in data['sections']):
        from .ppt_layouts import profile
        data['presentationProfile'] = profile(spec)
        data['presentationProfileSpecified'] = 'presentationProfile' in spec
    return validation


def _lines(text, width, size):
    # Hangul is roughly one em, Latin half an em; reserve wrapping tolerance.
    capacity = max(1, (width - 12) / (size * 1.08))
    return sum(max(1, math.ceil(sum(1 if unicodedata.east_asian_width(c) in 'WF' else .56 for c in line) / capacity)) for line in text.split('\n'))


def _table_metrics(table, width, style=None):
    rows = [table['headers'], *table['rows']]
    weights = [min(3.5, max(1, max(sum(1 if unicodedata.east_asian_width(c) in 'WF' else .56 for c in r[j]) for r in rows)/9)) for j in range(len(table['headers']))]
    widths = [width*v/sum(weights) for v in weights]
    if style:
        size, padding = style.get('fontSize', 16), style.get('padding', 6)
        heights = [max(36, max(_lines(cell, max(1, widths[j]-2*padding+12), size) for j, cell in enumerate(r))*size*1.31+2*padding+4) for r in rows]
    else:
        heights = [max(36, max(_lines(cell, widths[j], 16) for j, cell in enumerate(r))*21+16) for r in rows]
    return widths, heights


def _vertical(row, number, x, y, width, bottom, elements, text, profile=None):
    gap = profile['gap'] if profile else 18.
    body_size = profile['bodySize'] if profile else 18
    table_size = profile['tableSize'] if profile else 16
    table_style = {'fontSize':table_size, **row.get('tableStyle', {})} if profile else row.get('tableStyle')
    caption_h, caption_offset = _chart_caption(row.get('chart', {}), width, profile)
    specs = []
    for name in row['contentOrder']:
        entry = {'name': name}
        if name in ('body', 'bullets'):
            value = row['body'] if name == 'body' else '\n\n'.join(row['bullets'])
            entry.update(value=value, h=_lines(value, width, body_size)*body_size*1.27+4)
        elif name == 'table':
            widths, heights = _table_metrics(row['table'], width, table_style)
            entry.update(h=sum(heights), columnWidths=widths, rowHeights=heights)
        elif name in ('chart', 'image'):
            entry['h'] = 180. + (caption_offset if name == 'chart' else 0.)
        else:
            raise DesignError('이 본문 항목은 PPT의 세로 배치로 만들 수 없습니다. 지원되는 배치를 확인해 주세요.')
        specs.append(entry)
    required = sum(e['h'] for e in specs) + gap*(len(specs)-1)
    if required > bottom-y+.01:
        raise DesignError(f'{number}장에 요청한 본문 순서를 읽기 좋은 크기로 담을 수 없습니다. 설명을 줄이거나 장을 나눌지 확인해 주세요. 옆 배치·글자 축소로 바꾸지 않았습니다.')
    flexible = sum(e['name'] in ('chart','image') for e in specs)
    extra = (bottom-y-required)/flexible if flexible else 0.
    blocks = []
    for entry in specs:
        name, h = entry['name'], entry['h']
        if name in ('chart','image'):
            h += extra
        first = len(elements)
        if name in ('body','bullets'):
            text(entry['value'], x, y, width, h)
        elif name == 'table':
            elements.append(dict(kind='table', x=x, y=y, w=width, h=h, size=table_size,
                                 columnWidths=entry['columnWidths'], rowHeights=entry['rowHeights']))
        elif name == 'image':
            elements.append(dict(kind='image', x=x, y=y, w=width, h=h, fit=row.get('imageFit','contain')))
        else:
            title = row['chart'].get('title','')
            if title:
                text(title, x, y, width, caption_h, 15, 'muted', True)
            elements.append(dict(kind='chart', x=x, y=y+caption_offset, w=width, h=h-caption_offset))
        blocks.append(dict(name=name, y=y, h=h, elementIndices=list(range(first,len(elements)))))
        y += h+gap
    return blocks


def _chart_caption(chart, width, profile):
    if not chart.get('title'):
        return 0., 0.
    size = profile['annotationSize'] if profile else 15
    h = max(27., _lines(chart['title'],width,size)*size*1.27+4) if profile else 27.
    return h, h+4


def _profile_kpis(row, margin, top, usable, elements, text, profile):
    gap = profile['gap']
    width = (usable-gap*(len(row['kpis'])-1))/len(row['kpis'])
    label_size, value_size = profile['annotationSize'], profile['emphasisSize']
    label_h = max(_lines(k['label']+(' / '+k['unit'] if k['unit'] else ''),width,label_size)*label_size*1.27+4 for k in row['kpis'])
    value_h = max(_lines(k['value'],width,value_size)*value_size*1.27+4 for k in row['kpis'])
    for index, kpi in enumerate(row['kpis']):
        x = margin+index*(width+gap)
        first = len(elements)
        text(kpi['label']+(' / '+kpi['unit'] if kpi['unit'] else ''),x,top,width,label_h,15,'muted')
        text(kpi['value'],x,top+label_h+4,width,value_h,38,'accent',True)
        for element in elements[first:]:
            element['group'] = f'kpi-{index+1}'
    return top+label_h+4+value_h+gap


def _structured(row, number, width, height, elements, text, profile=None):
    """Answer-first layouts using primitives supported by both native exporters."""
    margin = profile['margin'] if profile else width*.05
    usable, gap = width-2*margin, profile['gap'] if profile else 28.
    bottom = height-margin if profile else height-48
    body_size = profile['bodySize'] if profile else 18
    title_size = profile['titleSize'] if profile else 30
    annotation_size = profile['annotationSize'] if profile else 10
    table_size = profile['tableSize'] if profile else 16
    table_style = {'fontSize':table_size, **row.get('tableStyle', {})} if profile else row.get('tableStyle')
    section_gap = gap if profile else 20
    layout = row['layout']
    annotation_h = max(22, annotation_size*1.27+4) if profile else 22
    page_number_w = max(30,annotation_size*2+12) if profile else 30
    text(row.get('eyebrow', ''), margin, margin if profile else 12, usable, annotation_h if profile else 20, 11, 'muted')
    title_lines = _lines(row['title'], usable, title_size)
    if title_lines > 2:
        raise DesignError(f'{number}장 결론 제목이 두 줄보다 깁니다. 뜻을 유지해 줄이거나 장을 나누어 주세요.')
    title_y = (margin+annotation_h+gap if row.get('eyebrow') else margin) if profile else (37. if row.get('eyebrow') else 24.)
    title_h = title_lines*title_size*1.27+4
    text(row['title'], margin, title_y, usable, title_h, 30, 'title', True)
    top = title_y+title_h+section_gap
    text(row.get('source', ''), margin, height-31, usable-page_number_w-15, annotation_h, 10, 'muted')
    text(f'{number:02d}', width-margin-page_number_w, height-31, page_number_w, annotation_h, 10, 'muted')
    takeaway = row.get('takeaway', '')
    if takeaway:
        takeaway_h = _lines(takeaway, usable, body_size)*body_size*1.27+4
        if layout in ('evidence', 'actions'):
            text(takeaway, margin, bottom-takeaway_h, usable, takeaway_h, 18, 'accent', True)
            bottom -= takeaway_h+section_gap
        else:
            text(takeaway, margin, top, usable, takeaway_h, 18, 'accent', True)
            top += takeaway_h+section_gap
    if row.get('kpis') and profile:
        top = _profile_kpis(row,margin,top,usable,elements,text,profile)
    elif row.get('kpis'):
        kpi_w = usable/len(row['kpis'])
        for index, kpi in enumerate(row['kpis']):
            x = margin+index*kpi_w
            first = len(elements)
            text(kpi['label']+(' · '+kpi['unit'] if kpi['unit'] else ''), x, top, kpi_w-16, 26, 15, 'muted')
            text(kpi['value'], x, top+28, kpi_w-16, 57, 38, 'accent', True)
            for element in elements[first:]:
                element['group'] = f'kpi-{index+1}'
        top += 103
    if top > bottom:
        raise DesignError(f'{number}장 제목·요약·지표가 본문 영역보다 큽니다. 내용을 줄이거나 장을 나누어 주세요.')
    visuals = [k for k in ('chart', 'table', 'image') if row.get(k)]
    prose = '\n\n'.join(([row['body']] if row['body'] else [])+row['bullets'])
    if not visuals and not prose and not row.get('kpis'):
        raise DesignError(f'{number}장에 제목 외의 핵심 내용이 없습니다.')
    if len(visuals) > 2 or (len(visuals) == 2 and prose and layout != 'comparison'):
        raise DesignError(f'{number}장에 근거와 설명이 너무 많습니다. 비교 구성으로 바꾸거나 장을 나누어 주세요.')

    def visual(kind, x, y, w, h):
        if h <= 0:
            raise DesignError(f'{number}장 근거 영역이 부족합니다. 설명을 줄이거나 장을 나누어 주세요.')
        e = dict(kind=kind, x=x, y=y, w=w, h=h)
        if kind == 'table':
            widths, heights = _table_metrics(row['table'], w, table_style)
            if sum(heights) > h:
                raise DesignError(f'{number}장 표를 읽기 좋은 크기로 담을 수 없습니다. 행·열을 나누어 주세요.')
            e.update(h=sum(heights), columnWidths=widths, rowHeights=heights, size=table_size)
        elif kind == 'chart':
            title = row['chart'].get('title', '')
            caption_h, caption_offset = _chart_caption(row['chart'],w,profile)
            if w < 260 or h-caption_offset < 180:
                raise DesignError(f'{number}장 차트 공간이 작습니다. 지표나 설명을 다른 장으로 옮겨 주세요.')
            if title:
                text(title, x, y, w, caption_h, 15, 'muted', True)
                e.update(y=y+caption_offset, h=h-caption_offset)
        else:
            e['fit'] = row.get('imageFit', 'contain')
        elements.append(e)
        return e['h']+(_chart_caption(row['chart'],w,profile)[1] if kind == 'chart' else 0)

    # An action table spans the page so owners/status text keeps readable width.
    if layout == 'actions':
        if len(visuals) > 1:
            raise DesignError(f'{number}장 실행안의 표·차트는 한 개씩 나누어 주세요.')
        prose_h = _lines(prose, usable, body_size)*body_size*1.27+4 if prose else 0
        if visuals:
            used = visual(visuals[0], margin, top, usable, bottom-top-(prose_h+section_gap if prose else 0))
            top += used+section_gap
        text(prose, margin, top, usable, bottom-top, 18)
        return
    # Two compared exhibits may share a conclusion underneath, never dropped.
    if layout == 'comparison' and len(visuals) == 2:
        prose_h = _lines(prose, usable, body_size)*body_size*1.27+4 if prose else 0
        h = bottom-top-(prose_h+section_gap if prose else 0)
        for index, kind in enumerate(visuals):
            visual(kind, margin+index*(usable+gap)/2, top, (usable-gap)/2, h)
        text(prose, margin, bottom-prose_h, usable, prose_h, 18)
        return
    if visuals:
        if len(visuals) == 2:
            for index, kind in enumerate(visuals):
                visual(kind, margin+index*(usable+gap)/2, top, (usable-gap)/2, bottom-top)
        elif prose:
            fraction = {'summary':.58, 'evidence':.70, 'comparison':.50}[layout]
            w = (usable-gap)*fraction
            visual(visuals[0], margin, top, w, bottom-top)
            text(prose, margin+w+gap, top, usable-w-gap, bottom-top, 18)
        else:
            visual(visuals[0], margin, top, usable, bottom-top)
        return
    if layout == 'summary':
        if row['body']:
            summary_size = body_size if profile else 22
            h = _lines(row['body'], usable, summary_size)*summary_size*1.27+4
            if h > bottom-top:
                raise DesignError(f'{number}장 핵심 요약이 너무 깁니다. 뜻을 유지해 줄이거나 장을 나누어 주세요.')
            text(row['body'], margin, top, usable, h, 22)
            top += h+(gap if profile else 24)
        columns = min(len(row['bullets']), 3) if len(row['bullets']) <= 3 else 2
        if columns:
            per_column = math.ceil(len(row['bullets'])/columns)
            w = (usable-gap*(columns-1))/columns
            for index in range(columns):
                values = row['bullets'][index*per_column:(index+1)*per_column]
                text('\n\n'.join(values), margin+index*(w+gap), top, w, bottom-top, 18)
    elif layout == 'comparison' and row['bullets']:
        if row['body']:
            columns = [row['body'], '\n\n'.join(row['bullets'])]
        else:
            split = math.ceil(len(row['bullets'])/2)
            columns = ['\n\n'.join(row['bullets'][:split]), '\n\n'.join(row['bullets'][split:])]
        for index, value in enumerate(columns):
            text(value, margin+index*(usable+gap)/2, top, (usable-gap)/2, bottom-top, 18)
    else:
        text(prose, margin, top, usable, bottom-top, 21)


def plan(data, width=960., height=540.):
    from .ppt_component_styles import inherit as component_styles
    if not (600 <= width <= 1800 and 400 <= height <= 1100 and 1.25 <= width / height <= 2.1):
        raise DesignError("이 양식의 화면 비율은 자동 배치를 지원하지 않습니다. 4:3 또는 16:9 양식을 선택해 주세요.")
    profile = data.get('presentationProfile') if data.get('presentationProfileSpecified') else None
    margin = profile['margin'] if profile else width*.05
    right, bottom = width-margin, height-margin if profile else height-48
    usable = right - margin
    pages = []
    for number, row in enumerate(data['sections'], 1):
        elements = []

        if 'elements' in row:
            from .ppt_scene import elements as validate_elements
            pages.append({'elements':validate_elements(component_styles(row['elements'],row),width,height,data['presentationTheme']), 'background':row.get('background',data['presentationTheme']['background'])})
            continue
        if row.get('imageLayout') == 'full-slide':
            pages.append({'elements':[dict(kind='image',x=0,y=0,w=width,h=height,fit=row['imageFit'])]})
            continue

        def text(value, x, y, w, h, size=18, color='text', bold=False):
            if not value:
                return
            role = 'title' if size == 30 else 'emphasis' if size == 38 else 'annotation' if size in (10,11,15) else 'body'
            if profile:
                size = profile[role+'Size']
            if _lines(value, w, size) * size * 1.27 + 4 > h:
                raise DesignError(f"{number}장 글자가 배치 공간보다 많습니다. 문장을 줄이거나 장을 나누어 주세요.")
            e = dict(kind='text', text=value, x=x, y=y, w=w, h=h, size=size, color=color, bold=bold)
            if profile:
                e.update(font=profile['titleFont' if role in ('title','emphasis') else 'bodyFont'],
                         wrap=True,align='left',lineSpacing=1.15)
            elements.append(e)

        if row.get('pageRole') and 'contentOrder' not in row:
            from .ppt_layouts import compose
            from .ppt_scene import elements as validate_elements
            page = compose(row,number,width,height,data['presentationTheme'],
                           data.get('presentationFont','Malgun Gothic'),data.get('presentationProfile',{}))
            if page is not None:
                page['elements'] = validate_elements(component_styles(page['elements'],row),width,height,data['presentationTheme'])
                pages.append(page)
                continue

        if row.get('layout', 'auto') != 'auto' and 'contentOrder' not in row:
            _structured(row, number, width, height, elements, text, profile)
            for e in elements:
                if min(e['x'], e['y']) < 0 or e['x']+e['w'] > width+.01 or e['y']+e['h'] > height+.01:
                    raise DesignError('슬라이드 영역을 벗어나는 배치를 저장하지 않았습니다.')
            pages.append({'elements': elements})
            continue

        if profile:
            annotation_h = max(22,profile['annotationSize']*1.27+4)
            page_number_w = max(30,profile['annotationSize']*2+12)
            title_y = margin+annotation_h+profile['gap'] if row.get('eyebrow') else margin
            title_h = _lines(row['title'],usable,profile['titleSize'])*profile['titleSize']*1.27+4
            text(row.get('eyebrow',''),margin,margin,usable,annotation_h,11,'muted')
            text(row['title'],margin,title_y,usable,title_h,30,'title',True)
            top = title_y+title_h+profile['gap']
            if row.get('takeaway'):
                takeaway_h = _lines(row['takeaway'],usable,profile['bodySize'])*profile['bodySize']*1.27+4
                text(row['takeaway'],margin,top,usable,takeaway_h,17,'text')
                top += takeaway_h+profile['gap']
            text(row.get('source',''),margin,height-31,usable-page_number_w-15,annotation_h,10,'muted')
            text(f'{number:02d}',right-page_number_w,height-31,page_number_w,annotation_h,10,'muted')
        else:
            text(row.get('eyebrow', ''), margin, 12, usable, 20, 11, 'muted')
            text(row['title'], margin, 37, usable, 48, 30, 'title', True)
            text(row.get('takeaway', ''), margin, 91, usable, 30, 17, 'text')
            text(row.get('source', ''), margin, height-31, usable-45, 22, 10, 'muted')
            text(f'{number:02d}', right-30, height-31, 30, 22, 10, 'muted')
            top = 139.
        if row.get('kpis') and profile:
            top = _profile_kpis(row,margin,top,usable,elements,text,profile)
        elif row.get('kpis'):
            kpi_w = usable / len(row['kpis'])
            for index, kpi in enumerate(row['kpis']):
                x = margin + index*kpi_w
                first = len(elements)
                text(kpi['label'] + (' · '+kpi['unit'] if kpi['unit'] else ''), x, top, kpi_w-16, 26, 15, 'muted')
                text(kpi['value'], x, top+28, kpi_w-16, 57, 38, 'accent', True)
                for element in elements[first:]:
                    element['group'] = f'kpi-{index+1}'
            top += 103
        if profile and top > bottom:
            raise DesignError(f'{number}장 제목과 요약, 지표가 본문 영역보다 큽니다. 내용을 줄이거나 장을 나누어 주세요.')
        if 'contentOrder' in row:
            blocks = _vertical(row, number, margin, top, usable, bottom, elements, text, profile)
            pages.append({'elements': elements, 'contentBlocks': blocks})
            continue
        visuals = [k for k in ('chart', 'table', 'image') if row.get(k)]
        prose = '\n\n'.join(([row['body']] if row['body'] else []) + row['bullets'])
        if len(visuals) > 2 or (len(visuals) == 2 and prose):
            raise DesignError(f"{number}장은 표·차트·설명이 너무 많습니다. 근거와 설명을 별도 장으로 나누어 주세요.")
        gap = profile['gap'] if profile else 28.
        slots = []
        if len(visuals) == 2:
            slots = [(margin, top, (usable-gap)/2, bottom-top), (margin+(usable+gap)/2, top, (usable-gap)/2, bottom-top)]
        elif visuals and prose:
            visual_w = usable*.64
            slots = [(margin, top, visual_w, bottom-top)]
            text(prose, margin+visual_w+gap, top+8, usable-visual_w-gap, bottom-top-8)
        elif visuals:
            slots = [(margin, top, usable, bottom-top)]
        elif prose:
            text(prose, margin, top+10, usable, bottom-top-10, 21)
        for kind, (x, y, w, h) in zip(visuals, slots):
            element = dict(kind=kind, x=x, y=y, w=w, h=h)
            if kind == 'image':
                element['fit'] = row.get('imageFit','contain')
            if kind == 'table':
                table = row['table']
                # Give longer text columns more space, within a bounded weight.
                table_size = profile['tableSize'] if profile else 16
                table_style = {'fontSize':table_size, **row.get('tableStyle', {})} if profile else row.get('tableStyle')
                widths, heights = _table_metrics(table, w, table_style)
                if sum(heights) > h:
                    raise DesignError(f"{number}장 표를 읽기 좋은 크기로 담을 수 없습니다. 행·열을 나누어 주세요.")
                element.update(h=sum(heights), columnWidths=widths, rowHeights=heights, size=table_size)
            elif kind == 'chart':
                if h < 180 or w < 260:
                    raise DesignError(f"{number}장 차트 공간이 작습니다. 지표나 설명을 다른 장으로 옮겨 주세요.")
                title = row['chart'].get('title', '')
                if title:
                    caption_h, caption_offset = _chart_caption(row['chart'],w,profile)
                    if profile and h-caption_offset < 180:
                        raise DesignError(f"{number}장 차트 공간이 작습니다. 지표나 설명을 다른 장으로 옮겨 주세요.")
                    text(title, x, y, w, caption_h, 15, 'muted', True)
                    element.update(y=y+caption_offset, h=h-caption_offset)
            elements.append(element)
        if not prose and not visuals and not row.get('kpis'):
            raise DesignError(f"{number}장에 제목 외의 핵심 내용이 없습니다.")
        for e in elements:
            if min(e['x'], e['y']) < 0 or e['x']+e['w'] > width+.01 or e['y']+e['h'] > height+.01:
                raise DesignError("슬라이드 영역을 벗어나는 배치를 저장하지 않았습니다.")
        pages.append({'elements': elements})
    for row, page in zip(data['sections'], pages):
        page['elements'] = component_styles(page['elements'], row)
    return {'width': width, 'height': height, 'pages': pages, 'font': data.get('presentationFont','Malgun Gothic'), 'theme': data['presentationTheme']}


def render_python(data, draft, template):
    import base64
    from io import BytesIO
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import (XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION,
                                XL_TICK_LABEL_POSITION, XL_MARKER_STYLE)
    from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
    from pptx.dml.color import RGBColor
    from pptx.util import Pt
    from pptx.oxml.xmlchemy import OxmlElement
    # New documents do not depend on site-packages/templates/default.pptx,
    # which an enterprise document policy may wrap on disk. Supplied templates
    # still use the normal reader and retain all existing access checks.
    from .ppt_empty import blank_presentation
    prs = Presentation(str(template)) if template else blank_presentation(data['presentationPlan']['font'])
    if not template:
        prs.slide_width, prs.slide_height = Pt(data['presentationPlan']['width']), Pt(data['presentationPlan']['height'])
    for relation in list(prs.slides._sldIdLst):
        prs.part.drop_rel(relation.rId)
        prs.slides._sldIdLst.remove(relation)
    design = data['presentationPlan']
    palette = design['theme']
    color = lambda name: RGBColor.from_string(palette.get(name, name))
    native = {'text': 0, 'tables': 0, 'charts': 0, 'images': 0, 'shapes':0, 'groups':0}
    blank = min(prs.slide_layouts, key=lambda layout: len(layout.placeholders))

    def typeface(font, name=None):
        name = name or design['font']
        font.name = name
        # Latin name alone leaves Korean runs dependent on the template's EA font.
        for tag in ('a:ea', 'a:cs'):
            child = font._rPr.find('{http://schemas.openxmlformats.org/drawingml/2006/main}'+tag.split(':')[1])
            if child is None:
                child = OxmlElement(tag)
                font._rPr.append(child)
            child.set('typeface', name)
        font._rPr.set('lang', 'ko-KR')

    def format_text(frame, size, ink='text', bold=False):
        frame.word_wrap = True
        frame.auto_size = MSO_AUTO_SIZE.NONE
        frame.margin_top = frame.margin_bottom = Pt(2)
        frame.margin_left = frame.margin_right = Pt(0)
        for p in frame.paragraphs:
            typeface(p.font)
            p.font.size = Pt(size)
            for run in p.runs:
                typeface(run.font)
                run.font.size = Pt(size)
                run.font.bold = bold
                run.font.color.rgb = color(ink)
            p.font.bold, p.font.color.rgb = bold, color(ink)
            p.space_before = p.space_after = Pt(0)
            p.line_spacing = 1.15

    for row, page in zip(data['sections'], design['pages']):
        slide = prs.slides.add_slide(blank)
        for shape in list(slide.placeholders):
            shape._element.getparent().remove(shape._element)
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = color(page.get('background','background'))
        for e in page['elements']:
            box = tuple(Pt(e[k]) for k in ('x', 'y', 'w', 'h'))
            kind = e['kind']
            if kind == 'text':
                shape = slide.shapes.add_textbox(*box)
                shape.text_frame.text = e['text']
                format_text(shape.text_frame, e['size'], e['color'], e['bold'])
                if e.get('runs'):
                    from .ppt_text import write_runs
                    write_runs(shape.text_frame,e,palette,design['font'])
                if e.get('verticalAlign'):
                    shape.text_frame.vertical_anchor={'top':MSO_ANCHOR.TOP,'middle':MSO_ANCHOR.MIDDLE,'bottom':MSO_ANCHOR.BOTTOM}[e['verticalAlign']]
                if 'wrap' in e:
                    frame=shape.text_frame
                    frame.word_wrap=e['wrap']
                    frame.margin_top=frame.margin_bottom=0
                    for p in frame.paragraphs:
                        p.alignment={'left':PP_ALIGN.LEFT,'center':PP_ALIGN.CENTER,'right':PP_ALIGN.RIGHT}[e.get('align','left')]
                        p.line_spacing=e.get('lineSpacing',1.15)
                        typeface(p.font,e.get('font'))
                        for run in p.runs:
                            if not e.get('runs'):
                                typeface(run.font,e.get('font'))
                                run.font.size=Pt(e['size'])
                                run.font.italic=e.get('italic',False)
                                run.font.underline=e.get('underline',False)
                native['text'] += 1
            elif kind in ('shape','line','path'):
                from .ppt_primitives import add_primitive
                add_primitive(slide,e,box)
                native['shapes'] += 1
            elif kind == 'table':
                from .ppt_component_styles import table_style, cell_style, native_cell_border
                content = e.get(kind,row.get(kind))
                style = table_style(e, palette) if 'tableStyle' in e else None
                table = slide.shapes.add_table(len(content['rows'])+1, len(content['headers']), *box).table
                for j, width in enumerate(e['columnWidths']):
                    table.columns[j].width = Pt(width)
                for i, values in enumerate([content['headers'], *content['rows']]):
                    table.rows[i].height = Pt(e['rowHeights'][i])
                    for j, value in enumerate(values):
                        cell = table.cell(i, j)
                        cell.text = value
                        cell.fill.solid()
                        fill, ink, bold = cell_style(style, i) if style else ('title' if i == 0 else ('tint' if i % 2 else 'background'), 'background' if i == 0 else 'text', i == 0)
                        cell.fill.fore_color.rgb = color(fill)
                        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                        format_text(cell.text_frame, style['fontSize'] if style else e.get('size',16), ink, bold)
                        cell.margin_left = cell.margin_right = Pt(6)
                        if style:
                            cell.margin_top = cell.margin_bottom = cell.margin_left = cell.margin_right = Pt(style['padding'])
                            for paragraph in cell.text_frame.paragraphs:
                                paragraph.alignment = {'left':PP_ALIGN.LEFT,'center':PP_ALIGN.CENTER,'right':PP_ALIGN.RIGHT}[style['align']]
                            native_cell_border(cell, style)
                native['tables'] += 1
            elif kind == 'chart':
                from .ppt_component_styles import chart_style
                content = e.get(kind,row.get(kind))
                style = chart_style(e, palette) if 'chartStyle' in e else None
                chart_data = CategoryChartData()
                chart_data.categories = content['categories']
                for s in content['series']:
                    chart_data.add_series(s['name'], s['values'])
                kinds = {'column': XL_CHART_TYPE.COLUMN_CLUSTERED, 'bar': XL_CHART_TYPE.BAR_CLUSTERED,
                         'line': XL_CHART_TYPE.LINE, 'pie': XL_CHART_TYPE.PIE}
                chart = slide.shapes.add_chart(kinds[content['type']], *box, chart_data).chart
                # Some python-pptx chart templates use signed axis IDs. OOXML
                # readers expect UInt32; update IDs and their references together.
                axis_nodes = chart._chartSpace.xpath('.//c:axId | .//c:crossAx')
                axis_map = {value: str(100001+i) for i, value in enumerate(dict.fromkeys(node.get('val') for node in axis_nodes))}
                for axis_id in axis_nodes:
                    axis_id.set('val', axis_map[axis_id.get('val')])
                chart.has_title = False
                typeface(chart.font)
                chart.font.size = Pt(style['fontSize'] if style else 13)
                chart.font.color.rgb = color('text')
                chart.has_legend = len(content['series']) > 1 or content['type'] == 'pie'
                if style and 'legendPosition' in e['chartStyle']:
                    chart.has_legend = style['legendPosition'] != 'none'
                if chart.has_legend:
                    chart.legend.position = {'bottom':XL_LEGEND_POSITION.BOTTOM, 'top':XL_LEGEND_POSITION.TOP,
                                             'right':XL_LEGEND_POSITION.RIGHT, 'left':XL_LEGEND_POSITION.LEFT}[style['legendPosition'] if style else 'bottom']
                    chart.legend.include_in_layout = False
                    if style:
                        typeface(chart.legend.font)
                        chart.legend.font.size = Pt(style['fontSize'])
                series_colors = style['seriesColors'] if style else ['accent', 'title', '52667C', 'B05C32']
                for i, s in enumerate(chart.series):
                    series_color = series_colors[i % len(series_colors)]
                    s.format.fill.solid()
                    s.format.fill.fore_color.rgb = color(series_color)
                    s.format.line.color.rgb = color(series_color)
                    if content['type'] in ('bar', 'column'):
                        # Office otherwise renders negative solid bars white.
                        s.invert_if_negative = False
                    elif content['type'] == 'line':
                        s.marker.style = {'circle':XL_MARKER_STYLE.CIRCLE, 'square':XL_MARKER_STYLE.SQUARE,
                                          'diamond':XL_MARKER_STYLE.DIAMOND, 'none':XL_MARKER_STYLE.NONE}[style['marker'] if style else 'circle']
                        s.marker.size = 5
                        s.marker.format.fill.solid()
                        s.marker.format.fill.fore_color.rgb = color(series_color)
                        s.marker.format.line.color.rgb = color(series_color)
                        if style:
                            s.format.line.width = Pt(style['lineWidth'])
                    elif content['type'] == 'pie' and style:
                        for j, point in enumerate(s.points):
                            point.format.fill.solid()
                            point.format.fill.fore_color.rgb = color(series_colors[j % len(series_colors)])
                if content['type'] != 'pie':
                    typeface(chart.category_axis.tick_labels.font)
                    typeface(chart.value_axis.tick_labels.font)
                    chart.category_axis.tick_labels.font.size = Pt(style['fontSize'] if style else 13)
                    chart.value_axis.tick_labels.font.size = Pt(style['fontSize'] if style and 'fontSize' in e['chartStyle'] else 12)
                    # Mixed-sign bars cross zero inside the plot. Keep category
                    # text at the outside edge and explicitly retain every item.
                    chart.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.LOW
                    axis = chart.category_axis._element
                    for old in axis.xpath('./c:tickLblSkip'):
                        axis.remove(old)
                    skip = OxmlElement('c:tickLblSkip')
                    skip.set('val', '1')
                    axis.insert_element_before(skip, 'c:tickMarkSkip', 'c:noMultiLvlLbl', 'c:extLst')
                    if content['type'] in ('bar', 'column'):
                        values = [v for s in content['series'] for v in s['values']]
                        if min(values) >= 0:
                            chart.value_axis.minimum_scale = 0
                    chart.value_axis.has_major_gridlines = style['showGrid'] if style else True
                    if chart.value_axis.has_major_gridlines:
                        chart.value_axis.major_gridlines.format.line.color.rgb = color(style['gridColor'] if style else 'tint')
                if len(content['categories']) <= 6:
                    plot = chart.plots[0]
                    plot.has_data_labels = True
                    typeface(plot.data_labels.font)
                    plot.data_labels.font.size = Pt(style['labelSize'] if style else 12)
                    plot.data_labels.font.color.rgb = color('text')
                    if content['type'] in ('bar', 'column'):
                        plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
                    elif content['type'] == 'line':
                        plot.data_labels.position = XL_LABEL_POSITION.ABOVE
                        # Keep labels off the marker/line. A second series gets
                        # the other side; dense/crossing lines still need review.
                        for i, series in enumerate(chart.series):
                            position = XL_LABEL_POSITION.BELOW if i % 2 else XL_LABEL_POSITION.ABOVE
                            for point in series.points:
                                point.data_label.position = position
                native['charts'] += 1
            elif kind == 'image':
                from .ppt_scene import fit_picture
                im = e.get(kind,row.get(kind))
                picture = slide.shapes.add_picture(BytesIO(base64.b64decode(im['data'])), box[0], box[1], height=box[3])
                fit_picture(picture,box,e.get('fit','contain'))
                native['images'] += 1
        from .ppt_scene import group_shapes
        native['groups'] += group_shapes(slide, page['elements'])
    prs.core_properties.title, prs.core_properties.subject = data['title'], data['subtitle']
    prs.save(str(draft))
    return native
