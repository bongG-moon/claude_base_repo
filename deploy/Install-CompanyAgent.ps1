[CmdletBinding()]
param(
    [string] $BundleRoot,
    [string] $CoreVersion,
    [string] $KnowledgeVersion,
    [Alias('SmallModel')]
    [string] $SmallModelId,
    [Alias('MediumModel')]
    [string] $MediumModelId,
    [Alias('LargeModel')]
    [string] $LargeModelId,
    [string] $DefaultTier,
    [switch] $UseExistingClaudeModels,
    [string] $InstallRoot,
    [string] $DataRoot,
    [string] $UserStateRoot,
    [string] $ClaudeCommand = 'claude',
    [string] $PythonCommand = 'python',
    [string] $ShortcutPath,
    [switch] $SkipAcl,
    [switch] $SkipAdminCheck,
    [switch] $SkipPrerequisiteCheck,
    [switch] $SkipShortcut,
    [switch] $SkipBundleVerification
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')

if ([string]::IsNullOrWhiteSpace($BundleRoot)) {
    $BundleRoot = Split-Path -Parent $PSScriptRoot
}
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Get-CompanyAgentDefaultInstallRoot
}
if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $DataRoot = Get-CompanyAgentDefaultDataRoot
}
if ([string]::IsNullOrWhiteSpace($UserStateRoot)) {
    $UserStateRoot = Get-CompanyAgentDefaultUserStateRoot
}

$BundleRoot = ConvertTo-CompanyAgentFullPath -Path $BundleRoot
$InstallRoot = ConvertTo-CompanyAgentFullPath -Path $InstallRoot
$DataRoot = ConvertTo-CompanyAgentFullPath -Path $DataRoot
$UserStateRoot = ConvertTo-CompanyAgentFullPath -Path $UserStateRoot
if ([string]::IsNullOrWhiteSpace($ShortcutPath)) {
    $ShortcutPath = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Company Agent.lnk'
}
$ShortcutPath = ConvertTo-CompanyAgentFullPath -Path $ShortcutPath

Assert-CompanyAgentRootsSeparated -InstallRoot $InstallRoot -DataRoot $DataRoot -UserStateRoot $UserStateRoot

Assert-CompanyAgentAdministrator -SkipAdminCheck:$SkipAdminCheck
Assert-CompanyAgentPrerequisites -ClaudeCommand $ClaudeCommand -PythonCommand $PythonCommand -SkipPrerequisiteCheck:$SkipPrerequisiteCheck

$manifestPath = Join-Path $BundleRoot 'bundle-manifest.json'
$manifest = $null
if ($SkipBundleVerification) {
    if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
        $manifest = Read-CompanyAgentJson -Path $manifestPath
    }
}
else {
    $manifest = Test-CompanyAgentBundleIntegrity -BundleRoot $BundleRoot
}

if ([string]::IsNullOrWhiteSpace($CoreVersion) -and $null -ne $manifest) {
    $CoreVersion = [string]$manifest.coreVersion
}
if ([string]::IsNullOrWhiteSpace($KnowledgeVersion) -and $null -ne $manifest) {
    $KnowledgeVersion = [string]$manifest.knowledgeVersion
}
if ([string]::IsNullOrWhiteSpace($CoreVersion) -or [string]::IsNullOrWhiteSpace($KnowledgeVersion)) {
    throw 'CoreVersion and KnowledgeVersion must be provided directly or by bundle-manifest.json.'
}
Assert-CompanyAgentVersion -Version $CoreVersion -Name 'CoreVersion'
Assert-CompanyAgentVersion -Version $KnowledgeVersion -Name 'KnowledgeVersion'

$coreSource = Join-Path $BundleRoot 'payload\core\plugin'
$knowledgeSource = Join-Path $BundleRoot 'payload\knowledge'
if (-not (Test-Path -LiteralPath $coreSource -PathType Container)) {
    throw "Core plugin payload was not found: $coreSource"
}
if (-not (Test-Path -LiteralPath $knowledgeSource -PathType Container)) {
    throw "Corporate knowledge payload was not found: $knowledgeSource"
}

