"""Native Skill storage uses isolated .smoke profiles, never a live Claude host."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))

from company_agent import cli
from company_agent.asset_factory import create_asset
from company_agent.native_skill_storage import config_root, locate_skill, registered_location
from company_agent.paths import atomic_write_json
from company_agent.resource_scope import selected_root
from company_agent.skill_lifecycle import inspect_skill, update_skill
from company_agent.skill_tool_dependencies import check_skill_dependencies


class NativeSkillStorageTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.smoke').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='native-skills-', dir=ROOT / '.smoke')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state, self.project, self.config = [self.base / name for name in ('state', 'project', 'profile')]
        self.project.mkdir()
        self.config.mkdir()
        self.env = patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.config), 'COMPANY_AGENT_SCOPE': 'User',
                                          'COMPANY_AGENT_CWD': str(self.project),
                                          'COMPANY_AGENT_REGISTRATIONS_ROOT': str(self.base / 'registrations')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.spec = {'type': 'skill', 'name': 'storage-example', 'description': 'A local workflow',
                     'instructions': 'Read the current inputs and summarize the result.'}

    def command(self, *arguments, state=None):
        out, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(error):
            code = cli.main(['asset', *arguments, '--state-root', str(state or self.state),
                             '--project-root', str(self.project)])
        return code, json.loads(out.getvalue() or error.getvalue())

    def create(self, scope='personal', **changes):
        source = self.base / 'input.json'
        source.write_text(json.dumps({**self.spec, **changes}), encoding='utf-8')
        return self.command('create', '--spec', str(source), '--storage-scope', scope)

    def native_file(self, scope='personal', name=None, content=None):
        root = self.config if scope == 'personal' else self.project / '.claude'
        file = root / 'skills' / (name or self.spec['name']) / 'SKILL.md'
        file.parent.mkdir(parents=True)
        file.write_text(content or '---\nname: storage-example\ndescription: Existing workflow\n---\n\nOld body.\n', encoding='utf-8')
        return file

    def snapshot(self):
        return {str(p.relative_to(self.base)): p.read_bytes() for p in self.base.rglob('*') if p.is_file()}

    def test_cli_personal_and_project_use_one_native_source_and_registry_pointer(self):
        settings = self.config / 'settings.json'
        settings.write_bytes(b'{"model":"unchanged","permissions":{"allow":[]}}')
        for scope, name, root in [('personal', 'personal-example', self.config),
                                  ('project', 'project-example', self.project / '.claude')]:
            with self.subTest(scope=scope):
                status, result = self.create(scope, name=name)
                self.assertEqual(0, status, result)
                expected = root / 'skills' / name / 'SKILL.md'
                self.assertEqual(str(expected), result['effectivePath'])
                self.assertEqual('native-' + scope, result['storageKind'])
                self.assertTrue(result['factoryOwned'])
                self.assertRegex(result['factoryRegistrationId'], r'^[a-f0-9]{32}$')
                self.assertEqual('/' + name, result['usage']['command'])
                self.assertEqual('not-verified', result['usage']['hostDiscovery'])
                self.assertIsNone(result['usage']['currentSessionReady'])
                self.assertIsNone(result['usage']['refreshRequired'])
                self.assertIn('/reload-skills', result['usage']['refreshIfMissing'])
                state = Path(result['stateRoot'])
                self.assertFalse((state / 'personal-root/.claude/skills' / name / 'SKILL.md').exists())
                record = json.loads((state / 'assets/registry.json').read_text(encoding='utf-8'))['assets'][0]
                self.assertEqual(str(expected), record['effectivePath'])
                self.assertEqual(result['sha256'], record['sha256'])
                self.assertEqual(result['factoryRegistrationId'], record['factoryRegistrationId'])
                self.assertEqual(0, self.command('inspect', '--name', name)[0])
        self.assertEqual(b'{"model":"unchanged","permissions":{"allow":[]}}', settings.read_bytes())
        self.assertFalse((self.project / '.claude/settings.json').exists())
        self.assertFalse((self.project / '.claude/settings.local.json').exists())
        self.assertFalse((self.config / 'plugins').exists())

    def test_existing_native_create_is_refused_but_update_preserves_all_native_metadata(self):
        header = ('---\nname: storage-example\ndescription: >-\n  Existing multiline\n  description\n'
                  'user-invocable: false\ndisable-model-invocation: true\ncontext: fork\n'
                  'hooks:\n  PreToolUse:\n    - matcher: Read\n      hooks: []\n---\n')
        file = self.native_file(content=header + '\nOld body.\n')
        before = file.read_bytes()
        status, failed = self.create()
        self.assertEqual(1, status, failed)
        self.assertEqual(before, file.read_bytes())
        self.assertFalse(self.state.exists())
        location = locate_skill(self.state, self.project, self.spec['name'])
        result = update_skill(location.state_root, self.spec['name'], 'New body.', location=location,
                              expected_sha256=hashlib.sha256(before).hexdigest())
        self.assertTrue(file.read_text(encoding='utf-8').startswith(header))
        self.assertIn('New body.', file.read_text(encoding='utf-8'))
        self.assertFalse(result['factoryOwned'])
        self.assertIsNone(result['factoryRegistrationId'])
        self.assertFalse(result['usage']['userInvocable'])
        self.assertIsNone(result['usage']['command'])
        location = locate_skill(self.state, self.project, self.spec['name'])
        result = update_skill(location.state_root, self.spec['name'], 'Third body.', location=location,
                              description='Updated description')
        text = file.read_text(encoding='utf-8')
        self.assertIn('description: "Updated description"', text)
        self.assertNotIn('  Existing multiline', text)
        self.assertIn('hooks:\n  PreToolUse:', text)
        self.assertIn('user-invocable: false', text)
        self.assertFalse(result['factoryOwned'])
        optional = self.native_file(name='optional-metadata', content='---\nuser-invocable: false\n---\nExisting body.\n')
        location = locate_skill(self.state, self.project, 'optional-metadata')
        result = update_skill(self.state, 'optional-metadata', 'Revised body.', location=location)
        self.assertTrue(result['ok'])
        self.assertTrue(optional.read_text(encoding='utf-8').startswith('---\nuser-invocable: false\n---\n'))

    def test_legacy_managed_cli_upsert_keeps_private_original_without_native_copy(self):
        managed = create_asset(self.spec, self.state)
        status, result = self.create(instructions='Updated private body.')
        self.assertEqual(0, status, result)
        self.assertEqual(str(managed / 'SKILL.md'), result['effectivePath'])
        self.assertEqual('managed', result['storageKind'])
        self.assertIsNone(result['usage']['nativeInvocation'])
        self.assertFalse((self.config / 'skills').exists())
        self.assertFalse((self.project / '.claude').exists())

    def test_registered_upsert_requires_unchanged_file_and_update_keeps_registration_identity(self):
        _, initial = self.create()
        identity = initial['factoryRegistrationId']
        file = Path(initial['effectivePath'])
        status, updated = self.create(instructions='Registered upsert body.')
        self.assertEqual(0, status)
        self.assertEqual(identity, updated['factoryRegistrationId'])
        file.write_text(file.read_text(encoding='utf-8') + '\nManual addition.\n', encoding='utf-8')
        manual = file.read_bytes()
        self.assertEqual(1, self.create(instructions='Do not overwrite manual addition.')[0])
        self.assertEqual(manual, file.read_bytes())
        body = self.base / 'new-body.md'
        body.write_text('Explicit merged body.\nManual addition.', encoding='utf-8')
        status, updated = self.command('update', '--name', self.spec['name'], '--instructions-file', str(body),
                                      '--expected-sha256', hashlib.sha256(manual).hexdigest())
        self.assertEqual(0, status)
        self.assertEqual(identity, updated['factoryRegistrationId'])
        file.unlink()
        file.parent.rmdir()
        status, recreated = self.create()
        self.assertEqual(0, status)
        self.assertNotEqual(identity, recreated['factoryRegistrationId'])

    def test_create_rejects_other_scope_native_or_private_without_shadow_copy(self):
        for kind in ('native', 'managed'):
            with self.subTest(kind=kind):
                name = kind + '-existing'
                if kind == 'native':
                    self.native_file('project', name, f'---\nname: {name}\ndescription: Existing\n---\nBody.\n')
                else:
                    create_asset({**self.spec, 'name': name}, selected_root(self.state, self.project, 'project'))
                status, result = self.create('personal', name=name)
                self.assertEqual(1, status, result)
                self.assertFalse((self.config / 'skills' / name).exists())

    def test_existing_same_name_in_multiple_scopes_needs_selection(self):
        self.native_file('project')
        self.native_file('personal')
        with self.assertRaisesRegex(ValueError, '모두'):
            locate_skill(self.state, self.project, self.spec['name'])
        selected = locate_skill(self.state, self.project, self.spec['name'], 'project')
        self.assertEqual('native-project', selected.storage_kind)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            locate_skill(self.state, self.project, self.spec['name'], 'project', for_create=True)
        self.assertEqual(before, self.snapshot())

    def test_legacy_commands_and_declared_name_collisions_are_preserved(self):
        cases = [('command', self.config / 'commands/storage-example.md'),
                 ('nested', self.project / '.claude/commands/group/storage-example.md'),
                 ('ancestor', self.base / '.claude/commands/storage-example.md'),
                 ('alias', self.config / 'skills/other-folder/SKILL.md')]
        for label, existing in cases:
            with self.subTest(kind=label):
                existing.parent.mkdir(parents=True, exist_ok=True)
                existing.write_text('---\nname: storage-example\ndescription: Preserved\n---\nOld command.\n', encoding='utf-8')
                original = existing.read_bytes()
                with self.assertRaisesRegex(ValueError, '겹칩니다'):
                    locate_skill(self.state, self.project, self.spec['name'], 'project', for_create=True)
                self.assertEqual(original, existing.read_bytes())
                existing.unlink()
        self.assertFalse(self.state.exists())

    def test_builtin_names_rejected_but_namespaced_company_skill_is_not_collision(self):
        for name in ('synced', 'synched', 'sync', 'help', 'reload-skills', 'anthropic-skills'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, '기본 명령'):
                locate_skill(self.state, self.project, name, 'personal', for_create=True)
        company = self.config / 'plugins/cache/company-agent/skills/storage-example/SKILL.md'
        company.parent.mkdir(parents=True)
        company.write_text('Company namespaced body', encoding='utf-8')
        self.assertEqual(0, self.create()[0])

    def test_custom_profile_and_default_home_are_resolved_without_settings_writes(self):
        home = self.base / 'fake-home'
        home.mkdir()
        with patch('pathlib.Path.home', return_value=home):
            self.assertEqual(self.config, config_root())
            self.assertEqual(0, self.create()[0])
            self.assertFalse((home / '.claude').exists())
            with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': ''}):
                self.assertEqual(home / '.claude', config_root())
                self.assertEqual(0, self.create(name='default-example')[0])
                self.assertTrue((home / '.claude/skills/default-example/SKILL.md').is_file())
        self.assertFalse(any(p.name.startswith('settings') for p in self.base.rglob('*')))

    def test_relative_profile_non_directory_and_bare_destination_fail_without_fallback(self):
        for value in ('relative-profile', str(self.base / 'not-folder')):
            if value != 'relative-profile':
                Path(value).write_text('Preserve', encoding='utf-8')
            with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': value}), self.assertRaises(ValueError):
                locate_skill(self.state, self.project, self.spec['name'], 'personal', for_create=True)
        bare = self.config / 'skills/storage-example'
        bare.mkdir(parents=True)
        (bare / 'notes.txt').write_text('Existing unrelated notes', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '덮어쓰지'):
            locate_skill(self.state, self.project, self.spec['name'], 'personal', for_create=True)
        self.assertFalse((bare / 'SKILL.md').exists())
        self.assertFalse(self.state.exists())

    def test_registry_cannot_redirect_to_arbitrary_path_or_another_profile(self):
        _, result = self.create()
        record_file = self.state / 'assets/registry.json'
        registry = json.loads(record_file.read_text(encoding='utf-8'))
        external = self.base / 'unrelated/SKILL.md'
        external.parent.mkdir()
        external.write_text('Private unrelated data', encoding='utf-8')
        registry['assets'][0].update(path=str(external.parent), effectivePath=str(external))
        atomic_write_json(record_file, registry)
        self.assertIsNone(registered_location(self.state, self.spec['name'], self.project))
        location = locate_skill(self.state, self.project, self.spec['name'])
        self.assertEqual(result['effectivePath'], str(location.file))
        self.assertFalse(location.factory_owned)
        self.assertFalse(inspect_skill(self.state, self.spec['name'], location=location)['factoryOwned'])
        update_skill(self.state, self.spec['name'], 'Update actual native file.', location=location)
        self.assertEqual('Private unrelated data', external.read_text(encoding='utf-8'))
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.base / 'another-profile')}):
            self.assertIsNone(registered_location(self.state, self.spec['name'], self.project))
            with self.assertRaisesRegex(ValueError, '찾지 못했습니다'):
                locate_skill(self.state, self.project, self.spec['name'])

    def test_project_dependency_readback_uses_already_selected_state_without_rehashing(self):
        state = selected_root(self.state, self.project, 'project')
        frozen = self.base / 'frozen-server.py'
        frozen.write_text('# No execution in this test', encoding='utf-8')
        desired = {'command': 'unused', 'args': [str(frozen)]}
        binding = {'server': 'demo-server', 'tools': ['lookup'], 'assetHash': 'a', 'schemaHash': 'b'}
        atomic_write_json(state / 'mcp/servers/demo-server/asset.json', {})
        atomic_write_json(state / 'mcp/registry.json', {'mcpServers': {'demo-server': desired}})
        with patch('company_agent.skill_tool_dependencies._binding', return_value=binding), \
             patch('company_agent.mcp_execution.execution_definition', return_value=desired), \
             patch('company_agent.native_mcp.registration_status', return_value='registered'):
            code, created = self.create('project', tool_dependencies=[{'server': 'demo-server', 'tools': ['lookup']}])
            self.assertEqual(0, code, created)
            location = registered_location(state, self.spec['name'], self.project)
            self.assertEqual(state, location.state_root)
            code, inspected = self.command('inspect', '--name', self.spec['name'], state=state)
            self.assertEqual(0, code, inspected)
            self.assertEqual(created['factoryRegistrationId'], inspected['factoryRegistrationId'])
            self.assertEqual(str(state), inspected['stateRoot'])
            self.assertTrue(check_skill_dependencies(state, self.spec['name'], self.project)['ok'])
            self.assertEqual(0, self.command('check-skill', '--name', self.spec['name'], state=state)[0])
            updated = update_skill(state, self.spec['name'], 'Use the bound tool.', location=location)
            self.assertTrue(updated['ok'])
            self.assertEqual(created['factoryRegistrationId'], updated['factoryRegistrationId'])
            text = location.file.read_text(encoding='utf-8')
            self.assertEqual(1, text.count('## 연결 도구 확인'))
            self.assertIn(state.as_posix(), text)
            self.assertTrue((location.directory / 'tool-dependencies.json').is_file())
            self.assertFalse((state / 'project-scopes').exists())

    def test_update_refuses_changed_hash_and_reparse_descendant_before_snapshot(self):
        _, result = self.create()
        file = Path(result['effectivePath'])
        child = file.parent / 'scripts'
        child.mkdir()
        location = locate_skill(self.state, self.project, self.spec['name'])
        before = file.read_bytes()
        with self.assertRaisesRegex(ValueError, '조회 후 변경'):
            update_skill(self.state, self.spec['name'], 'Never written.', location=location, expected_sha256='stale')
        from company_agent.native_skill_storage import _no_reparse
        def reject_descendant(path):
            if path == child:
                raise ValueError('Reparse descendant is not followed')
            return _no_reparse(path)
        with patch('company_agent.native_skill_storage._no_reparse', side_effect=reject_descendant), \
             patch('company_agent.asset_factory._snapshot_existing') as snapshot:
            with self.assertRaisesRegex(ValueError, 'Reparse descendant'):
                update_skill(self.state, self.spec['name'], 'Never written.', location=location)
            snapshot.assert_not_called()
        self.assertEqual(before, file.read_bytes())

    def test_oversized_skill_is_rejected_before_unbounded_read(self):
        self.native_file(content='x' * 262145)
        with self.assertRaisesRegex(ValueError, 'bounded'):
            locate_skill(self.state, self.project, self.spec['name'])
        code, result = self.create(name='oversized-new', instructions='x' * 262145)
        self.assertEqual(1, code, result)
        self.assertFalse((self.config / 'skills/oversized-new').exists())


if __name__ == '__main__':
    unittest.main()
