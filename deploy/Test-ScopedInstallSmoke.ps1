[CmdletBinding()]
param(
    [string] $BundleRoot,
    [string] $ClaudeCommand = 'claude',
    [string] $PythonCommand = 'python',
    [switch] $IncludeBundledPython,
    [switch] $KeepTestDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')
function Assert-ScopedSmoke {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "Scoped install smoke failed: $Message" }
}
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('CompanyAgent-ScopedSmoke-' + [guid]::NewGuid().ToString('N'))
$originalConfig = $env:CLAUDE_CONFIG_DIR
$originalForce = $env:CLAUDE_CODE_SUBAGENT_MODEL
$originalForce2 = $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE
try {
    New-CompanyAgentDirectory -Path $testRoot
    if ([string]::IsNullOrWhiteSpace($BundleRoot)) {
        $repoRoot = Split-Path -Parent $PSScriptRoot
        $pluginManifest = Read-CompanyAgentJson -Path (Join-Path $repoRoot 'company-agent-plugin\.claude-plugin\plugin.json')
        $knowledgeManifest = Read-CompanyAgentJson -Path (Join-Path $repoRoot 'corporate-knowledge\pack.json')
        $bundleZip = Join-Path $testRoot 'bundle.zip'
        $null = & (Join-Path $PSScriptRoot 'New-OfflineBundle.ps1') -SourceRoot $repoRoot -CoreVersion ([string]$pluginManifest.version) -KnowledgeVersion ([string]$knowledgeManifest.version) -OutputPath $bundleZip -SkipSourceValidation:(-not $IncludeBundledPython)
        $BundleRoot = Join-Path $testRoot 'bundle'
        Expand-Archive -LiteralPath $bundleZip -DestinationPath $BundleRoot
    }
    $profileRoot = Join-Path $testRoot 'profile'
    $localAppData = Join-Path $profileRoot 'AppData\Local'
    $configRoot = Join-Path $profileRoot '.claude'
    $projectRoot = Join-Path $testRoot 'My project'
    $otherProject = Join-Path $testRoot 'Other project'
    $customStateRoot = Join-Path $testRoot 'Personal state outside the defaults'
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
    Write-CompanyAgentUtf8File -Path (Join-Path $configRoot '.credentials.json') -Content '{"fixture":"do-not-copy"}'
    $settingsLocalPath = Join-Path $projectRoot '.claude\settings.local.json'
    Write-CompanyAgentJsonAtomic -Path $settingsLocalPath -Value ([pscustomobject]@{ permissions = [pscustomobject]@{ allow = @('Read') } })
    $common = @{
        BundleRoot = $BundleRoot; ClaudeConfigRoot = $configRoot; InvokingUserProfile = $profileRoot
        InvokingLocalAppData = $localAppData; ClaudeCommand = $ClaudeCommand; PythonCommand = $PythonCommand
        NonInteractive = $true; SkipAdminCheck = $true
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
    $preview = & $setup @common -Scope User -DryRun
    Assert-ScopedSmoke ($preview.status -eq 'dry-run' -and -not $preview.needsElevation) 'User dry-run should be read-only without UAC'
    Assert-ScopedSmoke (-not (Test-Path -LiteralPath (Join-Path $localAppData 'CompanyAgent-Distribution'))) 'Dry-run created distribution'
    if ($IncludeBundledPython) { Assert-ScopedSmoke ($preview.pythonCommand -like '*\runtime\python\python.exe') 'Full package did not choose its embedded Python' }
    $user = & $setup @common -Scope User
    Assert-ScopedSmoke ($user.status -eq 'installed' -and $user.nativeClaudeScope -eq 'user') 'User installation failed'
    $userRecord = Read-CompanyAgentJson -Path $user.registrationPath
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
    Assert-ScopedSmoke ((Get-Content -LiteralPath (Join-Path $configRoot 'skills\existing-skill\SKILL.md') -Raw) -like 'Existing skill*') 'Existing skill changed'
    $backup = Read-CompanyAgentJson -Path (Join-Path $user.safetyBackup 'claude-config\settings.json')
    Assert-ScopedSmoke ($backup.env.API_TOKEN -eq '[REDACTED_BY_COMPANY_AGENT_BACKUP]') 'Backup secret redaction failed'
    Assert-ScopedSmoke (-not (Test-Path -LiteralPath (Join-Path $user.safetyBackup 'claude-config\.credentials.json'))) 'Backup copied credentials'
    $project = & $setup @common -Scope Project -ProjectRoot $projectRoot
    $project2 = & $setup @common -Scope Project -ProjectRoot $otherProject -UserStateRoot $customStateRoot
    Assert-ScopedSmoke ($project.nativeClaudeScope -eq 'local') 'Project must use local settings scope'
    Assert-ScopedSmoke ($project.userStateRoot -ne $user.userStateRoot -and $project.userStateRoot -ne $project2.userStateRoot) 'Per-scope state was shared'
    Assert-ScopedSmoke (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.claude\settings.json'))) 'Project installed shared tracked settings'
    $projectSettings = Read-CompanyAgentJson -Path $settingsLocalPath
    Assert-ScopedSmoke ($projectSettings.permissions.allow -contains 'Read') 'Existing project permissions changed'
    $inventory = Read-CompanyAgentJson -Path (Join-Path $configRoot 'plugins\installed_plugins.json')
    $entries = @($inventory.plugins.'company-agent@company-agent-local')
    Assert-ScopedSmoke ($entries.Count -eq 3) 'User plus two Project registrations should coexist as one plugin identity'
    $again = & $setup @common -Scope Project -ProjectRoot $projectRoot
    Assert-ScopedSmoke ($again.status -eq 'installed') 'Repeat installation failed'
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
    $didFail = $false
    try { $null = & $setup @failureCommon -Scope Project -ProjectRoot $failedProject }
    catch {
        if ($_.Exception.Message -notlike '*SCOPED_SMOKE_INJECTED_UPDATE_FAILURE*') { throw }
        $didFail = $true
    }
    Assert-ScopedSmoke $didFail 'Injected plugin update failure was ignored'
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
    Copy-CompanyAgentDirectoryContents -Source $BundleRoot -Destination $updateBundleRoot
    $updateManifestPath = Join-Path $updateBundleRoot 'bundle-manifest.json'
    $updateManifest = Read-CompanyAgentJson -Path $updateManifestPath
    $baselineVersion = [version]$updateManifest.coreVersion
    $updateVersion = '{0}.{1}.{2}' -f $baselineVersion.Major, $baselineVersion.Minor, ($baselineVersion.Build + 1)
    $updatePluginManifestPath = Join-Path $updateBundleRoot 'payload\core\plugin\.claude-plugin\plugin.json'
    $updatePluginManifest = Read-CompanyAgentJson -Path $updatePluginManifestPath
    $updatePluginManifest.version = $updateVersion
    Write-CompanyAgentJsonAtomic -Path $updatePluginManifestPath -Value $updatePluginManifest
    $updateManifest.coreVersion = $updateVersion
    $updateManifest.bundleVersion = $updateVersion + '+' + [string]$updateManifest.knowledgeVersion
    $updateManifest.files = @(Get-CompanyAgentTreeRecords -Root $updateBundleRoot | Where-Object { $_.path -ne 'bundle-manifest.json' })
    Write-CompanyAgentJsonAtomic -Path $updateManifestPath -Value $updateManifest
    $updateCommon = $common.Clone()
    $updateCommon.BundleRoot = $updateBundleRoot
    $updateSetup = Join-Path $updateBundleRoot 'deploy\Setup-CompanyAgent.ps1'
    Write-CompanyAgentUtf8File -Path $latestMemoryPath -Content 'Newest preference saved immediately before the distinct-version update.'
    $stateBeforeVersionUpdate = @(Get-CompanyAgentTreeRecords -Root $customStateRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    $updatedCustom = & $updateSetup @updateCommon -Scope Project -ProjectRoot $otherProject
    $updatedRegistration = Read-CompanyAgentJson -Path $updatedCustom.registrationPath
    Assert-ScopedSmoke ($updatedRegistration.coreVersion -eq $updateVersion) 'Distinct-version update did not advance the scope registration'
    Assert-ScopedSmoke ($updatedRegistration.userStateRoot -ieq $customStateRoot) 'Distinct-version update disconnected the custom state'
    $updatedEntries = @((Read-CompanyAgentJson -Path (Join-Path $configRoot 'plugins\installed_plugins.json')).plugins.'company-agent@company-agent-local')
    $updatedProjectEntries = @($updatedEntries | Where-Object { $_.scope -eq 'local' -and $_.projectPath -ieq $otherProject -and $_.version -eq $updateVersion })
    Assert-ScopedSmoke ($updatedProjectEntries.Count -eq 1) 'Real Claude CLI did not select the new plugin version for the custom-state project'
    Assert-ScopedSmoke ((@(Get-CompanyAgentTreeRecords -Root $customStateRoot | ConvertTo-Json -Depth 10 -Compress) -join '') -ceq $stateBeforeVersionUpdate) 'Distinct-version update changed latest memory, personal knowledge, or Skill files'
    Write-Host "Scoped install smoke PASS (real offline Claude plugin CLI): $testRoot"
    [pscustomobject]@{ status = 'pass'; testRoot = $testRoot; nativeClaude = $true; scopes = @('user', 'local'); registrations = 3; nativeSessionStart = $true; embeddedPython = [bool]$IncludeBundledPython; customStatePreserved = $true; conflictingStateBlocked = $true; futureStateBlocked = $true; distinctVersionUpdate = $updateVersion }
}
finally {
    $env:CLAUDE_CONFIG_DIR = $originalConfig
    $env:CLAUDE_CODE_SUBAGENT_MODEL = $originalForce
    $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE = $originalForce2
    if (-not $KeepTestDirectory -and (Test-Path -LiteralPath $testRoot)) {
        $resolved = ConvertTo-CompanyAgentFullPath -Path $testRoot
        $tempRoot = (ConvertTo-CompanyAgentFullPath -Path ([IO.Path]::GetTempPath())).TrimEnd('\')
        if (-not $resolved.StartsWith(($tempRoot + '\'), [StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $resolved) -notlike 'CompanyAgent-ScopedSmoke-*') { throw 'Unsafe smoke-test cleanup path.' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
