"""Validated native slide primitives, shared by HTML preview and PPT export.

No code evaluation. Coordinates and typography are in slide points. HTML import
normalizes browser pixels into these same primitives before approval.
"""
from __future__ import annotations

import base64
import math
import re
from copy import deepcopy

from .business_artifacts import ArtifactError, _image, _normalize, _text


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ArtifactError('invalid_ppt_element', 'PPT 개체의 좌표·크기·효과 범위를 확인해 주세요.')
    return float(value)


def ink(value, palette, *, transparent=False):
    if transparent and value in (None, 'none'):
        return None
    value = palette.get(value, value) if isinstance(value, str) else value
    if not isinstance(value, str) or not re.fullmatch('[0-9A-Fa-f]{6}', value):
        raise ArtifactError('invalid_ppt_element', '개체 색상은 여섯 자리 RGB 또는 지정된 테마 색상입니다.')
    return value.upper()


def elements(rows, width, height, palette, *, embedded=False):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1200:
        raise ArtifactError('invalid_ppt_element', '한 장에는 1~1200개 편집 개체를 사용할 수 있습니다.')
    checked = []
    image_bytes = 0
    for raw in rows:
        if not isinstance(raw, dict) or raw.get('kind') not in ('text', 'shape', 'image', 'table', 'chart'):
            raise ArtifactError('invalid_ppt_element', '지원하는 개체는 text, shape, image, table, chart입니다.')
        e = {'kind': raw['kind']}
        for key, maximum in (('x', width), ('y', height), ('w', width), ('h', height)):
            e[key] = number(raw.get(key), 0 if key in ('x', 'y') else .01, maximum)
        if e['x']+e['w'] > width+.5 or e['y']+e['h'] > height+.5:
            raise ArtifactError('ppt_element_out_of_bounds', '화면 밖으로 나간 개체가 있습니다. HTML/개체 배치를 수정해 주세요.')
        kind = e['kind']
        if kind == 'text':
            e.update(text=_text(raw.get('text', ''), 12000), size=number(raw.get('size',18), 6, 200),
                     color=ink(raw.get('color','text'),palette), bold=bool(raw.get('bold',False)),
                     italic=bool(raw.get('italic',False)), underline=bool(raw.get('underline',False)))
            e['align'] = raw.get('align','left')
            if e['align'] not in ('left','center','right'):
                raise ArtifactError('invalid_ppt_element','글자 정렬은 left, center, right입니다.')
            e['wrap'] = raw.get('wrap', True) is not False
            e['lineSpacing'] = number(raw.get('lineSpacing',1.15), .8, 3)
            e['font'] = _text(raw.get('font',''), 80)
        elif kind == 'shape':
            e['shape'] = raw.get('shape','rect')
            if e['shape'] not in ('rect','roundRect','ellipse'):
                raise ArtifactError('invalid_ppt_element','도형은 rect, roundRect, ellipse입니다.')
            e.update(fill=ink(raw.get('fill','background'),palette,transparent=True),
                     opacity=number(raw.get('opacity',1),0,1),
                     border=ink(raw.get('border'),palette,transparent=True),
                     borderWidth=number(raw.get('borderWidth',0),0,20),
                     radius=number(raw.get('radius',min(12,min(e['w'],e['h'])/2)),0,min(e['w'],e['h'])/2) if e['shape']=='roundRect' else 0)
            if raw.get('shadow'):
                s = raw['shadow']
                if not isinstance(s,dict):
                    raise ArtifactError('invalid_ppt_element','그림자 형식을 확인해 주세요.')
                e['shadow'] = {'color':ink(s.get('color','000000'),palette),
                               'opacity':number(s.get('opacity',.18),0,1),
                               'blur':number(s.get('blur',8),0,100),
                               'x':number(s.get('x',0),-100,100),'y':number(s.get('y',3),-100,100)}
        elif kind == 'image':
            value = raw.get('image')
            if embedded and isinstance(value,dict) and 'data' in value:
                binary = base64.b64decode(value['data'],validate=True)
                mime = 'image/png' if binary.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if binary.startswith(b'\xff\xd8\xff') else None
                if not mime or len(binary)>10*1024*1024:
                    raise ArtifactError('invalid_image','PNG/JPEG 그림만 사용할 수 있습니다.')
                e['image'] = {'data':value['data'],'mime':mime,'alt':_text(value.get('alt',''),1000)}
            else:
                e['image'] = _image(value)
            e['fit'] = raw.get('fit','contain')
            if e['fit'] not in ('contain','cover','stretch'):
                raise ArtifactError('invalid_ppt_element','이미지 맞춤은 contain, cover, stretch입니다.')
            image_bytes += len(e['image']['data'])
            if image_bytes>32*1024*1024:
                raise ArtifactError('spec_too_large','한 장의 그림 자료가 너무 큽니다. 그림 용량을 줄여 주세요.')
        else:
            e[kind] = _normalize({'slides':[{kind:raw.get(kind)}]})['sections'][0][kind]
            if kind == 'table':
                table = e[kind]
                count, columns = len(table['rows'])+1, len(table['headers'])
                e['size'] = number(raw.get('size',16),6,96)
                for key,n,span in (('columnWidths',columns,e['w']),('rowHeights',count,e['h'])):
                    sizes = raw.get(key,[span/n]*n)
                    if not isinstance(sizes,list) or len(sizes)!=n:
                        raise ArtifactError('invalid_ppt_element','표의 행·열 크기가 내용과 다릅니다.')
                    e[key] = [number(v,.01,span) for v in sizes]
                    if abs(sum(e[key])-span)>.5:
                        raise ArtifactError('invalid_ppt_element','표의 행·열 크기 합계가 지정 영역과 다릅니다.')
            elif len(e[kind]['series'])>4 or len(e[kind]['categories'])>12:
                raise ArtifactError('invalid_ppt_element','차트는 12항목·4계열 이하로 나누어 주세요.')
        checked.append(e)
    return checked


