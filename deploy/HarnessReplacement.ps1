# Windows PowerShell 5.1. Dot-source Setup-CompanyAgent.ps1 -FunctionsOnly first.
# Only the selected scope's instruction Markdown and top-level settings hooks are
# replaced. Snapshots are DPAPI CurrentUser encrypted, including Markdown.
Add-Type -AssemblyName System.Security

function Get-SetupHarnessHash {
    param([byte[]] $Bytes)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $hash.Dispose() }
}

function Get-SetupHarnessLocalPath {
    param([string] $Path, [string] $Name)
    if ([string]::IsNullOrWhiteSpace($Path) -or $Path -notmatch '^[A-Za-z]:[\\/]' -or $Path.Substring(2).Contains(':') -or $Path -match '(^|[\\/])\.\.?([\\/]|$)' -or $Path -match '[*?]') {
        throw "$Name must be an absolute local path without traversal, wildcards, or alternate streams."
    }
    $full = Get-SetupFullPath -Path $Path
    if ($full.TrimEnd([char[]]@('\', '/')) -ieq ([IO.Path]::GetPathRoot($full)).TrimEnd([char[]]@('\', '/'))) { throw "$Name cannot be a drive root." }
    $drive = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($full))
    if ($drive.DriveType -eq [IO.DriveType]::Network) { throw "$Name must be PC-local, not a mapped network drive." }
    Assert-SetupPathHasNoReparsePoint -Path $full -Name $Name
    return $full
}

function Assert-SetupHarnessTarget {
    param([object] $Plan, [string] $Path, [string] $Kind)
    $root = Get-SetupHarnessLocalPath -Path ([string]$Plan.scopeRoot) -Name 'Harness scope root'
    $config = Get-SetupHarnessLocalPath -Path ([string]$Plan.claudeConfigRoot) -Name 'Claude config root'
    $target = Get-SetupHarnessLocalPath -Path $Path -Name 'Harness replacement target'
    if ($Plan.scope -eq 'User') {
        if ($root -ine $config) { throw 'User replacement scope must equal the Claude config root.' }
        $ruleRoot = Join-Path $root 'rules'
        $instructions = @((Join-Path $root 'CLAUDE.md'), (Join-Path $root 'CLAUDE.local.md'))
        $settings = @((Join-Path $root 'settings.json'))
    }
    elseif ($Plan.scope -eq 'Project') {
        $project = Get-SetupHarnessLocalPath -Path ([string]$Plan.projectRoot) -Name 'Harness project root'
        if ($project -ine $root) { throw 'Project replacement scope must equal the project root.' }
        $localConfig = Join-Path $root '.claude'
        $ruleRoot = Join-Path $localConfig 'rules'
        $instructions = @((Join-Path $root 'CLAUDE.md'), (Join-Path $root 'CLAUDE.local.md'), (Join-Path $localConfig 'CLAUDE.md'), (Join-Path $localConfig 'CLAUDE.local.md'))
        $settings = @((Join-Path $localConfig 'settings.json'), (Join-Path $localConfig 'settings.local.json'))
    }
    else { throw 'Only User and Project harness replacement scopes are supported.' }
    $allowed = $false
    if ($Kind -eq 'instruction') {
        $allowed = $instructions -icontains $target
        if (-not $allowed -and [IO.Path]::GetExtension($target) -ieq '.md') { $allowed = (Test-SetupSameOrChildPath -Candidate $target -Parent $ruleRoot) -and $target -ine $ruleRoot }
    }
    elseif ($Kind -eq 'hooks') { $allowed = $settings -icontains $target }
    if (-not $allowed) { throw "Harness target is outside the selected replacement allowlist: $target" }
    return $target
}

function Read-SetupHarnessBytes {
    param([string] $Path, [long] $MaximumBytes = 8388608)
    Assert-SetupPathHasNoReparsePoint -Path $Path -Name 'Harness file'
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        if ($stream.Length -gt $MaximumBytes) { throw "Harness file exceeds the backup size limit: $Path" }
        $bytes = New-Object byte[] ([int]$stream.Length)
        $offset = 0
        while ($offset -lt $bytes.Length) {
            $count = $stream.Read($bytes, $offset, $bytes.Length - $offset)
            if ($count -eq 0) { throw 'Harness file changed while being read.' }
            $offset += $count
        }
        return ,$bytes
    }
    finally { $stream.Dispose() }
}

function Get-SetupHarnessFileAccessSddl {
    param([string] $Path)
    Assert-SetupPathHasNoReparsePoint -Path $Path -Name 'Harness access-control source'
    $security = [IO.File]::GetAccessControl($Path, [Security.AccessControl.AccessControlSections]::Access)
    return $security.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access)
}

