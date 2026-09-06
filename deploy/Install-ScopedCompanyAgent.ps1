[CmdletBinding()]
param(
    [string] $BundleRoot,
    [ValidateSet('User', 'Project')]
    [string] $Scope = 'User',
    [string] $ProjectRoot,
    [string] $UserStateRoot,
    [string] $BackupRoot,
    [string] $ClaudeConfigRoot,
    [string] $ClaudeCommand = 'claude',
    [string] $PythonCommand = 'python',
    [string] $InvokingUserProfile,
    [string] $InvokingLocalAppData,
    [switch] $NonInteractive,
    [switch] $DryRun,
    [switch] $SkipAdminCheck,
    [switch] $SkipPrerequisiteCheck,
    [switch] $SkipBundleVerification
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$scopedEntryValues = @{}
foreach ($name in @('BundleRoot', 'Scope', 'ProjectRoot', 'UserStateRoot', 'BackupRoot', 'ClaudeConfigRoot',
    'ClaudeCommand', 'PythonCommand', 'InvokingUserProfile', 'InvokingLocalAppData', 'NonInteractive',
    'DryRun', 'SkipAdminCheck', 'SkipPrerequisiteCheck', 'SkipBundleVerification')) {
    $scopedEntryValues[$name] = Get-Variable -Name $name -ValueOnly
}
. (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1') -FunctionsOnly
foreach ($name in $scopedEntryValues.Keys) { Set-Variable -Name $name -Value $scopedEntryValues[$name] }
$usesConfigOverride = -not [string]::IsNullOrWhiteSpace([string]$scopedEntryValues['ClaudeConfigRoot']) -or
    -not [string]::IsNullOrWhiteSpace($env:CLAUDE_CONFIG_DIR)

function Get-ScopedHash {
    param([string] $Text)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
}

function Get-ScopedNormalizedStateRoot {
    param([string] $Path)
    $fullPath = Get-SetupFullPath -Path $Path
    $driveRoot = [IO.Path]::GetPathRoot($fullPath)
    if ($fullPath.StartsWith('\\') -or $fullPath.TrimEnd('\') -ieq $driveRoot.TrimEnd('\')) {
        throw 'UserStateRoot must be a dedicated folder on this local PC, not a network share or drive root.'
    }
    if ((New-Object IO.DriveInfo($driveRoot)).DriveType -eq [IO.DriveType]::Network) {
        throw 'UserStateRoot must be a dedicated folder on this local PC, not a mapped network drive.'
    }
    if ($fullPath.Length -gt ([IO.Path]::GetPathRoot($fullPath)).Length) {
        return $fullPath.TrimEnd([char[]]@('\', '/'))
    }
    return $fullPath
}

function Read-ScopedJsonOrEmpty {
    param([string] $Path)
    if (Test-Path -LiteralPath $Path -PathType Leaf) { return Read-CompanyAgentJson -Path $Path }
    return [pscustomobject]@{}
}

function Get-ScopedEntrySnapshot {
    param([string] $Path, [string] $Container, [string] $Key)
    $document = Read-ScopedJsonOrEmpty -Path $Path
    $parent = $document
    if ($Container) { $parent = Get-SetupPropertyValue -Object $document -Name $Container }
    $property = $null
    if ($null -ne $parent) { $property = $parent.PSObject.Properties[$Key] }
    return [pscustomobject]@{
        path = $Path; container = $Container; key = $Key
        fileExisted = (Test-Path -LiteralPath $Path -PathType Leaf)
        containerExisted = ($null -ne $parent)
        existed = ($null -ne $property)
        value = $(if ($null -ne $property) { $property.Value } else { $null })
    }
}

function Restore-ScopedEntry {
    param([object] $Snapshot)
    Assert-SetupPathHasNoReparsePoint -Path $Snapshot.path -Name 'Registration restore target'
    $document = Read-ScopedJsonOrEmpty -Path $Snapshot.path
    $parent = $document
    if ($Snapshot.container) {
        $parent = Get-SetupPropertyValue -Object $document -Name $Snapshot.container
        if ($null -eq $parent -and $Snapshot.existed) {
            $parent = [pscustomobject]@{}
            $document | Add-Member -MemberType NoteProperty -Name $Snapshot.container -Value $parent -Force
        }
    }
    if ($null -ne $parent) {
        $parent.PSObject.Properties.Remove($Snapshot.key)
        if ($Snapshot.existed) {
            $parent | Add-Member -MemberType NoteProperty -Name $Snapshot.key -Value $Snapshot.value -Force
        }
        if ($Snapshot.container -and -not $Snapshot.containerExisted -and @($parent.PSObject.Properties).Count -eq 0) {
            $document.PSObject.Properties.Remove($Snapshot.container)
        }
    }
    if (-not $Snapshot.fileExisted -and @($document.PSObject.Properties).Count -eq 0) {
        if (Test-Path -LiteralPath $Snapshot.path -PathType Leaf) { Remove-Item -LiteralPath $Snapshot.path -Force }
    }
    else { Write-CompanyAgentJsonAtomic -Path $Snapshot.path -Value $document }
}

function Invoke-ScopedClaude {
    param([string[]] $Arguments)
    $output = & $script:ScopedClaudeExecutable @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ('Claude plugin registration failed (' + ($Arguments -join ' ') + '): ' + ($output -join [Environment]::NewLine))
    }
    foreach ($line in @($output)) { Write-Host ([string]$line) }
}

if (-not $SkipAdminCheck -and (Test-CompanyAgentAdministrator)) {
    throw 'Run this installer from your normal Windows account without Run as administrator. User and Project installation do not require administrator rights.'
}
if ([string]::IsNullOrWhiteSpace($BundleRoot)) { $BundleRoot = Split-Path -Parent $PSScriptRoot }
if ([string]::IsNullOrWhiteSpace($InvokingUserProfile)) { $InvokingUserProfile = $env:USERPROFILE }
if ([string]::IsNullOrWhiteSpace($InvokingLocalAppData)) { $InvokingLocalAppData = $env:LOCALAPPDATA }
if ([string]::IsNullOrWhiteSpace($ClaudeConfigRoot)) { $ClaudeConfigRoot = $env:CLAUDE_CONFIG_DIR }
if ([string]::IsNullOrWhiteSpace($ClaudeConfigRoot)) { $ClaudeConfigRoot = Join-Path $InvokingUserProfile '.claude' }
if ([string]::IsNullOrWhiteSpace($BackupRoot)) { $BackupRoot = Join-Path $InvokingLocalAppData 'CompanyAgent-Backups' }
foreach ($variable in @('BundleRoot', 'InvokingUserProfile', 'InvokingLocalAppData', 'ClaudeConfigRoot', 'BackupRoot')) {
    Set-Variable -Name $variable -Value (Get-SetupFullPath -Path (Get-Variable -Name $variable -ValueOnly))
}
if ($Scope -eq 'Project') {
    if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
        if ($NonInteractive -or $DryRun) { throw 'Project installation needs -ProjectRoot with the existing project folder path.' }
        Write-Host '이 프로젝트에서 Claude Code를 사용하는 폴더 경로를 입력해 주세요.'
        do { $ProjectRoot = (Read-Host '프로젝트 폴더 경로').Trim().Trim('"') } while ([string]::IsNullOrWhiteSpace($ProjectRoot))
    }
    $ProjectRoot = (Get-SetupFullPath -Path $ProjectRoot).TrimEnd([char[]]@('\', '/'))
    if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) { throw "The project folder does not exist: $ProjectRoot. Choose the existing folder and run setup again." }
    if ($ProjectRoot -ieq ([IO.Path]::GetPathRoot($ProjectRoot)).TrimEnd('\')) { throw 'Select a project folder, not an entire drive.' }
    Assert-SetupPathHasNoReparsePoint -Path $ProjectRoot -Name 'Project folder'
}

$distributionRoot = Join-Path $InvokingLocalAppData 'CompanyAgent-Distribution'
$marketplaceRoot = Join-Path $distributionRoot 'marketplace'
$registrationsRoot = Join-Path $InvokingLocalAppData 'CompanyAgent\installations'
$scopeRelative = 'user'
if ($Scope -eq 'Project') {
    $projectHash = (Get-ScopedHash -Text $ProjectRoot.ToUpperInvariant()).Substring(0, 16)
    $scopeRelative = Join-Path 'projects' $projectHash
}
$registrationRoot = Join-Path $registrationsRoot $scopeRelative
$registrationPath = Join-Path $registrationRoot 'company-agent-install.json'
Assert-SetupPathHasNoReparsePoint -Path $registrationPath -Name 'Existing scope registration'
$existingScopeRegistration = $null
if (Test-Path -LiteralPath $registrationPath -PathType Leaf) {
    $existingScopeRegistration = Read-CompanyAgentJson -Path $registrationPath
    if ((Get-SetupPropertyValue -Object $existingScopeRegistration -Name 'schemaVersion') -ne 1 -or
        [string](Get-SetupPropertyValue -Object $existingScopeRegistration -Name 'scope') -ine $Scope) {
        throw "The existing installation record does not match this scope or its supported schema: $registrationPath. Ask the package owner to repair the record; personal data and registration were not changed."
    }
    if ($Scope -eq 'Project') {
        $recordedProject = Get-SetupPropertyValue -Object $existingScopeRegistration -Name 'projectRoot'
        if ($recordedProject -isnot [string] -or $recordedProject -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+(?:[\\/]|$))' -or
            (Get-SetupFullPath -Path $recordedProject).TrimEnd([char[]]@('\', '/')) -ine $ProjectRoot) {
            throw "The existing installation record belongs to a different project: $registrationPath. Personal data and registration were not changed."
        }
    }
    $recordedState = Get-SetupPropertyValue -Object $existingScopeRegistration -Name 'userStateRoot'
    if ($recordedState -isnot [string] -or $recordedState -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+(?:[\\/]|$))') {
        throw "The existing installation record has no valid absolute UserStateRoot: $registrationPath. Restore the original personal data path in that record before retrying; no new state location was selected."
    }
    $recordedState = Get-ScopedNormalizedStateRoot -Path $recordedState
    Assert-SetupPathHasNoReparsePoint -Path $recordedState -Name 'Recorded UserStateRoot'
    if (-not [string]::IsNullOrWhiteSpace($UserStateRoot)) {
        $requestedState = Get-ScopedNormalizedStateRoot -Path $UserStateRoot
        if ($requestedState -ine $recordedState) {
            throw "This scope already uses UserStateRoot '$recordedState'. Run setup without -UserStateRoot, or pass that same path. Moving personal data to '$requestedState' requires a separate explicit migration; setup did not change any registration or personal data."
        }
    }
    # Reuse the recorded location for both ordinary and custom-path updates.
    # The old record is also retained below as the rollback snapshot.
    $UserStateRoot = $recordedState
}
if ([string]::IsNullOrWhiteSpace($UserStateRoot)) { $UserStateRoot = Join-Path (Join-Path $InvokingLocalAppData 'CompanyAgent\states') $scopeRelative }
$UserStateRoot = Get-ScopedNormalizedStateRoot -Path $UserStateRoot
$nativeScope = $(if ($Scope -eq 'Project') { 'local' } else { 'user' })
$settingsPath = $(if ($Scope -eq 'Project') { Join-Path $ProjectRoot '.claude\settings.local.json' } else { Join-Path $ClaudeConfigRoot 'settings.json' })
$marketplaceName = 'company-agent-local'
$pluginId = 'company-agent@company-agent-local'
foreach ($path in @($BundleRoot, $ClaudeConfigRoot, $distributionRoot, $registrationsRoot, $UserStateRoot, $BackupRoot)) {
    Assert-SetupPathHasNoReparsePoint -Path $path -Name 'Installation path'
}
foreach ($target in @($settingsPath, $registrationPath,
    (Join-Path $ClaudeConfigRoot 'settings.json'), (Join-Path $ClaudeConfigRoot 'plugins\installed_plugins.json'),
    (Join-Path $ClaudeConfigRoot 'plugins\known_marketplaces.json'), (Join-Path $marketplaceRoot '.claude-plugin\marketplace.json'))) {
    Assert-SetupPathHasNoReparsePoint -Path $target -Name 'Claude registration target'
}
if ($Scope -eq 'Project') {
    Assert-SetupPathHasNoReparsePoint -Path (Join-Path $ProjectRoot '.claude\settings.json') -Name 'Project Claude settings'
}
$existingRegistrationFiles = @()
if (Test-Path -LiteralPath (Join-Path $registrationsRoot 'user\company-agent-install.json')) {
    $existingRegistrationFiles += Join-Path $registrationsRoot 'user\company-agent-install.json'
}
$projectRegistrations = Join-Path $registrationsRoot 'projects'
if (Test-Path -LiteralPath $projectRegistrations -PathType Container) {
    foreach ($directory in @(Get-ChildItem -LiteralPath $projectRegistrations -Directory)) {
        Assert-SetupPathHasNoReparsePoint -Path $directory.FullName -Name 'Existing project registration'
        $candidate = Join-Path $directory.FullName 'company-agent-install.json'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { $existingRegistrationFiles += $candidate }
    }
}
foreach ($recordPath in $existingRegistrationFiles) {
    Assert-SetupPathHasNoReparsePoint -Path $recordPath -Name 'Existing registration'
    $record = Read-CompanyAgentJson -Path $recordPath
    $recordOverride = Get-SetupPropertyValue -Object $record -Name 'claudeConfigDirOverride'
    if ([string]$record.claudeConfigRoot -ine $ClaudeConfigRoot -or
        ($null -ne $recordOverride -and [bool]$recordOverride -ne [bool]$usesConfigOverride)) {
        throw 'Company Agent is already installed for another Claude configuration profile on this Windows account. Use that existing profile or uninstall its scopes before changing profiles. No registration was changed.'
    }
}
foreach ($protected in @($BundleRoot, $ClaudeConfigRoot, $distributionRoot, $registrationsRoot, $UserStateRoot)) {
    if (Test-SetupSameOrChildPath -Candidate $BackupRoot -Parent $protected) { throw "BackupRoot must be outside installation, state, and Claude folders: $protected" }
}
foreach ($protected in @($BundleRoot, $ClaudeConfigRoot, $distributionRoot, $registrationsRoot)) {
    if ((Test-SetupSameOrChildPath -Candidate $UserStateRoot -Parent $protected) -or (Test-SetupSameOrChildPath -Candidate $protected -Parent $UserStateRoot)) {
        throw "UserStateRoot must be separate from package, registration, and Claude configuration folders: $protected"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $BundleRoot 'bundle-manifest.json') -PathType Leaf)) {
    throw "Extract the complete Company Agent ZIP first, then double-click Install-CompanyAgent.cmd. Checked: $BundleRoot"
}
Write-Host ''
Write-Host "Company Agent setup - $Scope"
Write-Host '[1/4] 설치 파일과 기존 Claude Code의 실행 조건을 확인합니다...'
$manifest = $(if ($SkipBundleVerification) { Read-CompanyAgentJson -Path (Join-Path $BundleRoot 'bundle-manifest.json') } else { Test-CompanyAgentBundleIntegrity -BundleRoot $BundleRoot })
Assert-CompanyAgentVersion -Version ([string]$manifest.coreVersion) -Name 'CoreVersion'
Assert-CompanyAgentVersion -Version ([string]$manifest.knowledgeVersion) -Name 'KnowledgeVersion'
Assert-SetupPathHasNoReparsePoint -Path (Join-Path $ClaudeConfigRoot ('plugins\cache\company-agent-local\company-agent\' + [string]$manifest.coreVersion)) -Name 'Claude plugin cache target'
$sourcePlugin = Join-Path $BundleRoot 'payload\core\plugin'
$sourceRuntime = Join-Path $sourcePlugin 'runtime\python\python.exe'
$resolvedPython = $null
if (Test-Path -LiteralPath $sourceRuntime -PathType Leaf) { $resolvedPython = Resolve-SetupApprovedPython -PreferredCommand $sourceRuntime }
if ([string]::IsNullOrWhiteSpace($resolvedPython)) { $resolvedPython = Resolve-SetupApprovedPython -PreferredCommand $PythonCommand }
$script:ScopedClaudeExecutable = Resolve-SetupCommand -Command $ClaudeCommand
if ([string]::IsNullOrWhiteSpace($script:ScopedClaudeExecutable)) { throw 'The claude command is unavailable. Open a new terminal after installing Claude Code, then run this installer again.' }
if ([string]::IsNullOrWhiteSpace($resolvedPython)) { throw 'This package has no working Python 3.11+ runtime. Ask the package owner for the complete Windows bundle that includes Python, then run setup again.' }
if (-not $SkipPrerequisiteCheck) {
    Assert-CompanyAgentPrerequisites -ClaudeCommand $script:ScopedClaudeExecutable -PythonCommand $resolvedPython
}
$stateCheckScript = Join-Path $sourcePlugin 'scripts\harness_cli.py'
$stateCheckOutput = @()
$stateCheckExit = -1
$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    $stateCheckOutput = @(& $resolvedPython -B $stateCheckScript state check --state-root $UserStateRoot 2>&1)
    $stateCheckExit = $LASTEXITCODE
}
finally { $ErrorActionPreference = $previousErrorActionPreference }
if ($stateCheckExit -ne 0) {
    throw ("The new Company Agent package cannot read the existing personal state at '$UserStateRoot'. Keep that folder and use the previous compatible package, or ask the package owner for a supported migration. No installation or personal data was changed. Details: " + ($stateCheckOutput -join [Environment]::NewLine))
}
$modelSettingsPaths = @((Join-Path $ClaudeConfigRoot 'settings.json'))
if ($Scope -eq 'Project') {
    $folder = $ProjectRoot
    while ($folder) {
        $modelSettingsPaths += Join-Path $folder '.claude\settings.json'
        $modelSettingsPaths += Join-Path $folder '.claude\settings.local.json'
        $parent = Split-Path -Parent $folder
        if ($parent -eq $folder) { break }
        $folder = $parent
    }
}
$modelOverrides = @(Get-CompanyAgentSubagentModelForceSettings -SettingsPaths $modelSettingsPaths -IncludeWindowsPolicy)
$forcedEnvironment = @(@('CLAUDE_CODE_SUBAGENT_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE') | Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_, 'Process')) })
if ($modelOverrides.Count -gt 0 -or $forcedEnvironment.Count -gt 0) {
    throw 'Existing Claude settings force every subagent to one model. Remove the CLAUDE_CODE_SUBAGENT_MODEL / CLAUDE_CODE_SUBAGENT_MODEL_FORCE override in its original setting before installing. Your SMALL/MEDIUM/LARGE aliases will otherwise be reused as-is.'
}
$inventoryPath = Join-Path $ClaudeConfigRoot 'plugins\installed_plugins.json'
$knownPath = Join-Path $ClaudeConfigRoot 'plugins\known_marketplaces.json'
$inventory = Read-ScopedJsonOrEmpty -Path $inventoryPath
$installedPlugins = Get-SetupPropertyValue -Object $inventory -Name 'plugins'
$collisionNames = @()
if ($null -ne $installedPlugins) {
    $collisionNames += @($installedPlugins.PSObject.Properties | Where-Object { $_.Name -like 'company-agent@*' -and $_.Name -ne $pluginId } | ForEach-Object { $_.Name })
}
foreach ($settingFile in @($modelSettingsPaths | Select-Object -Unique)) {
    $enabled = Get-SetupPropertyValue -Object (Read-ScopedJsonOrEmpty -Path $settingFile) -Name 'enabledPlugins'
    if ($null -ne $enabled) { $collisionNames += @($enabled.PSObject.Properties | Where-Object { $_.Name -like 'company-agent@*' -and $_.Name -ne $pluginId -and $_.Value } | ForEach-Object { $_.Name }) }
}
if ($collisionNames.Count -gt 0) { throw ('Another Company Agent plugin already owns this name: ' + (($collisionNames | Select-Object -Unique) -join ', ') + '. Keep that installation or ask its owner to migrate it first.') }
$known = Read-ScopedJsonOrEmpty -Path $knownPath
$knownMarket = Get-SetupPropertyValue -Object $known -Name $marketplaceName
if ($null -ne $knownMarket) {
    $knownInstall = [string](Get-SetupPropertyValue -Object $knownMarket -Name 'installLocation')
    $knownSource = Get-SetupPropertyValue -Object $knownMarket -Name 'source'
    $knownSourcePath = [string](Get-SetupPropertyValue -Object $knownSource -Name 'path')
    if ($knownSourcePath -and (Get-SetupFullPath -Path $knownSourcePath) -ine $marketplaceRoot) { throw 'The company-agent-local marketplace name is already registered to another source. No registration was changed.' }
    if (-not $knownSourcePath -and $knownInstall -and (Get-SetupFullPath -Path $knownInstall) -ine $marketplaceRoot) { throw 'The company-agent-local marketplace belongs to a different installation. No registration was changed.' }
}
$releaseRoot = Join-Path $marketplaceRoot ('versions\' + [string]$manifest.coreVersion)
$releasePlugin = Join-Path $releaseRoot 'plugin'
$releaseKnowledge = Join-Path $releaseRoot 'knowledge'
$releaseConfig = Join-Path $releaseRoot 'config'
$payloadRecords = @($manifest.files | Where-Object { $_.path -like 'payload/*' } | Sort-Object path | ForEach-Object { "$($_.path)|$($_.sha256)|$($_.length)" })
$payloadHash = Get-ScopedHash -Text ($payloadRecords -join "`n")
$releaseReceipt = Join-Path $releaseRoot 'release.json'
if (Test-Path -LiteralPath $releaseRoot) {
    if (-not (Test-Path -LiteralPath $releaseReceipt -PathType Leaf)) { throw "An incomplete release exists at $releaseRoot. Ask the package owner to inspect this folder before retrying." }
    $existingRelease = Read-CompanyAgentJson -Path $releaseReceipt
    if ([string]$existingRelease.payloadHash -cne $payloadHash) { throw "This Core version already exists with different contents. The package owner must increase CoreVersion before redistributing ($($manifest.coreVersion))." }
}

$backupItems = @(Get-SetupBackupItems -ClaudeConfigPath $ClaudeConfigRoot -PersonalStatePath $UserStateRoot -ManagedDataPath $registrationRoot -ManagedInstallPath $distributionRoot -ManagedShortcutPath '')
if ($Scope -eq 'Project' -and (Test-Path -LiteralPath (Join-Path $ProjectRoot '.claude') -PathType Container)) {
    # Personal state was already selected above; only add project Claude files.
    $projectItems = @(Get-SetupBackupItems -ClaudeConfigPath (Join-Path $ProjectRoot '.claude') -PersonalStatePath '' -ManagedDataPath $registrationRoot -ManagedInstallPath $distributionRoot -ManagedShortcutPath '')
    foreach ($item in $projectItems) { $item.relativePath = 'project-' + $item.relativePath; $backupItems += $item }
}
foreach ($ownedFile in @($registrationPath, (Join-Path $marketplaceRoot '.claude-plugin\marketplace.json'))) {
    if (Test-Path -LiteralPath $ownedFile -PathType Leaf) {
        $backupItems += [pscustomobject]@{ source = $ownedFile; relativePath = ('company-agent\' + (Split-Path -Leaf $ownedFile)); purpose = 'Company Agent installation registration'; mode = 'sanitized-json' }
    }
}
if ($DryRun) {
    return [pscustomobject]@{
        status = 'dry-run'; scope = $Scope; nativeClaudeScope = $nativeScope; projectRoot = $ProjectRoot
        coreVersion = [string]$manifest.coreVersion; userStateRoot = $UserStateRoot; registrationPath = $registrationPath
        distributionRoot = $distributionRoot; settingsPath = $settingsPath; backupRoot = $BackupRoot
        backupItems = $backupItems; needsElevation = $false; pythonCommand = $resolvedPython
        modelSource = 'existing Claude aliases: haiku/sonnet/opus'; pluginId = $pluginId
    }
}

Write-Host '[2/4] 기존 Claude 설정과 개인 자료를 먼저 백업합니다...'
Write-Host '기존 설정, Skill, Agent, Command, Hook, Plugin 등록 정보를 선택 백업합니다.'
Write-Host '개인 Memory·수정 이력·Knowledge·Skill도 선택 백업하며, 기존 저장 위치는 그대로 사용합니다.'
Write-Host '인증정보와 대화 원문은 제외하며, 설정의 비밀값은 마스킹합니다.'
$backupPath = New-SetupBackup -BackupBase $BackupRoot -Items $backupItems -ClaudeConfigPath $ClaudeConfigRoot -PersonalStatePath $UserStateRoot -ManagedDataPath $registrationRoot -ManagedInstallPath $distributionRoot
Write-Host "Backup: $backupPath"
$snapshots = @(
    (Get-ScopedEntrySnapshot -Path $settingsPath -Container 'enabledPlugins' -Key $pluginId),
    (Get-ScopedEntrySnapshot -Path $settingsPath -Container 'extraKnownMarketplaces' -Key $marketplaceName),
    (Get-ScopedEntrySnapshot -Path $inventoryPath -Container 'plugins' -Key $pluginId),
    (Get-ScopedEntrySnapshot -Path $knownPath -Container '' -Key $marketplaceName)
)
$marketplaceManifestPath = Join-Path $marketplaceRoot '.claude-plugin\marketplace.json'
$oldMarketplace = $null
if (Test-Path -LiteralPath $marketplaceManifestPath -PathType Leaf) { $oldMarketplace = Read-CompanyAgentJson -Path $marketplaceManifestPath }
$oldRegistration = $null
if (Test-Path -LiteralPath $registrationPath -PathType Leaf) { $oldRegistration = Read-CompanyAgentJson -Path $registrationPath }
$previousConfigRoot = [Environment]::GetEnvironmentVariable('CLAUDE_CONFIG_DIR', 'Process')
$releaseCreated = $false
$locationPushed = $false
try {
    Write-Host '[3/4] 오프라인 Plugin을 설치합니다...'
    if (-not (Test-Path -LiteralPath $releaseRoot)) {
        $releaseCreated = $true
        New-CompanyAgentDirectory -Path $releaseRoot
        Copy-CompanyAgentDirectoryContents -Source $sourcePlugin -Destination $releasePlugin
        Copy-CompanyAgentDirectoryContents -Source (Join-Path $BundleRoot 'payload\knowledge') -Destination $releaseKnowledge
        Copy-CompanyAgentDirectoryContents -Source (Join-Path $BundleRoot 'payload\config') -Destination $releaseConfig
        $runtimeForMetadata = $resolvedPython
        if (Test-Path -LiteralPath (Join-Path $releasePlugin 'runtime\python\python.exe') -PathType Leaf) { $runtimeForMetadata = Join-Path $releasePlugin 'runtime\python\python.exe' }
        Write-CompanyAgentJsonAtomic -Path (Join-Path $releasePlugin 'company-agent-install.json') -Value ([pscustomobject]@{
            schemaVersion = 1; registrationsRoot = $registrationsRoot; coreVersion = [string]$manifest.coreVersion
            claudeConfigRoot = $ClaudeConfigRoot; claudeConfigDirOverride = [bool]$usesConfigOverride
            knowledgeBaseRoot = $releaseKnowledge; managedConfigPath = (Join-Path $releaseConfig 'managed.json')
            pythonCommand = $runtimeForMetadata
        })
        Write-CompanyAgentJsonAtomic -Path $releaseReceipt -Value ([pscustomobject]@{ coreVersion = [string]$manifest.coreVersion; knowledgeVersion = [string]$manifest.knowledgeVersion; payloadHash = $payloadHash })
    }
    Write-CompanyAgentJsonAtomic -Path $marketplaceManifestPath -Value ([pscustomobject]@{
        name = $marketplaceName; owner = [pscustomobject]@{ name = 'Company Agent Platform Team' }
        plugins = @([pscustomobject]@{ name = 'company-agent'; source = ('./versions/' + [string]$manifest.coreVersion + '/plugin'); description = 'Company Agent organizational harness and project harness builder' })
    })
    $nativeConfigOverride = $(if ($usesConfigOverride) { $ClaudeConfigRoot } else { $null })
    [Environment]::SetEnvironmentVariable('CLAUDE_CONFIG_DIR', $nativeConfigOverride, 'Process')
    $workingDirectory = $(if ($Scope -eq 'Project') { $ProjectRoot } else { $InvokingUserProfile })
    Push-Location -LiteralPath $workingDirectory
    $locationPushed = $true
    Invoke-ScopedClaude -Arguments @('plugin', 'marketplace', 'add', $marketplaceRoot, '--scope', $nativeScope)
    Invoke-ScopedClaude -Arguments @('plugin', 'install', $pluginId, '--scope', $nativeScope)
    Invoke-ScopedClaude -Arguments @('plugin', 'update', $pluginId, '--scope', $nativeScope)
    $installed = Get-SetupPropertyValue -Object (Read-ScopedJsonOrEmpty -Path $inventoryPath) -Name 'plugins'
    $entries = @(Get-SetupPropertyValue -Object $installed -Name $pluginId)
    $matching = @($entries | Where-Object {
        $entryScope = [string](Get-SetupPropertyValue -Object $_ -Name 'scope')
        $entryProject = [string](Get-SetupPropertyValue -Object $_ -Name 'projectPath')
        $entryScope -eq $nativeScope -and ($Scope -eq 'User' -or ($entryProject -and (Get-SetupFullPath -Path $entryProject).TrimEnd('\') -ieq $ProjectRoot))
    })
    if ($matching.Count -eq 0) { throw 'Claude reported success but the requested plugin scope was not present in installed_plugins.json.' }
    $enabledPlugins = Get-SetupPropertyValue -Object (Read-ScopedJsonOrEmpty -Path $settingsPath) -Name 'enabledPlugins'
    if ((Get-SetupPropertyValue -Object $enabledPlugins -Name $pluginId) -ne $true) { throw 'Claude did not enable the plugin in the selected settings scope.' }
    $installedPython = $resolvedPython
    if (Test-Path -LiteralPath (Join-Path $releasePlugin 'runtime\python\python.exe') -PathType Leaf) { $installedPython = Join-Path $releasePlugin 'runtime\python\python.exe' }
    $registration = [pscustomobject]@{
        schemaVersion = 1; scope = $Scope; nativeClaudeScope = $nativeScope; projectRoot = $ProjectRoot
        userStateRoot = $UserStateRoot; pythonCommand = $installedPython
        knowledgeBaseRoot = $releaseKnowledge; managedConfigPath = (Join-Path $releaseConfig 'managed.json')
        coreVersion = [string]$manifest.coreVersion; knowledgeVersion = [string]$manifest.knowledgeVersion
        pluginId = $pluginId; claudeConfigRoot = $ClaudeConfigRoot; claudeConfigDirOverride = [bool]$usesConfigOverride
        installedAtUtc = [DateTime]::UtcNow.ToString('o')
    }
    Write-CompanyAgentJsonAtomic -Path $registrationPath -Value $registration
    Write-Host '[4/4] 설치가 완료되었습니다.'
    Write-Host 'Claude Code를 닫았다 다시 열면 Company Agent가 적용됩니다.'
    if ($Scope -eq 'Project') { Write-Host "이 프로젝트 폴더에서 Claude를 열어 주세요: $ProjectRoot" }
    else { Write-Host '현재 Windows 계정의 Claude Code 작업에서 사용할 수 있습니다.' }
    Write-Host '모델 설정은 기존 값을 재사용하며, MCP는 별도로 연결할 수 있습니다.'
    Write-Host "개인 자료 저장 위치: $UserStateRoot"
    Write-Host "백업 위치: $backupPath"
    return [pscustomobject]@{ status = 'installed'; scope = $Scope; nativeClaudeScope = $nativeScope; projectRoot = $ProjectRoot; pluginId = $pluginId; coreVersion = [string]$manifest.coreVersion; userStateRoot = $UserStateRoot; registrationPath = $registrationPath; safetyBackup = $backupPath; needsElevation = $false }
}
catch {
    $failure = $_.Exception.Message
    $recoveryErrors = @()
    foreach ($snapshot in $snapshots) {
        try { Restore-ScopedEntry -Snapshot $snapshot } catch { $recoveryErrors += $_.Exception.Message }
    }
    try {
        if ($null -ne $oldMarketplace) { Write-CompanyAgentJsonAtomic -Path $marketplaceManifestPath -Value $oldMarketplace }
        elseif (Test-Path -LiteralPath $marketplaceManifestPath -PathType Leaf) { Remove-Item -LiteralPath $marketplaceManifestPath -Force }
        if ($null -ne $oldRegistration) { Write-CompanyAgentJsonAtomic -Path $registrationPath -Value $oldRegistration }
        elseif (Test-Path -LiteralPath $registrationPath -PathType Leaf) { Remove-Item -LiteralPath $registrationPath -Force }
        if ($releaseCreated -and (Test-Path -LiteralPath $releaseRoot)) {
            Assert-SetupPathHasNoReparsePoint -Path $releaseRoot -Name 'Failed release'
            if (-not (Test-SetupSameOrChildPath -Candidate $releaseRoot -Parent (Join-Path $marketplaceRoot 'versions'))) { throw 'Failed release cleanup escaped the owned versions directory.' }
            Remove-Item -LiteralPath $releaseRoot -Recurse -Force
        }
    }
    catch { $recoveryErrors += $_.Exception.Message }
    if ($recoveryErrors.Count -gt 0) { throw "$failure Recovery needs attention: $($recoveryErrors -join '; '). Backup: $backupPath" }
    throw "$failure Company Agent registration was restored. Other Claude registrations and personal state were preserved. Backup: $backupPath"
}
finally {
    if ($locationPushed) { Pop-Location }
    [Environment]::SetEnvironmentVariable('CLAUDE_CONFIG_DIR', $previousConfigRoot, 'Process')
}
