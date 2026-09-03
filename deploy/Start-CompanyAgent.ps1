[CmdletBinding()]
param(
    [string] $InstallRoot,
    [string] $DataRoot,
    [string] $UserStateRoot,
    [ValidateSet('AUTO', 'SMALL', 'MEDIUM', 'LARGE')]
    [string] $ModelTier = 'AUTO',
    [string] $ModelId,
    [string] $Prompt,
    [switch] $NonInteractive,
    [string] $WorkingDirectory,
    [string] $ClaudeCommand = 'claude',
    [string] $PythonCommand = 'python',
    [string] $UserEmail,
    [string] $DisplayName,
    [switch] $SkipAcl,
    [switch] $SkipAdminCheck,
    [switch] $SkipPrerequisiteCheck,
    [switch] $SkipUserInitialization,
    [switch] $SkipKnowledgePreparation,
    [switch] $DryRun,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $ClaudeArguments
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Get-CompanyAgentDefaultInstallRoot
}
if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $DataRoot = Get-CompanyAgentDefaultDataRoot
}
if ([string]::IsNullOrWhiteSpace($UserStateRoot)) {
    $UserStateRoot = Get-CompanyAgentDefaultUserStateRoot
}
if ([string]::IsNullOrWhiteSpace($WorkingDirectory)) {
    $WorkingDirectory = (Get-Location).Path
}

$InstallRoot = ConvertTo-CompanyAgentFullPath -Path $InstallRoot
$DataRoot = ConvertTo-CompanyAgentFullPath -Path $DataRoot
$UserStateRoot = ConvertTo-CompanyAgentFullPath -Path $UserStateRoot
$WorkingDirectory = ConvertTo-CompanyAgentFullPath -Path $WorkingDirectory
if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) {
    throw "Working directory was not found: $WorkingDirectory"
}
Assert-CompanyAgentPrerequisites -ClaudeCommand $ClaudeCommand -PythonCommand $PythonCommand -SkipPrerequisiteCheck:$SkipPrerequisiteCheck

$currentPointerPath = Get-CompanyAgentCurrentPointerPath -DataRoot $DataRoot
$deployment = Read-CompanyAgentJson -Path $currentPointerPath
Assert-CompanyAgentVersion -Version ([string]$deployment.coreVersion) -Name 'coreVersion in current.json'
Assert-CompanyAgentVersion -Version ([string]$deployment.knowledgeVersion) -Name 'knowledgeVersion in current.json'

$corePluginPath = Join-Path $InstallRoot (Join-Path 'versions' (Join-Path ([string]$deployment.coreVersion) 'plugin'))
$corporateKnowledgePath = Join-Path $DataRoot (Join-Path 'knowledge\versions' ([string]$deployment.knowledgeVersion))
$personalKnowledgePath = Join-Path $UserStateRoot 'knowledge'
$personalRootPath = Join-Path $UserStateRoot 'personal-root'
$coreCliBinPath = Join-Path $corePluginPath 'bin'
$settingsPath = Join-Path $DataRoot 'config\managed.settings.json'
$managedConfigPath = Join-Path $DataRoot 'config\managed.json'
$managedMcpPath = Join-Path $DataRoot 'config\managed-mcp.json'
$personalMcpPath = Join-Path $UserStateRoot 'mcp\registry.json'

if (-not (Test-Path -LiteralPath $corePluginPath -PathType Container)) {
    throw "Active core plugin directory was not found: $corePluginPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $coreCliBinPath 'company-agent.cmd') -PathType Leaf)) {
    throw "Active core does not contain the Company Agent CLI wrapper: $coreCliBinPath"
}
if (-not (Test-Path -LiteralPath $corporateKnowledgePath -PathType Container)) {
    throw "Active corporate knowledge directory was not found: $corporateKnowledgePath"
}
if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
    throw "Managed Claude settings file was not found: $settingsPath"
}

