from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent import usability_sources as sources


class UsabilitySourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / 'PRIVATE 한글 project'
        self.project.mkdir()
        self.claude = self.base / 'claude'
        self.state = self.base / 'state'
        self.now = datetime(2026, 10, 29, 9, tzinfo=timezone.utc)
        self.start = self.now - timedelta(hours=1)

    def record(self, kind='assistant', second=1, **message):
        return {'type': kind, 'cwd': str(self.project),
                'timestamp': (self.start + timedelta(seconds=second)).isoformat(),
                'message': message}

    def user(self, second=0, identifier='PRIVATE-REQUEST'):
        row = self.record('user', second, content='PRIVATE PROMPT QUESTION')
        row['uuid'] = identifier
        return row

    def assistant(self, identifier='PRIVATE-MESSAGE', second=1, *, name=None, call=None, inp=None, usage=None):
        content = [{'type': 'text', 'text': 'PRIVATE BODY'}]
        if name:
            content.append({'type': 'tool_use', 'id': call or identifier + '-call', 'name': name,
                            'input': inp or {'command': 'PRIVATE COMMAND'}})
        return self.record('assistant', second, id=identifier, content=content,
                           usage=usage if usage is not None else {key: 10 for key in sources.METRICS})

    def result(self, call, second=2, error=False):
        return self.record('user', second, content=[{'type': 'tool_result', 'tool_use_id': call,
                                                   'is_error': error, 'content': 'PRIVATE ERROR RESULT'}])

    def log(self, rows, name='PRIVATE-SESSION.jsonl', *, native=False):
        parent = self.claude / 'projects' / re.sub(r'[^A-Za-z0-9]', '-', str(self.project)) if native else self.base / 'selected'
        parent.mkdir(parents=True, exist_ok=True)
        path = parent / name
        path.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n', encoding='utf-8')
        return path

    def state_file(self, data=None, name='PRIVATE-STATE.json', *, age=0):
        folder = self.state / 'sessions'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_text(json.dumps(data if data is not None else {
            'skillWorkflow': {'project': os.path.normcase(str(self.project))},
            'taskToolCount': 4, 'taskFailureCount': 1,
        }), encoding='utf-8')
        timestamp = (self.now - timedelta(seconds=1, days=age)).timestamp()
        os.utime(path, (timestamp, timestamp))
        return path

    def collect(self, *logs, state=None, **kwargs):
        return sources.collect(self.project, state, self.claude, logs=logs, now=self.now, **kwargs)

    def test_streaming_usage_uses_maximum_per_message_and_fixed_export_fields(self):
        first = self.assistant(name='Read', inp={'file_path': 'PRIVATE/path', 'offset': 1, 'limit': 5})
        second = json.loads(json.dumps(first))
        second['message']['usage']['output_tokens'] = 17
        other = self.assistant('PRIVATE-MESSAGE2', 3, name='PRIVATE-MCP-NAME')
        log = self.log([self.user(), first, second, other])
        before = (log.read_bytes(), log.stat().st_mtime_ns)
        output = io.StringIO()
        with redirect_stdout(output):
            report = self.collect(log, log)
        row = report['transcripts'][0]
        self.assertEqual({'Other': 1, 'Read': 1}, row['toolCounts'])
        self.assertEqual(20, row['tokens']['input_tokens'])
        self.assertEqual(27, row['tokens']['output_tokens'])
        self.assertEqual(2, row['usageMessages'])
        self.assertFalse(row['usageMissing'])
        self.assertEqual(1, row['requests'])
        self.assertEqual(3000, row['observedSpanMs'])
        self.assertRegex(row['key'], r'^[a-f0-9]{12}$')
        self.assertEqual('observed', report['coverage']['status'])
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertEqual('', output.getvalue())
        self.assertEqual(before, (log.read_bytes(), log.stat().st_mtime_ns))

    def test_missing_usage_and_ids_remain_unknown(self):
        missing = self.assistant(usage={'input_tokens': 5})
        noid = self.assistant('ignored')
        del noid['message']['id']
        log = self.log([self.user(), missing, noid])
        report = self.collect(log)
        row = report['transcripts'][0]
        self.assertIsNone(row['tokens']['input_tokens'])
        self.assertIsNone(row['tokens']['output_tokens'])
        self.assertTrue(row['usageMissing'])
        self.assertEqual('partial', report['coverage']['status'])

    def test_streaming_missing_usage_is_filled_by_later_chunk(self):
        missing = self.assistant()
        del missing['message']['usage']
        log = self.log([self.user(), missing, self.assistant()])
        row = self.collect(log)['transcripts'][0]
        self.assertEqual(10, row['tokens']['input_tokens'])
        self.assertFalse(row['usageMissing'])

    def test_missing_field_in_one_message_never_exports_a_partial_sum_as_total(self):
        log = self.log([self.user(), self.assistant('one'), self.assistant('two', usage={'input_tokens': 5})])
        row = self.collect(log)['transcripts'][0]
        self.assertEqual(15, row['tokens']['input_tokens'])
        self.assertIsNone(row['tokens']['output_tokens'])
        self.assertTrue(row['usageMissing'])

    def test_copied_logs_are_deduplicated_across_messages_requests_calls_and_errors(self):
        rows = [self.user(), self.assistant('one', 1, name='Read', call='one'),
                self.result('one', 2, True), self.assistant('two', 3, name='Read', call='two'),
                self.result('two', 4)]
        report = self.collect(self.log(rows, 'first.jsonl'), self.log(rows, 'copy.jsonl'))
        self.assertEqual(1, len(report['transcripts']))
        row = report['transcripts'][0]
        self.assertEqual(1, row['requests'])
        self.assertEqual(2, row['toolCalls'])
        self.assertEqual(1, row['toolErrors'])
        self.assertEqual(20, row['tokens']['input_tokens'])
        self.assertEqual(4000, row['observedSpanMs'])
        self.assertEqual('observed', report['coverage']['status'])
        self.assertEqual(1, report['coverage']['duplicateTranscriptFiles'])

    def test_fork_keeps_new_calls_and_cumulative_usage_max_without_shared_prefix(self):
        initial = [self.user(), self.assistant('one', 1, name='Bash', call='one'), self.result('one', 2, True)]
        forked = json.loads(json.dumps(initial))
        forked[1]['message']['usage']['output_tokens'] = 17
        forked.extend([self.assistant('two', 3, name='Bash', call='two'), self.result('two', 4),
                       self.assistant('three', 5, name='Bash', call='three')])
        report = self.collect(self.log(initial, 'first.jsonl'), self.log(forked, 'fork.jsonl'))
        self.assertEqual(2, len(report['transcripts']))
        rows = report['transcripts']
        self.assertEqual(1, sum(row['requests'] for row in rows))
        self.assertEqual(3, sum(row['toolCalls'] for row in rows))
        self.assertEqual(1, sum(row['toolErrors'] for row in rows))
        self.assertEqual(1, sum(row['repeatedFailedCalls'] for row in rows))
        self.assertEqual(30, sum(row['tokens']['input_tokens'] for row in rows))
        self.assertEqual(37, sum(row['tokens']['output_tokens'] for row in rows))
        self.assertEqual(2000, rows[0]['observedSpanMs'])
        self.assertEqual(2000, rows[1]['observedSpanMs'])

    def test_cross_file_streamed_message_updates_owner_and_new_tool_without_missing_usage(self):
        initial = [self.user(), self.assistant('one', 1)]
        del initial[1]['message']['usage']
        continuation = [self.user(), self.assistant('one', 2, name='Read', call='new-call')]
        report = self.collect(self.log(initial, 'first.jsonl'), self.log(continuation, 'stream.jsonl'))
        self.assertEqual(1, len(report['transcripts']))
        row = report['transcripts'][0]
        self.assertEqual(1, row['toolCalls'])
        self.assertFalse(row['usageMissing'])
        self.assertEqual(10, row['tokens']['input_tokens'])
        self.assertEqual('observed', report['coverage']['status'])

    def test_invalid_file_does_not_poison_global_seen_ids(self):
        invalid = [self.user(), self.assistant()]
        invalid[0]['cwd'] = str(self.base / 'other')
        report = self.collect(self.log(invalid, 'wrong.jsonl'), self.log([self.user(), self.assistant()], 'valid.jsonl'))
        self.assertEqual(1, report['transcripts'][0]['requests'])
        self.assertEqual(10, report['transcripts'][0]['tokens']['input_tokens'])

    def test_failures_questions_and_reads_are_request_bound_candidates(self):
        read = {'file_path': 'PRIVATE/path', 'offset': 0, 'limit': 5}
        rows = [self.user(),
                self.assistant('a', 1, name='Bash', call='a'),
                self.assistant('b', 2, name='Bash', call='b'),
                self.result('a', 3, True), self.result('a', 3, True),
                self.assistant('c', 4, name='Bash', call='c'),
                self.assistant('q1', 5, name='AskUserQuestion', call='q1', inp={'questions': ['PRIVATE QUESTION']}),
                self.assistant('q2', 6, name='AskUserQuestion', call='q2', inp={'questions': ['PRIVATE QUESTION']}),
                self.result('q1', 7), self.result('q1', 7),
                self.assistant('r1', 8, name='Read', inp=read),
                self.assistant('r2', 9, name='Read', inp=read),
                self.user(10, 'second'),
                self.assistant('d', 11, name='Bash', call='d'),
                self.assistant('q3', 12, name='AskUserQuestion', inp={'questions': ['PRIVATE QUESTION']}),
                self.assistant('r3', 13, name='Read', inp=read)]
        row = self.collect(self.log(rows))['transcripts'][0]
        self.assertEqual(2, row['requests'])
        self.assertEqual(1, row['toolErrors'])
        self.assertEqual(1, row['repeatedFailedCalls'])
        self.assertEqual(3, row['questionCalls'])
        self.assertEqual(1, row['repeatedQuestions'])
        self.assertEqual(1, row['sameRangeReads'])
        self.assertEqual(1, row['questionPairs'])
        self.assertEqual(2000, row['questionWaitMs'])

    def test_unpaired_old_cross_request_and_failed_questions_do_not_claim_wait(self):
        old = self.assistant('old', -8 * 86400, name='AskUserQuestion', call='old')
        rows = [old, self.user(), self.result('old', 1),
                self.assistant('q', 2, name='AskUserQuestion', call='q'), self.result('q', 3, True),
                self.assistant('next', 4, name='AskUserQuestion', call='next'),
                self.user(5, 'next request'), self.result('next', 6)]
        row = self.collect(self.log(rows))['transcripts'][0]
        self.assertEqual(0, row['questionPairs'])
        self.assertIsNone(row['questionWaitMs'])

    def test_unknown_timestamp_request_and_malformed_records_break_repeat_candidates(self):
        unknown = self.user(5, 'unknown-time-request')
        del unknown['timestamp']
        rows = [self.user(), self.assistant('a', 1, name='Bash', call='a'), self.result('a', 2, True),
                self.assistant('q', 3, name='AskUserQuestion', call='q'), unknown,
                self.assistant('b', 6, name='Bash', call='b'), self.result('q', 7),
                self.result('b', 8, True)]
        log = self.log(rows)
        with log.open('a', encoding='utf-8') as stream:
            stream.write('PRIVATE malformed\n' + json.dumps(self.assistant('c', 9, name='Bash', call='c')) + '\n')
        row = self.collect(log)['transcripts'][0]
        self.assertEqual(1, row['requests'])
        self.assertEqual(0, row['repeatedFailedCalls'])
        self.assertEqual(0, row['questionPairs'])

    def test_actual_timestamps_filter_recent_mtime_and_unknown_times(self):
        old = self.assistant('old', -8 * 86400)
        future = self.assistant('future', 7200)
        missing = self.assistant('missing')
        del missing['timestamp']
        naive = self.assistant('naive')
        naive['timestamp'] = '2026-10-29T08:00:00'
        log = self.log([old, missing, naive, future, self.user(), self.assistant()])
        os.utime(log, (1, 1))
        report = self.collect(log)
        self.assertEqual(10, report['transcripts'][0]['tokens']['input_tokens'])
        self.assertEqual(2, report['coverage']['outsideWindowRecords'])
        self.assertEqual(2, report['coverage']['unknownTimeRecords'])
        self.assertEqual(4, report['coverage']['skippedRecords'])

    def test_unknown_or_wrong_project_and_mixed_cwd_are_excluded(self):
        missing = self.assistant()
        del missing['cwd']
        wrong = self.assistant('wrong')
        wrong['cwd'] = str(self.base / 'other')
        logs = [self.log([missing], 'missing.jsonl'), self.log([wrong], 'wrong.jsonl'),
                self.log([self.user(), self.assistant(), wrong], 'mixed.jsonl')]
        report = self.collect(*logs)
        self.assertEqual([], report['transcripts'])
        self.assertEqual(3, report['coverage']['projectExcludedFiles'])
        self.assertEqual('no-data', report['coverage']['status'])

    def test_old_wrong_cwd_still_invalidates_mixed_project_log(self):
        wrong = self.assistant('wrong', -8 * 86400)
        wrong['cwd'] = str(self.base / 'other')
        self.assertEqual([], self.collect(self.log([wrong, self.user(), self.assistant()]))['transcripts'])

    def test_native_discovery_is_exact_and_never_descends_into_subagents(self):
        expected = self.log([self.user(), self.assistant()], native=True)
        nested = expected.parent / 'subagents'
        nested.mkdir()
        (nested / 'secret.jsonl').write_bytes(expected.read_bytes())
        sibling = expected.parent.with_name(expected.parent.name + '-other')
        sibling.mkdir()
        (sibling / 'secret.jsonl').write_bytes(expected.read_bytes())
        report = self.collect()
        self.assertEqual(1, len(report['transcripts']))
        self.assertEqual(1, report['coverage']['filesRead'])
        self.assertEqual(2, report['coverage']['candidateEntries'])

    def test_explicit_log_works_outside_native_directory_but_sidechains_do_not(self):
        row = self.assistant()
        row['isSidechain'] = True
        log = self.log([row])
        self.assertEqual([], self.collect(log)['transcripts'])

    def test_state_snapshot_uses_real_schema_and_fixed_enums_only(self):
        state = {'sessionId': 'PRIVATE SESSION', 'turnId': 'PRIVATE TURN',
                 'skillWorkflow': {'project': str(self.project), 'loadObservation': {'turn': 'PRIVATE TURN', 'status': 'loaded'}},
                 'taskToolCount': 9, 'taskFailureCount': 2,
                 'verification': {'status': 'pass', 'summary': 'PRIVATE SUMMARY'},
                 'hookDiagnostics': {'UserPromptSubmit': {'status': 'output-produced', 'elapsedMs': 7, 'contextChars': 100,
                                                         'errorType': 'PRIVATE ERROR', 'candidateNames': ['PRIVATE SKILL']},
                                     'PRIVATE EVENT': {'status': 'failed'}}}
        path = self.state_file(state)
        before = path.read_bytes(), path.stat().st_mtime_ns
        report = self.collect(state=self.state)
        row = report['states'][0]
        self.assertEqual(9, row['taskToolCount'])
        self.assertEqual('pass', row['verification'])
        self.assertEqual('loaded', row['loadStatus'])
        self.assertEqual([{'event': 'UserPromptSubmit', 'status': 'output-produced', 'elapsedMs': 7, 'contextChars': 100}], row['hooks'])
        self.assertEqual('file-mtime-latest-state', report['coverage']['stateSnapshotBasis'])
        self.assertEqual('partial', report['coverage']['status'])
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))

    def test_states_reject_wrong_missing_or_conflicting_bindings_and_old_snapshots(self):
        self.state_file({'taskToolCount': 10}, 'missing.json')
        self.state_file({'cwd': str(self.base)}, 'wrong.json')
        self.state_file({'cwd': str(self.base), 'skillWorkflow': {'project': str(self.project)}}, 'mixed.json')
        self.state_file(name='old.json', age=8)
        report = self.collect(state=self.state)
        self.assertEqual([], report['states'])
        self.assertEqual(3, report['coverage']['projectExcludedFiles'])
        self.assertEqual(1, report['coverage']['outsideWindowStates'])

    def test_malformed_state_fields_are_safe_unknown_enums(self):
        self.state_file({'cwd': str(self.project), 'turnId': 'x', 'taskToolCount': True,
                         'taskFailureCount': -1, 'verification': {'status': ['PRIVATE']},
                         'skillWorkflow': {'loadObservation': {'turn': 'x', 'status': ['PRIVATE']}},
                         'hookDiagnostics': {'SessionStart': {'status': {}, 'elapsedMs': 'PRIVATE', 'contextChars': -1}}})
        row = self.collect(state=self.state)['states'][0]
        self.assertEqual('unknown', row['verification'])
        self.assertEqual('unknown', row['loadStatus'])
        self.assertIsNone(row['taskToolCount'])
        self.assertIsNone(row['taskFailureCount'])
        self.assertEqual('not-observed', row['hooks'][0]['status'])

    def test_no_data_creates_no_state_layout_and_does_not_report_zero_success(self):
        report = self.collect(state=self.state)
        self.assertEqual('no-data', report['coverage']['status'])
        self.assertEqual([], report['transcripts'])
        self.assertEqual([], report['states'])
        self.assertFalse(self.state.exists())
        self.assertFalse(self.claude.exists())
        self.assertIn(sources.WARNINGS['no-data'], report['coverage']['warnings'])

    def test_malformed_json_and_nonobjects_are_visible(self):
        log = self.log([self.user(), self.assistant()])
        with log.open('ab') as stream:
            stream.write(b'[]\nPRIVATE malformed\n{"type":[],"timestamp":"2026-10-29T08:00:00Z"}\n')
        report = self.collect(log)
        self.assertEqual(2, report['coverage']['skippedRecords'])
        self.assertEqual('partial', report['coverage']['status'])
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_byte_line_record_and_file_limits_are_finite_and_visible(self):
        log = self.log([self.user(), self.assistant()])
        for limit, value in [('MAX_BYTES', 10), ('MAX_LINE', 30), ('MAX_RECORDS', 1)]:
            with self.subTest(limit=limit), patch.object(sources, limit, value):
                report = self.collect(log)
                self.assertTrue(report['coverage']['truncated'])
                self.assertEqual([], report['transcripts'])
                self.assertLessEqual(report['coverage']['bytesRead'], sources.MAX_BYTES)
                self.assertLessEqual(report['coverage']['recordsRead'], sources.MAX_RECORDS)
        with patch.object(sources, 'MAX_LOGS', 1):
            report = self.collect(log, self.log([self.assistant()], 'two.jsonl'))
        self.assertTrue(report['coverage']['truncated'])
        self.assertEqual(1, len(report['transcripts']))

    def test_total_byte_budget_spans_sources_and_state_sizes_are_bounded(self):
        log = self.log([self.user(), self.assistant()])
        self.state_file()
        with patch.object(sources, 'MAX_BYTES', log.stat().st_size + 1):
            report = self.collect(log, state=self.state)
            self.assertTrue(report['coverage']['truncated'])
            self.assertEqual(1, len(report['transcripts']))
            self.assertEqual([], report['states'])
            self.assertLessEqual(report['coverage']['bytesRead'], sources.MAX_BYTES)
        with patch.object(sources, 'MAX_STATE_BYTES', 10):
            self.assertTrue(self.collect(log, state=self.state)['coverage']['truncated'])

    def test_directory_enumeration_and_state_count_limits(self):
        self.log([self.user(), self.assistant()], native=True)
        self.log([self.user(), self.assistant()], 'two.jsonl', native=True)
        with patch.object(sources, 'MAX_CANDIDATES', 1):
            report = self.collect()
        self.assertEqual(1, report['coverage']['candidateEntries'])
        self.assertTrue(report['coverage']['truncated'])
        self.state_file(name='one.json')
        self.state_file(name='two.json')
        with patch.object(sources, 'MAX_STATES', 1):
            report = self.collect(state=self.state)
        self.assertEqual(1, len(report['states']))
        self.assertTrue(report['coverage']['truncated'])

    def test_explicit_candidates_and_state_scan_share_one_candidate_budget(self):
        log = self.log([self.user(), self.assistant()])
        self.state_file()
        with patch.object(sources, 'MAX_CANDIDATES', 1):
            report = self.collect(log, state=self.state)
        self.assertEqual(1, report['coverage']['candidateEntries'])
        self.assertTrue(report['coverage']['truncated'])
        self.assertEqual([], report['states'])

    def test_changed_files_are_discarded_without_leaking_errors(self):
        log = self.log([self.user(), self.assistant()])
        with patch.object(sources, '_unchanged', return_value=False):
            report = self.collect(log)
        self.assertEqual([], report['transcripts'])
        self.assertIn(sources.WARNINGS['changed'], report['coverage']['warnings'])
        with patch.object(sources, '_open_checked', side_effect=OSError('PRIVATE ERROR PATH')):
            report = self.collect(log)
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_symlinks_are_never_followed_when_platform_allows_creation(self):
        log = self.log([self.user(), self.assistant()])
        link = self.base / 'link.jsonl'
        try:
            link.symlink_to(log)
        except OSError:
            self.skipTest('Symlink creation is unavailable on this host')
        report = self.collect(link)
        self.assertEqual([], report['transcripts'])
        self.assertEqual(0, report['coverage']['filesRead'])

    def test_reparse_guard_rejects_ancestor_and_exports_only_fixed_warning(self):
        log = self.log([self.user(), self.assistant()])
        from company_agent import skill_registry
        original = skill_registry._no_reparse
        def reject(path):
            if Path(path) != self.project:
                raise ValueError('PRIVATE junction path')
            original(path)
        with patch.object(skill_registry, '_no_reparse', side_effect=reject):
            report = self.collect(log)
        self.assertEqual([], report['transcripts'])
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_invalid_days_or_naive_now_fail_with_fixed_messages(self):
        for days in (0, 31, True, '7'):
            with self.subTest(days=days), self.assertRaises(ValueError):
                self.collect(days=days)
        with self.assertRaises(ValueError):
            sources.collect(self.project, None, None, now=datetime(2026, 10, 29))


if __name__ == '__main__':
    unittest.main()
