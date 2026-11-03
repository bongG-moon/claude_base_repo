import copy
import base64
import hashlib
import json
import re
import shutil
import subprocess
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
                expected = 'embedded_not_rendered' if choice in ('noto-sans-kr', 'pretendard', 'auto') else 'not_verified'
                self.assertEqual(result['typography']['availability'], expected)
                if expected == 'embedded_not_rendered':
                    raw = base64.b64decode(re.search(r'data:font/woff2;base64,([A-Za-z0-9+/=]+)', doc).group(1))
                    name, _ = fonts.BUNDLED[result['typography']['family']]
                    self.assertEqual(raw, (fonts.font_directory() / name).read_bytes())
                    self.assertIn('font-src data:', doc)
                    self.assertIn('SIL OPEN FONT LICENSE', doc)

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

    def test_default_without_font_choice_applies_and_reports_embedded_family(self):
        for style, family in (('minimalism', 'Noto Sans KR'), ('bento-grid', 'Pretendard')):
            result = create_html({**self.spec, 'style': style}, self.output.with_name(style + '.html'))
            self.assertTrue(result['ok'], result)
            self.assertEqual(family, result['typography']['family'])
            self.assertEqual('bundled', result['typography']['source'])
            self.assertFalse(any('PC 설치' in warning for warning in result['warnings']))

    def test_explicit_system_font_remains_system_and_template_stays_intact(self):
        result = create_html({**self.spec, 'fontChoice': 'pretendard', 'fontSource': 'system'}, self.output)
        self.assertEqual('system', result['typography']['source'])
        self.assertNotIn('data:font/woff2', self.output.read_text(encoding='utf-8'))
        self.assertEqual('', fonts.css({'fontChoice': 'auto', 'referenceCss': 'body{font-family:serif}'}))

    def test_bundled_files_match_provenance_and_portable_copy(self):
        folder = fonts.font_directory()
        manifest = json.loads((folder / 'SOURCE.json').read_text(encoding='utf-8'))
        root = Path(__file__).resolve().parents[1]
        for row in manifest['fonts']:
            raw = (folder / row['file']).read_bytes()
            self.assertEqual(b'wOF2', raw[:4])
            self.assertEqual(row['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(raw, (root / 'standalone-skills/html-report/assets/fonts' / row['file']).read_bytes())

    def test_reference_heading_font_is_preserved_without_an_extra_choice(self):
        for field in ('referenceStyle', 'themeOverrides'):
            spec = {field: {'typography': {'headingFont': 'Georgia'}}, 'fontChoiceRequired': True}
            self.assertEqual('template', fonts.selection(spec)['source'])
            self.assertEqual('', fonts.css(spec))
            self.assertEqual([], fonts.missing(spec))

    def test_explicit_bundled_rejects_fonts_not_shipped(self):
        for choice in ({'fontChoice': 'nanum-square-neo'}, {'fontChoice': 'custom', 'fontName': 'Missing Font'}):
            result = create_html({**self.spec, **choice, 'fontSource': 'bundled'}, self.output)
            self.assertEqual('invalid_font', result['code'])

    @unittest.skipUnless(shutil.which('node'), 'Node needed for font preview selection')
    def test_picker_font_changes_visible_preview_without_replacing_other_choices(self):
        from company_agent.report_styles import PICKER_JS
        fixture = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
function element(value='keep'){return {value,options:[{text:'기존 선택 유지'}],selectedIndex:0,handlers:{},dataset:{},attrs:{},style:{setProperty(k,v){this[k]=v}},addEventListener(k,f){this.handlers[k]=f},setAttribute(k,v){this.attrs[k]=v}}}
const ids={};for(const id of ['length-choice','mode-choice','font-choice','font-name','font-preview-status','choice-result','copy-status','additional-designs','selected-design','copy-choice'])ids[id]=element();
const previews=['minimalism','bento-grid'].map(style=>{const p=element();p.dataset.style=style;return p});
const context={document:{getElementById:id=>ids[id],querySelectorAll:s=>s==='.style-preview'?previews:[]},location:{hash:''},window:{addEventListener(){}},navigator:{}};
'''
        checks = r'''
assert.equal(previews[0].dataset.fontPreview,'Noto Sans KR');
assert.equal(previews[1].dataset.fontPreview,'Pretendard');
ids['font-choice'].value='pretendard';ids['font-choice'].options=[{text:'Pretendard'}];ids['font-choice'].handlers.change();
for(const p of previews)assert.equal(p.dataset.fontPreview,'Pretendard');
assert.ok(previews[0].style['--preview-font'].startsWith('"Pretendard"'));
assert.equal(ids['mode-choice'].value,'keep');assert.equal(ids['length-choice'].value,'keep');
ids['font-choice'].value='custom';ids['font-name'].value='맑은 고딕';ids['font-choice'].handlers.change();
assert.equal(previews[1].dataset.fontPreview,'맑은 고딕');
assert.ok(ids['font-preview-status'].textContent.includes('대체 글꼴'));
'''
        run = subprocess.run(['node', '-e', fixture + '\nvm.runInNewContext(' + json.dumps(PICKER_JS) + ',context);\n' + checks],
                             capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(0, run.returncode, run.stderr)


if __name__ == '__main__':
    unittest.main()
