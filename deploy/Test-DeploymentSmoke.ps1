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

try {
    $sourceRoot = Join-Path $TestRoot 'source'
    $sourceDeploy = Join-Path $sourceRoot 'deploy'
    $pluginRoot = Join-Path $sourceRoot 'company-agent-plugin'
    $knowledgeRoot = Join-Path $sourceRoot 'corporate-knowledge'
    $repositoryRoot = Split-Path -Parent $PSScriptRoot
    Copy-CompanyAgentDirectoryContents -Source $PSScriptRoot -Destination $sourceDeploy
    Copy-CompanyAgentDirectoryContents -Source (Join-Path $repositoryRoot 'company-agent-plugin') -Destination $pluginRoot
    Copy-CompanyAgentDirectoryContents -Source (Join-Path $repositoryRoot 'corporate-knowledge') -Destination $knowledgeRoot
    Write-CompanyAgentUtf8File -Path (Join-Path $pluginRoot 'SMOKE_VERSION.txt') -Content "v1`r`n"
    Write-CompanyAgentUtf8File -Path (Join-Path $knowledgeRoot 'SMOKE_VERSION.txt') -Content "v1`r`n"

    $bundleV1 = Join-Path $TestRoot 'company-agent-v1.zip'
    $bundleResult = & (Join-Path $PSScriptRoot 'New-OfflineBundle.ps1') -SourceRoot $sourceRoot -CoreVersion '0.1.0' -KnowledgeVersion '2026.09.03' -OutputPath $bundleV1 -SkipSourceValidation
    Assert-SmokeCondition -Condition (Test-Path -LiteralPath $bundleResult.outputPath -PathType Leaf) -Message 'v1 bundle was not created'

    $expandedV1 = Join-Path $TestRoot 'expanded-v1'
    Expand-Archive -LiteralPath $bundleV1 -DestinationPath $expandedV1
    $installResult = & (Join-Path $expandedV1 'deploy\Install-CompanyAgent.ps1') `
        -BundleRoot $expandedV1 `
        -SmallModelId 'corp-small-id' `
        -MediumModelId 'corp-medium-id' `
        -LargeModelId 'corp-large-id' `
        -DefaultTier 'MEDIUM' `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -SkipAcl `
        -SkipAdminCheck `
        -SkipShortcut
    Assert-SmokeCondition -Condition ($installResult.coreVersion -eq '0.1.0') -Message 'v1 core was not installed'

    $initializeResult = & (Join-Path $expandedV1 'deploy\Initialize-CompanyAgentUser.ps1') `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -UserEmail 'smoke.user@example.internal' `
        -DisplayName 'Smoke User' `
        -NonInteractive `
        -SkipAcl
    Assert-SmokeCondition -Condition (Test-Path -LiteralPath $initializeResult.personalKnowledge -PathType Container) -Message 'personal knowledge was not initialized'

    $dryRun = & (Join-Path $expandedV1 'deploy\Start-CompanyAgent.ps1') `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -ModelTier 'SMALL' `
        -UserEmail 'ignored@example.internal' `
        -DisplayName 'Ignored Name' `
        -Prompt 'smoke' `
        -NonInteractive `
        -SkipAcl `
        -DryRun
    Assert-SmokeCondition -Condition ($dryRun.modelId -eq 'corp-small-id') -Message 'SMALL model mapping was not selected'
    Assert-SmokeCondition -Condition ($dryRun.modelArgument -eq 'haiku') -Message 'SMALL tier did not use the haiku alias'
    Assert-SmokeCondition -Condition ($dryRun.arguments -contains '--plugin-dir') -Message 'plugin directory argument is missing'
    Assert-SmokeCondition -Condition ($dryRun.arguments -contains $initializeResult.personalKnowledge) -Message 'personal knowledge add-dir is missing'
    Assert-SmokeCondition -Condition ($dryRun.arguments -contains $initializeResult.personalRoot) -Message 'personal Skill root add-dir is missing'
    Assert-SmokeCondition -Condition ($dryRun.arguments -contains $initializeResult.personalMcpRegistry) -Message 'personal MCP registry argument is missing'
    Assert-SmokeCondition -Condition ($dryRun.arguments -contains '--strict-mcp-config') -Message 'strict MCP scope is missing'
    Assert-SmokeCondition -Condition ($dryRun.environment.ANTHROPIC_DEFAULT_HAIKU_MODEL -eq 'corp-small-id') -Message 'haiku alias environment mapping is missing'
    Assert-SmokeCondition -Condition ($dryRun.environment.COMPANY_AGENT_PYTHON -eq 'python') -Message 'Harness Python command mapping is missing'
    Assert-SmokeCondition -Condition ($dryRun.environment.Path.StartsWith((Join-Path $dryRun.corePlugin 'bin') + ';', [System.StringComparison]::OrdinalIgnoreCase)) -Message 'Harness CLI directory is not first on PATH'
    Assert-SmokeCondition -Condition (Test-Path -LiteralPath $initializeResult.knowledgeCatalog -PathType Leaf) -Message 'effective knowledge catalog was not built'
    $storedUserConfig = Read-CompanyAgentJson -Path (Join-Path $UserStateRoot 'config\user.json')
    Assert-SmokeCondition -Condition ($storedUserConfig.user_email -eq 'smoke.user@example.internal') -Message 'user email was not preserved'
    Assert-SmokeCondition -Condition ($storedUserConfig.display_name -eq 'Smoke User') -Message 'display name was not preserved'
    Assert-SmokeCondition -Condition (-not $dryRun.userClaudeHomeMutated) -Message 'launcher claims it mutated user Claude home'

    $pluginManifest = Read-CompanyAgentJson -Path (Join-Path $pluginRoot '.claude-plugin\plugin.json')
    $pluginManifest.version = '0.2.0'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $pluginRoot '.claude-plugin\plugin.json') -Value $pluginManifest
    $knowledgeManifest = Read-CompanyAgentJson -Path (Join-Path $knowledgeRoot 'pack.json')
    $knowledgeManifest.version = '2026.10.01'
    Write-CompanyAgentJsonAtomic -Path (Join-Path $knowledgeRoot 'pack.json') -Value $knowledgeManifest
    Write-CompanyAgentUtf8File -Path (Join-Path $pluginRoot 'SMOKE_VERSION.txt') -Content "v2`r`n"
    Write-CompanyAgentUtf8File -Path (Join-Path $knowledgeRoot 'SMOKE_VERSION.txt') -Content "v2`r`n"
    $bundleV2 = Join-Path $TestRoot 'company-agent-v2.zip'
    $null = & (Join-Path $PSScriptRoot 'New-OfflineBundle.ps1') -SourceRoot $sourceRoot -CoreVersion '0.2.0' -KnowledgeVersion '2026.10.01' -OutputPath $bundleV2 -SkipSourceValidation
    $expandedV2 = Join-Path $TestRoot 'expanded-v2'
    Expand-Archive -LiteralPath $bundleV2 -DestinationPath $expandedV2
    $updateResult = & (Join-Path $expandedV2 'deploy\Update-CompanyAgent.ps1') `
        -BundleRoot $expandedV2 `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -SkipAcl `
        -SkipAdminCheck `
        -SkipShortcut
    Assert-SmokeCondition -Condition ($updateResult.coreVersion -eq '0.2.0') -Message 'v2 core was not activated'

    $currentAfterUpdate = Read-CompanyAgentJson -Path (Get-CompanyAgentCurrentPointerPath -DataRoot $DataRoot)
    $previousAfterUpdate = Read-CompanyAgentJson -Path (Get-CompanyAgentPreviousPointerPath -DataRoot $DataRoot)
    Assert-SmokeCondition -Condition ($currentAfterUpdate.coreVersion -eq '0.2.0') -Message 'current pointer is not v2'
    Assert-SmokeCondition -Condition ($previousAfterUpdate.coreVersion -eq '0.1.0') -Message 'previous pointer is not v1'
    Assert-SmokeCondition -Condition (Test-Path -LiteralPath $UserStateRoot -PathType Container) -Message 'update removed personal state'

    $rollbackResult = & (Join-Path $expandedV2 'deploy\Rollback-CompanyAgent.ps1') `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -SkipAcl `
        -SkipAdminCheck
    Assert-SmokeCondition -Condition ($rollbackResult.coreVersion -eq '0.1.0') -Message 'rollback did not restore v1'

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
            'offline bundle and SHA-256 manifest',
            'side-by-side install',
            'personal state initialization',
            'Outlook self identity and personal MCP registry',
            'effective Corporate plus Personal knowledge catalog',
            'SMALL alias mapping and strict Claude MCP arguments',
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
