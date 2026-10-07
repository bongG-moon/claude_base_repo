# Dot-source after Setup-CompanyAgent.ps1 -FunctionsOnly and HarnessReplacement.ps1.
# The launcher is mutable installation state outside the immutable plugin copy.
function ConvertTo-CompanyAgentBatchPath {
    param([string] $Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or $Path -match '["\r\n\x00]' -or -not [IO.Path]::IsPathRooted($Path)) {
        throw 'Read hook requires an absolute path without command delimiters.'
    }
    return '"' + $Path.Replace('%', '%%') + '"'
}

function Get-CompanyAgentReadHookLauncherBytes {
    param([string] $PythonCommand, [string] $PluginRoot)
    if ([IO.Path]::GetExtension($PythonCommand) -ine '.exe') { throw 'Read hook requires the approved Python executable.' }
    $python = ConvertTo-CompanyAgentBatchPath -Path $PythonCommand
    $entry = ConvertTo-CompanyAgentBatchPath -Path (Join-Path $PluginRoot 'scripts\read_hook.py')
    $fallback = ConvertTo-CompanyAgentBatchPath -Path (Join-Path $PluginRoot 'scripts\Invoke-CompanyAgent.ps1')
    $system = [Environment]::GetFolderPath([Environment+SpecialFolder]::System)
    $chcp = ConvertTo-CompanyAgentBatchPath -Path (Join-Path $system 'chcp.com')
    $powershell = ConvertTo-CompanyAgentBatchPath -Path (Join-Path $system 'WindowsPowerShell\v1.0\powershell.exe')
    # ASCII lines switch cmd to UTF-8 before it reads any Unicode path. Do not
    # CALL the interpreter: CALL would expand literal percent signs a second time.
    $lines = @(
        '@echo off',
        'setlocal DisableDelayedExpansion',
        'set "ERRORLEVEL="',
        ($chcp + ' 65001 >nul'),
        ('if not exist ' + $python + ' goto fallback'),
        ('if not exist ' + $entry + ' goto fallback'),
        ($python + ' -X utf8 -B ' + $entry),
        'exit /b %errorlevel%',
        ':fallback',
        ($powershell + ' -NoLogo -NoProfile -ExecutionPolicy Bypass -File ' + $fallback + ' -Mode Hook -Event PreToolUse'),
        'exit /b %errorlevel%'
    )
    return ,(ConvertTo-SetupHarnessUtf8Bytes -Text (($lines -join "`r`n") + "`r`n"))
}

function Set-CompanyAgentReadHookRegistration {
    param([string] $PluginRoot, [string] $LauncherPath)
    # Exec-form arguments use standard Windows argv quoting. CALL accepts that
    # quoting for spaces/Unicode/&/!, with delayed expansion disabled. Percent
    # expansion, carets and unquoted metacharacters need the original PS hook.
    if ($LauncherPath -match '[%\^"\r\n\x00]' -or
        ($LauncherPath -notmatch '[ \t]' -and $LauncherPath -match '[&|<>()]')) { return $false }
    if (-not [IO.Path]::IsPathRooted($LauncherPath)) { throw 'Read hook launcher must have an absolute path.' }
    $entry = Join-Path $PluginRoot 'scripts\read_hook.py'
    $hooksPath = Join-Path $PluginRoot 'hooks\hooks.json'
    Assert-SetupPathHasNoReparsePoint -Path $hooksPath -Name 'Read hook registration'
    if (-not (Test-Path -LiteralPath $entry -PathType Leaf) -or -not (Test-Path -LiteralPath $hooksPath -PathType Leaf)) { return $false }
    $document = Read-CompanyAgentJson -Path $hooksPath
    $events = Get-SetupPropertyValue -Object $document -Name 'hooks'
    $changed = $false
    $expectedArgs = @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        '${CLAUDE_PLUGIN_ROOT}/scripts/Invoke-CompanyAgent.ps1', '-Mode', 'Hook', '-Event', 'PreToolUse')
    foreach ($group in @(Get-SetupPropertyValue -Object $events -Name 'PreToolUse')) {
        if ([string](Get-SetupPropertyValue -Object $group -Name 'matcher') -cne '^Read$') { continue }
        foreach ($hook in @(Get-SetupPropertyValue -Object $group -Name 'hooks')) {
            if ([string](Get-SetupPropertyValue -Object $hook -Name 'type') -cne 'command' -or
                [string](Get-SetupPropertyValue -Object $hook -Name 'command') -ine 'powershell.exe' -or
                ((@(Get-SetupPropertyValue -Object $hook -Name 'args') -join '|') -cne ($expectedArgs -join '|'))) { continue }
            $hook.command = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'cmd.exe'
            $hook.args = @('/d', '/v:off', '/s', '/c', 'call', $LauncherPath)
            $changed = $true
        }
    }
    if ($changed) { Write-CompanyAgentJsonAtomic -Path $hooksPath -Value $document }
    return $changed
}

