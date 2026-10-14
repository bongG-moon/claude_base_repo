"""Allowlisted independent trial delivery and unpacked execution verification."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
BASE = ROOT / "outputs/excel-xlsm-migration-test"
OUT = ROOT / "outputs/excel-xlsm-native-check"
OLD = ROOT / "outputs/excel-macro-migration-test"
PREFIX = "Excel-XLSM-Python-독립시험"
ARCHIVE = OUT / "Excel-XLSM-Python-독립시험-0.4.0.zip"


def run(command, cwd, timeout=180):
    result = subprocess.run([sys.executable, "-X", "utf8", *map(str, command)],
                            cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result


def main():
    entries = {name: OUT / name for name in ("시작하기.md", "검증결과.md")}
    entries["advanced-manifest.json"] = OLD / "advanced-manifest.json"
    entries["fixtures/고급_내장VBA_혼합.xlsm"] = BASE / "fixtures/고급_내장VBA_혼합.xlsm"
    for name in ("고급_수식매크로_혼합.xlsx", "매크로전용_입력.xlsx"):
        entries["fixtures/" + name] = OLD / "fixtures" / name
    for name in ("complex_workbook.xlsx", "variant_next_month.xlsx", "ambiguous_cases.xlsx"):
        entries["fixtures/" + name] = ROOT / "outputs/excel-to-pipeline-test" / name
    for relative in ("SKILL.md", "시험안내.md", "requirements.txt", "requirements-vba.txt", "tests/fixtures-manifest.json"):
        entries["excel-to-pipeline/" + relative] = SKILL / relative
    for directory, patterns in (("scripts", ("*.py",)), ("references", ("*.md",)),
                                ("examples/macro-migration", ("*.py", "*.bas", "*.md", "*.json")),
                                ("tests", ("test_*.py",))):
        for pattern in patterns:
            for path in (SKILL / directory).glob(pattern):
                entries["excel-to-pipeline/" + path.relative_to(SKILL).as_posix()] = path
    for directory in ("analysis", "mixed-base", "mixed-exceptions"):
        for path in (OUT / "verified-budget" / directory).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                entries["처리예시/" + directory + "/" + path.relative_to(OUT / "verified-budget" / directory).as_posix()] = path
    for name, path in {
        "verification.json": OUT / "verified-budget/verification.json",
        "embedded-build.json": BASE / "native-validation/embedded-build.json",
        "previous-native-results.json": BASE / "native-validation/native-results.json",
        "change-verification.json": BASE / "change-validation/verification.json",
        "context-verification.json": OUT / "rechecked/context-verification.json",
    }.items():
        entries["검증기록/" + name] = path
    for path in (OUT / "native").glob("*.json"):
        entries["검증기록/native/" + path.name] = path
    entries["라이선스/pyOpenVBA-LICENSE.md"] = BASE / "native-validation/.runtime/pyopenvba-6.5.0.dist-info/licenses/LICENSE.md"
    for relative, path in entries.items():
        assert path.is_file() and not path.is_symlink(), path
        assert not any(part in {"node_modules", "__pycache__"} for part in path.parts)
        assert not relative.startswith("/") and ".." not in Path(relative).parts
    # Include reproducible unit evidence; require every test, not silent skips.
    unit = run(["-m", "unittest", "discover", "-s", SKILL / "tests", "-p", "test_*.py", "-v"], ROOT)
    count = int(re.search(r"Ran (\d+) tests", unit.stderr).group(1))
    assert "skipped" not in unit.stderr
    log = OUT / "unit-test-results.txt"
    log.write_text(unit.stdout + unit.stderr, encoding="utf-8")
    entries["검증기록/unit-test-results.txt"] = log
    with zipfile.ZipFile(ARCHIVE, "x", zipfile.ZIP_DEFLATED) as archive:
        for relative, path in sorted(entries.items()):
            archive.write(path, PREFIX + "/" + relative)
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None
        for relative, path in entries.items():
            assert archive.read(PREFIX + "/" + relative) == path.read_bytes()
        with tempfile.TemporaryDirectory(prefix="unpacked-check-", dir=OUT) as temp:
            assert Path(temp).resolve().is_relative_to(OUT.resolve())
            archive.extractall(temp)
            unpacked = Path(temp) / PREFIX
            done = run(["-m", "unittest", "discover", "-s", unpacked / "excel-to-pipeline/tests", "-p", "test_*.py", "-v"], unpacked)
            assert f"Ran {count} tests" in done.stderr and "skipped" not in done.stderr
            (OUT / "packaged-test-results.txt").write_text(done.stdout + done.stderr, encoding="utf-8")
            source = unpacked / "fixtures/고급_내장VBA_혼합.xlsm"
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            migrated = run([unpacked / "excel-to-pipeline/examples/macro-migration/migrate_embedded_training.py", source,
                            "--output", unpacked / "real-output", "--include-exceptions"], unpacked)
            summary = json.loads(migrated.stdout)
            assert summary["approved_count"] == 376 and summary["total_amount"] == 182230628
            assert summary["rejected_count"] == 9 and not summary["original_vba_equivalent"]
            assert summary["embedded_source_contract"]["status"] == "matched"
            assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    record = {"archive": ARCHIVE.name, "entries": len(entries), "bytes": ARCHIVE.stat().st_size,
              "sha256": hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(), "source_tests_passed": count,
              "unpacked_tests_passed": count, "unpacked_xlsm_migration_passed": True,
              "harness_installed": False, "dependencies_bundled": False}
    (OUT / "package-verification.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