def add_shape(slide, e, box):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.dml.color import RGBColor
    from pptx.util import Pt
    from pptx.oxml.xmlchemy import OxmlElement
    kinds = {'rect':MSO_SHAPE.RECTANGLE,'roundRect':MSO_SHAPE.ROUNDED_RECTANGLE,'ellipse':MSO_SHAPE.OVAL}
    shape = slide.shapes.add_shape(kinds[e['shape']],*box)
    if e['shape']=='roundRect':
        shape.adjustments[0] = e['radius']/min(e['w'],e['h'])
    if e['fill']:
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string(e['fill'])
        alpha = OxmlElement('a:alpha')
        alpha.set('val',str(round(e['opacity']*100000)))
        shape.fill.fore_color._color._xClr.append(alpha)
    else:
        shape.fill.background()
    if e['border'] and e['borderWidth']:
        shape.line.color.rgb = RGBColor.from_string(e['border'])
        shape.line.width = Pt(e['borderWidth'])
    else:
        shape.line.fill.background()
    # Explicit effect list also disables inherited theme shadows.
    effects = shape._element.spPr.get_or_add_effectLst()
    for child in list(effects):
        effects.remove(child)
    if e.get('shadow'):
        s = e['shadow']
        shadow = OxmlElement('a:outerShdw')
        for key,value in {'blurRad':round(s['blur']*12700),'dist':round(math.hypot(s['x'],s['y'])*12700),
                          'dir':round(math.degrees(math.atan2(s['y'],s['x']))%360*60000),
                          'algn':'tl','rotWithShape':'0'}.items():
            shadow.set(key,str(value))
        rgb = OxmlElement('a:srgbClr'); rgb.set('val',s['color'])
        alpha = OxmlElement('a:alpha'); alpha.set('val',str(round(s['opacity']*100000)))
        rgb.append(alpha); shadow.append(rgb); effects.append(shadow)
    return shape


def fit_picture(picture, box, mode):
    """Centered fit from original bitmap dimensions; safe for existing pictures too."""
    x,y,w,h = box
    iw,ih = picture.image.size
    picture.crop_left = picture.crop_right = picture.crop_top = picture.crop_bottom = 0
    if mode == 'contain':
        scale = min(w/iw,h/ih)
        pw,ph = round(iw*scale),round(ih*scale)
        picture.left,picture.top = round(x+(w-pw)/2),round(y+(h-ph)/2)
        picture.width,picture.height = pw,ph
    else:
        picture.left,picture.top,picture.width,picture.height = x,y,w,h
        if mode == 'cover':
            scale = max(w/iw,h/ih)
            picture.crop_left = picture.crop_right = max(0,(iw*scale-w)/(2*iw*scale))
            picture.crop_top = picture.crop_bottom = max(0,(ih*scale-h)/(2*ih*scale))


def template_layouts(plan):
    """Only geometry/styles and synthetic slot values; never retain source text/images."""
    pages = []
    for page in plan['pages']:
        result = []
        slot = 0
        for original in page['elements']:
            if original['kind'] == 'image':
                # Image content and paths are not a reusable style preference.
                result.append(dict(kind='shape',shape='rect',fill='EEF1F4',border='CBD2DA',borderWidth=1,
                                   **{k:original[k] for k in ('x','y','w','h')}))
                continue
            e = deepcopy(original)
            if e['kind']=='text':
                slot += 1
                e['text'] = '예시'
            elif e['kind']=='chart':
                c=e['chart']; c['categories']=[f'항목 {i+1}' for i in range(len(c['categories']))]
                for i,s in enumerate(c['series']):
                    s.update(name=f'계열 {i+1}',values=[100+i*10]*len(c['categories']))
            elif e['kind']=='table':
                t=e['table']; t['headers']=[f'열 {i+1}' for i in range(len(t['headers']))]
                t['rows']=[['예시']*len(t['headers']) for _ in t['rows']]
            result.append(e)
        pages.append({'elements':result,'textSlots':slot,'background':page.get('background','FFFFFF')})
    return pages
