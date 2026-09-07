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

function Test-CompanyAgentMcpConfigHasServers {
    param([string] $Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    try {
        $config = Read-CompanyAgentJson -Path $Path
        if ($null -eq $config.PSObject.Properties['mcpServers'] -or $null -eq $config.mcpServers) {
            return $false
        }
        return @($config.mcpServers.PSObject.Properties).Count -gt 0
    }
    catch {
        throw "Invalid MCP configuration '$Path': $($_.Exception.Message)"
    }
}

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
Assert-CompanyAgentRootsSeparated -InstallRoot $InstallRoot -DataRoot $DataRoot -UserStateRoot $UserStateRoot
if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) {
    throw "Working directory was not found: $WorkingDirectory"
}

$claudeConfigRoot = [Environment]::GetEnvironmentVariable('CLAUDE_CONFIG_DIR', 'Process')
if ([string]::IsNullOrWhiteSpace($claudeConfigRoot)) {
    $claudeConfigRoot = Join-Path $env:USERPROFILE '.claude'
}
$modelSettingsPaths = New-Object Collections.ArrayList
$null = $modelSettingsPaths.Add((Join-Path $claudeConfigRoot 'settings.json'))
$settingsSearchRoot = $WorkingDirectory
while (-not [string]::IsNullOrWhiteSpace($settingsSearchRoot)) {
    $null = $modelSettingsPaths.Add((Join-Path $settingsSearchRoot '.claude\settings.json'))
    $null = $modelSettingsPaths.Add((Join-Path $settingsSearchRoot '.claude\settings.local.json'))
    $settingsParent = Split-Path -Parent $settingsSearchRoot
    if ([string]::IsNullOrWhiteSpace($settingsParent) -or $settingsParent -ieq $settingsSearchRoot) {
        break
    }
    $settingsSearchRoot = $settingsParent
}
$settingsModelOverrides = @(Get-CompanyAgentSubagentModelForceSettings `
    -SettingsPaths @($modelSettingsPaths.ToArray()) `
    -IncludeWindowsPolicy)
if ($settingsModelOverrides.Count -gt 0) {
    $locations = @($settingsModelOverrides | ForEach-Object { "$($_.variable) in $($_.source)" }) -join '; '
    throw "Company Agent cannot start because Claude settings force every subagent to one model: $locations. Remove that setting through your Claude or IT configuration owner. Company Agent did not change the file."
}

$currentPointerPath = Get-CompanyAgentCurrentPointerPath -DataRoot $DataRoot
$deployment = Read-CompanyAgentJson -Path $currentPointerPath

# Setup records the exact interpreter that passed the user-context preflight.
# This also makes the Windows `py.exe` fallback safe: every hook reaches it via
# the plugin-local python.cmd shim instead of assuming a `python` alias exists.
if (-not $PSBoundParameters.ContainsKey('PythonCommand') -and
    $null -ne $deployment.PSObject.Properties['runtime'] -and
    $null -ne $deployment.runtime.PSObject.Properties['pythonCommand'] -and
    -not [string]::IsNullOrWhiteSpace([string]$deployment.runtime.pythonCommand)) {
    $PythonCommand = [string]$deployment.runtime.pythonCommand
}
$bundledPython = Join-Path $InstallRoot ('versions\' + [string]$deployment.coreVersion + '\plugin\runtime\python\python.exe')
if (-not $PSBoundParameters.ContainsKey('PythonCommand') -and (Test-Path -LiteralPath $bundledPython -PathType Leaf)) {
    $PythonCommand = $bundledPython
}
$pythonInfo = Get-Command $PythonCommand -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $pythonInfo) {
    throw "The Company Agent Python runtime was not found: $PythonCommand"
}
$resolvedPythonCommand = $pythonInfo.Source
if ([string]::IsNullOrWhiteSpace($resolvedPythonCommand)) {
    $resolvedPythonCommand = $pythonInfo.Definition
}
if ([string]::IsNullOrWhiteSpace($resolvedPythonCommand)) {
    throw "The Company Agent Python runtime could not be resolved: $PythonCommand"
}
$PythonCommand = [string]$resolvedPythonCommand
Assert-CompanyAgentPrerequisites -ClaudeCommand $ClaudeCommand -PythonCommand $PythonCommand -SkipPrerequisiteCheck:$SkipPrerequisiteCheck
Assert-CompanyAgentVersion -Version ([string]$deployment.coreVersion) -Name 'coreVersion in current.json'
Assert-CompanyAgentVersion -Version ([string]$deployment.knowledgeVersion) -Name 'knowledgeVersion in current.json'

