from __future__ import annotations

import json
import sys

from company_agent.state import record_activity
from company_agent.business_safety import protection_notice


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if isinstance(payload, dict):
            record_activity(payload)
        result = {}
        notice = protection_notice(payload)
        if notice:
            event = str(payload.get("hook_event_name") or "PostToolUse")
            if event not in {"PostToolUse", "PostToolUseFailure"}:
                event = "PostToolUse"
            result = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": notice},
                      "systemMessage": "처리하지 못한 보호 자료가 있습니다. 해당 자료를 제외한 범위만 결과에 반영하도록 안내했습니다."}
    except (OSError, UnicodeError, ValueError, TypeError):
        result = {"systemMessage": "Company Agent could not record this tool outcome. Do not treat missing observation as evidence of success."}
    json.dump(result, sys.stdout, ensure_ascii=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
