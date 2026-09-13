param([Parameter(Mandatory=$true)][ValidateSet('capabilities','search','read')][string]$Operation)

# Optional READ-ONLY bridge. Never start Outlook, change policy, or mutate mail.
# All messages are fixed codes; Python supplies user-facing Korean explanations.
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$script:watch = [Diagnostics.Stopwatch]::StartNew()
$script:outlook = $null
$script:session = $null

function Assert-Time {
    if ($script:watch.Elapsed.TotalSeconds -gt 25) { throw 'read_budget_exceeded' }
}
function Limit-Text([object]$Value, [int]$Limit) {
    $text = [string]$Value
    if ($text.Length -gt $Limit) { return $text.Substring(0, $Limit) }
    return $text
}
function Test-Id([object]$Value) {
    return ($Value -is [string] -and $Value -cmatch '^[A-Fa-f0-9]{8,4096}$')
}
function Get-FailureStatus($Exception) {
    $current=$Exception
    for ($depth=0; $depth -lt 6 -and $null -ne $current; $depth++) {
        if ($current.HResult -eq -2147024891) { return 'permission_denied' }
        $current=$current.InnerException
    }
    return 'unknown'
}
function Get-BridgeFailure([string]$Code) {
    # Fixed codes distinguish identity/scope/input failures without exposing COM
    # exception text, subjects, credentials, or filesystem paths.
    if ($Code -eq 'invalid_request') { return @{status='invalid_request'; reason='bridge_request_invalid'} }
    if ($Code -in @('store_not_allowed','body_permission_required')) { return @{status='permission_denied'; reason=$Code} }
    if ($Code -in @('account_mapping_required','store_selection_required','folder_selection_required','store_not_open')) {
        return @{status='connection_required'; reason=$Code}
    }
    if ($Code -eq 'read_budget_exceeded') { return @{status='unknown'; reason='read_budget_exceeded'} }
    return @{status='connection_required'; reason='classic_outlook_profile_unavailable'}
}
function Test-ReadPermission($Item) {
    try {
        if ([int]$Item.Class -ne 43) { return 'unknown' }
        # This is Microsoft IRM only, NOT detection of third-party document DRM.
        $permission=$Item.Permission
        if ($null -eq $permission) { return 'unknown' }
        if ([int]$permission -ne 0 -or -not [string]::IsNullOrEmpty([string]$Item.PermissionTemplateGuid)) {
            return 'blocked'
        }
        return 'ok'
    } catch { return 'unknown' }
}
function Get-ItemMetadata($Item, [string]$StoreId, [string]$EntryId) {
    $result = @{ store_id=$StoreId; entry_id=$EntryId; status=(Test-ReadPermission $Item) }
    if ($result.status -ne 'ok') {
        $result.protection_status = $(if ($result.status -eq 'blocked') {'restricted'} else {'unknown'})
        return $result
    }
    try {
        $result.subject = Limit-Text $Item.Subject 500
        $result.sender_name = Limit-Text $Item.SenderName 200
        $result.sender_address = Limit-Text $Item.SenderEmailAddress 320
        $result.received_at = $Item.ReceivedTime.ToUniversalTime().ToString('o')
        $result.size = [long]$Item.Size
        $result.attachment_count = [int]$Item.Attachments.Count
        $result.irm = 'unrestricted_reported_by_outlook'
        $result.external_drm = 'not_detectable'
        return $result
    } catch { return @{store_id=$StoreId; entry_id=$EntryId; status='unknown'} }
}
function Get-ProfileContext {
    # GetActiveObject cannot start another Outlook profile or login session.
    $script:outlook = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application')
    $script:session = $script:outlook.Session
    $accounts = New-Object 'System.Collections.Generic.List[object]'
    $stores = New-Object 'System.Collections.Generic.List[object]'
    if ($script:session.Accounts.Count -gt 16 -or $script:session.Stores.Count -gt 64) { throw 'profile_limit' }
    for ($i=1; $i -le $script:session.Accounts.Count; $i++) {
        Assert-Time
        $account = $script:session.Accounts.Item($i)
        $delivery = $account.DeliveryStore
        if ($null -ne $delivery) {
            $accounts.Add(@{smtp=([string]$account.SmtpAddress).ToLowerInvariant();
                display_name=(Limit-Text $account.DisplayName 200); delivery_store_id=[string]$delivery.StoreID})
        }
    }
    for ($i=1; $i -le $script:session.Stores.Count; $i++) {
        Assert-Time
        $store = $script:session.Stores.Item($i)
        $isPst = $false
        try { $isPst = [string]$store.FilePath -match '(?i)\.pst$' } catch { }
        $stores.Add(@{store_id=[string]$store.StoreID; display_name=(Limit-Text $store.DisplayName 200);
            is_pst=$isPst; is_open=[bool]$store.IsOpen; object=$store})
    }
    return @{accounts=@($accounts.ToArray()); stores=@($stores.ToArray())}
}
function Get-SelectedStores($Spec, $Context) {
    if ($Spec.account_smtp -isnot [string] -or $Spec.account_smtp.Length -gt 320) { throw 'invalid_request' }
    $matches = @($Context.accounts | Where-Object { $_.smtp -ieq $Spec.account_smtp })
    if ($matches.Count -ne 1) { throw 'account_mapping_required' }
    $selected = @($Spec.store_ids)
    $psts = @($Spec.pst_store_ids)
    if ($selected.Count -lt 1 -or $selected.Count -gt 20 -or $psts.Count -gt 20) { throw 'invalid_request' }
    $result = @{}
    foreach ($id in $selected) {
        Assert-Time
        if (-not (Test-Id $id)) { throw 'invalid_request' }
        $candidates = @($Context.stores | Where-Object { $_.store_id -ieq $id })
        if ($candidates.Count -ne 1) { throw 'store_selection_required' }
        $candidate = $candidates[0]
        if ($id -ine $matches[0].delivery_store_id) {
            # A connected PST must be explicitly selected and not belong to a
            # different account's delivery store, even if that account is open.
            $otherOwners = @($Context.accounts | Where-Object { $_.delivery_store_id -ieq $id -and $_.smtp -ine $Spec.account_smtp })
            if (-not $candidate.is_pst -or $psts -notcontains $id -or $otherOwners.Count -gt 0) { throw 'store_not_allowed' }
        }
        if (-not $candidate.is_open) { throw 'store_not_open' }
        $result[$id] = $candidate.object
    }
    foreach ($id in $psts) {
        if (-not (Test-Id $id) -or $selected -notcontains $id) { throw 'invalid_request' }
    }
    return $result
}
function Read-SelectedMail($Spec, $Selected) {
    $refs = @($Spec.message_refs)
    if ($refs.Count -lt 1 -or $refs.Count -gt 20) { throw 'invalid_request' }
    if ($Spec.include_body -isnot [bool] -or $Spec.body_access_approved -isnot [bool]) { throw 'invalid_request' }
    if ($Spec.include_body -and -not $Spec.body_access_approved) { throw 'body_permission_required' }
    if ($Spec.body_char_limit -lt 1 -or $Spec.body_char_limit -gt 12000) { throw 'invalid_request' }
    $items = New-Object 'System.Collections.Generic.List[object]'
    $partial = $false
    foreach ($ref in $refs) {
        if ($script:watch.Elapsed.TotalSeconds -gt 25) { $partial=$true; break }
        if (-not (Test-Id $ref.store_id) -or -not (Test-Id $ref.entry_id) -or -not $Selected.ContainsKey($ref.store_id)) {
            throw 'store_not_allowed'
        }
        try {
            $item = $script:session.GetItemFromID($ref.entry_id, $ref.store_id)
            if ([string]$item.Parent.StoreID -ine $ref.store_id) { throw 'store_not_allowed' }
            $record = Get-ItemMetadata $item $ref.store_id $ref.entry_id
            if ($record.status -eq 'ok') {
                $attachments = New-Object 'System.Collections.Generic.List[object]'
                for ($a=1; $a -le [Math]::Min([int]$item.Attachments.Count, 30); $a++) {
                    Assert-Time
                    try {
                        $attachment = $item.Attachments.Item($a)
                        $attachments.Add(@{name=(Limit-Text $attachment.FileName 200); size=[long]$attachment.Size;
                            status='metadata_only'; content_access='not_attempted'})
                    } catch { $attachments.Add(@{status='unknown'; content_access='not_attempted'}) }
                }
                $record.attachments = @($attachments.ToArray())
                $record.attachments_truncated = ([int]$item.Attachments.Count -gt 30)
                $record.body_status = 'not_requested'
                if ($Spec.include_body) {
                    try {
                        $body = [string]$item.Body
                        $record.body = Limit-Text $body ([int]$Spec.body_char_limit)
                        $record.body_truncated = ($body.Length -gt [int]$Spec.body_char_limit)
                        $record.body_status = 'ok'
                    } catch {
                        # No alternate HTML, raw MAPI, file, OCR, or screenshot fallback.
                        $record.body_status = Get-FailureStatus $_.Exception
                        $record.status = $record.body_status
                        $record.protection_status = 'unknown'
                    }
                }
            }
            if ($record.status -ne 'ok') { $partial=$true }
            $items.Add($record)
        } catch {
            $partial=$true
            $items.Add(@{store_id=$ref.store_id; entry_id=$ref.entry_id; status='unknown'})
        }
    }
    return @{status=$(if ($partial) {'partial'} else {'ok'}); items=@($items.ToArray()); requested_count=$refs.Count;
        completed_count=$items.Count; complete=(-not $partial)}
}
function Search-SelectedMail($Spec, $Selected) {
    if ($Spec.limit -lt 1 -or $Spec.limit -gt 50 -or $Spec.scan_limit -lt 1 -or $Spec.scan_limit -gt 2000 -or
        $Spec.folder_limit -lt 1 -or $Spec.folder_limit -gt 100 -or $Spec.query -isnot [string] -or
        $Spec.query.Length -gt 200 -or $Spec.include_subfolders -isnot [bool]) { throw 'invalid_request' }
    $folderIds = @($Spec.folder_ids)
    if ($folderIds.Count -gt 50) { throw 'invalid_request' }
    $queue = New-Object System.Collections.Queue
    $partial=$false; $scanned=0; $folders=0; $blocked=0; $unknown=0; $protectionUnknown=0
    $reasons=New-Object 'System.Collections.Generic.List[string]'
    $after=$null; $before=$null
    if ($Spec.received_after) { $after=[DateTimeOffset]::Parse($Spec.received_after).UtcDateTime }
    if ($Spec.received_before) { $before=[DateTimeOffset]::Parse($Spec.received_before).UtcDateTime }
    if ($folderIds.Count -gt 0) {
        foreach ($folderId in $folderIds) {
            if (-not (Test-Id $folderId)) { throw 'invalid_request' }
            $found=$false
            foreach ($storeId in $Selected.Keys) {
                try {
                    $folder=$script:session.GetFolderFromID($folderId, $storeId)
                    if ([string]$folder.StoreID -ieq $storeId) { $queue.Enqueue(@{folder=$folder; store_id=$storeId}); $found=$true; break }
                } catch { }
            }
            if (-not $found) { throw 'folder_selection_required' }
        }
    } else {
        foreach ($storeId in $Selected.Keys) { $queue.Enqueue(@{folder=$Selected[$storeId].GetRootFolder(); store_id=$storeId}) }
    }
    $items=New-Object 'System.Collections.Generic.List[object]'
    $visited=@{}
    :folders while ($queue.Count -gt 0) {
        if ($folders -ge $Spec.folder_limit) { $partial=$true; $reasons.Add('folder_limit'); break }
        if ($scanned -ge $Spec.scan_limit) { $partial=$true; $reasons.Add('scan_limit'); break }
        if ($script:watch.Elapsed.TotalSeconds -gt 25) { $partial=$true; $reasons.Add('time_limit'); break }
        $next=$queue.Dequeue(); $folder=$next.folder; $storeId=[string]$next.store_id
        try {
            $folderKey=$storeId + ':' + [string]$folder.EntryID
            if ($visited.ContainsKey($folderKey)) { continue }
            $visited[$folderKey]=$true; $folders++
            $collection=$folder.Items
            # Sorting this local Items view does not change or save any mail item.
            $sorted=$false
            try { $collection.Sort('[ReceivedTime]', $true); $sorted=$true } catch { }
            $itemCount=[int]$collection.Count
            for ($i=1; $i -le $itemCount; $i++) {
                if ($scanned -ge $Spec.scan_limit) { $partial=$true; $reasons.Add('scan_limit'); break folders }
                if ($script:watch.Elapsed.TotalSeconds -gt 25) { $partial=$true; $reasons.Add('time_limit'); break folders }
                $scanned++
                try {
                    $item=$collection.Item($i)
                    if ([int]$item.Class -ne 43) { continue }
                    $record=Get-ItemMetadata $item $storeId ([string]$item.EntryID)
                    if ($record.status -eq 'blocked') { $blocked++; continue }
                    if ($record.status -ne 'ok') {
                        $unknown++
                        if ($record.ContainsKey('protection_status') -and $record.protection_status -eq 'unknown') { $protectionUnknown++ }
                        continue
                    }
                    $received=[DateTimeOffset]::Parse($record.received_at).UtcDateTime
                    # Only a successfully sorted local Items view justifies
                    # skipping its older tail. Still visit child folders.
                    if ($sorted -and $null -ne $after -and $received -lt $after) { break }
                    if (($null -ne $after -and $received -lt $after) -or ($null -ne $before -and $received -ge $before)) { continue }
                    $haystack=$record.subject + ' ' + $record.sender_name + ' ' + $record.sender_address
                    if ($Spec.query -and $haystack.IndexOf($Spec.query, [StringComparison]::OrdinalIgnoreCase) -lt 0) { continue }
                    $record.folder_id=[string]$folder.EntryID
                    $items.Add($record)
                    if ($items.Count -ge $Spec.limit) { $partial=$true; $reasons.Add('result_limit'); break folders }
                } catch { $unknown++ }
            }
            if ($Spec.include_subfolders) {
                $children=$folder.Folders
                for ($f=1; $f -le $children.Count; $f++) {
                    if ($queue.Count + $folders -ge $Spec.folder_limit) { $partial=$true; $reasons.Add('folder_limit'); break }
                    $queue.Enqueue(@{folder=$children.Item($f); store_id=$storeId})
                }
            }
        } catch { $unknown++; $partial=$true; $reasons.Add('folder_access_failed') }
    }
    if ($blocked -gt 0 -or $unknown -gt 0) { $partial=$true }
    if ($blocked -gt 0) { $reasons.Add('protected_items_excluded') }
    if ($unknown -gt 0) { $reasons.Add('items_access_unverified') }
    return @{status=$(if ($partial) {'partial'} else {'ok'}); items=@($items.ToArray());
        searched_store_ids=@($Selected.Keys); scanned_count=$scanned; folders_scanned=$folders;
        blocked_count=$blocked; unknown_count=$unknown; protection_unknown_count=$protectionUnknown; complete=(-not $partial);
        search_fields=@('subject','sender_name','sender_address','received_at');
        coverage='selected_accessible_local_items_only'; server_completeness='not_verified';
        partial_reasons=@($reasons.ToArray() | Select-Object -Unique);
        ordering='newest_first_per_folder_not_global'}
}

