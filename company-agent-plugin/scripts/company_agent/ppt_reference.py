"""Bounded PPT reference routing. A capture plan neither captures nor grants access."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .business_artifacts import _failure, _source
from .business_safety import safe_path
from .ppt_workflow import analyze

BATCH_SIZE = 3
MAX_SELECTED_SLIDES = 60
_DENIED = {"permission_denied", "capture_denied", "ai_processing_denied", "drm_blocked", "protection_blocked"}
_AMBIGUOUS_FORMATS = {"protected_or_unsupported", "protected_or_invalid", "invalid_template", "artifact_failed"}


def summarize_reference(result: dict[str, Any]) -> dict[str, Any]:
    """Return compact style evidence without source text or duplicate analysis.

    This never claims a visual inspection. The complete response remains
    available through the caller's explicit detailed option.
    """
    if not result.get('ok') or not isinstance(result.get('analysis'), dict):
        return result
    analysis = result['analysis']
    pages = analysis.get('slides', [])
    compact = {k: analysis[k] for k in ('sha256', 'sizeEmu', 'themeColors',
               'declaredColors', 'declaredFonts', 'suggestedPresentationProfile') if k in analysis}
    compact['slides'] = [{'sourceSlide': p.get('sourceSlide'),
                          'examinedShapeCount': len(p.get('shapes', [])),
                          'shapesTruncated': p.get('shapesTruncated', False),
                          'groupCount': p.get('groupCount', 0)} for p in pages]
    samples, seen = [], set()
    for kind in ('declaredTextStyles', 'declaredShapeStyles', 'declaredParagraphStyles'):
        category_count = 0
        for page in pages:
            for sample in page.get(kind, []):
                cleaned = {k: v for k, v in sample.items() if k != 'shapeId'}
                key = (kind, repr(cleaned))
                if key not in seen and category_count < 4:
                    seen.add(key)
                    samples.append({'sourceSlide': page.get('sourceSlide'), 'kind': kind, 'style': cleaned})
                    category_count += 1
    compact['styleSamples'] = samples
    result = {key: value for key, value in result.items() if key != 'analysis'}
    result['analysis'] = compact
    result['contentCoverage'] = 'source_text_and_per_object_coordinates_omitted'
    result['message'] = '선택한 장의 구조와 서식 표본만 요약했습니다. 원본 텍스트와 개체별 좌표는 요약에 포함하지 않았으며 실제 화면은 확인하지 않았습니다.'
    result['detailOmitted'] = '본문과 개체별 좌표는 요약에서 제외했습니다. 필요할 때 상세 분석을 요청하세요.'
    return result


def _error(code: str, message: str, *, status: str = "invalid_request") -> dict[str, Any]:
    return {"ok": False, "status": status, "code": code, "message": message,
            "captured": False, "sourcePreserved": True}


def _selection(value: Any) -> list[int] | None:
    if value is None:
        return None
    if (not isinstance(value, list) or not 1 <= len(value) <= MAX_SELECTED_SLIDES
            or any(type(number) is not int or not 1 <= number <= 10000 for number in value)
            or len(set(value)) != len(value)):
        raise ValueError("slides")
    return value


def _batches(slides: list[int]) -> list[list[int]]:
    return [slides[start:start + BATCH_SIZE] for start in range(0, len(slides), BATCH_SIZE)]


def prepare_reference(spec: dict[str, Any]) -> dict[str, Any]:
    """Inspect a chosen file, or describe the authorized screen-tool workflow.

    Never opens Office, exports slides, reads a protected file in screen mode,
    claims a connected capture tool, or treats parser failure as a DRM decision.
    """
    if not isinstance(spec, dict) or set(spec) - {"file", "inputMode", "purpose", "slides", "accessStatus"}:
        return _error("invalid_reference_spec", "참고 명세에는 file, inputMode, purpose, slides, accessStatus만 사용할 수 있습니다.")
    if not isinstance(spec.get("file"), str) or not spec["file"].strip():
        return _error("invalid_reference_spec", "이미 선택한 참고 파일의 절대경로를 지정해 주세요.")
    mode = spec.get("inputMode", "file")
    purpose = spec.get("purpose", "style")
    access = spec.get("accessStatus")
    if not isinstance(mode, str) or not isinstance(purpose, str) or mode not in {"file", "powerpoint-screen"} or purpose not in {"style", "content"}:
        return _error("invalid_reference_spec", "inputMode는 file/powerpoint-screen, purpose는 style/content입니다.")
    if access is not None and (not isinstance(access, str) or access not in _DENIED):
        return _error("invalid_reference_spec", "accessStatus에는 실제로 확인된 접근·캡처·AI 처리 거절만 지정합니다. DRM 이름이나 일반 읽기 오류는 거절 근거가 아닙니다.")
    if access in _DENIED:
        return {**_error(access, "해당 자료의 접근·캡처 또는 AI 처리가 거절되어 중단했습니다.", status="blocked"),
                "restrictionConfirmed": True, "retryAllowed": False, "nextAction": "report_restricted_scope"}
    try:
        selected = _selection(spec.get("slides"))
    except ValueError:
        return _error("invalid_slide_selection", "slides에는 중복 없는 1부터 시작하는 장 번호를 최대 60개 지정해 주세요.")
    try:
        original = Path(spec["file"])
        if not original.is_absolute():
            return _error("invalid_reference_path", "참고 파일에는 절대경로를 사용해 주세요.")
        path = safe_path(original, exists=True)
        if not path.is_file():
            return _error("input_missing", "선택한 참고 파일을 찾을 수 없습니다.")
        if mode == "powerpoint-screen":
            if path.suffix.lower() not in {".pptx", ".ppt"}:
                return _error("unsupported_format", "PowerPoint 화면 참고는 선택한 PPT/PPTX 문서를 대상으로 합니다.")
            selection = {"mode": "specified", "slides": selected} if selected else {
                "mode": "requested_scope", "maximumSlides": MAX_SELECTED_SLIDES,
                "scopeStatus": "confirm_from_open_document"}
            return {"ok": True, "status": "capture_plan", "inputKind": "powerpoint-screen",
                    "sourcePath": str(path), "purpose": purpose, "selection": selection,
                    "batches": _batches(selected) if selected else [], "batchSize": BATCH_SIZE,
                    "coverage": {"expectedSlides": selected, "inspectedSlides": [],
                                 "visuallyReviewedSlides": [], "missingSlides": selected,
                                 "status": "not_started"},
                    "toolAvailability": "not_checked_by_helper",
                    "nextAction": "use_connected_approved_screen_tool", "captured": False,
                    "authorizationGranted": False, "sourcePreserved": True, "savedToMemory": False,
                    "requirements": ["정상적으로 열린 정확한 PowerPoint 문서와 요청 장을 확인",
                                     "현재 연결된 실제 화면 도구와 허용된 캡처·AI 처리·저장 범위 확인",
                                     "허용된 요청 범위의 각 장을 정상 열기 또는 다음 장 이동 후 실제 장 번호와 연결해 캡처",
                                     "2~3장씩 비전 참고하고 빈 화면, 중복 캡처, 누락 장을 확인한 뒤 공통 스타일만 짧게 합침"],
                    "ifUnavailable": "도구가 없으면 허용 범위의 사용자 캡처를 요청합니다. 실제 캡처/AI 처리 거절이면 중단합니다.",
                    "message": "화면 참고 절차를 준비했습니다. 화면을 캡처하거나 문서를 열지 않았습니다. 파일 Export·복호화·보호 해제는 수행하지 않습니다."}
        if path.suffix.lower() in {".html", ".htm", ".png", ".jpg", ".jpeg", ".webp"}:
            _source(path, (".html", ".htm", ".png", ".jpg", ".jpeg", ".webp"))
            kind = "html" if path.suffix.lower() in {".html", ".htm"} else "image"
            return {"ok": True, "status": "reference_ready", "inputKind": kind,
                    "sourcePath": str(path), "nextAction": "use_existing_html_workflow" if kind == "html" else "review_selected_reference_image",
                    "captured": False, "sourcePreserved": True, "visualReview": "not_performed"}
        if path.suffix.lower() != ".pptx":
            return _error("unsupported_format", "PPTX, HTML 또는 PNG/JPEG/WebP 참고 자료를 사용해 주세요.")
        result = analyze(path, selected_slides=selected)
    except PermissionError as exc:
        return {**_failure(exc), "restrictionConfirmed": True, "retryAllowed": False,
                "nextAction": "report_restricted_scope", "captured": False, "sourcePreserved": True}
    except Exception as exc:
        return {**_failure(exc), "restrictionConfirmed": False, "captured": False, "sourcePreserved": True}
    if not result.get("ok"):
        code = result.get("code")
        if code in _AMBIGUOUS_FORMATS:
            return {**_error("reference_format_unreadable", "일반 PPTX 구조로 읽지 못했습니다. XML 문서나 특정 DRM으로 단정하지 않습니다. PowerPoint에서 정상 열 수 있으면 허용된 각 장을 이미지로 참고하세요.", status="unknown"),
                    "sourceReadCode": code, "restrictionConfirmed": False,
                    "nextAction": "check_known_source_context", "automaticCapture": False,
                    "availableRoutes": ["reference --mode office --output NEW_PREVIEW_FOLDER: PowerPoint 정상 열기와 허용된 이미지 내보내기", "reference --mode screen: 연결된 화면 도구로 실제 장별 캡처 계획"],
                    "doNotInfer": ["xml_document", "specific_drm_vendor", "capture_permission"]}
        return {**result, "restrictionConfirmed": code in _DENIED or code == "protected_input",
                "retryAllowed": False, "captured": False, "sourcePreserved": True}
    count = result["slideCount"]
    if count < 1:
        return _error("reference_has_no_slides", "참고할 장이 없습니다. 실제 장이 있는 자료를 선택해 주세요.")
    if selected is None:
        selected = list(range(1, count + 1))
    if len(selected) > MAX_SELECTED_SLIDES:
        return _error("reference_range_required", "참고 범위가 60장을 넘습니다. 필요한 장 범위를 나누어 지정해 주세요.", status="input_required")
    pages = {page["sourceSlide"] + 1: page for page in result["slides"] if type(page.get("sourceSlide")) is int}
    if any(number > count or number not in pages for number in selected):
        return _error("invalid_slide_selection", "선택한 장이 없거나 이 분석에서 확인할 수 없는 범위입니다. 원본의 실제 장 번호를 확인해 주세요.")
    return {"ok": True, "status": "reference_ready", "inputKind": "pptx", "sourcePath": str(path),
            "purpose": purpose, "slideCount": count, "selectedSlides": selected, "batches": _batches(selected),
            "batchSize": BATCH_SIZE,
            "coverage": {"expectedSlides": selected, "inspectedSlides": selected,
                         "visuallyReviewedSlides": [], "missingSlides": selected,
                         "status": "structure_only"},
            "analysis": {**result, "slides": [pages[number] for number in selected]},
            "nextAction": "read_requested_content" if purpose == "content" else "use_selected_reference_structure", "sourcePreserved": True,
            "contentCoverage": "bounded_shape_previews_not_full_content",
            "captured": False, "savedToMemory": False, "visualReview": "not_performed",
            "message": "선택한 장의 구조를 확인했습니다. 텍스트는 개체당 160자·장당 80개까지의 미리보기이며 전체 내용 확인을 대신하지 않습니다. 실제 화면은 아직 확인하지 않았습니다."}
