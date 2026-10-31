import base64
import copy
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from work_report import render_report, render_markdown, related_definitions, FOLLOWUP_LINKS


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.links, self.ids, self.scripts, self.regions = [], set(), [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.add(attrs['id'])
        if tag == 'a':
            self.links.append(attrs)
        if tag == 'script':
            self.scripts.append(attrs)
        if attrs.get('role') == 'region':
            self.regions.append(attrs)


def example():
    sid, rid, eid, fid, aid = 'a' * 64, 'b' * 64, 'c' * 64, 'd' * 16, 'e' * 64
    steps = [{'action': 'read', 'target': '교육신청.csv', 'operation': '자료 읽기',
              'request_id': rid, 'request_ordinal': 100},
             {'action': 'aggregate', 'target': '부서별 신청 인원', 'operation': '집계',
              'request_id': rid, 'request_ordinal': 100},
             {'action': 'write', 'target': '교육신청.html', 'operation': '문서 작성',
              'request_id': rid, 'request_ordinal': 100}]
    events = [
        {'id': '1' * 64, 'request_ids': [rid], 'ordinal': 1, 'tool': 'Read',
         'operation': '파일 읽기', 'target': '교육신청.csv', 'status': 'returned',
         'result_observed': True, 'evidence': 'tool_call', 'request_group_ambiguous': False},
        {'id': '2' * 64, 'request_ids': [rid], 'ordinal': 2, 'tool': 'Bash',
         'operation': 'Python 실행', 'target': '교육집계.py', 'status': 'error',
         'result_observed': True, 'evidence': 'tool_call', 'request_group_ambiguous': False},
        {'id': '3' * 64, 'request_ids': [rid], 'ordinal': 3, 'tool': 'Write',
         'operation': '파일 쓰기', 'target': '교육신청.html', 'status': 'unconfirmed',
         'result_observed': False, 'evidence': 'tool_call', 'request_group_ambiguous': False}]
    session = {'id': sid, 'origins': [{'root': 'profile-01', 'path': 'projects/session.jsonl'}],
               'user_events': [rid], 'tool_events': {'Read': ['1' * 64], 'Bash': ['2' * 64], 'Write': ['3' * 64]},
               'intents': [], 'project_roots': ['project-01'], 'execution_events': events}
    episode = {'id': eid, 'session_id': sid, 'request_ids': [rid], 'steps': steps,
               'execution_events': events, 'execution_partial': False}
    flow = {'id': fid, 'title': '교육 신청', 'steps': steps, 'episodes': [episode],
            'occurrences': 1, 'session_ids': [sid], 'origins': session['origins'],
            'selection_reason': 'process', 'sequence_variants': 1, 'tools': {'Read': 1, 'Bash': 1, 'Write': 1},
            'representative_session': sid, 'failure_mentioned': False, 'partial': False}
    asset = {'id': aid, 'title': '교육 신청 상태', 'description': '신청과 취소를 구분하는 업무 용어 정의.',
             'kind': 'knowledge', 'topics': ['지식·업무 기준'],
             'origins': [{'root': 'project-01', 'path': 'knowledge/교육.md'}]}
    return {'generated_at': '2026-10-26T00:00:00+00:00', 'schema_version': 1,
            'kind': 'work-context-catalog', 'assets': [asset], 'sessions': [session],
            'roots': [{'id': 'project-01', 'scope': 'project', 'environment': '업무 폴더'}],
            'summary': {'defined_assets': 1, 'observed_sessions': 1, 'topic_definitions': {'지식·업무 기준': 1}},
            'coverage': {'warnings': {}, 'limits': {'session_events': 200000},
                         'session_scan': {'files_found': 1, 'files_scanned': 1, 'files_kept': 1}},
            'work_analysis': {'workflows': [flow], 'deferred_work': [], 'excluded_candidates': {}}}


class ReportTests(unittest.TestCase):
    def test_followup_basis_or_uncertainty_is_visible_in_both_reports(self):
        for basis, message in FOLLOWUP_LINKS.items():
            with self.subTest(basis=basis):
                report = example()
                report['work_analysis']['workflows'][0]['steps'][-1]['followup_link'] = basis
                self.assertIn(message, render_report(report))
                self.assertIn(message, render_markdown(report))

    def test_asset_name_heads_flow_without_inventing_business_meaning(self):
        report = example()
        flow = report['work_analysis']['workflows'][0]
        flow['asset_title'] = 'education-summary · 스킬 생성·수정'
        self.assertIn('<h3>education-summary · 스킬 생성·수정</h3>', render_report(report))
        self.assertIn('## education-summary · 스킬 생성·수정', render_markdown(report))
        self.assertIn('관찰한 업무 대상: 교육 신청', render_markdown(report))

    def test_shared_save_not_presented_as_work_specific_selection_evidence(self):
        from work_report import _asset_evidence
        report = example()
        flow = report['work_analysis']['workflows'][0]
        event = flow['episodes'][0]['execution_events'][0]
        event['asset_change'] = {'kind': 'skill', 'operation': 'create_or_update',
                                'basis': 'target_path', 'target': 'shared-skill'}
        event['status'] = 'returned'
        event['request_group_ambiguous'] = True
        event['request_ids'].append('e' * 64)
        self.assertEqual([], _asset_evidence(flow))

    def test_all_sessions_classified_but_only_asset_flows_get_details(self):
        report = example()
        report['sessions'][0]['topics'] = ['자료 분석·정리']
        report['sessions'].append({'id': 'f' * 64, 'topics': ['웹·업무 자동화'],
            'origins': [{'root': 'profile-01', 'path': 'projects/ordinary.jsonl'}],
            'execution_events': [{'purpose': {'text': 'ORDINARY_TRACE_MUST_NOT_APPEAR',
                                              'basis': 'invocation_description'}}]})
        report['work_analysis']['deferred_work'] = [{'id': 'e' * 16, 'title': 'ORDINARY_DETAIL_OMITTED',
            'selection_reason': 'no_save_evidence', 'session_ids': ['f' * 64]}]
        for text in (render_report(report), render_markdown(report)):
            self.assertIn('웹·업무 자동화', text)
            self.assertIn('유형만 분류', text)
            self.assertIn('ordinary.jsonl', text)
            self.assertNotIn('ORDINARY_TRACE_MUST_NOT_APPEAR', text)
            self.assertNotIn('ORDINARY_DETAIL_OMITTED', text)
        page = render_report(report)
        self.assertLess(page.index('id="sessions"'), page.index('id="workflows"'))

    def test_asset_selection_evidence_and_failed_save_are_distinct(self):
        report = example()
        event = report['work_analysis']['workflows'][0]['episodes'][0]['execution_events'][0]
        event['asset_change'] = {'kind': 'skill', 'operation': 'create_or_update',
                                'basis': 'target_path', 'target': '교육신청정리'}
        event['status'] = 'returned'
        report['work_analysis']['deferred_work'] = [{'id': 'd' * 16, 'title': '저장 실패 업무',
            'selection_reason': 'save_failed', 'representative_session': report['sessions'][0]['id'],
            'occurrences': 1}]
        for text in (render_report(report), render_markdown(report)):
            self.assertIn('상세 FLOW', text)
            self.assertIn('교육신청정리', text)
            self.assertIn('저장 중 오류 관찰', text)
            self.assertIn('저장 성공을 추가', text)

    def test_standalone_download_exactly_matches_written_markdown(self):
        report = example()
        page = Page(render_report(report))
        link = next(a for a in page.links if a.get('id') == 'download-markdown')
        self.assertEqual('업무자산.md', link['download'])
        decoded = base64.b64decode(link['href'].split(',', 1)[1]).decode('utf-8')
        self.assertEqual(render_markdown(report), decoded)
        self.assertFalse(page.scripts)
        self.assertTrue(all(a['href'].startswith(('#', 'data:text/markdown;')) for a in page.links))

    def test_guide_reading_layout_retains_valid_section_structure(self):
        class BalancedPage(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack, self.errors = [], []

            def handle_starttag(self, tag, attrs):
                if tag not in ('meta', 'br', 'hr', 'img', 'link', 'input', 'wbr'):
                    self.stack.append(tag)

            def handle_endtag(self, tag):
                if not self.stack or self.stack[-1] != tag:
                    self.errors.append((tag, list(self.stack)))
                else:
                    self.stack.pop()

        for report in (example(), {}):
            source = render_report(report)
            page = BalancedPage()
            page.feed(source)
            self.assertEqual([], page.errors)
            self.assertEqual([], page.stack)
            self.assertLess(source.index('id="report-start"'), source.index('class="guide-nav" open'))
            self.assertLess(source.index('class="guide-nav" open'), source.index('id="workflows"'))
            self.assertEqual(5, source.count('class="report-section card"'))
            self.assertIn('id="download-markdown"', source)

    def test_requested_process_and_actual_calls_preserve_different_orders(self):
        report = example()
        # The call trace is unsorted on purpose; request steps are a different sequence.
        report['work_analysis']['workflows'][0]['episodes'][0]['execution_events'].reverse()
        text = render_markdown(report)
        self.assertLess(text.index('1. 교육신청'), text.index('2. 부서별'))
        table = text.split('| 순서 |', 1)[1]
        self.assertLess(table.index('파일 읽기'), table.index('Python 실행'))
        self.assertLess(table.index('Python 실행'), table.index('파일 쓰기'))
        for value in ('응답 관찰', '오류 관찰', '결과 미확인', '업무 성공을 의미하지 않습니다'):
            self.assertIn(value, text)
        self.assertIn('실제 결과물 완성·정확성: 미검증', text)

    def test_trace_details_are_present_in_html_not_only_export(self):
        page = render_report(example())
        for value in ('교육집계.py', 'Python 실행', 'Bash', '오류 관찰', 'Claude Code·Codex가 실제 한 동작 보기'):
            self.assertIn(value, page)
        self.assertIn('class="execution-detail"', page)
        self.assertIn('class="episode" open', page)
        self.assertIn('하위 작업자의 내부 기록은 포함하지 않습니다', page)

    def test_action_purpose_and_evidence_are_in_html_and_markdown(self):
        report = example()
        event = report['work_analysis']['workflows'][0]['episodes'][0]['execution_events'][1]
        event['purpose'] = {'text': '신청 표의 중복을 제거하고 부서별 인원을 집계하려는 코드입니다.',
                            'basis': 'code_structure'}
        for text in (render_report(report), render_markdown(report)):
            self.assertIn(event['purpose']['text'], text)
            self.assertIn('코드 구조에서 확인한 처리', text)
            self.assertIn('오류 관찰', text)
            self.assertIn('하려던 일·처리 설명', text)
        page = render_report(report)
        self.assertLess(page.index(event['purpose']['text']), page.index('Python 실행 · Bash'))

    def test_legacy_call_does_not_borrow_whole_workflow_as_its_purpose(self):
        for text in (render_report(example()), render_markdown(example())):
            self.assertIn('구체적으로 무엇을 처리하려 했는지는 기록에서 확인하지 못했습니다.', text)
            self.assertIn('목적 미확인', text)

    def test_claude_only_scope_does_not_label_its_calls_as_codex(self):
        report = example()
        report['roots'][0]['environment'] = 'Claude'
        self.assertIn('Claude Code가 실제 한 동작 보기', render_report(report))
        self.assertIn('Claude Code가 실제 호출한 동작', render_markdown(report))
        self.assertNotIn('Claude Code·Codex가', render_report(report))

    def test_conflicting_purpose_is_not_shown_as_a_confirmed_description(self):
        report = example()
        event = report['work_analysis']['workflows'][0]['episodes'][0]['execution_events'][0]
        event['purpose_conflict'] = True
        event['purpose'] = {'text': 'CONFLICTING_DESCRIPTION', 'basis': 'invocation_description'}
        for text in (render_report(report), render_markdown(report)):
            self.assertIn('기록마다 달라 확인이 필요', text)
            self.assertNotIn('CONFLICTING_DESCRIPTION', text)

    def test_declared_purpose_is_not_confirmation_and_is_escaped(self):
        report = example()
        event = report['work_analysis']['workflows'][0]['episodes'][0]['execution_events'][0]
        event['purpose'] = {'text': '<script>alert(1)</script> [실행](javascript:alert(1))',
                            'basis': 'invocation_description'}
        for text in (render_report(report), render_markdown(report)):
            self.assertIn('AI가 작성한 설명', text)
            self.assertNotIn('<script>', text)
            self.assertIn('응답 관찰', text)

    def test_legacy_trace_absence_is_unknown_not_no_execution(self):
        report = example()
        del report['work_analysis']['workflows'][0]['episodes'][0]['execution_events']
        del report['sessions'][0]['execution_events']
        for text in (render_report(report), render_markdown(report)):
            self.assertIn('이전 내보내기', text)
            self.assertIn('미실행으로 단정하지 않습니다', text)

    def test_ambiguous_and_partial_evidence_remain_visible(self):
        report = example()
        episode = report['work_analysis']['workflows'][0]['episodes'][0]
        episode['execution_partial'] = True
        episode['execution_events'][1]['request_ids'].append('f' * 64)
        episode['execution_events'][1]['request_group_ambiguous'] = True
        for text in (render_report(report), render_markdown(report)):
            self.assertIn('여러 업무가 공유하는 호출', text)
            self.assertIn('일부 기록만 확인했습니다', text)
        self.assertEqual(1, render_markdown(report).count('| 순서 |'))

    def test_html_and_markdown_escape_active_content(self):
        report = example()
        malicious = '<script>alert(1)</script> [실행](javascript:alert(1)) | `code`'
        report['work_analysis']['workflows'][0]['title'] = malicious
        report['assets'][0]['description'] = malicious
        report['work_analysis']['workflows'][0]['episodes'][0]['execution_events'][0]['target'] = malicious
        page = render_report(report)
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
        text = render_markdown(report)
        self.assertNotIn('[실행](javascript:', text)
        self.assertNotIn('<script>', text)
        self.assertIn(r'\[실행\]\(javascript:', text)
        self.assertIn(r'\|', text)

    def test_extra_raw_fields_are_never_rendered(self):
        report = example()
        report['sessions'][0]['raw_message'] = 'RAW_HISTORY_PRIVATE'
        event = report['work_analysis']['workflows'][0]['episodes'][0]['execution_events'][0]
        event.update(input={'password': 'INPUT_PRIVATE'}, output='OUTPUT_PRIVATE', thinking='THINKING_PRIVATE')
        page, text = render_report(report), render_markdown(report)
        for value in ('RAW_HISTORY_PRIVATE', 'INPUT_PRIVATE', 'OUTPUT_PRIVATE', 'THINKING_PRIVATE'):
            self.assertNotIn(value, page)
            self.assertNotIn(value, text)

    def test_definition_candidates_need_subject_words_and_keep_sources(self):
        report = example()
        report['assets'].append({'id': 'f' * 64, 'title': 'Python HTML 도구',
                                 'description': '일반 데이터 보고서', 'kind': 'skill', 'origins': []})
        flow = report['work_analysis']['workflows'][0]
        candidates = related_definitions(flow, report['assets'])
        self.assertEqual(['교육 신청 상태'], [a['title'] for a, _ in candidates])
        text = render_markdown(report)
        self.assertIn('knowledge/교육', text)
        self.assertIn('검증된 도메인 규칙은 아닙니다', text)
        self.assertIn('신청과 취소를 구분', text)

    def test_missing_definitions_do_not_invent_rules(self):
        report = example(); report['assets'] = []
        for text in (render_markdown(report), render_report(report)):
            self.assertIn('직접 연결할 정의를 찾지 못했습니다', text)

    def test_sources_and_asset_links_resolve_in_single_file(self):
        page = Page(render_report(example()))
        for link in page.links:
            if link['href'].startswith('#'):
                self.assertIn(link['href'][1:], page.ids)
        self.assertTrue(page.regions)
        self.assertTrue(all(r.get('tabindex') == '0' and r.get('aria-label') for r in page.regions))

    def test_repeated_episodes_are_kept_separate(self):
        report = example()
        flow = report['work_analysis']['workflows'][0]
        extra = copy.deepcopy(flow['episodes'][0])
        extra['id'] = 'f' * 64
        extra['execution_events'] = []
        flow['episodes'].append(extra); flow['occurrences'] = 2
        page, text = render_report(report), render_markdown(report)
        self.assertIn('관찰 묶음 2', page)
        self.assertIn('#### 관찰 묶음 2', text)
        self.assertIn('3개 호출 근거', page)  # Duplicates do not inflate the overall call badge.

    def test_empty_report_and_old_inventory_are_supported(self):
        for report in ({}, {'assets': [], 'sessions': [], 'coverage': {}, 'summary': {}}):
            page, text = render_report(report), render_markdown(report)
            self.assertIn('상세 흐름으로 묶을 근거가 부족', page)
            self.assertIn('상세 흐름으로 묶을 근거가 부족', text)
            self.assertIn('catalog.json', text)

    def test_schema_ids_and_coverage_remain_in_markdown(self):
        report = example()
        report['coverage']['warnings'] = {'하위 작업자 세션 이벤트 제외': 3}
        text = render_markdown(report)
        for identifier in ('a' * 64, 'b' * 64, 'c' * 64, 'd' * 16, 'e' * 64):
            self.assertIn(identifier, text)
        self.assertIn('하위 작업자 세션 이벤트 제외: 3', text)
        self.assertIn('200000', text)

    def test_module_loads_without_harness(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/work_report.py'
        spec = importlib.util.spec_from_file_location('portable_report_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(render_markdown(example()), module.render_markdown(example()))


if __name__ == '__main__':
    unittest.main()
