"""HTML references are real offline reports, not decorative mockups."""
import copy
import hashlib
import base64
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business_artifacts as artifacts, report_gallery, report_interactions, report_styles


class ReferenceQualityTests(unittest.TestCase):
    def test_examples_use_real_renderer_and_have_valid_script_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            for key, *_ in report_styles.REFERENCE_PRESETS:
                spec = report_gallery.example_spec(key)
                before = copy.deepcopy(spec)
                output = Path(folder) / (key + '.html')
                result = artifacts.create_html(spec, output)
                self.assertTrue(result['ok'], result)
                self.assertEqual(before, spec)
                document = output.read_text(encoding='utf-8')
                scripts = re.findall(r'<script>(.*?)</script>', document, re.S)
                self.assertEqual(1, len(scripts))
                digest = base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
                self.assertIn('sha256-' + digest, document)
                self.assertIn('가상 자료', document)
                self.assertNotRegex(document, r'<(?:script|iframe)[^>]*src=|fetch\(|localStorage|@import')
                for base in ('company-agent-plugin/skills', 'standalone-skills'):
                    shipped = ROOT / base / 'html-report/assets/examples' / output.name
                    shipped_text = shipped.read_text(encoding='utf-8')
                    # Gallery pages share packaged font files; delivered reports
                    # embed just the chosen font. Content and controllers match.
                    self.assertEqual(document.split('<main class="report-main">', 1)[1],
                                     shipped_text.split('<main class="report-main">', 1)[1])
                    self.assertIn('../fonts/', shipped_text)
                    self.assertNotIn('data:font/woff2;base64,', shipped_text)

    def test_ordinary_reports_do_not_load_interactions_or_reference_observer(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'plain.html'
            self.assertTrue(artifacts.create_html({'sections': [{'title': '단순 보고', 'body': '내용'}]}, output)['ok'])
            text = output.read_text(encoding='utf-8')
            self.assertNotIn('data-report-scenarios', text)
            self.assertNotIn('IntersectionObserver', text)
            self.assertNotIn('closedBeforePrint', text)

    def test_details_only_receive_print_restore_and_fact_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'detail.html'
            spec = {'facts': [{'id': 'count', 'op': 'value', 'inputs': [12]}],
                    'sections': [{'title': '근거', 'details': [{'title': '범위', 'body': '{{fact:count}}건'}]}]}
            self.assertTrue(artifacts.create_html(spec, output)['ok'])
            text = output.read_text(encoding='utf-8')
            self.assertIn('12건', text)
            self.assertIn('closedBeforePrint', text)

    def test_invalid_interactions_leave_previous_result_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'keep.html'
            output.write_text('previous', encoding='utf-8')
            result = artifacts.create_html({'sections': [{'title': '검증', 'scenarios': {'items': []}}]}, output)
            self.assertFalse(result['ok'])
            self.assertEqual('output_exists', result['code'])
            self.assertEqual('previous', output.read_text(encoding='utf-8'))
            fresh = Path(folder) / 'new.html'
            result = artifacts.create_html({'sections': [{'title': '검증', 'scenarios': {'items': []}}]}, fresh)
            self.assertEqual('invalid_interaction', result['code'])
            self.assertFalse(fresh.exists())

    def test_unknown_fact_in_a_scenario_is_not_silently_published(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'bad-fact.html'
            spec = report_gallery.example_spec('reference-1')
            spec['sections'][1]['scenarios']['items'][0]['output'] = '{{fact:missing}}건'
            result = artifacts.create_html(spec, output)
            self.assertEqual('numeric_validation_failed', result['code'])
            self.assertFalse(output.exists())

    def test_explicit_content_order_precedes_optional_explanations(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'order.html'
            row = {'title': '설명', 'body': '본문', 'table': {'headers': ['상태'], 'rows': [['확인']]},
                   'contentOrder': ['table', 'body'], 'details': [{'title': '근거 확인', 'body': '원자료 기준'}]}
            self.assertTrue(artifacts.create_html({'referencePreset': 'reference-1', 'sections': [row]}, output)['ok'])
            text = output.read_text(encoding='utf-8').split('<main class="report-main">', 1)[1]
            self.assertLess(text.index('<table'), text.index('data-content-block="body"'))
            self.assertLess(text.index('data-content-block="body"'), text.index('class="report-detail"'))

    def test_picker_has_shipped_full_examples_and_copied_links_resolve(self):
        picker = report_styles.picker_html()
        for key, *_ in report_styles.REFERENCE_PRESETS:
            self.assertIn('href="examples/' + key + '.html"', picker)
        with tempfile.TemporaryDirectory() as folder:
            result = artifacts.html_designs(Path(folder) / 'copied.html')
            self.assertTrue(result['ok'], result)
            text = Path(result['outputPath']).read_text(encoding='utf-8')
            base = (ROOT / 'company-agent-plugin/skills/html-report/assets/examples').as_uri()
            self.assertIn(base + '/reference-1.html', text)


if __name__ == '__main__':
    unittest.main()
