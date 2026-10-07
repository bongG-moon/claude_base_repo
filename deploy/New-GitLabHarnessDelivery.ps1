[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $BundleZip,
    [Parameter(Mandatory = $true)][string] $OutputDirectory,
    [string] $ProjectUrl,
    [string] $SetupExe
)

# Maintainer-only preparation. No network, token, installation or update check.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
Add-Type -AssemblyName System.IO.Compression.FileSystem
$utf8 = New-Object Text.UTF8Encoding($false, $true)
$sourceZip = (Resolve-Path -LiteralPath $BundleZip).Path
$sourceHash = (Get-FileHash -LiteralPath $sourceZip -Algorithm SHA256).Hash.ToLowerInvariant()
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $outputRoot) { throw 'Output directory already exists. Choose a new delivery directory.' }

$project = ''
if ($ProjectUrl) {
    $uri = $null
    if (-not [Uri]::TryCreate($ProjectUrl, [UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or
        $ProjectUrl -match '[\x00-\x20\\<>"`]' -or $uri.AbsolutePath.Trim('/') -notmatch '^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$' -or
        $uri.AbsolutePath.Contains('/-/')) {
        throw 'ProjectUrl must be the HTTPS GitLab project page without credentials, query or fragment.'
    }
    $project = $uri.AbsoluteUri.TrimEnd('/')
}

function Read-DeliveryEntry {
    param([IO.Compression.ZipArchiveEntry] $Entry, [int64] $Limit)
    if ($Entry.Length -gt $Limit) { throw ('Bundle entry too large: ' + $Entry.FullName) }
    $inputStream = $Entry.Open()
    $memory = New-Object IO.MemoryStream
    try { $inputStream.CopyTo($memory); return ,$memory.ToArray() }
    finally { $inputStream.Dispose(); $memory.Dispose() }
}

$archive = [IO.Compression.ZipFile]::OpenRead($sourceZip)
$sha = [Security.Cryptography.SHA256]::Create()
try {
    $entries = @{}
    $total = [int64]0
    foreach ($entry in $archive.Entries) {
        $name = $entry.FullName.Replace('\', '/')
        if ($name -match '(^/|:|(^|/)\.\.(/|$))' -or $name -match '[\x00-\x1f]' -or
            $name -match '(^|/)\.(?:/|$)' -or $name.Contains('//')) {
            throw ('Unsafe bundle path: ' + $name)
        }
        # Unix symlink entry; never interpret it as a distributable file.
        if ((($entry.ExternalAttributes -shr 16) -band 61440) -eq 40960) { throw 'Bundle symlink is not supported.' }
        if (-not $entry.Name) { continue }
        if ($entries.ContainsKey($name)) { throw ('Duplicate bundle path: ' + $name) }
        $entries[$name] = $entry
        $total += $entry.Length
        if ($entries.Count -gt 5000 -or $total -gt 536870912) { throw 'Bundle size or file count exceeds the delivery limit.' }
    }
    if (-not $entries.ContainsKey('bundle-manifest.json')) { throw 'Employee bundle manifest missing. Do not use a Git source archive.' }
    $manifest = $utf8.GetString((Read-DeliveryEntry $entries['bundle-manifest.json'] 4194304)) | ConvertFrom-Json
    if ($manifest.format -ne 'company-agent-offline-bundle/v1' -or
        $manifest.coreVersion -notmatch '^\d+\.\d+\.\d+$' -or
        $manifest.knowledgeVersion -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') { throw 'Unsupported employee bundle version or format.' }
    $expected = @{}
    foreach ($record in $manifest.files) {
        $name = [string]$record.path
        if ($name.Contains('\') -or $expected.ContainsKey($name) -or -not $entries.ContainsKey($name) -or
            $name -eq 'bundle-manifest.json' -or [string]$record.sha256 -notmatch '^[a-fA-F0-9]{64}$') {
            throw ('Invalid bundle manifest entry: ' + $name)
        }
        $entry = $entries[$name]
        if ($entry.Length -ne [int64]$record.length) { throw ('Bundle length mismatch: ' + $name) }
        $stream = $entry.Open()
        try { $hash = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
        finally { $stream.Dispose() }
        if ($hash -cne ([string]$record.sha256).ToLowerInvariant()) { throw ('Bundle hash mismatch: ' + $name) }
        $expected[$name] = $true
    }
    if ($entries.Count -ne $expected.Count + 1) { throw 'Unlisted bundle files are not supported.' }
    foreach ($required in @('Install-CompanyAgent.cmd', 'deploy/Setup-CompanyAgent.ps1',
        'docs/Company-Agent-사용자-안내서.html', 'payload/core/plugin/resources/manuals/Company-Agent-사용자-안내서.html')) {
        if (-not $expected.ContainsKey($required)) { throw ('Required employee bundle file missing: ' + $required) }
    }
    $guide = Read-DeliveryEntry $entries['docs/Company-Agent-사용자-안내서.html'] 8388608
    $installedGuide = Read-DeliveryEntry $entries['payload/core/plugin/resources/manuals/Company-Agent-사용자-안내서.html'] 8388608
    $guideHash = [BitConverter]::ToString($sha.ComputeHash($guide)).Replace('-', '').ToLowerInvariant()
    $installedHash = [BitConverter]::ToString($sha.ComputeHash($installedGuide)).Replace('-', '').ToLowerInvariant()
    if ($guideHash -cne $installedHash) { throw 'Standalone and installed user guides differ.' }
    $version = [string]$manifest.coreVersion
    $knowledge = [string]$manifest.knowledgeVersion
}
finally { $sha.Dispose(); $archive.Dispose() }

$setupFile = $null
$setupHash = ''
if ($SetupExe) {
    $setupFile = (Resolve-Path -LiteralPath $SetupExe).Path
    if ([IO.Path]::GetExtension($setupFile) -ine '.exe' -or
        [Reflection.AssemblyName]::GetAssemblyName($setupFile).Version.ToString() -cne ($version + '.0')) {
        throw 'Setup EXE version does not match the employee bundle.'
    }
    $assembly = [Reflection.Assembly]::LoadFile($setupFile)
    $payloadStream = $assembly.GetManifestResourceStream('SetupPayload.zip')
    if ($null -eq $payloadStream) { throw 'Setup EXE does not contain the approved employee bundle.' }
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { $embeddedHash = [BitConverter]::ToString($algorithm.ComputeHash($payloadStream)).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $payloadStream.Dispose() }
    if ($embeddedHash -cne $sourceHash) { throw 'Setup EXE contains a different employee bundle; rebuild before publishing.' }
    $setupHash = (Get-FileHash -LiteralPath $setupFile -Algorithm SHA256).Hash.ToLowerInvariant()
}

$zipName = 'company-agent-' + $version + '-' + $knowledge + '.zip'
$guideName = 'Company-Agent-User-Guide.html'
$releaseUrl = if ($project) { $project + '/-/releases/v' + $version } else { '' }
$releaseLocation = if ($releaseUrl) { $releaseUrl } else { '담당자가 공유한 사내 GitLab의 Company Harness 배포 페이지' }
New-Item -ItemType Directory -Path $outputRoot -ErrorAction Stop | Out-Null
Copy-Item -LiteralPath $sourceZip -Destination (Join-Path $outputRoot $zipName) -ErrorAction Stop
$zipHash = (Get-FileHash -LiteralPath (Join-Path $outputRoot $zipName) -Algorithm SHA256).Hash.ToLowerInvariant()
if ($zipHash -cne $sourceHash) { throw 'Source bundle changed during delivery preparation. Do not publish this output.' }
[IO.File]::WriteAllBytes((Join-Path $outputRoot $guideName), $guide)
[IO.File]::WriteAllText((Join-Path $outputRoot ($zipName + '.sha256')), ($zipHash + '  ' + $zipName + "`n"), $utf8)
[IO.File]::WriteAllText((Join-Path $outputRoot ($guideName + '.sha256')), ($guideHash + '  ' + $guideName + "`n"), $utf8)
$employeeFiles = @($zipName, $guideName, ($zipName + '.sha256'), ($guideName + '.sha256'))
$installerName = $zipName
$installerHash = $zipHash
$installSteps = "1. 이 페이지에 첨부된 **$zipName**을 내려받습니다.`n2. 내려받은 ZIP을 **모두 압축 풀기**로 새 폴더에 풉니다.`n3. 폴더 안의 **Install-CompanyAgent.cmd**를 두 번 클릭합니다.`n4. 사용할 범위를 선택하고 설치 후 Claude Code를 다시 엽니다."
if ($setupFile) {
    $installerName = 'Company-Harness-Setup.exe'
    $installerHash = $setupHash
    Copy-Item -LiteralPath $setupFile -Destination (Join-Path $outputRoot $installerName)
    if ((Get-FileHash -LiteralPath (Join-Path $outputRoot $installerName) -Algorithm SHA256).Hash.ToLowerInvariant() -cne $setupHash) { throw 'Setup EXE changed while preparing delivery.' }
    [IO.File]::WriteAllText((Join-Path $outputRoot ($installerName + '.sha256')), ($setupHash + '  ' + $installerName + "`n"), $utf8)
    $employeeFiles = @($installerName, $guideName, ($installerName + '.sha256'), ($guideName + '.sha256'))
    $installSteps = "1. 이 페이지의 **Company-Harness-Setup.exe**를 내려받습니다.`n2. 내려받은 파일을 두 번 클릭합니다.`n3. 사용할 범위를 고르고 **설치하기**를 누릅니다.`n4. 완료되면 Claude Code를 닫았다 다시 엽니다."
}
$employeeList = ($employeeFiles | ForEach-Object { '   - ' + $_ }) -join "`n"

$notes = @"
# Company Harness $version

## 설치하기

$installSteps

기존 회사 하네스가 있으면 같은 범위로 업데이트합니다. 개인 기억·지식·스킬과 기존 모델·MCP 설정은 이어서 사용합니다.

처음 사용하는 분은 **$guideName**을 열어 시작하기부터 따라 해 보세요. 같은 안내서가 설치 ZIP에도 있습니다. 회사에서 준비한 Claude Code와 Python 3.11 이상이 필요합니다.

GitLab이 자동 제공하는 **Source code** 파일은 개발용 소스입니다. 직원 설치에는 위 이름의 설치 파일을 선택합니다.

## 담당자용 확인 값

- 설치 파일 SHA-256: $installerHash
- 안내서 SHA-256: $guideHash
- 회사 지식팩: $knowledge

<!-- 담당자: 아래에 GitLab 파일 삽입 기능으로 설치 파일, 안내서, 두 .sha256 파일을 첨부한 뒤 이 메모를 삭제하세요. -->
"@
[IO.File]::WriteAllText((Join-Path $outputRoot 'GitLab-Release.md'), $notes, $utf8)
$instructions = @"
# 사내 GitLab에 하네스 배포하기

이 폴더는 이미 만든 직원 설치 ZIP을 검증하여 준비한 자료입니다. EXE를 선택한 경우 동일한 ZIP이 EXE 안에 들어 있는지 확인했습니다. 기존 ZIP의 내용은 바꾸지 않았습니다. 이 도구는 게시 자료만 준비하며 실제 파일 업로드와 Release 게시는 아래 순서로 담당자가 진행합니다.

1. 사내 GitLab 프로젝트의 **Deploy → Releases**에서 **v$version** 배포 항목을 만듭니다. 해당 버전의 승인된 소스 태그를 선택합니다. 메뉴 이름은 사내 GitLab 버전에 따라 다를 수 있습니다.
2. **GitLab-Release.md**를 설명란에 붙여 넣습니다.
3. 설명란의 파일 삽입 기능으로 다음 **4개 파일**을 첨부합니다. GitLab이 만든 첨부 링크를 그대로 사용합니다.
$employeeList
4. 설명 끝의 담당자 메모를 지운 뒤 게시합니다. 기존 배포 항목이나 다른 버전의 첨부를 삭제하지 않습니다.
5. 일반 직원 계정으로 배포 페이지를 열고 **$installerName**을 실제로 내려받습니다. SHA-256이 위 설명의 값과 같은지 확인합니다. 프로젝트의 다운로드 권한과 첨부 용량 제한도 확인합니다.
6. 직원에게 아래 **배포 페이지 주소 하나**를 공유합니다. 게시 준비 도구·토큰·관리자 명령어를 전달할 필요는 없습니다.

배포 페이지: $releaseLocation

비공개 프로젝트는 직원의 사내 GitLab 로그인과 해당 프로젝트 읽기 권한을 사용합니다. 배포 URL이나 첨부 파일에 토큰을 넣지 않습니다. 이 도구는 프로젝트 공개 범위·권한을 변경하거나 서버에 접속하지 않습니다.

프로젝트에서 파일 첨부를 사용할 수 없는 경우 담당자가 승인한 Generic Package 저장소에 같은 파일을 올리고 Release에 링크를 연결합니다. 이 경우 브라우저의 실제 다운로드 인증을 직원 계정으로 먼저 확인합니다. 접속이 안 된다고 프로젝트를 공개하거나 토큰을 직원에게 배포하지 않습니다.

앱 실행 파일은 별도 배포합니다. Company Harness는 Claude Code에 기능을 추가하는 하네스이므로 설치 후 매번 이 설치 파일을 열 필요가 없습니다. 새 버전을 적용할 때만 담당자가 게시한 설치 파일을 다시 받습니다. 자동 업데이트는 추가하지 않았습니다. ZIP도 폴더에 있는 경우 EXE를 기본 직원용으로 게시하고 ZIP은 담당자 보관·대체 설치용으로 유지할 수 있습니다.
"@
[IO.File]::WriteAllText((Join-Path $outputRoot 'GitLab-배포안내.md'), $instructions, $utf8)
[pscustomobject][ordered]@{
    status = 'prepared'
    coreVersion = $version
    knowledgeVersion = $knowledge
    outputDirectory = $outputRoot
    releaseUrl = $releaseUrl
    employeeFiles = $employeeFiles
    bundleFilesVerified = $expected.Count
    published = $false
    networkUsed = $false
    zipSha256 = $zipHash
    setupSha256 = $setupHash
} | ConvertTo-Json -Depth 3
