[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'CompanyAgent.UserContext.ps1')

$script:assertions = 0
function Assert-UserContext {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "User context test failed: $Message" }
    $script:assertions++
}
function Assert-UserContextThrows {
    param([scriptblock] $Action, [string] $Expected)
    $caught = $null
    try { $null = & $Action } catch { $caught = $_.Exception.Message }
    Assert-UserContext -Condition ($null -ne $caught -and $caught.Contains($Expected)) -Message "expected $Expected, received $caught"
}
function New-UserContextFixture {
    return [pscustomobject]@{
        sid = 'S-1-5-21-111-222-333-1001'; accountName = 'CORP\employee'
        sessionId = 9; sessionSid = 'S-1-5-21-111-222-333-1001'; sessionAccountName = 'CORP\employee'
        isService = $false; isInteractive = $true; isAuthenticated = $true; isAdministrator = $false
        userProfile = 'C:\Users\employee'; localAppData = 'D:\Redirected\employee\Local'
        environmentUserProfile = 'C:\Users\employee'; environmentLocalAppData = 'D:\Redirected\employee\Local'
    }
}

# Keep native discovery available for a final read-only probe, then replace the
# observation boundary inside this script only. No production environment flag.
$nativeObservation = ${function:Get-SetupUserContextObservation}
try {
    function Get-SetupUserContextObservation { return $script:userContextFixture }
    $script:userContextFixture = New-UserContextFixture
    $normal = Resolve-SetupUserContext
    Assert-UserContext $normal.verified 'normal user is verified'
    Assert-UserContext (-not $normal.isAdministrator) 'normal user not marked admin'
    Assert-UserContext ($normal.sessionId -eq 9) 'use exact fixture session, not active console'
    Assert-UserContext ($normal.localAppData -ceq 'D:\Redirected\employee\Local') 'redirected LocalAppData retained'
    Assert-UserContext ($normal.sid -ceq $script:userContextFixture.sid) 'SID retained'
    Assert-UserContext ($normal.accountName -ceq 'CORP\employee') 'account retained'

    $script:userContextFixture.isAdministrator = $true
    $elevated = Resolve-SetupUserContext
    Assert-UserContext ($elevated.verified -and $elevated.isAdministrator) 'same-user elevated allowed'
    $explicit = Resolve-SetupUserContext -InvokingUserProfile 'c:\users\EMPLOYEE\' -InvokingLocalAppData 'D:/Redirected/employee/Local/'
    Assert-UserContext $explicit.verified 'case, separator and trailing slash normalization'
    Assert-UserContextThrows { Resolve-SetupUserContext -InvokingUserProfile 'C:\Users\other' } 'USER_CONTEXT_PATH_MISMATCH'
    Assert-UserContextThrows { Resolve-SetupUserContext -InvokingLocalAppData 'C:\Users\employee\AppData\Local' } 'USER_CONTEXT_PATH_MISMATCH'
    Assert-UserContextThrows { Resolve-SetupUserContext -InvokingUserProfile '.\employee' } 'USER_CONTEXT_INVALID_PATH'
    Assert-UserContextThrows { Resolve-SetupUserContext -InvokingUserProfile 'C:employee' } 'USER_CONTEXT_INVALID_PATH'
    Assert-UserContextThrows { Resolve-SetupUserContext -InvokingUserProfile '\\?\C:\Users\employee' } 'USER_CONTEXT_INVALID_PATH'
    Assert-UserContextThrows { Resolve-SetupUserContext -InvokingUserProfile 'C:\Users\employee \child' } 'USER_CONTEXT_INVALID_PATH'
    Assert-UserContextThrows { Resolve-SetupUserContext -InvokingUserProfile 'C:\Users\employee:stream' } 'USER_CONTEXT_INVALID_PATH'

    $script:userContextFixture.sessionSid = 'S-1-5-21-111-222-333-1002'
    Assert-UserContextThrows { Resolve-SetupUserContext } 'USER_CONTEXT_DIFFERENT_ACCOUNT'
    $script:userContextFixture = New-UserContextFixture
    $script:userContextFixture.sessionSid = ''
    Assert-UserContextThrows { Resolve-SetupUserContext } 'USER_CONTEXT_UNVERIFIED'
    $script:userContextFixture = New-UserContextFixture
    $script:userContextFixture.sessionAccountName = ''
    Assert-UserContextThrows { Resolve-SetupUserContext } 'USER_CONTEXT_UNVERIFIED'
    foreach ($serviceSid in @('S-1-5-18', 'S-1-5-19', 'S-1-5-20')) {
        $script:userContextFixture = New-UserContextFixture
        $script:userContextFixture.sid = $serviceSid
        Assert-UserContextThrows { Resolve-SetupUserContext } 'USER_CONTEXT_NONINTERACTIVE'
    }
    foreach ($flag in @('isService', 'isInteractive', 'isAuthenticated')) {
        $script:userContextFixture = New-UserContextFixture
        $script:userContextFixture.$flag = ($flag -eq 'isService')
        $expected = $(if ($flag -eq 'isAuthenticated') { 'USER_CONTEXT_UNVERIFIED' } else { 'USER_CONTEXT_NONINTERACTIVE' })
        Assert-UserContextThrows { Resolve-SetupUserContext } $expected
    }
    foreach ($badSession in @(0, -1)) {
        $script:userContextFixture = New-UserContextFixture
        $script:userContextFixture.sessionId = $badSession
        Assert-UserContextThrows { Resolve-SetupUserContext } 'USER_CONTEXT_NONINTERACTIVE'
    }
    foreach ($missing in @('sid', 'accountName', 'userProfile', 'localAppData')) {
        $script:userContextFixture = New-UserContextFixture
        $script:userContextFixture.$missing = ''
        $expected = $(if ($missing -in @('sid', 'accountName')) { 'USER_CONTEXT_UNVERIFIED' } else { 'USER_CONTEXT_INVALID_PATH' })
        Assert-UserContextThrows { Resolve-SetupUserContext } $expected
    }
    foreach ($mismatch in @('environmentUserProfile', 'environmentLocalAppData')) {
        $script:userContextFixture = New-UserContextFixture
        $script:userContextFixture.$mismatch = 'C:\Users\other'
        Assert-UserContextThrows { Resolve-SetupUserContext } 'USER_CONTEXT_PATH_MISMATCH'
    }
    $script:userContextFixture = New-UserContextFixture
    $script:userContextFixture.environmentUserProfile = ''
    $script:userContextFixture.environmentLocalAppData = ''
    Assert-UserContext (Resolve-SetupUserContext).verified 'missing environment roots use authoritative Windows paths'
    $script:userContextFixture.userProfile = '\\server\profiles\employee'
    $networkProfile = Resolve-SetupUserContext -InvokingUserProfile '\\server\profiles\employee\'
    Assert-UserContext ($networkProfile.userProfile -ceq '\\server\profiles\employee') 'authoritative redirected profile retained'

    function Get-SetupUserContextObservation { throw 'Simulated WTS query failure' }
    Assert-UserContextThrows { Resolve-SetupUserContext } 'USER_CONTEXT_UNVERIFIED'
    $fixtureContext = Resolve-SetupUserContext -SkipAdminCheck -InvokingUserProfile 'C:\fixture\profile' -InvokingLocalAppData 'C:\fixture\local'
    Assert-UserContext (-not $fixtureContext.verified) 'explicit test escape never claims identity verification'
    Assert-UserContext ($fixtureContext.userProfile -ceq 'C:\fixture\profile' -and $fixtureContext.localAppData -ceq 'C:\fixture\local') 'explicit fixture roots preserved without native discovery'
}
finally { Set-Item -LiteralPath Function:Get-SetupUserContextObservation -Value $nativeObservation }

