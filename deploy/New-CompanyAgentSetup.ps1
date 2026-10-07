[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string] $BundleZip,
    [string] $OutputDirectory
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$bundle = (Resolve-Path -LiteralPath $BundleZip).Path
$stage = Join-Path $repoRoot ('build\harness-setup-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
# Reuse the delivery check: verify every file and retain the exact approved ZIP.
$validation = & (Join-Path $PSScriptRoot 'New-GitLabHarnessDelivery.ps1') -BundleZip $bundle -OutputDirectory (Join-Path $stage 'validated')
$validation = $validation | ConvertFrom-Json
$version = [string]$validation.coreVersion
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repoRoot ('dist\harness-setup-' + $version) }
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $outputRoot) { throw 'Output directory already exists; use a new directory.' }
$utf8 = New-Object Text.UTF8Encoding($false)
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($bundle)
$sha = [Security.Cryptography.SHA256]::Create()
try {
    $rows = @(foreach ($entry in $archive.Entries) {
        if (-not $entry.Name) { continue }
        $stream = $entry.Open()
        try { $hash = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
        finally { $stream.Dispose() }
        $hash + "`t" + $entry.FullName.Replace('\', '/')
    })
} finally { $sha.Dispose(); $archive.Dispose() }
$payloadManifest = Join-Path $stage 'SetupPayload.manifest.tsv'
[IO.File]::WriteAllText($payloadManifest, (($rows -join "`n") + "`n"), $utf8)
$bridge = Join-Path $PSScriptRoot 'CompanyAgent.SetupBridge.ps1'
$bridgeHash = (Get-FileHash -LiteralPath $bridge -Algorithm SHA256).Hash.ToLowerInvariant()
$bundleHash = (Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()
if ($bundleHash -cne [string]$validation.zipSha256) { throw 'Approved bundle changed while building.' }
$buildInfo = Join-Path $stage 'SetupBuild.txt'
[IO.File]::WriteAllText($buildInfo, ($version + "`n" + $bundleHash + "`n" + $bridgeHash + "`n"), $utf8)
$assembly = Join-Path $stage 'Assembly.cs'
[IO.File]::WriteAllText($assembly, ('using System.Reflection; [assembly: AssemblyTitle("Company Harness Setup")] [assembly: AssemblyProduct("Company Harness")] [assembly: AssemblyVersion("' + $version + '.0")] [assembly: AssemblyFileVersion("' + $version + '.0")]'), $utf8)
$exe = Join-Path $stage 'Company-Harness-Setup.exe'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows .NET Framework x64 compiler required on the build PC.' }
$arguments = @('/nologo','/target:winexe','/platform:x64','/optimize+','/codepage:65001',('/out:' + $exe),
    '/reference:System.Core.dll','/reference:System.Drawing.dll','/reference:System.Windows.Forms.dll',
    '/reference:System.Web.Extensions.dll','/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll',
    ('/win32manifest:' + (Join-Path $PSScriptRoot 'CompanyAgent.Setup.manifest')),
    ('/resource:' + $bundle + ',SetupPayload.zip'),('/resource:' + $payloadManifest + ',SetupPayload.manifest.tsv'),
    ('/resource:' + $bridge + ',SetupBridge.ps1'),('/resource:' + $buildInfo + ',SetupBuild.txt'),
    (Join-Path $PSScriptRoot 'CompanyAgent.Setup.cs'), $assembly)
$compilerResult = & $compiler @arguments 2>&1
if ($LASTEXITCODE -ne 0) { throw ($compilerResult -join [Environment]::NewLine) }
# Exercise the real archive without installation. A deep source checkout can
# exceed the legacy Framework extraction limit when used as the cache root.
$verifyTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$verifyCache = [IO.Path]::GetFullPath((Join-Path $verifyTempRoot ('ca-v-' + [Guid]::NewGuid().ToString('N'))))
try {
    $verify = Start-Process -FilePath $exe -ArgumentList @('--verify-only','--cache-root',('"' + $verifyCache + '"')) -WindowStyle Hidden -PassThru -Wait
    if ($verify.ExitCode -ne 0) { throw ('Embedded installer verification failed: ' + $verify.ExitCode) }
}
finally {
    if (-not $verifyCache.StartsWith($verifyTempRoot, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($verifyCache) -notmatch '^ca-v-[0-9a-f]{32}$') {
        throw 'Refusing cleanup outside the owned verification cache.'
    }
    if (Test-Path -LiteralPath $verifyCache) { Remove-Item -LiteralPath $verifyCache -Recurse -Force }
}
New-Item -ItemType Directory -Path $outputRoot | Out-Null
$destination = Join-Path $outputRoot 'Company-Harness-Setup.exe'
Copy-Item -LiteralPath $exe -Destination $destination
$exeHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(($destination + '.sha256'), ($exeHash + "  Company-Harness-Setup.exe`n"), $utf8)
[pscustomobject][ordered]@{
    status='built'; coreVersion=$version; exe=$destination; sha256=$exeHash
    bundleSha256=$bundleHash; payloadFiles=$rows.Count; embeddedPayloadVerified=$true
    downloadsDependencies=$false; installsDependencies=$false; stage=$stage
} | ConvertTo-Json
