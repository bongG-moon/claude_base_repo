# Read-only inventory and decision helpers. Dot-source Setup-CompanyAgent.ps1
# -FunctionsOnly first. This file must never write to an existing installation.

function Assert-SetupNativeSettingsIntegerSafety {
    [CmdletBinding()]
    param(
        [AllowNull()][AllowEmptyCollection()][string[]] $Paths = @(),
        [ValidateRange(1, 8388608)][long] $MaxBytes = 1048576
    )

    # Native Claude plugin commands parse/write settings through JavaScript JSON.
    # Keep integer tokens exact until after checking the IEEE-754 safe range.
    # This is an integer-safety guard, not a general decimal-precision validator.
    $numberPattern = '"(?:\\.|[^"\\])*"|(?<number>-?(?<whole>0|[1-9][0-9]*)(?:\.(?<fraction>[0-9]+))?(?:[eE](?<exponent>[+-]?[0-9]+))?)'
    $numberLexer = New-Object Text.RegularExpressions.Regex($numberPattern, [Text.RegularExpressions.RegexOptions]::CultureInvariant, ([TimeSpan]::FromSeconds(2)))
    foreach ($candidate in @($Paths)) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        $path = Get-SetupFullPath -Path $candidate
        Assert-SetupPathHasNoReparsePoint -Path $path -Name 'Native Claude settings preflight'
        if (-not (Test-Path -LiteralPath $path)) { continue }
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Native Claude settings must be a file; original settings were not changed: $path" }
        $stream = $null
        $reader = $null
        $unsafeInteger = $false
        try {
            $stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
            if ($stream.Length -gt $MaxBytes) { throw 'settings-size-limit' }
            # Do not silently reinterpret UTF-16 as UTF-8. An optional UTF-8 BOM
            # is stripped explicitly; invalid UTF-8 causes a generic safe error.
            $reader = New-Object IO.StreamReader($stream, (New-Object Text.UTF8Encoding($false, $true)), $false)
            $json = $reader.ReadToEnd()
            if ($json.Length -gt 0 -and $json[0] -eq [char]0xFEFF) { $json = $json.Substring(1) }
            if (-not $json.TrimStart().StartsWith('{')) { throw 'settings-object-required' }
            $tokenCount = 0
            foreach ($match in $numberLexer.Matches($json)) {
                $tokenCount++
                if ($tokenCount -gt 100000) { throw 'settings-token-limit' }
                if (-not $match.Groups['number'].Success) { continue }
                $fraction = $match.Groups['fraction'].Value
                $digits = ($match.Groups['whole'].Value + $fraction).TrimStart('0')
                if ($digits.Length -eq 0) { continue }
                [int] $exponent = 0
                $exponentText = $match.Groups['exponent'].Value
                if ($exponentText.Length -gt 0 -and -not [int]::TryParse($exponentText, [Globalization.NumberStyles]::AllowLeadingSign, [Globalization.CultureInfo]::InvariantCulture, [ref]$exponent)) {
                    # With a bounded <= 8 MiB document, an exponent beyond Int32
                    # dominates every possible significand length. Huge positive
                    # exponents are unsafe integers; huge negative ones are not
                    # integral (zero was handled above).
                    if ($exponentText.StartsWith('-')) { continue }
                    $unsafeInteger = $true
                    break
                }
                [long] $scale = ([long]$exponent - [long]$fraction.Length)
                if ($scale -lt 0) {
                    [long] $requiredZeroes = -$scale
                    $trailingZeroes = $digits.Length - $digits.TrimEnd('0').Length
                    if ($requiredZeroes -gt $trailingZeroes) { continue }
                    $integerDigits = $digits.Substring(0, ($digits.Length - [int]$requiredZeroes))
                }
                else {
                    if (([long]$digits.Length + $scale) -gt 16) {
                        $unsafeInteger = $true
                        break
                    }
                    $integerDigits = $digits + ('0' * [int]$scale)
                }
                if ($integerDigits.Length -gt 16 -or ($integerDigits.Length -eq 16 -and [string]::CompareOrdinal($integerDigits, '9007199254740991') -gt 0)) {
                    $unsafeInteger = $true
                    break
                }
            }
            # Bound number-token work before a general JSON parser can attempt
            # to materialize an attacker-sized integer. Unsafe tokens always
            # reject; every accepted document must still parse as a JSON object.
            if (-not $unsafeInteger) {
                $document = $json | ConvertFrom-Json -ErrorAction Stop
                if ($null -eq $document -or $document -isnot [pscustomobject]) { throw 'settings-object-required' }
            }
        }
        catch {
            # Never include parser exceptions: they can contain private settings
            # values, Hook command bodies, or credential-like strings.
            throw "Native Claude settings cannot be safely inspected (invalid UTF-8 JSON, read error, or inspection limit); original settings were not changed: $path"
        }
        finally {
            if ($null -ne $reader) { $reader.Dispose() }
            elseif ($null -ne $stream) { $stream.Dispose() }
        }
        if ($unsafeInteger) {
            throw "Unsafe integer in native Claude settings: a numeric value exceeds the JavaScript safe integer range (-9007199254740991 to 9007199254740991). Installation stopped before native CLI writes; keep the original settings and consult their owner. Use a quoted string only if that setting's schema allows it: $path"
        }
    }
}

