import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import excel_xlwings as excel, office_reader as reader


class ExcelRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / '한글.xlsx'
        self.file.write_bytes(b'fixture')
        self.request = reader.normalize({'file': str(self.file)})
        self.frame = pd.DataFrame([['항목', '실적'], ['매출', 123]])
        self.selected = Mock(row=1, column=1)
        self.selected.rows.count = 2
        self.selected.columns.count = 2
        self.selected.options.return_value.value = self.frame
        self.sheet = Mock()
        self.sheet.name = '실적'
        self.sheet.used_range = self.selected
        self.sheet.range.return_value = self.selected
        self.book = Mock(api=NS(Permission=None), sheets=[self.sheet])
        self.scratch = Mock()
        self.books = Mock()
        self.books.add.return_value = self.scratch
        self.books.open.return_value = self.book
        # __len__ is deliberately observable for ownership-aware cleanup.
        self.books = type('Books', (), {
            'add': self.books.add, 'open': self.books.open,
            '__len__': lambda obj: self.remaining_books})()
        self.remaining_books = 0
        self.app = Mock(api=NS(), books=self.books)
        self.xw = Mock()
        self.xw.App.return_value = self.app

    def test_fixed_recipe_preserves_first_row_column_and_korean(self):
        result = excel._read(self.request, self.xw, pd)
        self.assertTrue(result['ok'], result)
        self.assertEqual(['항목', '실적', '매출', '123'], [i['text'] for i in result['items']])
        self.assertEqual(['R1C1', 'R1C2', 'R2C1', 'R2C2'], [i['location'] for i in result['items']])
        self.xw.App.assert_called_once_with(visible=False, add_book=False)
        self.xw.Book.assert_not_called()
        self.books.open.assert_called_once_with(str(self.file), read_only=True, update_links=False, add_to_mru=False)
        self.selected.options.assert_called_once_with(pd.DataFrame, header=False, index=False)
        self.assertEqual(3, self.app.api.AutomationSecurity)
        self.assertEqual('manual', self.app.calculation)
        self.book.close.assert_called_once_with()
        self.scratch.close.assert_called_once_with()
        self.app.quit.assert_called_once_with()
        self.app.kill.assert_not_called()
        self.assertEqual('unavailable', result['coverage']['officePermissionApi'])
        self.assertEqual('not_determined', result['coverage']['thirdPartyDrmAuthorization'])

    def test_does_not_quit_instance_with_other_books(self):
        self.remaining_books = 1
        self.assertTrue(excel._read(self.request, self.xw, pd)['ok'])
        self.app.quit.assert_not_called()
        self.app.kill.assert_not_called()

    def test_restriction_stops_before_read(self):
        self.book.api.Permission = NS(Enabled=True)
        result = excel._read(self.request, self.xw, pd)
        self.assertEqual('protected_input', result['code'])
        self.selected.options.assert_not_called()
        self.book.close.assert_called_once_with()

    def test_open_denial_no_fallback_or_raw_error(self):
        self.books.open.side_effect = PermissionError('private contents must not leak')
        result = excel._read(self.request, self.xw, pd)
        self.assertEqual({'ok': False, 'code': 'permission_denied', 'stage': 'open'}, result)
        self.selected.options.assert_not_called()
        self.xw.Book.assert_not_called()

    def test_read_denial_discards_contents(self):
        self.selected.options.side_effect = PermissionError('secret text')
        result = excel._read(self.request, self.xw, pd)
        self.assertEqual('permission_denied', result['code'])
        self.assertNotIn('items', result)
        self.assertNotIn('secret', json.dumps(result))

    def test_optional_api_failure_is_distinct_from_access_denial(self):
        class Api:
            @property
            def Permission(self):
                raise failure
        self.book.api = Api()
        failure = Exception('optional IRM is not installed')
        failure.hresult = -2147467259
        self.assertEqual('unavailable', excel.permission_status(self.book))
        failure = PermissionError('access denied')
        self.assertEqual('denied', excel.permission_status(self.book))
        failure = RuntimeError('unexpected problem')
        with self.assertRaises(RuntimeError):
            excel.permission_status(self.book)

    def test_used_range_is_bounded_before_dataframe_conversion(self):
        self.selected.rows.count = 10000
        self.selected.columns.count = 200
        cropped = Mock()
        cropped.options.return_value.value = pd.DataFrame([[None] * 20 for _ in range(100)])
        self.sheet.range.return_value = cropped
        result = excel._read(self.request, self.xw, pd)
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['truncated'])
        self.sheet.range.assert_called_once_with((1, 1), (100, 20))
        self.selected.options.assert_not_called()
        self.assertEqual(100, result['coverage']['rows'])

    def test_character_limit_and_named_sheet(self):
        self.book.sheets = {'실적': self.sheet}
        result = excel._read({**self.request, 'sheet': '실적', 'maxChars': 3}, self.xw, pd)
        self.assertTrue(result['ok'])
        self.assertTrue(result['truncated'])
        self.assertEqual(3, sum(len(i['text']) for i in result['items']))

    def test_dependency_failure_does_not_launch_any_reader(self):
        with patch.object(excel.importlib, 'import_module', side_effect=ImportError), patch.object(excel, '_read') as read:
            result = excel.read_excel(self.request)
        self.assertEqual('excel_dependencies_missing', result['code'])
        read.assert_not_called()

    def test_actual_isolated_entrypoint_rejects_extra_commands(self):
        proc = subprocess.run([sys.executable, '-E', '-P', str(ROOT / 'company-agent-plugin/scripts/Read-CompanyExcel.py')],
                              input=b'{"command":"do not run"}', capture_output=True, timeout=10)
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual('invalid_request', json.loads(proc.stdout)['code'])

    def test_powerpoint_keeps_its_separate_reader(self):
        file = self.file.with_suffix('.pptx')
        file.write_bytes(b'fixture')
        proc = subprocess.CompletedProcess([], 0, b'{"ok":false,"code":"office_read_failed"}', b'')
        with patch.object(reader, 'run_helper', return_value=proc) as run:
            reader._invoke(reader.normalize({'file': str(file)}))
        self.assertTrue(run.call_args.args[0][-1].endswith('Read-CompanyOffice.py'))


if __name__ == '__main__':
    unittest.main()
