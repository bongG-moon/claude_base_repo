"""Allowlisted 0.5.0 delivery; verifies extracted code without starting Excel.

Run explicitly with the approved local Python environment after the final live
verification and Korean guides exist. Dependencies and private files are never
bundled; verify_xlwings_trial.py is included but NOT executed by this packager.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import time
import zipfile

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
OUT = ROOT / "outputs/excel-xlwings-check"
VERIFIED = OUT / "verified-final"
SMALL = ROOT / "outputs/excel-to-pipeline-test"
ADVANCED = ROOT / "outputs/excel-macro-migration-test"
EMBEDDED = ROOT / "outputs/excel-xlsm-migration-test"
PREFIX = "Excel-XLSM-Python-독립시험"
ARCHIVE = OUT / "Excel-XLSM-Python-독립시험-0.5.0.zip"
RECORD = OUT / "packaging-verification.json"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        if isinstance(value, str):
            stream.write(value)
        else:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")


def collect_entries():
    entries = {name: OUT / name for name in ("시작하기.md", "검증결과.md")}
    entries["advanced-manifest.json"] = ADVANCED / "advanced-manifest.json"
    for name in ("complex_workbook.xlsx", "variant_next_month.xlsx", "ambiguous_cases.xlsx"):
        entries["fixtures/" + name] = SMALL / name
    for name in ("고급_수식매크로_혼합.xlsx", "매크로전용_입력.xlsx"):
        entries["fixtures/" + name] = ADVANCED / "fixtures" / name
    entries["fixtures/고급_내장VBA_혼합.xlsm"] = EMBEDDED / "fixtures/고급_내장VBA_혼합.xlsm"
    for relative in ("SKILL.md", "시험안내.md", "requirements.txt", "requirements-vba.txt",
                     "requirements-excel.txt", "tests/fixtures-manifest.json", "tests/verify_xlwings_trial.py"):
        entries["excel-to-pipeline/" + relative] = SKILL / relative
    for directory, patterns in (("scripts", ("*.py",)), ("references", ("*.md",)),
                                ("examples/macro-migration", ("*.py", "*.bas", "*.md", "*.json")),
                                ("tests", ("test_*.py",))):
        for pattern in patterns:
            for path in (SKILL / directory).glob(pattern):
                entries["excel-to-pipeline/" + path.relative_to(SKILL).as_posix()] = path
    entries["검증기록/verification.json"] = VERIFIED / "verification.json"
    # These are deliberately the ONLY result files copied. Never copy complete
    # source_cells/formulas/tables, runtime environments or intermediate output.
    for label in ("small", "large", "exceptions"):
        for filename in ("report.md", "model_context.json", "input_evidence.json"):
            entries[f"처리예시/{label}/{filename}"] = VERIFIED / label / filename
    entries["라이선스/pyOpenVBA-LICENSE.md"] = (
        EMBEDDED / "native-validation/.runtime/pyopenvba-6.5.0.dist-info/licenses/LICENSE.md")
    for relative, path in entries.items():
        parts = PurePosixPath(relative).parts
        if relative.startswith("/") or ".." in parts or "\\" in relative:
            raise ValueError("Unsafe package member name")
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f"Missing or unsafe allowlisted source: {path}")
        if any(part in {"node_modules", "__pycache__", ".git", ".env"} for part in path.parts):
            raise ValueError("Runtime/private directory cannot be packaged")
    return entries


def run(python, arguments, cwd, timeout=240):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    started = time.perf_counter()
    result = subprocess.run([str(python), "-X", "utf8", "-B", *map(str, arguments)],
                            cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                            timeout=timeout, env=env)
    elapsed = round(time.perf_counter() - started, 4)
    if result.returncode:
        raise RuntimeError((result.stdout + "\n" + result.stderr)[-16000:])
    return result, elapsed


def run_tests(python, skill, cwd, log_path):
    result, elapsed = run(python, ["-m", "unittest", "discover", "-s", skill / "tests",
                                  "-p", "test_*.py", "-v"], cwd)
    write_new(log_path, result.stdout + result.stderr)
    match = re.search(r"Ran (\d+) tests", result.stderr)
    if not match or int(match.group(1)) < 1 or re.search(r"skipped=\d+", result.stderr):
        raise RuntimeError("Unit discovery must execute every test without skips")
    return int(match.group(1)), elapsed


def verify_transform(python, unpacked):
    fixtures = unpacked / "fixtures"
    first, second = fixtures / "complex_workbook.xlsx", fixtures / "variant_next_month.xlsx"
    before = {path.name: sha256(path) for path in (first, second)}
    project = unpacked / "portable-generated-project"
    generated, first_seconds = run(python, [unpacked / "excel-to-pipeline/scripts/excel_pipeline.py",
                                            first, "--reader", "openpyxl", "--output", project,
                                            "--context-chars", "8000"], unpacked)
    summary = json.loads(generated.stdout)
    if summary["reader"] != "openpyxl" or summary["formula_status"] != {"computed": 82}:
        raise AssertionError("Portable first analysis failed")
    if json.loads((project / "input_evidence.json").read_text(encoding="utf-8"))["excel_started"]:
        raise AssertionError("Packaging validation must not start Excel")
    for filename in ("xlwings_reader.py", "workbook_input.py"):
        if not (project / "pipeline_lib" / filename).is_file():
            raise AssertionError("Generated project is missing native-reader support")
    if not (project / "requirements-excel.txt").is_file():
        raise AssertionError("Generated project is missing optional dependency instructions")
    next_output = unpacked / "portable-next-month"
    transformed, second_seconds = run(python, [project / "transform.py", second, "--reader", "openpyxl",
                                              "--output", next_output, "--context-chars", "8000"], unpacked)
    next_summary = json.loads(transformed.stdout)
    if next_summary["reader"] != "openpyxl" or next_summary["formula_status"] != {"computed": 89}:
        raise AssertionError("Portable generated transform failed")
    formulas = json.loads((next_output / "formulas.json").read_text(encoding="utf-8"))
    total = next(row["value"] for row in formulas if row["sheet"] == "정산" and row["cell"] == "H17")
    if total != 1871000:
        raise AssertionError("Next-month business total mismatch")
    for folder in (project, next_output):
        evidence = json.loads((folder / "input_evidence.json").read_text(encoding="utf-8"))
        if evidence["excel_started"] or len((folder / "model_context.json").read_text(encoding="utf-8")) > 8000:
            raise AssertionError("Native execution or model-context budget changed")
    if before != {path.name: sha256(path) for path in (first, second)}:
        raise AssertionError("Portable fixtures changed")
    return {"passed": True, "reader": "openpyxl", "excel_started": False,
            "first_formula_count": 82, "next_formula_count": 89, "next_total": total,
            "source_unchanged": True, "context_chars_limit": 8000,
            "first_seconds": first_seconds, "next_seconds": second_seconds}


def main():
    parser = argparse.ArgumentParser(description="독립 시험 ZIP 생성 및 압축 해제본 자동 시험. Excel은 실행하지 않습니다.")
    parser.add_argument("--python", type=Path, default=Path(sys.executable),
                        help="준비된 시험용 Python 경로. 기본값은 이 명령을 실행한 Python입니다.")
    parser.add_argument("--include-partial-verification", action="store_true",
                        help="실제 Excel과 원문 차이가 남은 시험판을 제한 사항·실패 기록 그대로 포함합니다. 통과로 변경하지 않습니다.")
    args = parser.parse_args()
    if not args.python.is_file():
        raise FileNotFoundError("Approved Python executable was not found")
    if ARCHIVE.exists() or RECORD.exists():
        raise FileExistsError("Archive/verification already exists; existing deliverables are not overwritten")
    entries = collect_entries()  # Missing guides/final evidence stops before running anything.
    native_verification = json.loads((VERIFIED / "verification.json").read_text(encoding="utf-8"))
    if not native_verification.get("passed") and not args.include_partial_verification:
        raise ValueError("Final native verification has not passed")
    if not native_verification.get("cases") or any(case.get("error_type") for case in native_verification["cases"]):
        raise ValueError("Native observation evidence is missing or execution failed")
    source_count, source_seconds = run_tests(args.python, SKILL, ROOT, OUT / "packaging-source-tests.txt")
    entries["검증기록/unit-test-results.txt"] = OUT / "packaging-source-tests.txt"
    with zipfile.ZipFile(ARCHIVE, "x", zipfile.ZIP_DEFLATED) as archive:
        for relative, path in sorted(entries.items()):
            archive.write(path, PREFIX + "/" + relative)
    with zipfile.ZipFile(ARCHIVE) as archive:
        if archive.testzip() is not None or len(archive.infolist()) != len(entries):
            raise AssertionError("Archive integrity/entry count mismatch")
        for relative, path in entries.items():
            if archive.read(PREFIX + "/" + relative) != path.read_bytes():
                raise AssertionError("Archive byte identity mismatch")
        with tempfile.TemporaryDirectory(prefix="unpacked-verification-", dir=OUT) as temp:
            if not Path(temp).resolve().is_relative_to(OUT.resolve()):
                raise AssertionError("Temporary folder escaped trial scope")
            archive.extractall(temp)  # All members were authored and checked above.
            unpacked = Path(temp) / PREFIX
            unpacked_count, unpacked_seconds = run_tests(args.python, unpacked / "excel-to-pipeline", unpacked,
                                                         OUT / "packaging-unpacked-tests.txt")
            if unpacked_count != source_count:
                raise AssertionError("Extracted archive executed a different test count")
            transformed = verify_transform(args.python, unpacked)
    record = {"archive": ARCHIVE.name, "version": "0.5.0", "prefix": PREFIX,
              "entries": len(entries), "bytes": ARCHIVE.stat().st_size, "sha256": sha256(ARCHIVE),
              "source_tests_passed": source_count, "unpacked_tests_passed": unpacked_count,
              "source_tests_seconds": source_seconds, "unpacked_tests_seconds": unpacked_seconds,
              "portable_generated_transform": transformed,
              "included_final_native_verification_passed": bool(native_verification.get("passed")),
              "partial_native_verification_included": not bool(native_verification.get("passed")),
              "live_excel_test_rerun_by_packager": False,
              "harness_installed_or_changed": False, "dependencies_bundled": False,
              "full_cell_dumps_bundled": False, "network_or_model_calls": 0}
    write_new(RECORD, record)
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
