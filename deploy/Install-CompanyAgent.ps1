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

if ($InstallRoot -ieq $DataRoot -or $InstallRoot -ieq $UserStateRoot -or $DataRoot -ieq $UserStateRoot) {
    throw 'InstallRoot, DataRoot, and UserStateRoot must be distinct directories.'
}

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

if ([string]::IsNullOrWhiteSpace($SmallModelId) -and $null -ne $existingSelection) {
    $SmallModelId = [string]$existingSelection.modelMap.SMALL
}
if ([string]::IsNullOrWhiteSpace($MediumModelId) -and $null -ne $existingSelection) {
    $MediumModelId = [string]$existingSelection.modelMap.MEDIUM
}
if ([string]::IsNullOrWhiteSpace($LargeModelId) -and $null -ne $existingSelection) {
    $LargeModelId = [string]$existingSelection.modelMap.LARGE
}
if ([string]::IsNullOrWhiteSpace($DefaultTier)) {
    if ($null -ne $existingSelection) {
        $DefaultTier = [string]$existingSelection.routing.defaultTier
    }
    else {
        $DefaultTier = 'MEDIUM'
    }
}
$DefaultTier = $DefaultTier.ToUpperInvariant()

if ([string]::IsNullOrWhiteSpace($SmallModelId) -or
    [string]::IsNullOrWhiteSpace($MediumModelId) -or
    [string]::IsNullOrWhiteSpace($LargeModelId)) {
    throw 'SmallModelId, MediumModelId, and LargeModelId are required for a fresh installation.'
}
if (@('SMALL', 'MEDIUM', 'LARGE') -notcontains $DefaultTier) {
    throw "DefaultTier must be SMALL, MEDIUM, or LARGE. Received: $DefaultTier"
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
    if (Test-Path -LiteralPath $binBackupPath) {
        Remove-Item -LiteralPath $binBackupPath -Recurse -Force
    }
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

$settingsDestination = Join-Path $DataRoot 'config\managed.settings.json'
$settingsSource = Join-Path $BundleRoot 'payload\config\managed.settings.json'
if (Test-Path -LiteralPath $settingsSource -PathType Leaf) {
    $settingsContent = Get-Content -LiteralPath $settingsSource -Raw -Encoding UTF8
    $null = $settingsContent | ConvertFrom-Json
    Write-CompanyAgentUtf8File -Path $settingsDestination -Content $settingsContent
}
else {
    $defaultModelAlias = @{
        SMALL  = 'haiku'
        MEDIUM = 'sonnet'
        LARGE  = 'opus'
    }[$DefaultTier]
    $managedSettings = [pscustomobject][ordered]@{
        model = $defaultModelAlias
        availableModels = @('haiku', 'sonnet', 'opus')
        env = [pscustomobject][ordered]@{
            ANTHROPIC_DEFAULT_HAIKU_MODEL  = $SmallModelId
            ANTHROPIC_DEFAULT_SONNET_MODEL = $MediumModelId
            ANTHROPIC_DEFAULT_OPUS_MODEL   = $LargeModelId
        }
    }
    Write-CompanyAgentJsonAtomic -Path $settingsDestination -Value $managedSettings
}

$managedMcpDestination = Join-Path $DataRoot 'config\managed-mcp.json'
$managedMcpSource = Join-Path $BundleRoot 'payload\config\managed-mcp.json'
if (Test-Path -LiteralPath $managedMcpSource -PathType Leaf) {
    $managedMcpContent = Get-Content -LiteralPath $managedMcpSource -Raw -Encoding UTF8
    $null = $managedMcpContent | ConvertFrom-Json
    Write-CompanyAgentUtf8File -Path $managedMcpDestination -Content $managedMcpContent
}
elseif (-not (Test-Path -LiteralPath $managedMcpDestination -PathType Leaf)) {
    Write-CompanyAgentJsonAtomic -Path $managedMcpDestination -Value ([pscustomobject][ordered]@{
        mcpServers = [pscustomobject]@{}
    })
}

$managedConfigSource = Join-Path $BundleRoot 'payload\config\managed.json'
$knowledgePacks = @('corporate-base')
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
}
$managedConfigDestination = Join-Path $DataRoot 'config\managed.json'
$managedConfig = [pscustomobject][ordered]@{
    schemaVersion = 1
    models = [pscustomobject][ordered]@{
        small  = $SmallModelId
        medium = $MediumModelId
        large  = $LargeModelId
    }
    defaultTier = $DefaultTier.ToLowerInvariant()
    managedMcpConfig = $managedMcpDestination
    knowledgePacks = $knowledgePacks
    policy = $managedPolicy
}
Write-CompanyAgentJsonAtomic -Path $managedConfigDestination -Value $managedConfig

$newSelection = [pscustomobject][ordered]@{
    schemaVersion    = 1
    coreVersion      = $CoreVersion
    knowledgeVersion = $KnowledgeVersion
    modelMap         = [pscustomobject][ordered]@{
        SMALL  = $SmallModelId
        MEDIUM = $MediumModelId
        LARGE  = $LargeModelId
    }
    routing          = [pscustomobject][ordered]@{
        defaultTier = $DefaultTier
    }
    activatedAtUtc   = [DateTime]::UtcNow.ToString('o')
}

if (-not (Test-CompanyAgentSelectionEqual -Left $existingSelection -Right $newSelection)) {
    if ($null -ne $existingSelection) {
        Write-CompanyAgentJsonAtomic -Path $previousPointerPath -Value $existingSelection
    }
    Write-CompanyAgentJsonAtomic -Path $currentPointerPath -Value $newSelection
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
    $shortcut.WorkingDirectory = '%USERPROFILE%\Documents'
    $shortcut.Description = 'Start the personalized corporate Claude Code agent'
    $shortcut.Save()
    if (-not (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) {
        throw "Start menu shortcut was not created: $ShortcutPath"
    }
}

Set-CompanyAgentCorporateAcl -Path $InstallRoot -SkipAcl:$SkipAcl
Set-CompanyAgentCorporateAcl -Path $DataRoot -SkipAcl:$SkipAcl

[pscustomobject][ordered]@{
    status               = 'installed'
    coreVersion          = $CoreVersion
    knowledgeVersion     = $KnowledgeVersion
    installRoot          = $InstallRoot
    dataRoot             = $DataRoot
    userStateRoot        = $UserStateRoot
    launcher             = $launcherPath
    shortcut             = $(if ($SkipShortcut) { $null } else { $ShortcutPath })
    userInitialization   = (Join-Path $binPath 'Initialize-CompanyAgentUser.ps1')
    currentPointer       = $currentPointerPath
    aclApplied           = (-not $SkipAcl.IsPresent)
}