function Get-SetupHarnessWriteSecurity {
    param([string] $Path, [string] $AccessSddl)
    $security = New-Object Security.AccessControl.FileSecurity
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        Assert-SetupPathHasNoReparsePoint -Path $Path -Name 'Harness access-control source'
        return [IO.File]::GetAccessControl($Path, [Security.AccessControl.AccessControlSections]::Access)
    }
    if (-not [string]::IsNullOrWhiteSpace($AccessSddl)) {
        try { $security.SetSecurityDescriptorSddlForm($AccessSddl, [Security.AccessControl.AccessControlSections]::Access) }
        catch { throw 'The protected harness backup contains invalid file access-control metadata.' }
        return $security
    }
    # New encrypted snapshots, metadata, and temporary files default to current
    # user + SYSTEM, not whichever access a surrounding directory might inherit.
    $security.SetAccessRuleProtection($true, $false)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ($null -eq $identity.User) { throw 'The Windows user SID could not be resolved for harness file protection.' }
    $system = New-Object Security.Principal.SecurityIdentifier([Security.Principal.WellKnownSidType]::LocalSystemSid, $null)
    foreach ($principal in @($identity.User, $system)) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($principal, [Security.AccessControl.FileSystemRights]::FullControl, [Security.AccessControl.AccessControlType]::Allow)
        $null = $security.AddAccessRule($rule)
    }
    return $security
}

function Write-SetupHarnessBytesAtomic {
    param([string] $Path, [byte[]] $Bytes, [string] $ExpectedHash, [switch] $AssertMissing, [string] $AccessSddl)
    Assert-SetupPathHasNoReparsePoint -Path $Path -Name 'Harness write target'
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw "Harness destination directory is missing: $parent" }
    $temporary = Join-Path $parent ('.company-agent-harness-' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $security = Get-SetupHarnessWriteSecurity -Path $Path -AccessSddl $AccessSddl
        # The DACL is passed to CreateFile by this .NET Framework constructor:
        # raw settings never exist briefly with a wider parent-inherited DACL.
        $stream = New-Object IO.FileStream($temporary, [IO.FileMode]::CreateNew, [Security.AccessControl.FileSystemRights]::Write, [IO.FileShare]::None, 4096, [IO.FileOptions]::None, $security)
        try { $stream.Write($Bytes, 0, $Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        Assert-SetupPathHasNoReparsePoint -Path $Path -Name 'Harness atomic replacement target'
        if ($AssertMissing -and (Test-Path -LiteralPath $Path)) { throw 'Restore conflict: a missing file was recreated before the atomic write.' }
        if ($PSBoundParameters.ContainsKey('ExpectedHash') -and (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or (Get-SetupHarnessHash -Bytes (Read-SetupHarnessBytes -Path $Path)) -cne $ExpectedHash)) { throw 'Harness write conflict: the destination changed before the atomic replacement.' }
        if (Test-Path -LiteralPath $Path -PathType Leaf) { [IO.File]::Replace($temporary, $Path, [NullString]::Value) }
        else { [IO.File]::Move($temporary, $Path) }
    }
    finally { if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) } }
}

function ConvertTo-SetupHarnessUtf8Bytes {
    param([string] $Text, [bool] $Bom = $false)
    $encoding = New-Object Text.UTF8Encoding($false, $true)
    [byte[]]$bytes = $encoding.GetBytes($Text)
    if ($Bom) { $bytes = [byte[]](@(239, 187, 191) + $bytes) }
    return ,$bytes
}

