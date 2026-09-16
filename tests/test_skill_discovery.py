from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'company-agent-plugin'
sys.path.insert(0, str(PLUGIN / 'scripts'))
from company_agent.native_runtime import runtime_context, worker_runtime_input, MAX_RUNTIME_CONTEXT_CHARS
from company_agent.skill_discovery import MAX_INDEX_CHARS, build_index
from company_agent.skill_registry import inventory_skills, set_skill_preference
from company_agent.skill_workflow import observe, select, preflight
from company_agent.paths import atomic_write_text
from company_agent.state import begin_turn, load_session, record_activity


class SkillDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state, self.project, self.claude = [self.root / name for name in ('state', 'project', 'claude')]
        self.project.mkdir()
        env = patch.dict(os.environ, {'COMPANY_AGENT_USER_STATE': str(self.state),
                         'COMPANY_AGENT_KNOWLEDGE_BASE': '', 'CLAUDE_CONFIG_DIR': str(self.claude)})
        env.start()
        self.addCleanup(env.stop)
        self.sid = 'discovery-test'

    def context(self, prompt='@테스트자료.pptx 이 자료 내용 확인해서 정리해줄 수 있을까?', source=''):
        if not source:
            begin_turn(self.sid, 'MEDIUM', False, [], self.state)
        text = runtime_context(PLUGIN, self.project, prompt, session_id=self.sid, source=source)
        self.assertLessEqual(len(text), MAX_RUNTIME_CONTEXT_CHARS)
        return json.loads(text)['company_agent_runtime']

    def skill(self, name, description='업무 문서 읽기', extra='', source='user'):
        base = self.project / '.claude' if source == 'project' else self.claude
        file = base / 'skills' / name / 'SKILL.md'
        atomic_write_text(file, f'---\nname: {name}\ndescription: {description}\n{extra}---\nSECRET-BODY-{name}\n')
        return file

    def read(self, file):
        content = file.read_text(encoding='utf-8-sig')
        observe(self.state, self.project, {'session_id': self.sid, 'hook_event_name': 'PostToolUse',
                'tool_name': 'Read', 'tool_input': {'file_path': str(file)},
                'tool_response': {'file': {'content': content, 'startLine': 1}}})

    def test_full_index_is_exposed_without_catalog_read_then_only_selected_body(self):
        ctx = self.context()
        index = ctx['skillIndex']
        self.assertEqual('inline', index['mode'])
        self.assertTrue(ctx['skillWorkflow']['indexDelivered'])
        self.assertFalse(ctx['skillWorkflow']['indexRead'])
        self.assertEqual('choose-skill', ctx['skillWorkflow']['nextAction'])
        rows = {row[0]: row for row in index['skills']}
        self.assertIn('office-reader', rows)
        self.assertIn('presentation', rows)
        self.assertIn('기존 PPT', rows['office-reader'][2])
        self.assertIn('skillIndex', ctx['instructions'])  # retained in condensed guidance too
        self.assertNotIn('Presentations.Open', json.dumps(index))  # body was not injected
        before = load_session(self.sid, self.state)['skillWorkflow']
        self.assertEqual({}, before['readSkills'])
        self.assertIsNone(before['selected'])
        row = rows['office-reader']
        self.read(Path(index['roots'][row[4]]) / row[5])
        state = load_session(self.sid, self.state)
        self.assertEqual('office-reader', state['skillWorkflow']['selected']['name'])
        self.assertFalse(state['skillWorkflow']['indexRead'])
        self.assertEqual(0, state['mutationCount'])
        self.assertEqual({}, preflight(self.state, self.project, {'session_id': self.sid,
                         'tool_name': 'Bash', 'tool_input': {'command': 'python sample.py'}}))

    def test_same_conversation_reuses_metadata_but_new_session_does_not(self):
        first = self.context()['skillIndex']
        later = self.context('다음 업무')['skillIndex']
        self.assertEqual('reuse', later['mode'])
        self.assertEqual(first['revision'], later['revision'])
        self.assertNotIn('skills', later)
        self.assertLess(len(json.dumps(later)), len(json.dumps(first)) / 5)
        self.sid = 'another-conversation'
        self.assertEqual('inline', self.context()['skillIndex']['mode'])

    def test_install_delete_and_edit_refresh_without_forgetting_unchanged_body(self):
        self.context()
        self.read(PLUGIN / 'skills/office-reader/SKILL.md')
        old_reads = load_session(self.sid, self.state)['skillWorkflow']['readSkills']
        file = self.skill('custom-reader')
        added = self.context()
        self.assertEqual('inline', added['skillIndex']['mode'])
        self.assertEqual(old_reads, load_session(self.sid, self.state)['skillWorkflow']['readSkills'])
        self.assertTrue(select(self.state, self.project, self.sid, added['skillWorkflow']['turn'], name='office-reader')['ok'])
        self.read(file)
        atomic_write_text(file, file.read_text(encoding='utf-8') + 'Updated\n')
        changed = self.context()
        with self.assertRaises(ValueError):
            select(self.state, self.project, self.sid, changed['skillWorkflow']['turn'], name='custom-reader')
        file.unlink()
        deleted = self.context()
        self.assertEqual('inline', deleted['skillIndex']['mode'])
        self.assertNotIn('custom-reader', [row[0] for row in deleted['skillIndex']['skills']])

    def test_compact_resume_reset_body_receipts_not_work_obligations(self):
        for source in ('compact', 'resume'):
            self.context()
            self.read(PLUGIN / 'skills/office-reader/SKILL.md')
            record_activity({'session_id': self.sid, 'tool_name': 'Write',
                             'tool_input': {'file_path': str(self.project / 'result.txt')}}, self.state)
            before = load_session(self.sid, self.state)
            restored = self.context(source=source)
            after = load_session(self.sid, self.state)
            self.assertEqual('inline', restored['skillIndex']['mode'])
            self.assertEqual({}, after['skillWorkflow']['readSkills'])
            before.pop('skillWorkflow'); after.pop('skillWorkflow')
            self.assertEqual(before, after)

    def test_project_change_never_reuses_another_folder_index(self):
        first = self.context()['skillIndex']
        self.project = self.root / 'different'
        self.project.mkdir()
        second = self.context()['skillIndex']
        self.assertEqual('inline', second['mode'])
        self.assertNotEqual(first['revision'], second['revision'])

    def test_third_party_yaml_and_explicit_only_are_preserved(self):
        file = self.skill('manual-only', extra='disable-model-invocation: true\naliases: [one, two]\nmetadata:\n  nested: value\n')
        ctx = self.context()
        row = next(row for row in ctx['skillIndex']['skills'] if row[0] == 'manual-only')
        self.assertTrue(row[7])
        with self.assertRaises(ValueError):
            self.read(file)
        self.context('/manual-only')
        self.read(file)
        self.assertEqual('manual-only', load_session(self.sid, self.state)['skillWorkflow']['selected']['name'])
        self.assertNotIn('SECRET-BODY', json.dumps(ctx))

    def test_scalar_controls_are_not_limited_to_short_headers_or_read_from_body(self):
        from company_agent.skill_registry import _frontmatter_field
        raw = ('---\nname: test\n' + '# comment\n' * 150 +
               'disable-model-invocation: true\n---\ndisable-model-invocation: false\n').encode()
        self.assertEqual('true', _frontmatter_field(raw, 'disable-model-invocation'))

    def test_preferences_are_injected_and_changes_invalidate_reuse(self):
        self.skill('shared')
        self.skill('shared', source='project')
        first = self.context()
        self.assertEqual({'unresolved'}, {row[3] for row in first['skillIndex']['skills'] if row[0] == 'shared'})
        options = {'project_root': self.project, 'plugin_root': PLUGIN, 'claude_root': self.claude}
        inventory = inventory_skills(self.state, **options)
        preferred = next(x for x in inventory['skills'] if x['name'] == 'shared' and x['source'] == 'project')
        set_skill_preference(self.state, 'shared', preferred['id'], **options)
        after = self.context()
        self.assertEqual('inline', after['skillIndex']['mode'])
        self.assertEqual({'project': 'preferred', 'user': 'other-preferred'},
                         {row[1]: row[3] for row in after['skillIndex']['skills'] if row[0] == 'shared'})

    def test_large_index_preserves_every_entry_and_cross_source_priority(self):
        entries = []
        for i in range(100):
            source = 'user' if i % 2 else 'project'
            entries.append({'id': str(i), 'name': 'shared' if i < 2 else f'skill-{i}', 'source': source,
                            'description': 'Complete description. ' * 20 + 'END',
                            'path': str(self.root / source / f'skill-{i}' / 'SKILL.md'),
                            'invocation': f'skill-{i}', 'explicitOnly': False})
        result = build_index(entries, {'skills': {'shared': '0'}, 'sourceOrder': []}, 'a'*64, self.state)
        self.assertEqual('pages', result['mode'])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, separators=(',', ':'))), MAX_INDEX_CHARS)
        self.assertEqual(100, sum(len(source['names']) for source in result['sources']))
        base, rows = Path(result['directory']), []
        for source in result['sources']:
            directory = json.loads((base / source['file']).read_text(encoding='utf-8'))
            for page in directory['pages']:
                rows.extend(json.loads((base / page['file']).read_text(encoding='utf-8'))['skills'])
        self.assertEqual(100, len(rows))
        self.assertTrue(all(row[2].endswith('END') for row in rows))
        self.assertEqual({'project': 'preferred', 'user': 'other-preferred'},
                         {row[1]: row[3] for row in rows if row[0] == 'shared'})

    def test_paged_runtime_can_choose_body_without_requiring_full_catalog(self):
        for i in range(40):
            self.skill(f'long-{i}', '설명과 조건을 모두 보존합니다. ' * 25)
        context = self.context()
        self.assertEqual('pages', context['skillIndex']['mode'])
        self.read(PLUGIN / 'skills/office-reader/SKILL.md')
        self.assertEqual({}, preflight(self.state, self.project, {'session_id': self.sid,
                         'tool_name': 'Bash', 'tool_input': {'command': 'python sample.py'}}))
        self.assertFalse(load_session(self.sid, self.state)['skillWorkflow']['indexRead'])
        self.assertEqual('reuse', self.context()['skillIndex']['mode'])

    def test_missing_scan_is_not_presented_as_an_empty_or_reused_index(self):
        self.context()
        with patch('company_agent.skill_catalog.refresh_skill_catalog', return_value={'status': 'incomplete'}):
            result = self.context()
        self.assertNotIn('skillIndex', result)
        self.assertEqual('incomplete', result['skillSelection']['catalog']['status'])
        self.assertEqual('unavailable', result['skillWorkflow']['status'])

    def test_malformed_delivery_receipt_is_repaired_by_fresh_exposure(self):
        from company_agent.state import _locked_session
        from company_agent.paths import atomic_write_json
        self.context()
        with _locked_session(self.sid, self.state) as (state, path):
            state['skillWorkflow']['indexDelivery'] = ['broken']
            atomic_write_json(path, state)
        self.assertEqual('inline', self.context()['skillIndex']['mode'])

    def test_worker_gets_own_index_unless_exact_selection_is_inherited(self):
        self.context()
        payload = {'session_id': self.sid, 'tool_name': 'Agent',
                   'tool_input': {'subagent_type': 'company-agent:medium-worker', 'prompt': '자료 정리'}}
        result = worker_runtime_input(PLUGIN, self.project, payload)
        worker_prompt = result['hookSpecificOutput']['updatedInput']['prompt']
        self.assertIn('"skillIndex"', worker_prompt)
        self.assertIn('office-reader', worker_prompt)
        self.read(PLUGIN / 'skills/office-reader/SKILL.md')
        selected = worker_runtime_input(PLUGIN, self.project, payload)['hookSpecificOutput']['updatedInput']['prompt']
        self.assertIn('"selectedSkill"', selected)
        self.assertNotIn('"skillIndex"', selected)


if __name__ == '__main__':
    unittest.main()
