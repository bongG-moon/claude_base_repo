[CmdletBinding()]
param(
    [ValidateSet('User', 'Project')]
    [string] $Scope = 'User',
    [string] $ProjectRoot,
    [string] $ClaudeCommand = 'claude',
    [string] $ClaudeConfigRoot,
    [string] $InvokingUserProfile,
    [string] $InvokingLocalAppData,
    [string] $BackupRoot,
    [switch] $NonInteractive,
    [switch] $DryRun,
    [switch] $SkipAdminCheck
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$uninstallValues = @{}
foreach ($name in @('Scope', 'ProjectRoot', 'ClaudeCommand', 'ClaudeConfigRoot', 'InvokingUserProfile', 'InvokingLocalAppData', 'BackupRoot', 'NonInteractive', 'DryRun', 'SkipAdminCheck')) {
    $uninstallValues[$name] = Get-Variable -Name $name -ValueOnly
}
. (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1') -FunctionsOnly
foreach ($name in $uninstallValues.Keys) { Set-Variable -Name $name -Value $uninstallValues[$name] }
$userContext = Resolve-SetupUserContext -InvokingUserProfile $InvokingUserProfile -InvokingLocalAppData $InvokingLocalAppData -SkipAdminCheck:$SkipAdminCheck
$InvokingUserProfile = $userContext.userProfile
$InvokingLocalAppData = $userContext.localAppData
$explicitConfig = -not [string]::IsNullOrWhiteSpace($ClaudeConfigRoot) -or -not [string]::IsNullOrWhiteSpace($env:CLAUDE_CONFIG_DIR)
if (-not $ClaudeConfigRoot) { $ClaudeConfigRoot = $env:CLAUDE_CONFIG_DIR }
if (-not $ClaudeConfigRoot) { $ClaudeConfigRoot = Join-Path $InvokingUserProfile '.claude' }
if (-not $BackupRoot) { $BackupRoot = Join-Path $InvokingLocalAppData 'CompanyAgent-Backups' }
$ClaudeConfigRoot = Get-SetupFullPath -Path $ClaudeConfigRoot
$distributionRoot = Join-Path $InvokingLocalAppData 'CompanyAgent-Distribution'
$registrationsRoot = Join-Path $InvokingLocalAppData 'CompanyAgent\installations'
$scopeRelative = 'user'
$nativeScope = 'user'
if ($Scope -eq 'Project') {
    if (-not $ProjectRoot -and -not $NonInteractive -and -not $DryRun) { $ProjectRoot = (Read-Host '적용을 해제할 프로젝트 폴더 경로').Trim().Trim('"') }
    if (-not $ProjectRoot) { throw 'Project uninstall requires -ProjectRoot with the installed project folder path.' }
    $ProjectRoot = (Get-SetupFullPath -Path $ProjectRoot).TrimEnd([char[]]@('\', '/'))
    if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) { throw "The project folder does not exist: $ProjectRoot" }
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $projectHash = ([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($ProjectRoot.ToUpperInvariant())))).Replace('-', '').ToLowerInvariant().Substring(0, 16) }
    finally { $hasher.Dispose() }
    $scopeRelative = Join-Path 'projects' $projectHash
    $nativeScope = 'local'
}
$registrationRoot = Join-Path $registrationsRoot $scopeRelative
$registrationPath = Join-Path $registrationRoot 'company-agent-install.json'
foreach ($path in @($registrationRoot, $ClaudeConfigRoot, $BackupRoot)) { Assert-SetupPathHasNoReparsePoint -Path $path -Name 'Uninstall path' }
foreach ($target in @($registrationPath, (Join-Path $ClaudeConfigRoot 'settings.json'),
    (Join-Path $ClaudeConfigRoot 'plugins\installed_plugins.json'), (Join-Path $ClaudeConfigRoot 'plugins\known_marketplaces.json'))) {
    Assert-SetupPathHasNoReparsePoint -Path $target -Name 'Uninstall registration target'
}
if ($Scope -eq 'Project') {
    Assert-SetupPathHasNoReparsePoint -Path (Join-Path $ProjectRoot '.claude\settings.local.json') -Name 'Uninstall project settings'
}
if (-not (Test-Path -LiteralPath $registrationPath -PathType Leaf)) { throw 'No Company Agent installation record exists for this scope. No change was made.' }
$registration = Read-CompanyAgentJson -Path $registrationPath
if ([int](Get-SetupPropertyValue -Object $registration -Name 'schemaVersion') -ne 1 -or
    [string](Get-SetupPropertyValue -Object $registration -Name 'pluginId') -cne 'company-agent@company-agent-local') {
    throw 'The installation record does not identify a supported Company Agent installation. No changes were made.'
}
if ($Scope -eq 'Project' -and (Get-SetupFullPath -Path ([string]$registration.projectRoot)).TrimEnd([char[]]@('\', '/')) -ine $ProjectRoot) {
    throw 'The installation record belongs to a different project. No changes were made.'
}
if (-not $explicitConfig) { $ClaudeConfigRoot = Get-SetupFullPath -Path ([string]$registration.claudeConfigRoot) }
if ([string]$registration.scope -ne $Scope -or [string]$registration.claudeConfigRoot -ine $ClaudeConfigRoot) { throw 'The installation record belongs to a different Claude configuration or scope.' }
$stateRoot = [string]$registration.userStateRoot
foreach ($target in @($ClaudeConfigRoot, $stateRoot, $BackupRoot, $ProjectRoot) | Where-Object { $_ }) {
    Assert-SetupPathHasNoReparsePoint -Path $target -Name 'Scoped uninstall target'
    Assert-SetupUserProfileTarget -Path $target -Context $userContext
}
foreach ($target in @((Join-Path $ClaudeConfigRoot 'settings.json'),
    (Join-Path $ClaudeConfigRoot 'plugins\installed_plugins.json'), (Join-Path $ClaudeConfigRoot 'plugins\known_marketplaces.json'))) {
    Assert-SetupPathHasNoReparsePoint -Path $target -Name 'Resolved Claude uninstall target'
}
$useConfigOverride = Get-SetupPropertyValue -Object $registration -Name 'claudeConfigDirOverride'
if ($null -ne $useConfigOverride -and $useConfigOverride -isnot [bool]) {
    throw 'The installation record contains an invalid Claude configuration override flag. No changes were made.'
}
if ($useConfigOverride -eq $false -and $ClaudeConfigRoot -ine (Get-SetupFullPath -Path (Join-Path $InvokingUserProfile '.claude'))) {
    throw 'The installation record has an inconsistent custom Claude configuration path. No changes were made.'
}
if ($DryRun) { return [pscustomobject]@{ status = 'dry-run'; scope = $Scope; nativeClaudeScope = $nativeScope; registrationPath = $registrationPath; preservedUserStateRoot = $stateRoot } }
$claudeSelection = Get-SetupClaudeForInstall -PreferredCommand $ClaudeCommand -UserProfile $InvokingUserProfile -NonInteractive:$NonInteractive
if ($claudeSelection.status -eq 'input-required') { return $claudeSelection }
$resolvedClaude = $claudeSelection.path
Assert-SetupUserProfileTarget -Path $resolvedClaude -Context $userContext
$items = @(Get-SetupBackupItems -ClaudeConfigPath $ClaudeConfigRoot -PersonalStatePath $stateRoot -ManagedDataPath $registrationRoot -ManagedInstallPath $distributionRoot -ManagedShortcutPath '')
$items += [pscustomobject]@{ source = $registrationPath; relativePath = 'company-agent\company-agent-install.json'; purpose = 'Scope registration before uninstall'; mode = 'sanitized-json' }
if ($Scope -eq 'Project' -and (Test-Path -LiteralPath (Join-Path $ProjectRoot '.claude') -PathType Container)) {
    foreach ($item in @(Get-SetupBackupItems -ClaudeConfigPath (Join-Path $ProjectRoot '.claude') -PersonalStatePath $stateRoot -ManagedDataPath $registrationRoot -ManagedInstallPath $distributionRoot -ManagedShortcutPath '')) {
        $item.relativePath = 'project-' + $item.relativePath
        $items += $item
    }
}
$backup = New-SetupBackup -BackupBase $BackupRoot -Items $items -ClaudeConfigPath $ClaudeConfigRoot -PersonalStatePath $stateRoot -ManagedDataPath $registrationRoot -ManagedInstallPath $distributionRoot
$previousConfig = $env:CLAUDE_CONFIG_DIR
try {
    $env:CLAUDE_CONFIG_DIR = $(if ($useConfigOverride -eq $false) { $null } else { $ClaudeConfigRoot })
    Push-Location -LiteralPath $(if ($Scope -eq 'Project') { $ProjectRoot } else { $InvokingUserProfile })
    try {
        $output = & $resolvedClaude plugin uninstall 'company-agent@company-agent-local' --scope $nativeScope --keep-data 2>&1
        if ($LASTEXITCODE -ne 0) { throw ('Claude plugin uninstall failed: ' + ($output -join [Environment]::NewLine)) }
        foreach ($line in @($output)) { Write-Host ([string]$line) }
    }
    finally { Pop-Location }
    # Only this exact owned registration is removed. Shared core and personal
    # state remain on disk so reinstalling the same scope resumes prior work.
    Remove-Item -LiteralPath $registrationPath -Force
    Write-Host '선택한 범위의 Company Agent 적용을 해제했습니다. Claude Code를 다시 열어 주세요.'
    Write-Host "개인 자료는 보존됩니다: $stateRoot"
    Write-Host "변경 전 백업: $backup"
    return [pscustomobject]@{ status = 'uninstalled'; scope = $Scope; preservedUserStateRoot = $stateRoot; safetyBackup = $backup; sharedCorePreserved = $true }
}
finally { $env:CLAUDE_CONFIG_DIR = $previousConfig }
