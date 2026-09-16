[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'Diagnose-CompanyAgent.ps1') -FunctionsOnly
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('CA-Diagnostic-' + [guid]::NewGuid().ToString('N'))
$assertions = 0
function Assert-Diagnostic($condition, [string] $message) {
    if (-not $condition) { throw $message }
    $script:assertions++
}
function Write-DiagnosticFixture([string] $path, $value) {
    $null = New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force
    [IO.File]::WriteAllText($path, ($value | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding($false)))
}
try {
    $project = Join-Path $fixture 'project with spaces'
    $config = Join-Path $fixture '.claude'
    $local = Join-Path $fixture 'local'
    $registry = Join-Path $local 'CompanyAgent\installations'
    $projectFile = Join-Path $registry 'projects\one\company-agent-install.json'
    $projectPython = Join-Path $fixture 'python outside PATH\python.exe'
    $userPython = Join-Path $fixture 'user python\python.exe'
    $record = @{ schemaVersion = 1; scope = 'Project'; projectRoot = $project; claudeConfigRoot = $config; pythonCommand = $projectPython; coreVersion = '1.4.11' }
    Write-DiagnosticFixture $projectFile $record
    $candidates = @(Get-DiagnosticPythonCandidates $project $local $config)
    Assert-Diagnostic ($candidates[0] -ceq $projectPython) 'Project-only recorded interpreter was not first.'
    Assert-Diagnostic ($candidates.Count -eq 3) 'Unexpected fallback interpreter.'
    Assert-Diagnostic (-not (Test-Path -LiteralPath $projectPython)) 'Discovery executed or created a fake interpreter.'
    Write-DiagnosticFixture (Join-Path $registry 'user\company-agent-install.json') @{schemaVersion=1; scope='User'; claudeConfigRoot=$config; pythonCommand=$userPython}
    $candidates = @(Get-DiagnosticPythonCandidates (Join-Path $project 'child') $local $config)
    Assert-Diagnostic ($candidates[0] -ceq $projectPython -and $candidates[1] -ceq $userPython) 'Project precedence was not retained.'
    $candidates = @(Get-DiagnosticPythonCandidates ($project + '-other') $local $config)
    Assert-Diagnostic ($candidates[0] -ceq $userPython) 'Sibling project incorrectly matched.'
    $record.enabled = $false
    Write-DiagnosticFixture $projectFile $record
    Assert-Diagnostic (@(Get-DiagnosticPythonCandidates $project $local $config)[0] -ceq $userPython) 'Disabled record used.'
    $record.enabled = $true
    $record.claudeConfigRoot = Join-Path $fixture 'different-profile'
    Write-DiagnosticFixture $projectFile $record
    Assert-Diagnostic (@(Get-DiagnosticPythonCandidates $project $local $config)[0] -ceq $userPython) 'Other config profile used.'
    $record.claudeConfigRoot = $config
    Write-DiagnosticFixture $projectFile $record
    $sharedPython = Join-Path $fixture 'repaired python\python.exe'
    Write-DiagnosticFixture (Join-Path $local 'CompanyAgent-Distribution\marketplace\versions\1.4.11\runtime-selection.json') @{coreVersion='1.4.11'; pythonCommand=$sharedPython}
    Assert-Diagnostic (@(Get-DiagnosticPythonCandidates $project $local $config)[0] -ceq $sharedPython) 'Shared repaired runtime not preferred.'
    Assert-Diagnostic (@(Get-DiagnosticPythonCandidates $project $local (Join-Path $fixture 'unregistered'))[0] -ceq 'python') 'Wrong profile record was accepted.'
    $record.nativeClaudeScope = 'local'
    Write-DiagnosticFixture $projectFile $record
    Assert-Diagnostic (@(Get-DiagnosticPythonCandidates $project $local $config)[0] -ceq $userPython) 'Unregistered native Project interpreter was selected.'
    Write-DiagnosticFixture (Join-Path $config 'plugins\installed_plugins.json') @{plugins=@{'company-agent@company-agent-local'=@(@{scope='local'; projectPath=$project})}}
    $projectSettings = Join-Path $project '.claude\settings.local.json'
    Write-DiagnosticFixture $projectSettings @{enabledPlugins=@{'company-agent@company-agent-local'=$false}}
    Assert-Diagnostic (@(Get-DiagnosticPythonCandidates $project $local $config)[0] -ceq $userPython) 'Disabled native Project interpreter was selected.'
    Write-DiagnosticFixture $projectSettings @{enabledPlugins=@{'company-agent@company-agent-local'=$true}}
    Assert-Diagnostic (@(Get-DiagnosticPythonCandidates $project $local $config)[0] -ceq $sharedPython) 'Active native Project interpreter was not selected.'
    [pscustomobject]@{status='pass'; assertions=$assertions; projectOnly=$true; interpreterExecuted=$false; realProfileChanged=$false}
} finally {
    $resolved = [IO.Path]::GetFullPath($fixture)
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $resolved) -notlike 'CA-Diagnostic-*') { throw 'Unsafe fixture cleanup target.' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
