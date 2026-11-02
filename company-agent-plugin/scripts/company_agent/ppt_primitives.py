"""Bounded editable geometry shared by HTML drafts and native PowerPoint.

Coordinates in ``points`` and structured ``commands`` are local slide points
inside x/y/w/h, not SVG source and not executable code. Named polygon shapes
compile to the same editable freeform paths used by their HTML preview; this
does not claim Office preset adjustment handles for those freeforms.

Public integration: normalize_primitive(raw, width, height, palette),
render_primitive_html(element, plan), add_primitive(slide, element, box).
Every element produces one native shape, so semantic grouping stays intact.
"""
from __future__ import annotations

import html
import math
import re

from .business_artifacts import ArtifactError


SHAPES = ('rect', 'roundRect', 'ellipse', 'rightArrow', 'leftArrow', 'upArrow',
          'downArrow', 'leftRightArrow', 'chevron', 'diamond', 'triangle',
          'hexagon', 'parallelogram', 'trapezoid', 'pentagon', 'octagon')
_BASIC = ('rect', 'roundRect', 'ellipse')
_ARROWS = ('none', 'triangle')


def _fail(message='도형과 선의 좌표, 색상, 경로 형식을 확인해 주세요.'):
    raise ArtifactError('invalid_ppt_element', message)


def _number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        _fail()
    return float(value)


def _ink(value, palette, transparent=False):
    if transparent and value in (None, 'none'):
        return None
    value = palette.get(value, value) if isinstance(value, str) else value
    if not isinstance(value, str) or not re.fullmatch('[a-fA-F0-9]{6}', value):
        _fail('도형과 선의 색은 여섯 자리 RGB 또는 지정된 테마 색으로 입력해 주세요.')
    return value.upper()


def _point(value, w, h):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        _fail('경로의 점은 [x, y] 형식으로 입력해 주세요.')
    return [_number(value[0], 0, w), _number(value[1], 0, h)]


def _polygon(name, w, h):
    """One deterministic contour, used in both previews and editable output."""
    if name == 'rightArrow':
        return [(0,.25*h),(.62*w,.25*h),(.62*w,0),(w,.5*h),(.62*w,h),(.62*w,.75*h),(0,.75*h)]
    if name == 'leftArrow':
        return [(w-x,y) for x,y in _polygon('rightArrow',w,h)]
    if name == 'upArrow':
        return [(y,w-x) for x,y in _polygon('rightArrow',h,w)]
    if name == 'downArrow':
        return [(y,x) for x,y in _polygon('rightArrow',h,w)]
    if name == 'leftRightArrow':
        return [(0,.5*h),(.25*w,0),(.25*w,.25*h),(.75*w,.25*h),(.75*w,0),
                (w,.5*h),(.75*w,h),(.75*w,.75*h),(.25*w,.75*h),(.25*w,h)]
    polygons = {
        'chevron':[(0,0),(.72,0),(1,.5),(.72,1),(0,1),(.28,.5)],
        'diamond':[(.5,0),(1,.5),(.5,1),(0,.5)],
        'triangle':[(.5,0),(1,1),(0,1)],
        'hexagon':[(.25,0),(.75,0),(1,.5),(.75,1),(.25,1),(0,.5)],
        'parallelogram':[(.22,0),(1,0),(.78,1),(0,1)],
        'trapezoid':[(.2,0),(.8,0),(1,1),(0,1)],
        'pentagon':[(.5,0),(1,.38),(.81,1),(.19,1),(0,.38)],
        'octagon':[(.29,0),(.71,0),(1,.29),(1,.71),(.71,1),(.29,1),(0,.71),(0,.29)],
    }
    return [(x*w,y*h) for x,y in polygons[name]]


