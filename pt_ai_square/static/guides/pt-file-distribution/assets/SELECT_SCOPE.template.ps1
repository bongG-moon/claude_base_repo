# 생성하는 설치 스크립트의 파일 복사/의존성 설치/설정 변경보다 먼저 사용하세요.
# 이 템플릿은 경로를 선택할 뿐 설치를 수행하지 않습니다.
param(
    [ValidateSet('project', 'user')][string]$Scope,
    [string]$ProjectDirectory = (Get-Location).Path
)
$ErrorActionPreference = 'Stop'
while (-not $Scope) {
    Write-Host '설치 범위: 1) 현재 디렉토리(프로젝트)  2) 전역(내 계정)  q) 취소'
    $choice = Read-Host '1 또는 2를 선택하세요. 기본값은 없습니다'
    switch ($choice) {
        '1' { $Scope = 'project' }
        '2' { $Scope = 'user' }
        'q' { throw '설치를 취소했습니다.' }
        default { Write-Host '설치 범위를 명시적으로 선택해 주세요.' }
    }
}
$InstallBase = if ($Scope -eq 'project') {
    (Resolve-Path -LiteralPath $ProjectDirectory -ErrorAction Stop).Path
} else { [Environment]::GetFolderPath('UserProfile') }
Write-Host "선택한 범위: $Scope / 기준 경로: $InstallBase"
# 이 아래에서 실제 호스트의 공식 설치 규칙에 맞는 대상 경로를 계산하세요.
# 지원하지 않는 범위면 명시적으로 중단하고 다른 범위로 자동 전환하지 마세요.
# 기존 설정을 병합하며 다른 도구/사용자 파일은 덮어쓰거나 지우지 마세요.
