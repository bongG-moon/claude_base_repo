[CmdletBinding(PositionalBinding = $false)]
param(
    [ValidateSet('Hook', 'Cli')]
    [string] $Mode = 'Cli',
    [string] $Event,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $CliArguments
)

$ErrorActionPreference = 'Stop'
$pluginRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = $utf8
[Console]::OutputEncoding = $utf8
[Console]::InputEncoding = $utf8
$recordedPython = $null
$selectedPython = $null
$metadataPath = Join-Path $pluginRoot 'company-agent-install.json'
if (Test-Path -LiteralPath $metadataPath -PathType Leaf) {
    $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($null -ne $metadata.PSObject.Properties['pythonCommand']) { $recordedPython = [string]$metadata.pythonCommand }
    if ($null -ne $metadata.PSObject.Properties['runtimeSelectionPath']) {
        $selectionPath = [string]$metadata.runtimeSelectionPath
        # The pointer must remain beside this release's durable knowledge root,
        # even when this script itself is running from Claude's plugin cache.
        if ([IO.Path]::IsPathRooted($selectionPath) -and $null -ne $metadata.PSObject.Properties['knowledgeBaseRoot']) {
            $expectedSelection = Join-Path (Split-Path -Parent ([string]$metadata.knowledgeBaseRoot)) 'runtime-selection.json'
            if ([IO.Path]::GetFullPath($selectionPath) -ieq [IO.Path]::GetFullPath($expectedSelection)) {
                $safeSelection = $true
                $ancestor = $selectionPath
                while (-not [string]::IsNullOrWhiteSpace($ancestor)) {
                    if (Test-Path -LiteralPath $ancestor) {
                        $item = Get-Item -LiteralPath $ancestor -Force
                        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { $safeSelection = $false; break }
                    }
                    $ancestor = Split-Path -Parent $ancestor
                }
                if ($safeSelection -and (Test-Path -LiteralPath $selectionPath -PathType Leaf)) {
                    $selection = Get-Content -LiteralPath $selectionPath -Raw -Encoding UTF8 | ConvertFrom-Json
                    if ($selection.coreVersion -eq $metadata.coreVersion) { $selectedPython = [string]$selection.pythonCommand }
                }
            }
        }
    }
}
# The installed release is retained independently of Claude's disposable plugin
# cache. Personal MCP entries therefore keep a durable interpreter location.
$candidates = @($selectedPython, $recordedPython, (Join-Path $pluginRoot 'runtime\python\python.exe'), $env:COMPANY_AGENT_PYTHON, 'python', 'py')
$probed = @{}
$bootstrap = Join-Path $PSScriptRoot 'native_bootstrap.py'
$readyMarker = 'COMPANY_AGENT_RUNTIME_READY:' + [Guid]::NewGuid().ToString('N')
$entryArguments = @('--cli') + $CliArguments
if ($Mode -eq 'Hook') {
    # Retain input only in memory so an unsupported interpreter can fall back.
    $payload = [Console]::In.ReadToEnd()
    $entryArguments = @('--event', $Event)
}
$launcherEnvironment = @{}
foreach ($name in @('PYLAUNCHER_ALLOW_INSTALL', 'PYLAUNCHER_ALWAYS_INSTALL', 'PYTHON_MANAGER_AUTOMATIC_INSTALL', 'COMPANY_AGENT_BOOTSTRAP_ENV')) {
    $launcherEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:COMPANY_AGENT_BOOTSTRAP_ENV = $launcherEnvironment | ConvertTo-Json -Compress
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
    # The bootstrap validates Python before importing or running the entrypoint.
    # Its per-call marker distinguishes launch failure from an application error:
    # after entry has begun, NEVER run that operation again with another runtime.
    $runtimeReady = $false
    $pendingOutput = New-Object 'System.Collections.Generic.List[object]'
    $writeLine = {
        param($line)
        if ($line -is [System.Management.Automation.ErrorRecord]) {
            [Console]::Error.WriteLine($line.ToString())
        } else {
            [Console]::Out.WriteLine([string]$line)
        }
    }
    $forwardOutput = {
        if ($_ -is [string] -and $_ -ceq $readyMarker) {
            $runtimeReady = $true
            foreach ($line in $pendingOutput) { & $writeLine $line }
            $pendingOutput.Clear()
        } elseif ($runtimeReady) {
            & $writeLine $_
        } else {
            # Startup noise is suppressed for rejected candidates, as before.
            $pendingOutput.Add($_)
        }
    }
    $candidateExit = $null
    $previousErrorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $LASTEXITCODE = $null
        if ($Mode -eq 'Hook') {
            $payload | & $info.Source @prefix -X utf8 -B $bootstrap $readyMarker @entryArguments 2>&1 | ForEach-Object $forwardOutput
        } else {
            & $info.Source @prefix -X utf8 -B $bootstrap $readyMarker @entryArguments 2>&1 | ForEach-Object $forwardOutput
        }
        $candidateExit = $LASTEXITCODE
    }
    catch {
        if ($runtimeReady) { [Console]::Error.WriteLine($_.ToString()); exit 1 }
        continue
    }
    finally { $ErrorActionPreference = $previousErrorPreference }
    if ($runtimeReady) {
        if ($null -eq $candidateExit) { exit 1 }
        exit $candidateExit
    }
}
}
finally {
    foreach ($name in $launcherEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $launcherEnvironment[$name], 'Process') }
}
[Console]::Error.WriteLine('Company Agent needs the company-approved Python 3.11+ already installed on this PC. Check its path and execution permission, then rerun Install-CompanyAgent.cmd to select it. Python is not downloaded or installed automatically.')
exit 2
