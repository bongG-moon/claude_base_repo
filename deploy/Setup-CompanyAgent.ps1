[CmdletBinding()]
param(
    [ValidateSet('User', 'Project', 'Machine')]
    [string] $Scope,
    [string] $ProjectRoot,
    [string] $BundleRoot,
    [string] $InstallRoot,
    [string] $DataRoot,
    [string] $UserStateRoot,
    [string] $BackupRoot,
    [string] $ShortcutPath,
    [string] $ClaudeConfigRoot,
    [string] $ClaudeCommand = 'claude',
    [string] $PythonCommand = 'python',
    [string] $InvokingUserProfile,
    [string] $InvokingLocalAppData,
    [ValidateSet('Ask', 'Keep', 'Replace', 'Update')]
    [string] $ExistingHarnessAction = 'Ask',
    [ValidateSet('Ask', 'KeepCurrent', 'PreferIncoming')]
    [string] $SkillConflictAction = 'Ask',
    [switch] $AllowExistingCompanyAgentPlugin,
    [switch] $NonInteractive,
    [switch] $FriendlyOutput,
    [switch] $DryRun,
    [switch] $SkipAcl,
    [switch] $SkipAdminCheck,
    [switch] $SkipPrerequisiteCheck,
    [switch] $SkipShortcut,
    [switch] $SkipBundleVerification,
    [Parameter(DontShow = $true)]
    [switch] $FunctionsOnly,
    [Parameter(DontShow = $true)]
    [string] $HandoffData
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')
. (Join-Path $PSScriptRoot 'CompanyAgent.UserContext.ps1')
. (Join-Path $PSScriptRoot 'CompanyAgent.ClaudeDiscovery.ps1')

# Some parent shells prepend PowerShell 7 module folders to PSModulePath before
# starting Windows PowerShell 5.1. Load the matching built-in utility module by
# absolute path so bundle hashing also works when this file is started by CMD.
if ($null -eq (Get-Command 'Get-FileHash' -ErrorAction SilentlyContinue)) {
    $utilityModule = Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1'
    if (Test-Path -LiteralPath $utilityModule -PathType Leaf) {
        Import-Module $utilityModule -Force -ErrorAction Stop
    }
}

function Get-SetupPropertyValue {
    param(
        [object] $Object,
        [Parameter(Mandatory = $true)]
        [string] $Name
    )

    if ($null -eq $Object) {
        return $null
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function ConvertFrom-SetupHandoff {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Encoded
    )

    try {
        $bytes = [Convert]::FromBase64String($Encoded)
        $json = [Text.Encoding]::UTF8.GetString($bytes)
        $value = $json | ConvertFrom-Json
    }
    catch {
        throw "The setup elevation handoff was invalid: $($_.Exception.Message)"
    }
    if ([int](Get-SetupPropertyValue -Object $value -Name 'schemaVersion') -ne 1) {
        throw 'The setup elevation handoff version is not supported.'
    }
    return $value
}

function Get-SetupFullPath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    return (ConvertTo-CompanyAgentFullPath -Path $Path)
}

function Test-SetupSameOrChildPath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Candidate,
        [Parameter(Mandatory = $true)]
        [string] $Parent
    )

    $candidateFull = (Get-SetupFullPath -Path $Candidate).TrimEnd([char[]]@('\', '/'))
    $parentFull = (Get-SetupFullPath -Path $Parent).TrimEnd([char[]]@('\', '/'))
    if ($candidateFull -ieq $parentFull) {
        return $true
    }
    return $candidateFull.StartsWith(
        ($parentFull + [IO.Path]::DirectorySeparatorChar),
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Resolve-SetupCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Command,
        [string[]] $FallbackCommands = @()
    )

    foreach ($candidate in @($Command) + @($FallbackCommands)) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Get-SetupFullPath -Path $candidate)
        }
        $commandInfo = Get-Command $candidate -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $commandInfo) {
            $resolved = $commandInfo.Source
            if ([string]::IsNullOrWhiteSpace($resolved)) {
                $resolved = $commandInfo.Definition
            }
            if (-not [string]::IsNullOrWhiteSpace($resolved)) {
                return [string]$resolved
            }
        }
    }
    return $null
}

function Invoke-SetupPythonProbe {
    param([string] $Executable)

    # Probe only an existing executable, without opening Store aliases, loading
    # user site/customization, changing PATH, or downloading an interpreter.
    if (-not [IO.Path]::IsPathRooted($Executable) -or
        [IO.Path]::GetExtension($Executable) -ine '.exe' -or
        -not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $null }
    if ($Executable -match '(?i)[\\/]Microsoft[\\/]WindowsApps[\\/]') { return $null }
    $item = Get-Item -LiteralPath $Executable -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -and $item.Length -eq 0) { return $null }
    try {
        $arguments = @()
        if ([IO.Path]::GetFileNameWithoutExtension($Executable) -ieq 'py') { $arguments += '-3' }
        $code = "import sys,json,os,sqlite3,ssl,ctypes; print(json.dumps({'version':list(sys.version_info[:3]),'executable':sys.executable,'automaticInstallDisabled':not any(k in os.environ for k in ('PYLAUNCHER_ALLOW_INSTALL','PYLAUNCHER_ALWAYS_INSTALL')) and os.environ.get('PYTHON_MANAGER_AUTOMATIC_INSTALL')=='false'})); sys.exit(0 if sys.version_info >= (3,11) and sys.version_info.major == 3 else 1)"
        # Isolated mode ignores PYTHONIOENCODING, so opt into UTF-8 explicitly.
        $arguments += @('-I', '-X', 'utf8', '-B', '-c', $code)
        $result = Invoke-CompanyAgentPythonProcess -Executable $Executable -Arguments $arguments -TimeoutMilliseconds 10000
        if ($result.ExitCode -ne 0) { return $null }
        return ($result.StdOut | ConvertFrom-Json)
    }
    catch { return $null }
}

function Resolve-SetupApprovedPython {
    param(
        [string] $PreferredCommand = 'python',
        [switch] $OnlyPreferred
    )

    # Approval is an organization policy, not something this compatibility
    # probe can certify. Pin sys.executable, never the mutable py launcher.
    $candidates = @($PreferredCommand)
    if (-not $OnlyPreferred) {
        $candidates += @('python', 'py')
        # A Store alias can precede a real interpreter on PATH. Check all native
        # candidates, then standard registrations belonging to this PC/user.
        foreach ($name in @('python.exe', 'python3.exe', 'py.exe')) {
            $candidates += @(Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
        }
        foreach ($registryRoot in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore', 'HKLM:\Software\WOW6432Node\Python\PythonCore')) {
            foreach ($versionKey in @(Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue)) {
                $installKey = Get-Item -LiteralPath ($versionKey.PSPath + '\InstallPath') -ErrorAction SilentlyContinue
                if ($null -eq $installKey) { continue }
                $registeredExecutable = [string]$installKey.GetValue('ExecutablePath')
                if (-not [string]::IsNullOrWhiteSpace($registeredExecutable)) { $candidates += $registeredExecutable }
                $registeredDirectory = [string]$installKey.GetValue('')
                if (-not [string]::IsNullOrWhiteSpace($registeredDirectory)) { $candidates += (Join-Path $registeredDirectory 'python.exe') }
            }
        }
    }
    foreach ($candidate in @($candidates | Select-Object -Unique)) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        $resolved = Resolve-SetupCommand -Command $candidate
        if ([string]::IsNullOrWhiteSpace($resolved)) {
            continue
        }
        try {
            $probe = Invoke-SetupPythonProbe -Executable $resolved
            if ($null -eq $probe) { continue }
            $version = [version](@($probe.version) -join '.')
            $actual = [string]$probe.executable
            if ($version.Major -ne 3 -or $version -lt [version]'3.11' -or
                -not [IO.Path]::IsPathRooted($actual) -or [IO.Path]::GetExtension($actual) -ine '.exe' -or
                -not (Test-Path -LiteralPath $actual -PathType Leaf)) { continue }
            # Confirm the recorded executable also runs without launcher flags.
            if ($actual -ine $resolved) {
                $direct = Invoke-SetupPythonProbe -Executable $actual
                if ($null -eq $direct -or [string]$direct.executable -ine $actual) { continue }
            }
            return (Get-SetupFullPath -Path $actual)
        }
        catch {
            continue
        }
    }
    return $null
}

function Get-SetupPythonForInstall {
    param(
        [string] $PreferredCommand = 'python',
        [switch] $NonInteractive,
        [switch] $DryRun
    )

    $resolved = Resolve-SetupApprovedPython -PreferredCommand $PreferredCommand
    if (-not [string]::IsNullOrWhiteSpace($resolved)) { return $resolved }
    $help = 'Python 3.11+ was not found or could not run. Use the company-approved Python already installed on this PC. Pass -PythonCommand "C:\Path\To\python.exe", or rerun interactive setup to enter its path. No Python download, installation, or PATH change was attempted.'
    if ($NonInteractive -or $DryRun) { throw $help }
    Write-Host '사내 Python 3.11 이상을 찾거나 실행하지 못했습니다. Python을 새로 설치하거나 다운로드하지 않습니다.'
    Write-Host '이미 설치된 python.exe의 전체 경로를 입력하세요. 위치를 모르면 담당자에게 확인해 주세요.'
    while ($true) {
        $selection = Read-Host 'Python 경로 (예: C:\Python313\python.exe), Enter는 설치 취소'
        if ([string]::IsNullOrWhiteSpace($selection)) { throw '설치를 취소했습니다. Python 확인 단계에서 중단하여 기존 설정과 개인 자료는 변경하지 않았습니다.' }
        $resolved = Resolve-SetupApprovedPython -PreferredCommand ($selection.Trim().Trim('"')) -OnlyPreferred
        if (-not [string]::IsNullOrWhiteSpace($resolved)) { return $resolved }
        Write-Host '해당 Python을 실행할 수 없거나 3.11 미만입니다. 경로·버전·실행 권한을 확인하고 다시 입력하세요.'
    }
}