function Get-SetupHarnessJsonProperties {
    param([byte[]] $Bytes)
    try {
        $encoding = New-Object Text.UTF8Encoding($false, $true)
        $text = $encoding.GetString($Bytes)
        $bom = $text.Length -gt 0 -and [int]$text[0] -eq 65279
        if ($bom) { $text = $text.Substring(1) }
        $json = $text | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $json -or $json -isnot [pscustomobject]) { throw 'object required' }
    }
    catch { throw 'Harness settings must contain a valid UTF-8 JSON object; its contents were not logged.' }
    # Locate top-level properties lexically. Removing one property this way keeps
    # every other field, value, key casing, and number byte-for-byte unchanged.
    $properties = New-Object Collections.ArrayList
    $i = 0
    while ($i -lt $text.Length -and [char]::IsWhiteSpace($text[$i])) { $i++ }
    $open = $i
    $i++
    $previousComma = -1
    $keys = @{}
    while ($i -lt $text.Length) {
        while ([char]::IsWhiteSpace($text[$i])) { $i++ }
        if ($text[$i] -eq '}') { break }
        $start = $i
        if ($text[$i] -ne '"') { throw 'Harness settings property could not be safely isolated.' }
        $i++
        while ($i -lt $text.Length) {
            if ($text[$i] -eq '\') { $i += 2; continue }
            if ($text[$i] -eq '"') { $i++; break }
            $i++
        }
        $name = $text.Substring($start, $i - $start) | ConvertFrom-Json
        if ($keys.ContainsKey($name)) { throw 'Harness settings contain duplicate or case-colliding top-level keys.' }
        $keys[$name] = $true
        while ([char]::IsWhiteSpace($text[$i])) { $i++ }
        if ($text[$i] -ne ':') { throw 'Harness settings property could not be safely isolated.' }
        $i++
        $valueStart = $i
        $depth = 0
        $inString = $false
        while ($i -lt $text.Length) {
            $character = $text[$i]
            if ($inString) {
                if ($character -eq '\') { $i += 2; continue }
                if ($character -eq '"') { $inString = $false }
            }
            elseif ($character -eq '"') { $inString = $true }
            elseif ($character -eq '{' -or $character -eq '[') { $depth++ }
            elseif ($depth -eq 0 -and ($character -eq ',' -or $character -eq '}')) { break }
            elseif ($character -eq '}' -or $character -eq ']') { $depth-- }
            $i++
        }
        $delimiter = $i
        $null = $properties.Add([pscustomobject]@{ name = [string]$name; start = $start; end = $delimiter; valueStart = $valueStart; previousComma = $previousComma; followingComma = $(if ($text[$i] -eq ',') { $i } else { -1 }) })
        if ($text[$i] -eq '}') { break }
        $previousComma = $i
        $i++
    }
    return [pscustomobject]@{ text = $text; bom = $bom; properties = @($properties.ToArray()); close = $i; open = $open }
}

function Get-SetupHarnessHookProperty {
    param([object] $Document)
    $hooks = @($Document.properties | Where-Object { $_.name -ieq 'hooks' })
    if ($hooks.Count -gt 0 -and $hooks[0].name -cne 'hooks') { throw 'Harness settings use nonstandard Hooks key casing; resolve it before replacement.' }
    if ($hooks.Count -eq 0) { return $null }
    return $hooks[0]
}

function Get-SetupHarnessWithoutHooks {
    param([byte[]] $Bytes)
    $document = Get-SetupHarnessJsonProperties -Bytes $Bytes
    $hooks = Get-SetupHarnessHookProperty -Document $document
    if ($null -eq $hooks) { throw 'The selected hook settings no longer contain hooks; run detection again.' }
    $start = $hooks.start
    $end = $hooks.end
    if ($hooks.followingComma -ge 0) { $end = $hooks.followingComma + 1 }
    elseif ($hooks.previousComma -ge 0) { $start = $hooks.previousComma }
    $result = $document.text.Substring(0, $start) + $document.text.Substring($end)
    $bytesOut = ConvertTo-SetupHarnessUtf8Bytes -Text $result -Bom $document.bom
    $null = Get-SetupHarnessJsonProperties -Bytes $bytesOut
    return ,$bytesOut
}

function Get-SetupHarnessRestoredSettings {
    param([byte[]] $OriginalBytes, [byte[]] $CurrentBytes, [string] $AfterHash)
    if ((Get-SetupHarnessHash -Bytes $CurrentBytes) -ceq $AfterHash) { return ,$OriginalBytes }
    $original = Get-SetupHarnessJsonProperties -Bytes $OriginalBytes
    $current = Get-SetupHarnessJsonProperties -Bytes $CurrentBytes
    $originalHook = Get-SetupHarnessHookProperty -Document $original
    $currentHook = Get-SetupHarnessHookProperty -Document $current
    if ($null -eq $originalHook) { throw 'The protected original settings do not contain the expected hooks.' }
    if ($null -ne $currentHook) {
        $oldValue = $original.text.Substring($originalHook.valueStart, $originalHook.end - $originalHook.valueStart) | ConvertFrom-Json | ConvertTo-Json -Depth 100 -Compress
        $newValue = $current.text.Substring($currentHook.valueStart, $currentHook.end - $currentHook.valueStart) | ConvertFrom-Json | ConvertTo-Json -Depth 100 -Compress
        if ($oldValue -cne $newValue) { throw 'Restore conflict: new hooks exist. Preserve or reconcile them manually before restoring this backup.' }
        return ,$CurrentBytes
    }
    $propertyText = $original.text.Substring($originalHook.start, $originalHook.end - $originalHook.start)
    $separator = $(if (@($current.properties).Count -gt 0) { ',' } else { '' })
    $text = $current.text.Substring(0, $current.close) + $separator + $propertyText + $current.text.Substring($current.close)
    $result = ConvertTo-SetupHarnessUtf8Bytes -Text $text -Bom $current.bom
    $null = Get-SetupHarnessJsonProperties -Bytes $result
    return ,$result
}

function Get-SetupHarnessEntropy {
    param([string] $Identity)
    return ,([Text.Encoding]::UTF8.GetBytes('CompanyAgent.HarnessReplacement.v1|' + $Identity))
}

function Protect-SetupHarnessBytes {
    param([byte[]] $Bytes, [string] $Identity)
    return ,([Security.Cryptography.ProtectedData]::Protect($Bytes, (Get-SetupHarnessEntropy -Identity $Identity), [Security.Cryptography.DataProtectionScope]::CurrentUser))
}

function Unprotect-SetupHarnessBytes {
    param([byte[]] $Bytes, [string] $Identity)
    try { return ,([Security.Cryptography.ProtectedData]::Unprotect($Bytes, (Get-SetupHarnessEntropy -Identity $Identity), [Security.Cryptography.DataProtectionScope]::CurrentUser)) }
    catch { throw 'Protected harness backup could not be decrypted. Use the same Windows user on the same PC, and check backup integrity.' }
}

function Write-SetupHarnessJournal {
    param([object] $Transaction, [string] $Status, [int] $EntryIndex = -1)
    $value = [ordered]@{ schemaVersion = 1; transactionId = $Transaction.id; status = $Status; entryIndex = $EntryIndex; updatedAt = [DateTime]::UtcNow.ToString('o') }
    $bytes = ConvertTo-SetupHarnessUtf8Bytes -Text ($value | ConvertTo-Json -Depth 8)
    Write-SetupHarnessBytesAtomic -Path (Join-Path $Transaction.directory 'progress.json') -Bytes $bytes
    $Transaction.status = $Status
}

function New-SetupHarnessReplacementBackup {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string] $BackupPath, [Parameter(Mandatory = $true)][object] $Inventory)
    $backup = Get-SetupHarnessLocalPath -Path $BackupPath -Name 'Harness backup directory'
    if (-not (Test-Path -LiteralPath $backup -PathType Container)) { throw 'A completed, ACL-protected setup backup directory is required.' }
    $scopeRoot = Get-SetupHarnessLocalPath -Path ([string]$Inventory.scopeRoot) -Name 'Harness scope root'
    if (Test-SetupSameOrChildPath -Candidate $backup -Parent $scopeRoot) { throw 'Harness replacement backup must be outside the selected source scope.' }
    $directory = Join-Path $backup 'previous-harness'
    if (Test-Path -LiteralPath $directory) { throw 'A previous-harness backup already exists here; choose a new backup directory.' }
    $plan = [pscustomobject][ordered]@{
        schemaVersion = 1; id = [guid]::NewGuid().ToString('N'); scope = [string]$Inventory.scope
        scopeRoot = $scopeRoot; claudeConfigRoot = [string]$Inventory.claudeConfigRoot
        projectRoot = [string](Get-SetupPropertyValue -Object $Inventory -Name 'projectRoot')
        backupPath = $backup; createdAt = [DateTime]::UtcNow.ToString('o'); protection = 'DPAPI-CurrentUser'; entries = @()
    }
    $targets = New-Object Collections.ArrayList
    $seen = @{}
    foreach ($kind in @('instruction', 'hooks')) {
        $paths = $(if ($kind -eq 'instruction') { @($Inventory.replacementFiles) } else { @($Inventory.hookSettingsPaths) })
        foreach ($path in $paths) {
            $target = Assert-SetupHarnessTarget -Plan $plan -Path ([string]$path) -Kind $kind
            if ($seen.ContainsKey($target)) { throw 'Harness replacement inventory contains a duplicate target.' }
            $seen[$target] = $true
            if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw "Harness replacement source disappeared: $target" }
            if (((Get-Item -LiteralPath $target -Force).Attributes -band [IO.FileAttributes]::ReadOnly) -ne 0) { throw "Harness source is read-only; resolve its permissions before replacing: $target" }
            $null = $targets.Add([pscustomobject]@{ kind = $kind; path = $target })
            if ($targets.Count -gt 512) { throw 'Harness replacement exceeds the 512-file limit.' }
        }
    }
    $null = [IO.Directory]::CreateDirectory($directory)
    Protect-SetupBackupDirectory -Path $directory
    $entries = New-Object Collections.ArrayList
    [long]$total = 0
    foreach ($target in @($targets.ToArray())) {
        [byte[]]$original = Read-SetupHarnessBytes -Path $target.path
        $total += $original.Length
        if ($total -gt 33554432) { throw 'Harness replacement exceeds the 32 MiB total backup limit.' }
        $originalHash = Get-SetupHarnessHash -Bytes $original
        $number = $entries.Count
        $snapshot = ('{0:D4}-original.dpapi' -f $number)
        $identity = $plan.id + '|' + $target.path + '|' + $originalHash
        [byte[]]$encrypted = Protect-SetupHarnessBytes -Bytes $original -Identity $identity
        Write-SetupHarnessBytesAtomic -Path (Join-Path $directory $snapshot) -Bytes $encrypted
        $entry = [pscustomobject][ordered]@{
            kind = $target.kind; path = $target.path; originalHash = $originalHash; originalBytes = $original.Length
            snapshot = $snapshot; snapshotHash = (Get-SetupHarnessHash -Bytes $encrypted)
            originalLastWriteUtc = (Get-Item -LiteralPath $target.path -Force).LastWriteTimeUtc.ToString('o')
            originalAccessSddl = (Get-SetupHarnessFileAccessSddl -Path $target.path)
            afterHash = $null; afterSnapshot = $null; afterSnapshotHash = $null
        }
        if ($target.kind -eq 'hooks') {
            [byte[]]$after = Get-SetupHarnessWithoutHooks -Bytes $original
            $entry.afterHash = Get-SetupHarnessHash -Bytes $after
            $entry.afterSnapshot = ('{0:D4}-after.dpapi' -f $number)
            [byte[]]$afterEncrypted = Protect-SetupHarnessBytes -Bytes $after -Identity ($identity + '|after')
            $entry.afterSnapshotHash = Get-SetupHarnessHash -Bytes $afterEncrypted
            Write-SetupHarnessBytesAtomic -Path (Join-Path $directory $entry.afterSnapshot) -Bytes $afterEncrypted
        }
        $null = $entries.Add($entry)
    }
    $plan.entries = @($entries.ToArray())
    [byte[]]$planBytes = ConvertTo-SetupHarnessUtf8Bytes -Text ($plan | ConvertTo-Json -Depth 12)
    Write-SetupHarnessBytesAtomic -Path (Join-Path $directory 'manifest.json') -Bytes $planBytes
    # DPAPI-authenticated immutable plan prevents edited plaintext manifests from
    # redirecting restore paths or supplying forged hashes. Progress is advisory.
    [byte[]]$sealed = Protect-SetupHarnessBytes -Bytes $planBytes -Identity 'immutable-plan'
    Write-SetupHarnessBytesAtomic -Path (Join-Path $directory 'manifest.dpapi') -Bytes $sealed
    $transaction = Read-SetupHarnessReplacementTransaction -BackupPath $backup
    $null = Get-SetupHarnessVerifiedSnapshots -Transaction $transaction
    Write-SetupHarnessJournal -Transaction $transaction -Status 'prepared'
    return $transaction
}

