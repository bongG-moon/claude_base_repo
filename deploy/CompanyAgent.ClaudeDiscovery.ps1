# Claude executable discovery is independent of the user's configuration root.
# Do not walk other profiles, download software, or execute discovery candidates.
function Get-SetupClaudeCandidates {
    param([string] $PreferredCommand = 'claude', [string] $UserProfile,
        [string] $RoamingAppData = [Environment]::GetFolderPath('ApplicationData'))

    $paths = New-Object 'Collections.Generic.List[object]'
    $explicit = $PreferredCommand -notin @('', 'claude', 'claude.exe')
    if ($explicit) {
        $resolved = Resolve-SetupCommand -Command $PreferredCommand
        if ($resolved) { $paths.Add([pscustomobject]@{ path = $resolved; source = 'specified' }) }
    }
    else {
        foreach ($command in @(Get-Command 'claude' -CommandType Application -All -ErrorAction SilentlyContinue)) {
            if ($command.Source) { $paths.Add([pscustomobject]@{ path = $command.Source; source = 'PATH' }) }
        }
        if ($UserProfile) {
            $paths.Add([pscustomobject]@{ path = (Join-Path $UserProfile '.local\bin\claude.exe'); source = 'user native install' })
            $paths.Add([pscustomobject]@{ path = (Join-Path $UserProfile '.claude\local\node_modules\.bin\claude.cmd'); source = 'user legacy install' })
        }
        if ($RoamingAppData) {
            $paths.Add([pscustomobject]@{ path = (Join-Path $RoamingAppData 'npm\claude.cmd'); source = 'user npm install' })
        }
    }
    $seen = @{}
    foreach ($candidate in $paths) {
        $path = [string]$candidate.path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        $path = [IO.Path]::GetFullPath($path)
        if ([IO.Path]::GetExtension($path) -notin @('.exe', '.cmd', '.bat', '.ps1')) { continue }
        # WindowsApps may resolve to a Desktop app execution alias, not the CLI.
        if (-not $explicit -and $path -match '(?i)[\\/]Microsoft[\\/]WindowsApps[\\/]') { continue }
        if (-not $seen.ContainsKey($path)) {
            $seen[$path] = $true
            [pscustomobject]@{ path = $path; source = $candidate.source }
        }
    }
}

function Get-SetupClaudeForInstall {
    param([string] $PreferredCommand = 'claude', [string] $UserProfile,
        [switch] $NonInteractive, [switch] $DryRun)

    $candidates = @(Get-SetupClaudeCandidates -PreferredCommand $PreferredCommand -UserProfile $UserProfile)
    if ($candidates.Count -eq 1) {
        return [pscustomobject]@{ status = 'resolved'; path = $candidates[0].path; source = $candidates[0].source }
    }
    if ($NonInteractive -or $DryRun) {
        return [pscustomobject]@{
            status = 'input-required'; input = 'ClaudeCommand'; candidates = $candidates
            message = 'Choose your existing Claude Code executable with -ClaudeCommand. No installation or backup was performed.'
        }
    }
    Write-Host ''
    if ($candidates.Count -gt 1) { Write-Host 'Claude Code가 여러 곳에 있습니다. 평소 사용하는 항목을 선택해 주세요.' }
    else { Write-Host 'Claude Code 위치를 자동으로 찾지 못했습니다. 이미 설치된 실행 파일 경로를 입력해 주세요.' }
    for ($index = 0; $index -lt $candidates.Count; $index++) {
        Write-Host ('  {0}. {1} ({2})' -f ($index + 1), $candidates[$index].path, $candidates[$index].source)
    }
    Write-Host 'claude.exe 또는 회사에서 사용하는 Claude 실행 파일 경로를 붙여 넣을 수도 있습니다. 빈 입력은 취소입니다.'
    while ($true) {
        $answer = (Read-Host '번호 또는 Claude 실행 파일 경로').Trim().Trim('"')
        if (-not $answer) { throw 'Claude selection cancelled. No installation or backup was performed.' }
        $selection = 0
        if ([int]::TryParse($answer, [ref]$selection) -and $selection -ge 1 -and $selection -le $candidates.Count) {
            return [pscustomobject]@{ status = 'resolved'; path = $candidates[$selection - 1].path; source = 'user selection' }
        }
        # Typed input must be an explicit file, not an ambiguous command name.
        if ([IO.Path]::IsPathRooted($answer) -and (Test-Path -LiteralPath $answer -PathType Leaf)) {
            $chosen = @(Get-SetupClaudeCandidates -PreferredCommand $answer -UserProfile $UserProfile)
            if ($chosen.Count -eq 1) { return [pscustomobject]@{ status = 'resolved'; path = $chosen[0].path; source = 'user selection' } }
        }
        Write-Host '해당 실행 파일을 확인할 수 없습니다. 번호나 전체 파일 경로를 다시 입력해 주세요.'
    }
}