function Assert-SetupPathHasNoReparsePoint {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,
        [Parameter(Mandatory = $true)]
        [string] $Name
    )

    $current = Get-SetupFullPath -Path $Path
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Name cannot use a junction, symbolic link, or other reparse point: $($item.FullName)"
            }
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -ieq $current) {
            break
        }
        $current = $parent
    }
}

function Get-SetupSkillOverlaps {
    param(
        [string] $BundlePath,
        [string] $ClaudeConfigPath,
        [string] $PersonalStatePath
    )

    # Plugin Skills are namespaced by Claude Code. Only the three unnamespaced
    # add-dir locations can collide: Corporate, ordinary user, and personal.
    $locations = @(
        [pscustomobject]@{ label = 'corporate'; root = (Join-Path $BundlePath 'payload\knowledge\.claude\skills') },
        [pscustomobject]@{ label = 'user'; root = (Join-Path $ClaudeConfigPath 'skills') },
        [pscustomobject]@{ label = 'personal'; root = (Join-Path $PersonalStatePath 'personal-root\.claude\skills') }
    )
    $byName = @{}
    foreach ($location in $locations) {
        if (-not (Test-Path -LiteralPath $location.root -PathType Container)) {
            continue
        }
        foreach ($directory in @(Get-ChildItem -LiteralPath $location.root -Directory -Force)) {
            $key = $directory.Name.ToLowerInvariant()
            if (-not $byName.ContainsKey($key)) {
                $byName[$key] = New-Object Collections.ArrayList
            }
            $null = $byName[$key].Add([pscustomobject][ordered]@{
                location = $location.label
                path = $directory.FullName
            })
        }
    }

    $overlaps = @()
    foreach ($key in @($byName.Keys | Sort-Object)) {
        $definitions = @($byName[$key].ToArray())
        if ($definitions.Count -gt 1) {
            $overlaps += [pscustomobject][ordered]@{
                name = (Split-Path -Leaf $definitions[0].path)
                definitions = $definitions
            }
        }
    }
    return @($overlaps)
}

function Invoke-SetupSkillCommand {
    param(
        [string] $PythonExecutable, [string] $PluginRoot, [string] $PersonalStatePath,
        [Parameter(Mandatory = $true)] [ValidateNotNullOrEmpty()] [string] $KnowledgeRoot,
        [string] $ClaudeConfigPath, [string] $ProjectPath,
        [ValidateSet('User', 'Project')] [string] $InstallScope,
        [ValidateSet('inventory', 'prefer-incoming')] [string] $Command = 'inventory'
    )
    # Setup can be launched from another Agent session. Pin discovery to this
    # verified bundle instead of inheriting that session's plugin/knowledge roots.
    $arguments = @('-B', (Join-Path $PluginRoot 'scripts\harness_cli.py'), 'skill', $Command,
        '--state-root', $PersonalStatePath, '--claude-root', $ClaudeConfigPath,
        '--plugin-root', $PluginRoot, '--incoming-plugin', $PluginRoot, '--base', $KnowledgeRoot)
    if ($InstallScope -eq 'Project') { $arguments += @('--project-root', $ProjectPath) }
    else { $arguments += '--no-project' }
    if ($Command -eq 'prefer-incoming') {
        $arguments += @('--scope', $(if ($InstallScope -eq 'Project') { 'project' } else { 'default' }))
    }
    $processResult = Invoke-CompanyAgentPythonProcess -Executable $PythonExecutable -Arguments $arguments
    if ($processResult.ExitCode -ne 0) {
        throw ("Skill $Command failed; installed/incoming Skills could not be checked or selected safely. Details: " + $processResult.StdErr + [Environment]::NewLine + $processResult.StdOut)
    }
    try { $result = $processResult.StdOut | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "Skill $Command returned invalid JSON. Setup cannot treat an unreadable inventory as no conflicts." }
    if ($Command -eq 'inventory') {
        foreach ($property in @('skills', 'conflicts', 'warnings', 'preferencesPath', 'effectivePreferences', 'complete')) {
            if ($null -eq $result -or $null -eq $result.PSObject.Properties[$property]) {
                throw "Skill inventory is missing '$property'. Use a complete, compatible Company Agent bundle."
            }
        }
        foreach ($conflict in @($result.conflicts)) {
            foreach ($property in @('name', 'kind', 'candidates', 'resolution')) {
                if ($null -eq $conflict -or $null -eq $conflict.PSObject.Properties[$property]) {
                    throw "Skill inventory conflict is missing '$property'. Setup stopped before changing any preferences."
                }
            }
            foreach ($candidate in @($conflict.candidates)) {
                foreach ($property in @('id', 'name', 'source', 'path', 'incoming')) {
                    if ($null -eq $candidate -or $null -eq $candidate.PSObject.Properties[$property]) {
                        throw "Skill inventory candidate is missing '$property'. Setup stopped before changing any preferences."
                    }
                }
            }
        }
        if ($result.complete -isnot [bool]) { throw 'Skill inventory returned an invalid completeness flag. Use a complete, compatible Company Agent bundle.' }
        if (-not $result.complete) {
            throw ('Skill inventory is incomplete or needs review. Setup cannot safely decide conflicts while metadata is skipped, unreadable, or outside supported limits. No installation changes were made. Details: ' + (@($result.warnings) -join '; '))
        }
    }
    return $result
}

function Resolve-SetupSkillConflictAction {
    param(
        [object[]] $Conflicts = @(),
        [ValidateSet('Ask', 'KeepCurrent', 'PreferIncoming')] [string] $Action = 'Ask',
        [switch] $NonInteractive, [switch] $DryRun
    )
    if (@($Conflicts).Count -eq 0) { return $(if ($Action -eq 'Ask') { 'KeepCurrent' } else { $Action }) }
    Write-Host ''
    Write-Host '설치할 Skill과 기존 Skill에서 겹치는 이름을 찾았습니다.'
    foreach ($conflict in $Conflicts) {
        Write-Host ("  {0} [{1}]" -f $conflict.name, $conflict.kind)
        foreach ($candidate in @($conflict.candidates)) {
            $label = $(if ($candidate.incoming) { '설치 예정' } else { '기존' })
            Write-Host ("    {0}: {1} / {2}" -f $label, $candidate.source, $candidate.path)
            $invocation = Get-SetupPropertyValue -Object $candidate -Name 'invocation'
            if ($invocation) { Write-Host ("      호출: {0}" -f $invocation) }
        }
    }
    Write-Host '기본 선택은 현재 선호 설정을 유지합니다. 새 Plugin Skill은 네임스페이스로 함께 설치됩니다.'
    Write-Host '새 Skill 우선은 Company Agent의 Skill 선택 설정에만 적용됩니다. 원본 Skill 파일은 보존됩니다.'
    if ($Action -ne 'Ask') { return $Action }
    if ($NonInteractive -or $DryRun) { return 'InputRequired' }
    Write-Host '  1. 현재 선호 설정 유지 (기본값)'
    Write-Host '  2. 겹치는 이름에서 새 Skill을 우선 사용'
    Write-Host '  3. 설치 취소'
    do { $selection = Read-Host '1, 2, 3 중 선택하세요. Enter를 누르면 1번' } while ($selection -notin @('', '1', '2', '3'))
    if ($selection -eq '3') { return 'Cancel' }
    if ($selection -eq '2') { return 'PreferIncoming' }
    return 'KeepCurrent'
}

