"""Exercise the real Windows entry without installing or touching a user profile."""
import base64
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PS = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell entry')
class NoviceSetupMessagesTests(unittest.TestCase):
    def invoke(self, code):
        encoded = base64.b64encode(("[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); " + code).encode('utf-16-le')).decode('ascii')
        return subprocess.run([str(PS), '-NoLogo', '-NoProfile', '-EncodedCommand', encoded],
                              capture_output=True, encoding='utf-8', timeout=35)

    def functions(self, code):
        path = str(ROOT / 'deploy/Setup-CompanyAgent.ps1').replace("'", "''")
        return self.invoke(f". '{path}' -FunctionsOnly; " + code)

    def test_recovery_attention_wins_and_raw_error_is_not_echoed(self):
        result = self.functions("Get-SetupFriendlyFailure 'Core version already exists with different contents. Recovery needs attention. API_KEY=PRIVATE'")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('복원도 확인이 필요', result.stdout)
        self.assertNotIn('PRIVATE', result.stdout)

    def test_version_conflict_explains_upgrade_not_delete(self):
        result = self.functions("Get-SetupFriendlyFailure 'This Core version already exists with different contents'")
        self.assertIn('버전 번호가 올라간', result.stdout)
        self.assertIn('지우지 말고', result.stdout)

    def test_backup_failures_explain_cause_without_raw_settings(self):
        codes = {'PATH_TOO_LONG': '경로', 'ACCESS_DENIED': '접근', 'FILE_IN_USE': '사용 중',
                 'DISK_FULL': '공간', 'PATH_MISSING': '찾지 못', 'INVALID_JSON': 'JSON',
                 'LIMIT_EXCEEDED': '안전 한도', 'LINK_UNSAFE': '연결 폴더', 'IO_ERROR': '진단'}
        for code, expected in codes.items():
            with self.subTest(code=code):
                result = self.functions(f"Get-SetupFriendlyFailure '[BACKUP_{code}] PRIVATE_SETTING_VALUE'")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn('새 버전 설치는 시작하지 않았습니다', result.stdout)
                self.assertIn(expected, result.stdout)
                self.assertNotIn('PRIVATE_SETTING_VALUE', result.stdout)

    def test_cancel_and_pending_never_claim_installed(self):
        result = self.functions("Write-SetupFriendlyResult ([pscustomobject]@{status='kept'}); Write-SetupFriendlyResult ([pscustomobject]@{status='input-required'})")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('아직 설치되지 않았습니다', result.stdout)
        self.assertNotIn('설치 완료', result.stdout)
        self.assertNotIn('닫았다 다시', result.stdout)

    def test_real_friendly_entry_stops_with_nonzero_and_no_stack(self):
        with tempfile.TemporaryDirectory(prefix='CA-novice-') as folder:
            path = str(ROOT / 'deploy/Setup-CompanyAgent.ps1').replace("'", "''")
            missing = str(Path(folder) / 'missing project').replace("'", "''")
            result = self.invoke(f"& '{path}' -FriendlyOutput -Scope Project -ProjectRoot '{missing}' -NonInteractive -SkipAdminCheck")
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn('프로젝트 폴더를 확인하지 못했습니다', result.stdout)
            self.assertNotIn('CategoryInfo', result.stdout + result.stderr)
            self.assertEqual([], list(Path(folder).iterdir()))

    def test_nonfriendly_entry_preserves_original_failure(self):
        path = str(ROOT / 'deploy/Setup-CompanyAgent.ps1').replace("'", "''")
        result = self.invoke(
            f"try {{ & '{path}' -NonInteractive -SkipAdminCheck; exit 9 }} "
            "catch { [Console]::WriteLine($_.Exception.Message); exit 7 }"
        )
        self.assertEqual(7, result.returncode, result.stdout + result.stderr)
        self.assertIn('Choose the installation scope', result.stdout)
        self.assertNotIn('ScriptHalted', result.stdout + result.stderr)

    def test_actual_friendly_trap_shows_backup_diagnostic_not_raw_json(self):
        with tempfile.TemporaryDirectory(prefix='CA-backup-ui-') as folder:
            root = Path(folder)
            source = root / 'invalid.json'
            source.write_text('{"apiKey":"PRIVATE_SETTING_VALUE", bad', encoding='utf-8')
            path = str(ROOT / 'deploy/Setup-CompanyAgent.ps1').replace("'", "''")
            escaped_root = str(root).replace("'", "''")
            # Execute the production trap with real backup functions, but no
            # installer entry, CLI registration, or actual profile mutation.
            result = self.functions(f"""
$tokens=$null; $parseErrors=$null
$syntax=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$tokens,[ref]$parseErrors)
$trapText=$syntax.EndBlock.Traps[0].Extent.Text
$root='{escaped_root}'
$items=@([pscustomobject]@{{source=(Join-Path $root 'invalid.json');relativePath='invalid.json';purpose='test';mode='sanitized-json';required=$true}})
$backupFixtureArgs=@{{BackupBase=(Join-Path $root 'backups');Items=$items;ClaudeConfigPath=(Join-Path $root 'profile');PersonalStatePath=(Join-Path $root 'state');ManagedDataPath=(Join-Path $root 'data');ManagedInstallPath=(Join-Path $root 'install')}}
$body='$FriendlyOutput=$true; $NonInteractive=$true; ' + $trapText + '; New-SetupBackup @backupFixtureArgs'
& ([scriptblock]::Create($body))
""")
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn('진단 코드: BACKUP_INVALID_JSON', result.stdout)
            self.assertIn('담당자에게 전달할 진단 파일:', result.stdout)
            self.assertIn('완료된 백업이 아님', result.stdout)
            self.assertNotIn('PRIVATE_SETTING_VALUE', result.stdout + result.stderr)
            self.assertEqual(1, len(list(root.rglob('backup-diagnostic.json'))))
            self.assertEqual([], list(root.rglob('backup-manifest.json')))

    def test_launcher_ascii_and_ps1_unicode_contract(self):
        cmd = (ROOT / 'deploy/Install-CompanyAgent.cmd').read_bytes().decode('ascii')
        self.assertIn('-FriendlyOutput', cmd)
        self.assertIn('%ERRORLEVEL%', cmd)
        raw = (ROOT / 'deploy/Setup-CompanyAgent.ps1').read_bytes()
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        diagnostic = (ROOT / 'Diagnose-CompanyAgent.cmd').read_bytes().decode('ascii')
        self.assertIn('-ExecutionPolicy Bypass', diagnostic)  # Process-local, like installation.
        self.assertIn('exit /b %COMPANY_AGENT_DIAGNOSTIC_EXIT%', diagnostic)
        self.assertNotIn('claude --', diagnostic.lower())


if __name__ == '__main__':
    unittest.main()
