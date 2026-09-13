[CmdletBinding()]
param([ValidateSet('Menu', 'Check', 'Install', 'Start')][string] $Action = 'Menu')

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$labRoot = $PSScriptRoot
$workspace = Join-Path $labRoot 'workspace'
$stateRoot = Join-Path $labRoot 'personal-state'
$package = Join-Path $labRoot 'installer\package'
$pythonPath = $null
$claudePath = $null

function Resolve-LabPython {
    foreach ($name in @('python.exe', 'python3.exe', 'py.exe')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $command -or $command.Source -match '\\Microsoft\\WindowsApps\\') { continue }
        $probeArgs = @('-X', 'utf8', '-c', 'import sys; print(sys.executable); sys.exit(0 if sys.version_info >= (3,11) else 3)')
        if ($name -eq 'py.exe') { $probeArgs = @('-3') + $probeArgs }
        $output = @(& $command.Source @probeArgs 2>$null)
        if ($LASTEXITCODE -eq 0 -and $output.Count -gt 0 -and (Test-Path -LiteralPath ([string]$output[-1]) -PathType Leaf)) {
            return [string]$output[-1]
        }
    }
    if ($Action -ne 'Check') {
        Write-Host 'Python을 자동으로 찾지 못했습니다. 이미 설치된 회사 승인 Python 경로만 입력하세요. Enter는 취소입니다.'
        $candidate = (Read-Host 'Python 3.11 이상 python.exe 전체 경로').Trim().Trim('"')
        if ($candidate -and [IO.Path]::IsPathRooted($candidate) -and [IO.Path]::GetExtension($candidate) -ieq '.exe' -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $output = @(& $candidate -X utf8 -c 'import sys; print(sys.executable); sys.exit(0 if sys.version_info >= (3,11) else 3)' 2>$null)
            if ($LASTEXITCODE -eq 0 -and $output.Count -gt 0) { return [string]$output[-1] }
        }
    }
    throw 'Python 3.11 이상을 확인하지 못했습니다. 01_START_TEST.cmd를 실행해 승인된 Python 경로를 입력하거나 담당자에게 문의하세요. 자동 다운로드는 하지 않았습니다.'
}

function Get-LabCheck {
    $raw = & $script:pythonPath -X utf8 -B (Join-Path $labRoot 'lab.py') --root $labRoot --json
    if ($LASTEXITCODE -ne 0) { throw "연습 환경 검사 중단: $raw" }
    return ($raw | ConvertFrom-Json)
}

function Write-LabSummary {
    param([object] $Check)
    Write-Host ''
    Write-Host ('Python: ' + $Check.python)
    Write-Host ('설치파일: ' + $Check.package.message)
    Write-Host ('테스트 적용: ' + $Check.installation.message)
    Write-Host ('정리 대상의 원래 위치: ' + $(if ($Check.fixtures.originalLocations) { '모두 그대로입니다.' } else { '바뀐 위치가 있습니다. 이동 시험 후에는 정상일 수 있습니다.' }))
    Write-Host ('정리 대상의 내용과 개수: ' + $(if ($Check.fixtures.sameContentsAndCount) { '원본과 같습니다.' } else { '원본과 다릅니다. 추가/삭제/수정 여부를 확인하세요.' }))
    Write-Host ('보고서 등 입력 원본: ' + $(if (@($Check.fixtures.differentInputFiles).Count -eq 0) { '모두 보존되어 있습니다.' } else { '바뀐 입력 파일이 있습니다.' }))
    foreach ($name in @($Check.fixtures.differentOriginalPaths)) { Write-Host ('  원래 위치와 다름: ' + $name) }
    foreach ($name in @($Check.fixtures.differentInputFiles)) { Write-Host ('  입력 변경: ' + $name) }
    Write-Host '이 결과는 파일/설치 정보 점검입니다. 기억·학습·메일 기능의 통과 판정은 질문을 실행한 뒤 따로 기록하세요.'
}

function Resolve-LabClaude {
    # Use the existing installer's current-user discovery. No other profile scan.
    . (Join-Path $package 'deploy\CompanyAgent.Common.ps1')
    . (Join-Path $package 'deploy\CompanyAgent.ClaudeDiscovery.ps1')
    $selection = Get-SetupClaudeForInstall -PreferredCommand 'claude' -UserProfile ([Environment]::GetFolderPath('UserProfile'))
    if ($selection.status -ne 'resolved') { throw 'Claude 실행 파일을 선택하지 않았습니다.' }
    return $selection.path
}

