"""Bounded observed design rules shared by report and presentation authoring.

The host observes reference images. This module validates and applies those
observations; it neither reads pixels nor calls a model or changes user state.
Sizes are pt for PPT and px for HTML, recorded in the current job only.
"""
from copy import deepcopy
import math
import re


def _error(message):
    raise ValueError('참고 디자인: '+message)


def _color(value):
    if not isinstance(value,str) or not re.fullmatch(r'#?[0-9a-fA-F]{6}',value):
        _error('색상은 # 선택형의 6자리 RGB로 지정해 주세요.')
    return value.lstrip('#').upper()


def _number(value,low,high):
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
        _error(f'크기와 간격은 {low}~{high} 사이의 유한 숫자여야 합니다.')
    return value


def _text(value,limit):
    if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 and c not in '\n\t' for c in value):
        _error('관찰 설명의 길이와 형식을 확인해 주세요.')
    return value


def _font(value):
    if not isinstance(value,str) or not re.fullmatch(r'[\w][\w ()-]{0,79}',value,re.UNICODE):
        _error('글꼴은 한 개의 실제 글꼴 이름으로 지정해 주세요.')
    return value


def _palette(value):
    if not isinstance(value,list) or not 1<=len(value)<=12:
        _error('계열 색상은 순서가 있는 1~12개 목록입니다.')
    return [_color(v) for v in value]


def normalize(raw):
    """Return a small data-only observation, rejecting executable style input."""
    fields={'colors','typography','spacing','table','chart','patterns','evidence'}
    if not isinstance(raw,dict) or set(raw)-fields:
        _error('지원하는 관찰 필드만 사용해 주세요.')
    result={}
    rules={
      'colors':{**{k:_color for k in ('bg','surface','text','muted','primary','secondary','border','tint')},'series':_palette},
      'typography':{'headingFont':_font,'bodyFont':_font,
                    'titleSize':lambda v:_number(v,6,96),'bodySize':lambda v:_number(v,6,64),
                    'captionSize':lambda v:_number(v,6,48)},
      'spacing':{'outer':lambda v:_number(v,0,160),'gap':lambda v:_number(v,0,80),'radius':lambda v:_number(v,0,60)},
      'table':{**{k:_color for k in ('headerFill','headerText','bodyFill','bodyText','alternateFill','borderColor')},
               'borderWidth':lambda v:_number(v,0,6),'fontSize':lambda v:_number(v,6,48),'padding':lambda v:_number(v,0,24)},
      'chart':{'seriesColors':_palette, 'fontSize':lambda v:_number(v,6,32),'labelSize':lambda v:_number(v,6,32),
               'gridColor':_color,'lineWidth':lambda v:_number(v,.25,8)},
      'patterns':{k:lambda v:_text(v,500) for k in ('layout','tables','charts','shapes','emphasis','writing')},
    }
    def flag(value):
        if type(value) is not bool:_error('표시 여부는 true 또는 false입니다.')
        return value
    def choice(value,allowed):
        if not isinstance(value,str) or value not in allowed:_error('지원하는 서식 선택값을 사용해 주세요.')
        return value
    rules['table'].update(headerBold=flag,align=lambda v:choice(v,('left','center','right')))
    rules['chart'].update(showGrid=flag,legendPosition=lambda v:choice(v,('top','bottom','left','right','none')),
                          marker=lambda v:choice(v,('circle','square','diamond','none')))
    for field,validators in rules.items():
        if field not in raw:continue
        source=raw[field]
        if not isinstance(source,dict) or set(source)-set(validators):_error(field+'의 지원 항목을 확인해 주세요.')
        result[field]={key:validators[key](value) for key,value in source.items()}
    if 'evidence' in raw:
        evidence=raw['evidence']
        if not isinstance(evidence,list) or len(evidence)>60:_error('관찰 근거는 최대 60개이며 전체 OCR을 넣지 않습니다.')
        result['evidence']=[]
        for item in evidence:
            if not isinstance(item,dict) or set(item)-{'source','scope','observed','uncertain'} or not item.get('source'):
                _error('관찰 근거에 원본 이름과 실제 확인 범위를 남겨 주세요.')
            checked={'source':_text(item['source'],2048)}
            if 'scope' in item:checked['scope']=_text(item['scope'],160)
            for key in ('observed','uncertain'):
                if key in item:
                    if not isinstance(item[key],list) or len(item[key])>12:_error('관찰과 추정은 짧은 목록 12개 이내입니다.')
                    checked[key]=[_text(v,300) for v in item[key]]
            result['evidence'].append(checked)
    return result


