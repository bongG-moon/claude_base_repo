"""Verify real 6-slide output with several reference and content images."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pptx import Presentation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business_artifacts, ppt_html, ppt_workflow


class MultipleImagePresentationTests(unittest.TestCase):
    def test_reference_without_color_accepts_observed_style_but_not_empty_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = folder / 'ref.png'
            Image.new('RGB', (8, 8), (50, 80, 100)).save(path)
            spec = {'title': '관찰', 'creationMode': 'reference', 'purpose': '검토', 'audience': '담당자',
                    'slideCount': 1, 'referenceImages': [str(path)],
                    'slides': [{'title': '새 내용', 'body': '가상 자료입니다.'}]}
            for index, style in enumerate(({'patterns': {'layout': '제목 아래 3열 정렬'}},
                                           {'typography': {'bodyFont': 'Malgun Gothic'}})):
                result = ppt_html.create_draft({**spec, 'referenceStyle': style}, folder / f'ok-{index}.html')
                self.assertTrue(result['ok'], result)
            for index, style in enumerate(({}, {'patterns': {'layout': '  '}},
                                           {'evidence': [{'source': str(path), 'uncertain': ['색 미확인']}]})):
                result = ppt_html.create_draft({**spec, 'referenceStyle': style}, folder / f'no-{index}.html')
                self.assertEqual('reference_design_needed', result.get('code'), result)

    def test_reference_and_slide_boundaries_match_choices_and_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = folder / 'ref.png'
            Image.new('RGB', (8, 8), (50, 80, 100)).save(path)
            spec = {'title': '경계', 'creationMode': 'reference', 'purpose': '시험', 'audience': '검토자',
                    'slideCount': 60, 'referenceImages': [str(path)] * 60,
                    'referenceStyle': {'colors': {'primary': '234E70'}},
                    'slides': [{'title': f'{i}장', 'body': f'가상 자료 {i}입니다.'} for i in range(60)]}
            self.assertEqual('design_preview', ppt_workflow.choices(spec)['stage'])
            result = ppt_html.create_draft(spec, folder / 'boundary.html')
            self.assertTrue(result['ok'], result)
            self.assertEqual(60, result['slides'])
            too_many_images = {**spec, 'referenceImages': [str(path)] * 61}
            self.assertEqual('invalid_choice', ppt_workflow.choices(too_many_images)['code'])
            self.assertFalse(ppt_html.create_draft(too_many_images, folder / 'bad-images.html')['ok'])
            too_many_slides = {**spec, 'slideCount': 61, 'slides': spec['slides'] + [spec['slides'][0]]}
            self.assertEqual('invalid_choice', ppt_workflow.choices(too_many_slides)['code'])
            self.assertFalse(ppt_html.create_draft(too_many_slides, folder / 'bad-slides.html')['ok'])

    def test_six_slides_seven_references_and_two_editable_content_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            references = []
            for number in range(7):
                path = folder / f'reference-{number}.png'
                Image.new('RGB', (32, 32), (number * 25, 110, 150)).save(path)
                references.append(str(path))
            spec = {'title': '여러 이미지 검증', 'creationMode': 'reference',
                    'purpose': '가상 업무 검토', 'audience': '담당자', 'slideCount': 6,
                    'referenceImages': references,
                    'referenceStyle': {'colors': {'primary': '234E70', 'secondary': 'C8892E'}},
                    'slides': [{'title': f'{i}장', 'body': f'새 업무 자료 {i}입니다.'} for i in range(1, 6)] + [
                        {'title': '두 이미지 비교', 'elements': [
                            {'kind': 'text', 'text': '두 이미지 비교', 'x': 40, 'y': 25, 'w': 800, 'h': 44, 'size': 24},
                            {'kind': 'image', 'x': 50, 'y': 100, 'w': 350, 'h': 300, 'image': {'path': references[0]}},
                            {'kind': 'image', 'x': 500, 'y': 100, 'w': 350, 'h': 300, 'image': {'path': references[1]}}]}]}
            choice = ppt_workflow.choices(spec)
            self.assertEqual('design_preview', choice['stage'])
            self.assertEqual(references, choice['preservedChoices']['referenceImages'])
            draft = ppt_html.create_draft(spec, folder / 'draft.html')
            self.assertTrue(draft['ok'], draft)
            self.assertEqual(6, draft['slides'])
            self.assertEqual(2, (folder / 'draft.html').read_text(encoding='utf-8').count('<img '))
            spec['designReview'] = {**draft['designReview'], 'confirmed': True}
            ppt_workflow.verify_design_review(spec)
            with patch.object(business_artifacts, '_office', return_value={'ok': False}):
                result = business_artifacts.create_ppt(spec, folder / 'result.pptx', require_choices=True)
            self.assertTrue(result['ok'], result)
            deck = Presentation(folder / 'result.pptx')
            self.assertEqual(6, len(deck.slides))
            self.assertEqual(2, sum(s.shape_type == 13 for page in deck.slides for s in page.shapes))
            Image.new('RGB', (32, 32), (255, 0, 10)).save(references[-1])
            with self.assertRaises(business_artifacts.ArtifactError) as error:
                ppt_workflow.verify_design_review(spec)
            self.assertEqual('design_review_changed', error.exception.code)


if __name__ == '__main__':
    unittest.main()
