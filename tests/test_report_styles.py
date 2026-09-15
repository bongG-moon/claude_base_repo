import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'company-agent-plugin/scripts'))
from company_agent import report_styles as styles, business_artifacts as artifacts, business


class ReportStylesTests(unittest.TestCase):
    def test_additional_selection_widgets_cover_all_eight_and_wait(self):
        pending=styles.choices({'designMenu':'additional','length':'detailed'})
        self.assertTrue(pending['waitForUser'])
        self.assertEqual(3,len(pending['selectionQuestion']['options']))
        labels=[]
        for question in pending['designQuestions']:
            self.assertFalse(question['multiSelect'])
            self.assertEqual(4,len(question['options']))
            labels.extend(option['label'] for option in question['options'])
        self.assertEqual([f'{i+1}. {row[1]}' for i,row in enumerate(styles.STYLES)],labels)
        self.assertEqual(['style'],pending['missing'])
        self.assertEqual({'length':'detailed'},pending['preservedChoices'])

    def test_initial_options_are_two_designs_and_disclosure(self):
        result=styles.choices({})
        self.assertEqual(4,len(result['initialDesignOptions']))
        self.assertEqual('추가 디자인(미리보기)',result['initialDesignOptions'][2])
        self.assertEqual('HTML 양식 직접 첨부',result['initialDesignOptions'][3])
        self.assertNotIn('뉴모피즘',json.dumps(result,ensure_ascii=False))
        self.assertEqual(['style'],result['missing'])
        self.assertEqual('design',result['stage'])
        self.assertNotIn('lengthOptions',result)
        self.assertNotIn('viewOptions',result)

    def test_sequence_resolves_extra_design_before_format(self):
        spec={}
        self.assertEqual('design',artifacts.html_choices(spec)['stage'])
        spec['designMenu']='additional'
        result=artifacts.html_choices(spec)
        self.assertEqual('design_detail',result['stage'])
        self.assertEqual(['style'],result['missing'])
        self.assertEqual([row[0] for row in styles.STYLES],[row['style'] for row in result['designOptions']])
        self.assertEqual(8,len(result['designOptions']))
        self.assertTrue(result['previewOptional'])
        self.assertNotIn('lengthOptions',result)
        self.assertNotIn('viewOptions',result)
        spec['style']='neumorphism'
        result=artifacts.html_choices(spec)
        self.assertEqual('format',result['stage'])
        self.assertEqual(['length','mode'],result['missing'])
        self.assertNotIn('designOptions',result)
        spec.update(length='detailed',mode='scroll')
        result=artifacts.html_choices(spec)
        self.assertEqual('ready',result['stage'])
        self.assertEqual({'style':'neumorphism','length':'detailed','mode':'scroll'},result['selection'])

    def test_reported_incident_preserves_detailed_scroll(self):
        spec={'designMenu':'additional','length':'detailed','mode':'scroll'}
        before=dict(spec)
        result=artifacts.html_choices(spec)
        self.assertEqual(before,spec)
        self.assertEqual('design_detail',result['stage'])
        self.assertEqual(['style'],result['missing'])
        self.assertEqual({'length':'detailed','mode':'scroll'},result['preservedChoices'])
        spec['style']='글래스모피즘'
        result=artifacts.html_choices(spec)
        self.assertEqual('ready',result['stage'])
        self.assertEqual({'style':'glassmorphism','length':'detailed','mode':'scroll'},result['selection'])

    def test_explicit_style_skips_initial_and_known_mode_is_not_reasked(self):
        result=artifacts.html_choices({'style':'bento','mode':'slides'})
        self.assertEqual('format',result['stage'])
        self.assertEqual(['length'],result['missing'])
        self.assertNotIn('viewOptions',result)
        self.assertNotIn('initialDesignOptions',result)

    def test_choice_helper_rejects_invalid_values_and_protection(self):
        for spec in ({'designMenu':'unknown'},{'style':'추가 디자인'},{'length':'enormous'},{'mode':None}):
            self.assertEqual('invalid_choice',artifacts.html_choices(spec)['code'])
        for spec in ({'protected':True},{'drmRestricted':True},{'permissionGranted':False},{'accessStatus':'denied'}):
            self.assertEqual('protected_input',artifacts.html_choices(spec)['code'])

    def test_choice_helper_does_not_read_report_assets(self):
        with patch.object(artifacts,'_source',side_effect=AssertionError('source must not be read')):
            result=artifacts.html_choices({'sections':[{'image':{'path':'absent.png'}}]})
        self.assertEqual('design',result['stage'])

    def test_real_cli_replays_incident_without_creating_state(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            spec=root/'choices.json'
            state=root/'not-created'
            command=[sys.executable,'-B',str(ROOT/'company-agent-plugin/scripts/harness_cli.py'),
                     'business','html-choices','--spec',str(spec),'--state-root',str(state)]
            for fields,stage in (({},'design'),({'designMenu':'additional','length':'detailed','mode':'scroll'},'design_detail'),
                                 ({'style':'glassmorphism','length':'detailed','mode':'scroll'},'ready')):
                spec.write_text(json.dumps(fields),encoding='utf-8')
                output=subprocess.run(command,capture_output=True,text=True,timeout=20)
                self.assertEqual(0,output.returncode,output.stderr)
                result=json.loads(output.stdout)
                self.assertEqual(stage,result['stage'])
                self.assertFalse(state.exists())

    def test_generation_gate_exposes_design_detail_before_unknown_format(self):
        with tempfile.TemporaryDirectory() as t:
            target=Path(t)/'not-created.html'
            result=artifacts.create_html({'designMenu':'additional','sections':[{}]},target,require_choices=True)
            self.assertEqual('design_detail',result['stage'])
            self.assertEqual(['style'],result['missing'])
            self.assertFalse(target.exists())

    def test_only_missing_choices_are_requested(self):
        result=styles.choices({'style':'neumorphism','length':'short'})
        self.assertEqual(['mode'],result['missing'])
        self.assertIsNone(styles.choices({'style':'glassmorphism','length':'standard','mode':'both'}))

    def test_cli_gate_does_not_publish_default_report(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            spec=root/'job.json'
            spec.write_text(json.dumps({'title':'보고','sections':[{'body':'내용'}]}),encoding='utf-8')
            args=argparse.Namespace(business_action='html',state_root=str(root),spec=str(spec),output=str(root/'out.html'))
            result=business.dispatch(args)
            self.assertEqual('input_required',result['status'])
            self.assertFalse((root/'out.html').exists())

    def test_all_styles_are_supported_with_explicit_choices(self):
        with tempfile.TemporaryDirectory() as t:
            for key,*_ in styles.STYLES:
                result=artifacts.create_html({'style':key,'length':'standard','mode':'scroll','sections':[{'title':'실적','body':'확인된 내용'}]},Path(t)/(key+'.html'),require_choices=True)
                self.assertTrue(result['ok'],result)
                self.assertEqual(key,result['style'])

    def test_extra_design_is_not_a_style(self):
        with tempfile.TemporaryDirectory() as t:
            result=artifacts.create_html({'style':'추가 디자인','length':'short','mode':'scroll','sections':[{}]},Path(t)/'bad.html',require_choices=True)
            self.assertEqual('invalid_choice',result['code'])

    def test_protection_still_blocks_before_choices(self):
        with tempfile.TemporaryDirectory() as t:
            result=artifacts.create_html({'protected':True,'sections':[{}]},Path(t)/'bad.html',require_choices=True)
            self.assertEqual('protected_input',result['code'])

    def test_old_internal_api_defaults_remain_compatible(self):
        with tempfile.TemporaryDirectory() as t:
            result=artifacts.create_html({'sections':[{'body':'기존 자동화'}]},Path(t)/'legacy.html')
            self.assertTrue(result['ok'])

    def test_packaged_picker_matches_current_production_css(self):
        path=ROOT/'company-agent-plugin/skills/html-report/assets/design-picker.html'
        text=path.read_text(encoding='utf-8')
        self.assertEqual(styles.picker_html(),text)
        self.assertIn(styles.CSS,text)
        self.assertEqual(8,text.count('class="design-card"'))

    def test_picker_closed_ids_unique_and_offline(self):
        text=styles.picker_html()
        tag=re.search(r'<details id="additional-designs"[^>]*>',text).group()
        self.assertNotIn('open',tag)
        ids=re.findall(r'\bid="([^"]+)"',text)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertNotRegex(text,r'<(?:script|img|iframe)[^>]+src=|<link[^>]+href=|@import|\bfetch\(|XMLHttpRequest|localStorage|sessionStorage')
        self.assertIn('아직 Claude에 전달되지 않았습니다',text)
        self.assertIn('Ctrl+C',text)

    def test_picker_script_hash_is_correct(self):
        text=styles.picker_html()
        scripts=re.findall(r'<script>(.*?)</script>',text,re.S)
        self.assertEqual(1,len(scripts))
        digest=base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
        self.assertIn('sha256-'+digest,text)

    def test_read_only_picker_does_not_create_state(self):
        with tempfile.TemporaryDirectory() as t:
            missing=Path(t)/'state'
            result=business.dispatch(argparse.Namespace(business_action='html-designs',state_root=str(missing),output=None))
            self.assertTrue(result['ok'],result)
            self.assertFalse(missing.exists())
            self.assertFalse(result['settingsChanged'])
            self.assertTrue(Path(result['outputPath']).is_file())

    def test_picker_copy_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'picker.html'
            result=artifacts.html_designs(path)
            self.assertTrue(result['ok'],result)
            before=path.read_bytes()
            self.assertEqual('output_exists',artifacts.html_designs(path)['code'])
            self.assertEqual(before,path.read_bytes())

    def test_report_and_preview_share_theme_palette_and_surfaces(self):
        from company_agent.report_design import PALETTE
        self.assertTrue(all('var(--series-' in value for value in PALETTE))
        for key,*_ in styles.STYLES:
            rule=re.search(r'\[data-style='+re.escape(key)+r'\]\{([^}]+)\}',styles.CSS).group(1)
            for token in ('--series-0:', '--series-1:', '--accent:', '--tint:', '--section-radius:'):
                self.assertIn(token,rule)
        self.assertIn('background:var(--cover)!important',styles.CSS)
        self.assertIn('background:var(--head-fill)',styles.CSS)
        self.assertIn('box-shadow:var(--cell-shadow)',styles.CSS)

    def test_theme_definitions_do_not_compete_with_legacy_layers(self):
        from company_agent import report_design
        for css in (artifacts._CSS, report_design.CSS):
            self.assertNotRegex(css, r'body\[data-style=[a-z-]+\]\{--')
        self.assertIn('--chart-shadow:var(--cell-shadow)', styles.CSS)
        self.assertIn('grid-column:span 2', styles.CSS)

    def test_glass_and_neumorphism_are_materials_not_only_palette_changes(self):
        glass = re.search(r'\[data-style=glassmorphism\]\{([^}]+)', styles.CSS).group(1)
        neo = re.search(r'\[data-style=neumorphism\]\{([^}]+)', styles.CSS).group(1)
        self.assertIn('radial-gradient', glass)
        self.assertIn('--surface:#ffffff2e', glass)
        self.assertIn('--cell:#ffffff24', glass)
        self.assertIn('backdrop-filter:blur(14px)', styles.CSS)
        self.assertIn('#bcbcbc 29.3%', glass)
        self.assertIn('inset 0 -1px 0 #00000012', glass)
        self.assertNotIn('saturate(140%)', styles.CSS)
        for color in re.findall(r'#([a-fA-F0-9]{6})(?:[a-fA-F0-9]{2})?\b', glass):
            self.assertEqual(color[:2],color[2:4])
            self.assertEqual(color[2:4],color[4:6])
        self.assertIn('--bg:#e5eaf0;--paper:#e5eaf0', neo)
        self.assertIn('-14px -14px', neo)
        self.assertIn('--cell-shadow:inset', neo)
        self.assertIn('--chart-shadow:7px 7px', neo)

    def test_reduced_transparency_and_print_use_opaque_readable_surfaces(self):
        self.assertIn('@supports not ((backdrop-filter:', styles.CSS)
        self.assertIn('@media(prefers-reduced-transparency:reduce)', styles.CSS)
        self.assertIn('background:#fafafa!important', styles.CSS)
        self.assertIn('@media print{:is(body,.style-preview)[data-style]', styles.CSS)
        self.assertIn('-webkit-backdrop-filter:none!important', styles.CSS)


if __name__=='__main__':
    unittest.main()
