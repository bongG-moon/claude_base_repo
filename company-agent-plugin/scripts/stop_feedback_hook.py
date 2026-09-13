from __future__ import annotations

import json
import sys

from company_agent.state import stop_decision
from company_agent.completion_feedback import present_stop_feedback


_FAILURE_OUTPUT = {
    "systemMessage": (
        "결과 확인 기록을 읽을 수 없어 완료 여부를 판단하지 못했습니다. "
        "검증되지 않은 결과를 성공으로 처리하지 마세요."
    )
}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        result = present_stop_feedback(stop_decision(payload if isinstance(payload, dict) else {}))
    except Exception:
        # End safely instead of crashing the hook or creating an unbounded Stop
        # loop. Never include exception or payload details in user-visible text.
        result = _FAILURE_OUTPUT
    json.dump(result, sys.stdout, ensure_ascii=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
