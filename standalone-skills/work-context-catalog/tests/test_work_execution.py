import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from work_catalog import Collector, clean
from work_execution import MAX_EXECUTIONS, ExecutionTrace, describe, result_state, safe_target


REQUEST = '교육 신청 CSV를 읽고 부서별 인원을 집계한 뒤 HTML 현황을 만들어줘'


def user(text=REQUEST, uuid='u1'):
    return {'type': 'user', 'uuid': uuid, 'sessionId': 'sample', 'message': {'content': text}}


def call(name, args=None, call_id='c1', uuid='a1'):
    return {'type': 'assistant', 'uuid': uuid, 'sessionId': 'sample', 'message': {
        'content': [{'type': 'tool_use', 'name': name, 'id': call_id, 'input': args or {}}]}}


def result(call_id='c1', error=False, value='PRIVATE CONTENT'):
    return {'type': 'user', 'uuid': 'r' + call_id, 'sessionId': 'sample', 'message': {
        'content': [{'type': 'tool_result', 'tool_use_id': call_id, 'is_error': error, 'content': value}]}}


def saved_skill(suffix='1'):
    """A real tool-call/result envelope; never inject derived asset metadata."""
    return [call('Write', {'file_path': '.claude/skills/work-procedure/SKILL.md',
                           'content': 'PRIVATE BODY'}, 'save-' + suffix, 'save-event-' + suffix),
            result('save-' + suffix)]


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def collect(self, rows, limits=None, duplicate=False):
        payload = '\n'.join(json.dumps(row, ensure_ascii=False) for row in rows)
        (self.root / 'sample.jsonl').write_text(payload, encoding='utf-8')
        if duplicate:
            (self.root / 'copy.jsonl').write_text(payload, encoding='utf-8')
        collector = Collector(limits)
        collector.add_root(self.root, 'profile')
        return collector.result()

    def test_claude_result_rows_keep_request_window_and_explicit_failure(self):
        report = self.collect([user(), call('Read', {'file_path': r'C:\private\교육신청.csv'}), result(),
                               call('Write', {'file_path': 'result.html', 'content': 'PRIVATE BODY'}, 'c2', 'a2'), result('c2', True),
                               *saved_skill()])
        session = report['sessions'][0]
        self.assertEqual(1, len(session['user_events']))
        self.assertEqual(1, len(session['work_requests']))
        events = session['execution_events']
        self.assertEqual(['returned', 'error', 'returned'], [event['status'] for event in events])
        self.assertEqual(['파일 내용 읽기', '파일 작성', '파일 작성'], [event['operation'] for event in events])
        self.assertEqual(['교육신청.csv', 'result.html', 'SKILL.md'], [event['target'] for event in events])
        self.assertEqual([1, 2, 3], [event['ordinal'] for event in events])
        self.assertEqual(events[0]['request_ids'], events[1]['request_ids'])
        self.assertEqual(events, report['work_analysis']['workflows'][0]['episodes'][0]['execution_events'])
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertNotIn('C:\\private', json.dumps(report))

    def test_claude_bookkeeping_between_request_and_call_keeps_attribution(self):
        records = [{'type': kind, 'sessionId': 'sample', 'attachment': {'type': 'hook_context', 'content': 'PRIVATE PROMPT'},
                    'rendered': '재고 CSV를 읽고 HTML 작성해줘 PRIVATE', 'renderedRole': 'user'}
                   for kind in ('attachment', 'last-prompt', 'atis-latch', 'cost-state', 'mode',
                                'permission-mode', 'ai-title', 'api-request-shape', 'file-history-delta')]
        report = self.collect([user(), *records,
                               call('Bash', {'command': 'python work.py', 'description': '교육 신청 인원을 부서별로 집계'}), result(),
                               *saved_skill()])
        session = report['sessions'][0]
        event = session['execution_events'][0]
        self.assertEqual([session['work_requests'][0]['id']], event['request_ids'])
        self.assertFalse(session['execution_partial'])
        self.assertEqual('returned', event['status'])
        self.assertEqual(event, report['work_analysis']['workflows'][0]['episodes'][0]['execution_events'][0])
        self.assertEqual(1, len(session['user_events']))
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_api_request_copies_do_not_duplicate_or_replace_live_request(self):
        copies = [{'type': kind, 'sessionId': 'sample', 'message': {'role': 'user', 'content': 'PRIVATE 예전 요청'},
                   'params': {'messages': [user('PRIVATE'), call('Write', {'content': 'PRIVATE'})]}}
                  for kind in ('api-request', 'api-request-blob')]
        report = self.collect([user(), *copies, call('Read'), result()])
        session = report['sessions'][0]
        self.assertEqual(1, len(session['user_events']))
        self.assertEqual(1, len(session['execution_events']))
        self.assertEqual([session['work_requests'][0]['id']], session['execution_events'][0]['request_ids'])
        self.assertFalse(session['execution_partial'])
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_unknown_new_record_still_breaks_request_attribution(self):
        report = self.collect([user(), {'type': 'unknown-future-context'}, call('Read'), result()])
        event = report['sessions'][0]['execution_events'][0]
        self.assertEqual([], event['request_ids'])
        self.assertTrue(report['sessions'][0]['execution_partial'])

    def test_different_request_targets_receive_only_their_calls(self):
        report = self.collect([user(), call('Read'), result(), *saved_skill('education'),
                               user('재고 CSV를 읽고 안전재고를 계산해줘', 'u2'),
                               call('Bash', {'command': 'python compute.py'}, 'c2', 'a2'), result('c2'), *saved_skill('inventory')])
        flows = {flow['title']: flow for flow in report['work_analysis']['workflows']}
        self.assertEqual(['Read', 'Write'], [e['tool'] for e in flows['교육 신청']['episodes'][0]['execution_events']])
        self.assertEqual(['Bash', 'Write'], [e['tool'] for e in flows['재고']['episodes'][0]['execution_events']])

    def test_multiple_tasks_in_a_single_request_are_explicitly_ambiguous(self):
        report = self.collect([user(REQUEST + '. 별개로 재고 CSV를 읽고 안전재고를 계산해줘'), call('Read'), result(), *saved_skill()])
        event = report['sessions'][0]['execution_events'][0]
        self.assertEqual(2, len(event['request_ids']))
        self.assertTrue(event['request_group_ambiguous'])
        self.assertEqual([], report['work_analysis']['workflows'])
        self.assertEqual(2, len(report['work_analysis']['deferred_work']))
        self.assertTrue(all(flow['selection_reason'] == 'ambiguous_save_evidence'
                            for flow in report['work_analysis']['deferred_work']))

    def test_codex_response_envelopes_ignore_duplicate_event_messages(self):
        rows = [
            {'type': 'session_meta', 'payload': {'id': 'codex-session'}},
            {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': REQUEST}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                'content': [{'type': 'input_text', 'text': REQUEST}]}},
            {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'codex-call',
                'name': 'exec_command', 'arguments': json.dumps({'cmd': 'python process.py --token SUPERSECRET'})}},
            {'type': 'event_msg', 'payload': {'type': 'agent_message', 'message': 'PRIVATE SUMMARY'}},
            {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'codex-call',
                'output': json.dumps({'exit_code': 1, 'output': 'PRIVATE RESULT'})}},
        ]
        report = self.collect(rows)
        session = report['sessions'][0]
        self.assertEqual(1, len(session['user_events']))
        self.assertEqual(1, len(session['execution_events']))
        event = session['execution_events'][0]
        self.assertEqual('Python 코드 실행', event['operation'])
        self.assertEqual('error', event['status'])
        self.assertEqual('process.py', event['target'])
        self.assertNotIn('SUPERSECRET', json.dumps(report))
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_codex_custom_tool_calls_do_not_export_patch_source(self):
        report = self.collect([
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': REQUEST}},
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'call_id': 'patch',
                'name': 'apply_patch', 'input': '*** Begin Patch\nPRIVATE CODE'}},
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': 'patch', 'output': 'done'}},
        ])
        event = report['sessions'][0]['execution_events'][0]
        self.assertEqual('파일 수정', event['operation'])
        self.assertEqual('returned', event['status'])
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_response_is_not_task_success_and_missing_response_is_unconfirmed(self):
        report = self.collect([user(), call('Read'), result(value='successfully read everything'),
                               call('Write', {}, 'c2', 'a2')])
        events = report['sessions'][0]['execution_events']
        self.assertEqual(['returned', 'unconfirmed'], [event['status'] for event in events])
        self.assertEqual([True, False], [event['result_observed'] for event in events])
        self.assertEqual('not_inferred', report['work_analysis']['completion'])

    def test_result_before_call_never_becomes_result_of_another_call(self):
        report = self.collect([user(), result(), call('Read'), result('missing')])
        self.assertEqual('unconfirmed', report['sessions'][0]['execution_events'][0]['status'])

    def test_result_text_not_considered_a_human_request(self):
        row = result()
        row['message']['content'].append({'type': 'text', 'text': '매출 CSV를 읽고 계산해줘'})
        report = self.collect([user(), call('Read'), row, *saved_skill()])
        self.assertEqual(1, len(report['sessions'][0]['work_requests']))
        self.assertEqual(['교육 신청'], [flow['title'] for flow in report['work_analysis']['workflows']])

    def test_image_only_human_turn_does_not_inherit_previous_work(self):
        image = user([{'type': 'image', 'source': {'data': 'PRIVATE'}}], 'u-image')
        report = self.collect([user(), call('Read'), result(), *saved_skill(), image,
                               call('Read', {'file_path': '조직도.png'}, 'c2', 'a2')])
        session = report['sessions'][0]
        self.assertEqual([], session['execution_events'][2]['request_ids'])
        self.assertEqual(2, report['work_analysis']['workflows'][0]['execution_count'])
        self.assertTrue(session['execution_partial'])

    def test_oversized_row_breaks_execution_attribution(self):
        report = self.collect([user(), call('Read'), user('PRIVATE' * 3000, 'u-large'),
                               call('Write', {'file_path': 'other.html'}, 'c2', 'a2')], {'line_bytes': 1024})
        session = report['sessions'][0]
        self.assertEqual([], session['execution_events'][1]['request_ids'])
        self.assertTrue(session['execution_partial'])

    def test_duplicate_source_calls_and_imports_not_inflated(self):
        report = self.collect([user(), call('Read'), result(), call('Read', uuid='a-duplicate'), result(),
                               *saved_skill(), *saved_skill()], duplicate=True)
        self.assertEqual(2, len(report['sessions'][0]['execution_events']))
        export = self.root / 'catalog.json'
        export.write_text(json.dumps(report), encoding='utf-8')
        collector = Collector()
        collector.add_catalog(export)
        collector.add_catalog(export)
        merged = collector.result()
        self.assertEqual(2, merged['summary']['execution_details'])
        self.assertEqual(2, merged['work_analysis']['workflows'][0]['execution_count'])

    def test_sensitive_metadata_is_redacted_and_shell_text_not_exported(self):
        report = self.collect([user(), call('Read', {'file_path': r'C:\secret\api_key_PRIVATE.txt'}),
                               call('Skill', {'skill': 'safe:csv-report'}, 'c2', 'a2'),
                               call('Bash', {'command': 'python -c "print(SECRET_CODE)"'}, 'c3', 'a3'),
                               call('mcp__oracle__query', {'sql': 'SELECT PRIVATE_SCHEMA', 'token': 'PRIVATE'}, 'c4', 'a4')])
        events = report['sessions'][0]['execution_events']
        self.assertEqual('[민감 대상 가림]', events[0]['target'])
        self.assertEqual('safe:csv-report', events[1]['target'])
        self.assertEqual('', events[2]['target'])
        self.assertEqual('연결 도구 호출', events[3]['operation'])
        serialized = json.dumps(report)
        for forbidden in ('PRIVATE', 'SECRET_CODE', 'SELECT', 'C:\\secret'):
            self.assertNotIn(forbidden, serialized)

    def test_unknown_and_sidechain_records_do_not_invent_results(self):
        sidechain = call('Write', {'file_path': 'not-exported.html'}, 'side', 'side')
        sidechain['isSidechain'] = True
        report = self.collect([user(), call('Read'), sidechain, {'type': 'strange-new-format', 'output': 'success'}])
        events = report['sessions'][0]['execution_events']
        self.assertEqual(1, len(events))
        self.assertEqual('unconfirmed', events[0]['status'])
        self.assertIn('하위 작업자 세션 이벤트 제외', report['coverage']['warnings'])

    def test_credential_like_tool_names_are_not_copied_into_execution(self):
        report = self.collect([user(), call('ghp_SECRET123456789')])
        self.assertEqual([], report['sessions'][0]['execution_events'])
        self.assertNotIn('ghp_SECRET', json.dumps(report))
        self.assertTrue(report['sessions'][0]['execution_partial'])

    def test_global_event_cap_limits_execution_details_but_observes_known_results(self):
        report = self.collect([user(), call('Read'), result(), call('Write', {}, 'c2', 'a2'), result('c2')], {'session_events': 2})
        session = report['sessions'][0]
        self.assertEqual(1, len(session['execution_events']))
        self.assertEqual('returned', session['execution_events'][0]['status'])
        self.assertTrue(session['execution_partial'])

    def test_execution_cap_is_marked_and_never_silently_claims_full_trace(self):
        trace = ExecutionTrace(clean, 2)
        for i in range(4):
            trace.observe(call('Read', call_id='c' + str(i)), 'row' + str(i))
        self.assertEqual(2, len(trace.events))
        self.assertTrue(trace.partial)

    def test_conflicting_call_id_keeps_original_but_marks_partial(self):
        report = self.collect([user(), call('Read'), call('Write', {}, 'c1', 'other')])
        self.assertEqual('Read', report['sessions'][0]['execution_events'][0]['tool'])
        self.assertTrue(report['sessions'][0]['execution_partial'])

    def test_legacy_catalog_without_execution_still_imports(self):
        report = self.collect([user(), call('Read')])
        for session in report['sessions']:
            session.pop('execution_events')
            session.pop('execution_partial')
        export = self.root / 'legacy.json'
        export.write_text(json.dumps(report), encoding='utf-8')
        collector = Collector()
        collector.add_catalog(export)
        self.assertEqual([], collector.result()['work_analysis']['workflows'])
        self.assertEqual(1, len(collector.result()['work_analysis']['deferred_work']))
        self.assertEqual([], collector.result()['sessions'][0]['execution_events'])

    def test_import_rejects_invalid_or_foreign_links_and_outcomes_atomically(self):
        report = self.collect([user(), call('Read'), result()])
        mutations = [
            {'request_ids': ['a' * 64]}, {'ordinal': True}, {'status': 'success'},
            {'result_observed': False}, {'evidence': 'assumed'}, {'operation': 'PRIVATE arbitrary text'},
            {'tool': 'C:/Users/secret'},
        ]
        for change in mutations:
            with self.subTest(change=change):
                corrupted = copy.deepcopy(report)
                corrupted['sessions'][0]['execution_events'][0].update(change)
                export = self.root / 'bad.json'
                export.write_text(json.dumps(corrupted), encoding='utf-8')
                collector = Collector()
                collector.add_catalog(export)
                self.assertEqual([], collector.result()['sessions'])
                self.assertIn('재집계 파일 형식·크기·접근 오류', collector.warnings)

    def test_import_disregards_injected_fields_and_redacts_targets(self):
        report = self.collect([user(), call('Read')])
        event = report['sessions'][0]['execution_events'][0]
        event.update(target='PRIVATE@example.com', arguments='PRIVATE ARGUMENT', content='PRIVATE RESULT',
                     request_group_ambiguous=True)
        export = self.root / 'safe.json'
        export.write_text(json.dumps(report), encoding='utf-8')
        collector = Collector()
        collector.add_catalog(export)
        imported = collector.result()['sessions'][0]['execution_events'][0]
        self.assertEqual('[민감 대상 가림]', imported['target'])
        self.assertFalse(imported['request_group_ambiguous'])
        self.assertNotIn('PRIVATE', json.dumps(collector.result()))

    def test_status_only_uses_explicit_result_metadata(self):
        self.assertEqual('returned', result_state({'output': 'error inside source text'}))
        self.assertEqual('returned', result_state({'output': {'exit_code': False}}))
        self.assertEqual('error', result_state({'output': {'metadata': {'exit_code': 2}}}))
        self.assertEqual('returned', result_state({'output': {'exit_code': 0}}))
        self.assertEqual('error', result_state({'isError': True}))

    def test_basic_operation_labels_have_no_command_or_selector_content(self):
        self.assertEqual(('검증 명령 실행', ''), describe('Bash', {'command': 'python -m unittest SECRET_TEST'}, clean))
        self.assertEqual(('브라우저 도구 호출', ''), describe('mcp__playwright__browser_click', {'selector': '#secret'}, clean))
        self.assertEqual(('하위 작업자 호출', 'vision-worker'), describe('Agent', {'subagent_type': 'vision-worker', 'prompt': 'PRIVATE'}, clean))
        self.assertEqual('[민감 대상 가림]', safe_target('.env', clean))

    def test_shell_labels_follow_executable_not_words_inside_arguments(self):
        for command in ('echo "python report.py"', 'git commit -m "fix pytest failures"',
                        'python report.py && rm output.txt', 'echo pytest'):
            self.assertEqual(('명령 실행', ''), describe('Bash', {'command': command}, clean), command)
        self.assertEqual(('Python 코드 실행', ''), describe('Bash', {'command': 'python -c "print(\'pytest\')"'}, clean))
        self.assertEqual(('검증 명령 실행', ''), describe('Bash', {'command': '"C:\\Program Files\\Python\\python.exe" -I -X utf8 -m unittest discover'}, clean))
        self.assertEqual(('Python 코드 실행', 'enrollment_summary.py'), describe('Bash', {'command': 'python -I -X utf8 "C:\\private\\enrollment_summary.py" --token PRIVATE'}, clean))
        self.assertEqual(('Python 코드 실행', ''), describe('Bash', {'command': 'python -m confidential.module'}, clean))


if __name__ == '__main__':
    unittest.main()
