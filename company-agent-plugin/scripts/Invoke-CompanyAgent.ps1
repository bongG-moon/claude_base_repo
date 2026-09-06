[CmdletBinding(PositionalBinding = $false)]
param(
    [ValidateSet('Hook', 'Cli')]
    [string] $Mode = 'Cli',
    [string] $Event,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $CliArguments
)

$ErrorActionPreference = 'Stop'
$pluginRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = $utf8
[Console]::OutputEncoding = $utf8
[Console]::InputEncoding = $utf8
$recordedPython = $null
$metadataPath = Join-Path $pluginRoot 'company-agent-install.json'
if (Test-Path -LiteralPath $metadataPath -PathType Leaf) {
    $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($null -ne $metadata.PSObject.Properties['pythonCommand']) { $recordedPython = [string]$metadata.pythonCommand }
}
# The installed release is retained independently of Claude's disposable plugin
# cache. Personal MCP entries therefore keep a durable interpreter location.
$candidates = @($recordedPython, (Join-Path $pluginRoot 'runtime\python\python.exe'), $env:COMPANY_AGENT_PYTHON, 'python', 'py')
$python = $null
$pythonPrefix = @()
foreach ($candidate in $candidates) {
    if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
    $info = Get-Command $candidate -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $info -or [IO.Path]::GetExtension($info.Source) -notin @('.exe', '')) { continue }
    $prefix = @()
    if ([IO.Path]::GetFileNameWithoutExtension($info.Source) -ieq 'py') { $prefix = @('-3') }
    $probe = & $info.Source @prefix -c 'import sys; print(sys.executable); sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace(($probe -join ''))) {
        $python = [string](@($probe)[-1]); break
    }
}
if ([string]::IsNullOrWhiteSpace($python)) {
    [Console]::Error.WriteLine('Company Agent runtime is missing. Run Install-CompanyAgent.cmd from the full offline package again.')
    exit 2
}
$env:COMPANY_AGENT_PYTHON = $python
$entry = Join-Path $PSScriptRoot 'native_entry.py'
if ($Mode -eq 'Hook') {
    # The only in-memory copy; never persist the input prompt/transcript payload.
    $payload = [Console]::In.ReadToEnd()
    $payload | & $python $entry --event $Event
} else {
    & $python $entry --cli @CliArguments
}
exit $LASTEXITCODE
