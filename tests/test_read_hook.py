"""Read fast path and real launcher parity, without opening files or a model."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_native_runtime as fixtures

sys.path.insert(0, str(fixtures.SCRIPTS))
import read_hook
from company_agent import vision_routing as vision


def payload(path='C:/가상 자료/report.md', **values):
    return {'tool_name': 'Read', 'tool_input': {'file_path': path}, **values}


class ReadHookTests(unittest.TestCase):
    def run_hook(self, value, *, raw=False, model=vision.VISION_MODEL, fallback_code=0):
        text = value if raw else json.dumps(value, ensure_ascii=False)
        out = io.StringIO()
        with patch.dict(os.environ, {'ANTHROPIC_CUSTOM_MODEL_OPTION': model}), \
                patch.object(sys, 'stdin', io.StringIO(text)), \
                contextlib.redirect_stdout(out), \
                patch.object(read_hook, 'fallback', return_value=fallback_code) as fallback:
            code = read_hook.main()
        return code, out.getvalue(), fallback

    def test_ordinary_read_no_subprocess_settings_or_session(self):
        for model in ('', 'HCP Vision', 'HCP-Vision-Latest', ' HCP-Vision-Latest '):
            for path in ('SKILL.md', '資料.html', 'report.csv', 'image.png.txt', 'image.svg', 'file'):
                with self.subTest(model=model, path=path), patch('builtins.open', side_effect=AssertionError('No file reads')):
                    code, output, fallback = self.run_hook(payload(path), model=model)
                self.assertEqual((0, '{}\n'), (code, output))
                fallback.assert_not_called()

    def test_main_image_uses_existing_scope_and_runtime_checks_once(self):
        for suffix in vision.IMAGE_SUFFIXES:
            value = payload('C:/가상/image' + suffix)
            code, output, fallback = self.run_hook(value, fallback_code=78)
            self.assertEqual((78, ''), (code, output))
            fallback.assert_called_once_with(json.dumps(value, ensure_ascii=False))

    def test_vision_child_and_disabled_images_do_not_start_shell(self):
        for value, model in ((payload('x.PNG'), ''), (payload('x.PDF'), 'HCP Vision'),
                             (payload('x.PDF', agent_type=vision.VISION_AGENT, agent_id='child'), vision.VISION_MODEL)):
            code, output, fallback = self.run_hook(value, model=model)
            self.assertEqual((0, '{}\n'), (code, output))
            fallback.assert_not_called()

    def test_main_agent_type_alone_does_not_bypass_handoff(self):
        _, output, fallback = self.run_hook(payload('x.PNG', agent_type=vision.VISION_AGENT))
        self.assertEqual('', output)
        fallback.assert_called_once()

    def test_malformed_and_misrouted_inputs_retain_normal_checks(self):
        for value in ('{', '[]', 'null', '{}', '{"tool_name":"Read"}',
                      '{"tool_name":"Read","tool_input":{"file_path":1}}',
                      '{"tool_name":"Read","tool_input":{"file_path":" "}}',
                      '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}'):
            with self.subTest(value=value):
                code, output, fallback = self.run_hook(value, raw=True, fallback_code=2)
                self.assertEqual((2, ''), (code, output))
                fallback.assert_called_once_with(value)

    def test_unsupported_python_goes_to_recovery_without_importing_application(self):
        with patch.object(sys, 'version_info', (3, 10, 0)), patch.object(vision, 'preflight') as preflight:
            code, _, fallback = self.run_hook(payload(), fallback_code=2)
        preflight.assert_not_called()
        self.assertEqual(2, code)
        fallback.assert_called_once()

    def test_fallback_forwards_utf8_input_and_original_exit_without_retry(self):
        text = json.dumps(payload('C:/한글/100% &! "quote".png'), ensure_ascii=False)
        for code in (0, 1, 2, 78):
            with patch.object(read_hook.subprocess, 'run', return_value=subprocess.CompletedProcess([], code)) as run:
                self.assertEqual(code, read_hook.fallback(text))
            run.assert_called_once()
            self.assertEqual(text.encode('utf-8'), run.call_args.kwargs['input'])
            self.assertNotIn('shell', run.call_args.kwargs)
            self.assertEqual(['-Mode', 'Hook', '-Event', 'PreToolUse'], run.call_args.args[0][-4:])

    def test_launcher_denial_is_not_retried_or_exposed_as_payload(self):
        out = io.StringIO()
        with patch.object(read_hook.subprocess, 'run', side_effect=PermissionError('private path')) as run, \
                contextlib.redirect_stderr(out):
            self.assertEqual(2, read_hook.fallback('private payload'))
        run.assert_called_once()
        self.assertNotIn('private', out.getvalue())


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows PowerShell required')
class ReadHookIntegrationTests(fixtures.NativeRuntimeTestBase):
    def setUp(self):
        super().setUp()
        self.plugin = self.root / 'plugin 한글'
        shutil.copytree(fixtures.PLUGIN, self.plugin, ignore=shutil.ignore_patterns('__pycache__', 'runtime'))
        self.register('project', 'Project', self.project)
        fixtures.atomic_write_json(self.plugin / 'company-agent-install.json', {
            'registrationsRoot': str(self.registrations), 'knowledgeBaseRoot': str(self.base),
            'pythonCommand': sys.executable,
        })

    def run_entry(self, value, *, cwd=None):
        env = dict(os.environ, ANTHROPIC_CUSTOM_MODEL_OPTION=vision.VISION_MODEL,
                   PYTHONDONTWRITEBYTECODE='1', CLAUDE_CONFIG_DIR=str(self.root / 'isolated-profile'))
        env.pop('CLAUDE_ENV_FILE', None)
        return subprocess.run([sys.executable, '-X', 'utf8', '-B', str(self.plugin / 'scripts/read_hook.py')],
                              input=json.dumps(value, ensure_ascii=False), capture_output=True, text=True,
                              encoding='utf-8', env=env, cwd=cwd or self.project, timeout=30)

    def test_real_active_image_and_unrelated_scope_parity(self):
        for active in (True, False):
            cwd = self.project if active else self.root
            result = self.run_entry(payload('C:/synthetic/한글.png', cwd=str(cwd)), cwd=cwd)
            self.assertEqual(0, result.returncode, result.stderr)
            actual = json.loads(result.stdout)
            if active:
                self.assertEqual('deny', actual['hookSpecificOutput']['permissionDecision'])
                self.assertIn(vision.VISION_AGENT, actual['hookSpecificOutput']['permissionDecisionReason'])
            else:
                self.assertEqual({}, actual)

    def test_large_payload_is_consumed_without_shell_or_pipe_error(self):
        # 1 MiB synthetic context; no real file, settings or prompt persistence.
        result = self.run_entry(payload(context='가' * 350000))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({}, json.loads(result.stdout))

    def test_application_error_is_forwarded_once(self):
        trace = self.root / 'calls.txt'
        fixtures.atomic_write_text(self.plugin / 'scripts/native_entry.py',
            'from pathlib import Path\n'
            f'with Path({str(trace)!r}).open("a") as f: f.write("entered\\n")\n'
            'print("fixture application error")\nraise SystemExit(78)\n')
        result = self.run_entry(payload('x.png'))
        self.assertEqual(78, result.returncode, result.stderr)
        self.assertEqual('entered\n', trace.read_text())
        self.assertEqual('fixture application error\n', result.stdout)


if __name__ == '__main__':
    unittest.main()
