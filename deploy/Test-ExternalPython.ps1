[CmdletBinding()]
param([string] $PythonCommand = 'python')

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$requestedPython = $PythonCommand
. (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1') -FunctionsOnly
$assertions = 0
function Assert-ExternalPython {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "External Python regression failed: $Message" }
    $script:assertions++
}

$actual = Resolve-SetupApprovedPython -PreferredCommand $requestedPython -OnlyPreferred
Assert-ExternalPython (-not [string]::IsNullOrWhiteSpace($actual)) 'Test PC needs a working Python 3.11+ interpreter'
Assert-ExternalPython ([IO.Path]::IsPathRooted($actual)) 'Resolution did not return an absolute path'
Assert-ExternalPython ([IO.Path]::GetFileName($actual) -ine 'py.exe') 'A launcher was recorded instead of sys.executable'
$direct = Invoke-SetupPythonProbe -Executable $actual
Assert-ExternalPython ([string]$direct.executable -ieq $actual) 'Resolved interpreter cannot execute its standard-library probe'
Assert-ExternalPython ($direct.automaticInstallDisabled -eq $true) 'Child process did not disable launcher automatic installation'
$launcherEnvironment = @{}
try {
    foreach ($name in @('PYLAUNCHER_ALLOW_INSTALL', 'PYLAUNCHER_ALWAYS_INSTALL', 'PYTHON_MANAGER_AUTOMATIC_INSTALL')) {
        $launcherEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, 'true', 'Process')
    }
    # Run the known interpreter, not an install-enabled launcher, and observe
    # the child environment that would be used for either executable.
    $guarded = Invoke-SetupPythonProbe -Executable $actual
    Assert-ExternalPython ($guarded.automaticInstallDisabled -eq $true) 'Inherited install-on-demand options leaked into the probe'
    foreach ($name in $launcherEnvironment.Keys) {
        Assert-ExternalPython ([Environment]::GetEnvironmentVariable($name, 'Process') -eq 'true') 'Probe changed the parent environment'
    }
}
finally {
    foreach ($name in $launcherEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $launcherEnvironment[$name], 'Process') }
}
Assert-ExternalPython ($null -eq (Resolve-SetupApprovedPython -PreferredCommand 'Z:\missing-python-for-company-agent\python.exe' -OnlyPreferred)) 'Missing explicit input silently fell back to another runtime'
Assert-ExternalPython ($null -eq (Invoke-SetupPythonProbe -Executable (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1'))) 'A script was accepted as an interpreter'
$launcher = Get-Command 'py.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
$launcherChecked = $false
if ($null -ne $launcher) {
    $viaLauncher = Resolve-SetupApprovedPython -PreferredCommand $launcher.Source -OnlyPreferred
    Assert-ExternalPython (-not [string]::IsNullOrWhiteSpace($viaLauncher)) 'Installed py launcher could not resolve Python 3.11+'
    Assert-ExternalPython ([IO.Path]::GetFileName($viaLauncher) -ine 'py.exe') 'py fallback remained mutable in installation metadata'
    $launcherChecked = $true
}

$probeFunction = (Get-Item Function:\Invoke-SetupPythonProbe).ScriptBlock
$resolverFunction = (Get-Item Function:\Resolve-SetupApprovedPython).ScriptBlock
try {
    $script:probeVersion = @(3, 10, 12)
    $script:probeExecutable = $actual
    function Invoke-SetupPythonProbe {
        param([string] $Executable)
        return [pscustomobject]@{ version = $script:probeVersion; executable = $script:probeExecutable }
    }
    Assert-ExternalPython ($null -eq (Resolve-SetupApprovedPython -PreferredCommand $actual -OnlyPreferred)) 'Python below 3.11 was accepted'
    $script:probeVersion = @(4, 0, 0)
    Assert-ExternalPython ($null -eq (Resolve-SetupApprovedPython -PreferredCommand $actual -OnlyPreferred)) 'Unsupported Python major version was accepted'
    $script:probeVersion = @(3, 11, 0)
    $script:probeExecutable = 'relative-python.exe'
    Assert-ExternalPython ($null -eq (Resolve-SetupApprovedPython -PreferredCommand $actual -OnlyPreferred)) 'Relative sys.executable was accepted'
    Set-Item Function:\Invoke-SetupPythonProbe -Value $probeFunction

    $script:promptCount = 0
    $script:selections = New-Object 'Collections.Generic.Queue[string]'
    $script:acceptedPythonInput = $actual
    $script:automaticallyFound = $false
    function Resolve-SetupApprovedPython {
        param([string] $PreferredCommand = 'python', [switch] $OnlyPreferred)
        if ($script:automaticallyFound -or ($OnlyPreferred -and $PreferredCommand -eq $script:acceptedPythonInput)) { return $script:acceptedPythonInput }
        return $null
    }
    function Read-Host {
        param([string] $Prompt)
        $script:promptCount++
        if ($script:selections.Count -eq 0) { throw 'Unexpected interactive prompt' }
        return $script:selections.Dequeue()
    }
    foreach ($mode in @('NonInteractive', 'DryRun')) {
        $arguments = @{}
        $arguments[$mode] = $true
        $rejected = $false
        try { $null = Get-SetupPythonForInstall @arguments }
        catch {
            if ($_.Exception.Message -notmatch 'Python 3.11\+.*-PythonCommand') { throw }
            $rejected = $true
        }
        Assert-ExternalPython $rejected "$mode did not return actionable missing-runtime guidance"
        Assert-ExternalPython ($script:promptCount -eq 0) "$mode attempted to prompt"
    }
    $script:automaticallyFound = $true
    Assert-ExternalPython ((Get-SetupPythonForInstall) -eq $actual) 'Detected runtime prompted unnecessarily'
    Assert-ExternalPython ($script:promptCount -eq 0) 'Automatic success asked for user input'
    $script:automaticallyFound = $false
    $script:selections.Enqueue('not-a-python-path')
    $script:selections.Enqueue('"' + $actual + '"')
    Assert-ExternalPython ((Get-SetupPythonForInstall) -eq $actual) 'Manual path retry/quote handling failed'
    Assert-ExternalPython ($script:promptCount -eq 2) 'Invalid input did not retry before accepting a valid path'
    $script:selections.Enqueue('')
    $cancelled = $false
    try { $null = Get-SetupPythonForInstall }
    catch { $cancelled = $true }
    Assert-ExternalPython $cancelled 'Empty input did not cancel setup'
}
finally {
    Set-Item Function:\Invoke-SetupPythonProbe -Value $probeFunction
    Set-Item Function:\Resolve-SetupApprovedPython -Value $resolverFunction
    if (Test-Path Function:\Read-Host) { Remove-Item Function:\Read-Host }
}

[pscustomobject]@{ status = 'pass'; assertions = $assertions; python = $actual; pyLauncherChecked = $launcherChecked; missingRuntimePrompt = $true; noDownloads = $true }
