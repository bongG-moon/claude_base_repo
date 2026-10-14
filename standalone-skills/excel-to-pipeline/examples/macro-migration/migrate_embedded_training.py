"""Reviewed training example: one real XLSM input, no exported BAS required.

This is intentionally not selected for arbitrary company workbooks. The skill
authors a separate translation from their actual embedded sources instead.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts"))
from excel_pipeline import InputError, preflight
from migration_contract import verify_contract
from migrate_training import process_workbook, publish


def migrate(source, mode="mixed", include_exceptions=False):
    source = Path(source).resolve()
    preflight(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    evidence = verify_contract(source, HERE / "embedded-source-contract.json")
    result = process_workbook(source, mode, include_exceptions)
    if hashlib.sha256(source.read_bytes()).hexdigest() != before:
        raise InputError("검토 후 입력 파일이 바뀌어 결과를 발행하지 않았습니다.")
    result["summary"]["embedded_source_contract"] = evidence
    result["summary"]["embedded_vba_extracted"] = True
    result["summary"]["source_sidecars_required"] = False
    result["summary"]["migration_type"] = "user_adjusted_embedded_training_not_exact_vba_equivalence"
    result["migration_scope"] = {
        "entrypoint": "RunTraining(mixed=True)" if mode == "mixed" else "RunTraining(mixed=False)",
        "stages": ["TrainingPreparation.PrepareTraining → preprocess",
                   "TrainingCalculation.CalculateMixed → calculate_mixed" if mode == "mixed" else
                   "TrainingCalculation.CalculateMacroOnly → calculate_macro_only",
                   "TrainingCalculation.AggregateDepartments → aggregate"],
        "input": "신청원본/출결원본/평가원본/사원기준/교육기준/정책; 예외신청은 선택",
        "excluded": ["이벤트 자동 발생과 Excel 화면 조작", "오류수식 시트의 의도적인 오류·미지원 사례"],
        "formula_handling": "검토한 VBA가 출력 범위에 쓰는 수식만 같은 순서로 재현; 저장 캐시 사용 안 함",
        "intentional_rule_change": "원본 CodeOf/UCase는 보존된 원문에만 존재. Python은 사용자 요청에 따라 대소문자를 보존하고 정확히 일치하는 식별자만 연결",
        "source_contract_scope": "원문 변경 감지용이며 Python과 원본 VBA의 의미 동등성을 보증하지 않음",
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="내장 VBA와 검토된 계약이 일치하는 교육 예제를 Python으로 처리합니다")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=["macro-only", "mixed"], default="mixed")
    parser.add_argument("--include-exceptions", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise InputError("결과 폴더가 이미 있습니다. 새 폴더를 지정하세요.")
        result = migrate(args.source, args.mode, args.include_exceptions)
        publish(result, args.output)
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "not_migrated", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
