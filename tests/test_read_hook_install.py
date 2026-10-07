"""Windows launcher fixtures; never install or start Claude or read user state."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SYSTEM = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32'
POWERSHELL = SYSTEM / 'WindowsPowerShell/v1.0/powershell.exe'
NODE = os.environ.get('COMPANY_AGENT_TEST_NODE') or shutil.which('node')
HOOK_ARGS = ['-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
             '${CLAUDE_PLUGIN_ROOT}/scripts/Invoke-CompanyAgent.ps1',
             '-Mode', 'Hook', '-Event', 'PreToolUse']


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name == 'nt', 'Windows CMD/PowerShell execution contract')
class ReadHookInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime_temp = tempfile.TemporaryDirectory(prefix='Read runtime fixture ')
        cls.addClassCleanup(cls.runtime_temp.cleanup)
        cls.pythons = []
        for name in ('Old Python 한글 %READ_PATH% & !READ_PATH!', 'New Python 한글 %READ_PATH% & !READ_PATH!'):
            root = Path(cls.runtime_temp.name) / name
            subprocess.run([sys.executable, '-I', '-B', '-m', 'venv', '--without-pip', str(root)],
                           check=True, capture_output=True, timeout=60)
            cls.pythons.append(root / 'Scripts/python.exe')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Read hook 한글 & !READ_PATH! ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugin = self.root / 'plugin 한글 %READ_PATH% & !READ_PATH!'
        (self.plugin / 'scripts').mkdir(parents=True)
        (self.plugin / 'hooks').mkdir()
        self.entry = self.plugin / 'scripts/read_hook.py'
        self.entry.write_text(
            'import json,sys\n'
            'raw=sys.stdin.read()\n'
            'print(json.dumps({"python":sys.executable,"stdin":raw},ensure_ascii=False))\n'
            'sys.exit(json.loads(raw).get("exit",0))\n', encoding='utf-8')
        (self.plugin / 'scripts/Invoke-CompanyAgent.ps1').write_text(
            'param([string]$Mode,[string]$Event)\n'
            '[Console]::InputEncoding=New-Object Text.UTF8Encoding($false)\n'
            '[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)\n'
            '$raw=[Console]::In.ReadToEnd()\n'
            '[Console]::Out.WriteLine((@{fallback=$true;stdin=$raw;event=$Event}|ConvertTo-Json -Compress))\n',
            encoding='utf-8-sig')
        self.hooks_path = self.plugin / 'hooks/hooks.json'
        self.hooks = {'hooks': {'PreToolUse': [
            {'matcher': '^Read$', 'hooks': [{'type': 'command', 'command': 'powershell.exe',
                                          'args': HOOK_ARGS, 'timeout': 5}]},
            {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'unchanged.exe'}]}],
            'SessionStart': [{'hooks': [{'type': 'command', 'command': 'unchanged.exe'}]}]}}
        self.hooks_path.write_text(json.dumps(self.hooks), encoding='utf-8')
        self.metadata = self.plugin / 'company-agent-install.json'
        self.metadata.write_bytes(b'\xef\xbb\xbf{ "immutable": true }\r\n')
        self.launcher = self.root / 'read-hook.cmd'
        self.backup = self.root / 'backup'
        self.payload = json.dumps({'tool_name': 'Read', 'tool_input': {'file_path': '한글 & !%.txt'}}, ensure_ascii=False)
        self.environment = {**os.environ, 'READ_PATH': 'POISON', 'COMPANY_AGENT_PYTHON': 'unapproved.exe',
                            'ERRORLEVEL': '91'}

    def ps(self, body):
        prefix = '$ErrorActionPreference="Stop"; '
        prefix += '[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false); '
        for path, args in [('Setup-CompanyAgent.ps1', ' -FunctionsOnly'),
                           ('HarnessReplacement.ps1', ''), ('CompanyAgent.ReadHook.ps1', '')]:
            prefix += '. ' + ps_quote(ROOT / 'deploy' / path) + args + '; '
        encoded = base64.b64encode((prefix + body).encode('utf-16le')).decode('ascii')
        result = subprocess.run([str(POWERSHELL), '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-EncodedCommand', encoded], capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr.decode('utf-8', errors='replace')[-6000:]
                         + result.stdout.decode('utf-8', errors='replace')[-3000:])
        return result

    def generate(self, python=None):
        self.ps('$snapshot=New-CompanyAgentReadHookSnapshot -LauncherPath ' + ps_quote(self.launcher)
                + ' -BackupPath ' + ps_quote(self.backup) + '; '
                + 'Set-CompanyAgentReadHookLauncher -Snapshot $snapshot -PythonCommand '
                + ps_quote(python or self.pythons[0]) + ' -PluginRoot ' + ps_quote(self.plugin) + '; '
                + '$null=Set-CompanyAgentReadHookRegistration -PluginRoot ' + ps_quote(self.plugin)
                + ' -LauncherPath ' + ps_quote(self.launcher))
        return json.loads(self.hooks_path.read_text(encoding='utf-8-sig'))['hooks']['PreToolUse'][0]['hooks'][0]

    def invoke(self, hook, payload=None, node=False):
        payload = self.payload if payload is None else payload
        if node:
            script = ('const {spawnSync}=require("child_process");const [h,p]=JSON.parse(process.argv[1]);'
                      'const r=spawnSync(h.command,h.args,{shell:false,input:p,encoding:"utf8"});'
                      'process.stdout.write(JSON.stringify({status:r.status,stdout:r.stdout,stderr:r.stderr,error:r.error?.message}));')
            result = subprocess.run([NODE, '-e', script, json.dumps([hook, payload], ensure_ascii=False)],
                                    capture_output=True, check=True, env=self.environment, timeout=30)
            value = json.loads(result.stdout.decode('utf-8'))
            self.assertIsNone(value.get('error'), value)
            return value['status'], value['stdout']
        result = subprocess.run([hook['command'], *hook['args']], input=payload.encode('utf-8'),
                                capture_output=True, env=self.environment, timeout=30)
        return result.returncode, result.stdout.decode('utf-8')

    def test_launcher_exec_form_handles_unicode_metacharacters_and_preserves_other_hooks(self):
        metadata = self.metadata.read_bytes()
        hook = self.generate()
        code, output = self.invoke(hook)
        self.assertEqual(0, code)
        result = json.loads(output)
        self.assertEqual(str(self.pythons[0]), result['python'])
        self.assertEqual(self.payload, result['stdin'])
        actual = json.loads(self.hooks_path.read_text(encoding='utf-8-sig'))
        self.assertEqual(self.hooks['hooks']['PreToolUse'][1], actual['hooks']['PreToolUse'][1])
        self.assertEqual(self.hooks['hooks']['SessionStart'], actual['hooks']['SessionStart'])
        self.assertEqual(metadata, self.metadata.read_bytes())
        self.assertIn(b'%%READ_PATH%%', self.launcher.read_bytes())

    @unittest.skipUnless(NODE, 'Node is needed to exercise the actual exec-form spawn quoting')
    def test_node_spawn_cached_hook_uses_new_runtime_after_reapply(self):
        hook = self.generate()
        code, output = self.invoke(hook, node=True)
        self.assertEqual(0, code)
        self.assertEqual(str(self.pythons[0]), json.loads(output)['python'])
        old_bytes = self.launcher.read_bytes()
        old_hooks, old_metadata = self.hooks_path.read_bytes(), self.metadata.read_bytes()
        self.ps('$snapshot=New-CompanyAgentReadHookSnapshot -LauncherPath ' + ps_quote(self.launcher)
                + ' -BackupPath ' + ps_quote(self.root / 'reapply-backup') + '; '
                + 'Set-CompanyAgentReadHookLauncher -Snapshot $snapshot -PythonCommand '
                + ps_quote(self.pythons[1]) + ' -PluginRoot ' + ps_quote(self.plugin))
        self.assertEqual(old_bytes, (self.root / 'reapply-backup/company-agent/read-hook.before-install.cmd').read_bytes())
        self.assertEqual(old_hooks, self.hooks_path.read_bytes())
        self.assertEqual(old_metadata, self.metadata.read_bytes())
        code, output = self.invoke(hook, node=True)
        self.assertEqual(0, code)
        self.assertEqual(str(self.pythons[1]), json.loads(output)['python'])

    def test_missing_runtime_falls_back_before_consuming_input(self):
        hook = self.generate(python=self.root / 'Missing Python %READ_PATH% & !READ_PATH!/python.exe')
        code, output = self.invoke(hook)
        self.assertEqual(0, code)
        result = json.loads(output)
        self.assertTrue(result['fallback'])
        self.assertEqual(self.payload, result['stdin'])
        self.assertEqual('PreToolUse', result['event'])

    def test_missing_entry_falls_back_before_consuming_input(self):
        hook = self.generate()
        self.entry.unlink()
        code, output = self.invoke(hook)
        self.assertEqual(0, code)
        self.assertEqual({'fallback': True, 'stdin': self.payload, 'event': 'PreToolUse'}, json.loads(output))

    def test_application_failure_is_not_retried_through_powershell(self):
        hook = self.generate()
        payload = json.dumps({'exit': 37})
        code, output = self.invoke(hook, payload)
        self.assertEqual(37, code)
        result = json.loads(output)
        self.assertNotIn('fallback', result)
        self.assertEqual(payload, result['stdin'])

    def test_unsupported_launcher_paths_keep_original_powershell_hook(self):
        before = self.hooks_path.read_bytes()
        for launcher in (self.root / '%READ_PATH%/read-hook.cmd', self.root / 'caret^/read-hook.cmd',
                         Path(r'C:\no-space&fixture\read-hook.cmd')):
            with self.subTest(launcher=launcher):
                result = self.ps('Set-CompanyAgentReadHookRegistration -PluginRoot ' + ps_quote(self.plugin)
                                 + ' -LauncherPath ' + ps_quote(launcher))
                self.assertEqual('False', result.stdout.decode('utf-8').strip())
                self.assertEqual(before, self.hooks_path.read_bytes())

    def test_rollback_restores_exact_bytes_and_removes_new_launcher(self):
        for previous in (None, b'\xef\xbb\xbf@rem Exact previous launcher\r\n\r\n'):
            with self.subTest(previous=previous):
                if previous is not None:
                    self.launcher.write_bytes(previous)
                self.ps('$snapshot=New-CompanyAgentReadHookSnapshot -LauncherPath ' + ps_quote(self.launcher)
                        + ' -BackupPath ' + ps_quote(self.backup) + '; '
                        + 'Set-CompanyAgentReadHookLauncher -Snapshot $snapshot -PythonCommand '
                        + ps_quote(self.pythons[0]) + ' -PluginRoot ' + ps_quote(self.plugin) + '; '
                        + 'Restore-CompanyAgentReadHookLauncher -Snapshot $snapshot')
                if previous is None:
                    self.assertFalse(self.launcher.exists())
                else:
                    self.assertEqual(previous, self.launcher.read_bytes())
                    self.assertEqual(previous, (self.backup / 'company-agent/read-hook.before-install.cmd').read_bytes())

    def test_installer_reapply_failure_restores_runtime_selection_and_launcher_together(self):
        # Installer release/backup suffixes must fit .NET Framework's MAX_PATH
        # even when the test runner's default temporary root is deeply nested.
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='.read-install-', dir=ROOT)))
        bundle = self.root / 'bundle'
        plugin = bundle / 'payload/core/plugin'
        shutil.copytree(self.plugin, plugin)
        (plugin / '.claude-plugin').mkdir()
        (plugin / '.claude-plugin/plugin.json').write_text('{"name":"company-agent","version":"9.9.9"}', encoding='utf-8')
        (bundle / 'payload/knowledge').mkdir()
        (bundle / 'payload/config').mkdir()
        (bundle / 'payload/config/managed.json').write_text('{}', encoding='utf-8')
        (bundle / 'bundle-manifest.json').write_text(
            json.dumps({'coreVersion': '9.9.9', 'knowledgeVersion': '1.0.0', 'files': []}), encoding='utf-8')
        # Only installation preflight is stubbed. The real installer, backup,
        # registration snapshots, release creation and catch/rollback all run.
        (plugin / 'scripts/harness_cli.py').write_text(
            'import json,sys\nfrom pathlib import Path\n'
            'if sys.argv[1:3]==["state","check"]: print("{}")\n'
            'elif sys.argv[1:3]==["skill","inventory"]:\n'
            ' state=Path(sys.argv[sys.argv.index("--state-root")+1])\n'
            ' print(json.dumps({"skills":[],"conflicts":[],"warnings":[],"complete":True,'
            '"preferencesPath":str(state/"config/skill-preferences.json"),"effectivePreferences":{}}))\n'
            'else: sys.exit(89)\n', encoding='utf-8')
        profile = self.root / 'profile'
        local = profile / 'AppData/Local'
        config = profile / '.claude'
        local.mkdir(parents=True)
        config.mkdir()
        fake_claude = self.root / 'fake-claude.ps1'
        fake_claude.write_text(r'''
$ErrorActionPreference='Stop'
$config=$env:CLAUDE_CONFIG_DIR
if (-not $config -or -not $config.StartsWith($PSScriptRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Fixture config escaped test root' }
$plugins=Join-Path $config 'plugins'
$null=New-Item -ItemType Directory -Force -Path $plugins
if ($args[0] -ne 'plugin') { throw 'Only plugin registration is supported by this fixture' }
if ($args[1] -eq 'marketplace') {
    @{ 'company-agent-local'=@{ source=@{path=$args[3]}; installLocation=$args[3] } } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $plugins 'known_marketplaces.json') -Encoding UTF8
    exit 0
}
if ($args[1] -eq 'update' -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'fail-update'))) { Write-Output 'READ_HOOK_FIXTURE_FAILURE'; exit 47 }
$known=Get-Content -LiteralPath (Join-Path $plugins 'known_marketplaces.json') -Raw | ConvertFrom-Json
$market=$known.'company-agent-local'.installLocation
$manifest=Get-Content -LiteralPath (Join-Path $market '.claude-plugin\marketplace.json') -Raw | ConvertFrom-Json
$plugin=Join-Path $market $manifest.plugins[0].source
$metadata=Get-Content -LiteralPath (Join-Path $plugin '.claude-plugin\plugin.json') -Raw | ConvertFrom-Json
@{version=2;plugins=@{'company-agent@company-agent-local'=@(@{scope='user';installPath=$plugin;version=$metadata.version})}} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $plugins 'installed_plugins.json') -Encoding UTF8
@{enabledPlugins=@{'company-agent@company-agent-local'=$true}} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $config 'settings.json') -Encoding UTF8
exit 0
''', encoding='utf-8-sig')
        result_path = self.root / 'installer-result.json'
        body = '$env:ProgramFiles=' + ps_quote(self.root / 'fake-program-files') + '; '
        # Remove registry provider drives in this child process so Windows
        # policy checks cannot read the host account/machine policy fixtures.
        body += 'Remove-PSDrive -Name HKCU,HKLM -ErrorAction SilentlyContinue; '
        body += '$env:CLAUDE_CODE_SUBAGENT_MODEL=$null; $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE=$null; '
        body += '$options=@{Scope="User";NonInteractive=$true;SkipAdminCheck=$true;SkipPrerequisiteCheck=$true;SkipBundleVerification=$true;ExistingHarnessAction="Replace";SkillConflictAction="KeepCurrent";'
        for key, value in [('BundleRoot', bundle), ('ClaudeConfigRoot', config), ('InvokingUserProfile', profile),
                           ('InvokingLocalAppData', local), ('BackupRoot', self.root / 'installer-backups'),
                           ('ClaudeCommand', fake_claude), ('PythonCommand', self.pythons[0])]:
            body += key + '=' + ps_quote(value) + ';'
        body += '}; $setup=' + ps_quote(ROOT / 'deploy/Install-ScopedCompanyAgent.ps1') + '; '
        body += '$first=& $setup @options; $firstRecord=Read-CompanyAgentJson -Path $first.registrationPath; '
        body += '$firstRelease=Split-Path -Parent $firstRecord.knowledgeBaseRoot; '
        body += '$immutableBefore=@("plugin/company-agent-install.json","plugin/hooks/hooks.json"|ForEach-Object{[Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $firstRelease $_)))}); '
        body += '$options.PythonCommand=' + ps_quote(self.pythons[1]) + '; '
        body += '$second=& $setup @options; $record=Read-CompanyAgentJson -Path $second.registrationPath; '
        body += '$release=Split-Path -Parent $record.knowledgeBaseRoot; '
        body += '$paths=@((Join-Path $release "runtime-selection.json"),(Join-Path $release "read-hook.cmd"),(Join-Path $release "plugin/company-agent-install.json"),(Join-Path $release "plugin/hooks/hooks.json")); '
        body += '$before=@($paths|ForEach-Object{[Convert]::ToBase64String([IO.File]::ReadAllBytes($_))}); '
        body += '[IO.File]::WriteAllText(' + ps_quote(self.root / 'fail-update') + ',"fixture"); '
        body += '$options.PythonCommand=' + ps_quote(self.pythons[0]) + '; $failure=$null; '
        body += 'try {$null=& $setup @options} catch {$failure=$_.Exception.Message}; '
        body += '$after=@($paths|ForEach-Object{[Convert]::ToBase64String([IO.File]::ReadAllBytes($_))}); '
        body += '@{first=$first.status;second=$second.status;failure=$failure;before=$before;after=$after;immutableBefore=$immutableBefore;release=$release}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath ' + ps_quote(result_path) + ' -Encoding UTF8'
        self.ps(body)
        result = json.loads(result_path.read_text(encoding='utf-8-sig'))
        self.assertEqual('installed', result['first'])
        self.assertEqual('reapplied', result['second'])
        self.assertIn('READ_HOOK_FIXTURE_FAILURE', result['failure'])
        self.assertEqual(result['before'], result['after'])
        self.assertEqual(result['immutableBefore'], result['before'][2:])
        release = Path(result['release'])
        self.assertEqual(str(self.pythons[1]), json.loads((release / 'runtime-selection.json').read_text(encoding='utf-8-sig'))['pythonCommand'])
        hook = json.loads((release / 'plugin/hooks/hooks.json').read_text(encoding='utf-8-sig'))['hooks']['PreToolUse'][0]['hooks'][0]
        code, output = self.invoke(hook)
        self.assertEqual(0, code)
        self.assertEqual(str(self.pythons[1]), json.loads(output)['python'])


if __name__ == '__main__':
    unittest.main()