function Install-Lab {
    $check = Get-LabCheck
    Write-Host '이번 연습 프로젝트에 Company Agent를 설치하고, 연습 기억은 personal-state 폴더에 보관합니다.'
    Write-Host '모델/MCP/기존 개인 자료는 유지합니다. 기존 플러그인 목록과 공통 배포 캐시는 설치 절차에 따라 갱신될 수 있습니다.'
    Write-Host '기존 회사 보안 정책과 상위 범위 규칙은 계속 적용됩니다. 보안 격리 프로그램을 설치하는 것은 아닙니다.'
    Write-Host '다른 Claude 창에서 진행 중인 업무는 먼저 마무리하세요. 설치를 원하지 않으면 Enter를 누르세요.'
    if ((Read-Host '이 테스트 프로젝트에 설치하려면 1').Trim() -ne '1') { return }
    if (-not $script:claudePath) { $script:claudePath = Resolve-LabClaude }
    # Keep installer validation, conflict questions, backups, account checks and approval intact.
    & (Join-Path $package 'deploy\Setup-CompanyAgent.ps1') -Scope Project -ProjectRoot $workspace `
        -BundleRoot $package -UserStateRoot $stateRoot -ClaudeCommand $script:claudePath -PythonCommand $script:pythonPath
    $after = Get-LabCheck
    if (-not $after.installation.ready) { throw $after.installation.message }
    Write-Host '프로젝트 설치 정보를 확인했습니다. 메뉴 3으로 새 Claude 대화를 여세요.' -ForegroundColor Green
}

function Start-LabClaude {
    $check = Get-LabCheck
    if (-not $check.installation.ready) {
        Write-Host $check.installation.message -ForegroundColor Yellow
        Install-Lab
        $check = Get-LabCheck
        if (-not $check.installation.ready) { Write-Host '설치가 완료되지 않아 Claude 실행을 중단했습니다. 기존 업무용 기억으로 대체하지 않았습니다.'; return }
    }
    if (-not $script:claudePath) { $script:claudePath = Resolve-LabClaude }
    Write-Host '질문 화면에서 T01의 요청만 복사해서 Claude에 붙여 넣으세요. 처음 프로젝트 신뢰 확인이 뜨면 직접 판단하세요.'
    Write-Host '이 창에서 /exit로 Claude를 끝내고 다시 메뉴 3을 고르면 같은 프로젝트의 새 대화를 시작합니다.'
    Start-Process -FilePath (Join-Path $labRoot '00_START_HERE.html')
    Push-Location -LiteralPath $workspace
    try { & $script:claudePath }
    finally { Pop-Location }
}

try {
    $script:pythonPath = Resolve-LabPython
    $check = Get-LabCheck
    if ($Action -eq 'Check') {
        Write-LabSummary -Check $check
        exit 0
    }
    if ($Action -eq 'Install') { Install-Lab; exit 0 }
    if ($Action -eq 'Start') { Start-LabClaude; exit 0 }
    Start-Process -FilePath (Join-Path $labRoot '00_START_HERE.html')
    while ($true) {
        Write-Host ''
        Write-Host 'Company Agent 연습실' -ForegroundColor Cyan
        Write-Host '1. 준비 상태와 파일 위치/내용 확인 (읽기 전용)'
        Write-Host '2. 이 테스트 프로젝트에 설치/다시 적용'
        Write-Host '3. 테스트 Claude 열기 (미설치 상태면 설치 안내)'
        Write-Host '4. 질문 화면 다시 열기'
        Write-Host '0. 종료'
        $choice = (Read-Host '처음에는 3을 선택하세요').Trim()
        switch ($choice) {
            '1' { $check = Get-LabCheck; Write-LabSummary -Check $check }
            '2' { Install-Lab }
            '3' { Start-LabClaude }
            '4' { Start-Process -FilePath (Join-Path $labRoot '00_START_HERE.html') }
            '0' { exit 0 }
            default { Write-Host '0~4 중 번호 하나를 입력하세요.' }
        }
    }
}
catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host '중단했습니다. 기존 설정 삭제, 권한 완화, 외부 다운로드로 해결하지 마세요. 이 화면을 알려주세요.'
    exit 1
}