function Read-SetupHarnessReplacementTransaction {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string] $BackupPath)
    $backup = Get-SetupHarnessLocalPath -Path $BackupPath -Name 'Harness backup directory'
    $directory = Join-Path $backup 'previous-harness'
    $sealed = Read-SetupHarnessBytes -Path (Join-Path $directory 'manifest.dpapi') -MaximumBytes 2097152
    $planBytes = Unprotect-SetupHarnessBytes -Bytes $sealed -Identity 'immutable-plan'
    $displayBytes = Read-SetupHarnessBytes -Path (Join-Path $directory 'manifest.json') -MaximumBytes 2097152
    if ((Get-SetupHarnessHash -Bytes $planBytes) -cne (Get-SetupHarnessHash -Bytes $displayBytes)) { throw 'Harness backup manifest integrity check failed.' }
    try { $plan = [Text.Encoding]::UTF8.GetString($planBytes) | ConvertFrom-Json -ErrorAction Stop }
    catch { throw 'Protected harness backup metadata is invalid.' }
    if ($plan.schemaVersion -ne 1 -or $plan.protection -cne 'DPAPI-CurrentUser' -or $plan.id -notmatch '^[a-f0-9]{32}$') { throw 'Unsupported harness replacement backup format.' }
    if ((Get-SetupHarnessLocalPath -Path $plan.backupPath -Name 'Recorded backup directory') -ine $backup) { throw 'The harness backup was moved. Restore it to its original local directory before recovery.' }
    if (Test-SetupSameOrChildPath -Candidate $backup -Parent $plan.scopeRoot) { throw 'Harness backup overlaps the protected source scope.' }
    if (@($plan.entries).Count -gt 512) { throw 'Harness backup target count exceeds its safety limit.' }
    $seen = @{}
    [long]$total = 0
    foreach ($entry in @($plan.entries)) {
        $null = Assert-SetupHarnessTarget -Plan $plan -Path $entry.path -Kind $entry.kind
        if ($seen.ContainsKey($entry.path)) { throw 'Harness backup contains duplicate target paths.' }
        $seen[$entry.path] = $true
        if ($entry.snapshot -notmatch '^\d{4}-original\.dpapi$' -or $entry.originalHash -notmatch '^[a-f0-9]{64}$' -or $entry.snapshotHash -notmatch '^[a-f0-9]{64}$' -or $entry.originalBytes -lt 0 -or $entry.originalBytes -gt 8388608) { throw 'Harness backup entry metadata is invalid.' }
        $accessSddl = [string](Get-SetupPropertyValue -Object $entry -Name 'originalAccessSddl')
        if ([string]::IsNullOrWhiteSpace($accessSddl) -or $accessSddl.Length -gt 16384) { throw 'Harness backup file access-control metadata is missing or exceeds its safety limit.' }
        try {
            $fileSecurity = New-Object Security.AccessControl.FileSecurity
            $fileSecurity.SetSecurityDescriptorSddlForm($accessSddl, [Security.AccessControl.AccessControlSections]::Access)
        }
        catch { throw 'The protected harness backup contains invalid file access-control metadata.' }
        if ($entry.kind -eq 'hooks' -and ($entry.afterSnapshot -notmatch '^\d{4}-after\.dpapi$' -or $entry.afterHash -notmatch '^[a-f0-9]{64}$' -or $entry.afterSnapshotHash -notmatch '^[a-f0-9]{64}$')) { throw 'Harness backup replacement metadata is invalid.' }
        $total += $entry.originalBytes
        if ($total -gt 33554432) { throw 'Harness backup total exceeds its safety limit.' }
    }
    $plan | Add-Member -MemberType NoteProperty -Name directory -Value $directory
    $plan | Add-Member -MemberType NoteProperty -Name status -Value 'loaded'
    return $plan
}

