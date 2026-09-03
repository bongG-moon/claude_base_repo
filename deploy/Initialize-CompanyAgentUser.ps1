[CmdletBinding()]
param(
    [string] $InstallRoot,
    [string] $DataRoot,
    [string] $UserStateRoot,
    [string] $UserEmail,
    [string] $DisplayName,
    [string] $ClaudeCommand = 'claude',
    [string] $PythonCommand = 'python',
    [switch] $NonInteractive,
    [switch] $SkipAcl,
    [switch] $SkipAdminCheck,
    [switch] $SkipDeploymentCheck,
    [switch] $SkipPrerequisiteCheck,
    [switch] $SkipKnowledgeBuild
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Get-CompanyAgentDefaultInstallRoot
}
if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $DataRoot = Get-CompanyAgentDefaultDataRoot
}
if ([string]::IsNullOrWhiteSpace($UserStateRoot)) {
    $UserStateRoot = Get-CompanyAgentDefaultUserStateRoot
}

$InstallRoot = ConvertTo-CompanyAgentFullPath -Path $InstallRoot
$DataRoot = ConvertTo-CompanyAgentFullPath -Path $DataRoot
$UserStateRoot = ConvertTo-CompanyAgentFullPath -Path $UserStateRoot

$deployment = $null
if (-not $SkipDeploymentCheck) {
    $currentPointerPath = Get-CompanyAgentCurrentPointerPath -DataRoot $DataRoot
    $deployment = Read-CompanyAgentJson -Path $currentPointerPath
}
Assert-CompanyAgentPrerequisites -ClaudeCommand $ClaudeCommand -PythonCommand $PythonCommand -SkipPrerequisiteCheck:$SkipPrerequisiteCheck

$UserStateRoot = Initialize-CompanyAgentManagedRoot -Root $UserStateRoot
$directories = @(
    'config',
    'knowledge',
    'knowledge\entries',
    'knowledge\overlays',
    'knowledge\versions',
    'knowledge\conflicts',
    'knowledge\generated-index',
    'knowledge\exports',
    'knowledge\suggestions',
    'personal-root',
    'personal-root\.claude\skills',
    'skills\candidates',
    'skills\active',
    'skills\archive',
    'tools\definitions',
    'tools\generated',
    'mcp',
    'sessions',
    'tmp',
    'memory',
    'evals',
    'ledger',
    'runtime\logs',
    'runtime\sessions',
    'runtime\temp'
)
foreach ($relativePath in $directories) {
    New-CompanyAgentDirectory -Path (Join-Path $UserStateRoot $relativePath)
}

$userConfigPath = Join-Path $UserStateRoot 'config\user.json'
$userConfigChanged = $false
if (Test-Path -LiteralPath $userConfigPath -PathType Leaf) {
    $userConfig = Read-CompanyAgentJson -Path $userConfigPath
}
else {
    $userConfig = [pscustomobject][ordered]@{
        schemaVersion = 1
        user_email    = $null
        display_name  = $null
        createdAtUtc  = [DateTime]::UtcNow.ToString('o')
        personalization = [pscustomobject][ordered]@{
            autoActivatePersonalSkills = $true
            storeFullSessionTranscript = $false
        }
        knowledge = [pscustomobject][ordered]@{
            defaultOverlayMode = 'extend'
        }
    }
    $userConfigChanged = $true
}

$configuredEmail = ''
$emailProperties = @($userConfig.PSObject.Properties | Where-Object { $_.Name -eq 'user_email' })
if ($emailProperties.Count -gt 0) {
    $configuredEmail = [string]$emailProperties[0].Value
}
Write-Verbose ("Existing Outlook identity present: {0}; supplied identity present: {1}" -f (-not [string]::IsNullOrWhiteSpace($configuredEmail)), (-not [string]::IsNullOrWhiteSpace($UserEmail)))
$needsEmail = [string]::IsNullOrWhiteSpace($configuredEmail)
if ($needsEmail -and [string]::IsNullOrWhiteSpace($UserEmail) -and $NonInteractive) {
    throw 'UserEmail is required for non-interactive initialization. It must be the signed-in user''s own Outlook address.'
}
if ($needsEmail -and [string]::IsNullOrWhiteSpace($UserEmail)) {
    $UserEmail = Read-Host 'Enter your own corporate Outlook email address'
}
if ($needsEmail) {
    $UserEmail = ([string]$UserEmail).Trim()
    if ($UserEmail -notmatch '^[^@\s]+@[^@\s]+$') {
        throw "UserEmail is not a valid email address: $UserEmail"
    }
    $userConfig | Add-Member -MemberType NoteProperty -Name 'user_email' -Value $UserEmail -Force
    $userConfigChanged = $true
}

