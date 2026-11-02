[CmdletBinding()]
param([switch] $KeepArtifacts)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1') -FunctionsOnly
. (Join-Path $PSScriptRoot 'HarnessReplacement.ps1')
. (Join-Path $PSScriptRoot 'CompanyAgent.ReadHook.ps1')
. (Join-Path $PSScriptRoot 'CompanyAgent.Cleanup.ps1')
if (-not ('CompanyAgentCleanupFixtureStreams' -as [type])) {
    Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public static class CompanyAgentCleanupFixtureStreams {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool DeleteFileW(string path);
}
'@
}

# All inputs and every deletion target are synthetic workspace files. The
# production API has no flag that bypasses process or reference safeguards.
$testRoot = Join-Path (Split-Path -Parent $PSScriptRoot) ('.smoke\vclean-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
$null = New-Item -ItemType Directory -Path $testRoot
$previousProgramData = $env:ProgramData
$env:ProgramData = Join-Path $testRoot 'machine-data'
$script:cleanupBlocker = $null
$script:cleanupProbe = $null
$script:cleanupProbeCount = 0
function Get-CompanyAgentCleanupProcessBlocker {
    $script:cleanupProbeCount++
    if ($null -ne $script:cleanupProbe) { & $script:cleanupProbe }
    return $script:cleanupBlocker
}

function Assert-Cleanup {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw ('Cleanup regression failed: ' + $Message) }
}

function New-CleanupFixture {
    param([string] $Name)
    $root = Join-Path $testRoot $Name
    $env:ProgramData = Join-Path $root 'machine-data'
    $local = Join-Path $root 'local'
    $claude = Join-Path $root 'claude'
    $marketplace = Join-Path $local 'CompanyAgent-Distribution\marketplace'
    $registrations = Join-Path $local 'CompanyAgent\installations'
    $null = New-Item -ItemType Directory -Path (Join-Path $marketplace 'versions') -Force
    $fixture = [pscustomobject]@{ root = $root; local = $local; claude = $claude; marketplace = $marketplace; registrations = $registrations; current = '1.5.1' }
    Write-CompanyAgentJsonAtomic (Join-Path $marketplace '.claude-plugin\marketplace.json') ([pscustomobject]@{
        name = 'company-agent-local'; plugins = @([pscustomobject]@{ name = 'company-agent'; source = './versions/1.5.1/plugin' })
    })
    Write-CompanyAgentJsonAtomic (Join-Path $claude 'settings.json') ([pscustomobject]@{ model = 'existing-model'; mcpServers = [pscustomobject]@{ existing = 'keep' } })
    Write-CompanyAgentJsonAtomic (Join-Path $claude 'plugins\known_marketplaces.json') ([pscustomobject]@{ 'company-agent-local' = [pscustomobject]@{ source = [pscustomobject]@{ source = 'directory'; path = $marketplace }; installLocation = $marketplace } })
    Write-CompanyAgentJsonAtomic (Join-Path $claude 'plugins\installed_plugins.json') ([pscustomobject]@{ version = 2; plugins = [pscustomobject]@{
        'company-agent@company-agent-local' = @([pscustomobject]@{ scope = 'user'; version = '1.5.1'; installPath = (Join-Path $marketplace 'versions\1.5.1\plugin') })
        'other@external' = @([pscustomobject]@{ scope = 'user'; version = '99'; installPath = (Join-Path $claude 'plugins\cache\other\99') })
    } })
    $release = Join-Path $marketplace 'versions\1.5.1'
    Write-CompanyAgentJsonAtomic (Join-Path $registrations 'user\company-agent-install.json') ([pscustomobject]@{
        schemaVersion = 1; scope = 'User'; nativeClaudeScope = 'user'; projectRoot = $null
        coreVersion = '1.5.1'; knowledgeVersion = '2026.09.03'; pluginId = 'company-agent@company-agent-local'
        userStateRoot = (Join-Path $local 'CompanyAgent\states\user'); claudeConfigRoot = $claude
        pythonCommand = 'C:\SyntheticPython\python.exe'; knowledgeBaseRoot = (Join-Path $release 'knowledge'); managedConfigPath = (Join-Path $release 'config\managed.json')
    })
    foreach ($relative in @('CompanyAgent\states\user\memory\remember.md', 'CompanyAgent\states\user\knowledge\personal.md',
        'CompanyAgent\states\user\learning\patterns.json', 'CompanyAgent\states\user\skills\my-skill\SKILL.md',
        'CompanyAgent-Backups\prior\backup.txt')) { Write-CompanyAgentUtf8File (Join-Path $local $relative) 'preserve-personal-bytes' }
    Write-CompanyAgentUtf8File (Join-Path $claude 'plugins\cache\other\99\personal.txt') 'other-plugin-preserved'
    $script:cleanupBlocker = $null; $script:cleanupProbe = $null; $script:cleanupProbeCount = 0
    return $fixture
}

