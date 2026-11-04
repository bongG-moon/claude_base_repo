"""Reference wrapper stays local, compact, and explicit about Office execution."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'standalone-skills/presentation/scripts/reference.py'
spec = importlib.util.spec_from_file_location('free_html_reference', SCRIPT)
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


class HtmlPresentationReferenceTests(unittest.TestCase):
    def test_plugin_skill_uses_its_own_sibling_runtime_without_personal_lookup(self):
        here = ROOT / 'company-agent-plugin/skills/presentation/scripts'
        with patch.object(reference, 'HERE', here), patch.object(reference.importlib, 'import_module', return_value='loaded') as load:
            self.assertEqual(reference.runtime('ppt_reference'), 'loaded')
        load.assert_called_once_with('company_agent.ppt_reference')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def deck(self):
        sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
        from company_agent.ppt_empty import blank_presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        deck = blank_presentation()
        for i in range(3):
            slide = deck.slides.add_slide(deck.slide_layouts[0])
            run = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(10), Inches(1)).text_frame.paragraphs[0].add_run()
            run.text = 'SOURCE BODY MUST BE OMITTED ' + str(i)
            run.font.name = 'Malgun Gothic'
            run.font.size = Pt(30)
            run.font.color.rgb = RGBColor.from_string('176C66')
        target = self.root / 'synthetic.pptx'
        deck.save(target)
        return target

    def test_pptx_summary_uses_exact_checkout_without_source_text_or_office(self):
        file = self.deck()
        before = file.read_bytes()
        with patch.object(reference, 'runtime', wraps=reference.runtime) as loaded:
            result = reference.inspect(file, slides='3,1')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['selectedSlides'], [3,1])
        self.assertEqual(result['coverage']['status'], 'structure_only')
        self.assertNotIn('SOURCE BODY MUST BE OMITTED', json.dumps(result))
        self.assertIn('declaredFonts', result['analysis'])
        self.assertNotIn('ppt_office_reference', [c.args[0] for c in loaded.call_args_list])
        self.assertEqual(file.read_bytes(), before)

    def test_arbitrary_html_summary_does_not_require_scene_or_execute_scripts(self):
        file = self.root / 'reference.html'
        file.write_text('<html><head><style>body{background:#123456;font-family:"Arial"}h1{font-size:36px}</style>'
                        '<script>throw new Error("MUST NOT EXECUTE")</script></head><body><section><h1>PRIVATE BODY</h1></section></body></html>', encoding='utf-8')
        result = reference.inspect(file)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['inputKind'], 'html')
        self.assertEqual(result['analysis']['tokens']['bg'], '#123456')
        self.assertEqual(result['analysis']['structure']['section'], 1)
        self.assertNotIn('PRIVATE BODY', json.dumps(result))
        self.assertNotIn('MUST NOT EXECUTE', json.dumps(result))
        self.assertEqual(result['visualReview'], 'not_performed')

    def test_image_summary_reports_metadata_without_visual_claims(self):
        file = self.root / 'reference.png'
        raw = b'\x89PNG\r\n\x1a\nsynthetic'
        file.write_bytes(raw)
        result = reference.inspect(file)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['imageMetadata']['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['imageMetadata']['sizeBytes'], len(raw))
        self.assertEqual(result['visualReview'], 'not_performed')

    def test_explicit_office_calls_existing_renderer_once_and_preserves_denial(self):
        module = reference.runtime('ppt_office_reference')
        denied = {'ok':False,'status':'blocked','code':'reference_permission_restricted','retryAllowed':False,'sourcePreserved':True}
        with patch.object(module, 'render_reference', return_value=denied) as render:
            result = reference.inspect(self.root / 'protected.pptx', office=True, output=self.root / 'images', slides='2,1')
        self.assertEqual(result, denied)
        render.assert_called_once_with(self.root / 'protected.pptx', self.root / 'images', [2,1])

    def test_invalid_selection_and_missing_office_output_do_not_load_runtime(self):
        for selection in ('0', '1,1', '1,,2', 'x', list(range(1,62))):
            with self.subTest(selection=selection), patch.object(reference, 'runtime') as loader:
                with self.assertRaises(reference.ReferenceError):
                    reference.inspect(self.root / 'missing.pptx', slides=selection)
                loader.assert_not_called()
        with patch.object(reference, 'runtime') as loader:
            with self.assertRaises(reference.ReferenceError):
                reference.inspect(self.root / 'missing.pptx', office=True)
            loader.assert_not_called()

    def test_relocated_incomplete_wrapper_does_not_find_personal_or_repo_runtime(self):
        staged = self.root / 'relocated/scripts'
        staged.mkdir(parents=True)
        shutil.copyfile(SCRIPT, staged / 'reference.py')
        process = subprocess.run([sys.executable,'-I','-B',str(staged / 'reference.py'),'--file',str(self.root / 'x.pptx')],
                                 cwd=self.root, capture_output=True, timeout=20)
        result = json.loads(process.stdout.decode('utf-8'))
        self.assertEqual(process.returncode, 1)
        self.assertEqual(result['code'], 'incomplete_package')

    def test_bundled_module_is_preferred_and_response_is_one_json(self):
        staged = self.root / 'portable/scripts'
        engine = staged / 'visual_engine'
        engine.mkdir(parents=True)
        shutil.copyfile(SCRIPT, staged / 'reference.py')
        (engine / '__init__.py').write_text('', encoding='utf-8')
        (engine / 'ppt_reference.py').write_text('def prepare_reference(spec):\n return {"ok":True,"inputKind":"pptx","bundled":True}\ndef summarize_reference(result):\n return result\n', encoding='utf-8')
        process = subprocess.run([sys.executable,'-I','-B',str(staged / 'reference.py'),'--file',str(self.root / 'x.pptx')],
                                 cwd=self.root, capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr.decode(errors='replace'))
        self.assertEqual(json.loads(process.stdout.decode('utf-8')), {'ok':True,'inputKind':'pptx','bundled':True})
        self.assertEqual(len(process.stdout.decode('utf-8').splitlines()), 1)


if __name__ == '__main__':
    unittest.main()
