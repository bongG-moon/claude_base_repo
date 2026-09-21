[CmdletBinding()]
param([string] $ProjectRoot, [string] $Session, [string] $ReportPath, [string[]] $UsageLog, [switch] $FunctionsOnly)
$ErrorActionPreference = 'Stop'
function Get-DiagnosticValue {
    param($Object, [string] $Name)
    if ($null -ne $Object -and $null -ne $Object.PSObject.Properties[$Name]) { return $Object.PSObject.Properties[$Name].Value }
    return $null
}
function Read-DiagnosticRecord {
    param([string] $Path)
    try {
        $ancestor = [IO.Path]::GetFullPath($Path)
        while ($ancestor) {
            if (Test-Path -LiteralPath $ancestor) {
                if (((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return $null }
            }
            $ancestor = Split-Path -Parent $ancestor
        }
        if ((Get-Item -LiteralPath $Path -ErrorAction Stop).Length -gt 2097152) { return $null }
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
    } catch { return $null }
}
function Test-DiagnosticRegistrationActive {
    param($Record, [string] $ConfigRoot)
    $nativeScope = [string](Get-DiagnosticValue $Record 'nativeClaudeScope')
    if (-not $nativeScope) { return $true } # Legacy records have no native contract.
    if ($nativeScope -notin @('user', 'local')) { return $false }
    $override = Get-DiagnosticValue $Record 'claudeConfigDirOverride'
    if ($null -ne $override -and $override -ne (-not [string]::IsNullOrWhiteSpace($env:CLAUDE_CONFIG_DIR))) { return $false }
    try {
        $pluginId = [string](Get-DiagnosticValue $Record 'pluginId')
        if (-not $pluginId) { $pluginId = 'company-agent@company-agent-local' }
        $installed = Read-DiagnosticRecord (Join-Path $ConfigRoot 'plugins\installed_plugins.json')
        $records = @(Get-DiagnosticValue (Get-DiagnosticValue $installed 'plugins') $pluginId)
        $settingsPath = Join-Path $ConfigRoot 'settings.json'
        if ($nativeScope -eq 'local') { $settingsPath = Join-Path ([string]$Record.projectRoot) '.claude\settings.local.json' }
        $settings = Read-DiagnosticRecord $settingsPath
        if ((Get-DiagnosticValue (Get-DiagnosticValue $settings 'enabledPlugins') $pluginId) -ne $true) { return $false }
        foreach ($item in $records) {
            if ((Get-DiagnosticValue $item 'scope') -ne $nativeScope) { continue }
            if ($nativeScope -eq 'user') { return $true }
            $project = [string](Get-DiagnosticValue $item 'projectPath')
            if ($project -and [IO.Path]::GetFullPath($project).TrimEnd('\') -ieq [IO.Path]::GetFullPath([string]$Record.projectRoot).TrimEnd('\')) { return $true }
        }
    } catch { return $false }
    return $false
}
function Get-DiagnosticPythonCandidates {
    param([string] $Project, [string] $LocalData, [string] $ConfigRoot)
    $projectPath = [IO.Path]::GetFullPath($Project).TrimEnd('\')
    $configPath = [IO.Path]::GetFullPath($ConfigRoot).TrimEnd('\')
    $registry = Join-Path $LocalData 'CompanyAgent\installations'
    $files = @((Join-Path $registry 'user\company-agent-install.json'))
    $projectRecords = Join-Path $registry 'projects'
    if (Test-Path -LiteralPath $projectRecords -PathType Container) {
        $files += @(Get-ChildItem -LiteralPath $projectRecords -Directory -Force | Select-Object -First 200 | ForEach-Object { Join-Path $_.FullName 'company-agent-install.json' })
    }
    $matches = @()
    foreach ($file in $files) {
        $record = Read-DiagnosticRecord $file
        if (-not $record -or (Get-DiagnosticValue $record 'schemaVersion') -ne 1 -or (Get-DiagnosticValue $record 'enabled') -eq $false -or -not (Get-DiagnosticValue $record 'claudeConfigRoot')) { continue }
        try {
            if ([IO.Path]::GetFullPath([string]$record.claudeConfigRoot).TrimEnd('\') -ine $configPath) { continue }
            $depth = 0
            if ((Get-DiagnosticValue $record 'scope') -eq 'Project') {
                if (-not (Get-DiagnosticValue $record 'projectRoot') -or -not [IO.Path]::IsPathRooted([string]$record.projectRoot)) { continue }
                $scopePath = [IO.Path]::GetFullPath([string]$record.projectRoot).TrimEnd('\')
                if ($projectPath -ine $scopePath -and -not $projectPath.StartsWith($scopePath + '\', [StringComparison]::OrdinalIgnoreCase)) { continue }
                $depth = $scopePath.Length
            } elseif ((Get-DiagnosticValue $record 'scope') -ne 'User') { continue }
            if (-not (Test-DiagnosticRegistrationActive $record $configPath)) { continue }
            $matches += [pscustomobject]@{ depth = $depth; record = $record }
        } catch { continue }
    }
    foreach ($match in @($matches | Sort-Object depth -Descending)) {
        $record = $match.record
        if ([string](Get-DiagnosticValue $record 'coreVersion') -match '^\d+\.\d+\.\d+$') {
            $selection = Read-DiagnosticRecord (Join-Path $LocalData ('CompanyAgent-Distribution\marketplace\versions\' + $record.coreVersion + '\runtime-selection.json'))
            if ($selection -and (Get-DiagnosticValue $selection 'coreVersion') -eq $record.coreVersion -and (Get-DiagnosticValue $selection 'pythonCommand') -and [IO.Path]::IsPathRooted([string]$selection.pythonCommand)) { [string]$selection.pythonCommand }
        }
        if ((Get-DiagnosticValue $record 'pythonCommand') -and [IO.Path]::IsPathRooted([string]$record.pythonCommand)) { [string]$record.pythonCommand }
    }
    'python'
    'py'
}
if ($FunctionsOnly) { return }
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYLAUNCHER_ALLOW_INSTALL = ''
$env:PYLAUNCHER_ALWAYS_INSTALL = ''
$env:PYTHON_MANAGER_AUTOMATIC_INSTALL = 'false'
$package = Split-Path -Parent $PSScriptRoot
$reader = Join-Path $package 'payload\core\plugin\scripts\diagnose_skill_routing.py'
if (-not (Test-Path -LiteralPath $reader)) {
    $reader = Join-Path $package 'company-agent-plugin\scripts\diagnose_skill_routing.py'
}
if (-not (Test-Path -LiteralPath $reader)) { throw '진단 파일이 없습니다. 설치 압축파일 전체를 먼저 풀어주세요.' }
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Read-Host '문제가 발생한 작업 폴더 경로를 붙여 넣으세요 (Enter = 현재 폴더)'
    if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = (Get-Location).Path }
}
$ProjectRoot = $ProjectRoot.Trim('"')
if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) { throw '작업 폴더가 없습니다. 경로를 확인해 주세요.' }
$configRoot = $env:CLAUDE_CONFIG_DIR
if ([string]::IsNullOrWhiteSpace($configRoot)) { $configRoot = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.claude' }
$candidates = @(Get-DiagnosticPythonCandidates -Project $ProjectRoot -LocalData $env:LOCALAPPDATA -ConfigRoot $configRoot | Select-Object -Unique)
foreach ($candidate in $candidates) {
    $app = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $app -or [IO.Path]::GetExtension($app.Source) -ine '.exe' -or $app.Source -match '\\WindowsApps\\') { continue }
    $prefix = @()
    if ([IO.Path]::GetFileNameWithoutExtension($app.Source) -ieq 'py') { $prefix = @('-3') }
    try { & $app.Source @prefix -I -X utf8 -B -c 'import sys; sys.exit(0 if sys.version_info.major == 3 and sys.version_info >= (3,11) else 1)' 2>$null }
    catch { continue }
    if ($LASTEXITCODE -ne 0) { continue }
    $options = @('--project-root', $ProjectRoot)
    if ($Session) { $options += @('--session', $Session) }
    if ($ReportPath) { $options += @('--report', $ReportPath) }
    foreach ($logPath in $UsageLog) { $options += @('--usage-log', $logPath) }
    & $app.Source @prefix -X utf8 -B $reader @options
    exit $LASTEXITCODE
}
throw 'Python 3.11 이상을 찾지 못했습니다. 설정을 변경하거나 Python을 설치하지 않았습니다.'