$currentPointerPath = Get-CompanyAgentCurrentPointerPath -DataRoot $DataRoot
$previousPointerPath = Get-CompanyAgentPreviousPointerPath -DataRoot $DataRoot
$existingSelection = $null
if (Test-Path -LiteralPath $currentPointerPath -PathType Leaf) {
    $existingSelection = Read-CompanyAgentJson -Path $currentPointerPath
}
$installCommitted = $false
$shortcutExistedBefore = Test-Path -LiteralPath $ShortcutPath -PathType Leaf
$shortcutBackupPath = Join-Path $env:TEMP ('CompanyAgent-Shortcut-' + [guid]::NewGuid().ToString('N') + '.lnk')
$previousPointerExistedBefore = Test-Path -LiteralPath $previousPointerPath -PathType Leaf
$previousSelectionBefore = $null
if ($previousPointerExistedBefore) {
    $previousSelectionBefore = Read-CompanyAgentJson -Path $previousPointerPath
}

$providedModelIdCount = @(@($SmallModelId, $MediumModelId, $LargeModelId) | Where-Object {
    -not [string]::IsNullOrWhiteSpace([string]$_)
}).Count
if ($UseExistingClaudeModels -and $providedModelIdCount -gt 0) {
    throw 'UseExistingClaudeModels cannot be combined with explicit SmallModelId, MediumModelId, or LargeModelId values.'
}
if ($providedModelIdCount -notin @(0, 3)) {
    throw 'Either provide all three model IDs or none of them.'
}

$modelMode = 'claude-config'
if (-not $UseExistingClaudeModels -and $providedModelIdCount -eq 3) {
    $modelMode = 'explicit-map'
}
elseif (-not $UseExistingClaudeModels -and $providedModelIdCount -eq 0 -and $null -ne $existingSelection) {
    if ($null -ne $existingSelection.PSObject.Properties['modelConfiguration'] -and
        $null -ne $existingSelection.modelConfiguration.PSObject.Properties['mode']) {
        $modelMode = [string]$existingSelection.modelConfiguration.mode
    }
    else {
        # Version 0.1 selections always stored explicit internal model IDs.
        $modelMode = 'explicit-map'
    }
}

if ($modelMode -eq 'explicit-map' -and $providedModelIdCount -eq 0) {
    $SmallModelId = [string]$existingSelection.modelMap.SMALL
    $MediumModelId = [string]$existingSelection.modelMap.MEDIUM
    $LargeModelId = [string]$existingSelection.modelMap.LARGE
}
elseif ($modelMode -eq 'claude-config') {
    $SmallModelId = 'haiku'
    $MediumModelId = 'sonnet'
    $LargeModelId = 'opus'
}
if ([string]::IsNullOrWhiteSpace($DefaultTier)) {
    if ($null -ne $existingSelection) {
        $DefaultTier = [string]$existingSelection.routing.defaultTier
    }
    else {
        $DefaultTier = 'AUTO'
    }
}
$DefaultTier = $DefaultTier.ToUpperInvariant()

if (@('AUTO', 'SMALL', 'MEDIUM', 'LARGE') -notcontains $DefaultTier) {
    throw "DefaultTier must be AUTO, SMALL, MEDIUM, or LARGE. Received: $DefaultTier"
}

$InstallRoot = Initialize-CompanyAgentManagedRoot -Root $InstallRoot
$DataRoot = Initialize-CompanyAgentManagedRoot -Root $DataRoot
New-CompanyAgentDirectory -Path (Join-Path $InstallRoot 'versions')
New-CompanyAgentDirectory -Path (Join-Path $DataRoot 'knowledge\versions')
New-CompanyAgentDirectory -Path (Join-Path $DataRoot 'state')
New-CompanyAgentDirectory -Path (Join-Path $DataRoot 'config')

