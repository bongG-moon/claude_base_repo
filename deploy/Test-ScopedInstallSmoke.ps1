[CmdletBinding()]
param(
    [string] $BundleRoot,
    [string] $BundleZip,
    [string] $UpdateBundleZip,
    [string] $ClaudeCommand = 'claude',
    [string] $PythonCommand = 'python',
    [switch] $IncludeBundledPython,
    [switch] $LegacyEncoding,
    [switch] $KeepTestDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')
function Assert-ScopedSmoke {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "Scoped install smoke failed: $Message" }
}
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('CompanyAgent-ScopedSmoke-' + [guid]::NewGuid().ToString('N').Substring(0, 12))
$originalConfig = $env:CLAUDE_CONFIG_DIR
$originalForce = $env:CLAUDE_CODE_SUBAGENT_MODEL
$originalForce2 = $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE
$originalPythonEncoding = $env:PYTHONIOENCODING
$originalPythonUtf8 = $env:PYTHONUTF8
$originalConsoleEncoding = [Console]::OutputEncoding
$originalPipeEncoding = $OutputEncoding
try {
    # This integration suite tests one known CLI, not the interactive chooser.
    # Pin the command PowerShell would run before passing it into the installer:
    # development PCs may legitimately have multiple native/npm installations.
    # Discovery ambiguity is covered separately by Test-ClaudeDiscovery.ps1.
    $testClaudeCommand = Get-Command $ClaudeCommand -CommandType Application,ExternalScript -ErrorAction Stop | Select-Object -First 1
    $testClaudePath = [string]$testClaudeCommand.Source
    if ([string]::IsNullOrWhiteSpace($testClaudePath) -or
        -not [IO.Path]::IsPathRooted($testClaudePath) -or
        -not (Test-Path -LiteralPath $testClaudePath -PathType Leaf) -or
        [IO.Path]::GetExtension($testClaudePath) -notin @('.exe', '.cmd', '.bat', '.ps1')) {
        throw 'Scoped smoke needs an existing Claude Code executable. Pass its absolute path with -ClaudeCommand.'
    }
    $ClaudeCommand = [IO.Path]::GetFullPath($testClaudePath)
    Write-Host ("Scoped smoke Claude CLI: {0}" -f $ClaudeCommand)
    New-CompanyAgentDirectory -Path $testRoot
    if ($BundleRoot -and $BundleZip) { throw 'Use BundleRoot or BundleZip, not both.' }
    if ([string]::IsNullOrWhiteSpace($BundleRoot)) {
        $repoRoot = Split-Path -Parent $PSScriptRoot
        $pluginManifest = Read-CompanyAgentJson -Path (Join-Path $repoRoot 'company-agent-plugin\.claude-plugin\plugin.json')
        $knowledgeManifest = Read-CompanyAgentJson -Path (Join-Path $repoRoot 'corporate-knowledge\pack.json')
        if ([string]::IsNullOrWhiteSpace($BundleZip)) {
            $BundleZip = Join-Path $testRoot 'bundle.zip'
            $null = & (Join-Path $PSScriptRoot 'New-OfflineBundle.ps1') -SourceRoot $repoRoot -CoreVersion ([string]$pluginManifest.version) -KnowledgeVersion ([string]$knowledgeManifest.version) -OutputPath $BundleZip -IncludeBundledPython:$IncludeBundledPython -SkipSourceValidation:(-not $IncludeBundledPython)
        }
        $BundleRoot = Join-Path $testRoot 'bundle'
        Expand-Archive -LiteralPath $bundleZip -DestinationPath $BundleRoot
    }
    if ($LegacyEncoding) {
        $env:PYTHONIOENCODING = 'cp949:strict'
        $env:PYTHONUTF8 = '0'
        [Console]::OutputEncoding = [Text.Encoding]::GetEncoding(949)
        $OutputEncoding = [Text.Encoding]::GetEncoding(949)
    }
    $unicodeLabel = [string][char]0xD55C + [char]0xAE00 + [char]0x2014 + [char]::ConvertFromUtf32(0x1F680)
    $profileRoot = Join-Path $testRoot ('profile ' + $unicodeLabel)
    $localAppData = Join-Path $profileRoot 'AppData\Local'
    $configRoot = Join-Path $profileRoot '.claude'
    $projectRoot = Join-Path $testRoot ('My project ' + $unicodeLabel)
    $otherProject = Join-Path $testRoot ('Other project ' + $unicodeLabel)
    $customStateRoot = Join-Path $testRoot ('Personal state ' + $unicodeLabel)
    $failedProject = Join-Path $testRoot 'Failed project'
    foreach ($path in @($localAppData, $configRoot, $projectRoot, $otherProject, $failedProject)) { New-CompanyAgentDirectory -Path $path }
    $env:CLAUDE_CONFIG_DIR = $configRoot
    $env:CLAUDE_CODE_SUBAGENT_MODEL = $null
    $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE = $null
    Write-CompanyAgentJsonAtomic -Path (Join-Path $configRoot 'settings.json') -Value ([pscustomobject]@{
        env = [pscustomobject]@{ API_TOKEN = 'fixture-not-a-real-secret'; ANTHROPIC_DEFAULT_HAIKU_MODEL = 'already-configured-small' }
        enabledPlugins = [pscustomobject]@{ 'unrelated@fixture' = $true }
    })
    Write-CompanyAgentUtf8File -Path (Join-Path $configRoot 'skills\existing-skill\SKILL.md') -Content 'Existing skill must survive.'
    Write-CompanyAgentUtf8File -Path (Join-Path $configRoot 'skills\unicode-fixture\SKILL.md') -Content ("---`nname: unicode-fixture`ndescription: $unicodeLabel`n---`nUnicode metadata must roundtrip.")
    Write-CompanyAgentUtf8File -Path (Join-Path $configRoot '.credentials.json') -Content '{"fixture":"do-not-copy"}'
    $settingsLocalPath = Join-Path $projectRoot '.claude\settings.local.json'
    Write-CompanyAgentJsonAtomic -Path $settingsLocalPath -Value ([pscustomobject]@{ permissions = [pscustomobject]@{ allow = @('Read') } })
    $common = @{
        BundleRoot = $BundleRoot; ClaudeConfigRoot = $configRoot; InvokingUserProfile = $profileRoot
        InvokingLocalAppData = $localAppData; ClaudeCommand = $ClaudeCommand; PythonCommand = $PythonCommand
        NonInteractive = $true; SkipAdminCheck = $true
        ExistingHarnessAction = 'Replace'
    }
    $setup = Join-Path $BundleRoot 'deploy\Setup-CompanyAgent.ps1'
    $scopeRequested = $false
    try {
        $needsScope = & $setup @common
        $scopeRequested = $needsScope.status -eq 'input-required' -and $needsScope.input -eq 'Scope'
    }
    catch {
        if ($_.Exception.Message -notmatch '(?i)Choose (the )?installation scope') { throw }
        $scopeRequested = $true
    }
    Assert-ScopedSmoke $scopeRequested 'Noninteractive setup silently chose a scope instead of requesting it'
    Assert-ScopedSmoke (-not (Test-Path -LiteralPath (Join-Path $localAppData 'CompanyAgent-Distribution'))) 'Missing-scope response changed the distribution'
    $junctionProject = Join-Path $testRoot 'Junction project'
    $externalClaude = Join-Path $testRoot 'External Claude sentinel'
    New-CompanyAgentDirectory -Path $junctionProject
    Write-CompanyAgentJsonAtomic -Path (Join-Path $externalClaude 'settings.local.json') -Value ([pscustomobject]@{ sentinel = 'external-settings-must-not-change' })
    $externalBefore = @(Get-CompanyAgentTreeRecords -Root $externalClaude | ConvertTo-Json -Depth 10 -Compress) -join ''
    $junctionPath = Join-Path $junctionProject '.claude'
    New-Item -ItemType Junction -Path $junctionPath -Value $externalClaude | Out-Null
    try {
        $junctionBlocked = $false
        try { $null = & $setup @common -Scope Project -ProjectRoot $junctionProject }
        catch {
            if ($_.Exception.Message -notmatch '(?i)(junction|reparse|symbolic link)') { throw }
            $junctionBlocked = $true
        }
        Assert-ScopedSmoke $junctionBlocked 'Project .claude junction was not rejected before registration'
        $externalAfter = @(Get-CompanyAgentTreeRecords -Root $externalClaude | ConvertTo-Json -Depth 10 -Compress) -join ''
        Assert-ScopedSmoke ($externalBefore -ceq $externalAfter) 'Project .claude junction modified external sentinel contents'
        Assert-ScopedSmoke (-not (Test-Path -LiteralPath (Join-Path $localAppData 'CompanyAgent-Distribution'))) 'Junction rejection occurred after changing distribution'
    }
    finally {
        # Delete only the verified junction itself, never traverse its target.
        $junctionItem = Get-Item -LiteralPath $junctionPath -Force -ErrorAction SilentlyContinue
        if ($null -ne $junctionItem) {
            $expectedJunction = [IO.Path]::GetFullPath((Join-Path $junctionProject '.claude'))
            if ($junctionItem.FullName -ine $expectedJunction -or ($junctionItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) { throw 'Unsafe junction fixture cleanup target.' }
            [IO.Directory]::Delete($junctionItem.FullName)
        }
    }
    Assert-ScopedSmoke (Test-Path -LiteralPath (Join-Path $externalClaude 'settings.local.json')) 'Junction cleanup removed its target'
    $userInstruction = Join-Path $configRoot 'CLAUDE.md'
    $userRule = Join-Path $configRoot 'rules\old-guidance.md'
    Write-CompanyAgentUtf8File -Path $userInstruction -Content 'Previous user harness instructions.'
    Write-CompanyAgentUtf8File -Path $userRule -Content 'Previous user harness rule.'
    $userBeforeSettings = Read-CompanyAgentJson -Path (Join-Path $configRoot 'settings.json')
    $oldHooks = [pscustomobject]@{ SessionStart = @([pscustomobject]@{ hooks = @([pscustomobject]@{ type = 'command'; command = 'echo PREVIOUS_HARNESS_FIXTURE' }) }) }
    $userBeforeSettings | Add-Member -MemberType NoteProperty -Name hooks -Value $oldHooks
    Write-CompanyAgentJsonAtomic -Path (Join-Path $configRoot 'settings.json') -Value $userBeforeSettings
    $userBeforeChoice = @(Get-CompanyAgentTreeRecords -Root $configRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    $askCommon = $common.Clone()
    $askCommon.ExistingHarnessAction = 'Ask'
    foreach ($previewOnly in @($true, $false)) {
        $choiceResult = & $setup @askCommon -Scope User -DryRun:$previewOnly
        Assert-ScopedSmoke ($choiceResult.status -eq 'input-required' -and $choiceResult.input -eq 'ExistingHarnessAction') 'Existing harness silently selected replacement in unattended setup'
    }
    $keepCommon = $common.Clone()
    $keepCommon.ExistingHarnessAction = 'Keep'
    $keptUser = & $setup @keepCommon -Scope User
    Assert-ScopedSmoke ($keptUser.status -eq 'kept' -and -not $keptUser.changed) 'Keep did not skip installation'
    Assert-ScopedSmoke ((@(Get-CompanyAgentTreeRecords -Root $configRoot | ConvertTo-Json -Depth 10 -Compress) -join '') -ceq $userBeforeChoice) 'Ask/Keep changed previous harness contents'
    Assert-ScopedSmoke (-not (Test-Path -LiteralPath (Join-Path $localAppData 'CompanyAgent-Backups'))) 'Ask/Keep created a backup despite no installation'
    Assert-ScopedSmoke (-not (Test-Path -LiteralPath (Join-Path $localAppData 'CompanyAgent-Distribution'))) 'Ask/Keep created distribution'
    $userSettingsPath = Join-Path $configRoot 'settings.json'
    $userSettingsContent = Get-Content -LiteralPath $userSettingsPath -Raw -Encoding UTF8
    $unsafeSettingsContent = '{"unsafeNumericIdentifier":9007199254740993,' + $userSettingsContent.TrimStart().Substring(1)
    Write-CompanyAgentUtf8File -Path $userSettingsPath -Content $unsafeSettingsContent
    $unsafeSettingsHash = (Get-FileHash -LiteralPath $userSettingsPath -Algorithm SHA256).Hash
    $unsafeIntegerBlocked = $false
    try {
        try {
            $unsafeResult = & $setup @common -Scope User
            if ($null -ne $unsafeResult -and $unsafeResult.status -eq 'input-required') {
                throw ("Scoped smoke fixture still needs '{0}' before the settings safety check. Resolve that prerequisite; no native registration was attempted." -f $unsafeResult.input)
            }
        }
        catch {
            if ($_.Exception.Message -notmatch '(?i)(integer|numeric|precision)') { throw }
            $unsafeIntegerBlocked = $true
        }
        Assert-ScopedSmoke $unsafeIntegerBlocked 'Native JSON registration could round an unsupported integer'
        Assert-ScopedSmoke ((Get-FileHash -LiteralPath $userSettingsPath -Algorithm SHA256).Hash -ceq $unsafeSettingsHash) 'Unsafe integer rejection modified original settings'
        Assert-ScopedSmoke ((Test-Path -LiteralPath $userInstruction) -and -not (Test-Path -LiteralPath (Join-Path $localAppData 'CompanyAgent-Backups'))) 'Unsafe integer rejection occurred after replacement or backup'
    }
    finally { Write-CompanyAgentUtf8File -Path $userSettingsPath -Content $userSettingsContent }
    $preview = & $setup @common -Scope User -DryRun
    Assert-ScopedSmoke ($preview.status -eq 'dry-run' -and -not $preview.needsElevation) 'User dry-run should be read-only without UAC'
    Assert-ScopedSmoke (-not (Test-Path -LiteralPath (Join-Path $localAppData 'CompanyAgent-Distribution'))) 'Dry-run created distribution'
    if ($IncludeBundledPython) { Assert-ScopedSmoke ($preview.pythonCommand -like '*\runtime\python\python.exe') 'Full package did not choose its embedded Python' }
    else {
        Assert-ScopedSmoke ([IO.Path]::IsPathRooted($preview.pythonCommand) -and [IO.Path]::GetFileName($preview.pythonCommand) -ine 'py.exe') 'External Python must be the validated absolute interpreter, not a launcher'
        Assert-ScopedSmoke (-not (Test-Path -LiteralPath (Join-Path $BundleRoot 'payload\core\plugin\runtime\python'))) 'Default package contains a Python runtime'
    }
    $user = & $setup @common -Scope User
    Assert-ScopedSmoke ($user.status -eq 'installed' -and $user.nativeClaudeScope -eq 'user') 'User installation failed'
    Assert-ScopedSmoke ($user.previousHarnessDeactivated -and -not (Test-Path -LiteralPath $userInstruction) -and -not (Test-Path -LiteralPath $userRule)) 'Replace did not deactivate old user instructions'
    Assert-ScopedSmoke (Test-Path -LiteralPath (Join-Path $user.safetyBackup 'previous-harness')) 'Replace has no encrypted recovery snapshot'
    Assert-ScopedSmoke (Test-Path -LiteralPath (Join-Path $user.safetyBackup 'claude-config\rules\old-guidance.md')) 'Selective backup omitted rules'
    $userRecord = Read-CompanyAgentJson -Path $user.registrationPath
    Assert-ScopedSmoke (Test-Path -LiteralPath $userRecord.managedConfigPath -PathType Leaf) 'Registered company policy file is absent'
    $installedStandards = (Read-CompanyAgentJson -Path $userRecord.managedConfigPath).workStandards
    Assert-ScopedSmoke ($installedStandards.revision -eq '1') 'Company standards were dropped during scoped installation'
    Assert-ScopedSmoke ($userRecord.userStateRoot -eq (Join-Path $localAppData 'CompanyAgent\states\user')) 'Default User state path changed'
    Assert-ScopedSmoke ($userRecord.claudeConfigDirOverride -eq $true -and $userRecord.claudeConfigRoot -eq $configRoot) 'Explicit isolated Claude configuration was not recorded as an override'
    $otherConfigRoot = Join-Path $profileRoot 'other-claude-config'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $otherConfigRoot 'settings.json') -Value ([pscustomobject]@{ sentinel = 'second-profile-must-not-change' })
    $otherConfigBefore = @(Get-CompanyAgentTreeRecords -Root $otherConfigRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    $registrationBefore = (Get-FileHash -LiteralPath $user.registrationPath -Algorithm SHA256).Hash
    $originalConfigBefore = @(Get-CompanyAgentTreeRecords -Root $configRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    $otherConfigArgs = $common.Clone()
    $otherConfigArgs.ClaudeConfigRoot = $otherConfigRoot
    $otherConfigBlocked = $false
    try { $null = & $setup @otherConfigArgs -Scope User }
    catch {
        if ($_.Exception.Message -notmatch '(?i)(configuration|config root|profile|config directory)') { throw }
        $otherConfigBlocked = $true
    }
    Assert-ScopedSmoke $otherConfigBlocked 'Shared distribution allowed a different Claude configuration to replace its User scope'
    $otherConfigAfter = @(Get-CompanyAgentTreeRecords -Root $otherConfigRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    $originalConfigAfter = @(Get-CompanyAgentTreeRecords -Root $configRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    Assert-ScopedSmoke ($otherConfigBefore -ceq $otherConfigAfter -and $originalConfigBefore -ceq $originalConfigAfter) 'Rejected alternate configuration changed either profile'
    Assert-ScopedSmoke ((Get-FileHash -LiteralPath $user.registrationPath -Algorithm SHA256).Hash -ceq $registrationBefore) 'Rejected alternate configuration replaced the existing scope registration'
    $settings = Read-CompanyAgentJson -Path (Join-Path $configRoot 'settings.json')
    Assert-ScopedSmoke ($settings.env.ANTHROPIC_DEFAULT_HAIKU_MODEL -eq 'already-configured-small') 'Model setting changed'
    Assert-ScopedSmoke ($settings.enabledPlugins.'unrelated@fixture' -eq $true) 'Other plugin disabled'
    Assert-ScopedSmoke ($settings.env.API_TOKEN -eq 'fixture-not-a-real-secret') 'Replace removed a model/auth configuration value'
    Assert-ScopedSmoke ($null -eq $settings.PSObject.Properties['hooks']) 'Old user hooks are still active after replacement'
    Assert-ScopedSmoke ((Get-Content -LiteralPath (Join-Path $configRoot 'skills\existing-skill\SKILL.md') -Raw) -like 'Existing skill*') 'Existing skill changed'
    $backup = Read-CompanyAgentJson -Path (Join-Path $user.safetyBackup 'claude-config\settings.json')
    Assert-ScopedSmoke ($backup.env.API_TOKEN -eq '[REDACTED_BY_COMPANY_AGENT_BACKUP]') 'Backup secret redaction failed'
    Assert-ScopedSmoke (-not (Test-Path -LiteralPath (Join-Path $user.safetyBackup 'claude-config\.credentials.json'))) 'Backup copied credentials'
    # A busy source makes the safety backup fail before any old rule is removed
    # or any Company Agent project registration is added.
    $lockedProject = Join-Path $testRoot 'Backup failure project'
    $lockedInstruction = Join-Path $lockedProject 'CLAUDE.md'
    Write-CompanyAgentUtf8File -Path $lockedInstruction -Content 'Busy previous harness must remain unchanged.'
    $lockedBefore = (Get-FileHash -LiteralPath $lockedInstruction -Algorithm SHA256).Hash
    $configBeforeBusyBackup = @(Get-CompanyAgentTreeRecords -Root $configRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    $busyHandle = [IO.File]::Open($lockedInstruction, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::Read)
    $busyBackupBlocked = $false
    try {
        try { $null = & $setup @common -Scope Project -ProjectRoot $lockedProject }
        catch { $busyBackupBlocked = $true }
    }
    finally { $busyHandle.Dispose() }
    Assert-ScopedSmoke $busyBackupBlocked 'Unreadable backup source did not block installation'
    Assert-ScopedSmoke ((Get-FileHash -LiteralPath $lockedInstruction -Algorithm SHA256).Hash -ceq $lockedBefore) 'Backup failure modified old instructions'
    Assert-ScopedSmoke (-not (Test-Path -LiteralPath (Join-Path $lockedProject '.claude\settings.local.json'))) 'Backup failure registered the new plugin'
    Assert-ScopedSmoke ((@(Get-CompanyAgentTreeRecords -Root $configRoot | ConvertTo-Json -Depth 10 -Compress) -join '') -ceq $configBeforeBusyBackup) 'Backup failure changed unrelated user settings'
    $projectInstruction = Join-Path $projectRoot 'CLAUDE.md'
    Write-CompanyAgentUtf8File -Path $projectInstruction -Content 'Old project harness must be backed up before replacement.'
    $project = & $setup @common -Scope Project -ProjectRoot $projectRoot
    Assert-ScopedSmoke (-not (Test-Path -LiteralPath $projectInstruction)) 'Project root instructions were not deactivated'
    Assert-ScopedSmoke (Test-Path -LiteralPath (Join-Path $project.safetyBackup 'project-root\CLAUDE.md')) 'Project root instructions were not backed up'
    $project2 = & $setup @common -Scope Project -ProjectRoot $otherProject -UserStateRoot $customStateRoot
    Assert-ScopedSmoke ($project.nativeClaudeScope -eq 'local') 'Project must use local settings scope'
    Assert-ScopedSmoke ($project.userStateRoot -ne $user.userStateRoot -and $project.userStateRoot -ne $project2.userStateRoot) 'Per-scope state was shared'
    Assert-ScopedSmoke (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.claude\settings.json'))) 'Project installed shared tracked settings'
    $projectSettings = Read-CompanyAgentJson -Path $settingsLocalPath
    Assert-ScopedSmoke ($projectSettings.permissions.allow -contains 'Read') 'Existing project permissions changed'
    $inventory = Read-CompanyAgentJson -Path (Join-Path $configRoot 'plugins\installed_plugins.json')
    $entries = @($inventory.plugins.'company-agent@company-agent-local')
    Assert-ScopedSmoke ($entries.Count -eq 3) 'User plus two Project registrations should coexist as one plugin identity'
    $reapplyCommon = $common.Clone()
    $reapplyCommon.ExistingHarnessAction = 'Update'
    Write-CompanyAgentUtf8File -Path $projectInstruction -Content 'New personal project instruction; preserve on Company Agent update.'
    $reapplyInstructionHash = (Get-FileHash -LiteralPath $projectInstruction -Algorithm SHA256).Hash
    $again = & $setup @reapplyCommon -Scope Project -ProjectRoot $projectRoot
    Assert-ScopedSmoke ($again.status -eq 'reapplied' -and $again.operation -eq 'reapply') 'Repeat installation was not distinguished from a new installation'
    Assert-ScopedSmoke (-not $again.previousHarnessDeactivated -and $again.existingHarnessAction -eq 'Update') 'Reapply incorrectly selected harness replacement'
    Assert-ScopedSmoke ((Get-FileHash -LiteralPath $projectInstruction -Algorithm SHA256).Hash -ceq $reapplyInstructionHash) 'Reapply removed a new personal instruction'
    $receipt = Read-CompanyAgentJson -Path $project.registrationPath
    Assert-ScopedSmoke ($receipt.projectRoot -eq $projectRoot -and $receipt.scope -eq 'Project') 'Project registry contract mismatch'
    Assert-ScopedSmoke ($receipt.claudeConfigDirOverride -eq $true) 'Project registration lost the explicit Claude config override'
    Assert-ScopedSmoke ($again.userStateRoot -eq $project.userStateRoot) 'Default Project state path changed on repeat installation'

    # A personal state path chosen at first install must remain authoritative
    # when the next installation omits the advanced parameter.
    $latestMemoryPath = Join-Path $customStateRoot 'memory\items\latest-preference.md'
    Write-CompanyAgentUtf8File -Path $latestMemoryPath -Content 'First saved preference.'
    Write-CompanyAgentUtf8File -Path (Join-Path $customStateRoot 'knowledge\entries\local-term.md') -Content 'Personal term definition.'
    Write-CompanyAgentUtf8File -Path (Join-Path $customStateRoot 'personal-root\.claude\skills\personal-example\SKILL.md') -Content 'Personal skill must survive.'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $customStateRoot 'config\learning.json') -Value @{ schemaVersion = 1; enabled = $false }
    Write-CompanyAgentJsonAtomic -Path (Join-Path $customStateRoot 'learning\state.json') -Value @{ schemaVersion = 1; preservationFixture = 'Local learning observations and rollback journal must survive.' }
    Write-CompanyAgentUtf8File -Path (Join-Path $customStateRoot 'handoffs\fixture\handoff.md') -Content 'Unfinished work note must survive.'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $customStateRoot 'setup-helpers\fixture\answers.json') -Value @{ style = 'summary' }
    # Save a real project-specific candidate through the packaged CLI. The ID
    # must survive repeated installation and a new version/cache directory.
    $skillPluginRoot = Join-Path $BundleRoot 'payload\core\plugin'
    $skillCli = Join-Path $skillPluginRoot 'scripts\harness_cli.py'
    $skillArgs = @('--state-root', $customStateRoot, '--project-root', $otherProject,
        '--claude-root', $configRoot, '--plugin-root', $skillPluginRoot,
        '--base', (Join-Path $BundleRoot 'payload\knowledge'))
    $skillInventoryRaw = & $PythonCommand -B $skillCli skill inventory @skillArgs
    Assert-ScopedSmoke ($LASTEXITCODE -eq 0) 'Packaged Skill inventory failed'
    $skillInventory = ($skillInventoryRaw -join [Environment]::NewLine) | ConvertFrom-Json
    $preferredSkill = @($skillInventory.skills | Where-Object { $_.source -eq 'company' -and $_.name -eq 'karpathy-guidelines' })
    Assert-ScopedSmoke ($skillInventory.complete -and $preferredSkill.Count -eq 1) 'Packaged Company Skill was not discovered unambiguously'
    $null = & $PythonCommand -B $skillCli skill prefer --name karpathy-guidelines --candidate $preferredSkill[0].id --scope project @skillArgs
    Assert-ScopedSmoke ($LASTEXITCODE -eq 0) 'Project Skill preference could not be saved'
    Write-CompanyAgentUtf8File -Path $latestMemoryPath -Content 'Latest saved preference, amended after installation.'
    $customStateBefore = @(Get-CompanyAgentTreeRecords -Root $customStateRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    $customRepeat = & $setup @common -Scope Project -ProjectRoot $otherProject
    Assert-ScopedSmoke ($customRepeat.userStateRoot -ieq $customStateRoot) 'Omitted UserStateRoot disconnected the custom state'
    Assert-ScopedSmoke ((Read-CompanyAgentJson -Path $customRepeat.registrationPath).userStateRoot -ieq $customStateRoot) 'Custom state was not retained in the registration'
    $customSame = & $setup @common -Scope Project -ProjectRoot $otherProject -UserStateRoot ($customStateRoot + '\.\')
    Assert-ScopedSmoke ($customSame.userStateRoot -ieq $customStateRoot) 'Explicit equivalent state path was rejected or changed'
    Assert-ScopedSmoke ((@(Get-CompanyAgentTreeRecords -Root $customStateRoot | ConvertTo-Json -Depth 10 -Compress) -join '') -ceq $customStateBefore) 'Repeat installation changed the latest memory, personal knowledge, or Skill'

    $registrationBeforeConflict = (Get-FileHash -LiteralPath $project2.registrationPath -Algorithm SHA256).Hash
    $configBeforeConflict = @(Get-CompanyAgentTreeRecords -Root $configRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    $backupsBeforeConflict = @(Get-ChildItem -LiteralPath (Join-Path $localAppData 'CompanyAgent-Backups') -Directory).Count
    $differentStateRoot = Join-Path $testRoot 'Must not create a different personal state'
    $differentStateBlocked = $false
    try { $null = & $setup @common -Scope Project -ProjectRoot $otherProject -UserStateRoot $differentStateRoot }
    catch {
        if ($_.Exception.Message -notmatch '(?i)(already uses UserStateRoot|separate explicit migration)') { throw }
        $differentStateBlocked = $true
    }
    Assert-ScopedSmoke $differentStateBlocked 'A conflicting explicit state root silently moved the registration'
    Assert-ScopedSmoke (-not (Test-Path -LiteralPath $differentStateRoot)) 'Conflicting state override created a new state directory'
    Assert-ScopedSmoke ((Get-FileHash -LiteralPath $project2.registrationPath -Algorithm SHA256).Hash -ceq $registrationBeforeConflict) 'Conflicting state override changed the registration'
    Assert-ScopedSmoke ((@(Get-CompanyAgentTreeRecords -Root $configRoot | ConvertTo-Json -Depth 10 -Compress) -join '') -ceq $configBeforeConflict) 'Conflicting state override changed Claude settings'
    Assert-ScopedSmoke ((@(Get-CompanyAgentTreeRecords -Root $customStateRoot | ConvertTo-Json -Depth 10 -Compress) -join '') -ceq $customStateBefore) 'Conflicting state override changed personal data'
    Assert-ScopedSmoke (@(Get-ChildItem -LiteralPath (Join-Path $localAppData 'CompanyAgent-Backups') -Directory).Count -eq $backupsBeforeConflict) 'Conflicting state override created a backup before rejecting it'

    $savedCustomRegistration = Read-CompanyAgentJson -Path $project2.registrationPath
    try {
        foreach ($invalidRecordedState in @('relative-personal-state', $configRoot, '\\fixture.invalid\share\state', [IO.Path]::GetPathRoot($testRoot))) {
            $invalidRegistration = Read-CompanyAgentJson -Path $project2.registrationPath
            $invalidRegistration.userStateRoot = $invalidRecordedState
            Write-CompanyAgentJsonAtomic -Path $project2.registrationPath -Value $invalidRegistration
            $invalidRegistrationBefore = (Get-FileHash -LiteralPath $project2.registrationPath -Algorithm SHA256).Hash
            $invalidRecordBlocked = $false
            try { $null = & $setup @common -Scope Project -ProjectRoot $otherProject -DryRun }
            catch {
                if ($_.Exception.Message -notmatch '(?i)(valid absolute UserStateRoot|UserStateRoot must be separate|dedicated folder on this local PC)') { throw }
                $invalidRecordBlocked = $true
            }
            Assert-ScopedSmoke $invalidRecordBlocked 'An invalid or overlapping recorded state path was accepted'
            Assert-ScopedSmoke ((Get-FileHash -LiteralPath $project2.registrationPath -Algorithm SHA256).Hash -ceq $invalidRegistrationBefore) 'Invalid state preflight rewrote the registration'
        }
    }
    finally { Write-CompanyAgentJsonAtomic -Path $project2.registrationPath -Value $savedCustomRegistration }

    foreach ($invalidIdentity in @(@{ key = 'pluginId'; value = 'not-company@other' }, @{ key = 'coreVersion'; value = "bad`nversion" })) {
        try {
            $invalidRegistration = Read-CompanyAgentJson -Path $project2.registrationPath
            $invalidRegistration.($invalidIdentity.key) = $invalidIdentity.value
            Write-CompanyAgentJsonAtomic -Path $project2.registrationPath -Value $invalidRegistration
            $invalidBefore = (Get-FileHash -LiteralPath $project2.registrationPath -Algorithm SHA256).Hash
            $identityBlocked = $false
            try { $null = & $setup @reapplyCommon -Scope Project -ProjectRoot $otherProject -DryRun }
            catch { if ($_.Exception.Message -notmatch 'does not identify a supported Company Agent') { throw }; $identityBlocked = $true }
            Assert-ScopedSmoke $identityBlocked 'Unrecognized plugin identity/version was offered as an owned update'
            Assert-ScopedSmoke ((Get-FileHash -LiteralPath $project2.registrationPath -Algorithm SHA256).Hash -ceq $invalidBefore) 'Rejected identity changed the registration'
        }
        finally { Write-CompanyAgentJsonAtomic -Path $project2.registrationPath -Value $savedCustomRegistration }
    }

    $futureMarker = Join-Path $customStateRoot 'state-format.json'
    Write-CompanyAgentJsonAtomic -Path $futureMarker -Value ([pscustomobject]@{ schemaVersion = 999 })
    $futureStateBefore = @(Get-CompanyAgentTreeRecords -Root $customStateRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    $futureRegistrationBefore = (Get-FileHash -LiteralPath $project2.registrationPath -Algorithm SHA256).Hash
    try {
        $futureStateBlocked = $false
        try { $null = & $setup @common -Scope Project -ProjectRoot $otherProject }
        catch {
            if ($_.Exception.Message -notmatch '(?i)cannot read the existing personal state') { throw }
            $futureStateBlocked = $true
        }
        Assert-ScopedSmoke $futureStateBlocked 'An unsupported future state format was accepted'
        Assert-ScopedSmoke ((@(Get-CompanyAgentTreeRecords -Root $customStateRoot | ConvertTo-Json -Depth 10 -Compress) -join '') -ceq $futureStateBefore) 'Future state rejection changed personal data'
        Assert-ScopedSmoke ((Get-FileHash -LiteralPath $project2.registrationPath -Algorithm SHA256).Hash -ceq $futureRegistrationBefore) 'Future state rejection changed registration'
        Assert-ScopedSmoke (@(Get-ChildItem -LiteralPath (Join-Path $localAppData 'CompanyAgent-Backups') -Directory).Count -eq $backupsBeforeConflict) 'State-format rejection occurred after creating a backup'
    }
    finally { Remove-Item -LiteralPath $futureMarker -Force }
    $beforeEntries = (Read-CompanyAgentJson -Path (Join-Path $configRoot 'plugins\installed_plugins.json')).plugins.'company-agent@company-agent-local' | ConvertTo-Json -Depth 30 -Compress
    $claudeInfo = Get-Command $ClaudeCommand | Select-Object -First 1
    $claudeExecutable = $claudeInfo.Source
    if (-not $claudeExecutable) { $claudeExecutable = $claudeInfo.Definition }
    $failureWrapper = Join-Path $testRoot 'claude-fail-update.ps1'
    $wrapperText = 'if ($args.Count -ge 2 -and $args[0] -eq ''plugin'' -and $args[1] -eq ''update'') { Write-Output ''SCOPED_SMOKE_INJECTED_UPDATE_FAILURE''; exit 47 }' + "`r`n"
    $wrapperText += '& ''' + $claudeExecutable.Replace("'", "''") + ''' @args' + "`r`n" + 'exit $LASTEXITCODE' + "`r`n"
    Write-CompanyAgentUtf8File -Path $failureWrapper -Content $wrapperText
    $failureCommon = $common.Clone()
    $failureCommon.ClaudeCommand = $failureWrapper
    $failedInstruction = Join-Path $failedProject 'CLAUDE.md'
    $failureSettings = Join-Path $failedProject '.claude\settings.local.json'
    Write-CompanyAgentUtf8File -Path $failedInstruction -Content 'Restore this previous harness when installation fails.'
    $failedInstructionHash = (Get-FileHash -LiteralPath $failedInstruction -Algorithm SHA256).Hash
    $deepProvider = '{"leaf":"deep-provider-setting-preserved","largeInteger":9007199254740991}'
    for ($level = 0; $level -lt 28; $level++) { $deepProvider = '{"nested":' + $deepProvider + '}' }
    $failureJsonText = '{"hooks":' + ($oldHooks | ConvertTo-Json -Depth 12 -Compress) + ',"env":{"API_TOKEN":"rollback-fixture-not-real"},"permissions":{"allow":["Read"]},"customProvider":' + $deepProvider + '}'
    Write-CompanyAgentUtf8File -Path $failureSettings -Content $failureJsonText
    $didFail = $false
    try { $null = & $setup @failureCommon -Scope Project -ProjectRoot $failedProject }
    catch {
        if ($_.Exception.Message -notlike '*SCOPED_SMOKE_INJECTED_UPDATE_FAILURE*') { throw }
        $didFail = $true
    }
    Assert-ScopedSmoke $didFail 'Injected plugin update failure was ignored'
    Assert-ScopedSmoke ((Get-FileHash -LiteralPath $failedInstruction -Algorithm SHA256).Hash -ceq $failedInstructionHash) 'Failed install did not restore previous instruction bytes'
    $restoredFailureSettings = Read-CompanyAgentJson -Path $failureSettings
    Assert-ScopedSmoke ($restoredFailureSettings.hooks.SessionStart[0].hooks[0].command -eq 'echo PREVIOUS_HARNESS_FIXTURE') 'Failed install did not restore old hooks'
    Assert-ScopedSmoke ($restoredFailureSettings.env.API_TOKEN -eq 'rollback-fixture-not-real' -and $restoredFailureSettings.permissions.allow -contains 'Read') 'Failed install damaged unrelated settings'
    $restoredProvider = $restoredFailureSettings.customProvider
    for ($level = 0; $level -lt 28; $level++) { $restoredProvider = $restoredProvider.nested }
    Assert-ScopedSmoke ($restoredProvider.leaf -eq 'deep-provider-setting-preserved') 'Rollback truncated deeply nested unrelated settings'
    Assert-ScopedSmoke ((Get-Content -LiteralPath $failureSettings -Raw) -match '9007199254740991') 'Rollback changed a large safe unrelated JSON integer'
    $afterEntries = (Read-CompanyAgentJson -Path (Join-Path $configRoot 'plugins\installed_plugins.json')).plugins.'company-agent@company-agent-local' | ConvertTo-Json -Depth 30 -Compress
    Assert-ScopedSmoke ($beforeEntries -ceq $afterEntries) 'Failure rollback changed existing user/project plugin registrations'
    $failureSettings = Join-Path $failedProject '.claude\settings.local.json'
    if (Test-Path -LiteralPath $failureSettings) {
        $failureJson = Read-CompanyAgentJson -Path $failureSettings
        $enabledProperty = $failureJson.PSObject.Properties['enabledPlugins']
        Assert-ScopedSmoke ($null -eq $enabledProperty -or $null -eq $enabledProperty.Value.PSObject.Properties['company-agent@company-agent-local']) 'Failed project remained enabled'
    }
    Write-CompanyAgentUtf8File -Path (Join-Path $project.userStateRoot 'memory\must-survive.md') -Content 'preserved personal memory'
    $uninstallArgs = $common.Clone()
    $uninstallArgs.Remove('BundleRoot')
    $uninstallArgs.Remove('PythonCommand')
    $uninstallArgs.Remove('ExistingHarnessAction')
    $removed = & (Join-Path $BundleRoot 'deploy\Uninstall-ScopedCompanyAgent.ps1') @uninstallArgs -Scope Project -ProjectRoot $projectRoot
    Assert-ScopedSmoke ($removed.status -eq 'uninstalled') 'Scoped uninstall failed'
    Assert-ScopedSmoke (-not (Test-Path -LiteralPath $project.registrationPath)) 'Scoped uninstall left active Project registry'
    Assert-ScopedSmoke (Test-Path -LiteralPath (Join-Path $project.userStateRoot 'memory\must-survive.md')) 'Scoped uninstall removed personal state'
    $remaining = @((Read-CompanyAgentJson -Path (Join-Path $configRoot 'plugins\installed_plugins.json')).plugins.'company-agent@company-agent-local')
    Assert-ScopedSmoke ($remaining.Count -eq 2) 'Project uninstall affected another scope'
    $reinstalled = & $setup @common -Scope Project -ProjectRoot $projectRoot
    Assert-ScopedSmoke ($reinstalled.userStateRoot -eq $project.userStateRoot -and (Test-Path -LiteralPath (Join-Path $project.userStateRoot 'memory\must-survive.md'))) 'Reinstall did not resume existing personal state'
    foreach ($initialization in @(
        [pscustomobject]@{ scope = 'Project'; cwd = $projectRoot; state = $project.userStateRoot },
        [pscustomobject]@{ scope = 'User'; cwd = $testRoot; state = $user.userStateRoot }
    )) {
        $debugFile = Join-Path $testRoot ('init-' + $initialization.scope + '.log')
        Push-Location -LiteralPath $initialization.cwd
        try {
            $initOutput = & $ClaudeCommand --init-only --debug-file $debugFile 2>&1
            if ($LASTEXITCODE -ne 0) { throw ('Claude initialization failed: ' + ($initOutput -join [Environment]::NewLine)) }
        }
        finally { Pop-Location }
        $debugText = Get-Content -LiteralPath $debugFile -Raw -Encoding UTF8
        Assert-ScopedSmoke ($debugText -match 'Registered [0-9]+ hooks from 1 plugins') 'Native User plus Project loaded duplicate plugin hook chains'
        Assert-ScopedSmoke ([regex]::Matches($debugText, 'Hook SessionStart:startup \(SessionStart\) success').Count -eq 1) 'Expected exactly one successful SessionStart hook'
        $responseLines = @(Get-Content -LiteralPath $debugFile -Encoding UTF8 | Where-Object { $_ -like '*Hooks: Parsed initial response:*' })
        $response = ($responseLines[0] -replace '^.*Hooks: Parsed initial response: ', '') | ConvertFrom-Json
        $runtime = ($response.hookSpecificOutput.additionalContext | ConvertFrom-Json).company_agent_runtime
        Assert-ScopedSmoke ($runtime.scope -eq $initialization.scope -and $runtime.stateRoot -eq $initialization.state) 'Native SessionStart selected the wrong personal scope'
        Assert-ScopedSmoke (Test-Path -LiteralPath (Join-Path $initialization.state 'config\user.json')) 'Native SessionStart did not initialize personal state'
    }
    $null = & (Join-Path $BundleRoot 'deploy\Uninstall-ScopedCompanyAgent.ps1') @uninstallArgs -Scope User
    $outsideDebug = Join-Path $testRoot 'init-project-only-outside.log'
    Push-Location -LiteralPath $testRoot
    try {
        $outsideOutput = & $ClaudeCommand --init-only --debug-file $outsideDebug 2>&1
        if ($LASTEXITCODE -ne 0) { throw ('Outside-project initialization failed: ' + ($outsideOutput -join [Environment]::NewLine)) }
    }
    finally { Pop-Location }
    Assert-ScopedSmoke ((Get-Content -LiteralPath $outsideDebug -Raw -Encoding UTF8) -notmatch 'company_agent_runtime') 'Project-only installation activated outside its projects'
    $null = & $setup @common -Scope User

    # Build a distinct-version fixture entirely within the test directory.
    # This tests actual Claude update registration without changing the release
    # version or payload in the checkout, distribution ZIP, or user profile.
    $updateBundleRoot = Join-Path $testRoot 'new-version-bundle'
    $updateManifestPath = Join-Path $updateBundleRoot 'bundle-manifest.json'
    $baselineVersion = [version](Read-CompanyAgentJson -Path (Join-Path $BundleRoot 'bundle-manifest.json')).coreVersion
    if ($UpdateBundleZip) {
        Expand-Archive -LiteralPath (Resolve-Path -LiteralPath $UpdateBundleZip).Path -DestinationPath $updateBundleRoot
        $updateManifest = Read-CompanyAgentJson -Path $updateManifestPath
        $updateVersion = [string]$updateManifest.coreVersion
        Assert-ScopedSmoke ([version]$updateVersion -gt $baselineVersion) 'Supplied update package must have a newer CoreVersion'
    }
    else {
        Copy-CompanyAgentDirectoryContents -Source $BundleRoot -Destination $updateBundleRoot
        $updateManifest = Read-CompanyAgentJson -Path $updateManifestPath
        $updateVersion = '{0}.{1}.{2}' -f $baselineVersion.Major, $baselineVersion.Minor, ($baselineVersion.Build + 1)
        $updatePluginManifestPath = Join-Path $updateBundleRoot 'payload\core\plugin\.claude-plugin\plugin.json'
        $updatePluginManifest = Read-CompanyAgentJson -Path $updatePluginManifestPath
        $updatePluginManifest.version = $updateVersion
        Write-CompanyAgentJsonAtomic -Path $updatePluginManifestPath -Value $updatePluginManifest
        $updateManifest.coreVersion = $updateVersion
        $updateManifest.bundleVersion = $updateVersion + '+' + [string]$updateManifest.knowledgeVersion
        $updateManifest.files = @(Get-CompanyAgentTreeRecords -Root $updateBundleRoot | Where-Object { $_.path -ne 'bundle-manifest.json' })
        Write-CompanyAgentJsonAtomic -Path $updateManifestPath -Value $updateManifest
    }
    Write-Host ("Testing actual update: {0} -> {1}" -f $baselineVersion, $updateVersion)
    $updateCommon = $common.Clone()
    $updateCommon.BundleRoot = $updateBundleRoot
    $updateCommon.ExistingHarnessAction = 'Update'
    $updateSetup = Join-Path $updateBundleRoot 'deploy\Setup-CompanyAgent.ps1'
    $updateInstruction = Join-Path $otherProject 'CLAUDE.md'
    $updateRule = Join-Path $otherProject '.claude\rules\personal-rule.md'
    $updateHooks = Join-Path $otherProject '.claude\settings.json'
    Write-CompanyAgentUtf8File -Path $updateInstruction -Content 'Personal instruction survives normal product updates.'
    Write-CompanyAgentUtf8File -Path $updateRule -Content 'Personal project rule survives normal product updates.'
    Write-CompanyAgentJsonAtomic -Path $updateHooks -Value @{ hooks = @{ Stop = @(@{ hooks = @(@{ type = 'command'; command = 'echo PERSONAL-HOOK-PRESERVED' }) }) } }
    $updatePersonalHashes = @{}
    foreach ($updatePersonalPath in @($updateInstruction, $updateRule, $updateHooks)) { $updatePersonalHashes[$updatePersonalPath] = (Get-FileHash -LiteralPath $updatePersonalPath -Algorithm SHA256).Hash }
    $updateAsk = $updateCommon.Clone()
    $updateAsk.ExistingHarnessAction = 'Ask'
    $updateAskResult = & $updateSetup @updateAsk -Scope Project -ProjectRoot $otherProject
    Assert-ScopedSmoke ($updateAskResult.status -eq 'input-required' -and ($updateAskResult.choices -join ',') -eq 'Update,Keep') 'Recognized Company Agent offered generic replacement rather than update'
    Assert-ScopedSmoke ($updateAskResult.operation -eq 'update' -and $updateAskResult.previousCoreVersion -eq $baselineVersion.ToString() -and $updateAskResult.coreVersion -eq $updateVersion) 'Update prompt omitted or misstated versions'
    Write-CompanyAgentUtf8File -Path $latestMemoryPath -Content 'Newest preference saved immediately before the distinct-version update.'
    $stateBeforeVersionUpdate = @(Get-CompanyAgentTreeRecords -Root $customStateRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    $updatedCustom = & $updateSetup @updateCommon -Scope Project -ProjectRoot $otherProject
    Assert-ScopedSmoke ($updatedCustom.status -eq 'updated' -and $updatedCustom.operation -eq 'update' -and $updatedCustom.previousCoreVersion -eq $baselineVersion.ToString()) 'Actual update did not report old-to-new update completion'
    Assert-ScopedSmoke (-not $updatedCustom.previousHarnessDeactivated -and $updatedCustom.existingHarnessAction -eq 'Update') 'Update deactivated unrelated personal rules/hooks'
    foreach ($updatePersonalPath in $updatePersonalHashes.Keys) { Assert-ScopedSmoke ((Get-FileHash -LiteralPath $updatePersonalPath -Algorithm SHA256).Hash -ceq $updatePersonalHashes[$updatePersonalPath]) 'Update changed a personal instruction, rule or hook' }
    $updatedRegistration = Read-CompanyAgentJson -Path $updatedCustom.registrationPath
    Assert-ScopedSmoke ($updatedRegistration.coreVersion -eq $updateVersion) 'Distinct-version update did not advance the scope registration'
    Assert-ScopedSmoke ($updatedRegistration.userStateRoot -ieq $customStateRoot) 'Distinct-version update disconnected the custom state'
    $updatedEntries = @((Read-CompanyAgentJson -Path (Join-Path $configRoot 'plugins\installed_plugins.json')).plugins.'company-agent@company-agent-local')
    $updatedProjectEntries = @($updatedEntries | Where-Object { $_.scope -eq 'local' -and $_.projectPath -ieq $otherProject -and $_.version -eq $updateVersion })
    Assert-ScopedSmoke ($updatedProjectEntries.Count -eq 1) 'Real Claude CLI did not select the new plugin version for the custom-state project'
    Assert-ScopedSmoke ((@(Get-CompanyAgentTreeRecords -Root $customStateRoot | ConvertTo-Json -Depth 10 -Compress) -join '') -ceq $stateBeforeVersionUpdate) 'Distinct-version update changed latest memory, personal knowledge, or Skill files'
    $updatedSkillRoot = [string]$updatedProjectEntries[0].installPath
    $updatedSkillCli = Join-Path $updatedSkillRoot 'scripts\harness_cli.py'
    $resolvedSkillRaw = & $PythonCommand -B $updatedSkillCli skill resolve karpathy-guidelines --state-root $customStateRoot --project-root $otherProject --claude-root $configRoot --plugin-root $updatedSkillRoot --base (Join-Path $updateBundleRoot 'payload\knowledge')
    Assert-ScopedSmoke ($LASTEXITCODE -eq 0) 'Updated cached CLI could not resolve the preserved Skill preference'
    $resolvedSkill = ($resolvedSkillRaw -join [Environment]::NewLine) | ConvertFrom-Json
    Assert-ScopedSmoke ($resolvedSkill.complete -and $resolvedSkill.resolution.status -eq 'selected' -and $resolvedSkill.resolution.selectedId -ceq $preferredSkill[0].id) 'Skill preference ID or resolution changed after a version update'
    $selectedUpdatedSkill = @($resolvedSkill.candidates | Where-Object { $_.id -eq $preferredSkill[0].id })
    Assert-ScopedSmoke ($selectedUpdatedSkill.Count -eq 1 -and $selectedUpdatedSkill[0].path.StartsWith($updatedSkillRoot, [StringComparison]::OrdinalIgnoreCase)) 'Preserved Skill preference still points at the old plugin payload'
    # Verify the actual updated hook, not only its plugin registration. No
    # model is contacted by --init-only and all paths remain in this fixture.
    $updatedDebug = Join-Path $testRoot 'init-after-version-update.log'
    Push-Location -LiteralPath $otherProject
    try {
        $updatedInit = & $ClaudeCommand --init-only --debug-file $updatedDebug 2>&1
        if ($LASTEXITCODE -ne 0) { throw ('Updated Claude initialization failed: ' + ($updatedInit -join [Environment]::NewLine)) }
    }
    finally { Pop-Location }
    $updatedDebugText = Get-Content -LiteralPath $updatedDebug -Raw -Encoding UTF8
    Assert-ScopedSmoke ([regex]::Matches($updatedDebugText, 'Hook SessionStart:startup \(SessionStart\) success').Count -eq 1) 'Updated plugin did not run exactly one successful SessionStart'
    $updatedResponseLines = @(Get-Content -LiteralPath $updatedDebug -Encoding UTF8 | Where-Object { $_ -like '*Hooks: Parsed initial response:*' })
    $updatedResponse = ($updatedResponseLines[0] -replace '^.*Hooks: Parsed initial response: ', '') | ConvertFrom-Json
    $updatedRuntime = ($updatedResponse.hookSpecificOutput.additionalContext | ConvertFrom-Json).company_agent_runtime
    Assert-ScopedSmoke ($updatedRuntime.scope -eq 'Project' -and $updatedRuntime.stateRoot -eq $customStateRoot) 'Updated native hook selected the wrong scope/state'
    if ([version]$updateVersion -ge [version]'1.4.11') {
        Assert-ScopedSmoke (Test-Path -LiteralPath (Join-Path $customStateRoot 'cache\skill-metadata-v1.json')) 'Updated runtime did not prepare metadata cache'
    }
    $rejectDowngrade = $false
    try { $null = & $setup @reapplyCommon -Scope Project -ProjectRoot $otherProject }
    catch { if ($_.Exception.Message -notmatch 'older') { throw }; $rejectDowngrade = $true }
    Assert-ScopedSmoke $rejectDowngrade 'Older package was presented as an ordinary update'
    Assert-ScopedSmoke ((Read-CompanyAgentJson -Path $updatedCustom.registrationPath).coreVersion -eq $updateVersion) 'Rejected downgrade changed the latest registration'
    # User scope was uninstalled above. Restore only its original instructions
    # and custom hooks through the packaged recovery entry point.
    $restoreEntry = Join-Path $BundleRoot 'deploy\Restore-PreviousHarness.ps1'
    $restorePreview = & $restoreEntry -BackupPath $user.safetyBackup -DryRun -NonInteractive
    Assert-ScopedSmoke ($restorePreview.status -eq 'restore-ready' -and -not (Test-Path -LiteralPath $userInstruction)) 'Recovery DryRun changed the old harness'
    $restoredUser = & $restoreEntry -BackupPath $user.safetyBackup -NonInteractive
    Assert-ScopedSmoke ($restoredUser.status -eq 'restored' -and (Test-Path -LiteralPath $userInstruction) -and (Test-Path -LiteralPath $userRule)) 'Packaged recovery entry did not restore User instructions'
    $afterRecovery = Read-CompanyAgentJson -Path (Join-Path $configRoot 'settings.json')
    Assert-ScopedSmoke ($afterRecovery.hooks.SessionStart[0].hooks[0].command -eq 'echo PREVIOUS_HARNESS_FIXTURE') 'Packaged recovery did not restore original hooks'
    Assert-ScopedSmoke ($afterRecovery.env.API_TOKEN -eq 'fixture-not-a-real-secret' -and $afterRecovery.enabledPlugins.'unrelated@fixture' -eq $true) 'Packaged recovery changed unrelated settings'
    Write-Host "Scoped install smoke PASS (real offline Claude plugin CLI): $testRoot"
    [pscustomobject]@{ status = 'pass'; testRoot = $testRoot; nativeClaude = $true; claudeCommand = $ClaudeCommand; unsafeIntegerBlocked = $unsafeIntegerBlocked; scopes = @('user', 'local'); registrations = 3; nativeSessionStart = $true; embeddedPython = [bool]$IncludeBundledPython; customStatePreserved = $true; conflictingStateBlocked = $true; futureStateBlocked = $true; distinctVersionUpdate = $updateVersion; existingHarnessChoice = $true; replacementRollback = $true; legacyCp949 = [bool]$LegacyEncoding; unicodePaths = $true }
}
finally {
    $env:CLAUDE_CONFIG_DIR = $originalConfig
    $env:CLAUDE_CODE_SUBAGENT_MODEL = $originalForce
    $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE = $originalForce2
    $env:PYTHONIOENCODING = $originalPythonEncoding
    $env:PYTHONUTF8 = $originalPythonUtf8
    [Console]::OutputEncoding = $originalConsoleEncoding
    $OutputEncoding = $originalPipeEncoding
    if (-not $KeepTestDirectory -and (Test-Path -LiteralPath $testRoot)) {
        $resolved = ConvertTo-CompanyAgentFullPath -Path $testRoot
        $tempRoot = (ConvertTo-CompanyAgentFullPath -Path ([IO.Path]::GetTempPath())).TrimEnd('\')
        if (-not $resolved.StartsWith(($tempRoot + '\'), [StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $resolved) -notlike 'CompanyAgent-ScopedSmoke-*') { throw 'Unsafe smoke-test cleanup path.' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
