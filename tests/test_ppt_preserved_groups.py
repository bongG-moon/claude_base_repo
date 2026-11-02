"""Explicitly kept native groups survive slot replacement without bypasses."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business_artifacts as artifacts, ppt_html


@unittest.skipUnless(importlib.util.find_spec('pptx'), 'python-pptx required for native group preservation')
class PptPreservedGroupsTests(unittest.TestCase):
    def setUp(self):
        from pptx import Presentation
        from pptx.util import Pt
        from pptx.enum.shapes import MSO_SHAPE
        parent = ROOT / '.smoke/ppt-preserved-groups'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        deck = Presentation()
        deck.slide_width, deck.slide_height = Pt(960), Pt(540)
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        title = slide.shapes.add_textbox(Pt(32), Pt(16), Pt(895), Pt(50))
        title.name = '교체할 제목'
        run = title.text_frame.paragraphs[0].add_run()
        run.text = '기존 제목'
        run.font.size = Pt(24)
        run.font.name = 'Malgun Gothic'
        group = slide.shapes.add_group_shape()
        group.name = '유지할 일정 그룹'
        background = group.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(50), Pt(110), Pt(500), Pt(180))
        background.name = '고정 일정 배경'
        nested = group.shapes.add_group_shape()
        nested.name = '고정 일정 하위 그룹'
        label = nested.shapes.add_textbox(Pt(65), Pt(130), Pt(440), Pt(45))
        label.name = '고정 업무명'
        label.text = '기존 양식의 고정 업무명'
        nested.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(65), Pt(190), Pt(220), Pt(24))
        self.title_id, self.group_id = title.shape_id, group.shape_id
        self.source = self.root / 'template.pptx'
        deck.save(self.source)
        self.before = self.source.read_bytes()
        self.job = {'title':'양식 유지 검증', 'creationMode':'reference', 'referenceMode':'preserve',
                    'purpose':'고정 그룹과 제목 교체 검증', 'audience':'검증 담당자', 'slideCount':1,
                    'slides':[{'title':'새 업무 제목'}],
                    'templateSlides':[{'sourceSlide':0, 'title':self.title_id, 'keepShapeIds':[self.group_id]}]}

    def preview(self, job=None):
        with patch.object(artifacts, '_office', side_effect=AssertionError('HTML preview does not start Office')):
            return ppt_html.create_draft(job or self.job, self.root / 'draft.html', self.source)

    def build(self, job=None, output=None):
        with patch.object(artifacts, '_office', return_value={'ok':False, 'code':'render_refused'}):
            return artifacts.create_ppt(job or self.job, output or self.root / 'output.pptx',
                                        self.source, require_choices=True)

    def test_title_replacement_keeps_nested_native_group_xml_and_geometry(self):
        from pptx import Presentation
        preview = self.preview()
        self.assertTrue(preview['ok'], preview)
        self.assertFalse(preview['designReview']['confirmed'])
        self.assertIn('새 업무 제목', (self.root / 'draft.html').read_text(encoding='utf-8'))
        self.job['designReview'] = {**preview['designReview'], 'confirmed':True}
        result = self.build()
        self.assertTrue(result['ok'], result)
        old = Presentation(self.source).slides[0]
        new = Presentation(self.root / 'output.pptx').slides[0]
        old_group = next(s for s in old.shapes if s.shape_id == self.group_id)
        new_group = next(s for s in new.shapes if s.shape_id == self.group_id)
        self.assertEqual(old_group._element.xml, new_group._element.xml)
        self.assertEqual((old_group.left, old_group.top, old_group.width, old_group.height),
                         (new_group.left, new_group.top, new_group.width, new_group.height))
        self.assertEqual(2, len(new_group.shapes))
        self.assertEqual(2, len(new_group.shapes[1].shapes))
        self.assertFalse(new_group._element.xpath('.//a:grpSpLocks[@noUngrp="1"]'))
        self.assertEqual('새 업무 제목', next(s.text for s in new.shapes if s.shape_id == self.title_id))
        self.assertEqual(self.before, self.source.read_bytes())

    def test_kept_group_does_not_skip_html_approval(self):
        preview = self.preview()
        self.assertTrue(preview['ok'], preview)
        self.job['designReview'] = preview['designReview']
        blocked = self.build()
        self.assertFalse(blocked['ok'])
        self.assertEqual('design_confirm', blocked['stage'])
        self.assertFalse((self.root / 'output.pptx').exists())
        self.assertEqual(self.before, self.source.read_bytes())

    def test_unmapped_group_is_rejected_without_publishing(self):
        job = copy.deepcopy(self.job)
        job['templateSlides'][0]['keepShapeIds'] = []
        preview = self.preview(job)
        self.assertFalse(preview['ok'])
        self.assertEqual('template_group_unsupported', preview['code'])
        self.assertFalse((self.root / 'draft.html').exists())
        result = artifacts.create_ppt(job, self.root / 'bad.pptx', self.source)
        self.assertFalse(result['ok'])
        self.assertEqual('template_group_unsupported', result['code'])
        self.assertFalse((self.root / 'bad.pptx').exists())
        self.assertEqual(self.before, self.source.read_bytes())

    def test_group_is_not_a_replaceable_title_or_body_slot(self):
        for field in ('title', 'body'):
            with self.subTest(field=field):
                job = copy.deepcopy(self.job)
                job['templateSlides'][0]['keepShapeIds'] = []
                job['templateSlides'][0][field] = self.group_id
                job['slides'][0][field] = '그룹을 글자 칸으로 교체하지 않습니다'
                result = self.preview(job)
                self.assertFalse(result['ok'])
                self.assertEqual('template_mapping_invalid', result['code'])
                self.assertFalse((self.root / 'draft.html').exists())
        self.assertEqual(self.before, self.source.read_bytes())

    def test_keeping_group_does_not_allow_other_unmapped_old_text(self):
        from pptx import Presentation
        from pptx.util import Pt
        deck = Presentation(self.source)
        box = deck.slides[0].shapes.add_textbox(Pt(600), Pt(120), Pt(250), Pt(40))
        box.text = '명시하지 않은 이전 보고 내용'
        deck.save(self.source)
        before = self.source.read_bytes()
        result = self.preview()
        self.assertFalse(result['ok'])
        self.assertEqual('template_unmapped_content', result['code'])
        self.assertFalse((self.root / 'draft.html').exists())
        self.assertEqual(before, self.source.read_bytes())


if __name__ == '__main__':
    unittest.main()
