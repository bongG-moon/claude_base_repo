"""Offline, data-only HTML layouts and accessible SVG charts. No third-party code."""
from __future__ import annotations
import base64
import hashlib
import html
import math

PALETTE = tuple(f"var(--series-{i},{color})" for i, color in enumerate(("#246858", "#c35b36", "#4664a5", "#92529b", "#977018", "#53656f")))
esc = lambda text: html.escape(str(text), quote=True)


def svg_chart(chart: dict, index: int) -> str:
    categories, series = chart["categories"], chart["series"]
    kind = chart["type"]
    parts = []
    width, height = 800, max(340, len(categories) * 38 + 80) if kind == "bar" else 360
    title = f"chart-title-{index}"
    parts.append(f'<svg class="report-chart" viewBox="0 0 {width} {height}" role="img" aria-labelledby="{title}" xmlns="http://www.w3.org/2000/svg"><title id="{title}">{esc(chart.get("title") or "지표 비교")} — 수치는 아래 원자료에서 확인</title>')
    values = [v for s in series for v in s["values"]]
    low, high = min(0, min(values)), max(0, max(values))
    if high == low:
        high = 1
    if kind == "pie":
        total = sum(values)
        angle = -math.pi / 2
        for i, value in enumerate(values):
            if value == 0:
                continue
            delta = value / total * math.tau
            label = esc(f"{categories[i]}: {value:g} ({value / total * 100:.1f}%)")
            color = PALETTE[i % len(PALETTE)]
            if delta >= math.tau - 1e-10:
                parts.append(f'<circle cx="205" cy="172" r="125" fill="{color}"><title>{label}</title></circle>')
            else:
                x1, y1 = 205 + 125 * math.cos(angle), 172 + 125 * math.sin(angle)
                x2, y2 = 205 + 125 * math.cos(angle + delta), 172 + 125 * math.sin(angle + delta)
                parts.append(f'<path d="M205,172 L{x1:.3f},{y1:.3f} A125,125 0 {int(delta > math.pi)},1 {x2:.3f},{y2:.3f} Z" fill="{color}" stroke="white" stroke-width="2"><title>{label}</title></path>')
            angle += delta
        parts.append('<circle cx="205" cy="172" r="72" fill="var(--paper)"/>')
        parts.append(f'<text x="205" y="174" text-anchor="middle" class="chart-total">{total:g}</text><text x="205" y="200" text-anchor="middle">합계</text>')
        # Long category sets remain fully available in the accessible data table.
        for i, value in enumerate(values[:8]):
            label = categories[i][:17] + ("…" if len(categories[i]) > 17 else "")
            parts.append(f'<rect x="420" y="{38+i*33}" width="10" height="10" rx="3" fill="{PALETTE[i % 6]}"/><text x="445" y="{48+i*33}">{esc(label)} · {value / total * 100:.1f}%</text>')
        if len(values) > 8:
            parts.append('<text x="445" y="325">전체 항목은 원자료 펼치기</text>')
    elif kind == "bar":
        x = lambda v: 150 + (v - low) / (high - low) * 580
        for tick in range(5):
            value = low + (high - low) * tick / 4
            pos = x(value)
            parts.append(f'<path d="M{pos:.2f},25 V{height-40}" class="gridline"/><text x="{pos:.2f}" y="{height-15}" text-anchor="middle">{value:g}</text>')
        band = (height - 80) / len(categories)
        for i, category in enumerate(categories):
            parts.append(f'<text x="138" y="{45+i*band:.2f}" text-anchor="end">{esc(category[:15])}</text>')
            for j, serie in enumerate(series):
                value = serie["values"][i]
                bar_h = max(2, (band - 10) / len(series))
                parts.append(f'<rect x="{min(x(0),x(value)):.3f}" y="{30+i*band+j*bar_h:.3f}" width="{abs(x(value)-x(0)):.3f}" height="{bar_h-1:.3f}" rx="2" fill="{PALETTE[j]}"><title>{esc(category)} · {esc(serie["name"])}: {value:g}</title></rect>')
    else:
        y = lambda v: 285 - (v - low) / (high - low) * 245
        for tick in range(5):
            value = low + (high - low) * tick / 4
            pos = y(value)
            parts.append(f'<path d="M75,{pos:.3f} H770" class="gridline"/><text x="62" y="{pos+4:.3f}" text-anchor="end">{value:g}</text>')
        band = 690 / len(categories)
        for i, category in enumerate(categories):
            cx = 80 + (i + .5) * band
            if i % max(1, math.ceil(len(categories) / 8)) == 0:
                parts.append(f'<text x="{cx:.3f}" y="315" text-anchor="middle">{esc(category[:13])}</text>')
        for j, serie in enumerate(series):
            points = []
            for i, value in enumerate(serie["values"]):
                cx, cy = 80 + (i + .5) * band, y(value)
                label = esc(f'{categories[i]} · {serie["name"]}: {value:g}')
                if kind == "line":
                    points.append(f"{cx:.3f},{cy:.3f}")
                    parts.append(f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="4" fill="{PALETTE[j]}"><title>{label}</title></circle>')
                else:
                    bar_w = band * .68 / len(series)
                    bx = cx - band * .34 + j * bar_w
                    parts.append(f'<rect x="{bx:.3f}" y="{min(cy,y(0)):.3f}" width="{bar_w*.85:.3f}" height="{abs(cy-y(0)):.3f}" rx="3" fill="{PALETTE[j]}"><title>{label}</title></rect>')
                if len(categories) <= 6 and len(series) <= 2:
                    tx = cx if kind == "line" else bx + bar_w * .425
                    ty = cy - 9 if value >= 0 else cy + 18
                    parts.append(f'<text x="{tx:.3f}" y="{ty:.3f}" text-anchor="middle" class="chart-value">{value:g}</text>')
            if kind == "line":
                parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{PALETTE[j]}" stroke-width="3"/>')
    parts.append('</svg>')
    legend = ''.join(f'<span><i style="background:{PALETTE[j]}"></i>{esc(s["name"])}</span>' for j, s in enumerate(series)) if kind != "pie" else ''
    return '<figure class="chart-frame"><figcaption>'+esc(chart.get('title') or '지표 비교')+'</figcaption>'+''.join(parts)+f'<div class="legend">{legend}</div></figure>'


CSS = """
:root{--ink:#182c32;--accent:#246858;--muted:#617277;--line:#dae2e0;--bg:#ecf0ef;--paper:#fff;--radius:18px}
body{font-size:16px;line-height:1.7}.report-masthead{max-width:1320px;padding:24px 40px 16px;display:flex;justify-content:space-between;align-items:center;gap:20px}.report-name{font-size:14px;letter-spacing:.02em;font-weight:700}.report-masthead .subtitle{font-size:12px;margin:3px 0}.report-masthead nav{margin:0;font-size:12px}.report-masthead button{font-size:12px;padding:8px 12px}.report-main{max-width:1320px;padding:12px 40px}.section{position:relative;padding:48px 52px;border-radius:var(--radius);margin-bottom:24px;box-shadow:0 8px 32px #1c353506}.page-number{font-variant-numeric:tabular-nums;color:var(--accent);font-size:12px;letter-spacing:.13em;margin-bottom:17px}.section h2{font-size:clamp(25px,3.1vw,40px);letter-spacing:-1.3px;max-width:28ch;margin-bottom:16px}.takeaway{font-size:18px;line-height:1.6;border-left:3px solid var(--accent);padding-left:15px;margin:0 0 26px;color:var(--ink)}.section-content{min-width:0}.copy-block{min-width:0}.text{font-size:15px;max-width:76ch}.text li{margin:10px 0}.section-source{font-size:11px;color:var(--muted);border-top:1px solid var(--line);padding-top:12px;margin-top:24px;overflow-wrap:anywhere}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin:25px 0}.kpi{border:1px solid var(--line);padding:20px 22px;border-radius:12px;background:var(--paper);min-width:0}.kpi-label{font-size:12px;color:var(--muted)}.kpi-value{font-size:clamp(27px,3.3vw,43px);font-weight:750;line-height:1.3;letter-spacing:-1.3px;margin:10px 0;color:var(--accent);font-variant-numeric:tabular-nums}.kpi-unit{font-size:13px;font-weight:400;letter-spacing:0;margin-left:5px}.kpi-note{font-size:12px;color:var(--muted)}.layout-cover{min-height:520px;background:linear-gradient(115deg,var(--paper) 65%,#e9f2ee)!important}.layout-cover h2{font-size:clamp(34px,4.9vw,62px);max-width:19ch;margin-top:20px;letter-spacing:-2px}.layout-cover .takeaway{max-width:65ch}.layout-cover .kpis{margin-top:45px}.layout-split .section-content{display:grid;grid-template-columns:minmax(0,.75fr) minmax(0,1.25fr);gap:35px;align-items:center}.layout-summary .copy-block{border-top:3px solid var(--accent);padding-top:14px}.chart-frame{border:1px solid var(--line);border-radius:12px;margin:16px 0;padding:20px;background:var(--paper)}.chart-frame figcaption{font-size:14px;font-weight:700;color:var(--ink);margin-bottom:10px}.report-chart{width:100%;height:auto;display:block;overflow:visible}.report-chart text{font:12px 'Malgun Gothic',sans-serif;fill:var(--muted)}.report-chart .chart-value{font-size:13px;font-weight:700;fill:var(--ink)}.report-chart .chart-total{font-size:28px;font-weight:700;fill:var(--ink)}.gridline{stroke:var(--line);stroke-width:1}.legend{display:flex;justify-content:center;flex-wrap:wrap;gap:20px;font-size:12px;color:var(--muted)}.legend i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:6px}.chart-values{font-size:12px;margin:12px 0 0}.chart-values summary{cursor:pointer;color:var(--muted)}.chart-values .table-wrap{margin:12px 0}.table-wrap{margin:22px 0}th{background:#edf3f0;font-size:12px;white-space:normal}td{font-size:14px;font-variant-numeric:tabular-nums}th,td{padding:13px 14px}tbody tr:nth-child(even){background:#f7f9f7}td.numeric{text-align:right}body[data-view=slides] main>.section.active{min-height:min(700px,calc(100vh - 165px))}
@media(max-width:760px){.report-masthead{display:block;padding:20px}.report-masthead nav{margin-top:14px}.report-main{padding:8px 16px}.section,body[data-style=minimalism] .section{padding:26px 22px}.layout-split .section-content,body[data-style=editorial] .layout-split .section-content,body[data-style=freeform] .layout-split .section-content{display:block}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.kpi{padding:15px 12px}.kpi-value{font-size:29px}.chart-frame{padding:10px}.layout-cover{min-height:0}.section h2{max-width:none}.report-chart{min-width:450px}.chart-frame{overflow-x:auto}body[data-view=slides] main>.section.active{min-height:0}}
@media print{.report-masthead{padding:0 0 10px}.report-main{padding:0}.section,body[data-style=minimalism] .section{padding:24px;min-height:0!important;box-shadow:none}.report-chart{max-height:340px;min-width:0}.kpis{grid-template-columns:repeat(3,1fr)}.layout-split .section-content{display:block}.chart-values{display:none}.section h2{font-size:28px}.layout-cover h2{font-size:38px}}
"""


def render(data: dict, base_css: str, script: str, table_renderer) -> str:
    from .report_styles import CSS as theme_css
    base_css = base_css + '\n' + CSS + '\n' + theme_css + '\n' + data.get('referenceCss', '')
    sections = []
    for i, row in enumerate(data["sections"], 1):
        layout = row.get("layout", "dashboard" if row.get("chart") or row.get("kpis") else "table" if row.get("table") else "summary")
        fragment = f'<section class="section layout-{layout}" id="section-{i}"><span class="page-number">{i:02d} / {len(data["sections"]):02d} · {esc(row.get("eyebrow") or "업무 보고")}</span><h2>{esc(row["title"])}</h2>'
        if row.get("takeaway"):
            fragment += f'<p class="takeaway">{esc(row["takeaway"])}</p>'
        if row.get("kpis"):
            fragment += '<div class="kpis">'+''.join(f'<div class="kpi"><div class="kpi-label">{esc(k["label"])}</div><div class="kpi-value">{esc(k["display"])}<span class="kpi-unit">{esc(k["unit"])}</span></div><div class="kpi-note">{esc(k["note"])}</div></div>' for k in row['kpis'])+'</div>'
        copy = f'<p class="text">{esc(row["body"])}</p>' if row['body'] else ''
        if row['bullets']:
            copy += '<ul class="text">'+''.join(f'<li>{esc(v)}</li>' for v in row['bullets'])+'</ul>'
        visuals = ''
        if row.get('chart'):
            chart = row['chart']
            visuals += svg_chart(chart, i)
            visuals += '<details class="chart-values"><summary>차트 수치 원자료 펼치기</summary>'+table_renderer(['항목']+[s['name'] for s in chart['series']], [[cat]+[s['values'][n] for s in chart['series']] for n, cat in enumerate(chart['categories'])], '차트 원자료')+'</details>'
        if row.get('table'):
            visuals += table_renderer(row['table']['headers'],row['table']['rows'])
        if row.get('image'):
            im=row['image'];visuals += f'<figure><img src="data:{im["mime"]};base64,{im["data"]}" alt="{esc(im["alt"])}"><figcaption>{esc(im["alt"])}</figcaption></figure>'
        fragment += '<div class="section-content"><div class="copy-block">'+copy+'</div><div class="visual-block">'+visuals+'</div></div>'
        if row.get('source'):
            fragment += f'<p class="section-source">{esc(row["source"])}</p>'
        sections.append(fragment+'</section>')
    digest=base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    csp=f"default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'sha256-{digest}'; base-uri 'none'; form-action 'none'"
    view='slides' if data['mode']=='slides' else 'scroll'
    toggle='<button id="toggle-view" type="button">페이지로 보기</button>' if data['mode']=='both' else ''
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+f'<meta http-equiv="Content-Security-Policy" content="{esc(csp)}"><title>{esc(data["title"])}</title><style>{base_css}</style></head>'+f'<body data-style="{data["style"]}" data-view="{view}" data-length="{data["length"]}"><header class="report-masthead"><div><div class="report-name">{esc(data["title"])}</div><p class="subtitle">{esc(data["subtitle"])}</p></div><nav aria-label="보고서 보기">{toggle}<button id="print" type="button">인쇄 / PDF 저장</button><span class="slide-controls"><button id="previous" type="button">이전</button> <span id="slide-count" aria-live="polite"></span> <button id="next" type="button">다음</button></span></nav></header><main class="report-main">'+''.join(sections)+'</main><footer>인터넷 없이 열리는 업무 보고서 · 원자료와 확인 필요 사항을 함께 검토해 주세요.</footer><script>'+script+'</script></body></html>')
