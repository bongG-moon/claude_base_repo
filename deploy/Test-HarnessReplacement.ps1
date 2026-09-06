[CmdletBinding()]
param([switch] $KeepTestDirectory)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1') -FunctionsOnly
. (Join-Path $PSScriptRoot 'HarnessReplacement.ps1')

function Assert-HarnessReplacement {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "Harness replacement regression failed: $Message" }
}

function Assert-HarnessRejected {
    param([scriptblock] $Action, [string] $Pattern, [string] $Message)
    $rejected = $false
    try { $null = & $Action }
    catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw }
        $rejected = $true
    }
    Assert-HarnessReplacement $rejected $Message
}

function Get-HarnessEffectiveDacl {
    param([string] $AccessSddl)
    $security = New-Object Security.AccessControl.FileSecurity
    $security.SetSecurityDescriptorSddlForm($AccessSddl, [Security.AccessControl.AccessControlSections]::Access)
    $rules = @($security.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]) | ForEach-Object {
        '{0}|{1}|{2}|{3}|{4}|{5}' -f $_.IdentityReference.Value, [int]$_.FileSystemRights, $_.AccessControlType, $_.InheritanceFlags, $_.PropagationFlags, $_.IsInherited
    } | Sort-Object)
    # Windows can normalize the descriptor's AutoInherited control marker at
    # file creation without changing effective ACEs or inheritance protection.
    return ('Protected={0};{1}' -f $security.AreAccessRulesProtected, ($rules -join ';'))
}

function New-HarnessFixture {
    param([string] $Name, [string] $Scope = 'Project')
    $base = Join-Path $fixtureRoot $Name
    $project = Join-Path $base 'project'
    $config = Join-Path $base 'profile\.claude'
    $source = $(if ($Scope -eq 'User') { $config } else { $project })
    $localConfig = $(if ($Scope -eq 'User') { $config } else { Join-Path $project '.claude' })
    $rule = Join-Path $localConfig 'rules\nested\original.md'
    $instruction = Join-Path $source 'CLAUDE.md'
    $settings = Join-Path $localConfig 'settings.json'
    $backup = Join-Path $base 'backup'
    foreach ($path in @($config, (Split-Path -Parent $rule), $backup)) { $null = [IO.Directory]::CreateDirectory($path) }
    Protect-SetupBackupDirectory -Path $backup
    [byte[]]$mdBytes = [byte[]]@(239, 187, 191, 35, 32, 79, 108, 100, 13, 10)
    [IO.File]::WriteAllBytes($instruction, $mdBytes)
    Write-CompanyAgentUtf8File -Path $rule -Content "Do not lose this local rule.`r`n"
    $json = @'
{
  "model": "already-configured-medium", "env": { "API_TOKEN": "fixture-RAW-secret-8071" },
  "hooks": { "Stop": [{ "hooks": [{ "type": "command", "command": "echo fixture-RAW-hook-9842" }] }] },
  "permissions": { "deny": ["Bash(remove:*)"] }, "enabledPlugins": {"my-existing-plugin@local":true},
  "mcpServers": { "personal": { "command": "existing-mcp" } }, "extra": 12345678901234567890
}
'@
    Write-CompanyAgentUtf8File -Path $settings -Content $json
    $inventory = [pscustomobject]@{ scope = $Scope; scopeRoot = $source; claudeConfigRoot = $config; projectRoot = $(if ($Scope -eq 'Project') { $project } else { '' }); replacementFiles = @($instruction, $rule); hookSettingsPaths = @($settings) }
    return [pscustomobject]@{ base = $base; project = $project; config = $config; instruction = $instruction; rule = $rule; settings = $settings; backup = $backup; inventory = $inventory; originalSettings = [IO.File]::ReadAllBytes($settings); originalInstruction = $mdBytes }
}

