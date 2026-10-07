param(
    [Parameter(Mandatory=$true)][string] $BundleRoot,
    [Parameter(Mandatory=$true)][string] $RequestFile,
    [Parameter(Mandatory=$true)][string] $ResultFile
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$utf8 = New-Object Text.UTF8Encoding($false)
try {
    $request = [IO.File]::ReadAllText($RequestFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($request.Scope -notin @('User', 'Project')) { throw 'Invalid installation scope.' }
    # Only user-facing parameters. No protection/prerequisite bypass switches.
    $parameters = @{ BundleRoot = $BundleRoot; Scope = [string]$request.Scope; NonInteractive = $true }
    foreach ($name in @('ProjectRoot', 'ClaudeCommand', 'PythonCommand', 'ExistingHarnessAction', 'SkillConflictAction')) {
        if ($request.PSObject.Properties[$name] -and [string]$request.$name) {
            $parameters[$name] = [string]$request.$name
        }
    }
    if ($parameters.ContainsKey('ExistingHarnessAction') -and $parameters.ExistingHarnessAction -notin @('Ask','Keep','Update','Replace')) { throw 'Invalid existing installation choice.' }
    if ($parameters.ContainsKey('SkillConflictAction') -and $parameters.SkillConflictAction -notin @('Ask','KeepCurrent','PreferIncoming')) { throw 'Invalid skill preference choice.' }
    $result = & (Join-Path $BundleRoot 'deploy/Setup-CompanyAgent.ps1') @parameters
    $objects = @($result | Where-Object { $_.PSObject.Properties['status'] })
    if ($objects.Count -ne 1) { throw 'Installer did not return a single completion result.' }
    $result = $objects[0]
    if ([string]$result.status -notin @('installed','updated','reapplied','kept','cancelled','input-required')) { throw 'Installer completion status is unrecognized.' }
}
catch {
    $detail = [string]$_.Exception.Message
    $code = 'setup_failed'
    $message = '설치를 완료하지 못했습니다. 자세한 내용을 확인해 주세요.'
    if ($detail -match 'Python 3\.11\+ was not found|approved Python installation was not found') {
        $code = 'python_required'
        $message = '회사에서 준비한 Python 실행 파일을 선택해 주세요.'
    }
    $result = [pscustomobject]@{ status = 'failed'; code = $code; message = $message; detail = $detail }
}
[IO.File]::WriteAllText($ResultFile, ($result | ConvertTo-Json -Depth 30), $utf8)
if ($result.status -eq 'failed') { exit 1 }
