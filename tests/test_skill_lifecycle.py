"""Skill changes stay in isolated .smoke state; no live Claude, model or install."""
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
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))

from company_agent.asset_factory import create_asset
from company_agent.cli import build_parser
from company_agent.frontmatter import parse_frontmatter_text
from company_agent.resource_scope import selected_root
from company_agent.skill_catalog import refresh_skill_catalog
from company_agent.skill_lifecycle import OWNED_FILES, inspect_skill, resolve_existing_skill, update_skill
from company_agent.skill_registry import inventory_skills


class SkillLifecycleTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.smoke').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='skill-lifecycle-', dir=ROOT / '.smoke')
        self.base = Path(self.tmp.name)
        self.state, self.project, self.config = [self.base / item for item in ('state', 'project', 'config')]
        self.project.mkdir()
        self.config.mkdir()
        self.env = patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.config),
                                          'COMPANY_AGENT_SCOPE': 'User',
                                          'COMPANY_AGENT_CWD': str(self.project)})
        self.env.start()
        self.spec = {'type': 'skill', 'name': 'mumu-pocket-launch', 'description': 'Launch workflow',
                     'instructions': 'Read the current project before starting.'}

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def command(self, *arguments):
        parser = build_parser()
        args = parser.parse_args(['asset', *arguments, '--state-root', str(self.state),
                                  '--project-root', str(self.project)])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = args.func(args)
        return status, json.loads(output.getvalue())

    def test_create_inspect_update_preserves_scope_and_next_catalog_reads_new_body(self):
        source = self.base / 'authoring-spec.json'
        source.write_text(json.dumps(self.spec), encoding='utf-8')
        status, created = self.command('create', '--spec', str(source), '--storage-scope', 'project')
        self.assertEqual(0, status)
        self.assertEqual('project', created['storageScope'])
        effective = Path(created['effectivePath'])
        self.assertEqual(self.project / '.claude/skills/mumu-pocket-launch/SKILL.md', effective)
        self.assertFalse((Path(created['stateRoot']) / 'personal-root/.claude/skills/mumu-pocket-launch/SKILL.md').exists())
        self.assertFalse(created['bodyIncluded'])
        self.assertEqual(str(source), created['authoringSource']['path'])
        self.assertFalse(created['authoringSource']['synchronized'])
        self.assertEqual('mumu-pocket-launch', created['usage']['nativeInvocation'])
        self.assertEqual('/mumu-pocket-launch', created['usage']['command'])
        self.assertEqual('not-verified', created['usage']['hostDiscovery'])
        inventory = inventory_skills(self.state, project_root=self.project, claude_root=self.config)
        first = refresh_skill_catalog(self.state, self.project, inventory)
        source.write_text(json.dumps({**self.spec, 'instructions': 'Not synchronized'}), encoding='utf-8')
        _, inspected = self.command('inspect', '--name', self.spec['name'])
        self.assertEqual(created['sha256'], inspected['sha256'])
        body = self.base / 'revised-body.md'
        body.write_text('Check the local launch result and report it.', encoding='utf-8')
        _, updated = self.command('update', '--name', self.spec['name'], '--instructions-file', str(body),
                                  '--expected-sha256', inspected['sha256'])
        self.assertEqual('updated', updated['operation'])
        self.assertEqual('project', updated['storageScope'])
        self.assertEqual(str(effective), updated['effectivePath'])
        self.assertNotEqual(inspected['sha256'], updated['sha256'])
        self.assertIn(body.read_text(encoding='utf-8'), effective.read_text(encoding='utf-8'))
        self.assertTrue((self.project / '.claude').exists())
        self.assertFalse((self.config / 'skills').exists())
        self.assertFalse(updated['activationRequired'])
        self.assertEqual('not-tested', updated['validation']['execution'])
        second = refresh_skill_catalog(self.state, self.project,
                                       inventory_skills(self.state, project_root=self.project, claude_root=self.config))
        self.assertNotEqual(first['revision'], second['revision'])

    def test_same_name_in_both_scopes_requires_explicit_selection_and_writes_nothing(self):
        create_asset(self.spec, self.state)
        project_state = selected_root(self.state, self.project, 'project')
        create_asset({**self.spec, 'instructions': 'Project instructions'}, project_state)
        before = inspect_skill(self.state, self.spec['name'])['sha256']
        with self.assertRaisesRegex(ValueError, '모두'):
            resolve_existing_skill(self.state, self.project, self.spec['name'])
        self.assertEqual(before, inspect_skill(self.state, self.spec['name'])['sha256'])
        self.assertEqual((project_state, 'project'),
                         resolve_existing_skill(self.state, self.project, self.spec['name'], 'project'))

    def test_missing_update_does_not_create_or_guess_an_asset(self):
        with self.assertRaisesRegex(ValueError, '찾지 못했습니다'):
            resolve_existing_skill(self.state, self.project, self.spec['name'])
        self.assertFalse(self.state.exists())

    def test_read_only_inspect_and_conflicting_hash_preserve_existing_files(self):
        destination = create_asset(self.spec, self.state)
        file = destination / 'SKILL.md'
        before = {str(path.relative_to(self.state)): (path.stat().st_mtime_ns, path.read_bytes())
                  for path in self.state.rglob('*') if path.is_file()}
        result = inspect_skill(self.state, self.spec['name'])
        self.assertEqual('structure-valid', result['validation']['status'])
        with self.assertRaisesRegex(ValueError, '조회 후 변경'):
            update_skill(self.state, self.spec['name'], 'Changed', expected_sha256='old')
        after = {str(path.relative_to(self.state)): (path.stat().st_mtime_ns, path.read_bytes())
                 for path in self.state.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(file.is_file())

    def test_update_preserves_additional_frontmatter_references_and_knowledge(self):
        destination = create_asset({**self.spec, 'knowledge_dependencies': ['local.term'],
                                    'references': ['Existing reference']}, self.state)
        file = destination / 'SKILL.md'
        file.write_text(file.read_text(encoding='utf-8').replace('---\n', '---\nlicense: Internal\n', 1), encoding='utf-8')
        previous = inspect_skill(self.state, self.spec['name'])
        result = update_skill(self.state, self.spec['name'], 'Revised only.', expected_sha256=previous['sha256'])
        metadata, body = parse_frontmatter_text(file.read_text(encoding='utf-8'))
        self.assertEqual('Internal', metadata['license'])
        self.assertEqual(self.spec['name'], metadata['name'])
        self.assertEqual(self.spec['description'], metadata['description'])
        self.assertEqual('Revised only.\n', body)
        self.assertTrue((destination / 'references/reference-1.md').is_file())
        registry = json.loads((self.state / 'assets/registry.json').read_text(encoding='utf-8'))
        self.assertEqual(['local.term'], registry['assets'][0]['knowledgeDependencies'])
        self.assertEqual(str(file), result['effectivePath'])

    def test_owned_obsolete_references_are_backed_up_and_removed_without_unowned_files(self):
        destination = create_asset({**self.spec, 'references': ['Keep', 'Remove']}, self.state)
        unowned = destination / 'references/reference-99.md'
        unowned.write_text('User-owned evidence', encoding='utf-8')
        create_asset({**self.spec, 'references': ['Keep']}, self.state)
        self.assertFalse((destination / 'references/reference-2.md').exists())
        self.assertEqual('User-owned evidence', unowned.read_text(encoding='utf-8'))
        report = inspect_skill(self.state, self.spec['name'])['lastReferenceUpdate']
        self.assertEqual(['references/reference-2.md'], report['removedReferences'])
        self.assertEqual('Remove\n', (Path(report['backupPath']) / 'references/reference-2.md').read_text(encoding='utf-8'))

    def test_manually_changed_obsolete_reference_is_preserved_and_reported(self):
        destination = create_asset({**self.spec, 'references': ['Keep', 'Old']}, self.state)
        edited = destination / 'references/reference-2.md'
        edited.write_text('Manually revised', encoding='utf-8')
        create_asset({**self.spec, 'references': ['Keep']}, self.state)
        self.assertEqual('Manually revised', edited.read_text(encoding='utf-8'))
        self.assertEqual(['references/reference-2.md'],
                         inspect_skill(self.state, self.spec['name'])['lastReferenceUpdate']['preservedReferences'])

    def test_old_untracked_references_are_not_deleted_and_omitted_references_stay(self):
        destination = create_asset({**self.spec, 'references': ['Legacy one', 'Legacy two']}, self.state)
        (destination / OWNED_FILES).unlink()
        create_asset({**self.spec, 'references': ['Legacy one']}, self.state)
        self.assertTrue((destination / 'references/reference-2.md').is_file())
        create_asset(self.spec, self.state)
        self.assertTrue((destination / 'references/reference-1.md').is_file())
        create_asset({**self.spec, 'references': []}, self.state)
        self.assertFalse((destination / 'references/reference-1.md').exists())
        self.assertTrue((destination / 'references/reference-2.md').is_file())

    def test_invalid_reference_replacement_fails_before_mutating_existing_skill(self):
        destination = create_asset(self.spec, self.state)
        before = (destination / 'SKILL.md').read_bytes()
        with self.assertRaisesRegex(ValueError, 'array of text'):
            create_asset({**self.spec, 'instructions': 'Should not save', 'references': [{'bad': 'shape'}]}, self.state)
        self.assertEqual(before, (destination / 'SKILL.md').read_bytes())

    def test_dependency_guidance_is_not_duplicated_by_an_ordinary_update(self):
        prefix = '## 연결 도구 확인\n\nGenerated dependency guidance.\n\n'
        with patch('company_agent.skill_tool_dependencies.dependency_instructions', return_value=prefix):
            destination = create_asset(self.spec, self.state)
            _, body = parse_frontmatter_text((destination / 'SKILL.md').read_text(encoding='utf-8'))
            update_skill(self.state, self.spec['name'], body + '\nNew instruction.')
        final = (destination / 'SKILL.md').read_text(encoding='utf-8')
        self.assertEqual(1, final.count('Generated dependency guidance.'))

    def test_native_only_body_is_not_advertised_as_ready_for_file_execution(self):
        create_asset({**self.spec, 'instructions': 'Use $ARGUMENTS to launch.'}, self.state)
        result = inspect_skill(self.state, self.spec['name'])
        self.assertEqual('structure-valid', result['validation']['status'])
        self.assertTrue(result['usage']['nativeRequired'])
        self.assertFalse(result['usage']['ready'])
        self.assertEqual('native-invocation-required', result['usage']['mode'])

    def test_concurrent_edit_during_update_preparation_is_not_overwritten(self):
        from company_agent import asset_factory
        destination = create_asset(self.spec, self.state)
        snapshot = asset_factory._snapshot_existing

        def edit_after_snapshot(*arguments):
            result = snapshot(*arguments)
            file = destination / 'SKILL.md'
            file.write_text(file.read_text(encoding='utf-8') + '\nConcurrent user change.\n', encoding='utf-8')
            return result

        with patch.object(asset_factory, '_snapshot_existing', side_effect=edit_after_snapshot):
            with self.assertRaisesRegex(ValueError, '수정 준비 중 변경'):
                update_skill(self.state, self.spec['name'], 'Do not overwrite concurrent edits.')
        final = (destination / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('Concurrent user change.', final)
        self.assertNotIn('Do not overwrite concurrent edits.', final)

    def test_inspect_does_not_create_stop_work_or_grant_permission_and_update_stays_a_write(self):
        from company_agent.execution_contract import classify_command, safe_permission
        from company_agent.state import begin_turn, record_activity, stop_decision
        cli = f'"{sys.executable}" -B "{ROOT / "company-agent-plugin/scripts/harness_cli.py"}"'
        command = (f'{cli} asset inspect --name {self.spec["name"]} --state-root "{self.state}" '
                   f'--project-root "{self.project}" --storage-scope project')
        self.assertEqual('read_only', classify_command(command))
        permission = {'hook_event_name': 'PermissionRequest', 'tool_name': 'Bash',
                      'tool_input': {'command': command}}
        self.assertIsNone(safe_permission(permission, self.state))
        for extra in (' --output changed.json', '; echo changed', ' --name other'):
            self.assertEqual('unknown', classify_command(command + extra))
        self.assertEqual('unknown', classify_command(command.replace('--storage-scope project', '--storage-scope company')))
        self.assertEqual('unknown', classify_command(command.replace('asset inspect', 'asset update')))
        begin_turn('skill-inspect', 'SMALL', False, [], self.state)
        event = {'session_id': 'skill-inspect', 'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                 'tool_input': {'command': command}, 'tool_response': {'stdout': '{"bodyIncluded":false}'}}
        self.assertEqual(0, record_activity(event, self.state)['mutationCount'])
        self.assertEqual({}, stop_decision({'session_id': 'skill-inspect'}, self.state))
        record_activity({'session_id': 'skill-inspect', 'tool_name': 'Write',
                         'tool_input': {'file_path': str(self.project / 'earlier.md')}}, self.state)
        self.assertEqual(1, record_activity(event, self.state)['mutationCount'])
        self.assertEqual('block', stop_decision({'session_id': 'skill-inspect'}, self.state)['decision'])

    def test_update_rejects_assetspec_json_without_touching_the_live_body(self):
        destination = create_asset(self.spec, self.state)
        before = (destination / 'SKILL.md').read_bytes()
        with self.assertRaisesRegex(ValueError, 'AssetSpec JSON 대신'):
            update_skill(self.state, self.spec['name'], json.dumps(self.spec))
        self.assertEqual(before, (destination / 'SKILL.md').read_bytes())
        # A JSON example with a non-AssetSpec shape remains ordinary authored text.
        self.assertTrue(update_skill(self.state, self.spec['name'], '{"type": ["row"], "example": 1}')['ok'])

    def test_reference_changed_after_snapshot_blocks_before_body_or_reference_write(self):
        from company_agent import asset_factory
        for existed in (False, True):
            with self.subTest(existed=existed):
                isolated = self.base / ('existing-reference' if existed else 'new-reference')
                destination = create_asset({**self.spec, **({'references': ['Before']} if existed else {})}, isolated)
                before = (destination / 'SKILL.md').read_bytes()
                snapshot = asset_factory._snapshot_existing

                def concurrent_reference(*arguments):
                    result = snapshot(*arguments)
                    target = destination / 'references/reference-1.md'
                    target.parent.mkdir(exist_ok=True)
                    target.write_text('Concurrent reference edit', encoding='utf-8')
                    return result

                with patch.object(asset_factory, '_snapshot_existing', side_effect=concurrent_reference):
                    with self.assertRaisesRegex(ValueError, '참조 파일이 수정 준비 중 변경'):
                        create_asset({**self.spec, 'instructions': 'Should not save', 'references': ['Replace']}, isolated)
                self.assertEqual(before, (destination / 'SKILL.md').read_bytes())
                self.assertEqual('Concurrent reference edit', (destination / 'references/reference-1.md').read_text(encoding='utf-8'))

    def test_registry_failure_reports_partial_update_with_real_backup_and_changed_body(self):
        from company_agent import asset_factory
        destination = create_asset(self.spec, self.state)
        before = (destination / 'SKILL.md').read_bytes()
        with patch.object(asset_factory, '_record_asset', side_effect=OSError('simulated registry denial')):
            result = update_skill(self.state, self.spec['name'], 'The updated body was saved.')
        self.assertFalse(result['ok'])
        self.assertEqual('partial', result['status'])
        self.assertTrue(result['written'])
        self.assertEqual('not-confirmed', result['registryStatus'])
        self.assertEqual(str(destination / 'SKILL.md'), result['effectivePath'])
        self.assertIn('The updated body was saved.', (destination / 'SKILL.md').read_text(encoding='utf-8'))
        self.assertEqual(before, (Path(result['backupPath']) / 'SKILL.md').read_bytes())
        self.assertIn('backupPath', result['recovery'])

    def test_create_cli_partial_save_is_not_reported_as_unchanged_failure(self):
        source = self.base / 'create-spec.json'
        source.write_text(json.dumps(self.spec), encoding='utf-8')
        with patch('company_agent.asset_factory._record_asset', side_effect=OSError('simulated ledger denial')):
            code, result = self.command('create', '--spec', str(source), '--storage-scope', 'project')
        self.assertEqual(1, code)
        self.assertEqual('partial', result['status'])
        self.assertTrue(result['written'])
        self.assertIsNone(result['backupPath'])
        self.assertTrue(Path(result['effectivePath']).is_file())

    def test_create_cli_returns_failure_if_readback_structure_is_invalid(self):
        source = self.base / 'create-spec.json'
        source.write_text(json.dumps(self.spec), encoding='utf-8')
        with patch('company_agent.skill_lifecycle.inspect_skill', return_value={'ok': False, 'validation': {'status': 'structure-invalid'}}):
            code, result = self.command('create', '--spec', str(source), '--storage-scope', 'project')
        self.assertEqual(1, code)
        self.assertIs(result['ok'], False)

    def test_update_cli_partial_result_preserves_boolean_types_and_backup_evidence(self):
        create_asset(self.spec, self.state)
        body = self.base / 'revised-body.md'
        body.write_text('Saved body before simulated registry failure.', encoding='utf-8')
        with patch('company_agent.asset_factory._record_asset', side_effect=OSError('simulated registry denial')):
            code, result = self.command('update', '--name', self.spec['name'], '--instructions-file', str(body))
        self.assertEqual(1, code)
        self.assertIs(result['ok'], False)
        self.assertIs(result['written'], True)
        self.assertIs(result['bodyIncluded'], False)
        self.assertEqual('partial-update', result['operation'])
        self.assertTrue((Path(result['backupPath']) / 'SKILL.md').is_file())


if __name__ == '__main__':
    unittest.main()