$nativeProfileRoots = ${function:Get-SetupRegisteredUserProfileRoots}
$nativeCanonicalPath = ${function:ConvertTo-SetupUserContextCanonicalPath}
try {
    function ConvertTo-SetupUserContextCanonicalPath {
        param([string] $Path)
        $normalized = ConvertTo-SetupUserContextPath -Path $Path -Name 'Fixture path'
        return $normalized -replace '(?i)C:\\Users\\OTHER~1(?=\\|$)', 'C:\Users\other'
    }
    function Get-SetupRegisteredUserProfileRoots {
        return @(
            [pscustomobject]@{ sid = 'S-1-5-21-111-222-333-1001'; path = 'C:\Users\employee' },
            [pscustomobject]@{ sid = 'S-1-5-21-111-222-333-1002'; path = 'C:\Users\other' },
            [pscustomobject]@{ sid = 'S-1-5-18'; path = 'C:\Windows\System32\config\systemprofile' },
            [pscustomobject]@{ sid = 'S-1-5-19'; path = 'C:\Windows\ServiceProfiles\LocalService' }
        )
    }
    $normalProfile = 'C:\Users\employee'
    $context = [pscustomobject]@{ verified = $true; sid = 'S-1-5-21-111-222-333-1001'; userProfile = $normalProfile }
    foreach ($allowed in @($normalProfile, ($normalProfile + '\.claude'), 'C:\Users\other-suffix\.claude', 'D:\SharedProjects\example')) {
        Assert-SetupUserProfileTarget -Path $allowed -Context $context
        Assert-UserContext $true ('allowed target ' + $allowed)
    }
    foreach ($forbidden in @('C:\Users\other', 'c:\users\OTHER\.claude', 'C:\Users\employee\..\other\.claude', 'C:\Users\OTHER~1\.claude',
        'C:\Windows\System32\config\systemprofile\.claude', 'C:\Windows\ServiceProfiles\LocalService\state')) {
        Assert-UserContextThrows { Assert-SetupUserProfileTarget -Path $forbidden -Context $context } 'USER_CONTEXT_FOREIGN_PROFILE'
    }
    function Get-SetupRegisteredUserProfileRoots { throw 'Simulated inaccessible registry' }
    Assert-UserContextThrows { Assert-SetupUserProfileTarget -Path 'D:\work' -Context $context } 'USER_CONTEXT_TARGET_UNVERIFIED'
    Assert-SetupUserProfileTarget -Path 'C:\fixture\state' -Context $fixtureContext
    Assert-UserContext $true 'explicit test context bypasses registry without claiming verification'
    function Get-SetupRegisteredUserProfileRoots { return @() }
    Assert-UserContextThrows { Assert-SetupUserProfileTarget -Path 'D:\work' -Context $context } 'USER_CONTEXT_TARGET_UNVERIFIED'

    function Get-SetupRegisteredUserProfileRoots {
        return @([pscustomobject]@{ sid = 'different-user'; path = 'C:\Users\OTHER~1' })
    }
    Assert-UserContextThrows { Assert-SetupUserProfileTarget -Path 'C:\Users\other\.claude' -Context $context } 'USER_CONTEXT_FOREIGN_PROFILE'
    function ConvertTo-SetupUserContextCanonicalPath { param([string] $Path) throw 'USER_CONTEXT_TARGET_UNVERIFIED: simulated denied ancestor' }
    Assert-UserContextThrows { Assert-SetupUserProfileTarget -Path 'C:\Users\other\.claude' -Context $context } 'USER_CONTEXT_TARGET_UNVERIFIED'

    function Get-SetupRegisteredUserProfileRoots { return @([pscustomobject]@{ sid = 'different-user'; path = 'C:\Users\other' }) }
    function ConvertTo-SetupUserContextCanonicalPath {
        param([string] $Path)
        if ($Path -ieq 'C:\Users\other') { throw 'USER_CONTEXT_TARGET_UNVERIFIED: matching profile ancestor denied' }
        return ConvertTo-SetupUserContextPath -Path $Path -Name 'Fixture path'
    }
    Assert-UserContextThrows { Assert-SetupUserProfileTarget -Path 'C:\Users\other\.claude' -Context $context } 'USER_CONTEXT_TARGET_UNVERIFIED'
    function Get-SetupRegisteredUserProfileRoots { return @([pscustomobject]@{ sid = 'S-1-5-18'; path = 'C:\Windows\System32\config\systemprofile' }) }
    $script:unrelatedDeepQueries = 0
    function ConvertTo-SetupUserContextCanonicalPath {
        param([string] $Path)
        if ($Path.StartsWith('C:\Windows\System32', [StringComparison]::OrdinalIgnoreCase)) {
            $script:unrelatedDeepQueries++
            throw 'USER_CONTEXT_TARGET_UNVERIFIED: unrelated protected service profile'
        }
        return ConvertTo-SetupUserContextPath -Path $Path -Name 'Fixture path'
    }
    Assert-SetupUserProfileTarget -Path 'C:\Users\employee\.claude' -Context $context
    Assert-UserContext ($script:unrelatedDeepQueries -eq 0) 'resolved nonmatching ancestor avoids unrelated protected-profile reads'
}
finally {
    Set-Item -LiteralPath Function:Get-SetupRegisteredUserProfileRoots -Value $nativeProfileRoots
    Set-Item -LiteralPath Function:ConvertTo-SetupUserContextCanonicalPath -Value $nativeCanonicalPath
}

