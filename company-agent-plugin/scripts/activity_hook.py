from __future__ import annotations

import json
import sys

from company_agent.state import record_activity


def main() -> int:
    payload = json.load(sys.stdin)
    record_activity(payload)
    json.dump({}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
