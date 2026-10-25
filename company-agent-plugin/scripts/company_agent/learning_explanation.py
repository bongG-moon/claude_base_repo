"""On-demand Korean summary of existing learning evidence; no model inference.

Only the explicit CLI status --explain path imports this module. Do not put the
summary in prompt hooks: absence of evidence must never become extra work.
"""
from __future__ import annotations


def read_explanation_session(root, session_id):
    """Read only an explicitly named snapshot, without creating state/lock files."""
    import json
    from pathlib import Path
    from .state import native_session_id, _safe_local_path
    if not session_id or native_session_id(session_id) != session_id:
        return None
    root = Path(root).absolute()
    path = root / "sessions" / (session_id + ".json")
    if not _safe_local_path(path, root):
        return None
    try:
        with path.open("rb") as stream:
            raw = stream.read(4_194_305)
        if len(raw) > 4_194_304:
            return None
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("sessionId") != session_id or value.get("schemaVersion") != 1:
            return None
        # Only the receipt fields are needed; never return full prompts/tool history.
        return {key: value.get(key) for key in
                ("sessionId", "turnId", "learningSubmission", "lastMemoryDelivery")}
    except (OSError, ValueError, TypeError, RecursionError):
        return None


_SUBMISSION = {
    "captured": "학습할 내용을 접수했습니다. 접수와 실제 적용은 다릅니다.",
    "no_candidates": "확인했지만 새로 저장할 학습 내용이 없었습니다.",
    "not_submitted": "이번 요청에서는 학습 내용을 제출한 기록이 없습니다. 일반 작업에서는 정상입니다.",
    "not_observable": "현재 요청의 학습 접수 여부를 확인할 정보가 없습니다.",
}
_DELIVERY = {
    "output-produced": "기억을 모델 입력용 후크 출력에 포함했습니다. 모델 수신·답변 반영은 확인되지 않았습니다.",
    "budget-dropped": "관련 기억을 찾았지만 입력 분량 제한으로 이번 후크 출력에서 제외했습니다. 기억은 삭제되지 않았습니다.",
    "no-matches": "이번 요청에 자동으로 참고할 기억을 찾지 못했습니다. 저장된 기억이 없다는 뜻은 아닙니다.",
    "not-observable": "현재 대화의 기억 전달 여부를 확인할 기록이 없습니다. 다른 대화를 찾아보지 않습니다.",
}
_CANDIDATE = {
    "active": "적용 기록 있음", "observing": "반복 사용 근거를 모으는 중",
    "deferred": "적용 보류", "rejected": "적용하지 않음",
}
_REASONS = {
    "skill_requires_success_and_current_verification": "업무 성공과 현재 스킬 확인 근거가 부족합니다.",
    "independent_work_sample_not_ready": "서로 다른 업무에서 반복됐는지 아직 확인되지 않았습니다.",
    "verified_fix_requires_observed_failure_then_pass": "실패 후 수정으로 해결된 근거가 부족합니다.",
}


def _count(value):
    return value if type(value) is int and value >= 0 else 0


def explain_learning(status: dict) -> dict:
    """Summarize already-read receipts, without enumerating memories or sessions."""
    submission = status.get("currentSubmission") or {}
    delivery = status.get("memoryDelivery") or {}
    delivery_code = delivery.get("status", "not-observable")
    text = _DELIVERY.get(delivery_code, _DELIVERY["not-observable"])
    if delivery.get("currentTurn") is False:
        text = "이전 요청의 마지막 기록입니다. 현재 요청에는 적용 여부를 알 수 없습니다. " + text
    scope = (status.get("storage") or {}).get("scopeLabel")
    candidates = []
    for item in (status.get("recentCandidates") or [])[-10:]:
        if not isinstance(item, dict):
            continue
        reason = item.get("reason")
        candidates.append({
            "title": str(item.get("title", "이름 미확인"))[:160],
            "state": _CANDIDATE.get(item.get("status"), "상태 미확인"),
            "reason": _REASONS.get(reason, "세부 사유는 상세 학습 기록에서 확인할 수 있습니다.") if reason else "",
        })
    return {
        "automaticLearning": "설정 켜짐" if status.get("enabled") else "일시 중지",
        "scope": scope if isinstance(scope, str) else "저장 범위 미확인",
        "submission": {
            "message": _SUBMISSION.get(submission.get("captureStatus"), _SUBMISSION["not_observable"]),
            "capturedCount": _count(submission.get("capturedCount")),
            "appliedCount": _count(submission.get("appliedCount")),
            "deferredCount": _count(submission.get("deferredCount")),
        },
        "storedLearning": {
            "activeChangeRecords": _count(status.get("activeChanges")),
            "candidateRecords": _count(status.get("candidateCount")),
            "message": "자동 학습 기록의 수입니다. 수동 기억 전체나 파일의 현재 상태를 다시 검사한 결과는 아닙니다.",
        },
        "memoryDelivery": {"status": delivery_code, "message": text,
                           "count": _count(delivery.get("count")),
                           "currentTurn": delivery.get("currentTurn"),
                           "items": [{key: item.get(key) for key in ("id", "revision", "storageScope")}
                                     for item in (delivery.get("items") or [])[:5] if isinstance(item, dict)]},
        "recentCandidates": candidates,
        "nextStep": "특정 기억이 궁금하면 제목과 저장 범위로 조회하세요. 이 설명만으로 기억을 다시 저장하거나 업무를 재실행할 필요는 없습니다.",
    }
