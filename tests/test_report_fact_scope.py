"""Declared number context survives rendering without extra reads or model calls."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin' / 'scripts'))
from company_agent.report_facts import (resolve, bind, compact_handoff, FactError,
                                       CONTEXT_FIELDS, HANDOFF_MAX_ITEMS, HANDOFF_MAX_CHARS)
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

    def test_statements_keep_the_declared_denominator_and_distinct_rate_names(self):
        spec = {'facts': [
            {'id': 'gap', 'op': 'difference', 'inputs': [10000, 7186]},
            {'id': 'shortfall', 'op': 'ratio', 'inputs': [{'fact': 'gap'}, 10000],
             'label': '예산 대비 미달률', 'unit': '%', 'decimals': 2,
             'period': '2026년 9월', 'scope': 'D03 전체', 'denominator': '예산 10,000'},
            {'id': 'excess', 'op': 'ratio', 'inputs': [{'fact': 'gap'}, 7186],
             'label': '실적 대비 예산 초과율', 'unit': '%', 'decimals': 2,
             'period': '2026년 9월', 'scope': 'D03 전체', 'denominator': '실적 7,186'}]}
        facts, validation = resolve(spec, [])
        self.assertEqual('예산 대비 미달률 28.14%', bind('{{fact:shortfall.statement}}', facts))
        self.assertEqual('실적 대비 예산 초과율 39.16%', bind('{{fact:excess.statement}}', facts))
        before = deepcopy(facts)
        handoff = compact_handoff(facts)
        self.assertEqual(handoff[1], {
            'id': 'shortfall', 'statement': '예산 대비 미달률 28.14%',
            'period': '2026년 9월', 'scope': 'D03 전체', 'denominator': '예산 10,000'})
        self.assertEqual(handoff[2]['denominator'], '실적 7,186')
        self.assertEqual(handoff, validation['factHandoff'])
        self.assertEqual(0, validation['factHandoffOmitted'])
        self.assertNotIn('source', handoff[1])
        json.dumps(handoff, ensure_ascii=False)
        self.assertEqual(before, facts)
        self.assertEqual('not_verified', validation['metricMeaning'])
        self.assertEqual('not_verified', validation['freeTextClaims'])

    def test_statement_reuses_the_same_named_value_in_html_and_ppt(self):
        spec = self.spec()
        spec['title'] = '{{fact:all.statement}}'
        spec['sections'][0]['body'] = '{{fact:plan.statement}} (분모: {{fact:plan.denominator}})'
        (Path(__file__).resolve().parents[1] / '.smoke').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / '.smoke') as tmp:
            output = Path(tmp) / 'statement.html'
            result = create_html(spec, output)
            self.assertTrue(result['ok'], result)
            self.assertEqual('전체 이익률 34.3%', result['validation']['factHandoff'][0]['statement'])
            self.assertIn('전체 이익률 34.3%', output.read_text(encoding='utf-8'))
        data = business_artifacts._normalize(spec)
        validation = presentation_design.prepare(spec, data)
        self.assertEqual('D03 전체 매출 1,000', validation['factHandoff'][0]['denominator'])
        self.assertEqual('전체 이익률 34.3%', data['title'])
        self.assertEqual('계획 대상 이익률 34.4% (분모: 계획 대상 매출 500)', data['sections'][0]['body'])

    def test_no_facts_does_not_add_an_empty_handoff(self):
        facts, validation = resolve({}, [])
        self.assertEqual({}, facts)
        self.assertNotIn('factHandoff', validation)
        self.assertNotIn('factHandoffOmitted', validation)

    def test_many_facts_limit_the_response_but_keep_all_bindings(self):
        spec = {'facts': [{'id': f'n{i}', 'label': f'지표 {i}', 'inputs': [i]}
                          for i in range(128)]}
        before = deepcopy(spec)
        facts, validation = resolve(spec, [])
        self.assertEqual(128, len(facts))
        self.assertEqual(HANDOFF_MAX_ITEMS, len(validation['factHandoff']))
        self.assertEqual(128 - HANDOFF_MAX_ITEMS, validation['factHandoffOmitted'])
        self.assertEqual('지표 127 127', bind('{{fact:n127.statement}}', facts))
        self.assertEqual(128, len(compact_handoff(facts)))
        self.assertEqual(before, spec)

    def test_long_context_limits_json_size_without_truncating_any_row(self):
        spec = {'facts': [{'id': f'n{i}', 'label': f'지표 {i}', 'inputs': [i],
                           'scope': '포함 범위 ' + '가' * 490,
                           'exclusions': '제외 조건 ' + '나' * 490,
                           'source': '자료 출처 ' + '다' * 490,
                           'denominator': '분모 ' + '라' * 290}
                          for i in range(12)]}
        facts, validation = resolve(spec, [])
        handoff = validation['factHandoff']
        serialized = json.dumps(handoff, ensure_ascii=False, separators=(',', ':'))
        self.assertLessEqual(len(serialized), HANDOFF_MAX_CHARS)
        self.assertGreater(len(handoff), 0)
        self.assertLess(len(handoff), HANDOFF_MAX_ITEMS)
        self.assertEqual(len(facts) - len(handoff), validation['factHandoffOmitted'])
        self.assertEqual(compact_handoff(facts)[:len(handoff)], handoff)
        self.assertEqual(spec['facts'][-1]['scope'], bind('{{fact:n11.scope}}', facts))
        self.assertEqual([], compact_handoff(facts, max_chars=2))


if __name__ == '__main__':
    unittest.main()
