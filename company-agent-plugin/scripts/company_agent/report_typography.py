"""Report font choices. Pure metadata/CSS: no discovery, downloads or model calls."""
import json
import re

FIELDS = ('fontChoiceRequired', 'fontChoice', 'fontName', 'fontSource')
OPTIONS = (
    ('noto-sans-kr', 'Noto Sans KR', '긴 본문과 업무 보고서에 고르게 읽히는 글꼴'),
    ('pretendard', 'Pretendard', '숫자·버튼·표가 많은 대시보드에 어울리는 글꼴'),
    ('nanum-square-neo', '나눔스퀘어 네오', '제목과 짧은 설명이 또렷한 안내 화면에 어울리는 글꼴'),
    ('auto', '디자인에 맞게 알아서 선택', '지정한 양식은 유지하고, 없으면 내용과 디자인에 맞춰 선택'),
    ('custom', '직접 입력', '사용할 글꼴 이름을 알려 주세요'),
)
FAMILIES = {'noto-sans-kr': 'Noto Sans KR', 'pretendard': 'Pretendard',
            'nanum-square-neo': 'NanumSquareNeo'}


def validate(spec):
    """Keep incomplete choices valid while rejecting CSS/URL disguised as a font."""
    if 'fontChoiceRequired' in spec and not isinstance(spec['fontChoiceRequired'], bool):
        raise ValueError('글꼴 질문 여부는 true 또는 false로 지정해 주세요.')
    choice = spec.get('fontChoice')
    if 'fontChoice' in spec and (not isinstance(choice, str) or choice not in {row[0] for row in OPTIONS}):
        raise ValueError('지원하는 글꼴 선택값을 사용해 주세요.')
    if 'fontName' in spec:
        name = spec['fontName']
        if (choice != 'custom' or not isinstance(name, str) or not name.strip()
                or len(name) > 80 or not re.fullmatch(r'[\w \-]+', name, re.UNICODE)):
            raise ValueError('직접 입력은 글꼴 이름만 사용해 주세요. URL이나 CSS는 넣지 않습니다.')
    if 'fontSource' in spec and spec['fontSource'] not in ('system', 'google'):
        raise ValueError('글꼴 출처는 system 또는 google로 지정해 주세요.')
    # This existing opt-in is specifically the Noto Sans KR Google stylesheet.
    if spec.get('fontSource') == 'google' and choice not in (None, 'noto-sans-kr', 'auto'):
        raise ValueError('Google Fonts 연결은 Noto Sans KR만 지원합니다. 다른 글꼴은 system을 사용해 주세요.')
    return {key: spec[key] for key in FIELDS if key in spec}


def missing(spec):
    if spec.get('fontChoice') == 'custom' and not spec.get('fontName'):
        return ['fontName']
    if spec.get('fontChoiceRequired') and 'fontChoice' not in spec:
        # Existing explicit Google selection already names its font.
        return [] if spec.get('fontSource') == 'google' else ['fontChoice']
    return []


def selection(spec):
    choice = spec.get('fontChoice')
    source = spec.get('fontSource', 'system')
    if choice == 'custom':
        family = spec.get('fontName', '').strip()
        if not family:
            raise ValueError('직접 입력할 글꼴 이름을 알려 주세요.')
    elif choice == 'auto' and source != 'google' and spec.get('referenceCss'):
        return {'choice': choice, 'family': None, 'source': 'template',
                'availability': 'not_verified'}
    elif choice == 'auto' and source != 'google':
        family = 'Pretendard' if spec.get('style') in ('bento-grid', 'glassmorphism', 'neumorphism') else 'Noto Sans KR'
    else:
        family = FAMILIES.get(choice, 'Noto Sans KR')
    return {'choice': choice or 'noto-sans-kr', 'family': family,
            'source': source, 'availability': 'not_verified'}


def css(spec):
    chosen = selection(spec)
    if not chosen['family']:
        return ''
    family = json.dumps(chosen['family'], ensure_ascii=False)
    stack = family + ',"Noto Sans KR","Malgun Gothic","Apple SD Gothic Neo",sans-serif'
    return ('\nbody[data-style]{--heading-font:' + stack + ';font-family:' + stack + '}'
            '\nbody[data-style] :is(button,input,select,textarea,h1,h2,h3,svg text){font-family:' + stack + '}')
