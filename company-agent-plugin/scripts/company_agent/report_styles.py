"""Offline report themes and the progressively disclosed Korean design picker."""
STYLES = (
    ('minimalism', '미니멀리즘', '깔끔한 업무형', '정돈된 제목과 얇은 구분선, 상자를 줄인 지표 띠로 핵심 내용에 집중합니다.'),
    ('bento-grid', '벤토그리드', '지표 중심형', '큰 핵심 지표와 보조 카드, 넓은 근거 영역을 한 격자에 정리합니다.'),
    ('editorial', '에디토리얼', '잡지형', '큰 제목과 편집 구획, 여백의 대비로 설명과 근거를 차례로 읽습니다.'),
    ('glassmorphism', '글래스모피즘', '밝은 반투명 유리형', '은은한 빛과 유리 프레임을 쓰고, 본문과 데이터는 또렷한 표면에 놓습니다.'),
    ('neumorphism', '뉴모피즘', '부드러운 입체형', '같은 색 표면의 낮은 돌출과 눌린 지표로 차분한 깊이를 만듭니다.'),
    ('brutalism', '브루탈리즘', '굵고 강한 강조형', '크게 강조한 제목, 단색 면과 검정 프레임으로 판단을 분명하게 보여줍니다.'),
    ('gradient-mesh', '그라디언트 메시', '색이 번지는 배경형', '색이 흐르는 표지와 흰 본문을 구분해 시선의 시작과 읽는 영역을 정합니다.'),
    ('freeform', '자유양식', '비대칭 조합형', '설명과 근거의 폭을 다르게 조합하고 정렬선으로 비대칭 구성을 연결합니다.'),
    ('immersive-3d', '3D·이머시브', '입체 오브제형', '빛과 그림자가 맞는 조형 표지 아래에 지표와 본문을 넓게 배치합니다.'),
    ('retro-y2k', '레트로·Y2K', '크롬과 파스텔형', '데스크톱 창의 프레임과 크롬 표제부, 절제한 파스텔로 친숙한 개성을 줍니다.'),
)

# Reviewed public examples, adapted locally. Selection never fetches the sites.
REFERENCE_PRESETS = (
    ('reference-1', '레퍼런스 1 · 스토리형 설명', '질문에서 시작해 같은 사례의 입력, 처리 과정과 결과를 살펴봅니다. 원리 설명과 전후 비교에 맞습니다.', 'editorial'),
    ('reference-2', '레퍼런스 2 · 데이터 리포트형', '핵심 지표에서 근거 차트와 상세 표로 이동합니다. 검색, 정렬, 페이지와 CSV로 자료를 탐색합니다.', 'bento-grid'),
    ('reference-3', '레퍼런스 3 · 핵심 브리핑형', '핵심 판단과 비교 근거를 나란히 읽고 실행 조건을 확인합니다. 기존 발표형의 선택과 페이지 보기를 유지합니다.', 'minimalism'),
)


def reference_choices(spec):
    """Resolve a named reference while preserving explicit theme/format choices."""
    import re
    result = dict(spec)
    raw = spec.get('referencePreset')
    style = spec.get('style')
    if isinstance(style, int) and not isinstance(style, bool):
        style = str(style)
    from_style = False
    if raw is None and 'referencePreset' not in spec and isinstance(style, str):
        if re.fullmatch(r'(?:reference[- ]?|레퍼런스\s*)[123]', style.strip(), re.I):
            raw, from_style = style, True
        elif spec.get('designMenu') == 'initial' and style.strip().removesuffix('번').strip() in ('5', '6', '7'):
            raw, from_style = 'reference-' + str(int(style.strip().removesuffix('번').strip()) - 4), True
    if raw is None and 'referencePreset' not in spec:
        return result
    if not isinstance(raw, str):
        raise ValueError('referencePreset은 reference-1, reference-2, reference-3 중에서 선택해 주세요.')
    matched = re.fullmatch(r'(?:reference[- ]?|레퍼런스\s*)([123])', raw.strip(), re.I)
    if not matched:
        raise ValueError('referencePreset은 reference-1, reference-2, reference-3 중에서 선택해 주세요.')
    preset = REFERENCE_PRESETS[int(matched[1]) - 1]
    result['referencePreset'] = preset[0]
    if 'style' not in result or from_style:
        result['style'] = preset[3]
    return result


