"""Opt-in, content-bearing Korean slide compositions shared by HTML and PPT.

These are editable scene plans, not image templates or a second authoring
engine. Legacy layout, explicit geometry and content-order decisions stay owned
by their existing renderer. Text measurement may read an installed local font;
no network, model, user profile or font installation is used.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import math
import re
import unicodedata


ROLES = ('cover', 'key-message', 'comparison', 'workflow', 'timeline', 'detail', 'closing')


def reference_profile(pages, available_fonts):
    """Small suggestions from explicit source styles, never a visual claim."""
    from collections import Counter
    from .ppt_workflow import font_available
    styles=[]
    titles=[]
    for page in pages:
        names={shape.get('shapeId'):shape.get('name','') for shape in page.get('shapes',[])}
        for style in page.get('declaredTextStyles',[]):
            try:size=float(style.get('sz',0))/100
            except (TypeError,ValueError):continue
            if not 8<=size<=96:continue
            styles.append((size,style))
            if re.search(r'title|heading|제목',names.get(style.get('shapeId'),''),re.I) and 16<=size<=60:
                titles.append((size,style))
    result={}
    if titles:
        size,style=titles[0]
        result['titleSize']=size
        face=style.get('ea') or style.get('latin')
        if face and font_available(face,available_fonts):result['titleFont']=face
    bodies=[(size,style) for size,style in styles if 10<=size<=24 and size!=result.get('titleSize')]
    if bodies:
        size=Counter(size for size,_ in bodies).most_common(1)[0][0]
        result['bodySize']=size
        faces=Counter(style.get('ea') or style.get('latin') for _,style in bodies)
        face=next((face for face,_ in faces.most_common() if face and font_available(face,available_fonts)),None)
        if face:result['bodyFont']=face
        result['density']='reading' if size<18 else 'presentation'
    annotations=[size for size,_ in styles if 8<=size<=18]
    if annotations:result['annotationSize']=min(annotations)
    return result


class LayoutError(ValueError):
    pass


def _number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise LayoutError(f'{label} 값은 {low:g}~{high:g} 범위의 숫자로 지정해 주세요.')
    return float(value)


def _string(value, label='문구', maximum=4000):
    if not isinstance(value, str) or len(value) > maximum:
        raise LayoutError(f'{label} 형식이나 길이를 확인해 주세요.')
    return value


def _lines(value, width, size, font="Malgun Gothic"):
    # The shared Korean font measurer is optional during isolated development;
    # once bundled, the installed font metrics are cached and reused per role.
    try:
        from .ppt_text import estimate_lines
    except ImportError:
        estimate_lines = None
    if estimate_lines is not None:
        return estimate_lines(value, width, size, font)
    capacity = max(1, (width - 8) / (size * 1.08))
    return sum(max(1, math.ceil(sum(1 if unicodedata.east_asian_width(c) in 'WF' else .56
                                  for c in line) / capacity)) for line in value.split('\n'))


def profile(spec, width=960, height=540):
    """Validate compact job-local typography and spacing without changing a job."""
    raw = spec.get('presentationProfile', {})
    keys = {'titleSize', 'bodySize', 'emphasisSize', 'annotationSize', 'tableSize', 'titleFont',
            'bodyFont', 'margin', 'gap', 'density'}
    if not isinstance(raw, dict) or set(raw) - keys:
        raise LayoutError('presentationProfile의 글꼴, 크기와 여백 항목을 확인해 주세요.')
    density = raw.get('density', 'presentation')
    if density not in ('presentation', 'reading'):
        raise LayoutError('정보 밀도는 presentation 또는 reading으로 지정해 주세요.')
    font = spec.get('presentationFont', 'Malgun Gothic')
    result = {'titleSize':30., 'bodySize':18. if density == 'presentation' else 16.,
              'emphasisSize':36., 'annotationSize':11., 'tableSize':16., 'titleFont':font,
              'bodyFont':font, 'margin':width*.05, 'gap':width*.025, 'density':density}
    result.update(raw)
    for key, low, high in (('titleSize', 16, 60), ('bodySize', 10, 32),
                           ('emphasisSize', 20, 96), ('annotationSize', 8, 18),
                           ('tableSize', 10, 28),
                           ('margin', 20, min(width*.16, height*.18)), ('gap', 8, 60)):
        result[key] = _number(result[key], low, high, key)
    for key in ('titleFont', 'bodyFont'):
        result[key] = _string(result[key], key, 80)
        if not result[key].strip():
            raise LayoutError('역할별 글꼴 이름은 빈칸으로 둘 수 없습니다.')
        if key in raw and result[key] != 'Malgun Gothic':
            from .ppt_workflow import font_available
            if not font_available(result[key]):
                raise LayoutError('역할별 글꼴을 이 PC에서 확인하지 못했습니다. 설치된 글꼴을 선택해 주세요.')
    return result


def _prose(row):
    body = _string(row.get('body', ''))
    bullets = row.get('bullets', [])
    if not isinstance(bullets, list) or len(bullets) > 30:
        raise LayoutError('한 장의 항목은 목록으로 지정해 주세요.')
    return '\n'.join(([body] if body else []) + [_string(value) for value in bullets])


def compose(row, number, width, height, palette, font, profile):
    """Return one role-specific shared scene, or None for the legacy composer.

    ``workflow`` requires explicit nodes and edges. ``milestones`` uses ISO dates
    and positions points on the actual min/max day scale. No dates, numbers,
    relationships, roles or business conclusions are invented here.
    """
    if 'elements' in row or 'contentOrder' in row or row.get('imageLayout') == 'full-slide':
        return None
    role = row.get('pageRole')
    if role is None:
        return None
    if role not in ROLES:
        raise LayoutError('pageRole은 '+', '.join(ROLES)+' 중 선택해 주세요.')
    p = profile
    margin, gap = p['margin'], p['gap']
    usable = width-2*margin
    title = _string(row.get('title', ''), '제목', 300)
    body = _prose(row)
    elements = []
    background = palette.get('background', 'FFFFFF')

    def lines(value, width, size, face=None):
        return _lines(value, width, size, face or p['bodyFont'])

    def text(value, x, y, w, h, size=None, color='text', bold=False, *, align='left', group=None, heading=False):
        if not value:
            return
        value = _string(value)
        size = p['bodySize'] if size is None else size
        if w <= 0 or h <= 0 or lines(value,w,size,p['titleFont'] if heading else p['bodyFont'])*size*1.22+3 > h+.01:
            raise LayoutError(f'{number}장 {role} 구성의 글자가 영역보다 많습니다. 의미를 보존해 문장을 나누거나 장을 나누어 주세요.')
        e = dict(kind='text',text=value,x=x,y=y,w=w,h=h,size=size,color=palette.get(color,color),
                 bold=bold,font=p['titleFont'] if heading else p['bodyFont'],wrap=True,
                 align=align,lineSpacing=1.15)
        if group:
            e['group'] = group
        elements.append(e)

    def shape(x,y,w,h,fill='tint', *, kind='rect', group=None, border=None):
        e = dict(kind='shape',shape=kind,x=x,y=y,w=w,h=h,fill=palette.get(fill,fill))
        if group:
            e['group'] = group
        if border:
            e.update(border=palette.get(border,border),borderWidth=.8)
        elements.append(e)

    def polyline(points, *, arrow=False, group=None):
        # Local point coordinates also express decreasing paths without negative
        # scene dimensions. A 0.1pt orthogonal extent is visually negligible.
        points=[point for i,point in enumerate(points) if not i or point!=points[i-1]]
        # Preserve a native straight connector when no actual bend is needed.
        compact=[]
        for point in points:
            while len(compact)>1:
                a,b=compact[-2:]
                cross=(b[0]-a[0])*(point[1]-b[1])-(b[1]-a[1])*(point[0]-b[0])
                forward=(b[0]-a[0])*(point[0]-b[0])+(b[1]-a[1])*(point[1]-b[1])
                if abs(cross)>.0001 or forward<0:break
                compact.pop()
            compact.append(point)
        points=compact
        x,y = min(point[0] for point in points),min(point[1] for point in points)
        w,h = max(.1,max(point[0] for point in points)-x),max(.1,max(point[1] for point in points)-y)
        e = dict(kind='line',x=x,y=y,w=w,h=h,points=[[px-x,py-y] for px,py in points],
                 border=palette.get('accent','087F8C'),borderWidth=1.4,fill='none')
        if arrow:
            e['endArrow'] = 'triangle'
        if group:
            e['group'] = group
        elements.append(e)

    def line(x1,y1,x2,y2, *, arrow=False, group=None):
        polyline([(x1,y1),(x2,y2)],arrow=arrow,group=group)

    note = _string(row.get('source',''), '출처', 180)
    if note:
        text(note,margin,height-31,usable-45,22,p['annotationSize'],'muted')
    text(f'{number:02d}',width-margin-30,height-31,30,22,p['annotationSize'],'muted',align='right')
    top = 34.
    if row.get('eyebrow'):
        text(_string(row['eyebrow'],'분류',70),margin,12,usable,21,p['annotationSize'],'muted')
    if role != 'cover':
        title_h = lines(title,usable,p['titleSize'],p['titleFont'])*p['titleSize']*1.22+4
        text(title,margin,top,usable,title_h,p['titleSize'],'title',True,heading=True)
        top += title_h+gap
    bottom = height-55
    for visual in ('image','chart','table','kpis'):
        if row.get(visual) and not ((role=='key-message' and visual=='kpis') or (role=='detail' and visual=='table')):
            raise LayoutError(f'{role} 구성에서 {visual} 자료를 생략하지 않았습니다. 해당 자료에 맞는 장 역할 또는 elements를 선택해 주세요.')
    for field, target in (('workflow','workflow'), ('milestones','timeline'), ('panels','comparison')):
        if row.get(field) and role != target:
            raise LayoutError(f'{field} 자료를 {role} 장에서 생략하지 않았습니다. 맞는 pageRole 또는 elements로 구성해 주세요.')

    if role == 'cover':
        if any(row.get(key) for key in ('workflow','milestones','panels')):
            raise LayoutError('표지에 업무 도식이나 일정 자료를 숨기지 않습니다. 본문 장 또는 elements로 구성해 주세요.')
        shape(width*.80,margin,width*.12,height-2*margin,'tint')
        shape(width*.80,margin,5,height-2*margin,'accent')
        tw=width*.68-margin
        title_h=lines(title,tw,p['emphasisSize'],p['titleFont'])*p['emphasisSize']*1.23+4
        text(title,margin,height*.23,tw,title_h,p['emphasisSize'],'title',True,heading=True)
        y=height*.23+title_h+gap
        text(body,margin,y,tw,bottom-y,p['bodySize'],'text')
    elif role == 'key-message':
        kpis=row.get('kpis',[])
        if not isinstance(kpis,list) or len(kpis)>3:
            raise LayoutError('핵심 지표는 이미 계산된 항목을 최대 3개 지정해 주세요.')
        if kpis:
            kw=(usable-gap*(len(kpis)-1))/len(kpis)
            for index,kpi in enumerate(kpis):
                if not isinstance(kpi,dict) or not all(isinstance(kpi.get(k),str) for k in ('label','value')):
                    raise LayoutError('핵심 지표의 확인된 label과 value가 필요합니다.')
                x=margin+index*(kw+gap)
                group=f'kpi-{number}-{index+1}'
                shape(x,top,kw,148,'tint',group=group)
                text(kpi['label'],x+16,top+16,kw-32,32,p['bodySize'],'muted',group=group)
                value=kpi['value']+(' '+_string(kpi.get('unit',''),'단위',12) if kpi.get('unit') else '')
                text(value,x+16,top+62,kw-32,68,p['emphasisSize'],'accent',True,group=group)
            top+=148+gap
            text(body,margin,top,usable,bottom-top,p['bodySize'])
        else:
            if not body:
                raise LayoutError('핵심 메시지에는 확인한 본문이나 지표가 필요합니다.')
            shape(margin,top,6,bottom-top,'accent')
            text(body,margin+gap,top,usable-gap,bottom-top,p['emphasisSize'],'title',True,heading=True)
    elif role == 'comparison':
        panels=row.get('panels')
        if not isinstance(panels,list) or not 2<=len(panels)<=3:
            raise LayoutError('비교 장은 실제 비교할 panels 2~3개를 지정해 주세요.')
        if body:
            bh=lines(body,usable,p['bodySize'])*p['bodySize']*1.22+4
            text(body,margin,top,usable,bh)
            top+=bh+gap
        cw=(usable-gap*(len(panels)-1))/len(panels)
        measured=[]
        for panel in panels:
            if not isinstance(panel,dict) or set(panel)-{'title','body','bullets'}:
                raise LayoutError('비교 항목의 제목과 본문을 객체로 지정해 주세요.')
            label=_string(panel.get('title',''),'비교 제목',100)
            content=_prose(panel)
            if not label or not content:
                raise LayoutError('비교 항목에는 제목과 확인할 내용이 필요합니다.')
            th=lines(label,cw-32,p['bodySize'])*p['bodySize']*1.22+4
            # Native Korean font ascent and paragraph leading need slightly
            # more room than CSS line-height, especially in compact boxes.
            ch=lines(content,cw-32,p['bodySize'])*p['bodySize']*1.36+4
            measured.append((label,content,th,ch))
        panel_h=max(th+ch+48 for _,_,th,ch in measured)
        if panel_h>bottom-top:
            raise LayoutError(f'{number}장 panels의 설명이 비교 영역보다 많습니다. 원본 의미를 유지해 비교 대상을 장으로 나누어 주세요.')
        panel_top=top+(bottom-top-panel_h)/2
        for index,(label,content,th,ch) in enumerate(measured):
            x=margin+index*(cw+gap)
            group=f'compare-{number}-{index+1}'
            shape(x,panel_top,cw,panel_h,'tint',group=group)
            text(label,x+16,panel_top+16,cw-32,th,p['bodySize'],'title',True,group=group)
            text(content,x+16,panel_top+th+32,cw-32,ch,p['bodySize'],group=group)
    elif role == 'workflow':
        flow=row.get('workflow')
        if not isinstance(flow,dict) or set(flow)-{'nodes','edges'}:
            raise LayoutError('업무 흐름은 workflow의 nodes와 edges로 실제 관계를 지정해 주세요.')
        nodes,edges=flow.get('nodes'),flow.get('edges')
        if not isinstance(nodes,list) or not 1<=len(nodes)<=8 or not isinstance(edges,list) or len(edges)>12:
            raise LayoutError('업무 흐름은 1~8개 노드와 최대 12개 실제 연결을 사용합니다.')
        ids=[]
        for node in nodes:
            if (not isinstance(node,dict) or set(node)-{'id','title','body','shape'}
                    or not isinstance(node.get('id'),str) or not node['id']
                    or node['id'] in ids or not isinstance(node.get('title'),str) or not node['title']):
                raise LayoutError('업무 노드에는 중복 없는 id와 제목이 필요합니다.')
            if node.get('shape','rect') not in ('rect','roundRect','diamond','chevron','hexagon','parallelogram'):
                raise LayoutError('업무 노드 도형은 rect, roundRect, diamond, chevron, hexagon, parallelogram을 지원합니다.')
            ids.append(node['id'])
        incoming={key:0 for key in ids}
        children=defaultdict(list)
        for edge in edges:
            if (not isinstance(edge,dict) or edge.get('from') not in ids or edge.get('to') not in ids
                    or edge.get('from')==edge.get('to')):
                raise LayoutError('연결의 from과 to에는 실제 서로 다른 노드 id가 필요합니다.')
            pair=(edge['from'],edge['to'])
            if pair in children[edge['from']]:
                raise LayoutError('같은 업무 연결을 중복 지정하지 마세요.')
            children[edge['from']].append(pair)
            incoming[edge['to']]+=1
        queue=[key for key in ids if incoming[key]==0]
        levels={key:0 for key in queue}
        visited=[]
        while queue:
            key=queue.pop(0);visited.append(key)
            for _,target in children[key]:
                levels[target]=max(levels.get(target,0),levels[key]+1)
                incoming[target]-=1
                if incoming[target]==0:queue.append(target)
        if len(visited)!=len(nodes):
            raise LayoutError('순환 업무 흐름은 위치를 직접 정한 elements로 표현해 주세요. 순서를 임의로 바꾸지 않았습니다.')
        if body:
            bh=lines(body,usable,p['bodySize'])*p['bodySize']*1.22+4
            text(body,margin,top,usable,bh);top+=bh+gap
        buckets=defaultdict(list)
        for node in nodes:buckets[levels[node['id']]].append(node)
        columns=max(levels.values())+1
        if columns>4:
            raise LayoutError('한 장의 업무 흐름은 4단계 이내로 나누거나 elements에 명시한 좌표를 사용해 주세요.')
        # Labels need real space between columns; a fixed 80pt label over a
        # 24pt gutter used to sit on the neighbouring node's border.
        column_gaps=[gap]*(columns-1)
        labels={}
        gutter_edges=defaultdict(list)
        for i,edge in enumerate(edges):
            if levels[edge['to']]==levels[edge['from']]+1:
                gutter_edges[levels[edge['from']]].append(i)
        for i,edge in enumerate(edges):
            if edge.get('label'):
                label=_string(edge['label'],'연결 설명',40)
                labels[i]=label
                if levels[edge['to']]==levels[edge['from']]+1:
                    label_w=24.
                    while label_w<120 and lines(label,label_w,p['annotationSize'])>1:
                        label_w+=4
                    band=10+3*(len(gutter_edges[levels[edge['from']]])-1)
                    level=levels[edge['from']]
                    column_gaps[level]=max(column_gaps[level],label_w+2*band+12)
        # Widen only the gutter that owns a label. Applying its maximum width
        # to every column needlessly squeezed Korean node text elsewhere.
        cw=(usable-sum(column_gaps))/columns
        column_x=[margin+level*cw+sum(column_gaps[:level]) for level in range(columns)]
        if cw<65:
            raise LayoutError('업무 연결 설명을 읽기 좋은 크기로 담기 어렵습니다. 장을 나누거나 elements로 배치해 주세요.')
        # Skipping a level must not draw through the intervening work. Reserve
        # an independent lane above all nodes, including space for its label.
        lanes={}
        node_top=top
        for i,edge in enumerate(edges):
            if levels[edge['to']]<=levels[edge['from']]+1:
                continue
            span=column_x[levels[edge['to']]]-column_x[levels[edge['from']]]-cw-12
            label_w=min(180.,span)
            label_h=lines(labels[i],label_w,p['annotationSize'])*p['annotationSize']*1.22+4 if i in labels else 0
            lanes[i]=(node_top+label_h+4,label_w,label_h)
            node_top+=label_h+14
        positions={}
        for level,bucket in buckets.items():
            desired=130.
            for node in bucket:
                if node.get('shape')=='diamond':
                    detail=_string(node.get('body',''),'업무 설명',500)
                    value=_string(node['title'],'업무 제목',120)+('\n'+detail if detail else '')
                    desired=max(desired,(lines(value,cw*.55,p['bodySize'])*p['bodySize']*1.22+4)/.4)
            nh=min(desired,(bottom-node_top-gap*(len(bucket)-1))/len(bucket))
            if nh<65:raise LayoutError('병렬 업무 노드를 읽기 좋은 크기로 담기 어렵습니다. 장을 나누어 주세요.')
            y=node_top+(bottom-node_top-(nh*len(bucket)+gap*(len(bucket)-1)))/2
            for node in bucket:
                positions[node['id']]=(column_x[level],y,cw,nh)
                y+=nh+gap
        # Forks and merges can share the same source or target height. Give
        # every edge in a labelled gutter its own horizontal route and reserve
        # narrow side bands for vertical segments so no line crosses a label.
        local_routes={}
        for level,indexes in gutter_edges.items():
            if not any(i in labels for i in indexes):continue
            band=10+3*(len(indexes)-1)
            label_w=column_gaps[level]-2*band-12
            slots=[]
            for rank,i in enumerate(indexes):
                edge=edges[i]
                sx,sy,sw,sh=positions[edge['from']];tx,ty,tw,th=positions[edge['to']]
                label_h=lines(labels[i],label_w,p['annotationSize'])*p['annotationSize']*1.22+4 if i in labels else 0
                slots.append({'i':i,'rank':rank,'h':label_h,'target':ty+th/2,
                              'source':sy+sh/2,'extent':label_h+10})
            slots.sort(key=lambda item:(item['target'],item['source'],item['i']))
            cursor=node_top
            for slot in slots:
                slot['y']=max(cursor,slot['target']-slot['h']-4)
                cursor=slot['y']+slot['extent']
            cursor=bottom
            for slot in reversed(slots):
                slot['y']=min(slot['y'],cursor-slot['extent'])
                cursor=slot['y']
            if cursor<node_top:
                raise LayoutError('업무 연결 설명을 읽기 좋은 크기로 담기 어렵습니다. 장을 나누거나 elements로 배치해 주세요.')
            for slot in slots:
                local_routes[slot['i']]={**slot,'w':label_w,'band':band}
        # Lines are behind editable node boxes and only reflect supplied edges.
        for i,edge in enumerate(edges):
            sx,sy,sw,sh=positions[edge['from']];tx,ty,tw,th=positions[edge['to']]
            source_y,target_y=sy+sh/2,ty+th/2
            if i in lanes:
                lane_y,label_w,label_h=lanes[i]
                # Keep vertical bypasses outside the adjacent edge's label.
                exit_x,entry_x=sx+sw+6,tx-6
                polyline([(sx+sw,source_y),(exit_x,source_y),(exit_x,lane_y),
                          (entry_x,lane_y),(entry_x,target_y),(tx,target_y)],arrow=True)
                if i in labels:
                    text(labels[i],(exit_x+entry_x-label_w)/2,lane_y-label_h-3,
                         label_w,label_h,p['annotationSize'],'muted',align='center')
            elif i in local_routes:
                slot=local_routes[i]
                offset=10+3*slot['rank']
                exit_x,entry_x=sx+sw+offset,tx-offset
                route_y=slot['y']+slot['h']+4
                polyline([(sx+sw,source_y),(exit_x,source_y),(exit_x,route_y),
                          (entry_x,route_y),(entry_x,target_y),(tx,target_y)],arrow=True)
                if i in labels:
                    text(labels[i],sx+sw+slot['band']+6,slot['y'],slot['w'],slot['h'],
                         p['annotationSize'],'muted',align='center')
            else:
                mid=(sx+sw+tx)/2
                polyline([(sx+sw,source_y),(mid,source_y),(mid,target_y),(tx,target_y)],arrow=True)
        for index,node in enumerate(nodes):
            x,y,w,h=positions[node['id']]
            group=f'flow-{number}-{index+1}'
            contour=node.get('shape','rect')
            shape(x,y,w,h,'tint',kind=contour,group=group,border='accent')
            label=_string(node['title'],'업무 제목',120)
            detail=_string(node.get('body',''),'업무 설명',500)
            if contour=='diamond':
                value=label+('\n'+detail if detail else '')
                # A centred rectangle is inside a diamond only if its width
                # and height ratios sum to <=1. Keep a little border clearance.
                text(value,x+w*.225,y+h*.30,w*.55,h*.4,p['bodySize'],'title',True,group=group,align='center')
                elements[-1]['verticalAlign']='middle'
                continue
            if contour in ('chevron','hexagon','parallelogram'):
                # Reserve the sloped contour ends; do not let text rest on them.
                x,w=x+w*.12,w*.76
            th=min(h-24,lines(label,w-24,p['bodySize'])*p['bodySize']*1.22+4)
            text(label,x+12,y+12,w-24,th,p['bodySize'],'title',True,group=group)
            if detail:text(detail,x+12,y+th+20,w-24,h-th-30,p['annotationSize']+2,group=group)
    elif role == 'timeline':
        milestones=row.get('milestones')
        if not isinstance(milestones,list) or not 2<=len(milestones)<=7:
            raise LayoutError('일정 장에는 실제 날짜가 있는 milestones 2~7개가 필요합니다.')
        parsed=[]
        for item in milestones:
            if (not isinstance(item,dict) or set(item)-{'label','date','detail'}
                    or not isinstance(item.get('date'),str)):
                raise LayoutError('일정은 label과 YYYY-MM-DD 날짜를 지정해 주세요.')
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',item['date']):
                raise LayoutError('일정 날짜는 실제 YYYY-MM-DD 형식으로 지정해 주세요.')
            try: day=date.fromisoformat(item['date'])
            except ValueError:raise LayoutError('일정 날짜는 실제 YYYY-MM-DD 형식으로 지정해 주세요.') from None
            parsed.append((day,_string(item.get('label',''),'일정 제목',100),_string(item.get('detail',''),'일정 설명',300)))
        if any(not label for _,label,_ in parsed):raise LayoutError('일정 제목은 빈칸으로 둘 수 없습니다.')
        if body:
            bh=lines(body,usable,p['bodySize'])*p['bodySize']*1.22+4
            text(body,margin,top,usable,bh);top+=bh+gap
        parsed.sort(key=lambda item:item[0])
        start,end=parsed[0][0],parsed[-1][0]
        label_w=min(usable*.34,260.)
        axis_x=margin+label_w+gap
        axis_w=width-margin-axis_x-18
        top+=28
        row_h=(bottom-top)/len(parsed)
        if row_h<35:raise LayoutError('일정 설명을 읽기 좋은 크기로 담기 어렵습니다. 장을 나누어 주세요.')
        text(start.isoformat(),axis_x,top-28,110,22,p['annotationSize'],'muted')
        text(end.isoformat(),axis_x+axis_w-110,top-28,110,22,p['annotationSize'],'muted',align='right')
        for index,(day,label,detail) in enumerate(parsed):
            y=top+index*row_h
            shape(margin,y,usable,row_h-3,'tint' if index%2==0 else 'background')
            heading=label+(' / '+detail if detail else '')
            text(heading,margin+8,y+4,label_w-8,row_h-8,p['bodySize'],'text')
            line(axis_x,y+row_h/2,axis_x+axis_w,y+row_h/2)
            ratio=((day-start).days/(end-start).days) if end>start else .5
            x=axis_x+axis_w*ratio
            shape(x-5,y+row_h/2-5,10,10,'accent',kind='ellipse')
            # End-point dates must stay inside the axis column. Centering the
            # first date over its marker used to intrude into a wrapped Korean
            # milestone description in the adjacent column.
            date_x=max(axis_x,min(x-42,axis_x+axis_w-84))
            text(day.isoformat(),date_x,y+row_h/2-24,84,20,p['annotationSize'],'muted',align='center')
    elif role == 'detail':
        table=row.get('table')
        if not isinstance(table,dict) or not isinstance(table.get('headers'),list) or not table['headers']:
            raise LayoutError('상세 표 장에는 table.headers와 table.rows가 필요합니다.')
        rows=[table['headers'],*table.get('rows',[])]
        if any(not isinstance(r,list) or len(r)!=len(rows[0]) for r in rows):
            raise LayoutError('상세 표의 table.rows는 table.headers와 같은 열 수여야 합니다.')
        rows=[[_string(v,'표 내용',2000) for v in r] for r in rows]
        if body:
            bh=lines(body,usable,p['bodySize'])*p['bodySize']*1.22+4
            text(body,margin,top,usable,bh);top+=bh+gap
        style=row.get('tableStyle', {})
        size=style.get('fontSize', p['tableSize'])
        padding=style.get('padding', 6)
        weights=[min(4,max(1,max(len(r[j]) for r in rows)/8)) for j in range(len(rows[0]))]
        widths=[usable*w/sum(weights) for w in weights]
        heights=[max(32,max(lines(v,max(1,widths[j]-2*padding),size) for j,v in enumerate(r))*size*1.22+2*padding) for r in rows]
        if sum(heights)>bottom-top:
            from .presentation_design import TableFitError
            raise TableFitError(number,heights,bottom-top)
        elements.append(dict(kind='table',x=margin,y=top,w=usable,h=sum(heights),size=size,
                             table={'headers':rows[0],'rows':rows[1:]},columnWidths=widths,rowHeights=heights))
    else: # closing
        if not body:raise LayoutError('결론 장에는 확인된 결론이나 다음 행동을 지정해 주세요.')
        content_h=lines(body,usable-2*gap,p['bodySize'])*p['bodySize']*1.36+4
        box_h=content_h+2*gap
        if box_h>bottom-top:
            raise LayoutError(f'{number}장 결론의 글자가 영역보다 많습니다. 의미를 보존해 장을 나누어 주세요.')
        box_top=top+(bottom-top-box_h)/2
        shape(margin,box_top,usable,box_h,'tint')
        shape(margin,box_top,usable,5,'accent')
        text(body,margin+gap,box_top+gap,usable-2*gap,content_h,p['bodySize'],'title',True)
    takeaway=_string(row.get('takeaway',''),'요점',160)
    if takeaway:
        # Preserve a separate takeaway rather than silently mixing it into the
        # title or dropping it. The role's footer has a dedicated second line.
        text(takeaway,margin,height-54,usable,22,p['annotationSize'],'accent',True)
    for e in elements:
        if min(e['x'],e['y'])<0 or e['x']+e['w']>width+.5 or e['y']+e['h']>height+.5:
            raise LayoutError('역할별 구성의 개체가 장표 영역을 벗어납니다. 여백과 자료 분량을 확인해 주세요.')
    return {'elements':elements,'background':background,'pageRole':role}


def examples():
    """Small fictitious examples; no approval or user content is generated."""
    return [
        {'pageRole':'cover','title':'가상 교육 운영 보고','body':'자료 준비부터 검토와 재사용까지\n현재 내용은 양식 비교용 가상 자료입니다.'},
        {'pageRole':'key-message','title':'작은 업무부터 결과를 확인합니다','body':'가상 자료로 도구와 검토 방법을 먼저 확인합니다.\n실제 업무 적용 여부는 시험 결과를 보고 정합니다.'},
        {'pageRole':'comparison','title':'조회와 실행의 범위를 구분합니다',
         'panels':[{'title':'조회 업무','body':'필요한 자료만 확인\n원본을 바꾸지 않고 요약'},
                   {'title':'실행 업무','body':'변경할 대상과 결과 확인\n수행 후 실제 결과 재확인'}]},
        {'pageRole':'workflow','title':'자료 확인 후 분기해 처리합니다',
         'workflow':{'nodes':[{'id':'request','title':'요청 확인'}, {'id':'read','title':'자료 조회'},
                              {'id':'change','title':'내용 변경'}, {'id':'review','title':'결과 확인'}],
                     'edges':[{'from':'request','to':'read'}, {'from':'request','to':'change'},
                              {'from':'read','to':'review'}, {'from':'change','to':'review'}]}},
        {'pageRole':'timeline','title':'가상 일정의 간격을 실제 날짜로 표시합니다',
         'milestones':[{'label':'자료 준비','date':'2027-01-05'}, {'label':'작은 시험','date':'2027-01-15'},
                       {'label':'결과 검토','date':'2027-02-20'}]},
        {'pageRole':'detail','title':'범위와 상태를 표로 확인합니다',
         'table':{'headers':['항목','확인할 내용','상태'],
                  'rows':[['원자료','항목과 범위','준비'],['작은 시험','의도한 결과와 오류','검토'],
                          ['재사용','절차와 판단 근거','미정']]}},
        {'pageRole':'closing','title':'검토한 절차를 다음 업무에 재사용합니다',
         'body':'확인한 결과와 예외를 함께 정리합니다.\n미확인 효과나 일정을 임의로 확정하지 않습니다.'}
    ]
