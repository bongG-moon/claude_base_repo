import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent.business_artifacts import create_html, html_choices, html_choice_selection
from company_agent import report_typography as fonts


class ReportTypographyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'report.html'
        self.spec = {'title': '교육 신청 현황', 'style': 'minimalism', 'length': 'standard',
                     'mode': 'both', 'sections': [{'title': '신청 내역', 'body': '확인할 내용입니다.',
                     'table': {'headers': ['이름', '과정'], 'rows': [['가상 사용자', 'AI 교육']]}}]}

    def test_new_choices_ask_only_missing_font(self):
        spec = {k: self.spec[k] for k in ('style', 'length', 'mode')}
        spec['fontChoiceRequired'] = True
        result = html_choices(spec)
        self.assertEqual(result['missing'], ['fontChoice'])
        self.assertEqual(len(result['fontOptions']), 5)
        spec['fontChoice'] = 'pretendard'
        ready = html_choices(spec)
        self.assertEqual(ready['stage'], 'ready')
        self.assertEqual(ready['selection']['fontChoice'], 'pretendard')

    def test_known_font_survives_design_question(self):
        result = html_choices({'fontChoiceRequired': True, 'fontChoice': 'noto-sans-kr'})
        self.assertEqual(result['stage'], 'design')
        self.assertEqual(result['preservedChoices']['fontChoice'], 'noto-sans-kr')

    def test_custom_name_question_then_ready(self):
        spec = {'style': 'minimalism', 'length': 'short', 'mode': 'scroll', 'fontChoice': 'custom'}
        self.assertEqual(html_choices(spec)['missing'], ['fontName'])
        spec['fontName'] = '맑은 고딕'
        self.assertTrue(html_choices(spec)['ok'])

    def test_legacy_without_font_still_creates(self):
        self.assertTrue(create_html(self.spec, self.output, require_choices=True)['ok'])

    def test_new_job_waits_before_creating_file(self):
        self.spec['fontChoiceRequired'] = True
        result = create_html(self.spec, self.output)
        self.assertEqual(result['missing'], ['fontChoice'])
        self.assertFalse(self.output.exists())

    def test_each_choice_is_applied_to_text_and_svg_without_network(self):
        for choice in ('noto-sans-kr', 'pretendard', 'nanum-square-neo', 'auto', 'custom'):
            with self.subTest(choice=choice):
                spec = copy.deepcopy(self.spec)
                spec.update(fontChoiceRequired=True, fontChoice=choice)
                if choice == 'custom':
                    spec['fontName'] = '맑은 고딕'
                target = self.output.with_name(choice + '.html')
                result = create_html(spec, target)
                self.assertTrue(result['ok'], result)
                doc = target.read_text(encoding='utf-8')
                self.assertIn('font-family:"' + result['typography']['family'] + '"', doc)
                self.assertIn('textarea,h1,h2,h3,svg text)', doc)
                self.assertNotIn('<link', doc)
                self.assertTrue(result['offline'])
                self.assertEqual(result['typography']['availability'], 'not_verified')

    def test_auto_respects_template_or_uses_style(self):
        self.assertEqual(fonts.selection({'fontChoice': 'auto', 'style': 'bento-grid'})['family'], 'Pretendard')
        self.assertEqual(fonts.css({'fontChoice': 'auto', 'referenceCss': 'body{font-family:serif}'}), '')
        self.assertEqual(fonts.selection({'fontChoice': 'auto', 'fontSource': 'google'})['family'], 'Noto Sans KR')
        from company_agent.business_artifacts import _normalize, _CSS, _JS, _html_table
        from company_agent.report_design import render
        data = _normalize({**self.spec, 'fontChoice': 'auto', 'fontSource': 'system'})
        data['referenceCss'] = 'body{font-family:serif}'
        doc = render(data, _CSS, _JS, _html_table)
        self.assertIn('body{font-family:serif}', doc)
        self.assertNotIn('body,button,.explanation-diagram text{font-family:"Noto Sans KR"', doc)

    def test_google_is_explicit_and_never_silently_replaces_another_font(self):
        self.spec.update(fontChoice='pretendard', fontSource='google')
        self.assertEqual(create_html(self.spec, self.output)['code'], 'invalid_font')
        self.spec.update(fontChoice='noto-sans-kr')
        result = create_html(self.spec, self.output)
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['offline'])
        self.assertIn('https://fonts.googleapis.com', self.output.read_text(encoding='utf-8'))

    def test_font_injection_and_malformed_fields_rejected(self):
        for invalid in ({'fontChoice': []}, {'fontChoiceRequired': 'yes'}, {'fontName': 'oops'},
                        *({'fontChoice': 'custom', 'fontName': value} for value in
                          ('', '  ', 'x; background:url(https://x)', '</style>', 'a' * 81))):
            with self.subTest(invalid=invalid):
                self.assertFalse(html_choices({**self.spec, **invalid})['ok'])

    def test_selection_metadata_preserves_font_but_not_business_data(self):
        spec = {'fontChoiceRequired': True, 'fontChoice': 'custom', 'fontName': '맑은 고딕'}
        self.assertEqual(html_choice_selection(spec, metadata_only=True)['fontName'], '맑은 고딕')
        with self.assertRaises(Exception):
            html_choice_selection({**spec, 'sections': []}, metadata_only=True)


if __name__ == '__main__':
    unittest.main()
