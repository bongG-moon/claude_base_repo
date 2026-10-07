"""Exercise compiled installer extraction, real PS bridge and native form actions."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319'
CSC = FRAMEWORK / 'csc.exe'
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
BRIDGE = ROOT / 'deploy/CompanyAgent.SetupBridge.ps1'


@unittest.skipUnless(os.name == 'nt' and CSC.exists(), 'Windows .NET Framework required')
class HarnessSetupExeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='하네스 설치 & ')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.fixture_counter = 0
        cls.setup = '''param([string]$Scope,[string]$BundleRoot,[string]$ProjectRoot,[string]$ClaudeCommand,
            [string]$PythonCommand,[string]$ExistingHarnessAction='Ask',[string]$SkillConflictAction,[switch]$NonInteractive)
            $ErrorActionPreference='Stop'
            if ($env:SETUP_FIXTURE_MODE -eq 'failed') { throw 'fixture failure; do not report success' }
            if ($env:SETUP_FIXTURE_MODE -eq 'update' -and $ExistingHarnessAction -eq 'Ask') {
                return [pscustomobject]@{status='input-required'; input='ExistingHarnessAction'; choices=@('Update','Keep')}
            }
            $observation = @{scope=$Scope; project=$ProjectRoot; claude=$ClaudeCommand; python=$PythonCommand;
              existing=$ExistingHarnessAction; skills=$SkillConflictAction; nonInteractive=[bool]$NonInteractive;
              config=$env:CLAUDE_CONFIG_DIR; model=$env:ANTHROPIC_MODEL;
              unexpectedBypass=$PSBoundParameters.ContainsKey('SkipBundleVerification')}
            $observation | ConvertTo-Json | Set-Content -LiteralPath $env:SETUP_FIXTURE_RECORD -Encoding UTF8
            [pscustomobject]@{status=$(if($ExistingHarnessAction -eq 'Update'){'updated'}else{'installed'}); coreVersion='9.9.99'; safetyBackup='fixture backup'}
        '''.encode('utf-8-sig')
        cls.files = {'bundle-manifest.json': b'{"fixture":true}',
                     'deploy/Setup-CompanyAgent.ps1': cls.setup,
                     'docs/Company-Agent-사용자-안내서.html': '<html lang="ko">안내서</html>'.encode()}
        cls.exe = cls.compile_fixture()
        cls.probe = cls.root / 'probe.exe'
        cls.compile(['/target:exe', '/out:' + str(cls.probe), str(ROOT / 'scripts/test-lab/test-harness-setup.cs')])

    @classmethod
    def compile(cls, args):
        result = subprocess.run([str(CSC), '/nologo', '/codepage:65001', '/platform:x64',
                                 '/reference:System.Core.dll', '/reference:System.Drawing.dll',
                                 '/reference:System.Windows.Forms.dll', '/reference:System.Web.Extensions.dll',
                                 '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll', *args],
                                capture_output=True, timeout=30, creationflags=HIDDEN)
        if result.returncode:
            raise AssertionError(result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace'))

    @classmethod
    def compile_fixture(cls, extra=None, payload_files=None):
        cls.fixture_counter += 1
        files = cls.files if payload_files is None else payload_files
        directory = cls.root / ('compile-' + str(cls.fixture_counter))
        directory.mkdir()
        archive = directory / 'payload.zip'
        with zipfile.ZipFile(archive, 'w') as zipped:
            for name, raw in files.items():
                zipped.writestr(name, raw)
            if extra:
                zipped.writestr(extra, b'escape')
        rows = ''.join(hashlib.sha256(raw).hexdigest() + '\t' + name + '\n' for name, raw in files.items())
        manifest = directory / 'manifest.tsv'
        manifest.write_text(rows, encoding='utf-8')
        build = directory / 'build.txt'
        build.write_text('9.9.99\n' + hashlib.sha256(archive.read_bytes()).hexdigest() + '\n' +
                         hashlib.sha256(BRIDGE.read_bytes()).hexdigest() + '\n', encoding='utf-8')
        exe = directory / 'Company-Harness-Setup.exe'
        cls.compile(['/target:winexe', '/out:' + str(exe),
                     '/win32manifest:' + str(ROOT / 'deploy/CompanyAgent.Setup.manifest'),
                     '/resource:' + str(archive) + ',SetupPayload.zip',
                     '/resource:' + str(manifest) + ',SetupPayload.manifest.tsv',
                     '/resource:' + str(BRIDGE) + ',SetupBridge.ps1',
                     '/resource:' + str(build) + ',SetupBuild.txt', str(ROOT / 'deploy/CompanyAgent.Setup.cs')])
        return exe

    def setUp(self):
        self.temp_case = tempfile.TemporaryDirectory(prefix='설치 검증 ', dir=self.root)
        self.addCleanup(self.temp_case.cleanup)
        self.case = Path(self.temp_case.name)
        self.cache = self.case / 'cache & 한글'
        self.report = self.case / 'result.json'
        self.record = self.case / 'called.json'
        self.env = os.environ.copy()
        self.env.update(SETUP_FIXTURE_RECORD=str(self.record), CLAUDE_CONFIG_DIR=str(self.case / 'profile'),
                        ANTHROPIC_MODEL='fixture-inherited-model', SETUP_FIXTURE_MODE='fresh')

    def verify(self, exe=None):
        return subprocess.run([str(exe or self.exe), '--verify-only', '--cache-root', str(self.cache)],
                              capture_output=True, timeout=15, creationflags=HIDDEN)

    def probe_run(self, mode, *extra):
        result = subprocess.run([str(self.probe), str(self.exe), mode, str(self.cache), str(self.report), *map(str, extra)],
                                capture_output=True, env=self.env, timeout=40, creationflags=HIDDEN)
        self.assertEqual(0, result.returncode, result.stderr.decode(errors='replace'))
        return json.loads(self.report.read_text(encoding='utf-8'))

    def test_verification_does_not_install_and_detects_cached_tampering(self):
        self.assertEqual(0, self.verify().returncode)
        self.assertFalse(self.record.exists())
        self.assertEqual(0, self.verify().returncode)
        next(self.cache.glob('*/bundle/deploy/Setup-CompanyAgent.ps1')).write_bytes(b'changed')
        self.assertNotEqual(0, self.verify().returncode)

    def test_prepare_only_diagnoses_long_fresh_cache_and_short_cache_verifies(self):
        # Match the longest production payload path: a deep checkout's build
        # cache adds .prepare-GUID/bundle and reaches legacy .NET's 260 limit.
        relative = 'payload/core/plugin/skills/platform-mcp-builder/assets/template/requirements-local.txt'
        exe = self.compile_fixture(payload_files={**self.files, relative: b'fixture dependency'})
        prefix = str(self.case / 'cache-')
        long_cache = Path(prefix + 'x' * max(1, 124 - len(prefix)))
        self.assertGreaterEqual(len(str(long_cache)) + 50 + len(relative), 260)
        self.assertFalse(long_cache.exists())
        result = subprocess.run([str(self.probe), str(exe), 'prepare-only', str(long_cache), str(self.report)],
                                capture_output=True, env=self.env, timeout=20, creationflags=HIDDEN)
        self.assertEqual(1, result.returncode)
        self.assertIn(b'System.IO.PathTooLongException', result.stderr)
        self.assertFalse(self.report.exists())
        self.assertFalse(self.record.exists())

        self.cache = self.root / ('short-verify-' + str(self.fixture_counter))
        self.assertFalse(self.cache.exists())
        self.assertEqual(0, self.verify(exe).returncode)
        prepared = list(self.cache.glob('*/bundle/' + relative))
        self.assertEqual(1, len(prepared))
        self.assertEqual(b'fixture dependency', prepared[0].read_bytes())
        self.assertFalse(self.record.exists())

    def test_path_escape_is_rejected_without_writing_outside_owned_cache(self):
        bad = self.compile_fixture(extra='../escape.txt')
        self.assertNotEqual(0, self.verify(bad).returncode)
        self.assertFalse((self.case / 'escape.txt').exists())

    def test_bridge_preserves_unicode_arguments_and_inherited_cli_environment(self):
        request = self.case / 'request.json'
        request.write_text(json.dumps({'Scope':'Project', 'ProjectRoot':str(self.case / "업무 & '폴더"),
                                      'ClaudeCommand':str(self.case / 'claude.cmd'),
                                      'PythonCommand':str(self.case / 'python.exe'),
                                      'SkipBundleVerification':True}), encoding='utf-8')
        result = self.probe_run('run', request)
        self.assertEqual('installed', result['status'], result)
        observed = json.loads(self.record.read_text(encoding='utf-8-sig'))
        self.assertEqual('Project', observed['scope'])
        self.assertEqual(str(self.case / "업무 & '폴더"), observed['project'])
        self.assertEqual(self.env['CLAUDE_CONFIG_DIR'], observed['config'])
        self.assertEqual(self.env['ANTHROPIC_MODEL'], observed['model'])
        self.assertTrue(observed['nonInteractive'])
        self.assertFalse(observed['unexpectedBypass'])
        self.assertFalse(list(self.cache.glob('*/requests/*/request.json')))

    def test_native_install_button_finishes_without_console_or_extra_questions(self):
        ui = self.probe_run('gui')
        self.assertIn('설치가 완료되었습니다', ui['message'], ui)
        self.assertFalse(ui['installVisible'])
        self.assertTrue(ui['closeEnabled'])
        self.assertTrue(ui['busyAtStart'])
        self.assertTrue(ui['closeDisabledDuringWork'])
        observed = json.loads(self.record.read_text(encoding='utf-8-sig'))
        self.assertEqual('User', observed['scope'])
        self.assertEqual('KeepCurrent', observed['skills'])

    def test_native_project_selection_and_existing_update_are_honored(self):
        self.env['SETUP_FIXTURE_MODE'] = 'update'
        project = self.case / '내 업무 폴더'
        project.mkdir()
        ui = self.probe_run('gui', project)
        self.assertIn('설치가 완료되었습니다', ui['message'], ui)
        observed = json.loads(self.record.read_text(encoding='utf-8-sig'))
        self.assertEqual('Update', observed['existing'])
        self.assertEqual('Project', observed['scope'])
        self.assertEqual(str(project), observed['project'])

    def test_failed_installer_is_not_reported_as_completed(self):
        self.env['SETUP_FIXTURE_MODE'] = 'failed'
        ui = self.probe_run('gui')
        self.assertIn('완료하지 못했습니다', ui['message'])
        self.assertTrue(ui['installVisible'])
        self.assertTrue(ui['closeEnabled'], ui)
        self.assertIn('fixture failure', ui['details'])
        self.assertFalse(self.record.exists())

    def test_large_fonts_keep_text_rows_and_footer_unclipped(self):
        for factor in ('1', '1.5', '2'):
            with self.subTest(scale=factor):
                ui = self.probe_run('layout', factor)
                self.assertEqual('Company Harness 설치', ui['title'])
                self.assertEqual('Company Harness', ui['headingText'])
                for name in ('heading', 'introduction', 'user', 'project', 'status', 'browse', 'install', 'close'):
                    box = ui[name]
                    self.assertGreaterEqual(box['height'], box['preferredHeight'], (name, box, ui))
                for previous, following in (('heading','introduction'), ('introduction','user'), ('user','project'), ('project','folder')):
                    a, b = ui[previous], ui[following]
                    self.assertLessEqual(a['y'] + a['height'], b['y'], (previous, following, ui))
                for name in ('browse','install','close'):
                    box = ui[name]
                    self.assertGreaterEqual(box['x'], 0, (name, ui))
                    self.assertLessEqual(box['x'] + box['width'], ui['width'], (name, ui))
                for name in ('install','close'):
                    box = ui[name]
                    self.assertLessEqual(box['y'] + box['height'], ui['height'], (name, ui))

    def test_small_window_scrolls_content_while_install_buttons_remain_visible(self):
        ui = self.probe_run('layout', '2', 'compact')
        self.assertTrue(ui['scrollable'], ui)
        for name in ('heading','introduction','status'):
            self.assertGreaterEqual(ui[name]['height'], ui[name]['preferredHeight'], (name, ui))
        for name in ('install','close'):
            box = ui[name]
            self.assertLessEqual(box['x'] + box['width'], ui['width'], (name, ui))
            self.assertLessEqual(box['y'] + box['height'], ui['height'], (name, ui))


if __name__ == '__main__':
    unittest.main()
