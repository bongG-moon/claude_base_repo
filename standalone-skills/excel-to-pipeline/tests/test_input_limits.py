"""Tiny container tests: reject oversized implicit ranges before loading Excel."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import excel_pipeline as pipeline


NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def worksheet(merges=(), dimension="A1:B2", cell="A1"):
    dimension_xml = "" if dimension is None else f'<dimension ref="{dimension}"/>'
    merge_xml = "".join(f'<mergeCell ref="{ref}"/>' for ref in merges)
    return (f'<worksheet xmlns="{NAMESPACE}">{dimension_xml}'
            f'<sheetData><row r="1"><c r="{cell}"><v>1</v></c></row></sheetData>'
            f'<mergeCells count="{len(merges)}">{merge_xml}</mergeCells></worksheet>').encode()


class InputLimitsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="excel-pipeline-limits-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "small.xlsx"

    def container(self, sheet=None, tables=(), extra=None):
        with zipfile.ZipFile(self.source, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", f'<workbook xmlns="{NAMESPACE}"/>')
            archive.writestr("xl/worksheets/sheet1.xml", worksheet() if sheet is None else sheet)
            for index, ref in enumerate(tables, 1):
                archive.writestr(f"xl/tables/table{index}.xml",
                                 f'<table xmlns="{NAMESPACE}" ref="{ref}"/>')
            for name, data in (extra or {}).items():
                archive.writestr(name, data)
        self.assertLess(self.source.stat().st_size, 4096)

    def assert_rejected_before_load(self, phrase):
        before = self.source.read_bytes()
        with patch.object(pipeline.openpyxl, "load_workbook") as loader:
            with self.assertRaisesRegex(pipeline.InputError, phrase):
                pipeline.analyze(self.source)
            loader.assert_not_called()
        self.assertEqual(self.source.read_bytes(), before)

    def test_normal_small_ranges_pass_preflight(self):
        self.container(worksheet(["A1:C2", "A4:B5"], dimension="A1:E12"), tables=["B3:D12"])
        self.assertEqual(pipeline.preflight(self.source), [])

    def test_merge_over_coordinate_limit(self):
        self.container(worksheet(["A1:XFD1048576"]))
        self.assert_rejected_before_load("병합.*512열")

    def test_merge_over_area_limit(self):
        self.container(worksheet(["A1:SF1000"]))
        self.assert_rejected_before_load("병합.*면적")

    def test_cumulative_merge_area_same_sheet(self):
        self.container(worksheet(["A1:GR500", "A501:GR1000", "A1001:GR1500"]))
        self.assert_rejected_before_load("병합.*누적")

    def test_cumulative_merge_area_across_sheets(self):
        self.container(worksheet(["A1:GR1000"]), extra={
            "xl/worksheets/sheet2.xml": worksheet(["A1:GR500"])})
        self.assert_rejected_before_load("병합.*누적")

    def test_table_over_coordinate_limit(self):
        self.container(tables=["A1:XFD1048576"])
        self.assert_rejected_before_load("Excel Table.*512열")

    def test_table_over_area_limit(self):
        self.container(tables=["A1:SF3000"])
        self.assert_rejected_before_load("Excel Table.*면적")

    def test_cumulative_table_area_is_bounded(self):
        self.container(tables=["A1:SF800", "A1:SF800", "A1:SF800"])
        self.assert_rejected_before_load("Excel Table 누적")

    def test_table_count_is_bounded(self):
        self.container(tables=["A1:B2"] * 3)
        # Lower the same configurable guard to avoid creating hundreds of files.
        with patch.object(pipeline, "MAX_REGIONS", 2):
            self.assert_rejected_before_load("Excel Table 누적")

    def test_bad_merge_ranges_are_input_errors(self):
        for ref in ["", "A:B", "1:10", "B2:A1", "A0:B2", "A1:B2:C3", "Other!A1:B2"]:
            with self.subTest(ref=ref):
                self.container(worksheet([ref]))
                self.assert_rejected_before_load("잘못된 병합")

    def test_bad_table_ranges_are_input_errors(self):
        for ref in ["", "A:B", "B2:A1", "A0:B2", "A1:B2:C3"]:
            with self.subTest(ref=ref):
                self.container(tables=[ref])
                self.assert_rejected_before_load("잘못된 Excel Table")

    def test_missing_merge_range_is_input_error(self):
        self.container(worksheet(["A1:B2"]).replace(b'ref="A1:B2"/></mergeCells>', b'/></mergeCells>'))
        self.assert_rejected_before_load("잘못된 병합")

    def test_invalid_dimension_is_input_error(self):
        self.container(worksheet(dimension="B2:A1"))
        self.assert_rejected_before_load("잘못된 시트")

    def test_invalid_cell_reference_is_input_error(self):
        self.container(worksheet(cell="A1:B2"))
        self.assert_rejected_before_load("잘못된 셀")

    def test_no_dimension_cannot_hide_large_merge(self):
        self.container(worksheet(["A1:XFD1048576"], dimension=None))
        self.assert_rejected_before_load("병합.*512열")

    def test_dtd_entities_blocked_in_utf8_utf16_utf32(self):
        xml = ('<?xml version="1.0"?><!DOCTYPE worksheet [<!ENTITY test "value">]>'
               f'<worksheet xmlns="{NAMESPACE}"/>')
        for encoding in ["utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"]:
            with self.subTest(encoding=encoding):
                self.container(xml.encode(encoding))
                self.assert_rejected_before_load("DTD/entity")

    def test_entities_blocked_in_non_worksheet_xml(self):
        self.container(extra={"xl/comments1.xml": '<!ENTITY test "value">'.encode("utf-16")})
        self.assert_rejected_before_load("DTD/entity")


if __name__ == "__main__":
    unittest.main()
