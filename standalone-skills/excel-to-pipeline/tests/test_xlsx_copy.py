"""선택 XLSX의 원천 셀, 수식 원문과 자료형을 파일 왕복으로 검사합니다."""
import datetime as dt
import hashlib
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import openpyxl
from openpyxl.workbook.defined_name import DefinedName

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from excel_pipeline import analyze, main
from xlsx_copy import prepare_copy, write_copy, CopySelectionError


class CopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / '원본.xlsx'

    def tearDown(self):
        self.temp.cleanup()

    def source_result(self, expression='=SUM(입력!B2:B4)'):
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = '결과'
        ws.append(['항목', '결과']); ws.append(['필요값', expression])
        ws['Z300'].number_format = '0.00'
        data = wb.create_sheet('입력'); data.append(['코드', '금액', '별도업무'])
        for row in [('001a', 2, 999), ('c02', 3, 999), ('D03', 5, 999)]: data.append(row)
        wb.create_sheet('관계없는업무')['A1'] = '사본에는 필요 없음'
        wb.save(self.source); wb.close()
        return analyze(self.source)

    def test_static_dependencies_drop_unrelated_data_preserve_coordinates(self):
        result = self.source_result(); before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        prepared = prepare_copy(result, ['결과!A1:B2'])
        receipt = write_copy(prepared, self.root/'선택.xlsx')
        wb = openpyxl.load_workbook(receipt['path'])
        self.assertEqual(wb.sheetnames, ['결과', '입력'])
        self.assertEqual(wb['결과']['B2'].value, '=SUM(입력!B2:B4)')
        self.assertEqual([wb['입력'].cell(r, 2).value for r in range(2, 5)], [2, 3, 5])
        self.assertIsNone(wb['입력']['C2'].value)
        self.assertEqual(wb['결과'].max_row, 2)
        self.assertFalse(receipt['cached_formula_values_copied'])
        self.assertEqual(wb.calculation.calcMode, 'manual'); wb.close()
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)

    def test_broken_refs_and_external_formula_remain_visible_without_claimed_repair(self):
        for expression in ["='입력'!#REF!", "=SUMIF('입력'!A2:A4,A2,'입력'!#REF!)", "='D:/backup/[missing.xlsx]Sheet1'!A1"]:
            with self.subTest(expression=expression):
                result = self.source_result(expression)
                prepared = prepare_copy(result, ['결과!A1:B2'])
                self.assertTrue(prepared['receipt']['warnings'])
                dest = self.root / ('copy'+str(len(list(self.root.glob('copy*.xlsx'))))+'.xlsx')
                write_copy(prepared, dest)
                wb = openpyxl.load_workbook(dest)
                self.assertEqual(wb['결과']['B2'].value, expression); wb.close()

    def test_static_unknown_calculation_keeps_input_but_dynamic_or_udf_does_not_guess(self):
        result = self.source_result('=INDEX(입력!B2:B4,MATCH(3,입력!B2:B4,0))')
        prepared = prepare_copy(result, ['결과!B2'])
        self.assertEqual(prepared['receipt']['kept_cell_count'], 6)
        for expression in ['=INDIRECT("입력!B2")', '=OFFSET(입력!A1,1,1)', '=PrivateFunction(입력!B2)', '=Table1[금액]', '=SUBTOTAL(109,입력!B2:B4)', '=GETPIVOTDATA("금액",입력!B2)']:
            with self.subTest(expression=expression):
                with self.assertRaises(CopySelectionError):
                    prepare_copy(self.source_result(expression), ['결과!B2'])

    def test_full_column_reference_copies_only_populated_cells(self):
        prepared = prepare_copy(self.source_result('=SUM(입력!B:B)'), ['결과!B2'])
        self.assertEqual(prepared['receipt']['kept_cell_count'], 6)

    def test_python_selection_shares_current_analysis_budget(self):
        from project_selection import select_result
        result = self.source_result()
        with patch('excel_pipeline.MAX_CELLS', 2), self.assertRaisesRegex(ValueError, '분석 한도'):
            select_result(result, ['결과!B2'])
        self.assertTrue(select_result(result, ['결과!B2'])['source_cells'])

    def test_named_range_keeps_its_definition_and_precedents(self):
        self.source_result()
        wb = openpyxl.load_workbook(self.source)
        wb.defined_names.add(DefinedName('선택금액', attr_text="'입력'!$B$2:$B$4"))
        wb['결과']['B2'] = '=SUM(선택금액)'; wb.save(self.source); wb.close()
        result = analyze(self.source)
        prepared = prepare_copy(result, ['결과!B2'])
        receipt = write_copy(prepared, self.root/'이름.xlsx')
        wb = openpyxl.load_workbook(receipt['path'])
        self.assertEqual(wb.defined_names['선택금액'].attr_text, "'입력'!$B$2:$B$4")
        self.assertEqual(wb['입력']['B4'].value, 5); wb.close()

    def test_values_dates_durations_errors_and_formula_like_text_roundtrip(self):
        wb = openpyxl.Workbook(); ws = wb.active
        ws['A1'] = '001a'; ws['A2'] = '=keep as text'; ws['A2'].data_type = 's'
        ws['A3'] = dt.datetime(2026, 11, 5); ws['A4'] = dt.timedelta(hours=26); ws['A4'].number_format='[h]:mm:ss'
        ws['A5'] = '#REF!'; ws['A5'].data_type='e'; ws['A6']=False
        wb.save(self.source); wb.close()
        receipt = write_copy(prepare_copy(analyze(self.source)), self.root/'종류.xlsx')
        wb = openpyxl.load_workbook(receipt['path']); ws=wb.active
        self.assertEqual(ws['A1'].value, '001a'); self.assertEqual(ws['A2'].data_type, 's')
        self.assertEqual(ws['A3'].value, dt.datetime(2026, 11, 5))
        self.assertEqual(ws['A4'].value, dt.timedelta(hours=26))
        self.assertEqual(ws['A5'].data_type, 'e'); self.assertEqual(receipt['literal_error_counts'], {'#REF!':1})
        self.assertIs(ws['A6'].value, False); wb.close()

    def test_does_not_overwrite_original_or_existing_output(self):
        prepared = prepare_copy(self.source_result())
        before = self.source.read_bytes()
        with self.assertRaises(CopySelectionError): write_copy(prepared, self.source)
        self.assertEqual(self.source.read_bytes(), before)
        with self.assertRaises(CopySelectionError): write_copy(prepared, self.root/'wrong.xlsm')

    def test_full_copy_keeps_empty_sheet_references_and_reports_missing_metadata(self):
        self.source_result('=SUM(Table1[금액])')
        wb = openpyxl.load_workbook(self.source)
        wb.create_sheet('빈시트')
        wb.defined_names.add(DefinedName('미래입력', attr_text="'빈시트'!$A$1"))
        wb.save(self.source); wb.close()
        prepared = prepare_copy(analyze(self.source))
        self.assertIn('빈시트', prepared['sheets'])
        self.assertIn('structured_or_spill_metadata_not_copied', prepared['receipt']['warnings'])
        receipt = write_copy(prepared, self.root/'모두.xlsx')
        wb = openpyxl.load_workbook(receipt['path'])
        self.assertEqual(wb.defined_names['미래입력'].attr_text, "'빈시트'!$A$1")
        self.assertIn('빈시트', wb.sheetnames); wb.close()

    def test_empty_targets_and_three_dimensional_references_are_not_silent_success(self):
        result=self.source_result()
        with self.assertRaises(CopySelectionError): prepare_copy(result, ['결과!K9:K10'])
        with self.assertRaises(CopySelectionError): prepare_copy(self.source_result('=SUM(결과:입력!B2)'), ['결과!B2'])

    def test_cli_emits_copy_and_project_from_one_analysis_without_extra_model_calls(self):
        result = self.source_result()
        output = self.root/'한번분석'
        capture=io.StringIO()
        with patch('excel_pipeline.analyze', return_value=result) as read, contextlib.redirect_stdout(capture):
            code = main([str(self.source), '--output', str(output), '--xlsx-copy', '--copy-target', '결과!A1:B2'])
        self.assertEqual(code, 0); read.assert_called_once()
        receipt = json.loads(capture.getvalue())
        self.assertEqual(receipt['model_calls'], 0)
        self.assertTrue((output/'필요자료.xlsx').is_file())
        self.assertTrue((output/'main.py').is_file())
        self.assertTrue((output/'_support/xlsx_copy.py').is_file())
        self.assertLess(receipt['xlsx_copy']['kept_cell_count'], receipt['xlsx_copy']['source_cell_count'])

    def test_invalid_copy_selection_does_not_publish_a_partial_project(self):
        result = self.source_result('=INDIRECT("입력!B2")')
        output=self.root/'생성안함'
        with patch('excel_pipeline.analyze', return_value=result), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(self.source), '--output', str(output), '--copy-target', '결과!B2']), 2)
        self.assertFalse(output.exists())


if __name__ == '__main__': unittest.main()
