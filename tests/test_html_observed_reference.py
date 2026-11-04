"""Reference roles must change generated elements, while data stays newly authored."""
import copy
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business_artifacts as artifacts, html_reference


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.styles, self.elements, self.in_style = [], [], False
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))
        if tag == 'style':
            self.in_style = True

    def handle_endtag(self, tag):
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data)

    @property
    def css(self):
        return '\n'.join(self.styles)


class HtmlObservedReferenceTests(unittest.TestCase):
    def test_short_explicit_palette_does_not_leak_the_third_preset_color(self):
        from company_agent import report_styles
        css=report_styles.reference_style_css({'colors':{'series':['134E4A','C8892E']}})
        self.assertIn('--series-2:#134E4A',css)
        self.assertIn('--series-29:#C8892E',css)
        css=report_styles.reference_style_css({'colors':{'secondary':'C8892E'},'chart':{'seriesColors':['134E4A']}})
        self.assertIn('--series-1:#134E4A',css)
        self.assertNotIn('--series-1:#C8892E',css)
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = {
            'colors': {'bg':'#FAF5EE', 'surface':'#FFFFFF', 'text':'#203040', 'muted':'#556677',
                       'primary':'#713D52', 'secondary':'#2F7185', 'border':'#C5A684', 'tint':'#F3E5D8',
                       'series':['#713D52','#2F7185','#D5A76B']},
            'typography': {'headingFont':'Batang', 'bodyFont':'Pretendard', 'titleSize':44, 'bodySize':19, 'captionSize':13},
            'spacing': {'outer':38, 'gap':23, 'radius':9},
            'table': {'headerFill':'#713D52', 'headerText':'#FFFFFF', 'bodyFill':'#FFFAF4',
                      'bodyText':'#203040', 'alternateFill':'#F3E5D8', 'borderColor':'#C5A684',
                      'borderWidth':2, 'headerBold':False, 'fontSize':17, 'align':'center', 'padding':15},
            'chart': {'seriesColors':['#713D52','#2F7185','#D5A76B'], 'legendPosition':'top',
                      'fontSize':14, 'labelSize':15, 'gridColor':'#C5A684', 'showGrid':False, 'marker':'diamond', 'lineWidth':4},
            'patterns': {'writing':'요약과 근거를 분리하고 새 내용으로 작성'},
            'evidence': [{'source':'reference-1.png','scope':'전체 화면','observed':['제목과 본문은 다른 글꼴']},
                         {'source':'reference-2.html','scope':'표','uncertain':['정확한 글꼴 설치 여부']}],
        }
        self.spec = {'title':'새 보고서', 'length':'short', 'mode':'scroll', 'referenceStyle':self.profile,
                     'sections':[{'title':'새 내용', 'body':'직접 작성한 분석', 'takeaway':'두 색상으로 비교합니다.',
                                  'chart':{'type':'line','categories':['가','나'],
                                           'series':[{'name':'실적','values':[3,4]},{'name':'계획','values':[2,5]}]},
                                  'table':{'headers':['항목','값'],'rows':[['새 항목',3],['다음 항목',4]]}}]}

    def create(self, spec=None, filename='report.html'):
        path = self.root / filename
        result = artifacts.create_html(self.spec if spec is None else spec, path, require_choices=True)
        self.assertTrue(result['ok'], result)
        source = path.read_text(encoding='utf-8')
        return result, source, Document(source)

    def test_observed_combination_changes_rendered_css_and_chart_shapes(self):
        before = copy.deepcopy(self.spec)
        with patch.object(artifacts, 'open_local_preview') as opened:
            result, source, doc = self.create()
            opened.assert_not_called()
        self.assertEqual(before, self.spec)
        self.assertEqual('minimalism', result['style'])
        for token in ('--accent:#713D52', '--secondary:#2F7185', '--series-1:#2F7185',
                      '--heading-font:"Batang"', '--body-font:"Pretendard"', 'font-size:44px',
                      'font-size:19px', 'padding:38px', 'gap:23px', '--section-radius:9px',
                      '--table-head-fill:#713D52', '--table-head-text:#FFFFFF', '--table-body-fill:#FFFAF4',
                      '--table-alternate-fill:#F3E5D8', '--table-border-width:2px', '--table-head-weight:400',
                      '--table-font-size:17px', '--table-padding:15px', '--table-align:center',
                      '--chart-line-width:4', '.gridline{display:none}', '.legend{order:-1'):
            self.assertIn(token, doc.css)
        self.assertTrue(any(tag == 'path' and 'l5,5 -5,5 -5,-5 Z' in attrs.get('d','') for tag, attrs in doc.elements))
        self.assertTrue(any(tag == 'polyline' and attrs.get('stroke','').startswith('var(--series-1,') for tag, attrs in doc.elements))
        self.assertIn('data-reference-style="observed"', source)
        self.assertNotIn('reference-1.png', source)
        self.assertNotIn('정확한 글꼴 설치 여부', source)
        self.assertFalse(any(tag == 'link' for tag, _ in doc.elements))

    def test_explicit_role_changes_do_not_reset_other_observed_choices(self):
        spec = copy.deepcopy(self.spec)
        spec.update(style='editorial', fontChoice='custom', fontName='맑은 고딕',
                    themeOverrides={'colors':{'primary':'#112233'}, 'table':{'padding':11}})
        normalized = artifacts._normalize(spec, html_tables=True)
        self.assertEqual('112233', normalized['themeOverrides']['colors']['primary'])
        self.assertEqual('2F7185', normalized['themeOverrides']['colors']['secondary'])
        self.assertEqual(11, normalized['themeOverrides']['table']['padding'])
        self.assertEqual('713D52', normalized['themeOverrides']['table']['headerFill'])
        _, source, doc = self.create(spec)
        self.assertIn('--accent:#112233', doc.css)
        self.assertIn('--series-0:#713D52', doc.css)
        self.assertIn('--secondary:#2F7185', doc.css)
        self.assertGreater(doc.css.rfind('--heading-font:"맑은 고딕"'), doc.css.rfind('--heading-font:"Batang"'))
        self.assertIn('data-style="editorial"', source)

    def test_choices_keep_reference_and_skip_reasking_design_or_known_font(self):
        spec = {'referenceStyle':self.profile,'length':'detailed','mode':'both','fontChoiceRequired':True,'fontChoice':'auto'}
        ready = artifacts.html_choices(spec)
        self.assertTrue(ready['ok'], ready)
        self.assertEqual(self.profile['evidence'], ready['selection']['referenceStyle']['evidence'])
        pending = artifacts.html_choices({'referenceStyle':self.profile})
        self.assertEqual('format', pending['stage'])
        self.assertEqual(['length','mode'], pending['missing'])
        self.assertIn('referenceStyle', pending['preservedChoices'])

    def test_auto_font_keeps_reference_fonts_and_scripts_are_not_accepted(self):
        spec = {**self.spec, 'fontChoice':'auto', 'fontSource':'system'}
        result, _, doc = self.create(spec)
        self.assertIsNone(result['typography']['family'])
        self.assertIn('--heading-font:"Batang"', doc.css)
        for invalid in ({'typography':{'bodyFont':'x;}</style><script>alert(1)</script>'}},
                        {'colors':{'primary':'url(https://invalid.example)'}},
                        {'chart':{'marker':'<script>'}}, {'spacing':{'outer':float('inf')}}):
            invalid_spec = {**self.spec, 'referenceStyle':invalid}
            response = artifacts.create_html(invalid_spec, self.root/'rejected.html')
            self.assertEqual('invalid_reference_style', response['code'])
            self.assertFalse((self.root/'rejected.html').exists())

    def test_table_controls_and_accessible_source_survive_reference_styling(self):
        _, source, doc = self.create()
        self.assertTrue(any(attrs.get('data-report-table') == 'interactive' for _, attrs in doc.elements))
        self.assertTrue(any(attrs.get('class') == 'table-wrap' and attrs.get('tabindex') == '0' for _, attrs in doc.elements))
        for text in ('표 안에서 검색', 'filterColumn', '전체 CSV', '차트 수치 원자료 펼치기', 'URL.createObjectURL'):
            self.assertIn(text, source)
        self.assertIn('.report-data-table thead th{background:var(--table-head-fill', doc.css)
        self.assertIn('.report-data-table tbody tr:nth-child(even){background:var(--table-alternate-fill', doc.css)

    def test_native_html_extracts_full_palette_and_semantic_table_roles_only(self):
        path = self.root/'reference.html'
        path.write_text('''<html><style>
        :root{--accent:#713d52;--secondary:#2f7185;--series-0:#111111;--series-1:#222222;--series-7:#777777}
        body{font-family:"Pretendard",sans-serif;font-size:19px}
        h2{font-family:Batang;font-size:44px}.section{padding:38px;border-radius:9px}
        thead th{background:#713d52;color:#fff;font-weight:400;padding:15px}
        tbody td{background:#fffaf4;color:#203040;border-bottom:2px solid #c5a684}
        tbody tr:nth-child(even){background:#f3e5d8}
        .status-warning{--secondary:#ff0000;background:#ff0000}
        th:hover{background:#ff0000} body[data-theme=dark]{--series-1:#ff0000}
        </style><body>source secret<table><tr><td>secret row</td></tr></table><script>fetch('bad')</script></body></html>''',encoding='utf-8')
        analyzed = html_reference.analyze(path)
        self.assertEqual('#777777', analyzed['tokens']['series-7'])
        self.assertEqual('#2f7185', analyzed['tokens']['secondary'])
        self.assertEqual('#713d52', analyzed['tokens']['tableHeaderFill'])
        self.assertEqual('2px', analyzed['tokens']['tableBorderWidth'])
        css = html_reference.theme_css(analyzed)
        self.assertIn('--series-0:#111111', css)
        self.assertNotIn('--series-0:#713d52', css)
        self.assertNotIn('#ff0000', css)
        preview = html_reference.inspect_template(path, self.root/'reference-preview.html')
        self.assertTrue(preview['ok'], preview)
        selected = preview['htmlTemplate']
        review = {**preview['templateReview'], 'confirmed': True}
        spec = {key:value for key,value in self.spec.items() if key != 'referenceStyle'}
        result = artifacts.create_html({**spec,'htmlTemplate':selected,'templateReview':review}, self.root/'native.html')
        self.assertTrue(result['ok'], result)
        source = (self.root/'native.html').read_text(encoding='utf-8')
        self.assertIn('--table-head-fill:#713d52', source)
        self.assertIn('data-reference-style="observed"', source)
        self.assertNotIn('source secret', source)
        self.assertNotIn("fetch('bad')", source)


if __name__ == '__main__':
    unittest.main()
