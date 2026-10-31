from __future__ import annotations

import base64
import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))
from company_agent.usability_report import render_markdown, render_report, write_report


class ReportParser(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.elements = []
        self.content = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.content.append(data)

    def metadata(self):
        encoded = next(attrs["content"] for tag, attrs in self.elements if tag == "meta" and attrs.get("name") == "usability-report")
        return json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))

    def markdown(self):
        href = next(attrs["href"] for tag, attrs in self.elements if tag == "a" and attrs.get("download"))
        return base64.b64decode(href.split(",", 1)[1], validate=True).decode("utf-8")


def example_report():
    return {
        "schemaVersion": 1, "generatedAt": "2026-10-29T10:00:00+09:00", "generatorVersion": "1",
        "scopeKey": "a" * 64,
        "window": {"since": "2026-10-22", "until": "2026-10-29", "days": 7},
        "summary": {"status": "observed", "title": "반복된 확인부터 살펴보세요", "message": "선택한 대화에서 개선 후보를 확인했습니다."},
        "coverage": {"filesRead": 2, "recordsRead": 20, "skippedRecords": 0, "truncated": False, "warnings": []},
        "metrics": {"transcriptSessions": 2, "requests": 4, "toolCalls": 12, "toolErrors": 0,
                    "repeatedFailedCalls": 0, "questionCalls": 3, "repeatedQuestions": 2, "sameRangeReads": 1,
                    "questionWaitMs": None, "questionPairs": 0, "observedSpanMs": 65_000,
                    "tokens": {"input_tokens": None, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 1000}},
        "findings": [{"code": "repeated-questions", "title": "같은 질문을 다시 확인했습니다", "detail": "반복된 확인 질문이 관찰되었습니다.",
                      "nextStep": "이미 정한 조건을 다음 요청에 함께 적어보세요.", "count": 2, "evidence": "같은 확인 질문 2건", "confidence": "검토 후보"}],
        "snapshots": {"sessions": 2, "toolFailures": 0, "slowPreparation": 0, "failedPreparation": 0, "maxContextChars": 100, "loadFailures": 0},
        "limitations": ["기록에 포함되지 않은 동작은 확인할 수 없습니다."],
    }


