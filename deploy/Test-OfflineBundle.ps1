[CmdletBinding()]
param([switch] $KeepArtifacts)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')

function Assert-OfflineBundle {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "Offline bundle regression failed: $Message" }
}

function Assert-BundleBuildRejected {
    param([hashtable] $Parameters, [string] $MessagePattern)
    $rejected = $false
    try { $null = & $buildScript @Parameters }
    catch {
        if ($_.Exception.Message -notmatch $MessagePattern) { throw }
        $rejected = $true
    }
    Assert-OfflineBundle $rejected "Expected build rejection matching: $MessagePattern"
}

function Assert-EmployeeBundle {
    param([string] $ZipPath, [string] $ExpandedPath)
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $ExpandedPath
    $manifest = Test-CompanyAgentBundleIntegrity -BundleRoot $ExpandedPath
    Assert-OfflineBundle ($manifest.runtime.mode -ceq 'external') 'Default runtime mode is not external.'
    Assert-OfflineBundle ($manifest.runtime.minimumVersion -ceq '3.11') 'Minimum Python version is not 3.11.'
    Assert-OfflineBundle ($manifest.runtime.command -ceq 'python') 'Default Python command is not recorded.'
    $plugin = Join-Path $ExpandedPath 'payload\core\plugin'
    $check = & python -X utf8 -B (Join-Path $sourceRoot 'scripts\harness_core\build-profile.py') --source-root $sourceRoot --destination $plugin --check 2>&1
    Assert-OfflineBundle ($LASTEXITCODE -eq 0) ('Installed file manifest differs: ' + ($check -join ' '))
    $profile = Read-CompanyAgentJson -Path (Join-Path $plugin 'resources\core-install.json')
    Assert-OfflineBundle ($profile.schemaVersion -eq 1 -and $profile.profile -ceq 'personal-harness') 'Personal harness profile marker is missing.'
    $skills = @(Get-ChildItem -LiteralPath (Join-Path $plugin 'skills') -Directory | Select-Object -ExpandProperty Name | Sort-Object)
    Assert-OfflineBundle (($skills -join ',') -ceq 'asset-factory,company-agent,personal-knowledge,personal-memory,self-learning') 'The core Skill boundary changed.'
    foreach ($removed in @('skills\html-report', 'skills\presentation', 'skills\file-organizer',
        'skills\excel-to-pipeline', 'skills\work-context-catalog', 'skills\web-interface',
        'skills\website-rebuild', 'skills\platform-mcp-builder', 'skills\karpathy-guidelines',
        'skills\new-functional-fixture', 'scripts\company_agent\future_engine.py',
        'scripts\company_agent\business.py', 'scripts\company_agent\business_artifacts.py',
        'scripts\company_agent\business_files.py', 'scripts\company_agent\excel_pipeline_command.py',
        'scripts\company_agent\artifact_delivery.py', 'scripts\company_agent\browser_workflow.py',
        'scripts\Confirm-BusinessAction.ps1', 'scripts\Invoke-BusinessPowerPoint.ps1',
        'agents\vision-worker.md', 'commands\vision-model.md', 'commands\business-check.md',
        'templates', 'runtime')) {
        Assert-OfflineBundle (-not (Test-Path -LiteralPath (Join-Path $plugin $removed))) "Functional payload leaked into the harness: $removed"
    }
    $engines = @(Get-ChildItem -LiteralPath $plugin -Recurse -File | Where-Object {
        $_.Name -match '^(ppt_|report_|presentation_|explanation_|vision_)' -or
        $_.Extension -iin @('.woff', '.woff2', '.ttf', '.otf', '.exe', '.dll', '.pyd', '.so', '.dylib')
    })
    Assert-OfflineBundle ($engines.Count -eq 0) 'Functional engines, fonts, or native binaries leaked into the core.'
    $requiredDeployFiles = @(
        'Diagnose-CompanyAgent.ps1', 'CompanyAgent.Common.ps1', 'ExistingHarness.ps1', 'HarnessReplacement.ps1',
        'CompanyAgent.UserContext.ps1', 'CompanyAgent.ClaudeDiscovery.ps1',
        'CompanyAgent.PluginCompatibility.ps1', 'CompanyAgent.ReadHook.ps1',
        'Initialize-CompanyAgentUser.ps1', 'Install-CompanyAgent.cmd', 'Install-CompanyAgent.ps1',
        'Install-ScopedCompanyAgent.ps1', 'Restore-PreviousHarness.ps1', 'Rollback-CompanyAgent.ps1',
        'Setup-CompanyAgent.ps1', 'Start-CompanyAgent.ps1', 'Uninstall-CompanyAgent.ps1',
        'Uninstall-ScopedCompanyAgent.ps1', 'Update-CompanyAgent.ps1'
    )
    foreach ($name in $requiredDeployFiles) {
        Assert-OfflineBundle (Test-Path -LiteralPath (Join-Path $ExpandedPath ('deploy\' + $name)) -PathType Leaf) "Deployment dependency is absent: $name"
    }
    Assert-OfflineBundle (@(Get-ChildItem -LiteralPath (Join-Path $ExpandedPath 'deploy') -File -Force).Count -eq $requiredDeployFiles.Count) 'Build/test tools leaked into the employee bundle.'
    foreach ($name in @('Install-CompanyAgent.cmd', 'Diagnose-CompanyAgent.cmd', 'INSTALL_WITH_CLAUDE.md')) {
        Assert-OfflineBundle (Test-Path -LiteralPath (Join-Path $ExpandedPath $name) -PathType Leaf) "Beginner entrypoint is absent: $name"
    }
    $standards = (Read-CompanyAgentJson -Path (Join-Path $ExpandedPath 'payload\config\managed.json')).workStandards
    Assert-OfflineBundle ($standards.revision -eq '1' -and @($standards.rules).Count -ge 2) 'Company standards did not reach the bundle.'
    $manuals = @('CLAUDE_CODE_BASICS.md', 'ONBOARDING_COURSE.md', 'USER_GUIDE.md',
        'COMPANY_AGENT_HANDBOOK.md', 'CLAUDE_CODE_COMMANDS.md', 'README.md', 'Company-Agent-사용자-안내서.html')
    Assert-OfflineBundle (@(Get-ChildItem -LiteralPath (Join-Path $plugin 'resources\manuals') -File).Count -eq $manuals.Count) 'Only current core manuals should be installed.'
    foreach ($manual in $manuals) {
        $expectedHash = (Get-FileHash -LiteralPath (Join-Path $sourceRoot ('docs\' + $manual)) -Algorithm SHA256).Hash
        Assert-OfflineBundle ((Get-FileHash -LiteralPath (Join-Path $ExpandedPath ('docs\' + $manual)) -Algorithm SHA256).Hash -ceq $expectedHash) 'Manual source changed during packaging.'
        Assert-OfflineBundle ((Get-FileHash -LiteralPath (Join-Path $plugin ('resources\manuals\' + $manual)) -Algorithm SHA256).Hash -ceq $expectedHash) 'Installed manual differs from source.'
    }
    foreach ($removed in @('HTML_DESIGN_SELECTION.md', 'BUSINESS_PILOT_GUIDE.md', 'DESIGN_TERMS.md',
        'PROJECT_HARNESS.md', 'MCP_CONTRACTS.md', 'COMPANY_PERSONAL_WORKFLOW.md', 'LEGACY_MACHINE_DEPLOYMENT.md',
        'LOCAL_WORKSPACE.md', 'WORKSPACE_STARTUP_DIAGNOSTIC.md', 'WORKSPACE_USER_GUIDE.html')) {
        Assert-OfflineBundle (-not (Test-Path -LiteralPath (Join-Path $ExpandedPath ('docs\' + $removed)))) "Non-core documentation leaked into the harness: $removed"
    }
    foreach ($required in @('DEPLOYMENT.md', 'STATE_PRESERVATION.md', 'SKILL_PRIORITY.md',
        'ADMIN_KNOWLEDGE_GUIDE.md', 'SELF_LEARNING.md', 'SKILL_CATALOG.md', 'HARNESS_CORE_SPLIT.md')) {
        Assert-OfflineBundle (Test-Path -LiteralPath (Join-Path $ExpandedPath ('docs\' + $required)) -PathType Leaf) "Core operation guide is absent: $required"
    }
    $developmentDocs = @(Get-ChildItem -LiteralPath (Join-Path $ExpandedPath 'docs') -File -Recurse | Where-Object {
        $_.Name -match '^(UPDATE_|AUDIT_|VALIDATION_)|_\d{4}-\d{2}-\d{2}\.md$'
    })
    Assert-OfflineBundle ($developmentDocs.Count -eq 0) 'Historical development records leaked into the employee bundle.'
    return $manifest
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$buildScript = Join-Path $PSScriptRoot 'New-OfflineBundle.ps1'
$temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([char[]]@('\', '/'))
$testRoot = Join-Path $temporaryBase ('CompanyAgent-OfflineBundleTest-' + [guid]::NewGuid().ToString('N'))
try {
    New-CompanyAgentDirectory -Path $testRoot
    $sourceRoot = Join-Path $testRoot 'source'
    foreach ($directory in @('deploy', 'company-agent-plugin', 'corporate-knowledge', 'docs', 'config', 'harness-core', 'scripts\harness_core')) {
        Copy-CompanyAgentDirectoryContents -Source (Join-Path $repositoryRoot $directory) -Destination (Join-Path $sourceRoot $directory)
    }
    foreach ($name in @('Install-CompanyAgent.cmd', 'Diagnose-CompanyAgent.cmd', 'INSTALL_WITH_CLAUDE.md')) {
        Copy-Item -LiteralPath (Join-Path $repositoryRoot $name) -Destination (Join-Path $sourceRoot $name)
    }
    Write-CompanyAgentUtf8File -Path (Join-Path $sourceRoot 'deploy\Future-AdminTool.ps1') -Content '# Must stay on the build PC.'
    $pluginRoot = Join-Path $sourceRoot 'company-agent-plugin'
    Write-CompanyAgentUtf8File -Path (Join-Path $pluginRoot 'skills\new-functional-fixture\SKILL.md') -Content 'Never install an unlisted Skill.'
    Write-CompanyAgentUtf8File -Path (Join-Path $pluginRoot 'scripts\company_agent\future_engine.py') -Content 'Never install an unlisted engine.'
    $pluginManifest = Read-CompanyAgentJson -Path (Join-Path $pluginRoot '.claude-plugin\plugin.json')
    $knowledgeManifest = Read-CompanyAgentJson -Path (Join-Path $sourceRoot 'corporate-knowledge\pack.json')
    $staleRuntime = Join-Path $pluginRoot 'runtime\python'
    foreach ($name in @('python.exe', 'python313.dll', '_ssl.pyd', 'python313.zip', 'stale-marker.txt')) {
        Write-CompanyAgentUtf8File -Path (Join-Path $staleRuntime $name) -Content 'Stale source runtime fixture; never ship this file.'
    }
    Write-CompanyAgentUtf8File -Path (Join-Path $pluginRoot 'runtime\other-stale-runtime.txt') -Content 'Omit the entire generated runtime directory.'
    # An existing build cache also must not select bundled mode implicitly.
    Write-CompanyAgentUtf8File -Path (Join-Path $sourceRoot 'build\runtime\python-3.13.15-embed-amd64.zip') -Content 'Not a verified runtime archive.'
    $runtimeBefore = @(Get-CompanyAgentTreeRecords -Root (Join-Path $pluginRoot 'runtime') | ConvertTo-Json -Depth 10 -Compress) -join ''
    # Stale source copies must not reintroduce retired entrypoints into new ZIPs.
    # These fixtures live only in the isolated source copy, never in the checkout.
    $legacyGuideHashes = @{}
    foreach ($relative in @('resources\first-work.html', 'resources\manuals\Company-Agent-Guide.html',
        'resources\manuals\Company-Agent-Handbook.html', 'resources\manuals\Company-Agent-Onboarding.html',
        'resources\manuals\Claude-Code-필수-사용법.html')) {
        $legacyGuide = Join-Path $pluginRoot $relative
        Write-CompanyAgentUtf8File -Path $legacyGuide -Content '<html><body>Retired guide fixture.</body></html>'
        $legacyGuideHashes[$legacyGuide] = (Get-FileHash -LiteralPath $legacyGuide -Algorithm SHA256).Hash
    }
    $common = @{
        SourceRoot = $sourceRoot
        CoreVersion = [string]$pluginManifest.version
        KnowledgeVersion = [string]$knowledgeManifest.version
        SkipSourceValidation = $true
    }

    $defaultZip = Join-Path $testRoot 'default.zip'
    $defaultResult = & $buildScript @common -OutputPath $defaultZip
    $defaultManifest = Assert-EmployeeBundle -ZipPath $defaultZip -ExpandedPath (Join-Path $testRoot 'default')
    Assert-OfflineBundle ($defaultResult.status -ceq 'created') 'Default build did not finish.'
    Assert-OfflineBundle ($defaultResult.fileCount -eq @($defaultManifest.files).Count) 'Result and manifest file counts differ.'
    Assert-OfflineBundle ((Get-FileHash -LiteralPath $defaultZip -Algorithm SHA256).Hash -ieq $defaultResult.sha256) 'Reported ZIP digest does not match.'
    $runtimeAfter = @(Get-CompanyAgentTreeRecords -Root (Join-Path $pluginRoot 'runtime') | ConvertTo-Json -Depth 10 -Compress) -join ''
    Assert-OfflineBundle ($runtimeBefore -ceq $runtimeAfter) 'Packaging changed or deleted source runtime files.'
    foreach ($legacyGuide in $legacyGuideHashes.Keys) {
        Assert-OfflineBundle ((Get-FileHash -LiteralPath $legacyGuide -Algorithm SHA256).Hash -ceq $legacyGuideHashes[$legacyGuide]) 'Packaging modified a retired source guide instead of excluding it.'
    }

    # Identical payload rebuilds remain possible; changed same-version payloads
    # are rejected even with Force, before damaging the previous output.
    $null = & $buildScript @common -OutputPath $defaultZip -Force
    $immutableHash = (Get-FileHash -LiteralPath $defaultZip -Algorithm SHA256).Hash
    $changedPayloadFixture = Join-Path $pluginRoot 'scripts\company_agent\__init__.py'
    $changedPayloadBytes = [IO.File]::ReadAllBytes($changedPayloadFixture)
    Write-CompanyAgentUtf8File -Path $changedPayloadFixture -Content '# This changed allowlisted payload needs a new CoreVersion.'
    try {
        $sameVersion = $common.Clone()
        $sameVersion.OutputPath = $defaultZip
        $sameVersion.Force = $true
        Assert-BundleBuildRejected $sameVersion 'Increase CoreVersion'
        Assert-OfflineBundle ((Get-FileHash -LiteralPath $defaultZip -Algorithm SHA256).Hash -ceq $immutableHash) 'Same-version rejection overwrote the existing ZIP.'
    }
    finally { [IO.File]::WriteAllBytes($changedPayloadFixture, $changedPayloadBytes) }

    $explicitZip = Join-Path $testRoot 'explicit-external.zip'
    $null = & $buildScript @common -OutputPath $explicitZip -WithoutBundledPython
    $explicitManifest = Assert-EmployeeBundle -ZipPath $explicitZip -ExpandedPath (Join-Path $testRoot 'explicit-external')
    Assert-OfflineBundle (($defaultManifest.files | ConvertTo-Json -Depth 10 -Compress) -ceq ($explicitManifest.files | ConvertTo-Json -Depth 10 -Compress)) 'Compatibility external flag changed packaged contents.'

    # Failed builds must preserve a pre-existing output even when Force is set.
    $sentinelZip = Join-Path $testRoot 'preserve-existing.zip'
    Write-CompanyAgentUtf8File -Path $sentinelZip -Content 'Existing output must survive rejected builds.'
    $sentinelHash = (Get-FileHash -LiteralPath $sentinelZip -Algorithm SHA256).Hash
    $installedGuide = Join-Path $pluginRoot 'resources\manuals\CLAUDE_CODE_COMMANDS.md'
    $guideBytes = [IO.File]::ReadAllBytes($installedGuide)
    try {
        Write-CompanyAgentUtf8File -Path $installedGuide -Content '# Stale manual fixture'
        $invalid = $common.Clone()
        $invalid.OutputPath = $sentinelZip
        $invalid.Force = $true
        Assert-BundleBuildRejected $invalid 'Packaged Markdown is out of date'
        Assert-OfflineBundle ((Get-FileHash -LiteralPath $sentinelZip -Algorithm SHA256).Hash -ceq $sentinelHash) 'Stale manual rejection overwrote the existing ZIP.'
        Remove-Item -LiteralPath $installedGuide -Force
        Assert-BundleBuildRejected $invalid 'Required Markdown manual is missing'
    }
    finally { [IO.File]::WriteAllBytes($installedGuide, $guideBytes) }
    $installedHtmlGuide = Join-Path $pluginRoot 'resources\manuals\Company-Agent-사용자-안내서.html'
    $htmlGuideBytes = [IO.File]::ReadAllBytes($installedHtmlGuide)
    try {
        Write-CompanyAgentUtf8File -Path $installedHtmlGuide -Content '<html><body>Stale unified guide.</body></html>'
        Assert-BundleBuildRejected $invalid 'Packaged unified HTML is out of date'
        Assert-OfflineBundle ((Get-FileHash -LiteralPath $sentinelZip -Algorithm SHA256).Hash -ceq $sentinelHash) 'Stale HTML rejection overwrote the existing ZIP.'
        Remove-Item -LiteralPath $installedHtmlGuide -Force
        Assert-BundleBuildRejected $invalid 'Required unified HTML manual is missing'
    }
    finally { [IO.File]::WriteAllBytes($installedHtmlGuide, $htmlGuideBytes) }
    $invalid = $common.Clone()
    $invalid.OutputPath = $sentinelZip
    $invalid.Force = $true
    $invalid.IncludeBundledPython = $true
    $invalid.WithoutBundledPython = $true
    Assert-BundleBuildRejected $invalid 'cannot be used together'
    foreach ($runtimeArgument in @('PythonRuntimeZip', 'PythonRuntimeSha256')) {
        $invalid = $common.Clone()
        $invalid.OutputPath = $sentinelZip
        $invalid.Force = $true
        $invalid[$runtimeArgument] = 'unrequested-runtime-input'
        Assert-BundleBuildRejected $invalid 'require -IncludeBundledPython'
        $invalid.WithoutBundledPython = $true
        Assert-BundleBuildRejected $invalid 'require -IncludeBundledPython'
    }
    $invalid = $common.Clone()
    $invalid.OutputPath = $sentinelZip
    $invalid.Force = $true
    $invalid.IncludeBundledPython = $true
    $invalid.PythonRuntimeZip = Join-Path $testRoot 'missing-runtime.zip'
    Assert-BundleBuildRejected $invalid 'optional bundled Python archive was not found'
    $invalid.Remove('PythonRuntimeZip')
    Assert-BundleBuildRejected $invalid 'archive hash does not match'

    $profileManifestPath = Join-Path $sourceRoot 'deploy\harness-core-manifest.json'
    $profileManifestBytes = [IO.File]::ReadAllBytes($profileManifestPath)
    foreach ($extension in @('.exe', '.DLL', '.pyd')) {
        $nativeFixture = Join-Path $pluginRoot ('unexpected-runtime' + $extension)
        Write-CompanyAgentUtf8File -Path $nativeFixture -Content 'An explicit native binary entry must fail closed.'
        try {
            $profileManifest = Read-CompanyAgentJson -Path $profileManifestPath
            $profileManifest.files = @($profileManifest.files) + @('unexpected-runtime' + $extension)
            Write-CompanyAgentJsonAtomic -Path $profileManifestPath -Value $profileManifest
            $invalid = $common.Clone()
            $invalid.OutputPath = $sentinelZip
            $invalid.Force = $true
            Assert-BundleBuildRejected $invalid 'cannot include binaries'
            Assert-OfflineBundle (Test-Path -LiteralPath $nativeFixture -PathType Leaf) 'Failed packaging removed the source binary fixture.'
        }
        finally {
            [IO.File]::WriteAllBytes($profileManifestPath, $profileManifestBytes)
            Remove-Item -LiteralPath $nativeFixture -Force
        }
    }

    Assert-OfflineBundle ((Get-FileHash -LiteralPath $sentinelZip -Algorithm SHA256).Hash -ceq $sentinelHash) 'Rejected build replaced an existing output.'

    [pscustomobject][ordered]@{
        status = 'passed'
        defaultRuntimeMode = $defaultManifest.runtime.mode
        minimumPythonVersion = $defaultManifest.runtime.minimumVersion
        productionDeployFiles = @($defaultManifest.files | Where-Object { $_.path -like 'deploy/*' }).Count
        testRoot = $testRoot
        artifactsKept = [bool]$KeepArtifacts
    }
}
finally {
    if (-not $KeepArtifacts -and (Test-Path -LiteralPath $testRoot)) {
        $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
        $tempPrefix = $temporaryBase + [IO.Path]::DirectorySeparatorChar
        if (-not $resolvedTestRoot.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
            (Split-Path -Leaf $resolvedTestRoot) -notlike 'CompanyAgent-OfflineBundleTest-*') {
            throw 'Refusing cleanup outside the owned temporary test directory.'
        }
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
