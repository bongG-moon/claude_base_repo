"""Developer-only complex fixture verification. Not a hook or everyday prerequisite."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

import openpyxl
from test_case_preserving_controls import revised_expected

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
DEFAULT = ROOT / "outputs" / "excel-macro-migration-test"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(arguments, timeout=240):
    start = time.perf_counter()
    result = subprocess.run([sys.executable, "-X", "utf8", *map(str, arguments)],
                            capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    return result, round(time.perf_counter() - start, 4)


def compare(result_dir, expected):
    expected = revised_expected(expected)
    load = lambda name: json.loads((result_dir / (name + ".json")).read_text(encoding="utf-8"))
    summary = load("summary")
    checks = 0
    for key in ("input_rows", "deduplicated_rows", "approved_count", "excluded_count", "rejected_count", "total_amount", "completed_count"):
        assert summary[key] == expected[key], (key, summary[key], expected[key])
        checks += 1
    records = {r["application_id"]: r for r in load("records")}
    assert len(records) == len(expected["records"])
    for row in expected["records"]:
        for key, value in row.items():
            assert records[row["application_id"]][key] == value, (row["application_id"], key, records[row["application_id"]][key], value)
            checks += 1
    departments = {r["department"]: r for r in load("departments")}
    assert departments == {r["department"]: r for r in expected["departments"]}
    assert sorted(r["application_id"] for r in load("rejected")) == sorted(r["application_id"] for r in expected["rejected"])
    assert sorted(r["application_id"] for r in load("excluded")) == sorted(expected["excluded"])
    assert summary["source_unchanged"] and not summary["vba_executed"] and not summary["formula_caches_used"]
    return checks + 5


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="New verification directory")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((DEFAULT / "advanced-manifest.json").read_text(encoding="utf-8"))
    tests, elapsed = execute(["-m", "unittest", "discover", "-s", SKILL / "tests", "-p", "test_*.py", "-v"])
    (args.output / "unit-test-results.txt").write_text(tests.stdout + tests.stderr, encoding="utf-8")
    test_count = int(re.search(r"Ran (\d+) tests", tests.stderr).group(1))
    measures, formula_counts, checks = [], {}, 0
    for source_kind, relative in manifest["files"].items():
        source = DEFAULT / relative
        before = digest(source)
        wb = openpyxl.load_workbook(source, data_only=False, keep_links=False)
        formula_counts[source_kind] = sum(c.data_type == "f" for ws in wb for row in ws for c in row)
        assert wb.sheetnames == manifest["sheet_names"][source_kind]
        assert wb["정책"].sheet_state == "hidden"
        assert wb["신청원본"].row_dimensions[12].hidden
        assert wb["신청원본"]["C6"].value == "000001"
        wb.close()
        if source_kind == "macro_only":
            assert formula_counts[source_kind] == 0
        for mode in ("macro-only", "mixed"):
            for include in (False, True):
                label = f"{source_kind}-{mode}-{'exceptions' if include else 'base'}"
                dest = args.output / label
                cmd = [SKILL / "examples" / "macro-migration" / "migrate_training.py", source, "--output", dest, "--mode", mode]
                if include:
                    cmd.append("--include-exceptions")
                run, duration = execute(cmd)
                summary = json.loads(run.stdout)
                checks += compare(dest, manifest["all_expected" if include else "base_expected"])
                assert digest(source) == before
                measures.append({"case": label, "seconds_single_run": duration, "summary": summary})
                print(json.dumps({"case": label, "seconds": duration, "approved": summary["approved_count"], "total": summary["total_amount"]}), flush=True)
    # Exercise the original decomposition workflow on the larger workbook as well.
    result, duration = execute([SKILL / "scripts" / "excel_pipeline.py", DEFAULT / manifest["files"]["mixed"], "--output", args.output / "structure-analysis"])
    structure = json.loads(result.stdout)
    assert structure["formula_status"] == {"computed": 6790, "unsupported": 4, "error": 4}
    assert not structure["cache_comparison"].get("mismatch", 0)
    assert structure["source_unchanged"] and structure["table_count"] == 16
    plan = json.loads((args.output / "structure-analysis" / "plan.json").read_text(encoding="utf-8"))
    for expected in manifest["expected_tables"]:
        assert any(all(t[k] == v for k, v in expected.items()) for t in plan["tables"]), expected
    formulas = json.loads((args.output / "structure-analysis" / "formulas.json").read_text(encoding="utf-8"))
    assert all(f["sheet"] == "오류수식" for f in formulas if f["status"] != "computed")
    assert next(f["value"] for f in formulas if f["sheet"] == "집계" and f["cell"] == "D12") == manifest["base_expected"]["total_amount"]
    report = {"date": "2026-10-14", "automated_tests": {"passed": test_count, "seconds": elapsed},
              "independent_expected_value_checks": checks, "formula_counts": formula_counts,
              "migration_cases": measures, "structure_analysis": {"seconds_single_run": duration, "summary": structure, "table_boundaries_checked": len(manifest["expected_tables"])},
              "native_vba_execution_comparison": "not_tested", "embedded_vba_extraction": "not_tested",
              "harness_changed_or_installed": False, "runtime_model_or_network_calls": 0,
              "timing_scope": "local Python startup/read/processing/write; single run, not enterprise CLI timing"}
    (args.output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"tests": test_count, "checks": checks, "formula_counts": formula_counts, "structure": structure}, ensure_ascii=False))


if __name__ == "__main__":
    main()