$corePluginPath = Join-Path $InstallRoot (Join-Path 'versions' (Join-Path ([string]$deployment.coreVersion) 'plugin'))
$corporateKnowledgePath = Join-Path $DataRoot (Join-Path 'knowledge\versions' ([string]$deployment.knowledgeVersion))
$personalKnowledgePath = Join-Path $UserStateRoot 'knowledge'
$personalRootPath = Join-Path $UserStateRoot 'personal-root'
$coreCliBinPath = Join-Path $corePluginPath 'bin'
$configRoot = Join-Path $DataRoot 'config'
if ($null -ne $deployment.PSObject.Properties['configVersion'] -and
    -not [string]::IsNullOrWhiteSpace([string]$deployment.configVersion)) {
    $configRoot = Join-Path $configRoot (Join-Path 'versions' ([string]$deployment.configVersion))
}
$settingsPath = Join-Path $configRoot 'session.settings.json'
if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
    # Backward compatibility with 0.1 installations.
    $settingsPath = Join-Path $configRoot 'managed.settings.json'
}
$managedConfigPath = Join-Path $configRoot 'managed.json'
$managedMcpPath = Join-Path $configRoot 'managed-mcp.json'
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
    $null = Read-CompanyAgentJson -Path $userConfigPath
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
        $reconcileOutput = Invoke-CompanyAgentPythonProcess -Executable $pythonExecutable -Arguments @(
            '-B', $harnessCliPath, 'knowledge', 'reconcile', '--state-root', $UserStateRoot,
            '--base', $corporateKnowledgePath, '--apply-safe')
        $reconcileExitCode = $reconcileOutput.ExitCode
        if ($reconcileExitCode -notin @(0, 2)) {
            throw "Personal knowledge reconciliation failed:`r`n$($reconcileOutput.StdOut)`r`n$($reconcileOutput.StdErr)"
        }
        if ($reconcileExitCode -eq 2) {
            try {
                $reconcileReport = $reconcileOutput.StdOut | ConvertFrom-Json
                $knowledgeConflictCount = @($reconcileReport.conflicts).Count
                $knowledgeDetachedCount = @($reconcileReport.detached).Count
            }
            catch {
                $knowledgeConflictCount = 1
            }
            Write-Warning ("Personal knowledge needs review after the Corporate Knowledge update. Safe changes were applied; unresolved items remain under knowledge\conflicts. conflicts={0}, detached={1}" -f $knowledgeConflictCount, $knowledgeDetachedCount)
        }

        $buildOutput = Invoke-CompanyAgentPythonProcess -Executable $pythonExecutable -Arguments @(
            '-B', $harnessCliPath, 'knowledge', 'build', '--state-root', $UserStateRoot,
            '--base', $corporateKnowledgePath, '--personal', $personalKnowledgePath,
            '--output', (Join-Path $UserStateRoot 'knowledge\generated-index'))
        if ($buildOutput.ExitCode -ne 0) {
            throw "Effective Knowledge index build failed:`r`n$($buildOutput.StdOut)`r`n$($buildOutput.StdErr)"
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
    $configuredDefaultTier = ([string]$deployment.routing.defaultTier).ToUpperInvariant()
    if (-not [string]::IsNullOrWhiteSpace($configuredDefaultTier) -and $configuredDefaultTier -ne 'AUTO') {
        $effectiveTier = $configuredDefaultTier
    }
}
if (@('AUTO', 'SMALL', 'MEDIUM', 'LARGE') -notcontains $effectiveTier) {
    throw "Invalid effective model tier in current.json: $effectiveTier"
}

