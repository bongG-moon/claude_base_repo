"""Small, local-only routing contract for the production image worker.

No model discovery, settings reads, network requests or session writes. Native
permissions still apply; this module never grants a tool permission. It cannot
intercept images pasted into the CLI before a tool call, or every mixed-output
MCP tool. The normal path is proactive delegation; the preflight is a backstop.
"""
from __future__ import annotations

import os
from pathlib import PureWindowsPath
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
    "이미지→visionRouting.agent→텍스트. 작업자는 NEEDS_VISION 반환."
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


def preflight(payload: dict[str, Any]) -> dict[str, Any] | None:
    """None continues existing policy; {} finishes with NO permission override."""
    name = str(payload.get("tool_name") or "")
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
            "확인된 내용/문제/미확인 범위를 짧은 한국어 텍스트로 반환하세요. 설정·파일 변경·재위임은 금지합니다. "
            "모델·권한·도구 실패 시 원인을 추측하거나 다른 경로로 재시도하지 마세요.\n" + inputs["prompt"]
        )
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": updated}}
    if _vision_child(payload):
        # Unknown/mutating tools are not part of image observation. Never grant
        # permissions, rewrite capture args or weaken the MCP's own boundaries.
        if name in {"Read", "Glob", "Grep", "ToolSearch"} or name in OBSERVATION_TOOLS:
            return {}
        return _deny("[비전 읽기 전용] 이 작업자는 지정한 자료 관찰만 합니다. 실행·입력·저장·설정 변경은 부모에게 반환하세요.")
    if enabled() and (_image_read(payload) or name in CAPTURE_TOOLS):
        if payload.get("agent_id"):
            return _deny("[비전 인계: NEEDS_VISION] 아직 이미지를 읽지 않았습니다. 정확한 파일 경로 또는 관찰 도구·인자, 질문과 workFile을 부모에게 반환하세요. 재귀 위임하지 마세요.")
        return _deny("[비전 인계] 아직 이미지를 읽지 않았습니다. 이 읽기 요청의 정확한 경로 또는 도구·인자를 company-agent:vision-worker에 전달하고 텍스트 결과로 계속하세요. 메인 모델·승인 설정은 바꾸지 마세요.")
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
        "이미지를 본 대화에 다시 읽지 말고 기존 모델·같은 workFile로 계속하세요. 응답 오류·미확인 범위는 성공으로 처리하지 마세요."
    )
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}
