"""Create a genuine embedded VBA fixture without changing Excel trust settings.

Only copies the independently authored synthetic xlsx. Adds reviewed local VBA
and a read/return-only validation bridge. Native execution is an explicit mode.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import time
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "outputs/excel-xlsm-migration-test"
FIXTURE = OUT / "fixtures/고급_내장VBA_혼합.xlsm"
VALIDATION = OUT / "native-validation"
SOURCE = ROOT / "outputs/excel-macro-migration-test/fixtures/고급_수식매크로_혼합.xlsx"
MODULES = ROOT / "standalone-skills/excel-to-pipeline/examples/macro-migration"
RUNTIME = VALIDATION / ".runtime"
sys.path.insert(0, str(RUNTIME))

BRIDGE = '''Attribute VB_Name = "FixtureBridge"
Option Explicit

' Synthetic test bridge. Returns values only. No file, network, mail or shell calls.
Public Function ValidateTraining(ByVal mixed As Boolean, ByVal includeExceptions As Boolean) As Variant
    Dim result As Object, item As Variant, department As Variant, totals As Object
    Dim output() As Variant, r As Long, c As Long, fields As Variant
    Set result = RunTraining(ThisWorkbook, mixed, includeExceptions)
    ReDim output(0 To result("records").Count + result("departments").Count + 1, 0 To 18)
    output(0, 0) = "summary"
    output(0, 1) = result("input_rows")
    output(0, 2) = result("deduplicated_rows")
    output(0, 3) = result("records").Count
    output(0, 4) = result("excluded").Count
    output(0, 5) = result("rejected").Count
    output(0, 6) = result("superseded").Count
    output(0, 7) = result("total_amount")
    output(0, 8) = result("completed_count")
    fields = Array("application_id", "employee_id", "department", "course_code", _
        "training_date", "quantity", "discount", "manual_amount", "unit_price", _
        "amount", "attended_sessions", "exam_taken", "score", "completed", _
        "source_sheet", "source_row", "pass_score", "round")
    output(1, 0) = "record_headers"
    For c = 0 To UBound(fields): output(1, c + 1) = fields(c): Next c
    r = 2
    For Each item In result("records")
        output(r, 0) = "record"
        For c = 0 To UBound(fields): output(r, c + 1) = item(fields(c)): Next c
        r = r + 1
    Next item
    For Each department In result("departments").Keys
        Set totals = result("departments")(department)
        output(r, 0) = "department"
        output(r, 1) = totals("department")
        output(r, 2) = totals("approved_count")
        output(r, 3) = totals("total_amount")
        output(r, 4) = totals("completed_count")
        r = r + 1
    Next department
    ValidateTraining = output
End Function
'''


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized(source: str) -> str:
    return source.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def create() -> None:
    from pyopenvba import ExcelFile

    if FIXTURE.exists():
        raise FileExistsError("Existing embedded fixture will not be replaced")
    VALIDATION.mkdir(parents=True, exist_ok=True)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    original_hash = sha(SOURCE.read_bytes())
    with zipfile.ZipFile(SOURCE) as z:
        parts = {i.filename: z.read(i.filename) for i in z.infolist()}
    ct = ET.fromstring(parts["[Content_Types].xml"])
    workbook_content_type_found = False
    for element in ct:
        if element.get("PartName") == "/xl/workbook.xml":
            element.set("ContentType", "application/vnd.ms-excel.sheet.macroEnabled.main+xml")
            workbook_content_type_found = True
    if not workbook_content_type_found:
        ET.SubElement(ct, "{http://schemas.openxmlformats.org/package/2006/content-types}Override", {
            "PartName": "/xl/workbook.xml",
            "ContentType": "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
        })
    converted = dict(parts)
    ET.register_namespace("", "http://schemas.openxmlformats.org/package/2006/content-types")
    converted["[Content_Types].xml"] = ET.tostring(ct, encoding="utf-8", xml_declaration=True)
    # pyOpenVBA's measured project-creation API expects conventional default XML
    # namespaces. Our synthetic fixture patch used equivalent ns0 prefixes.
    # Normalize only namespacing, then verify all worksheet data below.
    ET.register_namespace("", "http://schemas.openxmlformats.org/spreadsheetml/2006/main")
    ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
    for name in parts:
        if name == "xl/workbook.xml" or re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
            converted[name] = ET.tostring(ET.fromstring(parts[name]), encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(FIXTURE, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in converted.items():
            z.writestr(name, content)

    sources = {p.stem: normalized(p.read_text(encoding="utf-8-sig")) for p in sorted(MODULES.glob("*.bas"))}
    if set(sources) != {"TrainingPreparation", "TrainingCalculation", "EventWrapper"}:
        raise ValueError("Unexpected VBA source inventory")
    sources["FixtureBridge"] = normalized(BRIDGE)
    denied = r"(?im)^\s*(?:Public |Private )?(?:Sub|Function)\s+(?:Auto_Open|Workbook_Open|Worksheet_Change)\b|\b(?:Shell|CreateProcess|URLDownloadToFile|WinHttpRequest|XMLHTTP)\b"
    for name, source in sources.items():
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("'"))
        if re.search(denied, code):
            raise ValueError(f"Unexpected automatic or external action in {name}")

    with ExcelFile(FIXTURE) as book:
        project = book.add_vba_project()
        # The fresh Office template uses code page 1252. Korean literals need a
        # matching declared project code page, not lossy encoding replacement.
        needle = struct.pack("<HIH", 0x0003, 2, project.code_page)
        if project.dir_raw.count(needle) != 1:
            raise ValueError("Ambiguous PROJECTCODEPAGE record")
        project.dir_raw = project.dir_raw.replace(needle, struct.pack("<HIH", 0x0003, 2, 949), 1)
        project.code_page = 949
        document_modules = project.module_names()
        for module in project.modules:
            body = "\n".join(line for line in module.source.splitlines() if not line.startswith("Attribute ")).strip()
            if body:
                raise ValueError("Template document module contains executable code")
        for name, source in sources.items():
            project.add_module(name, source.replace("\n", "\r\n"))
        book.save()

    with ExcelFile(FIXTURE) as book:
        identities = []
        for name in book.module_names():
            actual = normalized(book.get_module(name))
            if name in sources and actual != sources[name]:
                raise AssertionError(f"Source round trip changed {name}")
            identities.append({"name": name, "sha256": sha(actual.encode("utf-8")), "characters": len(actual), "kind": "reviewed_business_or_bridge" if name in sources else "empty_document"})
        if book.vba_project().code_page != 949:
            raise AssertionError("Korean code page did not round trip")
    with zipfile.ZipFile(FIXTURE) as z:
        final = {i.filename: z.read(i.filename) for i in z.infolist()}
    changed = [name for name in parts if final.get(name) != parts[name]]
    permitted = {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
    unexpected = [name for name in changed if name not in permitted and not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)]
    # New document codenames are the only worksheet metadata change permitted.
    worksheet_diffs = []
    for name in changed:
        if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
            continue
        before, after = ET.fromstring(parts[name]), ET.fromstring(final[name])
        n = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        for x in (before, after):
            prop = x.find(n + "sheetPr")
            if prop is not None:
                prop.attrib.pop("codeName", None)
                if not prop.attrib and not list(prop):
                    x.remove(prop)
        if ET.tostring(before) != ET.tostring(after):
            worksheet_diffs.append(name)
    if unexpected or worksheet_diffs:
        raise AssertionError({"unexpected_parts": unexpected, "worksheet_content_changes": worksheet_diffs})
    assert sha(SOURCE.read_bytes()) == original_hash
    report = {"source_sha256": original_hash, "fixture_sha256": sha(FIXTURE.read_bytes()), "fixture": str(FIXTURE), "created_by": "pyOpenVBA 6.5.0 (MIT)", "project_code_page": 949, "vba_project_present": "xl/vbaProject.bin" in final, "modules": identities, "source_round_trip": "exact_normalized", "changed_parts": changed, "added_parts": sorted(set(final)-set(parts)), "sheet_values_formulas_styles_preserved": True, "original_xlsx_unchanged": True, "native_macro_execution": "not_run_yet", "vbom_access": "denied_by_existing_policy_not_changed", "automatic_entrypoints": False}
    (VALIDATION / "embedded-build.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def native() -> None:
    """Only run the locally created, SHA-bound fixture in a private Excel process."""
    import pythoncom
    import win32com.client
    import win32process

    build = json.loads((VALIDATION / "embedded-build.json").read_text(encoding="utf-8"))
    if sha(FIXTURE.read_bytes()) != build["fixture_sha256"]:
        raise ValueError("Fixture changed since source verification")
    pythoncom.CoInitialize()
    app = book = None
    result = {"fixture_sha256": build["fixture_sha256"], "trust_settings_changed": False, "external_links_updated": False, "native_runs": [], "status": "not_started"}
    try:
        app = win32com.client.DispatchEx("Excel.Application")
        app.Visible = False
        app.DisplayAlerts = False
        app.EnableEvents = False
        app.AskToUpdateLinks = False
        # Never weaken macro policy. Use UI policy for this dedicated instance.
        app.AutomationSecurity = 2
        result["excel_version"] = app.Version
        result["owned_process_id"] = win32process.GetWindowThreadProcessId(app.Hwnd)[1]
        book = app.Workbooks.Open(str(FIXTURE), UpdateLinks=0, ReadOnly=True, IgnoreReadOnlyRecommended=True, AddToMru=False)
        result["opened_sheet_count"] = book.Worksheets.Count
        for mixed, include_exceptions in [(False, False), (True, False), (False, True), (True, True)]:
            started = time.perf_counter()
            matrix = app.Run(f"'{book.Name}'!FixtureBridge.ValidateTraining", mixed, include_exceptions)
            s = matrix[0]
            summary_names = ["input_rows", "deduplicated_rows", "approved_count", "excluded_count", "rejected_count", "superseded_count", "total_amount", "completed_count"]
            headers = matrix[1][1:]
            run = {"mixed": mixed, "include_exceptions": include_exceptions, "elapsed_seconds": round(time.perf_counter()-started, 4), "summary": dict(zip(summary_names, s[1:9])), "records": [], "departments": []}
            for row in matrix[2:]:
                if row[0] == "record":
                    run["records"].append(dict(zip(headers, row[1:])))
                elif row[0] == "department":
                    run["departments"].append(dict(zip(["department", "approved_count", "total_amount", "completed_count"], row[1:5])))
            result["native_runs"].append(run)
            print(json.dumps({k: v for k, v in run.items() if k not in {"records", "departments"}}, ensure_ascii=False), flush=True)
        result["status"] = "executed"
    except Exception as error:
        result["status"] = "failed_or_policy_blocked"
        result["exception_type"] = type(error).__name__
        result["message"] = str(error)
    finally:
        if book is not None:
            book.Close(SaveChanges=False)
        if app is not None:
            app.Quit()
        pythoncom.CoUninitialize()
        result["fixture_unchanged"] = sha(FIXTURE.read_bytes()) == build["fixture_sha256"]
        (VALIDATION / "native-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "native_runs"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["create", "native"])
    args = parser.parse_args()
    create() if args.mode == "create" else native()
