"""Observed typography/spacing must reach classic PPT scenes and native output."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import ppt_html, presentation_design, business_artifacts


class PptClassicProfileTests(unittest.TestCase):
    def spec(self, **slide):
        return {'title':'관찰 서식', 'referenceStyle': {
            'typography': {'headingFont':'Malgun Gothic', 'bodyFont':'Arial',
                           'titleSize':40, 'bodySize':24, 'captionSize':12},
            'spacing': {'outer':60, 'gap':32}},
            'slides':[{'title':'제목', 'body':'본문', **slide}]}

    def prepared(self, spec):
        with patch('company_agent.ppt_workflow.font_available', return_value=True):
            return ppt_html.prepare(spec)[0]

    def test_observed_profile_reaches_classic_structured_and_ordered_html_and_ooxml(self):
        from pptx import Presentation
        for extra in ({}, {'layout':'summary'}, {'layout':'evidence'}, {'layout':'comparison'},
                      {'layout':'actions'}, {'contentOrder':['body']}):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                data = self.prepared(self.spec(**extra))
                page = data['presentationPlan']['pages'][0]
                title = next(e for e in page['elements'] if e.get('text') == '제목')
                body = next(e for e in page['elements'] if e.get('text') == '본문')
                self.assertEqual(40, title['size'])
                self.assertEqual(24, body['size'])
                self.assertEqual('Malgun Gothic', title['font'])
                self.assertEqual('Arial', body['font'])
                self.assertEqual(60, title['x'])
                self.assertEqual(60, body['x'])
                self.assertEqual(840, title['w'])
                self.assertGreaterEqual(body['y'] - (title['y']+title['h']), 32)
                document = ppt_html.render(data)
                self.assertIn('font-size:4.166667cqw', document)
                self.assertIn('font-size:2.500000cqw', document)
                self.assertIn('font-family:&#x27;Arial&#x27;,sans-serif', document)
                path = Path(directory)/'profile.pptx'
                presentation_design.render_python(data, path, None)
                deck = Presentation(path)
                for value, size, font in (('제목',40,'Malgun Gothic'),('본문',24,'Arial')):
                    shape = next(s for s in deck.slides[0].shapes if s.has_text_frame and s.text == value)
                    self.assertEqual(size, shape.text_frame.paragraphs[0].font.size.pt)
                    self.assertEqual(font, shape.text_frame.paragraphs[0].font.name)

    def test_ordered_gap_and_table_size_honor_explicit_profile_and_component_override(self):
        spec = self.spec(table={'headers':['항목','값'],'rows':[['자료','10']]}, contentOrder=['body','table'])
        spec['presentationProfile'] = {'tableSize':20}
        data = self.prepared(spec)
        blocks = data['presentationPlan']['pages'][0]['contentBlocks']
        self.assertAlmostEqual(32, blocks[1]['y']-blocks[0]['y']-blocks[0]['h'])
        # Observed body size was deliberately mapped into tableStyle by the
        # reference mapper; an explicit tableStyle remains the strongest choice.
        spec['tableStyle'] = {'fontSize':19}
        data = self.prepared(spec)
        table = next(e for e in data['presentationPlan']['pages'][0]['elements'] if e['kind']=='table')
        self.assertEqual(19, table['size'])
        explicit = {'presentationProfile':{'tableSize':20}, 'slides':[{'title':'표', 'table':spec['slides'][0]['table']}]}
        table = next(e for e in self.prepared(explicit)['presentationPlan']['pages'][0]['elements'] if e['kind']=='table')
        self.assertEqual(20, table['size'])

    def test_explicit_elements_keep_geometry_size_and_font(self):
        spec = self.spec()
        spec['slides'] = [{'title':'직접 배치', 'elements':[
            {'kind':'text','x':14,'y':28,'w':360,'h':80,'text':'고정 배치',
             'size':18,'font':'Courier New','color':'112233'}]}]
        element = self.prepared(spec)['presentationPlan']['pages'][0]['elements'][0]
        self.assertEqual((14,28,360,80,18,'Courier New'), tuple(element[key] for key in ('x','y','w','h','size','font')))

    def test_absent_profile_and_implicit_role_profile_keep_classic_legacy(self):
        spec = {'slides':[{'title':'기존 제목','body':'기존 본문'}]}
        legacy = self.prepared(spec)['presentationPlan']['pages'][0]
        mixed = copy.deepcopy(spec)
        mixed['slides'].append({'title':'역할 제목','body':'역할 본문','pageRole':'cover'})
        self.assertEqual(legacy,self.prepared(mixed)['presentationPlan']['pages'][0])
        title = next(e for e in legacy['elements'] if e.get('text')=='기존 제목')
        self.assertEqual((48,37,30), (title['x'],title['y'],title['size']))
        self.assertNotIn('font',title)

    def test_profile_rejects_dense_text_instead_of_shrinking_or_overlapping(self):
        spec = self.spec(body='긴 본문을 보존해야 합니다. '*35)
        with self.assertRaises(business_artifacts.ArtifactError) as caught:
            self.prepared(spec)
        self.assertEqual('ppt_design_invalid',caught.exception.code)

    def test_large_annotation_remains_readable_and_profile_gap_separates_columns(self):
        spec = self.spec(body='', bullets=['첫 번째', '두 번째'], layout='comparison')
        spec['presentationProfile'] = {'annotationSize':18}
        elements = self.prepared(spec)['presentationPlan']['pages'][0]['elements']
        number = next(e for e in elements if e.get('text')=='01')
        self.assertEqual(18,number['size'])
        left = next(e for e in elements if e.get('text')=='첫 번째')
        right = next(e for e in elements if e.get('text')=='두 번째')
        self.assertAlmostEqual(32,right['x']-left['x']-left['w'])

    def test_missing_python_blocks_profile_export_before_com_can_drop_font_roles(self):
        # Typography alone must be protected even without a styled table/chart.
        spec = {'presentationProfile':{'titleSize':40,'bodySize':24},
                'slides':[{'title':'제목','body':'본문'}]}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(business_artifacts.importlib.util,'find_spec',return_value=None), \
                patch.object(business_artifacts,'_office',side_effect=AssertionError('COM must not run')):
            path = Path(directory)/'blocked.pptx'
            result = business_artifacts.create_ppt(spec,path)
            self.assertFalse(result['ok'])
            self.assertEqual('template_engine_unavailable',result['code'])
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
