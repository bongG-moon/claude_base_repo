from __future__ import annotations

import json
import sys

from company_agent.state import stop_decision


_FAILURE_OUTPUT = {
    "systemMessage": (
        "Company Agent could not evaluate completion because its verification "
        "state was unavailable. This run is not verified; do not treat it as successful."
    )
}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        result = stop_decision(payload if isinstance(payload, dict) else {})
    except Exception:
        # End safely instead of crashing the hook or creating an unbounded Stop
        # loop. Never include exception or payload details in user-visible text.
        result = _FAILURE_OUTPUT
    json.dump(result, sys.stdout, ensure_ascii=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
