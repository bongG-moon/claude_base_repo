# Optional scoped-install maintenance. Nothing runs when this file is loaded.
# Only verified, unreferenced version directories are eligible. Personal state,
# backups, setup caches, source bundles and machine installations are never targets.
if (-not (Get-Command Read-CompanyAgentJson -ErrorAction SilentlyContinue)) {
    . (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')
}

function Get-CompanyAgentCleanupProperty {
    param([object] $Object, [string] $Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -ne $property) { return $property.Value }
    return $null
}

function Get-CompanyAgentCleanupHash {
    param([string] $Text)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-', '').ToLowerInvariant() }
    finally { $hash.Dispose() }
}

function Get-CompanyAgentCleanupFullPath {
    param([string] $Path)
    # Relative, drive-relative, UNC and device paths are not cleanup authority.
    if ($Path -notmatch '^[A-Za-z]:[\\/]' -or $Path.Substring(2) -match ':') { throw 'Cleanup requires an absolute local path.' }
    return [IO.Path]::GetFullPath($Path).TrimEnd([char[]]@('\', '/'))
}

function Test-CompanyAgentCleanupContained {
    param([string] $Path, [string] $Root)
    $full = Get-CompanyAgentCleanupFullPath $Path
    $base = Get-CompanyAgentCleanupFullPath $Root
    return ($full -ieq $base -or $full.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase))
}

function Assert-CompanyAgentCleanupPath {
    param([string] $Path, [string] $Root)
    $full = Get-CompanyAgentCleanupFullPath $Path
    if ($Root -and -not (Test-CompanyAgentCleanupContained $full $Root)) { throw 'Cleanup path escaped its owned root.' }
    Assert-CompanyAgentPathHasNoReparsePoint -Path $full -Name 'Cleanup path'
    return $full
}

function Assert-CompanyAgentCleanupNoStreams {
    param([string] $Path)
    # Windows PowerShell 5.1 Get-Item -Stream does not enumerate directory ADS.
    # Use the Windows stream API for both files and directories; failure defers.
    if (-not ('CompanyAgent.CleanupStreams' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
namespace CompanyAgent {
    public static class CleanupStreams {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct StreamData {
            public long Size;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 296)] public string Name;
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr FindFirstStreamW(string path, int level, out StreamData data, int flags);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool FindNextStreamW(IntPtr handle, out StreamData data);
        [DllImport("kernel32.dll")] private static extern bool FindClose(IntPtr handle);
        public static void AssertNone(string path) {
            StreamData data;
            IntPtr handle = FindFirstStreamW(path, 0, out data, 0);
            if (handle == new IntPtr(-1)) {
                int error = Marshal.GetLastWin32Error();
                if (error == 38) return;
                throw new Win32Exception(error);
            }
            try {
                do {
                    if (data.Name != "::$DATA") throw new InvalidOperationException("Additional file or directory data streams were found; preserved.");
                } while (FindNextStreamW(handle, out data));
                int error = Marshal.GetLastWin32Error();
                if (error != 38) throw new Win32Exception(error);
            } finally { FindClose(handle); }
        }
    }
}
'@ -ErrorAction Stop
    }
    [CompanyAgent.CleanupStreams]::AssertNone($Path)
}

function Get-CompanyAgentCleanupTree {
    param([string] $Root)
    $base = Assert-CompanyAgentCleanupPath $Root
    if (-not (Test-Path -LiteralPath $base -PathType Container)) { throw 'Cleanup directory is missing.' }
    Assert-CompanyAgentCleanupNoStreams $base
    $files = New-Object 'Collections.Generic.List[object]'
    $directories = New-Object 'Collections.Generic.List[string]'
    $pending = New-Object 'Collections.Generic.Stack[string]'
    $pending.Push($base)
    while ($pending.Count) {
        $directory = $pending.Pop()
        $null = Assert-CompanyAgentCleanupPath $directory $base
        foreach ($item in @(Get-ChildItem -LiteralPath $directory -Force -ErrorAction Stop)) {
            $null = Assert-CompanyAgentCleanupPath $item.FullName $base
            $relative = $item.FullName.Substring($base.Length + 1).Replace('\', '/')
            # NTFS alternate streams can hold user data invisible to ordinary
            # hashes and directory listings. Unknown streams are never erased.
            Assert-CompanyAgentCleanupNoStreams $item.FullName
            if ($item.PSIsContainer) { $directories.Add($relative); $pending.Push($item.FullName) }
            else {
                $files.Add([pscustomobject]@{ path = $relative; length = [int64]$item.Length; sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant() })
            }
            if ($files.Count + $directories.Count -gt 30000) { throw 'Cleanup tree exceeds its bounded inventory.' }
        }
    }
    return [pscustomobject]@{ files = @($files | Sort-Object path); directories = @($directories | Sort-Object) }
}

function Test-CompanyAgentCleanupTreeEqual {
    param([object] $Actual, [object] $Expected)
    $left = @($Actual.files | Sort-Object path | ForEach-Object { '{0}|{1}|{2}' -f $_.path, $_.length, $_.sha256 })
    $right = @($Expected.files | Sort-Object path | ForEach-Object { '{0}|{1}|{2}' -f $_.path, $_.length, $_.sha256 })
    return (($left -join "`n") -ceq ($right -join "`n") -and
        (@($Actual.directories | Sort-Object) -join "`n") -ceq (@($Expected.directories | Sort-Object) -join "`n"))
}

function Enter-CompanyAgentVersionMaintenance {
    param([string] $MarketplaceRoot)
    $path = Assert-CompanyAgentCleanupPath $MarketplaceRoot
    $mutex = New-Object Threading.Mutex($false, ('Local\CompanyAgentVersionMaintenance-' + (Get-CompanyAgentCleanupHash $path.ToUpperInvariant())))
    $held = $false
    try {
        try { $held = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held = $true }
        if (-not $held) { throw 'Another Company Agent installation or cleanup is running.' }
        return [pscustomobject]@{ mutex = $mutex; held = $true }
    }
    catch { $mutex.Dispose(); throw }
}

function Exit-CompanyAgentVersionMaintenance {
    param([object] $Lease)
    if ($null -ne $Lease -and $Lease.held) {
        try { $Lease.mutex.ReleaseMutex() } finally { $Lease.held = $false; $Lease.mutex.Dispose() }
    }
}

function New-CompanyAgentCleanupReceipt {
    param([string] $ReleaseRoot, [string] $MarketplaceRoot, [switch] $NewlyCreated)
    if (-not $NewlyCreated) { throw 'Only a newly created, successfully installed release may receive a cleanup receipt.' }
    $versions = Join-Path (Assert-CompanyAgentCleanupPath $MarketplaceRoot) 'versions'
    $release = Assert-CompanyAgentCleanupPath $ReleaseRoot $versions
    if ((Split-Path -Parent $release) -ine $versions -or (Split-Path -Leaf $release) -notmatch '^\d+\.\d+\.\d+$') { throw 'Not a managed release directory.' }
    $path = Join-Path $release 'cleanup-manifest.json'
    if (Test-Path -LiteralPath $path) { throw 'A cleanup receipt already exists; existing files must never be re-sealed.' }
    $record = Read-CompanyAgentJson (Join-Path $release 'release.json')
    if ([string]$record.coreVersion -cne (Split-Path -Leaf $release) -or [string]$record.payloadHash -notmatch '^[a-f0-9]{64}$') { throw 'Release identity is invalid.' }
    $tree = Get-CompanyAgentCleanupTree $release
    Write-CompanyAgentJsonAtomic -Path $path -Value ([pscustomobject]@{
        schemaVersion = 1; kind = 'company-agent-scoped-immutable-release'; coreVersion = [string]$record.coreVersion
        payloadHash = [string]$record.payloadHash; files = $tree.files; directories = $tree.directories
    })
    return $path
}

function Get-CompanyAgentCleanupStrings {
    param([object] $Value)
    if ($null -eq $Value) { return }
    if ($Value -is [string]) { $Value; return }
    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [pscustomobject]) {
        foreach ($entry in $Value) { Get-CompanyAgentCleanupStrings $entry }; return
    }
    if ($Value -is [pscustomobject]) {
        foreach ($property in $Value.PSObject.Properties) { Get-CompanyAgentCleanupStrings $property.Value }
    }
}

function Get-CompanyAgentCleanupReferences {
    param([string] $LocalRoot, [string] $ClaudeConfigRoot, [string] $CurrentCoreVersion, [string[]] $ProtectedPaths)
    $marketplace = Join-Path $LocalRoot 'CompanyAgent-Distribution\marketplace'
    $registrations = Join-Path $LocalRoot 'CompanyAgent\installations'
    $paths = New-Object 'Collections.Generic.List[string]'
    $strings = New-Object 'Collections.Generic.List[string]'
    $protectedRoots = New-Object 'Collections.Generic.List[string]'
    $versions = New-Object 'Collections.Generic.List[string]'
    $versions.Add($CurrentCoreVersion)
    foreach ($protected in $ProtectedPaths) { if ($protected) { $protectedRoots.Add((Get-CompanyAgentCleanupFullPath $protected)) } }
    $files = New-Object 'Collections.Generic.List[string]'
    # Any unknown registration file/layout prevents guessing about hidden scopes.
    $registrationTree = Get-CompanyAgentCleanupTree $registrations
    foreach ($directory in $registrationTree.directories) {
        if ($directory -notmatch '^(user|projects|projects/[a-fA-F0-9]{16})$') { throw 'Unknown scope registration directory.' }
    }
    foreach ($record in $registrationTree.files) {
        if ($record.path -notmatch '^(user|projects/[a-fA-F0-9]{16})/company-agent-install\.json$') { throw 'Unknown scope registration layout.' }
        $path = Join-Path $registrations $record.path.Replace('/', '\')
        $files.Add($path)
        $registration = Read-CompanyAgentJson $path
        $scope = [string](Get-CompanyAgentCleanupProperty $registration 'scope')
        if ((Get-CompanyAgentCleanupProperty $registration 'schemaVersion') -ne 1 -or
            [string](Get-CompanyAgentCleanupProperty $registration 'pluginId') -cne 'company-agent@company-agent-local' -or
            [string](Get-CompanyAgentCleanupProperty $registration 'coreVersion') -notmatch '^\d+\.\d+\.\d+$' -or
            $scope -notin @('User', 'Project') -or ($scope -eq 'User') -ne ($record.path -like 'user/*')) { throw 'Invalid scope registration.' }
        if ((Get-CompanyAgentCleanupFullPath ([string]$registration.claudeConfigRoot)) -ine $ClaudeConfigRoot) { throw 'Another Claude profile shares these versions.' }
        $versions.Add([string]$registration.coreVersion)
        foreach ($name in @('userStateRoot', 'knowledgeBaseRoot', 'managedConfigPath', 'pythonCommand')) {
            $strings.Add((Get-CompanyAgentCleanupFullPath ([string](Get-CompanyAgentCleanupProperty $registration $name))))
        }
        $protectedRoots.Add((Get-CompanyAgentCleanupFullPath ([string]$registration.userStateRoot)))
        if ($scope -eq 'Project') {
            $project = Get-CompanyAgentCleanupFullPath ([string]$registration.projectRoot)
            $strings.Add($project)
            $protectedRoots.Add($project)
            $files.Add((Join-Path $project '.claude\settings.json'))
            $files.Add((Join-Path $project '.claude\settings.local.json'))
        }
    }
    foreach ($relative in @('settings.json', 'settings.local.json', 'plugins\installed_plugins.json', 'plugins\known_marketplaces.json')) {
        $files.Add((Join-Path $ClaudeConfigRoot $relative))
    }
    $manifestPath = Join-Path $marketplace '.claude-plugin\marketplace.json'
    $files.Add($manifestPath)
    # Legacy machine rollback pointers are read only, never cleanup targets.
    foreach ($base in @((Join-Path $LocalRoot 'CompanyAgent'), $(if ($env:ProgramData) { Join-Path $env:ProgramData 'CompanyAgent' }))) {
        if ($base) { foreach ($name in @('current', 'previous')) { $files.Add((Join-Path $base ('state\' + $name + '.json'))) } }
    }
    $inventoryPath = Join-Path $ClaudeConfigRoot 'plugins\installed_plugins.json'
    $null = Assert-CompanyAgentCleanupPath $inventoryPath
    $inventory = Read-CompanyAgentJson $inventoryPath
    if ((Get-CompanyAgentCleanupProperty $inventory 'version') -ne 2 -or (Get-CompanyAgentCleanupProperty $inventory 'plugins') -isnot [pscustomobject]) { throw 'Unknown Claude plugin inventory.' }
    $entries = @(Get-CompanyAgentCleanupProperty $inventory.plugins 'company-agent@company-agent-local')
    if ($entries.Count -eq 0 -or $null -eq $entries[0]) { throw 'Current Company Agent registration is missing.' }
    $currentFound = $false
    foreach ($entry in $entries) {
        if ([string](Get-CompanyAgentCleanupProperty $entry 'scope') -notin @('user', 'local', 'project') -or
            [string](Get-CompanyAgentCleanupProperty $entry 'version') -notmatch '^\d+\.\d+\.\d+$') { throw 'Unknown Claude scope or version.' }
        $installedPath = Get-CompanyAgentCleanupFullPath ([string]$entry.installPath)
        $strings.Add($installedPath)
        $files.Add((Join-Path $installedPath 'company-agent-install.json'))
        $files.Add((Join-Path $installedPath 'hooks\hooks.json'))
        $versions.Add([string]$entry.version)
        if ([string]$entry.version -ceq $CurrentCoreVersion) { $currentFound = $true }
        $projectPath = [string](Get-CompanyAgentCleanupProperty $entry 'projectPath')
        if ($projectPath) {
            $projectPath = Get-CompanyAgentCleanupFullPath $projectPath
            $strings.Add($projectPath)
            $protectedRoots.Add($projectPath)
            $files.Add((Join-Path $projectPath '.claude\settings.json'))
            $files.Add((Join-Path $projectPath '.claude\settings.local.json'))
        }
    }
    if (-not $currentFound) { throw 'The new version is not registered in Claude.' }
    foreach ($plugin in $inventory.plugins.PSObject.Properties) {
        foreach ($entry in @($plugin.Value)) {
            $pluginPath = Get-CompanyAgentCleanupFullPath ([string](Get-CompanyAgentCleanupProperty $entry 'installPath'))
            # Optional compatibility repair can point another plugin's Python
            # hook at a Company Agent runtime. Read references, never its data.
            $files.Add((Join-Path $pluginPath 'hooks\hooks.json'))
        }
    }
    $null = Assert-CompanyAgentCleanupPath $manifestPath
    $marketplaceDocument = Read-CompanyAgentJson $manifestPath
    $pluginEntries = @($marketplaceDocument.plugins | Where-Object { $_.name -ceq 'company-agent' })
    if ($marketplaceDocument.name -cne 'company-agent-local' -or $pluginEntries.Count -ne 1 -or
        [string]$pluginEntries[0].source -notmatch '^\./versions/(\d+\.\d+\.\d+)/plugin$') { throw 'Unknown marketplace source.' }
    $versions.Add($Matches[1])
    $snapshot = New-Object 'Collections.Generic.List[string]'
    $seen = @{}
    for ($index = 0; $index -lt $files.Count; $index++) {
        $file = $files[$index]
        if ($seen.ContainsKey($file)) { continue }
        $seen[$file] = $true
        if ($seen.Count -gt 10000) { throw 'Reference inventory exceeds its safe bound.' }
        $null = Assert-CompanyAgentCleanupPath $file
        if (Test-Path -LiteralPath $file -PathType Leaf) {
            $value = Read-CompanyAgentJson $file
            $snapshot.Add($file + '|' + (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash)
            foreach ($text in @(Get-CompanyAgentCleanupStrings $value)) { $strings.Add($text) }
            $runtimePath = [string](Get-CompanyAgentCleanupProperty $value 'runtimeSelectionPath')
            if ($runtimePath) { $files.Add((Get-CompanyAgentCleanupFullPath $runtimePath)) }
            if ($file -match '[\\/]state[\\/](current|previous)\.json$') {
                $rollbackVersion = [string](Get-CompanyAgentCleanupProperty $value 'coreVersion')
                if ($rollbackVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Unknown rollback selection.' }
                $versions.Add($rollbackVersion)
            }
        }
        elseif (Test-Path -LiteralPath $file) { throw 'A reference file is not a regular file.' }
        else { $snapshot.Add($file + '|missing') }
    }
    $snapshot.Add(($registrationTree | ConvertTo-Json -Depth 30 -Compress))
    return [pscustomobject]@{ hash = Get-CompanyAgentCleanupHash (@($snapshot | Sort-Object) -join "`n"); strings = $strings.ToArray(); protectedPaths = $protectedRoots.ToArray(); versions = @($versions | Sort-Object -Unique) }
}

function Get-CompanyAgentCleanupProcessBlocker {
    # Failure to inspect processes means deferred cleanup, never permission to delete.
    foreach ($process in @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)) {
        $name = [string]$process.Name
        $command = [string]$process.CommandLine
        if ($name -match '^(?i:claude|claude-code)(?:\.exe)?$' -or
            ($name -match '^(?i:node|python|pythonw)(?:\.exe)?$' -and
             ($command -match '(?i)claude-code|[/\\]claude(?:\.js|\.cjs)?(?:\s|\x22|$)|CompanyAgent-Distribution|company[_-]agent')) -or
            ($name -match '^(?i:node|python|pythonw)(?:\.exe)?$' -and -not $command)) {
            return 'Close running Claude and Company Agent sessions before deleting old versions.'
        }
    }
    return $null
}

function Test-CompanyAgentCleanupProtected {
    param([string] $Path, [string] $Version, [object] $References)
    if ($Version -in $References.versions) { return $true }
    $full = (Get-CompanyAgentCleanupFullPath $Path).Replace('/', '\')
    foreach ($protected in $References.protectedPaths) {
        if ((Test-CompanyAgentCleanupContained $full $protected) -or (Test-CompanyAgentCleanupContained $protected $full)) { return $true }
    }
    foreach ($text in $References.strings) {
        $value = ([string]$text).Replace('/', '\')
        # Also handles launcher paths embedded in hook command strings.
        if ($value.IndexOf($full, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
    }
    return $false
}

function Get-CompanyAgentCleanupBundleEvidence {
    param([string] $LocalRoot, [string] $BundleRoot)
    $roots = New-Object 'Collections.Generic.List[string]'
    if ($BundleRoot) { $roots.Add((Assert-CompanyAgentCleanupPath $BundleRoot)) }
    $cache = Join-Path $LocalRoot 'CompanyAgent\setup-cache'
    $null = Assert-CompanyAgentCleanupPath $cache
    if (Test-Path -LiteralPath $cache -PathType Container) {
        foreach ($entry in @(Get-ChildItem -LiteralPath $cache -Directory -Force)) {
            if ($entry.Name -notmatch '^\d+\.\d+\.\d+-[a-f0-9]{16}-[a-f0-9]{8}$') { continue }
            try { $roots.Add((Assert-CompanyAgentCleanupPath (Join-Path $entry.FullName 'bundle') $cache)) } catch { }
        }
    }
    $result = @{}
    foreach ($root in @($roots | Sort-Object -Unique)) {
        try {
            # Walk without following links before the common manifest validator.
            $null = Get-CompanyAgentCleanupTree $root
            $manifest = Test-CompanyAgentBundleIntegrity $root
            $records = @($manifest.files | Where-Object { $_.path -like 'payload/*' } | Sort-Object path)
            $hash = Get-CompanyAgentCleanupHash ((@($records | ForEach-Object { "$($_.path)|$($_.sha256)|$($_.length)" })) -join "`n")
            $result[$hash] = [pscustomobject]@{ root = $root; manifest = $manifest; records = $records }
        }
        catch { # An incomplete/modified cache is not evidence and is never removed.
        }
    }
    return $result
}

function Assert-CompanyAgentCleanupJsonFields {
    param([object] $Value, [string[]] $Names)
    if ((@($Value.PSObject.Properties.Name | Sort-Object) -join '|') -cne (@($Names | Sort-Object) -join '|')) { throw 'Unknown installer metadata fields.' }
}

function Test-CompanyAgentCleanupLegacyRelease {
    param([string] $ReleaseRoot, [string] $LocalRoot, [string] $ClaudeConfigRoot, [object] $Tree, [object] $Evidence)
    $release = Read-CompanyAgentJson (Join-Path $ReleaseRoot 'release.json')
    Assert-CompanyAgentCleanupJsonFields $release @('coreVersion', 'knowledgeVersion', 'payloadHash')
    if ($release.coreVersion -cne (Split-Path -Leaf $ReleaseRoot) -or $release.coreVersion -cne $Evidence.manifest.coreVersion -or
        $release.knowledgeVersion -cne $Evidence.manifest.knowledgeVersion) { throw 'Legacy release identity mismatch.' }
    $expected = @{}
    foreach ($record in $Evidence.records) {
        $path = [string]$record.path
        if ($path.StartsWith('payload/core/plugin/')) { $target = 'plugin/' + $path.Substring(20) }
        elseif ($path.StartsWith('payload/knowledge/')) { $target = 'knowledge/' + $path.Substring(18) }
        elseif ($path.StartsWith('payload/config/')) { $target = 'config/' + $path.Substring(15) }
        else { throw 'Unknown legacy payload section.' }
        $expected[$target] = $record
    }
    $metadataPath = Join-Path $ReleaseRoot 'plugin\company-agent-install.json'
    $metadata = Read-CompanyAgentJson $metadataPath
    Assert-CompanyAgentCleanupJsonFields $metadata @('schemaVersion', 'registrationsRoot', 'coreVersion', 'claudeConfigRoot', 'claudeConfigDirOverride', 'knowledgeBaseRoot', 'managedConfigPath', 'pythonCommand', 'runtimeSelectionPath')
    if ($metadata.schemaVersion -ne 1 -or $metadata.coreVersion -cne $release.coreVersion -or $metadata.claudeConfigDirOverride -isnot [bool]) { throw 'Unknown legacy install metadata.' }
    foreach ($pair in @(
        @('registrationsRoot', (Join-Path $LocalRoot 'CompanyAgent\installations')),
        @('claudeConfigRoot', $ClaudeConfigRoot), @('knowledgeBaseRoot', (Join-Path $ReleaseRoot 'knowledge')),
        @('managedConfigPath', (Join-Path $ReleaseRoot 'config\managed.json')),
        @('runtimeSelectionPath', (Join-Path $ReleaseRoot 'runtime-selection.json')))) {
        if ((Get-CompanyAgentCleanupFullPath ([string](Get-CompanyAgentCleanupProperty $metadata $pair[0]))) -ine $pair[1]) { throw 'Legacy install path mismatch.' }
    }
    $null = Get-CompanyAgentCleanupFullPath ([string]$metadata.pythonCommand)
    $runtime = Read-CompanyAgentJson (Join-Path $ReleaseRoot 'runtime-selection.json')
    Assert-CompanyAgentCleanupJsonFields $runtime @('schemaVersion', 'coreVersion', 'pythonCommand')
    if ($runtime.schemaVersion -ne 1 -or $runtime.coreVersion -cne $release.coreVersion) { throw 'Unknown legacy runtime selection.' }
    $python = Get-CompanyAgentCleanupFullPath ([string]$runtime.pythonCommand)
    if ([IO.Path]::GetExtension($python) -ine '.exe') { throw 'Unknown legacy runtime command.' }
    $allowed = @('release.json', 'plugin/company-agent-install.json', 'runtime-selection.json')
    $launcher = Join-Path $ReleaseRoot 'read-hook.cmd'
    if (Test-Path -LiteralPath $launcher -PathType Leaf) {
        if (-not (Get-Command Get-CompanyAgentReadHookLauncherBytes -ErrorAction SilentlyContinue)) { throw 'Legacy read-hook verifier is unavailable.' }
        $bytes = Get-CompanyAgentReadHookLauncherBytes -PythonCommand $python -PluginRoot (Join-Path $ReleaseRoot 'plugin')
        if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($launcher)) -cne [Convert]::ToBase64String($bytes)) { throw 'Modified legacy Read launcher.' }
        $allowed += 'read-hook.cmd'
    }
    foreach ($file in $Tree.files) {
        if ($file.path -in $allowed) { continue }
        if (-not $expected.ContainsKey($file.path)) { throw 'Unknown file in legacy release.' }
        $record = $expected[$file.path]
        if ($file.sha256 -ceq $record.sha256 -and $file.length -eq $record.length) { continue }
        if ($file.path -cne 'plugin/hooks/hooks.json' -or -not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw 'Modified legacy payload.' }
        $document = Read-CompanyAgentJson (Join-Path $Evidence.root ([string]$record.path).Replace('/', '\'))
        $args = @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', '${CLAUDE_PLUGIN_ROOT}/scripts/Invoke-CompanyAgent.ps1', '-Mode', 'Hook', '-Event', 'PreToolUse')
        foreach ($group in @($document.hooks.PreToolUse)) {
            if ($group.matcher -cne '^Read$') { continue }
            foreach ($hook in @($group.hooks)) {
                if ($hook.type -ceq 'command' -and $hook.command -ieq 'powershell.exe' -and (@($hook.args) -join '|') -ceq ($args -join '|')) {
                    $hook.command = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'cmd.exe'
                    $hook.args = @('/d', '/v:off', '/s', '/c', 'call', $launcher)
                }
            }
        }
        $installed = Read-CompanyAgentJson (Join-Path $ReleaseRoot 'plugin\hooks\hooks.json')
        if (($document | ConvertTo-Json -Depth 30 -Compress) -cne ($installed | ConvertTo-Json -Depth 30 -Compress)) { throw 'Unknown legacy hook changes.' }
    }
    if ($Tree.files.Count -ne $expected.Count + $allowed.Count) { throw 'Missing legacy payload.' }
    $directories = @{}
    foreach ($path in @($expected.Keys) + $allowed) {
        while ($path.Contains('/')) { $path = $path.Substring(0, $path.LastIndexOf('/')); $directories[$path] = $true }
    }
    if ((@($Tree.directories | Sort-Object) -join '|') -cne (@($directories.Keys | Sort-Object) -join '|')) { throw 'Unknown legacy directories.' }
}

function Get-CompanyAgentCleanupVerifiedRelease {
    param([string] $ReleaseRoot, [string] $LocalRoot, [string] $ClaudeConfigRoot, [hashtable] $Evidence)
    $tree = Get-CompanyAgentCleanupTree $ReleaseRoot
    $release = Read-CompanyAgentJson (Join-Path $ReleaseRoot 'release.json')
    if ([string]$release.coreVersion -cne (Split-Path -Leaf $ReleaseRoot) -or [string]$release.payloadHash -notmatch '^[a-f0-9]{64}$') { throw 'Unknown release identity.' }
    $receiptPath = Join-Path $ReleaseRoot 'cleanup-manifest.json'
    if (Test-Path -LiteralPath $receiptPath -PathType Leaf) {
        $receipt = Read-CompanyAgentJson $receiptPath
        Assert-CompanyAgentCleanupJsonFields $receipt @('schemaVersion', 'kind', 'coreVersion', 'payloadHash', 'files', 'directories')
        if ($receipt.schemaVersion -ne 1 -or $receipt.kind -cne 'company-agent-scoped-immutable-release' -or
            $receipt.coreVersion -cne $release.coreVersion -or $receipt.payloadHash -cne $release.payloadHash) { throw 'Unknown cleanup receipt.' }
        foreach ($record in @($receipt.files)) { Assert-CompanyAgentCleanupJsonFields $record @('path', 'length', 'sha256') }
        $withoutReceipt = [pscustomobject]@{ files = @($tree.files | Where-Object { $_.path -cne 'cleanup-manifest.json' }); directories = $tree.directories }
        if (-not (Test-CompanyAgentCleanupTreeEqual $withoutReceipt $receipt)) { throw 'Modified release; preserved.' }
    }
    elseif ($Evidence.ContainsKey([string]$release.payloadHash)) {
        Test-CompanyAgentCleanupLegacyRelease -ReleaseRoot $ReleaseRoot -LocalRoot $LocalRoot -ClaudeConfigRoot $ClaudeConfigRoot -Tree $tree -Evidence $Evidence[[string]$release.payloadHash]
    }
    else { throw 'No original manifest or installation receipt; preserved.' }
    return $tree
}

function Test-CompanyAgentCleanupCacheEqual {
    param([string] $CacheRoot, [object] $CacheTree, [object] $PluginTree)
    $files = @($CacheTree.files)
    $marker = @($files | Where-Object { $_.path -ceq '.orphaned_at' })
    if ($marker.Count -eq 1) {
        # Claude's observed orphan marker is a 13-byte Unix millisecond value
        # (covered by real upgrade fixtures and a synthetic regression). No
        # other marker, extra data, whitespace or future timestamp is exempted.
        $value = [IO.File]::ReadAllText((Join-Path $CacheRoot '.orphaned_at'))
        if ($marker[0].length -ne 13 -or $value -cnotmatch '^\d{13}$' -or
            [int64]$value -lt 946684800000 -or [int64]$value -gt [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()) { return $false }
        $files = @($files | Where-Object { $_.path -cne '.orphaned_at' })
    }
    return Test-CompanyAgentCleanupTreeEqual ([pscustomobject]@{ files = $files; directories = $CacheTree.directories }) $PluginTree
}

function Remove-CompanyAgentVerifiedTree {
    param([string] $Path, [string] $OwnedRoot, [object] $Tree, [scriptblock] $Guard, [object] $Progress)
    $full = Assert-CompanyAgentCleanupPath $Path $OwnedRoot
    if ((Split-Path -Parent $full) -ine $OwnedRoot) { throw 'Cleanup targets must be direct version children.' }
    if (-not (Test-CompanyAgentCleanupTreeEqual (Get-CompanyAgentCleanupTree $full) $Tree)) { throw 'Files changed before deletion.' }
    & $Guard
    $freed = [int64]0
    foreach ($record in $Tree.files) {
        & $Guard
        $file = Assert-CompanyAgentCleanupPath (Join-Path $full $record.path.Replace('/', '\')) $full
        $item = Get-Item -LiteralPath $file -Force -ErrorAction Stop
        Assert-CompanyAgentCleanupNoStreams $file
        if ($item.PSIsContainer -or [int64]$item.Length -ne $record.length -or (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ine $record.sha256) { throw 'File changed during deletion; remaining files preserved.' }
        # Never recurse: a newly introduced file must survive, even after validation.
        Remove-Item -LiteralPath $file -Force -ErrorAction Stop
        $freed += [int64]$record.length
        $Progress.bytesFreed += [int64]$record.length
    }
    foreach ($relative in @($Tree.directories | Sort-Object { $_.Length } -Descending)) {
        $directory = Assert-CompanyAgentCleanupPath (Join-Path $full $relative.Replace('/', '\')) $full
        Assert-CompanyAgentCleanupNoStreams $directory
        if (@(Get-ChildItem -LiteralPath $directory -Force).Count -eq 0) { [IO.Directory]::Delete($directory, $false) }
    }
    $null = Assert-CompanyAgentCleanupPath $full $OwnedRoot
    Assert-CompanyAgentCleanupNoStreams $full
    if (@(Get-ChildItem -LiteralPath $full -Force).Count -ne 0) { throw 'New files appeared; the remaining directory was preserved.' }
    [IO.Directory]::Delete($full, $false)
    & $Guard
    return $freed
}

function Invoke-CompanyAgentVersionCleanup {
    [CmdletBinding()]
    param(
        [string] $InvokingLocalAppData, [string] $ClaudeConfigRoot, [string] $CurrentCoreVersion,
        [string] $BundleRoot, [ValidateSet('Keep', 'DeleteUnused')][string] $OldVersionAction = 'Keep',
        [string[]] $ProtectedPaths = @()
    )
    $deleted = New-Object 'Collections.Generic.List[object]'
    $retained = New-Object 'Collections.Generic.List[object]'
    $result = [pscustomobject]@{ status = 'kept'; deleted = @(); retained = @(); bytesFreed = [int64]0; message = '이전 버전 파일을 그대로 보존했습니다.' }
    if ($OldVersionAction -eq 'Keep') { return $result }
    $lease = $null
    try {
        $local = Assert-CompanyAgentCleanupPath $InvokingLocalAppData
        $claude = Assert-CompanyAgentCleanupPath $ClaudeConfigRoot
        if ($CurrentCoreVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid current core version.' }
        $marketplace = Join-Path $local 'CompanyAgent-Distribution\marketplace'
        $versionsRoot = Assert-CompanyAgentCleanupPath (Join-Path $marketplace 'versions')
        $cacheRoot = Assert-CompanyAgentCleanupPath (Join-Path $claude 'plugins\cache\company-agent-local\company-agent')
        $lease = Enter-CompanyAgentVersionMaintenance $marketplace
        $blocker = Get-CompanyAgentCleanupProcessBlocker
        if ($blocker) { throw $blocker }
        $referenceArgs = @{ LocalRoot = $local; ClaudeConfigRoot = $claude; CurrentCoreVersion = $CurrentCoreVersion; ProtectedPaths = @($ProtectedPaths) + @($BundleRoot, (Join-Path $local 'CompanyAgent-Backups'), (Join-Path $local 'CompanyAgent\states'), (Join-Path $local 'CompanyAgent\setup-cache')) }
        $references = Get-CompanyAgentCleanupReferences @referenceArgs
        $evidence = Get-CompanyAgentCleanupBundleEvidence -LocalRoot $local -BundleRoot $BundleRoot
        $guard = {
            $blocker = Get-CompanyAgentCleanupProcessBlocker
            if ($blocker) { throw $blocker }
            $latest = Get-CompanyAgentCleanupReferences @referenceArgs
            if ($latest.hash -cne $references.hash) { throw 'Registration changed during cleanup; remaining versions preserved.' }
        }
        $result.status = 'completed'
        foreach ($directory in @(Get-ChildItem -LiteralPath $versionsRoot -Directory -Force | Sort-Object Name)) {
            $version = $directory.Name
            $path = $directory.FullName
            $kind = 'release'
            try {
                $null = Assert-CompanyAgentCleanupPath $path $versionsRoot
                if ($version -notmatch '^\d+\.\d+\.\d+$' -or [version]$version -ge [version]$CurrentCoreVersion) { throw 'Current, future, or unknown version; preserved.' }
                if (Test-CompanyAgentCleanupProtected $path $version $references) { throw 'Referenced by a scope, launcher, rollback, or protected path; preserved.' }
                $tree = Get-CompanyAgentCleanupVerifiedRelease -ReleaseRoot $path -LocalRoot $local -ClaudeConfigRoot $claude -Evidence $evidence
                # Native cache must match the proven installed plugin, with only
                # Claude's narrowly validated orphan timestamp allowed as extra.
                $cache = Join-Path $cacheRoot $version
                if (Test-Path -LiteralPath $cache -PathType Container) {
                    try {
                        if (Test-CompanyAgentCleanupProtected $cache $version $references) { throw 'Referenced native cache; preserved.' }
                        $cacheTree = Get-CompanyAgentCleanupTree $cache
                        $pluginTree = Get-CompanyAgentCleanupTree (Join-Path $path 'plugin')
                        if (-not (Test-CompanyAgentCleanupCacheEqual $cache $cacheTree $pluginTree)) { throw 'Unknown or modified native cache files; preserved.' }
                        $bytes = Remove-CompanyAgentVerifiedTree -Path $cache -OwnedRoot $cacheRoot -Tree $cacheTree -Guard $guard -Progress $result
                        $deleted.Add([pscustomobject]@{ path = $cache; kind = 'native-cache'; bytes = $bytes })
                    }
                    catch {
                        $retained.Add([pscustomobject]@{ path = $cache; kind = 'native-cache'; reason = $_.Exception.Message })
                        throw 'Native cache was retained; its release dependencies were also preserved.'
                    }
                }
                $bytes = Remove-CompanyAgentVerifiedTree -Path $path -OwnedRoot $versionsRoot -Tree $tree -Guard $guard -Progress $result
                $deleted.Add([pscustomobject]@{ path = $path; kind = $kind; bytes = $bytes })
            }
            catch { $retained.Add([pscustomobject]@{ path = $path; kind = $kind; reason = $_.Exception.Message }) }
        }
        & $guard
        $result.message = '사용하지 않고 원본과 일치하는 이전 하네스 파일만 백업 없이 삭제했습니다. 개인 자료와 확인할 수 없는 파일은 보존했습니다.'
        if (@($retained | Where-Object { (Split-Path -Leaf $_.path) -match '^\d+\.\d+\.\d+$' -and [version](Split-Path -Leaf $_.path) -lt [version]$CurrentCoreVersion }).Count) { $result.status = 'partial' }
    }
    catch { $result.status = $(if ($result.bytesFreed -gt 0) { 'partial' } else { 'deferred' }); $result.message = '이전 버전 정리를 보류했습니다. 기존 자료는 보존됩니다. ' + $_.Exception.Message }
    finally { Exit-CompanyAgentVersionMaintenance $lease }
    $result.deleted = $deleted.ToArray()
    $result.retained = $retained.ToArray()
    return $result
}
