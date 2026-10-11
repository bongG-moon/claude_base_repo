"""Native factory skills learn from real body receipts, never profile-wide grants."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_learning as learning_fixtures
from company_agent import learning
from company_agent.asset_factory import create_asset
from company_agent.native_skill_storage import locate_skill
from company_agent.paths import atomic_write_json, atomic_write_text
from company_agent.skill_catalog import refresh_skill_catalog
from company_agent.skill_registry import inventory_skills
from company_agent.skill_workflow import observe, prepare
from company_agent.state import load_session, record_activity, session_path


class NativeSkillLearningTests(unittest.TestCase):
    def setUp(self):
        self.f = learning_fixtures.LearningTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root = self.f.root
        self.project = Path(self.f.temp.name) / 'project'
        self.project.mkdir()
        self.config = Path(self.f.temp.name) / 'isolated-claude'
        self.env = patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.config), 'COMPANY_AGENT_SCOPE': 'User',
                                          'COMPANY_AGENT_USER_STATE': str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def create(self, scope='personal'):
        location = locate_skill(self.root, self.project, 'weekly-report', scope, for_create=True)
        return create_asset({'type': 'skill', 'name': 'weekly-report', 'description': 'Weekly summary',
                             'instructions': '# Work\nKeep original content.'},
                            location.state_root, skill_location=location) / 'SKILL.md'

    def prepare(self, prompt='/weekly-report'):
        turn = self.f.turn(failure=1, verification='pass')
        catalog = refresh_skill_catalog(self.root, self.project,
            inventory_skills(self.root, project_root=self.project, claude_root=self.config))
        prepare(self.root, self.project, self.f.session, catalog, prompt=prompt)
        return turn

    def native_load(self, success=True):
        observe(self.root, self.project, {'hook_event_name': 'PostToolUse', 'session_id': self.f.session,
            'tool_name': 'Skill', 'tool_input': {'skill': 'weekly-report'}, 'tool_response': {'success': success}})
        return load_session(self.f.session, self.root)['usedSkills']

    def read(self, file, start=1, end=None, **overrides):
        lines = file.read_text(encoding='utf-8').splitlines()
        payload = {'hook_event_name': 'PostToolUse', 'session_id': self.f.session, 'tool_name': 'Read',
                   'tool_input': {'file_path': str(file)},
                   'tool_response': {'file': {'content': '\n'.join(lines[start - 1:end]), 'startLine': start}}}
        payload.update(overrides)
        record_activity(payload, self.root)
        return load_session(self.f.session, self.root)['usedSkills']

    def submit(self, turn):
        return self.f.submit(turn, self.f.spec([self.f.lesson()]))['changes'][0]

    def test_native_personal_actual_skill_load_learns_and_rolls_back(self):
        file = self.create()
        before = file.read_bytes()
        turn = self.prepare()
        used = self.native_load()
        self.assertEqual(1, len(used))
        self.assertEqual('native-personal', used[0]['skillTarget']['kind'])
        self.assertNotIn('Keep original', json.dumps(load_session(self.f.session, self.root)))
        change = self.submit(turn)
        self.assertEqual('active', change['status'])
        self.assertTrue(file.read_bytes().startswith(before))
        self.assertEqual('rolled_back', learning.rollback_change(self.root, change['id'])['status'])
        self.assertEqual(before, file.read_bytes())
        self.assertFalse((self.root / 'personal-root/.claude/skills/weekly-report/SKILL.md').exists())

    def test_project_native_uses_runtime_ledger_and_verified_project_registry(self):
        file = self.create('project')
        original = file.read_bytes()
        turn = self.prepare()
        target = self.native_load()[0]['skillTarget']
        self.assertEqual('project', target['scope'])
        self.assertNotEqual(str(self.root), target['stateRoot'])
        change = self.submit(turn)
        self.assertEqual('active', change['status'])
        self.assertTrue((self.root / 'learning/state.json').is_file())
        self.assertFalse((Path(target['stateRoot']) / 'learning/state.json').exists())
        self.assertTrue(learning.rollback_change(self.root, change['id'])['changed'])
        self.assertEqual(original, file.read_bytes())

    def test_personal_native_learning_continues_across_projects_and_rolls_back(self):
        file = self.create()
        original = file.read_bytes()
        first_turn = self.prepare()
        target = self.native_load()[0]['skillTarget']
        self.assertIsNone(target['project'])
        first = self.submit(first_turn)
        first_bytes = file.read_bytes()
        self.project = Path(self.f.temp.name) / 'second-project'
        self.project.mkdir()
        next_turn = self.prepare()
        self.assertEqual(target, self.native_load()[0]['skillTarget'])
        second = self.f.submit(next_turn, self.f.spec([self.f.lesson(body='기간과 단위를 확정한 뒤 집계한다.')]))['changes'][0]
        self.assertEqual('active', second['status'])
        self.assertEqual('rolled_back', learning.rollback_change(self.root, second['id'])['status'])
        self.assertEqual(first_bytes, file.read_bytes())
        self.assertEqual('rolled_back', learning.rollback_change(self.root, first['id'])['status'])
        self.assertEqual(original, file.read_bytes())

    def test_personal_native_survives_creation_project_removal(self):
        file = self.create()
        original = file.read_bytes()
        turn = self.prepare()
        self.native_load()
        first = self.submit(turn)
        self.project.rmdir()  # Only this test's empty creation-project fixture.
        self.project = Path(self.f.temp.name) / 'remaining-project'
        self.project.mkdir()
        self.prepare()
        self.assertEqual(1, len(self.native_load()))
        self.assertEqual('rolled_back', learning.rollback_change(self.root, first['id'])['status'])
        self.assertEqual(original, file.read_bytes())

    def test_native_read_receipt_requires_all_lines_and_no_worker_failure(self):
        file = self.create()
        self.prepare()
        self.assertEqual([], self.read(file, end=1))
        self.assertEqual([], self.read(file, agent_id='worker'))
        self.assertEqual([], self.read(file, tool_response={'success': False}))
        self.assertEqual(1, len(self.read(file, start=2)))

    def test_failed_native_skill_is_not_learning_evidence(self):
        self.create()
        self.prepare()
        self.assertEqual([], self.native_load(False))

    def test_existing_native_unregistered_or_explicitly_updated_is_not_owned(self):
        file = self.config / 'skills/weekly-report/SKILL.md'
        atomic_write_text(file, '---\nname: weekly-report\ndescription: Native user skill\n---\nKeep user workflow.\n')
        for registered in (False, True):
            with self.subTest(registered=registered):
                if registered:
                    location = locate_skill(self.root, self.project, 'weekly-report')
                    create_asset({'type': 'skill', 'name': 'weekly-report', 'description': 'Native user skill',
                                  'instructions': 'Keep user workflow.'}, location.state_root, skill_location=location)
                before = file.read_bytes()
                turn = self.prepare()
                self.assertEqual([], self.native_load())
                self.assertEqual([], self.read(file))
                self.assertEqual('deferred', self.submit(turn)['status'])
                self.assertEqual(before, file.read_bytes())

    def test_stale_deleted_moved_and_same_name_targets_defer(self):
        file = self.create()
        for mode in ('changed', 'deleted', 'moved', 'same-name'):
            with self.subTest(mode=mode):
                original = file.read_bytes()
                turn = self.prepare()
                self.native_load()
                alternative = self.project / '.claude/skills/weekly-report/SKILL.md'
                if mode == 'changed':
                    atomic_write_text(file, original.decode() + '\nManual edit.\n')
                elif mode in ('deleted', 'moved'):
                    file.unlink()
                    if mode == 'moved':
                        atomic_write_text(alternative, original.decode())
                else:
                    atomic_write_text(alternative, original.decode())
                before = file.read_bytes() if file.exists() else None
                self.assertEqual('deferred', self.submit(turn)['status'])
                self.assertEqual(before, file.read_bytes() if file.exists() else None)
                if alternative.exists():
                    self.assertEqual(original, alternative.read_bytes())
                    alternative.unlink()
                atomic_write_text(file, original.decode())

    def test_forged_registry_path_and_current_profile_change_are_not_authority(self):
        file = self.create()
        self.prepare()
        target = self.native_load()[0]['skillTarget']
        from company_agent.native_skill_learning import resolve
        forged = copy.deepcopy(target)
        forged['path'] = str(self.project / 'other/weekly-report/SKILL.md')
        with self.assertRaises(ValueError):
            resolve(self.root, 'weekly-report', forged)
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.project / 'other-profile')}):
            with self.assertRaises(ValueError):
                resolve(self.root, 'weekly-report', target)
        self.assertNotIn(learning.BEGIN, file.read_text(encoding='utf-8'))

    def test_removed_registration_and_recreated_same_bytes_cannot_redirect_rollback(self):
        file = self.create()
        turn = self.prepare()
        self.native_load()
        change = self.submit(turn)
        learned = file.read_bytes()
        registry = self.root / 'assets/registry.json'
        value = json.loads(registry.read_text(encoding='utf-8'))
        value['assets'][0]['factoryRegistrationId'] = 'f' * 32
        atomic_write_json(registry, value)
        self.assertEqual('blocked_conflict', learning.rollback_change(self.root, change['id'])['status'])
        self.assertEqual(learned, file.read_bytes())

    def test_native_rollback_preserves_any_newer_manual_changes(self):
        file = self.create()
        turn = self.prepare()
        self.native_load()
        change = self.submit(turn)
        atomic_write_text(file, file.read_text(encoding='utf-8') + '\nNew manual content.\n')
        before = file.read_bytes()
        self.assertEqual('blocked_conflict', learning.rollback_change(self.root, change['id'])['status'])
        self.assertEqual(before, file.read_bytes())

    def test_legacy_ledger_does_not_follow_same_name_native_replacement(self):
        legacy = self.f.skill()
        old = self.f.submit(self.f.turn(used=self.f.used(legacy), failure=1, verification='pass'), self.f.spec([self.f.lesson()]))['changes'][0]
        legacy.unlink()
        legacy.parent.rmdir()
        native = self.create()
        before = native.read_bytes()
        self.assertEqual('blocked_conflict', learning.rollback_change(self.root, old['id'])['status'])
        self.assertEqual(before, native.read_bytes())

    def test_native_yaml_frontmatter_requires_native_load_and_is_preserved(self):
        file = self.create()
        raw = file.read_text(encoding='utf-8').replace('---\n\n# Work', 'hooks:\n  PreToolUse:\n    - matcher: Read\n      hooks: []\ncontext: fork\nmodel: haiku\narguments: [scope]\n---\n\n# Work')
        atomic_write_text(file, raw)
        turn = self.prepare()
        self.assertEqual([], self.read(file))
        self.assertEqual(1, len(self.native_load()))
        change = self.submit(turn)
        self.assertEqual('active', change['status'])
        self.assertTrue(file.read_bytes().startswith(raw.encode('utf-8')))

    def test_global_safe_boundary_is_not_expanded(self):
        file = self.create()
        with self.assertRaisesRegex(ValueError, 'escaped personal state'):
            learning._safe(file, self.root)


if __name__ == '__main__':
    unittest.main()