def apply_reference(data):
    """Fill only absent layout choices; never reorder sections or change facts."""
    preset = data.get('referencePreset')
    if not preset:
        return
    for index, row in enumerate(data['sections']):
        if 'layout' in row or 'contentOrder' in row:
            continue
        visuals = [key for key in ('chart', 'table', 'image', 'diagram') if row.get(key)]
        copy = [key for key in ('body', 'bullets') if row.get(key)]
        if preset == 'reference-1':
            row['layout'] = 'split' if index == 0 and visuals and copy else 'summary'
            if index != 0 and visuals and copy:
                row['contentOrder'] = visuals + copy
                row['contentLayout'] = 'vertical'
        elif preset == 'reference-2':
            row['layout'] = 'dashboard' if row.get('chart') or row.get('kpis') else 'table' if row.get('table') else 'summary'
        elif preset == 'reference-3':
            row['layout'] = 'split' if visuals and copy else 'table' if row.get('table') else 'cover' if index == 0 and not visuals else 'summary'


# The picker and delivered reports use the same reviewed compositions.
from .report_theme_templates import CSS


def reference_style_css(overrides):
    """Render validated, data-only observations without importing source CSS."""
    import json
    if not overrides:
        return ''
    colors = overrides.get('colors', {})
    typography = overrides.get('typography', {})
    spacing = overrides.get('spacing', {})
    table = overrides.get('table', {})
    chart = overrides.get('chart', {})
    declarations, rules = [], []
    root = 'body[data-style][data-reference-style]'
    color = lambda value: '#' + value.lstrip('#')
    px = lambda value: f'{value:g}px'
    mappings = {'bg': ('bg',), 'surface': ('paper', 'surface', 'cell', 'cover'),
                'text': ('ink',), 'muted': ('muted',), 'primary': ('accent',),
                'secondary': ('secondary',), 'border': ('line',), 'tint': ('tint', 'head-fill', 'row-fill')}
    for key, variables in mappings.items():
        if key in colors:
            declarations.extend('--' + name + ':' + color(colors[key]) for name in variables)
    series = chart.get('seriesColors', colors.get('series', []))
    # Preserve the whole observed combination. A primary-only choice does not
    # overwrite a separately identified first chart color.
    if not series:
        series = [colors[key] for key in ('primary','secondary') if key in colors]
    if series:
        # An observed palette is the complete combination, not just replacements
        # for the first two preset colors. Cycle it just like the PPT renderer.
        declarations.extend(f'--series-{index}:' + color(series[index % len(series)]) for index in range(30))
    for key, variable in (('headingFont', 'heading-font'), ('bodyFont', 'body-font')):
        if key in typography:
            declarations.append('--' + variable + ':' + json.dumps(typography[key], ensure_ascii=False) + ',"Malgun Gothic",sans-serif')
    if 'bodyFont' in typography:
        rules.append(root + '{font-family:var(--body-font)}')
        rules.append(root + ' :is(button,input,select,textarea,svg text){font-family:var(--body-font)}')
    if 'headingFont' in typography:
        rules.append(root + ' :is(h1,h2,h3){font-family:var(--heading-font)}')
    for key, selector in (('titleSize', ' .section h2'), ('bodySize', ' .text'),
                          ('captionSize', ' :is(.page-number,.section-source,figcaption,.kpi-label,.kpi-note)')):
        if key in typography:
            rules.append(root + selector + '{font-size:' + px(typography[key]) + '}')
    if 'bodySize' in typography:
        rules.append(root + '{font-size:' + px(typography['bodySize']) + '}')
    if 'outer' in spacing:
        rules.append(root + ' .section{padding:' + px(spacing['outer']) + '}')
        rules.append(root + ' :is(.report-main,.report-masthead){padding-left:' + px(spacing['outer']) + ';padding-right:' + px(spacing['outer']) + '}')
        rules.append('@media(max-width:760px){' + root + ' .section{padding:' + px(min(spacing['outer'], 24)) + '}' + root + ' :is(.report-main,.report-masthead){padding-left:' + px(min(spacing['outer'], 20)) + ';padding-right:' + px(min(spacing['outer'], 20)) + '}}')
    if 'gap' in spacing:
        rules.append(root + ' :is(.report-main,.section-content,.kpis){gap:' + px(spacing['gap']) + '}')
    if 'radius' in spacing:
        declarations.extend('--' + key + ':' + px(spacing['radius']) for key in ('radius', 'section-radius', 'cell-radius'))
        rules.append(root + ' .report-data-table{border-radius:' + px(spacing['radius']) + '}')
    # Preset accents sometimes live below body. Override the observed roles on
    # those surfaces as well so a chosen composition cannot reset the palette.
    local = ['--' + variable + ':' + color(colors[key])
             for key, variable in (('text', 'ink'), ('muted', 'muted'), ('primary', 'accent'), ('border', 'line')) if key in colors]
    if local:
        rules.append(root + ' .kpi{' + ';'.join(local) + '}')
    if 'surface' in colors:
        rules.append(root + ' :is(.kpi,.report-masthead){background:var(--paper)}')
    if 'text' in colors:
        rules.append(root + ' .report-masthead{color:var(--ink)}')
    if 'muted' in colors:
        rules.append(root + ' .report-masthead .subtitle{color:var(--muted)}')
    if 'secondary' in colors:
        rules.append(root + ' .takeaway{border-color:var(--secondary)}')
        rules.append(root + ' .kpi:nth-child(even) .kpi-value{color:var(--secondary)}')
        rules.append(root + ' .theme-art{background:linear-gradient(135deg,var(--accent),var(--secondary));box-shadow:none}')
        rules.append(root + ' .theme-art i:nth-child(even){background:var(--secondary)}')
    table_map = {'headerFill': 'table-head-fill', 'headerText': 'table-head-text',
                 'bodyFill': 'table-body-fill', 'bodyText': 'table-body-text',
                 'alternateFill': 'table-alternate-fill', 'borderColor': 'table-border'}
    for key, variable in table_map.items():
        if key in table:
            declarations.append('--' + variable + ':' + color(table[key]))
    for key, variable in (('borderWidth', 'table-border-width'), ('fontSize', 'table-font-size'), ('padding', 'table-padding')):
        if key in table:
            declarations.append('--' + variable + ':' + px(table[key]))
    if 'headerBold' in table:
        declarations.append('--table-head-weight:' + ('700' if table['headerBold'] else '400'))
    if 'align' in table:
        declarations.append('--table-align:' + table['align'])
    if 'fontSize' in chart:
        rules.append(root + ' :is(.report-chart text,.legend){font-size:' + px(chart['fontSize']) + '}')
    if 'labelSize' in chart:
        rules.append(root + ' .report-chart .chart-value{font-size:' + px(chart['labelSize']) + '}')
    if 'gridColor' in chart:
        rules.append(root + ' .gridline{stroke:' + color(chart['gridColor']) + '}')
    if chart.get('showGrid') is False:
        rules.append(root + ' .gridline{display:none}')
    if 'lineWidth' in chart:
        declarations.append('--chart-line-width:' + str(chart['lineWidth']))
    position = chart.get('legendPosition')
    if position == 'none':
        rules.append(root + ' .legend{display:none}')
    elif position == 'top':
        rules.append(root + ' .chart-frame{display:flex;flex-direction:column}' + root + ' .chart-frame figcaption{order:-2}' + root + ' .legend{order:-1;margin-bottom:12px}')
    elif position in ('left', 'right'):
        first, second = ('1', '2') if position == 'left' else ('2', '1')
        rules.append(root + ' .chart-frame{display:grid;grid-template-columns:' + ('minmax(90px,.3fr) minmax(0,1fr)' if position == 'left' else 'minmax(0,1fr) minmax(90px,.3fr)') + ';gap:14px;align-items:center}')
        rules.append(root + ' .chart-frame figcaption{grid-column:1/-1}' + root + ' .legend{grid-column:' + first + ';grid-row:2;flex-direction:column;align-items:flex-start;gap:10px}' + root + ' .report-chart{grid-column:' + second + ';grid-row:2}')
        rules.append('@media(max-width:760px){' + root + ' .chart-frame{display:block}' + root + ' .legend{flex-direction:row;justify-content:center}}')
    return '\n' + root + '{' + ';'.join(declarations) + '}\n' + '\n'.join(rules)