$modelMode = 'explicit-map'
if ($null -ne $deployment.PSObject.Properties['modelConfiguration'] -and
    $null -ne $deployment.modelConfiguration.PSObject.Properties['mode']) {
    $modelMode = [string]$deployment.modelConfiguration.mode
}
$modelOverrideProvided = -not [string]::IsNullOrWhiteSpace($ModelId)
$resolvedEntryModel = $null
$entryModelArgument = $null
$modelAliases = @{
    SMALL  = 'haiku'
    MEDIUM = 'sonnet'
    LARGE  = 'opus'
}
if ($modelOverrideProvided) {
    $resolvedEntryModel = $ModelId
    $entryModelArgument = $ModelId
}
elseif ($effectiveTier -ne 'AUTO') {
    $modelProperty = $deployment.modelMap.PSObject.Properties[$effectiveTier]
    if ($null -eq $modelProperty -or [string]::IsNullOrWhiteSpace([string]$modelProperty.Value)) {
        throw "No model ID is configured for tier $effectiveTier."
    }
    $resolvedEntryModel = [string]$modelProperty.Value
    $entryModelArgument = [string]$modelAliases[$effectiveTier]
}

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
    '--settings', $settingsPath
)
if (-not [string]::IsNullOrWhiteSpace($entryModelArgument)) {
    $arguments += @('--model', $entryModelArgument)
}

$strictMcpConfig = $false
if (Test-Path -LiteralPath $managedConfigPath -PathType Leaf) {
    $managedRuntimeConfig = Read-CompanyAgentJson -Path $managedConfigPath
    if ($null -ne $managedRuntimeConfig.PSObject.Properties['strictMcpConfig']) {
        $strictMcpConfig = [bool]$managedRuntimeConfig.strictMcpConfig
    }
}
$mcpConfigPaths = @()
if ($strictMcpConfig -or (Test-CompanyAgentMcpConfigHasServers -Path $managedMcpPath)) {
    $mcpConfigPaths += $managedMcpPath
}
if ($strictMcpConfig -or (Test-CompanyAgentMcpConfigHasServers -Path $personalMcpPath)) {
    $mcpConfigPaths += $personalMcpPath
}
if ($mcpConfigPaths.Count -gt 0) {
    $arguments += @('--mcp-config') + $mcpConfigPaths
    if ($strictMcpConfig) {
        $arguments += '--strict-mcp-config'
    }
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
    COMPANY_AGENT_MODEL_MODE        = $modelMode
    COMPANY_AGENT_MODEL_TIER        = $effectiveTier
    COMPANY_AGENT_ENTRY_MODEL       = $(if ($null -eq $resolvedEntryModel) { '' } else { $resolvedEntryModel })
    COMPANY_AGENT_PYTHON            = $PythonCommand
    Path                             = ($coreCliBinPath + ';' + [Environment]::GetEnvironmentVariable('Path', 'Process'))
}
if ($modelMode -eq 'explicit-map') {
    $environmentValues.ANTHROPIC_DEFAULT_HAIKU_MODEL = [string]$deployment.modelMap.SMALL
    $environmentValues.ANTHROPIC_DEFAULT_SONNET_MODEL = [string]$deployment.modelMap.MEDIUM
    $environmentValues.ANTHROPIC_DEFAULT_OPUS_MODEL = [string]$deployment.modelMap.LARGE
}
$environmentClearNames = @(
    'CLAUDE_CODE_SUBAGENT_MODEL',
    'CLAUDE_CODE_SUBAGENT_MODEL_FORCE'
)

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
        sessionSettings      = $settingsPath
        configRoot           = $configRoot
        knowledgeCatalog     = $(if (Test-Path -LiteralPath $knowledgeCatalogPath -PathType Leaf) { $knowledgeCatalogPath } else { $null })
        knowledgeConflicts   = $knowledgeConflictCount
        knowledgeDetached    = $knowledgeDetachedCount
        modelMode            = $modelMode
        modelTier            = $effectiveTier
        modelId              = $resolvedEntryModel
        modelArgument        = $entryModelArgument
        mcpConfigMode        = $(if ($strictMcpConfig) { 'strict' } elseif ($mcpConfigPaths.Count -gt 0) { 'merge' } else { 'existing-only' })
        mcpConfigPaths       = $mcpConfigPaths
        processOnlyEnvironmentClears = $environmentClearNames
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
foreach ($name in $environmentClearNames) {
    if (-not $previousEnvironment.ContainsKey($name)) {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
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
    foreach ($name in $environmentClearNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
}
