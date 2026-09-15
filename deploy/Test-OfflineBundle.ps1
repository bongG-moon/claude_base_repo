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
    foreach ($relative in @(
        'payload/core/plugin/THIRD_PARTY_NOTICES.md',
        'payload/core/plugin/scripts/company_agent/skill_catalog.py',
        'payload/core/plugin/scripts/company_agent/completion_feedback.py',
        'payload/core/plugin/scripts/company_agent/user_language.py',
        'payload/core/plugin/scripts/company_agent/report_design.py',
        'payload/core/plugin/scripts/company_agent/report_facts.py',
        'payload/core/plugin/scripts/company_agent/report_styles.py',
        'payload/core/plugin/skills/html-report/assets/design-picker.html',
        'payload/core/plugin/scripts/company_agent/presentation_design.py',
        'payload/core/plugin/scripts/company_agent/ppt_workflow.py',
        'payload/core/plugin/scripts/company_agent/runtime_diagnostics.py',
        'payload/core/plugin/scripts/Inspect-ClaudeRuntime.ps1',
        'payload/core/plugin/skills/presentation/references/sources.md',
        'docs/UPDATE_1.4.0.md',
        'docs/VALIDATION_1.4.0.md',
        'payload/core/plugin/scripts/company_agent/office_reader.py',
        'payload/core/plugin/scripts/Read-CompanyOffice.py',
        'payload/core/plugin/scripts/company_agent/office_pywin32.py',
        'payload/core/plugin/scripts/company_agent/office_structure.py',
        'payload/core/plugin/scripts/Read-CompanyExcel.py',
        'payload/core/plugin/scripts/company_agent/excel_xlwings.py',
        'payload/core/plugin/skills/office-reader/SKILL.md',
        'payload/core/plugin/skills/office-reader/references/reading.md',
        'payload/core/plugin/skills/office-reader/references/excel-fixed-recipe.md',
        'payload/core/plugin/skills/office-reader/references/office-fixed-recipe.md',
        'docs/UPDATE_1.4.1.md',
        'docs/VALIDATION_1.4.1.md',
        'docs/UPDATE_1.4.2.md',
        'docs/OFFICE_READ_TROUBLESHOOTING.md',
        'payload/core/plugin/skills/presentation/references/design-and-quality.md',
        'payload/core/plugin/skills/html-report/references/design-and-numbers.md',
        'docs/UPDATE_1.3.6.md',
        'docs/UPDATE_1.3.7.md',
        'docs/UPDATE_1.3.8.md',
        'docs/UPDATE_1.3.9.md',
        'docs/VALIDATION_1.3.9.md',
        'docs/HTML_DESIGN_SELECTION.md',
        'docs/VALIDATION_1.3.8.md',
        'docs/VALIDATION_1.3.7.md',
        'docs/Claude-Code-필수-사용법.html',
        'payload/core/plugin/skills/company-agent/references/completion.md',
        'deploy/CompanyAgent.PluginCompatibility.ps1',
        'docs/SKILL_CATALOG.md',
        'docs/UPDATE_1.3.3.md',
        'docs/UPDATE_1.3.4.md',
        'docs/UPDATE_1.3.5.md',
        'payload/core/plugin/skills/asset-factory/references/authoring.md',
        'payload/core/plugin/skills/asset-factory/references/windows-setup.md',
        'payload/core/plugin/skills/personal-knowledge/references/term-quality.md',
        'payload/core/plugin/skills/karpathy-guidelines/references/evidence-diagnosis.md',
        'docs/LEAN_SKILL_INTEGRATION.md'
    )) {
        Assert-OfflineBundle (Test-Path -LiteralPath (Join-Path $ExpandedPath $relative) -PathType Leaf) "Lean guidance/provenance is absent: $relative"
    }
    Assert-OfflineBundle ($manifest.runtime.description -match 'existing Python') 'External runtime requirement is not explained.'
    Assert-OfflineBundle (-not (Test-Path -LiteralPath (Join-Path $ExpandedPath 'payload\core\plugin\runtime'))) 'Source runtime directory leaked into the bundle.'
    $nativeFiles = @(Get-ChildItem -LiteralPath $ExpandedPath -Recurse -Force | Where-Object {
        -not $_.PSIsContainer -and $_.Extension -iin @('.exe', '.dll', '.pyd', '.so', '.dylib')
    })
    Assert-OfflineBundle ($nativeFiles.Count -eq 0) 'Employee bundle contains native binaries.'
    foreach ($name in @(
        'CompanyAgent.Common.ps1', 'ExistingHarness.ps1', 'HarnessReplacement.ps1',
        'CompanyAgent.UserContext.ps1', 'CompanyAgent.ClaudeDiscovery.ps1',
        'Initialize-CompanyAgentUser.ps1', 'Install-CompanyAgent.cmd', 'Install-CompanyAgent.ps1',
        'Install-ScopedCompanyAgent.ps1', 'Restore-PreviousHarness.ps1', 'Rollback-CompanyAgent.ps1',
        'Setup-CompanyAgent.ps1', 'Start-CompanyAgent.ps1', 'Uninstall-CompanyAgent.ps1',
        'Uninstall-ScopedCompanyAgent.ps1', 'Update-CompanyAgent.ps1'
    )) {
        Assert-OfflineBundle (Test-Path -LiteralPath (Join-Path $ExpandedPath ('deploy\' + $name)) -PathType Leaf) "Required deployment dependency is absent: $name"
    }
    $deployFiles = @(Get-ChildItem -LiteralPath (Join-Path $ExpandedPath 'deploy') -File -Force)
    Assert-OfflineBundle ($deployFiles.Count -eq 17) 'Unexpected deploy tools were included.'
    foreach ($name in @(
        'New-OfflineBundle.ps1', 'Get-EmbeddedPython.ps1', 'Test-DeploymentSmoke.ps1',
        'Test-ExistingHarness.ps1', 'Test-HarnessReplacement.ps1', 'Test-PersonalStateBackup.ps1',
        'Test-ScopedInstallSmoke.ps1', 'Test-OfflineBundle.ps1', 'Future-AdminTool.ps1'
    )) {
        Assert-OfflineBundle (-not (Test-Path -LiteralPath (Join-Path $ExpandedPath ('deploy\' + $name)))) "Build/test tool leaked into employee bundle: $name"
    }
    Assert-OfflineBundle (Test-Path -LiteralPath (Join-Path $ExpandedPath 'Install-CompanyAgent.cmd') -PathType Leaf) 'Root installer is missing.'
    Assert-OfflineBundle (Test-Path -LiteralPath (Join-Path $ExpandedPath 'INSTALL_WITH_CLAUDE.md') -PathType Leaf) 'Installation guide is missing.'
    foreach ($relative in @('docs\SELF_LEARNING.md', 'docs\USER_GUIDE.md', 'docs\BUSINESS_PILOT_GUIDE.md',
        'payload\core\plugin\scripts\company_agent\learning.py',
        'payload\core\plugin\commands\learning.md',
        'payload\core\plugin\commands\business-check.md',
        'payload\core\plugin\scripts\company_agent\business.py',
        'payload\core\plugin\scripts\company_agent\business_safety.py',
        'payload\core\plugin\scripts\company_agent\business_files.py',
        'payload\core\plugin\scripts\company_agent\business_mail.py',
        'payload\core\plugin\scripts\company_agent\business_artifacts.py',
        'payload\core\plugin\scripts\Confirm-BusinessAction.ps1',
        'payload\core\plugin\scripts\Invoke-BusinessOutlook.ps1',
        'payload\core\plugin\scripts\Invoke-BusinessPowerPoint.ps1',
        'payload\core\plugin\skills\file-organizer\SKILL.md',
        'payload\core\plugin\skills\outlook-assistant\SKILL.md',
        'payload\core\plugin\skills\html-report\SKILL.md',
        'payload\core\plugin\skills\presentation\SKILL.md',
        'payload\core\plugin\skills\company-agent\references\business-protection.md',
        'payload\core\plugin\templates\business\report.spec.json',
        'payload\core\plugin\skills\self-learning\SKILL.md')) {
        Assert-OfflineBundle (Test-Path -LiteralPath (Join-Path $ExpandedPath $relative) -PathType Leaf) "Business/learning/guide release file is missing: $relative"
    }
    $htmlGuides = @(Get-ChildItem -LiteralPath (Join-Path $ExpandedPath 'docs') -Filter 'Company-Agent-*.html' -File)
    Assert-OfflineBundle ($htmlGuides.Count -eq 2) 'Expected offline user guide and validation chat reader.'
    foreach ($htmlGuide in $htmlGuides) {
        Assert-OfflineBundle ((Get-FileHash -LiteralPath $htmlGuide.FullName -Algorithm SHA256).Hash -ceq
            (Get-FileHash -LiteralPath (Join-Path $sourceRoot ('docs\' + $htmlGuide.Name)) -Algorithm SHA256).Hash) 'HTML guide content changed during packaging.'
    }
    return $manifest
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$buildScript = Join-Path $PSScriptRoot 'New-OfflineBundle.ps1'
$temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([char[]]@('\', '/'))
$testRoot = Join-Path $temporaryBase ('CompanyAgent-OfflineBundleTest-' + [guid]::NewGuid().ToString('N'))
try {
    New-CompanyAgentDirectory -Path $testRoot
    $sourceRoot = Join-Path $testRoot 'source'
    foreach ($directory in @('deploy', 'company-agent-plugin', 'corporate-knowledge', 'docs')) {
        Copy-CompanyAgentDirectoryContents -Source (Join-Path $repositoryRoot $directory) -Destination (Join-Path $sourceRoot $directory)
    }
    foreach ($name in @('Install-CompanyAgent.cmd', 'INSTALL_WITH_CLAUDE.md')) {
        Copy-Item -LiteralPath (Join-Path $repositoryRoot $name) -Destination (Join-Path $sourceRoot $name)
    }
    Write-CompanyAgentUtf8File -Path (Join-Path $sourceRoot 'deploy\Future-AdminTool.ps1') -Content '# Must stay on the build PC.'
    $pluginRoot = Join-Path $sourceRoot 'company-agent-plugin'
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

    # Identical payload rebuilds remain possible; changed same-version payloads
    # are rejected even with Force, before damaging the previous output.
    $null = & $buildScript @common -OutputPath $defaultZip -Force
    $immutableHash = (Get-FileHash -LiteralPath $defaultZip -Algorithm SHA256).Hash
    $changedPayloadFixture = Join-Path $pluginRoot 'same-version-change.txt'
    Write-CompanyAgentUtf8File -Path $changedPayloadFixture -Content 'This payload needs a new CoreVersion.'
    try {
        $sameVersion = $common.Clone()
        $sameVersion.OutputPath = $defaultZip
        $sameVersion.Force = $true
        Assert-BundleBuildRejected $sameVersion 'Increase CoreVersion'
        Assert-OfflineBundle ((Get-FileHash -LiteralPath $defaultZip -Algorithm SHA256).Hash -ceq $immutableHash) 'Same-version rejection overwrote the existing ZIP.'
    }
    finally { Remove-Item -LiteralPath $changedPayloadFixture -Force }

    $explicitZip = Join-Path $testRoot 'explicit-external.zip'
    $null = & $buildScript @common -OutputPath $explicitZip -WithoutBundledPython
    $explicitManifest = Assert-EmployeeBundle -ZipPath $explicitZip -ExpandedPath (Join-Path $testRoot 'explicit-external')
    Assert-OfflineBundle (($defaultManifest.files | ConvertTo-Json -Depth 10 -Compress) -ceq ($explicitManifest.files | ConvertTo-Json -Depth 10 -Compress)) 'Compatibility external flag changed packaged contents.'

    # Failed builds must preserve a pre-existing output even when Force is set.
    $sentinelZip = Join-Path $testRoot 'preserve-existing.zip'
    Write-CompanyAgentUtf8File -Path $sentinelZip -Content 'Existing output must survive rejected builds.'
    $sentinelHash = (Get-FileHash -LiteralPath $sentinelZip -Algorithm SHA256).Hash
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

    foreach ($extension in @('.exe', '.DLL', '.pyd')) {
        $nativeFixture = Join-Path $pluginRoot ('unexpected-runtime' + $extension)
        Write-CompanyAgentUtf8File -Path $nativeFixture -Content 'This named native runtime file must fail closed.'
        try {
            $invalid = $common.Clone()
            $invalid.OutputPath = $sentinelZip
            $invalid.Force = $true
            Assert-BundleBuildRejected $invalid 'cannot contain native binary files'
            Assert-OfflineBundle (Test-Path -LiteralPath $nativeFixture -PathType Leaf) 'Failed packaging removed the source binary fixture.'
        }
        finally { Remove-Item -LiteralPath $nativeFixture -Force }
    }
    Assert-OfflineBundle ((Get-FileHash -LiteralPath $sentinelZip -Algorithm SHA256).Hash -ceq $sentinelHash) 'Rejected build replaced an existing output.'

    [pscustomobject][ordered]@{
        status = 'passed'
        defaultRuntimeMode = $defaultManifest.runtime.mode
        minimumPythonVersion = $defaultManifest.runtime.minimumVersion
        productionDeployFiles = 17
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