$coreDestination = Join-Path $InstallRoot (Join-Path 'versions' (Join-Path $CoreVersion 'plugin'))
$knowledgeDestination = Join-Path $DataRoot (Join-Path 'knowledge\versions' $KnowledgeVersion)
$installedCore = Install-CompanyAgentImmutableDirectory -Source $coreSource -Destination $coreDestination
$installedKnowledge = Install-CompanyAgentImmutableDirectory -Source $knowledgeSource -Destination $knowledgeDestination

# Management scripts are atomically replaced as one directory. They are not user state.
$managementSource = Join-Path $BundleRoot 'deploy'
if (-not (Test-Path -LiteralPath $managementSource -PathType Container)) {
    throw "Deployment scripts were not found in the bundle: $managementSource"
}
$binPath = Join-Path $InstallRoot 'bin'
$binStagePath = Join-Path $InstallRoot ('.bin-staging-' + [guid]::NewGuid().ToString('N'))
$binBackupPath = Join-Path $InstallRoot ('.bin-backup-' + [guid]::NewGuid().ToString('N'))
try {
    Copy-CompanyAgentDirectoryContents -Source $managementSource -Destination $binStagePath
    if (Test-Path -LiteralPath $binPath -PathType Container) {
        Move-Item -LiteralPath $binPath -Destination $binBackupPath
    }
    Move-Item -LiteralPath $binStagePath -Destination $binPath
}
catch {
    if ((-not (Test-Path -LiteralPath $binPath)) -and (Test-Path -LiteralPath $binBackupPath)) {
        Move-Item -LiteralPath $binBackupPath -Destination $binPath -ErrorAction SilentlyContinue
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $binStagePath) {
        Remove-Item -LiteralPath $binStagePath -Recurse -Force -ErrorAction SilentlyContinue
    }
}

