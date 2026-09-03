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
    [switch] $SkipAcl,
    [switch] $SkipSourceValidation,
    [switch] $Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.Common.ps1')

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
foreach ($requiredPath in @($pluginSource, $knowledgeSource, $deploySource)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Container)) {
        throw "Required source directory was not found: $requiredPath"
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
        $knowledgeValidation = & $pythonExecutable (Join-Path $pluginSource 'scripts\harness_cli.py') knowledge validate --base $knowledgeSource 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Corporate Knowledge validation failed:`r`n$($knowledgeValidation -join [Environment]::NewLine)"
        }
    }
    finally {
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', $previousDontWriteBytecode, 'Process')
    }

    $compileCache = Join-Path $env:TEMP ('CompanyAgent-Compile-' + [guid]::NewGuid().ToString('N'))
    $previousCachePrefix = [Environment]::GetEnvironmentVariable('PYTHONPYCACHEPREFIX', 'Process')
    try {
        [Environment]::SetEnvironmentVariable('PYTHONPYCACHEPREFIX', $compileCache, 'Process')
        $compileOutput = & $pythonExecutable -m compileall -q $pluginSource 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Python compile validation failed:`r`n$($compileOutput -join [Environment]::NewLine)"
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
    Copy-CompanyAgentDirectoryContents -Source $pluginSource -Destination (Join-Path $stagePath 'payload\core\plugin')
    Copy-CompanyAgentDirectoryContents -Source $knowledgeSource -Destination (Join-Path $stagePath 'payload\knowledge')
    Copy-CompanyAgentDirectoryContents -Source $deploySource -Destination (Join-Path $stagePath 'deploy')

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

    foreach ($configName in @('managed.settings.json', 'managed.json', 'managed-mcp.json')) {
        $configSource = Join-Path $SourceRoot (Join-Path 'config' $configName)
        if (Test-Path -LiteralPath $configSource -PathType Leaf) {
            $configContent = Get-Content -LiteralPath $configSource -Raw -Encoding UTF8
            $null = $configContent | ConvertFrom-Json
            $configDestination = Join-Path $stagePath (Join-Path 'payload\config' $configName)
            Write-CompanyAgentUtf8File -Path $configDestination -Content $configContent
        }
    }

    $deploymentDoc = Join-Path $SourceRoot 'docs\DEPLOYMENT.md'
    if (Test-Path -LiteralPath $deploymentDoc -PathType Leaf) {
        New-CompanyAgentDirectory -Path (Join-Path $stagePath 'docs')
        Copy-Item -LiteralPath $deploymentDoc -Destination (Join-Path $stagePath 'docs\DEPLOYMENT.md') -Force
    }

    $fileRecords = @(Get-CompanyAgentTreeRecords -Root $stagePath)
    $manifest = [pscustomobject][ordered]@{
        format           = 'company-agent-offline-bundle/v1'
        schemaVersion    = 1
        bundleVersion    = ($CoreVersion + '+' + $KnowledgeVersion)
        coreVersion      = $CoreVersion
        knowledgeVersion = $KnowledgeVersion
        createdAtUtc     = [DateTime]::UtcNow.ToString('o')
        payload          = [pscustomobject][ordered]@{
            corePlugin        = 'payload/core/plugin'
            corporateKnowledge = 'payload/knowledge'
        }
        files            = $fileRecords
    }
    Write-CompanyAgentJsonAtomic -Path (Join-Path $stagePath 'bundle-manifest.json') -Value $manifest

    Add-Type -AssemblyName System.IO.Compression.FileSystem
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
