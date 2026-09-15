"""Offline business reports and editable presentations, without runtime downloads.

The public functions accept data, never generated code. All output is new-file-only.
PowerPoint rendering is optional and cannot bypass Office protection or DRM.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import html
import importlib.util
import json
import math
import os
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

from .business_safety import safe_path

STYLES = ("glassmorphism", "brutalism", "neumorphism", "minimalism", "bento-grid",
          "gradient-mesh", "editorial", "freeform")
MODES = ("scroll", "slides", "both")
LIMIT = 40 * 1024 * 1024
MAX_PARTS = 3000
MAX_EXPANDED = 160 * 1024 * 1024
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/package/2006/relationships"


class ArtifactError(Exception):
    def __init__(self, code: str, message: str, status: str = "blocked"):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _failure(error: Exception) -> dict[str, Any]:
    if isinstance(error, ArtifactError):
        return {"ok": False, "status": error.status, "code": error.code, "message": error.message}
    if isinstance(error, PermissionError):
        return {"ok": False, "status": "blocked", "code": "permission_denied",
                "message": "파일을 읽지 못했습니다. 파일 접근 권한을 확인해 주세요."}
    if isinstance(error, FileExistsError):
        return {"ok": False, "status": "blocked", "code": "output_exists",
                "message": "같은 이름의 결과물이 생겨 기존 파일을 보존했습니다. 새 이름을 선택해 주세요."}
    return {"ok": False, "status": "unknown", "code": "artifact_failed",
            "message": "결과물을 완성하지 못했습니다. 원본을 유지했습니다. 입력 형식과 실행 조건을 확인해 주세요."}


def _reject_reparse(path: Path) -> None:
    for ancestor in (path, *path.parents):
        if ancestor.exists() and (ancestor.is_symlink() or
                getattr(ancestor.lstat(), "st_file_attributes", 0) & 0x400):
            raise ArtifactError("linked_path", "연결된 폴더나 파일은 자동 처리하지 않습니다. 실제 로컬 경로를 선택해 주세요.")


def _source(path: Path, suffixes: tuple[str, ...]) -> Path:
    # Nested image paths come from the specification, not only CLI arguments.
    # Reject UNC/device/ADS before any stat/open can touch a remote resource.
    try:
        path = safe_path(path)
    except ValueError:
        raise ArtifactError("unsupported_path", "실제 PC 로컬 경로를 선택해 주세요. 네트워크·장치·연결 경로는 처리하지 않습니다.") from None
    _reject_reparse(path)
    if path.suffix.lower() not in suffixes:
        raise ArtifactError("unsupported_format", "지원하는 원본 파일 형식을 선택해 주세요.")
    if not path.is_file():
        raise ArtifactError("input_missing", "입력 파일을 찾을 수 없습니다.")
    if path.stat().st_size > LIMIT:
        raise ArtifactError("input_too_large", "입력 파일은 40 MB 이하로 나누어 주세요.")
    return path


def _target(path: Path, suffix: str) -> Path:
    try:
        path = safe_path(path)
    except ValueError:
        raise ArtifactError("unsupported_path", "실제 PC 로컬 경로에 저장해 주세요. 네트워크·장치·연결 경로는 처리하지 않습니다.") from None
    _reject_reparse(path)
    if path.suffix.lower() != suffix:
        raise ArtifactError("output_format", f"결과 파일의 확장자는 {suffix}이어야 합니다.")
    if path.exists():
        raise ArtifactError("output_exists", "같은 이름의 결과물이 있습니다. 새 파일 이름을 선택해 주세요.")
    if not path.parent.is_dir():
        raise ArtifactError("output_folder_missing", "결과물을 저장할 기존 폴더를 선택해 주세요.")
    return path


def _publish(source: Path, output: Path) -> None:
    # Exclusive create also checks races after preflight. Never replace another file.
    created = False
    try:
        with output.open("xb") as dest:
            created = True
            with source.open("rb") as src:
                shutil.copyfileobj(src, dest)
            dest.flush()
            os.fsync(dest.fileno())
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise


def _text(value: Any, maximum: int = 10000) -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ArtifactError("invalid_spec", "본문과 제목에는 글자 또는 숫자만 사용할 수 있습니다.")
    result = str(value)
    if len(result) > maximum or any(ord(c) < 32 and c not in "\n\r\t" for c in result):
        raise ArtifactError("invalid_spec", "입력 글자가 너무 길거나 지원하지 않는 제어 문자를 포함합니다.")
    return result


def _image(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise ArtifactError("invalid_image", "이미지는 로컬 PNG/JPEG 파일 경로로 지정해 주세요.")
    path = _source(Path(value["path"]), (".png", ".jpg", ".jpeg"))
    raw = path.read_bytes()
    if len(raw) > 10 * 1024 * 1024:
        raise ArtifactError("image_too_large", "이미지는 10 MB 이하로 준비해 주세요.")
    mime = "image/png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if raw.startswith(b"\xff\xd8\xff") else None
    if mime is None:
        raise ArtifactError("invalid_image", "이미지의 실제 형식이 PNG/JPEG가 아닙니다.")
    return {"path": str(path), "alt": _text(value.get("alt", "참고 이미지"), 1000),
            "data": base64.b64encode(raw).decode("ascii"), "mime": mime}


def _normalize(spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ArtifactError("invalid_spec", "작업 내용은 JSON 객체로 전달해 주세요.")
    if (spec.get("drmRestricted") or spec.get("protected") or spec.get("permissionGranted") is False or
            str(spec.get("accessStatus", "")).lower() in ("blocked", "denied", "protected")):
        raise ArtifactError("protected_input", "보호 또는 접근 제한이 표시된 자료는 자동 처리하지 않습니다.")
    style = spec.get("style", "minimalism")
    aliases = {"글래스모피즘": "glassmorphism", "브루탈리즘": "brutalism", "뉴모피즘": "neumorphism",
               "미니멀리즘": "minimalism", "벤토그리드": "bento-grid", "그라디언트 메시": "gradient-mesh",
               "에디토리얼": "editorial", "자유양식": "freeform", "minimal": "minimalism", "bento": "bento-grid", "gradient_mesh": "gradient-mesh"}
    style = aliases.get(style, style)
    mode = spec.get("mode", "scroll")
    length = spec.get("length", "standard")
    if style not in STYLES or mode not in MODES or length not in ("short", "standard", "detailed"):
        raise ArtifactError("invalid_choice", "지원하는 디자인, 보기 방식, 분량을 선택해 주세요.")
    rows = spec.get("sections", spec.get("slides", []))
    if not isinstance(rows, list) or not 1 <= len(rows) <= 60:
        raise ArtifactError("invalid_sections", "본문은 1~60개 페이지 또는 구역으로 구성해 주세요.")
    result = {"title": _text(spec.get("title", "업무 보고서"), 300), "subtitle": _text(spec.get("subtitle", ""), 1000),
              "style": style, "mode": mode, "length": length, "sections": []}
    for row in rows:
        if not isinstance(row, dict):
            raise ArtifactError("invalid_section", "각 페이지에는 제목과 본문을 객체로 지정해 주세요.")
        if row.get("drmRestricted") or row.get("protected") or row.get("permissionGranted") is False:
            raise ArtifactError("protected_input", "보호 또는 접근 제한이 표시된 자료는 자동 처리하지 않습니다.")
        section: dict[str, Any] = {"title": _text(row.get("title", ""), 300), "body": _text(row.get("body", ""))}
        bullets = row.get("bullets", [])
        if not isinstance(bullets, list) or len(bullets) > 30:
            raise ArtifactError("invalid_bullets", "한 페이지의 목록은 30개 이하로 나누어 주세요.")
        section["bullets"] = [_text(value, 2000) for value in bullets]
        if "table" in row:
            table = row["table"]
            if not isinstance(table, dict) or not isinstance(table.get("headers"), list) or not 1 <= len(table["headers"]) <= 12:
                raise ArtifactError("invalid_table", "표에는 1~12개의 열 제목이 필요합니다.")
            headers = [_text(value, 1000) for value in table["headers"]]
            cells = table.get("rows", [])
            if not isinstance(cells, list) or len(cells) > 100 or any(not isinstance(v, list) or len(v) != len(headers) for v in cells):
                raise ArtifactError("invalid_table", "표는 열 수가 일치하는 100행 이하의 데이터가 필요합니다.")
            section["table"] = {"headers": headers, "rows": [[_text(v, 2000) for v in r] for r in cells]}
        if "chart" in row:
            chart = row["chart"]
            if not isinstance(chart, dict) or chart.get("type", "column") not in ("column", "bar", "line", "pie"):
                raise ArtifactError("invalid_chart", "차트 유형은 column, bar, line, pie 중 하나를 선택해 주세요.")
            categories, series = chart.get("categories"), chart.get("series")
            if not isinstance(categories, list) or not 1 <= len(categories) <= 30 or not isinstance(series, list) or not 1 <= len(series) <= 6:
                raise ArtifactError("invalid_chart", "차트는 1~30개 항목과 1~6개 수치 계열을 지원합니다.")
            checked = []
            for serie in series:
                if not isinstance(serie, dict) or not isinstance(serie.get("values"), list) or len(serie["values"]) != len(categories):
                    raise ArtifactError("invalid_chart", "차트 항목과 수치의 개수가 같아야 합니다.")
                values = serie["values"]
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 1e15 for v in values):
                    raise ArtifactError("invalid_chart", "차트에는 유한한 숫자만 사용할 수 있습니다.")
                checked.append({"name": _text(serie.get("name", "값"), 200), "values": values})
            if chart.get("type") == "pie" and (len(checked) != 1 or any(v < 0 for v in checked[0]["values"]) or sum(checked[0]["values"]) == 0):
                raise ArtifactError("invalid_chart", "원형 차트는 합계가 양수인 한 개의 음수 없는 계열만 지원합니다.")
            section["chart"] = {"type": chart.get("type", "column"), "categories": [_text(v, 200) for v in categories], "series": checked}
        if "image" in row:
            section["image"] = _image(row["image"])
        result["sections"].append(section)
    if len(json.dumps(result, ensure_ascii=True)) > 32 * 1024 * 1024:
        raise ArtifactError("spec_too_large", "전체 자료가 너무 큽니다. 보고서를 나누어 주세요.")
    return result


_CSS = """
:root{color-scheme:light;--bg:#f5f6f8;--paper:#fff;--ink:#172132;--muted:#526075;--accent:#315da8;--line:#dce1e9;--radius:14px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.65 'Malgun Gothic','Segoe UI',sans-serif}
header,main,footer{max-width:1150px;margin:auto;padding:24px}header{padding-top:48px}h1{font-size:clamp(30px,5vw,52px);line-height:1.2;margin:0 0 16px}
h2{font-size:clamp(24px,3vw,34px);line-height:1.3;margin:0 0 22px}h1,h2{overflow-wrap:anywhere}p{white-space:pre-line;overflow-wrap:anywhere}li,td,th{overflow-wrap:anywhere}
.subtitle,.page-number,footer{color:var(--muted)}.section{background:var(--paper);padding:40px;margin:0 0 24px;border:1px solid var(--line);border-radius:var(--radius)}
.page-number{display:block;font-size:13px;margin-bottom:14px}.text{max-width:80ch}.section{min-width:0}.table-wrap{overflow:auto;max-width:100%;margin:24px 0}table{border-collapse:collapse;width:100%;text-align:left}
@media screen{table{min-width:calc(var(--columns,1)*7rem)}th{word-break:keep-all;overflow-wrap:normal}.table-wrap:focus-visible{outline:3px solid var(--accent)}}
th,td{border-bottom:1px solid var(--line);padding:12px;vertical-align:top}th{color:var(--accent);font-weight:700}figure{margin:24px 0}img{max-width:100%;max-height:65vh;object-fit:contain}figcaption{font-size:14px;color:var(--muted)}
nav{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:24px}button{border:1px solid var(--line);background:var(--paper);color:var(--ink);border-radius:8px;padding:10px 16px;font:inherit;cursor:pointer}button:disabled{opacity:.4}button:focus-visible{outline:3px solid var(--accent)}
body[data-view=slides] main>.section{display:none}body[data-view=slides] main>.section.active{display:block;min-height:60vh}body[data-view=scroll] .slide-controls{display:none}.chart-data caption{text-align:left;font-weight:700;color:var(--accent)}
body[data-length=short] .text{max-width:58ch}body[data-length=detailed] .text{max-width:95ch}body[data-length=detailed] .section{padding:32px}
@media(max-width:700px){header,main,footer{padding:20px}.section{padding:24px}body[data-style=bento-grid][data-view=scroll] main{display:block}.section{margin-bottom:24px!important}}
@media print{body{background:white!important}header{padding-top:0}nav,footer{display:none!important}main{display:block!important}.section{display:block!important;box-shadow:none!important;backdrop-filter:none!important;break-inside:avoid;border-color:#ccc!important}body[data-view=slides] .section{break-after:page;min-height:0}img{max-height:600px}}
"""
_JS = """'use strict';(()=>{const sections=[...document.querySelectorAll('main>.section')];let index=0;const count=document.getElementById('slide-count');const prev=document.getElementById('previous');const next=document.getElementById('next');function show(){sections.forEach((s,i)=>s.classList.toggle('active',i===index));count.textContent=(index+1)+' / '+sections.length;prev.disabled=index===0;next.disabled=index===sections.length-1}prev.addEventListener('click',()=>{index=Math.max(0,index-1);show()});next.addEventListener('click',()=>{index=Math.min(sections.length-1,index+1);show()});const toggle=document.getElementById('toggle-view');if(toggle)toggle.addEventListener('click',()=>{const scroll=document.body.dataset.view==='scroll';document.body.dataset.view=scroll?'slides':'scroll';toggle.textContent=scroll?'스크롤로 보기':'페이지로 보기';show()});document.getElementById('print').addEventListener('click',()=>window.print());document.addEventListener('keydown',event=>{if(document.body.dataset.view!=='slides'||/INPUT|TEXTAREA|BUTTON/.test(event.target.tagName))return;if(event.key==='ArrowRight')next.click();if(event.key==='ArrowLeft')prev.click()});show()})();"""


def _html_table(headers: list[str], rows: list[list[Any]], caption: str = "") -> str:
    esc = lambda value: html.escape(str(value), quote=True)
    return (f'<div class="table-wrap" tabindex="0" role="region" aria-label="가로로 스크롤할 수 있는 표"><table style="--columns:{len(headers)}">' + (f'<caption>{esc(caption)}</caption>' if caption else '') +
            '<thead><tr>' + ''.join(f'<th scope="col">{esc(v)}</th>' for v in headers) + '</tr></thead><tbody>' +
            ''.join('<tr>' + ''.join(f'<td>{esc(v)}</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>')


def html_choices(spec: dict[str, Any]) -> dict[str, Any]:
    """Read-only next-question contract, without reading report source assets."""
    try:
        if not isinstance(spec, dict) or spec.get('designMenu') not in (None, 'initial', 'additional', 'template'):
            raise ArtifactError('invalid_choice', '디자인 선택 단계의 형식을 확인해 주세요.')
        fields = {key: spec[key] for key in ('style','length','mode','protected','drmRestricted','permissionGranted','accessStatus') if key in spec}
        normalized = _normalize({**fields, 'sections': [{}]})
        from .report_styles import choices
        pending = choices(spec)
        selection = {key: normalized[key] for key in ('style','length','mode')}
        if isinstance(spec.get('htmlTemplate'), dict):
            selection['htmlTemplate'] = {key: spec['htmlTemplate'].get(key) for key in ('path','sha256')}
        return pending or {'ok': True, 'status': 'choices_ready', 'stage': 'ready',
                           'selection': selection,
                           'message': '디자인·분량·보기 방식이 정해졌습니다. 같은 조건을 다시 묻지 않고 제작합니다.'}
    except Exception as exc:
        return _failure(exc)


def open_local_preview(path: Path, *, fragment: str = '') -> dict[str, Any]:
    """Open only a caller-generated/shipped local preview, not attached source HTML."""
    try:
        if os.name != 'nt':
            raise OSError('Windows default application required')
        target = path.resolve().as_uri() + '#additional-designs' if fragment == 'additional-designs' else str(path.resolve())
        os.startfile(target)
        return {'browserOpened': None, 'previewOpenStatus': 'requested',
                'previewMessage': '기본 브라우저에 열기를 요청했습니다. 창이 안 보이면 아래 파일을 직접 열어 주세요.'}
    except OSError:
        return {'browserOpened': False, 'previewOpenStatus': 'unavailable',
                'previewMessage': '자동으로 열지 못했습니다. 미리보기 파일을 직접 열거나 채팅에서 디자인을 선택해 주세요.'}


def html_designs(output: Path | None = None, *, open_preview: bool = False) -> dict[str, Any]:
    """Expose the shipped picker; --open explicitly requests a local preview."""
    try:
        source = Path(__file__).resolve().parents[2] / 'skills/html-report/assets/design-picker.html'
        source = _source(source, ('.html',))
        target = _target(output, '.html') if output else source
        if output:
            _publish(source, target)
        result = {'ok': True, 'status': 'choices_available', 'outputPath': str(target),
                'message': '추천 디자인만 먼저 표시합니다. 추가 디자인을 펼쳐 비교한 뒤 선택 내용을 Claude 채팅에 붙여 넣어 주세요.',
                'settingsChanged': False, 'browserOpened': False}
        if open_preview:
            result.update(open_local_preview(target, fragment='additional-designs'))
        return result
    except Exception as exc:
        return _failure(exc)


def create_html(spec: dict[str, Any], output: Path, *, require_choices: bool = False) -> dict[str, Any]:
    try:
        output = _target(output, ".html")
        data = _normalize(spec)
        if require_choices:
            from .report_styles import choices
            pending = choices(spec)
            if pending:
                return pending
        reference = None
        if spec.get('htmlTemplate') is not None:
            from .html_reference import analyze, theme_css
            selected = spec['htmlTemplate']
            if not isinstance(selected, dict) or not isinstance(selected.get('path'), str) or not isinstance(selected.get('sha256'), str):
                raise ArtifactError('invalid_template', '첨부 HTML 양식을 먼저 확인해 주세요.')
            reference = analyze(Path(selected['path']))
            if reference['sha256'] != selected['sha256']:
                raise ArtifactError('template_changed', '첨부 양식이 변경되었습니다. 변경된 양식의 미리보기를 다시 확인해 주세요.', 'input_required')
            data['referenceCss'] = theme_css(reference)
        from .report_facts import FactError, resolve, bind
        from .report_design import render
        try:
            facts, validation = resolve(spec, data["sections"])
            data["title"] = bind(data["title"], facts)
            data["subtitle"] = bind(data["subtitle"], facts)
            for raw, row in zip(spec.get("sections", spec.get("slides", [])), data["sections"]):
                layout = raw.get("layout")
                if layout is not None:
                    if layout not in ("cover", "dashboard", "split", "table", "summary"):
                        raise ArtifactError("invalid_layout", "지원하는 페이지 구성 방식을 선택해 주세요.")
                    row["layout"] = layout
                for field in ("eyebrow", "takeaway", "source"):
                    row[field] = bind(_text(raw.get(field, ""), 2000), facts)
                for field in ("title", "body"):
                    row[field] = bind(row[field], facts)
                row["bullets"] = [bind(value, facts) for value in row["bullets"]]
                if "table" in row:
                    row["table"]["rows"] = [[bind(v, facts) for v in cells] for cells in row["table"]["rows"]]
                if "chart" in row:
                    row["chart"]["title"] = bind(_text(raw["chart"].get("title", "지표 비교"), 300), facts)
                kpis = raw.get("kpis", [])
                if not isinstance(kpis, list) or len(kpis) > 6:
                    raise ArtifactError("invalid_kpi", "한 페이지의 핵심 지표는 6개 이하로 구성해 주세요.")
                row["kpis"] = []
                for kpi in kpis:
                    if not isinstance(kpi, dict) or not isinstance(kpi.get("fact"), str) or kpi["fact"] not in facts:
                        raise ArtifactError("invalid_kpi", "핵심 지표는 계산된 공통 수치를 참조해야 합니다.")
                    fact = facts[kpi["fact"]]
                    row["kpis"].append({"label": _text(kpi.get("label", fact["label"]), 200),
                                        "display": fact["display"], "unit": fact["unit"],
                                        "note": bind(_text(kpi.get("note", ""), 500), facts)})
        except FactError as exc:
            raise ArtifactError("numeric_validation_failed", str(exc)) from None
        document = render(data, _CSS, _JS, _html_table)
        with tempfile.TemporaryDirectory(prefix="company-report-") as temp:
            draft = Path(temp) / "report.html"
            draft.write_text(document, encoding="utf-8")
            _publish(draft, output)
        return {"ok": True, "status": "created", "outputPath": str(output), "style": data["style"], "mode": data["mode"],
                "sections": len(data["sections"]), "offline": True, "validation": validation,
                "templateReference": reference,
                "warnings": ["선언한 계산식·대조 항목만 확인했습니다. 원본 일치·자유문장 수치·실제 화면은 별도로 확인해야 합니다."] + (reference['warnings'] if reference else [])}
    except Exception as exc:
        return _failure(exc)


def _xml(raw: bytes) -> ET.Element:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ArtifactError("unsafe_package", "지원하지 않는 XML 선언이 포함된 파일은 처리하지 않습니다.")
    return ET.fromstring(raw)


def _check_embedded_workbook(raw: bytes) -> None:
    """Allow chart data workbooks, but not hidden macros/external-data fetches."""
    try:
        with zipfile.ZipFile(BytesIO(raw)) as workbook:
            entries = workbook.infolist()
            if len(entries) > 1000 or sum(v.file_size for v in entries) > LIMIT:
                raise ArtifactError("unsafe_workbook", "삽입된 차트 데이터가 안전 처리 한도를 초과합니다.")
            names = {v.filename for v in entries}
            if len(names) != len(entries):
                raise ArtifactError("unsafe_workbook", "삽입된 차트 데이터에 중복 내부 파일이 있습니다.")
            for part in entries:
                name = part.filename.lower()
                if (part.flag_bits & 1 or "vbaproject" in name or "/externalLinks/".lower() in name or
                        "/embeddings/" in name or "/activex/" in name or "connections.xml" in name):
                    raise ArtifactError("unsafe_workbook", "삽입된 차트 데이터에 외부 연결 또는 실행 개체가 있습니다.")
                if name.endswith(".rels"):
                    if any(v.get("TargetMode", "").lower() == "external" for v in _xml(workbook.read(part))):
                        raise ArtifactError("unsafe_workbook", "삽입된 차트 데이터의 외부 연결은 자동 처리하지 않습니다.")
    except zipfile.BadZipFile:
        raise ArtifactError("unsafe_workbook", "삽입된 차트 데이터의 형식을 확인할 수 없습니다.") from None


def inspect_template(path: Path) -> dict[str, Any]:
    try:
        path = _source(path, (".pptx",))
        with path.open("rb") as stream:
            if stream.read(8) == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                raise ArtifactError("protected_or_unsupported", "암호화·보호되었거나 지원하지 않는 형식입니다. 복호화나 화면 캡처를 시도하지 않습니다.")
        with zipfile.ZipFile(path) as package:
            entries = package.infolist()
            if len(entries) > MAX_PARTS or sum(v.file_size for v in entries) > MAX_EXPANDED:
                raise ArtifactError("package_too_large", "PPT 내부 파일이 안전 처리 한도를 초과합니다.")
            names = {v.filename for v in entries}
            if len(names) != len(entries) or any(v.flag_bits & 1 or v.file_size > LIMIT or v.filename.startswith(("/", "\\")) or ".." in v.filename.replace("\\", "/").split("/") for v in entries):
                raise ArtifactError("unsafe_package", "PPT 내부 경로나 압축 구조가 안전 처리 기준에 맞지 않습니다.")
            if any("vbaproject" in n.lower() or "/activex/" in n.lower() or "/embeddings/" in n.lower() and not n.lower().endswith(".xlsx") for n in names):
                raise ArtifactError("active_content", "매크로 또는 실행 가능한 삽입 개체가 포함된 양식은 자동 처리하지 않습니다.")
            if "ppt/presentation.xml" not in names or "[Content_Types].xml" not in names:
                raise ArtifactError("invalid_template", "정상적인 PPTX 양식 구조를 찾지 못했습니다.")
            slides, layouts = [], []
            external = False
            for name in sorted(names):
                if name.startswith("ppt/embeddings/") and name.lower().endswith(".xlsx"):
                    _check_embedded_workbook(package.read(name))
                elif name.endswith(".rels"):
                    root = _xml(package.read(name))
                    external |= any(v.get("TargetMode", "").lower() == "external" for v in root)
                elif name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                    root = _xml(package.read(name))
                    slides.append({"part": name, "textShapes": len(root.findall(f".//{{{P}}}sp")),
                                   "tables": len(root.findall(f".//{{{A}}}tbl")), "pictures": len(root.findall(f".//{{{P}}}pic"))})
                elif name.startswith("ppt/slideLayouts/") and name.endswith(".xml"):
                    root = _xml(package.read(name))
                    common = root.find(f"{{{P}}}cSld")
                    layouts.append({"part": name, "name": common.get("name", "") if common is not None else ""})
            presentation = _xml(package.read("ppt/presentation.xml"))
            size = presentation.find(f"{{{P}}}sldSz")
            warnings = ["이미지나 지원하지 않는 원본 개체까지 편집 가능하다고 보장하지 않습니다."]
            if external:
                warnings.append("외부 연결이 있습니다. 자동 제작은 중단되며 연결 해제는 원본 작성자가 결정해야 합니다.")
            return {"ok": True, "status": "inspected", "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "slides": slides, "layouts": layouts, "slideCount": len(slides), "hasExternalRelationships": external,
                    "sizeEmu": {"width": int(size.get("cx", "0")), "height": int(size.get("cy", "0"))} if size is not None else None,
                    "warnings": warnings, "editability": "native-objects-detected-not-full-reconstruction"}
    except zipfile.BadZipFile:
        return _failure(ArtifactError("protected_or_invalid", "파일이 보호되었거나 정상 PPTX가 아닙니다. 다른 방식으로 내용을 추출하지 않았습니다.", "unknown"))
    except Exception as exc:
        return _failure(exc)


def capabilities() -> dict[str, Any]:
    found = importlib.util.find_spec("pptx") is not None
    shell = _windows_powershell()
    return {"ok": True, "html": {"available": True, "styles": list(STYLES), "modes": list(MODES), "offline": True},
            "ppt": {"pythonPptxAvailable": found, "powerShellAvailable": shell is not None,
                    "powerPointInstalled": "checked-when-requested" if shell else "unavailable",
                    "automaticDownload": False, "templateFormats": [".pptx"],
                    "notes": "생성은 python-pptx 또는 Windows PowerPoint가 필요합니다. 이미지 미리보기는 PowerPoint가 있어야 합니다."}}


def _windows_powershell() -> str | None:
    """Resolve the Windows binary without consulting PATH or the current folder."""
    if os.name != "nt":
        return None
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        directory = ctypes.create_unicode_buffer(32768)
        size = kernel.GetSystemDirectoryW(directory, len(directory))
        if not 0 < size < len(directory):
            return None
        executable = Path(directory.value) / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        _reject_reparse(executable)
        return str(executable) if executable.is_absolute() and executable.is_file() else None
    except Exception:
        return None


def _fit_preflight(data: dict[str, Any]) -> None:
    for row in data["sections"]:
        count = sum(bool(row.get(k)) for k in ("body", "bullets", "table", "chart", "image"))
        if count > 3 or len(row["title"]) > 90 or len(row["body"]) > 900 or len(row["bullets"]) > 8 or any(len(v) > 160 for v in row["bullets"]):
            raise ArtifactError("slide_too_dense", "한 슬라이드의 내용이 많습니다. 제목·본문을 줄이거나 여러 장으로 나누어 주세요.")
        if "table" in row and (len(row["table"]["rows"]) > 10 or len(row["table"]["headers"]) > 8 or any(len(v) > 100 for r in row["table"]["rows"] for v in r)):
            raise ArtifactError("slide_table_too_dense", "PPT 표는 10행·8열 이하로 나누고 긴 셀 내용을 줄여 주세요.")


def _python_ppt(data: dict[str, Any], draft: Path, template: Path | None) -> dict[str, Any]:
    from .presentation_design import render_python
    return render_python(data, draft, template)


def _office(data: dict[str, Any], draft: Path, template: Path | None, work: Path, render_only: bool) -> dict[str, Any]:
    shell = _windows_powershell()
    if not shell:
        return {"ok": False, "status": "unavailable", "code": "powerpoint_unavailable", "message": "Windows PowerPoint 실행 환경이 없어 이미지 미리보기를 만들지 못했습니다."}
    request = work / "office-request.json"
    payload = {"spec": data, "output": str(draft), "template": str(template) if template else None,
               "renderOnly": render_only, "previewDirectory": str(work / "preview")}
    request.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    runner = Path(__file__).resolve().parents[1] / "Invoke-BusinessPowerPoint.ps1"
    try:
        process = subprocess.run([shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(runner), "-RequestPath", str(request)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        answer = json.loads(process.stdout.decode("utf-8-sig"))
        if not isinstance(answer, dict) or "ok" not in answer:
            raise ValueError("invalid office result")
        # Never return raw Office errors or stderr: these may contain private paths/content.
        allowed = {"ok", "status", "code", "message", "rendered", "slides", "editability", "diagnostic"}
        return {key: answer[key] for key in allowed if key in answer}
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "unknown", "code": "office_timeout", "message": "PowerPoint 작업 제한 시간을 초과했습니다. 사용 중인 PowerPoint를 종료하지 않았습니다."}
    except Exception:
        return {"ok": False, "status": "unknown", "code": "office_failed", "message": "PowerPoint 작업을 확인하지 못했습니다. 보안 설정을 변경하거나 다른 캡처 방식으로 재시도하지 않았습니다."}


def preview_template(template: Path, output: Path) -> dict[str, Any]:
    try:
        checked = inspect_template(template)
        if not checked.get('ok'):
            return checked
        if checked.get('hasExternalRelationships'):
            raise ArtifactError('external_template_links','외부 연결이 있는 양식은 미리보기를 만들지 않습니다.')
        output = safe_path(output)
        _reject_reparse(output)
        if output.exists():
            raise FileExistsError(output)
        with tempfile.TemporaryDirectory(prefix='company-template-preview-',ignore_cleanup_errors=True) as temp:
            work=Path(temp)
            draft=work/'reference.pptx'
            draft.write_bytes(Path(template).read_bytes())
            if hashlib.sha256(draft.read_bytes()).hexdigest()!=checked['sha256']:
                raise ArtifactError('template_changed','분석 후 양식이 변경되었습니다. 다시 확인해 주세요.')
            result=_office({},draft,None,work,True)
            if not result.get('ok'):
                return result
            images=sorted((work/'preview').glob('slide-*.png'))
            if len(images)!=checked['slideCount']:
                raise ArtifactError('preview_incomplete','일부 장의 미리보기가 빠져 전체 확인을 완료하지 못했습니다.')
            output.mkdir(parents=True,exist_ok=False)
            for file in images:
                _publish(file,output/file.name)
            return {'ok':True,'status':'created','previews':[str(output/f.name) for f in images],
                    'visualReview':'required','sourcePreserved':True}
    except Exception as exc:
        return _failure(exc)


def create_ppt(spec: dict[str, Any], output: Path, template: Path | None = None, *, require_choices: bool = False, preview_only: bool = False) -> dict[str, Any]:
    try:
        output = _target(output, ".pptx")
        from . import ppt_workflow
        if require_choices:
            from .business_safety import blocked_input
            if (blocked := blocked_input(spec)) is not None:
                return blocked
            selected = ppt_workflow.choices(spec, template, for_preview=preview_only)
            if not selected.get('ok'):
                return selected
            if not preview_only:
                ppt_workflow.verify_design_review(spec, template)
        data = _normalize(spec)
        if require_choices and spec['slideCount'] != len(data['sections']):
            raise ArtifactError('slide_count_mismatch','생성할 장수가 선택한 장수와 다릅니다. 몰래 늘리거나 줄이지 않았습니다.')
        review_digest = ppt_workflow.design_digest(spec,template) if preview_only else None
        preserve = bool(template and spec.get('referenceMode') == 'preserve')
        from . import presentation_design, report_facts
        try:
            arithmetic = presentation_design.prepare(spec, data)
        except (presentation_design.DesignError, report_facts.FactError) as exc:
            raise ArtifactError("ppt_design_invalid", str(exc)) from None
        # Resolve facts against the FULL job before selecting representative pages.
        # Preview does not grant authority to generate the remaining slides.
        preview_indices = list(range(min(2,len(data['sections']))))
        preview_outline = [row['title'] for row in data['sections']]
        if preview_only:
            data['sections'] = [data['sections'][i] for i in preview_indices]
        _fit_preflight(data)
        inspected = inspect_template(template) if template else None
        if inspected and not inspected["ok"]:
            return inspected
        if inspected and inspected["hasExternalRelationships"]:
            raise ArtifactError("external_template_links", "양식에 현재 제작 기능이 지원하지 않는 외부 연결이 있어 자동 제작을 중단했습니다.")
        size = inspected.get("sizeEmu", {}) if inspected else {}
        try:
            data['presentationPlan'] = presentation_design.plan(
                data, size.get('width', 12192000) / 12700, size.get('height', 6858000) / 12700) if not preserve else {}
        except presentation_design.DesignError as exc:
            raise ArtifactError("ppt_design_invalid", str(exc)) from None
        python_available = importlib.util.find_spec("pptx") is not None
        if preserve and not python_available:
            raise ArtifactError('template_engine_unavailable','양식 유지 제작에 필요한 python-pptx가 없습니다. 자동 설치나 다른 제작 방식으로 바꾸지 않았습니다.')
        # Office can retain a handle after a timeout. Do not kill its process or
        # mask a saved output with cleanup errors when a temporary file is locked.
        with tempfile.TemporaryDirectory(prefix="company-presentation-", ignore_cleanup_errors=True) as temp:
            work = Path(temp)
            draft = work / "draft.pptx"
            copy = None
            if template:
                copy = work / "template.pptx"
                copy.write_bytes(Path(template).read_bytes())
                if hashlib.sha256(copy.read_bytes()).hexdigest() != inspected["sha256"]:
                    raise ArtifactError("template_changed", "확인 후 원본 양식이 변경되었습니다. 다시 확인해 주세요.")
            if python_available:
                mappings=spec.get('templateSlides')
                if preview_only and isinstance(mappings,list):
                    mappings=[mappings[i] for i in preview_indices if i<len(mappings)]
                native = ppt_workflow.fill_template(data,draft,copy,mappings) if preserve else _python_ppt(data, draft, copy)
                engine = "python-pptx"
                visual = _office(data, draft, None, work, True)
            else:
                visual = _office(data, draft, copy, work, False)
                if not draft.exists() or (not visual.get("ok") and visual.get("code") != "render_refused"):
                    return visual
                native = {"text": "native", "tables": "native", "charts": "native", "images": "raster"}
                engine = "powerpoint-com"
            structure = inspect_template(draft)
            if not structure["ok"] or structure["slideCount"] != len(data["sections"]):
                raise ArtifactError("ppt_validation_failed", "생성한 PPT의 구조 검증에 실패해 결과물을 저장하지 않았습니다.", "unknown")
            # Rendering refusal is reported as partial, never retried through an alternate capture path.
            try:
                quality = ppt_workflow.quality(draft)
            except Exception:
                quality = {'status':'unavailable','message':'추가 품질 검사를 완료하지 못했습니다. 구조 검사와 별개로 확인이 필요합니다.'}
            quality['archforge'] = ppt_workflow.optional_archforge(draft)
            if quality['archforge']['status']=='issues_found':
                quality['status']='issues_found'
            if preview_only and review_digest != ppt_workflow.design_digest(spec,template):
                raise ArtifactError('design_review_changed','대표 슬라이드 생성 중 명세 또는 원본 양식이 달라졌습니다.')
            if require_choices and not preview_only:
                ppt_workflow.verify_design_review(spec,template)
            _publish(draft, output)
            previews = []
            preview_source = work / "preview"
            if visual.get("ok") and preview_source.is_dir():
                preview_target = output.parent / (output.stem + "-preview")
                try:
                    preview_target.mkdir(exist_ok=False)
                    for picture in sorted(preview_source.glob("slide-*.png")):
                        _publish(picture, preview_target / picture.name)
                        previews.append(str(preview_target / picture.name))
                except FileExistsError:
                    visual = {"ok": False, "status": "blocked", "code": "preview_exists", "message": "기존 미리보기 파일·폴더를 보존했습니다. PPT 파일은 생성했습니다."}
                except OSError as error:
                    # The presentation was already published. Do not hide it or
                    # retry an export after an independent preview failure.
                    visual = _failure(error)
                    visual["message"] = "PPT 파일은 생성했지만 미리보기 저장은 완료하지 못했습니다. 다른 경로로 재출력하지 않았습니다."
            warnings = ["사진·배경 이미지와 원본의 지원하지 않는 개체는 개별 편집을 보장하지 않습니다.",
                        "이미지 출력은 육안 품질 검토를 돕습니다. 글자 잘림과 회사 양식 일치 여부는 미리보기에서 확인해 주세요."]
            if template:
                warnings.append('지정한 원본 슬라이드의 개체 배치를 유지하고 내용을 교체했습니다. 혼합 서식·그룹 개체 등은 지원하지 않습니다.' if preserve else "원본 테마·마스터·레이아웃을 재사용하며 예시 슬라이드는 제거합니다. 원본 화면의 정확한 재구성은 보장하지 않습니다.")
            if quality.get('status') != 'checked':
                warnings.append('개체 범위·글자 크기 검사에 확인할 항목이 있습니다. 최종 완료로 보고하지 말고 확인해 주세요.')
            if not visual.get("ok"):
                warnings.append(visual.get("message", "이미지 미리보기를 만들지 못했습니다."))
            review = {'designReview':{'specSha256':review_digest,
                       'previewPath':str(output.resolve()),'previewSha256':hashlib.sha256(output.read_bytes()).hexdigest(),
                       'confirmed':False}, 'previewOnly':True,'stage':'design_confirm',
                       'outline':preview_outline} if preview_only else {}
            return {**review,"ok": True, "status": "created" if visual.get("ok") and quality.get('status') == 'checked' else "partial", "outputPath": str(output),
                    "engine": engine, "slides": len(data["sections"]), "editability": native,
                    "validation": {"structure": "passed", "render": visual, "visualReview": "required",
                                   "arithmetic": arithmetic, "quality":quality, "layout": 'template-slots-preserved' if preserve else "bounded-plan-checked-not-visual-proof"},
                    "previews": previews, "warnings": warnings}
    except Exception as exc:
        return _failure(exc)