function New-CompanyAgentReadHookSnapshot {
    param([string] $LauncherPath, [string] $BackupPath)
    Assert-SetupPathHasNoReparsePoint -Path $LauncherPath -Name 'Read hook launcher snapshot'
    $previous = $null
    if (Test-Path -LiteralPath $LauncherPath -PathType Leaf) {
        $previous = Read-SetupHarnessBytes -Path $LauncherPath
        $backup = Join-Path $BackupPath 'company-agent\read-hook.before-install.cmd'
        New-CompanyAgentDirectory -Path (Split-Path -Parent $backup)
        Write-SetupHarnessBytesAtomic -Path $backup -Bytes $previous -AssertMissing
        if ((Get-SetupHarnessHash -Bytes (Read-SetupHarnessBytes -Path $backup)) -cne (Get-SetupHarnessHash -Bytes $previous)) {
            throw 'Read hook recovery backup verification failed. Installation did not start.'
        }
    }
    return [pscustomobject]@{ path = $LauncherPath; previous = $previous; changed = $false; writtenHash = $null }
}

function Set-CompanyAgentReadHookLauncher {
    param([object] $Snapshot, [string] $PythonCommand, [string] $PluginRoot)
    $bytes = Get-CompanyAgentReadHookLauncherBytes -PythonCommand $PythonCommand -PluginRoot $PluginRoot
    if ($null -ne $Snapshot.previous) {
        Write-SetupHarnessBytesAtomic -Path $Snapshot.path -Bytes $bytes -ExpectedHash (Get-SetupHarnessHash -Bytes $Snapshot.previous)
    }
    else { Write-SetupHarnessBytesAtomic -Path $Snapshot.path -Bytes $bytes -AssertMissing }
    $Snapshot.writtenHash = Get-SetupHarnessHash -Bytes $bytes
    $Snapshot.changed = $true
}

function Restore-CompanyAgentReadHookLauncher {
    param([object] $Snapshot)
    if ($null -eq $Snapshot -or -not $Snapshot.changed) { return }
    Assert-SetupPathHasNoReparsePoint -Path $Snapshot.path -Name 'Read hook launcher recovery'
    if ($null -ne $Snapshot.previous) {
        Write-SetupHarnessBytesAtomic -Path $Snapshot.path -Bytes $Snapshot.previous -ExpectedHash $Snapshot.writtenHash
    }
    else {
        if (-not (Test-Path -LiteralPath $Snapshot.path -PathType Leaf) -or
            (Get-SetupHarnessHash -Bytes (Read-SetupHarnessBytes -Path $Snapshot.path)) -cne $Snapshot.writtenHash) {
            throw 'Read hook launcher changed before rollback; review the backup before retrying.'
        }
        Remove-Item -LiteralPath $Snapshot.path -Force
    }
    $Snapshot.changed = $false
}