def choices(spec):
    from pathlib import Path
    from . import report_typography
    spec = reference_choices(spec)
    # Expose ONLY the current step. Length/view questions must not be bundled
    # with the initial design question or an unresolved additional-design menu.
    pending = {'ok': False, 'status': 'input_required', 'code': 'report_choices_required',
               'preservedChoices': {key: spec[key] for key in ('style','referencePreset','referenceStyle','themeOverrides','length','mode','htmlTemplate','templateReview', *report_typography.FIELDS) if key in spec}}
    if spec.get('designMenu') == 'template' or 'htmlTemplate' in spec:
        template = spec.get('htmlTemplate')
        if not (isinstance(template, dict) and isinstance(template.get('path'), str) and template['path']
                and isinstance(template.get('sha256'), str) and len(template['sha256']) == 64):
            pending.update(stage='template_attach', missing=['htmlTemplate'],
                           message='참고할 HTML 파일을 첨부하거나 파일 경로를 알려 주세요. 양식 확인 전에는 분량·보기 방식을 묻지 않습니다.',
                           templateCommand='business html-template --template ABSOLUTE_PATH --output NEW_PREVIEW.html --open')
            return pending
        from .html_reference import review_stage, preview_delivery
        stage = review_stage(spec)
        if stage:
            pending.update(stage=stage, missing=['templateReview' if stage == 'template_preview' else 'templateReview.confirmed'],
                           waitForUser=stage == 'template_confirm',
                           message='첨부 양식의 실제 미리보기를 준비해 주세요.' if stage == 'template_preview' else
                                   '이 느낌으로 진행 / 바꾸고 싶은 부분 입력 / 다른 양식 첨부 중 선택해 주세요.',
                           templateCommand='business html-template --template ABSOLUTE_PATH --output NEW_PREVIEW.html --open')
            if stage == 'template_confirm':
                # review_stage has already verified this generated file and hash.
                pending.update(preview_delivery(Path(spec['templateReview']['previewPath'])))
            return pending
    elif 'style' not in spec and not spec.get('referenceStyle'):
        pending.update(missing=['style'], stage='design',
                       message='디자인만 먼저 선택해 주세요. 확정 전에는 분량·보기 방식을 묻지 않습니다.')
        if spec.get('designMenu') == 'additional':
            pending.update(stage='design_detail',
                           message='선택 대기 중입니다. 번호나 이름을 입력해 주세요. 예: 4번 글래스모피즘. 미리보기를 원하면 미리보기라고 입력해 주세요.',
                           designOptions=[{'number':i,'style':key,'name':name,'description':description}
                                          for i,(key,name,_,description) in enumerate(STYLES,1)],
                           selectionInput='chat-number-or-name',
                           selectionPrompt='\n'.join(f'{i}. {name} — {label}' for i,(_,name,label,_) in enumerate(STYLES,1))
                               +'\n\n선택 대기 중입니다. 번호나 이름 하나를 입력해 주세요. 예: 4번 글래스모피즘. 미리보기라고 입력해도 됩니다.',
                           selectionInstruction='전체 번호 목록을 한 번에 보여주고 이번 응답을 끝내세요. 다음 사용자 메시지에서 선택을 받습니다. 4개 제한 질문 도구에 맞추려고 번호 묶음·다음 페이지·분할 질문을 만들지 마세요.',
                           waitForUser=True,
                           previewCommand='business html-designs --open', previewOptional=True,
                           previewInstruction='미리보기를 선택하면 로컬 화면 열기를 요청하고 링크를 안내한 뒤 같은 디자인 질문에서 선택을 기다리세요. 창 표시 여부는 단정하지 않습니다.')
        else:
            pending['initialDesignOptions']=['깔끔한 업무형(추천)', '지표 중심형', '추가 디자인(미리보기)', 'HTML 양식 직접 첨부'] + [name for _, name, _, _ in REFERENCE_PRESETS]
            pending['referenceOptions'] = [{'referencePreset': key, 'name': name, 'description': description, 'defaultStyle': style}
                                           for key, name, description, style in REFERENCE_PRESETS]
            pending['selectionPrompt'] = '\n'.join(f'{i}. {name}' for i, name in enumerate(pending['initialDesignOptions'][:4], 1)) + '\n' + '\n'.join(
                f'{i}. {name} — {description}' for i, (_, name, description, _) in enumerate(REFERENCE_PRESETS, 5))
            pending['selectionInput'] = 'chat-number-or-name'
            pending['selectionInstruction'] = '일곱 항목과 설명을 채팅에 한 번에 보여주고 번호나 이름을 받으세요. 질문 도구의 항목 제한에 맞춰 여러 질문으로 나누지 마세요.'
            pending['waitForUser'] = True
        return pending
    missing = [key for key in ('length','mode') if key not in spec]
    missing += report_typography.missing(spec)
    if not missing:
        return None
    pending.update(stage='format', missing=missing,
                   message='아직 정하지 않은 분량·보기 방식·글꼴만 선택해 주세요.')
    if 'length' in missing:
        pending['lengthOptions']=['핵심','보통','상세']
    if 'mode' in missing:
        pending['viewOptions']=['스크롤','페이지 넘김','둘 다']
    if 'fontChoice' in missing:
        pending['fontOptions'] = [{'value': key, 'name': name, 'description': description}
                                  for key, name, description in report_typography.OPTIONS]
        pending['fontInstruction'] = '다섯 항목을 채팅에 한 번에 보여 주세요. 번호·이름·직접 입력을 받으며, 이미 정한 글꼴은 다시 묻지 않습니다.'
    if 'fontName' in missing:
        pending['fontInstruction'] = '사용할 글꼴 이름만 알려 주세요. 파일·설치·인터넷 연결은 별도 요청 없이 추가하지 않습니다.'
    return pending