# Native path spelling checks use only a uniquely owned temporary directory.
# Volumes may disable 8.3 generation: the same assertions still execute using
# the API-returned spelling, while deterministic alias fixtures above remain.
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
public static class CompanyAgentUserContextTestPaths {
    [DllImport("kernel32.dll", EntryPoint = "GetShortPathNameW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetShortPathName(string longPath, StringBuilder shortPath, uint characters);
    public static string ShortPath(string longPath) {
        StringBuilder result = new StringBuilder(32768);
        uint length = GetShortPathName(longPath, result, (uint)result.Capacity);
        if (length == 0 || length >= result.Capacity) throw new Win32Exception(Marshal.GetLastWin32Error());
        return result.ToString();
    }
}
'@
$pathTestBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$pathTestRoot = Join-Path $pathTestBase ('company-agent-path-context-' + [Guid]::NewGuid().ToString('N'))
$nativeShortAlias = $false
try {
    $null = New-Item -Path $pathTestRoot -ItemType Directory
    $foreignRoot = Join-Path $pathTestRoot 'Foreign Employee With A Long Name'
    $null = New-Item -Path $foreignRoot -ItemType Directory
    $shortRoot = [CompanyAgentUserContextTestPaths]::ShortPath($foreignRoot)
    $nativeShortAlias = -not [string]::Equals($shortRoot, $foreignRoot, [StringComparison]::OrdinalIgnoreCase)
    $canonicalRoot = ConvertTo-SetupUserContextCanonicalPath -Path $foreignRoot
    $aliasRoot = ConvertTo-SetupUserContextCanonicalPath -Path $shortRoot
    Assert-UserContext ($aliasRoot -ieq $canonicalRoot) 'native long/short directory spellings match'
    $missingAlias = Join-Path $shortRoot '.claude\new-state\nested'
    $canonicalMissing = ConvertTo-SetupUserContextCanonicalPath -Path $missingAlias
    Assert-UserContext ($canonicalMissing -ieq (Join-Path $canonicalRoot '.claude\new-state\nested')) 'native closest existing ancestor resolves missing suffix'
    function Get-SetupRegisteredUserProfileRoots { return @([pscustomobject]@{ sid = 'another-user'; path = $foreignRoot }) }
    Assert-UserContextThrows { Assert-SetupUserProfileTarget -Path $missingAlias -Context $context } 'USER_CONTEXT_FOREIGN_PROFILE'
    $tildeRoot = Join-Path $pathTestRoot 'legitimate~project'
    $null = New-Item -Path $tildeRoot -ItemType Directory
    Assert-UserContext ((ConvertTo-SetupUserContextCanonicalPath -Path $tildeRoot) -like '*\legitimate~project') 'legitimate tilde directory allowed'
}
finally {
    Set-Item -LiteralPath Function:Get-SetupRegisteredUserProfileRoots -Value $nativeProfileRoots
    $resolvedTestRoot = [IO.Path]::GetFullPath($pathTestRoot)
    if (-not $resolvedTestRoot.StartsWith($pathTestBase.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($resolvedTestRoot) -notmatch '^company-agent-path-context-[0-9a-f]{32}$') {
        throw 'Refusing cleanup outside the owned temporary path fixture.'
    }
    if (Test-Path -LiteralPath $resolvedTestRoot) { Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force }
}

# Probe APIs without installing, modifying environment, or writing to any user
# profile. A service-hosted test runner may correctly fail identity verification.
$native = Get-SetupUserContextObservation
Assert-UserContext (-not [string]::IsNullOrWhiteSpace($native.sid)) 'native token SID available'
Assert-UserContext ([IO.Path]::IsPathRooted($native.userProfile)) 'native token profile available'
Assert-UserContext ([IO.Path]::IsPathRooted($native.localAppData)) 'native known LocalAppData available'
$nativeResult = 'unverified'
try {
    $actual = Resolve-SetupUserContext
    Assert-UserContext $actual.verified 'actual session identity matched'
    Assert-SetupUserProfileTarget -Path (Join-Path $actual.userProfile '.claude') -Context $actual
    Assert-UserContext $true 'native registry check permits actual own profile without file access'
    $nativeResult = 'verified'
}
catch {
    if ($_.Exception.Message -notmatch '^USER_CONTEXT_(NONINTERACTIVE|UNVERIFIED|DIFFERENT_ACCOUNT|PATH_MISMATCH):') { throw }
    Write-Host ('Read-only native context probe correctly stopped: ' + ($_.Exception.Message -split ':', 2)[0])
}
[pscustomobject]@{ status = 'passed'; assertions = $script:assertions; nativeContext = $nativeResult; nativeShortAlias = $nativeShortAlias; profileWrites = 0 }
