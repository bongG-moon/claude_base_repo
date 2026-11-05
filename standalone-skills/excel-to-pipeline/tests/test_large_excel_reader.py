"""Large and formatting-heavy reads use bounded COM blocks, not per-cell work."""
from collections import Counter
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from xml.sax.saxutils import escape
import zipfile

import openpyxl
from openpyxl.utils.cell import range_boundaries

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import excel_pipeline as pipeline
import xlwings_reader as reader
from test_xlwings_reader import Collection, NativeBook, environment, xml


class FakeRange:
    def __init__(self, sheet, top, left, bottom, right):
        self.sheet=sheet; self.Row=top; self.Column=left
        self.Rows=types.SimpleNamespace(Count=bottom-top+1)
        self.Columns=types.SimpleNamespace(Count=right-left+1)
        self._oleobj_=types.SimpleNamespace(Invoke=self.document)

    @property
    def HasFormula(self):
        return False

    @property
    def Formula2(self):
        self.sheet.calls['formula']+=1
        return self.matrix()

    @property
    def Value2(self):
        self.sheet.calls['value']+=1
        return self.matrix()

    def matrix(self):
        rows,cols=self.Rows.Count,self.Columns.Count
        result=tuple(tuple(1 if r==c==0 else None for c in range(cols)) for r in range(rows))
        return result[0][0] if rows==cols==1 else result

    def document(self,*args):
        self.sheet.calls['xml']+=1
        self.sheet.areas.append(self.Rows.Count*self.Columns.Count)
        merge=f' ss:MergeDown="{min(3,self.Rows.Count-1)}"' if self.sheet.crossing and self.Row==1 else ''
        return xml(f'<Row><Cell{merge}><Data ss:Type="Number">1</Data></Cell></Row>')

    @property
    def MergeArea(self):
        assert self.sheet.crossing and self.Row==1
        return types.SimpleNamespace(Address='$A$1:$A$4')


class FakeSheet:
    def __init__(self,name,rows,cols,formatted=None,crossing=False):
        self.Name=name; self.Visible=-1; self.Type=-4167
        self.calls=Counter(); self.areas=[]; self.crossing=crossing
        self.rows=rows;self.cols=cols
        self.UsedRange=FakeRange(self,1,1,*(formatted or (rows,cols)))
        self.Cells=types.SimpleNamespace(Find=self.find)
        self.ListObjects=Collection([]);self.QueryTables=Collection([])
        self.PivotTables=lambda:Collection([])

    def Range(self,address):
        left,top,right,bottom=range_boundaries(address)
        return FakeRange(self,top,left,bottom,right)

    def find(self,**kwargs):
        self.calls['find']+=1
        assert kwargs['LookIn']==-4123 and kwargs['SearchFormat'] is False
        assert 'After' in kwargs
        last=kwargs['SearchDirection']==2
        return types.SimpleNamespace(Row=self.rows if last else 1,Column=self.cols if last else 1)


