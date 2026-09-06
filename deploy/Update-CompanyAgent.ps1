[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $BundleRoot,
    [string] $CoreVersion,
    [string] $KnowledgeVersion,
    [string] $SmallModelId,
    [string] $MediumModelId,
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
$BundleRoot = ConvertTo-CompanyAgentFullPath -Path $BundleRoot

$null = Read-CompanyAgentJson -Path (Get-CompanyAgentCurrentPointerPath -DataRoot $DataRoot)
$installerPath = Join-Path $BundleRoot 'deploy\Install-CompanyAgent.ps1'
if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "The new bundle does not contain its installer: $installerPath"
}

$installParameters = @{
    BundleRoot              = $BundleRoot
    CoreVersion             = $CoreVersion
    KnowledgeVersion        = $KnowledgeVersion
    SmallModelId            = $SmallModelId
    MediumModelId           = $MediumModelId
    LargeModelId            = $LargeModelId
    DefaultTier             = $DefaultTier
    UseExistingClaudeModels = $UseExistingClaudeModels
    InstallRoot             = $InstallRoot
    DataRoot                = $DataRoot
    UserStateRoot           = $UserStateRoot
    ClaudeCommand           = $ClaudeCommand
    PythonCommand           = $PythonCommand
    ShortcutPath            = $ShortcutPath
    SkipAcl                 = $SkipAcl
    SkipAdminCheck          = $SkipAdminCheck
    SkipPrerequisiteCheck   = $SkipPrerequisiteCheck
    SkipShortcut            = $SkipShortcut
    SkipBundleVerification  = $SkipBundleVerification
}

& $installerPath @installParameters