function Get-SetupHarnessSettingsHasHooks {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [long] $MaxBytes = 1048576
    )

    Assert-SetupPathHasNoReparsePoint -Path $Path -Name 'Existing harness settings'
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Existing harness settings must be a file: $Path" }
    if ($MaxBytes -lt 1) { throw 'Existing harness settings size limit must be positive.' }
    $stream = $null
    $reader = $null
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        if ($stream.Length -gt $MaxBytes) { throw 'settings-size-limit' }
        $reader = New-Object IO.StreamReader($stream, (New-Object Text.UTF8Encoding($false, $true)), $true)
        $document = $reader.ReadToEnd() | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $document -or $document -isnot [pscustomobject]) { throw 'settings-object-required' }
        $hooks = Get-SetupPropertyValue -Object $document -Name 'hooks'
        if ($null -eq $hooks) { return $false }
        if ($hooks -isnot [pscustomobject]) { throw 'hooks-object-required' }
        $foundHooks = $false
        foreach ($eventProperty in @($hooks.PSObject.Properties)) {
            $matchers = $eventProperty.Value
            if ($matchers -isnot [array]) { throw 'hook-event-array-required' }
            foreach ($matcher in $matchers) {
                if ($null -eq $matcher -or $matcher -isnot [pscustomobject]) { throw 'hook-matcher-object-required' }
                $definitionsProperty = $matcher.PSObject.Properties['hooks']
                if ($null -eq $definitionsProperty) { throw 'hook-definitions-array-required' }
                $definitions = $definitionsProperty.Value
                if ($definitions -isnot [array]) { throw 'hook-definitions-array-required' }
                if ($definitions.Count -gt 0) { $foundHooks = $true }
            }
        }
        return $foundHooks
    }
    catch {
        # Parser exceptions can contain command bodies or credentials. Return only
        # a generic, actionable error and the selected path, never the JSON.
        throw "Existing harness settings cannot be safely inspected (invalid JSON/hooks, read error, or size limit): $Path"
    }
    finally {
        if ($null -ne $reader) { $reader.Dispose() }
        elseif ($null -ne $stream) { $stream.Dispose() }
    }
}

