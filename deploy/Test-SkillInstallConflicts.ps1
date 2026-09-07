[CmdletBinding()]
param(
    [string] $BundleRoot,
    [string] $PythonCommand = 'python',
    [switch] $KeepTestDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$testEntry = @{ BundleRoot = $BundleRoot; PythonCommand = $PythonCommand; KeepTestDirectory = $KeepTestDirectory }
. (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1') -FunctionsOnly
foreach ($entryName in $testEntry.Keys) { Set-Variable -Name $entryName -Value $testEntry[$entryName] }
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('CompanyAgent-SkillConflicts-' + [guid]::NewGuid().ToString('N').Substring(0, 12))
$savedConfig = $env:CLAUDE_CONFIG_DIR
$savedForce = $env:CLAUDE_CODE_SUBAGENT_MODEL
$savedForce2 = $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE
$savedFailure = $env:COMPANY_AGENT_SKILL_TEST_FAIL
$savedPluginRoot = $env:COMPANY_AGENT_PLUGIN_ROOT
$savedKnowledgeRoot = $env:COMPANY_AGENT_KNOWLEDGE_BASE
$assertions = 0
function Assert-SkillInstall {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "Skill installation regression failed: $Message" }
    $script:assertions++
}
function Get-SkillFixtureDigest {
    param([string] $Root)
    if (-not (Test-Path -LiteralPath $Root)) { return 'missing' }
    return (@(Get-ChildItem -LiteralPath $Root -File -Recurse -Force | Sort-Object FullName | ForEach-Object {
        '{0}|{1}|{2}' -f $_.FullName, $_.Length, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }) -join "`n")
}
function Write-SkillFixture {
    param([string] $Path, [string] $Name)
    Write-CompanyAgentUtf8File -Path $Path -Content ("---`nname: $Name`ndescription: Existing isolated fixture for $Name.`n---`nKeep the original Skill file.`n")
}

try {
    New-CompanyAgentDirectory -Path $testRoot
    if ([string]::IsNullOrWhiteSpace($BundleRoot)) {
        $repoRoot = Split-Path -Parent $PSScriptRoot
        $pluginManifest = Read-CompanyAgentJson -Path (Join-Path $repoRoot 'company-agent-plugin\.claude-plugin\plugin.json')
        $knowledgeManifest = Read-CompanyAgentJson -Path (Join-Path $repoRoot 'corporate-knowledge\pack.json')
        $zip = Join-Path $testRoot 'bundle.zip'
        $null = & (Join-Path $PSScriptRoot 'New-OfflineBundle.ps1') -SourceRoot $repoRoot -CoreVersion $pluginManifest.version -KnowledgeVersion $knowledgeManifest.version -OutputPath $zip -SkipSourceValidation
        $BundleRoot = Join-Path $testRoot 'bundle'
        Expand-Archive -LiteralPath $zip -DestinationPath $BundleRoot
    }
    $python = [string](& $PythonCommand -I -B -c 'import sys; print(sys.executable)')
    if ($LASTEXITCODE -ne 0) { throw 'A working Python 3.11+ is required for Skill conflict checks.' }
    $sourcePlugin = Join-Path $BundleRoot 'payload\core\plugin'
    $sourceKnowledge = Join-Path $BundleRoot 'payload\knowledge'
    $setup = Join-Path $BundleRoot 'deploy\Setup-CompanyAgent.ps1'
    $profile = Join-Path $testRoot 'profile'
    $config = Join-Path $profile '.claude'
    $localData = Join-Path $profile 'AppData\Local'
    $state = Join-Path $testRoot 'personal state'
    $project = Join-Path $testRoot 'Selected project'
    $otherProject = Join-Path $testRoot 'Unselected project'
    foreach ($directory in @($config, $localData, $project, $otherProject)) { New-CompanyAgentDirectory -Path $directory }
    $env:CLAUDE_CONFIG_DIR = $config
    $env:CLAUDE_CODE_SUBAGENT_MODEL = $null
    $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE = $null
    $env:COMPANY_AGENT_SKILL_TEST_FAIL = $null
    $ambientPlugin = Join-Path $testRoot 'ambient plugin'
    $ambientKnowledge = Join-Path $testRoot 'ambient knowledge'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $ambientPlugin '.claude-plugin\plugin.json') -Value ([pscustomobject]@{ name = 'unrelated-session-plugin'; version = '1.0.0' })
    Write-SkillFixture -Path (Join-Path $ambientPlugin 'skills\ambient-plugin-only\SKILL.md') -Name 'ambient-plugin-only'
    Write-SkillFixture -Path (Join-Path $ambientKnowledge '.claude\skills\ambient-knowledge-only\SKILL.md') -Name 'ambient-knowledge-only'
    $env:COMPANY_AGENT_PLUGIN_ROOT = $ambientPlugin
    $env:COMPANY_AGENT_KNOWLEDGE_BASE = $ambientKnowledge

    # Emulate only the three registration commands, against this test profile.
    # Inventory and preference behavior always use the package's real Python CLI.
    $claudeFixture = Join-Path $testRoot 'claude-registration-fixture.ps1'
    Write-CompanyAgentUtf8File -Path $claudeFixture -Content @'
$ErrorActionPreference = 'Stop'
function Read-Doc([string] $path) {
    if (Test-Path -LiteralPath $path) { return Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json }
    return [pscustomobject]@{}
}
function Save-Doc([string] $path, [object] $doc) {
    $null = New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force
    [IO.File]::WriteAllText($path, ($doc | ConvertTo-Json -Depth 30), (New-Object Text.UTF8Encoding($false)))
}
if ($args[0] -eq '--version') { Write-Output '2.1.0'; exit 0 }
if ($args[0] -ne 'plugin') { throw 'Unexpected fixture command.' }
if ($args[1] -eq 'update' -and $env:COMPANY_AGENT_SKILL_TEST_FAIL -eq 'update') {
    Write-Output 'SKILL_INSTALL_INJECTED_FAILURE'; exit 41
}
$config = $env:CLAUDE_CONFIG_DIR
$scope = [string]$args[$args.Count - 1]
$knownPath = Join-Path $config 'plugins\known_marketplaces.json'
if ($args[1] -eq 'marketplace' -and $args[2] -eq 'add') {
    $known = Read-Doc $knownPath
    $known | Add-Member -MemberType NoteProperty -Name 'company-agent-local' -Value ([pscustomobject]@{
        source = [pscustomobject]@{ source = 'directory'; path = [string]$args[3] }; installLocation = [string]$args[3]
    }) -Force
    Save-Doc $knownPath $known
    exit 0
}
$known = Read-Doc $knownPath
$market = [string]$known.'company-agent-local'.source.path
$manifest = Read-Doc (Join-Path $market '.claude-plugin\marketplace.json')
$pluginPath = [IO.Path]::GetFullPath((Join-Path $market $manifest.plugins[0].source))
$inventoryPath = Join-Path $config 'plugins\installed_plugins.json'
$inventory = Read-Doc $inventoryPath
if ($null -eq $inventory.PSObject.Properties['plugins']) { $inventory | Add-Member NoteProperty plugins ([pscustomobject]@{}) }
$pluginId = 'company-agent@company-agent-local'
$projectPath = $(if ($scope -eq 'local') { (Get-Location).Path } else { $null })
$prior = @()
if ($null -ne $inventory.plugins.PSObject.Properties[$pluginId]) {
    $prior = @($inventory.plugins.$pluginId | Where-Object { $_.scope -ne $scope -or ($scope -eq 'local' -and $_.projectPath -ne $projectPath) })
}
$pluginVersion = (Read-Doc (Join-Path $pluginPath '.claude-plugin\plugin.json')).version
$record = [pscustomobject]@{ scope = $scope; installPath = $pluginPath; projectPath = $projectPath; version = $pluginVersion }
$inventory | Add-Member NoteProperty version 2 -Force
$inventory.plugins | Add-Member NoteProperty $pluginId @($prior + @($record)) -Force
Save-Doc $inventoryPath $inventory
$settingsPath = $(if ($scope -eq 'local') { Join-Path $projectPath '.claude\settings.local.json' } else { Join-Path $config 'settings.json' })
$settings = Read-Doc $settingsPath
if ($null -eq $settings.PSObject.Properties['enabledPlugins']) { $settings | Add-Member NoteProperty enabledPlugins ([pscustomobject]@{}) }
$settings.enabledPlugins | Add-Member NoteProperty $pluginId $true -Force
Save-Doc $settingsPath $settings
exit 0
'@
    $common = @{
        BundleRoot = $BundleRoot; Scope = 'User'; UserStateRoot = $state; ClaudeConfigRoot = $config
        InvokingUserProfile = $profile; InvokingLocalAppData = $localData; ClaudeCommand = $claudeFixture
        PythonCommand = $python; NonInteractive = $true; SkipAdminCheck = $true; SkipPrerequisiteCheck = $true
        BackupRoot = (Join-Path $testRoot 'backups')
        ExistingHarnessAction = 'Replace'
    }
    $inventoryArgs = @{
        PythonExecutable = $python; PluginRoot = $sourcePlugin; PersonalStatePath = $state
        KnowledgeRoot = $sourceKnowledge
        ClaudeConfigPath = $config; InstallScope = 'User'
    }
    $pinnedInventory = Invoke-SetupSkillCommand @inventoryArgs
    Assert-SkillInstall (@($pinnedInventory.skills | Where-Object { $_.name -like 'ambient-*' }).Count -eq 0) 'Installer inventory inherited unrelated session Plugin or Corporate Knowledge Skills'
    $pinnedIncoming = @($pinnedInventory.skills | Where-Object { $_.incoming })
    Assert-SkillInstall ($pinnedIncoming.Count -gt 0 -and @($pinnedIncoming | Where-Object { $_.source -ne 'company' -or -not $_.path.StartsWith($sourcePlugin, [StringComparison]::OrdinalIgnoreCase) }).Count -eq 0) 'Installer did not pin incoming Company Skill identity to the verified bundle'
    $empty = & $setup @common -DryRun
    Assert-SkillInstall ($empty.status -eq 'dry-run' -and @($empty.skillConflicts).Count -eq 0) 'An empty profile did not install normally without a Skill question'
    Assert-SkillInstall (-not (Test-Path -LiteralPath $state)) 'Read-only inventory initialized personal state'

    $skillNames = @(Get-ChildItem -LiteralPath (Join-Path $sourcePlugin 'skills') -Directory | Sort-Object Name | Select-Object -ExpandProperty Name)
    Assert-SkillInstall ($skillNames.Count -ge 2) 'Bundle must contain two incoming Skills for the project-isolation fixture'
    $skillName = [string]$skillNames[0]
    $projectSkillName = [string]$skillNames[1]
    $userSkill = Join-Path $config ("skills\$skillName\SKILL.md")
    $stateSkill = Join-Path $state ("personal-root\.claude\skills\$skillName\SKILL.md")
    $projectSkill = Join-Path $project (".claude\skills\$projectSkillName\SKILL.md")
    Write-SkillFixture -Path $userSkill -Name $skillName
    Write-SkillFixture -Path $stateSkill -Name $skillName
    Write-SkillFixture -Path $projectSkill -Name $projectSkillName
    Write-SkillFixture -Path (Join-Path $otherProject '.claude\skills\unselected-only\SKILL.md') -Name 'unselected-only'
    $otherPlugin = Join-Path $config 'plugins\cache\other-fixture'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $otherPlugin '.claude-plugin\plugin.json') -Value ([pscustomobject]@{ name = 'other-fixture'; version = '1.0.0' })
    Write-SkillFixture -Path (Join-Path $otherPlugin ("skills\$skillName\SKILL.md")) -Name $skillName
    Write-CompanyAgentJsonAtomic -Path (Join-Path $config 'plugins\installed_plugins.json') -Value ([pscustomobject]@{
        version = 2; plugins = [pscustomobject]@{
            'other-fixture@fixture' = @([pscustomobject]@{ scope = 'user'; installPath = $otherPlugin; version = '1.0.0' })
        }
    })
    Write-CompanyAgentJsonAtomic -Path (Join-Path $config 'settings.json') -Value ([pscustomobject]@{
        enabledPlugins = [pscustomobject]@{ 'other-fixture@fixture' = $true }; model = 'existing-alias'
    })
    $userSkillHash = (Get-FileHash -LiteralPath $userSkill -Algorithm SHA256).Hash
    $before = (Get-SkillFixtureDigest $profile) + (Get-SkillFixtureDigest $state) + (Get-SkillFixtureDigest $project)
    foreach ($preview in @($false, $true)) {
        $ask = & $setup @common -DryRun:$preview
        Assert-SkillInstall ($ask.status -eq 'input-required' -and $ask.input -eq 'SkillConflictAction') 'Unattended Ask did not request an explicit Skill decision'
        Assert-SkillInstall (@($ask.choices).Count -eq 2 -and @($ask.skillConflicts).Count -gt 0) 'Skill question omitted choices or conflict detail'
        $allCandidates = @($ask.skillConflicts | ForEach-Object { $_.candidates })
        Assert-SkillInstall (@($allCandidates | Where-Object { $_.source -eq 'plugin' -and -not $_.incoming }).Count -gt 0) 'Namespaced installed plugin overlap was hidden'
        Assert-SkillInstall (@($allCandidates | Where-Object { $_.path -like ($project + '*') }).Count -eq 0) 'User install scanned the unrelated current project'
    }
    foreach ($action in @('KeepCurrent', 'PreferIncoming')) {
        $dry = & $setup @common -DryRun -SkillConflictAction $action
        Assert-SkillInstall ($dry.status -eq 'dry-run' -and $dry.skillConflictAction -eq $action) 'Explicit Skill choice was not returned by DryRun'
    }
    Assert-SkillInstall (((Get-SkillFixtureDigest $profile) + (Get-SkillFixtureDigest $state) + (Get-SkillFixtureDigest $project)) -ceq $before) 'Ask or DryRun wrote into fixture source/state'
    Assert-SkillInstall (-not (Test-Path -LiteralPath $common.BackupRoot)) 'Skill Ask/DryRun created a backup'
    Assert-SkillInstall (-not (Test-Path -LiteralPath (Join-Path $localData 'CompanyAgent-Distribution'))) 'Skill Ask/DryRun created a release'

    $conflicts = @($ask.skillConflicts)
    $script:skillFixtureAnswers = New-Object Collections.Queue
    function Read-Host { return $script:skillFixtureAnswers.Dequeue() }
    foreach ($case in @(@('', 'KeepCurrent'), @('2', 'PreferIncoming'), @('3', 'Cancel'))) {
        $script:skillFixtureAnswers.Enqueue($case[0])
        Assert-SkillInstall ((Resolve-SetupSkillConflictAction -Conflicts $conflicts) -eq $case[1]) 'Interactive Skill choice mapped incorrectly'
    }
    Remove-Item -LiteralPath Function:\Read-Host
    $preferencePath = Join-Path $state 'config\skill-preferences.json'
    $installedKeep = & $setup @common -SkillConflictAction KeepCurrent
    Assert-SkillInstall ($installedKeep.status -eq 'installed' -and $installedKeep.skillConflictAction -eq 'KeepCurrent') 'KeepCurrent did not complete installation'
    Assert-SkillInstall (-not (Test-Path -LiteralPath $preferencePath)) 'KeepCurrent created preferences'
    $installedPrefer = & $setup @common -SkillConflictAction PreferIncoming
    Assert-SkillInstall ($installedPrefer.status -eq 'reapplied' -and (Test-Path -LiteralPath $preferencePath)) 'PreferIncoming did not save explicit selections'
    $selectionInventory = Invoke-SetupSkillCommand @inventoryArgs
    $userCandidate = @($selectionInventory.skills | Where-Object { $_.name -eq $skillName -and $_.source -eq 'user' })[0]
    $null = & $python -B (Join-Path $sourcePlugin 'scripts\harness_cli.py') skill prefer --state-root $state --claude-root $config --plugin-root $sourcePlugin --incoming-plugin $sourcePlugin --base $sourceKnowledge --no-project --scope default --name $skillName --candidate $userCandidate.id
    Assert-SkillInstall ($LASTEXITCODE -eq 0) 'Could not seed an explicit existing Skill preference'
    $preferencesBefore = (Get-FileHash -LiteralPath $preferencePath -Algorithm SHA256).Hash
    $updatedKeep = & $setup @common -SkillConflictAction KeepCurrent
    Assert-SkillInstall ($updatedKeep.status -eq 'reapplied' -and (Get-FileHash -LiteralPath $preferencePath -Algorithm SHA256).Hash -ceq $preferencesBefore) 'Update with KeepCurrent replaced saved selections'
    $preferenceBackup = Join-Path $updatedKeep.safetyBackup 'company-agent\personal-learning\config\skill-preferences.json'
    Assert-SkillInstall (Test-Path -LiteralPath $preferenceBackup) 'Selective backup omitted Skill preferences'
    Assert-SkillInstall (Test-Path -LiteralPath (Join-Path $updatedKeep.safetyBackup 'company-agent\personal-learning\config\skill-preferences-history')) 'Selective backup omitted Skill preference history'
    $validPreferenceBytes = [IO.File]::ReadAllBytes($preferencePath)
    $stalePreferences = Read-CompanyAgentJson -Path $preferencePath
    $stalePreferences.defaults.skills.$skillName = 'user:000000000000000000000000'
    Write-CompanyAgentJsonAtomic -Path $preferencePath -Value $stalePreferences
    try {
        $stalePreview = & $setup @common -DryRun -SkillConflictAction KeepCurrent
        Assert-SkillInstall ($stalePreview.status -eq 'dry-run' -and @($stalePreview.skillWarnings).Count -gt 0) 'Stale preference warnings blocked a valid inventory instead of allowing reselection'
    }
    finally { [IO.File]::WriteAllBytes($preferencePath, $validPreferenceBytes) }

    # Formatting makes byte preservation observable even if the same preference
    # is selected again during the deliberately failed update.
    $prefText = [IO.File]::ReadAllText($preferencePath)
    Write-CompanyAgentUtf8File -Path $preferencePath -Content ("`r`n  " + $prefText + "`r`n")
    $preferencesBefore = (Get-FileHash -LiteralPath $preferencePath -Algorithm SHA256).Hash
    $env:COMPANY_AGENT_SKILL_TEST_FAIL = 'update'
    $failed = $false
    try { $null = & $setup @common -SkillConflictAction PreferIncoming }
    catch { if ($_.Exception.Message -notmatch 'SKILL_INSTALL_INJECTED_FAILURE') { throw }; $failed = $true }
    finally { $env:COMPANY_AGENT_SKILL_TEST_FAIL = $null }
    Assert-SkillInstall $failed 'Injected native failure was ignored'
    Assert-SkillInstall ((Get-FileHash -LiteralPath $preferencePath -Algorithm SHA256).Hash -ceq $preferencesBefore) 'Failed installation did not restore exact original preference bytes'
    Assert-SkillInstall ((Get-FileHash -LiteralPath $userSkill -Algorithm SHA256).Hash -ceq $userSkillHash) 'Incoming preference deleted, renamed, or changed an original Skill'

    $projectCommon = $common.Clone()
    $projectCommon.Scope = 'Project'
    $projectCommon.ProjectRoot = $project
    $projectCommon.UserStateRoot = Join-Path $testRoot 'project state'
    $projectAsk = & $setup @projectCommon
    Assert-SkillInstall ($projectAsk.status -eq 'input-required' -and @($projectAsk.skillConflicts | Where-Object { $_.name -eq $projectSkillName }).Count -gt 0) 'Project install omitted selected project Skill overlap'
    Assert-SkillInstall (($projectAsk.skillConflicts | ConvertTo-Json -Depth 20) -notmatch 'unselected-only') 'Project inventory scanned another project'
    $env:COMPANY_AGENT_SKILL_TEST_FAIL = 'update'
    $failedProject = $false
    try { $null = & $setup @projectCommon -SkillConflictAction PreferIncoming }
    catch { if ($_.Exception.Message -notmatch 'SKILL_INSTALL_INJECTED_FAILURE') { throw }; $failedProject = $true }
    finally { $env:COMPANY_AGENT_SKILL_TEST_FAIL = $null }
    Assert-SkillInstall ($failedProject -and -not (Test-Path -LiteralPath (Join-Path $projectCommon.UserStateRoot 'config\skill-preferences.json'))) 'Failed fresh installation left a new preference file'
    $projectInstalled = & $setup @projectCommon -SkillConflictAction PreferIncoming
    Assert-SkillInstall ($projectInstalled.status -eq 'installed') 'Project preference installation failed'
    $projectPreferences = Read-CompanyAgentJson -Path (Join-Path $projectCommon.UserStateRoot 'config\skill-preferences.json')
    Assert-SkillInstall ($null -ne $projectPreferences.projects.PSObject.Properties[$project.ToLowerInvariant()] -and @($projectPreferences.defaults.skills.PSObject.Properties).Count -eq 0) 'Project selection was not tied to the selected project'

    # A locked Skill cannot be read safely; this must stop before any backup.
    $locked = [IO.File]::Open($userSkill, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $unreadableRejected = $false
    try { try { $null = Invoke-SetupSkillCommand @inventoryArgs } catch { $unreadableRejected = $true } }
    finally { $locked.Dispose() }
    Assert-SkillInstall $unreadableRejected 'Unreadable Skill inventory silently reported no conflict'
    [pscustomobject]@{
        status = 'pass'; assertions = $assertions; actualPythonInventory = $true
        isolatedClaudeRegistration = $true; noWriteChoices = $true; exactPreferenceRollback = $true; testRoot = $testRoot
    }
}
finally {
    if (Test-Path -LiteralPath Function:\Read-Host) { Remove-Item -LiteralPath Function:\Read-Host }
    $env:CLAUDE_CONFIG_DIR = $savedConfig
    $env:CLAUDE_CODE_SUBAGENT_MODEL = $savedForce
    $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE = $savedForce2
    $env:COMPANY_AGENT_SKILL_TEST_FAIL = $savedFailure
    $env:COMPANY_AGENT_PLUGIN_ROOT = $savedPluginRoot
    $env:COMPANY_AGENT_KNOWLEDGE_BASE = $savedKnowledgeRoot
    if (-not $KeepTestDirectory -and (Test-Path -LiteralPath $testRoot)) {
        $fullTestRoot = [IO.Path]::GetFullPath($testRoot)
        $tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
        if ((Split-Path -Parent $fullTestRoot) -ine $tempBase -or (Split-Path -Leaf $fullTestRoot) -notlike 'CompanyAgent-SkillConflicts-*') { throw 'Unsafe Skill fixture cleanup target.' }
        Remove-Item -LiteralPath $fullTestRoot -Recurse -Force
    }
}
