[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1') -FunctionsOnly
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('CA-ClaudeDiscovery-' + [guid]::NewGuid().ToString('N'))
$assertions = 0
function Assert-ClaudeDiscovery {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "Claude discovery regression failed: $Message" }
    $script:assertions++
}
$provider = (Get-Item Function:\Get-SetupClaudeCandidates).ScriptBlock
try {
    $profile = Join-Path $testRoot 'Profile with spaces'
    $roaming = Join-Path $profile 'AppData\Roaming'
    $native = Join-Path $profile '.local\bin\claude.exe'
    $npm = Join-Path $roaming 'npm\claude.cmd'
    $other = Join-Path $testRoot 'Other user\.local\bin\claude.exe'
    $scriptFile = Join-Path $testRoot 'not-a-cli.txt'
    foreach ($path in @($native, $npm, $other, $scriptFile)) {
        Write-CompanyAgentUtf8File -Path $path -Content 'Discovery must not execute this file.'
    }
    $script:fakePathCommands = @()
    function Get-Command {
        param([string] $Name, [object] $CommandType, [switch] $All, [string] $ErrorAction)
        if ($Name -eq 'claude') { return $script:fakePathCommands }
    }
    $candidates = @(Get-SetupClaudeCandidates -UserProfile $profile -RoamingAppData $roaming)
    Assert-ClaudeDiscovery ($candidates.Count -eq 2) 'Known native/npm locations were not discovered'
    Assert-ClaudeDiscovery ($other -notin @($candidates.path)) 'Another user profile was scanned'
    $script:fakePathCommands = @([pscustomobject]@{ Source = $native }, [pscustomobject]@{ Source = $native.ToUpperInvariant() })
    $candidates = @(Get-SetupClaudeCandidates -UserProfile $profile -RoamingAppData $roaming)
    Assert-ClaudeDiscovery ($candidates.Count -eq 2) 'PATH and known-location duplicates were not deduplicated'
    Assert-ClaudeDiscovery ($candidates[0].source -eq 'PATH') 'PATH candidate order changed'
    Assert-ClaudeDiscovery (@(Get-SetupClaudeCandidates -PreferredCommand $npm -UserProfile $profile).Count -eq 1) 'Explicit selection was mixed with fallback locations'
    Assert-ClaudeDiscovery (@(Get-SetupClaudeCandidates -PreferredCommand (Join-Path $testRoot 'missing.exe') -UserProfile $profile).Count -eq 0) 'Invalid explicit input silently chose another installation'
    Assert-ClaudeDiscovery (@(Get-SetupClaudeCandidates -PreferredCommand $scriptFile -UserProfile $profile).Count -eq 0) 'Unsupported file was accepted'
    $alias = Join-Path $testRoot 'Microsoft\WindowsApps\claude.exe'
    Write-CompanyAgentUtf8File -Path $alias -Content 'Do not execute a Desktop alias.'
    $script:fakePathCommands = @([pscustomobject]@{ Source = $alias })
    $candidates = @(Get-SetupClaudeCandidates -UserProfile (Join-Path $testRoot 'missing-profile') -RoamingAppData (Join-Path $testRoot 'missing-roaming'))
    Assert-ClaudeDiscovery ($candidates.Count -eq 0) 'Desktop execution alias was selected automatically'
    Remove-Item Function:\Get-Command

    $script:promptCount = 0
    $script:answers = New-Object 'Collections.Generic.Queue[string]'
    $script:found = @()
    $script:manualPath = $npm
    function Get-SetupClaudeCandidates {
        param([string] $PreferredCommand = 'claude', [string] $UserProfile)
        if ($PreferredCommand -eq $script:manualPath) { return [pscustomobject]@{ path = $script:manualPath; source = 'specified' } }
        return $script:found
    }
    function Read-Host {
        param([string] $Prompt)
        $script:promptCount++
        if (-not $script:answers.Count) { throw 'Unexpected prompt' }
        return $script:answers.Dequeue()
    }
    foreach ($mode in @('DryRun', 'NonInteractive')) {
        $modeArguments = @{ UserProfile = $profile }; $modeArguments[$mode] = $true
        $selection = Get-SetupClaudeForInstall @modeArguments
        Assert-ClaudeDiscovery ($selection.status -eq 'input-required' -and $selection.input -eq 'ClaudeCommand') 'Missing CLI did not return machine-readable input-required'
    }
    $script:found = @([pscustomobject]@{ path = $native; source = 'PATH' })
    Assert-ClaudeDiscovery ((Get-SetupClaudeForInstall -UserProfile $profile).path -eq $native) 'Single candidate did not resolve automatically'
    Assert-ClaudeDiscovery ($script:promptCount -eq 0) 'Automatic or noninteractive discovery prompted'
    $script:found += [pscustomobject]@{ path = $npm; source = 'user npm install' }
    $selection = Get-SetupClaudeForInstall -UserProfile $profile -NonInteractive
    Assert-ClaudeDiscovery ($selection.status -eq 'input-required' -and @($selection.candidates).Count -eq 2) 'Ambiguous candidates were silently selected'
    $script:answers.Enqueue('9'); $script:answers.Enqueue('2')
    Assert-ClaudeDiscovery ((Get-SetupClaudeForInstall -UserProfile $profile).path -eq $npm) 'Number selection or invalid retry failed'
    $script:found = @()
    $script:answers.Enqueue('relative.exe'); $script:answers.Enqueue('"' + $npm + '"')
    Assert-ClaudeDiscovery ((Get-SetupClaudeForInstall -UserProfile $profile).path -eq $npm) 'Quoted manual path or retry failed'
    $script:answers.Enqueue('')
    $cancelled = $false
    try { $null = Get-SetupClaudeForInstall -UserProfile $profile }
    catch { if ($_.Exception.Message -notmatch 'selection cancelled') { throw }; $cancelled = $true }
    Assert-ClaudeDiscovery $cancelled 'Blank selection did not cancel safely'
    Assert-ClaudeDiscovery ($script:promptCount -eq 5) 'Unexpected number of interactive prompts'
}
finally {
    Set-Item Function:\Get-SetupClaudeCandidates -Value $provider
    foreach ($name in @('Get-Command', 'Read-Host')) { if (Test-Path "Function:\$name") { Remove-Item "Function:\$name" } }
    $full = [IO.Path]::GetFullPath($testRoot)
    $base = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $full.StartsWith($base, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($full) -notlike 'CA-ClaudeDiscovery-*') { throw 'Unsafe fixture cleanup path.' }
    if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
}
[pscustomobject]@{ status = 'pass'; assertions = $assertions; candidateExecution = $false; profileWrites = $false }
