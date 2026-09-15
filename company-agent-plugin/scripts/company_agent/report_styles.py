"""Offline report themes and the progressively disclosed Korean design picker."""
STYLES = (
    ('minimalism', '미니멀리즘', '깔끔한 업무형', '여백과 얇은 구분선으로 내용을 또렷하게 보여줍니다.'),
    ('bento-grid', '벤토그리드', '지표 중심형', '관련 지표와 내용을 크기가 다른 구획으로 묶어 보여줍니다.'),
    ('editorial', '에디토리얼', '잡지형', '큰 제목과 차분한 지면 구성으로 설명의 흐름을 강조합니다.'),
    ('glassmorphism', '글래스모피즘', '투명한 흰색 유리형', '흰색·연회색 배경 위에 투명한 흰색 유리판, 은은한 흐림과 밝은 테두리를 사용합니다.'),
    ('neumorphism', '뉴모피즘', '부드러운 입체형', '배경과 같은 색의 표면에 양방향 그림자를 주어 솟은 판과 눌린 지표를 만듭니다.'),
    ('brutalism', '브루탈리즘', '굵고 강한 강조형', '굵은 테두리와 선명한 대비로 핵심을 강하게 강조합니다.'),
    ('gradient-mesh', '그라디언트 메시', '색이 번지는 배경형', '여러 색이 자연스럽게 섞이는 배경에 내용을 배치합니다.'),
    ('freeform', '자유양식', '비대칭 조합형', '설명과 시각 자료의 비중을 다르게 배치합니다. 임의 웹페이지 복제는 아닙니다.'),
)

