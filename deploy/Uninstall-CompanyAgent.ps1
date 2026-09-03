[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string] $InstallRoot,
    [string] $DataRoot,
    [string] $UserStateRoot,
    [string] $ShortcutPath,
    [switch] $RemoveUserState,
    [switch] $SkipShortcut,
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
if ([string]::IsNullOrWhiteSpace($ShortcutPath)) {
    $ShortcutPath = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Company Agent.lnk'
}
$ShortcutPath = ConvertTo-CompanyAgentFullPath -Path $ShortcutPath

if ($InstallRoot -ieq $DataRoot -or $InstallRoot -ieq $UserStateRoot -or $DataRoot -ieq $UserStateRoot) {
    throw 'InstallRoot, DataRoot, and UserStateRoot must be distinct directories.'
}

Assert-CompanyAgentAdministrator -SkipAdminCheck:$SkipAdminCheck
$removed = @()

if (-not $SkipShortcut -and (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) {
    $expectedTarget = Join-Path $InstallRoot 'bin\CompanyAgent.cmd'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $actualTarget = [string]$shortcut.TargetPath
    if ($actualTarget -ieq $expectedTarget) {
        if ($PSCmdlet.ShouldProcess($ShortcutPath, 'Remove Company Agent start menu shortcut')) {
            Remove-Item -LiteralPath $ShortcutPath -Force
            $removed += $ShortcutPath
        }
    }
    else {
        Write-Warning "Shortcut was preserved because its target is not managed by this installation: $ShortcutPath"
    }
}

foreach ($managedRoot in @($DataRoot, $InstallRoot)) {
    if (Test-Path -LiteralPath $managedRoot -PathType Container) {
        Assert-CompanyAgentManagedRoot -Root $managedRoot
        if ($PSCmdlet.ShouldProcess($managedRoot, 'Remove Company Agent managed system data')) {
            Remove-Item -LiteralPath $managedRoot -Recurse -Force
            $removed += $managedRoot
        }
    }
}

if ($RemoveUserState -and (Test-Path -LiteralPath $UserStateRoot -PathType Container)) {
    Assert-CompanyAgentManagedRoot -Root $UserStateRoot
    if ($PSCmdlet.ShouldProcess($UserStateRoot, 'Permanently remove personal knowledge, skills, memory, and history')) {
        Remove-Item -LiteralPath $UserStateRoot -Recurse -Force
        $removed += $UserStateRoot
    }
}

[pscustomobject][ordered]@{
    status             = 'uninstalled'
    removed            = $removed
    userStateRemoved   = $RemoveUserState.IsPresent
    userStatePreserved = $(if ($RemoveUserState) { $null } else { $UserStateRoot })
    note               = $(if ($RemoveUserState) { 'Personal state was permanently removed.' } else { 'Personal state was preserved and can be reused after reinstall.' })
}
