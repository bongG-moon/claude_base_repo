# Skill-local entrypoint: keep the model from reconstructing the plugin root.
# Delegate in this PowerShell process; no extra Python probe, install or consent.
[CmdletBinding(PositionalBinding = $false)]
param(
    [ValidateSet('Cli')]
    [string] $Mode = 'Cli',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $CliArguments
)

$ErrorActionPreference = 'Stop'
if ($CliArguments.Count -lt 2 -or $CliArguments[0] -cne 'business' -or $CliArguments[1] -cne 'office-read') {
    [Console]::Error.WriteLine('office-reader entrypoint: use -Mode Cli business office-read --file "filename.xlsx"')
    exit 2
}
$entry = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..\scripts\Invoke-CompanyAgent.ps1'))
& $entry -Mode Cli @CliArguments
exit $LASTEXITCODE
