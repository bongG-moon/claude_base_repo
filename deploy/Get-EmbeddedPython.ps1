[CmdletBinding()]
param([string] $OutputDirectory)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) 'build\runtime'
}
$version = '3.13.15'
$fileName = "python-$version-embed-amd64.zip"
$expectedHash = 'd1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf'
$uri = "https://www.python.org/ftp/python/$version/$fileName"
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$destination = Join-Path ([IO.Path]::GetFullPath($OutputDirectory)) $fileName
if (-not (Test-Path -LiteralPath $destination)) {
    Write-Host 'Build PC only: downloading the pinned official Python embeddable runtime.'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $uri -OutFile $destination -UseBasicParsing
}
$actualHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -cne $expectedHash) { throw 'Runtime SHA-256 mismatch. The file was left in place for investigation and must not be bundled.' }
[pscustomobject]@{ status = 'verified'; path = $destination; sha256 = $actualHash; source = $uri }
