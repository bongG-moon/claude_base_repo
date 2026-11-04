"""Packaged HTML entrypoint asks once, keeps choices, and groups new outputs."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import html_reference
from company_agent.business_artifacts import create_html, html_choices


class HtmlSelectionFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package_temp = tempfile.TemporaryDirectory()
        cls.skill = Path(cls.package_temp.name) / 'skill'
        shutil.copytree(ROOT / 'standalone-skills/html-report', cls.skill)
        metadata = json.loads((ROOT / 'scripts/platform_skills/catalog-metadata.json').read_text(encoding='utf-8-sig'))
        runtime = cls.skill / 'scripts/visual_engine'
        runtime.mkdir(parents=True, exist_ok=True)
        for name in metadata['html-report']['packaging']['runtimeModules']:
            shutil.copyfile(ROOT / 'company-agent-plugin/scripts/company_agent' / name, runtime / name)

    @classmethod
    def tearDownClass(cls):
        cls.package_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.spec = {'title': '업무 현황', 'sections': [{'title': '현재 상황', 'body': '사용자 자료'}]}
        self.selected = {**self.spec, 'style': 'bento-grid', 'length': 'detailed',
                         'mode': 'both', 'fontChoice': 'pretendard', 'fontSource': 'system'}

    def build(self, spec, output='보고서.html'):
        job = self.root / 'html-report/.work/job.json'
        job.parent.mkdir(parents=True, exist_ok=True)
        job.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
        run = subprocess.run([sys.executable, '-B', str(self.skill / 'scripts/report.py'),
                              'build', '--spec', str(job), '--output', str(output)],
                             cwd=self.root, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertIn(run.returncode, (0, 1), run.stderr)
        return run.returncode, json.loads(run.stdout)

    def test_unselected_build_is_one_normal_pause_before_asset_reads(self):
        spec = {**self.spec, 'sections': [{'image': {'path': 'not-yet-read.png'}}]}
        code, result = self.build(spec)
        self.assertEqual(0, code)
        self.assertEqual('input_required', result['status'])
        self.assertTrue(result['choiceRequired'])
        self.assertEqual(['style', 'length', 'mode', 'fontChoice'], result['missing'])
        for field in ('initialDesignOptions', 'lengthOptions', 'viewOptions', 'fontOptions'):
            self.assertIn(field, result)
        self.assertFalse((self.root / 'html-report/outputs').exists())

    def test_partial_selection_only_requests_missing_values(self):
        code, result = self.build({**self.spec, 'style': 'editorial', 'mode': 'scroll'})
        self.assertEqual(0, code)
        self.assertEqual(['length', 'fontChoice'], result['missing'])
        self.assertEqual('editorial', result['preservedChoices']['style'])
        self.assertNotIn('initialDesignOptions', result)
        self.assertNotIn('viewOptions', result)

    def test_known_and_auto_choices_generate_without_another_question(self):
        for name, fields in (('known.html', self.selected), ('auto.html', {**self.spec,
                'style': 'minimalism', 'length': 'standard', 'mode': 'scroll', 'fontChoice': 'auto'})):
            with self.subTest(name=name):
                code, result = self.build(fields, name)
                self.assertEqual(0, code, result)
                self.assertTrue(result['ok'], result)
                self.assertTrue((self.root / 'html-report/outputs' / name).is_file())
                self.assertFalse((self.root / name).exists())

    def test_explicit_paths_are_preserved_and_existing_file_is_not_overwritten(self):
        for output in (self.root / 'chosen/final.html', Path('custom/results.html')):
            target = output if output.is_absolute() else self.root / output
            target.parent.mkdir(parents=True, exist_ok=True)
            code, result = self.build(self.selected, output)
            self.assertEqual(0, code, result)
            self.assertEqual(target.resolve(), Path(result['outputPath']).resolve())
        existing = self.root / 'existing.html'
        existing.write_text('original', encoding='utf-8')
        code, result = self.build(self.selected, 'existing.html')
        self.assertEqual(1, code)
        self.assertEqual('output_exists', result['code'])
        self.assertEqual('original', existing.read_text(encoding='utf-8'))
        self.assertFalse((self.root / 'html-report/outputs/existing.html').exists())

    def reference_spec(self):
        source = self.root / 'reference.html'
        source.write_text('<html><style>body{font-family:"Malgun Gothic",sans-serif;color:#234567}</style><body>원본</body></html>', encoding='utf-8')
        preview = html_reference.inspect_template(source, self.root / 'preview.html')
        self.assertTrue(preview['ok'], preview)
        return {**self.spec, 'fontChoiceRequired': True,
                'htmlTemplate': preview['htmlTemplate'], 'templateReview': preview['templateReview']}

    def test_reference_confirmation_includes_unanswered_format_and_font(self):
        result = html_choices(self.reference_spec())
        self.assertEqual('template_confirm', result['stage'])
        self.assertEqual(['templateReview.confirmed', 'length', 'mode', 'fontChoice'], result['missing'])
        self.assertIn('previewLink', result)
        self.assertIn('첨부 양식의 글꼴 따라가기', [row['name'] for row in result['fontOptions']])

    def test_selected_font_wins_without_losing_reference_palette(self):
        spec = self.reference_spec()
        spec['templateReview']['confirmed'] = True
        spec.update(style='minimalism', length='standard', mode='scroll',
                    fontChoice='pretendard', fontSource='system')
        result = create_html(spec, self.root / 'selected-font.html', require_choices=True)
        self.assertTrue(result['ok'], result)
        self.assertEqual('Pretendard', result['typography']['family'])
        doc = (self.root / 'selected-font.html').read_text(encoding='utf-8')
        self.assertIn('#234567', doc)
        self.assertGreater(doc.rfind('font-family:"Pretendard"'), doc.find('font-family:"Malgun Gothic"'))
        spec['fontChoice'] = 'auto'
        result = create_html(spec, self.root / 'reference-font.html', require_choices=True)
        self.assertTrue(result['ok'], result)
        self.assertEqual('template', result['typography']['source'])

    def test_reference_simple_preview_name_goes_to_intermediate_folder(self):
        source = self.root / 'reference.html'
        source.write_text('<html><body>가상 참고</body></html>', encoding='utf-8')
        run = subprocess.run([sys.executable, '-B', str(self.skill / 'scripts/report.py'),
                              'reference', '--file', str(source), '--preview', 'preview.html'],
                             cwd=self.root, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(0, run.returncode, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(self.root / 'html-report/.work/preview.html', Path(result['previewPath']))
        self.assertTrue(Path(result['previewPath']).is_file())


if __name__ == '__main__':
    unittest.main()
