"""Developer-only evidence for the real embedded-VBA fixture. Never a hook."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
OUT = ROOT / "outputs/excel-xlsm-migration-test"
SOURCE = OUT / "fixtures/고급_내장VBA_혼합.xlsm"
EXAMPLE = SKILL / "examples/macro-migration"
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(EXAMPLE))
from migration_contract import observe_contract
from vba_extract import extract_vba
from migrate_training import SCHEMAS
from verify_macro_trial import compare


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def bind_reviewed_fixture():
    """Explicit developer authoring step; never called by migration execution."""
    extracted = extract_vba(SOURCE)
    assert extracted["status"] == "extracted", extracted
    normalized = lambda s: s.replace("\r\n", "\n").replace("\r", "\n").strip()
    modules = {m["name"]: m for m in extracted["modules"]}
    # All business procedures must exactly match the sources reviewed in this task.
    for path in EXAMPLE.glob("*.bas"):
        assert normalized(modules[path.stem]["source"]) == normalized(path.read_text(encoding="utf-8-sig")), path
    build = json.loads((OUT / "native-validation/embedded-build.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == build["fixture_sha256"]
    assert len(modules) == 17
    for name, module in modules.items():
        if name in {"TrainingPreparation", "TrainingCalculation", "EventWrapper", "FixtureBridge"}:
            continue
        assert all(not line.strip() or line.startswith("Attribute ") or line == "Option Explicit"
                   for line in normalized(module["source"]).splitlines()), name
    from openpyxl.utils import get_column_letter
    headers = [{"sheet": sheet, "range": f"B5:{get_column_letter(len(schema)+1)}5"} for sheet, schema in SCHEMAS.items()]
    headers.append({"sheet": "예외신청", "range": "B5:M5"})
    contract = observe_contract(SOURCE, headers, extracted)
    contract["review"] = {"recipe": "synthetic_training_v1", "business_sources_reviewed": True,
                           "fixture_sha256": build["fixture_sha256"],
                           "excluded": ["자동 이벤트", "오류수식 시트의 의도적인 비지원 수식"]}
    write_new(EXAMPLE / "embedded-source-contract.json", contract)
    print(json.dumps({"bound": True, "modules": len(modules), "formulas": contract["formula_count"]}))


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((ROOT / "outputs/excel-macro-migration-test/advanced-manifest.json").read_text(encoding="utf-8"))
    before = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    checks, cases = 0, []
    for mode in ("macro-only", "mixed"):
        for include in (False, True):
            label = mode + ("-exceptions" if include else "-base")
            command = [sys.executable, "-X", "utf8", str(EXAMPLE / "migrate_embedded_training.py"),
                       str(SOURCE), "--output", str(output / label), "--mode", mode]
            if include:
                command.append("--include-exceptions")
            start = time.perf_counter()
            done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=120)
            assert done.returncode == 0, done.stdout + done.stderr
            count = compare(output / label, manifest["all_expected" if include else "base_expected"])
            summary = json.loads(done.stdout)
            assert summary["embedded_source_contract"]["status"] == "matched"
            assert not summary["source_sidecars_required"]
            checks += count
            cases.append({"case": label, "seconds": round(time.perf_counter()-start, 4), "checks": count, "summary": summary})
            print(json.dumps({"case": label, "checks": count, "seconds": cases[-1]["seconds"]}), flush=True)
    start = time.perf_counter()
    done = subprocess.run([sys.executable, "-X", "utf8", str(SKILL / "scripts/excel_pipeline.py"), str(SOURCE),
                           "--output", str(output / "analysis")], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    summary = json.loads(done.stdout)
    assert summary["vba"] == {"status": "extracted", "module_count": 17, "procedure_count": 21,
                              "macro_executed": False, "translation_generated": False}
    assert summary["sheet_count"] == 12 and summary["table_count"] == 16
    assert summary["formula_count"] == 6798 and not summary["cache_comparison"].get("mismatch", 0)
    assert summary["formula_status"] == {"computed": 6790, "unsupported": 4, "error": 4}
    plan = json.loads((output / "analysis/migration_plan.json").read_text(encoding="utf-8"))
    assert any(p["procedure"] == "CalculateMixed" for p in plan["calculation_order_candidates"])
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == before
    native = json.loads((OUT / "native-validation/native-results.json").read_text(encoding="utf-8"))
    record = {"fixture_sha256": before, "genuine_embedded_vba": True,
              "independent_expected_value_checks": checks, "cases": cases,
              "analysis_seconds": round(time.perf_counter()-start, 4), "analysis": summary,
              "native_vba": {"status": native["status"], "executed_cases": len(native["native_runs"]),
                             "opened_sheet_count": native.get("opened_sheet_count"),
                             "trust_settings_changed": native["trust_settings_changed"]},
              "source_unchanged": True, "runtime_llm_or_network_calls": 0,
              "harness_installed_or_modified": False}
    write_new(output / "verification.json", record)
    print(json.dumps({"checks": checks, "native_status": native["status"], "source_unchanged": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind-reviewed-fixture", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.bind_reviewed_fixture:
        bind_reviewed_fixture()
    elif args.output:
        run(args.output)
    else:
        parser.error("authoring --bind-reviewed-fixture or --output required")
