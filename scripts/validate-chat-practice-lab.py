"""Read-only fixture validation, except running the intentionally buggy code in a temp copy."""
import argparse
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lab", type=Path)
    args = parser.parse_args()
    root = args.lab.resolve()
    manifest = json.loads((root / "최초자료목록.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] and not manifest["personal_state_included"]
    with zipfile.ZipFile(root / "원본보관.zip") as z:
        assert z.testzip() is None
        assert set(z.namelist()) == {x["path"] for x in manifest["files"]}
        for entry in manifest["files"]:
            path = (root / entry["path"]).resolve()
            assert path.is_relative_to(root)
            data = path.read_bytes()
            assert len(data) == entry["bytes"]
            assert hashlib.sha256(data).hexdigest() == entry["sha256"]
            assert z.read(entry["path"]) == data
    assert not list(root.rglob("*.cmd")) and not list(root.rglob("*.ps1"))
    assert not list(root.rglob("*.exe"))
    # Sample Skill candidates must not yet be installed.
    assert len(list(root.rglob("SKILL.md"))) == 2
    assert not list((root / "실습프로젝트").rglob(".claude"))
    data = json.loads((root / "자료/02_실적과회의/월간실적_대체자료.json").read_text(encoding="utf-8"))
    rows = data["rows"]
    assert len(rows) == 6 and sum(r[2] for r in rows) == 450
    assert sum(r[3] for r in rows) == 530 and sum(r[4] for r in rows) == 25
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(root / "자료/02_실적과회의/월간실적.xlsx") as z:
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        byref = {c.attrib["r"]: c for c in sheet.findall(".//s:c", ns)}
        for i, row in enumerate(rows, 5):
            for col, value in zip("CDE", row[2:]):
                c = byref[f"{col}{i}"]
                assert c.attrib.get("t", "n") == "n"
                assert float(c.find("s:v", ns).text) == value
        assert not any("externalLink" in name or "vbaProject" in name for name in z.namelist())
    with zipfile.ZipFile(root / "자료/03_발표양식/가상회사_발표양식.pptx") as z:
        slides = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        assert len(slides) == 2
        for name in slides:
            x = ET.fromstring(z.read(name))
            assert len(x.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}t')) >= 5
            assert not x.findall('.//{http://schemas.openxmlformats.org/presentationml/2006/main}pic')
        assert not any("vbaProject" in name for name in z.namelist())
    mail_count, attachment_count = 0, 0
    for path in root.rglob("*.eml"):
        mail = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        assert not mail.defects
        assert parsedate_to_datetime(mail["Date"]).year == 2026
        assert "@example.invalid" in mail["To"] and "@example.invalid" in mail["From"]
        assert mail.get_body(preferencelist=("plain",)).get_content()
        for part in mail.iter_attachments():
            assert part.get_filename() == "회의안건.txt"
            assert "월간 실적" in part.get_payload(decode=True).decode("utf-8")
            attachment_count += 1
        mail_count += 1
    assert mail_count == 6 and attachment_count == 1
    guide = (root / "채팅대본.md").read_text(encoding="utf-8")
    assert len(re.findall(r"^## C\d+ ·", guide, re.M)) == 22
    # Existing referenced source paths (output files are intentionally absent).
    quoted = re.findall(r'"((?:자료|실습프로젝트)/[^"\n]+)"', guide)
    unresolved = []
    for rel in quoted:
        if "/.claude/" in rel:
            continue  # Installed only by an explicitly requested later chat.
        if not (root / rel).exists():
            unresolved.append(rel)
    assert not unresolved, unresolved
    with tempfile.TemporaryDirectory(prefix="company-chat-fixture-") as folder:
        copy = Path(folder) / "calculator"
        shutil.copytree(root / "실습프로젝트/작은계산기", copy)
        result = subprocess.run([sys.executable, "-B", "tests.py"], cwd=copy, capture_output=True, text=True)
        assert result.returncode == 1
        assert "Ran 6 tests" in result.stderr and "failures=3, errors=1" in result.stderr, result.stderr
    print(json.dumps({"status": "pass", "fixture_files": len(manifest["files"]), "chat_cases": 22,
                      "mail_files": mail_count, "attachments": attachment_count,
                      "workbook_numeric_data": True, "editable_template_slides": 2,
                      "baseline_and_backup_match": True, "source_references_exist": True,
                      "intended_calculator_defects_verified": True,
                      "harness_live_workflows_tested": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
