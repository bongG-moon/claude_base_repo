"""Native reader safety and normalization without starting Microsoft Excel."""
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import xlwings_reader as reader


def xml(rows, styles="", table_attrs=""):
    return ('<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
            'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Styles>'
            '<Style ss:ID="Default"><NumberFormat ss:Format="General"/></Style>'
            + styles + '</Styles><Worksheet ss:Name="Sheet"><Table ' + table_attrs + '>'
            + rows + '</Table></Worksheet></Workbook>')


SIMPLE_XML = xml('<Row><Cell><Data ss:Type="String">ID</Data></Cell>'
                 '<Cell><Data ss:Type="String">값</Data></Cell></Row>'
                 '<Row><Cell><Data ss:Type="String">001</Data></Cell>'
                 '<Cell ss:Formula="=1+2"><Data ss:Type="Number">3</Data></Cell></Row>')


class Collection:
    def __init__(self, items):
        self.items = items

    @property
    def Count(self):
        return len(self.items)

    def Item(self, index):
        return self.items[index-1]


class NativeBook:
    def __init__(self, *, has_vba=True):
        self.ReadOnly = True
        self.Date1904 = False
        self.FileFormat = 52 if has_vba else 51
        self.HasVBProject = has_vba
        self.vba_reads = 0
        self.Close = Mock()
        used = types.SimpleNamespace(Row=4, Column=2, Rows=types.SimpleNamespace(Count=2),
                                     Columns=types.SimpleNamespace(Count=2),
                                     Formula=(("ID", "값"), ("001", "=1+2")),
                                     Value2=(("ID", "값"), ("001", 3)),
                                     _oleobj_=types.SimpleNamespace(Invoke=Mock(return_value=SIMPLE_XML)))
        used.HasFormula = None
        area = types.SimpleNamespace(Row=5, Column=3, Rows=types.SimpleNamespace(Count=1),
                                     Columns=types.SimpleNamespace(Count=1))
        used.SpecialCells = Mock(return_value=types.SimpleNamespace(Areas=Collection([area])))
        sheet = types.SimpleNamespace(Name="자료", Visible=-1, Type=-4167, UsedRange=used,
                                      ListObjects=Collection([]), QueryTables=Collection([]),
                                      PivotTables=lambda: Collection([]))
        self.Worksheets = Collection([sheet])
        self.Sheets = self.Worksheets
        self.Names = Collection([])
        self.Connections = Collection([])
        self.LinkSources = lambda kind: None

    @property
    def VBProject(self):
        self.vba_reads += 1
        raise PermissionError("VBOM denied")


def environment(book=None, fail_open=False):
    book = book or NativeBook()
    blank = types.SimpleNamespace(Close=Mock())
    native = types.SimpleNamespace(Version="16.0")

    def add(kind):
        assert kind == -4167
        assert native.AutomationSecurity == 3 and native.EnableEvents is False
        return blank

    def open_book(source, **options):
        assert native.AutomationSecurity == 3 and native.EnableEvents is False
        assert native.Calculation == -4135
        assert options == {"UpdateLinks": 0, "ReadOnly": True, "Password": "", "WriteResPassword": "",
                           "IgnoreReadOnlyRecommended": True, "Notify": False, "AddToMru": False,
                           "CorruptLoad": 0}
        if fail_open:
            raise PermissionError("Company policy")
        return book

    native.Workbooks = types.SimpleNamespace(Add=Mock(side_effect=add), Open=Mock(side_effect=open_book))
    app = types.SimpleNamespace(api=native, pid=123456, quit=Mock())
    xw = types.SimpleNamespace(App=Mock(return_value=app))
    return xw, app, blank, book


