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
    $assertions += 3

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
    $assertions += 6

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
