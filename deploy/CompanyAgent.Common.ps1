Set-StrictMode -Version 2.0

function Get-CompanyAgentDefaultInstallRoot {
    $basePath = $env:ProgramFiles
    if ([string]::IsNullOrWhiteSpace($basePath)) {
        $basePath = 'C:\Program Files'
    }

    return (Join-Path $basePath 'CompanyAgent')
}

function Get-CompanyAgentDefaultDataRoot {
    $basePath = $env:ProgramData
    if ([string]::IsNullOrWhiteSpace($basePath)) {
        $basePath = 'C:\ProgramData'
    }

    return (Join-Path $basePath 'CompanyAgent')
}

function Get-CompanyAgentDefaultUserStateRoot {
    $basePath = $env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($basePath)) {
        $basePath = Join-Path $env:USERPROFILE 'AppData\Local'
    }

    return (Join-Path $basePath 'CompanyAgent')
}

function ConvertTo-CompanyAgentFullPath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw 'Path cannot be empty.'
    }

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }

    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
}

function Test-CompanyAgentAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-CompanyAgentAdministrator {
    param(
        [switch] $SkipAdminCheck
    )

    if ($SkipAdminCheck) {
        return
    }

    if (-not (Test-CompanyAgentAdministrator)) {
        throw 'This operation requires an elevated PowerShell session. For isolated tests only, use -SkipAdminCheck with non-system path overrides.'
    }
}

function Assert-CompanyAgentPrerequisites {
    param(
        [string] $ClaudeCommand = 'claude',
        [string] $PythonCommand = 'python',
        [switch] $SkipPrerequisiteCheck
    )

    if ($SkipPrerequisiteCheck) {
        return
    }

    $claude = Get-Command $ClaudeCommand -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $claude) {
        throw "Claude Code CLI was not found on PATH ('$ClaudeCommand'). Install the approved offline Claude Code package first."
    }

    $claudeExecutable = $claude.Source
    if ([string]::IsNullOrWhiteSpace($claudeExecutable)) {
        $claudeExecutable = $claude.Definition
    }
    $claudeVersionText = & $claudeExecutable --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not execute Claude Code prerequisite check: $claudeVersionText"
    }
    $claudeVersionMatch = [regex]::Match([string]($claudeVersionText | Select-Object -Last 1), '(?<![0-9])([0-9]+\.[0-9]+\.[0-9]+)')
    if (-not $claudeVersionMatch.Success) {
        throw "Could not parse Claude Code version: $claudeVersionText"
    }
    $claudeVersion = [version]$claudeVersionMatch.Groups[1].Value
    if ($claudeVersion -lt [version]'2.1.220') {
        throw "Claude Code 2.1.220 or newer is required. Found: $claudeVersion"
    }

    $python = Get-Command $PythonCommand -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $python) {
        throw "Python was not found on PATH ('$PythonCommand'). Company Agent requires Python 3.11 or newer."
    }

    $pythonExecutable = $python.Source
    if ([string]::IsNullOrWhiteSpace($pythonExecutable)) {
        $pythonExecutable = $python.Definition
    }
    $versionText = & $pythonExecutable -c "import sys; print('.'.join(str(v) for v in sys.version_info[:3]))" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not execute Python prerequisite check: $versionText"
    }
    try {
        $pythonVersion = [version]([string]($versionText | Select-Object -Last 1))
    }
    catch {
        throw "Could not parse Python version: $versionText"
    }
    if ($pythonVersion -lt [version]'3.11') {
        throw "Python 3.11 or newer is required. Found: $pythonVersion"
    }
}

function Assert-CompanyAgentVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Version,

        [Parameter(Mandatory = $true)]
        [string] $Name
    )

    if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$') {
        throw "$Name '$Version' is invalid. Use 1-64 letters, digits, dots, underscores, or hyphens."
    }
}

