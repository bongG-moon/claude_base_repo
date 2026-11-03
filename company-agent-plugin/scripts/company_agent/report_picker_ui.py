"""Presentation styles for the local HTML report gallery.

Keep gallery rules scoped to its own elements. The report specimens retain their
renderer and theme styles, with only their viewport geometry adjusted here.
"""

CSS = r'''
body.picker{
  --picker-bg:#f6f5f2;--picker-paper:#fff;--picker-ink:#1c252d;
  --picker-muted:#646e72;--picker-line:#dddfda;--picker-accent:#215c56;
  --picker-accent-soft:#edf4f0;--picker-focus:#327a72;
  margin:0;background:var(--picker-bg);color:var(--picker-ink);
  font:15px/1.6 "Pretendard","Noto Sans KR","Malgun Gothic",sans-serif;
  -webkit-font-smoothing:antialiased;
}
.picker .picker-header{
  display:flex;align-items:center;justify-content:space-between;gap:24px;
  max-width:1560px;margin:0 auto;padding:22px 40px;
  border-bottom:1px solid var(--picker-line);
}
.picker .picker-brand{
  display:inline-flex;align-items:center;gap:11px;min-height:44px;
  color:var(--picker-ink);text-decoration:none;font-size:14px;font-weight:750;
  letter-spacing:-.02em;
}
.picker .picker-brand-mark{
  display:grid;place-items:center;width:29px;height:33px;border:1px solid currentColor;
  border-radius:3px;color:var(--picker-accent);font-size:12px;font-weight:700;
}
.picker .picker-nav{
  display:flex;align-items:center;gap:26px;flex-wrap:wrap;margin:0;
}
.picker .picker-nav a{
  display:inline-flex;align-items:center;min-height:44px;color:var(--picker-muted);
  font-size:13px;font-weight:600;text-decoration:none;text-underline-offset:5px;
}
.picker .picker-nav a:hover{color:var(--picker-accent);text-decoration:underline}
.picker .picker-wrap{max-width:1560px;margin:0 auto;padding:0 40px 40px}
.picker :is(.picker-hero,.section-heading,.design-card-copy,.reference-card-copy,.template-copy,.selection-panel,.picker-footer) p{white-space:normal}
.picker .picker-hero{
  display:flex;align-items:flex-end;justify-content:space-between;gap:40px;
  max-width:none;margin:0;padding:60px 0 44px;
}
.picker .picker-kicker,.picker .section-kicker,.picker .selection-kicker{
  margin:0 0 12px;font-size:12px;line-height:1.4;letter-spacing:.12em;
  font-weight:750;text-transform:uppercase;color:var(--picker-accent);
}
.picker .picker-hero h1{
  margin:0;font-size:clamp(34px,3.6vw,50px);font-weight:730;line-height:1.18;
  letter-spacing:-.055em;word-break:keep-all;overflow-wrap:anywhere;
}
.picker .picker-hero .intro,.picker .picker-hero .hero-description{
  max-width:660px;margin:18px 0 0;color:var(--picker-muted);font-size:16px;
  line-height:1.8;letter-spacing:-.015em;word-break:keep-all;overflow-wrap:anywhere;
}
.picker .hero-meta{
  display:flex;flex:0 0 auto;gap:28px;padding:0 0 4px;color:var(--picker-muted);
  font-size:12px;line-height:1.6;
}
.picker .hero-meta>div,.picker .hero-meta>span{display:flex;flex-direction:column;gap:4px}
.picker .hero-meta strong{
  display:block;color:var(--picker-ink);font-size:27px;line-height:1.25;
  font-weight:650;letter-spacing:-.045em;font-variant-numeric:tabular-nums;
}
.picker .hero-meta small{font-size:12px}
.picker .flow-steps{
  display:flex;flex-wrap:wrap;gap:12px 24px;margin:22px 0 0;padding:0;
  list-style:none;font-size:12px;color:var(--picker-muted);
}
.picker .flow-steps li{display:flex;align-items:center;gap:8px}
.picker .flow-steps b{font-size:12px;color:var(--picker-accent);font-variant-numeric:tabular-nums}
.picker .picker-workspace{
  display:grid;grid-template-columns:minmax(0,1fr) 300px;
  grid-template-areas:"gallery selection";gap:40px;align-items:start;
}
.picker .picker-gallery{grid-area:gallery;min-width:0;max-width:none;margin:0;padding:0}
.picker .picker-gallery>section{min-width:0;margin:0 0 52px;scroll-margin-top:24px}
.picker .section-heading{
  display:flex;justify-content:space-between;align-items:flex-end;gap:20px;
  max-width:none;margin:0 0 20px;padding:0;
}
.picker .section-heading .section-kicker{margin-bottom:7px}
.picker .section-heading h2{
  margin:0;font-size:23px;line-height:1.35;font-weight:700;letter-spacing:-.035em;
  word-break:keep-all;overflow-wrap:anywhere;
}
.picker .section-heading p:not(.section-kicker){
  margin:8px 0 0;color:var(--picker-muted);font-size:14px;line-height:1.7;
  word-break:keep-all;overflow-wrap:anywhere;
}
.picker .section-count{
  flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;
  min-width:30px;height:25px;padding:0 8px;border:1px solid var(--picker-line);
  border-radius:20px;color:var(--picker-muted);font-size:12px;font-variant-numeric:tabular-nums;
}
.picker .design-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}
.picker .design-card,.picker .reference-card{
  display:flex;flex-direction:column;min-width:0;background:var(--picker-paper);
  border:1px solid var(--picker-line);border-radius:12px;overflow:hidden;
  transition:border-color 160ms ease,box-shadow 160ms ease;
}
.picker .design-card:hover,.picker .reference-card:hover{
  border-color:#b5bdb8;box-shadow:0 8px 24px #1c252d07;
}
.picker .design-card[data-selected=true],.picker .reference-card[data-selected=true]{
  border-color:var(--picker-accent);box-shadow:0 0 0 1px var(--picker-accent),0 7px 20px #215c560b;
}
.picker .design-card-copy{
  display:flex;flex:1;flex-direction:column;align-items:stretch;padding:22px 24px 24px;
}
.picker .design-card-copy .design-index{
  display:flex;align-items:center;justify-content:space-between;gap:8px;
  margin:0 0 8px;color:var(--picker-muted);font-size:12px;line-height:1.6;
  font-weight:650;letter-spacing:.075em;overflow-wrap:anywhere;
}
.picker .design-card-copy h3{
  margin:0 0 10px;font-size:23px;line-height:1.3;font-weight:700;
  letter-spacing:-.035em;word-break:keep-all;overflow-wrap:anywhere;
}
.picker .design-card-copy>p:not(.design-index){
  margin:0 0 12px;color:#525e62;font-size:14px;line-height:1.8;
  letter-spacing:-.01em;word-break:keep-all;overflow-wrap:anywhere;
}
.picker .design-card-copy>p.design-use{color:var(--picker-muted);font-size:12px;margin-bottom:16px}
.picker .design-source{
  margin:0 0 16px;padding-top:3px;border-top:1px solid #eceee9;
  color:var(--picker-muted);font-size:12px;line-height:1.75;
}
.picker .design-source summary{
  display:list-item;min-height:44px;padding:11px 0;cursor:pointer;
  font-size:12px;list-style-position:inside;overflow-wrap:anywhere;
}
.picker .design-source summary::marker{color:#87938e;font-size:12px}
.picker .design-source p{margin:0 0 10px;word-break:keep-all;overflow-wrap:anywhere}
.picker .design-source a{color:var(--picker-accent);text-underline-offset:3px}
.picker .design-actions{
  display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;
  gap:10px 16px;margin-top:auto;
}
.picker .example-link{
  display:inline-flex;align-items:center;min-height:44px;color:var(--picker-muted);
  font-size:12px;font-weight:600;text-decoration:none;text-underline-offset:4px;
}
.picker .example-link:hover{color:var(--picker-accent);text-decoration:underline}
.picker [data-choice],.picker .selection-panel button{
  display:inline-flex;align-items:center;justify-content:center;gap:8px;
  min-height:44px;max-width:100%;padding:11px 16px;border:1px solid #d1d8d2;
  border-radius:7px;background:#fff;color:var(--picker-ink);
  font:600 12px/1.5 "Pretendard","Noto Sans KR","Malgun Gothic",sans-serif;
  letter-spacing:-.01em;white-space:normal;word-break:keep-all;overflow-wrap:anywhere;
  cursor:pointer;transition:background 160ms ease,border-color 160ms ease,color 160ms ease;
}
.picker [data-choice]:hover{background:var(--picker-accent-soft);border-color:#8aa99b}
.picker [data-choice][aria-pressed=true]{
  border-color:var(--picker-accent);background:var(--picker-accent);color:#fff;
}
.picker [data-choice][aria-pressed=true]::before{content:"\2713";font-size:13px;font-weight:700}
.picker .mini-window{
  position:relative;width:100%;min-width:0;aspect-ratio:1.55;overflow:hidden;
  border-bottom:1px solid #e5e7e1;background:#eeefeb;pointer-events:none;
}
.picker .mini-window>.style-preview{
  position:absolute;top:0;left:0;width:960px;min-height:0;padding:30px;
  box-sizing:border-box;transform:scale(.5);transform-origin:top left;
}
.picker .style-preview .section{margin:0}
.picker .style-preview .report-main{padding:0}
.picker .style-preview .report-chart{min-width:0}
.picker .style-preview .chart-values{display:none}
.picker .style-preview .report-masthead{padding:16px 20px;margin:0 0 20px;font-size:14px}
.picker .style-preview .report-masthead .report-name{font-size:16px}
.picker .style-preview .layout-cover .kpi-unit{white-space:nowrap}
.picker .style-preview[data-style]{--preview-font:"Noto Sans KR","Malgun Gothic",sans-serif;font-family:var(--preview-font)}
.picker .style-preview:is([data-style=bento-grid],[data-style=glassmorphism],[data-style=neumorphism]){--preview-font:"Pretendard","Noto Sans KR","Malgun Gothic",sans-serif}
.picker .style-preview[data-style] :is(h1,h2,h3,h4,h5,p,li,td,th,button,svg text){font-family:var(--preview-font)!important}
.picker .reference-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}
.picker .reference-card-copy{
  display:flex;flex:1;flex-direction:column;align-items:stretch;padding:19px 18px 20px;
}
.picker .reference-card-copy h3,.picker .reference-card>h3{
  margin:0 0 10px;font-size:17px;line-height:1.4;font-weight:700;letter-spacing:-.025em;
  word-break:keep-all;overflow-wrap:anywhere;
}
.picker .reference-card-copy>p,.picker .reference-card>p{
  flex:1;margin:0 0 14px;color:var(--picker-muted);font-size:14px;
  line-height:1.8;word-break:keep-all;overflow-wrap:anywhere;
}
.picker .reference-card .example-link{margin-bottom:8px;font-size:12px}
.picker .reference-card [data-choice]{width:100%}
.picker .template-callout{
  display:flex;align-items:center;gap:20px;padding:24px;border:1px solid var(--picker-line);
  border-radius:10px;background:#eeefea;
}
.picker .template-icon{
  flex:0 0 auto;display:grid;place-items:center;width:40px;height:46px;
  border:1px solid #a6b2a8;border-radius:4px;color:var(--picker-accent);font-size:14px;
}
.picker .template-copy{flex:1;min-width:0}
.picker .template-callout h3{
  margin:0 0 5px;font-size:16px;line-height:1.4;letter-spacing:-.025em;
  word-break:keep-all;overflow-wrap:anywhere;
}
.picker .template-callout p{
  margin:0;color:var(--picker-muted);font-size:14px;line-height:1.8;
  word-break:keep-all;overflow-wrap:anywhere;
}
.picker .template-callout[data-selected=true]{border-color:var(--picker-accent);background:var(--picker-accent-soft)}
.picker .template-callout [data-choice]{flex:0 0 auto}
.picker .selection-panel{
  grid-area:selection;position:sticky;top:24px;min-width:0;margin:0;padding:24px;
  border:1px solid #d8ddd6;border-radius:12px;background:#fff;
  box-shadow:0 6px 24px #1c252d04;scroll-margin-top:24px;
}
.picker .selection-panel .selection-kicker{margin-bottom:18px}
.picker .selected-style-marker{
  display:inline-flex;align-items:center;gap:7px;margin:0 0 8px;color:var(--picker-accent);
  font-size:12px;line-height:1.5;font-weight:650;
}
.picker .selected-style-marker::before{
  content:"";width:6px;height:6px;border-radius:50%;background:currentColor;
}
.picker .selection-panel h2{
  margin:0;color:var(--picker-ink);font-size:21px;line-height:1.45;font-weight:700;
  letter-spacing:-.035em;word-break:keep-all;overflow-wrap:anywhere;
}
.picker .selection-hint{
  margin:9px 0 0;color:var(--picker-muted);font-size:12px;line-height:1.7;
  word-break:keep-all;overflow-wrap:anywhere;
}
.picker .choice-fields{display:flex;flex-direction:column;gap:15px;margin:22px 0 0}
.picker .choice-fields+.choice-fields{margin-top:15px}
.picker .choice-fields label{
  display:flex;flex-direction:column;gap:7px;min-width:0;color:#57615e;
  font-size:12px;line-height:1.5;font-weight:650;
}
.picker .choice-fields :is(select,input){
  width:100%;min-width:0;max-width:100%;min-height:44px;margin:0;padding:10px 11px;
  border:1px solid #d8ded7;border-radius:6px;background:#fff;color:var(--picker-ink);
  font:400 12px/1.5 "Pretendard","Noto Sans KR","Malgun Gothic",sans-serif;
}
.picker .choice-fields select{cursor:pointer;padding-right:5px}
.picker .choice-fields input::placeholder{color:#818b84}
.picker .choice-fields [hidden]{display:none}
.picker .selection-panel .note{
  margin:12px 0 0;color:var(--picker-muted);font-size:12px;line-height:1.75;
  word-break:keep-all;overflow-wrap:anywhere;
}
.picker .selection-panel #copy-choice{
  width:100%;min-height:46px;margin:23px 0 0;border-color:var(--picker-accent);
  border-radius:7px;background:var(--picker-accent);color:#fff;font-size:13px;
}
.picker .selection-panel #copy-choice:hover{border-color:#194a45;background:#194a45}
.picker .selection-panel #copy-status{
  min-height:2.8em;margin:10px 0 0;color:var(--picker-muted);font-size:12px;
  line-height:1.7;word-break:keep-all;overflow-wrap:anywhere;
}
.picker .prompt-details{margin:17px 0 0;padding-top:8px;border-top:1px solid #e7eae3}
.picker .prompt-details>summary{
  min-height:44px;padding:10px 0;color:var(--picker-muted);font-size:12px;
  line-height:1.7;cursor:pointer;list-style-position:inside;
}
.picker .prompt-details label{display:block;margin:3px 0 8px;color:var(--picker-muted);font-size:12px}
.picker .prompt-details textarea{
  display:block;width:100%;min-height:190px;max-width:100%;margin:0;padding:12px;
  border:1px solid #d8ded7;border-radius:6px;background:#f8f9f6;color:#46534c;
  font:14px/1.8 "Pretendard","Noto Sans KR","Malgun Gothic",sans-serif;
  resize:vertical;overflow-wrap:anywhere;
}
.picker .selection-panel noscript{display:block;margin:14px 0 0;color:var(--picker-muted);font-size:12px}
.picker .picker-footer{
  display:flex;justify-content:space-between;gap:16px;max-width:none;margin:0;
  padding:22px 0 0;border-top:1px solid var(--picker-line);color:var(--picker-muted);
  font-size:12px;line-height:1.7;word-break:keep-all;overflow-wrap:anywhere;
}
.picker .picker-footer p{margin:0}
.picker .picker-nav a:focus-visible,.picker .picker-brand:focus-visible,
.picker .example-link:focus-visible,.picker .design-source a:focus-visible,
.picker [data-choice]:focus-visible,.picker .selection-panel button:focus-visible,
.picker .design-source summary:focus-visible,.picker .prompt-details summary:focus-visible,
.picker .choice-fields :is(select,input):focus-visible,.picker .prompt-details textarea:focus-visible{
  outline:3px solid var(--picker-focus);outline-offset:4px;
}
@media(min-width:1280px){
  .picker .selection-panel{max-height:calc(100vh - 48px);max-height:calc(100dvh - 48px);overflow-y:auto;scrollbar-width:thin;scrollbar-color:#b4c2b8 transparent}
}
@media(min-width:760px) and (max-width:1279px){
  .picker .selection-panel{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);column-gap:28px}
  .picker .selection-panel>.selection-kicker{grid-column:1/-1;margin-bottom:12px}
  .picker .selection-panel>.selection-heading{grid-column:1;grid-row:2/5}
  .picker .selection-panel>.choice-fields{grid-column:2;margin-top:0;margin-bottom:15px}
  .picker .selection-panel>.note{grid-column:2;margin-top:0;margin-bottom:10px}
  .picker .selection-panel>#copy-choice{grid-column:1;margin-top:0;align-self:start}
  .picker .selection-panel>#copy-status{grid-column:1}
  .picker .selection-panel>.prompt-details{grid-column:2;grid-row:6/9;align-self:start;margin-top:0}
}
@media(max-width:1279px){
  .picker .picker-header{padding-left:32px;padding-right:32px}
  .picker .picker-wrap{padding-left:32px;padding-right:32px}
  .picker .picker-hero{padding-top:44px;padding-bottom:34px}
  .picker .picker-workspace{grid-template-columns:minmax(0,1fr);grid-template-areas:"selection" "gallery";gap:36px}
  .picker .selection-panel{position:static}
}
@media(max-width:999px){
  .picker .picker-hero{display:block}
  .picker .hero-meta{margin-top:24px;gap:26px}
  .picker .hero-meta>div,.picker .hero-meta>span{flex-direction:row;align-items:baseline;gap:8px}
  .picker .hero-meta strong{font-size:21px}
  .picker .reference-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:759px){
  .picker .picker-header{gap:12px;padding:14px 20px}
  .picker .picker-nav{gap:12px}
  .picker .picker-nav a{font-size:12px}
  .picker .picker-wrap{padding:0 20px 28px}
  .picker .picker-hero{padding:34px 0 30px}
  .picker .picker-hero h1{font-size:35px}
  .picker .picker-hero .intro,.picker .picker-hero .hero-description{font-size:14px;line-height:1.8;margin-top:15px}
  .picker .hero-meta{flex-wrap:wrap;gap:10px 22px;margin-top:20px}
  .picker .picker-workspace{gap:32px}
  .picker .selection-panel{padding:22px}
  .picker .selection-panel .selection-kicker{margin-bottom:12px}
  .picker .selection-panel h2{font-size:20px}
  .picker .choice-fields{gap:13px;margin-top:18px}
  .picker .selection-panel #copy-choice{margin-top:20px}
  .picker .selection-panel #copy-status{min-height:0}
  .picker .section-heading{gap:14px;margin-bottom:17px}
  .picker .section-heading h2{font-size:21px}
  .picker .section-heading p:not(.section-kicker){font-size:14px}
  .picker .design-grid{grid-template-columns:minmax(0,1fr);gap:20px}
  .picker .design-card-copy{padding:21px}
  .picker .design-card-copy h3{font-size:22px}
  .picker .picker-gallery>section{margin-bottom:38px}
  .picker .reference-grid{grid-template-columns:minmax(0,1fr);gap:20px}
  .picker .reference-card-copy{padding:21px}
  .picker .reference-card-copy h3{font-size:19px}
  .picker .reference-card-copy>p{font-size:14px}
  .picker .reference-card .example-link{font-size:12px}
  .picker .template-callout{flex-wrap:wrap;gap:14px;padding:21px}
  .picker .template-callout [data-choice]{width:100%}
  .picker .picker-footer{flex-direction:column;gap:6px;padding-top:20px}
}
@media(max-width:420px){
  .picker .picker-header{flex-wrap:wrap;gap:0;padding:12px 18px}
  .picker .picker-brand{font-size:13px}
  .picker .picker-nav{margin-left:auto;gap:10px}
  .picker .picker-wrap{padding-left:18px;padding-right:18px}
  .picker .picker-hero h1{font-size:32px}
  .picker .hero-meta{font-size:12px}
  .picker .selection-panel{padding:20px}
  .picker .design-card-copy{padding:20px}
  .picker .design-actions{gap:8px}
  .picker .design-actions [data-choice]{padding-left:12px;padding-right:12px}
}
@media(prefers-reduced-motion:reduce){
  .picker .design-card,.picker .reference-card,.picker [data-choice],.picker .selection-panel button{transition:none}
}
@media print{
  .picker .picker-nav,.picker .selection-panel,.picker [data-choice]{display:none!important}
  .picker .picker-workspace{display:block}.picker .picker-wrap{max-width:none;padding:0}
  .picker .picker-hero{padding-top:20px}.picker .design-card,.picker .reference-card{break-inside:avoid;box-shadow:none}
  .picker .mini-window{break-inside:avoid}.picker .picker-footer{display:block!important}
}
'''