function Get-SetupClaudeCompatibility {
    param(
        [Parameter(Mandatory = $true)]
        [string] $ClaudeConfigPath
    )

    $installedNames = @()
    $enabledNames = @()
    $hookProviders = @()
    $companyAgentNameCollision = $false
    $settingsPath = Join-Path $ClaudeConfigPath 'settings.json'
    $settings = $null
    if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
        try {
            $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $enabledPlugins = Get-SetupPropertyValue -Object $settings -Name 'enabledPlugins'
            if ($null -ne $enabledPlugins) {
                foreach ($property in @($enabledPlugins.PSObject.Properties)) {
                    if ([bool]$property.Value) {
                        $enabledNames += $property.Name
                        if ([string]$property.Name -match '(?i)(^|@)company-agent($|@)') {
                            $companyAgentNameCollision = $true
                        }
                    }
                }
            }
            $userHooks = Get-SetupPropertyValue -Object $settings -Name 'hooks'
            if ($null -ne $userHooks -and @($userHooks.PSObject.Properties).Count -gt 0) {
                $hookProviders += 'user settings.json Hooks'
            }
        }
        catch {
            Write-Warning "Could not inspect existing Claude compatibility settings: $settingsPath"
        }
    }
    if (Test-Path -LiteralPath (Join-Path $ClaudeConfigPath 'hooks') -PathType Container) {
        $hookProviders += 'user hooks directory'
    }

    $inventoryPath = Join-Path $ClaudeConfigPath 'plugins\installed_plugins.json'
    if (Test-Path -LiteralPath $inventoryPath -PathType Leaf) {
        try {
            $inventory = Get-Content -LiteralPath $inventoryPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $plugins = Get-SetupPropertyValue -Object $inventory -Name 'plugins'
            if ($null -eq $plugins) {
                throw 'The plugin inventory has no plugins object.'
            }
            foreach ($property in @($plugins.PSObject.Properties)) {
                $pluginName = [string]$property.Name
                $installedNames += $pluginName
                if ($pluginName -match '(?i)(^|@)company-agent($|@)') {
                    $companyAgentNameCollision = $true
                }
                if ($enabledNames.Count -gt 0 -and $enabledNames -notcontains $pluginName) {
                    continue
                }
                foreach ($installation in @($property.Value)) {
                    $installPath = [string](Get-SetupPropertyValue -Object $installation -Name 'installPath')
                    if ([string]::IsNullOrWhiteSpace($installPath)) {
                        continue
                    }
                    $hookManifest = Join-Path $installPath 'hooks\hooks.json'
                    if (Test-Path -LiteralPath $hookManifest -PathType Leaf) {
                        try {
                            $hookJson = Get-Content -LiteralPath $hookManifest -Raw -Encoding UTF8 | ConvertFrom-Json
                            $hookTable = Get-SetupPropertyValue -Object $hookJson -Name 'hooks'
                            $events = @()
                            if ($null -ne $hookTable) {
                                $events = @($hookTable.PSObject.Properties | ForEach-Object { $_.Name })
                            }
                            $label = $pluginName
                            if ($events.Count -gt 0) {
                                $label += ' [' + ($events -join ', ') + ']'
                            }
                            $hookProviders += $label
                        }
                        catch {
                            $hookProviders += ($pluginName + ' [Hook manifest unreadable]')
                        }
                    }
                }
            }
        }
        catch {
            Write-Warning "Could not inspect existing Claude plugin inventory: $inventoryPath"
        }
    }

    return [pscustomobject][ordered]@{
        installedPlugins          = @($installedNames | Sort-Object -Unique)
        enabledPlugins            = @($enabledNames | Sort-Object -Unique)
        parallelHookProviders     = @($hookProviders | Sort-Object -Unique)
        companyAgentNameCollision = $companyAgentNameCollision
    }
}

function Get-SetupBackupItems {
    param(
        [string] $ClaudeConfigPath,
        [string] $PersonalStatePath,
        [string] $ManagedDataPath,
        [string] $ManagedInstallPath,
        [string] $ManagedShortcutPath
    )

    $items = New-Object Collections.ArrayList
    $seen = @{}
    function Add-BackupItem {
        param(
            [string] $Source,
            [string] $RelativePath,
            [string] $Purpose,
            [ValidateSet('copy', 'sanitized-json', 'learning-markdown')]
            [string] $Mode = 'copy',
            [bool] $Required = $false
        )
        if ([string]::IsNullOrWhiteSpace($Source) -or -not (Test-Path -LiteralPath $Source)) {
            return
        }
        $fullSource = Get-SetupFullPath -Path $Source
        if ($seen.ContainsKey($fullSource.ToLowerInvariant())) {
            return
        }
        $seen[$fullSource.ToLowerInvariant()] = $true
        $null = $items.Add([pscustomobject][ordered]@{
            source       = $fullSource
            relativePath = $RelativePath
            purpose      = $Purpose
            mode         = $Mode
            required     = $Required
        })
    }

    $claudeRoot = $ClaudeConfigPath
    if (Test-Path -LiteralPath $claudeRoot -PathType Container) {
        foreach ($file in @(Get-ChildItem -LiteralPath $claudeRoot -File -Force | Where-Object {
            ($_.Extension -ieq '.md' -or $_.Name -like 'settings*.json') -and
            $_.Name -notmatch '(?i)(credential|secret|token|session|history|cache|debug|telemetry)'
        })) {
            $mode = $(if ($file.Extension -ieq '.json') { 'sanitized-json' } else { 'copy' })
            Add-BackupItem -Source $file.FullName -RelativePath (Join-Path 'claude-config' $file.Name) -Purpose 'Claude user instruction or settings file' -Mode $mode
        }
        foreach ($directoryName in @('skills', 'commands', 'agents', 'hooks', 'rules')) {
            Add-BackupItem -Source (Join-Path $claudeRoot $directoryName) -RelativePath (Join-Path 'claude-config' $directoryName) -Purpose 'Claude user customization directory'
        }
        foreach ($pluginFileName in @('config.json', 'installed_plugins.json', 'known_marketplaces.json')) {
            Add-BackupItem -Source (Join-Path $claudeRoot (Join-Path 'plugins' $pluginFileName)) -RelativePath (Join-Path 'claude-config\plugins' $pluginFileName) -Purpose 'Claude plugin registration file' -Mode 'sanitized-json'
        }
    }
    Add-BackupItem -Source (Join-Path $ManagedDataPath 'state') -RelativePath 'company-agent\managed\state' -Purpose 'Existing active and rollback selection'
    Add-BackupItem -Source (Join-Path $ManagedInstallPath 'bin') -RelativePath 'company-agent\managed\bin' -Purpose 'Existing management scripts'
    Add-BackupItem -Source $ManagedShortcutPath -RelativePath 'company-agent\managed\Company Agent.lnk' -Purpose 'Existing Start menu shortcut'

    # This is deliberately not a snapshot of the entire user-state directory.
    # Runtime MCP registries, transcripts, temporary files and derived indexes
    # are not needed to recover learned knowledge and may contain credentials.
    if (-not [string]::IsNullOrWhiteSpace($PersonalStatePath)) {
        foreach ($relative in @('memory\items', 'memory\versions', 'knowledge\entries', 'knowledge\overlays', 'knowledge\versions')) {
            Add-BackupItem -Source (Join-Path $PersonalStatePath $relative) `
                -RelativePath (Join-Path 'company-agent\personal-learning' $relative) `
                -Purpose 'Personal learning Markdown sources and revision history (selective)' -Mode 'learning-markdown' -Required $true
        }
        Add-BackupItem -Source (Join-Path $PersonalStatePath 'personal-root\.claude\skills') `
            -RelativePath 'company-agent\personal-learning\personal-root\.claude\skills' `
            -Purpose 'Personal Skills and supporting files (secret and runtime files excluded)' -Required $true
        foreach ($relative in @('config\user.json', 'state-format.json', 'config\learning.json', 'learning\state.json')) {
            Add-BackupItem -Source (Join-Path $PersonalStatePath $relative) `
                -RelativePath (Join-Path 'company-agent\personal-learning' $relative) `
                -Purpose 'Personal configuration or state-format marker (sanitized)' -Mode 'sanitized-json' -Required $true
        }
        Add-BackupItem -Source (Join-Path $PersonalStatePath 'config\skill-preferences.json') `
            -RelativePath 'company-agent\personal-learning\config\skill-preferences.json' `
            -Purpose 'Explicit Skill selections before installation' -Required $true
        Add-BackupItem -Source (Join-Path $PersonalStatePath 'config\skill-preferences-history') `
            -RelativePath 'company-agent\personal-learning\config\skill-preferences-history' `
            -Purpose 'Skill selection revision history (selective)' -Required $true
    }

    return @($items.ToArray())
}

function ConvertTo-SetupRedactedData {
    param(
        [AllowNull()]
        [object] $Value,
        [string] $PropertyName = ''
    )

    if ($PropertyName -match '(?i)(token|secret|password|credential|api.?key|auth|access.?key|private.?key|client.?secret|(^|[_-])pat($|[_-])|bearer|session.?key)') {
        return '[REDACTED_BY_COMPANY_AGENT_BACKUP]'
    }
    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $result = [ordered]@{}
        foreach ($property in @($Value.PSObject.Properties)) {
            $result[$property.Name] = ConvertTo-SetupRedactedData -Value $property.Value -PropertyName $property.Name
        }
        return [pscustomobject]$result
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $result = [ordered]@{}
        foreach ($key in @($Value.Keys)) {
            $keyText = [string]$key
            $result[$keyText] = ConvertTo-SetupRedactedData -Value $Value[$key] -PropertyName $keyText
        }
        return [pscustomobject]$result
    }
    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        $items = New-Object Collections.ArrayList
        foreach ($entry in $Value) {
            $null = $items.Add((ConvertTo-SetupRedactedData -Value $entry))
        }
        return ,$items.ToArray()
    }
    return $Value
}