function New-CompanyAgentDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Write-CompanyAgentUtf8File {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string] $Content
    )

    $parentPath = Split-Path -Parent $Path
    New-CompanyAgentDirectory -Path $parentPath
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Write-CompanyAgentJsonAtomic {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [Parameter(Mandatory = $true)]
        [object] $Value
    )

    $parentPath = Split-Path -Parent $Path
    New-CompanyAgentDirectory -Path $parentPath
    $temporaryPath = Join-Path $parentPath ((Split-Path -Leaf $Path) + '.tmp.' + [guid]::NewGuid().ToString('N'))
    $json = $Value | ConvertTo-Json -Depth 20

    try {
        Write-CompanyAgentUtf8File -Path $temporaryPath -Content ($json + [Environment]::NewLine)
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Read-CompanyAgentJson {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required JSON file was not found: $Path"
    }

    try {
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
    }
    catch {
        throw "Invalid JSON file '$Path': $($_.Exception.Message)"
    }
}

function Copy-CompanyAgentDirectoryContents {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Source,

        [Parameter(Mandatory = $true)]
        [string] $Destination
    )

    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Source directory was not found: $Source"
    }

    New-CompanyAgentDirectory -Path $Destination
    foreach ($item in @(Get-ChildItem -LiteralPath $Source -Force)) {
        Copy-Item -LiteralPath $item.FullName -Destination $Destination -Recurse -Force
    }
}

function Get-CompanyAgentTreeRecords {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Root
    )

    $fullRoot = (ConvertTo-CompanyAgentFullPath -Path $Root).TrimEnd([char[]]@('\', '/'))
    if (-not (Test-Path -LiteralPath $fullRoot -PathType Container)) {
        throw "Directory was not found: $fullRoot"
    }

    $records = @()
    foreach ($file in @(Get-ChildItem -LiteralPath $fullRoot -Recurse -Force | Where-Object { -not $_.PSIsContainer })) {
        $relativePath = $file.FullName.Substring($fullRoot.Length).TrimStart([char[]]@('\', '/')).Replace('\', '/')
        $records += [pscustomobject][ordered]@{
            path   = $relativePath
            length = [int64]$file.Length
            sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }

    return @($records | Sort-Object path)
}

function Test-CompanyAgentDirectoryEquivalent {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Left,

        [Parameter(Mandatory = $true)]
        [string] $Right
    )

    $leftRecords = @(Get-CompanyAgentTreeRecords -Root $Left)
    $rightRecords = @(Get-CompanyAgentTreeRecords -Root $Right)
    if ($leftRecords.Count -ne $rightRecords.Count) {
        return $false
    }

    for ($index = 0; $index -lt $leftRecords.Count; $index++) {
        if ($leftRecords[$index].path -cne $rightRecords[$index].path -or
            $leftRecords[$index].length -ne $rightRecords[$index].length -or
            $leftRecords[$index].sha256 -ne $rightRecords[$index].sha256) {
            return $false
        }
    }

    return $true
}

function Install-CompanyAgentImmutableDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Source,

        [Parameter(Mandatory = $true)]
        [string] $Destination
    )

    if (Test-Path -LiteralPath $Destination -PathType Container) {
        if (Test-CompanyAgentDirectoryEquivalent -Left $Source -Right $Destination) {
            return $Destination
        }

        throw "Immutable version directory already exists with different content: $Destination. Publish a new version instead of overwriting it."
    }

    $parentPath = Split-Path -Parent $Destination
    New-CompanyAgentDirectory -Path $parentPath
    $stagePath = Join-Path $parentPath ('.staging-' + [guid]::NewGuid().ToString('N'))

    try {
        Copy-CompanyAgentDirectoryContents -Source $Source -Destination $stagePath
        if (-not (Test-CompanyAgentDirectoryEquivalent -Left $Source -Right $stagePath)) {
            throw "Staged file verification failed for $Destination"
        }

        Move-Item -LiteralPath $stagePath -Destination $Destination
        return $Destination
    }
    finally {
        if (Test-Path -LiteralPath $stagePath) {
            Remove-Item -LiteralPath $stagePath -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Set-CompanyAgentManagedRootMarker {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Root
    )

    New-CompanyAgentDirectory -Path $Root
    $markerPath = Join-Path $Root '.company-agent-managed-root'
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        Write-CompanyAgentUtf8File -Path $markerPath -Content "CompanyAgentManagedRoot:v1`r`n"
    }
}

function Initialize-CompanyAgentManagedRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Root
    )

    $fullRoot = ConvertTo-CompanyAgentFullPath -Path $Root
    if (Test-Path -LiteralPath $fullRoot -PathType Container) {
        $markerPath = Join-Path $fullRoot '.company-agent-managed-root'
        if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
            $existingItems = @(Get-ChildItem -LiteralPath $fullRoot -Force)
            if ($existingItems.Count -gt 0) {
                throw "Target directory already contains unmanaged files: $fullRoot"
            }
        }
    }

    Set-CompanyAgentManagedRootMarker -Root $fullRoot
    return $fullRoot
}