class XmlTests(unittest.TestCase):
    def test_used_range_offset_and_formula(self):
        cells, merges = reader.parse_range_xml(SIMPLE_XML, (("ID", "값"), ("001", "=1+2")), (4, 2), (2, 2))
        self.assertEqual(cells[0][:2], [4, 2])
        self.assertEqual(cells[2][2:5], ["001", "s", None])
        self.assertEqual(cells[3][2:5], [3, "n", "=1+2"])
        self.assertEqual(merges, [])

    def test_literal_equals_is_not_formula(self):
        payload = xml('<Row><Cell><Data ss:Type="String">=not a formula</Data></Cell></Row>')
        cells, _ = reader.parse_range_xml(payload, "=not a formula", (1, 1), (1, 1))
        self.assertEqual(cells[0][3:5], ["s", None])

    def test_date_error_boolean_zero_and_number_format(self):
        payload = xml('<Row><Cell><Data ss:Type="DateTime">2026-10-14T12:30:00</Data></Cell>'
                      '<Cell><Data ss:Type="Error">#DIV/0!</Data></Cell>'
                      '<Cell><Data ss:Type="Boolean">0</Data></Cell>'
                      '<Cell ss:StyleID="code"><Data ss:Type="Number">0</Data></Cell></Row>',
                      '<Style ss:ID="code"><NumberFormat ss:Format="00000"/></Style>')
        cells, _ = reader.parse_range_xml(payload, ((0, 0, False, 0),), (1, 1), (1, 4))
        self.assertEqual([c[3] for c in cells], ["d", "e", "b", "n"])
        self.assertEqual(cells[3][2], 0)
        self.assertEqual(cells[3][5], "00000")

    def test_merge_and_sparse_indexes(self):
        payload = xml('<Row ss:Index="2"><Cell ss:Index="2" ss:MergeAcross="1" ss:MergeDown="1">'
                      '<Data ss:Type="String">제목</Data></Cell></Row>')
        cells, merges = reader.parse_range_xml(payload, ((None,)*3,)*3, (4, 2), (3, 3))
        self.assertEqual(cells[0][:2], [5, 3])
        self.assertEqual(merges, ["C5:D6"])

    def test_empty_string_is_not_blank(self):
        cells, _ = reader.parse_range_xml(xml('<Row><Cell><Data ss:Type="String"></Data></Cell></Row>'),
                                         "", (1, 1), (1, 1))
        self.assertEqual(cells[0][2:4], ["", "s"])

    def test_styles_inherit_and_cycle_rejected(self):
        payload = xml('<Row><Cell ss:StyleID="child"><Data ss:Type="Number">7</Data></Cell></Row>',
                      '<Style ss:ID="parent"><NumberFormat ss:Format="000"/></Style>'
                      '<Style ss:ID="child" ss:Parent="parent"/>')
        cells, _ = reader.parse_range_xml(payload, 7, (1, 1), (1, 1))
        self.assertEqual(cells[0][5], "000")
        bad = payload.replace('ss:Parent="parent"', 'ss:Parent="child"')
        with self.assertRaises(reader.NativeReadError):
            reader.parse_range_xml(bad, 7, (1, 1), (1, 1))

    def test_dtd_and_xml_size_rejected(self):
        with self.assertRaises(reader.NativeReadError):
            reader.parse_range_xml('<!DOCTYPE x>' + SIMPLE_XML, (), (1, 1), (1, 1))
        with patch.object(reader, "MAX_XML", 10), self.assertRaises(reader.NativeReadError):
            reader.parse_range_xml(SIMPLE_XML, (), (1, 1), (1, 1))

    def test_bad_shape_and_outside_range_rejected(self):
        with self.assertRaises(reader.NativeReadError):
            reader.parse_range_xml(SIMPLE_XML, ((1,),), (1, 1), (2, 2))
        with self.assertRaises(reader.NativeReadError):
            reader.parse_range_xml(SIMPLE_XML, ((1,2),(3,4)), (100_000, 512), (2, 2))

    def test_unknown_cell_type_and_nonfinite_number_rejected(self):
        for cell in ['<Data ss:Type="Mystery">x</Data>', '<Data ss:Type="Number">nan</Data>']:
            with self.subTest(cell=cell), self.assertRaises(reader.NativeReadError):
                reader.parse_range_xml(xml('<Row><Cell>' + cell + '</Cell></Row>'), "", (1,1), (1,1))

    def test_header_style_preserved(self):
        payload = xml('<Row><Cell ss:StyleID="heading"><Data ss:Type="String">부서</Data></Cell></Row>',
                      '<Style ss:ID="heading"><Font ss:Bold="1"/><Interior ss:Pattern="Solid"/></Style>')
        cells, _ = reader.parse_range_xml(payload, "부서", (1,1), (1,1))
        self.assertEqual(cells[0][6], {"bold": True, "fill": True})

    def test_cross_sheet_formula_preserved_when_xml_omits_formula_attribute(self):
        payload = xml('<Row><Cell><Data ss:Type="String">00105</Data></Cell>'
                      '<Cell><Data ss:Type="String">=literal</Data></Cell></Row>')
        cells, _ = reader.parse_range_xml(payload, (("='신청'!B10", "=literal"),), (10, 2), (1, 2), {(10,2)})
        self.assertEqual(cells[0][4], "='신청'!B10")
        self.assertIsNone(cells[1][4])

    def test_missing_native_formula_from_xml_is_not_silently_dropped(self):
        with self.assertRaises(reader.NativeReadError):
            reader.parse_range_xml(xml('<Row/>'), "=1", (1,1), (1,1), {(1,1)})

    def test_formula_mask_without_per_cell_calls(self):
        used = types.SimpleNamespace(HasFormula=True)
        self.assertEqual(reader._formula_cells(used, (4,2), (1,2)), {(4,2),(4,3)})
        used.HasFormula = False
        self.assertEqual(reader._formula_cells(used, (4,2), (1,2)), set())

    def test_bulk_values_preserve_spaces_and_formula_cached_strings(self):
        payload = xml('<Row><Cell><Data ss:Type="String">c03</Data></Cell>'
                      '<Cell><Data ss:Type="String">text</Data></Cell>'
                      '<Cell><Data ss:Type="String">=literal</Data></Cell></Row>')
        cells, _ = reader.parse_range_xml(payload, ((" c03 ", '=A1&" "', " =literal "),),
                                         (15,5), (1,3), {(15,6)}, ((" c03 ", " text\t\n ", " =literal "),))
        self.assertEqual([cell[2] for cell in cells], [" c03 ", " text\t\n ", " =literal "])
        self.assertEqual(cells[1][4], '=A1&" "')
        self.assertIsNone(cells[2][4])

    def test_xml_and_bulk_string_types_must_agree(self):
        payload = xml('<Row><Cell><Data ss:Type="String">123</Data></Cell></Row>')
        with self.assertRaises(reader.NativeReadError):
            reader.parse_range_xml(payload, 123, (1,1), (1,1), set(), 123)