# Scoped selectors are shared by full reports and miniature previews. No external
# fonts, scripts, image assets or user-provided CSS are evaluated.
CSS = r'''
:is(body,.style-preview)[data-style]{--heading-font:'Malgun Gothic','Segoe UI',sans-serif;--surface:var(--paper);--cell:var(--paper);--cover:var(--paper);--panel-shadow:none;--cell-shadow:none;--chart-shadow:var(--cell-shadow);--stroke:1px;--section-radius:16px;--cell-radius:12px;--head-fill:var(--tint);--row-fill:var(--tint);--series-2:#4664a5;--series-3:#92529b;--series-4:#977018;--series-5:#53656f;color:var(--ink);background:var(--bg)}
:is(body,.style-preview)[data-style=minimalism]{--bg:#f5f7fa;--paper:#fff;--ink:#19314a;--muted:#526579;--accent:#155f84;--line:#d9e2eb;--tint:#edf3f8;--cover:#fff;--section-radius:4px;--cell-radius:4px;--series-0:#155f84;--series-1:#b95c28}
:is(body,.style-preview)[data-style=bento-grid]{--bg:#edf1e7;--paper:#fff;--ink:#253527;--muted:#50634c;--accent:#3d6839;--line:#d4dfcb;--tint:#e7efdd;--cover:linear-gradient(125deg,#f8fbeF,#deebd0);--section-radius:26px;--cell-radius:18px;--cell-shadow:0 5px 14px #2c51230a;--series-0:#3d6839;--series-1:#a55e21}
:is(body,.style-preview)[data-style=editorial]{--bg:#f4efe6;--paper:#faf7f0;--ink:#302a25;--muted:#716151;--accent:#94482f;--line:#cabeb0;--tint:#eee5d8;--heading-font:Georgia,'Batang',serif;--section-radius:0px;--cell-radius:0px;--series-0:#94482f;--series-1:#416276}
:is(body,.style-preview)[data-style=glassmorphism]{--bg:radial-gradient(ellipse at 100% 18%,transparent 0 29%,#bcbcbc 29.3%,#e4e4e4 43%,transparent 43.3%),radial-gradient(ellipse at 0% 95%,transparent 0 26%,#ffffffcc 26.3%,#c4c4c4 40%,transparent 40.3%),linear-gradient(125deg,#f8f8f8,#dedede 48%,#eeeeee);--paper:#fafafa;--surface:#ffffff2e;--cell:#ffffff24;--ink:#252525;--muted:#444444;--accent:#454545;--line:#ffffffbd;--tint:#ffffff30;--cover:linear-gradient(120deg,#ffffff57,#ffffff1a);--panel-shadow:0 18px 44px #00000010,inset 0 1px 0 #fffffff0,inset 0 -1px 0 #00000012;--cell-shadow:0 6px 18px #00000007,inset 0 1px 0 #ffffffcc;--section-radius:28px;--cell-radius:20px;--series-0:#454545;--series-1:#777777;--series-2:#999999;--series-3:#595959;--series-4:#b0b0b0;--series-5:#303030}
:is(body,.style-preview)[data-style=neumorphism]{--bg:#e5eaf0;--paper:#e5eaf0;--ink:#23394e;--muted:#445a6f;--accent:#30557b;--line:#b4c1ce;--tint:#d8e1eb;--panel-shadow:14px 14px 32px #bdc6d0,-14px -14px 32px #fff;--cell-shadow:inset 6px 6px 12px #bdc7d2,inset -6px -6px 12px #fff;--chart-shadow:7px 7px 16px #bdc6d0,-7px -7px 16px #fff;--stroke:0px;--section-radius:32px;--cell-radius:20px;--series-0:#30557b;--series-1:#865224}
:is(body,.style-preview)[data-style=brutalism]{--bg:#f0ef63;--paper:#fffef3;--ink:#171717;--muted:#484837;--accent:#292999;--line:#171717;--tint:#eeeeac;--panel-shadow:8px 8px 0 #171717;--cell-shadow:4px 4px 0 #171717;--stroke:3px;--section-radius:0px;--cell-radius:0px;--series-0:#292999;--series-1:#bc3e28}
:is(body,.style-preview)[data-style=gradient-mesh]{--bg:radial-gradient(at 12% 10%,#c9eafa,transparent 55%),radial-gradient(at 88% 35%,#f3cde7,transparent 60%),#e9e3fa;--paper:#fff9fff0;--ink:#382747;--muted:#705379;--accent:#794391;--line:#ddcce6;--tint:#f0e3f4;--cover:radial-gradient(at 90% 0%,#d9f2fc,transparent 65%),radial-gradient(at 15% 80%,#f7d9ed,transparent 60%),#faf1ff;--panel-shadow:0 20px 40px #60307912;--section-radius:30px;--cell-radius:20px;--series-0:#794391;--series-1:#167d8a}
:is(body,.style-preview)[data-style=freeform]{--bg:#eaf3f1;--paper:#fff;--ink:#173c3b;--muted:#446965;--accent:#16675c;--line:#bdd8d0;--tint:#e5f1ed;--cover:linear-gradient(110deg,#fff 60%,#d9eee8 60%);--section-radius:6px;--cell-radius:4px;--series-0:#16675c;--series-1:#b16331}
:is(body,.style-preview)[data-style] .section{background:var(--surface);border:var(--stroke) solid var(--line);border-radius:var(--section-radius);box-shadow:var(--panel-shadow)}
:is(body,.style-preview)[data-style] .layout-cover{background:var(--cover)!important}
:is(body,.style-preview)[data-style] h2{font-family:var(--heading-font)}
:is(body,.style-preview)[data-style] :is(.kpi,.chart-frame){background:var(--cell);border:var(--stroke) solid var(--line);border-radius:var(--cell-radius);box-shadow:var(--cell-shadow)}
:is(body,.style-preview)[data-style] .chart-frame{box-shadow:var(--chart-shadow)}
:is(body,.style-preview)[data-style] .section{margin-bottom:0}
:is(body,.style-preview)[data-style] .report-main{display:grid;gap:32px}
:is(body,.style-preview)[data-style] :is(.section-content,.copy-block,.visual-block){min-width:0}
:is(body,.style-preview)[data-style] .section h2{word-break:keep-all;overflow-wrap:anywhere;letter-spacing:-.035em;line-height:1.25}
:is(body,.style-preview)[data-style] .takeaway{max-width:65ch}
:is(body,.style-preview)[data-style] th{background:var(--head-fill);color:var(--ink)}
:is(body,.style-preview)[data-style] tbody tr:nth-child(even){background:var(--row-fill)}
:is(body,.style-preview)[data-style=glassmorphism]{background-size:100% 100vh;background-attachment:fixed}
.style-preview[data-style=glassmorphism]{background-size:100% 100%;background-attachment:scroll}
:is(body,.style-preview)[data-style=glassmorphism] .section{-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px)}
:is(body,.style-preview)[data-style=glassmorphism] .report-masthead{background:#ffffff57;border:1px solid #ffffffbd;-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px)}
:is(body,.style-preview)[data-style=neumorphism] .report-main{gap:42px;padding-top:22px;padding-bottom:42px}
:is(body,.style-preview)[data-style=neumorphism] .report-masthead{background:var(--paper);border-bottom:1px solid var(--line);backdrop-filter:none}
:is(body,.style-preview)[data-style=neumorphism] .kpis{gap:26px}
:is(body,.style-preview)[data-style=neumorphism] .kpi{padding:26px}
:is(body,.style-preview)[data-style=neumorphism] .chart-frame{padding:26px;margin-top:28px}
:is(body,.style-preview)[data-style=minimalism] .section{border-width:0 0 1px;padding:44px 48px}
:is(body,.style-preview)[data-style=minimalism] .kpi{border-width:0 0 0 2px;border-radius:0}
:is(body,.style-preview)[data-style=editorial] .section{border-width:2px 0 0;padding-left:12px;padding-right:12px}
:is(body,.style-preview)[data-style=editorial] .kpi{border-width:0 0 0 1px;border-radius:0}
:is(body,.style-preview)[data-style=editorial] .layout-cover h2{font-size:clamp(36px,5.5vw,68px)}
:is(body,.style-preview)[data-style=editorial] .section-content{border-top:1px solid var(--line);padding-top:22px}
:is(body,.style-preview)[data-style=editorial] .section h2{font-size:clamp(30px,3.8vw,48px)}
:is(body,.style-preview)[data-style=freeform] .section{border-left:6px solid var(--accent)}
:is(body,.style-preview)[data-style=freeform] .layout-split .section-content{grid-template-columns:1.2fr 1fr}
:is(body,.style-preview)[data-style=freeform][data-view=scroll] .section:nth-child(even){margin-left:36px}
:is(body,.style-preview)[data-style=bento-grid][data-view=scroll] .report-main{grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}
:is(body,.style-preview)[data-style=bento-grid] :is(.layout-cover,.layout-table,.layout-split,.layout-dashboard){grid-column:1/-1}
:is(body,.style-preview)[data-style=bento-grid] .kpis{grid-template-columns:repeat(3,minmax(0,1fr))}
:is(body,.style-preview)[data-style=bento-grid] .kpi:first-child{grid-column:span 2}
:is(body,.style-preview)[data-style=bento-grid] .kpi:first-child{background:var(--tint)}
:is(body,.style-preview)[data-style=brutalism] h2{letter-spacing:-1.6px;font-weight:900}
:is(body,.style-preview)[data-style=brutalism] .takeaway{font-weight:800;border-left:0;border-bottom:3px solid var(--ink);padding:8px 0 12px}
:is(body,.style-preview)[data-style=gradient-mesh]{background-size:100% 100vh;background-attachment:fixed}
.style-preview[data-style=gradient-mesh]{background-size:100% 100%;background-attachment:scroll}
@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){:is(body,.style-preview)[data-style=glassmorphism] :is(.section,.layout-cover,.kpi,.chart-frame){background:#fafafa!important}}
@media(prefers-reduced-transparency:reduce){:is(body,.style-preview)[data-style=glassmorphism] :is(.section,.layout-cover,.kpi,.chart-frame,.report-masthead){background:#fafafa!important;backdrop-filter:none;-webkit-backdrop-filter:none}}
@media(max-width:760px){body[data-style] .section{padding:26px 22px}body[data-style] .report-main{grid-template-columns:minmax(0,1fr)!important;padding:12px 20px;gap:28px}body[data-style] .layout-split .section-content{display:block}body[data-style=freeform][data-view=scroll] .section:nth-child(even){margin-left:0}body[data-style=bento-grid] .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}body[data-style=bento-grid] .kpi:first-child{grid-column:auto}body[data-style=neumorphism] .kpi{padding:18px}body[data-style=glassmorphism]{background-attachment:scroll}}
@media(max-width:760px){body[data-style] .kpi-unit{display:block;margin:5px 0 0;white-space:nowrap}}
@media print{:is(body,.style-preview)[data-style]{background:white!important;--ink:#172132;--muted:#344154}body[data-style] .report-main{display:block!important}:is(body,.style-preview)[data-style] :is(.section,.layout-cover,.kpi,.chart-frame){box-shadow:none!important;backdrop-filter:none!important;-webkit-backdrop-filter:none!important;background:white!important;border-color:#aaa}body[data-style] .section{margin:0 0 24px!important}body[data-style=freeform][data-view=scroll] .section:nth-child(even){margin-left:0}}
'''