$userConfigPath = Join-Path $UserStateRoot 'config\user.json'
$requiresUserInitialization = (-not (Test-Path -LiteralPath $personalKnowledgePath -PathType Container)) -or
    (-not (Test-Path -LiteralPath $personalRootPath -PathType Container)) -or
    (-not (Test-Path -LiteralPath $personalMcpPath -PathType Leaf)) -or
    (-not (Test-Path -LiteralPath $userConfigPath -PathType Leaf))
if (-not $requiresUserInitialization) {
    $existingUserConfig = Read-CompanyAgentJson -Path $userConfigPath
    $existingEmail = @($existingUserConfig.PSObject.Properties | Where-Object { $_.Name -eq 'user_email' } | Select-Object -First 1)
    $existingDisplayName = @($existingUserConfig.PSObject.Properties | Where-Object { $_.Name -eq 'display_name' } | Select-Object -First 1)
    $requiresUserInitialization = $existingEmail.Count -eq 0 -or
        $existingDisplayName.Count -eq 0 -or
        [string]::IsNullOrWhiteSpace([string]$existingEmail[0].Value) -or
        [string]::IsNullOrWhiteSpace([string]$existingDisplayName[0].Value)
}

if ($requiresUserInitialization -and -not $SkipUserInitialization) {
    $initializerPath = Join-Path $PSScriptRoot 'Initialize-CompanyAgentUser.ps1'
    if (-not (Test-Path -LiteralPath $initializerPath -PathType Leaf)) {
        throw "User initializer was not found: $initializerPath"
    }
    $null = & $initializerPath `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -UserStateRoot $UserStateRoot `
        -UserEmail $UserEmail `
        -DisplayName $DisplayName `
        -ClaudeCommand $ClaudeCommand `
        -PythonCommand $PythonCommand `
        -NonInteractive:$NonInteractive `
        -SkipAcl:$SkipAcl `
        -SkipAdminCheck:$SkipAdminCheck `
        -SkipPrerequisiteCheck:$SkipPrerequisiteCheck `
        -SkipKnowledgeBuild
}
elseif ($requiresUserInitialization) {
    throw "Personal state is not initialized: $UserStateRoot"
}
if (-not (Test-Path -LiteralPath $personalRootPath -PathType Container)) {
    throw "Personal Skill root was not found: $personalRootPath"
}
if (-not (Test-Path -LiteralPath $personalMcpPath -PathType Leaf)) {
    throw "Personal MCP registry was not found: $personalMcpPath"
}

