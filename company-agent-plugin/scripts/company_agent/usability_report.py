"""Bounded offline usability reports, with no scripts or raw-log export."""
from __future__ import annotations

import base64
from html import escape
import json
from pathlib import Path
import re
from typing import Any

from .skill_registry import _no_reparse


MAX_TEXT = 900
MAX_ITEMS = 12
MAX_METADATA_BYTES = 16_384
UNKNOWN = "기록 없음"
METRICS = (
    ("transcriptSessions", "대화 세션", "분석한 대화 기록의 수"),
    ("requests", "사용자 요청", "기록에서 확인한 사용자 요청 수"),
    ("toolCalls", "도구 요청", "도구를 부른 횟수이며 성공 횟수는 아닙니다"),
    ("toolErrors", "도구 오류", "오류 응답이 확인된 요청 수"),
    ("repeatedFailedCalls", "실패 후 같은 동작 재요청", "실패 뒤 동일한 입력으로 다시 요청한 관찰 수입니다. 재호출 결과의 실패 여부는 별도로 확인해야 합니다"),
    ("questionCalls", "확인 질문", "사용자에게 선택이나 확인을 요청한 횟수"),
    ("repeatedQuestions", "확인 질문의 반복", "같은 확인 질문이 반복된 후보"),
    ("sameRangeReads", "같은 범위 재읽기", "같은 파일 범위를 다시 읽은 후보"),
    ("questionPairs", "응답이 연결된 확인 질문", "질문과 응답 시각을 함께 확인한 수"),
    ("questionWaitMs", "확인 질문의 응답 대기", "연결된 질문부터 응답까지의 시간 합계"),
    ("observedSpanMs", "기록의 관찰 구간", "기록의 시작부터 끝까지이며 실제 작업 시간과 다릅니다"),
)
TOKENS = (
    ("input_tokens", "입력 토큰"), ("output_tokens", "출력 토큰"),
    ("cache_creation_input_tokens", "캐시 생성 토큰"),
    ("cache_read_input_tokens", "캐시 읽기 토큰"),
)
SNAPSHOTS = (
    ("sessions", "진단 상태 기록"), ("toolFailures", "상태 기록의 도구 실패"),
    ("slowPreparation", "준비 지연 후보"), ("failedPreparation", "준비 실패 기록"),
    ("maxContextChars", "준비 안내의 최대 문자 수"), ("loadFailures", "자료 읽기 실패 기록"),
)

