[CmdletBinding()]
param(
    [string] $PythonCommand = 'python',
    [string] $ClaudeCommand = 'claude',
    [switch] $KeepTestDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('CompanyAgent-ScopedUserContext-' + [guid]::NewGuid().ToString('N'))
$savedConfig = $env:CLAUDE_CONFIG_DIR
$savedForce = $env:CLAUDE_CODE_SUBAGENT_MODEL
$savedForce2 = $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE
$assertions = 0
$caseCount = 0

function Assert-ScopedContext {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "Scoped user context regression failed: $Message" }
    $script:assertions++
}

function Get-ScopedContextSnapshot {
    param([string] $Root)
    $records = @(Get-ChildItem -LiteralPath $Root -Recurse -Force | Sort-Object FullName | ForEach-Object {
        $relative = $_.FullName.Substring($Root.Length)
        if ($_.PSIsContainer) { 'D:' + $relative }
        else { 'F:' + $relative + ':' + (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
    })
    return $records -join "`n"
}

function Get-ScopedContextProjectHash {
    param([string] $Path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($Path.ToUpperInvariant())))).Replace('-', '').ToLowerInvariant().Substring(0, 16)
    }
    finally { $hasher.Dispose() }
}

function New-ScopedContextFixture {
    param([string] $Name, [string] $Scope = 'User')
    $script:caseCount++
    $root = Join-Path $testRoot ('case-' + $script:caseCount + '-' + $Name)
    $profile = Join-Path $root 'employee'
    $localData = Join-Path $profile 'AppData\Local'
    $config = Join-Path $profile '.claude'
    $project = Join-Path $profile 'Projects\Example'
    foreach ($directory in @($localData, $config, $project)) { New-CompanyAgentDirectory -Path $directory }
    Write-CompanyAgentUtf8File -Path (Join-Path $config 'settings.json') -Content '{"model":"existing-medium"}'
    Write-CompanyAgentUtf8File -Path (Join-Path $project 'personal-work.txt') -Content 'Existing project work must remain byte-for-byte unchanged.'
    $scopeRelative = 'user'
    if ($Scope -eq 'Project') { $scopeRelative = Join-Path 'projects' (Get-ScopedContextProjectHash -Path $project) }
    $parameters = @{
        BundleRoot = $bundleRoot; Scope = $Scope; PythonCommand = $pythonExecutable
        ClaudeCommand = $claudeExecutable; NonInteractive = $true; DryRun = $true
        # Only the fixture observation provider differs from the real package.
        # Identity and prerequisite guards remain enabled throughout this test.
        SkipBundleVerification = $true; SkillConflictAction = 'KeepCurrent'
    }
    if ($Scope -eq 'Project') { $parameters.ProjectRoot = $project }
    $observation = [ordered]@{
        sid = 'S-1-5-21-101-202-303-1001'; accountName = 'CORP\employee'
        sessionId = 8; sessionSid = 'S-1-5-21-101-202-303-1001'; sessionAccountName = 'CORP\employee'
        isService = $false; isInteractive = $true; isAuthenticated = $true; isAdministrator = $true
        userProfile = $profile; localAppData = $localData
        environmentUserProfile = $profile; environmentLocalAppData = $localData
    }
    return [pscustomobject]@{
        root = $root; profile = $profile; localData = $localData; config = $config; project = $project
        scope = $Scope; parameters = $parameters; observation = $observation; throwObservation = $false
        defaultState = Join-Path (Join-Path $localData 'CompanyAgent\states') $scopeRelative
        backup = Join-Path $localData 'CompanyAgent-Backups'
        registration = Join-Path (Join-Path (Join-Path $localData 'CompanyAgent\installations') $scopeRelative) 'company-agent-install.json'
        profiles = @(
            [pscustomobject]@{ sid = $observation.sid; path = $profile }
            [pscustomobject]@{ sid = 'S-1-5-21-101-202-303-1002'; path = (Join-Path $root 'other-employee') }
        )
    }
}

function Set-ScopedContextObservation {
    param([object] $Fixture)
    Write-CompanyAgentUtf8File -Path $observationPath -Content (ConvertTo-Json -Depth 12 -InputObject @{
        observation = $Fixture.observation; profiles = $Fixture.profiles; throwObservation = $Fixture.throwObservation
    })
}