$knowledgeConflictCount = 0
$knowledgeDetachedCount = 0
$knowledgeCatalogPath = Join-Path $UserStateRoot 'knowledge\generated-index\catalog.json'
if (-not $SkipKnowledgePreparation) {
    $harnessCliPath = Join-Path $corePluginPath 'scripts\harness_cli.py'
    if (-not (Test-Path -LiteralPath $harnessCliPath -PathType Leaf)) {
        throw "Active core does not contain harness_cli.py: $harnessCliPath"
    }
    $pythonInfo = Get-Command $PythonCommand | Select-Object -First 1
    $pythonExecutable = $pythonInfo.Source
    if ([string]::IsNullOrWhiteSpace($pythonExecutable)) {
        $pythonExecutable = $pythonInfo.Definition
    }

    $previousDontWriteBytecode = [Environment]::GetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', 'Process')
    try {
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', '1', 'Process')
        $reconcileOutput = & $pythonExecutable $harnessCliPath knowledge reconcile `
            --state-root $UserStateRoot `
            --base $corporateKnowledgePath `
            --apply-safe 2>&1
        $reconcileExitCode = $LASTEXITCODE
        if ($reconcileExitCode -notin @(0, 2)) {
            throw "Personal knowledge reconciliation failed:`r`n$($reconcileOutput -join [Environment]::NewLine)"
        }
        if ($reconcileExitCode -eq 2) {
            try {
                $reconcileReport = ($reconcileOutput -join [Environment]::NewLine) | ConvertFrom-Json
                $knowledgeConflictCount = @($reconcileReport.conflicts).Count
                $knowledgeDetachedCount = @($reconcileReport.detached).Count
            }
            catch {
                $knowledgeConflictCount = 1
            }
            Write-Warning ("Personal knowledge needs review after the Corporate Knowledge update. Safe changes were applied; unresolved items remain under knowledge\conflicts. conflicts={0}, detached={1}" -f $knowledgeConflictCount, $knowledgeDetachedCount)
        }

        $buildOutput = & $pythonExecutable $harnessCliPath knowledge build `
            --state-root $UserStateRoot `
            --base $corporateKnowledgePath `
            --personal $personalKnowledgePath `
            --output (Join-Path $UserStateRoot 'knowledge\generated-index') 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Effective Knowledge index build failed:`r`n$($buildOutput -join [Environment]::NewLine)"
        }
    }
    finally {
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', $previousDontWriteBytecode, 'Process')
    }
    if (-not (Test-Path -LiteralPath $knowledgeCatalogPath -PathType Leaf)) {
        throw "Knowledge preparation completed without catalog.json: $knowledgeCatalogPath"
    }
}

$effectiveTier = $ModelTier.ToUpperInvariant()
if ($effectiveTier -eq 'AUTO') {
    $effectiveTier = ([string]$deployment.routing.defaultTier).ToUpperInvariant()
}
if (@('SMALL', 'MEDIUM', 'LARGE') -notcontains $effectiveTier) {
    throw "Invalid effective model tier in current.json: $effectiveTier"
}

$modelOverrideProvided = -not [string]::IsNullOrWhiteSpace($ModelId)
if (-not $modelOverrideProvided) {
    $modelProperty = $deployment.modelMap.PSObject.Properties[$effectiveTier]
    if ($null -eq $modelProperty -or [string]::IsNullOrWhiteSpace([string]$modelProperty.Value)) {
        throw "No model ID is configured for tier $effectiveTier."
    }
    $ModelId = [string]$modelProperty.Value
}
$modelAliases = @{
    SMALL  = 'haiku'
    MEDIUM = 'sonnet'
    LARGE  = 'opus'
}
$entryModelArgument = $(if ($modelOverrideProvided) { $ModelId } else { [string]$modelAliases[$effectiveTier] })

$protectedOptions = @('--model', '--plugin-dir', '--add-dir', '--settings', '--mcp-config', '--strict-mcp-config')
foreach ($argument in @($ClaudeArguments)) {
    if ($null -eq $argument) {
        continue
    }
    foreach ($protectedOption in $protectedOptions) {
        if ($argument -ieq $protectedOption -or $argument.StartsWith($protectedOption + '=', [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Claude argument '$argument' is managed by Company Agent and cannot be overridden from the launcher."
        }
    }
}
if ($NonInteractive -and [string]::IsNullOrWhiteSpace($Prompt)) {
    throw 'NonInteractive mode requires -Prompt.'
}

$arguments = @(
    '--plugin-dir', $corePluginPath,
    '--add-dir', $corporateKnowledgePath, $personalKnowledgePath, $personalRootPath,
    '--settings', $settingsPath,
    '--model', $entryModelArgument
)
if (Test-Path -LiteralPath $managedMcpPath -PathType Leaf) {
    $arguments += @('--mcp-config', $managedMcpPath, $personalMcpPath, '--strict-mcp-config')
}
if ($NonInteractive) {
    $arguments += '--print'
}
$arguments += @($ClaudeArguments)
if (-not [string]::IsNullOrWhiteSpace($Prompt)) {
    $arguments += $Prompt
}

$environmentValues = [ordered]@{
    COMPANY_AGENT_HOME              = $InstallRoot
    COMPANY_AGENT_INSTALL_ROOT      = $InstallRoot
    COMPANY_AGENT_DATA_ROOT         = $DataRoot
    COMPANY_AGENT_USER_STATE_ROOT   = $UserStateRoot
    COMPANY_AGENT_USER_STATE        = $UserStateRoot
    COMPANY_AGENT_KNOWLEDGE_BASE    = $corporateKnowledgePath
    COMPANY_AGENT_MANAGED_CONFIG    = $managedConfigPath
    COMPANY_AGENT_MANAGED_MCP       = $managedMcpPath
    COMPANY_AGENT_KNOWLEDGE_INDEX   = (Join-Path $UserStateRoot 'knowledge\generated-index')
    COMPANY_AGENT_CORE_VERSION      = [string]$deployment.coreVersion
    COMPANY_AGENT_KNOWLEDGE_VERSION = [string]$deployment.knowledgeVersion
    COMPANY_AGENT_MODEL_SMALL       = [string]$deployment.modelMap.SMALL
    COMPANY_AGENT_MODEL_MEDIUM      = [string]$deployment.modelMap.MEDIUM
    COMPANY_AGENT_MODEL_LARGE       = [string]$deployment.modelMap.LARGE
    COMPANY_AGENT_MODEL_TIER        = $effectiveTier
    COMPANY_AGENT_ENTRY_MODEL       = $ModelId
    COMPANY_AGENT_PYTHON            = $PythonCommand
    ANTHROPIC_DEFAULT_HAIKU_MODEL   = [string]$deployment.modelMap.SMALL
    ANTHROPIC_DEFAULT_SONNET_MODEL  = [string]$deployment.modelMap.MEDIUM
    ANTHROPIC_DEFAULT_OPUS_MODEL    = [string]$deployment.modelMap.LARGE
    Path                             = ($coreCliBinPath + ';' + [Environment]::GetEnvironmentVariable('Path', 'Process'))
}

if ($DryRun) {
    return [pscustomobject][ordered]@{
        command              = $ClaudeCommand
        arguments            = $arguments
        workingDirectory     = $WorkingDirectory
        corePlugin           = $corePluginPath
        corporateKnowledge   = $corporateKnowledgePath
        personalKnowledge    = $personalKnowledgePath
        personalRoot         = $personalRootPath
        personalMcpRegistry  = $personalMcpPath
        knowledgeCatalog     = $(if (Test-Path -LiteralPath $knowledgeCatalogPath -PathType Leaf) { $knowledgeCatalogPath } else { $null })
        knowledgeConflicts   = $knowledgeConflictCount
        knowledgeDetached    = $knowledgeDetachedCount
        modelTier            = $effectiveTier
        modelId              = $ModelId
        modelArgument        = $entryModelArgument
        environment          = [pscustomobject]$environmentValues
        userClaudeHomeMutated = $false
    }
}

$resolvedCommand = $null
if (Test-Path -LiteralPath $ClaudeCommand -PathType Leaf) {
    $resolvedCommand = ConvertTo-CompanyAgentFullPath -Path $ClaudeCommand
}
else {
    $commandInfo = Get-Command $ClaudeCommand -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $commandInfo) {
        throw "Claude command was not found: $ClaudeCommand"
    }
    $resolvedCommand = $commandInfo.Source
    if ([string]::IsNullOrWhiteSpace($resolvedCommand)) {
        $resolvedCommand = $commandInfo.Definition
    }
}

$previousEnvironment = @{}
foreach ($name in $environmentValues.Keys) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, [string]$environmentValues[$name], 'Process')
}

Push-Location -LiteralPath $WorkingDirectory
try {
    & $resolvedCommand @arguments
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) {
        $exitCode = 0
    }
    if ($exitCode -ne 0) {
        throw "Claude Code exited with code $exitCode."
    }
}
finally {
    Pop-Location
    foreach ($name in $environmentValues.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
}