PICKER_JS = r'''"use strict";
(()=>{
  const buttons=[...document.querySelectorAll('[data-choice]')];
  const length=document.getElementById('length-choice'), mode=document.getElementById('mode-choice');
  const font=document.getElementById('font-choice'), custom=document.getElementById('font-name');
  const result=document.getElementById('choice-result'), status=document.getElementById('copy-status');
  function fitPreviews(){
    document.querySelectorAll('.mini-window').forEach(box=>{
      if(!box.clientWidth)return;
      const scale=box.clientWidth/960;
      const preview=box.querySelector('.style-preview');
      preview.style.transform='scale('+scale+')';
      box.style.height=Math.ceil(preview.scrollHeight*scale)+'px';
    });
  }
  window.addEventListener('resize',fitPreviews);
  let choice='minimalism', label='미니멀리즘(깔끔한 업무형)';
  function update(){
    buttons.forEach(button=>{
      const selected=button.dataset.choice===choice;
      button.setAttribute('aria-pressed',String(selected));
      const card=button.closest('.design-card, .reference-card, .template-callout');
      if(card)card.dataset.selected=String(selected);
    });
    document.getElementById('selected-design').textContent=label.split('(')[0];
    const kind=document.getElementById('selected-kind');
    if(kind)kind.textContent=choice==='template'?'내 양식으로 시작':choice.startsWith('reference-')?'내용 구성 선택':'디자인 선택';
    const parts=['디자인: '+label];
    if(length.value!=='keep')parts.push('분량: '+length.options[length.selectedIndex].text);
    if(mode.value!=='keep')parts.push('보기: '+mode.options[mode.selectedIndex].text);
    custom.hidden=font.value!=='custom';
    if(font.value!=='keep')parts.push('글꼴: '+(font.value==='custom'?(custom.value.trim()||'직접 입력할 이름을 물어봐줘'):font.options[font.selectedIndex].text));
    result.value='HTML 보고서를 만들어줘. '+parts.join(' / ')+'. 따로 지정하지 않은 분량과 보기 방식은 이미 정한 조건을 유지하고, 정하지 않은 항목만 물어봐줘. 원자료와 요청 내용은 앞서 전달한 것을 사용해줘.';
    if(choice.startsWith('reference-'))result.value='HTML 보고서를 '+label+' 구성으로 만들어줘. '+(parts.length>1?parts.slice(1).join(' / ')+'. ':'')+'이미 정한 색상 스타일·글꼴·분량·보기 방식은 유지하고, 미정인 항목만 물어봐줘. 스킬에 있는 레퍼런스 구성으로 원자료를 정리해줘.';
    if(choice==='template')result.value='HTML 보고서에 내가 첨부할 HTML 양식을 참고해줘. '+(parts.length>1?parts.slice(1).join(' / ')+'. ':'')+'먼저 양식 파일을 받고 미리보기를 보여줘. 따로 지정하지 않은 분량과 보기 방식은 이미 정한 조건을 유지하고, 정하지 않은 항목은 양식 확인 후에만 물어봐줘.';
    status.textContent='아직 Claude에 전달되지 않았습니다. 복사한 내용을 채팅에 붙여 넣어 주세요.';
    // 선택 문장과 보이는 양식에 같은 글꼴을 사용한다. 설치/네트워크 호출은 없다.
    const families={'noto-sans-kr':'Noto Sans KR','pretendard':'Pretendard','nanum-square-neo':'NanumSquareNeo'};
    const defaultFamily=style=>['bento-grid','glassmorphism','neumorphism'].includes(style)?'Pretendard':'Noto Sans KR';
    document.querySelectorAll('.style-preview').forEach(preview=>{
      const family=font.value==='custom'?(custom.value.trim()||defaultFamily(preview.dataset.style)):(families[font.value]||defaultFamily(preview.dataset.style));
      // JSON quoting makes custom names a single CSS family, never a CSS fragment.
      preview.style.setProperty('--preview-font',JSON.stringify(family)+',"Malgun Gothic",sans-serif');
      preview.dataset.fontPreview=family;
    });
    const fontNote=document.getElementById('font-preview-status');
    if(fontNote)fontNote.textContent=['keep','auto'].includes(font.value)?(font.value==='keep'?'예제에는 Noto Sans KR과 Pretendard가 포함되어 있습니다. 기존에 정한 글꼴은 유지합니다.':'예제는 양식별 기본 글꼴로 표시합니다. 실제 자료에 어울리는 글꼴은 제작할 때 추천합니다.'):
      (font.value==='custom'||font.value==='nanum-square-neo'?'미리보기에 적용했습니다. PC에 없는 글꼴은 대체 글꼴로 표시됩니다.':'미리보기에 적용했습니다. 포함된 글꼴 파일을 사용합니다.');
    fitPreviews();
  }
  buttons.forEach(button=>button.addEventListener('click',()=>{choice=button.dataset.choice;label=button.dataset.label;update();}));
  length.addEventListener('change',update);mode.addEventListener('change',update);
  font.addEventListener('change',update);custom.addEventListener('input',update);
  document.getElementById('copy-choice').addEventListener('click',async()=>{
    try { if(!navigator.clipboard)throw new Error('unavailable');await navigator.clipboard.writeText(result.value);status.textContent='복사했습니다. Claude 채팅에 붙여 넣으면 선택을 전달할 수 있습니다.'; }
    catch {
      const details=document.getElementById('prompt-details');
      if(details)details.open=true;
      result.focus();result.select();
      status.textContent='자동 복사가 제한되었습니다. 선택된 문장을 Ctrl+C로 복사해 채팅에 붙여 넣어 주세요.';
    }
  });
  update();fitPreviews();
  if(document.fonts&&document.fonts.ready)document.fonts.ready.then(fitPreviews);
})();'''


