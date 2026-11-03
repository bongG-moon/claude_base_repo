"""New-deck choices, optional examples and independent PPT approval lifecycle."""
from __future__ import annotations

import copy
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import ppt_html, ppt_workflow, presentation_design

# Stage the same runtime files that the portable ZIP actually ships. A second
# handwritten list can leave this fixture incomplete after a renderer split.
RUNTIME_FILES = json.loads(
    (ROOT / 'scripts/platform_skills/catalog-metadata.json').read_text(encoding='utf-8')
)['presentation']['packaging']['runtimeModules']
ISOLATED_PPTX = subprocess.run([sys.executable, '-I', '-B', '-c', 'import pptx'],
                               capture_output=True, timeout=20).returncode == 0


class GalleryReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.pages = 0
        self.sources = []
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.append(attrs['id'])
        self.pages += tag == 'section' and attrs.get('class') == 'ppt-page'
        if attrs.get('src') or attrs.get('href', '').startswith(('http:', 'https:')):
            self.sources.append(attrs.get('src') or attrs.get('href'))
        self.scripts += tag == 'script'


class PptSelectionFlowTests(unittest.TestCase):
    def setUp(self):
        temporary_parent = ROOT / '.smoke/ppt-flow-tests'
        temporary_parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        temporary_patch = patch.object(tempfile, 'tempdir', str(self.root))
        temporary_patch.start()
        self.addCleanup(temporary_patch.stop)
        self.brief = {'purpose': '진행 보고', 'audience': '담당자', 'slideCount': 1}

    def chart(self):
        return {'type': 'column', 'categories': ['생산', '품질'],
                'series': [{'name': '신청 인원', 'values': [12, 8]}]}

    def table(self):
        return {'headers': ['부서', '인원'], 'rows': [['생산', '12'], ['품질', '8']]}

    def prepared(self, rows, **extra):
        return ppt_html.prepare({'title': '가상 현황', 'slides': rows, **extra})[0]

    def test_first_selection_preserves_brief_and_offers_executable_presets(self):
        source = copy.deepcopy(self.brief)
        result = ppt_workflow.choices(source)
        self.assertEqual('design_selection', result['stage'])
        self.assertEqual(source, result['preservedChoices'])
        self.assertEqual([], result['briefMissing'])
        self.assertTrue(result['waitForUser'])
        self.assertEqual(6, len(result['options']))
        self.assertEqual(self.brief, source)
        for option in result['options'][:3]:
            advanced = ppt_workflow.choices({**source, **option['selection']})
            self.assertEqual('design_preview', advanced['stage'])
            self.assertEqual(option['id'], advanced['preservedChoices']['designPreset'])
            self.assertFalse(advanced['waitForUser'])

    def test_partial_brief_and_empty_request_do_not_hide_missing_inputs(self):
        result = ppt_workflow.choices({'audience': '담당자'})
        self.assertEqual('design_selection', result['stage'])
        self.assertEqual(['purpose', 'slideCount'], result['briefMissing'])
        self.assertEqual({'audience': '담당자'}, result['preservedChoices'])
        self.assertEqual('design_selection', ppt_workflow.choices({})['stage'])

    def test_existing_job_explicit_design_and_custom_direction_do_not_restart_selection(self):
        for extra in ({'designPreset': 'warm'}, {'creationMode': 'new'},
                      {'designDirection': '흑백으로 대비를 강조'},
                      {'slides': [{'title': '기존 제목', 'body': '기존 내용'}]}):
            with self.subTest(extra=extra):
                result = ppt_workflow.choices({**self.brief, **extra})
                self.assertEqual('design_preview', result['stage'])
                self.assertFalse(result['waitForUser'])

    def test_actual_reference_and_saved_template_take_their_own_route(self):
        for mode in ('reference', 'saved'):
            self.assertEqual('reference_file', ppt_workflow.choices({**self.brief, 'creationMode': mode})['stage'])
        result = ppt_workflow.choices(self.brief, self.root / 'reference.pptx')
        self.assertEqual('design_preview', result['stage'])
        self.assertEqual('style', result['preservedChoices']['referenceMode'])
        result = ppt_workflow.choices({**self.brief, 'referenceMode': 'style'}, self.root / 'reference.pptx')
        self.assertEqual('design_preview', result['stage'])

    def test_bad_brief_or_direction_reports_input_error_before_a_menu(self):
        for field, value in (('slideCount', True), ('slideCount', 0), ('purpose', ''),
                             ('audience', None), ('designDirection', []), ('designDirection', 'x' * 501),
                             ('compositionMode', 'unknown')):
            with self.subTest(field=field, value=value):
                result = ppt_workflow.choices({**self.brief, field: value})
                self.assertEqual('invalid_choice', result['code'])
                self.assertEqual(field, result['field'])
                self.assertNotIn('options', result)

    def test_content_led_uses_relationship_specific_composition(self):
        rows = [{'title': '요약', 'body': '가상 설명', 'bullets': ['확인', '검증']},
                {'title': '근거', 'chart': self.chart(), 'body': '수치를 비교합니다.'},
                {'title': '실행', 'table': self.table(), 'body': '대상별로 확인합니다.'},
                {'title': '비교', 'chart': self.chart(), 'table': self.table(), 'body': '두 근거를 비교합니다.'}]
        data = self.prepared(rows, compositionMode='content-led')
        self.assertEqual(['summary', 'evidence', 'actions', 'comparison'], [row['layout'] for row in data['sections']])
        pages = data['presentationPlan']['pages']
        table = next(e for e in pages[2]['elements'] if e['kind'] == 'table')
        self.assertEqual(864, table['w'])
        evidence = next(e for e in pages[1]['elements'] if e['kind'] == 'chart')
        comparison = next(e for e in pages[3]['elements'] if e['kind'] == 'chart')
        self.assertGreater(evidence['w'], comparison['w'])
        for page in pages:
            for element in page['elements']:
                self.assertGreaterEqual(min(element['x'], element['y']), 0)
                self.assertLessEqual(element['x'] + element['w'], 960.01)
                self.assertLessEqual(element['y'] + element['h'], 540.01)

    def test_existing_classic_and_explicit_auto_geometry_is_unchanged(self):
        row = {'title': '기존 구성', 'chart': self.chart(), 'body': '확인합니다.'}
        classic = self.prepared([row])['presentationPlan']
        explicit_classic = self.prepared([row], compositionMode='classic')['presentationPlan']
        explicit_auto = self.prepared([{**row, 'layout': 'auto'}], compositionMode='content-led')['presentationPlan']
        self.assertEqual(classic, explicit_classic)
        self.assertEqual(classic, explicit_auto)
        self.assertEqual(139, next(e for e in classic['pages'][0]['elements'] if e['kind'] == 'chart')['y'])

    def test_explicit_layout_content_order_and_elements_survive_content_led(self):
        rows = [
            {'title': '직접 배치', 'layout': 'summary', 'body': '직접 정한 요약'},
            {'title': '순서 유지', 'table': self.table(), 'body': '표 아래 설명', 'contentOrder': ['table', 'body']},
            {'title': '자유 배치', 'elements': [{'kind': 'text', 'text': '지정 위치', 'x': 40, 'y': 50,
                                            'w': 400, 'h': 50, 'size': 24, 'color': '17324D', 'bold': True}]}]
        classic = self.prepared(rows)['presentationPlan']
        actual = self.prepared(rows, compositionMode='content-led')['presentationPlan']
        self.assertEqual(classic, actual)

    def test_gallery_has_twenty_one_distinct_offline_pages_and_no_approval(self):
        target = self.root / 'gallery.html'
        with patch.object(ppt_html.artifacts, '_office', side_effect=AssertionError('No Office for samples')):
            result = ppt_html.create_design_gallery(target)
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['sampleOnly'])
        self.assertFalse(result['approvalGranted'])
        self.assertFalse(result['officeStarted'])
        self.assertNotIn('designReview', result)
        reader = GalleryReader()
        reader.feed(target.read_text(encoding='utf-8'))
        self.assertEqual(21, reader.pages)
        self.assertEqual(len(reader.ids), len(set(reader.ids)))
        self.assertEqual([], reader.sources)
        self.assertEqual(0, reader.scripts)
        self.assertEqual({'business', 'monochrome', 'warm'}, set(result['designs']))


class PortablePptSelectionLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary_parent = ROOT / '.smoke/ppt-flow-tests'
        temporary_parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'empty-profile'
        self.home.mkdir()
        self.skill = self.root / 'presentation'
        shutil.copytree(ROOT / 'standalone-skills/presentation', self.skill)
        for name in RUNTIME_FILES:
            shutil.copyfile(ROOT / 'company-agent-plugin/scripts/company_agent' / name,
                            self.skill / 'scripts/visual_engine' / name)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.upper().startswith(('COMPANY', 'ANTHROPIC', 'CLAUDE', 'PYTHONPATH'))}
        self.env.update(TEMP=str(self.root), TMP=str(self.root), HOME=str(self.home), USERPROFILE=str(self.home),
                        CLAUDE_CONFIG_DIR=str(self.home / '.claude'), PYTHONDONTWRITEBYTECODE='1')
        self.spec = {'title': '가상 신청 현황', 'creationMode': 'new', 'designPreset': 'business',
                     'compositionMode': 'content-led', 'purpose': '현황 보고', 'audience': '담당자', 'slideCount': 2,
                     'slides': [{'title': '두 부서에서 신청했습니다', 'body': '가상 자료입니다.',
                                 'bullets': ['생산 부서 확인', '품질 부서 확인']},
                                {'title': '신청 인원', 'table': {'headers': ['부서', '인원'],
                                  'rows': [['생산', '12'], ['품질', '8']]}, 'body': '부서별 신청을 확인했습니다.'}]}

    def run_cli(self, *args, expected=0):
        proc = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(self.skill / 'scripts/presentation.py'),
                               *map(str, args)], cwd=self.root, env=self.env, text=True, encoding='utf-8',
                              capture_output=True, timeout=40)
        self.assertEqual(expected, proc.returncode, (proc.stdout, proc.stderr))
        self.assertEqual('', proc.stderr)
        self.assertEqual([], list(self.home.iterdir()), 'Independent skill must not alter any personal profile')
        return json.loads(proc.stdout)

    def write_spec(self):
        path = self.root / 'job.json'
        path.write_text(json.dumps(self.spec, ensure_ascii=False), encoding='utf-8')
        return path

    def test_choices_and_gallery_work_without_harness_or_user_settings(self):
        choice = self.run_cli('choices')
        self.assertEqual('design_selection', choice['stage'])
        self.assertEqual(6, len(choice['options']))
        ready = self.run_cli('choices', '--spec', self.write_spec())
        self.assertEqual('create_html_preview', ready['nextAction'])
        self.assertNotIn('business ', ready.get('previewCommand', ''))
        result = self.run_cli('gallery', '--output', self.root / 'gallery.html')
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['approvalGranted'])

    def test_screen_reference_plan_supports_twelve_slides_without_parsing_or_office(self):
        source = self.root / 'protected-example.pptx'
        original = b'not-a-readable-pptx'
        source.write_bytes(original)
        result = self.run_cli('reference', '--file', source, '--mode', 'screen',
                              '--slides', ','.join(map(str, range(1, 13))))
        self.assertTrue(result['ok'], result)
        self.assertEqual('capture_plan', result['status'])
        self.assertFalse(result['captured'])
        self.assertFalse(result['authorizationGranted'])
        self.assertEqual([[1,2,3],[4,5,6],[7,8,9],[10,11,12]], result['batches'])
        self.assertEqual(list(range(1, 13)), result['coverage']['missingSlides'])
        self.assertEqual('not_checked_by_helper', result['toolAvailability'])
        self.assertEqual(original, source.read_bytes())

    def test_generic_html_reference_does_not_claim_saved_template_analysis(self):
        source=self.root/'plain.html'
        source.write_text('<html><p>plain source</p></html>',encoding='utf-8')
        result=self.run_cli('reference','--file',source,expected=1)
        self.assertFalse(result['ok'])
        self.assertEqual('invalid_ppt_template',result['code'])

    @unittest.skipUnless(ISOLATED_PPTX, 'isolated Python needs python-pptx; use a prepared runtime')
    def test_html_approval_build_reference_and_changed_content_rejection(self):
        from pptx import Presentation
        job = self.write_spec()
        preview = self.run_cli('draft', '--spec', job, '--output', self.root / 'draft.html')
        self.assertTrue(preview['ok'], preview)
        self.assertEqual(2, preview['slides'])
        self.assertFalse(preview['designReview']['confirmed'])
        failed = self.run_cli('build', '--spec', job, '--output', self.root / 'unapproved.pptx', expected=1)
        self.assertEqual('design_approval_required', failed['code'])
        self.assertFalse((self.root / 'unapproved.pptx').exists())
        self.spec['designReview'] = {**preview['designReview'], 'confirmed': True}
        job = self.write_spec()
        built = self.run_cli('build', '--spec', job, '--output', self.root / 'approved.pptx')
        self.assertTrue(built['ok'], built)
        self.assertFalse(built['officeStarted'])
        deck = Presentation(self.root / 'approved.pptx')
        self.assertEqual(2, len(deck.slides))
        self.assertTrue(any(shape.has_table for slide in deck.slides for shape in slide.shapes))
        self.assertTrue(all(not slide._element.xpath('.//a:spLocks[@noTextEdit="1"]') for slide in deck.slides))
        reference = self.run_cli('reference', '--file', self.root / 'approved.pptx', '--slides', '1,2')
        self.assertTrue(reference['ok'], reference)
        self.assertEqual(2, len(reference['slides']))
        self.assertEqual('not_performed', reference['visualReview'])
        compact = self.run_cli('reference', '--file', self.root / 'approved.pptx', '--slides', '1,2', '--summary')
        self.assertTrue(compact['ok'], compact)
        self.assertEqual([0, 1], [p['sourceSlide'] for p in compact['analysis']['slides']])
        self.assertNotIn('textPreview', json.dumps(compact, ensure_ascii=False))
        self.assertEqual('source_text_and_per_object_coordinates_omitted',compact['contentCoverage'])
        self.assertIn('원본 텍스트와 개체별 좌표',compact['message'])
        self.assertNotIn('slides', {k: v for k, v in compact.items() if k != 'analysis'})
        self.assertLess(len(json.dumps(compact, ensure_ascii=False)), len(json.dumps(reference, ensure_ascii=False)))
        self.spec['slides'][0]['body'] = '승인 후 바뀐 내용입니다.'
        failure = self.run_cli('build', '--spec', self.write_spec(), '--output', self.root / 'changed.pptx', expected=1)
        self.assertEqual('design_review_changed', failure['code'])
        self.assertFalse((self.root / 'changed.pptx').exists())


if __name__ == '__main__':
    unittest.main()
