[CmdletBinding()]
param([switch] $KeepTestDirectory)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1') -FunctionsOnly
. (Join-Path $PSScriptRoot 'ExistingHarness.ps1')

function Assert-ExistingHarness {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "Existing harness regression failed: $Message" }
}

function Assert-ExistingHarnessRejected {
    param([scriptblock] $Action, [string] $Pattern, [string] $Message)
    $rejected = $false
    try { $null = & $Action }
    catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw }
        Assert-ExistingHarness ($_.Exception.Message -notmatch 'fixture-super-secret') 'Settings parser leaked a hook body'
        $rejected = $true
    }
    Assert-ExistingHarness $rejected $Message
}

function Get-ExistingHarnessFixtureDigest {
    param([string] $Root)
    return (@(Get-ChildItem -LiteralPath $Root -File -Recurse -Force | Sort-Object FullName | ForEach-Object {
        '{0}|{1}|{2}|{3}' -f $_.FullName, $_.Length, $_.LastWriteTimeUtc.Ticks, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }) -join "`n")
}

$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('CompanyAgent-ExistingHarness-' + [guid]::NewGuid().ToString('N'))
$fixtureFull = [IO.Path]::GetFullPath($fixtureRoot)
$junctions = New-Object Collections.ArrayList
$assertions = 0
try {
    $claudeRoot = Join-Path $fixtureRoot 'profile\.claude'
    $projectRoot = Join-Path $fixtureRoot 'work\parent\project'
    $projectClaude = Join-Path $projectRoot '.claude'
    foreach ($directory in @($claudeRoot, $projectClaude)) { New-CompanyAgentDirectory -Path $directory }
    $userArgs = @{ Scope = 'User'; ClaudeConfigRoot = $claudeRoot }
    $projectArgs = @{ Scope = 'Project'; ClaudeConfigRoot = $claudeRoot; ProjectRoot = $projectRoot }
    $inventory = Get-SetupExistingHarness @userArgs
    Assert-ExistingHarness (-not $inventory.detected -and $inventory.items.Count -eq 0) 'Empty profile requires a decision'
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $inventory -Action Ask -NonInteractive) -eq 'Install') 'Empty profile did not proceed without input'
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $inventory -Action Keep) -eq 'Install') 'No-existing Keep should remain a normal installation'
    Assert-ExistingHarness (-not $inventory.hasCompanyAgent -and -not $inventory.hasCustomHarness) 'Empty profile acquired an installation identity'
    $newIntent = Get-SetupInstallationIntent -Inventory $inventory -TargetCoreVersion '1.1.1' -TargetKnowledgeVersion '2026.09.03'
    Assert-ExistingHarness ($newIntent.operation -eq 'install' -and -not $newIntent.hasCompanyAgent -and $newIntent.coreVersion -eq '1.1.1' -and $newIntent.knowledgeVersion -eq '2026.09.03') 'New installation intent is incorrect'
    Assert-ExistingHarnessRejected -Action { Resolve-SetupExistingHarnessAction -Inventory $inventory -Action Update -NonInteractive } -Pattern 'existing|installed|registration|Company Agent' -Message 'Explicit update accepted an empty scope'
    $assertions += 6

    Write-CompanyAgentJsonAtomic -Path (Join-Path $claudeRoot 'settings.json') -Value ([pscustomobject]@{
        model = 'already-configured'; env = [pscustomobject]@{ ANTHROPIC_AUTH_TOKEN = 'fixture-super-secret' }
        mcpServers = [pscustomobject]@{ internal = [pscustomobject]@{ command = 'preserve' } }
        enabledPlugins = [pscustomobject]@{ 'unrelated@private' = $true }; hooks = [pscustomobject]@{ Stop = @() }
    })
    Write-CompanyAgentUtf8File -Path (Join-Path $claudeRoot 'skills\personal\SKILL.md') -Content 'Standalone Skill is preserved.'
    Write-CompanyAgentUtf8File -Path (Join-Path $claudeRoot 'CLAUDE.md') -Content ''
    $inventory = Get-SetupExistingHarness @userArgs
    Assert-ExistingHarness (-not $inventory.detected) 'Bare models, MCPs, plugins, empty rules, or standalone Skills were treated as a replacement harness'
    Assert-ExistingHarness ($inventory.scopeRoot -eq $claudeRoot -and $inventory.claudeConfigRoot -eq $claudeRoot) 'User scope roots were not returned'
    Assert-ExistingHarness (($inventory | ConvertTo-Json -Depth 10) -notmatch 'fixture-super-secret') 'Inventory leaked settings content'
    $assertions += 3

    Write-CompanyAgentUtf8File -Path (Join-Path $claudeRoot 'CLAUDE.md') -Content 'Existing user instructions'
    Write-CompanyAgentUtf8File -Path (Join-Path $claudeRoot 'CLAUDE.local.md') -Content 'Existing user local instructions'
    Write-CompanyAgentUtf8File -Path (Join-Path $claudeRoot 'rules\nested\review.MD') -Content 'Existing nested rule'
    Write-CompanyAgentUtf8File -Path (Join-Path $claudeRoot 'rules\not-a-rule.txt') -Content 'Preserve non-Markdown files'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $claudeRoot 'settings.json') -Value ([pscustomobject]@{
        model = 'already-configured'; env = [pscustomobject]@{ ANTHROPIC_AUTH_TOKEN = 'fixture-super-secret' }
        hooks = [pscustomobject]@{ Stop = @([pscustomobject]@{ hooks = @([pscustomobject]@{ type = 'command'; command = 'echo fixture-super-secret' }) }) }
    })
    # User settings.local.json is not a supported user settings layer. Leave it
    # unparsed and untouched; the project-local variant is handled below.
    Write-CompanyAgentUtf8File -Path (Join-Path $claudeRoot 'settings.local.json') -Content '{fixture-super-secret malformed and deliberately irrelevant'
    $before = Get-ExistingHarnessFixtureDigest -Root $fixtureRoot
    $inventory = Get-SetupExistingHarness @userArgs
    Assert-ExistingHarness ($inventory.detected -and $inventory.replacementFiles.Count -eq 3 -and $inventory.hookSettingsPaths.Count -eq 1) 'User instructions/rules/hooks were not identified precisely'
    Assert-ExistingHarness ($inventory.hookSettingsPaths[0] -eq (Join-Path $claudeRoot 'settings.json')) 'User hook settings target is wrong'
    Assert-ExistingHarness ((Get-ExistingHarnessFixtureDigest -Root $fixtureRoot) -ceq $before) 'Inventory changed source files or timestamps'
    Assert-ExistingHarness (($inventory | ConvertTo-Json -Depth 10) -notmatch 'fixture-super-secret') 'Inventory emitted a sensitive hook body'
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $inventory -Action Keep -NonInteractive) -eq 'Keep') 'Explicit Keep was not respected'
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $inventory -Action Replace -NonInteractive) -eq 'Replace') 'Explicit Replace was not respected'
    Assert-ExistingHarness (-not $inventory.hasCompanyAgent -and $inventory.hasCustomHarness) 'A custom harness was mistaken for Company Agent'
    Assert-ExistingHarnessRejected -Action { Resolve-SetupExistingHarnessAction -Inventory $inventory -Action Update -NonInteractive } -Pattern 'existing|installed|registration|Company Agent' -Message 'Explicit update accepted a different harness'
    $assertions += 8

    function Read-Host { throw 'Read-Host must never be called in a noninteractive or dry run.' }
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $inventory -NonInteractive) -eq 'InputRequired') 'Noninteractive Ask did not require input safely'
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $inventory -DryRun) -eq 'InputRequired') 'DryRun Ask tried to prompt or silently select replacement'
    Remove-Item -LiteralPath Function:\Read-Host
    $script:harnessFixtureAnswers = New-Object Collections.Queue
    function Read-Host { return $script:harnessFixtureAnswers.Dequeue() }
    $script:harnessFixtureAnswers.Enqueue('')
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $inventory) -eq 'Keep') 'Interactive default did not keep existing harness'
    $script:harnessFixtureAnswers.Enqueue('invalid')
    $script:harnessFixtureAnswers.Enqueue('2')
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $inventory) -eq 'Replace') 'Interactive replacement did not accept explicit option 2'
    Remove-Item -LiteralPath Function:\Read-Host
    $assertions += 4

    $projectRelativeFiles = @('CLAUDE.md', 'CLAUDE.local.md', '.claude\CLAUDE.md', '.claude\CLAUDE.local.md', '.claude\rules\quality\review.md')
    foreach ($relative in $projectRelativeFiles) { Write-CompanyAgentUtf8File -Path (Join-Path $projectRoot $relative) -Content ("existing project: $relative") }
    foreach ($settingsName in @('settings.json', 'settings.local.json')) {
        Write-CompanyAgentJsonAtomic -Path (Join-Path $projectClaude $settingsName) -Value ([pscustomobject]@{
            model = 'preserve-project-model'; hooks = [pscustomobject]@{ SessionStart = @([pscustomobject]@{ matcher = ''; hooks = @([pscustomobject]@{ type = 'command'; command = 'echo fixture-super-secret' }) }) }
        })
    }
    $ancestorInstructions = Join-Path (Split-Path -Parent $projectRoot) 'CLAUDE.md'
    Write-CompanyAgentUtf8File -Path $ancestorInstructions -Content 'Ancestor rules must not become replacement targets'
    Write-CompanyAgentUtf8File -Path (Join-Path (Split-Path -Parent $projectRoot) '.claude\settings.json') -Content '{fixture-super-secret not a project setting'
    $before = Get-ExistingHarnessFixtureDigest -Root $fixtureRoot
    $projectInventory = Get-SetupExistingHarness @projectArgs
    Assert-ExistingHarness ($projectInventory.replacementFiles.Count -eq 5 -and $projectInventory.hookSettingsPaths.Count -eq 2) 'Project scope target list is incomplete'
    Assert-ExistingHarness ($projectInventory.scopeRoot -eq $projectRoot -and $projectInventory.projectRoot -eq $projectRoot) 'Project scope roots were not returned'
    foreach ($target in @($projectInventory.replacementFiles) + @($projectInventory.hookSettingsPaths)) {
        Assert-ExistingHarness (Test-SetupSameOrChildPath -Candidate $target -Parent $projectRoot) 'Inherited file became a replacement target'
    }
    Assert-ExistingHarness (@($projectInventory.inherited | Where-Object { $_.path -eq $ancestorInstructions }).Count -eq 1) 'Ancestor guidance was not reported as preserved'
    Assert-ExistingHarness (@($projectInventory.inherited | Where-Object { $_.path -eq (Join-Path $claudeRoot 'settings.json') }).Count -eq 1) 'User-wide settings were not flagged as inherited'
    Assert-ExistingHarness ((Get-ExistingHarnessFixtureDigest -Root $fixtureRoot) -ceq $before) 'Project inventory changed source content'
    $assertions += 12

    $emptyProject = Join-Path $fixtureRoot 'empty-project'
    New-CompanyAgentDirectory -Path $emptyProject
    $inheritedOnly = Get-SetupExistingHarness -Scope Project -ClaudeConfigRoot $claudeRoot -ProjectRoot $emptyProject
    Assert-ExistingHarness (-not $inheritedOnly.detected -and $inheritedOnly.inherited.Count -gt 0) 'Inherited-only project was treated as owning existing rules'
    $registered = Get-SetupExistingHarness -Scope Project -ClaudeConfigRoot $claudeRoot -ProjectRoot $emptyProject -ExistingRegistration ([pscustomobject]@{ userStateRoot = 'not-scanned'; private = 'fixture-super-secret' })
    Assert-ExistingHarness ($registered.detected -and $registered.items.Count -eq 1 -and $registered.replacementFiles.Count -eq 0 -and $registered.hookSettingsPaths.Count -eq 0) 'Existing Company Agent registration did not produce an update choice'
    Assert-ExistingHarness (($registered | ConvertTo-Json -Depth 10) -notmatch 'fixture-super-secret|not-scanned') 'Registration metadata leaked into inventory'
    $assertions += 3

    # Own registration is a different decision from replacing an unrelated
    # harness. It must not require reading private state to classify an update.
    $registration = [pscustomobject]@{
        coreVersion = '1.0.0'; knowledgeVersion = '2026.09.03'
        userStateRoot = 'not-scanned'; private = 'fixture-super-secret'
    }
    $before = Get-ExistingHarnessFixtureDigest -Root $fixtureRoot
    $ownedOnly = Get-SetupExistingHarness -Scope Project -ClaudeConfigRoot $claudeRoot -ProjectRoot $emptyProject -ExistingRegistration $registration
    $ownedWithCustom = Get-SetupExistingHarness @userArgs -ExistingRegistration $registration
    Assert-ExistingHarness ($ownedOnly.hasCompanyAgent -and -not $ownedOnly.hasCustomHarness) 'Owned-only registration was not distinguished from custom harness rules'
    Assert-ExistingHarness ($ownedWithCustom.hasCompanyAgent -and $ownedWithCustom.hasCustomHarness) 'Custom rules alongside Company Agent were not reported separately'
    Assert-ExistingHarness ($ownedOnly.installedCoreVersion -eq '1.0.0' -and $ownedOnly.installedKnowledgeVersion -eq '2026.09.03') 'Installed version display fields were not projected correctly'
    Assert-ExistingHarness (($ownedOnly | ConvertTo-Json -Depth 10) -notmatch 'fixture-super-secret|not-scanned') 'Owned installation inventory exposed private registration fields'
    $updateIntent = Get-SetupInstallationIntent -Inventory $ownedOnly -TargetCoreVersion '1.1.1' -TargetKnowledgeVersion '2026.09.03'
    Assert-ExistingHarness ($updateIntent.operation -eq 'update' -and $updateIntent.hasCompanyAgent -and $updateIntent.previousCoreVersion -eq '1.0.0' -and $updateIntent.previousKnowledgeVersion -eq '2026.09.03' -and $updateIntent.coreVersion -eq '1.1.1') 'Upgrade intent lost the installed and target versions'
    $reapplyIntent = Get-SetupInstallationIntent -Inventory $ownedOnly -TargetCoreVersion '1.0.0' -TargetKnowledgeVersion '2026.09.03'
    Assert-ExistingHarness ($reapplyIntent.operation -eq 'reapply') 'An identical package was displayed as a new upgrade'
    $knowledgeIntent = Get-SetupInstallationIntent -Inventory $ownedOnly -TargetCoreVersion '1.0.0' -TargetKnowledgeVersion '2026.09.04'
    Assert-ExistingHarness ($knowledgeIntent.operation -eq 'update') 'A knowledge-only update was not classified as an update'
    Assert-ExistingHarnessRejected -Action { Get-SetupInstallationIntent -Inventory $ownedOnly -TargetCoreVersion '0.9.9' -TargetKnowledgeVersion '2026.09.03' } -Pattern 'older' -Message 'An older core package was accepted'
    Assert-ExistingHarnessRejected -Action { Get-SetupInstallationIntent -Inventory $ownedOnly -TargetCoreVersion '1.0.0' -TargetKnowledgeVersion '2026.09.02' } -Pattern 'older' -Message 'An older knowledge package with unchanged core was accepted'
    $numericOrdering = Get-SetupExistingHarness -Scope Project -ClaudeConfigRoot $claudeRoot -ProjectRoot $emptyProject -ExistingRegistration ([pscustomobject]@{ coreVersion = '1.10.0'; knowledgeVersion = '2026.09.03' })
    Assert-ExistingHarnessRejected -Action { Get-SetupInstallationIntent -Inventory $numericOrdering -TargetCoreVersion '1.2.0' -TargetKnowledgeVersion '2026.09.04' } -Pattern 'older' -Message 'Version comparison used lexical rather than numeric ordering'
    Assert-ExistingHarness ((Get-ExistingHarnessFixtureDigest -Root $fixtureRoot) -ceq $before) 'Version classification or downgrade rejection changed source files'
    Assert-ExistingHarness (($updateIntent | ConvertTo-Json -Depth 10) -notmatch 'fixture-super-secret|not-scanned') 'Update intent copied private registration data'
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $ownedOnly -Action Update -NonInteractive) -eq 'Update') 'Explicit owned update did not select Update'
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $ownedWithCustom -Action Update -NonInteractive) -eq 'Update') 'Custom rules alongside Company Agent forced replacement instead of update'
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $ownedWithCustom -Action Keep -NonInteractive) -eq 'Keep') 'Explicit Keep did not preserve an owned installation'
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $ownedWithCustom -Action Replace -NonInteractive) -eq 'Replace') 'Legacy explicit Replace is no longer supported for an owned installation'
    $assertions += 16

    function Read-Host { throw 'Read-Host must never be called in a noninteractive or dry update.' }
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $ownedOnly -NonInteractive -TargetCoreVersion '1.1.1' -TargetKnowledgeVersion '2026.09.03') -eq 'InputRequired') 'Owned noninteractive Ask silently updated'
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $ownedWithCustom -DryRun -TargetCoreVersion '1.1.1' -TargetKnowledgeVersion '2026.09.03') -eq 'InputRequired') 'Owned dry-run Ask tried to prompt or silently chose replacement'
    Remove-Item -LiteralPath Function:\Read-Host
    $script:harnessFixtureAnswers = New-Object Collections.Queue
    function Read-Host { return $script:harnessFixtureAnswers.Dequeue() }
    $script:harnessFixtureAnswers.Enqueue('')
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $ownedOnly -TargetCoreVersion '1.1.1' -TargetKnowledgeVersion '2026.09.03') -eq 'Update') 'Owned interactive default did not update'
    $script:harnessFixtureAnswers.Enqueue('2')
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $ownedWithCustom -TargetCoreVersion '1.1.1' -TargetKnowledgeVersion '2026.09.03') -eq 'Keep') 'Owned interactive Keep option did not preserve custom rules'
    $script:harnessFixtureAnswers.Enqueue('invalid')
    $script:harnessFixtureAnswers.Enqueue('1')
    Assert-ExistingHarness ((Resolve-SetupExistingHarnessAction -Inventory $ownedWithCustom -TargetCoreVersion '1.1.1' -TargetKnowledgeVersion '2026.09.03') -eq 'Update') 'Owned interactive update did not recover from an invalid answer'
    Remove-Item -LiteralPath Function:\Read-Host
    Assert-ExistingHarness ((Get-ExistingHarnessFixtureDigest -Root $fixtureRoot) -ceq $before) 'Interactive update choice changed rules, hooks, or settings before installation'
    $assertions += 6

    $previewInventory = Get-SetupExistingHarness -Scope Project -ClaudeConfigRoot $claudeRoot -ProjectRoot $emptyProject -ExistingRegistration ([pscustomobject]@{ coreVersion = 'preview-a'; knowledgeVersion = 'knowledge-preview'; private = 'fixture-super-secret' })
    Assert-ExistingHarness ($previewInventory.installedCoreVersion -eq 'preview-a' -and $previewInventory.installedKnowledgeVersion -eq 'knowledge-preview') 'A safe nonnumeric version label was discarded'
    $previewUpdate = Get-SetupInstallationIntent -Inventory $previewInventory -TargetCoreVersion 'preview-b' -TargetKnowledgeVersion 'knowledge-preview'
    Assert-ExistingHarness ($previewUpdate.operation -eq 'update') 'Nonnumeric labels were incorrectly assigned numeric ordering'
    $previewReapply = Get-SetupInstallationIntent -Inventory $previewInventory -TargetCoreVersion 'preview-a' -TargetKnowledgeVersion 'knowledge-preview'
    Assert-ExistingHarness ($previewReapply.operation -eq 'reapply') 'Identical nonnumeric labels did not produce reapply'
    $unknownVersion = Get-SetupInstallationIntent -Inventory $registered -TargetCoreVersion '1.1.1' -TargetKnowledgeVersion '2026.09.03'
    Assert-ExistingHarness ($unknownVersion.operation -eq 'update' -and $unknownVersion.hasCompanyAgent) 'Legacy registration without version fields no longer supports update'
    $unsafeVersion = Get-SetupExistingHarness -Scope Project -ClaudeConfigRoot $claudeRoot -ProjectRoot $emptyProject -ExistingRegistration ([pscustomobject]@{ coreVersion = "1.0.0`nfixture-super-secret"; knowledgeVersion = @{ private = 'fixture-super-secret' }; private = 'fixture-super-secret' })
    Assert-ExistingHarness (($unsafeVersion | ConvertTo-Json -Depth 10) -notmatch 'fixture-super-secret') 'Invalid version values leaked private or multiline metadata'
    Assert-ExistingHarness ((Get-ExistingHarnessFixtureDigest -Root $fixtureRoot) -ceq $before) 'Unknown or nonnumeric version inspection changed files'
    $assertions += 6

    Assert-ExistingHarnessRejected -Action { Get-SetupExistingHarness @userArgs -MaxSettingsBytes 8 } -Pattern 'cannot be safely inspected' -Message 'Settings size cap was not enforced'
    Assert-ExistingHarnessRejected -Action { Get-SetupExistingHarness @userArgs -MaxFiles 1 } -Pattern 'file limit' -Message 'Rule file count cap was not enforced'
    Assert-ExistingHarnessRejected -Action { Get-SetupExistingHarness @userArgs -MaxDepth 0 } -Pattern 'depth limit' -Message 'Rule directory depth cap was not enforced'
    Assert-ExistingHarnessRejected -Action { Get-SetupExistingHarness @userArgs -MaxVisited 1 } -Pattern 'traversal limit' -Message 'Rule traversal cap was not enforced'
    Write-CompanyAgentUtf8File -Path (Join-Path $projectClaude 'settings.local.json') -Content '{"hooks": "fixture-super-secret"
