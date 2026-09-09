---
name: outlook-assistant
description: Search and summarize current or archived Outlook mail, group related mail, draft replies and plan mailbox cleanup. Uses existing corporate MCP first; includes an explicit read-only Outlook 2016 pilot and honest DRM partial results.
---

# Outlook assistant

Read `../company-agent/references/business-protection.md` first. Use the installed
cliCommand/stateRoot. Never replace or register `corp-outlook-self` automatically.

## Choose actual capabilities

Prefer connected `corp-outlook-self` tools and their real schemas. Do not invent
tool names, SMTP credentials, archive endpoints, or immutable identity evidence.
The corporate MCP must enforce the authenticated own-account boundary for sends.
When it is absent, offer the bundled **read-only** Classic Outlook 2016 pilot:
`business mail-capabilities`. It only attaches to an already running Outlook;
if needed ask the user to open their Outlook normally. Show available account
choices privately. Multiple accounts need a choice. Local profile mapping is
not corporate identity verification; this pilot cannot send or archive mail.

## Read-only pilot

Use `business mail-search --spec "<job.json>" --state-root "<stateRoot>"` with
`account_smtp`, selected `store_ids`, explicit standalone `pst_store_ids`,
`query`, `limit` (start 20), optional `received_after`/`received_before`.
Scope the period and stores first; do not enumerate a whole mailbox repeatedly.
Results are metadata candidates, not body summaries. Treat PST copies as possible
duplicates. Report coverage/limits and excluded folders; partial no-match is not
proof of absence. Only connected and selected PSTs can be searched; do not attach
new PSTs silently or manipulate OST/PST bytes.

For relevant results use `business mail-read --spec "<job.json>"` with the same
account/stores and `message_refs:[{"store_id":"...","entry_id":"..."}]`.
`include_body:true` requires a separate actual local confirmation window. Never
provide `body_access_approved` in the input: the CLI owns that decision. The user
must confirm AI processing/possible Claude transcript retention; this does not
override organization DRM. Input specs contain metadata/IDs only, no mail bodies.
Attachments are listed as metadata only and are NOT extracted by the pilot.
Do not misreport unrequested attachment extraction as a DRM failure.

## User-facing work

- Summarize with source subject/date/store reference, decisions, outstanding
  requests, deadlines and uncertainty. Never invent the unread attachment.
- Group related mail in the answer without changing Outlook. Actual categories,
  folder moves, saved search folders and rule activation require a preview and
  approval through supported corporate MCP tools.
- Draft a reply in conversation. Sending through corporate MCP requires a preview
  of recipients/body/attachments and user approval; the local pilot cannot send.
- PST capacity cleanup needs real corporate MCP archive tools, destination and
  period choice, protection-preserving copy verification, separately approved
  original move and partial-result receipts. If tools are missing say connection
  is required, not that archiving completed. Copy alone does not free mailbox
  quota; server quota and local OST/PST file sizes are different.
- Never retry an ambiguous send/move blindly. Do not store mail content in Memory.

On partial access, explain exactly what was excluded. If body was readable but
the connected MCP reported a DRM-blocked attachment, use the clear Korean
partial-result sentence in the protection reference and continue body-only.
