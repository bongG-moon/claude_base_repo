"""Offline report themes and the progressively disclosed Korean design picker."""
STYLES = (
    ('minimalism', '미니멀리즘', '깔끔한 업무형', '따뜻한 흰색과 올리브 포인트, 넓은 여백과 얇은 선으로 정돈합니다.'),
    ('bento-grid', '벤토그리드', '지표 중심형', '남색 핵심 카드와 밝은 보조 영역을 크기가 다른 격자로 조합합니다.'),
    ('editorial', '에디토리얼', '잡지형', '아이보리 지면에 버건디·먹색, 큰 제목과 편집 구획을 사용합니다.'),
    ('glassmorphism', '글래스모피즘', '밝은 반투명 유리형', '연한 하늘색·라벤더 배경이 흰 유리판 뒤로 비치며 파랑·보라로 지표를 강조합니다.'),
    ('neumorphism', '뉴모피즘', '부드러운 입체형', '배경과 같은 색의 표면에 양방향 그림자를 주어 솟은 판과 눌린 지표를 만듭니다.'),
    ('brutalism', '브루탈리즘', '굵고 강한 강조형', '크림색 바탕, 노랑·파랑·코랄, 검은 테두리와 단단한 그림자로 강조합니다.'),
    ('gradient-mesh', '그라디언트 메시', '색이 번지는 배경형', '코랄·보라·파랑·청록이 번지는 배경 안에 차분한 흰색 본문을 놓습니다.'),
    ('freeform', '자유양식', '비대칭 조합형', '설명과 시각 자료의 비중을 다르게 배치합니다. 임의 웹페이지 복제는 아닙니다.'),
    ('immersive-3d', '3D·이머시브', '입체 오브제형', '베이지·브라운·테라코타와 조형 장식으로 깊이를 표현합니다. 실제 3D 모델 뷰어는 아닙니다.'),
    ('retro-y2k', '레트로·Y2K', '크롬과 파스텔형', '은빛 크롬 테두리와 하늘색·분홍·보라, 별빛 장식으로 복고적인 화면을 만듭니다.'),
)