class NativeSafetyTests(unittest.TestCase):
    def test_force_disabled_readonly_no_save_no_macro_and_denial_partial(self):
        xw, app, blank, book = environment()
        owner = Mock()
        result = reader._native_snapshot(Path("fake.xlsm"), xw, owner)
        xw.App.assert_called_once_with(visible=False, add_book=False)
        owner.assert_called_once_with(123456)
        self.assertEqual(book.vba_reads, 1)
        self.assertEqual(result["extraction"]["status"], "access_denied")
        self.assertEqual(len(result["sheets"][0]["cells"]), 4)
        self.assertEqual(result["evidence"]["drm_status"], "not_determined")
        self.assertFalse(result["evidence"]["fresh_recalculation_verified"])
        book.Close.assert_called_once_with(SaveChanges=False)
        blank.Close.assert_called_once_with(SaveChanges=False)
        app.quit.assert_called_once()
        self.assertFalse(hasattr(app.api, "Run"))
        self.assertFalse(hasattr(book, "Save"))

    def test_open_failure_still_closes_only_owned_blank_and_app(self):
        xw, app, blank, book = environment(fail_open=True)
        with self.assertRaises(PermissionError):
            reader._native_snapshot(Path("blocked.xlsm"), xw, Mock())
        book.Close.assert_not_called()
        blank.Close.assert_called_once_with(SaveChanges=False)
        app.quit.assert_called_once()

    def test_range_limit_before_bulk_cell_read(self):
        xw, app, blank, book = environment()
        used = book.Worksheets.Item(1).UsedRange
        used.Rows.Count = 100_001
        with self.assertRaises(reader.NativeReadError):
            reader._native_snapshot(Path("big.xlsx"), xw, Mock())
        used._oleobj_.Invoke.assert_not_called()
        book.Close.assert_called_once_with(SaveChanges=False)

    def test_cumulative_limit_before_second_read(self):
        xw, _, _, book = environment()
        book.Worksheets.items.append(book.Worksheets.Item(1))
        with patch.object(reader, "MAX_CELLS", 5), self.assertRaises(reader.NativeReadError):
            reader._native_snapshot(Path("big.xlsx"), xw, Mock())
        self.assertEqual(book.Worksheets.Item(1).UsedRange._oleobj_.Invoke.call_count, 1)

    def test_owner_denied_never_opens_target(self):
        xw, app, _, book = environment()
        with self.assertRaises(PermissionError):
            reader._native_snapshot(Path("fake.xlsm"), xw, Mock(side_effect=PermissionError()))
        app.api.Workbooks.Open.assert_not_called()
        app.quit.assert_called_once()

    def test_tables_names_states_preserved(self):
        xw, _, _, book = environment(NativeBook(has_vba=False))
        sheet = book.Worksheets.Item(1)
        sheet.Visible = 2
        sheet.ListObjects = Collection([types.SimpleNamespace(Name="NativeTable", Range=types.SimpleNamespace(Address="$B$4:$C$5"),
                                                             ShowHeaders=True, ShowTotals=False)])
        book.Names = Collection([types.SimpleNamespace(Name="전역", RefersTo="='자료'!$B$5", Visible=True),
                                 types.SimpleNamespace(Name="'자료'!지역", RefersTo="='자료'!$C$5", Visible=False)])
        snapshot = reader._native_snapshot(Path("fake.xlsx"), xw, Mock())
        wb, cached, _, extraction, _ = reader.snapshot_to_workbooks(snapshot)
        self.assertEqual(wb["자료"].sheet_state, "veryHidden")
        self.assertEqual(wb["자료"].tables["NativeTable"].ref, "B4:C5")
        self.assertEqual(wb.defined_names["전역"].attr_text, "'자료'!$B$5")
        self.assertTrue(wb["자료"].defined_names["지역"].hidden)
        self.assertEqual(wb["자료"]["B5"].value, "001")
        self.assertEqual(wb["자료"]["C5"].data_type, "f")
        self.assertEqual(cached["자료"]["C5"].value, 3)
        self.assertEqual(extraction["status"], "no_vba")

    def test_optional_metadata_failure_reported(self):
        xw, _, _, book = environment()
        book.Worksheets.Item(1).ListObjects = None
        book.Names = None
        snapshot = reader._native_snapshot(Path("fake.xlsm"), xw, Mock())
        self.assertIn("sheet_1_tables", snapshot["evidence"]["incomplete_metadata"])
        self.assertIn("defined_names", snapshot["evidence"]["incomplete_metadata"])

    def test_old_binary_format_and_legacy_macro_sheet_rejected(self):
        xw, _, _, book = environment()
        book.FileFormat = 56
        with self.assertRaisesRegex(reader.NativeReadError, "실제 Excel 형식"):
            reader._native_snapshot(Path("renamed.xlsx"), xw, Mock())
        book.FileFormat = 52
        book.Worksheets.Item(1).Type = 3
        with self.assertRaisesRegex(reader.NativeReadError, "매크로"):
            reader._native_snapshot(Path("macro.xlsm"), xw, Mock())
        book.Worksheets.Item(1).UsedRange._oleobj_.Invoke.assert_not_called()

    def test_readonly_verification_required(self):
        xw, app, blank, book = environment()
        book.ReadOnly = False
        with self.assertRaises(reader.NativeReadError):
            reader._native_snapshot(Path("fake.xlsx"), xw, Mock())
        book.Close.assert_called_once_with(SaveChanges=False)
        app.quit.assert_called_once()

    def test_formula2_is_preferred_without_rewriting(self):
        xw, _, _, book = environment()
        used = book.Worksheets.Item(1).UsedRange
        used.Formula2 = (("ID", "값"), ("001", "=UNIQUE(A1:A3)"))
        result = reader._native_snapshot(Path("fake.xlsm"), xw, Mock())
        self.assertEqual(result["sheets"][0]["cells"][-1][4], "=UNIQUE(A1:A3)")
        self.assertFalse(any("formula2_unavailable" in note for note in result["evidence"]["incomplete_metadata"]))