def _commands(raw, w, h):
    commands = raw.get('commands')
    if commands is not None and 'points' in raw:
        _fail('하나의 경로에는 commands 또는 points 중 하나만 지정해 주세요.')
    if commands is None:
        points = raw.get('points')
        if not isinstance(points, list) or not 2 <= len(points) <= 256:
            _fail('경로는 점 2~256개 또는 구조화한 M/L/C/Q/Z 명령으로 지정해 주세요.')
        points = [_point(p,w,h) for p in points]
        commands = [['M',*points[0]],*[['L',*p] for p in points[1:]]]
        if raw.get('closed', False):
            commands.append(['Z'])
    if not isinstance(commands, list) or not 2 <= len(commands) <= 256:
        _fail('경로 명령은 2~256개로 나누어 주세요.')
    checked = []
    active = False
    for command in commands:
        if not isinstance(command, (list, tuple)) or not command:
            _fail()
        kind = command[0]
        counts = {'M':2,'L':2,'C':6,'Q':4,'Z':0}
        if not isinstance(kind,str) or kind not in counts or len(command) != counts[kind]+1 or (not active and kind != 'M'):
            _fail('경로 명령은 M, L, C, Q, Z와 해당 좌표만 사용할 수 있습니다.')
        if kind == 'Z':
            checked.append(['Z'])
            active = False
            continue
        values = []
        for index in range(1,len(command),2):
            values.extend(_point(command[index:index+2],w,h))
        checked.append([kind,*values])
        active = True
    if checked[0][0] != 'M' or not any(c[0] in ('L','C','Q') for c in checked):
        _fail('경로에는 시작점과 하나 이상의 선 또는 곡선이 필요합니다.')
    closed = raw.get('closed', checked[-1][0]=='Z')
    if type(closed) is not bool:
        _fail('closed에는 true 또는 false를 지정해 주세요.')
    if closed and checked[-1][0] != 'Z':
        checked.append(['Z'])
    if not closed and any(c[0]=='Z' for c in checked):
        _fail('열린 경로에는 닫기 명령 Z를 섞지 마세요.')
    return checked, closed


def normalize_primitive(raw, width, height, palette):
    """Validate a shape, line or path without reading resources or executing SVG."""
    if not isinstance(raw, dict) or raw.get('kind') not in ('shape','line','path'):
        _fail()
    e = {'kind':raw['kind']}
    for key, maximum in (('x',width),('y',height),('w',width),('h',height)):
        e[key] = _number(raw.get(key), 0 if key in ('x','y') else .01, maximum)
    if e['x']+e['w'] > width+.5 or e['y']+e['h'] > height+.5:
        raise ArtifactError('ppt_element_out_of_bounds','화면 밖의 도형이나 선은 저장하지 않습니다.')
    if raw.get('group') is not None:
        if not isinstance(raw['group'],str) or not re.fullmatch(r'[\w-]{1,64}',raw['group']):
            raise ArtifactError('invalid_ppt_group','그룹 이름은 64자 이하의 글자, 숫자, 밑줄 또는 하이픈입니다.')
        e['group'] = raw['group']
    e.update(fill=_ink(raw.get('fill','background' if e['kind']=='shape' else None),palette,True),
             opacity=_number(raw.get('opacity',1),0,1),
             border=_ink(raw.get('border','text' if e['kind']=='line' else None),palette,True),
             borderWidth=_number(raw.get('borderWidth',1.5 if e['kind']=='line' else 0),0,20))
    dash=raw.get('dash','solid')
    if dash not in ('solid','dash','dot'):
        _fail('선 모양은 solid, dash 또는 dot입니다.')
    if dash!='solid':
        e['dash']=dash
    if raw.get('shadow'):
        s=raw['shadow']
        if not isinstance(s,dict):
            _fail()
        e['shadow']={'color':_ink(s.get('color','000000'),palette),
                     'opacity':_number(s.get('opacity',.18),0,1),'blur':_number(s.get('blur',8),0,100),
                     'x':_number(s.get('x',0),-100,100),'y':_number(s.get('y',3),-100,100)}
    if e['kind']=='shape':
        name=raw.get('shape','rect')
        if name not in SHAPES:
            _fail('지원 도형: '+', '.join(SHAPES))
        e['shape']=name
        e['radius']=_number(raw.get('radius',min(12,min(e['w'],e['h'])/2)),0,min(e['w'],e['h'])/2) if name=='roundRect' else 0
        e['representation']='native-preset' if name in _BASIC else 'native-freeform'
        if name not in _BASIC:
            points=_polygon(name,e['w'],e['h'])
            e['commands']=[['M',*points[0]],*[['L',*p] for p in points[1:]],['Z']]
            e['closed']=True
    elif e['kind']=='line':
        points=raw.get('points',[[0,0],[e['w'],e['h']]])
        if not isinstance(points,list) or not 2<=len(points)<=256:
            _fail('선의 점은 2~256개로 지정해 주세요.')
        e['points']=[_point(p,e['w'],e['h']) for p in points]
        if all(p==e['points'][0] for p in e['points']):
            _fail('선의 시작점과 끝점 또는 중간점은 달라야 합니다.')
        for key in ('startArrow','endArrow'):
            e[key]=raw.get(key,'none')
            if e[key] not in _ARROWS:
                _fail('선 끝 모양은 none 또는 triangle입니다.')
        if not e['border'] or not e['borderWidth']:
            _fail('선에는 보이는 색과 0보다 큰 두께가 필요합니다.')
        e.update(fill=None,closed=False,representation='native-connector' if len(points)==2 else 'native-freeform')
        e['commands']=[['M',*e['points'][0]],*[['L',*p] for p in e['points'][1:]]]
    else:
        e['commands'],e['closed']=_commands(raw,e['w'],e['h'])
        if not e['closed'] and e['fill']:
            _fail('열린 경로는 fill:none으로 두고 선 색과 두께를 지정해 주세요.')
        if not e['fill'] and (not e['border'] or not e['borderWidth']):
            _fail('경로에는 보이는 채움 또는 선이 필요합니다.')
        e['representation']='native-freeform'
    return e


