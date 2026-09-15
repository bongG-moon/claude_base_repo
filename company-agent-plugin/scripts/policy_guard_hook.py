from __future__ import annotations

import json
import sys

from company_agent.policy import deny_tool_call, evaluate_tool_call


_FAIL_CLOSED_REASON = "관리 MCP 정책을 안전하게 판별하지 못해 호출을 차단했습니다."


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            result = deny_tool_call(_FAIL_CLOSED_REASON)
        else:
            tool_name = str(payload.get("tool_name") or "").strip().casefold()
            if not tool_name.startswith(
                ("mcp__corp-db-read__", "mcp__corp-outlook-self__")
            ):
                # This hook is registered only for the two managed servers. If
                # Claude supplies an incomplete or inconsistent event, there
                # is no safe basis for an allow decision.
                result = deny_tool_call(_FAIL_CLOSED_REASON)
            else:
                result = evaluate_tool_call(payload)
    except Exception:
        # A policy hook must fail closed. Do not echo exception details because
        # they can include local paths or values derived from a tool payload.
        result = deny_tool_call(_FAIL_CLOSED_REASON)

    # ASCII transport is valid UTF-8 and CP949 alike; consumers still decode
    # the Korean reason from JSON. Keep fail-closed output readable in either shell.
    json.dump(result, sys.stdout, ensure_ascii=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