function Get-SetupHarnessVerifiedSnapshots {
    param([object] $Transaction)
    $result = New-Object Collections.ArrayList
    foreach ($entry in @($Transaction.entries)) {
        $identity = $Transaction.id + '|' + $entry.path + '|' + $entry.originalHash
        $encrypted = Read-SetupHarnessBytes -Path (Join-Path $Transaction.directory $entry.snapshot) -MaximumBytes 8454144
        if ((Get-SetupHarnessHash -Bytes $encrypted) -cne $entry.snapshotHash) { throw 'Harness snapshot integrity check failed. No source files were changed.' }
        [byte[]]$original = Unprotect-SetupHarnessBytes -Bytes $encrypted -Identity $identity
        if ($original.Length -ne $entry.originalBytes -or (Get-SetupHarnessHash -Bytes $original) -cne $entry.originalHash) { throw 'Decrypted harness snapshot integrity check failed.' }
        $after = $null
        if ($entry.kind -eq 'hooks') {
            $afterEncrypted = Read-SetupHarnessBytes -Path (Join-Path $Transaction.directory $entry.afterSnapshot) -MaximumBytes 8454144
            if ((Get-SetupHarnessHash -Bytes $afterEncrypted) -cne $entry.afterSnapshotHash) { throw 'Replacement settings snapshot integrity check failed.' }
            $after = Unprotect-SetupHarnessBytes -Bytes $afterEncrypted -Identity ($identity + '|after')
            if ((Get-SetupHarnessHash -Bytes $after) -cne $entry.afterHash) { throw 'Decrypted replacement settings integrity check failed.' }
        }
        $null = $result.Add([pscustomobject]@{ entry = $entry; original = $original; after = $after })
    }
    return ,$result.ToArray()
}