def choices(spec):
    # Expose ONLY the current step. Length/view questions must not be bundled
    # with the initial design question or an unresolved additional-design menu.
    pending = {'ok': False, 'status': 'input_required', 'code': 'report_choices_required',
               'preservedChoices': {key: spec[key] for key in ('style','length','mode','htmlTemplate') if key in spec}}
    if spec.get('designMenu') == 'template' or 'htmlTemplate' in spec:
        template = spec.get('htmlTemplate')
        if not (isinstance(template, dict) and isinstance(template.get('path'), str) and template['path']
                and isinstance(template.get('sha256'), str) and len(template['sha256']) == 64):
            pending.update(stage='template_attach', missing=['htmlTemplate'],
                           message='참고할 HTML 파일을 첨부하거나 파일 경로를 알려 주세요. 양식 확인 전에는 분량·보기 방식을 묻지 않습니다.',
                           templateCommand='business html-template --template ABSOLUTE_PATH --output NEW_PREVIEW.html --open')
            return pending
    elif 'style' not in spec:
        pending.update(missing=['style'], stage='design',
                       message='디자인만 먼저 선택해 주세요. 확정 전에는 분량·보기 방식을 묻지 않습니다.')
        if spec.get('designMenu') == 'additional':
            pending.update(stage='design_detail',
                           message='선택 대기 중입니다. 번호나 이름을 입력해 주세요. 예: 4번 글래스모피즘. 미리보기를 원하면 미리보기라고 입력해 주세요.',
                           designOptions=[{'style':key,'name':name,'description':description} for key,name,_,description in STYLES],
                           selectionQuestion={'header':'디자인 선택','question':'어떤 디자인을 선택할까요? 번호나 이름을 바로 입력해도 됩니다.',
                               'multiSelect':False,'options':[
                                   {'label':'1~4번 디자인','description':'미니멀리즘 · 벤토그리드 · 에디토리얼 · 글래스모피즘'},
                                   {'label':'5~8번 디자인','description':'뉴모피즘 · 브루탈리즘 · 그라디언트 메시 · 자유양식'},
                                   {'label':'미리보기','description':'예시 화면을 확인한 뒤 디자인을 선택합니다.'}]},
                           designQuestions=[{'header':'디자인 선택','question':'사용할 디자인을 선택해 주세요.',
                               'multiSelect':False,'options':[
                                   {'label':f'{index+1}. {STYLES[index][1]}','description':STYLES[index][3]}
                                   for index in range(start,start+4)]} for start in (0,4)],
                           waitForUser=True,
                           previewCommand='business html-designs --open', previewOptional=True,
                           previewInstruction='미리보기를 선택하면 로컬 화면 열기를 요청하고 링크를 안내한 뒤 같은 디자인 질문에서 선택을 기다리세요. 창 표시 여부는 단정하지 않습니다.')
        else:
            pending['initialDesignOptions']=['깔끔한 업무형(추천)', '지표 중심형', '추가 디자인(미리보기)', 'HTML 양식 직접 첨부']
        return pending
    missing = [key for key in ('length','mode') if key not in spec]
    if not missing:
        return None
    pending.update(stage='format', missing=missing,
                   message='디자인이 확정되었습니다. 아직 정하지 않은 분량·보기 방식만 선택해 주세요.')
    if 'length' in missing:
        pending['lengthOptions']=['핵심','보통','상세']
    if 'mode' in missing:
        pending['viewOptions']=['스크롤','페이지 넘김','둘 다']
    return pending