function Protect-SetupBackupDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ($null -eq $identity.User) {
        throw 'The current Windows user SID could not be resolved for backup protection.'
    }
    $security = New-Object Security.AccessControl.DirectorySecurity
    $security.SetAccessRuleProtection($true, $false)
    $inheritance = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    $propagation = [Security.AccessControl.PropagationFlags]::None
    $allow = [Security.AccessControl.AccessControlType]::Allow
    $userRule = New-Object Security.AccessControl.FileSystemAccessRule(
        $identity.User,
        [Security.AccessControl.FileSystemRights]::FullControl,
        $inheritance,
        $propagation,
        $allow
    )
    $systemSid = New-Object Security.Principal.SecurityIdentifier(
        [Security.Principal.WellKnownSidType]::LocalSystemSid,
        $null
    )
    $systemRule = New-Object Security.AccessControl.FileSystemAccessRule(
        $systemSid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        $inheritance,
        $propagation,
        $allow
    )
    $null = $security.AddAccessRule($userRule)
    $null = $security.AddAccessRule($systemRule)
    [IO.Directory]::SetAccessControl($Path, $security)
}

function Copy-SetupBackupFile {
    param(
        [string] $Source,
        [string] $Destination,
        [bool] $SanitizeJson,
        [hashtable] $Budget
    )

    Assert-SetupPathHasNoReparsePoint -Path $Source -Name 'Backup source file'
    Assert-SetupPathHasNoReparsePoint -Path $Destination -Name 'Backup destination file'
    # A read-only share prevents another writer from growing/replacing this file
    # while it is being copied. An already-open writer causes a safe failure.
    $sourceStream = [IO.File]::Open($Source, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        $length = $sourceStream.Length
        if ($length -gt $Budget.maxFileBytes -or ($Budget.bytes + $length) -gt $Budget.maxTotalBytes -or $Budget.files -ge $Budget.maxFiles) {
            throw "Selective backup size or file-count limit exceeded at: $Source. No installation changes have started."
        }
        if ($SanitizeJson) {
            $reader = New-Object IO.StreamReader($sourceStream, [Text.Encoding]::UTF8, $true, 4096, $true)
            try { $json = $reader.ReadToEnd() | ConvertFrom-Json -ErrorAction Stop }
            finally { $reader.Dispose() }
            $redacted = ConvertTo-SetupRedactedData -Value $json
            $jsonText = ($redacted | ConvertTo-Json -Depth 100) + [Environment]::NewLine
            $encoding = New-Object Text.UTF8Encoding($false)
            $jsonBytes = $encoding.GetBytes($jsonText)
            $length = [Math]::Max($length, [long]$jsonBytes.LongLength)
            if ($length -gt $Budget.maxFileBytes -or ($Budget.bytes + $length) -gt $Budget.maxTotalBytes) {
                throw "Selective backup size limit exceeded while sanitizing: $Source"
            }
            # This is a new, protected, incomplete backup. Its final manifest is
            # the completion marker; no long .tmp filename is needed per JSON.
            $destinationStream = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try { $destinationStream.Write($jsonBytes, 0, $jsonBytes.Length) }
            finally { $destinationStream.Dispose() }
        }
        else {
            $destinationStream = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try { $sourceStream.CopyTo($destinationStream) }
            finally { $destinationStream.Dispose() }
        }
        $Budget.files += 1
        $Budget.bytes += $length
    }
    finally { $sourceStream.Dispose() }
}

function Copy-SetupBackupItem {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Source,
        [Parameter(Mandatory = $true)]
        [string] $Destination,
        [ValidateSet('copy', 'sanitized-json', 'learning-markdown')]
        [string] $Mode = 'copy',
        [hashtable] $Budget = @{
            files = 0; bytes = [long]0; visited = 0
            maxFiles = 20000; maxTotalBytes = 1GB; maxFileBytes = 64MB; maxDepth = 32; maxVisited = 100000
        }
    )

    $skipped = New-Object Collections.ArrayList
    $excluded = New-Object Collections.ArrayList
    Assert-SetupPathHasNoReparsePoint -Path (Split-Path -Parent (Get-SetupFullPath -Path $Source)) -Name 'Backup source parent'
    Assert-SetupPathHasNoReparsePoint -Path $Destination -Name 'Backup destination'
    $sourceItem = Get-Item -LiteralPath $Source -Force -ErrorAction Stop
    if (($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        $null = $skipped.Add($sourceItem.FullName)
        return [pscustomobject][ordered]@{ copied = $false; skippedReparsePoints = @($skipped.ToArray()); excludedPaths = @() }
    }

    if (-not $sourceItem.PSIsContainer) {
        if ($Mode -eq 'learning-markdown') { throw "A learning source directory was replaced by a file: $Source" }
        Copy-SetupBackupFile -Source $sourceItem.FullName -Destination $Destination -SanitizeJson ($Mode -eq 'sanitized-json' -or $sourceItem.Extension -ieq '.json') -Budget $Budget
        return [pscustomobject][ordered]@{ copied = $true; skippedReparsePoints = @(); excludedPaths = @() }
    }
    if ($Mode -eq 'sanitized-json') { throw "A selected JSON file was replaced by a directory: $Source" }

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $queue = New-Object Collections.Queue
    $queue.Enqueue([pscustomobject]@{ source = $sourceItem.FullName; destination = $Destination; depth = 0 })
    $excludedDirectoryNames = @('.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache', 'cache', 'caches', 'sessions', 'transcripts', 'history', 'projects', 'debug', 'telemetry', 'tmp', 'temp', 'mcp', 'credentials', '.ssh', '.aws', '.azure')
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        Assert-SetupPathHasNoReparsePoint -Path $current.source -Name 'Backup source directory'
        # Stream the enumeration so a giant source directory cannot allocate an
        # unbounded array before the traversal limit is checked.
        Get-ChildItem -LiteralPath $current.source -Force -ErrorAction Stop | ForEach-Object {
            $child = $_
            $Budget.visited += 1
            if ($Budget.visited -gt $Budget.maxVisited) { throw "Selective backup traversal limit exceeded at: $($current.source)" }
            $target = Join-Path $current.destination $child.Name
            if (($child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                $null = $skipped.Add($child.FullName)
                return
            }
            if ($child.PSIsContainer) {
                if ($excludedDirectoryNames -contains $child.Name -or $child.Name -match '(?i)^\.?(credential|secret|token|password)s?$') {
                    $null = $excluded.Add($child.FullName)
                    return
                }
                if ($current.depth -ge $Budget.maxDepth) { throw "Selective backup directory depth limit exceeded at: $($child.FullName)" }
                New-Item -ItemType Directory -Path $target -Force | Out-Null
                $queue.Enqueue([pscustomobject]@{ source = $child.FullName; destination = $target; depth = $current.depth + 1 })
                return
            }
            if ($child.Name -match '(?i)(^\.env(?:\.|$)|credential|secret|token|password|private.?key|(^|[._-])pat([._-]|$)|^id_(rsa|dsa|ecdsa|ed25519)(\.|$)|^\.?mcp(?:\.|$)|^settings(?:\..*)?\.json$|^(conversation|transcript|session-history)([._-].*)?\.(md|txt|json)$)' -or
                $child.Extension -match '(?i)^\.(pfx|p12|pem|key|kdbx|jsonl|ndjson|log)$' -or
                ($Mode -eq 'learning-markdown' -and $child.Extension -ine '.md')) {
                $null = $excluded.Add($child.FullName)
                return
            }
            Copy-SetupBackupFile -Source $child.FullName -Destination $target -SanitizeJson ($child.Extension -ieq '.json') -Budget $Budget
        }
    }
    return [pscustomobject][ordered]@{
        copied = $true
        skippedReparsePoints = @($skipped.ToArray())
        excludedPaths = @($excluded.ToArray())
    }
}

