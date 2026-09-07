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
    [ValidateSet('Ask', 'Keep', 'Replace', 'Update')]
    [string] $ExistingHarnessAction = 'Ask',
    [ValidateSet('Ask', 'KeepCurrent', 'PreferIncoming')]
    [string] $SkillConflictAction = 'Ask',
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
    'DryRun', 'SkipAdminCheck', 'SkipPrerequisiteCheck', 'SkipBundleVerification', 'ExistingHarnessAction', 'SkillConflictAction')) {
    $scopedEntryValues[$name] = Get-Variable -Name $name -ValueOnly
}
. (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1') -FunctionsOnly
foreach ($name in $scopedEntryValues.Keys) { Set-Variable -Name $name -Value $scopedEntryValues[$name] }
. (Join-Path $PSScriptRoot 'ExistingHarness.ps1')
. (Join-Path $PSScriptRoot 'HarnessReplacement.ps1')
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

function Get-ScopedRawProperty {
    param([byte[]] $Bytes, [string] $Key)
    $document = Get-SetupHarnessJsonProperties -Bytes $Bytes
    $properties = @($document.properties | Where-Object { $_.name -ieq $Key })
    if ($properties.Count -eq 0) { return $null }
    $property = $properties[0]
    return $document.text.Substring($property.valueStart, $property.end - $property.valueStart)
}

function Set-ScopedRawProperty {
    param([byte[]] $Bytes, [string] $Key, [bool] $Exists, [string] $RawValue)
    $document = Get-SetupHarnessJsonProperties -Bytes $Bytes
    $properties = @($document.properties | Where-Object { $_.name -ieq $Key })
    $text = $document.text
    if ($properties.Count -gt 0) {
        $property = $properties[0]
        if ($Exists) {
            $text = $text.Substring(0, $property.valueStart) + $RawValue + $text.Substring($property.end)
        }
        else {
            $start = $property.start
            $end = $property.end
            if ($property.followingComma -ge 0) { $end = $property.followingComma + 1 }
            elseif ($property.previousComma -ge 0) { $start = $property.previousComma }
            $text = $text.Substring(0, $start) + $text.Substring($end)
        }
    }
    elseif ($Exists) {
        $separator = $(if (@($document.properties).Count -gt 0) { ',' } else { '' })
        $encodedKey = ConvertTo-Json -InputObject $Key -Compress
        $text = $text.Substring(0, $document.close) + $separator + $encodedKey + ':' + $RawValue + $text.Substring($document.close)
    }
    $result = ConvertTo-SetupHarnessUtf8Bytes -Text $text -Bom $document.bom
    $null = Get-SetupHarnessJsonProperties -Bytes $result
    return ,$result
}

function Get-ScopedEntrySnapshot {
    param([string] $Path, [string] $Container, [string] $Key)
    $document = Read-ScopedJsonOrEmpty -Path $Path
    $parent = $document
    if ($Container) { $parent = Get-SetupPropertyValue -Object $document -Name $Container }
    $property = $null
    if ($null -ne $parent) { $property = $parent.PSObject.Properties[$Key] }
    $rawValue = $null
    if ($null -ne $property) {
        $sourceBytes = Read-SetupHarnessBytes -Path $Path
        if ($Container) {
            $containerRaw = Get-ScopedRawProperty -Bytes $sourceBytes -Key $Container
            $sourceBytes = ConvertTo-SetupHarnessUtf8Bytes -Text $containerRaw
        }
        $rawValue = Get-ScopedRawProperty -Bytes $sourceBytes -Key $Key
    }
    return [pscustomobject]@{
        path = $Path; container = $Container; key = $Key
        fileExisted = (Test-Path -LiteralPath $Path -PathType Leaf)
        containerExisted = ($null -ne $parent)
        existed = ($null -ne $property)
        value = $(if ($null -ne $property) { $property.Value } else { $null })
        rawValue = $rawValue
    }
}

function Restore-ScopedEntry {
    param([object] $Snapshot)
    Assert-SetupPathHasNoReparsePoint -Path $Snapshot.path -Name 'Registration restore target'
    $fileExists = Test-Path -LiteralPath $Snapshot.path -PathType Leaf
    $sourceBytes = $(if ($fileExists) { Read-SetupHarnessBytes -Path $Snapshot.path } else { ConvertTo-SetupHarnessUtf8Bytes -Text '{}' })
    $beforeHash = Get-SetupHarnessHash -Bytes $sourceBytes
    $resultBytes = $sourceBytes
    if ($Snapshot.container) {
        $containerRaw = Get-ScopedRawProperty -Bytes $sourceBytes -Key $Snapshot.container
        if ($null -ne $containerRaw -or $Snapshot.existed) {
            if ($null -eq $containerRaw) { $containerRaw = '{}' }
            $containerBytes = Set-ScopedRawProperty -Bytes (ConvertTo-SetupHarnessUtf8Bytes -Text $containerRaw) -Key $Snapshot.key -Exists ([bool]$Snapshot.existed) -RawValue $Snapshot.rawValue
            $containerDocument = Get-SetupHarnessJsonProperties -Bytes $containerBytes
            $keepContainer = [bool]$Snapshot.containerExisted -or @($containerDocument.properties).Count -gt 0
            $resultBytes = Set-ScopedRawProperty -Bytes $sourceBytes -Key $Snapshot.container -Exists $keepContainer -RawValue $containerDocument.text
        }
    }
    else {
        $resultBytes = Set-ScopedRawProperty -Bytes $sourceBytes -Key $Snapshot.key -Exists ([bool]$Snapshot.existed) -RawValue $Snapshot.rawValue
    }
    $resultDocument = Get-SetupHarnessJsonProperties -Bytes $resultBytes
    if (-not $Snapshot.fileExisted -and @($resultDocument.properties).Count -eq 0) {
        if ($fileExists) {
            if ((Get-SetupHarnessHash -Bytes (Read-SetupHarnessBytes -Path $Snapshot.path)) -cne $beforeHash) { throw 'Claude registration changed during rollback; review the backup before retrying.' }
            Remove-Item -LiteralPath $Snapshot.path -Force
        }
    }
    elseif ((Get-SetupHarnessHash -Bytes $resultBytes) -cne $beforeHash -or -not $fileExists) {
        if ($fileExists) { Write-SetupHarnessBytesAtomic -Path $Snapshot.path -Bytes $resultBytes -ExpectedHash $beforeHash }
        else { Write-SetupHarnessBytesAtomic -Path $Snapshot.path -Bytes $resultBytes -AssertMissing }
    }
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
    if ([string](Get-SetupPropertyValue -Object $existingScopeRegistration -Name 'pluginId') -cne 'company-agent@company-agent-local' -or
        (Get-SetupDisplayVersion -Value (Get-SetupPropertyValue -Object $existingScopeRegistration -Name 'coreVersion')) -eq 'unknown') {
        throw "The existing installation record does not identify a supported Company Agent plugin/version: $registrationPath. No installation or personal data was changed."
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
# Verify the proposed version before presenting it as an available update.
$manifest = $(if ($SkipBundleVerification) { Read-CompanyAgentJson -Path (Join-Path $BundleRoot 'bundle-manifest.json') } else { Test-CompanyAgentBundleIntegrity -BundleRoot $BundleRoot })
Assert-CompanyAgentVersion -Version ([string]$manifest.coreVersion) -Name 'CoreVersion'
Assert-CompanyAgentVersion -Version ([string]$manifest.knowledgeVersion) -Name 'KnowledgeVersion'
$existingHarness = Get-SetupExistingHarness -Scope $Scope -ClaudeConfigRoot $ClaudeConfigRoot -ProjectRoot $ProjectRoot -ExistingRegistration $existingScopeRegistration
$intent = Get-SetupInstallationIntent -Inventory $existingHarness -TargetCoreVersion ([string]$manifest.coreVersion) -TargetKnowledgeVersion ([string]$manifest.knowledgeVersion)
$harnessAction = Resolve-SetupExistingHarnessAction -Inventory $existingHarness -Action $ExistingHarnessAction -TargetCoreVersion $intent.coreVersion -TargetKnowledgeVersion $intent.knowledgeVersion -NonInteractive:$NonInteractive -DryRun:$DryRun
if ($harnessAction -eq 'InputRequired') {
    $choices = @('Keep', 'Replace')
    $choiceMessage = 'Ask the user to keep the existing harness or back it up, deactivate scoped instructions/custom hooks, and install Company Agent. No files were changed.'
    if ($intent.hasCompanyAgent) {
        Write-SetupCompanyAgentUpdateSummary -Intent $intent -Inventory $existingHarness
        Write-Host '백업 후 업데이트/다시 적용: -ExistingHarnessAction Update / 현재 버전 유지: -ExistingHarnessAction Keep'
        $choices = @('Update', 'Keep')
        $choiceMessage = 'Existing Company Agent: ask to update/reapply common components with a safety backup, or keep the current version. Update preserves all current rules/hooks and personal data. No files were changed.'
    }
    else {
        Write-Host '기존 하네스가 있습니다. 기존 구성을 유지할지, 백업 후 Company Agent로 설치할지 선택해 주세요.'
        Write-Host '기존 유지: -ExistingHarnessAction Keep / 백업 후 설치: -ExistingHarnessAction Replace'
    }
    return [pscustomobject]@{
        status = 'input-required'; input = 'ExistingHarnessAction'; choices = $choices
        operation = $intent.operation; previousCoreVersion = $intent.previousCoreVersion; coreVersion = $intent.coreVersion
        scope = $Scope; projectRoot = $ProjectRoot; existingHarness = $existingHarness
        userStateRoot = $UserStateRoot; backupRoot = $BackupRoot; dryRun = [bool]$DryRun
        message = $choiceMessage
    }
}
if ($harnessAction -eq 'Keep') {
    if ($intent.hasCompanyAgent) { Write-Host ("현재 Company Agent {0} 버전을 유지합니다. 업데이트와 설정 변경은 하지 않았습니다." -f $intent.previousCoreVersion) }
    else { Write-Host '기존 하네스를 그대로 유지합니다. Company Agent 설치·업데이트와 설정 변경은 하지 않았습니다.' }
    return [pscustomobject]@{
        status = 'kept'; scope = $Scope; projectRoot = $ProjectRoot; existingHarness = $existingHarness
        userStateRoot = $UserStateRoot; changed = $false; dryRun = [bool]$DryRun
        operation = $intent.operation; previousCoreVersion = $intent.previousCoreVersion; coreVersion = $intent.previousCoreVersion
    }
}
Write-Host ''
if ($intent.hasCompanyAgent -and ($ExistingHarnessAction -ne 'Ask' -or $NonInteractive -or $DryRun)) { Write-SetupCompanyAgentUpdateSummary -Intent $intent -Inventory $existingHarness -ReplaceCustomHarness:($harnessAction -eq 'Replace') }
Write-Host ("Company Agent {0} - {1}" -f $intent.operation, $Scope)
Write-Host '[1/4] 설치 파일과 기존 Claude Code의 실행 조건을 확인합니다...'
Assert-SetupPathHasNoReparsePoint -Path (Join-Path $ClaudeConfigRoot ('plugins\cache\company-agent-local\company-agent\' + [string]$manifest.coreVersion)) -Name 'Claude plugin cache target'
$sourcePlugin = Join-Path $BundleRoot 'payload\core\plugin'
$sourceRuntime = Join-Path $sourcePlugin 'runtime\python\python.exe'
$resolvedPython = $null
if (Test-Path -LiteralPath $sourceRuntime -PathType Leaf) { $resolvedPython = Resolve-SetupApprovedPython -PreferredCommand $sourceRuntime }
if ([string]::IsNullOrWhiteSpace($resolvedPython)) { $resolvedPython = Get-SetupPythonForInstall -PreferredCommand $PythonCommand -NonInteractive:$NonInteractive -DryRun:$DryRun }
$script:ScopedClaudeExecutable = Resolve-SetupCommand -Command $ClaudeCommand
if ([string]::IsNullOrWhiteSpace($script:ScopedClaudeExecutable)) { throw 'The claude command is unavailable. Open a new terminal after installing Claude Code, then run this installer again.' }
Write-Host ("사용할 Python: {0}" -f $resolvedPython)
if (-not $SkipPrerequisiteCheck) {
    Assert-CompanyAgentPrerequisites -ClaudeCommand $script:ScopedClaudeExecutable -PythonCommand $resolvedPython
}
$stateCheckScript = Join-Path $sourcePlugin 'scripts\harness_cli.py'
$stateCheckResult = Invoke-CompanyAgentPythonProcess -Executable $resolvedPython -Arguments @('-B', $stateCheckScript, 'state', 'check', '--state-root', $UserStateRoot)
if ($stateCheckResult.ExitCode -ne 0) {
    throw ("The new Company Agent package cannot read the existing personal state at '$UserStateRoot'. Keep that folder and use the previous compatible package, or ask the package owner for a supported migration. No installation or personal data was changed. Details: " + $stateCheckResult.StdErr + [Environment]::NewLine + $stateCheckResult.StdOut)
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
# Native Claude plugin commands rewrite JSON settings. Reject integer literals
# that their JavaScript number representation cannot preserve before any write.
Assert-SetupNativeSettingsIntegerSafety -Paths @($modelSettingsPaths | Select-Object -Unique)
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
$runtimeSelectionPath = Join-Path $releaseRoot 'runtime-selection.json'
Assert-SetupPathHasNoReparsePoint -Path $runtimeSelectionPath -Name 'Runtime selection'
$payloadRecords = @($manifest.files | Where-Object { $_.path -like 'payload/*' } | Sort-Object path | ForEach-Object { "$($_.path)|$($_.sha256)|$($_.length)" })
$payloadHash = Get-ScopedHash -Text ($payloadRecords -join "`n")
$releaseReceipt = Join-Path $releaseRoot 'release.json'
if (Test-Path -LiteralPath $releaseRoot) {
    if (-not (Test-Path -LiteralPath $releaseReceipt -PathType Leaf)) { throw "An incomplete release exists at $releaseRoot. Ask the package owner to inspect this folder before retrying." }
    $existingRelease = Read-CompanyAgentJson -Path $releaseReceipt
    if ([string]$existingRelease.payloadHash -cne $payloadHash) { throw "This Core version already exists with different contents. The package owner must increase CoreVersion before redistributing ($($manifest.coreVersion))." }
}

$skillCommandParameters = @{
    PythonExecutable = $resolvedPython; PluginRoot = $sourcePlugin; PersonalStatePath = $UserStateRoot
    KnowledgeRoot = (Join-Path $BundleRoot 'payload\knowledge')
    ClaudeConfigPath = $ClaudeConfigRoot; ProjectPath = $ProjectRoot; InstallScope = $Scope
}
$skillInventory = Invoke-SetupSkillCommand @skillCommandParameters
$skillPreferencesPath = Join-Path $UserStateRoot 'config\skill-preferences.json'
if ((Get-SetupFullPath -Path ([string]$skillInventory.preferencesPath)) -ine (Get-SetupFullPath -Path $skillPreferencesPath)) {
    throw 'Skill inventory returned a preferences path outside the selected personal state. No installation changes were made.'
}
Assert-SetupPathHasNoReparsePoint -Path $skillPreferencesPath -Name 'Skill preferences'
$skillConflicts = @($skillInventory.conflicts | Where-Object {
    @($_.candidates | Where-Object { $_.incoming }).Count -gt 0 -and
    @($_.candidates | Where-Object { -not $_.incoming }).Count -gt 0
})
foreach ($warning in @($skillInventory.warnings)) { Write-Warning ("Skill inventory: {0}" -f $warning) }
$resolvedSkillAction = Resolve-SetupSkillConflictAction -Conflicts $skillConflicts -Action $SkillConflictAction -NonInteractive:$NonInteractive -DryRun:$DryRun
if ($resolvedSkillAction -eq 'InputRequired') {
    return [pscustomobject]@{
        status = 'input-required'; input = 'SkillConflictAction'; choices = @('KeepCurrent', 'PreferIncoming')
        scope = $Scope; projectRoot = $ProjectRoot; userStateRoot = $UserStateRoot
        skillConflicts = $skillConflicts; conflicts = $skillConflicts; skillConflictAction = 'Ask'
        skillWarnings = @($skillInventory.warnings); dryRun = [bool]$DryRun; changed = $false
        message = 'Choose KeepCurrent to preserve current Skill preferences, or PreferIncoming to select incoming Skills for this scope. Namespaced plugin Skills coexist; no files were changed.'
    }
}
if ($resolvedSkillAction -eq 'Cancel') {
    return [pscustomobject]@{
        status = 'cancelled'; scope = $Scope; projectRoot = $ProjectRoot; changed = $false
        skillConflicts = $skillConflicts; skillConflictAction = 'Cancel'; dryRun = [bool]$DryRun
    }
}

$backupItems = @(Get-SetupBackupItems -ClaudeConfigPath $ClaudeConfigRoot -PersonalStatePath $UserStateRoot -ManagedDataPath $registrationRoot -ManagedInstallPath $distributionRoot -ManagedShortcutPath '')
if ($Scope -eq 'Project' -and (Test-Path -LiteralPath (Join-Path $ProjectRoot '.claude') -PathType Container)) {
    # Personal state was already selected above; only add project Claude files.
    $projectItems = @(Get-SetupBackupItems -ClaudeConfigPath (Join-Path $ProjectRoot '.claude') -PersonalStatePath '' -ManagedDataPath $registrationRoot -ManagedInstallPath $distributionRoot -ManagedShortcutPath '')
    foreach ($item in $projectItems) { $item.relativePath = 'project-' + $item.relativePath; $backupItems += $item }
}
if ($Scope -eq 'Project') {
    foreach ($instructionName in @('CLAUDE.md', 'CLAUDE.local.md')) {
        $instructionPath = Join-Path $ProjectRoot $instructionName
        if (Test-Path -LiteralPath $instructionPath -PathType Leaf) {
            $backupItems += [pscustomobject]@{
                source = $instructionPath; relativePath = ('project-root\' + $instructionName)
                purpose = 'Project root Claude instruction before harness replacement'; mode = 'copy'; required = $true
            }
        }
    }
}
foreach ($ownedFile in @($registrationPath, $runtimeSelectionPath, (Join-Path $marketplaceRoot '.claude-plugin\marketplace.json'))) {
    if (Test-Path -LiteralPath $ownedFile -PathType Leaf) {
        $backupItems += [pscustomobject]@{ source = $ownedFile; relativePath = ('company-agent\' + (Split-Path -Leaf $ownedFile)); purpose = 'Company Agent installation registration'; mode = 'sanitized-json' }
    }
}
if ($DryRun) {
    return [pscustomobject]@{
        status = 'dry-run'; scope = $Scope; nativeClaudeScope = $nativeScope; projectRoot = $ProjectRoot
        operation = $intent.operation; previousCoreVersion = $intent.previousCoreVersion
        coreVersion = [string]$manifest.coreVersion; userStateRoot = $UserStateRoot; registrationPath = $registrationPath
        distributionRoot = $distributionRoot; settingsPath = $settingsPath; backupRoot = $BackupRoot
        backupItems = $backupItems; needsElevation = $false; pythonCommand = $resolvedPython
        modelSource = 'existing Claude aliases: haiku/sonnet/opus'; pluginId = $pluginId
        existingHarness = $existingHarness; existingHarnessAction = $harnessAction
        skillConflicts = $skillConflicts; skillConflictAction = $resolvedSkillAction; skillWarnings = @($skillInventory.warnings)
    }
}

Write-Host '[2/4] 기존 Claude 설정과 개인 자료를 먼저 백업합니다...'
Write-Host '기존 설정, Skill, Agent, Command, Hook, Plugin 등록 정보를 선택 백업합니다.'
Write-Host '개인 Memory·수정 이력·Knowledge·Skill도 선택 백업하며, 기존 저장 위치는 그대로 사용합니다.'
Write-Host '인증정보와 대화 원문은 제외하며, 설정의 비밀값은 마스킹합니다.'
$backupPath = New-SetupBackup -BackupBase $BackupRoot -Items $backupItems -ClaudeConfigPath $ClaudeConfigRoot -PersonalStatePath $UserStateRoot -ManagedDataPath $registrationRoot -ManagedInstallPath $distributionRoot
Write-Host "Backup: $backupPath"
$harnessTransaction = $null
if ($harnessAction -eq 'Replace' -and (@($existingHarness.replacementFiles).Count -gt 0 -or @($existingHarness.hookSettingsPaths).Count -gt 0)) {
    # Persist and verify every exact snapshot before removing any instruction/hook.
    $harnessTransaction = New-SetupHarnessReplacementBackup -BackupPath $backupPath -Inventory $existingHarness
}
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
$oldRuntimeSelection = $null
if (Test-Path -LiteralPath $runtimeSelectionPath -PathType Leaf) { $oldRuntimeSelection = Read-SetupHarnessBytes -Path $runtimeSelectionPath }
$runtimeSelectionChanged = $false
$oldSkillPreferences = $null
$skillPreferencesChanged = $false
if ($resolvedSkillAction -eq 'PreferIncoming' -and $skillConflicts.Count -gt 0) {
    Assert-SetupPathHasNoReparsePoint -Path $skillPreferencesPath -Name 'Skill preferences snapshot'
    if (Test-Path -LiteralPath $skillPreferencesPath -PathType Leaf) {
        $oldSkillPreferences = Read-SetupHarnessBytes -Path $skillPreferencesPath
        # Keep an exact, independently verifiable recovery copy after the overall
        # backup succeeds and before the first installation mutation.
        $exactPreferenceBackup = Join-Path $backupPath 'company-agent\skill-preferences.before-install.json'
        Write-SetupHarnessBytesAtomic -Path $exactPreferenceBackup -Bytes $oldSkillPreferences -AssertMissing
        if ((Get-SetupHarnessHash -Bytes (Read-SetupHarnessBytes -Path $exactPreferenceBackup)) -cne (Get-SetupHarnessHash -Bytes $oldSkillPreferences)) {
            throw 'Skill preference recovery backup verification failed. Installation did not start.'
        }
    }
}
$previousConfigRoot = [Environment]::GetEnvironmentVariable('CLAUDE_CONFIG_DIR', 'Process')
$releaseCreated = $false
$locationPushed = $false
try {
    if ($resolvedSkillAction -eq 'PreferIncoming' -and $skillConflicts.Count -gt 0) {
        $skillPreferencesChanged = $true
        $null = Invoke-SetupSkillCommand @skillCommandParameters -Command 'prefer-incoming'
    }
    if ($null -ne $harnessTransaction) {
        Write-Host '기존 규칙·Hook의 암호화 백업을 확인했습니다. 선택한 범위에서만 비활성화합니다.'
        $null = Invoke-SetupHarnessReplacement -Transaction $harnessTransaction
    }
    if ($intent.operation -eq 'update') { Write-Host '[3/4] Company Agent 공통 구성을 새 버전으로 업데이트합니다...' }
    elseif ($intent.operation -eq 'reapply') { Write-Host '[3/4] 같은 버전의 Company Agent 등록과 실행 환경을 다시 적용합니다...' }
    else { Write-Host '[3/4] 오프라인 Plugin을 설치합니다...' }
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
            pythonCommand = $runtimeForMetadata; runtimeSelectionPath = $runtimeSelectionPath
        })
        Write-CompanyAgentJsonAtomic -Path $releaseReceipt -Value ([pscustomobject]@{ coreVersion = [string]$manifest.coreVersion; knowledgeVersion = [string]$manifest.knowledgeVersion; payloadHash = $payloadHash })
    }
    # A durable pointer also reaches already-cached copies of this release when
    # setup is rerun after an external interpreter moves or is replaced.
    $installedPython = $resolvedPython
    if (Test-Path -LiteralPath (Join-Path $releasePlugin 'runtime\python\python.exe') -PathType Leaf) { $installedPython = Join-Path $releasePlugin 'runtime\python\python.exe' }
    Assert-SetupPathHasNoReparsePoint -Path $runtimeSelectionPath -Name 'Runtime selection'
    $runtimeSelectionChanged = $true
    Write-CompanyAgentJsonAtomic -Path $runtimeSelectionPath -Value ([pscustomobject]@{
        schemaVersion = 1; coreVersion = [string]$manifest.coreVersion; pythonCommand = $installedPython
    })
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
    if ($matching.Count -ne 1 -or [string](Get-SetupPropertyValue -Object $matching[0] -Name 'version') -cne [string]$manifest.coreVersion) {
        throw 'Claude did not register exactly the requested Company Agent version in this scope. Update was not completed; restoring the previous registration.'
    }
    $enabledPlugins = Get-SetupPropertyValue -Object (Read-ScopedJsonOrEmpty -Path $settingsPath) -Name 'enabledPlugins'
    if ((Get-SetupPropertyValue -Object $enabledPlugins -Name $pluginId) -ne $true) { throw 'Claude did not enable the plugin in the selected settings scope.' }
    $registration = [pscustomobject]@{
        schemaVersion = 1; scope = $Scope; nativeClaudeScope = $nativeScope; projectRoot = $ProjectRoot
        userStateRoot = $UserStateRoot; pythonCommand = $installedPython
        knowledgeBaseRoot = $releaseKnowledge; managedConfigPath = (Join-Path $releaseConfig 'managed.json')
        coreVersion = [string]$manifest.coreVersion; knowledgeVersion = [string]$manifest.knowledgeVersion
        pluginId = $pluginId; claudeConfigRoot = $ClaudeConfigRoot; claudeConfigDirOverride = [bool]$usesConfigOverride
        installedAtUtc = [DateTime]::UtcNow.ToString('o')
    }
    Write-CompanyAgentJsonAtomic -Path $registrationPath -Value $registration
    if ($null -ne $harnessTransaction) { $null = Complete-SetupHarnessReplacement -Transaction $harnessTransaction }
    $resultStatus = 'installed'
    if ($intent.operation -eq 'update') {
        $resultStatus = 'updated'
        Write-Host ("[4/4] Company Agent 업데이트가 완료되었습니다. {0} -> {1}" -f $intent.previousCoreVersion, $manifest.coreVersion)
    }
    elseif ($intent.operation -eq 'reapply') {
        $resultStatus = 'reapplied'
        Write-Host ("[4/4] Company Agent {0} 같은 버전 다시 적용이 완료되었습니다." -f $manifest.coreVersion)
    }
    else { Write-Host '[4/4] 설치가 완료되었습니다.' }
    Write-Host 'Claude Code를 닫았다 다시 열면 Company Agent가 적용됩니다.'
    if ($Scope -eq 'Project') { Write-Host "이 프로젝트 폴더에서 Claude를 열어 주세요: $ProjectRoot" }
    else { Write-Host '현재 Windows 계정의 Claude Code 작업에서 사용할 수 있습니다.' }
    Write-Host '모델 설정은 기존 값을 재사용하며, MCP는 별도로 연결할 수 있습니다.'
    Write-Host "개인 자료 저장 위치: $UserStateRoot"
    Write-Host "백업 위치: $backupPath"
    if ($null -ne $harnessTransaction) { Write-Host '기존 하네스 복원 자료: 백업 폴더의 previous-harness (현재 Windows 계정으로 복원)' }
    foreach ($note in @($existingHarness.inheritedNotes)) { Write-Host ([string]$note) }
    return [pscustomobject]@{ status = $resultStatus; operation = $intent.operation; previousCoreVersion = $intent.previousCoreVersion; scope = $Scope; nativeClaudeScope = $nativeScope; projectRoot = $ProjectRoot; pluginId = $pluginId; coreVersion = [string]$manifest.coreVersion; userStateRoot = $UserStateRoot; registrationPath = $registrationPath; safetyBackup = $backupPath; needsElevation = $false; existingHarnessAction = $harnessAction; previousHarnessDeactivated = ($null -ne $harnessTransaction); existingHarness = $existingHarness; skillConflicts = $skillConflicts; skillConflictAction = $resolvedSkillAction; skillWarnings = @($skillInventory.warnings) }
}
catch {
    $failure = $_.Exception.Message
    $recoveryErrors = @()
    if ($skillPreferencesChanged) {
        try {
            Assert-SetupPathHasNoReparsePoint -Path $skillPreferencesPath -Name 'Skill preference recovery'
            if ($null -ne $oldSkillPreferences) { Write-SetupHarnessBytesAtomic -Path $skillPreferencesPath -Bytes $oldSkillPreferences }
            elseif (Test-Path -LiteralPath $skillPreferencesPath -PathType Leaf) { Remove-Item -LiteralPath $skillPreferencesPath -Force }
        }
        catch { $recoveryErrors += $_.Exception.Message }
    }
    if ($runtimeSelectionChanged) {
        try {
            Assert-SetupPathHasNoReparsePoint -Path $runtimeSelectionPath -Name 'Runtime selection recovery'
            if ($null -ne $oldRuntimeSelection) { Write-SetupHarnessBytesAtomic -Path $runtimeSelectionPath -Bytes $oldRuntimeSelection }
            elseif (Test-Path -LiteralPath $runtimeSelectionPath -PathType Leaf) { Remove-Item -LiteralPath $runtimeSelectionPath -Force }
        }
        catch { $recoveryErrors += $_.Exception.Message }
    }
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
    if ($null -ne $harnessTransaction) {
        try { $null = Restore-SetupHarnessReplacement -Transaction $harnessTransaction }
        catch { $recoveryErrors += $_.Exception.Message }
    }
    if ($recoveryErrors.Count -gt 0) { throw "$failure Recovery needs attention: $($recoveryErrors -join '; '). Backup: $backupPath" }
    if ($skillPreferencesChanged) {
        throw "$failure Company Agent registration and any deactivated previous harness were restored. Exact prior Skill preferences were restored; Skill preference revision history remains available as recovery evidence. Other Claude registrations and personal state were preserved. Backup: $backupPath"
    }
    throw "$failure Company Agent registration and any deactivated previous harness were restored. Other Claude registrations and personal state were preserved. Backup: $backupPath"
}
finally {
    if ($locationPushed) { Pop-Location }
    [Environment]::SetEnvironmentVariable('CLAUDE_CONFIG_DIR', $previousConfigRoot, 'Process')
}
