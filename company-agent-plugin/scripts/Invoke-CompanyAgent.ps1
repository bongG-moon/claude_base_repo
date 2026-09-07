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
$python = $null
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
    $prefix = @()
    if ([IO.Path]::GetFileNameWithoutExtension($info.Source) -ieq 'py') { $prefix = @('-3') }
    # -I ignores PYTHONIOENCODING. Pin UTF-8 explicitly so a Korean or emoji
    # interpreter path is decoded correctly by this UTF-8 PowerShell wrapper.
    try { $probe = & $info.Source @prefix -I -X utf8 -B -c 'import sys; print(sys.executable); sys.exit(0 if sys.version_info >= (3,11) and sys.version_info.major == 3 else 1)' 2>$null }
    catch { continue }
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace(($probe -join ''))) {
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
    $payload | & $python $entry --event $Event
} else {
    & $python $entry --cli @CliArguments
}
exit $LASTEXITCODE
