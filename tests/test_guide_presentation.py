"""Offline typography, glyph coverage and responsive-reader contracts."""
import base64
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / 'scripts/assets/manual-font'


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.code = 0
        self.text = []
        self.prose = []
        self.cells = []

    def handle_starttag(self, tag, attrs):
        if tag in ('style', 'script'):
            self.hidden += 1
        if tag in ('pre', 'code'):
            self.code += 1
        if tag == 'td':
            self.cells.append(dict(attrs))

    def handle_endtag(self, tag):
        if tag in ('style', 'script'):
            self.hidden -= 1
        if tag in ('pre', 'code'):
            self.code -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
            if not self.code:
                self.prose.append(data)


class GuidePresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = [*sorted((ROOT / 'company-agent-plugin/resources/manuals').glob('*.html')),
                     ROOT / 'company-agent-plugin/resources/first-work.html']
        cls.manifest = json.loads((FONT / 'manifest.json').read_text(encoding='utf-8'))

    def test_embedded_font_is_small_identical_and_licensed(self):
        font = (FONT / 'NotoSansKR-guide.woff').read_bytes()
        self.assertEqual(font[:4], b'wOFF')
        self.assertLess(len(font), 150_000)
        self.assertEqual(hashlib.sha256(font).hexdigest(), self.manifest['sha256'])
        for path in self.pages:
            with self.subTest(file=path.name):
                page = path.read_text(encoding='utf-8')
                payloads = re.findall(r'data:font/woff;base64,([A-Za-z0-9+/=]+)', page)
                self.assertEqual(len(payloads), 1)
                self.assertEqual(base64.b64decode(payloads[0]), font)
                self.assertIn("font-src data:", page)
                self.assertIn("font-family:'Noto Sans KR'", page)
                self.assertIn('SIL OPEN FONT LICENSE Version 1.1', page)
                self.assertNotIn('fonts.googleapis.com', page)
                self.assertNotIn('fonts.gstatic.com', page)
                self.assertLess(len(page.encode('utf-8')), 400_000)

    def test_all_visible_characters_are_covered_and_markdown_is_rendered(self):
        supported = set(self.manifest['characters'])
        for path in self.pages:
            with self.subTest(file=path.name):
                parser = VisibleText()
                parser.feed(path.read_text(encoding='utf-8'))
                visible = ''.join(parser.text)
                self.assertNotIn('\ufffd', visible)
                self.assertNotIn('**', ''.join(parser.prose))
                self.assertFalse({c for c in visible if c.isprintable()} - supported)

    def test_tables_keep_headers_and_mobile_labels(self):
        page = (ROOT / 'docs/Company-Agent-Guide.html').read_text(encoding='utf-8')
        parser = VisibleText()
        parser.feed(page)
        self.assertGreater(len(parser.cells), 100)
        self.assertTrue(all(cell.get('data-label') and cell.get('role') == 'cell' for cell in parser.cells))
        self.assertIn('<th scope="col">', page)
        self.assertIn('td::before{content:attr(data-label)', page)
        self.assertIn('aria-label="모바일 목차"', page)
        self.assertIn('<details class="mobile-nav">', page)
        self.assertIn('@media print', page)
        self.assertIn('td::before{display:none}', page)

    def test_first_work_rebuild_is_idempotent(self):
        builder = runpy.run_path(str(ROOT / 'scripts/build-first-work.py'))
        actual = (ROOT / 'company-agent-plugin/resources/first-work.html').read_text(encoding='utf-8')
        self.assertEqual(actual, builder['render']())


if __name__ == '__main__':
    unittest.main()
