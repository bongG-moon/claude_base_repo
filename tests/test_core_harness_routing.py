"""Core payloads run without bundled business engines or image routing."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'company-agent-plugin' / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from company_agent import core_profile, cli, execution_contract, native_runtime, state
from company_agent.paths import atomic_write_json, atomic_write_text
from company_agent.skill_workflow import observe, preflight
import native_entry
import read_hook


OPTIONAL_MODULES = ('business', 'business_artifacts', 'business_files', 'excel_pipeline_command',
                    'ppt_workflow', 'vision_routing', 'vision_dispatch', 'vision_handoff', 'vision_settings')


class CoreHarnessRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='core-harness-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project, self.plugin, self.claude, self.state = [self.root / name for name in
                                                           ('project', 'plugin', 'claude', 'state')]
        self.project.mkdir()
        self.marker = self.plugin / 'resources/core-install.json'
        atomic_write_json(self.marker, {'schemaVersion': 1, 'profile': 'personal-harness'})
        atomic_write_json(self.plugin / '.claude-plugin/plugin.json', {'name': 'company-agent', 'version': 'test'})
        self.patch = patch.object(core_profile, '_MARKER', self.marker)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        core_profile.is_core_install.cache_clear()
        self.addCleanup(core_profile.is_core_install.cache_clear)
        self.env = patch.dict(os.environ, {'COMPANY_AGENT_USER_STATE': str(self.state),
            'CLAUDE_CONFIG_DIR': str(self.claude), 'COMPANY_AGENT_KNOWLEDGE_BASE': '',
            'COMPANY_AGENT_SCOPE': 'User', 'COMPANY_AGENT_PYTHON': sys.executable,
            'COMPANY_AGENT_CWD': str(self.project),
            'COMPANY_AGENT_REGISTRATIONS_ROOT': str(self.root / 'registrations')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.missing = patch.dict(sys.modules, {'company_agent.' + name: None for name in OPTIONAL_MODULES})
        self.missing.start()
        self.addCleanup(self.missing.stop)
        self.sid = 'core-test'

    def runtime(self, prompt='HTML 보고서 만들어줘'):
        state.begin_turn(self.sid, 'MEDIUM', False, (), self.state)
        return json.loads(native_runtime.runtime_context(self.plugin, self.project, prompt,
                          session_id=self.sid))['company_agent_runtime']

    def hook(self, event, **fields):
        output = io.StringIO()
        payload = {'session_id': self.sid, 'cwd': str(self.project), **fields}
        with patch.object(sys, 'argv', ['native_entry.py', '--event', event]), \
             patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))), \
             patch.object(native_entry, 'configure_runtime', return_value=True), \
             contextlib.redirect_stdout(output):
            self.assertEqual(0, native_entry.main())
        return json.loads(output.getvalue())

    def command(self, suffix):
        return shlex.quote(sys.executable) + ' -B ' + shlex.quote(str(SCRIPTS / 'harness_cli.py')) + ' ' + suffix

    def test_profile_requires_explicit_valid_marker_and_caches_once(self):
        self.assertTrue(core_profile.is_core_install())
        self.marker.unlink()
        self.assertTrue(core_profile.is_core_install())
        core_profile.is_core_install.cache_clear()
        self.assertFalse(core_profile.is_core_install())
        for value in ({'profile': 'full'}, [], 'personal-harness'):
            self.marker.write_text(json.dumps(value), encoding='utf-8')
            core_profile.is_core_install.cache_clear()
            self.assertFalse(core_profile.is_core_install())

    def test_core_parser_exposes_only_personal_skill_asset_commands(self):
        parser = cli.build_parser()
        sub = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
        self.assertNotIn('business', sub.choices)
        self.assertNotIn('vision', sub.choices)
        self.assertTrue({'memory', 'knowledge', 'learning', 'context', 'skill', 'harness'} <= sub.choices.keys())
        assets = next(action for action in sub.choices['asset']._actions if isinstance(action, argparse._SubParsersAction))
        self.assertEqual({'create', 'inspect', 'update', 'validate', 'check-skill'}, set(assets.choices))

    def test_runtime_and_workers_do_not_inject_missing_business_or_vision_workflows(self):
        runtime = self.runtime()
        self.assertNotIn('visionRouting', runtime)
        text = json.dumps(runtime, ensure_ascii=False)
        for absent in ('workFile', 'company-agent:vision-worker', 'company-agent:html-report', 'karpathy-guidelines'):
            self.assertNotIn(absent, text)
        self.assertIn('metadataCommand 뒤에 doctor', runtime['instructions'])
        result = native_runtime.worker_runtime_input(self.plugin, self.project, {'session_id': self.sid,
            'tool_name': 'Agent', 'tool_input': {'subagent_type': 'company-agent:medium-worker', 'prompt': '이미지를 확인해줘'}})
        worker = result['hookSpecificOutput']['updatedInput']['prompt']
        self.assertNotIn('visionRouting', worker)
        self.assertNotIn('workFile', worker)

    def test_empty_functional_catalogue_does_not_deny_tools_or_create_stop_debt(self):
        self.runtime()
        result = preflight(self.state, self.project, {'session_id': self.sid, 'tool_name': 'Write',
                                                     'tool_input': {'file_path': str(self.project / 'result.html')}})
        self.assertNotEqual('deny', result.get('hookSpecificOutput', {}).get('permissionDecision'))
        self.assertEqual({}, state.stop_decision({'session_id': self.sid}, self.state))
        self.assertEqual(0, state.load_session(self.sid, self.state)['mutationCount'])

    def test_core_guidance_never_prescribes_uninstalled_business_capabilities(self):
        prompt = 'Outlook 계정과 DB 권한을 설명해줘'
        runtime = self.runtime(prompt)
        texts = [runtime['instructions'], native_runtime._prompt_instructions(runtime)]
        self.assertFalse(runtime.get('taskReminders'))
        # Exercise the full, condensed and minimal budgets, as well as the
        # prompt guidance reused on a later turn, without changing tool policy.
        for budget in (100_000, 6_000, 3_500):
            with patch.object(native_runtime, 'MAX_RUNTIME_BASE_CHARS', budget), \
                 patch.object(native_runtime, 'MAX_RUNTIME_CONTEXT_CHARS', budget + 10_000):
                output = native_runtime.runtime_context(self.plugin, self.project, prompt, session_id=self.sid)
                texts.append(json.loads(output)['company_agent_runtime']['instructions'])
        route = '{"company_agent_route":{"tier":"MEDIUM"}}'
        encoded = json.dumps({'company_agent_runtime': runtime}, ensure_ascii=False)
        texts.append(native_runtime.task_prompt_context(route, encoded))
        texts.append(native_runtime.task_prompt_context(route, encoded))
        for text in texts:
            for absent in ('Outlook', 'DB SELECT', 'capabilities confirms', 'business doctor',
                           'workFile', 'vision-worker', 'html-choices', 'ppt-capabilities'):
                self.assertNotIn(absent, text)

    def test_individually_installed_native_skill_keeps_actual_load_and_reuse(self):
        file = self.claude / 'skills/my-report/SKILL.md'
        atomic_write_text(file, '---\nname: my-report\ndescription: HTML 보고서 작성\n---\n사용자 개인 절차\n')
        runtime = self.runtime('/my-report HTML 보고서 만들어줘')
        self.assertIn('my-report', json.dumps(runtime, ensure_ascii=False))
        self.assertEqual({}, preflight(self.state, self.project, {'session_id': self.sid, 'tool_name': 'Bash',
                                                                'tool_input': {'command': self.command('doctor')}}))
        observe(self.state, self.project, {'session_id': self.sid, 'hook_event_name': 'PostToolUse',
            'tool_name': 'Skill', 'tool_input': {'skill': 'my-report'}, 'tool_response': {'success': True}})
        selected = state.load_session(self.sid, self.state)['skillWorkflow']['selected']
        self.assertEqual('my-report', selected['name'])
        self.assertEqual(str(file), selected['path'])
        self.assertEqual({}, preflight(self.state, self.project, {'session_id': self.sid, 'tool_name': 'Write',
                                                                'tool_input': {'file_path': str(self.project / 'result.html')}}))
        self.assertEqual('사용자 개인 절차', file.read_text(encoding='utf-8').splitlines()[-1])

    def test_image_read_and_native_agents_remain_under_native_permissions(self):
        for suffix in ('.png', '.pdf', '.txt'):
            self.assertEqual({}, self.hook('PreToolUse', tool_name='Read',
                                          tool_input={'file_path': str(self.project / ('input' + suffix))}))
        self.assertEqual({}, self.hook('PreToolUse', tool_name='Agent', tool_input={
            'subagent_type': 'personal-vision-worker', 'prompt': '확인', 'model': 'sonnet'}))
        with patch.object(sys, 'stdin', io.StringIO(json.dumps({'tool_name': 'Read',
                  'tool_input': {'file_path': str(self.project / 'image.png')}}))), \
             patch.object(read_hook, 'fallback', side_effect=AssertionError('image must not invoke legacy launcher')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, read_hook.main())
        self.assertEqual({}, json.loads(output.getvalue()))

    def test_session_start_and_prompt_work_with_vision_modules_absent(self):
        self.assertIn('hookSpecificOutput', self.hook('SessionStart', source='startup'))
        result = self.hook('UserPromptSubmit', prompt='안녕하세요')
        self.assertIn('hookSpecificOutput', result)
        self.assertNotIn('visionRouting', json.dumps(result))
        self.assertEqual({}, self.hook('Stop'))

    def test_core_metadata_permission_is_exact_doctor_and_never_business_or_asset_write(self):
        for suffix, allowed in (('doctor', True), ('doctor --help', True), ('business doctor', False),
                                ('vision status', False), ('asset create --spec input.json', False)):
            command = self.command(suffix)
            result = execution_contract.safe_permission({'hook_event_name': 'PermissionRequest',
                'tool_name': 'Bash', 'tool_input': {'command': command}}, self.state)
            self.assertEqual({'behavior': 'allow'} if allowed else None, result, suffix)
        self.assertEqual('read_only', execution_contract.classify_command(self.command('doctor')))
        self.assertEqual('unknown', execution_contract.classify_command(self.command('business excel-analyze --inspect --file input.xlsx')))

    def test_core_choice_metadata_cannot_import_engines_or_suspend_completion(self):
        for name, function in (('html', state._is_html_choices_spec_write), ('ppt', state._is_ppt_choices_spec_write)):
            self.assertFalse(function('Write', {'file_path': str(self.state / 'tmp' / (name + '-choices-test.json')),
                                               'content': '{}'}, self.state))
        self.assertFalse(state._html_choice_wait({}, self.state))

    def test_non_skill_asset_creation_is_rejected_and_doctor_creates_no_profile(self):
        spec = self.root / 'asset.json'
        spec.write_text(json.dumps({'type': 'mcp', 'name': 'new-tool'}), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
            code = cli.main(['asset', 'create', '--spec', str(spec), '--storage-scope', 'personal',
                             '--project-root', str(self.project)])
        self.assertEqual(1, code)
        self.assertIn('asset-factory', errors.getvalue())
        self.assertFalse(self.state.exists())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            cli.main(['doctor'])
        self.assertIn('checks', json.loads(output.getvalue()))
        self.assertFalse(self.state.exists())

    def test_personal_skill_lifecycle_preserves_existing_settings_and_mcp(self):
        settings, registry = self.claude / 'settings.json', self.state / 'mcp/registry.json'
        atomic_write_json(settings, {'model': 'existing-model', 'permissions': {'allow': []},
                                    'mcpServers': {'existing': {'command': 'existing-server'}}})
        atomic_write_json(registry, {'mcpServers': {'existing': {'command': 'existing-server'}}})
        originals = {file: file.read_bytes() for file in (settings, registry)}
        spec = self.root / 'skill.json'
        atomic_write_json(spec, {'type': 'skill', 'name': 'personal-procedure', 'description': '입력 자료를 확인하는 개인 절차',
                                'instructions': '입력 자료를 확인하고 출처를 붙여 결과를 요약합니다.'})
        def run(*arguments):
            with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
                code = cli.main(list(arguments))
            self.assertEqual(0, code, output.getvalue() + errors.getvalue())
            return json.loads(output.getvalue())
        scope = ['--storage-scope', 'personal', '--project-root', str(self.project)]
        created = run('asset', 'create', '--spec', str(spec), *scope)
        expected = self.claude / 'skills/personal-procedure/SKILL.md'
        self.assertEqual(str(expected), created['effectivePath'])
        inspected = run('asset', 'inspect', '--name', 'personal-procedure', *scope)
        body = self.root / 'instructions.md'
        body.write_text('입력 자료의 출처와 범위를 확인하고 최종 결과를 요약합니다.', encoding='utf-8')
        updated = run('asset', 'update', '--name', 'personal-procedure', '--instructions-file', str(body),
                     '--expected-sha256', inspected['sha256'], *scope)
        self.assertEqual(str(expected), updated['effectivePath'])
        self.assertTrue(run('asset', 'validate', str(expected.parent))['ok'])
        self.assertTrue(run('asset', 'check-skill', '--name', 'personal-procedure', '--project-root', str(self.project))['ok'])
        native_runtime.session_start(self.plugin, self.project, session_id=self.sid, source='startup')
        for file, original in originals.items():
            self.assertEqual(original, file.read_bytes())


if __name__ == '__main__':
    unittest.main()
