"""Run the installer backup boundary in Windows PowerShell 5.1, not pwsh 7."""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "deploy/Setup-CompanyAgent.ps1"
PS = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def io_path(value):
    value = str(value)
    return Path(value if value.startswith("\\\\?\\") else "\\\\?\\" + value)


@contextmanager
def fixture(prefix):
    with tempfile.TemporaryDirectory(prefix=prefix) as directory:
        root = Path(directory)
        try:
            yield root
        finally:
            # Only this test-created, verified root may be removed. Explicit
            # extended paths also work when Windows long paths are disabled.
            assert root.parent.resolve() == Path(tempfile.gettempdir()).resolve()
            assert root.name.startswith(prefix) and not root.is_symlink()
            shutil.rmtree(io_path(root))


@unittest.skipUnless(os.name == "nt", "Windows PowerShell backup API")
class SetupBackupPathsTests(unittest.TestCase):
    def invoke(self, code):
        code = ("$ProgressPreference='SilentlyContinue'; "
                "[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false); "
                f". {quote(SETUP)} -FunctionsOnly; " + code)
        encoded = base64.b64encode(code.encode("utf-16-le")).decode("ascii")
        result = subprocess.run([str(PS), "-NoLogo", "-NoProfile", "-EncodedCommand", encoded],
                                capture_output=True, encoding="utf-8", timeout=45)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def backup(self, root, source, *, mode="copy", extra="", prelude=""):
        return self.invoke(prelude + f"""
$items=@([pscustomobject]@{{source={quote(source)};relativePath='claude-config\\skills';purpose='fixture';mode='{mode}';required=$true}})
$backupFixtureArgs=@{{BackupBase={quote(root / 'backups')};Items=$items;ClaudeConfigPath={quote(root / 'profile')};PersonalStatePath={quote(root / 'state')};ManagedDataPath={quote(root / 'data')};ManagedInstallPath={quote(root / 'install')}}}
try {{
    $backup=New-SetupBackup @backupFixtureArgs {extra}
    @{{status='passed';backup=$backup}} | ConvertTo-Json
}} catch {{
    @{{status='failed';code=$_.Exception.Data['CompanyAgentBackupCode'];backup=$_.Exception.Data['CompanyAgentBackupPath'];diagnostic=$_.Exception.Data['CompanyAgentBackupDiagnostic'];message=(Get-SetupFriendlyFailure $_.Exception.Message)}} | ConvertTo-Json
}}
""")

    def test_boundary_copy_259_260_261_and_360_without_registry_change(self):
        with fixture("CA-path-") as root:
            source = root / "original.md"
            source.write_text("한글 실습 내용", encoding="utf-8")
            source_before = (source.read_bytes(), source.stat().st_mtime_ns)
            targets = []
            for length in (259, 260, 261, 360):
                base = root / str(length)
                while len(str(base / "내용.md")) + 70 < length:
                    base /= "깊은 폴더" + "x" * 54
                padding = length - len(str(base / "내용.md")) - 1
                target = base / ("p" * padding) / "내용.md"
                self.assertEqual(length, len(str(target)))
                io_path(target.parent).mkdir(parents=True)
                targets.append(target)
            target_args = ",".join(quote(path) for path in targets)
            result = self.invoke(f"""
$before=(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem').LongPathsEnabled
foreach ($target in @({target_args})) {{
  $budget=@{{files=0;bytes=[long]0;maxFileBytes=64MB;maxTotalBytes=1GB;maxFiles=20000}}
  Copy-SetupBackupFile -Source {quote(source)} -Destination $target -SanitizeJson $false -Budget $budget
}}
@{{count=4;registryUnchanged=($before -eq (Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem').LongPathsEnabled)}} | ConvertTo-Json
""")
            self.assertTrue(result["registryUnchanged"])
            for target in targets:
                self.assertEqual(source_before[0], io_path(target).read_bytes())
            self.assertEqual(source_before, (source.read_bytes(), source.stat().st_mtime_ns))

    def test_long_source_tree_backup_redaction_exclusions_and_manifest(self):
        with fixture("CA-tree-") as root:
            source = root / "profile/.claude/skills"
            nested = source / "synced" / ("a" * 36 + "_" + "b" * 36) / "docx/scripts/office/schemas/ISO-IEC29500-4_2016"
            nested /= "한글 자료 " + "q" * 75
            io_path(nested).mkdir(parents=True)
            original = nested / "dml-spreadsheetDrawing.xsd"
            io_path(original).write_text("unchanged schema 한글", encoding="utf-8")
            self.assertGreater(len(str(original)), 260)
            settings = nested / "options.json"
            io_path(settings).write_text(json.dumps({"label": "표시", "apiKey": "fixture-private-value"}), encoding="utf-8")
            io_path(nested / ".env").write_text("fixture-secret", encoding="utf-8")
            io_path(nested / "node_modules").mkdir()
            io_path(nested / "node_modules/private.txt").write_text("excluded", encoding="utf-8")
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in io_path(source).rglob("*") if path.is_file()}
            result = self.backup(root, source)
            self.assertEqual("passed", result["status"], result)
            backup = io_path(result["backup"])
            copied = backup / "claude-config/skills" / original.relative_to(source)
            self.assertEqual(io_path(original).read_bytes(), copied.read_bytes())
            copied_options = copied.with_name("options.json")
            self.assertEqual({"label": "표시", "apiKey": "[REDACTED_BY_COMPANY_AGENT_BACKUP]"}, json.loads(copied_options.read_text("utf-8")))
            self.assertFalse(copied.with_name(".env").exists())
            self.assertFalse(copied.with_name("node_modules").exists())
            manifest = json.loads((backup / "backup-manifest.json").read_text("utf-8"))
            self.assertEqual(2, manifest["copiedFiles"])
            self.assertNotIn("\\\\?\\", json.dumps(manifest))
            self.assertEqual("directory", manifest["items"][0]["itemType"])
            self.assertFalse(list(backup.rglob("*.partial-*")))
            self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before})

    def test_long_backup_root_can_publish_completion_marker(self):
        with fixture("CA-meta-") as root:
            source = root / "original.md"
            source.write_text("preserve", encoding="utf-8")
            deep = root / ("p" * 95) / ("q" * 95)
            result = self.backup(deep, source)
            self.assertEqual("passed", result["status"], result)
            manifest_path = io_path(result["backup"]) / "backup-manifest.json"
            self.assertGreater(len(str(manifest_path)), 260)
            self.assertEqual(1, json.loads(manifest_path.read_text("utf-8"))["copiedFiles"])

    def test_failure_has_safe_diagnostic_and_never_complete_manifest(self):
        cases = [("broken.json", '{"apiKey":"do-not-print-me", invalid', "sanitized-json", "", "BACKUP_INVALID_JSON"),
                 ("size.txt", "two", "copy", "-MaxFileBytes 1", "BACKUP_LIMIT_EXCEEDED"),
                 ("missing.md", None, "copy", "", "BACKUP_PATH_MISSING")]
        for filename, content, mode, extra, expected_code in cases:
            with self.subTest(code=expected_code), fixture("CA-diag-") as root:
                source = root / filename
                if content is not None:
                    source.write_text(content, encoding="utf-8")
                result = self.backup(root, source, mode=mode, extra=extra)
                self.assertEqual("failed", result["status"])
                self.assertEqual(expected_code, result["code"])
                diagnostic = Path(result["diagnostic"])
                data = json.loads(diagnostic.read_text("utf-8"))
                self.assertEqual(expected_code, data["code"])
                self.assertNotIn("do-not-print-me", diagnostic.read_text("utf-8") + result["message"])
                self.assertNotIn(str(source), diagnostic.read_text("utf-8"))
                self.assertFalse((Path(result["backup"]) / "backup-manifest.json").exists())
                self.assertIn("설치는 시작하지 않았습니다", result["message"])
                if content is not None:
                    self.assertEqual(content, source.read_text("utf-8"))

    def test_diagnostic_write_failure_preserves_original_error(self):
        with fixture("CA-no-diag-") as root:
            source = root / "invalid.json"
            source.write_text("not json", encoding="utf-8")
            result = self.backup(root, source, mode="sanitized-json", prelude="function Write-SetupBackupText { throw 'diagnostic destination unavailable' }; ")
            self.assertEqual("BACKUP_INVALID_JSON", result["code"])
            self.assertEqual("", result["diagnostic"])
            self.assertTrue(Path(result["backup"]).is_dir())

    def test_device_paths_are_not_accepted_as_user_input(self):
        result = self.invoke("""
$rejected=0
foreach ($path in @('\\\\?\\C:\\example', '\\\\.\\C:\\example', '\\??\\C:\\example')) {
  try { $null=ConvertTo-SetupBackupIOPath $path } catch { $rejected++ }
}
@{rejected=$rejected} | ConvertTo-Json
""")
        self.assertEqual(3, result["rejected"])

    def test_long_path_junction_and_ancestor_are_still_rejected(self):
        with fixture("CA-link-") as root:
            outside = root / "outside"
            outside.mkdir()
            sentinel = outside / "private.md"
            sentinel.write_text("must not be followed", encoding="utf-8")
            holder = root / "short-holder"
            holder.mkdir()
            deep = root / ("p" * 95) / ("q" * 95) / "long-holder"
            io_path(deep.parent).mkdir(parents=True)
            result = self.invoke(f"""
$link=New-Item -ItemType Junction -Path {quote(holder / 'linked')} -Value {quote(outside)}
[IO.Directory]::Move((ConvertTo-SetupBackupIOPath {quote(holder)}),(ConvertTo-SetupBackupIOPath {quote(deep)}))
$rejected=0
try {{
  foreach ($path in @({quote(deep / 'linked')},{quote(deep / 'linked/private.md')})) {{
    try {{ Assert-SetupPathHasNoReparsePoint -Path $path -Name 'Fixture' }} catch {{ if ($_.Exception.Message -notmatch 'reparse point') {{ throw }}; $rejected++ }}
  }}
}} finally {{ [IO.Directory]::Delete((ConvertTo-SetupBackupIOPath {quote(deep / 'linked')}),$false) }}
@{{rejected=$rejected}} | ConvertTo-Json
""")
            self.assertEqual(2, result["rejected"])
            self.assertEqual("must not be followed", sentinel.read_text("utf-8"))

    def test_metadata_never_overwrites_existing_file(self):
        with fixture("CA-marker-") as root:
            target = root / "backup-manifest.json"
            target.write_text("original marker", encoding="utf-8")
            result = self.invoke(f"""
$failed=$false
try {{ Write-SetupBackupText -Path {quote(target)} -Content 'replacement' }} catch {{ $failed=$true }}
@{{failed=$failed}} | ConvertTo-Json
""")
            self.assertTrue(result["failed"])
            self.assertEqual("original marker", target.read_text("utf-8"))
            self.assertEqual([target], list(root.iterdir()))


if __name__ == "__main__":
    unittest.main()