PICKER_JS = r'''"use strict";
(()=>{
  const buttons=[...document.querySelectorAll('[data-choice]')];
  const length=document.getElementById('length-choice'), mode=document.getElementById('mode-choice');
  const result=document.getElementById('choice-result'), status=document.getElementById('copy-status');
  if(location.hash==='#additional-designs')document.getElementById('additional-designs').open=true;
  let choice='minimalism', label='미니멀리즘(깔끔한 업무형)';
  function update(){
    buttons.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.choice===choice)));
    document.getElementById('selected-design').textContent='선택한 디자인: '+label;
    const parts=['디자인: '+label];
    if(length.value!=='keep')parts.push('분량: '+length.options[length.selectedIndex].text);
    if(mode.value!=='keep')parts.push('보기: '+mode.options[mode.selectedIndex].text);
    result.value='HTML 보고서를 만들어줘. '+parts.join(' / ')+'. 따로 지정하지 않은 분량과 보기 방식은 이미 정한 조건을 유지하고, 정하지 않은 항목만 물어봐줘. 원자료와 요청 내용은 앞서 전달한 것을 사용해줘.';
    if(choice==='template')result.value='HTML 보고서에 내가 첨부할 HTML 양식을 참고해줘. 먼저 양식 파일을 받고 미리보기를 보여줘. 분량과 보기 방식은 이미 정한 조건을 유지하고, 정하지 않은 항목은 양식 확인 후에만 물어봐줘.';
    status.textContent='이 선택은 아직 Claude에 전달되지 않았습니다. 아래 문장을 복사해 채팅에 붙여 넣어 주세요.';
  }
  buttons.forEach(button=>button.addEventListener('click',()=>{choice=button.dataset.choice;label=button.dataset.label;update();}));
  length.addEventListener('change',update);mode.addEventListener('change',update);
  document.getElementById('copy-choice').addEventListener('click',async()=>{
    try { if(!navigator.clipboard)throw new Error('unavailable');await navigator.clipboard.writeText(result.value);status.textContent='복사했습니다. Claude 채팅에 붙여 넣으면 선택을 전달할 수 있습니다.'; }
    catch { result.focus();result.select();status.textContent='자동 복사가 제한되었습니다. 선택된 문장을 Ctrl+C로 복사해 채팅에 붙여 넣어 주세요.'; }
  });
  update();
})();'''


