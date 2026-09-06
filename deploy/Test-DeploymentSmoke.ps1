[CmdletBinding()]
param(
    [string] $TestRoot,
    [string] $InstallRoot,
    [string] $DataRoot,
    [string] $UserStateRoot,
    [switch] $SkipAcl,
    [switch] $KeepArtifacts
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')

function Assert-SmokeCondition {
    param(
        [Parameter(Mandatory = $true)]
        [bool] $Condition,
        [Parameter(Mandatory = $true)]
        [string] $Message
    )

    if (-not $Condition) {
        throw "Smoke assertion failed: $Message"
    }
}

$ownsTestRoot = [string]::IsNullOrWhiteSpace($TestRoot)
if ($ownsTestRoot) {
    $TestRoot = Join-Path $env:TEMP ('CompanyAgent-Smoke-' + [guid]::NewGuid().ToString('N'))
}
$TestRoot = ConvertTo-CompanyAgentFullPath -Path $TestRoot
if (Test-Path -LiteralPath $TestRoot) {
    if (@(Get-ChildItem -LiteralPath $TestRoot -Force).Count -gt 0) {
        throw "TestRoot must be empty: $TestRoot"
    }
}
else {
    New-CompanyAgentDirectory -Path $TestRoot
}

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Join-Path $TestRoot 'machine\install'
}
if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $DataRoot = Join-Path $TestRoot 'machine\data'
}
if ([string]::IsNullOrWhiteSpace($UserStateRoot)) {
    $UserStateRoot = Join-Path $TestRoot 'user\state'
}
$InstallRoot = ConvertTo-CompanyAgentFullPath -Path $InstallRoot
$DataRoot = ConvertTo-CompanyAgentFullPath -Path $DataRoot
$UserStateRoot = ConvertTo-CompanyAgentFullPath -Path $UserStateRoot
$nestedRootRejected = $false
try {
    Assert-CompanyAgentRootsSeparated `
        -InstallRoot (Join-Path $TestRoot 'nested') `
        -DataRoot (Join-Path $TestRoot 'nested\data') `
        -UserStateRoot (Join-Path $TestRoot 'separate-user')
}
catch {
    $nestedRootRejected = $true
}
Assert-SmokeCondition -Condition $nestedRootRejected -Message 'nested managed roots were not rejected'

try {
    $sourceRoot = Join-Path $TestRoot 'source'
    $sourceDeploy = Join-Path $sourceRoot 'deploy'
    $pluginRoot = Join-Path $sourceRoot 'company-agent-plugin'
    $knowledgeRoot = Join-Path $sourceRoot 'corporate-knowledge'
    $configRoot = Join-Path $sourceRoot 'config'
    $repositoryRoot = Split-Path -Parent $PSScriptRoot
    Copy-CompanyAgentDirectoryContents -Source $PSScriptRoot -Destination $sourceDeploy
    Copy-CompanyAgentDirectoryContents -Source (Join-Path $repositoryRoot 'company-agent-plugin') -Destination $pluginRoot
    Copy-CompanyAgentDirectoryContents -Source (Join-Path $repositoryRoot 'corporate-knowledge') -Destination $knowledgeRoot
    Copy-CompanyAgentDirectoryContents -Source (Join-Path $repositoryRoot 'config') -Destination $configRoot
    # This lifecycle fixture deliberately exercises 0.3.0 -> 0.3.1 even when
    # the real release advances. Set versions only in the temporary source
    # copy so bundle validation does not depend on the checkout's version.
    $pluginManifest = Read-CompanyAgentJson -Path (Join-Path $pluginRoot '.claude-plugin\plugin.json')
    $pluginManifest.version = '0.3.0'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $pluginRoot '.claude-plugin\plugin.json') -Value $pluginManifest
    $knowledgeManifest = Read-CompanyAgentJson -Path (Join-Path $knowledgeRoot 'pack.json')
    $knowledgeManifest.version = '2026.09.03'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $knowledgeRoot 'pack.json') -Value $knowledgeManifest
    foreach ($rootInstallerFile in @('Install-CompanyAgent.cmd', 'INSTALL_WITH_CLAUDE.md')) {
        $rootInstallerSource = Join-Path $repositoryRoot $rootInstallerFile
        if (Test-Path -LiteralPath $rootInstallerSource -PathType Leaf) {
            Copy-Item -LiteralPath $rootInstallerSource -Destination (Join-Path $sourceRoot $rootInstallerFile) -Force
        }
    }
    Write-CompanyAgentUtf8File -Path (Join-Path $pluginRoot 'SMOKE_VERSION.txt') -Content "v1`r`n"
    Write-CompanyAgentUtf8File -Path (Join-Path $knowledgeRoot 'SMOKE_VERSION.txt') -Content "v1`r`n"

    $bundleV1 = Join-Path $TestRoot 'company-agent-v1.zip'
    $bundleResult = & (Join-Path $PSScriptRoot 'New-OfflineBundle.ps1') -SourceRoot $sourceRoot -CoreVersion '0.3.0' -KnowledgeVersion '2026.09.03' -OutputPath $bundleV1 -SkipSourceValidation
    Assert-SmokeCondition -Condition (Test-Path -LiteralPath $bundleResult.outputPath -PathType Leaf) -Message 'v1 bundle was not created'

    $expandedV1 = Join-Path $TestRoot 'expanded-v1'
    Expand-Archive -LiteralPath $bundleV1 -DestinationPath $expandedV1
    Assert-SmokeCondition -Condition (Test-Path -LiteralPath (Join-Path $expandedV1 'Install-CompanyAgent.cmd') -PathType Leaf) -Message 'bundle root easy installer is missing'
    Assert-SmokeCondition -Condition (Test-Path -LiteralPath (Join-Path $expandedV1 'INSTALL_WITH_CLAUDE.md') -PathType Leaf) -Message 'bundle root Claude installation guide is missing'

    # Exercise the beginner-facing Setup separately from the lower-level
    # lifecycle below. It must inventory collisions, redact settings secrets,
    # preserve the source Claude directory, and avoid initializing user state
    # in the machine-install phase.
    $setupClaudeRoot = Join-Path $TestRoot 'existing-claude'
    $setupSkillRoot = Join-Path $setupClaudeRoot 'skills\daily-summary'
    New-CompanyAgentDirectory -Path $setupSkillRoot
    Write-CompanyAgentUtf8File -Path (Join-Path $setupSkillRoot 'SKILL.md') -Content "existing skill`r`n"
    Write-CompanyAgentUtf8File -Path (Join-Path $setupSkillRoot '.env') -Content "SHOULD_NOT_BE_BACKED_UP=1`r`n"
    Write-CompanyAgentUtf8File -Path (Join-Path $setupClaudeRoot '.credentials.json') -Content "{}`r`n"
    Write-CompanyAgentUtf8File -Path (Join-Path $setupClaudeRoot 'history.jsonl') -Content "private history`r`n"
    Write-CompanyAgentJsonAtomic -Path (Join-Path $setupClaudeRoot 'settings.json') -Value ([pscustomobject][ordered]@{
        theme = 'dark'
        env = [pscustomobject][ordered]@{
            API_TOKEN = 'must-not-survive'
            NORMAL_SETTING = 'preserved'
            CLAUDE_CODE_SUBAGENT_MODEL = 'forced-model'
        }
    })
    Write-CompanyAgentJsonAtomic -Path (Join-Path $setupClaudeRoot 'plugins\installed_plugins.json') -Value ([pscustomobject][ordered]@{
        plugins = [pscustomobject][ordered]@{
            'company-agent@personal' = @()
        }
    })
    $claudeBeforeSetup = @(Get-CompanyAgentTreeRecords -Root $setupClaudeRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    $setupInstallRoot = Join-Path $TestRoot 'easy-setup\install'
    $setupDataRoot = Join-Path $TestRoot 'easy-setup\data'
    $setupUserStateRoot = Join-Path $TestRoot 'easy-setup\user'
    $setupBackupRoot = Join-Path $TestRoot 'easy-setup-backups'
    $setupDryRun = & (Join-Path $expandedV1 'deploy\Setup-CompanyAgent.ps1') `
        -BundleRoot $expandedV1 `
        -InstallRoot $setupInstallRoot `
        -DataRoot $setupDataRoot `
        -UserStateRoot $setupUserStateRoot `
        -BackupRoot $setupBackupRoot `
        -ClaudeConfigRoot $setupClaudeRoot `
        -SkipAcl `
        -SkipAdminCheck `
        -SkipShortcut `
        -DryRun
    Assert-SmokeCondition -Condition $setupDryRun.pluginCollisionBlocked -Message 'easy Setup did not block a duplicate company-agent plugin'
    Assert-SmokeCondition -Condition $setupDryRun.settingsModelOverrideBlocked -Message 'easy Setup did not block a settings-based subagent model override'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $setupClaudeRoot 'plugins\installed_plugins.json') -Value ([pscustomobject][ordered]@{
        plugins = [pscustomobject][ordered]@{
            'other-plugin@personal' = @()
        }
    })
    Write-CompanyAgentJsonAtomic -Path (Join-Path $setupClaudeRoot 'settings.json') -Value ([pscustomobject][ordered]@{
        theme = 'dark'
        env = [pscustomobject][ordered]@{
            API_TOKEN = 'must-not-survive'
            NORMAL_SETTING = 'preserved'
        }
    })
    $claudeBeforeSetup = @(Get-CompanyAgentTreeRecords -Root $setupClaudeRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    $setupResult = & (Join-Path $expandedV1 'deploy\Setup-CompanyAgent.ps1') `
        -BundleRoot $expandedV1 `
        -InstallRoot $setupInstallRoot `
        -DataRoot $setupDataRoot `
        -UserStateRoot $setupUserStateRoot `
        -BackupRoot $setupBackupRoot `
        -ClaudeConfigRoot $setupClaudeRoot `
        -SkipAcl `
        -SkipAdminCheck `
        -SkipShortcut
    Assert-SmokeCondition -Condition ($setupResult.status -eq 'installed') -Message 'easy Setup did not complete'
    Assert-SmokeCondition -Condition (-not (Test-Path -LiteralPath $setupUserStateRoot)) -Message 'machine Setup initialized personal state in the wrong context'
    $claudeAfterSetup = @(Get-CompanyAgentTreeRecords -Root $setupClaudeRoot | ConvertTo-Json -Depth 10 -Compress) -join ''
    Assert-SmokeCondition -Condition ($claudeAfterSetup -ceq $claudeBeforeSetup) -Message 'easy Setup changed the existing Claude user directory'
    $backupSettings = Read-CompanyAgentJson -Path (Join-Path $setupResult.safetyBackup 'claude-config\settings.json')
    Assert-SmokeCondition -Condition ($backupSettings.env.API_TOKEN -eq '[REDACTED_BY_COMPANY_AGENT_BACKUP]') -Message 'backup retained a secret-like settings value'
    Assert-SmokeCondition -Condition ($backupSettings.env.NORMAL_SETTING -eq 'preserved') -Message 'backup lost a non-secret settings value'
    Assert-SmokeCondition -Condition (-not (Test-Path -LiteralPath (Join-Path $setupResult.safetyBackup 'claude-config\.credentials.json'))) -Message 'backup included Claude credentials'
    Assert-SmokeCondition -Condition (-not (Test-Path -LiteralPath (Join-Path $setupResult.safetyBackup 'claude-config\skills\daily-summary\.env'))) -Message 'backup included an environment-secret file'
    Assert-SmokeCondition -Condition (Test-Path -LiteralPath (Join-Path $setupResult.safetyBackup 'claude-config\skills\daily-summary\SKILL.md') -PathType Leaf) -Message 'backup lost a normal Skill file'
    $backupAcl = Get-Acl -LiteralPath $setupResult.safetyBackup
    Assert-SmokeCondition -Condition $backupAcl.AreAccessRulesProtected -Message 'backup ACL still inherits access for unrelated users'

    $installResult = & (Join-Path $expandedV1 'deploy\Install-CompanyAgent.ps1') `
        -BundleRoot $expandedV1 `
        -UseExistingClaudeModels `
        -DefaultTier 'AUTO' `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -SkipAcl `
        -SkipAdminCheck `
        -SkipShortcut
    Assert-SmokeCondition -Condition ($installResult.coreVersion -eq '0.3.0') -Message 'v1 core was not installed'
    Assert-SmokeCondition -Condition ($installResult.modelMode -eq 'claude-config') -Message 'fresh install did not preserve the existing Claude model configuration'

    $initializeResult = & (Join-Path $expandedV1 'deploy\Initialize-CompanyAgentUser.ps1') `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -NonInteractive `
        -SkipAcl
    Assert-SmokeCondition -Condition (Test-Path -LiteralPath $initializeResult.personalKnowledge -PathType Container) -Message 'personal knowledge was not initialized'

    $dryRun = & (Join-Path $expandedV1 'deploy\Start-CompanyAgent.ps1') `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -ModelTier 'AUTO' `
        -Prompt 'smoke' `
        -NonInteractive `
        -SkipAcl `
        -DryRun
    Assert-SmokeCondition -Condition ($dryRun.modelMode -eq 'claude-config') -Message 'launcher did not retain Claude-config model mode'
    Assert-SmokeCondition -Condition ($dryRun.modelTier -eq 'AUTO') -Message 'AUTO did not preserve the existing Claude default model'
    Assert-SmokeCondition -Condition ($null -eq $dryRun.modelArgument) -Message 'AUTO unexpectedly forced a main-session model'
    Assert-SmokeCondition -Condition (-not ($dryRun.arguments -contains '--model')) -Message 'AUTO added a --model override'
    Assert-SmokeCondition -Condition ($dryRun.arguments -contains '--plugin-dir') -Message 'plugin directory argument is missing'
    Assert-SmokeCondition -Condition ($dryRun.arguments -contains $initializeResult.personalKnowledge) -Message 'personal knowledge add-dir is missing'
    Assert-SmokeCondition -Condition ($dryRun.arguments -contains $initializeResult.personalRoot) -Message 'personal Skill root add-dir is missing'
    Assert-SmokeCondition -Condition (-not ($dryRun.arguments -contains '--mcp-config')) -Message 'empty Harness MCP config hid or changed existing MCP servers'
    Assert-SmokeCondition -Condition (-not ($dryRun.arguments -contains '--strict-mcp-config')) -Message 'default launcher unexpectedly isolated existing MCP servers'
    Assert-SmokeCondition -Condition ($null -eq $dryRun.environment.PSObject.Properties['ANTHROPIC_DEFAULT_HAIKU_MODEL']) -Message 'launcher overwrote the existing haiku mapping'
    Assert-SmokeCondition -Condition ($dryRun.processOnlyEnvironmentClears -contains 'CLAUDE_CODE_SUBAGENT_MODEL') -Message 'subagent override was not scoped away from routed workers'
    $expectedPythonInfo = Get-Command 'python' | Select-Object -First 1
    $expectedPythonCommand = $expectedPythonInfo.Source
    if ([string]::IsNullOrWhiteSpace($expectedPythonCommand)) {
        $expectedPythonCommand = $expectedPythonInfo.Definition
    }
    Assert-SmokeCondition -Condition ($dryRun.environment.COMPANY_AGENT_PYTHON -ieq $expectedPythonCommand) -Message 'Harness Python command mapping is missing'
    Assert-SmokeCondition -Condition (Test-Path -LiteralPath (Join-Path $dryRun.corePlugin 'bin\python.cmd') -PathType Leaf) -Message 'Harness Python wrapper is missing'
    Assert-SmokeCondition -Condition ($dryRun.environment.Path.StartsWith((Join-Path $dryRun.corePlugin 'bin') + ';', [System.StringComparison]::OrdinalIgnoreCase)) -Message 'Harness CLI directory is not first on PATH'
    Assert-SmokeCondition -Condition (Test-Path -LiteralPath $initializeResult.knowledgeCatalog -PathType Leaf) -Message 'effective knowledge catalog was not built'
    $storedUserConfig = Read-CompanyAgentJson -Path (Join-Path $UserStateRoot 'config\user.json')
    Assert-SmokeCondition -Condition ([string]::IsNullOrWhiteSpace([string]$storedUserConfig.user_email)) -Message 'MCP-independent initialization unexpectedly required or invented an Outlook email'
    Assert-SmokeCondition -Condition (-not [string]::IsNullOrWhiteSpace([string]$storedUserConfig.display_name)) -Message 'Windows display name default was not created'
    Assert-SmokeCondition -Condition (-not $dryRun.userClaudeHomeMutated) -Message 'launcher claims it mutated user Claude home'

    $forcedModelWorkRoot = Join-Path $TestRoot 'forced-model-project'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $forcedModelWorkRoot '.claude\settings.local.json') -Value ([pscustomobject][ordered]@{
        env = [pscustomobject][ordered]@{ CLAUDE_CODE_SUBAGENT_MODEL_FORCE = 'forced-model' }
    })
    $projectModelForceRejected = $false
    try {
        $null = & (Join-Path $expandedV1 'deploy\Start-CompanyAgent.ps1') `
            -InstallRoot $InstallRoot `
            -DataRoot $DataRoot `
            -UserStateRoot $UserStateRoot `
            -WorkingDirectory $forcedModelWorkRoot `
            -Prompt 'smoke-model-force' `
            -NonInteractive `
            -SkipAcl `
            -SkipKnowledgePreparation `
            -DryRun
    }
    catch {
        $projectModelForceRejected = $true
    }
    Assert-SmokeCondition -Condition $projectModelForceRejected -Message 'launcher did not reject a project settings subagent model override'

    Write-CompanyAgentJsonAtomic -Path (Join-Path $UserStateRoot 'mcp\registry.json') -Value ([pscustomobject][ordered]@{
        mcpServers = [pscustomobject][ordered]@{
            'smoke-readonly' = [pscustomobject][ordered]@{ command = 'smoke-mcp'; args = @() }
        }
    })
    $mergeMcpDryRun = & (Join-Path $expandedV1 'deploy\Start-CompanyAgent.ps1') `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -Prompt 'smoke-mcp' `
        -NonInteractive `
        -SkipAcl `
        -SkipKnowledgePreparation `
        -DryRun
    Assert-SmokeCondition -Condition ($mergeMcpDryRun.mcpConfigMode -eq 'merge') -Message 'non-empty personal MCP registry did not use merge mode'
    Assert-SmokeCondition -Condition ($mergeMcpDryRun.arguments -contains '--mcp-config') -Message 'non-empty personal MCP registry was not passed to Claude'
    Assert-SmokeCondition -Condition (-not ($mergeMcpDryRun.arguments -contains '--strict-mcp-config')) -Message 'personal MCP registry unexpectedly hid existing MCP servers'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $UserStateRoot 'mcp\registry.json') -Value ([pscustomobject][ordered]@{ mcpServers = [pscustomobject]@{} })

    $smallDryRun = & (Join-Path $expandedV1 'deploy\Start-CompanyAgent.ps1') `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -ModelTier 'SMALL' `
        -Prompt 'smoke-small' `
        -NonInteractive `
        -SkipAcl `
        -DryRun
    Assert-SmokeCondition -Condition ($smallDryRun.modelId -eq 'haiku') -Message 'SMALL alias was not selected from existing Claude configuration'
    Assert-SmokeCondition -Condition ($smallDryRun.modelArgument -eq 'haiku') -Message 'SMALL tier did not pass the haiku alias'
    foreach ($modelCase in @(
        [pscustomobject]@{ tier = 'MEDIUM'; alias = 'sonnet' },
        [pscustomobject]@{ tier = 'LARGE'; alias = 'opus' }
    )) {
        $tierDryRun = & (Join-Path $expandedV1 'deploy\Start-CompanyAgent.ps1') `
            -InstallRoot $InstallRoot `
            -DataRoot $DataRoot `
            -UserStateRoot $UserStateRoot `
            -ModelTier $modelCase.tier `
            -Prompt ('smoke-' + $modelCase.tier.ToLowerInvariant()) `
            -NonInteractive `
            -SkipAcl `
            -SkipKnowledgePreparation `
            -DryRun
        Assert-SmokeCondition -Condition ($tierDryRun.modelArgument -eq $modelCase.alias) -Message ("{0} tier did not pass the {1} alias" -f $modelCase.tier, $modelCase.alias)
    }

    $pluginManifest = Read-CompanyAgentJson -Path (Join-Path $pluginRoot '.claude-plugin\plugin.json')
    $pluginManifest.version = '0.3.1'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $pluginRoot '.claude-plugin\plugin.json') -Value $pluginManifest
    $knowledgeManifest = Read-CompanyAgentJson -Path (Join-Path $knowledgeRoot 'pack.json')
    $knowledgeManifest.version = '2026.10.01'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $knowledgeRoot 'pack.json') -Value $knowledgeManifest
    Write-CompanyAgentUtf8File -Path (Join-Path $pluginRoot 'SMOKE_VERSION.txt') -Content "v2`r`n"
    Write-CompanyAgentUtf8File -Path (Join-Path $knowledgeRoot 'SMOKE_VERSION.txt') -Content "v2`r`n"
    $bundleV2 = Join-Path $TestRoot 'company-agent-v2.zip'
    $null = & (Join-Path $PSScriptRoot 'New-OfflineBundle.ps1') -SourceRoot $sourceRoot -CoreVersion '0.3.1' -KnowledgeVersion '2026.10.01' -OutputPath $bundleV2 -SkipSourceValidation
    $expandedV2 = Join-Path $TestRoot 'expanded-v2'
    Expand-Archive -LiteralPath $bundleV2 -DestinationPath $expandedV2
    $launcherBeforeFailedUpdate = (Get-FileHash -LiteralPath (Join-Path $InstallRoot 'bin\Start-CompanyAgent.ps1') -Algorithm SHA256).Hash
    $failedUpdateRejected = $false
    try {
        $null = & (Join-Path $expandedV2 'deploy\Update-CompanyAgent.ps1') `
            -BundleRoot $expandedV2 `
            -InstallRoot $InstallRoot `
            -DataRoot $DataRoot `
            -UserStateRoot $UserStateRoot `
            -ShortcutPath (Join-Path $TestRoot 'invalid-shortcut.txt') `
            -SkipAcl `
            -SkipAdminCheck
    }
    catch {
        $failedUpdateRejected = $true
    }
    Assert-SmokeCondition -Condition $failedUpdateRejected -Message 'intentional late-stage update failure was not rejected'
    $selectionAfterFailedUpdate = Read-CompanyAgentJson -Path (Get-CompanyAgentCurrentPointerPath -DataRoot $DataRoot)
    Assert-SmokeCondition -Condition ($selectionAfterFailedUpdate.coreVersion -eq '0.3.0') -Message 'failed update changed the active pointer'
    $launcherAfterFailedUpdate = (Get-FileHash -LiteralPath (Join-Path $InstallRoot 'bin\Start-CompanyAgent.ps1') -Algorithm SHA256).Hash
    Assert-SmokeCondition -Condition ($launcherAfterFailedUpdate -ceq $launcherBeforeFailedUpdate) -Message 'failed update did not restore the previous launcher scripts'

    $updateResult = & (Join-Path $expandedV2 'deploy\Update-CompanyAgent.ps1') `
        -BundleRoot $expandedV2 `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -SkipAcl `
        -SkipAdminCheck `
        -SkipShortcut
    Assert-SmokeCondition -Condition ($updateResult.coreVersion -eq '0.3.1') -Message 'v2 core was not activated'

    $currentAfterUpdate = Read-CompanyAgentJson -Path (Get-CompanyAgentCurrentPointerPath -DataRoot $DataRoot)
    $previousAfterUpdate = Read-CompanyAgentJson -Path (Get-CompanyAgentPreviousPointerPath -DataRoot $DataRoot)
    Assert-SmokeCondition -Condition ($currentAfterUpdate.coreVersion -eq '0.3.1') -Message 'current pointer is not v2'
    Assert-SmokeCondition -Condition ($currentAfterUpdate.configVersion -eq '0.3.1') -Message 'current config pointer is not v2'
    Assert-SmokeCondition -Condition ($previousAfterUpdate.coreVersion -eq '0.3.0') -Message 'previous pointer is not v1'
    Assert-SmokeCondition -Condition ($previousAfterUpdate.configVersion -eq '0.3.0') -Message 'previous config pointer is not v1'
    Assert-SmokeCondition -Condition (Test-Path -LiteralPath $UserStateRoot -PathType Container) -Message 'update removed personal state'

    $rollbackResult = & (Join-Path $expandedV2 'deploy\Rollback-CompanyAgent.ps1') `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -SkipAcl `
        -SkipAdminCheck
    Assert-SmokeCondition -Condition ($rollbackResult.coreVersion -eq '0.3.0') -Message 'rollback did not restore v1'
    Assert-SmokeCondition -Condition ($rollbackResult.configVersion -eq '0.3.0') -Message 'rollback did not restore v1 config'

    $uninstallResult = & (Join-Path $expandedV2 'deploy\Uninstall-CompanyAgent.ps1') `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -SkipAcl `
        -SkipAdminCheck `
        -SkipShortcut `
        -Confirm:$false
    Assert-SmokeCondition -Condition (-not (Test-Path -LiteralPath $InstallRoot)) -Message 'system core survived uninstall'
    Assert-SmokeCondition -Condition (-not (Test-Path -LiteralPath $DataRoot)) -Message 'corporate data survived uninstall'
    Assert-SmokeCondition -Condition (Test-Path -LiteralPath $UserStateRoot -PathType Container) -Message 'default uninstall removed personal state'
    Assert-SmokeCondition -Condition ($uninstallResult.userStatePreserved -eq $UserStateRoot) -Message 'uninstall did not report preserved personal state'

    # With system roots already gone, purge the explicitly requested personal state.
    $purgeResult = & (Join-Path $expandedV2 'deploy\Uninstall-CompanyAgent.ps1') `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -RemoveUserState `
        -SkipAcl `
        -SkipAdminCheck `
        -SkipShortcut `
        -Confirm:$false
    Assert-SmokeCondition -Condition (-not (Test-Path -LiteralPath $UserStateRoot)) -Message 'explicit personal-state purge failed'
    Assert-SmokeCondition -Condition $purgeResult.userStateRemoved -Message 'purge result did not report removal'

    [pscustomobject][ordered]@{
        status = 'passed'
        tested = @(
            'offline bundle, SHA-256 manifest, and root install entrypoints',
            'nested root rejection',
            'easy Setup preflight, protected selective backup, and collision detection',
            'side-by-side install',
            'personal state initialization',
            'lazy Outlook identity and personal MCP registry',
            'effective Corporate plus Personal knowledge catalog',
            'existing Claude model aliases without launcher overrides',
            'settings-based subagent model-force rejection',
            'existing MCP coexistence and additive Harness MCP merge',
            'late-stage update failure rollback for pointers and launcher scripts',
            'versioned configuration rollback',
            'side-by-side update and previous pointer',
            'rollback',
            'uninstall preserving personal state',
            'explicit personal-state purge'
        )
        testRoot = $TestRoot
    }
}
finally {
    if ($ownsTestRoot -and -not $KeepArtifacts -and (Test-Path -LiteralPath $TestRoot)) {
        $leafName = Split-Path -Leaf $TestRoot
        $temporaryBase = (ConvertTo-CompanyAgentFullPath -Path $env:TEMP).TrimEnd([char[]]@('\', '/'))
        $testRootFull = ConvertTo-CompanyAgentFullPath -Path $TestRoot
        if ($leafName -like 'CompanyAgent-Smoke-*' -and
            $testRootFull.StartsWith($temporaryBase + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $testRootFull -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
