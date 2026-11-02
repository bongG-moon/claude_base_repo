"""Real scoped installer lifecycle with isolated Claude/process test boundaries.

The installer, backup, registration, receipt and deletion code are unmodified.
No real Claude account, user profile, plugin cache or machine registry is used.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def ps_command(body):
    prefix = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=New-Object Text.UTF8Encoding($false); "
    encoded = base64.b64encode((prefix + body).encode("utf-16le")).decode("ascii")
    return [str(POWERSHELL), "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@unittest.skipUnless(os.name == "nt", "Windows PowerShell 5.1 installer contract")
class VersionCleanupIntegrationTests(unittest.TestCase):
    def setUp(self):
        # Short workspace path: .NET Framework backup suffixes have MAX_PATH.
        self.temp = tempfile.TemporaryDirectory(prefix=".vc-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "profile"
        self.local = self.profile / "local"
        self.config = self.profile / ".claude"
        self.state = self.root / "personal"
        self.backups = self.root / "backups"
        self.marketplace = self.local / "CompanyAgent-Distribution/marketplace"
        self.versions = self.marketplace / "versions"
        self.scan_log = self.root / "cleanup-scans.txt"
        self.local.mkdir(parents=True)
        self.config.mkdir(parents=True)
        for relative in ("memory/remember.md", "knowledge/personal.md", "learning/patterns.md", "skills/mine/SKILL.md"):
            path = self.state / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"Synthetic personal content must survive exactly.\r\n")
        write_json(self.config / "settings.json", {"model": "existing-model", "mcpServers": {"existing": {"command": "keep-me"}}})
        self.claude = self.root / "fake-claude.ps1"
        self.claude.write_text(r'''
$ErrorActionPreference='Stop'
$config=$env:CLAUDE_CONFIG_DIR
if (-not $config -or -not $config.StartsWith($PSScriptRoot + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Fixture config escaped workspace' }
$plugins=Join-Path $config 'plugins'
$null=New-Item -ItemType Directory -Force -Path $plugins
if ($args[0] -ne 'plugin') { throw 'This fixture supports plugin registration only' }
if ($args[1] -eq 'marketplace') {
    @{ 'company-agent-local'=@{ source=@{source='directory';path=$args[3]}; installLocation=$args[3] } } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $plugins 'known_marketplaces.json') -Encoding UTF8
    exit 0
}
if ($args[1] -eq 'update' -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'fail-update'))) { Write-Output 'CLEANUP_FIXTURE_INSTALL_FAILED'; exit 47 }
$known=Get-Content -LiteralPath (Join-Path $plugins 'known_marketplaces.json') -Raw | ConvertFrom-Json
$market=$known.'company-agent-local'.installLocation
$manifest=Get-Content -LiteralPath (Join-Path $market '.claude-plugin\marketplace.json') -Raw | ConvertFrom-Json
$plugin=[IO.Path]::GetFullPath((Join-Path $market $manifest.plugins[0].source))
$metadata=Get-Content -LiteralPath (Join-Path $plugin '.claude-plugin\plugin.json') -Raw | ConvertFrom-Json
@{version=2;plugins=@{'company-agent@company-agent-local'=@(@{scope='user';installPath=$plugin;version=$metadata.version})}} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $plugins 'installed_plugins.json') -Encoding UTF8
$settingsPath=Join-Path $config 'settings.json'
$settings=Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
$settings | Add-Member -NotePropertyName enabledPlugins -NotePropertyValue @{'company-agent@company-agent-local'=$true} -Force
$settings | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $settingsPath -Encoding UTF8
exit 0
''', encoding="utf-8-sig")
        self.environment = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.config), "PYTHONDONTWRITEBYTECODE": "1",
                            "TEMP": str(self.root), "TMP": str(self.root), "ProgramData": str(self.root / "machine-data")}

    def bundle(self, version):
        root = self.root / ("bundle-" + version)
        plugin = root / "payload/core/plugin"
        write_json(plugin / ".claude-plugin/plugin.json", {"name": "company-agent", "version": version})
        write_json(root / "payload/config/managed.json", {"schemaVersion": 1})
        knowledge = root / "payload/knowledge/base.md"
        knowledge.parent.mkdir(parents=True)
        knowledge.write_text("Synthetic organization knowledge", encoding="utf-8")
        scripts = plugin / "scripts"
        scripts.mkdir()
        # The actual install preflight subprocess executes; only its domain
        # payload is reduced to a deterministic personal-state inventory.
        (scripts / "harness_cli.py").write_text(
            'import json,sys\nfrom pathlib import Path\n'
            'if sys.argv[1:3]==["state","check"]: print("{}")\n'
            'elif sys.argv[1:3]==["skill","inventory"]:\n'
            ' state=Path(sys.argv[sys.argv.index("--state-root")+1])\n'
            ' print(json.dumps({"skills":[],"conflicts":[],"warnings":[],"complete":True,'
            '"preferencesPath":str(state/"config/skill-preferences.json"),"effectivePreferences":{}}))\n'
            'else: sys.exit(89)\n', encoding="utf-8")
        records = [{"path": p.relative_to(root).as_posix(), "length": p.stat().st_size,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                   for p in sorted(root.rglob("*")) if p.is_file()]
        write_json(root / "bundle-manifest.json", {"format": "company-agent-offline-bundle/v1", "coreVersion": version,
                                                   "knowledgeVersion": "1.0.0", "files": records})
        return root

    def install(self, bundle, *, cleanup=None):
        output = self.root / "result.json"
        output.unlink(missing_ok=True)
        version = json.loads((bundle / "bundle-manifest.json").read_text(encoding="utf-8"))["coreVersion"]
        body = "Remove-PSDrive -Name HKCU,HKLM -ErrorAction SilentlyContinue; "
        body += "$env:ProgramFiles=" + quote(self.root / "fake-program-files") + "; "
        body += "$env:CLAUDE_CODE_SUBAGENT_MODEL=$null; $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE=$null; "
        # This observation boundary proves Keep never calls cleanup discovery,
        # and every DeleteUnused scan sees the already committed registration.
        body += "function Get-CimInstance { [CmdletBinding()]param([string]$ClassName); "
        body += "$r=Get-Content -LiteralPath " + quote(self.local / "CompanyAgent/installations/user/company-agent-install.json") + " -Raw|ConvertFrom-Json; "
        body += "if ($r.coreVersion -cne " + quote(version) + ") {throw 'Cleanup ran before commit'}; "
        body += "Add-Content -LiteralPath " + quote(self.scan_log) + " -Value $r.coreVersion; }; "
        action = "Update" if (self.local / "CompanyAgent/installations/user/company-agent-install.json").exists() else "Replace"
        body += "$options=@{Scope='User';NonInteractive=$true;SkipAdminCheck=$true;SkipPrerequisiteCheck=$true;ExistingHarnessAction=" + quote(action) + ";SkillConflictAction='KeepCurrent';"
        for key, value in {"BundleRoot": bundle, "ClaudeConfigRoot": self.config, "InvokingUserProfile": self.profile,
                           "InvokingLocalAppData": self.local, "UserStateRoot": self.state, "BackupRoot": self.backups,
                           "ClaudeCommand": self.claude, "PythonCommand": sys.executable}.items():
            body += key + "=" + quote(value) + ";"
        if cleanup is not None:
            body += "OldVersionAction=" + quote(cleanup) + ";"
        body += "}; try {$r=& " + quote(ROOT / "deploy/Install-ScopedCompanyAgent.ps1") + " @options; $value=@{result=$r}} catch {$value=@{error=$_.Exception.Message}}; "
        body += "$value|ConvertTo-Json -Depth 20|Set-Content -LiteralPath " + quote(output) + " -Encoding UTF8"
        completed = subprocess.run(ps_command(body), env=self.environment, capture_output=True, timeout=90)
        self.assertEqual(0, completed.returncode, completed.stderr.decode("utf-8", errors="replace")[-4000:])
        self.assertTrue(output.exists(), completed.stdout.decode("utf-8", errors="replace")[-3000:])
        return json.loads(output.read_text(encoding="utf-8-sig"))

    def test_real_installer_keep_failure_success_receipts_and_mutex(self):
        first_bundle = self.bundle("9.1.0")
        current_bundle = self.bundle("9.2.0")
        failed_bundle = self.bundle("9.3.0")
        original_personal = hashes(self.state)
        first = self.install(first_bundle)
        self.assertNotIn("error", first, first)
        self.assertEqual("installed", first["result"]["status"])
        self.assertEqual("kept", first["result"]["cleanup"]["status"])
        receipt = self.versions / "9.1.0/cleanup-manifest.json"
        self.assertTrue(receipt.is_file(), "New successful release did not get ownership evidence")
        receipt_before = receipt.read_bytes(), receipt.stat().st_mtime_ns
        second = self.install(first_bundle)
        self.assertEqual("reapplied", second["result"]["status"])
        self.assertEqual(receipt_before, (receipt.read_bytes(), receipt.stat().st_mtime_ns), "Reapply re-sealed existing files")
        updated = self.install(current_bundle)
        self.assertEqual("updated", updated["result"]["status"])
        self.assertTrue(receipt.exists(), "Default Keep deleted the previous version")
        self.assertFalse(self.scan_log.exists(), "Default Keep scanned cleanup candidates")

        # A competing process owns the real named mutex. Failure must precede
        # backups and snapshots as well as mutation; all existing bytes survive.
        ready, release = self.root / "lock-ready", self.root / "lock-release"
        body = ". " + quote(ROOT / "deploy/CompanyAgent.Cleanup.ps1") + "; "
        body += "$lease=Enter-CompanyAgentVersionMaintenance -MarketplaceRoot " + quote(self.marketplace) + "; "
        body += "try {[IO.File]::WriteAllText(" + quote(ready) + ",'ready'); $deadline=[DateTime]::UtcNow.AddSeconds(30); "
        body += "while (-not (Test-Path -LiteralPath " + quote(release) + ") -and [DateTime]::UtcNow -lt $deadline) {Start-Sleep -Milliseconds 100}} finally {Exit-CompanyAgentVersionMaintenance $lease}"
        holder = subprocess.Popen(ps_command(body), env=self.environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and holder.poll() is None and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(ready.exists(), "Isolated mutex holder did not start")
            before_locked = hashes(self.profile), hashes(self.state), hashes(self.backups)
            locked = self.install(current_bundle, cleanup="DeleteUnused")
            self.assertIn("Another Company Agent", locked.get("error", ""), locked)
            self.assertEqual(before_locked, (hashes(self.profile), hashes(self.state), hashes(self.backups)),
                             "Mutex contention wrote or rolled back somebody else's files")
            self.assertFalse(self.scan_log.exists())
        finally:
            release.write_text("release", encoding="utf-8")
            holder.communicate(timeout=10)

        (self.root / "fail-update").write_text("fixture", encoding="utf-8")
        failed = self.install(failed_bundle, cleanup="DeleteUnused")
        self.assertIn("CLEANUP_FIXTURE_INSTALL_FAILED", failed.get("error", ""), failed)
        self.assertTrue(receipt.exists(), "Failed update cleaned an unused version")
        self.assertFalse((self.versions / "9.3.0").exists(), "Failed installation left a sealed version")
        self.assertFalse(self.scan_log.exists(), "Failed install invoked cleanup discovery")
        registration = self.local / "CompanyAgent/installations/user/company-agent-install.json"
        self.assertEqual("9.2.0", json.loads(registration.read_text(encoding="utf-8-sig"))["coreVersion"])
        (self.root / "fail-update").unlink()

        cleaned = self.install(current_bundle, cleanup="DeleteUnused")
        self.assertNotIn("error", cleaned, cleaned)
        self.assertEqual("reapplied", cleaned["result"]["status"])
        cleanup = cleaned["result"]["cleanup"]
        self.assertEqual("completed", cleanup["status"], cleanup)
        self.assertFalse((self.versions / "9.1.0").exists())
        self.assertGreater(cleanup["bytesFreed"], 0)
        self.assertTrue((self.versions / "9.2.0/cleanup-manifest.json").is_file())
        scans = self.scan_log.read_text(encoding="utf-8-sig").splitlines()
        self.assertTrue(scans)
        self.assertEqual({"9.2.0"}, set(scans), "Cleanup ran before the new registration committed")

        # Pre-existing unsealed installs must not be attested retroactively.
        current_receipt = self.versions / "9.2.0/cleanup-manifest.json"
        current_receipt.unlink()
        scan_bytes = self.scan_log.read_bytes()
        reapplied = self.install(current_bundle)
        self.assertEqual("kept", reapplied["result"]["cleanup"]["status"])
        self.assertFalse(current_receipt.exists(), "Existing unknown files were re-sealed")
        self.assertEqual(scan_bytes, self.scan_log.read_bytes(), "Default Keep scanned during reapply")
        self.assertEqual(original_personal, hashes(self.state))
        settings = json.loads((self.config / "settings.json").read_text(encoding="utf-8-sig"))
        self.assertEqual("existing-model", settings["model"])
        self.assertEqual({"existing": {"command": "keep-me"}}, settings["mcpServers"])


if __name__ == "__main__":
    unittest.main()