class VbaTests(unittest.TestCase):
    def test_source_available_is_not_executed(self):
        source = "Sub Prepare()\nEnd Sub\n"
        code = types.SimpleNamespace(CountOfLines=2, Lines=Mock(return_value=source))
        component = types.SimpleNamespace(Name="Module1", Type=1, CodeModule=code)
        book = types.SimpleNamespace(HasVBProject=True, VBProject=types.SimpleNamespace(
            Protection=0, VBComponents=Collection([component])))
        result = reader._vba(book)
        self.assertEqual(result["status"], "extracted")
        self.assertFalse(result["macro_executed"])
        self.assertEqual(result["modules"][0]["source_sha256"], hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(result["modules"][0]["relative_path"], "modules/001_Module1.bas")

    def test_locked_vba_and_limit_drop_all_partial_source(self):
        book = types.SimpleNamespace(HasVBProject=True, VBProject=types.SimpleNamespace(Protection=1))
        self.assertEqual(reader._vba(book)["status"], "access_denied")
        book.VBProject = types.SimpleNamespace(Protection=0, VBComponents=Collection([None]*65))
        self.assertEqual(reader._vba(book)["status"], "limit_exceeded")
        self.assertEqual(reader._vba(book)["modules"], [])

    def test_vba_source_budget_stops_chunk_reads(self):
        code = types.SimpleNamespace(CountOfLines=3000, Lines=Mock(return_value="x"*100))
        book = types.SimpleNamespace(HasVBProject=True, VBProject=types.SimpleNamespace(Protection=0,
            VBComponents=Collection([types.SimpleNamespace(Name="M", Type=1, CodeModule=code)])))
        with patch.object(reader, "MAX_MODULE_SOURCE", 50):
            result = reader._vba(book)
        self.assertEqual(result["status"], "limit_exceeded")
        self.assertEqual(result["modules"], [])
        code.Lines.assert_called_once_with(1, 1000)


class NormalizationTests(unittest.TestCase):
    def test_elapsed_time_uses_value2_and_matches_direct_reader_contract(self):
        from excel_pipeline import safe_value
        from project_builder import value_kind
        from project_runtime import _decode
        styles = '<Style ss:ID="duration"><NumberFormat ss:Format="[h]:mm:ss"/></Style>'
        for xml_type, text in (("Number", "1.0833333333333333"), ("DateTime", "1899-12-31T02:00:00.000")):
            for observed in (26 / 24, dt.timedelta(hours=26)):
                with self.subTest(xml_type=xml_type, observed=observed):
                    document = xml(f'<Row><Cell ss:StyleID="duration"><Data ss:Type="{xml_type}">{text}</Data></Cell></Row>', styles)
                    cells, merges = reader.parse_range_xml(document, observed, (1, 1), (1, 1), values=observed)
                    snapshot = {"date1904": False, "sheets": [{"name": "S", "state": "visible", "tables": [], "merges": merges, "cells": cells}],
                                "names": [], "features": [], "extraction": {"status": "no_vba"}, "evidence": {}}
                    # Child/parent JSON transport must retain the serial, not a Python object.
                    wb, cached, *_ = reader.snapshot_to_workbooks(json.loads(json.dumps(snapshot)))
                    cell = wb["S"]["A1"]
                    self.assertEqual(dt.timedelta(hours=26), cell.value)
                    self.assertEqual(cell.value, cached["S"]["A1"].value)
                    value = safe_value(cell.value)
                    kind = value_kind({"value": value, "type": cell.data_type, "number_format": cell.number_format})
                    self.assertEqual(("26:00:00", "duration"), (value, kind))
                    self.assertEqual(cell.value, _decode(value, {"kind": kind}))
                    wb.close()
                    cached.close()

    def test_elapsed_datetime_without_serial_does_not_guess_lost_days(self):
        document = xml('<Row><Cell ss:StyleID="duration"><Data ss:Type="DateTime">1899-12-31T02:00:00.000</Data></Cell></Row>',
                       '<Style ss:ID="duration"><NumberFormat ss:Format="[h]:mm:ss"/></Style>')
        for observed in (None, dt.time(2), dt.datetime(1899, 12, 31, 2)):
            with self.subTest(observed=observed), self.assertRaises(reader.NativeReadError) as failure:
                reader.parse_range_xml(document, None, (1, 1), (1, 1), values=observed)
            self.assertEqual("native_duration_unavailable", failure.exception.code)

    def test_elapsed_numeric_xml_can_use_its_own_serial_without_value2(self):
        document = xml('<Row><Cell ss:StyleID="duration"><Data ss:Type="Number">-2.125</Data></Cell></Row>',
                       '<Style ss:ID="duration"><NumberFormat ss:Format="[h]:mm:ss"/></Style>')
        cells, _ = reader.parse_range_xml(document, None, (1, 1), (1, 1))
        self.assertEqual((-2.125, "n"), tuple(cells[0][2:4]))

    def test_literal_equals_dates_errors_epoch_in_memory_only(self):
        snapshot = {"date1904": True, "sheets": [{"name": "S", "state": "visible", "tables": [], "merges": [],
                      "cells": [[1, 1, "=literal", "s", None, "General"],
                                [1, 2, "2026-10-14T00:00:00", "d", None, "yyyy-mm-dd"],
                                [1, 3, "#N/A", "e", None, "General"], [2, 1, 0, "n", None, "0000"]]}],
                    "names": [], "features": [], "extraction": {"status": "no_vba"}, "evidence": {}}
        with patch.object(reader.openpyxl.Workbook, "save", side_effect=AssertionError("No workbook copy")):
            wb, cached, *_ = reader.snapshot_to_workbooks(snapshot)
        self.assertEqual(wb["S"]["A1"].data_type, "s")
        self.assertEqual(wb["S"]["B1"].value, dt.datetime(2026, 10, 14))
        self.assertEqual(wb["S"]["C1"].data_type, "e")
        self.assertEqual(wb["S"]["A2"].number_format, "0000")
        self.assertEqual(wb.epoch.year, 1904)
        self.assertEqual(cached.epoch, wb.epoch)

    def test_child_missing_dependency_report_has_no_native_side_effects(self):
        import builtins
        original = builtins.__import__
        def missing(name, *args, **kwargs):
            if name == "xlwings":
                raise ImportError()
            return original(name, *args, **kwargs)
        output = io.StringIO()
        with patch("builtins.__import__", side_effect=missing), patch("sys.stdout", output):
            reader._worker("anything.xlsx")
        result = json.loads(output.getvalue())
        self.assertEqual(result["code"], "xlwings_missing")


class ParentWorkerTests(unittest.TestCase):
    def snapshot(self):
        xw, _, _, _ = environment()
        return reader._native_snapshot(Path("fake.xlsm"), xw, Mock())

    def process(self, payload):
        return types.SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO(payload),
                                     poll=Mock(return_value=0), kill=Mock(), wait=Mock(return_value=0))

    def test_worker_ownership_handshake_and_cleanup(self):
        payload = (json.dumps({"kind": "owner", "pid": 98765}) + "\n" +
                   json.dumps({"kind": "result", "snapshot": self.snapshot()})).encode()
        proc = self.process(payload)
        owner = Mock()
        owner.close.return_value = False
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as folder:
            source = Path(folder)/"fake.xlsx"
            source.touch()
            with patch.object(reader, "_process_ids", return_value={12}), \
                 patch.object(reader, "_OwnedProcess", return_value=owner) as ownership, \
                 patch.object(reader.subprocess, "Popen", return_value=proc):
                result = reader.load_via_excel(source, 2)
        self.assertEqual(ownership.call_args.args[0], 98765)
        self.assertEqual(ownership.call_args.args[1], {12})
        owner.close.assert_called_once()
        self.assertFalse(result[-1]["owned_excel_forced_cleanup"])
        proc.kill.assert_not_called()

    def test_oversized_output_cleans_only_held_owner(self):
        payload = (json.dumps({"kind": "owner", "pid": 98765}) + "\n" + "x"*100).encode()
        proc = self.process(payload)
        owner = Mock()
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as folder:
            source = Path(folder)/"fake.xlsx"
            source.touch()
            with patch.object(reader, "_process_ids", return_value=set()), \
                 patch.object(reader, "_OwnedProcess", return_value=owner), \
                 patch.object(reader.subprocess, "Popen", return_value=proc), \
                 patch.object(reader, "MAX_OUTPUT", 40), self.assertRaises(reader.NativeReadError):
                reader.load_via_excel(source, 2)
        owner.close.assert_called_once()

    def test_timeout_kills_worker_then_only_held_excel_handle(self):
        release = threading.Event()
        class Stream:
            first = True
            def read1(self, size):
                if self.first:
                    self.first = False
                    return b'{"kind":"owner","pid":98765}\n'
                release.wait(5)
                return b""
            def close(self):
                pass
        proc = self.process(b"")
        proc.stdout = Stream()
        proc.poll.return_value = None
        proc.kill.side_effect = release.set
        owner = Mock()
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as folder:
            source = Path(folder)/"fake.xlsx"
            source.touch()
            with patch.object(reader, "_process_ids", return_value=set()), \
                 patch.object(reader, "_OwnedProcess", return_value=owner), \
                 patch.object(reader.subprocess, "Popen", return_value=proc), \
                 self.assertRaisesRegex(reader.NativeReadError, "제한 시간"):
                reader.load_via_excel(source, 1)
        proc.kill.assert_called_once()
        owner.close.assert_called_once()

    def test_invalid_timeout_never_starts_worker(self):
        with patch.object(reader.subprocess, "Popen") as popen, self.assertRaises(reader.NativeReadError):
            reader.load_via_excel(Path("fake.xlsx"), float("nan"))
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
