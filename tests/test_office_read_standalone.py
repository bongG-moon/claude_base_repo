import contextlib
import io
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import office_read_test as testkit


class StandaloneReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def make_pdf(self, encrypted=False, text=False):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=200, height=200)
        if text:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                     NameObject('/Subtype'): NameObject('/Type1'),
                                     NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
            stream = DecodedStreamObject()
            stream.set_data(b'BT /F1 12 Tf 20 100 Td (TEST 123) Tj ET')
            page[NameObject('/Contents')] = stream
        if encrypted: writer.encrypt('fixture-password')
        path = self.folder / ('protected.pdf' if encrypted else 'sample.pdf')
        with path.open('wb') as target: writer.write(target)
        return path

    def test_pdf_actual_text_through_spawn_keeps_source(self):
        path = self.make_pdf(text=True)
        before = path.read_bytes()
        result = testkit.run_test(path, timeout=20)
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['opened'])
        self.assertIn('TEST 123', str(result['parts']))
        self.assertTrue(result['sourceUnchanged'])
        self.assertEqual(before, path.read_bytes())

    def test_encrypted_pdf_stops_without_text(self):
        result = testkit.read_once(self.make_pdf(encrypted=True))
        self.assertFalse(result['ok'])
        self.assertTrue(result['opened'])
        self.assertNotIn('parts', result)
        self.assertIn('암호', result['message'])

    def test_blank_pdf_is_not_misrepresented_as_content(self):
        result = testkit.read_once(self.make_pdf())
        output = io.StringIO()
        with contextlib.redirect_stdout(output): testkit.show(result)
        self.assertTrue(result['ok'])
        self.assertEqual([], result['parts'])
        self.assertIn('글자가 반환되지 않았습니다', output.getvalue())

    def test_missing_module_no_office_open(self):
        path = self.folder / 'file.xlsx'
        path.write_bytes(b'fixture')
        with patch.object(testkit.importlib, 'import_module', side_effect=ModuleNotFoundError(name='xlwings')), \
                patch.object(testkit, 'read_excel') as reader:
            result = testkit.read_once(path)
        self.assertFalse(result['ok'])
        self.assertFalse(result['opened'])
        self.assertIn('xlwings', result['message'])
        reader.assert_not_called()

    def test_known_restriction_blocks(self):
        with self.assertRaises(testkit.StopRead):
            testkit.check_permission(NS(Permission=NS(Enabled=True)))
        self.assertIn('미제공', testkit.check_permission(NS(Permission=None)))

    def test_actual_denial_not_treated_as_api_missing(self):
        class Document:
            @property
            def Permission(self): raise PermissionError('secret')
        with self.assertRaises(testkit.StopRead): testkit.check_permission(Document())

    def test_partial_read_failure_drops_contents(self):
        path = self.folder / 'file.docx'
        path.write_bytes(b'fixture')
        def fail(path, kind, preview, result):
            preview.add('paragraph', 'private source')
            result['opened'] = True
            raise PermissionError('private source')
        with patch.object(testkit.importlib, 'import_module'), patch.object(testkit, 'read_office', side_effect=fail):
            result = testkit.read_once(path)
        self.assertFalse(result['ok'])
        self.assertNotIn('private source', str(result))
        self.assertNotIn('parts', result)

    def test_empty_cells_and_text_have_limits(self):
        preview = testkit.Preview()
        for _ in range(2100): preview.add('cell', '')
        self.assertEqual(2000, preview.visited)
        self.assertTrue(preview.truncated)
        preview = testkit.Preview()
        preview.add('cell', '가' * 4000)
        self.assertEqual(3000, len(preview.parts[0][1]))
        self.assertTrue(preview.truncated)

    def test_path_quotes_and_unsupported_extension(self):
        path = self.make_pdf()
        self.assertEqual(path.resolve(), testkit.resolve_source(f'"{path}"'))
        bad = self.folder / 'file.exe'; bad.write_bytes(b'fixture')
        with self.assertRaises(ValueError): testkit.resolve_source(str(bad))

    def test_single_copied_file_cli_works_without_harness(self):
        import shutil
        path = self.make_pdf(text=True)
        script = self.folder / 'office_read_test.py'
        shutil.copyfile(ROOT / 'scripts/office_read_test.py', script)
        result = subprocess.run([sys.executable, str(script), str(path)], input='y\n',
                                capture_output=True, text=True, encoding='utf-8', timeout=20,
                                cwd=self.folder, env={**__import__('os').environ, 'PYTHONIOENCODING':'cp949:strict', 'PYTHONUTF8':'0'})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('TEST 123', result.stdout)
        self.assertIn('원본 바이트: 유지', result.stdout)


if __name__ == '__main__': unittest.main()
