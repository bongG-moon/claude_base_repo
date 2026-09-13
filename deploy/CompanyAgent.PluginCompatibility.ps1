# Dot-source after Setup-CompanyAgent.ps1 -FunctionsOnly.
# Only the known Ouroboros Python entrypoints are supported. Never execute a
# discovered plugin script during installation or change arbitrary commands.
function Repair-CompanyAgentPluginPython {
    param(
        [Parameter(Mandatory = $true)] [string] $ClaudeConfigRoot,
        [Parameter(Mandatory = $true)] [string] $PythonCommand,
        [Parameter(Mandatory = $true)] [string] $BackupBase,
        [ValidateSet('User', 'Project')] [string] $Scope = 'User',
        [string] $ProjectRoot
    )

    $configRoot = Get-SetupFullPath -Path $ClaudeConfigRoot
    $inventoryPath = Join-Path $configRoot 'plugins\installed_plugins.json'
    Assert-SetupPathHasNoReparsePoint -Path $inventoryPath -Name 'Plugin inventory'
    if (-not (Test-Path -LiteralPath $inventoryPath -PathType Leaf)) { return @() }
    $inventory = Read-CompanyAgentJson -Path $inventoryPath
    $plugins = Get-SetupPropertyValue -Object $inventory -Name 'plugins'
    $entries = @(Get-SetupPropertyValue -Object $plugins -Name 'ouroboros@ouroboros')
    if ($entries.Count -eq 0 -or $null -eq $entries[0]) { return @() }

    # Probe sys.executable on THIS PC; never trust a path copied from a package.
    $python = Resolve-SetupApprovedPython -PreferredCommand $PythonCommand -OnlyPreferred
    if ([string]::IsNullOrWhiteSpace($python)) { throw 'Plugin compatibility: selected Python cannot run. Reapply setup and select the installed python.exe.' }
    # Single-quote for Git Bash, including spaces, Unicode and shell metacharacters.
    $shellPython = "'" + $python.Replace('\', '/').Replace("'", "'" + '"' + "'" + '"' + "'") + "'"
    $cacheRoot = (Get-SetupFullPath -Path (Join-Path $configRoot 'plugins\cache\ouroboros\ouroboros')).TrimEnd('\') + '\'
    $settingsPath = Join-Path $configRoot 'settings.json'
    if ($Scope -eq 'Project') {
        if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { throw 'ProjectRoot is required for project plugin repair.' }
        $ProjectRoot = Get-SetupFullPath -Path $ProjectRoot
        $settingsPath = Join-Path $ProjectRoot '.claude\settings.json'
    }
    Assert-SetupPathHasNoReparsePoint -Path $settingsPath -Name 'Plugin settings'
    if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) { return @() }
    $settings = Read-CompanyAgentJson -Path $settingsPath
    $enabled = Get-SetupPropertyValue -Object (Get-SetupPropertyValue -Object $settings -Name 'enabledPlugins') -Name 'ouroboros@ouroboros'
    if ($enabled -ne $true) { return @() }

    foreach ($entry in $entries) {
        if ([string](Get-SetupPropertyValue -Object $entry -Name 'scope') -ine $Scope) { continue }
        if ($Scope -eq 'Project' -and [string](Get-SetupPropertyValue -Object $entry -Name 'projectPath') -ine $ProjectRoot) { continue }
        $installPath = Get-SetupFullPath -Path ([string](Get-SetupPropertyValue -Object $entry -Name 'installPath'))
        if (-not $installPath.StartsWith($cacheRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Plugin compatibility: Ouroboros is outside the selected profile cache; no files were changed there.'
        }
        # Project-only installation must not modify a cache shared with another scope.
        if ($Scope -eq 'Project' -and @($entries | Where-Object {
            [string]$_.installPath -ieq $installPath -and
            ([string]$_.scope -ine 'project' -or [string](Get-SetupPropertyValue -Object $_ -Name 'projectPath') -ine $ProjectRoot)
        }).Count -gt 0) {
            Write-Warning 'Ouroboros shares its cache with another scope. Reapply User setup to repair its Python connection; project setup left it unchanged.'
            continue
        }
        $hooksPath = Join-Path $installPath 'hooks\hooks.json'
        Assert-SetupPathHasNoReparsePoint -Path $hooksPath -Name 'Ouroboros hooks'
        if (-not (Test-Path -LiteralPath $hooksPath -PathType Leaf)) { continue }
        $document = Read-CompanyAgentJson -Path $hooksPath
        $events = Get-SetupPropertyValue -Object $document -Name 'hooks'
        $changed = 0
        $known = @{ SessionStart = 'session-start.py'; UserPromptSubmit = 'keyword-detector.py'; PostToolUse = 'drift-monitor.py' }
        foreach ($event in $known.Keys) {
            $suffix = '"${CLAUDE_PLUGIN_ROOT}/scripts/' + $known[$event] + '"'
            foreach ($group in @(Get-SetupPropertyValue -Object $events -Name $event)) {
                foreach ($hook in @(Get-SetupPropertyValue -Object $group -Name 'hooks')) {
                    if ($null -eq $hook -or [string](Get-SetupPropertyValue -Object $hook -Name 'type') -ne 'command') { continue }
                    $command = [string](Get-SetupPropertyValue -Object $hook -Name 'command')
                    $replacement = $shellPython + ' -X utf8 -B ' + $suffix
                    # Accept stock commands or our exact generated command shape only.
                    $ours = "^'(?:[^']|'" + '"' + "'" + '"' + "')+' -X utf8 -B " + [regex]::Escape($suffix) + '$'
                    if ($command -ne ('python3 ' + $suffix) -and $command -notmatch $ours) { continue }
                    if ($command -ceq $replacement) { continue }
                    $scriptPath = Join-Path $installPath ('scripts\' + $known[$event])
                    Assert-SetupPathHasNoReparsePoint -Path $scriptPath -Name 'Ouroboros script'
                    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) { throw 'Plugin compatibility: expected Ouroboros script is missing.' }
                    $hook.command = $replacement
                    $changed++
                }
            }
        }
        if ($changed -eq 0) { continue }
        $backup = Join-Path (Get-SetupFullPath -Path $BackupBase) ('plugin-python-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N'))
        Assert-SetupPathHasNoReparsePoint -Path $backup -Name 'Plugin backup'
        $null = New-Item -ItemType Directory -Path $backup
        Copy-Item -LiteralPath $hooksPath -Destination (Join-Path $backup 'hooks.json')
        Write-CompanyAgentJsonAtomic -Path (Join-Path $backup 'restore-info.json') -Value @{
            originalPath = $hooksPath; pythonCommand = $python; plugin = 'ouroboros@ouroboros'
            originalSha256 = (Get-FileHash -LiteralPath $hooksPath -Algorithm SHA256).Hash
        }
        Write-CompanyAgentJsonAtomic -Path $hooksPath -Value $document
        [pscustomobject]@{ plugin = 'ouroboros@ouroboros'; changed = $changed; python = $python; backup = $backup }
    }
}