def picker_html():
    from . import report_design
    from .business_artifacts import _CSS, _html_table
    from html import escape
    import base64
    import hashlib
    sample = {'title':'디자인 예시', 'subtitle':'실습용', 'mode':'scroll', 'length':'standard', 'style':'minimalism',
              'sections':[{'title':'이번 달 성과를 한눈에', 'layout':'dashboard', 'eyebrow':'예시용 가상 자료',
                           'takeaway':'핵심 지표와 변화 흐름을 구분해서 읽습니다.', 'body':'', 'bullets':[],
                           'kpis':[{'label':'누적 실적','display':'530','unit':'백만원','note':'예시 수치'},
                                   {'label':'달성률','display':'117.78','unit':'%','note':'예시 수치'}],
                           'chart':{'type':'column','title':'목표와 실적 · 예시', 'categories':['6월','7월','8월'],
                                    'series':[{'name':'실적','values':[145,175,210]}]}}]}
    rendered = report_design.render(sample, '', '', _html_table)
    sample_main = rendered.split('<main class="report-main">',1)[1].split('</main>',1)[0]
    cards=[]
    for key,name,label,description in STYLES:
        preview = sample_main.replace('id="', f'id="{key}-').replace('aria-labelledby="', f'aria-labelledby="{key}-')
        cards.append(f'<article class="design-card"><div class="mini-window" aria-hidden="true" inert><div class="style-preview" data-style="{key}">{preview}</div></div><h3>{name}</h3><p>{escape(description)}</p><button type="button" data-choice="{key}" data-label="{name}({label})" aria-pressed="false">{name} 선택</button></article>')
    digest=base64.b64encode(hashlib.sha256(PICKER_JS.encode()).digest()).decode()
    gallery_css='''
body.picker{background:#f4f6fa;color:#20364c;font:16px/1.65 'Malgun Gothic','Segoe UI',sans-serif;margin:0}.picker-wrap{max-width:1180px;margin:auto;padding:36px 24px}.picker h1{font-size:32px;margin:0 0 12px}.intro{max-width:70ch;color:#536477}.quick-choices{display:flex;flex-wrap:wrap;gap:12px;margin:20px 0}.picker button,.picker select{font:inherit;border:1px solid #bdccdc;background:white;color:#20364c;border-radius:8px;padding:10px 16px;cursor:pointer}.picker button[aria-pressed=true]{background:#193e67;color:white;border-color:#193e67}.picker button:focus-visible,.picker summary:focus-visible,.picker select:focus-visible,.picker textarea:focus-visible{outline:3px solid #d38321;outline-offset:3px}.design-options{border:1px solid #d2dce7;background:#fff;border-radius:12px;padding:16px;margin:16px 0}.design-options>summary{font-size:18px;font-weight:700;cursor:pointer}.design-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;margin-top:18px}.design-card{border:1px solid #d2dce7;border-radius:10px;padding:12px;min-width:0;overflow:hidden;background:#fff}.design-card h3{font-size:19px;margin:14px 0 5px}.design-card p{font-size:14px;min-height:48px;margin:6px 0 14px}.mini-window{height:218px;overflow:hidden;background:#eef2f7;border:1px solid #d6dfe8;border-radius:6px;pointer-events:none}.style-preview{width:960px;min-height:775px;padding:34px;transform:scale(.28);transform-origin:top left;box-sizing:border-box}.style-preview .section{margin:0;padding:30px!important}.style-preview .kpis{grid-template-columns:1fr 1fr}.style-preview .chart-frame{margin:8px 0;padding:16px}.style-preview h2{font-size:36px!important}.style-preview .report-chart{min-width:0}.style-preview .chart-values{display:none}.selection-panel{background:white;border:1px solid #d2dce7;border-radius:12px;padding:22px;margin-top:24px}.selection-panel h2{font-size:20px}.choice-fields{display:flex;flex-wrap:wrap;gap:20px;margin:16px 0}.choice-fields label{display:flex;gap:10px;align-items:center}.picker textarea{display:block;width:100%;min-height:115px;box-sizing:border-box;font:15px/1.7 'Malgun Gothic',sans-serif;padding:12px;border:1px solid #bdccdc;border-radius:8px;margin:16px 0}.note{font-size:14px;color:#536477}.picker footer{padding:20px 0;font-size:13px;color:#536477}@media(max-width:620px){.picker-wrap{padding:24px 16px}.picker h1{font-size:25px}.design-grid{grid-template-columns:1fr}}@media print{.picker button{display:none}.mini-window{break-inside:avoid}}
'''
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            +f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; script-src \'sha256-{digest}\'; base-uri \'none\'; form-action \'none\'"><title>HTML 보고서 디자인 선택</title><style>'+_CSS+report_design.CSS+CSS+gallery_css+'</style></head>'
            +'<body class="picker"><main class="picker-wrap"><h1>어떤 느낌의 보고서로 만들까요?</h1><p class="intro">바로 시작하려면 추천 디자인을 고르세요. 더 보고 싶을 때만 ‘추가 디자인’을 펼치면 됩니다. 이 화면에는 예시 자료만 있으며 업무 파일이나 개인 설정은 읽거나 바꾸지 않습니다.</p>'
            +'<div class="quick-choices"><button type="button" data-choice="minimalism" data-label="미니멀리즘(깔끔한 업무형)" aria-pressed="true">깔끔한 업무형 · 추천</button><button type="button" data-choice="bento-grid" data-label="벤토그리드(지표 중심형)" aria-pressed="false">지표 중심형</button><button type="button" data-choice="template" data-label="HTML 양식 직접 첨부" aria-pressed="false">HTML 양식 직접 첨부</button></div><p class="note">첨부 양식을 선택했다면 아래 문장을 채팅에 붙여 넣고 HTML 파일을 첨부하세요. 이 화면에서 파일을 업로드하거나 원본을 실행하지 않습니다.</p>'
            +'<details id="additional-designs" class="design-options"><summary>추가 디자인 · 설명과 미리보기</summary><p class="note">8가지 디자인을 같은 가상 자료로 비교합니다. 축소 예시이며 실제 분량·자료에 따라 배치는 달라집니다. 자유양식도 준비된 구성에서 시작합니다.</p><div class="design-grid">'+''.join(cards)+'</div></details>'
            +'<section class="selection-panel"><h2 id="selected-design">선택한 디자인: 미니멀리즘(깔끔한 업무형)</h2><div class="choice-fields"><label for="length-choice">분량<select id="length-choice"><option value="keep" selected>기존 선택 유지</option><option value="short">핵심</option><option value="standard">보통</option><option value="detailed">상세</option></select></label><label for="mode-choice">보기<select id="mode-choice"><option value="keep" selected>기존 선택 유지</option><option value="scroll">스크롤</option><option value="slides">페이지 넘김</option><option value="both">둘 다</option></select></label></div>'
            +'<label for="choice-result">Claude에 전달할 문장</label><textarea id="choice-result" readonly></textarea><button type="button" id="copy-choice">선택 내용 복사</button><p id="copy-status" role="status" aria-live="polite"></p><noscript>화면 동작이 제한되어 있습니다. 디자인 이름·분량·보기 방식을 직접 Claude 채팅에 입력해 주세요.</noscript></section><footer>인터넷 연결 불필요 · 자동 설치/설정 변경/자료 전송 없음</footer></main><script>'+PICKER_JS+'</script></body></html>')
