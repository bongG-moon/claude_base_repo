[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('scoped', 'environment', 'preservation')][string] $Group,
    [string] $ClaudeCommand = 'claude',
    [string] $PythonCommand = 'python',
    [string] $BundleZip,
    [string] $UpdateBundleZip
)

# Development-checkout tests only. The existing suites use owned temporary
# profiles and never install into the employee's actual Claude configuration.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$shellPath = Join-Path ([Environment]::GetFolderPath('System')) 'WindowsPowerShell\v1.0\powershell.exe'
$claudePath = (Get-Command $ClaudeCommand -CommandType Application,ExternalScript -ErrorAction Stop | Select-Object -First 1).Source
$pythonPath = (Get-Command $PythonCommand -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$runId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6)
$outputDirectory = Join-Path $root ('build\validation\' + $runId + '-' + $Group)
$null = New-Item -ItemType Directory -Path $outputDirectory
$utf8 = New-Object Text.UTF8Encoding($false)
$suite = @()
switch ($Group) {
    'scoped' {
        $bundle = if ($BundleZip) { (Resolve-Path -LiteralPath $BundleZip).Path } else { Join-Path $root 'dist\company-agent-1.3.3-2026.09.03.zip' }
        if (-not (Test-Path -LiteralPath $bundle -PathType Leaf)) { throw 'Build the current installer first or provide -BundleZip.' }
        $suite = @(
            @{ name = 'Test-ScopedInstallSmoke'; args = @('-BundleZip', $bundle, '-ClaudeCommand', $claudePath, '-PythonCommand', $pythonPath) },
            @{ name = 'Test-ScopedInstallSmoke-CP949'; script = 'Test-ScopedInstallSmoke'; args = @('-BundleZip', $bundle, '-ClaudeCommand', $claudePath, '-PythonCommand', $pythonPath, '-LegacyEncoding') }
        )
        if ($UpdateBundleZip) {
            $updateBundle = (Resolve-Path -LiteralPath $UpdateBundleZip).Path
            foreach ($test in $suite) { $test.args += @('-UpdateBundleZip', $updateBundle) }
        }
    }
    'environment' {
        $suite = @(
            @{ name = 'Test-UserContext'; args = @() },
            @{ name = 'Test-ScopedUserContext'; args = @() },
            @{ name = 'Test-ClaudeDiscovery'; args = @() },
            @{ name = 'Test-ExternalPython'; args = @('-PythonCommand', $pythonPath) },
            @{ name = 'Test-PluginCompatibility'; args = @('-PythonCommand', $pythonPath) },
            @{ name = 'Test-InstallerEncoding'; args = @('-PythonCommand', $pythonPath) },
            @{ name = 'Test-RuntimeSelection'; args = @('-ClaudeCommand', $claudePath, '-PythonCommand', $pythonPath) }
        )
    }
    'preservation' {
        $suite = @(
            @{ name = 'Test-OfflineBundle'; args = @() },
            @{ name = 'Test-SkillInstallConflicts'; args = @() },
            @{ name = 'Test-PersonalStateBackup'; args = @() },
            @{ name = 'Test-ExistingHarness'; args = @() },
            @{ name = 'Test-HarnessReplacement'; args = @() },
            @{ name = 'Test-DeploymentSmoke'; args = @() }
        )
    }
}
$rows = @()
foreach ($test in $suite) {
    $leaf = if ($test.ContainsKey('script')) { $test.script } else { $test.name }
    $scriptPath = Join-Path $root ('deploy\' + $leaf + '.ps1')
    $arguments = @('-NoLogo', '-NoProfile', '-File', $scriptPath) + $test.args
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = (& $shellPath @arguments 2>&1 | Out-String -Width 240)
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousErrorAction }
    $timer.Stop()
    $logPath = Join-Path $outputDirectory ($test.name + '.log')
    [IO.File]::WriteAllText($logPath, $output, $utf8)
    $rows += [pscustomobject]@{ name=$test.name; exitCode=$code; seconds=[Math]::Round($timer.Elapsed.TotalSeconds, 2); log=$logPath }
    [IO.File]::WriteAllText((Join-Path $outputDirectory 'results.json'), (ConvertTo-Json -InputObject @($rows) -Depth 8), $utf8)
    Write-Output ('{0}: exit={1} ({2}s)' -f $test.name, $code, $rows[-1].seconds)
}
Write-Output ('Evidence: ' + $outputDirectory)
if (@($rows | Where-Object { $_.exitCode -ne 0 }).Count -gt 0) { exit 1 }
