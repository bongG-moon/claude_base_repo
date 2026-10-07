"""Real PowerShell delivery preparation: portable assets and malformed bundles."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('powershell.exe')
SCRIPT = ROOT / 'deploy/New-GitLabHarnessDelivery.ps1'
GUIDE = 'docs/Company-Agent-사용자-안내서.html'
INSTALLED = 'payload/core/plugin/resources/manuals/Company-Agent-사용자-안내서.html'


@unittest.skipUnless(POWERSHELL, 'Windows PowerShell required')
class GitLabHarnessDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gitlab-harness-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / '배포 자료'
        self.bundle = self.root / 'approved.zip'

    def archive(self, *, altered=False, duplicate=False, extra=False, different_guide=False, source=False):
        files = {'Install-CompanyAgent.cmd': b'@echo off\r\n',
                 'deploy/Setup-CompanyAgent.ps1': b'# fixture; not executed\n',
                 GUIDE: '<html lang="ko">검증용 안내서</html>'.encode(),
                 INSTALLED: '<html lang="ko">검증용 안내서</html>'.encode()}
        if different_guide:
            files[INSTALLED] = b'<html>different</html>'
        manifest = {'format': 'company-agent-offline-bundle/v1', 'coreVersion': '1.4.36',
                    'knowledgeVersion': '2026.09.03', 'files': [
                        {'path': name, 'length': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                        for name, raw in files.items()]}
        if altered:
            files['Install-CompanyAgent.cmd'] = b'@echo on \r\n'
        with zipfile.ZipFile(self.bundle, 'w') as archive:
            for name, raw in files.items():
                archive.writestr(name, raw)
            if not source:
                archive.writestr('bundle-manifest.json', json.dumps(manifest).encode())
            if duplicate:
                archive.writestr('INSTALL-COMPANYAGENT.CMD', b'other')
            if extra:
                archive.writestr('../outside.txt', b'never extract')

    def run_delivery(self, project=None, setup=None):
        args = [POWERSHELL, '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                '-File', str(SCRIPT), '-BundleZip', str(self.bundle),
                '-OutputDirectory', str(self.output)]
        if project is not None:
            args += ['-ProjectUrl', project]
        if setup is not None:
            args += ['-SetupExe', str(setup)]
        env = os.environ.copy()
        env['PSModulePath'] = str(Path(env['WINDIR']) / 'System32/WindowsPowerShell/v1.0/Modules')
        return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=30)

    def setup_fixture(self, version='1.4.36'):
        compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        source = self.root / 'fixture.cs'
        source.write_text('using System.Reflection; [assembly: AssemblyVersion("' + version +
                          '.0")] internal static class Fixture { private static void Main() {} }', encoding='utf-8')
        exe = self.root / 'fixture.exe'
        result = subprocess.run([str(compiler), '/nologo', '/target:winexe', '/out:' + str(exe),
                                 '/resource:' + str(self.bundle) + ',SetupPayload.zip', str(source)],
                                capture_output=True, timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(0, result.returncode, result.stdout.decode(errors='replace'))
        return exe

    def test_exact_bundle_and_embedded_guide_become_portable_delivery(self):
        self.archive()
        result = self.run_delivery('https://gitlab.example.com/division/team/harness')
        self.assertEqual(0, result.returncode, result.stderr.decode(errors='replace'))
        report = json.loads(result.stdout)
        self.assertEqual('prepared', report['status'])
        self.assertFalse(report['published'])
        self.assertFalse(report['networkUsed'])
        self.assertEqual('https://gitlab.example.com/division/team/harness/-/releases/v1.4.36', report['releaseUrl'])
        self.assertEqual(4, len(report['employeeFiles']))
        delivered = self.output / report['employeeFiles'][0]
        self.assertEqual(self.bundle.read_bytes(), delivered.read_bytes())
        with zipfile.ZipFile(self.bundle) as archive:
            self.assertEqual(archive.read(GUIDE), (self.output / 'Company-Agent-User-Guide.html').read_bytes())
        for name in report['employeeFiles'][:2]:
            checksum = (self.output / (name + '.sha256')).read_text(encoding='utf-8')
            self.assertEqual(hashlib.sha256((self.output / name).read_bytes()).hexdigest() + '  ' + name + '\n', checksum)
        self.assertIn('Source code', (self.output / 'GitLab-Release.md').read_text(encoding='utf-8'))

    def test_preparation_without_internal_url_needs_no_credentials(self):
        self.archive()
        result = self.run_delivery()
        self.assertEqual(0, result.returncode)
        self.assertEqual('', json.loads(result.stdout)['releaseUrl'])

    def test_exe_delivery_uses_one_click_installation_instructions(self):
        self.archive()
        exe = self.setup_fixture()
        result = self.run_delivery(setup=exe)
        self.assertEqual(0, result.returncode, result.stderr.decode(errors='replace'))
        report = json.loads(result.stdout)
        self.assertEqual('Company-Harness-Setup.exe', report['employeeFiles'][0])
        self.assertFalse(report['published'])
        self.assertFalse(report['networkUsed'])
        self.assertNotIn('company-agent-1.4.36-2026.09.03.zip', report['employeeFiles'])
        self.assertEqual(exe.read_bytes(), (self.output / 'Company-Harness-Setup.exe').read_bytes())
        notes = (self.output / 'GitLab-Release.md').read_text(encoding='utf-8')
        self.assertIn('# Company Harness 1.4.36', notes)
        self.assertIn('Company-Harness-Setup.exe', notes)
        self.assertIn('실제 파일 업로드', (self.output / 'GitLab-배포안내.md').read_text(encoding='utf-8'))
        self.assertIn('두 번 클릭', notes)
        self.assertNotIn('Install-CompanyAgent.cmd', notes)
        self.assertNotIn('모두 압축 풀기', notes)

    def test_exe_with_old_version_is_rejected_before_delivery_creation(self):
        self.archive()
        exe = self.setup_fixture('1.4.35')
        self.assertNotEqual(0, self.run_delivery(setup=exe).returncode)
        self.assertFalse(self.output.exists())

    def test_existing_delivery_is_preserved(self):
        self.archive()
        self.output.mkdir()
        marker = self.output / 'keep.txt'
        marker.write_text('existing', encoding='utf-8')
        result = self.run_delivery()
        self.assertNotEqual(0, result.returncode)
        self.assertEqual('existing', marker.read_text())
        self.assertEqual([marker], list(self.output.iterdir()))

    def test_changed_payload_is_not_prepared(self):
        self.archive(altered=True)
        self.assertNotEqual(0, self.run_delivery().returncode)
        self.assertFalse(self.output.exists())

    def test_source_archive_is_not_mistaken_for_employee_installer(self):
        self.archive(source=True)
        self.assertNotEqual(0, self.run_delivery().returncode)
        self.assertFalse(self.output.exists())

    def test_duplicate_or_escaping_paths_do_not_write_output(self):
        for case in ('duplicate', 'extra'):
            with self.subTest(case=case):
                self.archive(**{case: True})
                self.assertNotEqual(0, self.run_delivery().returncode)
                self.assertFalse(self.output.exists())
                self.assertFalse((self.root / 'outside.txt').exists())

    def test_different_manual_cannot_be_published_as_matching_guide(self):
        self.archive(different_guide=True)
        self.assertNotEqual(0, self.run_delivery().returncode)
        self.assertFalse(self.output.exists())

    def test_secret_bearing_or_non_project_urls_are_rejected(self):
        self.archive()
        for url in ('http://gitlab.example.com/team/harness',
                    'https://name:secret@gitlab.example.com/team/harness',
                    'https://gitlab.example.com/team/harness?private_token=secret',
                    'https://gitlab.example.com/team/harness/-/releases/v1.4.36'):
            with self.subTest(url=url):
                self.assertNotEqual(0, self.run_delivery(url).returncode)
                self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
