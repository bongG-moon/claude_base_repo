[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $BundleZip,
    [Parameter(Mandatory = $true)][string] $UpdateBundleZip,
    [Parameter(Mandatory = $true)][string] $ClaudeCommand,
    [Parameter(Mandatory = $true)][string] $PythonCommand,
    [switch] $KeepArtifacts
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
    param([string] $Path, [switch] $IgnoreNativeCacheMarker)
    $records = @(Get-CompanyAgentTreeRecords -Root $Path)
    if ($IgnoreNativeCacheMarker) {
        # Claude marks its former cache orphaned during plugin update. This
        # host-owned timestamp is not an installed or personal source file.
        $records = @($records | Where-Object { $_.path -cne '.orphaned_at' })
    }
    return (@($records | ConvertTo-Json -Depth 10 -Compress) -join '')
}
# Keep the fixture profile close to a real user's path length. A long test name
# can exceed legacy PowerShell Copy-Item limits before the update is exercised.
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('ca-ru-' + [guid]::NewGuid().ToString('N').Substring(0, 12))
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
    $oldEntries = @((Read-CompanyAgentJson -Path (Join-Path $config 'plugins\installed_plugins.json')).plugins.'company-agent@company-agent-local')
    $oldCurrent = @($oldEntries | Where-Object { $_.scope -eq 'user' -and $_.version -eq $oldVersion })
    Assert-ReleaseUpgrade ($oldCurrent.Count -eq 1) 'Baseline plugin cache is ambiguous'
    $oldPluginRoot = [string]$oldCurrent[0].installPath
    $oldPluginBefore = Get-ReleaseTreeSnapshot $oldPluginRoot -IgnoreNativeCacheMarker
    # A preference referring to a removed built-in remains user-owned history.
    # The update must not rewrite it or install a replacement functional Skill.
    $oldCli = Join-Path $oldPluginRoot 'scripts\harness_cli.py'
    $oldSkillArgs = @('--state-root', $state, '--claude-root', $config, '--plugin-root', $oldPluginRoot,
        '--base', (Join-Path $baseline 'payload\knowledge'), '--no-project')
    $oldInventoryText = & $PythonCommand -B $oldCli skill inventory @oldSkillArgs
    Assert-ReleaseUpgrade ($LASTEXITCODE -eq 0) 'Baseline skill inventory failed'
    $oldInventory = ($oldInventoryText -join [Environment]::NewLine) | ConvertFrom-Json
    $oldHtml = @($oldInventory.skills | Where-Object { $_.source -eq 'company' -and $_.name -eq 'html-report' })
    if ($oldHtml.Count -eq 1) {
        $null = & $PythonCommand -B $oldCli skill prefer --scope default --name html-report --candidate $oldHtml[0].id @oldSkillArgs
        Assert-ReleaseUpgrade ($LASTEXITCODE -eq 0) 'Baseline removed-skill preference fixture could not be saved'
    }
    else {
        $oldMarkerPath = Join-Path $oldPluginRoot 'resources\core-install.json'
        Assert-ReleaseUpgrade ($oldHtml.Count -eq 0 -and (Test-Path -LiteralPath $oldMarkerPath -PathType Leaf)) 'Baseline lacks the expected HTML skill or personal harness marker'
        $oldMarker = Read-CompanyAgentJson -Path $oldMarkerPath
        Assert-ReleaseUpgrade ($oldMarker.profile -ceq 'personal-harness') 'Baseline without the HTML skill must be a personal harness release'
    }
    # Real-world synced Office Skills gain another long prefix during backup.
    # Add this after the baseline install so the update exercises that boundary.
    $longSkillRelative = 'skills\synced\aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa_bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb\docx\scripts\office\schemas\ISO-IEC29500-4_2016\dml-spreadsheetDrawing.xsd'
    $longSkillPath = Join-Path $config $longSkillRelative
    $null = [IO.Directory]::CreateDirectory(('\\?\' + (Split-Path -Parent $longSkillPath)))
    [IO.File]::WriteAllText(('\\?\' + $longSkillPath), 'Preserve long-path schema fixture.', (New-Object Text.UTF8Encoding($false)))
    $instruction = Join-Path $config 'CLAUDE.md'
    Write-CompanyAgentUtf8File -Path $instruction -Content 'Preserve personal instructions added after installation.'
    $individualFiles = @()
    foreach ($slug in @('html-report', 'presentation', 'file-organizer', 'work-context-catalog')) {
        $individualSkill = Join-Path $config ('skills\' + $slug + '\SKILL.md')
        Write-CompanyAgentUtf8File -Path $individualSkill -Content ("---`nname: " + $slug + "`ndescription: Separately installed personal Skill fixture`n---`nPreserve my individual package and edits.")
        $individualCode = Join-Path $config ('skills\' + $slug + '\scripts\personal.py')
        Write-CompanyAgentUtf8File -Path $individualCode -Content '# Preserve separate functional package code.'
        $individualFiles += @($individualSkill, $individualCode)
    }
    $personalMailSkill = Join-Path $config 'skills\outlook-assistant\SKILL.md'
    Write-CompanyAgentUtf8File -Path $personalMailSkill -Content "---`nname: outlook-assistant`ndescription: Personal mail fixture`n---`nPreserve this separately installed skill."
    foreach ($relative in @('memory\notes\release.md', 'knowledge\personal-release.md', 'skills\personal-release\SKILL.md',
        'personal-root\.claude\skills\learned-procedure\SKILL.md', 'handoffs\unfinished\handoff.md')) {
        Write-CompanyAgentUtf8File -Path (Join-Path $state $relative) -Content ('Preserve release sentinel: ' + $relative)
    }
    Write-CompanyAgentJsonAtomic -Path (Join-Path $state 'config\learning.json') -Value @{ schemaVersion = 1; enabled = $false }
    Write-CompanyAgentJsonAtomic -Path (Join-Path $state 'learning\state.json') -Value @{ schemaVersion = 1; preservationFixture = 'Keep observations and rollback history.' }
    $stateBefore = Get-ReleaseTreeSnapshot $state
    $personalHashes = @{}
    foreach ($path in @($personalSkill, $personalMailSkill, $instruction, $mcp) + $individualFiles) { $personalHashes[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
    $updated = & (Join-Path $update 'deploy\Setup-CompanyAgent.ps1') @common -BundleRoot $update -ExistingHarnessAction Update
    Assert-ReleaseUpgrade ($updated.status -eq 'updated' -and $updated.previousCoreVersion -eq $oldVersion) 'Update did not report the real old version'
    $longSkillBackup = Join-Path $updated.safetyBackup (Join-Path 'claude-config' $longSkillRelative)
    Assert-ReleaseUpgrade ($longSkillBackup.Length -gt 260) 'Upgrade did not exercise a long backup path'
    Assert-ReleaseUpgrade ([IO.File]::ReadAllText(('\\?\' + $longSkillBackup)) -ceq 'Preserve long-path schema fixture.') 'Long-path Skill file was not backed up intact'
    Assert-ReleaseUpgrade ([IO.File]::ReadAllText(('\\?\' + $longSkillPath)) -ceq 'Preserve long-path schema fixture.') 'Long-path source Skill was changed'
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
    # Verify every declared new payload file, including the exact core profile.
    # hooks.json is adapted once by the scoped installer and checked below.
    $newPluginRoot = Join-Path $update 'payload\core\plugin'
    foreach ($packedFile in @(Get-ChildItem -LiteralPath $newPluginRoot -Recurse -File -Force)) {
        $relative = $packedFile.FullName.Substring($newPluginRoot.TrimEnd('\').Length + 1)
        if ($relative -ieq 'hooks\hooks.json') { continue }
        $cachedModule = Join-Path $current[0].installPath $relative
        Assert-ReleaseUpgrade (Test-Path -LiteralPath $cachedModule -PathType Leaf) "Updated file was not installed: $relative"
        Assert-ReleaseUpgrade ((Get-FileHash -LiteralPath $cachedModule -Algorithm SHA256).Hash -ceq (Get-FileHash -LiteralPath $packedFile.FullName -Algorithm SHA256).Hash) "Updated file was not installed intact: $relative"
    }
    $coreMarker = Read-CompanyAgentJson -Path (Join-Path $current[0].installPath 'resources\core-install.json')
    Assert-ReleaseUpgrade ($coreMarker.schemaVersion -eq 1 -and $coreMarker.profile -ceq 'personal-harness') 'The updated plugin is not the personal harness profile'
    $coreSkills = @(Get-ChildItem -LiteralPath (Join-Path $current[0].installPath 'skills') -Directory | Select-Object -ExpandProperty Name | Sort-Object)
    Assert-ReleaseUpgrade (($coreSkills -join ',') -ceq 'asset-factory,company-agent,personal-knowledge,personal-memory,self-learning') 'Functional Skills remained in the active core'
    foreach ($removed in @('skills\html-report', 'skills\presentation', 'skills\file-organizer',
        'skills\excel-to-pipeline', 'skills\work-context-catalog', 'skills\web-interface',
        'skills\website-rebuild', 'skills\platform-mcp-builder', 'agents\vision-worker.md',
        'scripts\company_agent\business.py', 'scripts\company_agent\business_artifacts.py',
        'scripts\company_agent\business_files.py', 'scripts\company_agent\excel_pipeline_command.py',
        'scripts\company_agent\ppt_workflow.py', 'scripts\company_agent\vision_routing.py',
        'scripts\Invoke-BusinessPowerPoint.ps1', 'templates\business')) {
        Assert-ReleaseUpgrade (-not (Test-Path -LiteralPath (Join-Path $current[0].installPath $removed))) "Functional payload survived in the new core: $removed"
    }
    Assert-ReleaseUpgrade ((Get-ReleaseTreeSnapshot $oldPluginRoot -IgnoreNativeCacheMarker) -ceq $oldPluginBefore) 'Update changed previous plugin source files'
    # A scoped installation changes exactly the Read launcher command/args.
    # Compare the entire expected document, not a blanket exclusion or the
    # source-byte hash that can never match this intentional adaptation.
    $expectedHooks = Read-CompanyAgentJson -Path (Join-Path $update 'payload\core\plugin\hooks\hooks.json')
    $readGroups = @($expectedHooks.hooks.PreToolUse | Where-Object { $_.matcher -ceq '^Read$' })
    # Claude's registry can point to its cache copy rather than the managed
    # distribution folder; the durable launcher belongs to the latter.
    $installedReleaseRoot = Join-Path $localAppData ('CompanyAgent-Distribution\marketplace\versions\' + $newVersion)
    $readLauncher = Join-Path $installedReleaseRoot 'read-hook.cmd'
    if ($readGroups.Count -eq 0) {
        Assert-ReleaseUpgrade (-not (Test-Path -LiteralPath $readLauncher)) 'Read launcher was installed despite no Read hook'
    }
    else {
        Assert-ReleaseUpgrade ($readGroups.Count -eq 1 -and $readGroups[0].hooks.Count -eq 1) 'Source contains ambiguous Read hooks'
        Assert-ReleaseUpgrade (Test-Path -LiteralPath $readLauncher -PathType Leaf) 'Updated Read launcher is missing'
        $readGroups[0].hooks[0].command = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'cmd.exe'
        $readGroups[0].hooks[0].args = @('/d', '/v:off', '/s', '/c', 'call', $readLauncher)
    }
    $installedHooks = Read-CompanyAgentJson -Path (Join-Path $current[0].installPath 'hooks\hooks.json')
    Assert-ReleaseUpgrade (($expectedHooks | ConvertTo-Json -Depth 100 -Compress) -ceq ($installedHooks | ConvertTo-Json -Depth 100 -Compress)) 'Installed hooks differ beyond the expected Read launcher adaptation'
    foreach ($removed in @('resources\first-work.html', 'resources\manuals\Company-Agent-Guide.html',
        'resources\manuals\Company-Agent-Handbook.html', 'resources\manuals\Company-Agent-Onboarding.html',
        'resources\manuals\Claude-Code-필수-사용법.html',
        'skills\office-reader', 'scripts\Read-CompanyOffice.py', 'scripts\Read-CompanyExcel.py',
        'scripts\company_agent\office_reader.py', 'scripts\company_agent\office_consent.py',
        'scripts\company_agent\office_progress.py', 'scripts\company_agent\office_pywin32.py',
        'scripts\company_agent\office_structure.py', 'scripts\company_agent\excel_xlwings.py')) {
        Assert-ReleaseUpgrade (-not (Test-Path -LiteralPath (Join-Path $current[0].installPath $removed))) "Removed legacy material still exists in the active plugin: $removed"
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
        readHookRegistrationVerified = $true
        personalStatePreserved = $true; originalArchivesPreserved = $true
        individualFunctionalSkillsPreserved = $true; removedSkillPreferencePreserved = $true
        previousPluginPreserved = $true; activeCoreProfile = $coreMarker.profile
        longPathSkillBackupPreserved = $true
        artifactsKept = [bool]$KeepArtifacts; testRoot = $testRoot
    }
}
finally {
    foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    if (-not $KeepArtifacts -and (Test-Path -LiteralPath $testRoot)) {
        $resolved = ConvertTo-CompanyAgentFullPath -Path $testRoot
        $tempRoot = (ConvertTo-CompanyAgentFullPath -Path ([IO.Path]::GetTempPath())).TrimEnd('\')
        if (-not $resolved.StartsWith(($tempRoot + '\'), [StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $resolved) -notmatch '^ca-ru-[0-9a-f]{12}$') { throw 'Unsafe release upgrade cleanup path.' }
        $cleanupIO = '\\?\' + $resolved
        if (([IO.File]::GetAttributes($cleanupIO) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Unsafe release upgrade cleanup link.' }
        # The fixture now deliberately contains paths beyond MAX_PATH too.
        [IO.Directory]::Delete($cleanupIO, $true)
    }
}