function Get-SetupHarnessRuleFiles {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [int] $MaxFiles = 20000,
        [int] $MaxDepth = 32,
        [int] $MaxVisited = 100000
    )

    if ($MaxFiles -lt 1 -or $MaxDepth -lt 0 -or $MaxVisited -lt 1) { throw 'Existing harness inventory limits are invalid.' }
    Assert-SetupPathHasNoReparsePoint -Path $Root -Name 'Existing harness rules'
    if (-not (Test-Path -LiteralPath $Root)) { return }
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { throw "Existing harness rules must be a directory: $Root" }
    $pending = New-Object Collections.Stack
    $pending.Push([pscustomobject]@{ path = (Get-SetupFullPath -Path $Root); depth = 0 })
    $files = 0
    $visited = 0
    while ($pending.Count -gt 0) {
        $current = $pending.Pop()
        Assert-SetupPathHasNoReparsePoint -Path $current.path -Name 'Existing harness rule directory'
        foreach ($entryPath in [IO.Directory]::EnumerateFileSystemEntries($current.path)) {
            $visited++
            if ($visited -gt $MaxVisited) { throw 'Existing harness inventory traversal limit exceeded.' }
            $entry = Get-Item -LiteralPath $entryPath -Force -ErrorAction Stop
            if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Existing harness rules cannot contain a junction or symbolic link: $entryPath" }
            if ($entry.PSIsContainer) {
                if ($current.depth -ge $MaxDepth) { throw 'Existing harness inventory depth limit exceeded.' }
                $pending.Push([pscustomobject]@{ path = $entry.FullName; depth = ($current.depth + 1) })
                continue
            }
            $files++
            if ($files -gt $MaxFiles) { throw 'Existing harness inventory file limit exceeded.' }
            if ($entry.Extension -ieq '.md' -and $entry.Length -gt 0) { $entry.FullName }
        }
    }
}

