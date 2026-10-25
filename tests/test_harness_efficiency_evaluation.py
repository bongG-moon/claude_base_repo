"""Developer evaluation cannot quietly turn missing usage into a saving."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('harness_efficiency_evaluation',
                                             ROOT / 'scripts/test-lab/evaluate-harness-efficiency.py')
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


class HarnessEfficiencyEvaluationTests(unittest.TestCase):
    def test_real_offline_scenarios_are_isolated_and_do_not_measure_tokens(self):
        report = evaluation.collect(samples=1)
        self.assertTrue(report['passed'], [row for row in report['scenarios'] if not row['qualityPassed']])
        self.assertEqual(8, len(report['scenarios']))
        self.assertEqual(0, report['isolation']['modelCalls'])
        self.assertFalse(report['isolation']['normalHookIntegration'])
        rows = {row['case']: row for row in report['scenarios']}
        self.assertTrue(rows['overlap']['choicePlanned'])
        self.assertFalse(rows['explicit_choice']['choicePlanned'])
        self.assertLess(rows['body_reuse']['instructionChars'], rows['html']['instructionChars'])
        self.assertNotIn('inputTokens', rows['html'])
        same = evaluation.compare(report, report)
        for row in same['scenarios']:
            self.assertEqual(0, row['normalizedContextCharsDelta'])
            self.assertEqual(0, row['choicePlansDelta'])

    def test_different_or_incomplete_corpus_cannot_claim_comparison(self):
        report = {'schemaVersion': 1, 'corpusId': 'same', 'scenarios': [{'case': 'one'}]}
        for baseline in ({**report, 'corpusId': 'other'}, {**report, 'schemaVersion': 2},
                         {**report, 'scenarios': []}, {**report, 'scenarios': [{'case': 'one'}] * 2}):
            with self.subTest(baseline=baseline), self.assertRaises(ValueError):
                evaluation.compare(baseline, report)

    def test_missing_usage_stays_unknown_including_partially_measured_runs(self):
        report = evaluation.summarize_runs([
            {'case': 'html', 'completed': True, 'elapsedMs': 100, 'inputTokens': 20},
            {'case': 'html', 'completed': True, 'elapsedMs': 200, 'inputTokens': None},
        ])['html']
        self.assertEqual(150, report['metrics']['elapsedMs']['median'])
        self.assertEqual(300, report['metrics']['elapsedMs']['total'])
        self.assertIsNone(report['metrics']['inputTokens']['median'])
        self.assertIsNone(report['metrics']['inputTokens']['total'])
        self.assertEqual(1, report['metrics']['inputTokens']['observedRuns'])
        self.assertIsNone(report['metrics']['outputTokens']['total'])

    def test_failed_or_different_count_runs_do_not_claim_speedup(self):
        old = evaluation.summarize_runs([{'case': 'html', 'completed': True, 'elapsedMs': 100}])
        for rows in ([{'case': 'html', 'completed': False, 'elapsedMs': 1}],
                     [{'case': 'html', 'completed': True, 'elapsedMs': 1}] * 2):
            result = evaluation.compare_runs(old, evaluation.summarize_runs(rows))['html']
            self.assertFalse(result['comparable'])
            self.assertEqual({}, result['medianDeltas'])

    def test_complete_equal_workloads_report_exact_measured_deltas(self):
        old = evaluation.summarize_runs([{'case': 'html', 'completed': True, 'elapsedMs': 100,
                                         'inputTokens': 30, 'retries': 2}])
        new = evaluation.summarize_runs([{'case': 'html', 'completed': True, 'elapsedMs': 80,
                                         'inputTokens': 25, 'retries': 0}])
        result = evaluation.compare_runs(old, new)['html']
        self.assertTrue(result['comparable'])
        self.assertEqual(-20, result['medianDeltas']['elapsedMs'])
        self.assertEqual(-5, result['medianDeltas']['inputTokens'])
        self.assertEqual(-2, result['medianDeltas']['retries'])
        self.assertIsNone(result['medianDeltas']['cacheReadTokens'])
        with self.assertRaises(ValueError):
            evaluation.compare_runs(old, {})

    def test_only_bounded_sanitized_measurements_are_accepted(self):
        invalid = [[], {}, [{'case': 'one', 'completed': True, 'prompt': 'private'}],
                   [{'case': 'C:/private/file', 'completed': True}],
                   [{'case': 'one', 'completed': 'true'}],
                   [{'case': 'one', 'completed': True, 'inputTokens': -1}],
                   [{'case': 'one', 'completed': True, 'inputTokens': True}],
                   [{'case': 'one', 'completed': True, 'elapsedMs': float('nan')}]]
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                evaluation.summarize_runs(rows)

    def test_output_cannot_overwrite_baseline_and_invalid_arguments_do_not_run_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'baseline.json'
            path.write_text('{"keep":true}', encoding='utf-8')
            with patch.object(evaluation, 'collect') as collect, patch('sys.stderr'):
                for args in (['--baseline', str(path), '--output', str(path)], ['--baseline-runs', str(path)], ['--strict']):
                    with self.assertRaises(SystemExit) as raised:
                        evaluation.main(args)
                    self.assertEqual(2, raised.exception.code)
                collect.assert_not_called()
            self.assertEqual('{"keep":true}', path.read_text(encoding='utf-8'))

    def test_strict_comparison_blocks_growth_but_not_timing_noise_or_repaired_misrouting(self):
        base_row = {'case': 'html', 'qualityPassed': True, 'normalizedContextChars': 100,
                    'normalizedContextUtf8Bytes': 200, 'instructionChars': 20,
                    'choicePlanned': False, 'localContextMs': 10}
        baseline = {'schemaVersion': 1, 'corpusId': 'one', 'passed': True, 'scenarios': [base_row]}
        current = {**baseline, 'scenarios': [{**base_row, 'localContextMs': 1000}]}
        self.assertEqual([], evaluation.compare(baseline, current)['deterministicRegressions'])
        grown = {**baseline, 'scenarios': [{**base_row, 'normalizedContextChars': 101,
                                          'normalizedContextUtf8Bytes': 203, 'instructionChars': 21,
                                          'choicePlanned': True}]}
        self.assertEqual(4, len(evaluation.compare(baseline, grown)['deterministicRegressions']))
        invalid_baseline = {**baseline, 'passed': False, 'scenarios': [{**base_row, 'qualityPassed': False}]}
        repaired = evaluation.compare(invalid_baseline, grown)
        self.assertEqual(['html'], repaired['qualityFixedCases'])
        self.assertEqual([], repaired['deterministicRegressions'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'baseline.json'
            path.write_text(json.dumps(baseline), encoding='utf-8')
            with patch('sys.stdout'), patch.object(evaluation, 'collect', return_value=grown):
                self.assertEqual(1, evaluation.main(['--baseline', str(path), '--strict']))
                self.assertEqual(0, evaluation.main(['--baseline', str(path)]))

    def test_sampling_is_bounded(self):
        for count in (0, -1, 21):
            with self.assertRaises(ValueError):
                evaluation.collect(count)

    def test_external_execution_is_blocked_if_a_fixture_accidentally_starts_it(self):
        for call in (lambda _: subprocess.run(['unexpected-program'], check=True),
                     lambda _: socket.create_connection(('127.0.0.1', 1))):
            with patch.object(evaluation, 'measure_case', side_effect=call):
                with self.assertRaisesRegex(AssertionError, 'Offline evaluation'):
                    evaluation.collect(1)


if __name__ == '__main__':
    unittest.main()
