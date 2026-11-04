"""Exercise default artifact locations without touching personal profiles."""
from contextlib import chdir, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business_artifacts


def load(slug, script):
    spec = importlib.util.spec_from_file_location(slug.replace('-', '_'), ROOT / 'standalone-skills' / slug / 'scripts' / script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OutputFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def cli(self, slug, script, *args):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT / 'standalone-skills' / slug / 'scripts' / script), *map(str, args)], cwd=self.root, capture_output=True, text=True, encoding='utf-8', timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_catalog_default_and_explicit_nested_target(self):
        inputs = self.root / 'inputs'
        inputs.mkdir()
        (inputs / 'SKILL.md').write_text('---\nname: daily-work\n---\n# 일일 현황 정리\n자료를 읽고 현황을 집계합니다.', encoding='utf-8')
        self.cli('work-context-catalog', 'work_catalog.py', '--root', inputs, '--no-sessions')
        pages = list((self.root / 'work-context-catalog/outputs').glob('*/업무현황.html'))
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].with_name('업무자산.md').exists())
        explicit = self.root / 'chosen/nested/report'
        self.cli('work-context-catalog', 'work_catalog.py', '--root', inputs, '--no-sessions', '--output', explicit)
        self.assertTrue((explicit / '업무현황.html').exists())
        self.assertFalse((self.root / 'catalog.json').exists())

    def test_excel_default_is_executable_project_and_inspect_writes_nothing(self):
        import openpyxl
        workbook = openpyxl.Workbook()
        workbook.active.append(['상품', '수량'])
        workbook.active.append(['A', 3])
        source = self.root / 'input.xlsx'
        workbook.save(source)
        self.cli('excel-to-pipeline', 'excel_pipeline.py', source, '--context-only')
        self.assertFalse((self.root / 'excel-to-pipeline').exists())
        result = self.cli('excel-to-pipeline', 'excel_pipeline.py', source)
        output = Path(result['outputPath'])
        self.assertEqual(output.parent, self.root / 'excel-to-pipeline/outputs')
        self.assertTrue((output / 'main.py').exists())
        self.assertTrue((output / 'DATA').is_dir())
        self.assertFalse((self.root / 'main.py').exists())

    def test_file_organizer_records_grouped_but_moves_still_target_folder(self):
        organizer = load('file-organizer', 'organize.py')
        inputs = self.root / 'inputs'
        inputs.mkdir()
        (inputs / 'a.txt').write_text('preserved', encoding='utf-8')
        with chdir(self.root):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(organizer.main(['plan', '--folder', str(inputs)]), 0)
            plan = Path(json.loads(stdout.getvalue())['recordPath'])
            self.assertEqual(plan.parent, self.root / 'file-organizer/.work')
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(organizer.main(['apply', '--plan', str(plan)]), 0)
            receipt = Path(json.loads(stdout.getvalue())['recordPath'])
            self.assertEqual(receipt.parent, self.root / 'file-organizer/outputs')
        self.assertEqual((inputs / '문서/a.txt').read_text(encoding='utf-8'), 'preserved')
        self.assertEqual(json.loads(receipt.read_text(encoding='utf-8'))['notAttemptedCount'], 0)

    def test_presentation_bare_name_grouped_and_explicit_path_preserved(self):
        presentation = load('presentation', 'presentation.py')
        with chdir(self.root):
            output = presentation.output_path(Path('발표.html'), business_artifacts)
            self.assertEqual(output, self.root / 'presentation/outputs/발표.html')
            self.assertTrue(output.parent.is_dir())
            for explicit in (self.root / 'chosen.html', Path('chosen/deck.html')):
                self.assertEqual(presentation.output_path(explicit, business_artifacts), explicit)
            reference = presentation.output_path(Path('참고장표'), business_artifacts, intermediate=True)
            self.assertEqual(reference, self.root / 'presentation/.work/참고장표')
            with chdir(output.parent):
                self.assertEqual(presentation.output_path(Path('두번째.html'), business_artifacts).parent, output.parent)

    def test_excel_does_not_write_through_linked_skill_folder(self):
        target = self.root / 'outside'
        target.mkdir()
        link = self.root / 'excel-to-pipeline'
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError:
            self.skipTest('Directory symlinks unavailable under this Windows token')
        import openpyxl
        workbook = openpyxl.Workbook()
        workbook.active.append(['name', 'count'])
        workbook.active.append(['A', 3])
        source = self.root / 'input.xlsx'
        workbook.save(source)
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT / 'standalone-skills/excel-to-pipeline/scripts/excel_pipeline.py'), str(source)], cwd=self.root, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn('연결 폴더', result.stderr)
        self.assertEqual(list(target.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
