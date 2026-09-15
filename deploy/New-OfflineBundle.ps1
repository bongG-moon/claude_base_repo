[CmdletBinding()]
param(
    [string] $SourceRoot,
    [Parameter(Mandatory = $true)]
    [string] $CoreVersion,
    [Parameter(Mandatory = $true)]
    [string] $KnowledgeVersion,
    [string] $OutputPath,
    [string] $InstallRoot,
    [string] $DataRoot,
    [string] $UserStateRoot,
    [string] $ClaudeCommand = 'claude',
    [string] $PythonCommand = 'python',
    [string] $PythonRuntimeZip,
    [string] $PythonRuntimeSha256 = 'd1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf',
    [switch] $IncludeBundledPython,
    [switch] $WithoutBundledPython,
    [switch] $SkipAcl,
    [switch] $SkipSourceValidation,
    [switch] $Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')

if ($IncludeBundledPython -and $WithoutBundledPython) {
    throw 'IncludeBundledPython and WithoutBundledPython cannot be used together.'
}
if (-not $IncludeBundledPython -and
    ($PSBoundParameters.ContainsKey('PythonRuntimeZip') -or $PSBoundParameters.ContainsKey('PythonRuntimeSha256'))) {
    throw 'PythonRuntimeZip and PythonRuntimeSha256 require -IncludeBundledPython. The default employee bundle uses an existing Python 3.11 or later installation.'
}

# Employee packages contain only the deploy entrypoints and their dependencies.
# Build/download helpers and regression scripts remain on the build PC.
$productionDeployFiles = @(
    'CompanyAgent.Common.ps1',
    'CompanyAgent.UserContext.ps1',
    'CompanyAgent.ClaudeDiscovery.ps1',
    'CompanyAgent.PluginCompatibility.ps1',
    'ExistingHarness.ps1',
    'HarnessReplacement.ps1',
    'Initialize-CompanyAgentUser.ps1',
    'Install-CompanyAgent.cmd',
    'Install-CompanyAgent.ps1',
    'Install-ScopedCompanyAgent.ps1',
    'Restore-PreviousHarness.ps1',
    'Rollback-CompanyAgent.ps1',
    'Setup-CompanyAgent.ps1',
    'Start-CompanyAgent.ps1',
    'Uninstall-CompanyAgent.ps1',
    'Uninstall-ScopedCompanyAgent.ps1',
    'Update-CompanyAgent.ps1'
)

function Copy-CompanyAgentPluginSource {
    param([string] $Source, [string] $Destination)

    New-CompanyAgentDirectory -Path $Destination
    foreach ($item in @(Get-ChildItem -LiteralPath $Source -Force)) {
        if ($item.Name -ieq 'runtime') {
            # A prior local build must never supply the packaged interpreter.
            # Opt-in packages also receive a fresh, hash-verified runtime below.
            continue
        }
        Copy-Item -LiteralPath $item.FullName -Destination $Destination -Recurse -Force
    }
}

function Assert-CompanyAgentExternalBundleFiles {
    param([string] $Root)

    foreach ($file in @(Get-ChildItem -LiteralPath $Root -Recurse -Force | Where-Object { -not $_.PSIsContainer })) {
        if ($file.Extension -iin @('.exe', '.dll', '.pyd', '.so', '.dylib')) {
            throw "External-runtime bundle cannot contain native binary files: $($file.FullName)"
        }
    }
    if (Test-Path -LiteralPath (Join-Path $Root 'payload\core\plugin\runtime')) {
        throw 'External-runtime bundle unexpectedly contains a runtime directory.'
    }
}

if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $SourceRoot = Split-Path -Parent $PSScriptRoot
}
$SourceRoot = ConvertTo-CompanyAgentFullPath -Path $SourceRoot
Assert-CompanyAgentVersion -Version $CoreVersion -Name 'CoreVersion'
Assert-CompanyAgentVersion -Version $KnowledgeVersion -Name 'KnowledgeVersion'

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $SourceRoot ("dist\company-agent-{0}-{1}.zip" -f $CoreVersion, $KnowledgeVersion)
}
$OutputPath = ConvertTo-CompanyAgentFullPath -Path $OutputPath
if ([System.IO.Path]::GetExtension($OutputPath) -ine '.zip') {
    throw "OutputPath must end in .zip: $OutputPath"
}
if ((Test-Path -LiteralPath $OutputPath) -and -not $Force) {
    throw "Output bundle already exists. Use -Force to replace it: $OutputPath"
}

