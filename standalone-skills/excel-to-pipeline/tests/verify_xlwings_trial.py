"""Opt-in real Excel read tests using only the supplied synthetic fixtures.

Does not run VBA, change Trust Center settings, author workbooks, or use DRM files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from test_fixture_paths import fixture_root

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from excel_pipeline import analyze, publish
from model_context import build_model_context, serialize_model_context
from openpyxl.formula import Tokenizer


def formula_signature(formula):
    """Compare only Excel's optional sheet quoting, not evaluation dialects."""
    if not formula:
        return formula
    signature = []
    for token in Tokenizer(formula).items:
        value = token.value
        if token.type == "OPERAND" and token.subtype == "RANGE":
            value = re.sub(r"^'([^\W\d]\w*)'!", r"\1!", value)
        signature.append((token.type, token.subtype, value))
    return signature


def compare_rows(left, right, keys):
    def index(rows):
        return {(r["sheet"], r["cell"]): {
            key: formula_signature(r.get(key)) if key == "formula" else r.get(key) for key in keys} for r in rows}
    a, b = index(left), index(right)
    differences = [{"location": list(location), "direct": a.get(location), "excel": b.get(location)}
                   for location in sorted(set(a) | set(b)) if a.get(location) != b.get(location)]
    return {"same": not differences, "difference_count": len(differences), "examples": differences[:8]}


def check(source, output, expected):
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    start = time.perf_counter()
    direct = analyze(source)
    direct_seconds = time.perf_counter() - start
    start = time.perf_counter()
    native = analyze(source, reader="xlwings", excel_timeout=90)
    native_seconds = time.perf_counter() - start
    metrics = {key: native["summary"][key] for key in ("sheet_count", "table_count", "formula_count", "formula_status")}
    cells = compare_rows(direct["source_cells"], native["source_cells"], ("value", "type"))
    formulas = compare_rows(direct["formulas"], native["formulas"], ("value", "status"))
    supported_formulas = compare_rows([r for r in direct["formulas"] if r["status"] == "computed"],
                                     [r for r in native["formulas"] if r["status"] == "computed"], ("formula",))
    unsupported_representations = compare_rows([r for r in direct["formulas"] if r["status"] != "computed"],
                                             [r for r in native["formulas"] if r["status"] != "computed"], ("formula",))
    raw_direct = {(row["sheet"], row["cell"]): row["formula"] for row in direct["formulas"]}
    raw_native = {(row["sheet"], row["cell"]): row["formula"] for row in native["formulas"]}
    raw_formula_differences = sum(raw_direct.get(key) != raw_native.get(key) for key in set(raw_direct) | set(raw_native))
    table_keys = ("sheet", "range", "columns", "rows", "source_rows", "row_kinds", "header_rows")
    tables_same = [{key: t.get(key) for key in table_keys} for t in direct["tables"]] == [
        {key: t.get(key) for key in table_keys} for t in native["tables"]]
    states_same = [(s["name"], s["state"]) for s in direct["sheets"]] == [(s["name"], s["state"]) for s in native["sheets"]]
    budget_results = []
    for rows, chars in ((0, 1024), (5, 8000), (5, 12000), (1000, 12000), (1000, 50000)):
        context = build_model_context(native, rows, chars)
        encoded = serialize_model_context(context)
        assert len(encoded) <= chars and context["input"]["reader"] == "xlwings"
        assert context["vba"]["status"] == native.get("vba", {}).get("status", "not_present")
        budget_results.append({"sample_rows_limit": rows, "max_chars": chars,
                               "actual_chars": len(encoded), "actual_sample_rows": context["sampled_data_rows"]})
    publish(native, output)
    unchanged = hashlib.sha256(source.read_bytes()).hexdigest() == before
    return {"source": source.name, "source_sha256": before, "source_unchanged": unchanged,
            "metrics": metrics, "expected_metrics_match": metrics == expected,
            "cell_values_types": cells, "python_formula_results": formulas,
            "supported_formula_expressions": supported_formulas,
            "unsupported_formula_representation_changes": unsupported_representations,
            "tables_same": tables_same, "sheet_states_same": states_same,
            "direct_seconds": round(direct_seconds, 3), "xlwings_seconds": round(native_seconds, 3),
            "vba_direct": direct.get("vba", {}).get("status", "not_present"),
            "vba_excel": native.get("vba", {}).get("status", "not_present"),
            "input_evidence": native["input_evidence"], "model_context_budgets": budget_results,
            "raw_formula_text_differences": raw_formula_differences,
            "comparison_normalization": "Only optional single quotes around simple sheet identifiers; strings and formula semantics unchanged",
            "passed": bool(unchanged and metrics == expected and cells["same"] and formulas["same"]
                           and supported_formulas["same"] and tables_same and states_same)}


def main():
    parser = argparse.ArgumentParser(description="실제 Excel의 읽기 경로만 시험합니다. 매크로 실행·보안 설정 변경 없음.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", choices=("small", "large", "exceptions", "all"), default="all")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    base = fixture_root()
    large = base / "고급_내장VBA_혼합.xlsm"
    cases = [
        ("small", base / "complex_workbook.xlsx", {"sheet_count": 5, "table_count": 7, "formula_count": 82, "formula_status": {"computed": 82}}),
        ("large", large, {"sheet_count": 12, "table_count": 16, "formula_count": 6798,
                          "formula_status": {"computed": 6790, "unsupported": 4, "error": 4}}),
        ("exceptions", base / "ambiguous_cases.xlsx", {"sheet_count": 2, "table_count": 2, "formula_count": 7,
                                                      "formula_status": {"computed": 1, "unsupported": 2, "error": 4}}),
    ]
    report = {"synthetic_only": True, "real_drm_tested": False, "vba_executed": False,
              "harness_changed": False, "cases": [], "generated_transform": None}
    for label, source, expected in cases:
        if args.only not in ("all", label):
            continue
        try:
            result = check(source, args.output / label, expected)
        except Exception as error:
            result = {"source": source.name, "passed": False, "error_type": type(error).__name__, "message": str(error)}
        report["cases"].append(result)
        print(json.dumps({k: result.get(k) for k in ("source", "passed", "metrics", "vba_excel", "xlwings_seconds", "message")}, ensure_ascii=False), flush=True)
        (args.output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.only in ("all", "small") and (args.output / "small/transform.py").is_file():
        proc = subprocess.run([sys.executable, "-X", "utf8", str(args.output / "small/transform.py"),
                               str(base / "variant_next_month.xlsx"), "--reader", "xlwings", "--output", str(args.output / "next-month")],
                              capture_output=True, encoding="utf-8", timeout=120)
        summary = json.loads(proc.stdout) if proc.returncode == 0 else {}
        report["generated_transform"] = {"returncode": proc.returncode, "summary": summary, "error": proc.stderr[:1200],
                                         "passed": proc.returncode == 0 and summary.get("formula_status") == {"computed": 89}}
    report["passed"] = all(case["passed"] for case in report["cases"]) and (report["generated_transform"] or {"passed": True})["passed"]
    (args.output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
