"""Declared number context survives rendering without extra reads or model calls."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin' / 'scripts'))
from company_agent.report_facts import resolve, bind, FactError, CONTEXT_FIELDS
from company_agent.business_artifacts import create_html
from company_agent import business_artifacts, presentation_design


class FactScopeTests(unittest.TestCase):
    def spec(self):
        return {
            'title': 'D03 범위별 비교', 'style': 'minimal', 'mode': 'scroll',
            'facts': [
                {'id': 'all', 'label': '전체 이익률', 'unit': '%', 'op': 'ratio',
                 'inputs': [343, 1000], 'decimals': 1, 'period': '2026년 9월',
                 'scope': 'D03 전체, Unknown 포함', 'exclusions': '제외 없음',
                 'denominator': 'D03 전체 매출 1,000', 'source': '월 마감표'},
                {'id': 'plan', 'label': '계획 대상 이익률', 'unit': '%', 'op': 'ratio',
                 'inputs': [172, 500], 'decimals': 1, 'period': '2026년 9월',
                 'scope': '계획 대상만', 'exclusions': 'Unknown 제외',
                 'denominator': '계획 대상 매출 500', 'source': '계획표'}],
            'sections': [{'title': '같은 부서의 서로 다른 집계 범위',
                'table': {'headers': ['범위', '이익률', '제외 조건'], 'rows': [
                    ['{{fact:all.scope}}', '{{fact:all}}', '{{fact:all.exclusions}}'],
                    ['{{fact:plan.scope}}', '{{fact:plan}}', '{{fact:plan.exclusions}}']]},
                'body': '전체 {{fact:all.valueWithUnit}}, 계획 {{fact:plan.valueWithUnit}}. '
                        '분모: {{fact:all.denominator}} / {{fact:plan.denominator}}',
                'source': '{{fact:all.period}} / {{fact:all.source}} / {{fact:plan.source}}'}]}

    def test_context_reuse_preserves_distinct_scopes(self):
        spec = self.spec()
        before = deepcopy(spec)
        facts, validation = resolve(spec, [])
        self.assertEqual(bind('{{fact:all}} / {{fact:plan}}', facts), '34.3 / 34.4')
        for row in spec['facts']:
            for field in CONTEXT_FIELDS:
                self.assertEqual(bind('{{fact:' + row['id'] + '.' + field + '}}', facts), row[field])
        self.assertEqual(validation['metricMeaning'], 'not_verified')
        self.assertEqual(validation['sourceAccuracy'], 'not_verified')
        self.assertEqual(before, spec)

    def test_render_table_and_comment_from_same_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.html'
            result = create_html(self.spec(), output)
            self.assertTrue(result['ok'], result)
            html = output.read_text(encoding='utf-8')
            for expected in ['34.3%', '34.4%', 'D03 전체, Unknown 포함', 'Unknown 제외',
                             'D03 전체 매출 1,000', '계획 대상 매출 500', '월 마감표']:
                self.assertIn(expected, html)
            self.assertNotIn('{{fact:', html)

    def test_optional_context_keeps_old_specs_compatible(self):
        facts, _ = resolve({'facts': [{'id': 'n', 'inputs': [20, 30]}]}, [])
        self.assertEqual(bind('{{fact:n}}', facts), '50')
        self.assertFalse(set(CONTEXT_FIELDS) & set(facts['n']))
        with self.assertRaisesRegex(FactError, 'scope'):
            bind('{{fact:n.scope}}', facts)

    def test_same_job_context_survives_ppt_preparation(self):
        spec = self.spec()
        data = business_artifacts._normalize(spec)
        check = presentation_design.prepare(spec, data)
        table = data['sections'][0]['table']['rows']
        self.assertEqual(table[0], ['D03 전체, Unknown 포함', '34.3', '제외 없음'])
        self.assertEqual(table[1], ['계획 대상만', '34.4', 'Unknown 제외'])
        self.assertIn('D03 전체 매출 1,000', data['sections'][0]['body'])
        self.assertEqual(check['metricMeaning'], 'not_verified')

    def test_context_validation_is_bounded_and_never_coerces_objects(self):
        for field, maximum in CONTEXT_FIELDS.items():
            for invalid in ['', ' ', {}, ['a'], False, 'x' * (maximum + 1), 'a\nb', 'a\x7fb']:
                with self.subTest(field=field, value=invalid):
                    with self.assertRaisesRegex(FactError, field):
                        resolve({'facts': [{'id': 'n', 'inputs': [1], field: invalid}]}, [])

    def test_context_is_plain_text_not_active_markup(self):
        spec = self.spec()
        spec['facts'][0]['source'] = '<script>alert(1)</script>'
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.html'
            self.assertTrue(create_html(spec, output)['ok'])
            html = output.read_text(encoding='utf-8')
            self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
            self.assertNotIn('<script>alert(1)</script>', html)


if __name__ == '__main__':
    unittest.main()
