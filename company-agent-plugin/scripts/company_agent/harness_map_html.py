"""Escaped, self-contained harness map. No JavaScript, network or live actions."""
from __future__ import annotations

from html import escape
from pathlib import Path

from .skill_registry import _no_reparse


CSS = """
:root{color-scheme:light;--ink:#243630;--muted:#586861;--line:#dbe2da;--paper:#f5f6f0;--green:#1c644e}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 'Segoe UI','Malgun Gothic',sans-serif}
main{max-width:1460px;margin:auto;padding:44px 34px}a{color:var(--green)}
.eyebrow{color:var(--green);font-size:12px;font-weight:700;letter-spacing:.13em}h1{font-size:clamp(26px,3vw,40px);letter-spacing:-.045em;margin:8px 0}h2{font-size:23px;margin:6px 0}h3{font-size:17px;margin:0}p{margin:6px 0}.muted,small{color:var(--muted)}
.intro{display:flex;justify-content:space-between;gap:24px;align-items:start}.stamp{text-align:right;white-space:nowrap;font-size:12px;color:var(--muted)}
.workspace{padding:16px 20px;margin:22px 0 18px;background:white;border:1px solid var(--line);border-radius:12px}.path{overflow-wrap:anywhere;font-family:Consolas,'Malgun Gothic',monospace;font-size:12px}
.legend{display:flex;gap:9px;flex-wrap:wrap;margin:18px 0 24px}.badge{display:inline-flex;align-items:center;font-size:12px;font-weight:600;padding:3px 9px;border-radius:20px;background:#edf0eb;color:#405249;white-space:nowrap}.enabled,.available{background:#e2f1e9;color:#20523e}.unknown,.choice,.draft{background:#fff0d2;color:#805600}.disabled,.missing{background:#ececea;color:#646762}.observed{background:#dceaf8;color:#215983}.manual{background:#eae7f6;color:#5a4783}
.areas{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;align-items:start}.area{background:#fff;border:1px solid var(--line);border-radius:16px;overflow:hidden;min-width:0}.area-head{padding:22px;border-top:5px solid #245a47;background:#f8fbf8;min-height:177px}.area.personal .area-head{border-top-color:#517493;background:#f7faff}.area.project .area-head{border-top-color:#ad7d3e;background:#fffbf4}.number{font-size:12px;letter-spacing:.1em;color:var(--muted)}.count{font-size:12px;margin-top:10px;color:var(--muted)}
.category{border-top:1px solid var(--line)}summary{cursor:pointer;list-style:none;padding:15px 20px;font-weight:600;display:flex;gap:8px;justify-content:space-between}summary:after{content:'＋';font-weight:400}details[open]>summary:after{content:'−'}summary:focus-visible{outline:3px solid #527dff;outline-offset:-3px}.total{margin-left:auto;color:var(--muted);font-size:12px;font-weight:400}
.item{border-top:1px solid #edf0eb;padding:14px 20px}.item-head{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.name{font-weight:600;font-size:14px;overflow-wrap:anywhere}.detail{font-size:12px;color:var(--muted);margin-top:7px}.source{margin-top:8px;font-size:12px}.source summary{padding:0;font-size:12px;justify-content:start;font-weight:400;color:var(--green)}.source .path{margin-top:7px;border-left:2px solid var(--line);padding-left:9px}.sharing{font-size:11px;color:#6a6452;margin-top:5px}
.guidance{margin:26px 0 0;padding:22px;border:1px solid var(--line);border-radius:14px;background:#fff}.guidance ol{padding-left:22px;margin:12px 0 0;font-size:13px;color:var(--muted)}.warnings{border-color:#ddc492;background:#fffbf2}.footer{font-size:12px;color:var(--muted);margin-top:24px}.empty{padding:22px;color:var(--muted)}
@media(max-width:950px){main{padding:24px 18px}.areas{grid-template-columns:1fr}.area-head{min-height:0}.intro{display:block}.stamp{text-align:left;margin-top:12px}}
@media print{body{background:white}main{padding:0}.areas{display:block}.area{break-inside:avoid;margin:14px 0}.stamp{white-space:normal}.guidance{break-inside:avoid}}
"""


