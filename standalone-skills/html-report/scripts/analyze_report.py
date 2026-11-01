"""Runnable, opt-in example: source records -> checked report -> stable entry.

Replace only build() when adapting to a task. Keep publication in regenerate().
No commands or expressions supplied by input data are executed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from regenerate import build_job, regenerate


def build(data, run):
    # 원자료의 부서별 건수를 계산합니다. 실제 업무에서는 이 함수만 바꿉니다.
    records = data.get("records")
    if not isinstance(records, list) or len(records) > 5000:
        raise ValueError("records에 최대 5,000개의 자료를 넣어 주세요.")
    counts = Counter()
    for row in records:
        department = row.get("department") if isinstance(row, dict) else None
        if not isinstance(department, str) or not department.strip() or len(department) > 200:
            raise ValueError("각 자료에는 200자 이내의 부서명 department가 필요합니다.")
        counts[department.strip()] += 1
    if sum(counts.values()) != len(records):
        raise ValueError("원자료 건수와 집계 건수가 다릅니다.")

    # 정상본 폴더를 건드리지 않고 새 실행 폴더 안에서만 작성합니다.
    (run / "data").mkdir()
    (run / "data" / "records.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    job = {"title": "부서별 자료 현황", "style": "minimalism", "mode": "scroll",
           "fontChoice": "noto-sans-kr", "sections": [{"title": "부서별 건수",
               "body": f"입력한 자료 {len(records):,}건을 부서별로 집계했습니다.",
               "table": {"headers": ["부서", "건수"], "rows": [list(item) for item in sorted(counts.items())]}}]}
    # 제작 실패는 예외가 되므로 regenerate가 이전 정상본을 유지합니다.
    build_job(job, run)
    (run / "evidence" / "analysis.json").write_text(
        json.dumps({"ok": True, "sourceRows": len(records), "aggregatedRows": sum(counts.values()),
                    "departments": len(counts)}, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="부서별 원자료 분석과 HTML 재생성 예제")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = regenerate(args.source, args.work, build)
    except (OSError, ValueError) as exc:
        result = {"ok": False, "code": "regeneration_failed", "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.exit(main())