function Get-SetupExistingHarness {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][ValidateSet('User', 'Project')][string] $Scope,
        [Parameter(Mandatory = $true)][string] $ClaudeConfigRoot,
        [string] $ProjectRoot,
        [object] $ExistingRegistration,
        [int] $MaxFiles = 20000,
        [int] $MaxDepth = 32,
        [int] $MaxVisited = 100000,
        [long] $MaxSettingsBytes = 1048576
    )

    $configFull = Get-SetupFullPath -Path $ClaudeConfigRoot
    $projectFull = ''
    $scopeRoot = $configFull
    $settingsRoot = $configFull
    $instructionPaths = @((Join-Path $configFull 'CLAUDE.md'), (Join-Path $configFull 'CLAUDE.local.md'))
    $settingsPaths = @((Join-Path $configFull 'settings.json'))
    if ($Scope -eq 'Project') {
        if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { throw 'ProjectRoot is required for a Project harness inventory.' }
        $projectFull = Get-SetupFullPath -Path $ProjectRoot
        $scopeRoot = $projectFull
        $settingsRoot = Join-Path $projectFull '.claude'
        $instructionPaths = @(
            (Join-Path $projectFull 'CLAUDE.md'), (Join-Path $projectFull 'CLAUDE.local.md'),
            (Join-Path $settingsRoot 'CLAUDE.md'), (Join-Path $settingsRoot 'CLAUDE.local.md')
        )
        $settingsPaths = @((Join-Path $settingsRoot 'settings.json'), (Join-Path $settingsRoot 'settings.local.json'))
    }
    Assert-SetupPathHasNoReparsePoint -Path $scopeRoot -Name 'Existing harness selected scope'
    $items = New-Object Collections.ArrayList
    $replacementFiles = New-Object Collections.ArrayList
    $hookSettingsPaths = New-Object Collections.ArrayList
    $inherited = New-Object Collections.ArrayList
    $notes = New-Object Collections.ArrayList
    foreach ($instructionPath in $instructionPaths) {
        Assert-SetupPathHasNoReparsePoint -Path $instructionPath -Name 'Existing harness instruction'
        if (-not (Test-Path -LiteralPath $instructionPath)) { continue }
        $entry = Get-Item -LiteralPath $instructionPath -Force -ErrorAction Stop
        if ($entry.PSIsContainer) { throw "Existing harness instruction must be a file: $instructionPath" }
        if ($entry.Length -eq 0) { continue }
        $null = $replacementFiles.Add($entry.FullName)
        $null = $items.Add([pscustomobject]@{ kind = 'instruction'; path = $entry.FullName; label = 'Claude instruction file' })
    }
    $rulesRoot = Join-Path $settingsRoot 'rules'
    foreach ($rulePath in @(Get-SetupHarnessRuleFiles -Root $rulesRoot -MaxFiles $MaxFiles -MaxDepth $MaxDepth -MaxVisited $MaxVisited)) {
        $null = $replacementFiles.Add($rulePath)
        $null = $items.Add([pscustomobject]@{ kind = 'rule'; path = $rulePath; label = 'Claude Markdown rule' })
    }
    foreach ($settingsPath in $settingsPaths) {
        if (Get-SetupHarnessSettingsHasHooks -Path $settingsPath -MaxBytes $MaxSettingsBytes) {
            $fullSettingsPath = Get-SetupFullPath -Path $settingsPath
            $null = $hookSettingsPaths.Add($fullSettingsPath)
            $null = $items.Add([pscustomobject]@{ kind = 'hooks'; path = $fullSettingsPath; label = 'Claude settings hooks (other fields preserved)' })
        }
    }
    if ($null -ne $ExistingRegistration) {
        $null = $items.Add([pscustomobject]@{ kind = 'company-agent-registration'; path = $scopeRoot; label = 'Existing Company Agent installation in selected scope' })
    }

    if ($Scope -eq 'Project') {
        # Do not recursively scan parent projects, user history, or plugin caches.
        # Presence-only inherited entries are advisory: they are never targets and
        # must not cause unrelated malformed settings or links to block this scope.
        $inheritedCandidates = New-Object Collections.ArrayList
        foreach ($relative in @('CLAUDE.md', 'CLAUDE.local.md', 'rules', 'settings.json')) {
            $null = $inheritedCandidates.Add([pscustomobject]@{ kind = 'user-resource'; path = (Join-Path $configFull $relative); label = 'User-wide resource; outside selected project, preserved' })
        }
        $ancestor = Split-Path -Parent $projectFull
        $ancestorCount = 0
        while (-not [string]::IsNullOrWhiteSpace($ancestor) -and $ancestorCount -lt 32) {
            foreach ($relative in @('CLAUDE.md', 'CLAUDE.local.md', '.claude\CLAUDE.md', '.claude\CLAUDE.local.md', '.claude\rules')) {
                $null = $inheritedCandidates.Add([pscustomobject]@{ kind = 'ancestor-resource'; path = (Join-Path $ancestor $relative); label = 'Ancestor instruction resource; outside selected project, preserved' })
            }
            $ancestorCount++
            $nextAncestor = Split-Path -Parent $ancestor
            if ($nextAncestor -ieq $ancestor) { break }
            $ancestor = $nextAncestor
        }
        foreach ($candidate in $inheritedCandidates) {
            if (Test-Path -LiteralPath $candidate.path -ErrorAction SilentlyContinue) {
                $null = $inherited.Add($candidate)
                $null = $notes.Add(($candidate.label + ': ' + $candidate.path))
            }
        }
        if ($ancestorCount -ge 32 -and -not [string]::IsNullOrWhiteSpace($ancestor)) { $null = $notes.Add('Ancestor resource check was capped at 32 directories; no inherited resources are changed.') }
    }
    $null = $notes.Add('Plugin-provided and organization-managed rules/hooks are not scanned or disabled. Review conflicting plugins or managed policies separately.')
    return [pscustomobject]@{
        scope = $Scope; scopeRoot = $scopeRoot; claudeConfigRoot = $configFull; projectRoot = $projectFull
        detected = ($items.Count -gt 0); items = @($items.ToArray())
        hasCompanyAgent = ($null -ne $ExistingRegistration)
        hasCustomHarness = ($replacementFiles.Count -gt 0 -or $hookSettingsPaths.Count -gt 0)
        installedCoreVersion = Get-SetupDisplayVersion -Value (Get-SetupPropertyValue -Object $ExistingRegistration -Name 'coreVersion')
        installedKnowledgeVersion = Get-SetupDisplayVersion -Value (Get-SetupPropertyValue -Object $ExistingRegistration -Name 'knowledgeVersion')
        replacementFiles = [string[]]@($replacementFiles.ToArray()); hookSettingsPaths = [string[]]@($hookSettingsPaths.ToArray())
        inherited = @($inherited.ToArray()); inheritedNotes = [string[]]@($notes.ToArray())
        preserved = @('Model/provider settings', 'MCP configuration', 'Personal Memory and Company Agent state', 'Standalone Skills', 'Resources outside the selected scope', 'Plugin and managed-policy settings')
    }
}

