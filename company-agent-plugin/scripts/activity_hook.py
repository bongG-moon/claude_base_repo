from __future__ import annotations

import json
import sys

from company_agent.state import record_activity


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if isinstance(payload, dict):
            record_activity(payload)
        result = {}
    except (OSError, UnicodeError, ValueError, TypeError):
        result = {"systemMessage": "Company Agent could not record this tool outcome. Do not treat missing observation as evidence of success."}
    json.dump(result, sys.stdout, ensure_ascii=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