function Invoke-SetupHarnessReplacement {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][object] $Transaction)
    $current = Read-SetupHarnessReplacementTransaction -BackupPath $Transaction.backupPath
    $snapshots = Get-SetupHarnessVerifiedSnapshots -Transaction $current
    foreach ($snapshot in $snapshots) {
        $bytes = Read-SetupHarnessBytes -Path $snapshot.entry.path
        if ((Get-SetupHarnessHash -Bytes $bytes) -cne $snapshot.entry.originalHash) { throw "Harness changed after backup; no replacement started. Close Claude and retry: $($snapshot.entry.path)" }
    }
    Write-SetupHarnessJournal -Transaction $current -Status 'deactivating'
    for ($index = 0; $index -lt $snapshots.Count; $index++) {
        $snapshot = $snapshots[$index]
        $entry = $snapshot.entry
        Write-SetupHarnessJournal -Transaction $current -Status 'applying-entry' -EntryIndex $index
        $null = Assert-SetupHarnessTarget -Plan $current -Path $entry.path -Kind $entry.kind
        if ((Get-SetupHarnessHash -Bytes (Read-SetupHarnessBytes -Path $entry.path)) -cne $entry.originalHash) { throw "Harness changed during replacement. Restore the previous-harness backup: $($entry.path)" }
        if ($entry.kind -eq 'instruction') { [IO.File]::Delete($entry.path) }
        else { Write-SetupHarnessBytesAtomic -Path $entry.path -Bytes $snapshot.after -ExpectedHash $entry.originalHash }
        Write-SetupHarnessJournal -Transaction $current -Status 'entry-applied' -EntryIndex $index
    }
    Write-SetupHarnessJournal -Transaction $current -Status 'deactivated'
    $Transaction.status = 'deactivated'
}