function Invoke-ScopedContextDryRun {
    param([object] $Fixture)
    Assert-ScopedContext (-not $Fixture.parameters.ContainsKey('SkipAdminCheck')) 'Fixture bypassed the user context guard'
    Assert-ScopedContext (-not $Fixture.parameters.ContainsKey('SkipPrerequisiteCheck')) 'Fixture bypassed the real runtime prerequisites'
    Set-ScopedContextObservation -Fixture $Fixture
    $before = Get-ScopedContextSnapshot -Root $Fixture.root
    $parameters = $Fixture.parameters
    $result = & $setup @parameters
    Assert-ScopedContext ($result.status -eq 'dry-run') ('Preflight did not finish for ' + $Fixture.scope)
    Assert-ScopedContext ($result.userContext.verified -and $result.userContext.isAdministrator) 'Same-user elevated context was not verified'
    Assert-ScopedContext ($result.userContext.sid -ceq $Fixture.observation.sid) 'Verified identity changed unexpectedly'
    Assert-ScopedContext ($result.userContext.userProfile -ieq $Fixture.profile) 'Installer did not use the verified profile'
    Assert-ScopedContext ($result.claudeCommand -ieq $claudeExecutable) 'Installer did not use the explicit existing Claude executable'
    Assert-ScopedContext ($result.pythonCommand -ieq $pythonExecutable) 'Installer did not use the explicit existing Python executable'
    Assert-ScopedContext (-not $result.needsElevation) 'User/project installation requested an elevation handoff'
    Assert-ScopedContext ((Get-ScopedContextSnapshot -Root $Fixture.root) -ceq $before) 'Dry-run changed the fixture profile or project'
    Assert-ScopedContext (-not (Test-Path -LiteralPath $Fixture.backup)) 'Dry-run created a backup directory'
    Assert-ScopedContext (-not (Test-Path -LiteralPath (Join-Path $Fixture.localData 'CompanyAgent-Distribution'))) 'Dry-run created a distribution directory'
    return $result
}

function Get-ScopedContextUninstallParameters {
    param([object] $Fixture)
    $parameters = @{ Scope = $Fixture.scope; ClaudeCommand = $claudeExecutable; NonInteractive = $true; DryRun = $true }
    if ($Fixture.scope -eq 'Project') { $parameters.ProjectRoot = $Fixture.project }
    return $parameters
}

function Invoke-ScopedContextUninstallDryRun {
    param([object] $Fixture, [string] $ExpectedState)
    Set-ScopedContextObservation -Fixture $Fixture
    $before = Get-ScopedContextSnapshot -Root $Fixture.root
    $parameters = Get-ScopedContextUninstallParameters -Fixture $Fixture
    Assert-ScopedContext (-not $parameters.ContainsKey('SkipAdminCheck')) 'Uninstall bypassed the user context guard'
    $result = & $uninstall @parameters
    Assert-ScopedContext ($result.status -eq 'dry-run') 'Same-user elevated uninstall preflight did not finish'
    Assert-ScopedContext ($result.preservedUserStateRoot -ieq $ExpectedState) 'Uninstall did not preserve the recorded custom personal state'
    Assert-ScopedContext ($result.registrationPath -ieq $Fixture.registration) 'Uninstall did not use the verified account registration'
    Assert-ScopedContext ((Get-ScopedContextSnapshot -Root $Fixture.root) -ceq $before) 'Uninstall dry-run changed the fixture profile or project'
    Assert-ScopedContext (-not (Test-Path -LiteralPath $Fixture.backup)) 'Uninstall dry-run created a backup directory'
}

function Assert-ScopedContextRejected {
    param([object] $Fixture, [string] $Pattern, [ValidateSet('Install', 'Uninstall')] [string] $Operation = 'Install')
    $parameters = $Fixture.parameters
    $entryPoint = $setup
    if ($Operation -eq 'Uninstall') {
        $parameters = Get-ScopedContextUninstallParameters -Fixture $Fixture
        $entryPoint = $uninstall
    }
    Assert-ScopedContext (-not $parameters.ContainsKey('SkipAdminCheck')) 'Negative case bypassed the user context guard'
    Set-ScopedContextObservation -Fixture $Fixture
    $before = Get-ScopedContextSnapshot -Root $Fixture.root
    $message = ''
    try { $null = & $entryPoint @parameters }
    catch { $message = $_.Exception.Message }
    Assert-ScopedContext ($message -match $Pattern) ('Expected rejection ' + $Pattern + ', received: ' + $message)
    Assert-ScopedContext ((Get-ScopedContextSnapshot -Root $Fixture.root) -ceq $before) 'Rejected preflight changed existing files or directories'
    Assert-ScopedContext (-not (Test-Path -LiteralPath $Fixture.backup)) 'Rejected preflight created a backup directory'
    Assert-ScopedContext (-not (Test-Path -LiteralPath (Join-Path $Fixture.localData 'CompanyAgent-Distribution'))) 'Rejected preflight created a distribution directory'
}