function Get-SetupDisplayVersion {
    param([AllowNull()][object] $Value)
    if ($Value -is [string] -and $Value -cmatch '^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$') { return $Value }
    return 'unknown'
}

function Get-SetupInstallationIntent {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object] $Inventory,
        [string] $TargetCoreVersion,
        [string] $TargetKnowledgeVersion
    )
    $owned = [bool](Get-SetupPropertyValue -Object $Inventory -Name 'hasCompanyAgent')
    $oldCore = Get-SetupDisplayVersion -Value (Get-SetupPropertyValue -Object $Inventory -Name 'installedCoreVersion')
    $oldKnowledge = Get-SetupDisplayVersion -Value (Get-SetupPropertyValue -Object $Inventory -Name 'installedKnowledgeVersion')
    $newCore = Get-SetupDisplayVersion -Value $TargetCoreVersion
    $newKnowledge = Get-SetupDisplayVersion -Value $TargetKnowledgeVersion
    $operation = 'install'
    if ($owned) {
        $operation = 'update'
        if ($oldCore -cne 'unknown' -and $oldCore -ceq $newCore -and $oldKnowledge -ceq $newKnowledge) { $operation = 'reapply' }
        $oldNumeric = $null; $newNumeric = $null
        if ([version]::TryParse($oldCore, [ref]$oldNumeric) -and [version]::TryParse($newCore, [ref]$newNumeric) -and $newNumeric -lt $oldNumeric) {
            throw 'This package is older than the installed Company Agent. Use the current or a newer package; ordinary setup does not downgrade an installation.'
        }
        $oldNumeric = $null; $newNumeric = $null
        if ($oldCore -ceq $newCore -and [version]::TryParse($oldKnowledge, [ref]$oldNumeric) -and [version]::TryParse($newKnowledge, [ref]$newNumeric) -and $newNumeric -lt $oldNumeric) {
            throw 'This package contains an older knowledge pack for the installed Core version. Keep the current installation and ask the package owner for a compatible release.'
        }
    }
    return [pscustomobject]@{
        operation = $operation; hasCompanyAgent = $owned
        previousCoreVersion = $(if ($owned) { $oldCore } else { $null })
        previousKnowledgeVersion = $(if ($owned) { $oldKnowledge } else { $null })
        coreVersion = $newCore; knowledgeVersion = $newKnowledge
    }
}

function Write-SetupCompanyAgentUpdateSummary {
    param([Parameter(Mandatory = $true)][object] $Intent, [Parameter(Mandatory = $true)][object] $Inventory, [switch] $ReplaceCustomHarness)
    Write-Host ''
    if ($Intent.operation -eq 'reapply') { Write-Host '이 범위에는 같은 버전의 Company Agent가 이미 설치되어 있습니다.' -ForegroundColor Cyan }
    else { Write-Host '이 범위에 설치된 Company Agent를 찾았습니다. 공통 구성 업데이트를 준비합니다.' -ForegroundColor Cyan }
    Write-Host ("범위: {0}" -f $Inventory.scopeRoot)
    Write-Host ("Company Agent: {0} -> {1}" -f $Intent.previousCoreVersion, $Intent.coreVersion)
    Write-Host ("회사 지식: {0} -> {1}" -f $Intent.previousKnowledgeVersion, $Intent.knowledgeVersion)
    Write-Host '개인 Memory·학습 이력·Skill·Knowledge, 모델 설정과 MCP 연결은 그대로 유지합니다.'
    if ($ReplaceCustomHarness) { Write-Host '명시적인 Replace 선택: 기존 CLAUDE.md·규칙·Hook도 백업 후 비활성화합니다. 이를 보존하는 일반 업데이트는 Update입니다.' -ForegroundColor Yellow }
    else { Write-Host '업데이트 전 백업하며, 현재 추가된 CLAUDE.md·규칙·Hook도 비활성화하지 않습니다.' }
    if (-not $ReplaceCustomHarness -and [bool](Get-SetupPropertyValue -Object $Inventory -Name 'hasCustomHarness')) {
        Write-Host '추가 사용자 규칙·Hook이 함께 있습니다. 업데이트와 별개이므로 보존합니다.'
    }
}

