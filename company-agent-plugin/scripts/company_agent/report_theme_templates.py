"""Offline CSS compositions shared by reports and their design previews.

These rules style the existing semantic report DOM. Decorative geometry carries
no data; fonts, user palettes and reference layouts are resolved by the renderer.
"""

CSS = r'''
/* Shared report surface. Typography is inherited from the selected font. */
:is(body,.style-preview)[data-style]{--surface:var(--paper);--cell:var(--paper);--cover:var(--paper);--panel-shadow:none;--cell-shadow:none;--chart-shadow:none;--stroke:1px;--section-radius:16px;--cell-radius:12px;--head-fill:var(--tint);--row-fill:var(--tint);--series-2:#55758c;--series-3:#9673a3;--series-4:#a18448;--series-5:#586d68;background:var(--bg);color:var(--ink)}
:is(body,.style-preview)[data-style] .report-main{display:grid;gap:28px;padding-top:20px;padding-bottom:56px;align-items:start}
:is(body,.style-preview)[data-style] .report-masthead{margin:0 auto;padding-top:28px;padding-bottom:22px;border-bottom:1px solid var(--line);background:transparent;box-shadow:none}
:is(body,.style-preview)[data-style] .report-masthead :where(button){background:var(--paper);color:var(--ink);border:1px solid var(--line);border-radius:7px;box-shadow:none}
:is(body,.style-preview)[data-style] .report-name{letter-spacing:-.01em}
:is(body,.style-preview)[data-style] .section{margin:0;padding:44px 48px;background:var(--surface);border:var(--stroke) solid var(--line);border-radius:var(--section-radius);box-shadow:var(--panel-shadow);min-width:0}
:is(body,.style-preview)[data-style] .layout-cover{background:var(--cover)!important;min-height:0;padding-top:54px;padding-bottom:48px}
:is(body,.style-preview)[data-style] :is(.section-content,.copy-block,.visual-block){min-width:0}
:is(body,.style-preview)[data-style] .section h2{font-family:var(--heading-font,inherit);font-size:clamp(28px,3.2vw,42px);font-weight:750;line-height:1.3;letter-spacing:-.04em;word-break:keep-all;overflow-wrap:anywhere;text-wrap:pretty;margin-top:0;margin-bottom:20px}
:is(body,.style-preview)[data-style] .layout-cover h2{font-size:clamp(36px,4.6vw,60px);line-height:1.22;letter-spacing:-.045em;max-width:20ch;margin-top:14px;margin-bottom:24px}
:is(body,.style-preview)[data-style] .page-number{display:block;font-weight:650;letter-spacing:.12em;margin-bottom:18px}
:is(body,.style-preview)[data-style] .takeaway{max-width:67ch;overflow-wrap:anywhere;word-break:keep-all}
:is(body,.style-preview)[data-style] .text{line-height:1.7}
:is(body,.style-preview)[data-style] .section-source{line-height:1.6;margin-top:26px}
:is(body,.style-preview)[data-style] .kpis{grid-template-columns:repeat(12,minmax(0,1fr));gap:16px;margin:28px 0}
:is(body,.style-preview)[data-style] .kpi{grid-column:span 4;min-width:0;padding:24px;background:var(--cell);border:var(--stroke) solid var(--line);border-radius:var(--cell-radius);box-shadow:var(--cell-shadow)}
:is(body,.style-preview)[data-style] .kpis:where([data-kpi-count="1"]) .kpi{grid-column:1/-1}
:is(body,.style-preview)[data-style] .kpis:where([data-kpi-count="2"],[data-kpi-count="4"]) .kpi{grid-column:span 6}
:is(body,.style-preview)[data-style] .kpis:where([data-kpi-count="5"]) .kpi:where(:nth-child(-n+2)){grid-column:span 6}
:is(body,.style-preview)[data-style] .kpi-label{line-height:1.5;font-weight:600;overflow-wrap:anywhere}
:is(body,.style-preview)[data-style] .kpi-value{font-size:clamp(29px,3.4vw,44px);font-weight:750;line-height:1.2;margin:14px 0 10px;overflow-wrap:anywhere}
:is(body,.style-preview)[data-style] .kpi-unit{display:inline-block;font-size:13px;line-height:1.5;font-weight:500;white-space:normal}
:is(body,.style-preview)[data-style] .kpi-note{line-height:1.6;overflow-wrap:anywhere}
:is(body,.style-preview)[data-style] .chart-frame{background:var(--cell);border:var(--stroke) solid var(--line);border-radius:var(--cell-radius);box-shadow:var(--chart-shadow);padding:24px;margin:22px 0 12px;min-width:0}
:is(body,.style-preview)[data-style] .chart-frame figcaption{font-size:14px;line-height:1.6;margin-bottom:18px;overflow-wrap:anywhere}
:is(body,.style-preview)[data-style] .legend{gap:12px 22px;line-height:1.6;margin-top:10px}
:is(body,.style-preview)[data-style] th{background:var(--head-fill);color:var(--ink)}
:is(body,.style-preview)[data-style] tbody tr:nth-child(even){background:var(--row-fill)}

/* 01 / Quiet workspace: content, hairlines and an unboxed metric rail. */
:is(body,.style-preview)[data-style=minimalism]{--bg:#f5f6f4;--paper:#fff;--ink:#202923;--muted:#59645e;--accent:#3f6956;--line:#dce2dd;--tint:#f1f5f1;--section-radius:4px;--cell-radius:0px;--series-0:#4d7964;--series-1:#a3b7a5;--series-2:#be9a61;--series-3:#778b99}
:is(body,.style-preview)[data-style=minimalism] .report-main{gap:0}
:is(body,.style-preview)[data-style=minimalism] .section{border-width:0 0 1px;padding-top:48px;padding-bottom:48px}
:is(body,.style-preview)[data-style=minimalism] .layout-cover{padding-top:62px;padding-bottom:52px}
:is(body,.style-preview)[data-style=minimalism] .page-number{letter-spacing:.08em}
:is(body,.style-preview)[data-style=minimalism] .takeaway{border-left:0;padding-left:0;color:var(--muted);max-width:58ch}
:is(body,.style-preview)[data-style=minimalism] .kpis{gap:0;margin-top:40px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
:is(body,.style-preview)[data-style=minimalism] .kpi{border-width:0 0 0 1px;padding:26px 28px;background:transparent}
:is(body,.style-preview)[data-style=minimalism] .kpi:where(:first-child){border-left:0;padding-left:0}
:is(body,.style-preview)[data-style=minimalism] .kpi-value{color:var(--ink);font-weight:650}
:is(body,.style-preview)[data-style=minimalism] .chart-frame{border:0;border-top:1px solid var(--line);padding:24px 0 8px}
:is(body,.style-preview)[data-style=minimalism] .layout-summary .copy-block{border-top:0;padding-top:0}

/* 02 / Bento: one lead metric, complementary modules, no empty grid cells. */
:is(body,.style-preview)[data-style=bento-grid]{--bg:#edf0f4;--paper:#fff;--ink:#202c42;--muted:#546278;--accent:#385dc9;--line:#dde4ef;--tint:#f0f3fa;--section-radius:24px;--cell-radius:17px;--series-0:#4770dc;--series-1:#73a495;--series-2:#b694c9;--series-3:#c78a60}
:is(body,.style-preview)[data-style=bento-grid] .report-masthead{border-bottom:0}
:is(body,.style-preview)[data-style=bento-grid][data-view=scroll] .report-main{grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
:is(body,.style-preview)[data-style=bento-grid] :is(.layout-cover,.layout-table,.layout-split,.layout-dashboard,.bento-wide){grid-column:1/-1}
:is(body,.style-preview)[data-style=bento-grid] .section{border:0;padding:36px 40px}
:is(body,.style-preview)[data-style=bento-grid] .layout-cover{padding:44px 40px 30px}
:is(body,.style-preview)[data-style=bento-grid] .layout-cover h2{max-width:21ch}
:is(body,.style-preview)[data-style=bento-grid] .takeaway{border-left:0;padding-left:0;color:var(--muted)}
:is(body,.style-preview)[data-style=bento-grid] .kpis{gap:14px;margin-top:32px}
:is(body,.style-preview)[data-style=bento-grid] .kpi{border:0;padding:26px;background:var(--tint)}
:is(body,.style-preview)[data-style=bento-grid] .kpi:where(:first-child){background:#20334f;--ink:#f7f9ff;--muted:#c7d3e7;--accent:#e8eeff;--line:#465875}
:is(body,.style-preview)[data-style=bento-grid] .kpi:where(:nth-child(3n)){background:#eaf3ef}
:is(body,.style-preview)[data-style=bento-grid] .kpis:where([data-kpi-count="2"]) .kpi:where(:first-child){grid-column:span 7}
:is(body,.style-preview)[data-style=bento-grid] .kpis:where([data-kpi-count="2"]) .kpi:where(:last-child){grid-column:span 5}
:is(body,.style-preview)[data-style=bento-grid] .kpis:where([data-kpi-count="3"]) .kpi{grid-column:span 3}
:is(body,.style-preview)[data-style=bento-grid] .kpis:where([data-kpi-count="3"]) .kpi:where(:first-child){grid-column:span 6}
:is(body,.style-preview)[data-style=bento-grid] .kpis:where([data-kpi-count="5"]) .kpi:where(:first-child){grid-column:span 8}
:is(body,.style-preview)[data-style=bento-grid] .kpis:where([data-kpi-count="5"]) .kpi:where(:nth-child(2)){grid-column:span 4}
:is(body,.style-preview)[data-style=bento-grid] .kpis:where([data-kpi-count="6"]) .kpi{grid-column:span 3}
:is(body,.style-preview)[data-style=bento-grid] .kpis:where([data-kpi-count="6"]) .kpi:where(:nth-child(-n+2)){grid-column:span 6}
:is(body,.style-preview)[data-style=bento-grid] .chart-frame{border:0;background:var(--tint);padding:28px}
:is(body,.style-preview)[data-style=bento-grid] .layout-summary .copy-block{border-top:1px solid var(--line)}

/* 03 / Editorial: a paper spread, decisive rules and a geometric cover print. */
:is(body,.style-preview)[data-style=editorial]{--bg:#f0ede6;--paper:#fcfaf5;--ink:#262622;--muted:#625d55;--accent:#7a303b;--line:#d2ccc0;--tint:#f1ece3;--section-radius:0px;--cell-radius:0px;--series-0:#813746;--series-1:#597384;--series-2:#aa9263;--series-3:#889781}
:is(body,.style-preview)[data-style=editorial] .report-masthead{padding-top:24px;padding-bottom:18px;border-bottom:3px solid var(--ink)}
:is(body,.style-preview)[data-style=editorial] .report-name{font-weight:800;letter-spacing:.04em}
:is(body,.style-preview)[data-style=editorial] .report-main{gap:38px}
:is(body,.style-preview)[data-style=editorial] .section{border-width:1px 0 0;padding:36px 32px 42px}
:is(body,.style-preview)[data-style=editorial] .layout-cover{border-top:0;padding-top:40px}
:is(body,.style-preview)[data-style=editorial] .section h2{font-weight:800;max-width:24ch}
:is(body,.style-preview)[data-style=editorial] .layout-cover h2{font-size:clamp(38px,4.8vw,64px);max-width:17ch}
:is(body,.style-preview)[data-style=editorial] .takeaway{border-left:0;padding-left:0;max-width:56ch}
:is(body,.style-preview)[data-style=editorial] .section-content{padding-top:24px;border-top:1px solid var(--line)}
:is(body,.style-preview)[data-style=editorial] .layout-split .section-content{align-items:start;grid-template-columns:minmax(0,.8fr) minmax(0,1.2fr);gap:40px}
:is(body,.style-preview)[data-style=editorial] .layout-summary .copy-block{border-top:0;padding-top:0}
:is(body,.style-preview)[data-style=editorial] .kpis{gap:0;border-top:3px solid var(--ink);border-bottom:1px solid var(--line);margin-top:34px}
:is(body,.style-preview)[data-style=editorial] .kpi{border-width:0 0 0 1px;padding:22px 26px;background:transparent}
:is(body,.style-preview)[data-style=editorial] .kpi:where(:first-child){border-left:0;padding-left:0}
:is(body,.style-preview)[data-style=editorial] .kpi-value{color:var(--ink);font-size:clamp(31px,3.8vw,48px);font-weight:700}
:is(body,.style-preview)[data-style=editorial] .chart-frame{border:0;padding:0;background:transparent}
:is(body,.style-preview)[data-style=editorial] .chart-frame figcaption{border-bottom:1px solid var(--line);padding-bottom:14px}
:is(body,.style-preview)[data-style=editorial] .section-source{border-top:0;padding-top:0}

/* 04 / Glass: light lives behind the chrome; long-form content stays solid. */
:is(body,.style-preview)[data-style=glassmorphism]{--bg:radial-gradient(ellipse at 4% 3%,#d5d2f1 0,transparent 43%),radial-gradient(ellipse at 93% 20%,#bcddf0 0,transparent 48%),#e9eff7;--paper:#f9fbff;--surface:#ffffffd9;--cell:#ffffffed;--cover:linear-gradient(120deg,#ffffffdc,#ffffffa3);--ink:#27354c;--muted:#56657b;--accent:#505dba;--line:#ccd6e8;--tint:#edf2fa;--section-radius:25px;--cell-radius:16px;--panel-shadow:0 12px 34px #536a8a0e,inset 0 1px 0 #fff;--series-0:#5e78ce;--series-1:#7da7ba;--series-2:#9a8bc6;--series-3:#638580}
:is(body,.style-preview)[data-style=glassmorphism] .report-masthead{margin-top:16px;margin-bottom:10px;max-width:1240px;padding:20px 28px;border:1px solid #ffffffef;border-radius:20px;background:#ffffff9e;box-shadow:0 5px 20px #536a8a08;-webkit-backdrop-filter:blur(20px);backdrop-filter:blur(20px)}
:is(body,.style-preview)[data-style=glassmorphism] .section{border-color:#fffffff2;-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px)}
:is(body,.style-preview)[data-style=glassmorphism] .layout-cover{padding-top:52px;padding-bottom:40px}
:is(body,.style-preview)[data-style=glassmorphism] .page-number{display:inline-block;background:var(--cell);border:1px solid var(--line);border-radius:100px;padding:6px 12px;letter-spacing:.06em}
:is(body,.style-preview)[data-style=glassmorphism] .takeaway{border-color:#a8b8da}
:is(body,.style-preview)[data-style=glassmorphism] .kpi{border-color:#fff;box-shadow:0 2px 10px #50658a06,inset 0 1px 0 #fff}
:is(body,.style-preview)[data-style=glassmorphism] .chart-frame{background:var(--paper);border:1px solid var(--line)}
:is(body,.style-preview)[data-style=glassmorphism] .layout-summary .copy-block{border-top:1px solid var(--line)}

/* 05 / Soft relief: tactile frame and metric wells, flat evidence surfaces. */
:is(body,.style-preview)[data-style=neumorphism]{--bg:#e8eced;--paper:#e8eced;--ink:#2e3d42;--muted:#59696e;--accent:#476f74;--line:#c4d0d2;--tint:#e0e7e8;--section-radius:28px;--cell-radius:16px;--panel-shadow:9px 9px 22px #cbd3d580,-9px -9px 22px #ffffff9c;--cell-shadow:inset 3px 3px 7px #c8d2d580,inset -3px -3px 7px #ffffffbf;--series-0:#5c858a;--series-1:#90a9a5;--series-2:#a191b5;--series-3:#b19777}
:is(body,.style-preview)[data-style=neumorphism] .report-masthead{border-bottom:0;padding-bottom:16px}
:is(body,.style-preview)[data-style=neumorphism] .report-main{gap:36px;padding-top:24px;padding-bottom:64px}
:is(body,.style-preview)[data-style=neumorphism] .section{border:1px solid #ffffff70;padding:44px}
:is(body,.style-preview)[data-style=neumorphism] .layout-cover{padding-top:50px}
:is(body,.style-preview)[data-style=neumorphism] .takeaway{border-left:0;padding-left:0;color:var(--muted)}
:is(body,.style-preview)[data-style=neumorphism] .kpis{gap:20px;margin-top:34px}
:is(body,.style-preview)[data-style=neumorphism] .kpi{border:1px solid #dce3e5;padding:25px;background:var(--paper)}
:is(body,.style-preview)[data-style=neumorphism] .kpi-value{color:var(--ink);font-weight:650}
:is(body,.style-preview)[data-style=neumorphism] .chart-frame{background:#f5f8f7;border:1px solid var(--line);border-radius:16px;padding:28px;box-shadow:none}
:is(body,.style-preview)[data-style=neumorphism] .layout-summary .copy-block{border-top:1px solid var(--line)}

/* 06 / Graphic contrast: hard edges on the cover, quiet data underneath. */
:is(body,.style-preview)[data-style=brutalism]{--bg:#f5f1e8;--paper:#fffdf6;--ink:#20201f;--muted:#56544d;--accent:#2448bf;--line:#252522;--tint:#f4edcf;--cover:#f4d95d;--stroke:2px;--section-radius:0px;--cell-radius:0px;--series-0:#244bc9;--series-1:#ca6752;--series-2:#789166;--series-3:#9974a6}
:is(body,.style-preview)[data-style=brutalism] .report-masthead{border-bottom:2px solid var(--ink);padding-bottom:20px}
:is(body,.style-preview)[data-style=brutalism] .report-name{font-weight:850;text-transform:uppercase}
:is(body,.style-preview)[data-style=brutalism] .report-main{gap:30px}
:is(body,.style-preview)[data-style=brutalism] .section{padding:36px 40px}
:is(body,.style-preview)[data-style=brutalism] .layout-cover{padding-top:42px;box-shadow:7px 7px 0 var(--ink);margin-right:7px;margin-bottom:7px}
:is(body,.style-preview)[data-style=brutalism] .section h2{font-weight:900;letter-spacing:-.045em}
:is(body,.style-preview)[data-style=brutalism] .layout-cover h2{font-size:clamp(38px,5vw,66px);max-width:18ch}
:is(body,.style-preview)[data-style=brutalism] .page-number{display:inline-block;padding:5px 9px;border:1px solid var(--ink);background:var(--paper);color:var(--ink);letter-spacing:.07em}
:is(body,.style-preview)[data-style=brutalism] .takeaway{border-left:0;border-top:2px solid var(--ink);padding:16px 0 0;font-weight:650}
:is(body,.style-preview)[data-style=brutalism] .kpis{gap:12px;margin-top:30px}
:is(body,.style-preview)[data-style=brutalism] .kpi{padding:22px;background:var(--paper)}
:is(body,.style-preview)[data-style=brutalism] .kpi:where(:first-child){background:#2548b8;--ink:#fff;--muted:#e2e9ff;--accent:#fff}
:is(body,.style-preview)[data-style=brutalism] .kpi-value{font-weight:850}
:is(body,.style-preview)[data-style=brutalism] .chart-frame{border-width:1px 0 0;padding:24px 0 8px}
:is(body,.style-preview)[data-style=brutalism] .layout-summary .copy-block{border-top:2px solid var(--ink)}

/* 07 / Mesh: a luminous cover and completely neutral analytical pages. */
:is(body,.style-preview)[data-style=gradient-mesh]{--bg:#f3f4f8;--paper:#fff;--ink:#29304a;--muted:#5a637a;--accent:#6553b5;--line:#dfe3ee;--tint:#f3f2fa;--cover:linear-gradient(100deg,#fff 8%,#ffffffed 40%,#ffffff30 100%),radial-gradient(ellipse at 76% 8%,#e7b6bb,transparent 46%),radial-gradient(ellipse at 95% 62%,#aaa4e4,transparent 48%),radial-gradient(ellipse at 58% 94%,#9dcbd9,transparent 45%),#eff0fa;--section-radius:14px;--cell-radius:10px;--series-0:#7568be;--series-1:#5b9ba6;--series-2:#be7f8b;--series-3:#8c9e67}
:is(body,.style-preview)[data-style=gradient-mesh] .report-masthead{border-bottom:0}
:is(body,.style-preview)[data-style=gradient-mesh] .report-main{gap:24px}
:is(body,.style-preview)[data-style=gradient-mesh] .layout-cover{padding:60px 48px 36px;border-color:#ffffffcc}
:is(body,.style-preview)[data-style=gradient-mesh] .layout-cover h2{max-width:17ch;font-size:clamp(38px,4.8vw,64px)}
:is(body,.style-preview)[data-style=gradient-mesh] .layout-cover .takeaway{border-left:0;padding-left:0;max-width:52ch}
:is(body,.style-preview)[data-style=gradient-mesh] .layout-cover .kpis{margin-top:44px;margin-bottom:8px}
:is(body,.style-preview)[data-style=gradient-mesh] .kpi{border-color:var(--line);background:var(--cell)}
:is(body,.style-preview)[data-style=gradient-mesh] .kpi-value{color:var(--ink);font-weight:700}
:is(body,.style-preview)[data-style=gradient-mesh] .chart-frame{border:0;background:var(--tint)}
:is(body,.style-preview)[data-style=gradient-mesh] .layout-summary .copy-block{border-top:1px solid var(--line)}

/* 08 / Freeform: asymmetry inside useful columns, never empty staggered space. */
:is(body,.style-preview)[data-style=freeform]{--bg:#eef2ec;--paper:#fffdf6;--ink:#29493e;--muted:#5e7066;--accent:#386c58;--line:#ced9ce;--tint:#e9efe4;--cover:linear-gradient(115deg,#fffdf6 0 66%,#dce6ce 66% 100%);--section-radius:4px;--cell-radius:4px;--series-0:#467963;--series-1:#b47d54;--series-2:#92a47b;--series-3:#6b8b9b}
:is(body,.style-preview)[data-style=freeform] .report-masthead{border-bottom:0}
:is(body,.style-preview)[data-style=freeform] .report-main{gap:24px}
:is(body,.style-preview)[data-style=freeform] .section{border-width:0 0 0 5px;border-left-color:var(--accent);padding:38px 44px}
:is(body,.style-preview)[data-style=freeform] .section:where(:nth-child(even)){border-radius:4px 30px 4px 4px}
:is(body,.style-preview)[data-style=freeform] .layout-cover{padding-top:50px;padding-bottom:36px;border-left:0;border-radius:4px 52px 4px 4px}
:is(body,.style-preview)[data-style=freeform] .layout-cover h2{max-width:16ch;font-size:clamp(38px,4.7vw,62px)}
:is(body,.style-preview)[data-style=freeform] .takeaway{border-left:0;padding-left:0;max-width:54ch}
:is(body,.style-preview)[data-style=freeform] .layout-split .section-content{grid-template-columns:minmax(0,1.15fr) minmax(0,.85fr);align-items:start;gap:42px}
:is(body,.style-preview)[data-style=freeform] .layout-split:where(:nth-child(even)) .section-content{grid-template-columns:minmax(0,.8fr) minmax(0,1.2fr)}
:is(body,.style-preview)[data-style=freeform] .layout-summary .copy-block{border-top:0;padding-top:0}
:is(body,.style-preview)[data-style=freeform] .kpis{gap:12px;margin-top:34px}
:is(body,.style-preview)[data-style=freeform] .kpi{border:0;border-top:3px solid var(--accent);background:var(--cell)}
:is(body,.style-preview)[data-style=freeform] .kpi:where(:nth-child(even)){border-top-color:#b7875e;background:var(--tint)}
:is(body,.style-preview)[data-style=freeform] .kpi-value{font-weight:650}
:is(body,.style-preview)[data-style=freeform] .chart-frame{padding:24px;background:var(--tint);border:0;border-radius:4px 26px 4px 4px}

/* 09 / Sculptural: consistent warm light, dimensional objects, flat charts. */
:is(body,.style-preview)[data-style=immersive-3d]{--bg:#e9e2d8;--paper:#f8f4ed;--ink:#443b32;--muted:#71665a;--accent:#9d5e42;--line:#d8cdbf;--tint:#eee7dc;--cover:linear-gradient(120deg,#fbf8f1,#eee4d6);--section-radius:18px;--cell-radius:9px;--panel-shadow:0 10px 25px #65523c0c,inset 0 1px 0 #fff9;--series-0:#a66a48;--series-1:#8d9988;--series-2:#b89c75;--series-3:#84748a}
:is(body,.style-preview)[data-style=immersive-3d] .report-masthead{border-bottom:0}
:is(body,.style-preview)[data-style=immersive-3d] .report-main{gap:30px}
:is(body,.style-preview)[data-style=immersive-3d] .layout-cover{border-color:#e0d4c4;padding-top:48px}
:is(body,.style-preview)[data-style=immersive-3d] .takeaway{border-left:0;padding-left:0;max-width:50ch}
:is(body,.style-preview)[data-style=immersive-3d] .kpis{gap:16px;margin-top:34px}
:is(body,.style-preview)[data-style=immersive-3d] .kpi{border:1px solid #e5dccf;background:var(--cell);box-shadow:0 3px 6px #69513a06,inset 0 1px 0 #fff}
:is(body,.style-preview)[data-style=immersive-3d] .kpi-value{color:var(--ink);font-weight:650}
:is(body,.style-preview)[data-style=immersive-3d] .chart-frame{background:var(--paper);border-width:1px 0 0;border-radius:0;padding:24px 0 8px;box-shadow:none}
:is(body,.style-preview)[data-style=immersive-3d] .layout-summary .copy-block{border-top:1px solid var(--line)}

/* 10 / Refined Y2K: a chrome frame and one orbital ornament, modern reading. */
:is(body,.style-preview)[data-style=retro-y2k]{--bg:#eceef6;--paper:#fbfbff;--ink:#363750;--muted:#62647f;--accent:#756197;--line:#c6cbdc;--tint:#f0edf8;--cover:linear-gradient(125deg,#fbfcff 12%,#eeedf8 70%,#e7effa);--section-radius:15px;--cell-radius:9px;--series-0:#8b75ba;--series-1:#739eb7;--series-2:#bb86a5;--series-3:#939d71}
:is(body,.style-preview)[data-style=retro-y2k] .report-masthead{margin-top:16px;margin-bottom:8px;max-width:1240px;padding:18px 26px;border:1px solid #aeb9cc;border-radius:16px;background:linear-gradient(#fff,#edf1f8 45%,#d4dce9 49%,#f1f5fb 96%);box-shadow:inset 0 1px 0 #fff,0 2px 5px #71839e0c}
:is(body,.style-preview)[data-style=retro-y2k] .report-main{gap:26px}
:is(body,.style-preview)[data-style=retro-y2k] .section{border-color:#bdc5d6;padding-top:30px;box-shadow:inset 0 1px 0 #fff}
:is(body,.style-preview)[data-style=retro-y2k] .section::before{content:'';display:block;height:5px;margin:-8px 0 28px;background:linear-gradient(90deg,#c2d9ed,#dad1eb 54%,#e6cedd);border-radius:9px}
:is(body,.style-preview)[data-style=retro-y2k] .layout-cover{padding-top:32px}
:is(body,.style-preview)[data-style=retro-y2k] .page-number{letter-spacing:.09em}
:is(body,.style-preview)[data-style=retro-y2k] .takeaway{border-left:0;padding-left:0}
:is(body,.style-preview)[data-style=retro-y2k] .kpis{gap:14px;margin-top:34px}
:is(body,.style-preview)[data-style=retro-y2k] .kpi{background:var(--cell);border-color:var(--line);border-top:3px solid #c4b5df;padding:23px}
:is(body,.style-preview)[data-style=retro-y2k] .kpi:where(:nth-child(even)){border-top-color:#adc7df}
:is(body,.style-preview)[data-style=retro-y2k] .kpi-value{font-weight:650;color:var(--ink)}
:is(body,.style-preview)[data-style=retro-y2k] .chart-frame{background:var(--paper);box-shadow:none}
:is(body,.style-preview)[data-style=retro-y2k] .layout-summary .copy-block{border-top:1px solid var(--line)}

/* Data-free cover artwork. It has a real grid area, so it cannot overlap copy. */
.theme-art{display:none;pointer-events:none}
:is(body,.style-preview)[data-style] .layout-cover:where(.has-theme-art){display:grid;grid-template-columns:minmax(0,1.35fr) minmax(180px,.65fr);column-gap:36px;align-items:start}
:is(body,.style-preview)[data-style] .layout-cover:where(.has-theme-art)>*{grid-column:1/-1}
:is(body,.style-preview)[data-style] .layout-cover:where(.has-theme-art)>:is(.page-number,h2,.takeaway){grid-column:1}
:is(body,.style-preview)[data-style] .layout-cover:where(.has-theme-art)::before{grid-column:1/-1}
:is(body,.style-preview)[data-style] .layout-cover:where(.has-theme-art) h2{max-width:none}
:is(body,.style-preview)[data-style] .theme-art{display:block;position:relative;grid-column:2;grid-row:1/4;align-self:center;width:100%;height:250px;isolation:isolate}
:is(body,.style-preview)[data-style] .theme-art i{position:absolute;display:block}
:is(body,.style-preview)[data-style=editorial] .theme-art{height:235px;border-left:1px solid var(--line)}
:is(body,.style-preview)[data-style=editorial] .theme-art i:nth-child(1){inset:10% 2% 10% 14%;background:var(--accent);border-radius:50% 50% 0 0;transform:rotate(-8deg)}
:is(body,.style-preview)[data-style=editorial] .theme-art i:nth-child(2){inset:24% 14% 0 24%;background:repeating-linear-gradient(0deg,transparent 0 8px,#fcfaf57a 8px 9px);border:1px solid #fcfaf57a;transform:rotate(8deg)}
:is(body,.style-preview)[data-style=editorial] .theme-art i:nth-child(3){width:40%;height:39%;right:-1%;top:2%;border:12px solid #bfad80;border-radius:50%;mix-blend-mode:multiply}
:is(body,.style-preview)[data-style=immersive-3d] .theme-art{height:260px}
:is(body,.style-preview)[data-style=immersive-3d] .theme-art::before{content:'';position:absolute;inset:77% -3% 1%;background:radial-gradient(ellipse,#7a624b2e,transparent 69%);transform:rotate(-10deg)}
:is(body,.style-preview)[data-style=immersive-3d] .theme-art i:nth-child(1){width:60%;aspect-ratio:1;top:5%;left:9%;border:26px solid #bd7956;border-radius:50%;box-shadow:inset 5px 5px 7px #653b242f,inset -6px -5px 7px #f7d8ba8c,5px 8px 11px #68503a26;transform:rotate(-20deg) skewY(-8deg);background:transparent}
:is(body,.style-preview)[data-style=immersive-3d] .theme-art i:nth-child(2){width:45%;height:64%;right:3%;top:27%;border-radius:100px;background:linear-gradient(115deg,#fff9e8,#ded0b9 58%,#b7a489);box-shadow:7px 11px 12px #745d4024,inset 2px 1px 3px #fff;transform:rotate(32deg)}
:is(body,.style-preview)[data-style=immersive-3d] .theme-art i:nth-child(3){width:35%;aspect-ratio:1;left:4%;bottom:6%;border-radius:50%;background:radial-gradient(circle at 28% 23%,#b4bba9,#7f8b75 60%,#5d6b57);box-shadow:6px 10px 12px #6c5b4024}
:is(body,.style-preview)[data-style=retro-y2k] .theme-art{height:235px}
:is(body,.style-preview)[data-style=retro-y2k] .layout-cover:where(.has-theme-art)::before{grid-row:1}
:is(body,.style-preview)[data-style=retro-y2k] .layout-cover:where(.has-theme-art) .theme-art{grid-row:2/5}
:is(body,.style-preview)[data-style=retro-y2k] .theme-art i:nth-child(1){inset:4% 12% 12%;background:conic-gradient(from 40deg,#fff,#a3acc5,#eef4ff,#8e9db7,#fff,#c7b4da,#fff);clip-path:polygon(50% 0,60% 34%,86% 14%,67% 42%,100% 50%,67% 60%,86% 86%,60% 68%,50% 100%,40% 67%,14% 86%,33% 60%,0 50%,33% 40%,14% 14%,40% 33%)}
:is(body,.style-preview)[data-style=retro-y2k] .theme-art i:nth-child(2){width:98%;height:32%;top:37%;left:1%;border:7px solid #b7a8ce;border-top-color:#e9e4f1;border-bottom-color:#867699;border-radius:50%;transform:rotate(-25deg);box-shadow:0 3px 2px #8e90a11a}
:is(body,.style-preview)[data-style=retro-y2k] .theme-art i:nth-child(3){width:12%;aspect-ratio:1;top:12%;right:4%;border-radius:50%;background:radial-gradient(circle at 28% 20%,#fff,#b8c9df 60%,#8397b5)}
body[data-style][data-length=short][data-view=scroll]:not([data-reference-style]) .layout-cover.has-theme-art{display:block}
/* The page controller reveals active sections with display:block. Restore only
   the active decorative cover's desktop grid; inactive pages stay hidden. */
@media screen and (min-width:761px){
 body.report-ready[data-style][data-view=slides] main>.layout-cover.has-theme-art.active{display:grid}
}

/* User-observed palette roles win even on the theme's local accent surfaces. */
body[data-style][data-reference-style] .section{border-color:var(--line)}
body[data-style][data-reference-style] .chart-frame{background:var(--cell);border-color:var(--line)}
body[data-style][data-reference-style] .kpi{border-color:var(--line)}

/* The default glass surfaces already have a high-opacity text backing. */
@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){
 :is(body,.style-preview)[data-style=glassmorphism] :is(.section,.layout-cover,.report-masthead){background:var(--paper)!important}
}
@media(prefers-reduced-transparency:reduce){
 :is(body,.style-preview)[data-style=glassmorphism] :is(.section,.layout-cover,.kpi,.chart-frame,.report-masthead){background:var(--paper)!important;backdrop-filter:none;-webkit-backdrop-filter:none}
}

/* Previews represent the same desktop composition, irrespective of page width.
   Only actual reports use viewport rules; miniature scaling belongs to picker. */
@media(max-width:1000px){
 body[data-style][data-view] .section{padding:34px 32px}
 body[data-style][data-view] .layout-cover{padding-top:42px;padding-bottom:32px}
 body[data-style][data-view] .layout-cover.has-theme-art{grid-template-columns:minmax(0,1.4fr) minmax(160px,.6fr);column-gap:22px}
 body[data-style][data-view] .theme-art{height:210px}
 body[data-style][data-view] .kpi{padding:22px 18px}
 body[data-style=bento-grid][data-view] .kpis[data-kpi-count="3"] .kpi{grid-column:span 4}
}
@media(max-width:760px){
 body[data-style][data-view] .report-main{grid-template-columns:minmax(0,1fr)!important;padding:12px 20px 36px;gap:22px}
 body[data-style][data-view] .report-masthead{margin:0 20px 8px;padding:20px 0 16px;display:block;border-radius:0}
 body[data-style][data-view] .report-masthead nav{flex-wrap:wrap;gap:8px;margin-top:14px}
 body[data-style=glassmorphism][data-view] .report-masthead,body[data-style=retro-y2k][data-view] .report-masthead{margin-top:12px;padding:16px 18px;border-radius:16px}
 body[data-style][data-view] .section{padding:28px 24px}
 body[data-style][data-view] .layout-cover{padding:34px 24px 28px}
 body[data-style][data-view] .layout-cover.has-theme-art{display:block}
 body[data-style][data-view] .theme-art{display:none}
 body[data-style][data-view] .section h2{font-size:clamp(27px,4.4vw,34px);max-width:none}
 body[data-style][data-view] .layout-cover h2{font-size:clamp(34px,6vw,44px);max-width:none}
 body[data-style][data-view] .takeaway{font-size:17px}
 body[data-style][data-view] .layout-split .section-content{display:block}
 body[data-style][data-view] .kpis[data-kpi-count]{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
 body[data-style][data-view] .kpis[data-kpi-count] .kpi{grid-column:auto;padding:20px 18px}
 body[data-style][data-view] .kpis[data-kpi-count] .kpi:where(:last-child:nth-child(odd)){grid-column:1/-1}
 body[data-style][data-view] .kpi-value{font-size:32px}
 body[data-style][data-view] .kpi-unit{display:block;margin:5px 0 0}
 body[data-style][data-view] .chart-frame{padding:18px 12px}
 body[data-style=minimalism][data-view] .kpis,body[data-style=editorial][data-view] .kpis{gap:0}
 body[data-style=minimalism][data-view] .kpi,body[data-style=editorial][data-view] .kpi{border-width:0 0 1px 1px}
 body[data-style=neumorphism][data-view] .report-main{gap:28px}
 body[data-style=neumorphism][data-view] .section{box-shadow:6px 6px 15px #cbd3d580,-6px -6px 15px #ffffff9c}
 body[data-style=brutalism][data-view] .layout-cover{box-shadow:4px 4px 0 var(--ink);margin-right:4px;margin-bottom:4px}
 body[data-style=freeform][data-view] .layout-cover{border-radius:4px 32px 4px 4px}
}
@media(max-width:520px){
 body[data-style][data-view] .report-main{padding-left:14px;padding-right:14px;gap:18px}
 body[data-style][data-view] .report-masthead{margin-left:14px;margin-right:14px}
 body[data-style][data-view] .section{padding:26px 20px}
 body[data-style][data-view] .layout-cover{padding:30px 20px 24px}
 body[data-style][data-view] .section h2{font-size:27px}
 body[data-style][data-view] .layout-cover h2{font-size:34px}
 body[data-style][data-view] .kpis[data-kpi-count]{grid-template-columns:minmax(0,1fr);gap:12px;margin-top:26px}
 body[data-style][data-view] .kpis[data-kpi-count] .kpi{grid-column:1/-1;padding:20px}
 body[data-style][data-view] .kpi-value{font-size:36px}
 body[data-style][data-view] .kpi-unit{display:inline-block;margin-left:5px}
 body[data-style=minimalism][data-view] .kpis,body[data-style=editorial][data-view] .kpis{gap:0}
 body[data-style=minimalism][data-view] .kpis .kpi,body[data-style=editorial][data-view] .kpis .kpi{border-width:0 0 1px;padding-left:0;padding-right:0}
 body[data-style=minimalism][data-view] .kpis .kpi:last-child,body[data-style=editorial][data-view] .kpis .kpi:last-child{border-bottom:0}
 body[data-style=neumorphism][data-view] .section{padding:26px 20px}
}
@media print{
 :is(body,.style-preview)[data-style]{background:white!important;--ink:#172132;--muted:#344154;--accent:#172132;--line:#b8bfc6;--paper:#fff;--surface:#fff;--cell:#fff;--cover:#fff}
 body[data-style][data-view] .report-main{display:block!important;padding:0;gap:0}
 body[data-style][data-view] .report-masthead{margin:0 0 16px;padding:0 0 12px;background:white!important;color:#172132!important;border:0;border-bottom:1px solid #bbb;border-radius:0;box-shadow:none!important;backdrop-filter:none!important;-webkit-backdrop-filter:none!important}
 body[data-style][data-view] .report-masthead .subtitle{color:#344154!important}
 body[data-style][data-view] .section{display:block!important;margin:0 0 24px!important;padding:24px;min-height:0!important;border-radius:0;break-inside:auto}
 :is(body,.style-preview)[data-style] :is(.section,.layout-cover,.kpi,.chart-frame){box-shadow:none!important;backdrop-filter:none!important;-webkit-backdrop-filter:none!important;background:white!important;border-color:#bbb}
 body[data-style][data-view] .layout-cover{padding:24px}
 body[data-style][data-view] .theme-art,body[data-style][data-view] .section::before{display:none!important}
 body[data-style][data-view] .section h2{font-size:28px;max-width:none}
 body[data-style][data-view] .layout-cover h2{font-size:36px;max-width:none}
 body[data-style][data-view] .layout-split .section-content{display:block!important}
 body[data-style][data-view] .kpis[data-kpi-count]{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:24px 0}
 body[data-style][data-view] .kpis[data-kpi-count] .kpi{grid-column:auto;padding:16px;--ink:#172132;--muted:#344154;--accent:#172132;break-inside:avoid}
 body[data-style][data-view] .kpis[data-kpi-count] .kpi:where(:last-child:nth-child(odd)){grid-column:1/-1}
 body[data-style][data-view] .kpi-value{font-size:30px;color:#172132}
 body[data-style][data-view] .chart-frame{padding:16px 0;overflow:visible;break-inside:avoid}
 body[data-style][data-view] .report-chart{min-width:0;max-height:340px}
}
'''