'
    Assert-ExistingHarnessRejected -Action { Get-SetupExistingHarness @projectArgs } -Pattern 'cannot be safely inspected' -Message 'Malformed selected project settings did not fail safely'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $projectClaude 'settings.local.json') -Value ([pscustomobject]@{ hooks = 'fixture-super-secret' })
    Assert-ExistingHarnessRejected -Action { Get-SetupExistingHarness @projectArgs } -Pattern 'cannot be safely inspected' -Message 'Malformed hook shape did not fail safely'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $projectClaude 'settings.local.json') -Value ([pscustomobject]@{ hooks = [pscustomobject]@{ Stop = @([pscustomobject]@{ hooks = @() }) } })
    $emptyHooks = Get-SetupExistingHarness @projectArgs
    Assert-ExistingHarness ($emptyHooks.hookSettingsPaths.Count -eq 1) 'An empty hook definition was treated as active'
    $assertions += 7

    $integerRoot = Join-Path $fixtureRoot 'integer-safety'
    $integerPath = Join-Path $integerRoot 'settings.json'
    New-CompanyAgentDirectory -Path $integerRoot
    $null = Assert-SetupNativeSettingsIntegerSafety -Paths @()
    $null = Assert-SetupNativeSettingsIntegerSafety -Paths @($null, '', (Join-Path $integerRoot 'missing.json'))
    Write-CompanyAgentUtf8File -Path $integerPath -Content '{"safe":[0,-0,9007199254740991,-9007199254740991,9.007199254740991e15,900719925474099100e-2,1.5,0.000000000000000001],"bigString":"90071992547409930000000000","hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo \\\"90071992547409931234567890\\\" and -9007199254740992"}]}]}}'
    $integerBefore = Get-ExistingHarnessFixtureDigest -Root $integerRoot
    $null = Assert-SetupNativeSettingsIntegerSafety -Paths @($integerPath)
    Assert-ExistingHarness ((Get-ExistingHarnessFixtureDigest -Root $integerRoot) -ceq $integerBefore) 'Safe integer preflight changed settings content or timestamps'
    $assertions += 3
    foreach ($literal in @('9007199254740992', '-9007199254740992', '9007199254740993', '9.007199254740993e15', '-9.007199254740993e15', '9007199254740993000e-3', '9007199254740993.000', '1e99999999999', ('9' * 131072))) {
        Write-CompanyAgentUtf8File -Path $integerPath -Content ('{"nested":{"array":[{"key":' + $literal + '}]},"private":"fixture-super-secret"}')
        $integerBefore = Get-ExistingHarnessFixtureDigest -Root $integerRoot
        Assert-ExistingHarnessRejected -Action { Assert-SetupNativeSettingsIntegerSafety -Paths @($integerPath) } -Pattern 'Unsafe integer' -Message 'Unsafe native JSON integer was accepted'
        Assert-ExistingHarness ((Get-ExistingHarnessFixtureDigest -Root $integerRoot) -ceq $integerBefore) 'Rejected integer preflight changed original settings'
        $assertions += 2
    }
    # Fractions are deliberately not claimed to be arbitrary-precision safe by
    # this integer-only check; decimal/exponent integral forms above are checked.
    Write-CompanyAgentUtf8File -Path $integerPath -Content '{"fraction":9007199254740992.5,"ordinaryExponent":1e-12,"zeroExponent":0e1000}'
    $null = Assert-SetupNativeSettingsIntegerSafety -Paths @($integerPath)
    $assertions++
    Write-CompanyAgentUtf8File -Path $integerPath -Content '{"private":"fixture-super-secret" malformed}'
    Assert-ExistingHarnessRejected -Action { Assert-SetupNativeSettingsIntegerSafety -Paths @($integerPath) } -Pattern 'cannot be safely inspected' -Message 'Malformed JSON was accepted by integer preflight'
    Write-CompanyAgentUtf8File -Path $integerPath -Content '{"private":"fixture-super-secret","safe":42}'
    Assert-ExistingHarnessRejected -Action { Assert-SetupNativeSettingsIntegerSafety -Paths @($integerPath) -MaxBytes 8 } -Pattern 'cannot be safely inspected' -Message 'Integer preflight settings size cap was not enforced'
    [IO.File]::WriteAllBytes($integerPath, [byte[]]@(0x7B, 0x22, 0x78, 0x22, 0x3A, 0x22, 0xFF, 0x22, 0x7D))
    Assert-ExistingHarnessRejected -Action { Assert-SetupNativeSettingsIntegerSafety -Paths @($integerPath) } -Pattern 'cannot be safely inspected' -Message 'Invalid UTF-8 was accepted by integer preflight'
    $assertions += 3

    $outside = Join-Path $fixtureRoot 'outside'
    New-CompanyAgentDirectory -Path $outside
    Write-CompanyAgentUtf8File -Path (Join-Path $outside 'outside.md') -Content 'Outside fixture rule'
    $junction = Join-Path $claudeRoot 'rules\linked-outside'
    New-Item -ItemType Junction -Path $junction -Value $outside | Out-Null
    $null = $junctions.Add($junction)
    Assert-ExistingHarnessRejected -Action { Get-SetupExistingHarness @userArgs } -Pattern 'junction|symbolic|reparse' -Message 'Rule junction was followed'
    $parentJunction = Join-Path $fixtureRoot 'linked-config'
    New-Item -ItemType Junction -Path $parentJunction -Value $claudeRoot | Out-Null
    $null = $junctions.Add($parentJunction)
    Assert-ExistingHarnessRejected -Action { Get-SetupExistingHarness -Scope User -ClaudeConfigRoot $parentJunction } -Pattern 'junction|symbolic|reparse' -Message 'Selected root junction was followed'
    $assertions += 2

    [pscustomobject]@{ status = 'passed'; assertions = $assertions; readonly = $true; fixtureRoot = $fixtureRoot } | ConvertTo-Json
}
finally {
    if (Test-Path -LiteralPath Function:\Read-Host) { Remove-Item -LiteralPath Function:\Read-Host }
    foreach ($junction in @($junctions.ToArray())) {
        $item = Get-Item -LiteralPath $junction -Force -ErrorAction SilentlyContinue
        if ($null -ne $item) {
            if (-not (Test-SetupSameOrChildPath -Candidate $item.FullName -Parent $fixtureFull) -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) { throw 'Unsafe harness-inventory junction cleanup target.' }
            [IO.Directory]::Delete($item.FullName)
        }
    }
    if (-not $KeepTestDirectory -and (Test-Path -LiteralPath $fixtureRoot)) {
        $actual = [IO.Path]::GetFullPath($fixtureRoot)
        $expectedParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([char[]]@('\', '/'))
        if ((Split-Path -Parent $actual).TrimEnd([char[]]@('\', '/')) -ine $expectedParent -or (Split-Path -Leaf $actual) -notlike 'CompanyAgent-ExistingHarness-*') { throw 'Unsafe harness-inventory fixture cleanup target.' }
        Remove-Item -LiteralPath $actual -Recurse -Force
    }
}