$pluginSource = Join-Path $SourceRoot 'company-agent-plugin'
$knowledgeSource = Join-Path $SourceRoot 'corporate-knowledge'
$deploySource = Join-Path $SourceRoot 'deploy'
$claudeInstallDoc = Join-Path $SourceRoot 'INSTALL_WITH_CLAUDE.md'
$easyInstaller = Join-Path $SourceRoot 'Install-CompanyAgent.cmd'
foreach ($requiredPath in @($pluginSource, $knowledgeSource, $deploySource)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Container)) {
        throw "Required source directory was not found: $requiredPath"
    }
}
foreach ($requiredFile in @($claudeInstallDoc, $easyInstaller)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required beginner installation entrypoint was not found: $requiredFile"
    }
}
foreach ($deployName in $productionDeployFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $deploySource $deployName) -PathType Leaf)) {
        throw "Required production deployment file was not found: $deployName"
    }
}

$pluginManifestPath = Join-Path $pluginSource '.claude-plugin\plugin.json'
$knowledgeManifestPath = Join-Path $knowledgeSource 'pack.json'
$pluginManifest = Read-CompanyAgentJson -Path $pluginManifestPath
$knowledgeManifest = Read-CompanyAgentJson -Path $knowledgeManifestPath
if ([string]$pluginManifest.version -cne $CoreVersion) {
    throw "CoreVersion '$CoreVersion' does not match plugin manifest version '$($pluginManifest.version)' in $pluginManifestPath"
}
if ([string]$knowledgeManifest.version -cne $KnowledgeVersion) {
    throw "KnowledgeVersion '$KnowledgeVersion' does not match pack version '$($knowledgeManifest.version)' in $knowledgeManifestPath"
}

foreach ($sourcePath in @($pluginSource, $knowledgeSource, $deploySource)) {
    $reparsePoint = Get-ChildItem -LiteralPath $sourcePath -Recurse -Force |
        Where-Object { ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 } |
        Select-Object -First 1
    if ($null -ne $reparsePoint) {
        throw "Reparse points are not allowed in an offline bundle: $($reparsePoint.FullName)"
    }
}