# Scoped selectors are shared by full reports and miniature previews. No external
# fonts, scripts, image assets or user-provided CSS are evaluated.
CSS = r'''
:is(body,.style-preview)[data-style]{--heading-font:'Malgun Gothic','Segoe UI',sans-serif;--surface:var(--paper);--cell:var(--paper);--cover:var(--paper);--panel-shadow:none;--cell-shadow:none;--chart-shadow:var(--cell-shadow);--stroke:1px;--section-radius:16px;--cell-radius:12px;--head-fill:var(--tint);--row-fill:var(--tint);--series-2:#4664a5;--series-3:#92529b;--series-4:#977018;--series-5:#53656f;color:var(--ink);background:var(--bg)}
:is(body,.style-preview)[data-style=minimalism]{--bg:#f4f5ee;--paper:#fefefd;--ink:#292f28;--muted:#586051;--accent:#596b3c;--line:#e1e5d9;--tint:#eff2e6;--cover:#fefefd;--section-radius:6px;--cell-radius:5px;--series-0:#7e925d;--series-1:#c4ac67;--series-2:#596b3c}
:is(body,.style-preview)[data-style=bento-grid]{--bg:#f1f4f7;--paper:#fff;--ink:#202d43;--muted:#516179;--accent:#365bd9;--line:#e1e7ef;--tint:#edf1ff;--cover:#fff;--section-radius:18px;--cell-radius:12px;--cell-shadow:0 3px 12px #20314e05;--series-0:#5274df;--series-1:#df8576;--series-2:#79b7a3;--series-3:#a699de}
:is(body,.style-preview)[data-style=editorial]{--bg:#f3f1eb;--paper:#fcfbf7;--ink:#22272a;--muted:#61575a;--accent:#621e30;--line:#d9d5cf;--tint:#f2e9e8;--heading-font:Georgia,'Batang',serif;--section-radius:0px;--cell-radius:0px;--series-0:#762438;--series-1:#45657d;--series-2:#839cad}
:is(body,.style-preview)[data-style=glassmorphism]{--bg:radial-gradient(ellipse at 8% 8%,#d0c6f2 0,transparent 54%),radial-gradient(ellipse at 95% 75%,#a6dffc 0,transparent 58%),radial-gradient(ellipse at 64% 5%,#eff6ff 0,transparent 48%),linear-gradient(135deg,#e5def8,#e6f4ff 65%,#c7e8fc);--paper:#f4f8ff;--surface:#ffffff2e;--cell:#ffffff24;--ink:#253755;--muted:#4d607b;--accent:#4f5bcc;--line:#ffffffbd;--tint:#ffffff30;--cover:linear-gradient(120deg,#ffffff57,#ffffff1a);--panel-shadow:0 18px 44px #4e75ab18,inset 0 1px 0 #fffffff0,inset 0 -1px 0 #577cab12;--cell-shadow:0 6px 18px #4c76af0a,inset 0 1px 0 #ffffffcc;--section-radius:22px;--cell-radius:14px;--series-0:#6178e8;--series-1:#a095df;--series-2:#57abc7;--series-3:#748ee1;--series-4:#b7adeb;--series-5:#3f67aa}
:is(body,.style-preview)[data-style=neumorphism]{--bg:#e9ecf1;--paper:#e9ecf1;--ink:#303a4d;--muted:#525e71;--accent:#596dc2;--line:#bac3d3;--tint:#dde3ed;--panel-shadow:14px 14px 32px #c4c9d2,-14px -14px 32px #fff;--cell-shadow:inset 6px 6px 12px #c9cfd9,inset -6px -6px 12px #fff;--chart-shadow:7px 7px 16px #c4c9d2,-7px -7px 16px #fff;--stroke:0px;--section-radius:24px;--cell-radius:16px;--series-0:#6e83d1;--series-1:#a595ce;--series-2:#ce8f83}
:is(body,.style-preview)[data-style=brutalism]{--bg:#fff8e9;--paper:#fffaf0;--ink:#171717;--muted:#454033;--accent:#143ddc;--line:#171717;--tint:#ffeb3b;--cover:#ffe521;--panel-shadow:8px 8px 0 #171717;--cell-shadow:4px 4px 0 #171717;--stroke:3px;--section-radius:0px;--cell-radius:0px;--series-0:#1744ff;--series-1:#ff6252;--series-2:#e6b600}
:is(body,.style-preview)[data-style=gradient-mesh]{--bg:radial-gradient(at 0% 0%,#ff8c73,transparent 53%),radial-gradient(at 48% 5%,#d356c3,transparent 54%),radial-gradient(at 100% 90%,#46d5d7,transparent 55%),linear-gradient(130deg,#7355e9,#2938ec 68%,#6bbfef);--paper:#fff;--ink:#252641;--muted:#5a6078;--accent:#6642d7;--line:#e5e7f0;--tint:#f3f1fc;--cover:#fff;--panel-shadow:0 20px 48px #22145424;--section-radius:16px;--cell-radius:12px;--series-0:#7754de;--series-1:#32aeb6;--series-2:#ec7687}
:is(body,.style-preview)[data-style=freeform]{--bg:#eaf3f1;--paper:#fff;--ink:#173c3b;--muted:#446965;--accent:#16675c;--line:#bdd8d0;--tint:#e5f1ed;--cover:linear-gradient(110deg,#fff 60%,#d9eee8 60%);--section-radius:6px;--cell-radius:4px;--series-0:#16675c;--series-1:#b16331}
:is(body,.style-preview)[data-style=immersive-3d]{--bg:radial-gradient(at 25% 10%,#f2e6d8,transparent 65%),#dfd0bd;--paper:#f2ebe2;--ink:#3d332b;--muted:#68594c;--accent:#9b4e2e;--line:#d5c7b6;--tint:#e9dcca;--cover:linear-gradient(125deg,#f7f1e9,#e6d8c7);--panel-shadow:0 18px 38px #56422e25,inset 0 1px 0 #fff9;--cell-shadow:5px 7px 14px #69513a12,inset 0 1px 0 #fff;--section-radius:14px;--cell-radius:8px;--series-0:#ad613b;--series-1:#75624c;--series-2:#b59d7e}
:is(body,.style-preview)[data-style=retro-y2k]{--bg:linear-gradient(135deg,#e2f4ff,#cbdffc 55%,#e6d8f6);--paper:#f6faff;--ink:#313355;--muted:#555e7b;--accent:#7540b6;--line:#91a6bf;--tint:#e7eafa;--cover:linear-gradient(110deg,#eff9ff,#ede6fc);--panel-shadow:0 9px 20px #496b9430,inset 0 2px 0 #fff,inset 0 -3px 0 #b8c9db;--cell-shadow:inset 0 2px 0 #fff,0 2px 3px #859cbd44;--section-radius:18px;--cell-radius:10px;--series-0:#9a6ddb;--series-1:#e66aab;--series-2:#53a9df;--head-fill:linear-gradient(#fff,#d1e2f2);--row-fill:#e9effb}
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
:is(body,.style-preview)[data-style=bento-grid] .kpi:first-child{background:#1d2c48;--ink:#f5f7ff;--muted:#c0cce3;--accent:#a4b7ff;--line:#304362}
:is(body,.style-preview)[data-style=bento-grid] .kpi:nth-child(3n){background:#eef7f3}
:is(body,.style-preview)[data-style=brutalism] .report-masthead{background:#143ddc;color:#fff;border:3px solid #171717;box-shadow:6px 6px 0 #171717}
:is(body,.style-preview)[data-style=brutalism] .report-masthead .subtitle{color:#e9edff}
:is(body,.style-preview)[data-style=brutalism] .kpi:nth-child(3n){background:#ff7664}
:is(body,.style-preview)[data-style=editorial] .report-masthead{background:#541b2b;color:#fcfbf7;border-bottom:3px solid #32101c}
:is(body,.style-preview)[data-style=editorial] .report-masthead .subtitle{color:#e3cbd1}
:is(body,.style-preview)[data-style=gradient-mesh] .report-masthead{background:#202039;color:#fff;border-radius:12px}
:is(body,.style-preview)[data-style=gradient-mesh] .report-masthead .subtitle{color:#d3d4e7}
:is(body,.style-preview)[data-style=retro-y2k] .report-masthead{background:linear-gradient(#fff,#d9e5f0 45%,#a0b2c7 52%,#edf8ff);border:1px solid #8299b0;border-radius:18px;box-shadow:inset 0 2px 0 white,0 3px 8px #61789233;color:#343f60}
:is(body,.style-preview)[data-style=retro-y2k] .kpi{background:linear-gradient(135deg,#fff,#eee9ff 70%,#e4f5ff)}
:is(body,.style-preview)[data-style=retro-y2k] .section::before{content:'';display:block;height:6px;border-radius:8px;background:linear-gradient(90deg,#68b7ff,#b99bf6,#ee9edb);margin-bottom:22px}
/* Data-free cover artwork: decorative CSS geometry, not a fake chart or product. */
.theme-art{display:none;pointer-events:none}
:is(body,.style-preview)[data-style=immersive-3d] .layout-cover{padding-right:40%;min-height:500px}
:is(body,.style-preview)[data-style=immersive-3d] .theme-art{display:block;position:absolute;right:5%;top:18%;width:28%;height:280px;isolation:isolate}
:is(body,.style-preview)[data-style=immersive-3d] .theme-art::before{content:'';position:absolute;inset:70% -8% -2%;border-radius:50%;background:linear-gradient(#d0c2ad,#b09a7c);box-shadow:12px 22px 22px #67503b38,inset 0 3px 3px #fff9}
:is(body,.style-preview)[data-style=immersive-3d] .theme-art i{position:absolute;display:block;bottom:20%;border-radius:6px;transform:skewY(-12deg);box-shadow:12px 12px 16px #5a412e35,inset 3px 3px 2px #fff8,inset -10px 0 0 #0001}
:is(body,.style-preview)[data-style=immersive-3d] .theme-art i:nth-child(1){left:8%;width:40%;height:64%;background:linear-gradient(105deg,#eee5d6,#ac9575)}
:is(body,.style-preview)[data-style=immersive-3d] .theme-art i:nth-child(2){left:43%;width:39%;height:82%;background:repeating-linear-gradient(90deg,#71604d 0 3px,#9c876b 3px 6px)}
:is(body,.style-preview)[data-style=immersive-3d] .theme-art i:nth-child(3){left:35%;width:55%;height:47%;background:linear-gradient(120deg,#c97b50,#944523);border-radius:45% 5px 5px 5px}
:is(body,.style-preview)[data-style=editorial] .layout-cover{padding-right:38%}
:is(body,.style-preview)[data-style=editorial] .theme-art{display:block;position:absolute;right:4%;top:12%;width:28%;height:65%;max-height:300px;border-radius:80% 0 0 0;background:repeating-conic-gradient(from 230deg at 100% 100%,#541b2b 0deg 7deg,#8c4a5a 7deg 8deg,#283c51 8deg 15deg,#698096 15deg 16deg);box-shadow:inset -20px -12px 32px #10172344}
:is(body,.style-preview)[data-style=retro-y2k] .layout-cover{padding-right:32%}
:is(body,.style-preview)[data-style=retro-y2k] .theme-art{display:block;position:absolute;right:5%;top:12%;width:21%;height:210px;background:conic-gradient(#fff,#b8c8e8,#687b9a,#fff,#cea2e6,#fff);clip-path:polygon(50% 0,58% 36%,85% 12%,66% 43%,100% 50%,64% 57%,85% 87%,56% 66%,50% 100%,43% 65%,12% 89%,35% 58%,0 50%,36% 43%,13% 13%,43% 35%)}
:is(body,.style-preview)[data-style] .theme-art~.section-content{position:relative}
:is(body,.style-preview)[data-style=brutalism] h2{letter-spacing:-1.6px;font-weight:900}
:is(body,.style-preview)[data-style=brutalism] .takeaway{font-weight:800;border-left:0;border-bottom:3px solid var(--ink);padding:8px 0 12px}
:is(body,.style-preview)[data-style=gradient-mesh]{background-size:100% 100vh;background-attachment:fixed}
.style-preview[data-style=gradient-mesh]{background-size:100% 100%;background-attachment:scroll}
@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){:is(body,.style-preview)[data-style=glassmorphism] :is(.section,.layout-cover,.kpi,.chart-frame){background:#fafafa!important}}
@media(prefers-reduced-transparency:reduce){:is(body,.style-preview)[data-style=glassmorphism] :is(.section,.layout-cover,.kpi,.chart-frame,.report-masthead){background:#fafafa!important;backdrop-filter:none;-webkit-backdrop-filter:none}}
@media(max-width:760px){body[data-style] .section{padding:26px 22px}body[data-style] .report-main{grid-template-columns:minmax(0,1fr)!important;padding:12px 20px;gap:28px}body[data-style] .layout-split .section-content{display:block}body[data-style=freeform][data-view=scroll] .section:nth-child(even){margin-left:0}body[data-style=bento-grid] .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}body[data-style=bento-grid] .kpi:first-child{grid-column:auto}body[data-style=neumorphism] .kpi{padding:18px}body[data-style=glassmorphism]{background-attachment:scroll}}
@media(max-width:760px){body[data-style] .kpi-unit{display:block;margin:5px 0 0;white-space:nowrap}}
@media(max-width:760px){body[data-style] .layout-cover{padding-right:22px}body[data-style] .theme-art{position:relative;top:auto;right:auto;margin:22px auto;width:210px;height:180px}body[data-style=editorial] .theme-art{height:160px}body[data-style] .report-masthead{margin:12px 20px}body[data-style] .report-masthead nav{display:flex;flex-wrap:wrap;gap:8px}}
@media print{.theme-art{display:none!important}body[data-style] .layout-cover{padding-right:24px}body[data-style] .report-masthead{background:white!important;color:#172132!important;box-shadow:none!important}body[data-style] .report-masthead .subtitle{color:#344154!important}body[data-style] .kpi{--ink:#172132;--muted:#344154;--accent:#172132}}
@media print{body[data-style] :is(.kpi-value,.kpi-label,.kpi-note){color:#172132!important}}
@media print{:is(body,.style-preview)[data-style]{background:white!important;--ink:#172132;--muted:#344154}body[data-style] .report-main{display:block!important}:is(body,.style-preview)[data-style] :is(.section,.layout-cover,.kpi,.chart-frame){box-shadow:none!important;backdrop-filter:none!important;-webkit-backdrop-filter:none!important;background:white!important;border-color:#aaa}body[data-style] .section{margin:0 0 24px!important}body[data-style=freeform][data-view=scroll] .section:nth-child(even){margin-left:0}}
'''


