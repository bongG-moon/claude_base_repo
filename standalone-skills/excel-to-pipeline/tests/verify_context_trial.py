"""Local-only bounded-context evidence for a genuine embedded-VBA workbook."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from excel_pipeline import analyze
from model_context import build_model_context, serialize_model_context


def main():
    source = ROOT / "outputs/excel-xlsm-migration-test/fixtures/고급_내장VBA_혼합.xlsm"
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/excel-xlsm-native-check")
    args = parser.parse_args()
    output = args.output
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = analyze(source)
    snapshot = json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False)
    raw_chars = len(json.dumps({key: result[key] for key in ("source_cells", "tables", "formulas")},
                              ensure_ascii=False, separators=(",", ":")))
    cases = []
    for rows, budget in ((0, 1024), (5, 8000), (5, 12000), (1000, 12000), (1000, 50000)):
        start = time.perf_counter()
        context = build_model_context(result, sample_rows=rows, max_chars=budget)
        serialized = serialize_model_context(context)
        elapsed = time.perf_counter() - start
        assert len(serialized) <= budget
        assert json.loads(serialized) == context
        assert json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False) == snapshot
        cases.append({"sample_rows_per_table_limit": rows, "max_chars": budget,
                      "actual_chars": len(serialized), "seconds": round(elapsed, 6),
                      "valid_json": True, "full_analysis_unchanged": True})
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    record = {"source_sha256": before, "source_unchanged": True,
              "sheet_count": result["summary"]["sheet_count"],
              "table_count": len(result["tables"]),
              "largest_table_rows": max(len(t["rows"]) for t in result["tables"]),
              "full_cells_tables_formulas_compact_chars": raw_chars,
              "cases": cases, "model_or_network_calls": 0,
              "note": "Character budgets are not token estimates. Full local processing is unchanged; model evidence is sampled."}
    output.mkdir(parents=True, exist_ok=True)
    with (output / "context-verification.json").open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