function New-SetupBackup {
    param(
        [Parameter(Mandatory = $true)]
        [string] $BackupBase,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]] $Items,
        [string] $ClaudeConfigPath,
        [string] $PersonalStatePath,
        [string] $ManagedDataPath,
        [string] $ManagedInstallPath,
        [ValidateRange(1, 2147483647)]
        [int] $MaxFiles = 20000,
        [ValidateRange(1, 1099511627776)]
        [long] $MaxTotalBytes = 1GB,
        [ValidateRange(1, 1073741824)]
        [long] $MaxFileBytes = 64MB,
        [ValidateRange(1, 256)]
        [int] $MaxDepth = 32,
        [ValidateRange(1, 2147483647)]
        [int] $MaxVisited = 100000
    )

    $backupBaseFull = Get-SetupFullPath -Path $BackupBase
    Assert-SetupPathHasNoReparsePoint -Path $backupBaseFull -Name 'BackupRoot'
    $backupDriveRoot = [IO.Path]::GetPathRoot($backupBaseFull)
    $backupIsNetwork = $backupBaseFull.StartsWith('\\')
    if (-not $backupIsNetwork -and -not [string]::IsNullOrWhiteSpace($backupDriveRoot)) {
        try {
            $backupIsNetwork = ((New-Object IO.DriveInfo($backupDriveRoot)).DriveType -eq [IO.DriveType]::Network)
        }
        catch {
            $backupIsNetwork = $false
        }
    }
    if ($backupIsNetwork) {
        throw "BackupRoot must be on this PC, not a network path: $backupBaseFull"
    }
    if (Test-SetupSameOrChildPath -Candidate $backupBaseFull -Parent $ClaudeConfigPath) {
        throw "BackupRoot cannot be inside the existing Claude configuration directory: $ClaudeConfigPath"
    }

    foreach ($managedRoot in @($PersonalStatePath, $ManagedDataPath, $ManagedInstallPath)) {
        if (Test-SetupSameOrChildPath -Candidate $BackupBase -Parent $managedRoot) {
            throw "BackupRoot must be separate from every Company Agent managed directory: $managedRoot"
        }
    }
    foreach ($item in $Items) {
        if ((Test-Path -LiteralPath $item.source -PathType Container) -and
            (Test-SetupSameOrChildPath -Candidate $BackupBase -Parent $item.source)) {
            throw "BackupRoot cannot be inside a directory that is being backed up: $($item.source)"
        }
    }

    $stamp = [DateTime]::Now.ToString('yyyyMMdd-HHmmss')
    $suffix = [guid]::NewGuid().ToString('N').Substring(0, 6)
    $backupPath = Join-Path $backupBaseFull ("pre-install-$stamp-$suffix")
    New-Item -ItemType Directory -Path $backupPath -Force | Out-Null
    Assert-SetupPathHasNoReparsePoint -Path $backupPath -Name 'Created backup directory'
    try {
        Protect-SetupBackupDirectory -Path $backupPath
    }
    catch {
        Remove-Item -LiteralPath $backupPath -Recurse -Force -ErrorAction SilentlyContinue
        throw "The local backup folder could not be restricted to the current Windows user. Installation has not started. Details: $($_.Exception.Message)"
    }

    $records = @()
    $skippedReparsePoints = @()
    $excludedPaths = @()
    $budget = @{
        files = 0; bytes = [long]0; visited = 0
        maxFiles = $MaxFiles; maxTotalBytes = $MaxTotalBytes; maxFileBytes = $MaxFileBytes; maxDepth = $MaxDepth; maxVisited = $MaxVisited
    }
    try {
        foreach ($item in $Items) {
            if ([IO.Path]::IsPathRooted([string]$item.relativePath) -or [string]$item.relativePath -match '[:\x00-\x1f]') { throw 'A backup item destination must be a normal relative path without streams or control characters.' }
            $destination = Get-SetupFullPath -Path (Join-Path $backupPath $item.relativePath)
            if ($destination -ieq $backupPath -or -not (Test-SetupSameOrChildPath -Candidate $destination -Parent $backupPath)) {
                throw 'A backup item destination escapes the backup directory.'
            }
            Assert-SetupPathHasNoReparsePoint -Path $destination -Name 'Backup item destination'
            $destinationParent = Split-Path -Parent $destination
            if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
                New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
            }
            $copyResult = Copy-SetupBackupItem -Source $item.source -Destination $destination -Mode ([string]$item.mode) -Budget $budget
            $required = [bool](Get-SetupPropertyValue -Object $item -Name 'required')
            if ($required -and (-not $copyResult.copied -or @($copyResult.skippedReparsePoints).Count -gt 0)) {
                throw "Required personal learning backup could not safely include a selected source or descendant: $($item.source). Junctions and symbolic links must be reviewed before installation."
            }
            $skippedReparsePoints += @($copyResult.skippedReparsePoints)
            $excludedPaths += @($copyResult.excludedPaths)
            $records += [pscustomobject][ordered]@{
                source      = $item.source
                backup      = $destination
                purpose     = $item.purpose
                mode        = $item.mode
                required    = $required
                copied      = [bool]$copyResult.copied
                itemType    = $(if (Test-Path -LiteralPath $item.source -PathType Container) { 'directory' } else { 'file' })
            }
        }

        $manifest = [pscustomobject][ordered]@{
            schemaVersion = 2
            createdAt     = [DateTime]::Now.ToString('o')
            claudeConfigRoot = $ClaudeConfigPath
            userStateRoot = $PersonalStatePath
            note          = 'Selective pre-install backup, not a complete user-state snapshot. Personal learning sources and revisions are included; runtime MCP configuration, transcripts, caches and secret-like files are excluded.'
            access        = 'Current Windows user and LocalSystem only'
            copiedFiles   = $budget.files
            accountedBytes = $budget.bytes
            limits        = [pscustomobject]@{ maxFiles = $MaxFiles; maxTotalBytes = $MaxTotalBytes; maxFileBytes = $MaxFileBytes; maxDepth = $MaxDepth; maxVisited = $MaxVisited }
            skippedReparsePoints = @($skippedReparsePoints)
            excludedPaths = @($excludedPaths)
            items         = $records
        }
        $readme = @(
            'COMPANY AGENT PRE-INSTALL BACKUP',
            '',
            'This selective backup was created before installation changes.',
            'If replacement was selected, previous-harness contains encrypted',
            'exact snapshots of the scoped instructions and settings being changed.',
            'This SELECTIVE user-only backup protects Skills, commands, agents, Hooks,',
            'settings, plugin registrations, and managed Company Agent selection files.',
            'company-agent/personal-learning contains selected personal Memory and',
            'knowledge Markdown sources plus revisions, personal Skills, sanitized',
            'config/user.json and state-format.json when present. It is NOT a full',
            'user-state snapshot. MCP registries/configuration, full transcripts,',
            'sessions, indexes, caches, temporary files and secret-like files are excluded.',
            'Secret-like JSON fields were redacted. Re-enter those values if restoring.',
            'All copied JSON files are sanitized. Filename/key filters are not a full',
            'secret scanner; never store credentials inside learning text or scripts.',
            'Junctions/symbolic links are not followed. Required personal learning',
            'items containing them block installation. See backup-manifest.json.',
            'The backup may still contain private work instructions. Do not share it.',
            '',
            'If recovery is needed:',
            '1. Close Claude Code and Company Agent.',
            '2. Open backup-manifest.json in this folder.',
            '3. Ask your support owner to restore only the listed item that is needed.',
            '4. Do not restore credentials or session caches from another user.',
            '',
            'Existing Company Agent versions are installed side by side. The prior',
            'selection can normally be restored with Rollback-CompanyAgent.ps1.'
        ) -join "`r`n"
        Write-CompanyAgentUtf8File -Path (Join-Path $backupPath 'README.txt') -Content ($readme + "`r`n")
        Write-CompanyAgentJsonAtomic -Path (Join-Path $backupPath 'backup-manifest.json') -Value $manifest
    }
    catch {
        throw "The safety backup could not be completed. Installation has not started. Partial backup: $backupPath. Details: $($_.Exception.Message)"
    }
    return $backupPath
}

function Write-SetupResultFile {
    param(
        [string] $Path,
        [Parameter(Mandatory = $true)]
        [object] $Value
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    $json = $Value | ConvertTo-Json -Depth 20
    $encoding = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, ($json + [Environment]::NewLine), $encoding)
}

