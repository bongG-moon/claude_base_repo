[CmdletBinding()]
param([switch] $KeepTestDirectory)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'Setup-CompanyAgent.ps1') -FunctionsOnly

function Assert-PersonalBackup {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw "Personal-state backup regression failed: $Message" }
}

function Assert-PersonalBackupRejected {
    param([scriptblock] $Action, [string] $Pattern, [string] $Message)
    $rejected = $false
    try { $null = & $Action }
    catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw }
        $rejected = $true
    }
    Assert-PersonalBackup $rejected $Message
}

function Get-PersonalBackupFixtureDigest {
    param([string] $Root)
    return (@(Get-ChildItem -LiteralPath $Root -File -Recurse -Force | Sort-Object FullName | ForEach-Object {
        '{0}|{1}|{2}|{3}' -f $_.FullName, $_.Length, $_.LastWriteTimeUtc.Ticks, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }) -join "`n")
}

$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('CompanyAgent-PersonalBackup-' + [guid]::NewGuid().ToString('N'))
$fixtureFull = [IO.Path]::GetFullPath($fixtureRoot)
$junctions = New-Object Collections.ArrayList
try {
    $claudeRoot = Join-Path $fixtureRoot 'profile\.claude'
    $stateRoot = Join-Path $fixtureRoot 'personal-state'
    $managedData = Join-Path $fixtureRoot 'managed-data'
    $managedInstall = Join-Path $fixtureRoot 'managed-install'
    $backupBase = Join-Path $fixtureRoot 'backups'
    foreach ($path in @($claudeRoot, $stateRoot, $managedData, $managedInstall)) { New-CompanyAgentDirectory -Path $path }

    $learningFiles = @(
        'memory\items\lesson.md',
        'memory\items\session-guidance.md',
        'memory\versions\20260901\lesson.md',
        'knowledge\entries\term.md',
        'knowledge\overlays\term-note.md',
        'knowledge\versions\20260901\term-note.md',
        'personal-root\.claude\skills\daily-summary\SKILL.md',
        'personal-root\.claude\skills\daily-summary\scripts\helper.py'
    )
    foreach ($relative in $learningFiles) { Write-CompanyAgentUtf8File -Path (Join-Path $stateRoot $relative) -Content ("preserve: $relative`n") }
    foreach ($relative in @('memory\items\lesson.md', 'memory\items\session-guidance.md')) {
        Write-CompanyAgentUtf8File -Path (Join-Path $stateRoot $relative) -Content ("---`nkind: fact`nstatus: active`n---`npreserve: $relative`n")
    }
    Write-CompanyAgentJsonAtomic -Path (Join-Path $stateRoot 'config\user.json') -Value ([pscustomobject]@{
        schemaVersion = 2; displayName = 'Fixture employee'
        preferences = [pscustomobject]@{ concise = $true; apiKey = 'fixture-user-secret'; nested = @([pscustomobject]@{ password = 'fixture-password'; safe = 'keep' }) }
    })
    Write-CompanyAgentJsonAtomic -Path (Join-Path $stateRoot 'state-format.json') -Value ([pscustomobject]@{ schemaVersion = 1 })
    $learningPython = Resolve-SetupApprovedPython -PreferredCommand 'python' -OnlyPreferred
    if (-not $learningPython) { throw 'Python 3.11+ is required for the real learning journal backup regression.' }
    $learningScripts = Join-Path (Split-Path -Parent $PSScriptRoot) 'company-agent-plugin\scripts'
    $seedLearning = @'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from company_agent.state import begin_turn
from company_agent.learning import submit_review, set_learning_enabled
root = Path(sys.argv[2])
for body in ('Reports start with the conclusion.', 'Reports start with decisions needed.'):
    turn = begin_turn('backup-test', 'SMALL', False, [], root)
    result = submit_review(root, 'backup-test', turn['turnId'], {'schemaVersion': 1, 'taskType': 'weekly-report', 'outcome': 'unknown', 'summary': 'A durable reporting preference was corrected.', 'observations': [{'kind': 'preference', 'key': 'report-order', 'signal': 'explicit_correction', 'title': 'Report order', 'body': body}], 'evaluations': []})
    assert result['changes'][0]['status'] == 'active', result['changes'][0]
set_learning_enabled(root, False)
'@
    $seedResult = Invoke-CompanyAgentPythonProcess -Executable $learningPython -Arguments @('-B', '-c', $seedLearning, $learningScripts, $stateRoot)
    Assert-PersonalBackup ($seedResult.ExitCode -eq 0) ('Real learning fixture failed: ' + $seedResult.StdErr)
    Write-CompanyAgentJsonAtomic -Path (Join-Path $stateRoot 'personal-root\.claude\skills\daily-summary\options.json') -Value ([pscustomobject]@{
        label = 'Safe option'; env = [pscustomobject]@{ API_TOKEN = 'fixture-skill-secret'; NORMAL = 'keep' }
    })
    $excludedFiles = @(
        'sessions\conversation.jsonl', 'tmp\prompt.txt', 'mcp\registry.json', 'config\runtime.json',
        'memory\index\catalog.json', 'memory\items\scratch.json', 'knowledge\generated-index\catalog.json',
        'personal-root\.claude\skills\daily-summary\.env',
        'personal-root\.claude\skills\daily-summary\credentials.json',
        'personal-root\.claude\skills\daily-summary\.mcp.json',
        'personal-root\.claude\skills\daily-summary\settings.local.json',
        'personal-root\.claude\skills\daily-summary\sessions\conversation.md',
        'personal-root\.claude\skills\daily-summary\tmp\debug.txt',
        'personal-root\.claude\skills\daily-summary\cache\item.txt',
        'personal-root\.claude\skills\daily-summary\secrets\access.txt',
        'personal-root\.claude\skills\daily-summary\key.pem'
    )
    foreach ($relative in $excludedFiles) { Write-CompanyAgentUtf8File -Path (Join-Path $stateRoot $relative) -Content 'fixture-private-runtime-content' }
    Write-CompanyAgentJsonAtomic -Path (Join-Path $claudeRoot 'settings.json') -Value ([pscustomobject]@{ env = [pscustomobject]@{ API_TOKEN = 'fixture-claude-secret'; NORMAL = 'keep' } })
    Write-CompanyAgentUtf8File -Path (Join-Path $claudeRoot 'skills\existing\SKILL.md') -Content 'preserve global Skill'
    Write-CompanyAgentUtf8File -Path (Join-Path $claudeRoot '.credentials.json') -Content 'do-not-copy'
    $sourceBefore = Get-PersonalBackupFixtureDigest -Root $fixtureRoot
    $itemArgs = @{
        ClaudeConfigPath = $claudeRoot; PersonalStatePath = $stateRoot
        ManagedDataPath = $managedData; ManagedInstallPath = $managedInstall
        ManagedShortcutPath = (Join-Path $fixtureRoot 'missing-shortcut.lnk')
    }
    $items = @(Get-SetupBackupItems @itemArgs)
    $backupArgs = @{
        BackupBase = $backupBase; Items = $items; ClaudeConfigPath = $claudeRoot
        PersonalStatePath = $stateRoot; ManagedDataPath = $managedData; ManagedInstallPath = $managedInstall
    }
    $backup = New-SetupBackup @backupArgs
    $personalBackup = Join-Path $backup 'company-agent\personal-learning'
    foreach ($relative in $learningFiles) {
        $destination = Join-Path $personalBackup $relative
        Assert-PersonalBackup (Test-Path -LiteralPath $destination -PathType Leaf) "Missing personal learning artifact: $relative"
        Assert-PersonalBackup ((Get-FileHash -LiteralPath $destination).Hash -eq (Get-FileHash -LiteralPath (Join-Path $stateRoot $relative)).Hash) "Changed learning artifact: $relative"
    }
    foreach ($relative in $excludedFiles) {
        Assert-PersonalBackup (-not (Test-Path -LiteralPath (Join-Path $personalBackup $relative))) "Included excluded runtime or secret file: $relative"
    }
    $config = Read-CompanyAgentJson -Path (Join-Path $personalBackup 'config\user.json')
    Assert-PersonalBackup ($config.preferences.apiKey -eq '[REDACTED_BY_COMPANY_AGENT_BACKUP]') 'Personal config key was not redacted'
    Assert-PersonalBackup ($config.preferences.nested[0].password -eq '[REDACTED_BY_COMPANY_AGENT_BACKUP]' -and $config.preferences.nested[0].safe -eq 'keep') 'Nested JSON array redaction lost safe fields'
    Assert-PersonalBackup ($config.displayName -eq 'Fixture employee') 'Personal config nonsecret field was lost'
    $skillOptions = Read-CompanyAgentJson -Path (Join-Path $personalBackup 'personal-root\.claude\skills\daily-summary\options.json')
    Assert-PersonalBackup ($skillOptions.env.API_TOKEN -eq '[REDACTED_BY_COMPANY_AGENT_BACKUP]' -and $skillOptions.env.NORMAL -eq 'keep') 'Nested Skill JSON was not sanitized'
    $marker = Read-CompanyAgentJson -Path (Join-Path $personalBackup 'state-format.json')
    Assert-PersonalBackup ($marker.schemaVersion -eq 1) 'State format marker was not included'
    $learningConfig = Read-CompanyAgentJson -Path (Join-Path $personalBackup 'config\learning.json')
    Assert-PersonalBackup ($learningConfig.enabled -eq $false) 'Automatic learning pause setting was not preserved'
    $learningHistory = Read-CompanyAgentJson -Path (Join-Path $personalBackup 'learning\state.json')
    Assert-PersonalBackup ($learningHistory.changes[1].beforeContent -match 'Reports start with the conclusion.' -and $learningHistory.changes[1].afterContent -match 'Reports start with decisions needed.') 'Automatic learning comparison and rollback history was not preserved'
    Assert-PersonalBackup ($learningHistory.reviews[0].sessionFingerprint -match '^[a-f0-9]{64}$') 'A nonsecret learning correlation fingerprint was redacted'
    $claudeSettings = Read-CompanyAgentJson -Path (Join-Path $backup 'claude-config\settings.json')
    Assert-PersonalBackup ($claudeSettings.env.API_TOKEN -eq '[REDACTED_BY_COMPANY_AGENT_BACKUP]') 'Existing Claude JSON redaction regressed'
    Assert-PersonalBackup (-not (Test-Path -LiteralPath (Join-Path $backup 'claude-config\.credentials.json'))) 'Claude credentials were copied'
    $manifest = Read-CompanyAgentJson -Path (Join-Path $backup 'backup-manifest.json')
    Assert-PersonalBackup ($manifest.schemaVersion -eq 2 -and $manifest.note -match 'Selective' -and $manifest.copiedFiles -gt 0) 'Manifest incorrectly describes backup coverage'
    Assert-PersonalBackup (@($manifest.items | Where-Object { $_.required }).Count -eq 10) 'Personal learning artifacts are not required once selected'
    foreach ($record in @($manifest.items)) {
        Assert-PersonalBackup (Test-SetupSameOrChildPath -Candidate $record.backup -Parent $backup) 'Manifest backup item escaped the destination'
    }
    $acl = Get-Acl -LiteralPath $backup
    Assert-PersonalBackup $acl.AreAccessRulesProtected 'Backup folder inherited unrelated account permissions'
    $expectedSids = @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18')
    foreach ($rule in @($acl.Access)) {
        $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        Assert-PersonalBackup ($expectedSids -contains $sid) "Unexpected backup ACL principal: $sid"
    }
    $sourceAfter = (@(Get-ChildItem -LiteralPath $fixtureRoot -File -Recurse -Force | Where-Object {
        -not (Test-SetupSameOrChildPath -Candidate $_.FullName -Parent $backupBase)
    } | Sort-Object FullName | ForEach-Object {
        '{0}|{1}|{2}|{3}' -f $_.FullName, $_.Length, $_.LastWriteTimeUtc.Ticks, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }) -join "`n")
    Assert-PersonalBackup ($sourceBefore -ceq $sourceAfter) 'Backup modified the original state contents or timestamps'

    # A backup is useful only if the actual engine can read it and reverse its
    # latest owned change. Keep this restore fixture outside the original state.
    $restoredState = Join-Path $backupBase 'restored-learning-test'
    Copy-CompanyAgentDirectoryContents -Source $personalBackup -Destination $restoredState
    $verifyRestoredLearning = @'
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from company_agent.learning import learning_status, rollback_change
from company_agent.frontmatter import parse_frontmatter_text
source, restored = Path(sys.argv[2]), Path(sys.argv[3])
assert json.loads((source / 'learning/state.json').read_text(encoding='utf-8-sig')) == json.loads((restored / 'learning/state.json').read_text(encoding='utf-8-sig'))
status = learning_status(restored)
assert status['enabled'] is False and status['activeChanges'] == 1
active = next(c for c in status['recentChanges'] if c['status'] == 'active')
assert rollback_change(restored, active['id'])['status'] == 'rolled_back'
body = (restored / 'memory/items' / (active['memoryId'] + '.md')).read_text(encoding='utf-8')
metadata, _ = parse_frontmatter_text(body)
assert metadata['status'] == 'inactive'
assert 'Reports start with the conclusion.' in json.loads((restored / 'learning/state.json').read_text(encoding='utf-8'))['changes'][1]['beforeContent']
'@
    $restoreResult = Invoke-CompanyAgentPythonProcess -Executable $learningPython -Arguments @('-B', '-c', $verifyRestoredLearning, $learningScripts, $stateRoot, $restoredState)
    Assert-PersonalBackup ($restoreResult.ExitCode -eq 0) ('Restored learning journal is unusable: ' + $restoreResult.StdErr)

    Assert-PersonalBackupRejected -Action { New-SetupBackup @backupArgs -MaxFileBytes 1 } -Pattern 'limit exceeded' -Message 'Oversized selected source did not stop backup'
    Assert-PersonalBackupRejected -Action { New-SetupBackup @backupArgs -MaxTotalBytes 1 } -Pattern 'limit exceeded' -Message 'Aggregate byte limit was not enforced'
    Assert-PersonalBackupRejected -Action { New-SetupBackup @backupArgs -MaxFiles 1 } -Pattern 'limit exceeded' -Message 'Aggregate file limit was not enforced'
    Assert-PersonalBackupRejected -Action { New-SetupBackup @backupArgs -MaxDepth 1 } -Pattern 'depth limit' -Message 'Directory depth limit was not enforced'
    Assert-PersonalBackupRejected -Action { New-SetupBackup @backupArgs -MaxVisited 1 } -Pattern 'traversal limit' -Message 'Traversal limit was not enforced'
    $insideArgs = $backupArgs.Clone()
    $insideArgs.BackupBase = Join-Path $stateRoot 'unsafe-backups'
    Assert-PersonalBackupRejected -Action { New-SetupBackup @insideArgs } -Pattern 'separate' -Message 'Backup inside personal state was accepted'
    Assert-PersonalBackup (-not (Test-Path -LiteralPath $insideArgs.BackupBase)) 'Rejected backup root created a directory in personal state'

    $escapeArgs = $backupArgs.Clone()
    $escapeArgs.Items = @([pscustomobject]@{ source = (Join-Path $stateRoot 'memory\items\lesson.md'); relativePath = '..\..\escaped.md'; purpose = 'unsafe fixture'; mode = 'copy'; required = $true })
    Assert-PersonalBackupRejected -Action { New-SetupBackup @escapeArgs } -Pattern 'escapes' -Message 'Relative destination traversal was accepted'
    Assert-PersonalBackup (-not (Test-Path -LiteralPath (Join-Path $fixtureRoot 'escaped.md'))) 'Traversal check happened after an outside write'
    $missingArgs = $backupArgs.Clone()
    $missingArgs.Items = @([pscustomobject]@{ source = (Join-Path $stateRoot 'memory\items\missing.md'); relativePath = 'missing.md'; purpose = 'missing fixture'; mode = 'copy'; required = $true })
    Assert-PersonalBackupRejected -Action { New-SetupBackup @missingArgs } -Pattern 'could not be completed' -Message 'Disappeared required source did not stop backup'
    $streamArgs = $backupArgs.Clone()
    $streamArgs.Items = @([pscustomobject]@{ source = (Join-Path $stateRoot 'memory\items\lesson.md'); relativePath = 'hidden.txt:payload'; purpose = 'unsafe stream fixture'; mode = 'copy'; required = $true })
    Assert-PersonalBackupRejected -Action { New-SetupBackup @streamArgs } -Pattern 'normal relative path' -Message 'Alternate data stream destination was accepted'
    $invalidJsonPath = Join-Path $fixtureRoot 'invalid.json'
    Write-CompanyAgentUtf8File -Path $invalidJsonPath -Content '{not-valid-json'
    $invalidArgs = $backupArgs.Clone()
    $invalidArgs.Items = @([pscustomobject]@{ source = $invalidJsonPath; relativePath = 'invalid.json'; purpose = 'invalid JSON fixture'; mode = 'sanitized-json'; required = $true })
    Assert-PersonalBackupRejected -Action { New-SetupBackup @invalidArgs } -Pattern 'could not be completed' -Message 'Malformed selected JSON was copied without sanitization'

    $outside = Join-Path $fixtureRoot 'outside-sentinel'
    Write-CompanyAgentUtf8File -Path (Join-Path $outside 'private.md') -Content 'external file must not be copied or changed'
    $outsideBefore = Get-PersonalBackupFixtureDigest -Root $outside
    $junction = Join-Path $stateRoot 'memory\items\linked-outside'
    New-Item -ItemType Junction -Path $junction -Value $outside | Out-Null
    $null = $junctions.Add($junction)
    Assert-PersonalBackupRejected -Action { New-SetupBackup @backupArgs } -Pattern 'Required personal learning backup' -Message 'Junction in required personal learning state was silently accepted'
    $selectedJunctionArgs = $backupArgs.Clone()
    $selectedJunctionArgs.Items = @([pscustomobject]@{ source = $junction; relativePath = 'linked'; purpose = 'required root junction fixture'; mode = 'learning-markdown'; required = $true })
    Assert-PersonalBackupRejected -Action { New-SetupBackup @selectedJunctionArgs } -Pattern 'Required personal learning backup' -Message 'Selected source junction was treated as a completed backup'
    $parentJunction = Join-Path $fixtureRoot 'linked-parent'
    New-Item -ItemType Junction -Path $parentJunction -Value $stateRoot | Out-Null
    $null = $junctions.Add($parentJunction)
    $destinationJunctionArgs = $backupArgs.Clone()
    $destinationJunctionArgs.BackupBase = Join-Path $parentJunction 'unsafe-output'
    Assert-PersonalBackupRejected -Action { New-SetupBackup @destinationJunctionArgs } -Pattern 'reparse point' -Message 'Backup root reparse-point ancestor was followed'
    $parentArgs = $backupArgs.Clone()
    $parentArgs.Items = @([pscustomobject]@{ source = (Join-Path $parentJunction 'config\user.json'); relativePath = 'user.json'; purpose = 'parent reparse fixture'; mode = 'sanitized-json'; required = $true })
    Assert-PersonalBackupRejected -Action { New-SetupBackup @parentArgs } -Pattern 'reparse point' -Message 'Reparse-point source ancestor was followed'
    Assert-PersonalBackup ((Get-PersonalBackupFixtureDigest -Root $outside) -ceq $outsideBefore) 'Junction target was changed'
    $outsideCopies = @(Get-ChildItem -LiteralPath $backupBase -File -Recurse -Filter 'private.md')
    Assert-PersonalBackup ($outsideCopies.Count -eq 0) 'Junction target contents were copied'

    [pscustomobject][ordered]@{
        status = 'passed'
        checks = @('learning sources and versions', 'personal Skills', 'selective exclusions', 'recursive JSON redaction', 'user-only ACL', 'unchanged originals', 'size/file/depth/traversal limits', 'destination containment', 'required-source failure', 'reparse source and ancestor rejection')
        fixtureRoot = $fixtureRoot
    }
}
finally {
    foreach ($junction in @($junctions.ToArray())) {
        $item = Get-Item -LiteralPath $junction -Force -ErrorAction SilentlyContinue
        if ($null -ne $item) {
            if (-not (Test-SetupSameOrChildPath -Candidate $item.FullName -Parent $fixtureFull) -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) { throw 'Unsafe junction fixture cleanup target.' }
            [IO.Directory]::Delete($item.FullName)
        }
    }
    if (-not $KeepTestDirectory -and (Test-Path -LiteralPath $fixtureFull)) {
        $actual = (Get-Item -LiteralPath $fixtureFull -Force).FullName
        if ($actual -ine $fixtureFull -or -not (Test-SetupSameOrChildPath -Candidate $actual -Parent ([IO.Path]::GetTempPath())) -or (Split-Path -Leaf $actual) -notlike 'CompanyAgent-PersonalBackup-*') { throw 'Unsafe backup fixture cleanup target.' }
        Assert-SetupPathHasNoReparsePoint -Path $actual -Name 'Regression fixture cleanup'
        Remove-Item -LiteralPath $actual -Recurse -Force
    }
}
