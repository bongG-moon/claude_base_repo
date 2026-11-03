import copy
from html.parser import HTMLParser
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import ppt_html, presentation_design


class SlideBackgroundReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.backgrounds = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'ppt-slide' in attrs.get('class', '').split():
            styles = dict(item.split(':', 1) for item in attrs.get('style', '').split(';') if ':' in item)
            self.backgrounds.append(styles.get('background'))


class PptThemeBackgroundTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.theme = {'title': 'FFFFFF', 'accent': '2DD4BF', 'text': 'E6EEF5',
                      'muted': '9DB2C7', 'background': '0B1E3B', 'tint': '12305A'}
        self.spec = {'creationMode': 'new', 'designPreset': 'business',
                     'purpose': '배경 상속 검증', 'audience': '검토자', 'slideCount': 1,
                     'title': '테마 배경', 'presentationTheme': self.theme,
                     'slides': [{'title': '테마 배경', 'elements': [
                         {'kind': 'text', 'text': '테마 제목', 'x': 60, 'y': 60,
                          'w': 800, 'h': 80, 'size': 40, 'color': 'title'}]}]}

    def assert_outputs_background(self, spec, expected, *, template=None, name='draft'):
        from pptx import Presentation
        preview = ppt_html.create_draft(spec, self.root / f'{name}.html', template)
        self.assertTrue(preview['ok'], preview)
        reader = SlideBackgroundReader()
        reader.feed(Path(preview['outputPath']).read_text(encoding='utf-8'))
        self.assertEqual([f'#{expected}'], reader.backgrounds)
        data = ppt_html.prepare(spec, template)[0]
        output = self.root / f'{name}.pptx'
        presentation_design.render_python(data, output, None)
        slide = Presentation(output).slides[0]
        self.assertEqual(expected, str(slide.background.fill.fore_color.rgb))
        return preview, slide

    def test_missing_slide_background_inherits_custom_theme_in_html_and_pptx(self):
        _, slide = self.assert_outputs_background(self.spec, '0B1E3B')
        self.assertEqual('FFFFFF', str(slide.shapes[0].text_frame.paragraphs[0].runs[0].font.color.rgb))
        self.assertNotIn('background', self.spec['slides'][0])

    def test_explicit_white_slide_background_is_preserved(self):
        self.spec['slides'][0]['background'] = 'FFFFFF'
        self.spec['slides'][0]['elements'][0]['color'] = '17324D'
        self.assert_outputs_background(self.spec, 'FFFFFF')

    def test_saved_layout_background_is_preserved_when_theme_changes(self):
        for background in ('FFFFFF', 'EEE7DC'):
            with self.subTest(background=background):
                original = copy.deepcopy(self.spec)
                original.pop('presentationTheme')
                original['slides'][0]['background'] = background
                preview = ppt_html.create_draft(original, self.root / f'source-{background}.html')
                self.assertTrue(preview['ok'], preview)
                original['designReview'] = {**preview['designReview'], 'confirmed': True}
                template = self.root / f'template-{background}.html'
                saved = ppt_html.save_template(original, template)
                self.assertTrue(saved['ok'], saved)
                reused = {'creationMode': 'saved', 'purpose': '양식 검증', 'audience': '검토자',
                          'slideCount': 1, 'presentationTheme': self.theme,
                          'slides': [{'title': '새 내용', 'layoutIndex': 1, 'texts': ['새 제목']}]}
                self.assert_outputs_background(reused, background, template=template, name=f'reuse-{background}')


if __name__ == '__main__':
    unittest.main()
