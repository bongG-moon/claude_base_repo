"""Native chart defaults retain values, category names and visible negative bars."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business_artifacts, presentation_design


@unittest.skipUnless(importlib.util.find_spec('pptx'), 'python-pptx is not available')
class NativeChartReadabilityTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.smoke').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='chart-readability-', dir=ROOT / '.smoke')
        self.addCleanup(self.temp.cleanup)
        self.spec = json.loads((ROOT / 'tests/fixtures/presentation_chart_readability.json').read_text(encoding='utf-8'))

    def render(self):
        from pptx import Presentation
        data = business_artifacts._normalize(self.spec)
        presentation_design.prepare(self.spec, data)
        data['presentationPlan'] = presentation_design.plan(data)
        output = Path(self.temp.name) / 'charts.pptx'
        result = presentation_design.render_python(data, output, None)
        self.assertEqual(3, result['charts'])
        with zipfile.ZipFile(output) as package:
            self.assertEqual(3, len([n for n in package.namelist() if n.startswith('ppt/embeddings/')]))
        deck = Presentation(output)
        return [next(s.chart for s in slide.shapes if s.has_chart) for slide in deck.slides]

    def test_negative_bars_keep_explicit_solid_fill_and_outside_categories(self):
        from pptx.enum.chart import XL_TICK_LABEL_POSITION
        charts = self.render()
        for index in (0, 1):
            chart = charts[index]
            self.assertFalse(chart.series[0].invert_if_negative)
            self.assertEqual(['0'], chart._chartSpace.xpath('.//c:invertIfNegative/@val'))
            self.assertTrue(chart._chartSpace.xpath('.//c:ser/c:spPr/a:solidFill/a:srgbClr'))
            self.assertEqual(XL_TICK_LABEL_POSITION.LOW, chart.category_axis.tick_label_position)
            self.assertEqual(tuple(self.spec['slides'][index]['chart']['series'][0]['values']), chart.series[0].values)

    def test_eight_categories_and_supported_twelve_have_no_automatic_label_skips(self):
        for count in (8, 12):
            with self.subTest(categories=count):
                content = self.spec['slides'][1]['chart']
                content['categories'] = [f'{i + 1}월' for i in range(count)]
                content['series'][0]['values'] = list(range(count))
                chart = self.render()[1]
                self.assertEqual(content['categories'], [c.label for c in chart.plots[0].categories])
                self.assertEqual(['1'], chart._chartSpace.xpath('.//c:catAx/c:tickLblSkip/@val'))

    def test_line_labels_stay_above_and_below_editable_markers(self):
        from pptx.enum.chart import XL_LABEL_POSITION, XL_MARKER_STYLE
        chart = self.render()[2]
        self.assertTrue(chart.plots[0].has_data_labels)
        for index, series in enumerate(chart.series):
            self.assertEqual(XL_MARKER_STYLE.CIRCLE, series.marker.style)
            self.assertEqual(5, series.marker.size)
            expected = XL_LABEL_POSITION.BELOW if index else XL_LABEL_POSITION.ABOVE
            self.assertEqual([expected] * 5, [p.data_label.position for p in series.points])
            self.assertEqual(tuple(self.spec['slides'][2]['chart']['series'][index]['values']), series.values)

    def test_office_exporter_uses_same_chart_defaults(self):
        script = (ROOT / 'company-agent-plugin/scripts/Invoke-BusinessPowerPoint.ps1').read_text(encoding='utf-8')
        for setting in ('InvertIfNegative = $false', 'TickLabelPosition = -4134',
                        'TickLabelSpacing = 1', 'MarkerStyle = 8',
                        '$labels.Position = 0', '$labels.Position = 1'):
            self.assertIn(setting, script)


if __name__ == '__main__':
    unittest.main()
