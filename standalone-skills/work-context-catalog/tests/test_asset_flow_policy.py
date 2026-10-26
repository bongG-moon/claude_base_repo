import copy
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from work_process import request_steps, sanitize_request, summarize_work


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()


def clean(value, limit=180):
    return str(value)[:limit]


def request(text, number=1):
    return dict(request_steps(text, clean), id=h(text + str(number)), ordinal=number)


def event(req, kind='skill', status='returned', number=1):
    result = {'id': h('event' + str(number)), 'request_ids': [req['id']], 'ordinal': number,
        'tool': 'Write', 'operation': '파일 작성', 'target': 'SKILL.md',
        'status': status, 'evidence': 'tool_call', 'result_observed': status != 'unconfirmed',
        'request_group_ambiguous': False}
    if kind:
        result['asset_change'] = {'kind': kind, 'operation': 'create_or_update',
                                 'basis': 'target_path', 'target': '교육-신청'}
    return result


def session(name, requests, events=()):
    return {'id': h(name), 'work_requests': requests, 'execution_events': list(events),
        'origins': [{'root': 'profile-1', 'path': name + '.jsonl'}],
        'tool_events': {}, 'topics': ['문서·보고서'], 'user_events': [r['id'] for r in requests]}


class AssetFlowPolicyTests(unittest.TestCase):
    def test_shared_save_stays_unlinked_even_alongside_valid_save(self):
        req = request('교육 지식을 저장해줘')
        valid, shared = event(req), event(req, number=2)
        shared['request_ids'].append(h('other task'))
        shared['request_group_ambiguous'] = True
        shared['asset_change']['target'] = 'shared-other-work'
        result = summarize_work([session('mixed', [req], [valid, shared])])
        self.assertEqual(1, len(result['workflows']))
        self.assertEqual(1, result['asset_activity']['flow_linked_changes'])
        self.assertEqual(1, result['asset_activity']['unlinked_changes'])
        self.assertNotIn('shared-other-work', result['workflows'][0]['asset_title'])

    def test_saved_and_unsaved_occurrences_do_not_share_detailed_group(self):
        req = request('교육 신청 CSV를 읽고 중복 신청을 제거한 뒤 부서별 신청 인원을 집계해줘')
        saved = session('saved', [req], [event(req)])
        other = session('other', [req], [event(req, None)])
        inputs = [saved, other]
        before = copy.deepcopy(inputs)
        report = summarize_work(inputs)
        self.assertEqual(before, inputs)
        self.assertEqual('saved_assets', report['selection_policy'])
        self.assertEqual(1, len(report['workflows']))
        flow = report['workflows'][0]
        self.assertEqual([saved['id']], flow['session_ids'])
        self.assertEqual(1, flow['occurrences'])
        self.assertEqual('saved_asset', flow['selection_reason'])
        self.assertEqual('process', flow['structure_reason'])
        self.assertEqual(1, len(report['deferred_work']))
        self.assertEqual('no_save_evidence', report['deferred_work'][0]['selection_reason'])
        self.assertNotIn('episodes', report['deferred_work'][0])
        self.assertNotIn('steps', report['deferred_work'][0])

    def test_failed_unconfirmed_and_ambiguous_saves_are_not_detail_candidates(self):
        req = request('교육 지식을 저장해줘')
        failed, uncertain = event(req, 'knowledge', 'error'), event(req, 'memory', 'unconfirmed')
        shared = event(req)
        shared['request_ids'].append(h('another request'))
        shared['request_group_ambiguous'] = True
        report = summarize_work([session('error', [req], [failed]),
            session('unknown', [req], [uncertain]), session('ambiguous', [req], [shared])])
        self.assertEqual([], report['workflows'])
        self.assertEqual({'save_failed', 'save_unconfirmed', 'ambiguous_save_evidence'},
                         {g['selection_reason'] for g in report['deferred_work']})
        self.assertEqual({'error': 1, 'unconfirmed': 1, 'returned': 1}, report['asset_activity']['by_status'])
        self.assertEqual(3, report['asset_activity']['unlinked_changes'])

    def test_single_saved_step_is_candidate_without_claiming_success(self):
        req = request('교육 매뉴얼 지식을 저장해줘')
        observed = event(req, 'knowledge')
        observed['tool'] = 'mcp__datalake__save_query_knowledge'
        observed['asset_change']['basis'] = 'persistence_tool'
        report = summarize_work([session('one', [req], [observed])])
        flow = report['workflows'][0]
        self.assertEqual('single_step', flow['structure_reason'])
        self.assertEqual('not_inferred', report['completion'])
        self.assertEqual('returned', flow['asset_evidence'][0]['status'])
        self.assertEqual(1, report['asset_activity']['flow_linked_changes'])

    def test_skill_load_and_definition_word_overlap_do_not_select_flow(self):
        req = request('교육 신청 CSV를 읽고 부서별 신청 인원을 집계해줘')
        load = event(req, None)
        load.update(tool='Skill', operation='스킬 불러오기', target='교육-신청')
        definition = {'kind': 'skill', 'title': '교육 신청 CSV', 'description': '부서별 신청 인원 집계'}
        report = summarize_work([session('load', [req], [load])], [definition])
        self.assertEqual([], report['workflows'])
        self.assertEqual(1, report['asset_activity']['definition_assets'])
        self.assertEqual(0, report['asset_activity']['observed_changes'])

    def test_explicit_asset_followup_preserves_original_work_sequence(self):
        initial = request('교육 신청 CSV를 읽고 부서별 신청 인원을 집계해줘')
        followup = request('좋아 이 작업을 스킬로 만들어줘', 2)
        self.assertTrue(followup['asset_followup'])
        self.assertTrue(sanitize_request(followup, clean)['asset_followup'])
        read = event(initial, None)
        read.update(tool='Read', operation='파일 내용 읽기')
        save = event(followup, number=2)
        report = summarize_work([session('followup', [initial, followup], [read, save])])
        self.assertEqual(1, len(report['workflows']))
        flow = report['workflows'][0]
        self.assertEqual('교육 신청', flow['title'])
        self.assertEqual(['read', 'aggregate', 'write'], [s['action'] for s in flow['steps']])
        self.assertEqual(2, flow['execution_count'])
        self.assertEqual({'Read': 1, 'Write': 1}, flow['tools'])

    def test_explicit_topic_switch_never_attaches_save_to_prior_work(self):
        initial = request('교육 신청 CSV를 읽고 신청 인원을 집계해줘')
        followup = request('별개로 재고 정리 스킬을 만들어줘', 2)
        self.assertFalse(followup['asset_followup'])
        report = summarize_work([session('switch', [initial, followup], [event(followup)])])
        self.assertEqual(1, len(report['workflows']))
        self.assertNotEqual('교육 신청', report['workflows'][0]['title'])
        self.assertEqual(1, report['workflows'][0]['request_count'])
        self.assertEqual(1, len(report['deferred_work']))

    def test_conflicting_change_evidence_is_not_used(self):
        req = request('교육 지식을 저장해줘')
        observed = event(req)
        observed['asset_change_conflict'] = True
        report = summarize_work([session('conflict', [req], [observed])])
        self.assertEqual([], report['workflows'])

    def test_unlinked_save_is_counted_without_inventing_a_workflow(self):
        req = request('교육 지식을 저장해줘')
        observed = event(req)
        observed['request_ids'] = []
        report = summarize_work([session('unlinked', [], [observed])])
        self.assertEqual([], report['workflows'])
        self.assertEqual(1, report['asset_activity']['observed_changes'])
        self.assertEqual(1, report['asset_activity']['unlinked_changes'])

    def test_legacy_requests_without_new_flag_remain_valid(self):
        req = request('교육 신청 스킬을 만들어줘')
        req.pop('asset_followup', None)
        self.assertFalse(sanitize_request(req, clean)['asset_followup'])
        report = summarize_work([session('legacy', [req])])
        self.assertEqual([], report['workflows'])
        self.assertEqual(1, len(report['deferred_work']))

    def test_asset_display_title_uses_observed_name_without_replacing_subject(self):
        req = request('이거 지금 기능을 수정해줘')
        events = [event(req, number=n) for n in range(1, 5)]
        for observed, name in zip(events, ['lolps-recent-games', 'lolps-recent-games', '교육-신청', 'project-glossary']):
            observed['asset_change']['target'] = name
        report = summarize_work([session('names', [req], events)])
        flow = report['workflows'][0]
        self.assertEqual(flow['title'], flow['request_subject'])
        self.assertEqual('lolps-recent-games / 교육-신청 외 1개 · 스킬 생성·수정', flow['asset_title'])

    def test_generic_memory_filename_uses_kind_without_invented_domain(self):
        req = request('교육 지식을 저장해줘')
        observed = event(req, 'memory')
        observed['asset_change']['target'] = 'MEMORY.md'
        flow = summarize_work([session('generic', [req], [observed])])['workflows'][0]
        self.assertEqual('기억 저장·수정', flow['asset_title'])

    def test_pasted_html_attributes_and_hidden_code_do_not_become_steps(self):
        text = ('<input id="default-read" class="block-write" title="save > check">'
                '<!-- create default-table -->'
                '<script>read(data); save(data);</script>'
                '<style>.write { display: block; }</style>'
                '<p>교육 신청 CSV를 <strong title="save">읽고</strong> 부서별 인원을 집계해줘</p>')
        parsed = request_steps(text, clean)
        self.assertEqual('교육 신청', parsed['subject'])
        self.assertEqual(['read', 'aggregate'], [s['action'] for s in parsed['steps']])
        self.assertFalse(any('default' in s['target'] or 'class' in s['target'] for s in parsed['steps']))

    def test_html_only_attributes_are_not_work_and_plain_inequality_survives(self):
        parsed = request_steps('<input id="default-write" value="read create save">', clean)
        self.assertEqual('insufficient', parsed['kind'])
        parsed = request_steps('재고 < 10인 항목을 확인해줘', clean)
        self.assertEqual(['verify'], [s['action'] for s in parsed['steps']])


if __name__ == '__main__':
    unittest.main()
