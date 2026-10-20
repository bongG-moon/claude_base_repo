"""Create one reusable example and verify execution without touching source files."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from test_fixture_paths import fixture_root

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from excel_pipeline import analyze, publish, write_json
from project_selection import select_result
from project_builder import make_rules
from project_runtime import read_excel_data


def run(project, destination):
    started = time.perf_counter()
    completed = subprocess.run([sys.executable, "-X", "utf8", "-B", str(project / "main.py"),
                                "--output", str(destination), "--diagnostics"],
                               capture_output=True, encoding="utf-8", timeout=120)
    if completed.returncode:
        raise RuntimeError(completed.stderr)
    return json.loads(completed.stdout), round(time.perf_counter() - started, 3)


def process_hashes(project):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (project / "PROCESS").glob("*.py")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    output, evidence = Path(args.output).resolve(), Path(args.evidence).resolve()
    if output.exists() or evidence.exists():
        raise ValueError("새 검증 폴더를 지정하세요. 기존 자료를 덮어쓰지 않습니다.")
    evidence.mkdir(parents=True)
    source = fixture_root() / "고급_내장VBA_혼합.xlsm"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = analyze(source)
    publish(result, output, context_chars=4000)
    first, elapsed = run(output, output / "outputs/01-원본입력")
    formulas = json.loads((output / "outputs/01-원본입력/_details/formulas.json").read_text(encoding="utf-8"))
    signature = lambda rows: {(f["sheet"], f["cell"]): (f["value"], f["status"]) for f in rows}
    assert signature(formulas) == signature(result["formulas"])
    schedule = json.loads((output / "_details/calculation-order.json").read_text(encoding="utf-8"))

    # Targeted project uses the formula-only fixture: opaque VBA cannot be pruned.
    small = analyze(fixture_root() / "complex_workbook.xlsx")
    selected = select_result(small, ["집계!D8"])
    target = evidence / "필요한결과만"
    publish(selected, target, context_chars=4000)
    original, selected_elapsed = run(target, evidence / "선택결과")
    stable = process_hashes(target)
    data = read_excel_data(small["project_source"], make_rules(selected))
    data["cells"]["신청!G6"] = 2
    data.pop("sha256", None)
    data.pop("input_evidence", None)
    data.pop("source_unchanged", None)
    write_json(target / "DATA/입력값.json", data)
    (target / "DATA/load.py").write_text(
        '"""Excel 대신 외부 Python이 제공한 입력값을 읽습니다."""\n'
        'import json\nfrom pathlib import Path\n'
        'def load_data():\n'
        '    return json.loads(Path(__file__).with_name("입력값.json").read_text(encoding="utf-8"))\n', encoding="utf-8")
    changed, _ = run(target, evidence / "DATA교체결과")
    rows = json.loads((evidence / "DATA교체결과/_details/formulas.json").read_text(encoding="utf-8"))
    amount = next(f["value"] for f in rows if f["sheet"] == "집계" and f["cell"] == "D8")
    assert amount == 1285000
    assert stable == process_hashes(target)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    report = {
        "full": {"sheets": len(result["sheets"]), "formulas": len(formulas),
                 "formula_status": first["summary"]["formula_status"], "all_values_and_statuses_match": True,
                 "loop_groups": schedule["loop_groups"], "sheet_modules": len(list((output / "PROCESS").glob("sheet_*.py"))),
                 "execution_seconds": elapsed, "source_unchanged": True, "macro_executed": False},
        "selection": {**selected["selection"], "execution_seconds": selected_elapsed,
                      "new_result_after_data_replacement": amount, "process_unchanged": True},
        "model_calls": 0, "fresh_excel_native_comparison": False,
    }
    write_json(evidence / "verification.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
