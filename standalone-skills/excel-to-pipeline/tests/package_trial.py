"""Build a small standalone trial archive from an explicit file allowlist."""
import hashlib
import json
from pathlib import Path
import zipfile

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
OUTPUT = ROOT / "outputs" / "excel-to-pipeline-test"
ARCHIVE = OUTPUT / "Excel-구조분석-독립스킬-0.1.0.zip"


def main():
    entries = {
        "시작하기.md": SKILL / "시험안내.md",
        "검증결과.md": OUTPUT / "검증결과.md",
        "verification.json": OUTPUT / "verification.json",
        "unit-test-results.txt": OUTPUT / "unit-test-results.txt",
    }
    for relative in ["SKILL.md", "requirements.txt", "references/limits.md", "references/plan.md",
                     "scripts/excel_pipeline.py", "scripts/formula_engine.py",
                     "tests/test_formulas.py", "tests/test_extraction.py", "tests/test_end_to_end.py",
                     "tests/test_input_limits.py", "tests/fixtures-manifest.json"]:
        entries["excel-to-pipeline/" + relative] = SKILL / relative
    for name in ("complex_workbook.xlsx", "variant_next_month.xlsx", "ambiguous_cases.xlsx"):
        entries["fixtures/" + name] = OUTPUT / name
    for folder, label in [("verified-base", "첫분석"), ("verified-next", "다음달"),
                          ("verified-exceptions", "예외확인")]:
        for path in (OUTPUT / folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                entries["검증예시/" + label + "/" + path.relative_to(OUTPUT / folder).as_posix()] = path
    # No fixture-builder dependency junction, installed packages, or unrelated workspace files.
    assert len(entries) < 100
    for relative, path in entries.items():
        assert path.is_file(), path
        assert "node_modules" not in path.parts and not path.is_symlink(), path
        assert not relative.startswith("/") and ".." not in Path(relative).parts
    with zipfile.ZipFile(ARCHIVE, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, path in sorted(entries.items()):
            archive.write(path, "Excel-구조분석-독립시험/" + relative)
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None
        for relative, path in entries.items():
            assert archive.read("Excel-구조분석-독립시험/" + relative) == path.read_bytes()
    print(json.dumps({"archive": str(ARCHIVE), "file_count": len(entries), "bytes": ARCHIVE.stat().st_size,
                      "sha256": hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
