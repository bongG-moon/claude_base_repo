"""Report font choices and packaged fonts; no PC discovery or downloads."""
import json
import re
import base64
from pathlib import Path
from functools import lru_cache

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
BUNDLED = {'Noto Sans KR': ('NotoSansKR-Variable.woff2', 'NotoSansKR-OFL.txt'),
           'Pretendard': ('PretendardVariable.woff2', 'Pretendard-OFL.txt')}


def font_directory():
    """정해진 배포 리소스만 사용합니다. 사용자 글꼴 폴더를 탐색하지 않습니다."""
    root = Path(__file__).resolve().parents[2]
    return (root / 'assets/fonts' if __package__ == 'visual_engine'
            else root / 'skills/html-report/assets/fonts')


@lru_cache(maxsize=8)
def bundled_css(family, asset_base=None):
    """라이선스와 함께 선택한 글꼴만 HTML에 넣어 한 파일로 전달합니다."""
    font_name, license_name = BUNDLED[family]
    folder = font_directory()
    raw = (folder / font_name).read_bytes()
    if raw[:4] != b'wOF2' or len(raw) > 8 * 1024 * 1024:
        raise ValueError('배포 글꼴 파일을 확인해 주세요.')
    license_text = '\n'.join(line.rstrip() for line in (folder / license_name).read_text(encoding='utf-8').splitlines())
    license_text = license_text.replace('*/', '* /').replace('<', '&lt;')
    source = ('url(' + json.dumps(asset_base.rstrip('/') + '/' + font_name) + ')' if asset_base is not None
              else 'url(data:font/woff2;base64,' + base64.b64encode(raw).decode('ascii') + ')')
    return ('\n/* Bundled font license: ' + family + '\n' + license_text + '\n*/\n'
            '@font-face{font-family:' + json.dumps(family) + ';font-style:normal;font-weight:100 900;'
            'font-display:swap;src:' + source + ' format("woff2")}')


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
    if 'fontSource' in spec and spec['fontSource'] not in ('system', 'google', 'bundled'):
        raise ValueError('글꼴 출처는 bundled, system 또는 google로 지정해 주세요.')
    # This existing opt-in is specifically the Noto Sans KR Google stylesheet.
    if spec.get('fontSource') == 'google' and choice not in (None, 'noto-sans-kr', 'auto'):
        raise ValueError('Google Fonts 연결은 Noto Sans KR만 지원합니다. 다른 글꼴은 system을 사용해 주세요.')
    if spec.get('fontSource') == 'bundled' and choice not in (None, 'auto', 'noto-sans-kr', 'pretendard'):
        if choice != 'custom' or spec.get('fontName') not in BUNDLED:
            raise ValueError('동봉 글꼴은 Noto Sans KR와 Pretendard입니다. 다른 글꼴은 system을 사용해 주세요.')
    return {key: spec[key] for key in FIELDS if key in spec}


def missing(spec):
    if spec.get('fontChoice') == 'custom' and not spec.get('fontName'):
        return ['fontName']
    if spec.get('fontChoiceRequired') and 'fontChoice' not in spec:
        # A reference reveals a font; it does not choose whether that font or
        # the user's usual font should be used. Explicit auto preserves it.
        # Existing explicit Google selection already names its font.
        return [] if spec.get('fontSource') == 'google' else ['fontChoice']
    return []


def has_reference_font(spec):
    return any(spec.get(key, {}).get('typography', {}).get(role)
               for key in ('referenceStyle', 'themeOverrides')
               for role in ('bodyFont', 'headingFont'))


def selection(spec):
    choice = spec.get('fontChoice')
    source = spec.get('fontSource')
    if choice == 'custom':
        family = spec.get('fontName', '').strip()
        if not family:
            raise ValueError('직접 입력할 글꼴 이름을 알려 주세요.')
    elif choice in (None, 'auto') and source != 'google' and (spec.get('referenceCss') or has_reference_font(spec)):
        return {'choice': choice, 'family': None, 'source': 'template',
                'availability': 'not_verified'}
    elif choice in (None, 'auto') and source != 'google':
        family = 'Pretendard' if spec.get('style') in ('bento-grid', 'glassmorphism', 'neumorphism') else 'Noto Sans KR'
    else:
        family = FAMILIES.get(choice, 'Noto Sans KR')
    available = family in BUNDLED and all((font_directory() / name).is_file() for name in BUNDLED[family])
    if source is None:
        source = 'bundled' if available else 'system'
    if source == 'bundled' and not available:
        raise ValueError('이 글꼴의 동봉 파일이 없습니다. 전체 배포 ZIP 또는 fontSource:system을 사용해 주세요.')
    return {'choice': choice or 'auto', 'family': family,
            'source': source, 'availability': 'embedded_not_rendered' if source == 'bundled' else 'not_verified'}


def css(spec):
    chosen = selection(spec)
    if not chosen['family']:
        return ''
    family = json.dumps(chosen['family'], ensure_ascii=False)
    stack = family + ',"Noto Sans KR","Malgun Gothic","Apple SD Gothic Neo",sans-serif'
    embedded = bundled_css(chosen['family']) if chosen['source'] == 'bundled' else ''
    metrics = '' if any(spec.get(key) for key in ('referenceCss', 'themeOverrides', 'referenceStyle')) else METRICS_CSS
    return (embedded + metrics + '\nbody[data-style],body[data-style][data-reference-style]{--heading-font:' + stack + ';--body-font:' + stack + ';font-family:' + stack + '}'
            '\nbody[data-style] :is(button,input,select,textarea,h1,h2,h3,svg text),body[data-style][data-reference-style] :is(button,input,select,textarea,h1,h2,h3,svg text){font-family:' + stack + '}')


METRICS_CSS = '''
/* Korean default hierarchy. Reference typography and explicit fonts stay separate. */
body[data-style] .section .text{font-size:16px;line-height:1.5;letter-spacing:normal}
body[data-style] .section :is(h2,h3){letter-spacing:-.03em;line-height:1.3}
body[data-style] .section .takeaway{font-size:18px;line-height:1.5}
body[data-style] :is(.section-source,.page-number,.kpi-label,.kpi-note,.report-masthead .subtitle){font-size:12px}
body[data-style] :is(button,input,select,textarea){font-size:14px;line-height:normal}
body[data-style] .section :is(code,pre,.numeric,.kpi-value){letter-spacing:normal}
'''
