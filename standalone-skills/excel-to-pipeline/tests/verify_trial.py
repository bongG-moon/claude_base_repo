"""Developer-only local verification; not installed as a hook or skill prerequisite."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
OUTPUT = ROOT / "outputs" / "excel-to-pipeline-test"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(arguments):
    start = time.perf_counter()
    result = subprocess.run([sys.executable, "-X", "utf8", *map(str, arguments)],
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    elapsed = round(time.perf_counter() - start, 4)
    if result.returncode:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    return result, elapsed


def main():
    tests, test_elapsed = execute(["-m", "unittest", "discover", "-s", SKILL / "tests", "-p", "test_*.py", "-v"])
    (OUTPUT / "unit-test-results.txt").write_text(tests.stdout + tests.stderr, encoding="utf-8")
    count = int(re.search(r"Ran (\d+) tests", tests.stderr).group(1))
    measures = []
    for filename, folder, entry in [
        ("complex_workbook.xlsx", "verified-base", SKILL / "scripts" / "excel_pipeline.py"),
        ("variant_next_month.xlsx", "verified-next", OUTPUT / "verified-base" / "transform.py"),
        ("ambiguous_cases.xlsx", "verified-exceptions", SKILL / "scripts" / "excel_pipeline.py"),
    ]:
        source, destination = OUTPUT / filename, OUTPUT / folder
        before = digest(source)
        run, elapsed = execute([entry, source, "--output", destination])
        summary = json.loads(run.stdout)
        assert digest(source) == before
        assert (destination / "pipeline_plan.json").is_file()
        measures.append({"file": filename, "file_bytes": source.stat().st_size,
                         "process_seconds_single_run": elapsed, "summary": summary})
    record = {"date": "2026-10-14", "skill_version": "0.1.0", "python": sys.version.split()[0],
              "automated_tests": {"passed": count, "process_seconds": test_elapsed},
              "independent_forward_tests": {"passed": 5, "additional_formula_checks_passed": 21,
                  "method": "separate reviewer; expectations calculated from raw source without fixture manifest"},
              "samples": measures, "native_excel_recalculation": "not_tested",
              "enterprise_hcp_end_to_end": "not_tested", "harness_installed": False,
              "runtime_network_or_model_calls": 0,
              "timing_scope": "local Python process startup, read, compute and write; small synthetic examples only"}
    (OUTPUT / "verification.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
