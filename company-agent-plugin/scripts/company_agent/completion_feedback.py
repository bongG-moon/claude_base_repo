"""Localize Stop notices without discarding the model's next action.

The reason is execution feedback, not just a UI label. The state engine emits
a bounded, self-contained instruction; replacing it with a progress message
would make the model rediscover the current session, command and guide.
"""
from __future__ import annotations

from typing import Any


def present_stop_feedback(result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result.get("systemMessage"), str):
        message = result["systemMessage"]
        translations = {
            "Company Agent stopped after the same verification failure repeated.": "같은 결과 확인 실패가 반복되어 재시도를 멈췄습니다.",
            "Company Agent stopped after two corrective verification attempts.": "두 번의 보정 후에도 결과 확인을 마치지 못해 재시도를 멈췄습니다.",
            "Verification did not pass; do not treat this run as successful.": "검증을 통과하지 못했으므로 성공한 작업으로 처리하지 마세요.",
            "Report the failure evidence and the required next action honestly.": "확인된 실패와 필요한 다음 조치만 안내하세요.",
            "Report the unverified changes and the required next action honestly.": "확인하지 못한 변경과 필요한 다음 조치만 안내하세요.",
            "Company Agent could not finish this turn's automatic learning after two attempts.": "자동 학습을 두 번 시도했지만 완료하지 못했습니다.",
            "The review is deferred; do not claim that memory or skills were improved.": "학습을 보류했습니다. 기억이나 스킬이 개선되었다고 안내하지 마세요.",
            "Report the task outcome and any remaining verification failure honestly.": "업무 결과와 남은 확인 실패를 구분해 안내하세요.",
        }
        for original, translated in translations.items():
            message = message.replace(original, translated)
        result = {**result, "systemMessage": message}
    # Do not truncate commands or remove context from either verification or
    # learning feedback. This layer must not claim a check is already running.
    return result
