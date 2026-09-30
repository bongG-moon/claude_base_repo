"""Checked memory saves do not add a second model-driven Stop verification."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'
sys.path.insert(0, str(SCRIPTS))
from company_agent.memory import upsert_memory
from company_agent.memory_activity import checked_change, spec_write
from company_agent.memory_history import restore_memory
from company_agent.resource_scope import selected_root, scope_metadata
from company_agent.state import begin_turn, record_activity, stop_decision, mark_verified
from company_agent.execution_contract import classify_command


class MemoryActivityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / 'state'
        self.project = self.base / '프로젝트'
        self.project.mkdir()
        self.env = patch.dict('os.environ', {'COMPANY_AGENT_SCOPE': 'User'})
        self.env.start()
        self.addCleanup(self.env.stop)
        begin_turn('memory-test', 'SMALL', False, [], self.root)
        self.spec = {'id': 'memory.preference.order', 'title': '보고서 순서',
                     'body': '표 아래에 요약을 둔다.', 'kind': 'preference'}
        self.spec_path = self.root / 'tmp/memory-test.json'

    def command(self, operation, extra):
        return (f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}" memory {operation} '
                f'{extra} --state-root "{self.root}" --storage-scope project --project-root "{self.project}"')

    def write(self):
        return record_activity({'hook_event_name': 'PostToolUse', 'session_id': 'memory-test',
            'tool_name': 'Write', 'tool_input': {'file_path': str(self.spec_path), 'content': json.dumps(self.spec)}}, self.root)

    def event(self, receipt=None, operation='upsert', extra=None):
        if receipt is None:
            receipt = upsert_memory(self.spec, selected_root(self.root, self.project, 'project'), receipt=True)
        receipt = {**receipt, **scope_metadata('project', self.project)}
        return {'hook_event_name': 'PostToolUse', 'session_id': 'memory-test', 'tool_name': 'Bash',
                'tool_input': {'command': self.command(operation, extra or f'--spec "{self.spec_path}"')},
                'tool_response': {'stdout': json.dumps(receipt), 'exitCode': 0}}

    def test_successful_save_and_noop_need_no_second_verification(self):
        self.assertEqual(0, self.write()['mutationCount'])
        for _ in range(2):
            state = record_activity(self.event(), self.root)
            self.assertEqual(0, state['mutationCount'])
            self.assertIsNone(state['verification'])
            self.assertEqual('project', state['lastVerifiedMemory']['storageScope'])
            self.assertEqual('memory-item', state['recentTools'][-1]['checkedChange'])
            self.assertEqual({}, stop_decision({'session_id': 'memory-test'}, self.root))
        self.assertFalse(state['lastVerifiedMemory']['changed'])
        self.assertNotIn(self.spec['body'], json.dumps(state, ensure_ascii=False))

    def test_previous_unverified_business_change_is_not_discharged(self):
        record_activity({'session_id': 'memory-test', 'tool_name': 'Write',
                         'tool_input': {'file_path': str(self.project / 'report.html'), 'content': '<html>unfinished'}}, self.root)
        mark_verified('memory-test', 'fail', 'content missing', self.root)
        self.write()
        state = record_activity(self.event(), self.root)
        self.assertEqual(1, state['mutationCount'])
        self.assertEqual('fail', state['verification']['status'])
        self.assertEqual('block', stop_decision({'session_id': 'memory-test'}, self.root)['decision'])

    def test_same_scope_restore_receipt_is_checked(self):
        target = selected_root(self.root, self.project, 'project')
        first = upsert_memory(self.spec, target, receipt=True)
        second = upsert_memory({**self.spec, 'body': '이번 프로젝트 요약을 위에 둔다.'}, target, receipt=True)
        restored = restore_memory(target, self.spec['id'], first['revision'],
                                  expected_revision=second['revision'], expected_sha256=second['sha256'])
        event = self.event(restored, 'restore', f'--id {self.spec["id"]} --revision 1 --expected-revision 2 --expected-sha256 {second["sha256"]}')
        self.assertEqual('restore', checked_change(event, self.root)['operation'])
        self.assertEqual(0, record_activity(event, self.root)['mutationCount'])

    def test_fake_failed_foreign_or_stale_receipts_are_not_accepted(self):
        original = self.event()
        bad = []
        for key, value in [('hook_event_name', 'PostToolUseFailure'), ('tool_name', 'Read'), ('error', 'denied')]:
            bad.append({**original, key: value})
        for command in ('echo ok', original['tool_input']['command'] + ' | head -10',
                        original['tool_input']['command'].replace(str(self.root), str(self.base / 'other'))):
            bad.append({**original, 'tool_input': {'command': command}})
        for key, value in [('ok', False), ('operation', 'other'), ('sha256', '0' * 64),
                           ('storageScope', 'personal'), ('scopeLabel', '개인 전체'),
                           ('verification', {'status': 'pass'}), ('revision', True), ('changeId', '0' * 32)]:
            event = copy.deepcopy(original)
            result = json.loads(event['tool_response']['stdout'])
            result[key] = value
            event['tool_response']['stdout'] = json.dumps(result)
            bad.append(event)
        for response in ({'stdout': '{}'}, {'stdout': '{"ok":true,"ok":true}'},
                         {'stdout': original['tool_response']['stdout'], 'exitCode': 1},
                         {'stdout': original['tool_response']['stdout'], 'interrupted': True},
                         {'stdout': original['tool_response']['stdout'], 'isError': True},
                         {'stdout': '[' * 1100 + ']' * 1100}, {'stdout': ' ' * 16385}):
            bad.append({**original, 'tool_response': response})
        for event in bad:
            self.assertIsNone(checked_change(event, self.root), event)
        result = json.loads(original['tool_response']['stdout'])
        Path(result['path']).write_text('manual change', encoding='utf-8')
        self.assertIsNone(checked_change(original, self.root))

    def test_only_typed_bounded_temporary_write_is_preparation(self):
        inputs = {'file_path': str(self.spec_path), 'content': json.dumps(self.spec)}
        self.assertTrue(spec_write('Write', inputs, self.root))
        self.assertFalse(spec_write('Edit', inputs, self.root))
        for path in (self.root / 'tmp/job.json', self.project / 'memory-test.json',
                     self.root / 'tmp/../memory-test.json'):
            self.assertFalse(spec_write('Write', {**inputs, 'file_path': str(path)}, self.root))
        for spec in ({}, [], {'title': 'x', 'body': 'y', 'other': 'z'},
                     {**self.spec, 'kind': []}, {**self.spec, 'body': 'x' * 2001}):
            self.assertFalse(spec_write('Write', {**inputs, 'content': json.dumps(spec)}, self.root))

    def test_history_is_read_only_not_a_permission_grant(self):
        command = self.command('history', '--id memory.preference.order --limit 3')
        self.assertEqual('read_only', classify_command(command))
        for suffix in (' --output out', ' && echo changed', ' --id other'):
            self.assertEqual('unknown', classify_command(command + suffix))


if __name__ == '__main__':
    unittest.main()
