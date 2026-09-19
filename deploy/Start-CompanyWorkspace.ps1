[CmdletBinding()]
param([string]$PythonCommand = 'python', [switch]$Demo, [switch]$NoBrowser, [string]$StateRoot)
$ErrorActionPreference = 'Stop'
$workspaceMutex = $null
$workspaceLockHeld = $false
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Start Company Workspace as your normal Windows user, not as administrator.' }
    $mutexName = 'Local\CompanyWorkspace-' + $identity.User.Value
    if ($Demo) { $mutexName += '-demo' }
    $workspaceMutex = New-Object Threading.Mutex($false, $mutexName)
    $workspaceLockHeld = $workspaceMutex.WaitOne(0)
    if (-not $workspaceLockHeld) { return }
    $appRoot = Split-Path $PSScriptRoot -Parent
    $appStateRoot = if ($StateRoot) { [IO.Path]::GetFullPath($StateRoot) } else { Join-Path $env:LOCALAPPDATA 'CompanyAgent\local-ui' }
    $runtimeStateRoot = $appStateRoot
    if ($Demo) { $runtimeStateRoot = Join-Path $appStateRoot 'demo' }
    $runtimePath = Join-Path $runtimeStateRoot 'runtime.json'
    # Reuse a live local server; do not start another CLI or abandon active work.
    $otherWorkspaceRunning = $false
    if (Test-Path -LiteralPath $runtimePath) {
        try {
            $runtime = Get-Content -LiteralPath $runtimePath -Raw -Encoding UTF8 | ConvertFrom-Json
            $uri = [Uri]$runtime.url
            if ($uri.Scheme -ne 'http' -or $uri.Host -ne '127.0.0.1' -or $uri.AbsolutePath -ne '/' -or $uri.Fragment -notmatch '^#token=([A-Za-z0-9_-]{40,100})$') { throw 'Invalid local endpoint' }
            $auth = $Matches[1]
            $origin = $uri.GetLeftPart([UriPartial]::Authority)
            $health = Invoke-RestMethod -Uri ($origin + '/api/bootstrap') -Headers @{ Authorization = ('Bearer ' + $auth) } -TimeoutSec 2
            if ($health.application -eq 'company-workspace' -and [bool]$health.demo -eq [bool]$Demo) {
                if ($health.workspaceVersion -eq '0.4' -and $health.appRoot -eq $appRoot) {
                    if ($NoBrowser) { return }
                    $edge = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
                    if (Test-Path -LiteralPath $edge) { Start-Process -FilePath $edge -ArgumentList @('--new-window', ('--app=' + $uri.AbsoluteUri)) -WindowStyle Normal | Out-Null }
                    else { Start-Process $uri.AbsoluteUri | Out-Null }
                    return
                }
                $otherWorkspaceRunning = $true
            }
        } catch { # Stale runtime records never authorize process termination.
        }
    }
    if ($otherWorkspaceRunning) { throw 'Another Workspace version is still running. Use its top-right power button to exit, then open this version. Existing work was not stopped.' }
    if (-not $Demo -and -not $env:COMPANY_AGENT_CLAUDE) {
        # Resolve exactly what `claude` means in this user's shell. Do not silently
        # replace a profile alias/company wrapper with another executable on PATH.
        $terminalClaude = Get-Command claude -ErrorAction Stop | Select-Object -First 1
        while ($terminalClaude.CommandType -eq 'Alias') { $terminalClaude = $terminalClaude.ResolvedCommand }
        if ($terminalClaude.CommandType -in @('Application', 'ExternalScript')) {
            $env:COMPANY_WORKSPACE_CLAUDE_ENTRY = $terminalClaude.Source
            $env:COMPANY_WORKSPACE_CLAUDE_PROFILE = '0'
        } elseif ($terminalClaude.CommandType -eq 'Function') {
            # Functions are reloaded from the same trusted shell profiles; no
            # function body or credential is copied into the app's state directory.
            $env:COMPANY_WORKSPACE_CLAUDE_ENTRY = 'claude'
            $env:COMPANY_WORKSPACE_CLAUDE_PROFILE = '1'
            $definitionHasher = [Security.Cryptography.SHA256]::Create()
            try {
                $definitionBytes = [Text.Encoding]::UTF8.GetBytes($terminalClaude.Definition)
                $env:COMPANY_WORKSPACE_CLAUDE_DEFINITION_HASH = [BitConverter]::ToString($definitionHasher.ComputeHash($definitionBytes))
            } finally { $definitionHasher.Dispose() }
        } else { throw 'The terminal claude command could not be resolved. No login or settings were changed.' }
        $env:COMPANY_WORKSPACE_SHELL = (Get-Process -Id $PID).Path
    }
    $resolvedPython = (Get-Command $PythonCommand -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $probe = & $resolvedPython -X utf8 -c "import sys; print(sys.executable); print(int(sys.version_info >= (3, 11)))"
    if ($LASTEXITCODE -ne 0 -or $probe[-1] -ne '1') { throw 'Python 3.11 or later is required. Use the approved Company Agent Python installation.' }
    $resolvedPython = [string]$probe[0]
    $windowless = Join-Path (Split-Path $resolvedPython -Parent) 'pythonw.exe'
    if (Test-Path -LiteralPath $windowless) { $resolvedPython = $windowless }
    $arguments = @('-X', 'utf8', '-m', 'local_app.server')
    if ($Demo) { $arguments += '--demo' }
    if ($NoBrowser) { $arguments += '--no-browser' }
    if ($StateRoot) { $arguments += @('--state', ('"' + $appStateRoot + '"')) }
    $workspaceProcess = Start-Process -FilePath $resolvedPython -ArgumentList $arguments -WorkingDirectory $appRoot -WindowStyle Hidden -PassThru
    $workspaceReady = $false
    $deadline = [DateTime]::UtcNow.AddSeconds(40)
    while ([DateTime]::UtcNow -lt $deadline -and -not $workspaceProcess.HasExited) {
        if (Test-Path -LiteralPath $runtimePath) {
            try {
                $startedRuntime = Get-Content -LiteralPath $runtimePath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($startedRuntime.pid -eq $workspaceProcess.Id) { $workspaceReady = $true; break }
            } catch {}
        }
        Start-Sleep -Milliseconds 200
        $workspaceProcess.Refresh()
    }
    if (-not $workspaceReady) { throw 'The local app did not become ready. Check the approved Python and Claude installation. No settings were changed.' }
} catch {
    if ($NoBrowser) { [Console]::Error.WriteLine($_.Exception.Message) }
    else {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Company Workspace - startup', 'OK', 'Warning') | Out-Null
    }
    exit 1
} finally {
    if ($workspaceLockHeld -and $workspaceMutex) { $workspaceMutex.ReleaseMutex() }
    if ($workspaceMutex) { $workspaceMutex.Dispose() }
}