$configuredDisplayName = ''
$displayNameProperties = @($userConfig.PSObject.Properties | Where-Object { $_.Name -eq 'display_name' })
if ($displayNameProperties.Count -gt 0) {
    $configuredDisplayName = [string]$displayNameProperties[0].Value
}
$needsDisplayName = [string]::IsNullOrWhiteSpace($configuredDisplayName)
if ($needsDisplayName -and [string]::IsNullOrWhiteSpace($DisplayName) -and $NonInteractive) {
    throw 'DisplayName is required for non-interactive initialization.'
}
if ($needsDisplayName -and [string]::IsNullOrWhiteSpace($DisplayName)) {
    $DisplayName = Read-Host 'Enter the display name Company Agent should use'
}
if ($needsDisplayName) {
    $DisplayName = ([string]$DisplayName).Trim()
    if ([string]::IsNullOrWhiteSpace($DisplayName)) {
        throw 'DisplayName cannot be empty.'
    }
    $userConfig | Add-Member -MemberType NoteProperty -Name 'display_name' -Value $DisplayName -Force
    $userConfigChanged = $true
}

if ($userConfigChanged) {
    Write-CompanyAgentJsonAtomic -Path $userConfigPath -Value $userConfig
}

$personalMcpRegistryPath = Join-Path $UserStateRoot 'mcp\registry.json'
if (-not (Test-Path -LiteralPath $personalMcpRegistryPath -PathType Leaf)) {
    Write-CompanyAgentJsonAtomic -Path $personalMcpRegistryPath -Value ([pscustomobject][ordered]@{
        mcpServers = [pscustomobject]@{}
    })
}
else {
    $null = Read-CompanyAgentJson -Path $personalMcpRegistryPath
}

$knowledgeCatalogPath = Join-Path $UserStateRoot 'knowledge\generated-index\catalog.json'
if (-not $SkipKnowledgeBuild) {
    if ($null -eq $deployment) {
        throw 'Knowledge build requires an installed deployment. Remove -SkipDeploymentCheck or use -SkipKnowledgeBuild for isolated tests.'
    }
    $corePluginPath = Join-Path $InstallRoot (Join-Path 'versions' (Join-Path ([string]$deployment.coreVersion) 'plugin'))
    $corporateKnowledgePath = Join-Path $DataRoot (Join-Path 'knowledge\versions' ([string]$deployment.knowledgeVersion))
    $harnessCliPath = Join-Path $corePluginPath 'scripts\harness_cli.py'
    if (-not (Test-Path -LiteralPath $harnessCliPath -PathType Leaf)) {
        throw "Active core does not contain harness_cli.py: $harnessCliPath"
    }

    $pythonInfo = Get-Command $PythonCommand | Select-Object -First 1
    $pythonExecutable = $pythonInfo.Source
    if ([string]::IsNullOrWhiteSpace($pythonExecutable)) {
        $pythonExecutable = $pythonInfo.Definition
    }
    $previousDontWriteBytecode = [Environment]::GetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', 'Process')
    try {
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', '1', 'Process')
        $buildOutput = & $pythonExecutable $harnessCliPath knowledge build `
            --state-root $UserStateRoot `
            --base $corporateKnowledgePath `
            --personal (Join-Path $UserStateRoot 'knowledge') `
            --output (Join-Path $UserStateRoot 'knowledge\generated-index') 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Personal knowledge index build failed:`r`n$($buildOutput -join [Environment]::NewLine)"
        }
    }
    finally {
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', $previousDontWriteBytecode, 'Process')
    }
    if (-not (Test-Path -LiteralPath $knowledgeCatalogPath -PathType Leaf)) {
        throw "Knowledge build completed without catalog.json: $knowledgeCatalogPath"
    }
}

$knowledgeIndexPath = Join-Path $UserStateRoot 'knowledge\INDEX.md'
if (-not (Test-Path -LiteralPath $knowledgeIndexPath -PathType Leaf)) {
    $knowledgeIndex = @'
# Personal Knowledge Overlay

This directory is maintained by Company Agent. Corporate knowledge remains in the managed, read-only pack; personal additions and extensions are stored here.

Do not place credentials, connection strings, access tokens, or unmasked business records in this directory.
'@
    Write-CompanyAgentUtf8File -Path $knowledgeIndexPath -Content ($knowledgeIndex.Trim() + "`r`n")
}

$initializedPath = Join-Path $UserStateRoot 'runtime\initialized.json'
$initialized = [pscustomobject][ordered]@{
    schemaVersion = 1
    initializedAtUtc = [DateTime]::UtcNow.ToString('o')
    user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    userStateRoot = $UserStateRoot
}
Write-CompanyAgentJsonAtomic -Path $initializedPath -Value $initialized

Set-CompanyAgentPersonalAcl -Path $UserStateRoot -SkipAcl:$SkipAcl

[pscustomobject][ordered]@{
    status          = 'initialized'
    userStateRoot   = $UserStateRoot
    personalKnowledge = (Join-Path $UserStateRoot 'knowledge')
    personalRoot    = (Join-Path $UserStateRoot 'personal-root')
    personalSkills  = (Join-Path $UserStateRoot 'personal-root\.claude\skills')
    personalMcpRegistry = $personalMcpRegistryPath
    knowledgeCatalog = $(if (Test-Path -LiteralPath $knowledgeCatalogPath -PathType Leaf) { $knowledgeCatalogPath } else { $null })
    userEmail       = [string]$userConfig.user_email
    displayName     = [string]$userConfig.display_name
    userConfig      = $userConfigPath
    aclApplied      = (-not $SkipAcl.IsPresent)
}
