import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from work_catalog import Collector, clean, render
from work_process import MAX_REQUESTS, request_steps

EDUCATION = '교육 신청 CSV를 읽고 중복 신청을 제거한 뒤 부서별 신청 인원을 집계하고 강사 명단과 매칭한 후 HTML 현황을 만들어줘'
INVENTORY = '재고 CSV를 읽어 안전재고를 계산하고 발주표를 만들어줘'
SALES = '매출 CSV를 읽고 결측값을 정리한 후 월별 매출 HTML을 만들어줘'


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, name, messages, tools=('Read',), sid=None, save_asset=True):
        sid = sid or name
        rows = []
        for i, text in enumerate(messages):
            rows.append({'type': 'user', 'uuid': sid + ':' + str(i), 'sessionId': sid,
                         'message': {'content': text}})
            if tools and save_asset:
                # A persisted skill, rather than a read-only tool call, makes
                # this request eligible for the asset-focused detail report.
                call_id = sid + ':save:' + str(i)
                rows += [
                    {'type': 'assistant', 'uuid': call_id + ':call', 'sessionId': sid,
                     'message': {'content': [{'type': 'tool_use', 'id': call_id, 'name': 'Write',
                         'input': {'file_path': '.claude/skills/work-procedure/SKILL.md',
                                   'content': 'DO_NOT_EXPORT'}}]}},
                    {'type': 'user', 'uuid': call_id + ':result', 'sessionId': sid,
                     'message': {'content': [{'type': 'tool_result', 'tool_use_id': call_id,
                                             'is_error': False, 'content': 'DO_NOT_EXPORT'}]}}
                ]
        if tools:
            rows.append({'type': 'assistant', 'uuid': sid + ':tools', 'sessionId': sid,
                'message': {'content': [{'type': 'tool_use', 'name': t, 'input': {'secret': 'DO_NOT_EXPORT'}} for t in tools]}})
        path = self.root / (name + '.jsonl')
        path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')
        return path

    def collect(self):
        collector = Collector()
        collector.add_root(self.root, 'profile')
        return collector.result()

    def test_concrete_steps_and_independent_work_in_one_session(self):
        self.session('a', [EDUCATION, '그리고 ' + INVENTORY])
        report = self.collect()
        flows = {w['title']: w for w in report['work_analysis']['workflows']}
        self.assertEqual({'교육 신청', '재고'}, set(flows))
        self.assertEqual(['read', 'dedupe', 'aggregate', 'join', 'write'], [s['action'] for s in flows['교육 신청']['steps']])
        self.assertEqual(['교육 신청 CSV', '교육 신청 CSV 중복 항목', '부서별 신청 인원', '강사 명단', 'HTML 현황'], [s['target'] for s in flows['교육 신청']['steps']])
        self.assertEqual(['read', 'aggregate', 'write'], [s['action'] for s in flows['재고']['steps']])
        text = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(EDUCATION, text)
        self.assertNotIn('DO_NOT_EXPORT', text)
        self.assertEqual('not_inferred', report['work_analysis']['completion'])

    def test_explicit_switch_within_one_request_is_split(self):
        self.session('a', [EDUCATION + '. 별개로 ' + INVENTORY])
        report = self.collect()
        self.assertEqual({'교육 신청', '재고'}, {r['subject'] for r in report['sessions'][0]['work_requests']})
        # The request can be split, but its shared write does not establish
        # which one of the two procedures was saved.
        self.assertEqual([], report['work_analysis']['workflows'])
        self.assertEqual({'교육 신청', '재고'}, {w['title'] for w in report['work_analysis']['deferred_work']})
        self.assertTrue(all(w['selection_reason'] == 'ambiguous_save_evidence'
                            for w in report['work_analysis']['deferred_work']))

    def test_repeated_work_and_duplicate_files_not_inflated(self):
        for i in range(3):
            self.session('education' + str(i), [EDUCATION])
        self.session('copy', [EDUCATION], sid='education0')
        self.session('sales', [SALES])
        report = self.collect()
        flows = {w['title']: w for w in report['work_analysis']['workflows']}
        self.assertEqual(3, flows['교육 신청']['occurrences'])
        self.assertEqual(1, flows['매출']['occurrences'])
        exported = self.root / 'catalog.json'
        exported.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        merged = Collector(); merged.add_catalog(exported); merged.add_catalog(exported)
        self.assertEqual(3, next(w for w in merged.result()['work_analysis']['workflows'] if w['title'] == '교육 신청')['occurrences'])

    def test_followup_requests_preserve_observed_order(self):
        self.session('a', ['교육 신청 CSV를 읽어줘', '그다음 부서별 신청 인원을 집계해줘', '위 결과를 HTML 현황으로 만들어줘'])
        flows = self.collect()['work_analysis']['workflows']
        self.assertEqual(1, len(flows))
        self.assertEqual(['read', 'aggregate', 'write'], [s['action'] for s in flows[0]['steps']])
        self.assertEqual([100, 200, 300], [s['request_ordinal'] for s in flows[0]['steps']])

    def test_followup_marker_cannot_merge_an_explicit_new_work_target(self):
        self.session('a', [EDUCATION, '다음으로 재고 CSV를 계산해서 발주표를 작성해줘'])
        self.assertEqual({'교육 신청', '재고'}, {w['title'] for w in self.collect()['work_analysis']['workflows']})

    def test_one_step_repeated_is_featured_and_oneoff_or_failed_retained(self):
        self.session('one', ['계약서를 검토해줘'])
        self.session('two', ['계약서를 검토해줘'])
        self.session('three', ['안전교육 지침을 확인해줘'], save_asset=False)
        self.session('failed', ['발주표 오류를 확인해줘'], save_asset=False)
        report = self.collect()
        self.assertEqual('saved_asset', report['work_analysis']['workflows'][0]['selection_reason'])
        self.assertEqual('repeated', report['work_analysis']['workflows'][0]['structure_reason'])
        self.assertEqual(2, len(report['work_analysis']['deferred_work']))
        self.assertTrue(any(w['failure_mentioned'] for w in report['work_analysis']['deferred_work']))

    def test_non_work_and_ambiguous_are_candidates_not_workflows(self):
        for i, text in enumerate(['오늘 날씨 알려줘', '재미있는 농담해줘', '응', '왜?', '안녕하세요']):
            self.session(str(i), [text], tools=())
        report = self.collect()
        self.assertEqual(4, report['summary']['observed_sessions'])
        self.assertEqual([], report['work_analysis']['workflows'])
        self.assertEqual({'non_work': 2, 'insufficient': 2}, report['work_analysis']['excluded_candidates'])

    def test_negation_and_hypothetical_actions_not_presented_as_process(self):
        parsed = request_steps('계약서를 검토하되 메일로 전송하지 마', clean)
        self.assertEqual(['analyze'], [s['action'] for s in parsed['steps']])
        self.assertEqual('insufficient', request_steps('만약 보고서를 만들면 어떤 순서가 좋아? 아직 실행하지 마', clean)['kind'])
        self.assertEqual('insufficient', request_steps('계약서를 분석할 수 있는지 알려줘', clean)['kind'])
        self.assertEqual(['verify'], [s['action'] for s in request_steps('보고서를 만들지 말고 표만 확인해줘', clean)['steps']])

    def test_action_words_in_noun_phrases_do_not_invent_steps(self):
        parsed = request_steps('교육 집계 오류 원인을 확인해줘', clean)
        self.assertEqual(['verify'], [s['action'] for s in parsed['steps']])
        self.assertEqual('교육 집계 오류 원인', parsed['steps'][0]['target'])
        self.assertTrue(parsed['failure'])
        parsed = request_steps('교육 신청 CSV를 읽고 과정별 신청 인원을 집계해줘', clean)
        self.assertEqual(['read', 'aggregate'], [s['action'] for s in parsed['steps']])
        self.assertEqual('교육 신청', parsed['subject'])
        self.assertEqual(['write', 'verify'], [s['action'] for s in request_steps('매출 HTML을 만든 뒤 합계를 검증해줘', clean)['steps']])

    def test_different_order_variants_use_one_recorded_sequence_not_union(self):
        self.session('first', [EDUCATION])
        self.session('second', ['교육 신청 CSV를 읽고 담당자별 내역을 집계한 뒤 결과를 확인해줘'])
        flow = self.collect()['work_analysis']['workflows'][0]
        self.assertEqual(2, flow['sequence_variants'])
        self.assertTrue(any(flow['steps'] == e['steps'] for e in flow['episodes']))
        self.assertIn('관찰된 진행 방식 2종 비교', render(self.collect()))

    def test_label_spacing_and_file_format_not_different_work(self):
        self.session('a', ['교육 신청 CSV 중복을 제거하고 부서별 인원을 집계해줘'])
        self.session('b', ['교육신청CSV 중복을 제거하고 부서별 인원을 집계해줘'])
        flows = self.collect()['work_analysis']['workflows']
        self.assertEqual(1, len(flows))
        self.assertEqual(2, flows[0]['occurrences'])
        self.assertEqual(1, flows[0]['sequence_variants'])

    def test_filename_extension_and_common_english_requests(self):
        parsed = request_steps('교육신청.csv를 읽고 부서별 인원을 집계해줘', clean)
        self.assertEqual('교육신청', parsed['subject'])
        self.assertEqual('교육신청.csv', parsed['steps'][0]['target'])
        parsed = request_steps('Read sales.csv, remove duplicates, group by month and create an HTML report.', clean)
        self.assertEqual('sales', parsed['subject'])
        self.assertEqual(['read', 'dedupe', 'aggregate', 'write'], [s['action'] for s in parsed['steps']])
        self.assertEqual('sales.csv', parsed['steps'][0]['target'])
        self.assertEqual('month', parsed['steps'][2]['target'])
        self.assertNotIn('publish', [s['action'] for s in request_steps("Read sales.csv and do not send email", clean)['steps']])

    def test_step_storage_cap_is_visible_without_stopping_sessions(self):
        self.session('large', [EDUCATION] * (MAX_REQUESTS + 4))
        report = self.collect()
        self.assertEqual(MAX_REQUESTS + 4, len(report['sessions'][0]['user_events']))
        self.assertEqual(MAX_REQUESTS, len(report['sessions'][0]['work_requests']))
        self.assertTrue(report['sessions'][0]['workflow_partial'])
        self.assertTrue(report['work_analysis']['workflows'][0]['partial'])
        self.assertIn('업무 단계 요약 한도 · 세션 집계는 계속', report['coverage']['warnings'])

    def test_import_duplicate_request_ids_dedup_and_conflicting_labels_rejected(self):
        self.session('one', [EDUCATION]); report = self.collect()
        record = report['sessions'][0]['work_requests'][0]
        report['sessions'][0]['work_requests'].append(copy.deepcopy(record))
        path = self.root / 'export.json'; path.write_text(json.dumps(report), encoding='utf-8')
        merged = Collector(); merged.add_catalog(path)
        self.assertEqual(1, len(merged.result()['sessions'][0]['work_requests']))
        report['sessions'][0]['work_requests'][-1]['subject'] = '위조된 대상'
        path.write_text(json.dumps(report), encoding='utf-8')
        rejected = Collector(); rejected.add_catalog(path)
        self.assertEqual([], rejected.result()['sessions'])

    def test_old_exports_have_no_invented_steps_and_html_tables_scroll(self):
        self.session('one', [EDUCATION]); report = self.collect()
        report['sessions'][0].pop('work_requests')
        path = self.root / 'old.json'; path.write_text(json.dumps(report), encoding='utf-8')
        merged = Collector(); merged.add_catalog(path)
        self.assertEqual([], merged.result()['work_analysis']['workflows'])
        self.assertEqual({'no_step_evidence': 1}, merged.result()['work_analysis']['excluded_candidates'])
        page = render(self.collect())
        self.assertIn('role="region" tabindex="0" aria-label=', page)
        self.assertIn('min-width:860px', page)
        self.assertIn('position:sticky', page)
        self.assertIn('개별 단계와 직접 연결은 미확인', page)

    def test_import_work_request_without_steps_is_rejected_atomically(self):
        self.session('one', [EDUCATION]); report = self.collect()
        report['sessions'][0]['work_requests'][0]['steps'] = []
        path = self.root / 'invalid.json'; path.write_text(json.dumps(report), encoding='utf-8')
        collector = Collector(); collector.add_catalog(path)
        self.assertEqual([], collector.result()['sessions'])
        self.assertIn('재집계 파일 형식·크기·접근 오류', collector.warnings)


if __name__ == '__main__':
    unittest.main()
