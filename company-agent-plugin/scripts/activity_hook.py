from __future__ import annotations

import json
import sys

from company_agent.state import record_activity, load_session, _is_own_learning_command
from company_agent.paths import user_state_root
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
        elif (isinstance(payload, dict) and payload.get("hook_event_name") == "PostToolUse"
              and str(payload.get("tool_name", "")).casefold() in {"bash", "powershell"}):
            root = user_state_root()
            session_id = str(payload.get("session_id") or "")
            state = load_session(session_id, root)
            tool_input = payload.get("tool_input")
            command = str(tool_input.get("command") or "") if isinstance(tool_input, dict) else ""
            if (state.get("learningStatus") == "complete"
                    and _is_own_learning_command(command, session_id, state, root)):
                result = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext":
                    "Routine personal learning is complete. Keep this bookkeeping receipt quiet: do not narrate accepted, review, checkpoint, or verification status. Return to the original business result in the user's language. Explain only an actual warning requiring action, or learning details explicitly requested by the user. Do not repeat business actions."}}
    except (OSError, UnicodeError, ValueError, TypeError):
        result = {"systemMessage": "작업 결과를 기록하지 못했습니다. 기록이 없다는 이유로 성공했다고 판단하지 마세요."}
    json.dump(result, sys.stdout, ensure_ascii=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