def render_map(report):
    esc = lambda value: escape(str(value or ''), quote=True)
    areas = []
    for group in report['groups']:
        categories = {}
        for row in group['items']:
            categories.setdefault(row['category'], []).append(row)
        blocks = []
        for category, rows in categories.items():
            items = []
            for row in rows:
                source = ('<details class="source"><summary>위치 보기</summary><p class="path">' + esc(row['path']) + '</p></details>') if row.get('path') else ''
                observed = '<span class="badge observed">본문 로드 기록</span>' if row.get('observed') else ''
                preferred = '<span class="badge manual">우선 선택</span>' if row.get('preferred') else ''
                items.append(f'<div class="item"><div class="item-head"><span class="name">{esc(row["name"])}</span>'
                             f'<span class="badge {esc(row["status"])}">{esc(row["statusLabel"])}</span>{preferred}{observed}</div>'
                             f'<p class="detail">{esc(row["detail"])}</p><p class="sharing">{esc(row["sharing"])}</p>{source}</div>')
            opened = ' open' if category in {'설치', '저장소', '자동 학습', '지침'} else ''
            blocks.append(f'<details class="category"{opened}><summary>{esc(category)}<span class="total">{len(rows)}개</span></summary>{"".join(items)}</details>')
        counts = group['counts']
        count = (f'표시 {len(group["items"])}개 · 설정 켜짐 {counts["enabled"]} · 사용 가능 {counts["available"]}<br>'
                 f'꺼짐 {counts["disabled"]} · 확인/선택 필요 {counts["unknown"] + counts["choice"]}')
        areas.append(f'<section class="area {esc(group["id"])}" id="{esc(group["id"])}">'
                     f'<header class="area-head"><span class="number">0{len(areas)+1} / SCOPE</span><h2>{esc(group["label"])}</h2>'
                     f'<p class="muted">{esc(group["description"])}</p><p class="count">{count}</p></header>'
                     f'{"".join(blocks) or "<p class=empty>확인된 항목이 없습니다.</p>"}</section>')
    warnings = ''
    if report['warnings']:
        warnings = '<section class="guidance warnings"><h3>일부는 확인하지 못했습니다</h3><ol>' + ''.join(f'<li class="path">{esc(w)}</li>' for w in report['warnings']) + '</ol></section>'
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>내 작업 폴더의 하네스 구성</title><style>{CSS}</style></head><body><main>
<header class="intro"><div><span class="eyebrow">COMPANY AGENT / HARNESS MAP</span><h1>이 폴더에는 무엇이 적용될까요?</h1>
<p class="muted">기억과 업무 도구의 위치를, 세 영역으로 나누어 확인하세요.</p></div>
<div class="stamp">읽기 전용 · AI 호출 0회<br>{esc(report['generatedAt'])}<br>조회 {report['elapsedMs']} ms</div></header>
<section class="workspace"><strong>현재 작업 폴더</strong><p class="path">{esc(report['project'])}</p>
<details class="source"><summary>사용자 설정 위치</summary><p class="path">{esc(report['configRoot'])}</p></details></section>
<p class="muted">켜짐 ≠ 실제 사용. 설정 상태와 실행 증거를 분리해서 표시합니다.</p>
<div class="legend"><span class="badge enabled">설정 켜짐</span><span class="badge available">사용 가능 · 필요할 때 선택</span>
<span class="badge defined">정의 발견 · 실행 미확인</span><span class="badge disabled">꺼짐 / 제외</span>
<span class="badge unknown">확인 필요</span><span class="badge observed">본문 로드 기록 · 적용 성공 아님</span></div>
<div class="areas">{''.join(areas)}</div>{warnings}
<section class="guidance"><h3>어떻게 읽으면 되나요?</h3><ol>
<li>카테고리를 펼치면 이름과 상태를, ‘위치 보기’를 펼치면 실제 파일 경로를 확인할 수 있습니다.</li>
<li>회사 공통은 배포 담당자가 관리합니다. 개인 전체와 이 프로젝트의 개인 저장소는 자동 공유되지 않습니다.</li>
<li>프로젝트의 CLAUDE.md·.claude 파일은 폴더와 함께 공유할 수 있습니다. 개인 저장소와 다른 종류입니다.</li>
<li>우선 선택은 Company Agent에 저장한 선택 기준입니다. Claude 자체의 로드 순서나 실제 스킬 사용을 바꾸었다는 뜻은 아닙니다.</li>
<li>{esc(report['observation'])}. 과거의 성공이나 다른 대화 기록을 현재 상태로 대신 표시하지 않습니다.</li></ol></section>
<section class="guidance"><h3>확인 범위와 주의사항</h3><ol>{''.join('<li>'+esc(t)+'</li>' for t in report['limits'])}</ol></section>
<p class="footer">로컬 조회 결과 · 외부 통신 없음 · 파일/설정 변경 없음 · 저장한 HTML은 이후 변경을 자동 반영하지 않습니다.<br>
범위 설명 참고: <a href="https://code.claude.com/docs/en/settings" rel="noreferrer">Claude Code 설정</a> · <a href="https://code.claude.com/docs/en/mcp" rel="noreferrer">MCP 범위</a></p>
</main></body></html>'''


def write_map(path: Path, report):
    path = path.expanduser().absolute()
    _no_reparse(path)
    if path.suffix.lower() != '.html':
        raise ValueError('새 .html 파일 경로를 지정해 주세요.')
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(render_map(report))
    return str(path)
