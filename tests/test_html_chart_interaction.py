"""Offline chart interactions and presentation density contracts."""
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business_artifacts as artifacts, report_design


class ChartInteractionTests(unittest.TestCase):
    def test_every_supported_chart_exposes_all_values_without_script_interpolation(self):
        for kind in ('bar', 'column', 'line', 'pie'):
            chart = {'type': kind, 'title': '검사 결과', 'categories': ['<수율>', 'TAT "기준"'],
                     'series': [{'name': '실적', 'values': [7, 3]}]}
            html = report_design.svg_chart(chart, 2)
            self.assertEqual(html.count('class="chart-point"'), 2)
            self.assertEqual(html.count('tabindex="0"'), 1)
            self.assertIn('aria-label="&lt;수율&gt; / 실적: 7', html)
            self.assertIn('role="tooltip" hidden', html)
            self.assertIn('aria-describedby="chart-help-2"', html)
            self.assertNotIn('<수율>', html)
            self.assertNotIn('<script', html)

    def test_zero_and_negative_values_and_hidden_line_markers_are_still_reachable(self):
        chart = {'type': 'line', 'categories': ['현재', '차이'], 'series': [{'name': '수량', 'values': [0, -4]}]}
        html = report_design.svg_chart(chart, 1, {'marker': 'none'})
        self.assertEqual(html.count('class="chart-point"'), 2)
        self.assertEqual(html.count('class="chart-hit"'), 2)
        self.assertNotIn('class="chart-mark"', html)
        self.assertIn('차이 / 수량: -4', html)

    def test_tooltip_does_not_round_the_original_value_to_six_digits(self):
        chart = {'type': 'column', 'categories': ['정밀 측정'],
                 'series': [{'name': '측정값', 'values': [1234567.891234]}]}
        self.assertIn('측정값: 1234567.891234', report_design.svg_chart(chart, 1))

    def test_chart_controller_is_loaded_only_when_needed_and_retains_source_table(self):
        spec = {'title': '검증', 'style': 'minimalism', 'length': 'standard', 'mode': 'scroll',
                'fontChoice': 'pretendard', 'fontSource': 'system',
                'sections': [{'title': '생산 추이', 'body': '가상 자료'}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plain.html'
            self.assertTrue(artifacts.create_html(spec, path)['ok'])
            self.assertNotIn('One local controller per chart', path.read_text(encoding='utf-8'))
            spec['sections'][0]['chart'] = {'type': 'column', 'categories': ['A', 'B'],
                                          'series': [{'name': '수량', 'values': [5, 8]}]}
            path = Path(folder) / 'chart.html'
            self.assertTrue(artifacts.create_html(spec, path)['ok'])
            html = path.read_text(encoding='utf-8')
            self.assertIn('One local controller per chart', html)
            self.assertIn('차트 수치 원자료 펼치기', html)
            self.assertIn('default-src &#x27;none&#x27;', html)
            self.assertIn('max-width:800px', html)
            self.assertIn('font-family:"Pretendard"', html)
            self.assertIn("event.stopPropagation()", html)

    def test_reference_chart_font_and_table_size_keep_priority(self):
        from company_agent.report_styles import reference_style_css
        css = reference_style_css({'chart': {'fontSize': 16, 'labelSize': 18},
                                   'table': {'fontSize': 17, 'padding': 14}})
        self.assertIn('font-size:16px', css)
        self.assertIn('font-size:18px', css)
        self.assertIn('--table-font-size:17px', css)
        self.assertIn('--table-padding:14px', css)

    def test_reference_surface_keeps_kpi_foregrounds_readable(self):
        from company_agent.report_styles import reference_style_css
        # A light observed surface must not keep the bento preset's pale text
        # intended for its dark first card when muted was not specified.
        css = reference_style_css({'colors': {'surface': 'F0F4F5', 'text': '1F2D3A', 'primary': '1F2D3A'}})
        self.assertIn('.kpi{--ink:#1F2D3A;--muted:#1F2D3A;--accent:#1F2D3A}', css)
        # When only a dark surface was observed, derive a readable foreground.
        css = reference_style_css({'colors': {'surface': '20334F'}})
        self.assertIn('.kpi{--ink:#ffffff;--muted:#ffffff;--accent:#ffffff}', css)
        # No reference surface: preserve all preset backgrounds and text rules.
        self.assertNotIn('--muted:#ffffff', reference_style_css({'colors': {'primary': '345BE6'}}))

    def test_adequate_reference_colors_are_retained_and_low_contrast_is_corrected(self):
        from company_agent.report_styles import reference_style_css
        css = reference_style_css({'colors': {'surface':'FFFFFF', 'text':'202020',
                                              'muted':'555555', 'primary':'345BE6'}})
        self.assertIn('.kpi{--ink:#202020;--muted:#555555;--accent:#345BE6}', css)
        css = reference_style_css({'colors': {'surface':'FFFFFF', 'text':'202020', 'muted':'EEEEEE'}})
        self.assertIn('--muted:#202020', css)


if __name__ == '__main__':
    unittest.main()
