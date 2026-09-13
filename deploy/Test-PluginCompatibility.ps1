[CmdletBinding()]
param([string] $PythonCommand = 'python')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1') -FunctionsOnly
. (Join-Path $PSScriptRoot 'CompanyAgent.PluginCompatibility.ps1')
$python = Resolve-SetupApprovedPython -PreferredCommand $PythonCommand
if (-not $python) { throw 'Test requires an installed Python 3.11+.' }
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('company-agent-hook-test-' + [guid]::NewGuid().ToString('N'))
$config = Join-Path $fixture 'profile with spaces'
$plugin = Join-Path $config 'plugins\cache\ouroboros\ouroboros\test'
$null = New-Item -ItemType Directory -Path (Join-Path $plugin 'hooks') -Force
$null = New-Item -ItemType Directory -Path (Join-Path $plugin 'scripts') -Force
function Assert-Test($Condition, $Message) { if (-not $Condition) { throw $Message } }
$events = @{}
foreach ($pair in @(@('SessionStart', 'session-start.py'), @('UserPromptSubmit', 'keyword-detector.py'), @('PostToolUse', 'drift-monitor.py'))) {
    # Inert script: exercises stdin/stdout/exit status, not the third-party updater.
    [IO.File]::WriteAllText((Join-Path $plugin ('scripts\' + $pair[1])), 'import sys; print("fixture:" + sys.stdin.read()); sys.exit(0)', (New-Object Text.UTF8Encoding($false)))
    $events[$pair[0]] = @(@{ matcher = '*'; hooks = @(@{ type = 'command'; command = ('python3 "${CLAUDE_PLUGIN_ROOT}/scripts/' + $pair[1] + '"'); timeout = 5 }) })
}
$events['Stop'] = @(@{ hooks = @(@{ type = 'command'; command = 'python3 custom.py' }) })
$hooksPath = Join-Path $plugin 'hooks\hooks.json'
Write-CompanyAgentJsonAtomic $hooksPath @{ hooks = $events }
Write-CompanyAgentJsonAtomic (Join-Path $config 'settings.json') @{ enabledPlugins = @{ 'ouroboros@ouroboros' = $true }; untouched = 'preserve' }
$settingsHash = (Get-FileHash -LiteralPath (Join-Path $config 'settings.json')).Hash
Write-CompanyAgentJsonAtomic (Join-Path $config 'plugins\installed_plugins.json') @{ plugins = @{ 'ouroboros@ouroboros' = @(@{ scope = 'user'; installPath = $plugin }) } }
$originalHash = (Get-FileHash -LiteralPath $hooksPath).Hash
$repairs = @(Repair-CompanyAgentPluginPython -ClaudeConfigRoot $config -PythonCommand $python -BackupBase (Join-Path $fixture 'backups'))
Assert-Test ($repairs.Count -eq 1 -and $repairs[0].changed -eq 3) 'Expected three repaired known hooks.'
Assert-Test ((Get-FileHash -LiteralPath (Join-Path $repairs[0].backup 'hooks.json')).Hash -eq $originalHash) 'Backup is not byte-exact.'
$after = Read-CompanyAgentJson $hooksPath
Assert-Test ($after.hooks.Stop[0].hooks[0].command -ceq 'python3 custom.py') 'Unknown command changed.'
Assert-Test ((Get-FileHash -LiteralPath (Join-Path $config 'settings.json')).Hash -eq $settingsHash) 'Settings changed.'
Assert-Test (@(Repair-CompanyAgentPluginPython -ClaudeConfigRoot $config -PythonCommand $python -BackupBase (Join-Path $fixture 'backups')).Count -eq 0) 'Reapply is not idempotent.'
Assert-Test (@(Repair-CompanyAgentPluginPython -ClaudeConfigRoot $config -PythonCommand $python -BackupBase (Join-Path $fixture 'backups') -Scope Project -ProjectRoot $fixture).Count -eq 0) 'Project repair changed a user plugin.'
# Simulate another PC's Python path, including non-ASCII, spaces, a quote and $.
$alternateRoot = Join-Path $fixture ("runtime's " + '$ ' + [char]0xd55c)
$venv = Invoke-CompanyAgentPythonProcess -Executable $python -Arguments @('-I', '-X', 'utf8', '-B', '-m', 'venv', '--without-pip', $alternateRoot)
Assert-Test ($venv.ExitCode -eq 0) ('Alternate runtime fixture failed: ' + $venv.StdErr)
$alternatePython = Join-Path $alternateRoot 'Scripts\python.exe'
$remapped = @(Repair-CompanyAgentPluginPython -ClaudeConfigRoot $config -PythonCommand $alternatePython -BackupBase (Join-Path $fixture 'backups'))
Assert-Test ($remapped.Count -eq 1 -and $remapped[0].changed -eq 3) 'Moved interpreter did not update the previously repaired hooks.'
Assert-Test (@(Repair-CompanyAgentPluginPython -ClaudeConfigRoot $config -PythonCommand $alternatePython -BackupBase (Join-Path $fixture 'backups')).Count -eq 0) 'Quoted runtime path is not idempotent.'
$after = Read-CompanyAgentJson $hooksPath
$git = Get-Command git.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1
$bashPath = Join-Path (Split-Path (Split-Path $git.Source -Parent) -Parent) 'bin\bash.exe'
if (-not (Test-Path -LiteralPath $bashPath)) { throw 'Git Bash required to test the native Claude hook command.' }
$oldPluginRoot = $env:CLAUDE_PLUGIN_ROOT
try {
    $env:CLAUDE_PLUGIN_ROOT = $plugin.Replace('\', '/')
    foreach ($event in @('SessionStart', 'UserPromptSubmit', 'PostToolUse')) {
        $command = $after.hooks.$event[0].hooks[0].command
        # Use ProcessStartInfo's tested Windows argument escaping, not PS 5.1
        # native argument passing which strips the command's embedded quotes.
        $process = New-Object Diagnostics.Process
        $process.StartInfo.FileName = $bashPath
        $process.StartInfo.Arguments = '-c ' + (ConvertTo-CompanyAgentProcessArgument $command)
        $process.StartInfo.UseShellExecute = $false
        $process.StartInfo.CreateNoWindow = $true
        $process.StartInfo.RedirectStandardInput = $true
        $process.StartInfo.RedirectStandardOutput = $true
        $process.StartInfo.RedirectStandardError = $true
        $null = $process.Start()
        $inputBytes = [Text.Encoding]::UTF8.GetBytes('{"probe":true}')
        $process.StandardInput.BaseStream.Write($inputBytes, 0, $inputBytes.Length)
        $process.StandardInput.BaseStream.Close()
        $output = $process.StandardOutput.ReadToEnd()
        $errorText = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        # .NET Framework's redirected stdin can prepend its encoding BOM.
        # Account for that test-host artifact; the JSON payload must be intact.
        Assert-Test ($process.ExitCode -eq 0 -and $output.Replace([string][char]0xfeff, '').Contains('fixture:{"probe":true}')) ("Hook failed: $errorText $output")
        $process.Dispose()
    }
} finally { $env:CLAUDE_PLUGIN_ROOT = $oldPluginRoot }
# Out-of-profile inventory paths must fail closed.
Write-CompanyAgentJsonAtomic (Join-Path $config 'plugins\installed_plugins.json') @{ plugins = @{ 'ouroboros@ouroboros' = @(@{ scope = 'user'; installPath = $fixture }) } }
$rejected = $false
try { Repair-CompanyAgentPluginPython -ClaudeConfigRoot $config -PythonCommand $python -BackupBase (Join-Path $fixture 'backups') } catch { $rejected = $true }
Assert-Test $rejected 'External plugin path was not rejected.'
[pscustomobject]@{ status = 'pass'; repairedHooks = 3; gitBashExecutions = 3; fixture = $fixture; python = $python }
