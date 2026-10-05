"""Isolated native launcher boundaries; never use the real Claude profile."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
import venv

import test_native_runtime as fixtures


class BootstrapTests(unittest.TestCase):
    def test_unsupported_version_cannot_enter_application_or_emit_ready(self):
        path = fixtures.SCRIPTS / 'native_bootstrap.py'
        spec = importlib.util.spec_from_file_location('company_bootstrap_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for version in ((3, 10, 12), (2, 7, 18), (4, 0, 0)):
            output = io.StringIO()
            with patch.object(sys, 'version_info', version), patch('runpy.run_path') as run, contextlib.redirect_stdout(output):
                self.assertEqual(78, module.main())
                run.assert_not_called()
                self.assertEqual('', output.getvalue())


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Native Windows PowerShell required')
class NativeLauncherTests(fixtures.NativeRuntimeTestBase):
    run_wrapper = fixtures.NativePowerShellTests.run_wrapper

    def setUp(self):
        super().setUp()
        self.plugin = self.root / 'plugin 한글 😀'
        shutil.copytree(fixtures.PLUGIN, self.plugin, ignore=shutil.ignore_patterns('__pycache__', 'runtime'))
        self.record = self.register('project', 'Project', self.project)
        self.metadata = {'registrationsRoot': str(self.registrations), 'knowledgeBaseRoot': str(self.base),
                         'pythonCommand': sys.executable}
        self.save_metadata()
        self.trace = self.root / 'application-calls.txt'

    def save_metadata(self):
        fixtures.atomic_write_json(self.plugin / 'company-agent-install.json', self.metadata)

    def entry(self, content):
        fixtures.atomic_write_text(self.plugin / 'scripts/native_entry.py', content)

    def test_hook_payload_unicode_and_runtime_identity(self):
        self.entry('import json, os, sys\nprint(json.dumps({"payload":json.load(sys.stdin),'
                   '"args":sys.argv[1:],"python":os.environ["COMPANY_AGENT_PYTHON"]},ensure_ascii=True))\n')
        payload = {'session_id': 'fixture', 'prompt': '한글 😀 "literal"\nsecond line'}
        result = self.run_wrapper(['-Mode', 'Hook', '-Event', 'PostToolUse'], payload)
        self.assertEqual(0, result.returncode, result.stderr)
        actual = json.loads(result.stdout)
        self.assertEqual(payload, actual['payload'])
        self.assertEqual(['--event', 'PostToolUse'], actual['args'])
        self.assertEqual(Path(sys.executable), Path(actual['python']))
        self.assertEqual('', result.stderr)

    def test_cli_arguments_with_spaces_and_unicode(self):
        self.entry('import json, sys\nprint(json.dumps(sys.argv[1:],ensure_ascii=True))\n')
        arguments = ['business', 'fixture', '--file', str(self.root / '한글 😀 spaced file.json')]
        result = self.run_wrapper(['-Mode', 'Cli', *arguments])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['--cli', *arguments], json.loads(result.stdout))

    def test_application_receives_original_launcher_environment(self):
        self.entry('import json, os\nprint(json.dumps({key:os.environ.get(key) for key in '
                   '("PYLAUNCHER_ALLOW_INSTALL","PYLAUNCHER_ALWAYS_INSTALL","PYTHON_MANAGER_AUTOMATIC_INSTALL","COMPANY_AGENT_BOOTSTRAP_ENV")}))\n')
        original = {'PYLAUNCHER_ALLOW_INSTALL': '1', 'PYLAUNCHER_ALWAYS_INSTALL': None,
                    'PYTHON_MANAGER_AUTOMATIC_INSTALL': 'caller-value', 'COMPANY_AGENT_BOOTSTRAP_ENV': 'caller-private-value'}
        result = self.run_wrapper(['-Mode', 'Cli', 'fixture'], env_overrides=original)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(original, json.loads(result.stdout))

    def test_application_failure_is_not_retried_even_with_bootstrap_exit_code(self):
        self.entry('import pathlib, sys\n'
                   f'with pathlib.Path({str(self.trace)!r}).open("a",encoding="utf-8") as stream: stream.write("entered\\n")\n'
                   'print("output before failure",flush=True)\n'
                   'print("specific application failure",file=sys.stderr,flush=True)\nraise SystemExit(78)\n')
        result = self.run_wrapper(['-Mode', 'Cli', 'fixture'])
        self.assertEqual(78, result.returncode)
        self.assertEqual('entered\n', self.trace.read_text(encoding='utf-8'))
        self.assertEqual('output before failure\n', result.stdout)
        self.assertIn('specific application failure', result.stderr)
        self.assertNotIn('needs the company-approved Python', result.stderr)

    def test_entry_permission_error_preserves_error_without_fallback(self):
        self.entry('import pathlib\n'
                   f'with pathlib.Path({str(self.trace)!r}).open("a",encoding="utf-8") as stream: stream.write("entered\\n")\n'
                   'raise PermissionError("fixture execution denied")\n')
        result = self.run_wrapper(['-Mode', 'Cli', 'fixture'])
        self.assertEqual(1, result.returncode)
        self.assertEqual('entered\n', self.trace.read_text(encoding='utf-8'))
        self.assertIn('PermissionError: fixture execution denied', result.stderr)
        self.assertNotIn('needs the company-approved Python', result.stderr)

    def test_incompatible_interpreter_falls_back_before_running_application(self):
        # A disposable venv supplies a distinct interpreter path, while a local
        # sitecustomize simulates an older version. No old runtime is installed.
        runtime = self.root / 'python 한글 😀'
        venv.EnvBuilder(with_pip=False).create(runtime)
        executable = runtime / 'Scripts/python.exe'
        site = self.root / 'fixture-site'
        startup_trace = self.root / 'startup-calls.txt'
        fixtures.atomic_write_text(site / 'sitecustomize.py',
            'import os, sys\n'
            f'with open({str(startup_trace)!r},"a",encoding="utf-8") as stream: stream.write(sys.executable+"\\n")\n'
            f'if os.path.normcase(sys.executable)==os.path.normcase({str(executable)!r}): sys.version_info=(3,10,0,"final",0)\n')
        self.metadata['pythonCommand'] = str(executable)
        self.save_metadata()
        self.entry('import sys\nprint(sys.executable)\n')
        result = self.run_wrapper(['-Mode', 'Cli', 'fixture'], env_overrides={'PYTHONPATH': str(site)})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(Path(sys.executable), Path(result.stdout.strip()))
        self.assertEqual([str(executable), sys.executable], startup_trace.read_text(encoding='utf-8').splitlines())
        self.assertEqual('', result.stderr)

    def test_wrong_executable_falls_back_without_leaking_probe_output(self):
        self.metadata['pythonCommand'] = str(Path(os.environ['SystemRoot']) / 'System32/where.exe')
        self.save_metadata()
        self.entry('print("application entered")\n')
        result = self.run_wrapper(['-Mode', 'Cli', 'fixture'])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('application entered\n', result.stdout)
        self.assertEqual('', result.stderr)

    def test_selection_requires_matching_release_and_expected_path(self):
        runtime = self.root / 'selected-python'
        venv.EnvBuilder(with_pip=False).create(runtime)
        selected = runtime / 'Scripts/python.exe'
        self.entry('import sys\nprint(sys.executable)\n')
        expected = self.base.parent / 'runtime-selection.json'
        wrong = self.root / 'wrong-selection.json'
        self.metadata['coreVersion'] = 'fixture-version'
        cases = [(expected, 'fixture-version', selected), (expected, 'other-version', Path(sys.executable)),
                 (wrong, 'fixture-version', Path(sys.executable))]
        for path, version, wanted in cases:
            with self.subTest(path=path.name, version=version):
                self.metadata['runtimeSelectionPath'] = str(path)
                self.save_metadata()
                fixtures.atomic_write_json(path, {'coreVersion': version, 'pythonCommand': str(selected)})
                result = self.run_wrapper(['-Mode', 'Cli', 'fixture'])
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(wanted, Path(result.stdout.strip()))

    def test_selection_beneath_junction_is_not_followed(self):
        release = self.root / 'real-release'
        release.mkdir()
        runtime = release / 'selected-python'
        venv.EnvBuilder(with_pip=False).create(runtime)
        linked = self.root / 'linked-release'
        # Both paths are disposable fixture children; no user profile link.
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        command = ('$ErrorActionPreference="Stop"; New-Item -ItemType Junction -Path '
                   + quote(linked) + ' -Target ' + quote(release) + ' | Out-Null')
        made = subprocess.run([shutil.which('powershell.exe'), '-NoLogo', '-NoProfile', '-Command', command],
                              capture_output=True, text=True, timeout=15)
        self.assertEqual(0, made.returncode, made.stderr)
        self.metadata.update(coreVersion='fixture-version', knowledgeBaseRoot=str(linked / 'corporate'),
                             runtimeSelectionPath=str(linked / 'runtime-selection.json'))
        self.save_metadata()
        fixtures.atomic_write_json(release / 'runtime-selection.json',
                                   {'coreVersion': 'fixture-version', 'pythonCommand': str(runtime / 'Scripts/python.exe')})
        self.entry('import sys\nprint(sys.executable)\n')
        result = self.run_wrapper(['-Mode', 'Cli', 'fixture'])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(Path(sys.executable), Path(result.stdout.strip()))

    def test_cli_stdout_and_stderr_are_forwarded_before_process_exit(self):
        self.entry('import sys, time\nprint("early stdout",flush=True)\n'
                   'print("early stderr",file=sys.stderr,flush=True)\ntime.sleep(3)\nprint("done",flush=True)\n')
        env = dict(os.environ, COMPANY_AGENT_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE='1')
        env.pop('CLAUDE_ENV_FILE', None)
        command = [shutil.which('powershell.exe'), '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                   '-File', str(self.plugin / 'scripts/Invoke-CompanyAgent.ps1'), '-Mode', 'Cli', 'fixture']
        with subprocess.Popen(command, cwd=self.project, env=env, text=True, encoding='utf-8',
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            observed = queue.Queue()
            threads = [threading.Thread(target=lambda label=label, stream=stream: observed.put((label, stream.readline())), daemon=True)
                       for label, stream in (('stdout', process.stdout), ('stderr', process.stderr))]
            for thread in threads:
                thread.start()
            try:
                first = observed.get(timeout=8)
                second = observed.get(timeout=2)
                self.assertEqual({'stdout': 'early stdout\n', 'stderr': 'early stderr\n'}, dict([first, second]))
                self.assertIsNone(process.poll(), 'Output was buffered until the application exited')
            finally:
                for thread in threads:
                    thread.join(timeout=1)
                out, err = process.communicate(timeout=8)
            self.assertEqual(0, process.returncode, err)
            self.assertEqual('done\n', out)
            self.assertEqual('', err)


if __name__ == '__main__':
    unittest.main()
