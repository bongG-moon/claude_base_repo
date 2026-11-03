"""Ten theme specimens retain real report content and offline controllers.

These checks cover generated HTML and shipped artifacts. They do not claim
browser layout, contrast, or live click validation.
"""
import base64
import copy
from contextlib import ExitStack
import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business_artifacts as artifacts, report_gallery, report_styles
from company_agent.report_theme_sources import SOURCES


class _Tags(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        self.tags.append((tag, dict(attributes)))


def _kpis(source):
    return re.findall(r'<div class="kpi-value">([^<]+)<span class="kpi-unit">([^<]*)</span>', source)


def _main_and_after(source):
    return source.split('<main class="report-main">', 1)[1]


def _first_section(source):
    section = re.search(r'<section\b.*?</section>', source, re.S).group()
    # A thumbnail renders only the cover, so its page count is intentionally 1.
    return re.sub(r'<span class="page-number">.*?</span>', '', section, count=1, flags=re.S)


class ReportThemeExamplesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.styles = [row[0] for row in report_styles.STYLES]
        cls.scratch = ROOT / '.smoke/html-reference-tests'
        cls.scratch.mkdir(parents=True, exist_ok=True)
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            'TEMP': str(cls.scratch), 'TMP': str(cls.scratch), 'TMPDIR': str(cls.scratch),
        }))
        stack.enter_context(patch.object(tempfile, 'tempdir', str(cls.scratch)))
        cls.folder = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='themes-', dir=cls.scratch)))
        cls.network = [stack.enter_context(patch(target, side_effect=AssertionError('Rendering must remain offline')))
                       for target in ('socket.create_connection', 'socket.socket.connect', 'urllib.request.urlopen')]
        cls.documents, cls.results, cls.previews = {}, {}, {}
        for style in cls.styles:
            spec = report_gallery.style_example_spec(style)
            # Shipped pages use packaged fonts; content comparison begins at main.
            # Font embedding and font-copy contracts have their own existing tests.
            spec['fontSource'] = 'system'
            before = copy.deepcopy(spec)
            output = cls.folder / ('style-' + style + '.html')
            result = artifacts.create_html(spec, output)
            if not result.get('ok'):
                raise AssertionError(f'{style}: {result}')
            if spec != before:
                raise AssertionError(f'{style}: rendering mutated its source example')
            cls.results[style] = result
            cls.documents[style] = output.read_text(encoding='utf-8')
            cls.previews[style] = report_gallery.style_preview_markup(style)
        cls.picker = report_styles.picker_html()

    def test_ten_examples_share_one_fresh_dataset(self):
        self.assertEqual(10, len(self.styles))
        self.assertEqual(set(self.styles), set(SOURCES))
        baseline = report_gallery.style_example_spec(self.styles[0])
        baseline.pop('style')
        for style in self.styles:
            with self.subTest(style=style):
                spec = report_gallery.style_example_spec(style)
                self.assertEqual(style, spec.pop('style'))
                self.assertEqual(baseline, spec)
                self.assertNotIn('referencePreset', spec)
        changed = report_gallery.style_example_spec(self.styles[0])
        changed['sections'][4]['table']['rows'][0][0] = 'modified'
        self.assertEqual('TASK-001', report_gallery.style_example_spec(self.styles[0])['sections'][4]['table']['rows'][0][0])
        with self.assertRaises(ValueError):
            report_gallery.style_example_spec('unknown-theme')

    def test_real_reports_preserve_facts_all_rows_and_usable_controls(self):
        expected_kpis = [('530', '백만원'), ('117.78', '%'), ('18', '건')]
        expected_rows = report_gallery.style_example_spec(self.styles[0])['sections'][4]['table']['rows']
        for style, document in self.documents.items():
            with self.subTest(style=style):
                self.assertEqual(expected_kpis, _kpis(document))
                self.assertEqual(6, self.results[style]['sections'])
                self.assertTrue(self.results[style]['offline'])
                tables = [ET.fromstring(raw) for raw in re.findall(r'<table\b.*?</table>', document, re.S)]
                task_table = next(table for table in tables if table.find('./thead/tr/th').text == '과제 ID')
                rows = [[cell.text or '' for cell in row] for row in task_table.findall('./tbody/tr')]
                self.assertEqual(expected_rows, rows)
                self.assertEqual(48, len(rows))
                chart_table = next(table for table in tables if table.findtext('caption') == '차트 원자료')
                self.assertEqual([['6월', '120', '145'], ['7월', '150', '175'], ['8월', '180', '210']],
                                 [[cell.text or '' for cell in row] for row in chart_table.findall('./tbody/tr')])
                self.assertEqual({'완료': 30, '검토 중': 12, '지연': 6},
                                 {status: sum(row[3] == status for row in rows) for status in ('완료', '검토 중', '지연')})
                tags = _Tags(document).tags
                buttons = {attrs.get('id') for tag, attrs in tags if tag == 'button'}
                self.assertTrue({'toggle-view', 'print', 'previous', 'next'} <= buttons)
                self.assertEqual(3, sum(tag == 'button' and 'data-scenario-choice' in attrs for tag, attrs in tags))
                self.assertEqual(2, sum(attrs.get('data-report-table') == 'interactive' for _, attrs in tags))
                # These controls are progressively created by the bundled table
                # controller; all 48 rows remain in the initial HTML without JS.
                for label in ('표 안에서 검색', '필터 열 선택', '필터 값 선택', '검색 결과 CSV', '전체 CSV', '한 페이지에 표시할 행 수'):
                    self.assertIn(label, document)
                self.assertIn('가상 자료', document)
                self.assertIn('data-view="scroll"', document)

    def test_thumbnails_are_the_same_cover_with_resolved_numbers(self):
        for style, preview in self.previews.items():
            with self.subTest(style=style):
                self.assertEqual(_kpis(self.documents[style]), _kpis(preview))
                self.assertEqual(_first_section(self.documents[style]), _first_section(preview))
                self.assertEqual(1, len(re.findall(r'<section\b', preview)))
                self.assertNotRegex(preview, r'<(?:script|button|input|select)\b')
                self.assertNotIn('{{fact:', preview)

    def test_both_shipped_families_match_actual_rendered_content_and_controllers(self):
        for style, document in self.documents.items():
            for base in ('company-agent-plugin/skills', 'standalone-skills'):
                with self.subTest(style=style, base=base):
                    shipped = ROOT / base / 'html-report/assets/examples' / ('style-' + style + '.html')
                    self.assertTrue(shipped.is_file(), str(shipped))
                    packaged = shipped.read_text(encoding='utf-8')
                    self.assertIn(f'<body data-style="{style}"', packaged)
                    self.assertEqual(_main_and_after(document), _main_and_after(packaged))

    def test_each_picker_card_has_its_source_and_complete_local_example(self):
        for style in self.styles:
            with self.subTest(style=style):
                card = re.search(r'<article class="design-card" id="design-' + re.escape(style) + r'">(.*?)</article>', self.picker, re.S)
                self.assertIsNotNone(card)
                content = card.group(1)
                tags = _Tags(content).tags
                links = {attrs.get('href'): attrs for tag, attrs in tags if tag == 'a'}
                self.assertIn('examples/style-' + style + '.html', links)
                self.assertIn(SOURCES[style]['url'], links)
                self.assertIn('noopener', links[SOURCES[style]['url']]['rel'].split())
                self.assertIn(SOURCES[style]['applied'], content)
                self.assertIn(SOURCES[style]['use'], content)
                self.assertEqual(1, sum(tag == 'button' and attrs.get('data-choice') == style for tag, attrs in tags))
                self.assertTrue(any('inert' in attrs and attrs.get('aria-hidden') == 'true' for _, attrs in tags))
        copied = self.folder / 'copied-picker.html'
        result = artifacts.html_designs(copied)
        self.assertTrue(result['ok'], result)
        links = {attrs.get('href') for tag, attrs in _Tags(copied.read_text(encoding='utf-8')).tags if tag == 'a'}
        examples = ROOT / 'company-agent-plugin/skills/html-report/assets/examples'
        for style in self.styles:
            self.assertIn((examples / ('style-' + style + '.html')).as_uri(), links)

    def test_generated_scripts_have_exact_csp_hashes_and_no_remote_loading(self):
        scripts = set()
        for style, document in self.documents.items():
            with self.subTest(style=style):
                script_parts = re.findall(r'<script>(.*?)</script>', document, re.S)
                self.assertEqual(1, len(script_parts))
                script = script_parts[0]
                scripts.add(script)
                digest = base64.b64encode(hashlib.sha256(script.encode('utf-8')).digest()).decode('ascii')
                tags = _Tags(document).tags
                csp = next(attrs['content'] for tag, attrs in tags
                           if tag == 'meta' and attrs.get('http-equiv') == 'Content-Security-Policy')
                directives = dict(part.strip().split(None, 1) for part in csp.split(';') if part.strip())
                self.assertEqual("'sha256-" + digest + "'", directives['script-src'])
                self.assertEqual("'none'", directives['default-src'])
                for tag, attrs in tags:
                    for attr in ('src', 'href'):
                        self.assertFalse(re.match(r'(?i)^(?:https?:)?//', attrs.get(attr, '')), (tag, attrs))
                self.assertNotRegex(document, r'(?i)@import|url\(\s*[\'"]?(?:https?:)?//|\bfetch\(|XMLHttpRequest')
                self.assertNotIn(SOURCES[style]['url'], document)
        # Only visuals differ; the same content gets the same working controller.
        self.assertEqual(1, len(scripts))
        for mocked in self.network:
            mocked.assert_not_called()

    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed to parse the emitted controller')
    def test_emitted_controller_is_valid_javascript(self):
        script = re.search(r'<script>(.*?)</script>', self.documents[self.styles[0]], re.S).group(1)
        result = subprocess.run([shutil.which('node'), '--check'], input=script,
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == '__main__':
    unittest.main()
