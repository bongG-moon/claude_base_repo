"""Small real-model A/B response probe. Synthetic input, no tools, no user config.

This measures two reporting scenarios, not installed-harness behavior or speed.
Outputs are retained under a fresh build directory; no secrets or real work input.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import time


BASELINE = "Accept natural-language requests. Ask only for missing material choices. Lead with the result. Routine learning success/no-change stays silent. Final answers show business results and real omissions, not internal verification tables."
CASES = {
    "complete-list": "합성 테스트야. 설치 목록이 확인됐어: 회사 스킬은 문서작성, 표정리, 메일요약, 파일정리, 일정검토, 오류진단이고 개인 스킬은 주간보고, 용어정리야. 이 설치 목록을 전부 한국어로 보여줘. 다른 설정이나 작업은 필요 없어.",
    "partial-unknown": "합성 테스트야. 최근 메일 3건의 본문은 읽었고 공통 내용은 회의 일정 변경이야. 첨부 1개는 접근이 거절됐지만 원인은 확인 못 했어. 메일함이나 파일을 변경한 건 없어. 이 결과를 짧게 보고해줘. 원인을 단정하지 말고 누락 범위를 알려줘.",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--claude", type=Path, required=True)
    parser.add_argument("--model", default="sonnet")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    out = repo / "build" / ("response-style-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=False)
    (out / "mcp.json").write_text('{"mcpServers":{}}', encoding="utf-8")
    body = (repo / "company-agent-plugin/skills/company-agent/SKILL.md").read_text(encoding="utf-8")
    additions = "\n".join(line for line in body.splitlines() if line.startswith(("- For a completed task", "- Group long lists", "- Show progress only")))
    results = []
    for case, prompt in CASES.items():
        for condition, guidance in (("before", BASELINE), ("after", BASELINE + "\n" + additions)):
            command = [str(args.claude), "-p", "--output-format", "json", "--model", args.model,
                       "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--mcp-config", str(out / "mcp.json"),
                       "--no-chrome", "--no-session-persistence", "--max-budget-usd", "1",
                       "--append-system-prompt", guidance]
            start = time.monotonic()
            result = subprocess.run(command, input=prompt.encode("utf-8"), cwd=out, capture_output=True,
                                    timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            filename = f"{case}-{condition}.json"
            (out / filename).write_bytes(result.stdout)
            (out / (filename + ".stderr.txt")).write_bytes(result.stderr)
            payload = json.loads(result.stdout) if result.stdout else {}
            row = {"case": case, "condition": condition, "modelAlias": args.model,
                   "exitCode": result.returncode, "elapsedSeconds": round(time.monotonic() - start, 2),
                   "result": payload.get("result"), "costUsd": payload.get("total_cost_usd"),
                   "modelUsage": payload.get("modelUsage"), "file": filename}
            results.append(row)
            print(json.dumps(row, ensure_ascii=True), flush=True)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out), flush=True)


if __name__ == "__main__":
    main()