$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('CompanyAgent-HarnessReplacement-' + [guid]::NewGuid().ToString('N'))
$fixtureFull = [IO.Path]::GetFullPath($fixtureRoot)
$junctions = New-Object Collections.ArrayList
$checks = New-Object Collections.ArrayList
try {
    foreach ($scope in @('User', 'Project')) {
        $f = New-HarnessFixture -Name ('roundtrip-' + $scope) -Scope $scope
        $transaction = New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory
        Assert-HarnessReplacement ([IO.File]::Exists($f.instruction)) 'Backup mutated instructions'
        $plaintext = @(Get-ChildItem -LiteralPath $transaction.directory -File | Where-Object { $_.Extension -ne '.dpapi' } | ForEach-Object { [IO.File]::ReadAllText($_.FullName) }) -join "`n"
        Assert-HarnessReplacement ($plaintext -notmatch 'fixture-RAW-secret|fixture-RAW-hook|Do not lose') 'Raw content leaked into backup plaintext'
        Invoke-SetupHarnessReplacement -Transaction $transaction
        Assert-HarnessReplacement (-not [IO.File]::Exists($f.instruction) -and -not [IO.File]::Exists($f.rule)) 'Old instructions remained active'
        $currentText = [IO.File]::ReadAllText($f.settings)
        $current = $currentText | ConvertFrom-Json
        Assert-HarnessReplacement ($null -eq $current.PSObject.Properties['hooks']) 'Old hooks remained active'
        Assert-HarnessReplacement ($current.model -eq 'already-configured-medium' -and $current.env.API_TOKEN -eq 'fixture-RAW-secret-8071' -and $current.enabledPlugins.'my-existing-plugin@local' -eq $true -and $current.mcpServers.personal.command -eq 'existing-mcp') 'Non-hook settings were lost'
        Assert-HarnessReplacement ($currentText.Contains('12345678901234567890')) 'Untouched JSON number precision changed'
        Complete-SetupHarnessReplacement -Transaction $transaction
        $loaded = Read-SetupHarnessReplacementTransaction -BackupPath $f.backup
        $preview = Restore-SetupHarnessReplacement -Transaction $loaded -DryRun
        Assert-HarnessReplacement ($preview.filesToRestore -eq 3 -and -not [IO.File]::Exists($f.instruction)) 'Recovery dry-run changed source files'
        Restore-SetupHarnessReplacement -Transaction $loaded
        Assert-HarnessReplacement ((Get-SetupHarnessHash -Bytes ([IO.File]::ReadAllBytes($f.settings))) -ceq (Get-SetupHarnessHash -Bytes $f.originalSettings)) 'Settings raw-byte roundtrip failed'
        Assert-HarnessReplacement ((Get-SetupHarnessHash -Bytes ([IO.File]::ReadAllBytes($f.instruction))) -ceq (Get-SetupHarnessHash -Bytes $f.originalInstruction)) 'Markdown BOM/line endings were not preserved'
        Restore-SetupHarnessReplacement -Transaction $loaded
        $null = $checks.Add("$scope encrypted backup, deactivation, exact-byte restore, persisted recovery, idempotency")
    }

    $f = New-HarnessFixture -Name 'restricted-file-dacl'
    $userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $systemSid = New-Object Security.Principal.SecurityIdentifier([Security.Principal.WellKnownSidType]::LocalSystemSid, $null)
    $everyoneSid = New-Object Security.Principal.SecurityIdentifier([Security.Principal.WellKnownSidType]::WorldSid, $null)
    $wideDirectorySecurity = New-Object Security.AccessControl.DirectorySecurity
    $wideDirectorySecurity.SetAccessRuleProtection($true, $false)
    foreach ($sid in @($userSid, $systemSid)) {
        $null = $wideDirectorySecurity.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid, [Security.AccessControl.FileSystemRights]::FullControl, [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit', [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow)))
    }
    $null = $wideDirectorySecurity.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($everyoneSid, [Security.AccessControl.FileSystemRights]::ReadAndExecute, [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit', [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow)))
    [IO.Directory]::SetAccessControl($f.project, $wideDirectorySecurity)
    $restrictedFileSecurity = New-Object Security.AccessControl.FileSecurity
    $restrictedFileSecurity.SetAccessRuleProtection($true, $false)
    foreach ($sid in @($userSid, $systemSid)) {
        $null = $restrictedFileSecurity.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid, [Security.AccessControl.FileSystemRights]::FullControl, [Security.AccessControl.AccessControlType]::Allow)))
    }
    [IO.File]::SetAccessControl($f.instruction, $restrictedFileSecurity)
    $settingsFileSecurity = New-Object Security.AccessControl.FileSecurity
    $settingsFileSecurity.SetSecurityDescriptorSddlForm($restrictedFileSecurity.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access), [Security.AccessControl.AccessControlSections]::Access)
    [IO.File]::SetAccessControl($f.settings, $settingsFileSecurity)
    $originalInstructionSddl = Get-SetupHarnessFileAccessSddl -Path $f.instruction
    $originalSettingsSddl = Get-SetupHarnessFileAccessSddl -Path $f.settings
    $transaction = New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory
    Assert-HarnessReplacement ($transaction.entries[0].originalAccessSddl -ceq $originalInstructionSddl) 'Original file DACL was not recorded in the protected plan'
    Invoke-SetupHarnessReplacement -Transaction $transaction
    Assert-HarnessReplacement ((Get-HarnessEffectiveDacl -AccessSddl (Get-SetupHarnessFileAccessSddl -Path $f.settings)) -ceq (Get-HarnessEffectiveDacl -AccessSddl $originalSettingsSddl)) 'Existing settings DACL was widened during replacement'
    $stagingSecurity = Get-SetupHarnessWriteSecurity -Path $f.instruction -AccessSddl $transaction.entries[0].originalAccessSddl
    Assert-HarnessReplacement ($stagingSecurity.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access) -ceq $originalInstructionSddl) 'Missing Markdown staging DACL was not selected before writing'
    $newSettingsSecurity = New-Object Security.AccessControl.FileSecurity
    $newSettingsSecurity.SetAccessRuleProtection($true, $false)
    $null = $newSettingsSecurity.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($userSid, [Security.AccessControl.FileSystemRights]::FullControl, [Security.AccessControl.AccessControlType]::Allow)))
    $null = $newSettingsSecurity.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($systemSid, [Security.AccessControl.FileSystemRights]::Read, [Security.AccessControl.AccessControlType]::Allow)))
    [IO.File]::SetAccessControl($f.settings, $newSettingsSecurity)
    $changedSettingsSddl = Get-SetupHarnessFileAccessSddl -Path $f.settings
    Restore-SetupHarnessReplacement -Transaction $transaction
    Assert-HarnessReplacement ((Get-HarnessEffectiveDacl -AccessSddl (Get-SetupHarnessFileAccessSddl -Path $f.instruction)) -ceq (Get-HarnessEffectiveDacl -AccessSddl $originalInstructionSddl)) 'Restored Markdown inherited a broader parent DACL'
    Assert-HarnessReplacement ((Get-HarnessEffectiveDacl -AccessSddl (Get-SetupHarnessFileAccessSddl -Path $f.settings)) -ceq (Get-HarnessEffectiveDacl -AccessSddl $changedSettingsSddl)) 'Restore overwrote the current settings DACL'
    $null = $checks.Add('restricted staging DACL from file creation and original Markdown/current settings DACL preservation')

    # Hooks can occupy first, middle, last, or only property, with escaped braces.
    foreach ($json in @('{"hooks":{},"keep":{"v":"},\\\""}}', '{"keep":1,"hooks":{}}', '{"hooks":{}}', '{"a":1,"hooks":{"value":[1,2]},"b":2}')) {
        $bytes = [Text.Encoding]::UTF8.GetBytes($json)
        $after = Get-SetupHarnessWithoutHooks -Bytes $bytes
        $document = Get-SetupHarnessJsonProperties -Bytes $after
        Assert-HarnessReplacement ($null -eq (Get-SetupHarnessHookProperty -Document $document)) 'Lexical hook removal failed'
    }
    $null = $checks.Add('top-level JSON lexical preservation')

    $f = New-HarnessFixture -Name 'unrelated-edits'
    $transaction = New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory
    Invoke-SetupHarnessReplacement -Transaction $transaction
    $current = [IO.File]::ReadAllText($f.settings) | ConvertFrom-Json
    $current.model = 'user-changed-model'
    $current.enabledPlugins | Add-Member -MemberType NoteProperty -Name 'company-agent@company-agent-local' -Value $true
    Write-CompanyAgentJsonAtomic -Path $f.settings -Value $current
    Complete-SetupHarnessReplacement -Transaction $transaction
    Restore-SetupHarnessReplacement -Transaction $transaction
    $restored = [IO.File]::ReadAllText($f.settings) | ConvertFrom-Json
    Assert-HarnessReplacement ($restored.model -eq 'user-changed-model' -and $restored.enabledPlugins.'company-agent@company-agent-local' -and $null -ne $restored.PSObject.Properties['hooks']) 'Unrelated post-install settings edits were overwritten or hooks not restored'
    $null = $checks.Add('unrelated model/plugin/settings edits preserved on hook-only restore')

    $f = New-HarnessFixture -Name 'new-hooks-conflict'
    $transaction = New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory
    Invoke-SetupHarnessReplacement -Transaction $transaction
    $current = [IO.File]::ReadAllText($f.settings) | ConvertFrom-Json
    $current | Add-Member -MemberType NoteProperty -Name hooks -Value ([pscustomobject]@{ Stop = @('new-user-hook') })
    Write-CompanyAgentJsonAtomic -Path $f.settings -Value $current
    $conflictHash = (Get-FileHash -LiteralPath $f.settings).Hash
    Assert-HarnessRejected { Restore-SetupHarnessReplacement -Transaction $transaction } 'Restore conflict: new hooks' 'Changed hooks were overwritten'
    Assert-HarnessReplacement (-not [IO.File]::Exists($f.instruction) -and (Get-FileHash -LiteralPath $f.settings).Hash -ceq $conflictHash) 'Restore conflict preflight changed files'
    $null = $checks.Add('new hooks block recovery before any writes')

    $f = New-HarnessFixture -Name 'instruction-conflict'
    $transaction = New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory
    Invoke-SetupHarnessReplacement -Transaction $transaction
    Write-CompanyAgentUtf8File -Path $f.rule -Content 'New user rule'
    Assert-HarnessRejected { Restore-SetupHarnessReplacement -Transaction $transaction } 'Restore conflict' 'Recreated rule was overwritten'
    Assert-HarnessReplacement (-not [IO.File]::Exists($f.instruction)) 'Conflict preflight restored earlier file'
    $null = $checks.Add('new instruction blocks recovery before any writes')

    $f = New-HarnessFixture -Name 'corrupt-backup'
    $transaction = New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory
    $cipher = Join-Path $transaction.directory $transaction.entries[0].snapshot
    $cipherBytes = [IO.File]::ReadAllBytes($cipher)
    $cipherBytes[10] = $cipherBytes[10] -bxor 1
    [IO.File]::WriteAllBytes($cipher, $cipherBytes)
    Assert-HarnessRejected { Invoke-SetupHarnessReplacement -Transaction $transaction } 'integrity' 'Corrupt ciphertext was accepted'
    Assert-HarnessReplacement ([IO.File]::Exists($f.instruction) -and [IO.File]::Exists($f.rule)) 'Corrupt backup mutated sources'
    $null = $checks.Add('corrupt encrypted snapshot blocks deactivation')

    $f = New-HarnessFixture -Name 'manifest-tampering'
    $transaction = New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory
    Write-CompanyAgentUtf8File -Path (Join-Path $transaction.directory 'manifest.json') -Content '{}'
    Assert-HarnessRejected { Invoke-SetupHarnessReplacement -Transaction $transaction } 'manifest integrity' 'Edited manifest was accepted'
    $null = $checks.Add('authenticated manifest prevents target/hash tampering')

    foreach ($unsafe in @('..\CLAUDE.md', 'C:\', '\\server\share\CLAUDE.md', 'C:\tmp\file.md:stream', (Join-Path $fixtureFull 'unrelated\secret.md'))) {
        $f = New-HarnessFixture -Name ('unsafe-' + [guid]::NewGuid().ToString('N'))
        $f.inventory.replacementFiles = @($unsafe)
        Assert-HarnessRejected { New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory } 'absolute local|drive root|allowlist' 'Unsafe inventory was accepted'
    }
    $f = New-HarnessFixture -Name 'overlap'
    $badBackup = Join-Path $f.project 'backup'
    $null = [IO.Directory]::CreateDirectory($badBackup)
    Assert-HarnessRejected { New-SetupHarnessReplacementBackup -BackupPath $badBackup -Inventory $f.inventory } 'outside' 'Source-overlapping backup was accepted'
    $null = $checks.Add('absolute scope allowlist and backup overlap checks')

    $f = New-HarnessFixture -Name 'changed-after-backup'
    $transaction = New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory
    Write-CompanyAgentUtf8File -Path $f.rule -Content 'Concurrent rule edit'
    Assert-HarnessRejected { Invoke-SetupHarnessReplacement -Transaction $transaction } 'changed after backup' 'Changed source was deactivated'
    Assert-HarnessReplacement ([IO.File]::Exists($f.instruction)) 'Deactivation preflight mutated earlier file'
    $null = $checks.Add('all-source hash preflight before first mutation')

    $f = New-HarnessFixture -Name 'journal-concurrent-edit'
    $transaction = New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory
    $originalJournal = ${function:Write-SetupHarnessJournal}
    $script:replacementEditInjected = $false
    function Write-SetupHarnessJournal {
        param([object] $Transaction, [string] $Status, [int] $EntryIndex = -1)
        & $originalJournal -Transaction $Transaction -Status $Status -EntryIndex $EntryIndex
        if ($Status -eq 'applying-entry' -and -not $script:replacementEditInjected) {
            $script:replacementEditInjected = $true
            Write-CompanyAgentUtf8File -Path $Transaction.entries[$EntryIndex].path -Content 'User edit during journal I/O'
        }
    }
    try { Assert-HarnessRejected { Invoke-SetupHarnessReplacement -Transaction $transaction } 'changed during replacement' 'Journal-time concurrent edit was overwritten' }
    finally { Set-Item -Path Function:\Write-SetupHarnessJournal -Value $originalJournal }
    Assert-HarnessReplacement ([IO.File]::ReadAllText($f.instruction) -ceq 'User edit during journal I/O') 'Journal-time concurrent edit was lost'
    Assert-HarnessRejected { Restore-SetupHarnessReplacement -Transaction $transaction } 'Restore conflict' 'Rollback overwrote the concurrent edit'
    $null = $checks.Add('journal-time concurrent edits checked before mutation and preserved by rollback')

    $f = New-HarnessFixture -Name 'bounded-backup'
    $largePath = $f.rule
    $largeStream = [IO.File]::Open($largePath, [IO.FileMode]::Open, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $largeStream.SetLength(8388609) } finally { $largeStream.Dispose() }
    Assert-HarnessRejected { New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory } 'size limit' 'Oversized original was accepted'
    Assert-HarnessReplacement ([IO.File]::Exists($f.instruction) -and (Get-Item -LiteralPath $f.rule).Length -eq 8388609) 'Backup failure changed source files'
    $null = $checks.Add('backup size limit before any source mutation')

    $f = New-HarnessFixture -Name 'corrupt-seal'
    $transaction = New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory
    $sealPath = Join-Path $transaction.directory 'manifest.dpapi'
    $seal = [IO.File]::ReadAllBytes($sealPath)
    $seal[$seal.Length - 1] = $seal[$seal.Length - 1] -bxor 1
    [IO.File]::WriteAllBytes($sealPath, $seal)
    Assert-HarnessRejected { Invoke-SetupHarnessReplacement -Transaction $transaction } 'could not be decrypted' 'Corrupt authenticated plan was accepted'
    Assert-HarnessReplacement ([IO.File]::Exists($f.instruction)) 'Corrupt plan changed source files'
    $null = $checks.Add('corrupt DPAPI plan fails without plaintext fallback')

    # Simulate process failure immediately after the first deletion and before
    # its success journal. Recovery derives state from hashes, not the journal.
    $f = New-HarnessFixture -Name 'partial-failure'
    $transaction = New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory
    $originalJournal = ${function:Write-SetupHarnessJournal}
    $script:replacementFailureInjected = $false
    function Write-SetupHarnessJournal {
        param([object] $Transaction, [string] $Status, [int] $EntryIndex = -1)
        if ($Status -eq 'entry-applied' -and -not $script:replacementFailureInjected) { $script:replacementFailureInjected = $true; throw 'Injected journal failure after source mutation' }
        & $originalJournal -Transaction $Transaction -Status $Status -EntryIndex $EntryIndex
    }
    try { Assert-HarnessRejected { Invoke-SetupHarnessReplacement -Transaction $transaction } 'Injected journal failure' 'Partial failure fixture did not execute' }
    finally { Set-Item -Path Function:\Write-SetupHarnessJournal -Value $originalJournal }
    Assert-HarnessReplacement (-not [IO.File]::Exists($f.instruction)) 'Partial mutation did not happen in fixture'
    Restore-SetupHarnessReplacement -Transaction (Read-SetupHarnessReplacementTransaction -BackupPath $f.backup)
    Assert-HarnessReplacement ([IO.File]::Exists($f.instruction) -and (Get-SetupHarnessHash -Bytes ([IO.File]::ReadAllBytes($f.settings))) -ceq (Get-SetupHarnessHash -Bytes $f.originalSettings)) 'Partial failure recovery did not restore originals'
    $null = $checks.Add('failure after mutation before journal remains recoverable')

    $f = New-HarnessFixture -Name 'reparse'
    $outside = Join-Path $f.base 'outside'
    $null = [IO.Directory]::CreateDirectory($outside)
    Write-CompanyAgentUtf8File -Path (Join-Path $outside 'external.md') -Content 'Never traverse this junction'
    $junction = Join-Path $f.project '.claude\rules\junction'
    $null = New-Item -ItemType Junction -Path $junction -Target $outside
    $null = $junctions.Add($junction)
    $f.inventory.replacementFiles = @((Join-Path $junction 'external.md'))
    Assert-HarnessRejected { New-SetupHarnessReplacementBackup -BackupPath $f.backup -Inventory $f.inventory } 'reparse point' 'Junction source was accepted'
    $null = $checks.Add('reparse-point source rejection')

    [pscustomobject]@{ status = 'passed'; checks = @($checks.ToArray()); fixtureRoot = $fixtureRoot }
}
finally {
    foreach ($junction in @($junctions.ToArray())) {
        if (Test-Path -LiteralPath $junction) {
            $item = Get-Item -LiteralPath $junction -Force
            if (-not (Test-SetupSameOrChildPath -Candidate $item.FullName -Parent $fixtureFull) -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) { throw 'Unsafe junction cleanup target.' }
            [IO.Directory]::Delete($item.FullName)
        }
    }
    if (-not $KeepTestDirectory -and (Test-Path -LiteralPath $fixtureFull)) {
        $actual = (Get-Item -LiteralPath $fixtureFull -Force).FullName
        if ($actual -ine $fixtureFull -or -not (Test-SetupSameOrChildPath -Candidate $actual -Parent ([IO.Path]::GetTempPath())) -or (Split-Path -Leaf $actual) -notlike 'CompanyAgent-HarnessReplacement-*') { throw 'Unsafe replacement fixture cleanup target.' }
        Assert-SetupPathHasNoReparsePoint -Path $actual -Name 'Replacement regression cleanup'
        Remove-Item -LiteralPath $actual -Recurse -Force
    }
}
