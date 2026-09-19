[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $BundleZip,
    [Parameter(Mandatory = $true)][string] $UpdateBundleZip,
    [Parameter(Mandatory = $true)][string] $ClaudeCommand,
    [Parameter(Mandatory = $true)][string] $PythonCommand
)

# Positive old-release -> new-release integration using both unmodified ZIPs.
# Keep current-release rejection/rollback cases in Test-ScopedInstallSmoke.ps1:
# a legacy installer's error presentation must not prevent testing an update.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')
function Assert-ReleaseUpgrade {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "Release upgrade failed: $Message" }
}
function Get-ReleaseTreeSnapshot {
    param([string] $Path)
    return (@(Get-CompanyAgentTreeRecords -Root $Path | ConvertTo-Json -Depth 10 -Compress) -join '')
}
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('CompanyAgent-ReleaseUpgrade-' + [guid]::NewGuid().ToString('N'))
$savedEnvironment = @{}
foreach ($name in @('CLAUDE_CONFIG_DIR', 'CLAUDE_CODE_SUBAGENT_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE')) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $BundleZip = (Resolve-Path -LiteralPath $BundleZip).Path
    $UpdateBundleZip = (Resolve-Path -LiteralPath $UpdateBundleZip).Path
    $archiveHashes = @{}
    foreach ($archive in @($BundleZip, $UpdateBundleZip)) {
        $archiveHashes[$archive] = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    }
    $baseline = Join-Path $testRoot 'baseline'
    $update = Join-Path $testRoot 'update'
    Expand-Archive -LiteralPath $BundleZip -DestinationPath $baseline
    Expand-Archive -LiteralPath $UpdateBundleZip -DestinationPath $update
    $oldVersion = [string](Read-CompanyAgentJson -Path (Join-Path $baseline 'bundle-manifest.json')).coreVersion
    $newVersion = [string](Read-CompanyAgentJson -Path (Join-Path $update 'bundle-manifest.json')).coreVersion
    Assert-ReleaseUpgrade ([version]$newVersion -gt [version]$oldVersion) 'The update must have a newer version'
    $profile = Join-Path $testRoot 'isolated profile'
    $localAppData = Join-Path $profile 'AppData\Local'
    $config = Join-Path $profile '.claude'
    $state = Join-Path $testRoot 'personal state'
    $project = Join-Path $testRoot 'plain working folder'
    foreach ($path in @($config, $localAppData, $project)) { New-CompanyAgentDirectory -Path $path }
    $env:CLAUDE_CONFIG_DIR = $config
    $env:CLAUDE_CODE_SUBAGENT_MODEL = $null
    $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE = $null
    Write-CompanyAgentJsonAtomic -Path (Join-Path $config 'settings.json') -Value @{
        env = @{ ANTHROPIC_DEFAULT_SONNET_MODEL = 'fixture-company-model' }
        enabledPlugins = @{ 'unrelated@fixture' = $true }
    }
    $personalSkill = Join-Path $config 'skills\release-sentinel\SKILL.md'
    Write-CompanyAgentUtf8File -Path $personalSkill -Content "---`nname: release-sentinel`ndescription: Release preservation test`n---`nPreserve this personal skill."
    $mcp = Join-Path $config '.mcp.json'
    Write-CompanyAgentJsonAtomic -Path $mcp -Value @{ mcpServers = @{ fixture = @{ command = 'fixture-not-executed' } } }
    $common = @{
        Scope = 'User'; ClaudeConfigRoot = $config; InvokingUserProfile = $profile
        InvokingLocalAppData = $localAppData; UserStateRoot = $state
        ClaudeCommand = $ClaudeCommand; PythonCommand = $PythonCommand
        NonInteractive = $true; SkipAdminCheck = $true
    }
    $installed = & (Join-Path $baseline 'deploy\Setup-CompanyAgent.ps1') @common -BundleRoot $baseline -ExistingHarnessAction Replace
    Assert-ReleaseUpgrade ($installed.status -eq 'installed') 'Original release did not install'
    $instruction = Join-Path $config 'CLAUDE.md'
    Write-CompanyAgentUtf8File -Path $instruction -Content 'Preserve personal instructions added after installation.'
    foreach ($relative in @('memory\notes\release.md', 'knowledge\personal-release.md', 'skills\personal-release\SKILL.md')) {
        Write-CompanyAgentUtf8File -Path (Join-Path $state $relative) -Content ('Preserve release sentinel: ' + $relative)
    }
    $stateBefore = Get-ReleaseTreeSnapshot $state
    $personalHashes = @{}
    foreach ($path in @($personalSkill, $instruction, $mcp)) { $personalHashes[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
    $updated = & (Join-Path $update 'deploy\Setup-CompanyAgent.ps1') @common -BundleRoot $update -ExistingHarnessAction Update
    Assert-ReleaseUpgrade ($updated.status -eq 'updated' -and $updated.previousCoreVersion -eq $oldVersion) 'Update did not report the real old version'
    Assert-ReleaseUpgrade (-not $updated.previousHarnessDeactivated) 'Update deactivated personal instructions'
    Assert-ReleaseUpgrade ((Get-ReleaseTreeSnapshot $state) -ceq $stateBefore) 'Update changed personal state contents'
    foreach ($path in $personalHashes.Keys) {
        Assert-ReleaseUpgrade ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ceq $personalHashes[$path]) 'Update changed personal Skill, instructions or MCP'
    }
    $settings = Read-CompanyAgentJson -Path (Join-Path $config 'settings.json')
    Assert-ReleaseUpgrade ($settings.env.ANTHROPIC_DEFAULT_SONNET_MODEL -eq 'fixture-company-model' -and $settings.enabledPlugins.'unrelated@fixture' -eq $true) 'Update changed unrelated model/plugin settings'
    $registration = Read-CompanyAgentJson -Path $updated.registrationPath
    Assert-ReleaseUpgrade ($registration.coreVersion -eq $newVersion -and $registration.userStateRoot -ieq $state) 'Registration selected the wrong version/state'
    $entries = @((Read-CompanyAgentJson -Path (Join-Path $config 'plugins\installed_plugins.json')).plugins.'company-agent@company-agent-local')
    $current = @($entries | Where-Object { $_.scope -eq 'user' -and $_.version -eq $newVersion })
    Assert-ReleaseUpgrade ($current.Count -eq 1) 'Native Claude registry did not select the new version'
    foreach ($relative in @(
        'scripts\company_agent\skill_execution.py', 'scripts\company_agent\skill_workflow.py',
        'scripts\company_agent\office_progress.py', 'scripts\company_agent\office_reader.py',
        'scripts\company_agent\business_safety.py', 'scripts\company_agent\workspace_api.py',
        'scripts\company_agent\resource_scope.py', 'scripts\company_agent\harness_map.py',
        'scripts\company_agent\harness_map_html.py',
        'scripts\company_agent\company_policy.py', 'scripts\company_agent\skill_decision.py',
        'scripts\company_agent\workflow_evidence.py', 'scripts\company_agent\state.py',
        'scripts\company_agent\html_reference.py', 'scripts\company_agent\knowledge.py',
        'scripts\Invoke-CompanyAgent.ps1', 'scripts\Confirm-BusinessAction.ps1',
        'skills\office-reader\SKILL.md', 'skills\html-report\SKILL.md',
        'resources\first-work.html', 'resources\onboarding-course.json',
        'resources\manuals\Company-Agent-Handbook.html', 'resources\manuals\Company-Agent-Onboarding.html',
        'resources\manuals\Company-Agent-Cua-Pilot.html'
    )) {
        $cachedModule = Join-Path $current[0].installPath $relative
        $packedModule = Join-Path (Join-Path $update 'payload\core\plugin') $relative
        Assert-ReleaseUpgrade ((Get-FileHash -LiteralPath $cachedModule -Algorithm SHA256).Hash -ceq (Get-FileHash -LiteralPath $packedModule -Algorithm SHA256).Hash) "Updated file was not installed intact: $relative"
    }
    $debugFile = Join-Path $testRoot 'updated-init.log'
    Push-Location -LiteralPath $project
    try {
        $init = & $ClaudeCommand --init-only --debug-file $debugFile 2>&1
        Assert-ReleaseUpgrade ($LASTEXITCODE -eq 0) ('Updated Claude initialization failed: ' + ($init -join ' '))
    }
    finally { Pop-Location }
    $debugText = Get-Content -LiteralPath $debugFile -Raw -Encoding UTF8
    Assert-ReleaseUpgrade ([regex]::Matches($debugText, 'Hook SessionStart:startup \(SessionStart\) success').Count -eq 1) 'Updated plugin must run one SessionStart in a plain folder'
    foreach ($archive in $archiveHashes.Keys) {
        Assert-ReleaseUpgrade ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ceq $archiveHashes[$archive]) 'Test modified an input release ZIP'
    }
    [pscustomobject]@{
        status = 'pass'; previousVersion = $oldVersion; updatedVersion = $newVersion
        nativeClaudeRegistration = $true; nativeSessionStart = $true
        personalStatePreserved = $true; originalArchivesPreserved = $true
    }
}
finally {
    foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    if (Test-Path -LiteralPath $testRoot) {
        $resolved = ConvertTo-CompanyAgentFullPath -Path $testRoot
        $tempRoot = (ConvertTo-CompanyAgentFullPath -Path ([IO.Path]::GetTempPath())).TrimEnd('\')
        if (-not $resolved.StartsWith(($tempRoot + '\'), [StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $resolved) -notlike 'CompanyAgent-ReleaseUpgrade-*') { throw 'Unsafe release upgrade cleanup path.' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
