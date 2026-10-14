"""Opt-in clean-source test: copies only reusable source + synthetic fixtures.

No outputs/.smoke, dependency runtime, Office or network is copied or started.
The temporary mirror is deleted only after its resolved parent is checked.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SKILL = Path(__file__).resolve().parents[1]
PATTERNS = {
    "": ("*.md", "requirements*.txt"),
    "scripts": ("*.py",),
    "references": ("*.md",),
    "examples/macro-migration": ("*.py", "*.bas", "*.json", "*.md"),
    "tests": ("*.py", "*.json"),
    "tests/fixtures": ("*.xlsx", "*.xlsm", "*.md"),
}


def main():
    with tempfile.TemporaryDirectory(prefix=".clean-source-", dir=SKILL) as temporary:
        root = Path(temporary).resolve()
        if root.parent != SKILL.resolve():
            raise ValueError("Temporary source mirror escaped the skill folder")
        target = root / "standalone-skills" / "excel-to-pipeline"
        count, total = 0, 0
        for directory, patterns in PATTERNS.items():
            for pattern in patterns:
                for source in (SKILL / directory).glob(pattern):
                    if not source.is_file() or source.is_symlink():
                        raise ValueError("Only regular source and fixture files may be copied")
                    destination = target / source.relative_to(SKILL)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                    count += 1
                    total += source.stat().st_size
        if (root / "outputs").exists() or (root / ".smoke").exists():
            raise AssertionError("Clean-source validation cannot contain local outputs/runtime")
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        run = subprocess.run([sys.executable, "-X", "utf8", "-B", "-m", "unittest", "discover",
                              "-s", str(target / "tests"), "-p", "test_*.py", "-v"],
                             cwd=root, env=env, text=True, encoding="utf-8", capture_output=True, timeout=180)
        print(run.stdout)
        print(run.stderr)
        if run.returncode or "skipped=" in run.stderr:
            raise RuntimeError("Clean-source tests must pass without skips")
        print(json.dumps({"clean_source_passed": True, "copied_files": count, "copied_bytes": total,
                          "outputs_or_runtime_copied": False, "excel_started": False}))


if __name__ == "__main__":
    main()
