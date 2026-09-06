[CmdletBinding()]
param(
    [string] $InstallRoot,
    [string] $DataRoot,
    [string] $UserStateRoot,
    [switch] $SkipAcl,
    [switch] $SkipAdminCheck
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
Assert-CompanyAgentRootsSeparated -InstallRoot $InstallRoot -DataRoot $DataRoot -UserStateRoot $UserStateRoot

Assert-CompanyAgentAdministrator -SkipAdminCheck:$SkipAdminCheck
Assert-CompanyAgentManagedRoot -Root $InstallRoot
Assert-CompanyAgentManagedRoot -Root $DataRoot

$currentPointerPath = Get-CompanyAgentCurrentPointerPath -DataRoot $DataRoot
$previousPointerPath = Get-CompanyAgentPreviousPointerPath -DataRoot $DataRoot
$currentSelection = Read-CompanyAgentJson -Path $currentPointerPath
$previousSelection = Read-CompanyAgentJson -Path $previousPointerPath

Assert-CompanyAgentVersion -Version ([string]$previousSelection.coreVersion) -Name 'previous coreVersion'
Assert-CompanyAgentVersion -Version ([string]$previousSelection.knowledgeVersion) -Name 'previous knowledgeVersion'
$previousCorePath = Join-Path $InstallRoot (Join-Path 'versions' (Join-Path ([string]$previousSelection.coreVersion) 'plugin'))
$previousKnowledgePath = Join-Path $DataRoot (Join-Path 'knowledge\versions' ([string]$previousSelection.knowledgeVersion))
if (-not (Test-Path -LiteralPath $previousCorePath -PathType Container)) {
    throw "Previous core version is no longer installed: $previousCorePath"
}
if (-not (Test-Path -LiteralPath $previousKnowledgePath -PathType Container)) {
    throw "Previous knowledge version is no longer installed: $previousKnowledgePath"
}
if ($null -ne $previousSelection.PSObject.Properties['configVersion'] -and
    -not [string]::IsNullOrWhiteSpace([string]$previousSelection.configVersion)) {
    $previousConfigPath = Join-Path $DataRoot (Join-Path 'config\versions' ([string]$previousSelection.configVersion))
    if (-not (Test-Path -LiteralPath $previousConfigPath -PathType Container)) {
        throw "Previous configuration version is no longer installed: $previousConfigPath"
    }
}

# Write the reverse pointer first. If the second atomic write fails, the active pointer is unchanged.
Write-CompanyAgentJsonAtomic -Path $previousPointerPath -Value $currentSelection
Write-CompanyAgentJsonAtomic -Path $currentPointerPath -Value $previousSelection

Set-CompanyAgentCorporateAcl -Path $InstallRoot -SkipAcl:$SkipAcl
Set-CompanyAgentCorporateAcl -Path $DataRoot -SkipAcl:$SkipAcl

[pscustomobject][ordered]@{
    status           = 'rolled-back'
    coreVersion      = [string]$previousSelection.coreVersion
    knowledgeVersion = [string]$previousSelection.knowledgeVersion
    configVersion    = $(if ($null -ne $previousSelection.PSObject.Properties['configVersion']) { [string]$previousSelection.configVersion } else { $null })
    modelMap         = $previousSelection.modelMap
    reverseRollbackAvailable = $true
    userStateRootPreserved = $UserStateRoot
}
