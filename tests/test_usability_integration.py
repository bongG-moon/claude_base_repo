"""Requested-only reporting contracts, isolated from live profiles and models."""
import contextlib
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent import usability
from company_agent.cli import main
from company_agent.execution_contract import usability_report_command, safe_permission
from company_agent.skill_workflow import internal_command


def collected(**changes):
    result = {'window': {'since': '2026-10-22T00:00:00+00:00', 'until': '2026-10-29T00:00:00+00:00', 'days': 7},
              'coverage': {'filesRead': 0, 'recordsRead': 0, 'skippedRecords': 0, 'truncated': False, 'warnings': []},
              'transcripts': [], 'states': [], 'constraints': []}
    result.update(changes)
    return result


def transcript(**changes):
    row = {key: 0 for key in ('requests', 'toolCalls', 'toolErrors', 'repeatedFailedCalls', 'questionCalls',
                              'repeatedQuestions', 'sameRangeReads', 'questionPairs')}
    row.update(key='abcdef123456', requests=1, toolCalls=1, questionWaitMs=None,
               observedSpanMs=1000, tokens={k: None for k in usability.TOKEN_FIELDS}, usageMissing=True)
    row.update(changes)
    return row


class UsabilityIntegrationTests(unittest.TestCase):
    def test_empty_is_unknown_not_healthy_or_zero_tokens(self):
        result = usability.summarize(collected(), Path.cwd())
        self.assertEqual('no-data', result['summary']['status'])
        self.assertIsNone(result['metrics']['toolErrors'])
        self.assertIsNone(result['metrics']['tokens']['input_tokens'])
        self.assertEqual([], result['findings'])
        self.assertIn('부족', result['summary']['title'])
        for key in ('slowPreparation', 'failedPreparation', 'loadFailures'):
            self.assertIsNone(result['snapshots'][key])

    def test_missing_diagnostic_fields_and_requested_date_filter_are_not_failures(self):
        row = {'hooks': [], 'loadStatus': 'unknown', 'taskFailureCount': None}
        result = usability.summarize(collected(states=[row]), Path.cwd())
        for key in ('slowPreparation', 'failedPreparation', 'loadFailures'):
            self.assertIsNone(result['snapshots'][key])
        data = collected(transcripts=[transcript(tokens={k: 0 for k in usability.TOKEN_FIELDS}, usageMissing=False)])
        data['coverage'].update(status='observed', skippedRecords=10, outsideWindowRecords=10)
        self.assertEqual('observed', usability.summarize(data, Path.cwd())['summary']['status'])

    def test_top_three_order_and_candidate_not_causal(self):
        row = transcript(repeatedFailedCalls=4, repeatedQuestions=2, toolErrors=5, sameRangeReads=10)
        result = usability.summarize(collected(transcripts=[row]), Path.cwd())
        self.assertEqual(['repeat-failure', 'repeat-question', 'tool-error'], [x['code'] for x in result['findings']])
        self.assertEqual(0, result['modelCalls'])
        self.assertIn('확정', result['summary']['message'])
        self.assertEqual('partial', result['summary']['status'])

    def test_overlapping_session_spans_not_summed_and_partial_usage_unknown(self):
        a = transcript(tokens={k: 1 for k in usability.TOKEN_FIELDS}, usageMissing=False)
        b = transcript()
        result = usability.summarize(collected(transcripts=[a, b]), Path.cwd())
        self.assertIsNone(result['metrics']['observedSpanMs'])
        self.assertIsNone(result['metrics']['tokens']['input_tokens'])
        self.assertEqual(2, result['metrics']['toolCalls'])

    def test_latest_snapshots_are_not_window_totals(self):
        snapshots = [{'taskFailureCount': 2, 'loadStatus': 'tool-failed', 'hooks': [
            {'status': 'output-produced', 'elapsedMs': 1234, 'contextChars': 4500}]}]
        result = usability.summarize(collected(states=snapshots), Path.cwd())
        self.assertEqual('partial', result['summary']['status'])
        self.assertIsNone(result['metrics']['toolErrors'])
        self.assertEqual(2, result['snapshots']['toolFailures'])
        self.assertEqual(1, result['snapshots']['slowPreparation'])
        self.assertEqual('최근 상태', result['findings'][0]['confidence'])

    def test_cli_creates_one_html_small_receipt_and_does_not_mutate_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            state, config = folder / 'state', folder / 'config'
            state.mkdir(); config.mkdir()
            marker = state / 'keep.txt'
            marker.write_text('private original', encoding='utf-8')
            output = folder / '보고서.html'
            stdout = io.StringIO()
            with patch('company_agent.usability_sources.collect', return_value=collected()) as collect, \
                 patch('socket.create_connection', side_effect=AssertionError('network forbidden')), \
                 patch('subprocess.Popen', side_effect=AssertionError('subprocess forbidden')), contextlib.redirect_stdout(stdout):
                self.assertEqual(0, main(['usability-report', '--project-root', str(folder), '--state-root', str(state),
                    '--claude-root', str(config), '--output', str(output)]))
            receipt = json.loads(stdout.getvalue())
            self.assertLessEqual(len(stdout.getvalue().strip()), usability.MAX_CONSOLE_CHARS)
            self.assertTrue(output.exists())
            self.assertEqual('no-data', receipt['status'])
            self.assertEqual(7, collect.call_args.kwargs['days'])
            self.assertEqual('private original', marker.read_text(encoding='utf-8'))
            self.assertEqual([marker], list(state.iterdir()))
            self.assertNotIn('private original', output.read_text(encoding='utf-8'))

    def test_command_exemption_is_scoped_and_not_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory).absolute()
            args = ['usability-report', '--state-root', str(folder), '--project-root', str(folder), '--days', '7']
            state = {'skillWorkflow': {'project': str(folder)}}
            with patch('company_agent.execution_contract._trusted_arguments', return_value=args):
                self.assertTrue(usability_report_command('trusted usability-report', folder, str(folder)))
                self.assertTrue(internal_command('trusted usability-report', 'session', state, folder))
                self.assertFalse(usability_report_command('trusted usability-report', folder / 'other', str(folder)))
                self.assertFalse(usability_report_command('trusted usability-report', folder, str(folder / 'other')))
                self.assertIsNone(safe_permission({'tool_name': 'Bash', 'tool_input': {'command': 'trusted usability-report'}}, folder))
            for rest in (['--days', '31'], ['--output', str(folder / 'secret.json')], ['--unknown', 'x'], ['--days', '1', '--days', '2']):
                with patch('company_agent.execution_contract._trusted_arguments', return_value=args[:5] + rest):
                    self.assertFalse(usability_report_command('trusted usability-report', folder, str(folder)))
            with patch('company_agent.execution_contract._trusted_arguments', side_effect=AssertionError('unrelated command must not parse')):
                self.assertFalse(usability_report_command('python main.py', folder))

    def test_previous_report_comparison_requires_same_scope_and_nonoverlap(self):
        from company_agent.usability_report import write_report
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            before = usability.summarize(collected(transcripts=[transcript(toolErrors=3)]), folder)
            output = folder / 'previous.html'
            write_report(output, before)
            after = copy.deepcopy(before)
            self.assertEqual('not-comparable', usability.compare(after, output)['status'])
            after['window'] = {'since': '2026-10-29T00:00:00+00:00', 'until': '2026-11-05T00:00:00+00:00', 'days': 7}
            after['metrics']['toolErrors'] = 1
            comparison = usability.compare(after, output)
            self.assertEqual('observational', comparison['status'])
            errors = next(row for row in comparison['rows'] if row['label'] == '오류 응답')
            self.assertEqual((3, 1), (errors['before'], errors['after']))
            after['scopeKey'] = '0' * 64
            self.assertEqual('not-comparable', usability.compare(after, output)['status'])

    def test_old_report_data_is_not_executed_and_invalid_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.html'
            path.write_text('<script>doBadThing()</script>', encoding='utf-8')
            with self.assertRaises(ValueError):
                usability.compare(usability.summarize(collected(), path.parent), path)

    def test_report_is_not_in_normal_hooks_or_context(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('company-agent-plugin/hooks/hooks.json', 'company-agent-plugin/scripts/company_agent/native_runtime.py',
                     'company-agent-plugin/scripts/company_agent/hook_diagnostics.py'):
            text = (root / name).read_text(encoding='utf-8')
            self.assertNotIn('usability-report', text)
            self.assertNotIn('usability_sources', text)

    def test_actual_runtime_command_does_not_force_skill_or_completion_loop(self):
        from test_skill_list_review import ListReviewTests
        from company_agent.state import record_activity, stop_decision
        fixture = ListReviewTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        context, _ = fixture.output('최근 일주일 사용성 개선 보고서를 만들어줘')
        command = (context['cliCommand'] + ' usability-report --state-root "' + str(fixture.f.state) +
                   '" --project-root "' + str(fixture.f.project) + '" --days 7')
        self.assertEqual({}, fixture.pre('Bash', command=command))
        before = fixture.state()
        payload = {'session_id': fixture.f.sid, 'tool_name': 'Bash', 'tool_input': {'command': command},
                   'tool_response': {'stdout': '{"ok":true,"status":"no-data"}', 'exitCode': 0}}
        record_activity(payload, fixture.f.state)
        after = fixture.state()
        self.assertEqual(before.get('taskToolCount'), after.get('taskToolCount'))
        self.assertEqual({}, stop_decision({'session_id': fixture.f.sid}, fixture.f.state))


if __name__ == '__main__':
    unittest.main()