def _fmt(value):
    return format(value,'.8g')


def _path_d(commands):
    return ' '.join(c[0]+(' '+' '.join(_fmt(v) for v in c[1:]) if len(c)>1 else '') for c in commands)


def render_primitive_html(e, plan):
    """Return a safe SVG fragment; the caller positions its outer element."""
    w,h=e['w'],e['h']
    fill='#'+e['fill'] if e.get('fill') else 'none'
    stroke='#'+e['border'] if e.get('border') and e.get('borderWidth') else 'none'
    attributes=f'fill="{fill}" fill-opacity="{_fmt(e.get("opacity",1))}" stroke="{stroke}" stroke-width="{_fmt(e.get("borderWidth",0))}"'
    if e.get('dash') in ('dash','dot'):
        unit=e['borderWidth']
        attributes+=f' stroke-dasharray="{_fmt(unit*(4 if e["dash"]=="dash" else 1))} {_fmt(unit*2)}"'
    if e.get('shape')=='rect':
        drawing=f'<rect x="0" y="0" width="{_fmt(w)}" height="{_fmt(h)}" {attributes}/>'
    elif e.get('shape')=='roundRect':
        drawing=f'<rect x="0" y="0" width="{_fmt(w)}" height="{_fmt(h)}" rx="{_fmt(e["radius"])}" {attributes}/>'
    elif e.get('shape')=='ellipse':
        drawing=f'<ellipse cx="{_fmt(w/2)}" cy="{_fmt(h/2)}" rx="{_fmt(w/2)}" ry="{_fmt(h/2)}" {attributes}/>'
    else:
        drawing=f'<path d="{html.escape(_path_d(e["commands"]),quote=True)}" {attributes}/>'
    if e['kind']=='line':
        points=e['points']
        for key,a,b in (('startArrow',points[0],next(p for p in points[1:] if p!=points[0])),
                        ('endArrow',points[-1],next(p for p in reversed(points[:-1]) if p!=points[-1]))):
            if e[key]=='triangle':
                dx,dy=b[0]-a[0],b[1]-a[1]; length=math.hypot(dx,dy)
                dx,dy=dx/length,dy/length; size=e['borderWidth']*3
                coords=[a,(a[0]+dx*size-dy*size/2,a[1]+dy*size+dx*size/2),
                        (a[0]+dx*size+dy*size/2,a[1]+dy*size-dx*size/2)]
                drawing+='<polygon points="'+' '.join(_fmt(x)+','+_fmt(y) for x,y in coords)+f'" fill="#{e["border"]}"/>'
    effect=''
    if e.get('shadow'):
        s=e['shadow'];rgb=','.join(str(int(s['color'][i:i+2],16)) for i in (0,2,4))
        effect=f'filter:drop-shadow({_fmt(s["x"])}px {_fmt(s["y"])}px {_fmt(s["blur"]/2)}px rgba({rgb},{_fmt(s["opacity"])}));'
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_fmt(w)} {_fmt(h)}" preserveAspectRatio="none" aria-hidden="true" style="width:100%;height:100%;overflow:visible;{effect}">{drawing}</svg>'


