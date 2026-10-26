"""Reference choices must survive selection and change actual offline output."""
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business_artifacts as artifacts, report_styles as styles


def example():
    return {
        'title': '교육 신청 분석', 'length': 'standard', 'mode': 'scroll',
        'fontChoice': 'noto-sans-kr',
        'facts': [{'id': 'total', 'op': 'sum', 'inputs': [{'table': [1, 0, 1]}, {'table': [1, 1, 1]}], 'expected': 30}],
        'sections': [
            {'title': '신청은 어디에 모였나요?', 'body': '확인한 신청자는 {{fact:total}}명입니다.'},
            {'title': '두 회차를 비교했습니다', 'body': '회차 B의 신청자가 더 많습니다.',
             'table': {'headers': ['회차', '신청자'], 'rows': [['A', 10], ['B', 20]]}},
            {'title': '확인할 조건', 'body': '신청만 집계했으며 수료 실적은 포함하지 않았습니다.'},
        ],
    }


class HtmlReferencePresetsTests(unittest.TestCase):
    def test_all_references_resolve_without_another_design_question(self):
        for key, _, _, default in styles.REFERENCE_PRESETS:
            spec = {'referencePreset': key, 'length': 'detailed', 'mode': 'scroll', 'fontChoice': 'noto-sans-kr'}
            before = copy.deepcopy(spec)
            with patch.object(artifacts, '_source', side_effect=AssertionError('no asset reads for choices')):
                result = artifacts.html_choices(spec)
                recorded = artifacts.html_choice_selection(spec, metadata_only=True)
            self.assertEqual('ready', result['stage'], result)
            self.assertEqual(key, recorded['referencePreset'])
            self.assertEqual(default, recorded['style'])
            self.assertEqual('noto-sans-kr', recorded['fontChoice'])
            self.assertEqual(before, spec)

    def test_explicit_theme_and_format_are_preserved(self):
        spec = {'referencePreset': 'reference-3', 'style': 'glassmorphism',
                'length': 'short', 'mode': 'scroll', 'fontChoice': 'custom', 'fontName': '맑은 고딕'}
        result = artifacts.html_choices(spec)
        self.assertEqual('ready', result['stage'], result)
        for key, value in spec.items():
            self.assertEqual(value, result['selection'][key])
        pending = artifacts.html_choices({'referencePreset': 'reference-1', 'length': 'short', 'fontChoice': 'auto'})
        self.assertEqual(['mode'], pending['missing'])
        self.assertEqual('format', pending['stage'])

    def test_reference_name_and_menu_numbers_do_not_collide(self):
        for index, (key, _, _, default) in enumerate(styles.REFERENCE_PRESETS, 5):
            for chosen in ({'style': '레퍼런스 ' + key[-1]}, {'style': str(index) + '번', 'designMenu': 'initial'}, {'style': index, 'designMenu': 'initial'}):
                result = artifacts.html_choices({**chosen, 'length': 'short', 'mode': 'scroll'})
                self.assertEqual(key, result['selection']['referencePreset'], result)
                self.assertEqual(default, result['selection']['style'])
        ordinary = artifacts.html_choices({'designMenu': 'additional', 'style': '5', 'length': 'short', 'mode': 'scroll'})
        self.assertEqual('neumorphism', ordinary['selection']['style'])
        self.assertNotIn('referencePreset', ordinary['selection'])

    def test_invalid_reference_never_reads_assets_or_publishes(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(artifacts, '_source', side_effect=AssertionError('no asset read')):
            for value in (None, 2, 'reference-4', '<script>'):
                spec = {**example(), 'referencePreset': value}
                spec['sections'][0]['image'] = {'path': 'absent.png'}
                output = Path(folder) / 'result.html'
                self.assertEqual('invalid_choice', artifacts.create_html(spec, output)['code'])
                self.assertFalse(output.exists())

    def test_reference_layouts_and_numeric_bindings_are_real_and_input_is_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            for key, _, _, default in styles.REFERENCE_PRESETS:
                spec = {**example(), 'referencePreset': key}
                before = copy.deepcopy(spec)
                output = Path(folder) / (key + '.html')
                result = artifacts.create_html(spec, output, require_choices=True)
                self.assertTrue(result['ok'], result)
                text = output.read_text(encoding='utf-8')
                self.assertIn('확인한 신청자는 30명입니다.', text)
                self.assertIn('data-style="' + default + '"', text)
                self.assertIn('data-reference="' + key + '"', text)
                middle = re.search(r'<section\b[^>]*id="section-2".*?</section>', text, re.S).group()
                if key == 'reference-1':
                    self.assertLess(middle.index('<table'), middle.index('회차 B의 신청자가'))
                    self.assertIn('data-content-layout="vertical"', middle)
                elif key == 'reference-2':
                    self.assertIn('class="reference-toc"', text)
                    self.assertEqual(['1', '2', '3'], re.findall(r'href="#section-(\d+)"', text))
                else:
                    self.assertIn('layout-split', middle)
                    self.assertIn('data-content-columns="2"', middle)
                self.assertEqual(before, spec)

    def test_explicit_section_layout_and_order_win(self):
        with tempfile.TemporaryDirectory() as folder:
            spec = {**example(), 'referencePreset': 'reference-3', 'style': 'editorial'}
            spec['sections'][1].update(layout='table', contentOrder=['body', 'table'], contentLayout='vertical')
            output = Path(folder) / 'explicit.html'
            result = artifacts.create_html(spec, output)
            self.assertTrue(result['ok'], result)
            text = output.read_text(encoding='utf-8')
            middle = re.search(r'<section\b[^>]*id="section-2".*?</section>', text, re.S).group()
            self.assertIn('layout-table', middle)
            self.assertLess(middle.index('회차 B의 신청자가'), middle.index('<table'))
            self.assertIn('data-style="editorial"', text)

    def test_toc_escapes_titles_and_does_not_appear_in_page_only_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            for mode in ('scroll', 'slides', 'both'):
                spec = {**example(), 'referencePreset': 'reference-2', 'mode': mode}
                spec['sections'][0]['title'] = '<img src=x onerror=alert(1)>'
                output = Path(folder) / (mode + '.html')
                self.assertTrue(artifacts.create_html(spec, output)['ok'])
                text = output.read_text(encoding='utf-8')
                self.assertNotIn('<img src=x', text)
                self.assertEqual(mode != 'slides', 'class="reference-toc"' in text)
                self.assertIn('body[data-view=slides] .reference-toc{display:none}', text)

    @unittest.skipUnless(shutil.which('node'), 'Node needed for picker event test')
    def test_picker_reference_buttons_emit_named_choices_without_resetting_existing_choices(self):
        setup = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
function element(value='keep'){return {value,options:[{text:'기존 선택 유지'}],selectedIndex:0,handlers:{},dataset:{},attrs:{},addEventListener(k,f){this.handlers[k]=f},setAttribute(k,v){this.attrs[k]=v}}}
const ids={};for(const id of ['length-choice','mode-choice','font-choice','font-name','choice-result','copy-status','additional-designs','selected-design','copy-choice'])ids[id]=element();
const buttons=[1,2,3].map(n=>{const b=element();b.dataset={choice:'reference-'+n,label:'레퍼런스 '+n};return b});
const context={document:{getElementById:id=>ids[id],querySelectorAll:s=>s==='[data-choice]'?buttons:[]},location:{hash:''},window:{addEventListener(){}},navigator:{}};
'''
        checks = r'''
for(const button of buttons){button.handlers.click();assert.ok(ids['choice-result'].value.includes(button.dataset.label));assert.ok(ids['choice-result'].value.includes('이미 정한 색상 스타일·글꼴·분량·보기 방식은 유지'));assert.equal(button.attrs['aria-pressed'],'true');assert.ok(!ids['choice-result'].value.includes('양식 파일을 받고'));}
ids['font-choice'].value='noto-sans-kr';ids['font-choice'].options=[{text:'Noto Sans KR'}];ids['font-choice'].handlers.change();assert.ok(ids['choice-result'].value.includes('글꼴: Noto Sans KR'));
'''
        run = subprocess.run(['node', '-e', setup + '\nvm.runInNewContext(' + json.dumps(styles.PICKER_JS) + ',context);\n' + checks], capture_output=True, text=True, timeout=10)
        self.assertEqual(0, run.returncode, run.stderr)


if __name__ == '__main__':
    unittest.main()