class LargeNativeReadTests(unittest.TestCase):
    def snapshot(self,sheets):
        book=NativeBook(has_vba=False)
        book.Worksheets=Collection(sheets);book.Sheets=book.Worksheets
        xw,_,_,_=environment(book)
        return reader._native_snapshot(Path('synthetic.xlsx'),xw,Mock())

    def test_reported_nine_sheet_dimensions_read_without_old_250k_stop(self):
        sizes=[(84,81),(554,49),(576,145),(70,58),(1471,133),(637,142),(1336,179),(1641,204),(1265,67)]
        sheets=[FakeSheet(f'S{i}',r,c) for i,(r,c) in enumerate(sizes)]
        result=self.snapshot(sheets)
        expected=sum(r*c for r,c in sizes)
        self.assertGreater(expected,1_000_000)
        self.assertEqual(result['evidence']['scanned_cells'],expected)
        self.assertTrue(result['evidence']['complete_cell_read'])
        self.assertEqual(len(result['evidence']['sheet_inventory']),9)
        for s in sheets:
            self.assertEqual(s.calls['find'],4)
            self.assertEqual(s.calls['xml'],s.calls['formula'])
            self.assertEqual(s.calls['xml'],s.calls['value'])
            self.assertLessEqual(max(s.areas),reader.CHUNK_CELLS)
        self.assertLess(sum(s.calls['xml'] for s in sheets),60)
        self.assertEqual(result['evidence']['per_cell_value_formula_reads'],0)

    def test_blank_formatting_does_not_force_million_cell_read(self):
        s=FakeSheet('자료',3,4,formatted=(1048576,16384))
        result=self.snapshot([s]); evidence=result['evidence']['sheet_inventory'][0]
        self.assertEqual(evidence['scanned_cells'],12)
        self.assertEqual(evidence['original_used_range']['rows'],1048576)
        self.assertEqual(s.calls['xml'],1)

    def test_row_block_extends_once_for_cross_boundary_merge(self):
        s=FakeSheet('병합',6,2,crossing=True)
        with patch.object(reader,'CHUNK_CELLS',4): result=self.snapshot([s])
        self.assertEqual(result['sheets'][0]['merges'],['A1:A4'])
        self.assertEqual(result['evidence']['scanned_cells'],12)
        self.assertEqual(s.calls['xml'],3)
        self.assertEqual(s.calls['formula'],2)
        self.assertEqual(result['evidence']['boundary_merge_checks'],2)

    def test_more_than_new_limit_stops_before_any_value_read(self):
        s=FakeSheet('과대',5000,500)
        with self.assertRaises(reader.NativeReadError): self.snapshot([s])
        self.assertEqual(s.calls['xml'],0)


class DiagnosticTests(unittest.TestCase):
    def test_errors_do_not_imply_external_missing_or_readable_formula(self):
        wb=openpyxl.Workbook();ws=wb.active;ws.title='오류'
        cache=openpyxl.Workbook().active
        ws['A1']="='원본'!#REF!";cache['A1']='#REF!'
        ws['A2']='#REF!';cache['A2']='#REF!'
        ws['A3']='=1+"x"';cache['A3']='#VALUE!'
        ws['A4']="='[이전.xlsx]자료'!A1";cache['A4']=3
        ws['A5']='="#REF! [not.xlsx]Sheet!A1"';cache['A5']='#REF! [not.xlsx]Sheet!A1'
        formulas=[{'sheet':'오류','cell':cell.coordinate,'formula':cell.value} for row in ws for cell in row if cell.data_type=='f']
        result=pipeline.sheet_error_summary(ws,cache,formulas)
        self.assertEqual(result['error_counts'],{'#REF!':2,'#VALUE!':1})
        self.assertEqual(result['formula_error_cells'],2)
        self.assertEqual(result['literal_error_cells'],1)
        self.assertEqual(result['broken_reference_formula_count'],1)
        self.assertEqual(result['external_reference_formula_count'],1)
        self.assertFalse(result['error_examples'][1]['formula_observed'])
        self.assertIn('확인하지 않았습니다',result['diagnosis'][1])

    def test_normal_ooxml_above_250k_material_cells_passes_preflight(self):
        # A compressed small fixture proves the old limit is gone without
        # allocating two full Excel workbooks in the ordinary unit test run.
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path=Path(folder)/'large.xlsx'
            rows=''.join('<row r="%d">'%r+''.join(f'<c r="{openpyxl.utils.get_column_letter(c)}{r}"><v>1</v></c>' for c in range(1,252))+'</row>' for r in range(1,1001))
            with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('xl/workbook.xml','<workbook/>')
                z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:IQ1000"/><sheetData>'+rows+'</sheetData></worksheet>')
            self.assertEqual(pipeline.preflight(path),[])
            with patch.object(pipeline,'MAX_CELLS',250_000),self.assertRaises(pipeline.InputError):pipeline.preflight(path)


if __name__=='__main__':unittest.main()
