import copy
import html
import json
from pathlib import Path
import sys
import tempfile
import unittest
import re
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import ppt_deck_source as module
from company_agent.business_artifacts import ArtifactError


class NativeDeckSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '수정 발표.html'
        self.palette = dict(title='17324D', accent='087F8C', text='30465B',
                            muted='52667C', background='FFFFFF', tint='EEF4F7')
        self.plan = dict(width=960, height=540, font='Malgun Gothic', theme=self.palette, pages=[{
            'title': '원래 제목', 'background': 'FFFFFF', 'notes': '설명 메모', 'source': '가상 자료',
            'elements': [
                dict(kind='text', x=40, y=25, w=800, h=40, text='원래 제목', size=26),
                dict(kind='text', x=40, y=100, w=800, h=40, text='강조 본문', size=20,
                     runs=[{'text': '강조', 'bold': True}, {'text': ' 본문', 'color': '087F8C'}]),
                dict(kind='table', x=40, y=180, w=400, h=100,
                     table={'headers': ['항목', '건수'], 'rows': [['등록', '15']]}),
                dict(kind='chart', x=470, y=180, w=400, h=280,
                     chart={'type': 'column', 'categories': ['A', 'B'],
                            'series': [{'name': '실적', 'values': [15, 20]}]}),
            ]}])
        self.body = ('<div class="ppt-slide active" data-slide="P01" data-title="원래 제목">'
                     '<div data-edit="p0-e0" data-deck-title="true">새 제목</div>'
                     '<div><span data-edit="p0-e1-r0">변경</span><span data-edit="p0-e1-r1"> 본문</span></div>'
                     '<table><tr><th data-edit="p0-e2-c0-0">항목</th><th data-edit="p0-e2-c0-1">건수</th></tr>'
                     '<tr><td data-edit="p0-e2-c1-0">확인</td><td data-edit="p0-e2-c1-1">22</td></tr></table>'
                     '<svg><path d="M0 0 L1 1"/></svg></div>')

    def document(self, body=None, plan=None):
        payload = json.dumps(plan or self.plan, ensure_ascii=True).replace('<', '\\u003c')
        return ('<!doctype html><html><head><meta name="ppt-deck-format" content="editable-scene-v1">'
                '<script id="company-agent-ppt-scene" type="application/json">' + payload + '</script>'
                '<script>throw Error("source-must-not-run")</script></head><body data-ppt-deck="1">'
                + (body or self.body) + '</body></html>')

    def read(self, body=None, plan=None, document=None):
        self.path.write_text(document or self.document(body, plan), encoding='utf-8')
        return module.read_deck(self.path, self.palette)

    def test_current_text_runs_tables_and_title_preserve_native_chart_and_notes(self):
        with patch('company_agent.ppt_scene._image', side_effect=AssertionError('no image path')):
            result = self.read()
        page = result['pages'][0]
        self.assertEqual('새 제목', page['title'])
        self.assertEqual('새 제목', page['elements'][0]['text'])
        self.assertEqual('변경 본문', page['elements'][1]['text'])
        self.assertTrue(page['elements'][1]['runs'][0]['bold'])
        self.assertEqual('087F8C', page['elements'][1]['runs'][1]['color'])
        self.assertEqual(['확인', '22'], page['elements'][2]['table']['rows'][0])
        self.assertEqual(self.plan['pages'][0]['elements'][3]['chart'], page['elements'][3]['chart'])
        self.assertEqual(('설명 메모', '가상 자료'), (page['notes'], page['source']))
        self.assertNotIn('source', result)

    def test_plain_text_breaks_and_escaped_markup_do_not_execute(self):
        result = self.read(body=self.body.replace('새 제목', '첫째<br>둘째 &lt;img&gt;'))
        self.assertEqual('첫째\n둘째 <img>', result['pages'][0]['elements'][0]['text'])

    def test_browser_enter_blocks_do_not_add_phantom_trailing_line(self):
        result = self.read(body=self.body.replace('새 제목', '첫째<div>둘째</div>'))
        self.assertEqual('첫째\n둘째', result['pages'][0]['elements'][0]['text'])

    def test_missing_duplicate_unknown_and_nested_slots_are_rejected(self):
        cases = [self.body.replace('data-edit="p0-e0"', ''),
                 self.body.replace('새 제목</div>', '새 제목</div><div data-edit="p0-e0">중복</div>'),
                 self.body.replace('p0-e0', 'p0-e55'),
                 self.body.replace('새 제목', '<span data-edit="p0-e1-r0">중첩</span>')]
        for body in cases:
            with self.subTest(body=body), self.assertRaises(ArtifactError):
                self.read(body=body)

    def test_wrong_markers_order_and_malformed_metadata_are_rejected(self):
        source = self.document()
        cases = [source.replace('editable-scene-v1', 'unknown'),
                 source.replace('data-ppt-deck="1"', 'data-ppt-deck="0"'),
                 source.replace('data-slide="P01"', 'data-slide="P02"'),
                 source.replace('application/json', 'text/javascript'),
                 source.replace('"width": 960', '"width": true'),
                 source.replace('"text": "30465B"', '"text": "url(https://bad.invalid)"')]
        for document in cases:
            with self.subTest(document=document[:100]), self.assertRaises(ArtifactError):
                self.read(document=document)

    def test_external_image_path_is_rejected_before_open(self):
        plan = copy.deepcopy(self.plan)
        plan['pages'][0]['elements'].append(dict(kind='image', x=10, y=10, w=10, h=10,
                                                image={'path': 'C:/secret.png'}))
        with patch('company_agent.ppt_scene._image', side_effect=AssertionError('must not open')):
            with self.assertRaises(ArtifactError) as caught:
                self.read(plan=plan)
        self.assertEqual('invalid_native_deck', caught.exception.code)

    def test_dom_script_inside_text_slot_is_not_accepted(self):
        with self.assertRaises(ArtifactError):
            self.read(body=self.body.replace('새 제목', '<script>evil()</script>'))

    def test_size_is_bounded_before_parser(self):
        self.path.write_bytes(b'x' * 100)
        with patch.object(module, 'LIMIT', 99), self.assertRaises(ArtifactError) as caught:
            module.read_deck(self.path, self.palette)
        self.assertEqual('html_too_large', caught.exception.code)

    def test_real_default_seven_layouts_reimport_without_browser(self):
        from company_agent import ppt_html, ppt_html_import, ppt_layouts
        root = self.path.parent
        spec = {'title': '일곱 가지 가상 배치', 'creationMode': 'new', 'designPreset': 'business',
                'purpose': '합성 검사', 'audience': '검토자', 'slideCount': 7,
                'slides': ppt_layouts.examples(), 'presentationTheme': {'accent': '80452C'}}
        draft = ppt_html.create_draft(spec, root / '일곱장.html')
        self.assertTrue(draft['ok'], draft)
        original = ppt_html.prepare(spec)[0]['presentationPlan']
        plan = module.read_deck(draft['outputPath'], self.palette)
        self.assertEqual(7, len(plan['pages']))
        self.assertEqual('80452C', plan['theme']['accent'])
        for before, after in zip(original['pages'], plan['pages']):
            self.assertEqual([(e['kind'], e['x'], e['y'], e['w'], e['h']) for e in before['elements']],
                             [(e['kind'], e['x'], e['y'], e['w'], e['h']) for e in after['elements']])
        imported = {'title': spec['title'], 'creationMode': 'reference', 'purpose': '합성 검사',
                    'audience': '검토자', 'slideCount': 7,
                    'htmlSource': {'path': draft['outputPath'], 'nativeDeck': True}}
        with patch.object(ppt_html_import, 'browser_path', side_effect=AssertionError('no browser needed')):
            second = ppt_html.create_draft(imported, root / '검토본.html', require_choices=False)
        self.assertTrue(second['ok'], second)
        self.assertEqual('80452C', module.read_deck(second['outputPath'], self.palette)['theme']['accent'])

    def test_real_html_text_edits_roundtrip_to_native_chart_ppt(self):
        from company_agent import business_artifacts, ppt_html, ppt_html_import, ppt_layouts
        from pptx import Presentation
        root = self.path.parent
        extra = {'title': '원래 제목', 'notes': '가상 발표자 메모',
                 'elements': copy.deepcopy(self.plan['pages'][0]['elements'])}
        spec = {'title': '가상 편집 시험', 'creationMode': 'new', 'designPreset': 'business',
                'purpose': '합성 검사', 'audience': '검토자', 'slideCount': 8,
                'slides': [*ppt_layouts.examples(), extra], 'presentationTheme': {'accent': '80452C'}}
        first = ppt_html.create_draft(spec, root / '원본.html')
        self.assertTrue(first['ok'], first)
        document = Path(first['outputPath']).read_text(encoding='utf-8')
        # These are precisely the plain text slots changed by the UI; geometry,
        # source scene and generated JS remain unchanged in this test fixture.
        for identity, value in [('p7-e0', '새 제목'), ('p7-e1-r0', '변경'), ('p7-e2-c1-1', '22')]:
            pattern = r'(<(?:div|span|th|td)\b[^>]*data-edit="' + re.escape(identity) + r'"[^>]*>)([^<]*)(</(?:div|span|th|td)>)'
            document, count = re.subn(pattern, lambda m: m[1] + html.escape(value) + m[3], document)
            self.assertEqual(1, count, identity)
        self.path.write_text(document, encoding='utf-8')
        imported = {'title': '가상 편집 시험', 'creationMode': 'reference', 'purpose': '합성 검사',
                    'audience': '검토자', 'slideCount': 8,
                    'htmlSource': {'path': str(self.path), 'nativeDeck': True}}
        with patch.object(ppt_html_import, 'browser_path', side_effect=AssertionError('no browser needed')):
            preview = ppt_html.create_draft(imported, root / '편집-검토.html', require_choices=False)
            self.assertTrue(preview['ok'], preview)
            # Synthetic approval verifies the export contract, not real user consent.
            imported['designReview'] = {**preview['designReview'], 'confirmed': True}
            with patch.object(business_artifacts, '_office', return_value={'ok': False, 'code': 'not_requested'}):
                result = business_artifacts.create_ppt(imported, root / '검증.pptx', require_choices=True)
        self.assertTrue(result['ok'], result)
        deck = Presentation(root / '검증.pptx')
        self.assertEqual(8, len(deck.slides))
        last = deck.slides[-1]
        texts = [shape.text for shape in last.shapes if shape.has_text_frame]
        self.assertIn('새 제목', texts)
        self.assertIn('변경 본문', texts)
        chart = next(shape.chart for shape in last.shapes if shape.has_chart)
        self.assertEqual((15.0, 20.0), chart.series[0].values)
        table = next(shape.table for shape in last.shapes if shape.has_table)
        self.assertEqual('22', table.cell(1, 1).text)
        self.assertEqual(1, result['editability']['charts'])
        self.assertEqual(0, result['editability']['images'])
        self.assertEqual('80452C', module.read_deck(preview['outputPath'], self.palette)['theme']['accent'])


if __name__ == '__main__':
    unittest.main()