if (-not $SkipSourceValidation) {
    Assert-CompanyAgentPrerequisites -ClaudeCommand $ClaudeCommand -PythonCommand $PythonCommand
    $claudeInfo = Get-Command $ClaudeCommand | Select-Object -First 1
    $claudeExecutable = $claudeInfo.Source
    if ([string]::IsNullOrWhiteSpace($claudeExecutable)) {
        $claudeExecutable = $claudeInfo.Definition
    }
    $pluginValidation = & $claudeExecutable plugin validate --strict $pluginSource 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Claude plugin validation failed:`r`n$($pluginValidation -join [Environment]::NewLine)"
    }

    $pythonInfo = Get-Command $PythonCommand | Select-Object -First 1
    $pythonExecutable = $pythonInfo.Source
    if ([string]::IsNullOrWhiteSpace($pythonExecutable)) {
        $pythonExecutable = $pythonInfo.Definition
    }
    $previousDontWriteBytecode = [Environment]::GetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', 'Process')
    try {
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', '1', 'Process')
        $knowledgeValidation = Invoke-CompanyAgentPythonProcess -Executable $pythonExecutable -Arguments @('-B', (Join-Path $pluginSource 'scripts\harness_cli.py'), 'knowledge', 'validate', '--base', $knowledgeSource)
        if ($knowledgeValidation.ExitCode -ne 0) {
            throw "Corporate Knowledge validation failed:`r`n$($knowledgeValidation.StdOut)`r`n$($knowledgeValidation.StdErr)"
        }
    }
    finally {
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', $previousDontWriteBytecode, 'Process')
    }

    $compileCache = Join-Path $env:TEMP ('CompanyAgent-Compile-' + [guid]::NewGuid().ToString('N'))
    $previousCachePrefix = [Environment]::GetEnvironmentVariable('PYTHONPYCACHEPREFIX', 'Process')
    try {
        [Environment]::SetEnvironmentVariable('PYTHONPYCACHEPREFIX', $compileCache, 'Process')
        $compileOutput = Invoke-CompanyAgentPythonProcess -Executable $pythonExecutable -Arguments @('-m', 'compileall', '-q', $pluginSource)
        if ($compileOutput.ExitCode -ne 0) {
            throw "Python compile validation failed:`r`n$($compileOutput.StdOut)`r`n$($compileOutput.StdErr)"
        }
    }
    finally {
        [Environment]::SetEnvironmentVariable('PYTHONPYCACHEPREFIX', $previousCachePrefix, 'Process')
        if (Test-Path -LiteralPath $compileCache) {
            Remove-Item -LiteralPath $compileCache -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

$temporaryBase = ConvertTo-CompanyAgentFullPath -Path $env:TEMP
$stagePath = Join-Path $temporaryBase ('CompanyAgent-Bundle-' + [guid]::NewGuid().ToString('N'))
$outputParent = Split-Path -Parent $OutputPath
New-CompanyAgentDirectory -Path $outputParent

try {
    New-CompanyAgentDirectory -Path $stagePath
    Copy-CompanyAgentPluginSource -Source $pluginSource -Destination (Join-Path $stagePath 'payload\core\plugin')
    Copy-CompanyAgentDirectoryContents -Source $knowledgeSource -Destination (Join-Path $stagePath 'payload\knowledge')
    $deployDestination = Join-Path $stagePath 'deploy'
    New-CompanyAgentDirectory -Path $deployDestination
    foreach ($deployName in $productionDeployFiles) {
        Copy-Item -LiteralPath (Join-Path $deploySource $deployName) -Destination (Join-Path $deployDestination $deployName) -Force
    }

    if ($IncludeBundledPython) {
        if ([string]::IsNullOrWhiteSpace($PythonRuntimeZip)) {
            $PythonRuntimeZip = Join-Path $SourceRoot 'build\runtime\python-3.13.15-embed-amd64.zip'
        }
        if (-not (Test-Path -LiteralPath $PythonRuntimeZip -PathType Leaf)) {
            throw 'The optional bundled Python archive was not found. Run deploy\Get-EmbeddedPython.ps1 on the connected build PC, or supply -PythonRuntimeZip with -PythonRuntimeSha256. Omit -IncludeBundledPython to use an existing Python 3.11 or later installation.'
        }
        if ($PythonRuntimeSha256 -notmatch '^[a-fA-F0-9]{64}$' -or
            (Get-FileHash -LiteralPath $PythonRuntimeZip -Algorithm SHA256).Hash -ine $PythonRuntimeSha256) {
            throw 'Embedded Python archive hash does not match the pinned release digest.'
        }
        $runtimeDestination = Join-Path $stagePath 'payload\core\plugin\runtime\python'
        New-CompanyAgentDirectory -Path $runtimeDestination
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [IO.Compression.ZipFile]::OpenRead($PythonRuntimeZip)
        try {
            foreach ($entry in $archive.Entries) {
                if ($entry.FullName -match '(^[\\/]|^[A-Za-z]:|(^|[\\/])\.\.([\\/]|$))') {
                    throw 'Embedded Python archive contains an unsafe path.'
                }
            }
        } finally { $archive.Dispose() }
        [IO.Compression.ZipFile]::ExtractToDirectory($PythonRuntimeZip, $runtimeDestination)
        $runtimePth = @(Get-ChildItem -LiteralPath $runtimeDestination -Filter 'python*._pth')
        if ($runtimePth.Count -ne 1 -or -not (Test-Path -LiteralPath (Join-Path $runtimeDestination 'LICENSE.txt'))) {
            throw 'Expected the official Python Windows embeddable package with its license and isolated path file.'
        }
        $pthContent = Get-Content -LiteralPath $runtimePth[0].FullName -Raw -Encoding UTF8
        # Resolve package imports from any cwd without enabling site/PYTHONPATH.
        Write-CompanyAgentUtf8File -Path $runtimePth[0].FullName -Content ($pthContent.TrimEnd() + "`n../../scripts`n")
        $runtimeVersion = Invoke-CompanyAgentPythonProcess -Executable (Join-Path $runtimeDestination 'python.exe') -Arguments @('-B', '-c', 'import sys, company_agent; print(sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3,11) else 1)')
        if ($runtimeVersion.ExitCode -ne 0) { throw 'The bundled Python runtime failed its import/version check on this build PC.' }
        Write-CompanyAgentJsonAtomic -Path (Join-Path $runtimeDestination 'company-agent-runtime.json') -Value ([ordered]@{
            schemaVersion = 1; pythonVersion = $runtimeVersion.StdOut.Trim(); architecture = 'windows-x64'
            archiveSha256 = $PythonRuntimeSha256.ToLowerInvariant(); source = [IO.Path]::GetFileName($PythonRuntimeZip)
            pathCustomization = '../../scripts'; license = 'LICENSE.txt'
        })
    }

    $excludedDirectoryNames = @('.git', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.tox', '.nox', 'htmlcov')
    $excludedDirectories = @(Get-ChildItem -LiteralPath $stagePath -Recurse -Force | Where-Object {
        $_.PSIsContainer -and ($excludedDirectoryNames -contains $_.Name)
    } | Sort-Object { $_.FullName.Length } -Descending)
    foreach ($excludedDirectory in $excludedDirectories) {
        if (Test-Path -LiteralPath $excludedDirectory.FullName) {
            Remove-Item -LiteralPath $excludedDirectory.FullName -Recurse -Force
        }
    }
    foreach ($excludedFile in @(Get-ChildItem -LiteralPath $stagePath -Recurse -Force | Where-Object {
        -not $_.PSIsContainer -and (
            $_.Extension -in @('.pyc', '.pyo', '.tmp') -or
            $_.Name -in @('.coverage', 'coverage.xml', '.DS_Store', 'Thumbs.db')
        )
    })) {
        Remove-Item -LiteralPath $excludedFile.FullName -Force
    }

    foreach ($configName in @('session.settings.json', 'managed.json', 'managed-mcp.json')) {
        $configSource = Join-Path $SourceRoot (Join-Path 'config' $configName)
        if (Test-Path -LiteralPath $configSource -PathType Leaf) {
            $configContent = Get-Content -LiteralPath $configSource -Raw -Encoding UTF8
            $null = $configContent | ConvertFrom-Json
            $configDestination = Join-Path $stagePath (Join-Path 'payload\config' $configName)
            Write-CompanyAgentUtf8File -Path $configDestination -Content $configContent
        }
    }

    foreach ($docName in @('DEPLOYMENT.md', 'STATE_PRESERVATION.md', 'SKILL_PRIORITY.md', 'PROJECT_HARNESS.md', 'IMPLEMENTATION_REVIEW.md', 'CONTEXT_OPTIMIZATION.md', 'MCP_CONTRACTS.md', 'ADMIN_KNOWLEDGE_GUIDE.md', 'LEGACY_MACHINE_DEPLOYMENT.md', 'SELF_LEARNING.md', 'BUSINESS_PILOT_GUIDE.md', 'USER_GUIDE.md', 'Company-Agent-사용자-안내서.html', 'VALIDATION_CHAT_SET.md', 'VALIDATION_RESULTS_TEMPLATE.md', 'Company-Agent-운영-검증-채팅.html', 'UPDATE_1.3.2.md', 'LEAN_SKILL_INTEGRATION.md', 'VALIDATION_1.3.2.md', 'UPDATE_1.3.3.md', 'VALIDATION_1.3.3.md', 'SKILL_CATALOG.md', 'UPDATE_1.3.4.md', 'UPDATE_1.3.5.md', 'UPDATE_1.3.6.md', 'UPDATE_1.3.7.md', 'UPDATE_1.3.8.md', 'VALIDATION_1.3.8.md', 'UPDATE_1.3.9.md', 'VALIDATION_1.3.9.md', 'HTML_DESIGN_SELECTION.md', 'VALIDATION_1.3.7.md', 'Claude-Code-필수-사용법.html')) {
        $deploymentDoc = Join-Path $SourceRoot ('docs\' + $docName)
        if (Test-Path -LiteralPath $deploymentDoc -PathType Leaf) {
            New-CompanyAgentDirectory -Path (Join-Path $stagePath 'docs')
            Copy-Item -LiteralPath $deploymentDoc -Destination (Join-Path $stagePath ('docs\' + $docName)) -Force
        }
    }

    foreach ($docName in @('UPDATE_1.4.0.md','VALIDATION_1.4.0.md','UPDATE_1.4.1.md','VALIDATION_1.4.1.md','UPDATE_1.4.2.md','OFFICE_READ_TROUBLESHOOTING.md')) {
        Copy-Item -LiteralPath (Join-Path $SourceRoot ('docs\' + $docName)) -Destination (Join-Path $stagePath ('docs\' + $docName)) -Force
    }
    Copy-Item -LiteralPath $claudeInstallDoc -Destination (Join-Path $stagePath 'INSTALL_WITH_CLAUDE.md') -Force
    Copy-Item -LiteralPath $easyInstaller -Destination (Join-Path $stagePath 'Install-CompanyAgent.cmd') -Force

    if (-not $IncludeBundledPython) {
        Assert-CompanyAgentExternalBundleFiles -Root $stagePath
    }
    $runtimeMode = 'external'
    # PythonCommand selects the BUILD PC interpreter, not an employee path.
    $runtimeCommand = 'python'
    $runtimeDescription = 'Requires an existing Python 3.11 or later installation on the employee PC; this bundle does not install or download Python.'
    if ($IncludeBundledPython) {
        $runtimeMode = 'bundled'
        $runtimeCommand = 'payload/core/plugin/runtime/python/python.exe'
        $runtimeDescription = 'Contains the administrator-selected, hash-verified Python embeddable runtime and its license.'
    }
    $fileRecords = @(Get-CompanyAgentTreeRecords -Root $stagePath)
    $manifest = [pscustomobject][ordered]@{
        format           = 'company-agent-offline-bundle/v1'
        schemaVersion    = 1
        bundleVersion    = ($CoreVersion + '+' + $KnowledgeVersion)
        coreVersion      = $CoreVersion
        knowledgeVersion = $KnowledgeVersion
        createdAtUtc     = [DateTime]::UtcNow.ToString('o')
        runtime          = [pscustomobject][ordered]@{
            mode           = $runtimeMode
            minimumVersion = '3.11'
            command        = $runtimeCommand
            description    = $runtimeDescription
        }
        payload          = [pscustomobject][ordered]@{
            corePlugin        = 'payload/core/plugin'
            corporateKnowledge = 'payload/knowledge'
        }
        files            = $fileRecords
    }
    Write-CompanyAgentJsonAtomic -Path (Join-Path $stagePath 'bundle-manifest.json') -Value $manifest

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $OutputPath) {
        # Force may rebuild an identical payload, but must not manufacture the
        # same-version/different-content package rejected by scoped installation.
        $previousZip = [System.IO.Compression.ZipFile]::OpenRead($OutputPath)
        try {
            $previousEntry = $previousZip.GetEntry('bundle-manifest.json')
            if ($null -eq $previousEntry -or $previousEntry.Length -gt 4194304) { throw 'Existing bundle manifest is missing or too large. Preserve it and use a new version/output.' }
            $previousReader = New-Object IO.StreamReader($previousEntry.Open())
            try { $previousManifest = $previousReader.ReadToEnd() | ConvertFrom-Json }
            finally { $previousReader.Dispose() }
            if ([string]$previousManifest.coreVersion -ceq $CoreVersion) {
                $oldPayload = @($previousManifest.files | Where-Object { $_.path -like 'payload/*' } | Sort-Object path | ForEach-Object { "$($_.path)|$($_.sha256)|$($_.length)" }) -join "`n"
                $newPayload = @($manifest.files | Where-Object { $_.path -like 'payload/*' } | Sort-Object path | ForEach-Object { "$($_.path)|$($_.sha256)|$($_.length)" }) -join "`n"
                if ($oldPayload -cne $newPayload) { throw "CoreVersion $CoreVersion already has different payload contents in this output. Increase CoreVersion; -Force cannot replace a different same-version payload." }
            }
        }
        finally { $previousZip.Dispose() }
    }
    $temporaryZip = Join-Path $outputParent ((Split-Path -Leaf $OutputPath) + '.tmp.' + [guid]::NewGuid().ToString('N'))
    try {
        [System.IO.Compression.ZipFile]::CreateFromDirectory(
            $stagePath,
            $temporaryZip,
            [System.IO.Compression.CompressionLevel]::Optimal,
            $false
        )
        if (Test-Path -LiteralPath $OutputPath) {
            Remove-Item -LiteralPath $OutputPath -Force
        }
        Move-Item -LiteralPath $temporaryZip -Destination $OutputPath
    }
    finally {
        if (Test-Path -LiteralPath $temporaryZip) {
            Remove-Item -LiteralPath $temporaryZip -Force -ErrorAction SilentlyContinue
        }
    }

    [pscustomobject][ordered]@{
        status           = 'created'
        outputPath       = $OutputPath
        coreVersion      = $CoreVersion
        knowledgeVersion = $KnowledgeVersion
        fileCount        = $fileRecords.Count
        sha256           = (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
finally {
    if (Test-Path -LiteralPath $stagePath) {
        $stageFull = ConvertTo-CompanyAgentFullPath -Path $stagePath
        $tempPrefix = $temporaryBase.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
        if ($stageFull.StartsWith($tempPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path -Leaf $stageFull) -like 'CompanyAgent-Bundle-*') {
            Remove-Item -LiteralPath $stageFull -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
