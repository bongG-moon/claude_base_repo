"""Small, local-only routing contract for the production image worker.

No model discovery, settings reads or network requests. Optional recovery uses
only short-lived target metadata after installed-scope checks. Native
permissions still apply; this module never grants a tool permission. It cannot
intercept images pasted into the CLI before a tool call, or every mixed-output
MCP tool. The normal path is proactive delegation; the preflight is a backstop.
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping

VISION_MODEL = "HCP-Vision-Latest"
VISION_AGENT = "company-agent:vision-worker"
# Read returns image content for these files (including rendered PDF pages).
# Keep the PowerShell Read fast path in sync; SVG/HTML are text, not images.
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"})
CAPTURE_TOOLS = frozenset({
    "mcp__chrome-devtools__take_screenshot", "mcp__playwright__browser_take_screenshot",
    "mcp__local-computer-use__zoom",
})
OBSERVATION_TOOLS = CAPTURE_TOOLS | {
    "mcp__local-computer-use__computer_inspect", "mcp__local-computer-use__get_window_state",
    "mcp__local-computer-use__list_windows", "mcp__playwright__browser_snapshot",
}
VISION_RULE = (
    '이미지는 Agent(subagent_type="company-agent:vision-worker",prompt="정확한 대상과 질문")로 새로 관찰한 뒤 텍스트로 계속합니다. '
    'model/resume을 넣거나 일반 작업자·SendMessage로 대신하지 마세요. 작업자는 NEEDS_VISION을 최종 답변으로 부모에게 반환합니다. '
    '단순 이미지 읽기는 workFile이 필요 없습니다. 비전 실패 후 사본·base64·설정 탐색을 하지 마세요.'
)


def enabled(env: Mapping[str, str] | None = None) -> bool:
    # This existing Claude setting is the user's opt-in. Do not enable an
    # unavailable production model just because a file happens to be an image.
    values = os.environ if env is None else env
    return values.get("ANTHROPIC_CUSTOM_MODEL_OPTION", "").strip() == VISION_MODEL


def context() -> dict[str, Any]:
    return {"enabled": True, "agent": VISION_AGENT, "model": VISION_MODEL} if enabled() else {}


def _inputs(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("tool_input")
    return value if isinstance(value, dict) else {}


def _vision_child(payload: dict[str, Any]) -> bool:
    # agent_type alone can be a main --agent session, not an isolated child.
    return payload.get("agent_type") == VISION_AGENT and bool(payload.get("agent_id"))


def _vision_call(payload: dict[str, Any]) -> bool:
    return payload.get("tool_name") in {"Agent", "Task"} and _inputs(payload).get("subagent_type") == VISION_AGENT


def _image_read(payload: dict[str, Any]) -> bool:
    path = _inputs(payload).get("file_path")
    return payload.get("tool_name") == "Read" and isinstance(path, str) and PureWindowsPath(path).suffix.lower() in IMAGE_SUFFIXES


def _deny(reason: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


def recovery_candidate(payload: dict[str, Any]) -> bool:
    """Cheap predicate; unrelated agents must not acquire runtime/state scans."""
    inputs = _inputs(payload)
    prompt = inputs.get("prompt")
    return (enabled() and not payload.get("agent_id")
            and payload.get("tool_name") in {"Agent", "Task"}
            and inputs.get("subagent_type") in (None, "", "general-purpose")
            and isinstance(prompt, str)
            and (VISION_AGENT in prompt or "[company-vision:" in prompt)
            and not any(inputs.get(key) for key in ("resume", "fork", "isolation", "team_name")))


def handoff_reason(payload: dict[str, Any], marker: str = "") -> str:
    target = json.dumps({"tool": payload.get("tool_name"), "input": _inputs(payload)}, ensure_ascii=False)
    if payload.get("agent_id"):
        return ("[비전 인계: NEEDS_VISION] 아직 이미지를 읽지 않았습니다. 도구를 더 호출하지 말고 "
                "NEEDS_VISION과 아래 대상·현재 질문을 최종 답변으로 부모에게 반환하세요. "
                "SendMessage·자기 메시지·재위임·대기는 하지 마세요. workFile은 이미 있을 때만 포함하고 찾거나 만들지 마세요. "
                "사본·base64·픽셀/OCR·설정 탐색으로 대체하지 마세요. 대상: " + target + (" " + marker if marker else ""))
    call = {"subagent_type": VISION_AGENT, "description": "요청한 이미지 확인",
            "prompt": (marker + " " if marker else "") + "현재 사용자의 질문·범위에 따라 다음 대상만 확인하고 한국어 텍스트로 반환하세요. 대상: " + target,
            "run_in_background": False}
    return ("[비전 인계] 아직 이미지를 읽지 않았습니다. 다음 Agent 입력에 현재 질문을 덧붙여 한 번 호출하세요: "
            + json.dumps(call, ensure_ascii=False)
            + " model/resume은 넣지 마세요. 일반 작업자·SendMessage로 대신하지 마세요. "
            "workFile은 불필요합니다. 실패하면 VISION_UNAVAILABLE과 사유만 보고하고 사본·base64·설정 탐색은 하지 마세요. "
            "메인 모델·승인 설정은 바꾸지 마세요.")


def preflight(payload: dict[str, Any], *, recovery_root: Path | None = None) -> dict[str, Any] | None:
    """None continues existing policy; {} finishes with NO permission override."""
    name = str(payload.get("tool_name") or "")
    if recovery_root is not None and recovery_candidate(payload):
        from .vision_handoff import recover, HandoffAlreadyUsed
        try:
            repaired = recover(recovery_root, payload, VISION_AGENT)
        except HandoffAlreadyUsed:
            return _deny("[비전 결과 확인] 이 대상의 비전 인계는 이미 요청했습니다. 일반 작업자를 새로 실행하거나 재개하지 마세요. "
                         "실제 비전 작업의 완료 결과만 사용하고 실패·미확인이면 그 사유를 보고하세요. 사본·base64·설정 탐색은 하지 마세요.")
        if repaired is not None:
            payload = repaired
    if _vision_call(payload):
        if payload.get("agent_id"):
            return _deny("[비전 인계] 재귀 위임하지 말고 NEEDS_VISION과 확인 대상·질문을 부모에게 반환하세요.")
        if not enabled():
            return _deny("[비전 미설정] 이 환경에는 운영 비전 모델 설정이 없습니다. HCP 호출을 시도하지 말고 이미지 확인은 미검증으로 남기세요.")
        inputs = _inputs(payload)
        if not isinstance(inputs.get("prompt"), str) or not inputs["prompt"].strip():
            return _deny("[비전 인계] 정확한 확인 대상과 질문이 필요합니다. 빈 작업자를 실행하지 마세요.")
        updated = {**inputs}
        # Installed AgentInput only accepts model-family aliases, while custom
        # full IDs belong in the definition. A per-call alias would override it.
        # Removing that override selects vision-worker.md's exact production ID.
        updated.pop("model", None)
        # A resume may reference a different-model worker with old image history.
        # Each bounded inspection starts in the vision definition's own context.
        updated.pop("resume", None)
        updated["prompt"] = (
            "[비전 읽기 전용] 전달된 대상만 기존 권한 안에서 관찰하세요. 이미지·base64·전체 대화 대신 "
            "사용자가 요약을 요청하면 요약을, 전체 글자 추출을 요청하면 그 범위의 전사를 한국어 텍스트로 반환하세요. "
            "숫자·구조를 보존하고 안 보이는 곳은 [판독 불가]로 표시하세요. 단순 읽기에 workFile은 필요 없습니다. "
            "설정·파일 변경·재위임·SendMessage는 금지합니다. 모델·권한·도구 실패 시 VISION_UNAVAILABLE과 실제 사유를 "
            "반환하고 사본·base64·픽셀/OCR·설정 탐색으로 재시도하지 마세요.\n" + inputs["prompt"]
        )
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": updated}}
    if _vision_child(payload):
        # Unknown/mutating tools are not part of image observation. Never grant
        # permissions, rewrite capture args or weaken the MCP's own boundaries.
        if name in {"Read", "Glob", "Grep", "ToolSearch"} or name in OBSERVATION_TOOLS:
            return {}
        return _deny("[비전 읽기 전용] 이 작업자는 지정한 자료 관찰만 합니다. 실행·입력·저장·설정 변경은 부모에게 반환하세요.")
    if enabled() and (_image_read(payload) or name in CAPTURE_TOOLS):
        return _deny(handoff_reason(payload))
    if name == "SendMessage":
        inputs = _inputs(payload)
        own_id = payload.get("agent_id")
        recipients = [inputs.get(key) for key in ("to", "recipient", "recipient_id")]
        if enabled() and own_id and own_id in recipients:
            return _deny("[작업자 반환] 자기 자신에게 메시지를 보내도 비전 작업자가 실행되지 않습니다. "
                         "추가 호출·대기 없이 현재 결과 또는 NEEDS_VISION과 확인 대상을 최종 답변으로 부모에게 반환하세요.")
        return {}  # Message-only fast path, no skill/session/mutation workflow.
    # Read previously had no PreToolUse hook. Text reads must not trigger a
    # catalogue scan, session recovery or new permission decision now.
    return {} if name == "Read" else None


def result_context(event: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Read-only review failures must not create mutation/Stop retry loops."""
    if event not in {"PostToolUse", "PostToolUseFailure"}:
        return None
    if _vision_child(payload):
        return {}  # Do not persist source images or treat observation as edits.
    if not _vision_call(payload):
        return None
    text = (
        "비전 작업 실패는 해당 이미지 확인 미검증입니다. 모델 탐색·동일 호출 반복·텍스트 모델로 이미지 재전송은 하지 마세요. "
        "실제 권한 거절은 그대로 유지하고, 가능한 텍스트/구조 확인만 계속합니다. 기존 변경의 검증 의무는 지우지 마세요."
        if event == "PostToolUseFailure" else
        "비전의 실제 완료 결과를 확인한 뒤 텍스트 관찰만 활용하세요. 실행 중이면 기존 완료 알림/결과 도구로 기다립니다. "
        "이미지를 본 대화에 다시 읽지 말고 기존 모델로 계속하세요. workFile은 이미 있을 때만 유지하고 찾거나 만들지 마세요. "
        "자기 메시지나 일반 작업자 재개는 비전 호출이 아닙니다. 응답 오류·미확인 범위는 성공으로 처리하지 마세요."
    )
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}