function Restore-SetupHarnessReplacement {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][object] $Transaction, [switch] $DryRun)
    $current = Read-SetupHarnessReplacementTransaction -BackupPath $Transaction.backupPath
    $snapshots = Get-SetupHarnessVerifiedSnapshots -Transaction $current
    $writes = New-Object Collections.ArrayList
    # Preflight and stage ALL recovery bytes before changing any source. A new
    # rule or new hooks is a conflict, not permission to overwrite the user's work.
    foreach ($snapshot in $snapshots) {
        $entry = $snapshot.entry
        $null = Assert-SetupHarnessTarget -Plan $current -Path $entry.path -Kind $entry.kind
        $exists = Test-Path -LiteralPath $entry.path -PathType Leaf
        $beforeHash = $null
        $restore = $snapshot.original
        if ($exists) {
            $bytes = Read-SetupHarnessBytes -Path $entry.path
            $beforeHash = Get-SetupHarnessHash -Bytes $bytes
            if ($beforeHash -ceq $entry.originalHash) { continue }
            if ($entry.kind -eq 'instruction') { throw "Restore conflict: instruction file was edited or recreated. Move it aside before restoring: $($entry.path)" }
            $restore = Get-SetupHarnessRestoredSettings -OriginalBytes $snapshot.original -CurrentBytes $bytes -AfterHash $entry.afterHash
            if ((Get-SetupHarnessHash -Bytes $restore) -ceq $beforeHash) { continue }
        }
        elseif ($entry.kind -eq 'hooks' -or (Test-Path -LiteralPath $entry.path)) { throw "Restore conflict: the original settings path is missing or no longer a file: $($entry.path)" }
        if (-not (Test-Path -LiteralPath (Split-Path -Parent $entry.path) -PathType Container)) { throw "Restore destination directory is missing; restore the original directory layout first: $($entry.path)" }
        $null = $writes.Add([pscustomobject]@{ entry = $entry; bytes = $restore; beforeHash = $beforeHash })
    }
    if ($DryRun) {
        return [pscustomobject]@{ status = 'restore-ready'; dryRun = $true; scope = $current.scope; projectRoot = $current.projectRoot; claudeConfigRoot = $current.claudeConfigRoot; backupPath = $current.backupPath; filesToRestore = $writes.Count; totalTargets = @($current.entries).Count }
    }
    Write-SetupHarnessJournal -Transaction $current -Status 'restoring'
    for ($index = 0; $index -lt $writes.Count; $index++) {
        $write = $writes[$index]
        Write-SetupHarnessJournal -Transaction $current -Status 'restoring-entry' -EntryIndex $index
        $null = Assert-SetupHarnessTarget -Plan $current -Path $write.entry.path -Kind $write.entry.kind
        if ($null -eq $write.beforeHash) {
            if (Test-Path -LiteralPath $write.entry.path) { throw 'Restore conflict: a missing file was recreated during recovery.' }
        }
        elseif (-not (Test-Path -LiteralPath $write.entry.path -PathType Leaf) -or (Get-SetupHarnessHash -Bytes (Read-SetupHarnessBytes -Path $write.entry.path)) -cne $write.beforeHash) { throw 'Restore conflict: a file changed during recovery. Retry after closing Claude.' }
        if ($null -eq $write.beforeHash) { Write-SetupHarnessBytesAtomic -Path $write.entry.path -Bytes $write.bytes -AssertMissing -AccessSddl $write.entry.originalAccessSddl }
        else { Write-SetupHarnessBytesAtomic -Path $write.entry.path -Bytes $write.bytes -ExpectedHash $write.beforeHash }
        if ((Get-SetupHarnessHash -Bytes $write.bytes) -ceq $write.entry.originalHash) { [IO.File]::SetLastWriteTimeUtc($write.entry.path, [DateTime]::Parse($write.entry.originalLastWriteUtc).ToUniversalTime()) }
    }
    Write-SetupHarnessJournal -Transaction $current -Status 'restored'
    $Transaction.status = 'restored'
}

function Complete-SetupHarnessReplacement {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][object] $Transaction)
    $current = Read-SetupHarnessReplacementTransaction -BackupPath $Transaction.backupPath
    foreach ($entry in @($current.entries)) {
        if ($entry.kind -eq 'instruction') {
            if (Test-Path -LiteralPath $entry.path) { throw "Replaced instructions reappeared during installation: $($entry.path)" }
        }
        else {
            $document = Get-SetupHarnessJsonProperties -Bytes (Read-SetupHarnessBytes -Path $entry.path)
            if ($null -ne (Get-SetupHarnessHookProperty -Document $document)) { throw "Custom hooks reappeared during installation: $($entry.path)" }
        }
    }
    Write-SetupHarnessJournal -Transaction $current -Status 'completed'
    $Transaction.status = 'completed'
}