def _merge(base,overrides):
    result=deepcopy(base)
    for key,value in overrides.items():
        result[key]={**result.get(key,{}),**deepcopy(value)} if isinstance(value,dict) else deepcopy(value)
    return result


def apply(spec,target):
    """Apply observed defaults, then preserve each explicit authoring choice."""
    if target not in ('html','ppt'):_error('출력 형식을 확인해 주세요.')
    result=deepcopy(spec)
    if 'referenceStyle' not in spec and 'themeOverrides' not in spec:return result
    profile=normalize(spec.get('referenceStyle',{}))
    if 'referenceStyle' in spec:result['referenceStyle']=profile
    visual={k:deepcopy(v) for k,v in profile.items() if k not in ('patterns','evidence')}
    if target=='html':
        explicit=normalize(spec.get('themeOverrides',{}))
        if set(explicit)&{'patterns','evidence'}:_error('themeOverrides에는 실제 출력 서식만 지정해 주세요.')
        result['themeOverrides']=_merge(visual,explicit)
        return result
    for field in ('presentationTheme','presentationProfile','tableStyle','chartStyle'):
        if field in spec and not isinstance(spec[field],dict):
            _error(field+'는 서식 항목을 담은 객체여야 합니다.')
    colors=profile.get('colors',{})
    typography=profile.get('typography',{})
    spacing=profile.get('spacing',{})
    names={'surface':'background','text':'text','muted':'muted','primary':'accent','tint':'tint'}
    theme={names[key]:value for key,value in colors.items() if key in names}
    if 'text' in colors:theme['title']=colors['text']
    if 'background' not in theme and 'bg' in colors:theme['background']=colors['bg']
    result['presentationTheme']={**theme,**spec.get('presentationTheme',{})}
    font=spec.get('presentationFont') or typography.get('bodyFont') or typography.get('headingFont')
    if font:result['presentationFont']=font
    styles={key:typography[name] for name,key in (('titleSize','titleSize'),('bodySize','bodySize'),
             ('captionSize','annotationSize'),('headingFont','titleFont'),('bodyFont','bodyFont')) if name in typography}
    styles.update({dest:spacing[src] for src,dest in (('outer','margin'),('gap','gap')) if src in spacing})
    if spec.get('presentationFont'):
        styles.update(titleFont=spec['presentationFont'],bodyFont=spec['presentationFont'])
    if styles or 'presentationProfile' in spec:result['presentationProfile']={**styles,**spec.get('presentationProfile',{})}
    table={dest:colors[src] for src,dest in (('primary','headerFill'),('surface','headerText'),('surface','bodyFill'),
                ('text','bodyText'),('tint','alternateFill'),('border','borderColor')) if src in colors}
    if 'bodySize' in typography:table['fontSize']=typography['bodySize']
    table.update(profile.get('table',{}));table.update(spec.get('tableStyle',{}))
    if table:result['tableStyle']=table
    chart={}
    if colors.get('series'):chart['seriesColors']=colors['series']
    elif 'primary' in colors:chart['seriesColors']=[colors['primary']]+([colors['secondary']] if 'secondary' in colors else [])
    if 'border' in colors:chart['gridColor']=colors['border']
    chart.update(profile.get('chart',{}));chart.update(spec.get('chartStyle',{}))
    if chart:result['chartStyle']=chart
    return result
