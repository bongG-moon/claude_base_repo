"""HTML and actual editable OOXML must follow the same bounded component style."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business_artifacts as artifacts, ppt_html, presentation_design


TABLE = {'headers': ['항목', '실적'], 'rows': [['가', '10'], ['나', '20']]}
CHART = {'type': 'line', 'categories': ['가', '나'],
         'series': [{'name': '실적', 'values': [10, 20]}, {'name': '계획', 'values': [8, 18]}]}
STYLES = [
    {'tableStyle': {'headerFill': '123456', 'headerText': 'FFFFFF', 'bodyFill': 'FFF8EE',
                    'bodyText': '332211', 'alternateFill': 'FFEEDD', 'borderColor': 'ABCDEF',
                    'borderWidth': 2, 'headerBold': False, 'fontSize': 18, 'align': 'right', 'padding': 8},
     'chartStyle': {'seriesColors': ['AA2244', '2244AA'], 'legendPosition': 'right',
                    'fontSize': 15, 'labelSize': 11, 'gridColor': 'CCDDEE', 'showGrid': True,
                    'marker': 'diamond', 'lineWidth': 2}},
    {'tableStyle': {'headerFill': '543210', 'headerText': 'FFFFEE', 'bodyFill': 'EEFFEE',
                    'bodyText': '113311', 'alternateFill': 'CCDDAA', 'borderColor': '665544',
                    'borderWidth': .5, 'headerBold': True, 'fontSize': 14, 'align': 'center', 'padding': 4},
     'chartStyle': {'seriesColors': ['228844', '884422'], 'legendPosition': 'top',
                    'fontSize': 12, 'labelSize': 10, 'gridColor': 'EEEECC', 'showGrid': False,
                    'marker': 'square', 'lineWidth': 1}},
]


class PptComponentStylesTests(unittest.TestCase):
    def spec(self, style=None):
        return {'title': '스타일 검증', **copy.deepcopy(style or {}), 'slides': [
            {'title': '상세', 'table': copy.deepcopy(TABLE)},
            {'title': '추이', 'chart': copy.deepcopy(CHART)}]}

    def native(self, spec, directory):
        from pptx import Presentation
        data = ppt_html.prepare(spec)[0]
        path = Path(directory) / 'styled.pptx'
        stats = presentation_design.render_python(data, path, None)
        self.assertEqual(1, stats['tables'])
        self.assertEqual(1, stats['charts'])
        with zipfile.ZipFile(path) as archive:
            self.assertTrue(any(name.startswith('ppt/embeddings/') for name in archive.namelist()))
        return data, Presentation(path)

    def test_two_contrasting_styles_reach_html_and_native_editable_objects(self):
        from pptx.enum.text import PP_ALIGN
        from pptx.enum.chart import XL_LEGEND_POSITION, XL_MARKER_STYLE
        for styles in STYLES:
            with self.subTest(styles=styles), tempfile.TemporaryDirectory() as directory:
                data, deck = self.native(self.spec(styles), directory)
                document = ppt_html.render(data)
                table_style, chart_style = styles['tableStyle'], styles['chartStyle']
                table = next(shape.table for shape in deck.slides[0].shapes if shape.has_table)
                chart = next(shape.chart for shape in deck.slides[1].shapes if shape.has_chart)
                for row, fill in enumerate(('headerFill', 'alternateFill', 'bodyFill')):
                    cell = table.cell(row, 0)
                    self.assertEqual(table_style[fill], str(cell.fill.fore_color.rgb))
                    self.assertIn('background:#' + table_style[fill], document)
                    self.assertEqual(table_style['fontSize'], cell.text_frame.paragraphs[0].font.size.pt)
                    self.assertEqual(table_style['padding'], cell.margin_left.pt)
                    self.assertEqual(table_style['padding'], cell.margin_top.pt)
                    self.assertEqual({'right': PP_ALIGN.RIGHT, 'center': PP_ALIGN.CENTER}[table_style['align']], cell.text_frame.paragraphs[0].alignment)
                    borders = cell._tc.xpath('./a:tcPr/a:lnL | ./a:tcPr/a:lnR | ./a:tcPr/a:lnT | ./a:tcPr/a:lnB')
                    self.assertEqual(4, len(borders))
                    self.assertEqual(['lnL', 'lnR', 'lnT', 'lnB'], [node.tag.rsplit('}', 1)[-1] for node in list(cell._tc.get_or_add_tcPr())[:4]])
                    for border in borders:
                        self.assertEqual(str(round(table_style['borderWidth'] * 12700)), border.get('w'))
                        self.assertEqual(table_style['borderColor'], border[0][0].get('val'))
                self.assertEqual(table_style['headerBold'], table.cell(0, 0).text_frame.paragraphs[0].font.bold)
                self.assertEqual(table_style['headerText'], str(table.cell(0, 0).text_frame.paragraphs[0].font.color.rgb))
                self.assertEqual(table_style['bodyText'], str(table.cell(1, 0).text_frame.paragraphs[0].font.color.rgb))
                self.assertEqual({'right': XL_LEGEND_POSITION.RIGHT, 'top': XL_LEGEND_POSITION.TOP}[chart_style['legendPosition']], chart.legend.position)
                self.assertIn('data-legend-position="' + chart_style['legendPosition'] + '"', document)
                self.assertEqual(chart_style['fontSize'], chart.legend.font.size.pt)
                self.assertEqual(chart_style['labelSize'], chart.plots[0].data_labels.font.size.pt)
                self.assertEqual(chart_style['showGrid'], chart.value_axis.has_major_gridlines)
                self.assertNotIn('stroke-width:var(--chart-line-width', document)
                if chart_style['showGrid']:
                    self.assertEqual(chart_style['gridColor'], str(chart.value_axis.major_gridlines.format.line.color.rgb))
                    self.assertIn('stroke:#' + chart_style['gridColor'], document)
                else:
                    self.assertNotIn('class="gridline"', document)
                for index, series in enumerate(chart.series):
                    self.assertEqual(chart_style['seriesColors'][index], str(series.format.line.color.rgb))
                    self.assertIn('stroke="#' + chart_style['seriesColors'][index] + '"', document)
                    self.assertEqual({'diamond': XL_MARKER_STYLE.DIAMOND, 'square': XL_MARKER_STYLE.SQUARE}[chart_style['marker']], series.marker.style)
                    self.assertIn('data-marker="' + chart_style['marker'] + '"', document)
                    self.assertEqual(chart_style['lineWidth'], series.format.line.width.pt)
                self.assertEqual((10., 20.), chart.series[0].values)

    def test_global_slide_and_explicit_element_precedence_is_fieldwise(self):
        spec = self.spec(STYLES[0])
        spec['slides'] = [{'title': '수동 배치', 'tableStyle': {'headerFill': '112233', 'fontSize': 17},
                           'chartStyle': {'legendPosition': 'left'}, 'elements': [
            {'kind': 'table', 'x': 40, 'y': 60, 'w': 400, 'h': 180, 'table': TABLE,
             'tableStyle': {'headerFill': '332211', 'borderWidth': 0, 'fontSize': 16}},
            {'kind': 'chart', 'x': 470, 'y': 60, 'w': 440, 'h': 340, 'chart': CHART,
             'chartStyle': {'seriesColors': ['7700AA'], 'marker': 'none', 'legendPosition': 'none'}}]}]
        with tempfile.TemporaryDirectory() as directory:
            data, deck = self.native(spec, directory)
        elements = data['presentationPlan']['pages'][0]['elements']
        self.assertEqual('332211', elements[0]['tableStyle']['headerFill'])
        self.assertEqual('FFEEDD', elements[0]['tableStyle']['alternateFill'])
        self.assertEqual(16, elements[0]['size'])
        self.assertEqual('none', elements[1]['chartStyle']['legendPosition'])
        self.assertEqual(2, elements[1]['chartStyle']['lineWidth'])
        table = next(shape.table for shape in deck.slides[0].shapes if shape.has_table)
        self.assertTrue(table.cell(0, 0)._tc.xpath('./a:tcPr/a:lnL/a:noFill'))
        chart = next(shape.chart for shape in deck.slides[0].shapes if shape.has_chart)
        self.assertFalse(chart.has_legend)
        self.assertEqual(['none', 'none'], [node.get('val') for node in chart._chartSpace.xpath('.//c:ser/c:marker/c:symbol')])
        self.assertTrue(all(str(series.format.line.color.rgb) == '7700AA' for series in chart.series))
        document = ppt_html.render(data)
        self.assertIn('data-legend-position="none"', document)
        self.assertNotIn('data-marker=', document)

    def test_role_detail_table_and_ordered_classic_share_style(self):
        for extra in ({'pageRole': 'detail'}, {'contentOrder': ['table']}, {'layout': 'actions'}):
            spec = self.spec(STYLES[0])
            spec['slides'][0].update(extra)
            with tempfile.TemporaryDirectory() as directory:
                data, deck = self.native(spec, directory)
            element = next(e for e in data['presentationPlan']['pages'][0]['elements'] if e['kind'] == 'table')
            self.assertEqual(18, element['size'])
            self.assertEqual('123456', element['tableStyle']['headerFill'])
            self.assertGreater(element['rowHeights'][0], 36)
            self.assertIn('background:#123456', ppt_html.render(data))
            table = next(shape.table for shape in deck.slides[0].shapes if shape.has_table)
            self.assertEqual('123456', str(table.cell(0, 0).fill.fore_color.rgb))
            self.assertEqual(18, table.cell(0, 0).text_frame.paragraphs[0].font.size.pt)

    def test_all_four_legend_positions_and_pie_category_palette(self):
        from pptx.enum.chart import XL_LEGEND_POSITION
        for position in ('bottom', 'top', 'left', 'right'):
            style = {'chartStyle': {'legendPosition': position, 'seriesColors': ['112233', '445566', '778899']}}
            spec = self.spec(style)
            spec['slides'][1]['chart'] = {'type': 'pie', 'categories': ['가', '나', '다'],
                                        'series': [{'name': '비중', 'values': [1, 2, 3]}]}
            with tempfile.TemporaryDirectory() as directory:
                data, deck = self.native(spec, directory)
            chart = next(shape.chart for shape in deck.slides[1].shapes if shape.has_chart)
            self.assertEqual(getattr(XL_LEGEND_POSITION, position.upper()), chart.legend.position)
            document = ppt_html.render(data)
            for index, color in enumerate(style['chartStyle']['seriesColors']):
                self.assertEqual(color, str(chart.series[0].points[index].format.fill.fore_color.rgb))
                self.assertIn('fill="#' + color + '"', document)

    def test_invalid_tokens_rejected_globally_on_slide_and_element(self):
        invalid = [('tableStyle', {'headerFill': 'red;display:none'}), ('tableStyle', {'borderWidth': -1}),
                   ('tableStyle', {'padding': 25}), ('tableStyle', {'headerBold': 'false'}),
                   ('tableStyle', {'fontSize': True}), ('tableStyle', {'fontSize': float('nan')}),
                   ('tableStyle', {'align': 'justify'}), ('tableStyle', {'css': 'body{}'}),
                   ('chartStyle', {'seriesColors': []}), ('chartStyle', {'seriesColors': ['FFFFFF'] * 13}),
                   ('chartStyle', {'seriesColors': ['#123456']}), ('chartStyle', {'legendPosition': 'auto'}),
                   ('chartStyle', {'marker': 'star'}), ('chartStyle', {'showGrid': 1}),
                   ('chartStyle', {'lineWidth': 0}), ('chartStyle', {'labelSize': 33}),
                   ('chartStyle', {'fontSize': 33}), ('chartStyle', None)]
        for key, value in invalid:
            for location in ('global', 'slide', 'element'):
                with self.subTest(key=key, value=value, location=location):
                    spec = self.spec()
                    if location == 'global':
                        spec[key] = value
                    elif location == 'slide':
                        spec['slides'][0][key] = value
                    else:
                        kind = key.removesuffix('Style')
                        spec['slides'] = [{'title': '검증', 'elements': [
                            {'kind': kind, 'x': 40, 'y': 60, 'w': 800, 'h': 300,
                             kind: TABLE if kind == 'table' else CHART, key: value}]}]
                    with self.assertRaises(artifacts.ArtifactError) as caught:
                        ppt_html.prepare(spec)
                    self.assertEqual('invalid_ppt_component_style', caught.exception.code)

    def test_absent_styles_keep_legacy_plan_and_chart_html(self):
        from company_agent.report_design import svg_chart
        data = ppt_html.prepare(self.spec())[0]
        for page in data['presentationPlan']['pages']:
            for element in page['elements']:
                self.assertNotIn('tableStyle', element)
                self.assertNotIn('chartStyle', element)
        self.assertIn(svg_chart(CHART, '2'), ppt_html.render(data))


if __name__ == '__main__':
    unittest.main()
