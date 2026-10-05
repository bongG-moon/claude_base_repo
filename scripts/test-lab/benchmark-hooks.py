"""Local isolated before/after hook timings. No Claude/model/Driver calls.

The old wrapper is reconstructed from its unchanged registration/path-check
prefix and the audited pre-change launch tail below. Only temporary fixture
copies are changed. The state baseline removes the exact new early rejection.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
sys.dont_write_bytecode = True
import test_native_runtime as fixtures

BASELINE_TAIL = r'''$python = $null
$probed = @{}
$launcherEnvironment = @{}
foreach ($name in @('PYLAUNCHER_ALLOW_INSTALL', 'PYLAUNCHER_ALWAYS_INSTALL', 'PYTHON_MANAGER_AUTOMATIC_INSTALL')) {
    $launcherEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    [Environment]::SetEnvironmentVariable('PYLAUNCHER_ALLOW_INSTALL', $null, 'Process')
    [Environment]::SetEnvironmentVariable('PYLAUNCHER_ALWAYS_INSTALL', $null, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHON_MANAGER_AUTOMATIC_INSTALL', 'false', 'Process')
foreach ($candidate in $candidates) {
    if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
    $info = Get-Command $candidate -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $info -or [IO.Path]::GetExtension($info.Source) -ine '.exe') { continue }
    $item = Get-Item -LiteralPath $info.Source -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -and $item.Length -eq 0) { continue }
    if ($probed.ContainsKey($info.Source)) { continue }
    $probed[$info.Source] = $true
    $prefix = @()
    if ([IO.Path]::GetFileNameWithoutExtension($info.Source) -ieq 'py') { $prefix = @('-3') }
    # -I ignores PYTHONIOENCODING. Pin UTF-8 explicitly so a Korean or emoji
    # interpreter path is decoded correctly by this UTF-8 PowerShell wrapper.
    try {
        $probe = & $info.Source @prefix -I -X utf8 -B -c 'import sys; print(sys.executable); sys.exit(0 if sys.version_info >= (3,11) and sys.version_info.major == 3 else 1)' 2>$null
        $probeExit = $LASTEXITCODE
    }
    catch { continue }
    if ($probeExit -eq 0 -and -not [string]::IsNullOrWhiteSpace(($probe -join ''))) {
        $python = [string](@($probe)[-1]); break
    }
}
}
finally {
    foreach ($name in $launcherEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $launcherEnvironment[$name], 'Process') }
}
if ([string]::IsNullOrWhiteSpace($python)) {
    [Console]::Error.WriteLine('Company Agent needs the company-approved Python 3.11+ already installed on this PC. Check its path and execution permission, then rerun Install-CompanyAgent.cmd to select it. Python is not downloaded or installed automatically.')
    exit 2
}
$env:COMPANY_AGENT_PYTHON = $python
$entry = Join-Path $PSScriptRoot 'native_entry.py'
if ($Mode -eq 'Hook') {
    # The only in-memory copy; never persist the input prompt/transcript payload.
    $payload = [Console]::In.ReadToEnd()
    $payload | & $python -X utf8 $entry --event $Event
} else {
    & $python -X utf8 $entry --cli @CliArguments
}
exit $LASTEXITCODE
'''

EARLY_REJECTION = '''    # Only the accepted bare names or an exact absolute runtime path can match.
    # Ordinary commands (pwd, git, etc.) cannot pass _same_absolute_path, so do
    # not repeatedly walk PATH for every bookkeeping classification of them.
    if not Path(value).is_absolute():
        return False
'''


def main():
    variants = {}
    try:
        for name in ('before', 'after'):
            fixture = fixtures.NativePowerShellTests(methodName='test_native_permission_request_allows_only_registered_metadata_command')
            fixture.setUp()
            variants[name] = fixture
            if name == 'before':
                wrapper = fixture.plugin / 'scripts/Invoke-CompanyAgent.ps1'
                source = wrapper.read_text(encoding='utf-8')
                prefix, tail = source.split('$probed = @{}', 1)
                assert '$python = $null' not in prefix
                wrapper.write_text(prefix + BASELINE_TAIL, encoding='utf-8')
                state_file = fixture.plugin / 'scripts/company_agent/state.py'
                state_text = state_file.read_text(encoding='utf-8')
                assert state_text.count(EARLY_REJECTION) == 1
                state_file.write_text(state_text.replace(EARLY_REJECTION, ''), encoding='utf-8')
            fixtures.begin_turn('perf-isolated', 'LARGE', False, [], root=Path(fixture.record['userStateRoot']))
        samples = {}
        cases = [('pre-unrelated-agent', 'PreToolUse', 'Agent'), ('post-read', 'PostToolUse', 'Read'),
                 ('post-readonly-shell', 'PostToolUse', 'Bash')]
        for case, event, tool in cases:
            samples[case] = {name: {mode: [] for mode in ('direct_python', 'powershell_wrapper')} for name in variants}
            for iteration in range(5):
                names = list(variants) if iteration % 2 == 0 else list(reversed(variants))
                for name in names:
                    fixture = variants[name]
                    env = dict(os.environ, COMPANY_AGENT_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE='1',
                               PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                               CLAUDE_CONFIG_DIR=str(fixture.root / 'isolated-claude-config'),
                               COMPANY_AGENT_USER_STATE=fixture.record['userStateRoot'])
                    env.pop('CLAUDE_ENV_FILE', None)
                    tool_input = ({'subagent_type': 'general-purpose', 'prompt': 'fixture'} if tool == 'Agent' else
                                  {'file_path': str(fixture.project / 'fixture.txt')} if tool == 'Read' else {'command': 'pwd'})
                    payload = json.dumps({'cwd': str(fixture.project), 'session_id': 'perf-isolated',
                                          'hook_event_name': event, 'tool_name': tool, 'tool_input': tool_input,
                                          'tool_response': {'content': 'fixture', 'stdout': str(fixture.project), 'exit_code': 0}})
                    commands = {
                        'direct_python': [sys.executable, '-X', 'utf8', str(fixture.plugin / 'scripts/native_entry.py'), '--event', event],
                        'powershell_wrapper': ['powershell.exe', '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                               str(fixture.plugin / 'scripts/Invoke-CompanyAgent.ps1'), '-Mode', 'Hook', '-Event', event]}
                    modes = list(commands) if iteration % 2 == 0 else list(reversed(commands))
                    for mode in modes:
                        started = time.perf_counter()
                        result = subprocess.run(commands[mode], input=payload, text=True, encoding='utf-8',
                                                capture_output=True, cwd=fixture.project, env=env, timeout=30)
                        elapsed = round((time.perf_counter() - started) * 1000, 2)
                        assert result.returncode == 0 and not result.stderr and json.loads(result.stdout) == {}, result
                        samples[case][name][mode].append(elapsed)
        summary = {}
        for case, variants_samples in samples.items():
            summary[case] = {name: {mode: {'median_ms': round(statistics.median(values), 2),
                                          'first_ms': values[0], 'later4_median_ms': round(statistics.median(values[1:]), 2)}
                                    for mode, values in modes.items()} for name, modes in variants_samples.items()}
        hashes = {name: {rel: hashlib.sha256((fixture.plugin / rel).read_bytes()).hexdigest()
                         for rel in ('scripts/Invoke-CompanyAgent.ps1', 'scripts/company_agent/state.py')}
                  for name, fixture in variants.items()}
        report = {'python': sys.version, 'platform': platform.platform(), 'samples_per_case': 5,
                  'fresh_process_each_sample': True, 'os_cache_flushed': False, 'fixture': 'NativePowerShellTests',
                  'limitations': ['Local synthetic hook payloads; no Claude/model/Driver launched.',
                                  'Project fixture registration has no native Claude inventory.',
                                  'First invocation is not a forced cold OS cache sample.',
                                  'Before reconstructs audited wrapper tail and removes state early rejection; other source is identical.'],
                  'source_sha256': hashes, 'summary': summary, 'samples_ms': samples}
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        for fixture in reversed(list(variants.values())):
            fixture.tearDown()


if __name__ == '__main__':
    main()