try {
    New-CompanyAgentDirectory -Path $testRoot
    $env:CLAUDE_CONFIG_DIR = $null
    $env:CLAUDE_CODE_SUBAGENT_MODEL = $null
    $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE = $null
    $pythonExecutable = [string](& $PythonCommand -I -X utf8 -B -c 'import sys; print(sys.executable)')
    if ($LASTEXITCODE -ne 0) { throw 'A working Python 3.11+ is required for this regression.' }
    $pythonExecutable = $pythonExecutable.Trim()
    $claudeInfo = Get-Command $ClaudeCommand -ErrorAction Stop | Select-Object -First 1
    $claudeExecutable = $claudeInfo.Source
    if ([string]::IsNullOrWhiteSpace($claudeExecutable)) { $claudeExecutable = $claudeInfo.Definition }
    if (-not (Test-Path -LiteralPath $claudeExecutable -PathType Leaf)) { throw 'This regression requires an existing Claude Code executable.' }
    $sourceRoot = Split-Path -Parent $PSScriptRoot
    $plugin = Read-CompanyAgentJson -Path (Join-Path $sourceRoot 'company-agent-plugin\.claude-plugin\plugin.json')
    $knowledge = Read-CompanyAgentJson -Path (Join-Path $sourceRoot 'corporate-knowledge\pack.json')
    $bundleZip = Join-Path $testRoot 'fixture.zip'
    $null = & (Join-Path $PSScriptRoot 'New-OfflineBundle.ps1') -SourceRoot $sourceRoot -CoreVersion $plugin.version -KnowledgeVersion $knowledge.version -OutputPath $bundleZip -SkipSourceValidation
    $bundleRoot = Join-Path $testRoot 'bundle'
    Expand-Archive -LiteralPath $bundleZip -DestinationPath $bundleRoot
    $setup = Join-Path $bundleRoot 'deploy\Setup-CompanyAgent.ps1'
    $uninstall = Join-Path $bundleRoot 'deploy\Uninstall-ScopedCompanyAgent.ps1'
    $observationPath = Join-Path $bundleRoot 'deploy\fixture-user-context.json'
    $fixtureHelper = Join-Path $bundleRoot 'deploy\CompanyAgent.UserContext.ps1'
    $sourceHelper = Join-Path $PSScriptRoot 'CompanyAgent.UserContext.ps1'
    $sourceHash = (Get-FileHash -LiteralPath $sourceHelper -Algorithm SHA256).Hash
    # Replace only the OS observation boundaries in the extracted TEMP fixture.
    # There is deliberately no mock SID or bypass switch in production calls.
    $stub = @'

function Get-SetupUserContextObservation {
    $fixture = [IO.File]::ReadAllText('__OBSERVATION_PATH__') | ConvertFrom-Json
    if ($fixture.throwObservation) { throw 'Injected read-only Windows observation failure.' }
    return $fixture.observation
}
function Get-SetupRegisteredUserProfileRoots {
    $fixture = [IO.File]::ReadAllText('__OBSERVATION_PATH__') | ConvertFrom-Json
    return @($fixture.profiles)
}
'@.Replace('__OBSERVATION_PATH__', $observationPath.Replace("'", "''"))
    Write-CompanyAgentUtf8File -Path $fixtureHelper -Content ([IO.File]::ReadAllText($fixtureHelper) + $stub)

    foreach ($scope in @('User', 'Project')) {
        $fixture = New-ScopedContextFixture -Name 'same-user-elevated' -Scope $scope
        $result = Invoke-ScopedContextDryRun -Fixture $fixture
        Assert-ScopedContext ($result.userStateRoot -ieq $fixture.defaultState) 'New installation selected an unexpected personal state path'
        Assert-ScopedContext ($result.claudeConfigRoot -ieq $fixture.config) 'New installation did not select the verified user configuration'
        Assert-ScopedContext (-not (Test-Path -LiteralPath $fixture.defaultState)) 'New-install dry-run created personal state'
        Assert-ScopedContext (-not (Test-Path -LiteralPath $fixture.registration)) 'New-install dry-run created a registration'
        Assert-ScopedContext ($result.operation -eq 'install') 'New install was misidentified as an update'
    }

    foreach ($scenario in @('different-sid', 'session-zero', 'unknown-session', 'unknown-observation', 'profile-mismatch', 'local-data-mismatch', 'explicit-profile-mismatch', 'foreign-config')) {
        $fixture = New-ScopedContextFixture -Name $scenario
        $pattern = ''
        switch ($scenario) {
            'different-sid' { $fixture.observation.sessionSid = 'S-1-5-21-101-202-303-1002'; $pattern = 'USER_CONTEXT_DIFFERENT_ACCOUNT' }
            'session-zero' { $fixture.observation.sessionId = 0; $pattern = 'USER_CONTEXT_NONINTERACTIVE' }
            'unknown-session' { $fixture.observation.sessionSid = ''; $pattern = 'USER_CONTEXT_UNVERIFIED' }
            'unknown-observation' { $fixture.throwObservation = $true; $pattern = 'USER_CONTEXT_UNVERIFIED' }
            'profile-mismatch' { $fixture.observation.environmentUserProfile = Join-Path $fixture.root 'another-profile'; $pattern = 'USER_CONTEXT_PATH_MISMATCH' }
            'local-data-mismatch' { $fixture.observation.environmentLocalAppData = Join-Path $fixture.root 'another-local-data'; $pattern = 'USER_CONTEXT_PATH_MISMATCH' }
            'explicit-profile-mismatch' { $fixture.parameters.InvokingUserProfile = Join-Path $fixture.root 'another-profile'; $pattern = 'USER_CONTEXT_PATH_MISMATCH' }
            'foreign-config' { $fixture.parameters.ClaudeConfigRoot = Join-Path $fixture.profiles[1].path '.claude'; $pattern = 'USER_CONTEXT_FOREIGN_PROFILE' }
        }
        Assert-ScopedContextRejected -Fixture $fixture -Pattern $pattern
        Assert-ScopedContext (-not (Test-Path -LiteralPath $fixture.defaultState)) 'Rejected new install created personal state'
    }

    foreach ($scope in @('User', 'Project')) {
        $fixture = New-ScopedContextFixture -Name 'recorded-custom-profile' -Scope $scope
        $customConfig = Join-Path $fixture.profile 'My Claude Configuration'
        $customState = Join-Path $fixture.profile 'My Company Agent Memory'
        foreach ($directory in @($customConfig, $customState, (Split-Path -Parent $fixture.registration))) { New-CompanyAgentDirectory -Path $directory }
        Write-CompanyAgentUtf8File -Path (Join-Path $customConfig 'settings.json') -Content '{"model":"existing-large"}'
        Write-CompanyAgentUtf8File -Path (Join-Path $customState 'personal-memory.md') -Content 'Existing personal learning is retained.'
        $record = @{
            schemaVersion = 1; scope = $scope; nativeClaudeScope = $(if ($scope -eq 'Project') { 'local' } else { 'user' })
            pluginId = 'company-agent@company-agent-local'; coreVersion = $plugin.version; knowledgeVersion = $knowledge.version
            projectRoot = $(if ($scope -eq 'Project') { $fixture.project } else { '' })
            claudeConfigRoot = $customConfig; claudeConfigDirOverride = $true; userStateRoot = $customState
        }
        Write-CompanyAgentUtf8File -Path $fixture.registration -Content (ConvertTo-Json -Depth 8 -InputObject $record)
        $fixture.parameters.ExistingHarnessAction = 'Update'
        $result = Invoke-ScopedContextDryRun -Fixture $fixture
        Assert-ScopedContext ($result.claudeConfigRoot -ieq $customConfig) 'Recorded custom Claude configuration was not reused automatically'
        Assert-ScopedContext ($result.settingsPath -ieq $(if ($scope -eq 'Project') { Join-Path $fixture.project '.claude\settings.local.json' } else { Join-Path $customConfig 'settings.json' })) 'Update selected the wrong scoped settings file'
        Assert-ScopedContext ($result.userStateRoot -ieq $customState) 'Update moved the recorded personal state path'
        Assert-ScopedContext ($result.operation -eq 'reapply') 'Existing same-version installation was not recognized'
        Assert-ScopedContext (-not (Test-Path -LiteralPath $fixture.defaultState)) 'Update created an empty default personal state instead of reusing existing memory'

        $fixture.parameters.ClaudeConfigRoot = $fixture.config
        Assert-ScopedContextRejected -Fixture $fixture -Pattern 'another Claude configuration profile'
        $fixture.parameters.Remove('ClaudeConfigRoot')
        $env:CLAUDE_CONFIG_DIR = $fixture.config
        try { Assert-ScopedContextRejected -Fixture $fixture -Pattern 'another Claude configuration profile' }
        finally { $env:CLAUDE_CONFIG_DIR = $null }

        Invoke-ScopedContextUninstallDryRun -Fixture $fixture -ExpectedState $customState
        $fixture.observation.sessionSid = 'S-1-5-21-101-202-303-1002'
        Assert-ScopedContextRejected -Fixture $fixture -Pattern 'USER_CONTEXT_DIFFERENT_ACCOUNT' -Operation Uninstall
        $fixture.observation.sessionSid = $fixture.observation.sid

        # A false override with a custom location would make native Claude
        # uninstall affect a different (default) profile; reject before writes.
        $record.claudeConfigDirOverride = $false
        Write-CompanyAgentUtf8File -Path $fixture.registration -Content (ConvertTo-Json -Depth 8 -InputObject $record)
        Assert-ScopedContextRejected -Fixture $fixture -Pattern 'inconsistent custom Claude configuration path' -Operation Uninstall
        $record.claudeConfigDirOverride = $true
        Write-CompanyAgentUtf8File -Path $fixture.registration -Content (ConvertTo-Json -Depth 8 -InputObject $record)

        # The record is recovered after the initial default-config validation.
        # Its child paths must receive reparse-point checks again before backup.
        $junctionTarget = Join-Path $fixture.root 'junction-plugin-target'
        $junction = Join-Path $customConfig 'plugins'
        New-CompanyAgentDirectory -Path $junctionTarget
        Write-CompanyAgentUtf8File -Path (Join-Path $junctionTarget 'installed_plugins.json') -Content '{"version":2,"plugins":{}}'
        try {
            $null = New-Item -ItemType Junction -Path $junction -Target $junctionTarget
            Assert-ScopedContextRejected -Fixture $fixture -Pattern 'reparse point|junction|symbolic link' -Operation Uninstall
        }
        finally {
            if (Test-Path -LiteralPath $junction) {
                $resolvedJunction = [IO.Path]::GetFullPath($junction)
                if (-not $resolvedJunction.StartsWith($fixture.root + '\', [StringComparison]::OrdinalIgnoreCase) -or
                    ((Get-Item -LiteralPath $resolvedJunction -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
                    throw 'Unsafe fixture junction cleanup target.'
                }
                # Nonrecursive unlink only: do not traverse or remove its target.
                [IO.Directory]::Delete($resolvedJunction)
            }
        }
    }
    Assert-ScopedContext ((Get-FileHash -LiteralPath $sourceHelper -Algorithm SHA256).Hash -ceq $sourceHash) 'Production helper was changed by the fixture override'
    [pscustomobject]@{
        status = 'pass'; assertions = $assertions; cases = $caseCount
        sameUserElevated = 'User and Project'; guardBypass = $false; nativePrerequisitesChecked = $true
        registeredCustomProfileReused = $true; personalStatePreserved = $true; preflightWrites = $false
        uninstallContextAndSavedConfigGuarded = $true
        testRoot = $testRoot
    }
}
finally {
    $env:CLAUDE_CONFIG_DIR = $savedConfig
    $env:CLAUDE_CODE_SUBAGENT_MODEL = $savedForce
    $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE = $savedForce2
    if (-not $KeepTestDirectory -and (Test-Path -LiteralPath $testRoot)) {
        $fullTestRoot = [IO.Path]::GetFullPath($testRoot)
        $tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
        if ((Split-Path -Parent $fullTestRoot) -ine $tempBase -or (Split-Path -Leaf $fullTestRoot) -notlike 'CompanyAgent-ScopedUserContext-*') { throw 'Unsafe test cleanup target.' }
        Remove-Item -LiteralPath $fullTestRoot -Recurse -Force
    }
}
