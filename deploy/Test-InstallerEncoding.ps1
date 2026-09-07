[CmdletBinding()]
param(
    [string] $PythonCommand = 'python',
    [switch] $KeepTestDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$requestedPython = $PythonCommand
$keepFixture = $KeepTestDirectory
. (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1') -FunctionsOnly
$python = Resolve-SetupApprovedPython -PreferredCommand $requestedPython -OnlyPreferred
if ([string]::IsNullOrWhiteSpace($python)) { throw 'A working Python 3.11+ is required.' }
$unicode = ([string][char]0xD55C) + ([char]0xAE00) + ' ' + ([char]0x2014) + ' ' + [char]::ConvertFromUtf32(0x1F9EA)
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('CAEncoding-' + [guid]::NewGuid().ToString('N').Substring(0, 8) + ' ' + $unicode)
$savedEnvironment = @{}
$savedConsole = [Console]::OutputEncoding
$savedPipeline = $OutputEncoding
$assertions = 0

function Assert-Encoding {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "Installer encoding regression failed: $Message" }
    $script:assertions++
}

function Get-EncodingFixtureDigest {
    param([string] $Root)
    if (-not (Test-Path -LiteralPath $Root)) { return 'missing' }
    return (@(Get-ChildItem -LiteralPath $Root -File -Recurse -Force | Sort-Object FullName | ForEach-Object {
        '{0}|{1}|{2}' -f $_.FullName, $_.Length, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }) -join "`n")
}

try {
    New-CompanyAgentDirectory -Path $testRoot
    foreach ($name in @('PYTHONIOENCODING', 'PYLAUNCHER_ALLOW_INSTALL', 'PYLAUNCHER_ALWAYS_INSTALL', 'PYTHON_MANAGER_AUTOMATIC_INSTALL', 'CLAUDE_CONFIG_DIR', 'COMPANY_AGENT_PLUGIN_ROOT', 'COMPANY_AGENT_KNOWLEDGE_BASE', 'CLAUDE_CODE_SUBAGENT_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE')) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    $env:PYTHONIOENCODING = 'cp949'
    $env:PYLAUNCHER_ALLOW_INSTALL = 'true'
    $env:PYLAUNCHER_ALWAYS_INSTALL = 'true'
    $env:PYTHON_MANAGER_AUTOMATIC_INSTALL = 'true'
    [Console]::OutputEncoding = [Text.Encoding]::GetEncoding(949)
    $OutputEncoding = [Text.Encoding]::GetEncoding(949)
    $beforeConsole = [Console]::OutputEncoding.CodePage
    $beforePipeline = $OutputEncoding.CodePage

    # Use actual non-ASCII bytes on both pipes; JSON ASCII escaping in the CLI
    # must not accidentally hide a missing PowerShell-side UTF-8 decoder.
    $scriptPath = Join-Path $testRoot ('roundtrip ' + $unicode + '.py')
    Write-CompanyAgentUtf8File -Path $scriptPath -Content @'
import json, os, sys
payload = {'args': sys.argv[1:], 'cwd': os.getcwd(), 'stdoutEncoding': sys.stdout.encoding,
           'stderrEncoding': sys.stderr.encoding, 'env': os.environ.get('PYTHONIOENCODING'),
           'autoInstall': os.environ.get('PYTHON_MANAGER_AUTOMATIC_INSTALL'),
           'launcherInstall': [os.environ.get(k) for k in ('PYLAUNCHER_ALLOW_INSTALL','PYLAUNCHER_ALWAYS_INSTALL')]}
print(json.dumps(payload, ensure_ascii=False))
print(json.dumps({'message': chr(92) + 'u literal: ' + sys.argv[1]}, ensure_ascii=False), file=sys.stderr)
'@
    $sentinel = Join-Path $testRoot 'SHELL_MUST_NOT_RUN.txt'
    $arguments = @($unicode, '', 'space  space', 'quote"inside', 'C:\ends with slash\', 'two\\"quoted', '& whoami > "' + $sentinel + '"', '$(not-a-command)', '%PATH%', "line1`nline2")
    $result = Invoke-CompanyAgentPythonProcess -Executable $python -Arguments (@('-B', $scriptPath) + $arguments) -WorkingDirectory $testRoot
    Assert-Encoding ($result.ExitCode -eq 0) 'Unicode echo child failed'
    $payload = $result.StdOut | ConvertFrom-Json
    $errorPayload = $result.StdErr | ConvertFrom-Json
    Assert-Encoding (@($payload.args).Count -eq $arguments.Count) 'Windows argv count changed'
    for ($index = 0; $index -lt $arguments.Count; $index++) {
        Assert-Encoding ([string]$payload.args[$index] -ceq $arguments[$index]) "Windows argv entry $index was changed"
    }
    Assert-Encoding ($payload.cwd -ceq $testRoot) 'Unicode working directory did not round-trip'
    Assert-Encoding ($errorPayload.message -ceq ('\u literal: ' + $unicode)) 'Unicode stderr did not round-trip'
    Assert-Encoding ($result.StdOut.Contains($unicode) -and $result.StdErr.Contains($unicode)) 'Fixture output was ASCII escaped instead of exercising UTF-8 decoding'
    Assert-Encoding ($payload.stdoutEncoding -eq 'utf-8' -and $payload.stderrEncoding -eq 'utf-8' -and $payload.env -eq 'utf-8') 'CP949 leaked into child IO'
    Assert-Encoding ($payload.autoInstall -eq 'false' -and @($payload.launcherInstall | Where-Object { $null -ne $_ }).Count -eq 0) 'Launcher automatic installation was not disabled'
    Assert-Encoding (-not (Test-Path -LiteralPath $sentinel)) 'Argument metacharacters were executed by a shell'

    $pipes = Invoke-CompanyAgentPythonProcess -Executable $python -Arguments @('-c', "import sys; sys.stderr.write(chr(0x2014)*131072); sys.stderr.flush(); sys.stdout.write(chr(0xD55C)*131072)") -TimeoutMilliseconds 10000
    Assert-Encoding ($pipes.StdOut.Length -eq 131072 -and $pipes.StdErr.Length -eq 131072) 'Concurrent output/error pipe draining failed'
    $exitFailure = Invoke-CompanyAgentPythonProcess -Executable $python -Arguments @('-c', 'import sys; print(chr(0x2014), file=sys.stderr); sys.exit(17)')
    Assert-Encoding ($exitFailure.ExitCode -eq 17 -and $exitFailure.StdErr.Trim() -ceq [string][char]0x2014) 'Nonzero child exit lost its decoded error'
    $legacy = Invoke-CompanyAgentPythonProcess -Executable $python -Arguments @('-c', "import sys; sys.stdout.reconfigure(encoding='cp949'); print(chr(0x2014))")
    Assert-Encoding ($legacy.ExitCode -ne 0 -and $legacy.StdErr.Contains('UnicodeEncodeError')) 'Fixture did not reproduce the original CP949 failure condition'

    $missingRejected = $false
    try { $null = Invoke-CompanyAgentPythonProcess -Executable (Join-Path $testRoot 'missing.exe') }
    catch { $missingRejected = $_.Exception.Message -match 'existing absolute .exe' }
    Assert-Encoding $missingRejected 'Missing executable was not rejected clearly'
    $scriptRejected = $false
    try { $null = Invoke-CompanyAgentPythonProcess -Executable $scriptPath }
    catch { $scriptRejected = $_.Exception.Message -match 'existing absolute .exe' }
    Assert-Encoding $scriptRejected 'Non-executable shell/script wrapper was accepted'
    # Simulate alias metadata without launching a real Windows Store alias.
    $aliasRejected = $false
    try {
        function Get-Item { param([string] $LiteralPath, [switch] $Force)
            return [pscustomobject]@{ Attributes = [IO.FileAttributes]::ReparsePoint; Length = 0 }
        }
        try { $null = Invoke-CompanyAgentPythonProcess -Executable $python }
        catch { $aliasRejected = $_.Exception.Message -match 'Windows Store execution alias' }
    }
    finally { Remove-Item Function:\Get-Item }
    Assert-Encoding $aliasRejected 'Store alias metadata was not rejected before process launch'
    $invalidRejected = $false
    try { $null = Invoke-CompanyAgentPythonProcess -Executable $python -Arguments @('-c', 'import sys; sys.stdout.buffer.write(bytes([255])); sys.stdout.flush()') }
    catch { $invalidRejected = $true }
    Assert-Encoding $invalidRejected 'Invalid UTF-8 was silently replaced instead of rejected'
    $invalidErrorRejected = $false
    try { $null = Invoke-CompanyAgentPythonProcess -Executable $python -Arguments @('-c', 'import sys; sys.stderr.buffer.write(bytes([255])); sys.stderr.flush()') }
    catch { $invalidErrorRejected = $true }
    Assert-Encoding $invalidErrorRejected 'Invalid UTF-8 stderr was silently replaced instead of rejected'
    $timeout = [Diagnostics.Stopwatch]::StartNew()
    $timeoutRejected = $false
    try { $null = Invoke-CompanyAgentPythonProcess -Executable $python -Arguments @('-c', 'import time; time.sleep(20)') -TimeoutMilliseconds 200 }
    catch { $timeoutRejected = $_.Exception.Message -match 'timed out' }
    $timeout.Stop()
    Assert-Encoding ($timeoutRejected -and $timeout.Elapsed.TotalSeconds -lt 5) 'Timeout did not terminate promptly'
    # A subprocess may exit while its short-lived descendant still owns the
    # redirected handles. Capture must time out rather than wait forever.
    $drainTimeout = [Diagnostics.Stopwatch]::StartNew()
    $drainRejected = $false
    try {
        $null = Invoke-CompanyAgentPythonProcess -Executable $python -Arguments @('-c', "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)'],stdout=sys.stdout,stderr=sys.stderr)") -TimeoutMilliseconds 500
    }
    catch { $drainRejected = $_.Exception.Message -match 'output capture timed out' }
    $drainTimeout.Stop()
    Assert-Encoding ($drainRejected -and $drainTimeout.Elapsed.TotalSeconds -lt 5) 'Inherited pipe handles prevented bounded output capture'
    $probe = Invoke-SetupPythonProbe -Executable $python
    Assert-Encoding ($null -ne $probe -and $probe.automaticInstallDisabled -eq $true) 'Isolated Python probe failed under CP949 parent configuration'
    Assert-Encoding ($env:PYTHONIOENCODING -eq 'cp949' -and $env:PYLAUNCHER_ALLOW_INSTALL -eq 'true' -and $env:PYLAUNCHER_ALWAYS_INSTALL -eq 'true' -and $env:PYTHON_MANAGER_AUTOMATIC_INSTALL -eq 'true') 'Helper changed parent environment on success/failure'
    Assert-Encoding ([Console]::OutputEncoding.CodePage -eq $beforeConsole -and $OutputEncoding.CodePage -eq $beforePipeline) 'Helper changed parent console/pipeline encoding'

    # Exercise the real installer boundary too, with an isolated personal
    # Skill and namespaced incoming Skill carrying the reported character.
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $manifest = Read-CompanyAgentJson -Path (Join-Path $repoRoot 'company-agent-plugin\.claude-plugin\plugin.json')
    $knowledgeManifest = Read-CompanyAgentJson -Path (Join-Path $repoRoot 'corporate-knowledge\pack.json')
    $zip = Join-Path $testRoot 'bundle.zip'
    $null = & (Join-Path $PSScriptRoot 'New-OfflineBundle.ps1') -SourceRoot $repoRoot -CoreVersion $manifest.version -KnowledgeVersion $knowledgeManifest.version -OutputPath $zip -SkipSourceValidation
    $bundle = Join-Path $testRoot 'bundle'
    Expand-Archive -LiteralPath $zip -DestinationPath $bundle
    $profile = Join-Path $testRoot 'profile'
    $config = Join-Path $profile '.claude'
    $localData = Join-Path $profile 'AppData\Local'
    $state = Join-Path $testRoot ('state ' + $unicode)
    $project = Join-Path $testRoot ('project ' + $unicode)
    foreach ($path in @($config, $localData, $project)) { New-CompanyAgentDirectory -Path $path }
    $sourcePlugin = Join-Path $bundle 'payload\core\plugin'
    $sourceKnowledge = Join-Path $bundle 'payload\knowledge'
    $skillName = [string](Get-ChildItem -LiteralPath (Join-Path $sourcePlugin 'skills') -Directory | Sort-Object Name | Select-Object -First 1).Name
    $skillPath = Join-Path $config ("skills\$skillName\SKILL.md")
    Write-CompanyAgentUtf8File -Path $skillPath -Content ("---`nname: $skillName`ndescription: $unicode`n---`nUser content preserved.`n")
    $env:CLAUDE_CONFIG_DIR = $config
    $env:COMPANY_AGENT_PLUGIN_ROOT = $null
    $env:COMPANY_AGENT_KNOWLEDGE_BASE = $null
    $env:CLAUDE_CODE_SUBAGENT_MODEL = $null
    $env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE = $null
    $before = Get-EncodingFixtureDigest $profile
    $inventoryParameters = @{
        PythonExecutable = $python; PluginRoot = $sourcePlugin; PersonalStatePath = $state
        KnowledgeRoot = $sourceKnowledge; ClaudeConfigPath = $config; InstallScope = 'User'
    }
    $inventory = Invoke-SetupSkillCommand @inventoryParameters
    $existingSkill = @($inventory.skills | Where-Object { $_.source -eq 'user' -and $_.name -eq $skillName })
    Assert-Encoding ($inventory.complete -eq $true -and $existingSkill.Count -eq 1) 'Unicode installer inventory was incomplete'
    Assert-Encoding ($existingSkill[0].description -ceq $unicode -and $existingSkill[0].path -ceq $skillPath) 'Real Skill JSON lost Unicode metadata/path'
    Assert-Encoding (@($inventory.conflicts).Count -gt 0) 'Unicode fixture duplicate was not detected'
    Assert-Encoding (-not (Test-Path -LiteralPath $state)) 'Read-only inventory initialized personal state'
    Write-CompanyAgentUtf8File -Path $skillPath -Content ("---`nname: [invalid yaml`ndescription: $unicode`n---`nUser content preserved.`n")
    $invalidBefore = Get-EncodingFixtureDigest $profile
    $incompleteRejected = $false
    try { $null = Invoke-SetupSkillCommand @inventoryParameters }
    catch { $incompleteRejected = $_.Exception.Message -match 'incomplete|failed' }
    Assert-Encoding ($incompleteRejected -and -not (Test-Path -LiteralPath $state) -and (Get-EncodingFixtureDigest $profile) -ceq $invalidBefore) 'Failed inventory made changes or was treated as no conflicts'
    Write-CompanyAgentUtf8File -Path $skillPath -Content ("---`nname: $skillName`ndescription: $unicode`n---`nUser content preserved.`n")
    $selected = Invoke-SetupSkillCommand @inventoryParameters -Command 'prefer-incoming'
    $preferencesPath = Join-Path $state 'config\skill-preferences.json'
    Assert-Encoding (Test-Path -LiteralPath $preferencesPath -PathType Leaf) 'UTF-8 incoming preference command did not save a selection'
    $stateBefore = Get-EncodingFixtureDigest $state
    $setupParameters = @{
        BundleRoot = $bundle; Scope = 'Project'; ProjectRoot = $project; UserStateRoot = $state
        ClaudeConfigRoot = $config; InvokingUserProfile = $profile; InvokingLocalAppData = $localData
        PythonCommand = $python; NonInteractive = $true; DryRun = $true; SkipPrerequisiteCheck = $true
        SkipAdminCheck = $true; ExistingHarnessAction = 'Replace'; SkillConflictAction = 'KeepCurrent'
        BackupRoot = (Join-Path $testRoot 'backups')
    }
    $preflight = & (Join-Path $bundle 'deploy\Setup-CompanyAgent.ps1') @setupParameters
    Assert-Encoding ($preflight.status -eq 'dry-run') 'Real scoped installer preflight failed under CP949'
    Assert-Encoding ((Get-EncodingFixtureDigest $profile) -ceq $before -and (Get-EncodingFixtureDigest $state) -ceq $stateBefore) 'Read-only preflight changed personal files'
    Assert-Encoding (-not (Test-Path -LiteralPath $setupParameters.BackupRoot)) 'Read-only preflight created a backup/write unexpectedly'
}
finally {
    [Console]::OutputEncoding = $savedConsole
    $OutputEncoding = $savedPipeline
    foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    if (-not $keepFixture -and (Test-Path -LiteralPath $testRoot)) {
        $resolvedRoot = [IO.Path]::GetFullPath($testRoot)
        $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        if (-not $resolvedRoot.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
            (Split-Path -Leaf $resolvedRoot) -notlike 'CAEncoding-*') { throw 'Unsafe fixture cleanup target.' }
        Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
    }
}

[pscustomobject]@{ status = 'pass'; assertions = $assertions; parentCodePage = 949; unicodeRoundTrip = $true; realInstallerPreflight = $true; noPersonalInstall = $true }