function Assert-CompanyAgentManagedRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Root
    )

    $fullRoot = ConvertTo-CompanyAgentFullPath -Path $Root
    $rootOfDrive = [System.IO.Path]::GetPathRoot($fullRoot).TrimEnd([char[]]@('\', '/'))
    if ($fullRoot.TrimEnd([char[]]@('\', '/')) -ieq $rootOfDrive) {
        throw "Refusing to operate on a drive root: $fullRoot"
    }

    $forbidden = @(
        $env:USERPROFILE,
        $env:ProgramFiles,
        $env:ProgramData,
        $env:LOCALAPPDATA,
        $env:TEMP
    )
    foreach ($path in $forbidden) {
        if (-not [string]::IsNullOrWhiteSpace($path)) {
            $fullForbidden = (ConvertTo-CompanyAgentFullPath -Path $path).TrimEnd([char[]]@('\', '/'))
            if ($fullRoot.TrimEnd([char[]]@('\', '/')) -ieq $fullForbidden) {
                throw "Refusing to operate on broad system path: $fullRoot"
            }
        }
    }

    $markerPath = Join-Path $fullRoot '.company-agent-managed-root'
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        throw "Managed-root marker is missing; refusing destructive operation: $fullRoot"
    }

    $marker = (Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8).Trim()
    if ($marker -ne 'CompanyAgentManagedRoot:v1') {
        throw "Managed-root marker is invalid; refusing destructive operation: $fullRoot"
    }
}

function Set-CompanyAgentCorporateAcl {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [switch] $SkipAcl
    )

    if ($SkipAcl) {
        return
    }

    $icacls = Get-Command 'icacls.exe' -ErrorAction SilentlyContinue
    if ($null -eq $icacls) {
        throw 'icacls.exe was not found.'
    }

    $arguments = @(
        $Path,
        '/inheritance:r',
        '/grant:r',
        '*S-1-5-18:(OI)(CI)F',
        '*S-1-5-32-544:(OI)(CI)F',
        '*S-1-5-32-545:(OI)(CI)RX'
    )
    & $icacls.Source @arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to apply corporate read-only ACL to $Path (icacls exit $LASTEXITCODE)."
    }
}

function Set-CompanyAgentPersonalAcl {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [switch] $SkipAcl
    )

    if ($SkipAcl) {
        return
    }

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $userSid = $identity.User.Value
    $icacls = Get-Command 'icacls.exe' -ErrorAction SilentlyContinue
    if ($null -eq $icacls) {
        throw 'icacls.exe was not found.'
    }

    $arguments = @(
        $Path,
        '/inheritance:r',
        '/grant:r',
        '*S-1-5-18:(OI)(CI)F',
        '*S-1-5-32-544:(OI)(CI)F',
        ('*' + $userSid + ':(OI)(CI)F')
    )
    & $icacls.Source @arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to apply personal-state ACL to $Path (icacls exit $LASTEXITCODE)."
    }
}

function Get-CompanyAgentCurrentPointerPath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $DataRoot
    )

    return (Join-Path $DataRoot 'state\current.json')
}