def choices(spec):
    # Expose ONLY the current step. Length/view questions must not be bundled
    # with the initial design question or an unresolved additional-design menu.
    pending = {'ok': False, 'status': 'input_required', 'code': 'report_choices_required',
               'preservedChoices': {key: spec[key] for key in ('style','length','mode','htmlTemplate','templateReview') if key in spec}}
    if spec.get('designMenu') == 'template' or 'htmlTemplate' in spec:
        template = spec.get('htmlTemplate')
        if not (isinstance(template, dict) and isinstance(template.get('path'), str) and template['path']
                and isinstance(template.get('sha256'), str) and len(template['sha256']) == 64):
            pending.update(stage='template_attach', missing=['htmlTemplate'],
                           message='참고할 HTML 파일을 첨부하거나 파일 경로를 알려 주세요. 양식 확인 전에는 분량·보기 방식을 묻지 않습니다.',
                           templateCommand='business html-template --template ABSOLUTE_PATH --output NEW_PREVIEW.html --open')
            return pending
        from .html_reference import review_stage
        stage = review_stage(spec)
        if stage:
            pending.update(stage=stage, missing=['templateReview' if stage == 'template_preview' else 'templateReview.confirmed'],
                           waitForUser=stage == 'template_confirm',
                           message='첨부 양식의 실제 미리보기를 준비해 주세요.' if stage == 'template_preview' else
                                   '이 느낌으로 진행 / 바꾸고 싶은 부분 입력 / 다른 양식 첨부 중 선택해 주세요.',
                           templateCommand='business html-template --template ABSOLUTE_PATH --output NEW_PREVIEW.html --open')
            return pending
    elif 'style' not in spec:
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
  document.getElementById('additional-designs').addEventListener('toggle',fitPreviews);
  let choice='minimalism', label='미니멀리즘(깔끔한 업무형)';
  function update(){
    buttons.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.choice===choice)));
    document.getElementById('selected-design').textContent='선택한 디자인: '+label;
    const parts=['디자인: '+label];
    if(length.value!=='keep')parts.push('분량: '+length.options[length.selectedIndex].text);
    if(mode.value!=='keep')parts.push('보기: '+mode.options[mode.selectedIndex].text);
    result.value='HTML 보고서를 만들어줘. '+parts.join(' / ')+'. 따로 지정하지 않은 분량과 보기 방식은 이미 정한 조건을 유지하고, 정하지 않은 항목만 물어봐줘. 원자료와 요청 내용은 앞서 전달한 것을 사용해줘.';
    if(choice==='template')result.value='HTML 보고서에 내가 첨부할 HTML 양식을 참고해줘. '+(parts.length>1?parts.slice(1).join(' / ')+'. ':'')+'먼저 양식 파일을 받고 미리보기를 보여줘. 따로 지정하지 않은 분량과 보기 방식은 이미 정한 조건을 유지하고, 정하지 않은 항목은 양식 확인 후에만 물어봐줘.';
    status.textContent='이 선택은 아직 Claude에 전달되지 않았습니다. 아래 문장을 복사해 채팅에 붙여 넣어 주세요.';
  }
  buttons.forEach(button=>button.addEventListener('click',()=>{choice=button.dataset.choice;label=button.dataset.label;update();}));
  length.addEventListener('change',update);mode.addEventListener('change',update);
  document.getElementById('copy-choice').addEventListener('click',async()=>{
    try { if(!navigator.clipboard)throw new Error('unavailable');await navigator.clipboard.writeText(result.value);status.textContent='복사했습니다. Claude 채팅에 붙여 넣으면 선택을 전달할 수 있습니다.'; }
    catch { result.focus();result.select();status.textContent='자동 복사가 제한되었습니다. 선택된 문장을 Ctrl+C로 복사해 채팅에 붙여 넣어 주세요.'; }
  });
  update();fitPreviews();
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
                           'chart':{'type':'line','title':'월별 실적 · 예시', 'categories':['6월','7월','8월'],
                                    'series':[{'name':'실적','values':[145,175,210]}]}}]}
    rendered = report_design.render(sample, '', '', _html_table)
    sample_main = rendered.split('<main class="report-main">',1)[1].split('</main>',1)[0]
    cards=[]
    for number,(key,name,label,description) in enumerate(STYLES,1):
        specific = sample_main
        if key in ('immersive-3d','editorial','retro-y2k'):
            decorated={**sample,'style':key,'sections':[{**sample['sections'][0],'layout':'cover'}]}
            specific=report_design.render(decorated,'','',_html_table).split('<main class="report-main">',1)[1].split('</main>',1)[0]
        specific='<header class="report-masthead"><div class="report-name">월간 운영 보고 · 가상 예시</div><span>6–8월</span></header>'+specific
        preview = specific.replace('id="', f'id="{key}-').replace('aria-labelledby="', f'aria-labelledby="{key}-')
        cards.append(f'<article class="design-card"><div class="mini-window" aria-hidden="true" inert><div class="style-preview" data-style="{key}">{preview}</div></div><h3>{number}. {name}</h3><p>{escape(description)}</p><button type="button" data-choice="{key}" data-label="{name}({label})" aria-pressed="false">{name} 선택</button></article>')
    digest=base64.b64encode(hashlib.sha256(PICKER_JS.encode()).digest()).decode()
    gallery_css='''
body.picker{background:#f4f6fa;color:#20364c;font:16px/1.65 'Malgun Gothic','Segoe UI',sans-serif;margin:0}
.picker-wrap{max-width:1180px;margin:auto;padding:36px 24px}.picker h1{font-size:32px;margin:0 0 12px}.intro{max-width:70ch;color:#536477}
.quick-choices{display:flex;flex-wrap:wrap;gap:12px;margin:20px 0}.picker button,.picker select{font:inherit;border:1px solid #bdccdc;background:white;color:#20364c;border-radius:8px;padding:10px 16px;cursor:pointer}
.picker button[aria-pressed=true]{background:#193e67;color:white;border-color:#193e67}.picker button:focus-visible,.picker summary:focus-visible,.picker select:focus-visible,.picker textarea:focus-visible{outline:3px solid #d38321;outline-offset:3px}
.design-options{border:1px solid #d2dce7;background:#fff;border-radius:12px;padding:16px;margin:16px 0}.design-options>summary{font-size:18px;font-weight:700;cursor:pointer}.design-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px;margin-top:18px}
.design-card{border:1px solid #d2dce7;border-radius:10px;padding:12px;min-width:0;overflow:hidden;background:#fff}.design-card h3{font-size:19px;margin:14px 0 5px}.design-card p{font-size:14px;min-height:48px;margin:6px 0 14px}
.mini-window{height:218px;overflow:hidden;background:#eef2f7;border:1px solid #d6dfe8;border-radius:6px;pointer-events:none}.style-preview{width:960px;min-height:775px;padding:34px;transform:scale(.28);transform-origin:top left;box-sizing:border-box}
.style-preview .section{margin:0;padding:30px}.style-preview .kpis{grid-template-columns:1fr 1fr}.style-preview .chart-frame{margin:8px 0;padding:16px}.style-preview h2{font-size:36px!important}.style-preview .report-chart{min-width:0}.style-preview .chart-values{display:none}
.style-preview .report-masthead{padding:18px 24px;margin:0 0 22px;font-size:14px}.style-preview .report-masthead .report-name{font-size:16px}
.style-preview[data-style=immersive-3d] .layout-cover{padding-right:38%}.style-preview[data-style=immersive-3d] .theme-art{top:18%;height:250px}
.style-preview .layout-cover .kpi{padding:18px 14px}.style-preview .layout-cover .kpi-value{font-size:30px}.style-preview .layout-cover .kpi-unit{display:block;margin-left:0}
.selection-panel{background:white;border:1px solid #d2dce7;border-radius:12px;padding:22px;margin-top:24px}.selection-panel h2{font-size:20px}.choice-fields{display:flex;flex-wrap:wrap;gap:20px;margin:16px 0}.choice-fields label{display:flex;gap:10px;align-items:center}
.picker textarea{display:block;width:100%;min-height:115px;box-sizing:border-box;font:15px/1.7 'Malgun Gothic',sans-serif;padding:12px;border:1px solid #bdccdc;border-radius:8px;margin:16px 0}.note{font-size:14px;color:#536477}.picker footer{padding:20px 0;font-size:13px;color:#536477}
@media(max-width:620px){.picker-wrap{padding:24px 16px}.picker h1{font-size:25px}.design-grid{grid-template-columns:1fr}.choice-fields label{flex-wrap:wrap}}
@media print{.picker button{display:none}.mini-window{break-inside:avoid}}
'''
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            +f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; script-src \'sha256-{digest}\'; base-uri \'none\'; form-action \'none\'"><title>HTML 보고서 디자인 선택</title><style>'+_CSS+report_design.CSS+CSS+gallery_css+'</style></head>'
            +'<body class="picker"><main class="picker-wrap"><h1>어떤 느낌의 보고서로 만들까요?</h1><p class="intro">바로 시작하려면 추천 디자인을 고르세요. 더 보고 싶을 때만 ‘추가 디자인’을 펼치면 됩니다. 이 화면에는 예시 자료만 있으며 업무 파일이나 개인 설정은 읽거나 바꾸지 않습니다.</p>'
            +'<div class="quick-choices"><button type="button" data-choice="minimalism" data-label="미니멀리즘(깔끔한 업무형)" aria-pressed="true">깔끔한 업무형 · 추천</button><button type="button" data-choice="bento-grid" data-label="벤토그리드(지표 중심형)" aria-pressed="false">지표 중심형</button><button type="button" data-choice="template" data-label="HTML 양식 직접 첨부" aria-pressed="false">HTML 양식 직접 첨부</button></div><p class="note">첨부 양식을 선택했다면 아래 문장을 채팅에 붙여 넣고 HTML 파일을 첨부하세요. 이 화면에서 파일을 업로드하거나 원본을 실행하지 않습니다.</p>'
            +f'<details id="additional-designs" class="design-options"><summary>추가 디자인 · 설명과 미리보기</summary><p class="note">{len(STYLES)}가지 디자인을 같은 가상 자료로 비교합니다. 원하는 카드를 바로 선택하세요. 축소 예시이며 실제 분량·자료에 따라 배치는 달라집니다. 입체 오브제는 장식용이며 업무 데이터를 뜻하지 않습니다.</p><div class="design-grid">'+''.join(cards)+'</div></details>'
            +'<section class="selection-panel"><h2 id="selected-design">선택한 디자인: 미니멀리즘(깔끔한 업무형)</h2><div class="choice-fields"><label for="length-choice">분량<select id="length-choice"><option value="keep" selected>기존 선택 유지</option><option value="short">핵심</option><option value="standard">보통</option><option value="detailed">상세</option></select></label><label for="mode-choice">보기<select id="mode-choice"><option value="keep" selected>기존 선택 유지</option><option value="scroll">스크롤</option><option value="slides">페이지 넘김</option><option value="both">둘 다</option></select></label></div>'
            +'<label for="choice-result">Claude에 전달할 문장</label><textarea id="choice-result" readonly></textarea><button type="button" id="copy-choice">선택 내용 복사</button><p id="copy-status" role="status" aria-live="polite"></p><noscript>화면 동작이 제한되어 있습니다. 디자인 이름·분량·보기 방식을 직접 Claude 채팅에 입력해 주세요.</noscript></section><footer>인터넷 연결 불필요 · 자동 설치/설정 변경/자료 전송 없음</footer></main><script>'+PICKER_JS+'</script></body></html>')
