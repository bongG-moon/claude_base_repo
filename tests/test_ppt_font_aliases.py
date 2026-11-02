"""Localized family names keep their typeface without inventing installation."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business_artifacts, ppt_workflow, presentation_design


class PptFontAliasTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/ppt-font-aliases'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def prepare(self, font):
        spec = {'title':'서체 보존', 'presentationFont':font,
                'slides':[{'title':'기존 서체 유지', 'body':'같은 글꼴의 언어별 이름을 확인합니다.'}]}
        data = business_artifacts._normalize(spec)
        presentation_design.prepare(spec, data)
        data['presentationPlan'] = presentation_design.plan(data)
        return data

    def test_localized_and_english_names_use_actual_family_evidence(self):
        for requested, installed in (('맑은 고딕', {'Malgun Gothic'}),
                                     ('Malgun Gothic', {'맑은 고딕'}),
                                     ('malgun gothic', {'MALGun Gothic'}),
                                     ('맑은 고딕', {'맑은 고딕'})):
            with self.subTest(requested=requested, installed=installed):
                self.assertTrue(ppt_workflow.font_available(requested, installed))

    def test_no_installed_evidence_is_not_reported_as_available(self):
        self.assertFalse(ppt_workflow.font_available('맑은 고딕', set()))
        self.assertFalse(ppt_workflow.font_available('Malgun Gothic', set()))
        self.assertFalse(ppt_workflow.font_available('Missing Corp Font', {'Malgun Gothic'}))

    def test_weight_specific_faces_are_not_regular_family_aliases(self):
        self.assertFalse(ppt_workflow.font_available('맑은 고딕', {'Malgun Gothic Bold'}))
        self.assertFalse(ppt_workflow.font_available('맑은 고딕 Light', {'Malgun Gothic'}))
        self.assertTrue(ppt_workflow.font_available('Malgun Gothic Bold', {'Malgun Gothic Bold'}))

    def test_prepare_preserves_original_localized_typeface(self):
        with patch.object(ppt_workflow, 'installed_fonts', return_value={'Malgun Gothic'}):
            data = self.prepare('맑은 고딕')
        self.assertEqual('맑은 고딕', data['presentationFont'])
        self.assertEqual('맑은 고딕', data['presentationPlan']['font'])

    def test_alias_does_not_bypass_missing_custom_font_check(self):
        with patch.object(ppt_workflow, 'installed_fonts', return_value=set()):
            with self.assertRaises(presentation_design.DesignError):
                self.prepare('맑은 고딕')
            with self.assertRaises(presentation_design.DesignError):
                self.prepare('Missing Corp Font')

    def test_existing_default_fallback_does_not_require_inventory(self):
        with patch.object(ppt_workflow, 'installed_fonts', side_effect=AssertionError('default fallback is unchanged')):
            data = self.prepare('Malgun Gothic')
        self.assertEqual('Malgun Gothic', data['presentationFont'])

    @unittest.skipUnless(importlib.util.find_spec('pptx'), 'python-pptx required for native font preservation')
    def test_native_typeface_and_reference_inventory_agree(self):
        from pptx import Presentation
        with patch.object(ppt_workflow, 'installed_fonts', return_value={'Malgun Gothic'}):
            data = self.prepare('맑은 고딕')
            target = self.root / 'localized.pptx'
            presentation_design.render_python(data, target, None)
            found = ppt_workflow.analyze(target, first_slides=1)
        self.assertTrue(found['ok'], found)
        self.assertIn({'name':'맑은 고딕', 'available':True}, found['declaredFonts'])
        deck = Presentation(target)
        self.assertTrue(any('typeface="맑은 고딕"' in p._p.xml
                            for shape in deck.slides[0].shapes if shape.has_text_frame
                            for p in shape.text_frame.paragraphs))
        before = target.read_bytes()
        with patch.object(ppt_workflow, 'installed_fonts', return_value=set()):
            missing = ppt_workflow.analyze(target, first_slides=1)
        self.assertIn({'name':'맑은 고딕', 'available':False}, missing['declaredFonts'])
        self.assertEqual(before, target.read_bytes())


if __name__ == '__main__':
    unittest.main()
