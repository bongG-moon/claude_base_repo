"""Exercise read-only, bounded explanations without adding work to normal turns."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "company-agent-plugin/scripts"
sys.path.insert(0, str(SCRIPTS))
from company_agent import cli
from company_agent.execution_contract import classify_command
from company_agent.learning_explanation import explain_learning, read_explanation_session
from company_agent.memory import render_memory_context
from company_agent.memory_delivery import record_memory_delivery
from company_agent.state import begin_turn, load_session, record_activity, stop_decision


class LearningExplanationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'state'
        self.env = patch.dict(os.environ, {'COMPANY_AGENT_USER_STATE': str(self.root), 'COMPANY_AGENT_SCOPE': 'User'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def call(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['learning', 'status', '--explain', '--state-root', str(self.root), *args])
        self.assertEqual(0, code, out.getvalue())
        return json.loads(out.getvalue())

    def test_missing_session_is_unknown_without_state_creation_or_discovery(self):
        with patch.object(Path, 'glob', side_effect=AssertionError('Do not discover sessions')):
            result = self.call('--session', 'missing')
        self.assertFalse(self.root.exists())
        self.assertEqual('not-observable', result['explanation']['memoryDelivery']['status'])
        self.assertNotIn('session', result)

    def test_no_session_never_infers_empty_storage(self):
        result = self.call()
        self.assertFalse(result['changed'])
        self.assertIn('정보가 없습니다', result['explanation']['submission']['message'])
        self.assertFalse(self.root.exists())

    def test_delivery_explains_budget_empty_output_and_unknown_without_writes(self):
        for receipt_status in ('budget-dropped', 'no-matches', 'output-produced', 'not-observable'):
            with self.subTest(receipt_status=receipt_status):
                session = begin_turn('explanation', 'SMALL', False, [], self.root)
                offered = render_memory_context([{'id': 'report', 'revision': 1, 'kind': 'preference',
                    'status': 'active', 'title': 'PRIVATE_TITLE', 'body': 'PRIVATE_BODY', 'storageScope': 'personal'}])
                final = json.dumps({'company_agent_personal_memory_context': offered}) if receipt_status == 'output-produced' else '{}'
                record_memory_delivery(self.root, 'explanation', session['turnId'], final,
                    offered_context=offered if receipt_status in ('output-produced', 'budget-dropped') else None,
                    retrieval_status='no-matches' if receipt_status == 'no-matches' else 'unknown')
                before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
                result = self.call('--session', 'explanation')
                self.assertEqual(receipt_status, result['explanation']['memoryDelivery']['status'])
                self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
                self.assertNotIn('PRIVATE_', json.dumps(result))
                self.assertNotIn('session', result)

    def test_previous_turn_is_not_reported_as_current_delivery(self):
        result = explain_learning({'memoryDelivery': {'status': 'output-produced', 'count': 1, 'currentTurn': False}})
        self.assertIn('이전 요청', result['memoryDelivery']['message'])
        self.assertIn('반영은 확인되지', result['memoryDelivery']['message'])

    def test_candidate_counts_and_no_candidates_are_distinct_from_applied(self):
        result = explain_learning({'enabled': True, 'activeChanges': 1, 'candidateCount': 2,
            'currentSubmission': {'captureStatus': 'captured', 'capturedCount': 2, 'appliedCount': 0, 'deferredCount': 1},
            'recentCandidates': [{'title': '보고 순서', 'body': 'PRIVATE_BODY', 'status': 'observing', 'reason': None}]})
        self.assertEqual(0, result['submission']['appliedCount'])
        self.assertEqual(1, result['storedLearning']['activeChangeRecords'])
        self.assertIn('모으는 중', result['recentCandidates'][0]['state'])
        self.assertNotIn('PRIVATE_BODY', json.dumps(result))
        empty = explain_learning({'currentSubmission': {'captureStatus': 'no_candidates'}})
        self.assertIn('새로 저장할', empty['submission']['message'])

    def test_exact_session_only_corrupt_or_wrong_identity_is_unknown(self):
        session = begin_turn('exact', 'SMALL', False, [], self.root)
        path = self.root / 'sessions/exact.json'
        for value in ('{', json.dumps({**session, 'sessionId': 'someone-else'}), json.dumps({**session, 'schemaVersion': 999})):
            path.write_text(value, encoding='utf-8')
            self.assertIsNone(read_explanation_session(self.root, 'exact'))
        self.assertIsNone(read_explanation_session(self.root, '../exact'))

    def test_explanation_command_is_read_only_and_does_not_create_completion_debt(self):
        command = f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}" learning status --explain --session exact --state-root "{self.root}"'
        self.assertEqual('read_only', classify_command(command))
        self.assertEqual('unknown', classify_command(command + ' --explain'))
        self.assertEqual('unknown', classify_command(command + '; echo changed'))
        begin_turn('exact', 'SMALL', False, [], self.root)
        record_activity({'session_id': 'exact', 'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                         'tool_input': {'command': command}}, self.root)
        self.assertEqual(0, load_session('exact', self.root)['mutationCount'])
        self.assertEqual({}, stop_decision({'session_id': 'exact'}, self.root))


if __name__ == '__main__':
    unittest.main()
