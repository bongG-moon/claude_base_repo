"""실제 회사 DB 없이 한 번의 조회 요청과 로컬 화면 진입을 검증합니다."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
from query_core import cli, core
from query_core.store import Store


class QueryCliWorkflowTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/query-cli-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'state', demo=True)
        core.demo_init(self.store)
        self.params = self.root / 'params.json'
        self.params.write_text(json.dumps({'start_date': '2026-10-01', 'end_date': '2026-11-01',
                                           'process': 'WB'}), encoding='utf-8')

    def call(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli.main('demo', ['--state-root', str(self.store.root), *args])
        return code, json.loads(output.getvalue())

    def test_one_explicit_query_request_runs_without_second_plan_command(self):
        code, result = self.call('execute', '--id', '1', '--params', str(self.params), '--confirm')
        self.assertEqual(code, 0)
        self.assertTrue(result['complete'])
        self.assertEqual(result['savedRows'], 1)
        self.assertEqual(result['dataRowsReturned'], 0)
        self.assertNotIn('LOT006', json.dumps(result))

    def test_missing_confirmation_does_not_even_prepare(self):
        with patch.object(core, 'plan') as plan:
            code, result = self.call('execute', '--id', '1', '--params', str(self.params))
        self.assertEqual(code, 2)
        plan.assert_not_called()
        self.assertFalse((self.store.root / 'results').exists())

    def test_large_request_returns_same_unconsumed_plan_without_execution(self):
        self.params.write_text('{}', encoding='utf-8')
        code, proposal = self.call('execute', '--id', '5', '--params', str(self.params), '--confirm',
                                   '--max-rows', '20000')
        self.assertEqual(code, 0)
        self.assertFalse(proposal['executed'])
        self.assertTrue(proposal['requiresLargeApproval'])
        self.assertFalse((self.store.root / 'results').exists())
        code, result = self.call('run', '--plan', proposal['planId'], '--confirm', '--allow-large')
        self.assertEqual(code, 0)
        self.assertTrue(result['complete'])
        self.assertEqual(result['savedRows'], 12005)

    def test_long_conditions_wait_for_review_even_if_not_large(self):
        proposal = {'ok': True, 'planId': 'x', 'requiresLargeApproval': False,
                    'conditionsTruncated': True}
        with patch.object(core, 'plan', return_value=proposal), patch.object(core, 'run') as run:
            code, result = self.call('execute', '--id', '1', '--params', str(self.params), '--confirm')
        self.assertEqual(code, 0)
        self.assertFalse(result['executed'])
        run.assert_not_called()

    def test_plain_query_does_not_start_browser_or_review_previous_results(self):
        with patch('query_core.manager_ui.show') as gui, patch('query_core.results.list_candidates') as review:
            code, _ = self.call('execute', '--id', '1', '--params', str(self.params), '--confirm')
        self.assertEqual(code, 0)
        gui.assert_not_called()
        review.assert_not_called()

    def test_start_summarizes_without_connecting_or_deleting(self):
        with patch('query_core.adapters.open_backend') as db, patch('query_core.results.delete_cleanup') as delete:
            code, result = self.call('start')
        self.assertEqual(code, 0)
        self.assertFalse(result['connected'])
        self.assertEqual(result['profileCount'], 4)
        self.assertEqual(result['previousResults']['results'], [])
        self.assertIsNone(result['cleanup'])
        db.assert_not_called()
        delete.assert_not_called()

    def test_oracle_setup_and_manage_open_same_local_ui_only_when_requested(self):
        live = self.root / 'live'
        for args in (['profiles', 'setup'], ['manage']):
            with self.subTest(args=args), patch('query_core.manager_ui.show', return_value={'ok': True}) as gui:
                result = cli.execute('oracle', cli.parser('oracle').parse_args(['--state-root', str(live), *args]))
            self.assertTrue(result['ok'])
            gui.assert_called_once()

    def test_changed_previous_result_does_not_block_current_work(self):
        with patch('query_core.results.list_candidates', return_value={'results': [{'resultId': 'a'*32}]}), \
             patch('query_core.results.prepare_cleanup', side_effect=ValueError('changed')):
            code, result = self.call('start')
        self.assertEqual(code, 0)
        self.assertTrue(result['ok'])
        self.assertEqual(result['cleanup']['status'], 'retained')

    def test_no_old_results_means_no_cleanup_question(self):
        code, result = self.call('results', 'cleanup-plan')
        self.assertEqual(code, 0)
        self.assertEqual(result['status'], 'nothing_to_cleanup')

    def test_query_catalog_uses_one_catalog_connection_for_many_queries(self):
        for i in range(30):
            self.store.save_query({'name': f'간단 조회 {i}', 'profile': 'production',
                                   'sql': 'SELECT dummy FROM dual', 'parameters': {}}, 'demo')
        with patch.object(self.store, 'connect', wraps=self.store.connect) as connect:
            items = self.store.queries('demo')
        self.assertGreater(len(items), 30)
        self.assertEqual(connect.call_count, 1)


if __name__ == '__main__':
    unittest.main()
