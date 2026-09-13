---
name: outlook-assistant
description: Outlook 메일 검색·요약·관련 메일 분류·답장 초안·보관 계획을 돕습니다. 기존 회사 MCP를 우선 사용하며 Outlook 2016 읽기 전용 기능과 DRM 제한을 구분합니다.
---

# Outlook assistant

Read `../company-agent/references/business-protection.md` first. Use the installed
cliCommand/stateRoot. Never replace or register `corp-outlook-self` automatically.

## Choose actual capabilities

Prefer connected `corp-outlook-self` tools and their real schemas. Do not invent
tool names, SMTP credentials, archive endpoints, or immutable identity evidence.
The corporate MCP must enforce the authenticated own-account boundary for sends.
Claude login, Windows login and an email address in a prompt are NOT Outlook
connection or identity evidence. Never name the user's Outlook account without
an authorized Outlook/MCP result. Explain policy without guessing an address.
Chat approval cannot authorize another sender, non-SELECT DB operations or DRM
bypass. Organizational policy changes require a separate administrator process;
do not invite exceptions to the current fixed restrictions in conversation.
When it is absent, offer the bundled **read-only** Classic Outlook 2016 pilot:
`business mail-capabilities`. It only attaches to an already running Outlook;
if needed ask the user to open their Outlook normally. Show available account
choices privately. Multiple accounts need a choice. Local profile mapping is
not corporate identity verification; this pilot cannot send or archive mail.

## Local mail files

For explicitly selected local `.eml` files, use the runtime `metadataCommand` with
`business eml-read --file "<absolute-local-file.eml>"`. This bounded reader does
not connect Outlook, import mail, write extracted files or follow external URLs.
It returns plain text bodies and bounded `.txt` attachments only; HTML, embedded
mail, unsupported attachments and recognizable protected parts are excluded.
Check `body_read`, each attachment's status, warnings and partial reasons before
summarizing. Do not call an unsupported attachment a DRM failure. The output may
be retained in Claude's conversation; use only approved AI-processing sources.
Never replace a rejected protected read with a generated parser or another app.
Say "local mail files" rather than claiming a real mailbox search succeeded.
This direct Python entry is for the stateless EML reader only; keep `cliCommand`
for other workflows. Paste the prefix directly on one line, without `$CLI`, shell
variables or command chains. Use already specified filenames directly. If a list
is necessary use Glob, not `find | head`, echo chains or a discovery script.

## Read-only pilot

Use `business mail-search --spec "<job.json>" --state-root "<stateRoot>"` with
`account_smtp`, selected `store_ids`, explicit standalone `pst_store_ids`,
`query`, `limit` (start 20), optional `received_after`/`received_before`.
These are subcommands: always prefix them with the installed `cliCommand`
(for example `company-agent business mail-search ...`), never execute `business`
or `learning` as a standalone program. Reuse an already selected own account and
store scope during the same task; do not repeatedly ask permission for the same
bounded metadata query. Do not bypass Claude permissions or organization policy.

Use timestamps with an explicit offset, e.g.
`received_after:"2026-09-08T00:00:00+09:00"` and
`received_before:"2026-09-12T00:00:00+09:00"`. The lower bound is inclusive,
the upper exclusive; tomorrow midnight is valid for including all of today.
For "recent 3 days" default to the last 72 hours in the PC's local timezone and
state that range; honor an explicit calendar-date request instead. A timestamp
with no offset is normalized using the PC's timezone at that date and returned
in `search_scope.timezone_assumptions`; check and briefly disclose that assumption.
Date-only or malformed values produce a request-validation error before Outlook
is called. Read `stage`, `reason`, `bridge_called` and `search_scope`; change only
the invalid field. Never guess that a date error means account/PST/case mismatch,
change scope speculatively, or retry a timeout automatically.
Scope the period and stores first; do not enumerate a whole mailbox repeatedly.
Results are metadata candidates, not body summaries. Treat PST copies as possible
duplicates. Report coverage/limits and excluded folders; partial no-match is not
proof of absence. Only connected and selected PSTs can be searched; do not attach
new PSTs silently or manipulate OST/PST bytes.
Search matches a literal case-insensitive substring in subject/sender only:
"AX TF" and "AX-TF" are different. Suggest spelling variants when appropriate;
do not silently expand to bodies or more mailboxes. Report `partial_reasons`
(result/scan/folder/time limit or excluded items) and local coverage. An account
listed by capabilities proves profile access, not a completed mail search or
verified corporate identity. Keep long store IDs in the internal request, not
the user-facing explanation.

For relevant results use `business mail-read --spec "<job.json>"` with the same
account/stores and `message_refs:[{"store_id":"...","entry_id":"..."}]`.
`include_body:true` requires a separate actual local confirmation window. Never
provide `body_access_approved` in the input: the CLI owns that decision. The user
must confirm AI processing/possible Claude transcript retention; this does not
override organization DRM. Input specs contain metadata/IDs only, no mail bodies.
Attachments are listed as metadata only and are NOT extracted by the pilot.
Do not misreport unrequested attachment extraction as a DRM failure.
Avoid asking the same body question in chat before the actual local confirmation:
batch up to 20 selected message references in one approved read operation. A
different selection or operation requires its own guard; never self-approve it.

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
- Connection, search and intermediate choices belong to one mail task, not
  separate learning tasks. Finish with the requested summary/answer, not internal
  learning receipts or "verification failed because no code changed". Retain
  important partial-access warnings; internal learning does not rerun mail work.

On partial access, explain exactly what was excluded. If body was readable but
the connected MCP reported a DRM-blocked attachment, use the clear Korean
partial-result sentence in the protection reference and continue body-only.