function Resolve-SetupExistingHarnessAction {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object] $Inventory,
        [ValidateSet('Ask', 'Keep', 'Replace', 'Update')][string] $Action = 'Ask',
        [string] $TargetCoreVersion,
        [string] $TargetKnowledgeVersion,
        [switch] $NonInteractive,
        [switch] $DryRun
    )

    $owned = [bool](Get-SetupPropertyValue -Object $Inventory -Name 'hasCompanyAgent')
    if ($Action -eq 'Update' -and -not $owned) { throw 'Update requires a recognized Company Agent installation in the selected scope; it cannot replace another harness.' }
    if (-not [bool](Get-SetupPropertyValue -Object $Inventory -Name 'detected')) { return 'Install' }
    if ($Action -eq 'Keep') { return 'Keep' }
    if ($Action -eq 'Update') { return 'Update' }
    if ($Action -eq 'Replace') { return 'Replace' }
    if ($NonInteractive -or $DryRun) { return 'InputRequired' }

    if ($owned) {
        $intent = Get-SetupInstallationIntent -Inventory $Inventory -TargetCoreVersion $TargetCoreVersion -TargetKnowledgeVersion $TargetKnowledgeVersion
        Write-SetupCompanyAgentUpdateSummary -Intent $intent -Inventory $Inventory
        if ($intent.operation -eq 'reapply') { Write-Host '1. 백업 후 같은 버전 다시 적용·복구 (개인 설정 유지, 기본값)' }
        else { Write-Host '1. 백업 후 Company Agent 공통 구성 업데이트 (개인 설정 유지, 기본값)' }
        Write-Host '2. 현재 버전 유지하고 종료 (변경하지 않음)'
        while ($true) {
            $choice = Read-Host '번호를 선택해 주세요 [1/2, Enter=1]'
            if ([string]::IsNullOrWhiteSpace($choice) -or $choice.Trim() -eq '1') { return 'Update' }
            if ($choice.Trim() -eq '2') { return 'Keep' }
            Write-Host '1 또는 2를 입력해 주세요.' -ForegroundColor Yellow
        }
    }

    Write-Host ''
    Write-Host '선택한 설치 범위에 기존 하네스가 있습니다.' -ForegroundColor Yellow
    $scopeRoot = [string](Get-SetupPropertyValue -Object $Inventory -Name 'scopeRoot')
    Write-Host ("범위: {0}" -f $scopeRoot)
    $inventoryItems = @(Get-SetupPropertyValue -Object $Inventory -Name 'items')
    foreach ($item in @($inventoryItems | Select-Object -First 12)) { Write-Host (" - {0}: {1}" -f $item.kind, $item.path) }
    if ($inventoryItems.Count -gt 12) { Write-Host (" - 이외 {0}개 항목" -f ($inventoryItems.Count - 12)) }
    Write-Host '모델 설정, MCP, 개인 Memory와 Skill은 유지합니다.'
    Write-Host '다른 범위의 규칙 및 Plugin/조직 정책 Hook은 자동으로 비활성화하지 않습니다.'
    Write-Host '1. 기존 하네스 유지 (설치하지 않음, 기본값)'
    Write-Host '2. 기존 규칙·Hook을 자동 백업하고 비활성화한 뒤 Company Agent 설치/업데이트'
    while ($true) {
        $choice = Read-Host '번호를 선택해 주세요 [1/2, Enter=1]'
        if ([string]::IsNullOrWhiteSpace($choice) -or $choice.Trim() -eq '1') { return 'Keep' }
        if ($choice.Trim() -eq '2') { return 'Replace' }
        Write-Host '1 또는 2를 입력해 주세요.' -ForegroundColor Yellow
    }
}
