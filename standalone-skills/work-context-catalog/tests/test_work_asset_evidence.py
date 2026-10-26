import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from work_catalog import clean
from work_execution import ExecutionTrace, merge_executions, sanitize_execution
from work_asset_evidence import asset_change, normalize_asset_change, persistence_result


def call(name, args, call_id='a'):
    return {'type': 'assistant', 'message': {'content': [
        {'type': 'tool_use', 'name': name, 'id': call_id, 'input': args}]}}


class AssetEvidenceTests(unittest.TestCase):
    def signal(self, tool, args):
        return asset_change(tool, args, clean)

    def event(self, tool='Write', args=None):
        trace = ExecutionTrace(clean)
        trace.set_requests(['b' * 64])
        trace.observe(call(tool, args or {'file_path': '.claude/skills/교육정리/SKILL.md'}), 'r1')
        return trace, next(iter(trace.events.values()))

    def test_native_skill_entry_and_supporting_files(self):
        for path in (r'C:\Users\owner\.claude\skills\교육정리\SKILL.md',
                     'skills/교육정리/references/steps.md',
                     'standalone-skills/교육정리/scripts/run.py',
                     '.agents/skills/교육정리/template.json'):
            with self.subTest(path=path):
                value = self.signal('Write', {'file_path': path, 'content': 'PRIVATE BODY'})
                self.assertEqual('skill', value['kind'])
                self.assertEqual('교육정리', value['target'])
                self.assertEqual('target_path', value['basis'])
                self.assertNotIn('PRIVATE', json.dumps(value))
                self.assertNotIn('Users', json.dumps(value))
        self.assertEqual('skill', self.signal('Edit', {'file_path': 'SKILL.md'})['kind'])

    def test_memory_and_knowledge_markdown_writes(self):
        for tool in ('Write', 'Edit', 'MultiEdit', 'write_file'):
            for path, kind in (('.claude/projects/project/memory/업무.md', 'memory'),
                               ('MEMORY.md', 'memory'), ('state/memory/context.md', 'memory'),
                               ('state/knowledge/지표.md', 'knowledge')):
                self.assertEqual(kind, self.signal(tool, {'file_path': path})['kind'])

    def test_read_load_mentions_and_staging_are_not_saves(self):
        for tool in ('Read', 'Skill', 'Grep', 'ToolSearch', 'AskUserQuestion', 'Agent'):
            self.assertIsNone(self.signal(tool, {'file_path': '.claude/skills/test/SKILL.md',
                'skill': 'personal-memory', 'description': 'save knowledge', 'prompt': 'Write MEMORY.md'}))
        for path in ('tmp/memory-fact.json', 'tmp/knowledge-fact.json', 'outputs/skill-notes.md',
                     'memory/data.csv', 'knowledge.txt', 'skills.md', 'skills/example.md',
                     'skills/test/../../../unrelated.py', 'https://example.org/skills/x/SKILL.md'):
            self.assertIsNone(self.signal('Write', {'file_path': path}))
        self.assertIsNone(self.signal('Bash', {'command': 'echo "save_memory"'}))
        self.assertIsNone(self.signal('Bash', {'command': 'python -c "print(\'memory upsert\')"'}))

    def test_known_connected_persistence_tools_only(self):
        for name in ('mcp__datalake__save_query_knowledge', 'mcp__datalake__save_table_knowledge',
                     'mcp__datalake__save_column_meaning'):
            value = self.signal(name, {'body': 'PRIVATE QUERY', 'key': 'PRIVATE KEY'})
            self.assertEqual('knowledge', value['kind'])
            self.assertEqual('persistence_tool', value['basis'])
            self.assertNotIn('PRIVATE', json.dumps(value))
        for name in ('mcp__memory__create_entities', 'mcp__memory__add_observations', 'mcp__store__save_memory'):
            self.assertEqual('memory', self.signal(name, {})['kind'])
        for name in ('mcp__store__save_file', 'mcp__db__create_entities', 'mcp__memory__read_graph',
                     'mcp__datalake__search_query_knowledge', 'mcp__store__delete_memory',
                     'mcp__store__maybe_save_memory', 'mcp__store__save_memory_preview'):
            self.assertIsNone(self.signal(name, {}))

    def test_exact_managed_cli_upsert_and_skill_update(self):
        for prefix in ('company-agent', '"C:/tools/company-agent.cmd"',
                       'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:/회사/plugin/scripts/Invoke-CompanyAgent.ps1" -Mode Cli',
                       '& "C:/Windows/powershell.exe" -NoProfile -File C:/plugin/Invoke-CompanyAgent.ps1 -Mode Cli'):
            for kind in ('memory', 'knowledge'):
                with self.subTest(prefix=prefix, kind=kind):
                    value = self.signal('Bash', {'command': prefix + ' ' + kind + ' upsert --spec "C:/private/spec.json" --storage-scope project'})
                    self.assertEqual(kind, value['kind'])
                    self.assertEqual('managed_command', value['basis'])
                    self.assertNotIn('private', json.dumps(value))
        value = self.signal('PowerShell', {'command': 'company-agent asset update --name 교육정리 --instructions-file body.md'})
        self.assertEqual('skill', value['kind'])
        self.assertEqual('교육정리', value['target'])

    def test_managed_create_is_ambiguous_and_query_or_shell_strings_are_not_save_evidence(self):
        for command in ('company-agent asset create --spec source.json',
                        'company-agent asset validate .claude/skills/test',
                        'company-agent memory search upsert', 'company-agent memory upsert --help',
                        'company-agent knowledge upsert --spec x.json --dry-run',
                        'company-agent memory upsert --spec', 'company-agent asset update --name x',
                        'echo company-agent memory upsert --spec a.json',
                        'powershell -Command "company-agent memory upsert --spec a.json"',
                        'company-agent memory upsert --spec x.json && upload private',
                        'company-agent memory upsert --spec $(private)',
                        'company-agent memory upsert --spec x.json\nprint private',
                        'powershell -File wrong.ps1 -Mode Cli memory upsert --spec x.json'):
            with self.subTest(command=command):
                self.assertIsNone(self.signal('Bash', {'command': command}))

    def test_untrusted_arguments_are_bounded_and_not_decoded_as_code(self):
        for args in ('broken json', '[' * 80000, ['not-a-dict'], None):
            self.assertIsNone(self.signal('Write', args))
        value = self.signal('Write', json.dumps({'file_path': 'memory/메모.md', 'content': 'PRIVATE'}))
        self.assertEqual('memory', value['kind'])
        self.assertIsNone(self.signal('Bash', {'command': 'company-agent ' + 'x' * 32768}))

    def test_sensitive_targets_not_retained(self):
        for path in ('memory/api_key.md', 'memory/' + 'a' * 64 + '.md'):
            value = self.signal('Write', {'file_path': path})
            self.assertEqual('memory', value['kind'])
            self.assertNotIn('target', value)

    def test_result_state_stays_separate_from_persistence_invocation(self):
        trace, event = self.event()
        self.assertEqual('skill', event['asset_change']['kind'])
        self.assertEqual('unconfirmed', event['status'])
        trace.observe({'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': 'a', 'is_error': True, 'content': 'PRIVATE FAILURE'}]}}, 'r2')
        self.assertEqual('error', event['status'])
        self.assertEqual('skill', event['asset_change']['kind'])
        self.assertNotIn('PRIVATE', json.dumps(event))

    def test_import_roundtrip_old_format_and_reduced_metadata(self):
        _, event = self.event()
        event['asset_change']['body'] = 'PRIVATE BODY'
        restored = sanitize_execution(event, clean, set(event['request_ids']))
        self.assertEqual('skill', restored['asset_change']['kind'])
        self.assertNotIn('PRIVATE', json.dumps(restored))
        event.pop('asset_change')
        self.assertNotIn('asset_change', sanitize_execution(event, clean, set(event['request_ids'])))

    def test_import_invalid_schema_rejected_and_conflict_not_trusted(self):
        for value in ({}, {'kind': 'file'}, {'kind': 'skill', 'operation': 'verified', 'basis': 'target_path'},
                      {'kind': 'memory', 'operation': 'create_or_update', 'basis': 'assistant_claim'},
                      {'kind': 'skill', 'operation': 'create_or_update', 'basis': 'target_path', 'target': 'x' * 101}):
            with self.assertRaises(ValueError):
                normalize_asset_change(value, clean)
        _, event = self.event()
        event['asset_change_conflict'] = True
        restored = sanitize_execution(event, clean, set(event['request_ids']))
        self.assertTrue(restored['asset_change_conflict'])
        self.assertNotIn('asset_change', restored)
        event['asset_change_conflict'] = 'true'
        with self.assertRaises(ValueError):
            sanitize_execution(event, clean, set(event['request_ids']))

    def test_catalog_merge_enriches_legacy_but_conflicting_kinds_are_unknown(self):
        _, current = self.event()
        old = copy.deepcopy(current)
        old.pop('asset_change')
        self.assertEqual(current['asset_change'], merge_executions([old], [current])[0]['asset_change'])
        changed = copy.deepcopy(current)
        changed['asset_change']['kind'] = 'memory'
        for records in ((current, changed), (changed, current)):
            result = merge_executions([records[0]], [records[1]])[0]
            self.assertNotIn('asset_change', result)
            self.assertTrue(result['asset_change_conflict'])

    def test_import_cannot_turn_read_or_arbitrary_tools_into_a_save(self):
        _, event = self.event()
        for tool, basis in (('Read', 'target_path'), ('Skill', 'managed_command'),
                            ('mcp__store__save_file', 'persistence_tool')):
            event['tool'] = tool
            event['asset_change']['basis'] = basis
            with self.assertRaises(ValueError):
                sanitize_execution(event, clean, set(event['request_ids']))

    def test_duplicate_raw_call_with_different_path_drops_save_evidence(self):
        trace, event = self.event(args={'file_path': 'memory/example.md'})
        trace.observe(call('Write', {'file_path': 'outputs/example.md'}), 'r2')
        self.assertTrue(trace.partial)
        self.assertTrue(event['asset_change_conflict'])
        self.assertNotIn('asset_change', event)
        trace, event = self.event(args={'file_path': 'memory/example.md'})
        trace.observe(call('Read', {'file_path': 'memory/example.md'}), 'r2')
        self.assertTrue(event['asset_change_conflict'])
        self.assertNotIn('asset_change', event)

    def result(self, trace, body, key='r2'):
        trace.observe({'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': 'a', 'content': body}]}}, key)

    def test_complete_json_save_failure_prevents_returned_selection(self):
        for body in ('{"ok":false,"message":"PRIVATE"}',
                     [{'type': 'text', 'text': '{"status":"failed","body":"PRIVATE"}'}],
                     [{'type': 'text', 'text': '{"is_error":true}'}],
                     [{'type': 'text', 'text': '{"exit_code":2}'}]):
            trace, event = self.event()
            self.result(trace, body)
            self.assertEqual('error', event['status'])
            self.assertEqual('failed', event['asset_result'])
            self.assertTrue(event['result_observed'])
            self.assertNotIn('PRIVATE', json.dumps(event))
            self.assertEqual(event, sanitize_execution(event, clean, set(event['request_ids'])))
            self.result(trace, '{"ok":true}', 'r3')
            self.assertEqual('error', event['status'])

    def test_approval_input_or_cancelled_result_does_not_prove_save(self):
        for state in ('input_required', 'approval_required', 'cancelled', 'pending', 'deferred'):
            trace, event = self.event()
            self.result(trace, [{'type': 'text', 'text': json.dumps({'ok': False, 'status': state})}])
            self.assertEqual('unconfirmed', event['status'])
            self.assertTrue(event['result_observed'])
            self.assertEqual('pending', event['asset_result'])
            self.assertEqual(event, sanitize_execution(event, clean, set(event['request_ids'])))
            self.result(trace, '{"ok":true}', 'r3')
            self.assertEqual('unconfirmed', event['status'])

    def test_complete_json_only_and_bounded_status_read(self):
        for body in ('Example: {"ok":false}', 'An old error happened, now saved.',
                     '{"body":{"ok":false}}', '{"example":"status: failed"}',
                     '[{"ok":false}]', '{"ok":false}\nmore text',
                     '{"ok":false,"body":"' + 'a' * 65536 + '"}'):
            self.assertIsNone(persistence_result({'content': body}))
        self.assertIsNone(persistence_result({'content': [{'type': 'image', 'data': 'PRIVATE'}]}))
        self.assertIsNone(persistence_result({'content': [{'type': 'text', 'text': '{}'}] * 9}))
        self.assertEqual('failed', persistence_result({'structuredContent': {'ok': False}}))
        self.assertEqual('pending', persistence_result({'output': '{"saved":false}'}))

    def test_non_persistence_results_keep_transport_semantics(self):
        trace, event = self.event(tool='Read', args={'file_path': 'data.json'})
        self.result(trace, '{"ok":false}')
        self.assertEqual('returned', event['status'])
        self.assertNotIn('asset_result', event)

    def test_pending_merge_is_sticky_and_conflict_roundtrips(self):
        trace, event = self.event()
        self.result(trace, '{"status":"approval_required"}')
        _, returned = self.event()
        returned['status'], returned['result_observed'] = 'returned', True
        for left, right in ((event, returned), (returned, event)):
            merged = merge_executions([left], [right])[0]
            self.assertEqual('unconfirmed', merged['status'])
            self.assertEqual(merged, sanitize_execution(merged, clean, set(merged['request_ids'])))
        changed = copy.deepcopy(returned)
        changed['asset_change']['kind'] = 'memory'
        merged = merge_executions([event], [changed])[0]
        self.assertTrue(merged['asset_change_conflict'])
        self.assertEqual(merged, sanitize_execution(merged, clean, set(merged['request_ids'])))

    def test_import_cannot_invent_pending_for_missing_response(self):
        _, event = self.event()
        event['asset_result'] = 'pending'
        with self.assertRaises(ValueError):
            sanitize_execution(event, clean, set(event['request_ids']))


if __name__ == '__main__':
    unittest.main()
