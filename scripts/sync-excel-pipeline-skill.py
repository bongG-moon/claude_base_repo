"""Build/check the employee skill from the standalone authoritative sources.

Only the explicitly listed runtime and references are distributed. No fixtures,
tests, workbook contents, binaries, environments or migration-example code.
This runs during development/release validation, never in a user hook.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "standalone-skills" / "excel-to-pipeline"
DESTINATION = ROOT / "company-agent-plugin" / "skills" / "excel-to-pipeline"
RUNTIME = ("excel_pipeline.py", "formula_engine.py", "migration_contract.py",
           "model_context.py", "vba_extract.py", "vba_inspect.py",
           "workbook_input.py", "xlwings_reader.py", "project_builder.py", "project_runtime.py",
           "python_formulas.py", "project_selection.py", "compact_project.py", "workflow_report.py")
ASSETS = ("NotoSansKR-Variable.woff", "OFL.txt", "SOURCE.json")
REFERENCES = ("plan.md", "limits.md", "excel-reader.md", "vba-migration.md")
REQUIREMENTS = ("requirements.txt", "requirements-vba.txt", "requirements-excel.txt")


def reference_for_distribution(name: str, text: str) -> str:
    """Remove standalone-only locations, not analysis/security instructions."""
    text = text.replace("이 독립 스킬", "이 스킬").replace("현재 시험은", "현재 이전 방식은")
    if name == "vba-migration.md":
        first, rest = text.split("## 시험 예제", 1)
        text = first + "## 공식 참고" + rest.split("## 공식 참고", 1)[1]
    elif name == "excel-reader.md":
        text = text.replace(
            "- 기존 교육용 `migrate_embedded_training.py`는 일반 OOXML 원문 계약 전용이다.\n"
            "  보호 파일에 그대로 적용하지 말고, 확보한 원문에 맞춘 업무별 이전 코드가 필요하다.\n", "")
    elif name == "limits.md":
        text = text.replace("# 시험판 범위", "# 분석 범위와 제한")
        text = text.replace("기존 하네스, 스킬 목록, 후크, 사용자 Claude 설정은 바꾸지 않았다.",
                            "분석 요청에서만 실행하며 추가 후크·모델 호출·사용자 설정 변경은 하지 않는다.")
    return text


def expected_files() -> dict[str, bytes]:
    # Canonical LF for text, untouched bytes for fonts; Git checkout settings
    # must neither fake divergence nor corrupt a WOFF binary.
    result = {f"scripts/{name}": (SOURCE / "scripts" / name).read_bytes().replace(b'\r\n', b'\n') for name in RUNTIME}
    for name in ASSETS:
        content = (SOURCE / "assets" / name).read_bytes()
        result[f"assets/{name}"] = content if name.endswith('.woff') else content.replace(b'\r\n', b'\n')
    result.update({name: (SOURCE / name).read_bytes().replace(b'\r\n', b'\n') for name in REQUIREMENTS})
    for name in REFERENCES:
        result[f"references/{name}"] = reference_for_distribution(
            name, (SOURCE / "references" / name).read_text(encoding="utf-8")).encode("utf-8")
    manifest = {"source": "standalone-skills/excel-to-pipeline",
                "generatedBy": "scripts/sync-excel-pipeline-skill.py",
                "hashEncoding": "UTF-8 text with LF line endings; font assets are raw bytes",
                "files": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(result.items())}}
    result["runtime-source.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sync the Excel skill runtime without copying test data.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    different = []
    for name, content in expected_files().items():
        target = DESTINATION / name
        actual = target.read_bytes() if target.is_file() else None
        if actual is not None and not name.endswith('.woff'):
            actual = actual.replace(b'\r\n', b'\n')
        expected = content if name.endswith('.woff') else content.replace(b'\r\n', b'\n')
        if actual != expected:
            different.append(name)
            if not args.check:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
    if args.check and different:
        print("Excel skill is stale; run scripts/sync-excel-pipeline-skill.py: " + ", ".join(different))
        return 1
    print("Excel skill sources match." if args.check else f"Excel skill synchronized: {len(different)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
