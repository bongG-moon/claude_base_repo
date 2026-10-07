"""Compare installed Read hook with its unchanged PowerShell fallback.

Only synthetic hook JSON and an isolated registration are used. Does not start
Claude, call a model, open a document, or change the user's configuration.
"""
from __future__ import annotations

import argparse
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
from test_read_hook import ReadHookIntegrationTests, payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=15)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 3 <= args.samples <= 100:
        parser.error('--samples must be between 3 and 100')
    fixture = ReadHookIntegrationTests('test_real_active_image_and_unrelated_scope_parity')
    fixture.setUp()
    try:
        env = dict(os.environ, CA_BENCH_SOURCE=str(ROOT), CA_BENCH_PLUGIN=str(fixture.plugin),
                   CA_BENCH_ROOT=str(fixture.root), CA_BENCH_PYTHON=sys.executable,
                   PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
                   CLAUDE_CONFIG_DIR=str(fixture.root / 'isolated-profile'))
        env.pop('CLAUDE_ENV_FILE', None)
        setup = """$ErrorActionPreference='Stop'
. (Join-Path $env:CA_BENCH_SOURCE 'deploy/Setup-CompanyAgent.ps1') -FunctionsOnly
. (Join-Path $env:CA_BENCH_SOURCE 'deploy/HarnessReplacement.ps1')
. (Join-Path $env:CA_BENCH_SOURCE 'deploy/CompanyAgent.ReadHook.ps1')
$launcher = Join-Path $env:CA_BENCH_ROOT 'read-hook.cmd'
$snapshot = New-CompanyAgentReadHookSnapshot -LauncherPath $launcher -BackupPath (Join-Path $env:CA_BENCH_ROOT 'backup')
Set-CompanyAgentReadHookLauncher -Snapshot $snapshot -PythonCommand $env:CA_BENCH_PYTHON -PluginRoot $env:CA_BENCH_PLUGIN
if (-not (Set-CompanyAgentReadHookRegistration -PluginRoot $env:CA_BENCH_PLUGIN -LauncherPath $launcher)) { throw 'Read hook not optimized' }
"""
        prepared = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', setup],
                                  env=env, capture_output=True, text=True, encoding='utf-8', errors='backslashreplace', timeout=30)
        if prepared.returncode:
            raise RuntimeError(prepared.stderr or prepared.stdout)
        hooks = json.loads((fixture.plugin / 'hooks/hooks.json').read_text(encoding='utf-8-sig'))
        hook = next(x for x in hooks['hooks']['PreToolUse'] if x['matcher'] == '^Read$')['hooks'][0]
        commands = {
            'before': ['powershell.exe', '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                       str(fixture.plugin / 'scripts/Invoke-CompanyAgent.ps1'), '-Mode', 'Hook', '-Event', 'PreToolUse'],
            'after': [hook['command'], *hook['args']],
        }
        cases = [('text_without_vision', '', 'fixture.md'),
                 ('text_with_vision', 'HCP-Vision-Latest', 'fixture.md'),
                 ('image_handoff_with_vision', 'HCP-Vision-Latest', 'fixture.png')]
        timings = {}
        for case, model, filename in cases:
            case_env = {**env, 'ANTHROPIC_CUSTOM_MODEL_OPTION': model}
            request = json.dumps(payload(str(fixture.project / filename), cwd=str(fixture.project)), ensure_ascii=False)
            samples = {name: [] for name in commands}
            for index in range(args.samples + 3):
                names = list(commands) if index % 2 == 0 else list(reversed(commands))
                outputs = {}
                for name in names:
                    started = time.perf_counter()
                    result = subprocess.run(commands[name], input=request, env=case_env, cwd=fixture.project,
                                            text=True, encoding='utf-8', capture_output=True, timeout=30)
                    elapsed = round((time.perf_counter() - started) * 1000, 2)
                    if result.returncode or result.stderr:
                        raise RuntimeError(f'{case}/{name}: {result.returncode}, {result.stderr}')
                    outputs[name] = json.loads(result.stdout)
                    if index >= 3:
                        samples[name].append(elapsed)
                if outputs['before'] != outputs['after']:
                    raise RuntimeError(f'{case}: hook decisions changed')
            timings[case] = {name: {'median_ms': round(statistics.median(values), 2),
                                     'min_ms': min(values), 'max_ms': max(values), 'samples_ms': values}
                             for name, values in samples.items()}
        report = {'platform': platform.platform(), 'python': sys.version.split()[0],
                  'samples_per_variant': args.samples, 'warmups': 3, 'alternating_order': True,
                  'decision_parity': True, 'fresh_hook_process_each_sample': True,
                  'limits': ['Synthetic isolated registration; no model or actual Read tool execution.',
                             'OS cache not cleared; timing is not whole-task latency or token usage.',
                             'Image handoffs intentionally retain the existing PowerShell checks.'],
                  'source_sha256': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                    for path in ('company-agent-plugin/scripts/read_hook.py',
                                                 'deploy/CompanyAgent.ReadHook.ps1',
                                                 'company-agent-plugin/scripts/Invoke-CompanyAgent.ps1')},
                  'timings': timings}
        if args.output:
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        fixture.tearDown()


if __name__ == '__main__':
    main()