def _custom_geometry(shape,e):
    from pptx.oxml.xmlchemy import OxmlElement
    sp=shape._element.spPr
    for old in list(sp):
        if old.tag.endswith(('}prstGeom','}custGeom')):
            sp.remove(old)
    geometry=OxmlElement('a:custGeom')
    for name in ('avLst','gdLst','ahLst','cxnLst'):
        geometry.append(OxmlElement('a:'+name))
    rect=OxmlElement('a:rect')
    for key,value in (('l','0'),('t','0'),('r','r'),('b','b')):
        rect.set(key,value)
    geometry.append(rect)
    paths=OxmlElement('a:pathLst');path=OxmlElement('a:path')
    path.set('w',str(max(1,round(e['w']*1000))));path.set('h',str(max(1,round(e['h']*1000))))
    path.set('fill','norm' if e.get('fill') else 'none')
    for command in e['commands']:
        name={'M':'moveTo','L':'lnTo','C':'cubicBezTo','Q':'quadBezTo','Z':'close'}[command[0]]
        node=OxmlElement('a:'+name)
        for i in range(1,len(command),2):
            point=OxmlElement('a:pt');point.set('x',str(round(command[i]*1000)));point.set('y',str(round(command[i+1]*1000)))
            node.append(point)
        path.append(node)
    paths.append(path);geometry.append(paths)
    # Geometry follows xfrm and precedes fill/line properties in DrawingML.
    index=1 if len(sp) and sp[0].tag.endswith('}xfrm') else 0
    sp.insert(index,geometry)


def _paint(shape,e):
    from pptx.dml.color import RGBColor
    from pptx.enum.dml import MSO_LINE_DASH_STYLE
    from pptx.oxml.xmlchemy import OxmlElement
    from pptx.util import Pt
    if hasattr(shape,'fill'):
        if e.get('fill'):
            shape.fill.solid();shape.fill.fore_color.rgb=RGBColor.from_string(e['fill'])
            alpha=OxmlElement('a:alpha');alpha.set('val',str(round(e.get('opacity',1)*100000)))
            shape.fill.fore_color._color._xClr.append(alpha)
        else:
            shape.fill.background()
    if e.get('border') and e.get('borderWidth'):
        shape.line.color.rgb=RGBColor.from_string(e['border']);shape.line.width=Pt(e['borderWidth'])
        shape.line.dash_style={'solid':MSO_LINE_DASH_STYLE.SOLID,'dash':MSO_LINE_DASH_STYLE.DASH,'dot':MSO_LINE_DASH_STYLE.ROUND_DOT}[e.get('dash','solid')]
    else:
        shape.line.fill.background()
    effects=shape._element.spPr.get_or_add_effectLst()
    for child in list(effects):
        effects.remove(child)
    if e.get('shadow'):
        s=e['shadow'];node=OxmlElement('a:outerShdw')
        for key,value in {'blurRad':round(s['blur']*12700),'dist':round(math.hypot(s['x'],s['y'])*12700),
                          'dir':round(math.degrees(math.atan2(s['y'],s['x']))%360*60000),'algn':'tl','rotWithShape':'0'}.items():
            node.set(key,str(value))
        rgb=OxmlElement('a:srgbClr');rgb.set('val',s['color']);alpha=OxmlElement('a:alpha')
        alpha.set('val',str(round(s['opacity']*100000)));rgb.append(alpha);node.append(rgb);effects.append(node)


def add_primitive(slide,e,box):
    """Add one preset, native connector or editable custom path; never a bitmap."""
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.oxml.xmlchemy import OxmlElement
    from pptx.util import Pt
    if e['kind']=='shape' and e['shape'] in _BASIC:
        from .ppt_scene import add_shape
        shape=add_shape(slide,e,box)
        if e.get('dash'):
            from pptx.enum.dml import MSO_LINE_DASH_STYLE
            shape.line.dash_style={'dash':MSO_LINE_DASH_STYLE.DASH,'dot':MSO_LINE_DASH_STYLE.ROUND_DOT}[e['dash']]
        return shape
    if e['kind']=='line' and len(e['points'])==2:
        a,b=e['points']
        shape=slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                 Pt(e['x']+a[0]),Pt(e['y']+a[1]),Pt(e['x']+b[0]),Pt(e['y']+b[1]))
    else:
        shape=slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,*box)
        _custom_geometry(shape,e)
    _paint(shape,e)
    if e['kind']=='line':
        line=shape._element.spPr.get_or_add_ln()
        for key,tag in (('startArrow','a:headEnd'),('endArrow','a:tailEnd')):
            if e[key]=='triangle':
                node=OxmlElement(tag);node.set('type','triangle');node.set('w','med');node.set('len','med');line.append(node)
    return shape