CSS = """
:root{color-scheme:light;--ink:#193b47;--muted:#536c75;--mint:#e5f4ee;--green:#17644f;--line:#d9e5e1;--paper:#f3f7f5}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.75 'Noto Sans KR','Malgun Gothic','Apple SD Gothic Neo',system-ui,sans-serif}
main{max-width:1120px;padding:44px 28px 56px;margin:auto}a{color:var(--green)}p{margin:8px 0;overflow-wrap:anywhere}h1,h2,h3{line-height:1.4;letter-spacing:-.035em;overflow-wrap:anywhere}h1{font-size:clamp(30px,4vw,42px);margin:10px 0}h2{font-size:25px;margin:0 0 12px}h3{font-size:20px;margin:0 0 10px}.muted{color:var(--muted)}
.topline,.title-row{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.eyebrow{font-size:14px;font-weight:700;letter-spacing:.08em}.download{display:inline-block;text-decoration:none;border:1px solid #aec9bd;padding:9px 16px;border-radius:10px;background:#fff;font-weight:600}.download:focus-visible,summary:focus-visible{outline:3px solid #267d75;outline-offset:4px}.period{color:var(--muted);margin:12px 0 26px}
.hero{background:var(--mint);border:1px solid #c3ddd0;border-radius:20px;padding:28px 30px}.hero.no-data,.hero.partial{background:#fff7e9;border-color:#e8d3ac}.status{font-size:14px;font-weight:700;display:inline-block;padding:4px 11px;border-radius:20px;background:#fff;margin-bottom:12px}.hero h2{font-size:27px}.note{color:var(--muted);font-size:15px}.hero .note{margin-top:15px}
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:20px}.stat{background:#fff;border:1px solid var(--line);border-radius:14px;padding:19px 21px;min-width:0}.stat-label{display:block;color:var(--muted)}.stat-value{display:block;font-size:29px;line-height:1.5;font-weight:700;overflow-wrap:anywhere}.stat small{font-size:14px;color:var(--muted)}
.section{margin-top:30px}.findings{display:grid;gap:16px;margin-top:18px}.finding{background:#fff;border:1px solid var(--line);border-radius:16px;padding:24px;display:grid;grid-template-columns:40px minmax(0,1fr);gap:18px}.ordinal{display:flex;align-items:center;justify-content:center;width:36px;height:36px;border-radius:50%;background:var(--mint);color:var(--green);font-weight:700}.evidence{background:#f4f7f6;border-radius:10px;padding:12px 15px;margin:15px 0;color:var(--muted)}.next{border-left:3px solid #3a8c71;padding-left:14px}.meta{font-size:14px;color:var(--muted);margin-top:13px}.empty{background:#fff;border:1px dashed #b8cdc4;border-radius:14px;padding:24px}
.panel{background:#fff;border:1px solid var(--line);border-radius:16px;margin-top:18px;overflow:hidden}.panel>summary{cursor:pointer;padding:20px 24px;font-size:20px;font-weight:700}.panel-body{padding:0 24px 24px}.panel-body h3{margin-top:24px}.table-scroll{overflow-x:auto;margin:16px 0}table{border-collapse:collapse;width:100%;text-align:left;table-layout:fixed}th,td{padding:13px 14px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}thead th{background:#f1f6f3;font-weight:600}tbody th{font-weight:500;width:34%}.metrics-table th:first-child{width:29%}.metrics-table td:nth-child(2){width:22%;font-weight:600}.metrics-table td:last-child{color:var(--muted)}.comparison-table{min-width:540px}.comparison-table th:first-child{width:40%}.list{padding-left:23px;margin:12px 0}.list li{margin:8px 0;overflow-wrap:anywhere}.coverage{margin-top:24px;padding:21px 24px;background:#eaf1ee;border-radius:14px}.footer{margin-top:28px;color:var(--muted);font-size:14px}
@media(max-width:650px){main{padding:24px 16px 36px}.hero{padding:22px}.hero h2{font-size:24px}.stats{grid-template-columns:1fr;gap:10px}.stat{padding:14px 18px}.stat-value{font-size:26px}.finding{padding:19px;grid-template-columns:30px minmax(0,1fr);gap:12px}.ordinal{width:30px;height:30px}.panel>summary{padding:18px;font-size:19px}.panel-body{padding:0 18px 18px}.metrics-table{min-width:660px}th,td{padding:11px}.coverage{padding:18px}.download{padding:8px 12px}.period{margin-bottom:20px}}
@media print{body{background:#fff}main{max-width:none;padding:0}.download{display:none}.hero,.finding,.stat{break-inside:avoid}.panel-body{display:block}.table-scroll{overflow:visible}.footer{font-size:12px}}
"""


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: Any, maximum: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        return ""
    # Preserve readable text, not terminal controls or bidi overrides.
    return " ".join(re.sub(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]", " ", value[:maximum]).split())


def _number(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value < 10**18 else None


def _count(value: Any) -> str:
    number = _number(value)
    return UNKNOWN if number is None else f"{number:,}"


def _duration(value: Any) -> str:
    number = _number(value)
    if number is None:
        return UNKNOWN
    if number < 60_000:
        return f"{number / 1000:,.1f}".rstrip("0").rstrip(".") + "초"
    minutes, seconds = divmod(number // 1000, 60)
    hours, minutes = divmod(minutes, 60)
    return (f"{hours:,}시간 " if hours else "") + f"{minutes}분 {seconds}초"


def _texts(value: Any) -> list[str]:
    return [_text(item) for item in value[:MAX_ITEMS] if _text(item)] if isinstance(value, list) else []


def _view(report: dict) -> dict:
    if not isinstance(report, dict) or type(report.get("schemaVersion")) is not int or report["schemaVersion"] != 1:
        raise ValueError("Unsupported usability report schema.")
    source_summary = _object(report.get("summary"))
    status = source_summary.get("status")
    if not isinstance(status, str) or status not in {"observed", "partial", "no-data"}:
        status = "no-data"
    source_metrics = _object(report.get("metrics"))
    metrics = {key: _number(source_metrics.get(key)) if status != "no-data" else None for key, _, _ in METRICS}
    tokens = _object(source_metrics.get("tokens"))
    metrics["tokens"] = {key: _number(tokens.get(key)) if status != "no-data" else None for key, _ in TOKENS}
    window = _object(report.get("window"))
    coverage = _object(report.get("coverage"))
    findings = report.get("findings")
    findings = findings[:3] if isinstance(findings, list) and status != "no-data" else []
    findings = [{**{key: _text(item.get(key)) for key in ("code", "title", "detail", "nextStep", "evidence", "confidence")},
                 "count": _number(item.get("count"))} for item in findings if isinstance(item, dict)]
    comparison = _object(report.get("comparison"))
    comparison_rows = comparison.get("rows")
    comparison_rows = comparison_rows[:MAX_ITEMS] if isinstance(comparison_rows, list) else []
    comparison = {"status": _text(comparison.get("status"), 64), "message": _text(comparison.get("message")),
                  "rows": [{"label": _text(row.get("label"), 120), "before": _number(row.get("before")),
                            "after": _number(row.get("after")), "unit": _text(row.get("unit"), 24)}
                           for row in comparison_rows if isinstance(row, dict)]} if comparison else {}
    scope = report.get("scopeKey")
    return {
        "schemaVersion": 1, "generatedAt": _text(report.get("generatedAt"), 64),
        "generatorVersion": _text(report.get("generatorVersion"), 64),
        "scopeKey": scope if isinstance(scope, str) and re.fullmatch(r"[a-fA-F0-9]{64}", scope) else None,
        "window": {"since": _text(window.get("since"), 64), "until": _text(window.get("until"), 64), "days": _number(window.get("days"))},
        "summary": {"status": status, "title": "판단할 기록이 없습니다" if status == "no-data" else _text(source_summary.get("title")) or "선택한 기록을 확인했습니다",
                    "message": _text(source_summary.get("message"))},
        "coverage": {**{key: _number(coverage.get(key)) for key in ("filesRead", "recordsRead", "skippedRecords")},
                     "truncated": coverage.get("truncated") is True, "warnings": _texts(coverage.get("warnings"))},
        "metrics": metrics, "findings": findings, "comparison": comparison,
        "snapshots": {key: _number(_object(report.get("snapshots")).get(key)) for key, _ in SNAPSHOTS},
        "limitations": _texts(report.get("limitations")),
    }


def _metric(value: Any, key: str) -> str:
    return _duration(value) if key.endswith("Ms") else _count(value)


def _comparison_value(value: Any, unit: str) -> str:
    if unit == "ms":
        return _duration(value)
    return _count(value) + (f" {unit}" if _number(value) is not None and unit else "")


def _md(value: Any) -> str:
    # Neutralize HTML and Markdown link/image/format syntax in aggregate labels.
    value = escape(_text(value), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value)


def _markdown(view: dict) -> str:
    summary, metrics, coverage = view["summary"], view["metrics"], view["coverage"]
    lines = ["# 내 사용 흐름 점검", "", f"생성 시각: {_md(view['generatedAt']) or UNKNOWN}",
             f"분석 기간: {_md(view['window']['since']) or UNKNOWN} ~ {_md(view['window']['until']) or UNKNOWN}", "",
             f"## {_md(summary['title'])}", "", _md(summary["message"])]
    if summary["status"] == "no-data":
        lines += ["", "확인할 기록이 없어 상태를 판단할 수 없습니다. 문제가 없다는 뜻은 아닙니다.",
                  "분석 기간에 대화 기록이 있는지 확인한 뒤 다시 점검하세요."]
    lines += ["", f"## 먼저 확인할 {len(view['findings'])}가지" if view["findings"] else "## 다음 확인", "",
              "아래 항목은 개선 후보입니다. 반복이나 오류만으로 불필요한 동작을 확정하지 않습니다."]
    if not view["findings"]:
        lines += ["", "선택한 기록에서 개선 후보를 특정하지 못했습니다. 전체 사용 흐름이 정상이라는 판정은 아닙니다."]
    for index, item in enumerate(view["findings"], 1):
        lines += ["", f"### {index}. {_md(item['title'])}", "", _md(item["detail"]), "",
                  f"관찰 근거: {_md(item['evidence']) or UNKNOWN}",
                  f"후보 수: {_count(item['count'])} / 근거 수준: {_md(item['confidence']) or UNKNOWN}", "",
                  f"다음 행동: {_md(item['nextStep']) or '해당 작업의 목적과 기록을 함께 확인하세요.'}"]
    if view["comparison"]:
        comparison = view["comparison"]
        lines += ["", "## 이전 보고서와 비교", "", _md(comparison["message"])]
        if comparison["rows"]:
            lines += ["", "| 확인 항목 | 이전 | 이번 |", "| --- | ---: | ---: |"]
            for row in comparison["rows"]:
                lines.append(f"| {_md(row['label'])} | {_md(_comparison_value(row['before'], row['unit']))} | {_md(_comparison_value(row['after'], row['unit']))} |")
        lines += ["", "기록의 범위와 업무가 다르면 수치만으로 개선 효과를 판단할 수 없습니다."]
    lines += ["", "## 자세한 수치", "", "기록 없음은 0과 다릅니다. 확인하지 못한 값이며, 토큰 수로 비용을 계산하지 않습니다.", "",
              "| 항목 | 관찰값 | 의미 |", "| --- | ---: | --- |"]
    lines += [f"| {label} | {_metric(metrics[key], key)} | {description} |" for key, label, description in METRICS]
    lines += [f"| {label} | {_count(metrics['tokens'][key])} | 기록에 포함된 사용량 |" for key, label in TOKENS]
    lines += ["", "### 별도로 수집한 진단 상태", "", "대화 기록의 합계와 겹칠 수 있으므로 위 수치에 더하지 않습니다.", "",
              "| 항목 | 관찰값 |", "| --- | ---: |"]
    lines += [f"| {label} | {_count(view['snapshots'][key])} |" for key, label in SNAPSHOTS]
    lines += ["", "## 확인 범위와 해석", "",
              f"읽은 파일 {_count(coverage['filesRead'])}개 / 읽은 기록 {_count(coverage['recordsRead'])}개 / 제외된 기록 {_count(coverage['skippedRecords'])}개",
              "수집 한도에 도달하여 일부만 확인했습니다." if coverage["truncated"] else "수집 한도 초과 표시는 없습니다. 원본 기록의 완전성을 보장하지는 않습니다.", "",
              "- 도구 요청은 실행 성공이나 업무 완료의 증거가 아닙니다.",
              "- 응답 대기는 사람이 답한 시간도 포함하므로 모델의 처리 시간이나 낭비 시간과 다릅니다.",
              "- 같은 자료를 다시 읽거나 질문하는 과정이 업무에 필요했을 수 있습니다."]
    lines += ["- " + _md(item) for item in coverage["warnings"] + view["limitations"]]
    lines += ["", "이 보고서는 집계 결과만 담습니다. 대화 원문, 명령과 파일 경로는 포함하지 않습니다. 저장 후의 변화는 자동 반영하지 않습니다.", ""]
    return "\n".join(lines)


def render_markdown(report: dict) -> str:
    """Return the same aggregate report as inert, escaped UTF-8 Markdown text."""
    return _markdown(_view(report))


def _metadata(view: dict) -> str:
    # The comparison reader consumes this explicit projection, never HTML text.
    projection = {key: view[key] for key in ("schemaVersion", "scopeKey", "generatorVersion", "window", "metrics", "comparison")}
    raw = json.dumps(projection, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_METADATA_BYTES:
        projection["comparison"] = {}
        raw = json.dumps(projection, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def render_report(report: dict) -> str:
    """Render a script-free HTML artifact from a bounded allowlist of aggregates."""
    view = _view(report)
    esc = lambda item: escape(str(item), quote=True)
    summary, metrics, coverage = view["summary"], view["metrics"], view["coverage"]
    # Only fixed status classes reach attributes.
    labels = {"observed": "선택한 기록 확인", "partial": "일부 기록 확인", "no-data": "판단할 기록 없음"}
    markdown_uri = "data:text/markdown;charset=utf-8;base64," + base64.b64encode(_markdown(view).encode("utf-8")).decode("ascii")
    body = [f'<header><div class="topline"><span class="eyebrow">COMPANY AGENT / 사용 흐름 점검</span><a class="download" href="{markdown_uri}" download="사용-흐름-점검.md">Markdown 다운로드</a></div>',
            '<h1>내 사용 흐름, 어디부터 바꿔볼까요?</h1><p class="muted">선택한 로컬 기록에서 반복과 대기를 살펴보고, 다음에 확인할 행동을 정리했습니다.</p>',
            f'<p class="period">분석 기간 {esc(view["window"]["since"] or UNKNOWN)} ~ {esc(view["window"]["until"] or UNKNOWN)}<br>생성 시각 {esc(view["generatedAt"] or UNKNOWN)}</p></header>',
            f'<section class="hero {summary["status"]}" aria-labelledby="report-summary"><span class="status">{labels[summary["status"]]}</span><h2 id="report-summary">{esc(summary["title"])}</h2><p>{esc(summary["message"])}</p>']
    if summary["status"] == "no-data":
        body.append('<p>확인할 기록이 없어 상태를 판단할 수 없습니다. 문제가 없다는 뜻은 아닙니다.</p><p class="note">분석 기간에 대화 기록이 있는지 확인한 뒤 다시 점검하세요.</p>')
    elif summary["status"] == "partial":
        body.append('<p class="note">일부 기록만 확인했습니다. 아래 수치는 전체 사용량이나 전체 업무 상태를 뜻하지 않습니다.</p>')
    else:
        body.append('<p class="note">선택한 기록에 대한 관찰입니다. 업무 완료나 결과 품질을 판정하지 않습니다.</p>')
    body.append('</section><div class="stats" aria-label="관찰 요약">')
    for key, label, note in [("requests", "사용자 요청", "기록에서 확인한 요청"), ("toolErrors", "도구 오류", "오류 응답이 확인된 요청"), ("questionWaitMs", "확인 질문 응답 대기", "사람이 답한 시간도 포함")]:
        body.append(f'<div class="stat"><span class="stat-label">{label}</span><strong class="stat-value">{_metric(metrics[key], key)}</strong><small>{note}</small></div>')
    body += ['</div><section class="section" aria-labelledby="findings-title">', f'<h2 id="findings-title">먼저 확인할 {len(view["findings"])}가지</h2>' if view["findings"] else '<h2 id="findings-title">다음 확인</h2>',
             '<p class="muted">아래 항목은 개선 후보입니다. 반복이나 오류만으로 불필요한 동작을 확정하지 않습니다.</p><div class="findings">']
    for index, item in enumerate(view["findings"], 1):
        body.append(f'<article class="finding"><div class="ordinal" aria-hidden="true">{index}</div><div><h3>{esc(item["title"])}</h3><p>{esc(item["detail"])}</p><div class="evidence"><strong>관찰 근거</strong><p>{esc(item["evidence"] or UNKNOWN)}</p></div><p class="next"><strong>다음 행동</strong><br>{esc(item["nextStep"] or "해당 작업의 목적과 기록을 함께 확인하세요.")}</p><p class="meta">후보 수 {_count(item["count"])} / 근거 수준 {esc(item["confidence"] or UNKNOWN)}</p></div></article>')
    if not view["findings"]:
        body.append('<div class="empty"><strong>선택한 기록에서 개선 후보를 특정하지 못했습니다.</strong><p class="muted">전체 사용 흐름이 정상이라는 판정은 아닙니다. 기록의 범위와 수집 상태를 함께 확인하세요.</p></div>')
    body.append('</div></section>')
    if view["comparison"]:
        comparison = view["comparison"]
        body.append(f'<section class="section"><h2>이전 보고서와 비교</h2><p>{esc(comparison["message"])}</p>')
        if comparison["rows"]:
            body.append('<div class="table-scroll" tabindex="0" role="region" aria-label="이전 보고서 비교 표"><table class="comparison-table"><thead><tr><th scope="col">확인 항목</th><th scope="col">이전</th><th scope="col">이번</th></tr></thead><tbody>')
            body += [f'<tr><th scope="row">{esc(row["label"])}</th><td>{esc(_comparison_value(row["before"], row["unit"]))}</td><td>{esc(_comparison_value(row["after"], row["unit"]))}</td></tr>' for row in comparison["rows"]]
            body.append('</tbody></table></div>')
        body.append('<p class="note">기록의 범위와 업무가 다르면 수치만으로 개선 효과를 판단할 수 없습니다.</p></section>')
    body.append('<details class="panel"><summary>자세한 수치 보기</summary><div class="panel-body"><p class="muted">기록 없음은 0과 다릅니다. 확인하지 못한 값이며, 토큰 수로 비용을 계산하지 않습니다.</p><div class="table-scroll" tabindex="0" role="region" aria-label="자세한 관찰 수치 표"><table class="metrics-table"><thead><tr><th scope="col">항목</th><th scope="col">관찰값</th><th scope="col">읽는 방법</th></tr></thead><tbody>')
    body += [f'<tr><th scope="row">{label}</th><td>{_metric(metrics[key], key)}</td><td>{description}</td></tr>' for key, label, description in METRICS]
    body += [f'<tr><th scope="row">{label}</th><td>{_count(metrics["tokens"][key])}</td><td>기록에 포함된 사용량</td></tr>' for key, label in TOKENS]
    body.append('</tbody></table></div><h3>별도로 수집한 진단 상태</h3><p class="muted">대화 기록의 합계와 겹칠 수 있으므로 위 수치에 더하지 않습니다.</p><table><tbody>')
    body += [f'<tr><th scope="row">{label}</th><td>{_count(view["snapshots"][key])}</td></tr>' for key, label in SNAPSHOTS]
    body.append('</tbody></table></div></details>')
    limit_note = '수집 한도에 도달하여 일부만 확인했습니다.' if coverage["truncated"] else '수집 한도 초과 표시는 없습니다. 원본 기록의 완전성을 보장하지는 않습니다.'
    body.append(f'<section class="coverage"><h3>확인 범위</h3><p>읽은 파일 {_count(coverage["filesRead"])}개 / 읽은 기록 {_count(coverage["recordsRead"])}개 / 제외된 기록 {_count(coverage["skippedRecords"])}개</p><p>{limit_note}</p>')
    if coverage["warnings"]:
        body.append('<ul class="list">' + ''.join('<li>' + esc(item) + '</li>' for item in coverage["warnings"]) + '</ul>')
    body.append('</section><details class="panel"><summary>집계 방법과 해석 범위</summary><div class="panel-body"><ul class="list"><li>도구 요청은 실행 성공이나 업무 완료의 증거가 아닙니다.</li><li>응답 대기는 사람이 답한 시간도 포함하므로 모델의 처리 시간이나 낭비 시간과 다릅니다.</li><li>같은 자료를 다시 읽거나 질문하는 과정이 업무에 필요했을 수 있습니다.</li>')
    body += ['<li>' + esc(item) + '</li>' for item in view["limitations"]]
    body.append('</ul></div></details><footer class="footer">이 보고서는 집계 결과만 담습니다. 대화 원문, 명령과 파일 경로는 포함하지 않습니다.<br>외부 통신과 실행 스크립트가 없는 오프라인 보고서입니다. 저장 후의 변화는 자동 반영하지 않습니다.</footer>')
    return '<!doctype html>\n<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">' + f'<meta name="usability-report" content="{_metadata(view)}"><title>내 사용 흐름 점검 / Company Agent</title><style>{CSS}</style></head><body><main>' + ''.join(body) + '</main></body></html>\n'


def write_report(path: Path | str, report: dict) -> None:
    """Create one new HTML file; preserve existing files and reject reparse paths."""
    path = Path(path).expanduser().absolute()
    if ".." in path.parts or path.suffix.casefold() != ".html":
        raise ValueError("새 .html 파일 경로를 지정해 주세요.")
    _no_reparse(path)
    html = render_report(report)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(html)