function New-CleanupRelease {
    param([object] $Fixture, [string] $Version, [switch] $Sealed, [switch] $LegacyEvidence, [switch] $ReadHook, [switch] $NativeCache)
    $bundle = Join-Path $Fixture.local ('CompanyAgent\setup-cache\' + $Version + '-0123456789abcdef-01234567\bundle')
    $source = Join-Path $bundle 'payload\core\plugin'
    Write-CompanyAgentJsonAtomic (Join-Path $source '.claude-plugin\plugin.json') ([pscustomobject]@{ name = 'company-agent'; version = $Version })
    Write-CompanyAgentUtf8File (Join-Path $source 'skills\company-agent\SKILL.md') 'synthetic immutable core'
    Write-CompanyAgentUtf8File (Join-Path $bundle 'payload\knowledge\base.md') 'synthetic shared knowledge'
    Write-CompanyAgentJsonAtomic (Join-Path $bundle 'payload\config\managed.json') ([pscustomobject]@{ schemaVersion = 1 })
    if ($ReadHook) {
        Write-CompanyAgentUtf8File (Join-Path $source 'scripts\read_hook.py') '# synthetic read hook'
        Write-CompanyAgentJsonAtomic (Join-Path $source 'hooks\hooks.json') ([pscustomobject]@{ hooks = [pscustomobject]@{ PreToolUse = @([pscustomobject]@{
            matcher = '^Read$'; hooks = @([pscustomobject]@{ type = 'command'; command = 'powershell.exe'; args = @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', '${CLAUDE_PLUGIN_ROOT}/scripts/Invoke-CompanyAgent.ps1', '-Mode', 'Hook', '-Event', 'PreToolUse') })
        }) } })
    }
    $records = (Get-CompanyAgentCleanupTree $bundle).files
    $payloadHash = Get-CompanyAgentCleanupHash ((@($records | Sort-Object path | ForEach-Object { "$($_.path)|$($_.sha256)|$($_.length)" })) -join "`n")
    if ($LegacyEvidence) { Write-CompanyAgentJsonAtomic (Join-Path $bundle 'bundle-manifest.json') ([pscustomobject]@{ format = 'company-agent-offline-bundle/v1'; coreVersion = $Version; knowledgeVersion = '2026.09.03'; files = $records }) }
    $release = Join-Path $Fixture.marketplace ('versions\' + $Version)
    Copy-CompanyAgentDirectoryContents $source (Join-Path $release 'plugin')
    Copy-CompanyAgentDirectoryContents (Join-Path $bundle 'payload\knowledge') (Join-Path $release 'knowledge')
    Copy-CompanyAgentDirectoryContents (Join-Path $bundle 'payload\config') (Join-Path $release 'config')
    Write-CompanyAgentJsonAtomic (Join-Path $release 'release.json') ([pscustomobject]@{ coreVersion = $Version; knowledgeVersion = '2026.09.03'; payloadHash = $payloadHash })
    Write-CompanyAgentJsonAtomic (Join-Path $release 'plugin\company-agent-install.json') ([pscustomobject]@{
        schemaVersion = 1; coreVersion = $Version; registrationsRoot = $Fixture.registrations; claudeConfigRoot = $Fixture.claude; claudeConfigDirOverride = $true
        knowledgeBaseRoot = (Join-Path $release 'knowledge'); managedConfigPath = (Join-Path $release 'config\managed.json')
        pythonCommand = 'C:\SyntheticPython\python.exe'; runtimeSelectionPath = (Join-Path $release 'runtime-selection.json')
    })
    Write-CompanyAgentJsonAtomic (Join-Path $release 'runtime-selection.json') ([pscustomobject]@{ schemaVersion = 1; coreVersion = $Version; pythonCommand = 'C:\SyntheticPython\python.exe' })
    if ($ReadHook) {
        $launcher = Join-Path $release 'read-hook.cmd'
        $null = Set-CompanyAgentReadHookRegistration -PluginRoot (Join-Path $release 'plugin') -LauncherPath $launcher
        [IO.File]::WriteAllBytes($launcher, (Get-CompanyAgentReadHookLauncherBytes -PythonCommand 'C:\SyntheticPython\python.exe' -PluginRoot (Join-Path $release 'plugin')))
    }
    if ($NativeCache) { Copy-CompanyAgentDirectoryContents (Join-Path $release 'plugin') (Join-Path $Fixture.claude ('plugins\cache\company-agent-local\company-agent\' + $Version)) }
    if ($Sealed) { $null = New-CompanyAgentCleanupReceipt -ReleaseRoot $release -MarketplaceRoot $Fixture.marketplace -NewlyCreated }
    return $release
}

function Invoke-CleanupFixture {
    param([object] $Fixture)
    return Invoke-CompanyAgentVersionCleanup -InvokingLocalAppData $Fixture.local -ClaudeConfigRoot $Fixture.claude -CurrentCoreVersion $Fixture.current -OldVersionAction DeleteUnused
}

$count = 0
try {
    $keep = Invoke-CompanyAgentVersionCleanup -InvokingLocalAppData 'invalid-relative' -ClaudeConfigRoot 'invalid' -CurrentCoreVersion 'invalid'
    Assert-Cleanup ($keep.status -ceq 'kept' -and $script:cleanupProbeCount -eq 0 -and $keep.bytesFreed -eq 0) 'Default Keep performed discovery or mutation.'
    $count++

    $f = New-CleanupFixture 'sealed-delete'
    $old = New-CleanupRelease $f '1.4.37' -Sealed -NativeCache
    $current = New-CleanupRelease $f '1.5.1' -Sealed
    $future = New-CleanupRelease $f '9.0.0' -Sealed
    $beforeState = Get-CompanyAgentCleanupTree (Join-Path $f.local 'CompanyAgent\states')
    $beforeSettings = (Get-FileHash -LiteralPath (Join-Path $f.claude 'settings.json')).Hash
    $beforeBackup = Get-CompanyAgentCleanupTree (Join-Path $f.local 'CompanyAgent-Backups')
    $report = Invoke-CleanupFixture $f
    Assert-Cleanup (-not (Test-Path -LiteralPath $old) -and (Test-Path -LiteralPath $current) -and (Test-Path -LiteralPath $future)) ('Version selection failed: ' + ($report | ConvertTo-Json -Depth 5))
    Assert-Cleanup ($report.deleted.Count -eq 2 -and $report.bytesFreed -gt 0 -and $report.status -ceq 'completed') 'Release/cache accounting failed.'
    Assert-Cleanup (Test-CompanyAgentCleanupTreeEqual $beforeState (Get-CompanyAgentCleanupTree (Join-Path $f.local 'CompanyAgent\states'))) 'Personal memory/knowledge/learning/skills changed.'
    Assert-Cleanup (Test-CompanyAgentCleanupTreeEqual $beforeBackup (Get-CompanyAgentCleanupTree (Join-Path $f.local 'CompanyAgent-Backups'))) 'Backups changed or new backups appeared.'
    Assert-Cleanup ($beforeSettings -ceq (Get-FileHash -LiteralPath (Join-Path $f.claude 'settings.json')).Hash) 'Model/MCP settings changed.'
    Assert-Cleanup (Test-Path -LiteralPath (Join-Path $f.claude 'plugins\cache\other\99\personal.txt')) 'Other plugin changed.'
    $count++

    foreach ($validMarker in @($true, $false)) {
        $f = New-CleanupFixture ('orphan-' + $validMarker)
        $old = New-CleanupRelease $f '1.4.37' -Sealed -NativeCache
        $marker = Join-Path $f.claude 'plugins\cache\company-agent-local\company-agent\1.4.37\.orphaned_at'
        $value = $(if ($validMarker) { '1700000000000' } else { 'personal note: preserve' })
        Write-CompanyAgentUtf8File $marker $value
        $report = Invoke-CleanupFixture $f
        Assert-Cleanup ((Test-Path -LiteralPath $old) -ne $validMarker) ('Orphan marker validation failed: ' + $validMarker)
        Assert-Cleanup (($report.bytesFreed -gt 0) -eq $validMarker) 'Orphan marker deletion accounting failed.'
        $count++
    }

    foreach ($hook in @($false, $true)) {
        $f = New-CleanupFixture ('legacy-' + $hook)
        $old = New-CleanupRelease $f '1.4.37' -LegacyEvidence -ReadHook:$hook -NativeCache
        $report = Invoke-CleanupFixture $f
        Assert-Cleanup (-not (Test-Path -LiteralPath $old) -and $report.deleted.Count -eq 2) ('Legacy original bundle proof failed: ' + ($report | ConvertTo-Json -Depth 5))
        Assert-Cleanup (Test-Path -LiteralPath (Join-Path $f.local 'CompanyAgent\setup-cache\1.4.37-0123456789abcdef-01234567\bundle\bundle-manifest.json')) 'Source setup cache was removed.'
        $count++
    }

    foreach ($variant in @('unknown', 'modified', 'extra', 'empty-directory', 'missing', 'cache-modified', 'receipt-extra', 'legacy-modified', 'legacy-source-modified', 'legacy-runtime', 'legacy-hook')) {
        $f = New-CleanupFixture $variant
        $legacy = $variant.StartsWith('legacy-')
        $old = New-CleanupRelease $f '1.4.37' -Sealed:($variant -ne 'unknown' -and -not $legacy) -LegacyEvidence:$legacy -ReadHook:($variant -eq 'legacy-hook') -NativeCache:($variant -eq 'cache-modified')
        switch ($variant) {
            'modified' { Write-CompanyAgentUtf8File (Join-Path $old 'plugin\skills\company-agent\SKILL.md') 'user modified core' }
            'extra' { Write-CompanyAgentUtf8File (Join-Path $old 'personal-memory.md') 'do not delete' }
            'empty-directory' { $null = New-Item -ItemType Directory -Path (Join-Path $old 'personal-empty-folder') }
            'missing' { Remove-Item -LiteralPath (Join-Path $old 'config\managed.json') }
            'cache-modified' { Write-CompanyAgentUtf8File (Join-Path $f.claude 'plugins\cache\company-agent-local\company-agent\1.4.37\personal.md') 'keep cache and referenced launcher' }
            'receipt-extra' {
                $receipt = Read-CompanyAgentJson (Join-Path $old 'cleanup-manifest.json')
                $receipt | Add-Member -NotePropertyName personalNote -NotePropertyValue 'preserve unrecognized receipt edits'
                Write-CompanyAgentJsonAtomic (Join-Path $old 'cleanup-manifest.json') $receipt
            }
            'legacy-modified' { Write-CompanyAgentUtf8File (Join-Path $old 'knowledge\base.md') 'personal knowledge' }
            'legacy-source-modified' { Write-CompanyAgentUtf8File (Join-Path $f.local 'CompanyAgent\setup-cache\1.4.37-0123456789abcdef-01234567\bundle\payload\knowledge\base.md') 'changed source evidence' }
            'legacy-runtime' { Write-CompanyAgentJsonAtomic (Join-Path $old 'runtime-selection.json') ([pscustomobject]@{ schemaVersion = 1; coreVersion = '1.4.37'; pythonCommand = 'C:\SyntheticPython\python.exe'; personal = 'data' }) }
            'legacy-hook' { Write-CompanyAgentUtf8File (Join-Path $old 'read-hook.cmd') '@echo user customized' }
        }
        $before = Get-CompanyAgentCleanupTree $old
        $report = Invoke-CleanupFixture $f
        Assert-Cleanup ((Test-Path -LiteralPath $old) -and $report.bytesFreed -eq 0 -and (Test-CompanyAgentCleanupTreeEqual $before (Get-CompanyAgentCleanupTree $old))) ($variant + ' was deleted or mutated.')
        $count++
    }

    foreach ($reference in @('project', 'native-local', 'settings-hook', 'rollback', 'protected-path', 'runtime-dependency', 'runtime-pointer', 'other-plugin-hook')) {
        $f = New-CleanupFixture ('reference-' + $reference)
        $old = New-CleanupRelease $f '1.4.37' -Sealed
        $parameters = @{ InvokingLocalAppData = $f.local; ClaudeConfigRoot = $f.claude; CurrentCoreVersion = $f.current; OldVersionAction = 'DeleteUnused' }
        switch ($reference) {
            'project' {
                $record = Read-CompanyAgentJson (Join-Path $f.registrations 'user\company-agent-install.json')
                $record.scope = 'Project'; $record.projectRoot = Join-Path $f.root 'project'; $record.coreVersion = '1.4.37'
                Write-CompanyAgentJsonAtomic (Join-Path $f.registrations 'projects\0123456789abcdef\company-agent-install.json') $record
            }
            'native-local' {
                $path = Join-Path $f.claude 'plugins\installed_plugins.json'
                $document = Read-CompanyAgentJson $path
                $document.plugins.'company-agent@company-agent-local' += [pscustomobject]@{ scope = 'local'; version = '1.4.37'; installPath = (Join-Path $old 'plugin'); projectPath = (Join-Path $f.root 'unregistered-project') }
                Write-CompanyAgentJsonAtomic $path $document
            }
            'settings-hook' { Write-CompanyAgentJsonAtomic (Join-Path $f.claude 'settings.json') ([pscustomobject]@{ hooks = [pscustomobject]@{ command = ('call "' + (Join-Path $old 'read-hook.cmd') + '"') } }) }
            'rollback' { Write-CompanyAgentJsonAtomic (Join-Path $env:ProgramData 'CompanyAgent\state\previous.json') ([pscustomobject]@{ coreVersion = '1.4.37'; pluginPath = (Join-Path $old 'plugin') }) }
            'protected-path' { $parameters.ProtectedPaths = @((Join-Path $old 'personal-state')) }
            'runtime-dependency' {
                $path = Join-Path $f.registrations 'user\company-agent-install.json'
                $record = Read-CompanyAgentJson $path
                $record.pythonCommand = Join-Path $old 'plugin\runtime\python\python.exe'
                Write-CompanyAgentJsonAtomic $path $record
            }
            'runtime-pointer' {
                $current = New-CleanupRelease $f '1.5.1' -Sealed
                Write-CompanyAgentJsonAtomic (Join-Path $current 'runtime-selection.json') ([pscustomobject]@{ schemaVersion = 1; coreVersion = '1.5.1'; pythonCommand = (Join-Path $old 'plugin\runtime\python\python.exe') })
            }
            'other-plugin-hook' {
                Write-CompanyAgentJsonAtomic (Join-Path $f.claude 'plugins\cache\other\99\hooks\hooks.json') ([pscustomobject]@{ hooks = [pscustomobject]@{ command = (Join-Path $old 'plugin\runtime\python\python.exe') } })
            }
        }
        $report = Invoke-CompanyAgentVersionCleanup @parameters
        Assert-Cleanup ((Test-Path -LiteralPath $old) -and $report.bytesFreed -eq 0) ($reference + ' reference was ignored.')
        $count++
    }

    foreach ($invalid in @('corrupt-registration', 'unknown-scope', 'unknown-registration-file', 'corrupt-inventory', 'process', 'registration-race')) {
        $f = New-CleanupFixture $invalid
        $old = New-CleanupRelease $f '1.4.37' -Sealed
        switch ($invalid) {
            'corrupt-registration' { Write-CompanyAgentUtf8File (Join-Path $f.registrations 'user\company-agent-install.json') '{bad json' }
            'unknown-scope' { $record = Read-CompanyAgentJson (Join-Path $f.registrations 'user\company-agent-install.json'); $record.scope = 'Machine'; Write-CompanyAgentJsonAtomic (Join-Path $f.registrations 'user\company-agent-install.json') $record }
            'unknown-registration-file' { Write-CompanyAgentUtf8File (Join-Path $f.registrations 'unrecognized\scope.txt') 'unknown reference' }
            'corrupt-inventory' { Write-CompanyAgentUtf8File (Join-Path $f.claude 'plugins\installed_plugins.json') 'broken' }
            'process' { $script:cleanupBlocker = 'Synthetic active Claude session' }
            'registration-race' {
                $racePath = Join-Path $f.registrations 'user\company-agent-install.json'
                $script:cleanupProbe = {
                    if ($script:cleanupProbeCount -eq 2) {
                        $record = Read-CompanyAgentJson $racePath; $record.coreVersion = '1.4.37'; Write-CompanyAgentJsonAtomic $racePath $record
                    }
                }
            }
        }
        $before = Get-CompanyAgentCleanupTree $old
        $report = Invoke-CleanupFixture $f
        Assert-Cleanup ((Test-Path -LiteralPath $old) -and $report.bytesFreed -eq 0 -and (Test-CompanyAgentCleanupTreeEqual $before (Get-CompanyAgentCleanupTree $old))) ($invalid + ' failed closed.')
        $count++
    }

    $f = New-CleanupFixture 'junction'
    $old = New-CleanupRelease $f '1.4.37' -Sealed
    $external = Join-Path $f.root 'external-personal'
    Write-CompanyAgentUtf8File (Join-Path $external 'remember.md') 'personal sentinel'
    $link = Join-Path $old 'plugin\linked-data'
    $null = New-Item -ItemType Junction -Path $link -Target $external
    $report = Invoke-CleanupFixture $f
    Assert-Cleanup ((Test-Path -LiteralPath $old) -and (Test-Path -LiteralPath (Join-Path $external 'remember.md')) -and $report.bytesFreed -eq 0) 'A path link was followed or deleted.'
    # Remove only the fixture junction itself, never its destination.
    [IO.Directory]::Delete($link, $false)
    $count++

    foreach ($streamKind in @('file', 'directory', 'root')) {
        $f = New-CleanupFixture ('ads-' + $streamKind)
        $old = New-CleanupRelease $f '1.4.37' -Sealed
        $streamPath = switch ($streamKind) {
            'file' { Join-Path $old 'plugin\skills\company-agent\SKILL.md' }
            'directory' { Join-Path $old 'plugin' }
            'root' { $old }
        }
        Set-Content -LiteralPath $streamPath -Stream personal-note -Value 'personal alternate stream' -Encoding UTF8 -NoNewline
        $report = Invoke-CleanupFixture $f
        Assert-Cleanup ((Test-Path -LiteralPath $old) -and $report.bytesFreed -eq 0 -and (Get-Content -LiteralPath $streamPath -Stream personal-note -Raw -Encoding UTF8) -ceq 'personal alternate stream') ($streamKind + ' ADS was deleted.')
        Assert-Cleanup (($report.retained | ConvertTo-Json -Depth 8) -match 'streams') ($streamKind + ' ADS was not identified by the verifier.')
        # Remove the synthetic stream only so fixture teardown can prove purity.
        Assert-Cleanup ([CompanyAgentCleanupFixtureStreams]::DeleteFileW($streamPath + ':personal-note')) 'Synthetic stream teardown failed.'
        $count++
    }

    [pscustomobject]@{ status = 'passed'; tests = $count; root = $testRoot; realUserDataChanged = $false } | ConvertTo-Json
}
finally {
    $env:ProgramData = $previousProgramData
    if (-not $KeepArtifacts) {
        $resolved = [IO.Path]::GetFullPath($testRoot)
        $owned = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $PSScriptRoot) '.smoke')).TrimEnd('\') + '\'
        if (-not $resolved.StartsWith($owned, [StringComparison]::OrdinalIgnoreCase)) { throw 'Test cleanup escaped its workspace fixture.' }
        # A failed link test must retain its fixture for inspection.
        $null = Get-CompanyAgentCleanupTree $resolved
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
