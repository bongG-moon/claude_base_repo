[CmdletBinding()]
param(
    [string] $BackupPath,
    [switch] $DryRun,
    [switch] $NonInteractive
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$restoreArguments = @{ BackupPath = $BackupPath; DryRun = $DryRun; NonInteractive = $NonInteractive }
. (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1') -FunctionsOnly
. (Join-Path $PSScriptRoot 'HarnessReplacement.ps1')
$BackupPath = $restoreArguments.BackupPath
$DryRun = $restoreArguments.DryRun
$NonInteractive = $restoreArguments.NonInteractive

if ([string]::IsNullOrWhiteSpace($BackupPath)) {
    if ($NonInteractive -or $DryRun) {
        return [pscustomobject]@{ status = 'input-required'; input = 'BackupPath'; message = 'Pass the exact pre-install backup folder printed by setup. No files were changed.' }
    }
    $BackupPath = (Read-Host '설치 시 출력된 pre-install 백업 폴더 경로를 입력하세요').Trim().Trim('"')
    if ([string]::IsNullOrWhiteSpace($BackupPath)) { throw 'A pre-install backup folder is required. No files were changed.' }
}

# Validation/decryption and conflict checks occur even for a preview. Only the
# same Windows identity can open this backup; no credential values are printed.
$transaction = Read-SetupHarnessReplacementTransaction -BackupPath $BackupPath
$preview = Restore-SetupHarnessReplacement -Transaction $transaction -DryRun
if ($DryRun) { return $preview }

Write-Host '백업에 있던 기존 규칙·Hook만 복원합니다. 현재 모델·MCP·일반 Skill·개인 Memory는 유지합니다.'
Write-Host '기존 하네스로 완전히 돌아가려면 먼저 같은 범위의 Company Agent를 적용 해제하세요.'
Write-Host '이 복원 명령 자체는 Company Agent를 제거하거나 다른 Plugin을 비활성화하지 않습니다.'
Write-Host "복원할 백업: $BackupPath"
if (-not $NonInteractive) {
    $choice = Read-Host 'Claude Code를 닫은 뒤 복원하려면 1, 취소하려면 Enter를 누르세요'
    if ($choice.Trim() -ne '1') { return [pscustomobject]@{ status = 'cancelled'; changed = $false } }
}
$null = Restore-SetupHarnessReplacement -Transaction $transaction
Write-Host '기존 규칙·Hook 복원이 완료되었습니다. Claude Code를 다시 열어 주세요.'
return [pscustomobject]@{
    status = 'restored'; scope = $transaction.scope; projectRoot = $transaction.projectRoot
    backupPath = $transaction.backupPath; totalTargets = @($transaction.entries).Count
    companyAgentUninstalled = $false
}
