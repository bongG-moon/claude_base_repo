[CmdletBinding()]
param([string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repoRoot 'dist' }
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stage = Join-Path $repoRoot ('build\workspace-bundle-' + [Guid]::NewGuid().ToString('N'))
$payload = Join-Path $stage 'Company-Workspace'
New-Item -ItemType Directory -Path (Join-Path $payload 'local_app\web') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $payload 'deploy') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $payload 'docs') -Force | Out-Null
$files = @(
    'Company-Workspace.vbs',
    'deploy\Start-CompanyWorkspace.ps1',
    'docs\LOCAL_WORKSPACE.md',
    'docs\SKILL_PRIORITY.md', 'docs\AUDIT_HARNESS_2026-09-20.md',
    'docs\README.md', 'docs\CLAUDE_CODE_BASICS.md',
    'docs\COMPANY_AGENT_HANDBOOK.md', 'docs\ONBOARDING_COURSE.md',
    'docs\Company-Agent-Handbook.html', 'docs\Company-Agent-Onboarding.html',
    'docs\Company-Agent-Guide.html', 'docs\Company-Agent-사용자-안내서.html', 'docs\Claude-Code-필수-사용법.html',
    'docs\USER_GUIDE.md', 'docs\CLAUDE_CODE_COMMANDS.md', 'docs\UPDATE_1.4.19.md', 'docs\VALIDATION_UNIFIED_GUIDE_2026-09-19.md',
    'docs\VALIDATION_BEGINNER_WORKSPACE_2026-09-19.md',
    'docs\VALIDATION_AUDIT_FIXES_2026-09-19.md',
    'docs\UPDATE_1.4.16.md', 'docs\VALIDATION_RESOURCE_SCOPES_2026-09-19.md',
    'docs\VALIDATION_HARNESS_MAP_2026-09-19.md',
    'local_app\__init__.py', 'local_app\bridge.py', 'local_app\server.py', 'local_app\demo.py',
    'local_app\companion.py', 'local_app\harness_client.py', 'local_app\history.py', 'local_app\html_preview.py',
    'company-agent-plugin\resources\onboarding-course.json',
    'local_app\Pick-Path.ps1', 'local_app\Invoke-TerminalClaude.ps1',
    'local_app\web\index.html', 'local_app\web\app.css', 'local_app\web\app.js', 'local_app\web\companion.js'
)
foreach ($relative in $files) {
    New-Item -ItemType Directory -Path (Split-Path (Join-Path $payload $relative) -Parent) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repoRoot $relative) -Destination (Join-Path $payload $relative)
}
$zip = Join-Path $outputRoot ('company-workspace-preview-0.7-' + $stamp + '.zip')
if (Test-Path -LiteralPath $zip) { throw 'Output already exists; refusing to overwrite.' }
Compress-Archive -LiteralPath $payload -DestinationPath $zip -CompressionLevel Optimal
Get-FileHash -LiteralPath $zip -Algorithm SHA256 | Select-Object Path, Hash
# Keep staging for verification; no broad recursive deletion.
