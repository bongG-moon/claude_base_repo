"""A→Python 키 추출→B와 승인 뒤 이어가기를 실제 가상 DB 경로로 확인합니다."""
from pathlib import Path
from contextlib import contextmanager
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
from query_core import core, workflow
from query_core.adapters import AdapterError, DemoBackend
from query_core.store import Store, read_json


class QueryWorkflowTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / '.smoke/query-workflow-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'state', demo=True)
        core.demo_init(self.store)
        self.a = self.store.save_query({'name': '대상 공정', 'profile': 'production',
            'sql': 'SELECT process FROM production_records WHERE quantity>=:minimum ORDER BY lot_id',
            'parameters': {'minimum': {'type': 'int'}}}, 'demo')['id']
        self.b = self.store.save_query({'name': '공정별 실적', 'profile': 'production',
            'sql': 'SELECT lot_id, quantity FROM production_records WHERE process IN (:processes) AND quantity>=:floor ORDER BY lot_id',
            'parameters': {'processes': {'type': 'list[text]'}, 'floor': {'type': 'int'}}}, 'demo')['id']

    def spec(self, **overrides):
        spec = {'source': {'queryId': self.a, 'params': {'minimum': 0}},
                'target': {'queryId': self.b, 'params': {'floor': 0}, 'fromColumn': 'process', 'toParameter': 'processes'}}
        spec.update(overrides)
        return spec

    def run_flow(self, spec=None):
        return workflow.run_workflow(self.store, 'demo', self.spec() if spec is None else spec, confirmed=True)

    def count_plans(self):
        with self.store.connect() as connection:
            return connection.execute('SELECT COUNT(*) FROM plans').fetchone()[0]

    def test_a_is_fresh_each_time_and_b_uses_deduplicated_bind_values(self):
        one = self.run_flow()
        two = self.run_flow()
        self.assertTrue(one['ok'])
        self.assertEqual(one['status'], 'complete')
        self.assertEqual((one['sourceRows'], one['keyCount'], one['targetRows']), (6, 2, 6))
        self.assertEqual(one['dataRowsReturned'], 0)
        self.assertNotEqual(one['sourceResultId'], two['sourceResultId'])
        self.assertNotEqual(one['targetResultId'], two['targetResultId'])
        output = json.dumps(one)
        self.assertNotIn('LOT001', output)
        self.assertNotIn('processes', output)
        record = read_json(one['workflowFile'])
        self.assertEqual(record['targetParams']['processes'], ['DA', 'WB'])
        result = core.result_info(self.store, one['targetResultId'])
        self.assertEqual(sum(row[1] for row in core.load_result_rows(result['dataFile'])), 1040)

    def test_zero_rows_are_successful_empty_source_and_b_is_not_queried(self):
        spec = self.spec()
        spec['source']['params']['minimum'] = 999999
        result = self.run_flow(spec)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'empty_source')
        self.assertEqual(result['sourceRows'], 0)
        self.assertIsNone(result['targetResultId'])
        self.assertEqual(self.count_plans(), 1)

    def test_sql_looking_source_key_is_a_bound_value_not_sql(self):
        a = self.store.save_query({'name': '문자 키', 'profile': 'production',
            'sql': 'SELECT :key AS process FROM dual WHERE dummy=:dummy',
            'parameters': {'key': {'type': 'text'}, 'dummy': {'type': 'text'}}}, 'demo')['id']
        spec = self.spec()
        spec['source'] = {'queryId': a, 'params': {'key': "DA') OR 1=1 --", 'dummy': 'X'}}
        result = self.run_flow(spec)
        self.assertTrue(result['ok'])
        self.assertEqual(result['sourceRows'], 1)
        self.assertEqual(result['targetRows'], 0)
        self.assertEqual(result['keyCount'], 1)
        self.assertNotIn('OR 1=1', json.dumps(result))

    def test_null_only_keys_do_not_run_an_unfiltered_target(self):
        a = self.store.save_query({'name': '빈 키', 'profile': 'production',
            'sql': 'SELECT NULL AS process FROM production_records WHERE quantity>=:minimum',
            'parameters': {'minimum': {'type': 'int'}}}, 'demo')['id']
        spec = self.spec()
        spec['source'] = {'queryId': a, 'params': {'minimum': 0}}
        result = self.run_flow(spec)
        self.assertEqual(result['status'], 'empty_source_keys')
        self.assertEqual(result['nullKeysSkipped'], 6)
        self.assertIsNone(result['targetResultId'])
        self.assertEqual(self.count_plans(), 1)

    def test_large_derived_parameter_file_stops_before_b(self):
        a = self.store.save_query({'name': '긴 키', 'profile': 'production',
            'sql': 'SELECT :prefix || CAST(id AS VARCHAR(20)) AS process FROM large_records WHERE id<=:last_id',
            'parameters': {'prefix': {'type': 'text'}, 'last_id': {'type': 'int'}}}, 'demo')['id']
        spec = self.spec()
        spec['source'] = {'queryId': a, 'params': {'prefix': 'key' * 1300, 'last_id': 30}}
        result = self.run_flow(spec)
        self.assertEqual(result['status'], 'parameter_limit')
        self.assertEqual(result['keyCount'], 30)
        self.assertIsNone(result['targetResultId'])
        self.assertEqual(self.count_plans(), 1)

    def test_partial_source_stops_by_default_and_only_explicit_flag_allows_it(self):
        spec = self.spec()
        spec['source']['options'] = {'max_rows': 1}
        with patch.object(DemoBackend, 'inspect', return_value={'estimated_rows': None, 'exact_count': None}):
            stopped = self.run_flow(spec)
            allowed = self.run_flow(dict(spec, allowPartialSource=True))
        self.assertEqual(stopped['status'], 'partial_source')
        self.assertFalse(stopped['sourceComplete'])
        self.assertIsNone(stopped['targetResultId'])
        self.assertTrue(allowed['ok'])
        self.assertEqual(allowed['keyCount'], 1)
        self.assertEqual(allowed['targetRows'], 3)

    def test_more_than_500_keys_does_not_silently_slice_or_execute_b(self):
        a = self.store.save_query({'name': '많은 대상', 'profile': 'production',
            'sql': 'SELECT id FROM large_records WHERE id<=:last_id', 'parameters': {'last_id': {'type': 'int'}}}, 'demo')['id']
        b = self.store.save_query({'name': '키로 조회', 'profile': 'production',
            'sql': 'SELECT id FROM large_records WHERE id IN (:ids)', 'parameters': {'ids': {'type': 'list[int]'}}}, 'demo')['id']
        result = self.run_flow({'source': {'queryId': a, 'params': {'last_id': 501}},
                                'target': {'queryId': b, 'params': {}, 'fromColumn': 'id', 'toParameter': 'ids'}})
        self.assertEqual(result['status'], 'key_limit')
        self.assertEqual(result['keyCountAtLeast'], 501)
        self.assertIsNone(result['targetResultId'])
        self.assertEqual(self.count_plans(), 1)

    def test_target_large_approval_keeps_lineage_and_resume_does_not_query_again(self):
        spec = self.spec()
        spec['target']['options'] = {'max_rows': 20000}
        pending = self.run_flow(spec)
        self.assertEqual(pending['status'], 'approval_required')
        self.assertEqual(pending['pendingStage'], 'target')
        self.assertNotIn('conditions', pending)
        self.assertNotIn('targetParams', pending)
        still_pending = workflow.resume_workflow(self.store, 'demo', pending['workflowId'], confirmed=True)
        self.assertEqual(still_pending['planId'], pending['planId'])
        self.assertEqual(self.count_plans(), 2)
        receipt = core.run(self.store, 'demo', pending['planId'], confirmed=True, allow_large=True)
        finished = workflow.resume_workflow(self.store, 'demo', pending['workflowId'], confirmed=True)
        self.assertTrue(finished['ok'])
        self.assertEqual(finished['targetResultId'], receipt['resultId'])
        self.assertEqual(finished['sourceResultId'], pending['sourceResultId'])
        self.assertEqual(self.count_plans(), 2)

    def test_source_large_approval_then_resume_executes_only_b(self):
        spec = self.spec()
        spec['source']['options'] = {'max_rows': 20000}
        pending = self.run_flow(spec)
        self.assertEqual(pending['pendingStage'], 'source')
        source = core.run(self.store, 'demo', pending['planId'], confirmed=True, allow_large=True)
        finished = workflow.resume_workflow(self.store, 'demo', pending['workflowId'], confirmed=True)
        self.assertTrue(finished['ok'])
        self.assertEqual(finished['sourceResultId'], source['resultId'])
        self.assertEqual(self.count_plans(), 2)

    def test_changed_result_hash_never_drives_b(self):
        original = workflow._record_stage
        def tamper(store, record, stage, receipt):
            original(store, record, stage, receipt)
            if stage == 'source':
                data = Path(core.result_info(store, receipt['resultId'])['dataFile'])
                data.write_bytes(data.read_bytes().replace(b'DA', b'QA'))
        with patch.object(workflow, '_record_stage', side_effect=tamper), self.assertRaisesRegex(ValueError, '바뀌어 B'):
            self.run_flow()
        self.assertEqual(self.count_plans(), 1)

    def test_unconfirmed_or_invalid_mapping_never_starts_a_query(self):
        with self.assertRaises(ValueError):
            workflow.run_workflow(self.store, 'demo', self.spec())
        spec = self.spec()
        spec['target']['toParameter'] = 'floor'
        with self.assertRaisesRegex(ValueError, '목록 조건'):
            self.run_flow(spec)
        self.assertEqual(self.count_plans(), 0)

    def test_source_error_keeps_result_id_and_stops_b(self):
        @contextmanager
        def failure(*args, **kwargs):
            raise AdapterError('db_query', '합성 SQL 오류')
            yield
        with patch.object(DemoBackend, 'execute', failure), self.assertRaises(AdapterError) as error:
            self.run_flow()
        context = error.exception.workflow_context
        self.assertEqual(context['failedStage'], 'source')
        self.assertIsNotNone(context['sourceResultId'])
        self.assertIsNone(context['targetResultId'])
        self.assertEqual(self.count_plans(), 1)

    def test_plan_callback_rejects_wrong_path_or_plan_without_overwrite(self):
        spec = self.spec()
        spec['source']['options'] = {'max_rows': 20000}
        pending = self.run_flow(spec)
        proposal = dict(self.store.get_plan(pending['planId']), planId=pending['planId'])
        original = Path(pending['workflowFile']).read_bytes()
        proposal['workflowContext']['workflowFile'] = str(self.store.root / 'catalog.sqlite3')
        with self.assertRaisesRegex(ValueError, '위치'):
            workflow.record_plan_result(self.store, 'demo', proposal, {})
        self.assertEqual(Path(pending['workflowFile']).read_bytes(), original)

    def test_callback_rejects_workflow_record_with_another_identity(self):
        spec = self.spec()
        spec['source']['options'] = {'max_rows': 20000}
        pending = self.run_flow(spec)
        proposal = dict(self.store.get_plan(pending['planId']), planId=pending['planId'])
        path = Path(pending['workflowFile'])
        record = read_json(path)
        record['workflowId'] = 'f' * 32
        from query_core.store import atomic_json
        atomic_json(path, record)
        with self.assertRaisesRegex(ValueError, '번호와 위치'):
            workflow.record_plan_result(self.store, 'demo', proposal, {})
        self.assertFalse((path.parent / ('f' * 32 + '.json')).exists())
        self.assertFalse(workflow._completion_path(self.store, pending['workflowId'], pending['planId']).exists())

    def test_resume_detects_changed_query_without_new_query(self):
        result = self.run_flow()
        query = self.store.query(self.b, 'demo')
        query = {key: query[key] for key in ('name', 'profile', 'sql', 'parameters')}
        query['sql'] += ' LIMIT 1'
        self.store.save_query(query, 'demo', query_id=self.b)
        with self.assertRaisesRegex(ValueError, '쿼리가 바뀌었습니다'):
            workflow.resume_workflow(self.store, 'demo', result['workflowId'], confirmed=True)
        self.assertEqual(self.count_plans(), 2)

    def test_concurrent_resume_is_rejected_without_second_target_query(self):
        spec = self.spec()
        spec['source']['options'] = {'max_rows': 20000}
        pending = self.run_flow(spec)
        core.run(self.store, 'demo', pending['planId'], confirmed=True, allow_large=True)
        original = core.execute
        attempts = []
        def nested(store, engine, query_id, values, options=None, *, confirmed=False, **kwargs):
            if query_id == self.b:
                with self.assertRaisesRegex(ValueError, '중복 조회하지 않았습니다'):
                    workflow.resume_workflow(store, engine, pending['workflowId'], confirmed=True)
                attempts.append(query_id)
            return original(store, engine, query_id, values, options, confirmed=confirmed, **kwargs)
        with patch.object(core, 'execute', side_effect=nested):
            result = workflow.resume_workflow(self.store, 'demo', pending['workflowId'], confirmed=True)
        self.assertTrue(result['ok'])
        self.assertEqual(attempts, [self.b])
        self.assertEqual(self.count_plans(), 2)

    def test_completed_source_and_target_recover_after_callback_lock_collision_without_requery(self):
        spec = self.spec()
        spec['source']['options'] = {'max_rows': 20000}
        spec['target']['options'] = {'max_rows': 20000}
        pending_source = self.run_flow(spec)
        workflow_id = pending_source['workflowId']
        with workflow._lock(self.store, workflow_id):
            source = core.run(self.store, 'demo', pending_source['planId'], confirmed=True, allow_large=True)
        self.assertIn('workflowLinkWarning', source)
        source_marker = workflow._completion_path(self.store, workflow_id, pending_source['planId'])
        self.assertEqual(read_json(source_marker)['resultId'], source['resultId'])
        pending_target = workflow.resume_workflow(self.store, 'demo', workflow_id, confirmed=True)
        self.assertEqual(pending_target['pendingStage'], 'target')
        self.assertEqual(pending_target['sourceResultId'], source['resultId'])
        still_pending = workflow.resume_workflow(self.store, 'demo', workflow_id, confirmed=True)
        self.assertEqual(still_pending['planId'], pending_target['planId'])
        self.assertEqual(self.count_plans(), 2)
        with workflow._lock(self.store, workflow_id):
            target = core.run(self.store, 'demo', pending_target['planId'], confirmed=True, allow_large=True)
        self.assertIn('workflowLinkWarning', target)
        complete = workflow.resume_workflow(self.store, 'demo', workflow_id, confirmed=True)
        repeated = workflow.resume_workflow(self.store, 'demo', workflow_id, confirmed=True)
        self.assertTrue(complete['ok'])
        self.assertEqual(complete['sourceResultId'], source['resultId'])
        self.assertEqual(complete['targetResultId'], target['resultId'])
        self.assertEqual(repeated['targetResultId'], target['resultId'])
        self.assertEqual(self.count_plans(), 2)

    def test_approved_source_failure_keeps_row_count_unknown_not_zero(self):
        spec = self.spec()
        spec['source']['options'] = {'max_rows': 20000}
        pending = self.run_flow(spec)

        @contextmanager
        def failure(*args, **kwargs):
            raise AdapterError('db_query', '서버에서 SQL 실행을 거절했습니다.')
            yield

        with patch.object(DemoBackend, 'execute', failure), self.assertRaises(AdapterError):
            core.run(self.store, 'demo', pending['planId'], confirmed=True, allow_large=True)
        resumed = workflow.resume_workflow(self.store, 'demo', pending['workflowId'], confirmed=True)
        self.assertEqual(resumed['status'], 'failed')
        self.assertFalse(resumed['ok'])
        self.assertIsNone(resumed['sourceRows'])
        self.assertIsNone(resumed['targetRows'])
        self.assertEqual(self.count_plans(), 1)

    def test_completion_marker_cannot_adopt_a_different_plan_result(self):
        spec = self.spec()
        spec['source']['options'] = {'max_rows': 20000}
        pending = self.run_flow(spec)
        workflow_id = pending['workflowId']
        with workflow._lock(self.store, workflow_id):
            core.run(self.store, 'demo', pending['planId'], confirmed=True, allow_large=True)
        unrelated = core.execute(self.store, 'demo', self.a, {'minimum': 0}, confirmed=True)
        marker_path = workflow._completion_path(self.store, workflow_id, pending['planId'])
        marker = read_json(marker_path)
        marker['resultId'] = unrelated['resultId']
        from query_core.store import atomic_json
        atomic_json(marker_path, marker)
        with self.assertRaisesRegex(ValueError, '실행 계획과 완료 결과'):
            workflow.resume_workflow(self.store, 'demo', workflow_id, confirmed=True)
        self.assertEqual(self.count_plans(), 2)

    def test_partial_target_is_not_reported_as_complete_success(self):
        spec = self.spec()
        spec['target']['options'] = {'max_rows': 1}
        with patch.object(DemoBackend, 'inspect', return_value={'estimated_rows': None, 'exact_count': None}):
            result = self.run_flow(spec)
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'partial_target')
        self.assertFalse(result['complete'])
        self.assertFalse(result['targetComplete'])
        self.assertEqual(result['outcome'], 'partial')
        self.assertEqual(result['reason'], 'row_limit')
        self.assertIn('일부 결과', result['message'])
        self.assertNotIn('마쳤습니다', result['message'])
        self.assertEqual(result['targetRows'], 1)
        repeated = workflow.resume_workflow(self.store, 'demo', result['workflowId'], confirmed=True)
        self.assertEqual(repeated['status'], 'partial_target')
        self.assertEqual(self.count_plans(), 2)

    def test_partial_target_callback_recovery_preserves_partial_status(self):
        spec = self.spec()
        spec['target']['options'] = {'max_rows': 20000, 'max_bytes': 1}
        pending = self.run_flow(spec)
        self.assertEqual(pending['pendingStage'], 'target')
        with workflow._lock(self.store, pending['workflowId']):
            target = core.run(self.store, 'demo', pending['planId'], confirmed=True, allow_large=True)
        self.assertFalse(target['complete'])
        result = workflow.resume_workflow(self.store, 'demo', pending['workflowId'], confirmed=True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'partial_target')
        self.assertEqual(result['reason'], 'byte_limit')
        self.assertEqual(result['targetResultId'], target['resultId'])
        self.assertEqual(self.count_plans(), 2)


if __name__ == '__main__':
    unittest.main()