try {
if (-not $SkipShortcut -and $shortcutExistedBefore) {
    Copy-Item -LiteralPath $ShortcutPath -Destination $shortcutBackupPath -Force
}

$managedConfigSource = Join-Path $BundleRoot 'payload\config\managed.json'
$knowledgePacks = @('corporate-base')
$strictMcpConfig = $false
$managedPolicy = [pscustomobject][ordered]@{
    database           = 'select-only'
    outlookSender      = 'initialized-user-only'
    maxFeedbackRetries = 2
    storeRawTranscripts = $false
}
if (Test-Path -LiteralPath $managedConfigSource -PathType Leaf) {
    $managedTemplate = Read-CompanyAgentJson -Path $managedConfigSource
    if ($null -ne $managedTemplate.PSObject.Properties['knowledgePacks']) {
        $knowledgePacks = @($managedTemplate.knowledgePacks)
    }
    if ($null -ne $managedTemplate.PSObject.Properties['policy']) {
        $managedPolicy = $managedTemplate.policy
    }
    if ($null -ne $managedTemplate.PSObject.Properties['strictMcpConfig']) {
        $strictMcpConfig = [bool]$managedTemplate.strictMcpConfig
    }
}

# Session settings and MCP configuration are versioned with the Core. Rollback
# therefore selects the matching configuration instead of mixing old code with
# files overwritten by a newer release.
$configVersion = $CoreVersion
$configDestinationRoot = Join-Path $DataRoot (Join-Path 'config\versions' $configVersion)
$configStageRoot = Join-Path $env:TEMP ('CompanyAgent-Config-' + [guid]::NewGuid().ToString('N'))
$settingsDestination = Join-Path $configDestinationRoot 'session.settings.json'
$managedMcpDestination = Join-Path $configDestinationRoot 'managed-mcp.json'
$managedConfigDestination = Join-Path $configDestinationRoot 'managed.json'
try {
    New-CompanyAgentDirectory -Path $configStageRoot

    $settingsSource = Join-Path $BundleRoot 'payload\config\session.settings.json'
    if (-not (Test-Path -LiteralPath $settingsSource -PathType Leaf)) {
        # Backward compatibility for bundles produced before 0.2.0.
        $settingsSource = Join-Path $BundleRoot 'payload\config\managed.settings.json'
    }
    $settingsStage = Join-Path $configStageRoot 'session.settings.json'
    if (Test-Path -LiteralPath $settingsSource -PathType Leaf) {
        $settingsContent = Get-Content -LiteralPath $settingsSource -Raw -Encoding UTF8
        $null = $settingsContent | ConvertFrom-Json
        Write-CompanyAgentUtf8File -Path $settingsStage -Content $settingsContent
    }
    else {
        Write-CompanyAgentJsonAtomic -Path $settingsStage -Value ([pscustomobject][ordered]@{
            permissions = [pscustomobject][ordered]@{ allow = @() }
        })
    }

    $managedMcpSource = Join-Path $BundleRoot 'payload\config\managed-mcp.json'
    $managedMcpStage = Join-Path $configStageRoot 'managed-mcp.json'
    if (Test-Path -LiteralPath $managedMcpSource -PathType Leaf) {
        $managedMcpContent = Get-Content -LiteralPath $managedMcpSource -Raw -Encoding UTF8
        $null = $managedMcpContent | ConvertFrom-Json
        Write-CompanyAgentUtf8File -Path $managedMcpStage -Content $managedMcpContent
    }
    else {
        Write-CompanyAgentJsonAtomic -Path $managedMcpStage -Value ([pscustomobject][ordered]@{
            mcpServers = [pscustomobject]@{}
        })
    }

    $managedConfig = [pscustomobject][ordered]@{
        schemaVersion = 2
        modelMode = $modelMode
        models = [pscustomobject][ordered]@{
            small  = $SmallModelId
            medium = $MediumModelId
            large  = $LargeModelId
        }
        defaultTier = $DefaultTier.ToLowerInvariant()
        managedMcpConfig = $managedMcpDestination
        strictMcpConfig = $strictMcpConfig
        knowledgePacks = $knowledgePacks
        policy = $managedPolicy
    }
    Write-CompanyAgentJsonAtomic -Path (Join-Path $configStageRoot 'managed.json') -Value $managedConfig
    $installedConfig = Install-CompanyAgentImmutableDirectory -Source $configStageRoot -Destination $configDestinationRoot
}
finally {
    if (Test-Path -LiteralPath $configStageRoot) {
        Remove-Item -LiteralPath $configStageRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$newSelection = [pscustomobject][ordered]@{
    schemaVersion    = 2
    coreVersion      = $CoreVersion
    knowledgeVersion = $KnowledgeVersion
    configVersion    = $configVersion
    modelConfiguration = [pscustomobject][ordered]@{
        mode = $modelMode
    }
    modelMap         = [pscustomobject][ordered]@{
        SMALL  = $SmallModelId
        MEDIUM = $MediumModelId
        LARGE  = $LargeModelId
    }
    routing          = [pscustomobject][ordered]@{
        defaultTier = $DefaultTier
    }
    runtime          = [pscustomobject][ordered]@{
        pythonCommand = $PythonCommand
    }
    activatedAtUtc   = [DateTime]::UtcNow.ToString('o')
}

$launcherPath = Join-Path $binPath 'CompanyAgent.cmd'
$launcherContent = "@echo off`r`nsetlocal`r`npowershell.exe -NoLogo -NoProfile -File `"%~dp0Start-CompanyAgent.ps1`" %*`r`nexit /b %ERRORLEVEL%`r`n"
Write-CompanyAgentUtf8File -Path $launcherPath -Content $launcherContent

if (-not $SkipShortcut) {
    if ([System.IO.Path]::GetExtension($ShortcutPath) -ine '.lnk') {
        throw "ShortcutPath must end in .lnk: $ShortcutPath"
    }
    New-CompanyAgentDirectory -Path (Split-Path -Parent $ShortcutPath)
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $launcherPath
    $shortcut.WorkingDirectory = '%USERPROFILE%'
    $shortcut.Description = 'Start the personalized corporate Claude Code agent'
    $shortcut.Save()
    if (-not (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) {
        throw "Start menu shortcut was not created: $ShortcutPath"
    }
}

Set-CompanyAgentCorporateAcl -Path $InstallRoot -SkipAcl:$SkipAcl
Set-CompanyAgentCorporateAcl -Path $DataRoot -SkipAcl:$SkipAcl

# Activate only after the versioned Core, Knowledge, configuration, launcher,
# shortcut, and ACL work has completed successfully.
if (-not (Test-CompanyAgentSelectionEqual -Left $existingSelection -Right $newSelection)) {
    if ($null -ne $existingSelection) {
        Write-CompanyAgentJsonAtomic -Path $previousPointerPath -Value $existingSelection
    }
    Write-CompanyAgentJsonAtomic -Path $currentPointerPath -Value $newSelection
}
$installCommitted = $true
}
catch {
    $installError = $_
    $rollbackErrors = @()
    $failedBinPath = $null
    try {
        if (Test-Path -LiteralPath $binPath -PathType Container) {
            $failedBinPath = Join-Path $InstallRoot ('.bin-failed-' + [guid]::NewGuid().ToString('N'))
            Move-Item -LiteralPath $binPath -Destination $failedBinPath
        }
        if (Test-Path -LiteralPath $binBackupPath -PathType Container) {
            Move-Item -LiteralPath $binBackupPath -Destination $binPath
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$failedBinPath) -and (Test-Path -LiteralPath $failedBinPath)) {
            Remove-Item -LiteralPath $failedBinPath -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    catch {
        $rollbackErrors += "launcher rollback failed: $($_.Exception.Message)"
    }
    try {
        if ($null -ne $existingSelection) {
            Write-CompanyAgentJsonAtomic -Path $currentPointerPath -Value $existingSelection
        }
        elseif (Test-Path -LiteralPath $currentPointerPath -PathType Leaf) {
            Remove-Item -LiteralPath $currentPointerPath -Force
        }
        if ($previousPointerExistedBefore) {
            Write-CompanyAgentJsonAtomic -Path $previousPointerPath -Value $previousSelectionBefore
        }
        elseif (Test-Path -LiteralPath $previousPointerPath -PathType Leaf) {
            Remove-Item -LiteralPath $previousPointerPath -Force
        }
    }
    catch {
        $rollbackErrors += "selection rollback failed: $($_.Exception.Message)"
    }
    try {
        if (-not $SkipShortcut) {
            if (Test-Path -LiteralPath $shortcutBackupPath -PathType Leaf) {
                Copy-Item -LiteralPath $shortcutBackupPath -Destination $ShortcutPath -Force
            }
            elseif (-not $shortcutExistedBefore -and (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) {
                $rollbackShell = New-Object -ComObject WScript.Shell
                $rollbackShortcut = $rollbackShell.CreateShortcut($ShortcutPath)
                if ([string]$rollbackShortcut.TargetPath -ieq $launcherPath) {
                    Remove-Item -LiteralPath $ShortcutPath -Force
                }
            }
        }
    }
    catch {
        $rollbackErrors += "shortcut rollback failed: $($_.Exception.Message)"
    }
    if ($rollbackErrors.Count -gt 0) {
        throw ("Installation failed and automatic recovery was incomplete. Original error: {0}. Recovery errors: {1}" -f $installError.Exception.Message, ($rollbackErrors -join '; '))
    }
    throw $installError
}
finally {
    if ($installCommitted -and (Test-Path -LiteralPath $binBackupPath)) {
        Remove-Item -LiteralPath $binBackupPath -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $shortcutBackupPath -PathType Leaf) {
        Remove-Item -LiteralPath $shortcutBackupPath -Force -ErrorAction SilentlyContinue
    }
}

[pscustomobject][ordered]@{
    status               = 'installed'
    coreVersion          = $CoreVersion
    knowledgeVersion     = $KnowledgeVersion
    configVersion        = $configVersion
    modelMode            = $modelMode
    installRoot          = $InstallRoot
    dataRoot             = $DataRoot
    userStateRoot        = $UserStateRoot
    launcher             = $launcherPath
    shortcut             = $(if ($SkipShortcut) { $null } else { $ShortcutPath })
    userInitialization   = (Join-Path $binPath 'Initialize-CompanyAgentUser.ps1')
    currentPointer       = $currentPointerPath
    aclApplied           = (-not $SkipAcl.IsPresent)
}