function Invoke-SetupElevation {
    param(
        [Parameter(Mandatory = $true)]
        [object] $Payload,
        [Parameter(Mandatory = $true)]
        [string] $ResultPath
    )

    $Payload | Add-Member -MemberType NoteProperty -Name 'resultPath' -Value $ResultPath -Force
    $json = $Payload | ConvertTo-Json -Depth 20 -Compress
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
    $powershellPath = (Get-Command 'powershell.exe' -ErrorAction Stop | Select-Object -First 1).Source
    $argumentLine = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath.Replace('"', '""') + '" -HandoffData "' + $encoded + '"'

    try {
        $process = Start-Process -FilePath $powershellPath -ArgumentList $argumentLine -Verb RunAs -Wait -PassThru
    }
    catch {
        throw "Administrator approval was not completed. Nothing was installed. The safety backup is still available. Details: $($_.Exception.Message)"
    }

    $childResult = $null
    if (Test-Path -LiteralPath $ResultPath -PathType Leaf) {
        try {
            $childResult = Get-Content -LiteralPath $ResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        finally {
            Remove-Item -LiteralPath $ResultPath -Force -ErrorAction SilentlyContinue
        }
    }
    if ($process.ExitCode -ne 0) {
        $details = 'The elevated installer returned an error.'
        if ($null -ne $childResult -and -not [string]::IsNullOrWhiteSpace([string]$childResult.message)) {
            $details = [string]$childResult.message
        }
        throw $details
    }
    if ($null -eq $childResult -or [string]$childResult.status -ne 'ok') {
        throw 'The elevated installer finished without a readable completion report.'
    }
    return $childResult.result
}

function Get-SetupFriendlyFailure {
    param([string] $Message)
    # Recovery failures take precedence. Never promise an uncertain rollback.
    # Raw CLI errors may contain sensitive settings, so keep this summary fixed.
    if ($Message -match 'Recovery needs attention|changed during rollback') {
        return '설치 중 문제가 생겼고 이전 상태 복원도 확인이 필요합니다. 위에 표시된 백업 폴더를 보관하고 담당자에게 복구 점검을 요청하세요.'
    }
    if ($Message -match 'Core version already exists with different contents') {
        return '같은 버전 번호의 설치 파일이 기존 파일과 다릅니다. 기존 폴더를 지우지 말고, 담당자에게 버전 번호가 올라간 새 설치본을 받아 주세요.'
    }
    if ($Message -match '(?i)Python.*(not found|required|3\.11)|approved.*python|python.*경로') {
        return '사용할 Python을 확인하지 못했습니다. 회사에서 설치한 Python 3.11 이상의 python.exe 위치를 확인한 뒤 다시 실행해 주세요. 자동으로 내려받거나 설치하지 않습니다.'
    }
    if ($Message -match '(?i)Claude Code.*(required|not found)|Claude.*실행 파일') {
        return 'Claude Code 실행 파일 또는 버전 확인이 필요합니다. 평소 사용하는 Claude의 실제 실행 파일을 선택하고, 회사에서 제공한 지원 버전인지 확인해 주세요.'
    }
    if ($Message -match '(?i)project folder|Project installation needs|Select a project folder') {
        return '프로젝트 폴더를 확인하지 못했습니다. 실제로 존재하는 작업 폴더를 선택하고 다시 실행해 주세요.'
    }
    if ($Message -match '(?i)extract|bundle.*manifest|bundle.*(hash|integrity)|hash mismatch') {
        return '설치 파일 묶음을 확인하지 못했습니다. ZIP 전체를 새 폴더에 압축 해제한 뒤 Install-CompanyAgent.cmd를 실행해 주세요. 계속되면 담당자에게 원본 파일 확인을 요청하세요.'
    }
    if ($Message -match '(?i)Skill inventory|Skill.*failed') {
        return '기존 스킬 목록이나 우선 설정을 확인하지 못했습니다. 기존 스킬을 삭제하지 말고 진단 파일로 상태를 확인한 뒤 담당자에게 알려 주세요.'
    }
    if ($Message -match '(?i)interactive.*(user|session)|different.*(user|account)|owner|SID|another Claude configuration') {
        return '현재 로그인한 사용자와 Claude 설정 위치가 일치하는지 확인이 필요합니다. 다른 계정으로 실행하지 말고 본인이 평소 쓰는 Claude 환경에서 다시 진행해 주세요.'
    }
    return '설치를 완료하지 못했습니다. 기존 설정이나 개인 자료를 지우지 말고, 위에 표시된 단계와 진단 결과를 담당자에게 전달해 주세요.'
}

function Write-SetupFriendlyResult {
    param([object] $Result)
    $status = [string](Get-SetupPropertyValue -Object $Result -Name 'status')
    switch ($status) {
        'installed' { Write-Host '설치 완료. Claude Code를 닫았다 다시 열어 주세요.' }
        'updated' { Write-Host '업데이트 완료. Claude Code를 닫았다 다시 열어 주세요.' }
        'reapplied' { Write-Host '다시 적용 완료. Claude Code를 닫았다 다시 열어 주세요.' }
        'kept' { Write-Host '현재 구성을 유지했습니다. 설치·업데이트는 하지 않았습니다.' }
        'cancelled' { Write-Host '설치를 취소했습니다. 새 버전을 적용하지 않았습니다.' }
        'input-required' { Write-Host '아직 설치되지 않았습니다. 위에 안내된 항목을 선택해 다시 진행해 주세요.' }
        'dry-run' { Write-Host '미리 점검만 완료했습니다. 설치·업데이트는 하지 않았습니다.' }
        default { Write-Host '위의 단계별 결과를 확인해 주세요. 이 메시지만으로 설치 완료를 판단하지 마세요.' }
    }
    if ($status -in @('installed', 'updated', 'reapplied')) {
        Write-Host '업무별 준비 상태는 Diagnose-CompanyAgent.cmd에서 확인할 수 있습니다. Office·MCP는 별도 준비가 필요할 수 있습니다.'
    }
}

if ($FunctionsOnly) { return }

trap {
    # A bare throw in a trap produces ScriptHalted in Windows PowerShell 5.1,
    # hiding the original failure from automation and update diagnostics.
    if (-not $FriendlyOutput) { throw $_ }
    Write-Host ''
    Write-Host (Get-SetupFriendlyFailure -Message $_.Exception.Message) -ForegroundColor Red
    $errorFile = [IO.Path]::GetFileName([string]$_.InvocationInfo.ScriptName)
    if ($errorFile -match '^[A-Za-z0-9_.-]+\.ps1$') {
        Write-Host ("담당자 확인 위치: {0} / {1}번째 줄" -f $errorFile, $_.InvocationInfo.ScriptLineNumber)
    }
    Write-Host '초기 점검에서 중단되면 백업이 아직 없을 수 있습니다. 백업이 생성됐다면 위에 표시된 위치를 보관해 주세요.'
    if (-not $NonInteractive) { Write-Host '아무 키나 누르면 창을 닫습니다.' }
    exit 1
}
if ($FriendlyOutput) {
    Write-Host 'Company Agent 간편 설치'
    Write-Host '내 계정 전체 또는 한 프로젝트에 설치할 수 있습니다. 기존 설정은 먼저 확인하고 백업합니다.'
    Write-Host 'Claude Code와 회사에서 제공한 Python 3.11 이상이 필요합니다. 자동 다운로드는 하지 않습니다.'
    Write-Host '기존 모델·MCP·개인 기억·스킬은 유지합니다. 필요한 항목만 차례로 물어봅니다.'
}

# The beginner path registers a native Claude plugin for this Windows user or
# one project. Explicit machine roots keep the established administrator path.
if ([string]::IsNullOrWhiteSpace($Scope) -and [string]::IsNullOrWhiteSpace($HandoffData)) {
    if ($PSBoundParameters.ContainsKey('InstallRoot') -or $PSBoundParameters.ContainsKey('DataRoot')) {
        $Scope = 'Machine'
    }
    elseif ($DryRun -and -not $NonInteractive) {
        return [pscustomobject]@{
            status = 'input-required'; input = 'Scope'; choices = @('User', 'Project')
            message = 'Choose User for all Claude sessions of this Windows user, or Project for one folder.'
        }
    }
    elseif ($NonInteractive) { throw 'Choose the installation scope: pass -Scope User, or -Scope Project -ProjectRoot "C:\Work\MyProject".' }
    else {
        Write-Host ''
        Write-Host 'Company Agent를 어디에서 사용할까요?'
        Write-Host '  1. 내 Windows 계정의 모든 Claude Code 작업에서 사용 (기본값)'
        Write-Host '  2. 선택한 프로젝트 폴더에서만 사용'
        do { $selection = Read-Host '1 또는 2를 입력하세요. Enter를 누르면 1번' } while ($selection -notin @('', '1', '2'))
        $Scope = $(if ($selection -eq '2') { 'Project' } else { 'User' })
    }
}
if ($Scope -in @('User', 'Project')) {
    $scopedParameters = @{}
    foreach ($name in @('BundleRoot', 'Scope', 'ProjectRoot', 'UserStateRoot', 'BackupRoot', 'ClaudeConfigRoot',
        'ClaudeCommand', 'PythonCommand', 'InvokingUserProfile', 'InvokingLocalAppData', 'NonInteractive',
        'DryRun', 'SkipAdminCheck', 'SkipPrerequisiteCheck', 'SkipBundleVerification', 'ExistingHarnessAction', 'SkillConflictAction')) {
        $value = Get-Variable -Name $name -ValueOnly
        if ($null -ne $value -and -not ($value -is [string] -and [string]::IsNullOrWhiteSpace($value))) {
            $scopedParameters[$name] = $value
        }
    }
    if ($FriendlyOutput) {
        $setupResult = & (Join-Path $PSScriptRoot 'Install-ScopedCompanyAgent.ps1') @scopedParameters
        Write-SetupFriendlyResult -Result $setupResult
        if (-not $NonInteractive) { Write-Host '아무 키나 누르면 창을 닫습니다.' }
    }
    else { & (Join-Path $PSScriptRoot 'Install-ScopedCompanyAgent.ps1') @scopedParameters }
    return
}
if ($ExistingHarnessAction -ne 'Ask') {
    throw 'ExistingHarnessAction applies only to User/Project installation. Legacy Machine installation does not replace existing Claude rules or hooks.'
}
if ($SkillConflictAction -ne 'Ask') {
    throw 'SkillConflictAction applies only to User/Project installation. Legacy Machine setup reports Skill overlap warnings without changing Skill preferences.'
}

$isHandoff = -not [string]::IsNullOrWhiteSpace($HandoffData)
$completedBackupPath = $null
$handoffResultPath = $null
if ($isHandoff) {
    $handoff = ConvertFrom-SetupHandoff -Encoded $HandoffData
    $BundleRoot = [string](Get-SetupPropertyValue -Object $handoff -Name 'bundleRoot')
    $InstallRoot = [string](Get-SetupPropertyValue -Object $handoff -Name 'installRoot')
    $DataRoot = [string](Get-SetupPropertyValue -Object $handoff -Name 'dataRoot')
    $UserStateRoot = [string](Get-SetupPropertyValue -Object $handoff -Name 'userStateRoot')
    $BackupRoot = [string](Get-SetupPropertyValue -Object $handoff -Name 'backupRoot')
    $ShortcutPath = [string](Get-SetupPropertyValue -Object $handoff -Name 'shortcutPath')
    $ClaudeConfigRoot = [string](Get-SetupPropertyValue -Object $handoff -Name 'claudeConfigRoot')
    $ClaudeCommand = [string](Get-SetupPropertyValue -Object $handoff -Name 'claudeCommand')
    $PythonCommand = [string](Get-SetupPropertyValue -Object $handoff -Name 'pythonCommand')
    $InvokingUserProfile = [string](Get-SetupPropertyValue -Object $handoff -Name 'invokingUserProfile')
    $InvokingLocalAppData = [string](Get-SetupPropertyValue -Object $handoff -Name 'invokingLocalAppData')
    $completedBackupPath = [string](Get-SetupPropertyValue -Object $handoff -Name 'completedBackupPath')
    $handoffResultPath = [string](Get-SetupPropertyValue -Object $handoff -Name 'resultPath')
    $NonInteractive = [bool](Get-SetupPropertyValue -Object $handoff -Name 'nonInteractive')
    $SkipAcl = [bool](Get-SetupPropertyValue -Object $handoff -Name 'skipAcl')
    $SkipAdminCheck = [bool](Get-SetupPropertyValue -Object $handoff -Name 'skipAdminCheck')
    $SkipPrerequisiteCheck = [bool](Get-SetupPropertyValue -Object $handoff -Name 'skipPrerequisiteCheck')
    $SkipShortcut = [bool](Get-SetupPropertyValue -Object $handoff -Name 'skipShortcut')
    $SkipBundleVerification = [bool](Get-SetupPropertyValue -Object $handoff -Name 'skipBundleVerification')
    $AllowExistingCompanyAgentPlugin = [bool](Get-SetupPropertyValue -Object $handoff -Name 'allowExistingCompanyAgentPlugin')
}

$DefaultTier = 'AUTO'

try {
    if (-not $isHandoff -and -not $SkipAdminCheck -and (Test-CompanyAgentAdministrator)) {
        throw 'Run the easy Setup from a normal, non-elevated Windows session. It performs user-specific checks and requests UAC only for the managed install step. Already-elevated or software-distribution installs must use the low-level Install-CompanyAgent.ps1 flow with explicit user preflight.'
    }
    if ([string]::IsNullOrWhiteSpace($BundleRoot)) {
        $BundleRoot = Split-Path -Parent $PSScriptRoot
    }
    if ([string]::IsNullOrWhiteSpace($InvokingUserProfile)) {
        $InvokingUserProfile = $env:USERPROFILE
    }
    if ([string]::IsNullOrWhiteSpace($InvokingLocalAppData)) {
        $InvokingLocalAppData = $env:LOCALAPPDATA
    }
    if ([string]::IsNullOrWhiteSpace($ClaudeConfigRoot)) {
        $ClaudeConfigRoot = [Environment]::GetEnvironmentVariable('CLAUDE_CONFIG_DIR', 'Process')
    }
    if ([string]::IsNullOrWhiteSpace($ClaudeConfigRoot)) {
        $ClaudeConfigRoot = Join-Path $InvokingUserProfile '.claude'
    }
    if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
        $InstallRoot = Get-CompanyAgentDefaultInstallRoot
    }
    if ([string]::IsNullOrWhiteSpace($DataRoot)) {
        $DataRoot = Get-CompanyAgentDefaultDataRoot
    }
    if ([string]::IsNullOrWhiteSpace($UserStateRoot)) {
        $UserStateRoot = Join-Path $InvokingLocalAppData 'CompanyAgent'
    }
    if ([string]::IsNullOrWhiteSpace($BackupRoot)) {
        $BackupRoot = Join-Path $InvokingLocalAppData 'CompanyAgent-Backups'
    }
    if ([string]::IsNullOrWhiteSpace($ShortcutPath)) {
        $ShortcutPath = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Company Agent.lnk'
    }

    $BundleRoot = Get-SetupFullPath -Path $BundleRoot
    $InstallRoot = Get-SetupFullPath -Path $InstallRoot
    $DataRoot = Get-SetupFullPath -Path $DataRoot
    $UserStateRoot = Get-SetupFullPath -Path $UserStateRoot
    $BackupRoot = Get-SetupFullPath -Path $BackupRoot
    $ShortcutPath = Get-SetupFullPath -Path $ShortcutPath
    $ClaudeConfigRoot = Get-SetupFullPath -Path $ClaudeConfigRoot
    $InvokingUserProfile = Get-SetupFullPath -Path $InvokingUserProfile
    $InvokingLocalAppData = Get-SetupFullPath -Path $InvokingLocalAppData

    if (-not (Test-Path -LiteralPath (Join-Path $BundleRoot 'bundle-manifest.json') -PathType Leaf)) {
        throw "This easy installer must be run from an extracted Company Agent offline bundle. Extract the ZIP first, then run deploy\Install-CompanyAgent.cmd. Bundle root checked: $BundleRoot"
    }

    Write-Host ''
    Write-Host 'Company Agent easy setup'
    Write-Host '------------------------'
    Write-Host '[1/4] Checking Claude Code, Python, and the installation package...'

    if (-not $SkipPrerequisiteCheck) {
        $resolvedClaude = Resolve-SetupCommand -Command $ClaudeCommand
        if ([string]::IsNullOrWhiteSpace($resolvedClaude)) {
            throw 'Claude Code was not found. Confirm that the already-installed claude command works in a normal PowerShell window, then run setup again.'
        }
        $resolvedPython = Get-SetupPythonForInstall -PreferredCommand $PythonCommand -NonInteractive:$NonInteractive -DryRun:$DryRun
        $ClaudeCommand = $resolvedClaude
        try {
            Assert-CompanyAgentPrerequisites -ClaudeCommand $ClaudeCommand -PythonCommand $resolvedPython
        }
        catch {
            throw "A required program check failed. No installation changes were made. Details: $($_.Exception.Message)"
        }
        # Store the same absolute executable that passed the normal-user
        # preflight. The launcher exposes it only to its own child process.
        $PythonCommand = $resolvedPython
    }

    $manifest = $null
    if ($SkipBundleVerification) {
        $manifest = Read-CompanyAgentJson -Path (Join-Path $BundleRoot 'bundle-manifest.json')
    }
    else {
        try {
            $manifest = Test-CompanyAgentBundleIntegrity -BundleRoot $BundleRoot
        }
        catch {
            throw "The installation package failed its safety check. Do not continue with this copy. Details: $($_.Exception.Message)"
        }
    }

    $currentPointerPath = Get-CompanyAgentCurrentPointerPath -DataRoot $DataRoot
    $existingInstall = Test-Path -LiteralPath $currentPointerPath -PathType Leaf
    $DefaultTier = $DefaultTier.ToUpperInvariant()

    $backupItems = @(Get-SetupBackupItems `
        -ClaudeConfigPath $ClaudeConfigRoot `
        -PersonalStatePath $UserStateRoot `
        -ManagedDataPath $DataRoot `
        -ManagedInstallPath $InstallRoot `
        -ManagedShortcutPath $ShortcutPath)
    $skillOverlaps = @(Get-SetupSkillOverlaps -BundlePath $BundleRoot -ClaudeConfigPath $ClaudeConfigRoot -PersonalStatePath $UserStateRoot)
    $claudeCompatibility = Get-SetupClaudeCompatibility -ClaudeConfigPath $ClaudeConfigRoot
    $pluginCollisionBlocked = $claudeCompatibility.companyAgentNameCollision -and (-not $AllowExistingCompanyAgentPlugin)
    $settingsModelOverrides = @(Get-CompanyAgentSubagentModelForceSettings `
        -SettingsPaths @((Join-Path $ClaudeConfigRoot 'settings.json')) `
        -IncludeWindowsPolicy)
    $settingsModelOverrideBlocked = $settingsModelOverrides.Count -gt 0
    $subagentModelOverrides = @(@('CLAUDE_CODE_SUBAGENT_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE') | Where-Object {
        -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_, 'Process'))
    })
    $subagentModelOverrideDetected = $subagentModelOverrides.Count -gt 0
    foreach ($managedRoot in @($UserStateRoot, $DataRoot, $InstallRoot)) {
        if (Test-SetupSameOrChildPath -Candidate $BackupRoot -Parent $managedRoot) {
            throw "BackupRoot must be outside Company Agent managed directories. Choose a separate path instead of: $BackupRoot"
        }
    }

    if ($DryRun) {
        return [pscustomobject][ordered]@{
            status                = 'dry-run'
            action                = $(if ($existingInstall) { 'update-or-reinstall' } else { 'fresh-install' })
            bundleRoot            = $BundleRoot
            bundleVersion         = [string]$manifest.bundleVersion
            installRoot           = $InstallRoot
            dataRoot              = $DataRoot
            userStateRoot         = $UserStateRoot
            backupRoot            = $BackupRoot
            backupItems           = $backupItems
            possibleSkillOverlaps = $skillOverlaps
            claudeCompatibility    = $claudeCompatibility
            pluginCollisionBlocked = $pluginCollisionBlocked
            settingsModelOverrideBlocked = $settingsModelOverrideBlocked
            settingsModelOverrides = $settingsModelOverrides
            modelMap              = [pscustomobject][ordered]@{ SMALL = 'haiku'; MEDIUM = 'sonnet'; LARGE = 'opus' }
            modelSource           = 'existing Claude Code alias configuration'
            defaultTier           = $DefaultTier
            claudeConfigRoot       = $ClaudeConfigRoot
            subagentModelOverrideDetected = $subagentModelOverrideDetected
            subagentModelOverrides = $subagentModelOverrides
            needsElevation        = ((-not (Test-CompanyAgentAdministrator)) -and (-not $SkipAdminCheck))
            mutatesClaudeUserHome = $false
            promptsForUserProfile = $false
        }
    }

    if ($pluginCollisionBlocked) {
        throw 'A user-installed Claude plugin named company-agent already exists. Setup stopped before making a backup or installation change. Remove or rename that plugin first. Administrators may use -AllowExistingCompanyAgentPlugin only after reviewing the duplicate.'
    }
    if ($settingsModelOverrideBlocked) {
        $locations = @($settingsModelOverrides | ForEach-Object { "$($_.variable) in $($_.source)" }) -join '; '
        throw "A Claude settings source forces all subagents to one model, so SMALL/MEDIUM/LARGE routing cannot work: $locations. Remove that setting through your Claude or IT configuration owner, then run Setup again. No setting was changed."
    }

    Write-Host ("Package: Core {0}, Knowledge {1}" -f [string]$manifest.coreVersion, [string]$manifest.knowledgeVersion)
    Write-Host ("Mode: {0}" -f $(if ($existingInstall) { 'safe update or reinstall' } else { 'new installation' }))
    Write-Host 'Existing Claude model aliases will be reused. Model IDs will not be requested or copied.'
    Write-Host '  SMALL=haiku, MEDIUM=sonnet, LARGE=opus'
    Write-Host ''
    Write-Host '[2/4] Protecting existing personal settings before installation...'
    Write-Host 'Company Agent does not overwrite your existing .claude directory.'
    Write-Host 'The following existing information is copied only as a safety backup:'
    Write-Host '  - .claude Skills, commands, agents, Hooks, Markdown instructions, and settings'
    Write-Host '  - Claude plugin registration JSON files (not caches, credentials, or sessions)'
    Write-Host '  - existing Company Agent activation pointers and launcher scripts'
    Write-Host '  - selected personal Memory/Knowledge sources and revisions, Skills, and sanitized user configuration'
    Write-Host ("Company Agent personal state is preserved in place: $UserStateRoot")
    if ($skillOverlaps.Count -gt 0) {
        Write-Warning ('Possible duplicate Skill names were found: ' + (($skillOverlaps | ForEach-Object { $_.name }) -join ', '))
        Write-Warning 'Nothing will be overwritten. If Claude later reports an ambiguous Skill, keep one definition or rename the personal one.'
    }
    if ($claudeCompatibility.installedPlugins.Count -gt 0) {
        Write-Host ('Existing Claude plugins remain enabled: ' + ($claudeCompatibility.installedPlugins -join ', '))
    }
    if ($claudeCompatibility.parallelHookProviders.Count -gt 0) {
        Write-Warning ('Existing Hooks will run alongside Company Agent Hooks: ' + ($claudeCompatibility.parallelHookProviders -join '; '))
        Write-Warning 'After first launch, run a simple read-only prompt and one temporary-file edit as a compatibility check.'
    }
    if ($claudeCompatibility.companyAgentNameCollision) {
        Write-Warning 'An installed Claude plugin with the Company Agent name remains enabled under the explicit administrator override.'
    }
    if ($subagentModelOverrideDetected) {
        Write-Warning ('Model-forcing environment setting detected: ' + ($subagentModelOverrides -join ', ') + '. It would force every worker to one model.')
        Write-Warning 'Company Agent removes that override only inside its own child Claude process; your Windows or Claude setting is not changed.'
    }

    if ([string]::IsNullOrWhiteSpace($completedBackupPath)) {
        $completedBackupPath = New-SetupBackup `
            -BackupBase $BackupRoot `
            -Items $backupItems `
            -ClaudeConfigPath $ClaudeConfigRoot `
            -PersonalStatePath $UserStateRoot `
            -ManagedDataPath $DataRoot `
            -ManagedInstallPath $InstallRoot
    }
    Write-Host ("Safety backup completed: $completedBackupPath")

    $needsElevation = (-not (Test-CompanyAgentAdministrator)) -and (-not $SkipAdminCheck)
    if ($needsElevation) {
        Write-Host ''
        Write-Host '[3/4] Windows will ask for administrator approval.'
        Write-Host 'No model, MCP, Outlook, or display-name input is requested in the administrator profile.'
        $resultPath = Join-Path ([IO.Path]::GetTempPath()) ('CompanyAgent-Setup-Result-' + [guid]::NewGuid().ToString('N') + '.json')
        $payload = [pscustomobject][ordered]@{
            schemaVersion          = 1
            bundleRoot            = $BundleRoot
            installRoot           = $InstallRoot
            dataRoot              = $DataRoot
            userStateRoot         = $UserStateRoot
            backupRoot            = $BackupRoot
            shortcutPath          = $ShortcutPath
            claudeConfigRoot      = $ClaudeConfigRoot
            claudeCommand         = $ClaudeCommand
            pythonCommand         = $PythonCommand
            invokingUserProfile   = $InvokingUserProfile
            invokingLocalAppData  = $InvokingLocalAppData
            completedBackupPath   = $completedBackupPath
            nonInteractive        = [bool]$NonInteractive
            skipAcl               = [bool]$SkipAcl
            skipAdminCheck        = [bool]$SkipAdminCheck
            skipPrerequisiteCheck = $true
            skipShortcut          = [bool]$SkipShortcut
            skipBundleVerification = [bool]$SkipBundleVerification
            allowExistingCompanyAgentPlugin = [bool]$AllowExistingCompanyAgentPlugin
        }
        $elevatedResult = Invoke-SetupElevation -Payload $payload -ResultPath $resultPath
        Write-Host ''
        Write-Host '[4/4] Installation completed.'
        Write-Host 'Open Company Agent from the Start menu as your normal Windows user.'
        Write-Host 'Personal folders initialize automatically without questions on first launch.'
        Write-Host 'Outlook identity is configured separately only when the Outlook MCP is first used.'
        Write-Host ("Safety backup: $completedBackupPath")
        return $elevatedResult
    }

    Write-Host ''
    Write-Host '[3/4] Installing the managed core and Corporate Knowledge...'
    $installerParameters = @{
        BundleRoot             = $BundleRoot
        DefaultTier            = $DefaultTier
        UseExistingClaudeModels = $true
        InstallRoot            = $InstallRoot
        DataRoot               = $DataRoot
        UserStateRoot          = $UserStateRoot
        ClaudeCommand          = $ClaudeCommand
        PythonCommand          = $PythonCommand
        ShortcutPath           = $ShortcutPath
        SkipAcl                = $SkipAcl
        SkipAdminCheck         = $SkipAdminCheck
        SkipPrerequisiteCheck  = $true
        SkipShortcut           = $SkipShortcut
        SkipBundleVerification = $SkipBundleVerification
    }
    if ($existingInstall) {
        $operationResult = & (Join-Path $BundleRoot 'deploy\Update-CompanyAgent.ps1') @installerParameters
    }
    else {
        $operationResult = & (Join-Path $BundleRoot 'deploy\Install-CompanyAgent.ps1') @installerParameters
    }

    $finalResult = [pscustomobject][ordered]@{
        status                 = 'installed'
        action                 = $(if ($existingInstall) { 'updated-or-reinstalled' } else { 'fresh-install' })
        coreVersion            = [string]$manifest.coreVersion
        knowledgeVersion       = [string]$manifest.knowledgeVersion
        installRoot            = $InstallRoot
        dataRoot               = $DataRoot
        userStateRoot          = $UserStateRoot
        safetyBackup           = $completedBackupPath
        possibleSkillOverlaps  = $skillOverlaps
        claudeCompatibility    = $claudeCompatibility
        modelMapSource         = 'existing Claude Code aliases'
        subagentModelOverrideDetected = $subagentModelOverrideDetected
        subagentModelOverrides = $subagentModelOverrides
        personalInitialization = 'automatic-on-normal-user-first-launch-without-input'
        underlyingResult       = $operationResult
    }

    Write-Host ''
    Write-Host '[4/4] Installation completed.'
    Write-Host 'No existing Claude user Skill or setting was overwritten.'
    Write-Host 'Open Company Agent from the Start menu as your normal Windows user.'
    Write-Host 'Personal folders initialize automatically without questions on first launch.'
    Write-Host 'Outlook identity is configured separately only when the Outlook MCP is first used.'
    Write-Host ("Safety backup: $completedBackupPath")

    if ($isHandoff) {
        Write-SetupResultFile -Path $handoffResultPath -Value ([pscustomobject][ordered]@{
            status = 'ok'
            result = $finalResult
        })
    }
    $finalResult
}
catch {
    $message = $_.Exception.Message
    Write-Host ''
    Write-Host 'Setup stopped safely.' -ForegroundColor Red
    Write-Host $message -ForegroundColor Red
    Write-Host 'The existing Claude user directory was not modified by this installer.'
    if (-not [string]::IsNullOrWhiteSpace($completedBackupPath)) {
        Write-Host ("Pre-install backup: $completedBackupPath")
    }
    Write-Host 'If an older Company Agent was already installed, its versioned core and personal state remain on disk.'
    if (-not [string]::IsNullOrWhiteSpace([string]$InstallRoot)) {
        $rollbackPath = Join-Path ([string]$InstallRoot) 'bin\Rollback-CompanyAgent.ps1'
        if (Test-Path -LiteralPath $rollbackPath -PathType Leaf) {
            Write-Host ("Recovery command (administrator): powershell.exe -NoProfile -File `"$rollbackPath`"")
        }
    }
    if ($isHandoff) {
        Write-SetupResultFile -Path $handoffResultPath -Value ([pscustomobject][ordered]@{
            status  = 'error'
            message = $message
            backup  = $completedBackupPath
        })
    }
    throw
}
