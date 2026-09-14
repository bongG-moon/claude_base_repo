$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$taskCommands = @(Get-Command claude -All -ErrorAction SilentlyContinue | Where-Object { $_.CommandType -in @('Application','ExternalScript') })
$taskCandidates = @($taskCommands | ForEach-Object {
    [pscustomobject]@{ path = $_.Source; kind = [string]$_.CommandType }
})
$taskAlternatives = @()
if ($taskCandidates.Count -gt 0) {
    $taskSelected = $taskCandidates[0].path
    $taskDirectory = Split-Path -Parent $taskSelected
    foreach ($taskRelative in @('claude.cmd','node_modules\@anthropic-ai\claude-code\bin\claude.exe')) {
        $taskCandidate = Join-Path $taskDirectory $taskRelative
        if (Test-Path -LiteralPath $taskCandidate -PathType Leaf) {
            $taskFile = Get-Item -LiteralPath $taskCandidate
            if (-not ($taskFile.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                $taskAlternatives += [pscustomobject]@{ path = $taskFile.FullName; fileVersion = $taskFile.VersionInfo.FileVersion; executed = $false }
            }
        }
    }
}
[ordered]@{
    ok = $true
    status = 'diagnostic_only'
    powershellVersion = [string]$PSVersionTable.PSVersion
    hostScope = 'NoProfile diagnostic process; the interactive shell can have different aliases or functions'
    candidates = $taskCandidates
    sameInstallAlternatives = $taskAlternatives
    settingsChanged = $false
    claudeProcessesLaunched = $false
    message = 'Claude 경로만 확인했습니다. /exit와 Ctrl+C 종료를 비교해야 하며 종료 오류 원인은 아직 확정되지 않았습니다. 계정·모델·MCP·PATH는 변경하지 않았습니다.'
} | ConvertTo-Json -Depth 5