try {
    $raw=[Console]::In.ReadToEnd()
    if ($raw.Length -gt 32768) { throw 'invalid_request' }
    $spec=ConvertFrom-Json -InputObject $raw
    $context=Get-ProfileContext
    if ($Operation -eq 'capabilities') {
        $publicStores=@($context.stores | ForEach-Object { @{store_id=$_.store_id; display_name=$_.display_name; is_pst=$_.is_pst; is_open=$_.is_open} })
        $result=@{status='ok'; adapter='classic_outlook_com_read_only'; accounts=$context.accounts; stores=$publicStores;
            supported_operations=@('capabilities','search','read'); search_fields=@('subject','sender_name','sender_address','received_at');
            body_requires_guard_approval=$true; attachments='metadata_only'; mailbox_identity_verified=$false;
            mutation_transport='separately_managed_corp_outlook_self'}
    } else {
        $selected=Get-SelectedStores $spec $context
        if ($Operation -eq 'search') { $result=Search-SelectedMail $spec $selected }
        else { $result=Read-SelectedMail $spec $selected }
    }
} catch {
    $code=[string]$_.Exception.Message
    $result=Get-BridgeFailure $code
} finally {
    # Release only this process's references; never quit the user's Outlook.
    if ($null -ne $script:session -and [Runtime.InteropServices.Marshal]::IsComObject($script:session)) {
        try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($script:session) } catch { }
    }
    if ($null -ne $script:outlook -and [Runtime.InteropServices.Marshal]::IsComObject($script:outlook)) {
        try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($script:outlook) } catch { }
    }
}
[Console]::Write(($result | ConvertTo-Json -Depth 12 -Compress))
