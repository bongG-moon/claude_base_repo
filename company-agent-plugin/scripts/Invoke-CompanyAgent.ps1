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
$officeRead = $Mode -eq 'Cli' -and $CliArguments.Count -ge 2 -and
    $CliArguments[0] -eq 'business' -and $CliArguments[1] -eq 'office-read' -and
    '-h' -notin $CliArguments -and '--help' -notin $CliArguments
$officeWatch = [Diagnostics.Stopwatch]::StartNew()
if ($officeRead) { [Console]::Error.WriteLine(('"[\ubb38\uc11c \uc77d\uae30] \uc2e4\ud589 \uc900\ube44 \uc911 \u2014 Python \ud655\uc778"' | ConvertFrom-Json)) }

function Invoke-OfficePythonProbe {
    param([string] $Executable, [string[]] $Prefix)
    # Only this small, owned version probe is timed/killed. No Office process
    # exists yet. Fixed arguments contain no source path or request content.
    $process = New-Object Diagnostics.Process
    $process.StartInfo.FileName = $Executable
    $process.StartInfo.Arguments = (($Prefix + @('-I', '-X', 'utf8', '-B')) -join ' ') + ' -c "import sys; print(sys.executable); sys.exit(0 if sys.version_info >= (3,11) and sys.version_info.major == 3 else 1)"'
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    $process.StartInfo.StandardOutputEncoding = New-Object Text.UTF8Encoding($false)
    $process.StartInfo.StandardErrorEncoding = New-Object Text.UTF8Encoding($false)
    try {
        $null = $process.Start()
        $outTask = $process.StandardOutput.ReadToEndAsync()
        $errTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(10000) -or -not $outTask.Wait(1000) -or -not $errTask.Wait(1000)) {
            if (-not $process.HasExited) { $process.Kill(); $null = $process.WaitForExit(1000) }
            return @{ timedOut = $true; code = -1; output = @() }
        }
        return @{ timedOut = $false; code = $process.ExitCode; output = @($outTask.Result.Trim() -split '\r?\n') }
    } finally { $process.Dispose() }
}
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
$python = $null
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
        if ($officeRead) {
            $attempt = Invoke-OfficePythonProbe -Executable $info.Source -Prefix $prefix
            if ($attempt.timedOut) {
                [Console]::Error.WriteLine(('"[\ubb38\uc11c \uc77d\uae30] Python \uc900\ube44 \uc2dc\uac04 \ucd08\uacfc. Office\ub294 \uc544\uc9c1 \uc5f4\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4."' | ConvertFrom-Json))
                @{ ok = $false; status = 'unavailable'; code = 'office_bootstrap_timeout'; stage = 'python_probe'; retryAllowed = $false; elapsedMs = $officeWatch.ElapsedMilliseconds } | ConvertTo-Json -Compress
                exit 2
            }
            $probe = $attempt.output
            $probeExit = $attempt.code
        } else {
            $probe = & $info.Source @prefix -I -X utf8 -B -c 'import sys; print(sys.executable); sys.exit(0 if sys.version_info >= (3,11) and sys.version_info.major == 3 else 1)' 2>$null
            $probeExit = $LASTEXITCODE
        }
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
    if ($officeRead) {
        [Console]::Error.WriteLine((('"[\ubb38\uc11c \uc77d\uae30] Python \uc900\ube44 \uc644\ub8cc ({0}ms); \uc124\uce58\u00b7\uba85\ub839 \ud655\uc778 \uc911"' | ConvertFrom-Json) -f $officeWatch.ElapsedMilliseconds))
        $env:COMPANY_AGENT_OFFICE_BOOTSTRAP_MS = [string]$officeWatch.ElapsedMilliseconds
    }
    & $python -X utf8 $entry --cli @CliArguments
}
exit $LASTEXITCODE
