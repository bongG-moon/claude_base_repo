"""The shipped mixed-scene example stays executable and native-editable."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import ppt_html, presentation_design


class PptSceneExampleTests(unittest.TestCase):
    def test_preflight_guidance_precedes_approval_in_both_skill_versions(self):
        for path, approval_step in (
            (ROOT / 'standalone-skills/presentation/SKILL.md', '3. 초안 전체'),
            (ROOT / 'company-agent-plugin/skills/presentation/SKILL.md', '4. **확인:**'),
        ):
            with self.subTest(path=path):
                text = path.read_text(encoding='utf-8')
                warning = text.index('반환된 `scenePreflight`에 경고가 있으면')
                self.assertLess(warning, text.index(approval_step))
                self.assertIn('경고를 없애려고 반복 보정하지 않으며 경고가 없으면 이 검토를 추가하지 않습니다', text)
                self.assertIn('경고의 진위가 불확실하면 미확인으로 알려 줍니다', text)

    def test_example_draft_and_native_table_chart_and_group(self):
        source = ROOT / 'standalone-skills/presentation/references/scene-example.json'
        companion = ROOT / 'company-agent-plugin/skills/presentation/references/scene-example.json'
        self.assertEqual(source.read_bytes(), companion.read_bytes())
        spec = json.loads(source.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = ppt_html.create_draft(spec, root / 'draft.html', require_choices=False)
            self.assertTrue(result['ok'], result)
            self.assertTrue((root / 'draft.html').is_file())
            data = ppt_html.prepare(spec)[0]
            output = root / 'example.pptx'
            presentation_design.render_python(data, output, None)
            from pptx import Presentation
            from pptx.enum.shapes import MSO_SHAPE_TYPE
            deck = Presentation(output)
            shapes = deck.slides[0].shapes
            self.assertEqual(1, sum(bool(shape.has_table) for shape in shapes))
            self.assertEqual(1, sum(bool(shape.has_chart) for shape in shapes))
            table = next(shape.table for shape in shapes if shape.has_table)
            self.assertEqual('333333', str(table.cell(0, 0).fill.fore_color.rgb))
            self.assertEqual('EEEEEE', str(table.cell(1, 0).fill.fore_color.rgb))
            self.assertEqual('FFFFFF', str(table.cell(2, 0).fill.fore_color.rgb))
            self.assertEqual(18, table.cell(0, 0).text_frame.paragraphs[0].font.size.pt)
            self.assertIn('background:#333333', (root / 'draft.html').read_text(encoding='utf-8'))
            group = next(shape for shape in shapes if shape.shape_type == MSO_SHAPE_TYPE.GROUP)
            self.assertEqual('확인항목', group.name)
            self.assertEqual(2, len(group.shapes))
            self.assertFalse(group._element.xpath('.//a:grpSpLocks[@noUngrp="1"]'))
            self.assertTrue(any(shape._element.tag.endswith('}cxnSp') for shape in shapes))


if __name__ == '__main__':
    unittest.main()