class UsabilityReportTests(unittest.TestCase):
    def test_report_explains_unknown_zero_candidates_and_observation_limits(self):
        html = render_report(example_report())
        self.assertIn('<th scope="row">입력 토큰</th><td>기록 없음</td>', html)
        self.assertIn('<th scope="row">출력 토큰</th><td>0</td>', html)
        self.assertIn('1분 5초', html)
        self.assertIn('먼저 확인할 1가지', html)
        self.assertIn('불필요한 동작을 확정하지 않습니다', html)
        self.assertIn('사람이 답한 시간도 포함', html)
        self.assertIn('실행 성공이나 업무 완료의 증거가 아닙니다', html)
        self.assertIn('실패 후 같은 동작 재요청', html)
        self.assertIn('재호출 결과의 실패 여부는 별도로 확인해야 합니다', html)
        self.assertIn('자세한 수치 보기', html)
        self.assertIn('Noto Sans KR', html)
        self.assertIn('overflow-x:auto', html)

    def test_no_data_is_not_presented_as_healthy_or_measured_zero(self):
        report = example_report()
        report['summary'] = {'status': 'no-data', 'title': '정상입니다', 'message': '기록이 없습니다.'}
        html = render_report(report)
        self.assertIn('판단할 기록이 없습니다', html)
        self.assertIn('문제가 없다는 뜻은 아닙니다', html)
        self.assertNotIn('정상입니다', html)
        self.assertNotIn('class="finding"', html)
        self.assertIn('<th scope="row">도구 오류</th><td>기록 없음</td>', html)
        self.assertIsNone(ReportParser(html).metadata()['metrics']['toolErrors'])
        self.assertIn('상태를 판단할 수 없습니다', render_markdown(report))

    def test_partial_and_truncated_are_visible_without_opening_details(self):
        report = example_report()
        report['summary']['status'] = 'partial'
        report['coverage']['truncated'] = True
        report['coverage']['warnings'] = ['일부 기록을 해석하지 못했습니다.']
        html = render_report(report)
        self.assertIn('일부 기록만 확인했습니다', html)
        self.assertIn('수집 한도에 도달하여 일부만 확인했습니다', html)
        self.assertIn('일부 기록을 해석하지 못했습니다', html)

    def test_hostile_values_cannot_inject_html_scripts_or_active_links(self):
        payload = '</script><script>alert(1)</script><img src=x onerror="alert(2)"><a href="javascript:alert(3)">x</a>'
        report = example_report()
        for key in ['generatedAt', 'generatorVersion']:
            report[key] = payload
        report['window']['since'] = payload
        report['summary'].update(title=payload, message=payload)
        for key in ['title', 'detail', 'evidence', 'nextStep', 'confidence', 'code']:
            report['findings'][0][key] = payload
        report['coverage']['warnings'] = [payload]
        report['limitations'] = [payload]
        report['comparison'] = {'status': payload, 'message': payload, 'rows': [{'label': payload, 'before': 1, 'after': 2, 'unit': payload}]}
        html = render_report(report)
        parsed = ReportParser(html)
        self.assertNotIn('<script', html)
        self.assertNotIn('</script', html)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;/script&gt;', html)
        self.assertNotIn('script', [tag for tag, attrs in parsed.elements])
        for tag, attrs in parsed.elements:
            self.assertFalse(any(key.startswith('on') for key in attrs))
            if 'href' in attrs:
                self.assertTrue(attrs['href'].startswith('data:text/markdown;'))
                self.assertIn('download', attrs)
        self.assertIn("script-src 'none'", html)
        self.assertIn("default-src 'none'", html)
        self.assertNotIn('<script', parsed.markdown())
        self.assertEqual(parsed.metadata()['metrics']['toolErrors'], 0)

    def test_download_is_same_utf8_markdown_and_source_is_unchanged(self):
        report = example_report()
        before = copy.deepcopy(report)
        html = render_report(report)
        markdown = render_markdown(report)
        self.assertEqual(markdown, ReportParser(html).markdown())
        self.assertIn('내 사용 흐름 점검', markdown)
        self.assertIn('같은 질문을 다시 확인했습니다', markdown)
        self.assertEqual(report, before)

    def test_markdown_does_not_turn_report_values_into_links_or_html(self):
        report = example_report()
        report['findings'][0]['detail'] = '![이미지](https://example.invalid/pixel) [열기](javascript:alert(1)) <iframe src="x"></iframe>'
        markdown = render_markdown(report)
        self.assertNotIn('![이미지](', markdown)
        self.assertNotIn('[열기](', markdown)
        self.assertNotIn('<iframe', markdown)
        self.assertIn('&lt;iframe', markdown)

    def test_at_most_three_findings_are_visible_and_exported(self):
        report = example_report()
        report['findings'] = [{**report['findings'][0], 'title': f'후보{index}'} for index in range(9)]
        html = render_report(report)
        self.assertEqual(3, html.count('<article class="finding">'))
        self.assertIn('먼저 확인할 3가지', html)
        self.assertNotIn('후보3', html)
        self.assertNotIn('후보3', ReportParser(html).markdown())

    def test_only_bounded_aggregate_projection_is_embedded_for_comparison(self):
        report = example_report()
        report.update(sourcePath='C:/secret/raw.jsonl', rawTranscript='RAW PRIVATE WORDS', extra={'instructions': 'DO THIS'})
        report['findings'][0]['sourcePath'] = report['sourcePath']
        report['metrics']['unknownField'] = report['rawTranscript']
        html = render_report(report)
        metadata = ReportParser(html).metadata()
        self.assertEqual({'schemaVersion', 'scopeKey', 'generatorVersion', 'window', 'metrics', 'comparison'}, set(metadata))
        self.assertEqual(metadata['scopeKey'], 'a' * 64)
        for value in [html, ReportParser(html).markdown(), json.dumps(metadata)]:
            self.assertNotIn('C:/secret', value)
            self.assertNotIn('RAW PRIVATE WORDS', value)
            self.assertNotIn('DO THIS', value)
        report['scopeKey'] = report['sourcePath']
        self.assertIsNone(ReportParser(render_report(report)).metadata()['scopeKey'])

    def test_comparison_shows_values_without_claiming_impact(self):
        report = example_report()
        report['comparison'] = {'status': 'comparable', 'message': '이전 보고서와 같은 조건입니다.', 'rows': [
            {'label': '같은 실패의 반복', 'before': 3, 'after': 0, 'unit': '회'},
            {'label': '질문 응답 대기', 'before': None, 'after': 3000, 'unit': 'ms'},
        ]}
        html = render_report(report)
        self.assertIn('이전 보고서와 비교', html)
        self.assertIn('<td>3 회</td><td>0 회</td>', html)
        self.assertIn('<td>기록 없음</td><td>3초</td>', html)
        self.assertIn('수치만으로 개선 효과를 판단할 수 없습니다', html)
        self.assertIn('3 회', ReportParser(html).markdown())
        self.assertEqual(ReportParser(html).metadata()['comparison']['rows'][0]['after'], 0)

    def test_report_and_metadata_size_are_bounded(self):
        report = example_report()
        huge = '<&' * 30_000
        report['findings'] = [{**report['findings'][0], **{key: huge for key in ['title', 'detail', 'nextStep', 'evidence', 'confidence']}}] * 200
        report['summary'].update(title=huge, message=huge)
        report['coverage']['warnings'] = [huge] * 100
        report['limitations'] = [huge] * 100
        report['comparison'] = {'status': huge, 'message': huge, 'rows': [{'label': huge, 'before': 0, 'after': 0, 'unit': huge}] * 100}
        html = render_report(report)
        self.assertLess(len(html.encode('utf-8')), 512_000)
        parsed = ReportParser(html)
        encoded = next(attrs['content'] for tag, attrs in parsed.elements if tag == 'meta' and attrs.get('name') == 'usability-report')
        self.assertLessEqual(len(base64.b64decode(encoded)), 16_384)

    def test_invalid_schema_and_invalid_counts_are_not_silently_zero(self):
        for report in [None, [], {}, {'schemaVersion': 2}, {'schemaVersion': True}]:
            with self.assertRaises(ValueError):
                render_report(report)
        report = example_report()
        report['metrics'].update(toolErrors=True, questionWaitMs=-1, requests='4')
        metadata = ReportParser(render_report(report)).metadata()
        self.assertIsNone(metadata['metrics']['toolErrors'])
        self.assertIsNone(metadata['metrics']['questionWaitMs'])
        self.assertIsNone(metadata['metrics']['requests'])
        report['summary']['status'] = []
        self.assertIn('판단할 기록이 없습니다', render_report(report))

    def test_write_utf8_html_exclusively_preserves_existing_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / '사용-점검.html'
            report = example_report()
            before = copy.deepcopy(report)
            self.assertIsNone(write_report(path, report))
            content = path.read_bytes()
            self.assertIn('내 사용 흐름'.encode('utf-8'), content)
            self.assertEqual(report, before)
            with self.assertRaises(FileExistsError):
                write_report(path, report)
            self.assertEqual(path.read_bytes(), content)
            with self.assertRaises(ValueError):
                write_report(path.with_suffix('.md'), report)
            self.assertFalse(path.with_suffix('.md').exists())

    def test_reparse_guard_precedes_any_write(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / 'report.html'
            with patch('company_agent.usability_report._no_reparse', side_effect=ValueError('reparse path skipped')) as guard:
                with self.assertRaisesRegex(ValueError, 'reparse'):
                    write_report(path, example_report())
                guard.assert_called_once_with(path.absolute())
            self.assertFalse(path.exists())

    def test_rendering_failure_does_not_create_empty_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / 'report.html'
            with self.assertRaises(ValueError):
                write_report(path, {'schemaVersion': 2})
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
