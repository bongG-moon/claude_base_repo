"""Package only the independent Excel/VBA trial, never installed harness files."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
OUTPUT = ROOT / "outputs" / "excel-macro-migration-test"
VERIFIED = OUTPUT / "verified-final"
ARCHIVE = OUTPUT / "Excel-VBA-Python-독립시험-0.2.0.zip"
PREFIX = "Excel-VBA-Python-독립시험"


def main():
    entries = {name: OUTPUT / name for name in ("시작하기.md", "검증결과.md", "advanced-manifest.json", "vba-index.json")}
    for name in ("verification.json", "unit-test-results.txt"):
        entries["검증기록/" + name] = VERIFIED / name
    for relative in ("SKILL.md", "requirements.txt", "references/plan.md", "references/limits.md",
                     "references/vba-migration.md", "scripts/excel_pipeline.py", "scripts/formula_engine.py", "scripts/vba_inspect.py",
                     "tests/fixtures-manifest.json"):
        entries["excel-to-pipeline/" + relative] = SKILL / relative
    for p in (SKILL / "tests").glob("test_*.py"):
        entries["excel-to-pipeline/tests/" + p.name] = p
    for name in ("migrate_training.py", "TrainingPreparation.bas", "TrainingCalculation.bas", "EventWrapper.bas", "이전-매핑.md"):
        entries["excel-to-pipeline/examples/macro-migration/" + name] = SKILL / "examples" / "macro-migration" / name
    for name in ("고급_수식매크로_혼합.xlsx", "매크로전용_입력.xlsx"):
        entries["fixtures/" + name] = OUTPUT / "fixtures" / name
    for name in ("complex_workbook.xlsx", "variant_next_month.xlsx", "ambiguous_cases.xlsx"):
        entries["fixtures/" + name] = ROOT / "outputs" / "excel-to-pipeline-test" / name
    for folder, label in (("macro_only-macro-only-base", "매크로전용-정상"),
                          ("mixed-mixed-base", "혼합-정상"), ("mixed-mixed-exceptions", "혼합-예외포함")):
        for path in (VERIFIED / folder).iterdir():
            if path.is_file():
                entries["처리결과/" + label + "/" + path.name] = path
    for path in (VERIFIED / "structure-analysis").rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            entries["구조분석/" + path.relative_to(VERIFIED / "structure-analysis").as_posix()] = path
    for name in ("고급_수식매크로_혼합-집계.png", "고급_수식매크로_혼합-비정형.png"):
        entries["미리보기/" + name] = OUTPUT / "previews" / name
    for relative, path in entries.items():
        assert path.is_file() and not path.is_symlink(), path
        assert "node_modules" not in path.parts and "__pycache__" not in path.parts
        assert not relative.startswith("/") and ".." not in Path(relative).parts
    with zipfile.ZipFile(ARCHIVE, "x", zipfile.ZIP_DEFLATED) as archive:
        for relative, path in sorted(entries.items()):
            archive.write(path, PREFIX + "/" + relative)
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None
        for relative, path in entries.items():
            assert archive.read(PREFIX + "/" + relative) == path.read_bytes()
        # Test the actual extracted distribution, not just source-tree imports.
        with tempfile.TemporaryDirectory(prefix="package-check-", dir=OUTPUT) as temp:
            archive.extractall(temp)
            unpacked = Path(temp) / PREFIX
            run = subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s",
                                  str(unpacked / "excel-to-pipeline" / "tests"), "-p", "test_*.py", "-v"],
                                 cwd=unpacked, capture_output=True, text=True, encoding="utf-8", timeout=120)
            (OUTPUT / "packaged-test-results.txt").write_text(run.stdout + run.stderr, encoding="utf-8")
            if run.returncode:
                raise RuntimeError(run.stdout + run.stderr)
            assert "Ran 87 tests" in run.stderr and "skipped" not in run.stderr, run.stderr
    record = {"archive": ARCHIVE.name, "files": len(entries), "bytes": ARCHIVE.stat().st_size,
              "sha256": hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(), "unpacked_tests_passed": 87,
              "harness_installed": False}
    (OUTPUT / "package-verification.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
