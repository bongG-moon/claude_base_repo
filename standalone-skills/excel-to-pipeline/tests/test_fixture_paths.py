"""Resolve committed synthetic inputs or the established standalone ZIP layout.

No home folders, generated outputs, Office, downloads or fixture writes are used.
"""
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]


def fixture_root():
    for folder in (SKILL / "tests" / "fixtures", SKILL.parent / "fixtures"):
        if (folder / "complex_workbook.xlsx").is_file():
            return folder
    raise FileNotFoundError("Synthetic test fixtures are missing; restore tests/fixtures from Git.")


def advanced_root():
    for folder in (SKILL / "tests", SKILL.parent):
        if (folder / "advanced-manifest.json").is_file():
            return folder
    raise FileNotFoundError("Synthetic test controls are missing; restore tests/advanced-manifest.json from Git.")