function Get-CompanyAgentPreviousPointerPath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $DataRoot
    )

    return (Join-Path $DataRoot 'state\previous.json')
}

function Test-CompanyAgentBundleIntegrity {
    param(
        [Parameter(Mandatory = $true)]
        [string] $BundleRoot
    )

    $bundleRootFull = (ConvertTo-CompanyAgentFullPath -Path $BundleRoot).TrimEnd([char[]]@('\', '/'))
    $manifestPath = Join-Path $bundleRootFull 'bundle-manifest.json'
    $manifest = Read-CompanyAgentJson -Path $manifestPath
    if ($manifest.format -ne 'company-agent-offline-bundle/v1') {
        throw "Unsupported bundle format in $manifestPath"
    }

    $expected = @{}
    foreach ($record in @($manifest.files)) {
        $relativePath = [string]$record.path
        if ([string]::IsNullOrWhiteSpace($relativePath) -or [System.IO.Path]::IsPathRooted($relativePath) -or $relativePath -match '(^|/)\.\.(/|$)') {
            throw "Unsafe path in bundle manifest: $relativePath"
        }

        $candidate = ConvertTo-CompanyAgentFullPath -Path (Join-Path $bundleRootFull ($relativePath.Replace('/', '\')))
        $prefix = $bundleRootFull + [System.IO.Path]::DirectorySeparatorChar
        if (-not $candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Bundle path escapes bundle root: $relativePath"
        }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "Bundle file is missing: $relativePath"
        }

        $actualHash = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne ([string]$record.sha256).ToLowerInvariant()) {
            throw "Bundle hash mismatch: $relativePath"
        }
        if ([int64](Get-Item -LiteralPath $candidate).Length -ne [int64]$record.length) {
            throw "Bundle length mismatch: $relativePath"
        }
        $expected[$relativePath.ToLowerInvariant()] = $true
    }

    foreach ($file in @(Get-ChildItem -LiteralPath $bundleRootFull -Recurse -Force | Where-Object { -not $_.PSIsContainer })) {
        $relativePath = $file.FullName.Substring($bundleRootFull.Length).TrimStart([char[]]@('\', '/')).Replace('\', '/')
        if ($relativePath -ieq 'bundle-manifest.json') {
            continue
        }
        if (-not $expected.ContainsKey($relativePath.ToLowerInvariant())) {
            throw "Unlisted file found in bundle: $relativePath"
        }
    }

    return $manifest
}

function Test-CompanyAgentSelectionEqual {
    param(
        [object] $Left,
        [object] $Right
    )

    if ($null -eq $Left -or $null -eq $Right) {
        return $false
    }

    $leftNormalized = [ordered]@{
        coreVersion      = [string]$Left.coreVersion
        knowledgeVersion = [string]$Left.knowledgeVersion
        small             = [string]$Left.modelMap.SMALL
        medium            = [string]$Left.modelMap.MEDIUM
        large             = [string]$Left.modelMap.LARGE
        defaultTier       = [string]$Left.routing.defaultTier
    }
    $rightNormalized = [ordered]@{
        coreVersion      = [string]$Right.coreVersion
        knowledgeVersion = [string]$Right.knowledgeVersion
        small             = [string]$Right.modelMap.SMALL
        medium            = [string]$Right.modelMap.MEDIUM
        large             = [string]$Right.modelMap.LARGE
        defaultTier       = [string]$Right.routing.defaultTier
    }

    return (($leftNormalized | ConvertTo-Json -Compress) -ceq ($rightNormalized | ConvertTo-Json -Compress))
}
