"""Request-only diagram output through the existing safe artifact pipeline."""
import base64
import copy
import hashlib
from html import unescape
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business_artifacts as artifacts, artifact_delivery, ppt_html
from local_app import html_preview


class ExplanationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec = json.loads((ROOT / 'company-agent-plugin/templates/business/explanation.spec.json').read_text(encoding='utf-8'))

    def build(self, spec=None, name='explanation.html'):
        output = self.root / name
        result = artifacts.create_html(spec or self.spec, output, require_choices=True)
        self.assertTrue(result['ok'], result)
        return result, output.read_text(encoding='utf-8')

    def test_full_document_offline_csp_and_unique_ids(self):
        self.spec['sections'].append(copy.deepcopy(self.spec['sections'][0]))
        result, page = self.build()
        self.assertTrue(result['offline'])
        self.assertIn('id="explanation-1"', page)
        self.assertIn('id="explanation-2"', page)
        # data-node-id is not a DOM id.
        ids = re.findall(r'(?<![-\w])id="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)))
        script, = re.findall(r'<script>(.*?)</script>', page, re.S)
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        self.assertIn("script-src 'sha256-" + digest + "'", unescape(page))
        self.assertNotIn('unsafe-eval', page)
        self.assertNotRegex(page, r'<(?:script|link|img)[^>]+(?:src|href)="https:')
        self.assertIn('data-diagram-target="explanation-1" hidden', page)
        self.assertIn('body:not(.diagram-report-ready)', page)
        self.assertIn('max-height:230mm', page)
        self.assertIn('.section.has-diagram{break-inside:auto}', page)
        self.assertIn('실제 작업을 다시 실행하지 않습니다', page)

    def test_google_font_is_explicit_and_has_fixed_network_scope(self):
        self.spec['fontSource'] = 'google'
        result, page = self.build()
        self.assertFalse(result['offline'])
        self.assertIn('https://fonts.googleapis.com/css2?family=Noto+Sans+KR', page)
        self.assertIn('font-src https://fonts.gstatic.com', page)
        self.assertIn('PC 글꼴', page)
        self.assertTrue(any('Google Fonts' in v for v in result['warnings']))
        for invalid in ('https://evil.invalid/font', True, {}):
            self.spec['fontSource'] = invalid
            blocked = artifacts.create_html(self.spec, self.root/'invalid.html')
            self.assertEqual(blocked['code'], 'invalid_font_source')
            self.assertFalse((self.root/'invalid.html').exists())

    def test_bad_graph_fails_without_partial_output(self):
        self.spec['sections'][0]['diagram']['edges'][0]['to'] = 'missing'
        result = artifacts.create_html(self.spec, self.root/'bad.html')
        self.assertEqual(result['code'], 'invalid_diagram')
        self.assertFalse((self.root/'bad.html').exists())

    def test_static_workspace_preview_retains_multiline_svg_and_no_active_controls(self):
        _, page = self.build()
        preview = html_preview.render(page)
        self.assertIn('<desc', preview)
        self.assertIn('dy="0"', preview)
        self.assertIn('data-diagram-target="explanation-1" hidden=""', preview)
        self.assertNotIn('<script', preview)
        self.assertIn('script-src &#x27;none&#x27;', preview)
        self.assertIn('가상 예시', preview)
        self.assertNotIn('href=', preview)

    def test_ordinary_report_has_no_diagram_js_css_or_font_requests(self):
        spec = {'title':'일반 보고', 'style':'minimalism', 'mode':'scroll', 'length':'short', 'sections':[{'title':'요약','body':'간단한 글'}]}
        _, page = self.build(spec)
        for token in ('explanation-', 'diagram-export', 'googleapis', 'google_font', 'XMLSerializer'):
            self.assertNotIn(token, page)
        self.assertEqual(re.findall(r'<script>(.*?)</script>', page, re.S), [artifacts._JS])

    def test_one_final_file_existing_lifecycle(self):
        project = self.root/'사용자 작업'
        project.mkdir()
        state = self.root/'state'
        result = artifact_delivery.start(state, project/'설명.html')
        self.assertTrue(result['ok'], result)
        work = result['workFile']
        built = artifact_delivery.build(state, work, 'html', self.spec)
        self.assertTrue(built['ok'], built)
        self.assertEqual([], list(project.iterdir()))
        final = artifact_delivery.publish(state, work)
        self.assertTrue(final['ok'], final)
        self.assertEqual([project/'설명.html'], list(project.iterdir()))
        self.assertNotIn('.png', ' '.join(p.name for p in project.iterdir()))

    def test_ppt_never_silently_discards_diagram(self):
        with self.assertRaises(artifacts.ArtifactError) as caught:
            ppt_html.prepare(self.spec)
        self.assertEqual(caught.exception.code, 'diagram_html_only')
        result = artifacts.create_ppt(self.spec, self.root/'explanation.pptx')
        self.assertEqual(result['code'], 'diagram_html_only')
        self.assertFalse((self.root/'explanation.pptx').exists())

    def test_existing_ppt_purpose_is_free_text(self):
        # PPT already uses purpose for business purpose, not diagram mode.
        data = artifacts._normalize({'purpose':'임원 보고', 'slides':[{'title':'요약'}]})
        self.assertEqual(data['sections'][0]['title'], '요약')


if __name__ == '__main__':
    unittest.main()
