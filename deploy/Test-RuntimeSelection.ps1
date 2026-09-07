[CmdletBinding()]
param(
    [string] $BundleRoot,
    [string] $PythonCommand = 'python',
    [string] $ClaudeCommand = 'claude',
    [switch] $KeepTestDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('CompanyAgent-RuntimeSelection-' + [guid]::NewGuid().ToString('N'))
$savedConfig = $env:CLAUDE_CONFIG_DIR
$savedForce = $env:CLAUDE_CODE_SUBAGENT_MODEL
$savedForce2 = $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE
$assertions = 0
function Assert-RuntimeSelection {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "Runtime selection regression failed: $Message" }
    $script:assertions++
}

try {
    New-CompanyAgentDirectory -Path $testRoot
    if ([string]::IsNullOrWhiteSpace($BundleRoot)) {
        $sourceRoot = Split-Path -Parent $PSScriptRoot
        $plugin = Read-CompanyAgentJson -Path (Join-Path $sourceRoot 'company-agent-plugin\.claude-plugin\plugin.json')
        $knowledge = Read-CompanyAgentJson -Path (Join-Path $sourceRoot 'corporate-knowledge\pack.json')
        $zip = Join-Path $testRoot 'bundle.zip'
        $null = & (Join-Path $PSScriptRoot 'New-OfflineBundle.ps1') -SourceRoot $sourceRoot -CoreVersion $plugin.version -KnowledgeVersion $knowledge.version -OutputPath $zip -SkipSourceValidation
        $BundleRoot = Join-Path $testRoot 'bundle'
        Expand-Archive -LiteralPath $zip -DestinationPath $BundleRoot
    }
    $basePython = [string](& $PythonCommand -I -X utf8 -B -c 'import sys; print(sys.executable)')
    if ($LASTEXITCODE -ne 0) { throw 'A working Python 3.11+ is required for this regression.' }
    # Codepoints keep the regression source ASCII-safe under PowerShell 5.1
    # while exercising real Korean, em-dash, and emoji interpreter paths.
    $unicodeSuffix = [string][char]0xD55C + [char]0xAE00 + [char]0x2014 + [char]::ConvertFromUtf32(0x1F680)
    $oldVenv = Join-Path $testRoot ('Previous Python ' + $unicodeSuffix)
    $newVenv = Join-Path $testRoot ('Replacement Python ' + $unicodeSuffix)
    foreach ($venv in @($oldVenv, $newVenv)) {
        & $basePython -I -B -m venv --without-pip $venv
        if ($LASTEXITCODE -ne 0) { throw "Could not create temporary Python fixture: $venv" }
    }
    $oldPython = Join-Path $oldVenv 'Scripts\python.exe'
    $newPython = Join-Path $newVenv 'Scripts\python.exe'
    $profile = Join-Path $testRoot 'profile'
    $localData = Join-Path $profile 'AppData\Local'
    $config = Join-Path $profile '.claude'
    foreach ($directory in @($profile, $localData, $config)) { New-CompanyAgentDirectory -Path $directory }
    $env:CLAUDE_CONFIG_DIR = $config
    $env:CLAUDE_CODE_SUBAGENT_MODEL = $null
    $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE = $null
    $setup = Join-Path $BundleRoot 'deploy\Setup-CompanyAgent.ps1'
    $common = @{
        BundleRoot = $BundleRoot; Scope = 'User'; ClaudeConfigRoot = $config
        InvokingUserProfile = $profile; InvokingLocalAppData = $localData
        PythonCommand = $oldPython; ClaudeCommand = $ClaudeCommand
        NonInteractive = $true; SkipAdminCheck = $true; ExistingHarnessAction = 'Replace'
    }
    $first = & $setup @common
    Assert-RuntimeSelection ($first.status -eq 'installed') 'Initial isolated installation failed'
    $record = Read-CompanyAgentJson -Path $first.registrationPath
    $releaseRoot = Split-Path -Parent $record.knowledgeBaseRoot
    $metadataPath = Join-Path $releaseRoot 'plugin\company-agent-install.json'
    $metadata = Read-CompanyAgentJson -Path $metadataPath
    $selectionPath = Join-Path $releaseRoot 'runtime-selection.json'
    Assert-RuntimeSelection ($metadata.runtimeSelectionPath -eq $selectionPath) 'Plugin metadata has no durable selection pointer'
    Assert-RuntimeSelection ((Read-CompanyAgentJson -Path $selectionPath).pythonCommand -ieq $oldPython) 'Initial interpreter was not selected'

    # Preserve a cache copy from before the reinstall, including stale metadata.
    $cache = Join-Path $testRoot 'Unchanged cache fixture'
    New-CompanyAgentDirectory -Path (Join-Path $cache 'scripts')
    Copy-Item -LiteralPath $metadataPath -Destination (Join-Path $cache 'company-agent-install.json')
    Copy-Item -LiteralPath (Join-Path $releaseRoot 'plugin\scripts\Invoke-CompanyAgent.ps1') -Destination (Join-Path $cache 'scripts\Invoke-CompanyAgent.ps1')
    Write-CompanyAgentUtf8File -Path (Join-Path $cache 'scripts\native_entry.py') -Content 'import json,sys; print(json.dumps({"python":sys.executable}))'
    $oldMetadataHash = (Get-FileHash -LiteralPath $metadataPath -Algorithm SHA256).Hash
    Assert-RuntimeSelection ($oldPython.StartsWith($testRoot + '\', [StringComparison]::OrdinalIgnoreCase)) 'Old interpreter fixture escaped test root'
    Remove-Item -LiteralPath $oldPython -Force
    $common.PythonCommand = $newPython
    $second = & $setup @common
    Assert-RuntimeSelection ($second.status -eq 'reapplied' -and $second.operation -eq 'reapply') 'Same-version reinstall failed'
    Assert-RuntimeSelection ((Read-CompanyAgentJson -Path $selectionPath).pythonCommand -ieq $newPython) 'Same-version reinstall retained the removed interpreter'
    Assert-RuntimeSelection ((Get-FileHash -LiteralPath $metadataPath -Algorithm SHA256).Hash -ceq $oldMetadataHash) 'Reinstall mutated immutable plugin metadata'
    $backupSelection = Join-Path $second.safetyBackup 'company-agent\runtime-selection.json'
    Assert-RuntimeSelection ((Read-CompanyAgentJson -Path $backupSelection).pythonCommand -ieq $oldPython) 'Prior runtime selection was not backed up'
    $powerShell = (Get-Command powershell.exe | Select-Object -First 1).Source
    $savedPath = $env:PATH
    $savedPython = $env:COMPANY_AGENT_PYTHON
    try {
        $env:PATH = ''
        $env:COMPANY_AGENT_PYTHON = $null
        $output = & $powerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $cache 'scripts\Invoke-CompanyAgent.ps1') -Mode Cli
        Assert-RuntimeSelection ($LASTEXITCODE -eq 0) 'Stale cache failed without old Python or PATH fallback'
        Assert-RuntimeSelection (($output | ConvertFrom-Json).python -ieq $newPython) 'Stale cache did not actually launch the newly selected interpreter'
    }
    finally { $env:PATH = $savedPath; $env:COMPANY_AGENT_PYTHON = $savedPython }

    $claudeInfo = Get-Command $ClaudeCommand | Select-Object -First 1
    $claudeExecutable = $claudeInfo.Source
    if (-not $claudeExecutable) { $claudeExecutable = $claudeInfo.Definition }
    $failureWrapper = Join-Path $testRoot 'claude-fail-update.ps1'
    $wrapper = 'if ($args.Count -ge 2 -and $args[0] -eq ''plugin'' -and $args[1] -eq ''update'') { Write-Output ''RUNTIME_SELECTION_INJECTED_FAILURE''; exit 47 }' + "`r`n"
    $wrapper += '& ''' + $claudeExecutable.Replace("'", "''") + ''' @args' + "`r`n" + 'exit $LASTEXITCODE' + "`r`n"
    Write-CompanyAgentUtf8File -Path $failureWrapper -Content $wrapper
    $common.ClaudeCommand = $failureWrapper
    $common.PythonCommand = $basePython
    $beforeFailure = (Get-FileHash -LiteralPath $selectionPath -Algorithm SHA256).Hash
    $failed = $false
    try { $null = & $setup @common }
    catch {
        if ($_.Exception.Message -notmatch 'RUNTIME_SELECTION_INJECTED_FAILURE') { throw }
        $failed = $true
    }
    Assert-RuntimeSelection $failed 'Injected native update failure was ignored'
    Assert-RuntimeSelection ((Get-FileHash -LiteralPath $selectionPath -Algorithm SHA256).Hash -ceq $beforeFailure) 'Failed reinstall did not restore exact prior selection bytes'
    Assert-RuntimeSelection ((Read-CompanyAgentJson -Path $first.registrationPath).pythonCommand -ieq $newPython) 'Failed reinstall changed the previous scope registration'
    [pscustomobject]@{ status = 'pass'; assertions = $assertions; sameVersionRecovery = $true; staleCacheUsesSelectedPython = $true; selectionRollback = $true; testRoot = $testRoot }
}
finally {
    $env:CLAUDE_CONFIG_DIR = $savedConfig
    $env:CLAUDE_CODE_SUBAGENT_MODEL = $savedForce
    $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE = $savedForce2
    if (-not $KeepTestDirectory -and (Test-Path -LiteralPath $testRoot)) {
        $fullTestRoot = [IO.Path]::GetFullPath($testRoot)
        $tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
        if ((Split-Path -Parent $fullTestRoot) -ine $tempBase -or (Split-Path -Leaf $fullTestRoot) -notlike 'CompanyAgent-RuntimeSelection-*') { throw 'Unsafe test cleanup target.' }
        Remove-Item -LiteralPath $fullTestRoot -Recurse -Force
    }
}
