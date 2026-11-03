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
        for path, quality_reference in (
            (ROOT / 'standalone-skills/presentation/SKILL.md', 'references/design.md'),
            (ROOT / 'company-agent-plugin/skills/presentation/SKILL.md', 'references/design-review.md'),
        ):
            with self.subTest(path=path):
                text = path.read_text(encoding='utf-8')
                flow = text.split('## 기본 흐름', 1)[1].split('## 필요한 경로만 읽기', 1)[0]
                warning = flow.index('경고가 있으면 관련 장만 확인합니다')
                self.assertLess(warning, flow.index('실제 승인 후'))
                self.assertLess(flow.index('실제 승인 후'), flow.index('`confirmed:true`'))
                self.assertIn('같은 내용의 유효한 승인은 다시 묻지 않습니다', flow)
                self.assertIn('화면을 못 봤으면 구조 검사와 구분합니다', text)
                # Detailed preflight guidance is loaded only when needed; the
                # concise entrypoint still links to the warning interpretation.
                self.assertIn(f']({quality_reference})', text)
                quality = (path.parent / quality_reference).read_text(encoding='utf-8')
                self.assertIn('scenePreflight', quality)
                self.assertIn('possible_diamond_text_clipping', quality)
                self.assertIn('추정', quality)

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