def picker_html(example_base='examples', font_base='fonts'):
    from .report_typography import OPTIONS
    from . import report_design
    from .business_artifacts import _CSS
    from html import escape
    import base64
    import hashlib
    from .report_gallery import style_preview_markup
    from .report_theme_sources import SOURCES
    cards=[]
    for number,(key,name,label,description) in enumerate(STYLES,1):
        specific = style_preview_markup(key)
        preview = specific.replace('id="', f'id="{key}-').replace('aria-labelledby="', f'aria-labelledby="{key}-')
        link = escape(example_base.rstrip('/') + '/style-' + key + '.html', quote=True)
        reference = SOURCES[key]
        cards.append(f'<article class="design-card" id="design-{key}"><div class="mini-window" aria-hidden="true" inert><div class="style-preview" data-style="{key}" data-view="scroll" data-length="detailed">{preview}</div></div>'
            f'<div class="design-card-copy"><p class="design-index">DESIGN {number:02d} / {escape(label)}</p><h3>{name}</h3><p>{escape(description)}</p>'
            f'<p class="design-use">어울리는 자료: {escape(reference["use"])}</p>'
            f'<details class="design-source"><summary>참고한 실제 사례와 적용점</summary><p><a href="{escape(reference["url"], quote=True)}" target="_blank" rel="noopener noreferrer">{escape(reference["name"])} ↗</a></p><p>{escape(reference["applied"])}</p><p>구성과 표현 원칙을 참고한 자체 양식입니다. 사이트의 코드와 이미지를 복제하지 않았습니다.</p></details>'
            f'<div class="design-actions"><a class="example-link" href="{link}" target="_blank" rel="noopener">완성 예제 열기 ↗</a><button type="button" data-choice="{key}" data-label="{name}({label})" aria-pressed="false">{name} 선택</button></div></div></article>')
    from .report_gallery import preview_markup
    reference_cards = []
    for key, name, description, style in REFERENCE_PRESETS:
        preview = preview_markup(key).replace('id="', f'id="{key}-').replace('aria-labelledby="', f'aria-labelledby="{key}-')
        link = escape(example_base.rstrip('/') + '/' + key + '.html', quote=True)
        reference_cards.append(f'<article class="reference-card"><div class="mini-window" aria-hidden="true" inert><div class="style-preview" data-style="{style}">{preview}</div></div><div class="reference-card-copy"><h3>{escape(name)}</h3><p>{escape(description)}</p>'
            f'<a class="example-link" href="{link}" target="_blank" rel="noopener">완성 예제 열기 ↗</a>'
            f'<button type="button" data-choice="{key}" data-label="{escape(name)}" aria-pressed="false">{escape(name.split(" · ")[0])} 선택</button></div></article>')
    reference_cards = ''.join(reference_cards)
    from .report_typography import bundled_css
    font_faces = bundled_css('Noto Sans KR', font_base) + bundled_css('Pretendard', font_base)
    digest=base64.b64encode(hashlib.sha256(PICKER_JS.encode()).digest()).decode()
    from .report_picker_ui import CSS as gallery_css
    font_options = ''.join('<option value="'+key+'">'+escape(name)+'</option>' for key,name,_ in OPTIONS)
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            +f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; font-src \'self\' file: data:; style-src \'unsafe-inline\'; script-src \'sha256-{digest}\'; base-uri \'none\'; form-action \'none\'"><title>보고서 디자인 모음</title><style>'+font_faces+_CSS+report_design.CSS+CSS+gallery_css+'</style></head>'
            +'<body class="picker"><header class="picker-header"><a class="picker-brand" href="#top"><span class="picker-brand-mark" aria-hidden="true">R</span>보고서 디자인</a><nav class="picker-nav" aria-label="디자인 모음 탐색"><a href="#additional-designs">디자인</a><a href="#reference-options">내용 구성</a><a href="#own-template">내 양식</a></nav></header>'
            +'<main class="picker-wrap" id="top"><div class="picker-hero"><div><p class="picker-kicker">REPORT DESIGN COLLECTION</p><h1>자료에 어울리는 디자인을<br>직접 보고 고르세요.</h1><p class="intro">같은 자료, 서로 다른 인상. 표지부터 본문과 데이터 표까지<br>완성 예제를 살펴보고 원하는 스타일을 골라 보세요.</p><ol class="flow-steps"><li><b>01</b> 예제 비교</li><li><b>02</b> 디자인 선택</li><li><b>03</b> 채팅에 전달</li></ol></div><div class="hero-meta" aria-label="포함된 양식"><span><strong>10</strong>디자인</span><span><strong>3</strong>내용 구성</span><span><strong>13</strong>완성 예제</span></div></div>'
            +'<div class="picker-workspace"><aside class="selection-panel" aria-labelledby="selected-design"><p class="selection-kicker">나의 선택</p><div class="selection-heading"><p class="selected-style-marker" id="selected-kind">디자인 선택</p><h2 id="selected-design">미니멀리즘</h2><p class="selection-hint">카드에서 디자인을 고른 뒤<br>선택 내용을 채팅에 전달하세요.</p></div>'
            +'<div class="choice-fields"><label for="font-choice">글꼴<select id="font-choice"><option value="keep" selected>기존 선택 유지</option>'+font_options+'</select></label><input id="font-name" aria-label="직접 입력할 글꼴 이름" placeholder="예: 맑은 고딕" maxlength="80" hidden></div>'
            +'<div class="choice-fields"><label for="length-choice">분량<select id="length-choice"><option value="keep" selected>기존 선택 유지</option><option value="short">핵심</option><option value="standard">보통</option><option value="detailed">상세</option></select></label><label for="mode-choice">보기 방식<select id="mode-choice"><option value="keep" selected>기존 선택 유지</option><option value="scroll">스크롤</option><option value="slides">페이지 넘김</option><option value="both">둘 다</option></select></label></div>'
            +'<p class="note" id="font-preview-status">예제에는 Noto Sans KR과 Pretendard가 포함되어 있습니다.</p><button type="button" id="copy-choice">선택 내용 복사</button><p id="copy-status" role="status" aria-live="polite"></p>'
            +'<details class="prompt-details" id="prompt-details"><summary>전달할 문장 확인</summary><label for="choice-result">Claude 채팅에 붙여 넣을 문장</label><textarea id="choice-result" readonly></textarea><p class="note">글꼴을 바꾸면 카드의 미리보기에 반영됩니다. 완성 예제는 기본 글꼴로 열립니다.</p></details><noscript>디자인 이름과 원하는 조건을 직접 Claude 채팅에 입력해 주세요.</noscript></aside>'
            +'<div class="picker-gallery"><section id="additional-designs" aria-labelledby="design-heading"><div class="section-heading"><div><p class="section-kicker">01 / VISUAL STYLES</p><h2 id="design-heading">어떤 인상으로 전달할까요?</h2><p>모든 예제는 같은 가상 업무 자료로 만들었습니다. 전체 내용과 표 기능은 완성 예제에서 확인하세요.</p></div><span class="section-count">10</span></div><div class="design-grid">'+''.join(cards)+'</div></section>'
            +'<section id="reference-options" aria-labelledby="reference-heading"><div class="section-heading"><div><p class="section-kicker">02 / CONTENT STRUCTURES</p><h2 id="reference-heading">내용을 엮는 세 가지 방식</h2><p>전달할 내용에 맞춰 구성을 고르세요. 이미 정한 색상과 글꼴은 유지합니다.</p></div><span class="section-count">3</span></div><div class="reference-grid">'+reference_cards+'</div></section>'
            +'<section id="own-template" aria-labelledby="template-heading"><div class="template-callout"><span class="template-icon" aria-hidden="true">&lt;/&gt;</span><div class="template-copy"><h3 id="template-heading">평소 쓰던 양식이 있나요?</h3><p>선택 내용을 채팅에 붙여 넣고 HTML 파일을 첨부하세요.<br>양식의 색감, 글꼴과 구성을 새 자료에 반영합니다.</p></div><button type="button" data-choice="template" data-label="HTML 양식 직접 첨부" aria-pressed="false">내 HTML 양식 사용</button></div></section></div></div>'
            +'<footer class="picker-footer"><p>업무 자료와 개인 설정을 읽거나 바꾸지 않습니다. 선택 내용은 직접 전달할 때만 사용됩니다.</p><p>인터넷 연결 없이 사용 가능</p></footer></main><script>'+PICKER_JS+'</script></body></html>')
