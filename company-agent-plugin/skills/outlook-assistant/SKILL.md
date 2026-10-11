---
name: outlook-assistant
description: Outlook 메일을 목록부터 좁혀 검색하고 필요한 본문만 읽어 요약·답장 초안·정리 계획을 만듭니다. 회사 MCP 우선, 로컬 Outlook은 읽기 전용입니다.
---

# Outlook assistant

Use the installed cliCommand/stateRoot and the connected `corp-outlook-self`
tools' actual schemas. Do not register/replace a connection or invent endpoints.
Keep the user's selected account, dates, folders, query and message IDs for this
task; do not ask again or rediscover an already established scope.

## Read the smallest useful set

1. Search metadata first: IDs, subject, sender, received date, attachment count.
   Start with 20 candidates; use the schema's supported date/folder/filter/page/
   field/limit controls only. Do not request all bodies or attachment content.
   For a supplied exact message ID, skip search and read that selected message.
2. Choose relevant candidates from the metadata yourself when the request is clear.
   For an ordinary summary, start with at most 5 relevant bodies, up to 4,000
   characters each and 12,000 body characters in total. Reuse already read text.
   These are working defaults, not another question or a change to explicit scope.
3. Read only bodies needed for the requested answer. A narrow follow-up may need
   one message; a list/count request normally needs no bodies. Read an attachment
   only when explicitly relevant and supported by the approved tool/reader.
4. Stop when evidence is sufficient. Do not fetch every page, re-read complete
   threads or increase limits automatically after a partial result. If the user
   requested broader coverage, continue with supported bounded pages only for
   that purpose and report remaining coverage instead of claiming completeness.
   Corporate MCP limits are available only if its real schema supports them;
   local bridge options are not MCP arguments. If an MCP cannot select metadata
   or bound bodies/results, explain that limit before another broad read and
   use a narrower supported query or return the available metadata. Do not keep
   retrieving full-mail batches, invent truncation controls or use a new parser.

## Connection, protection and delivery

- Use authenticated own-account evidence from Outlook/MCP. Claude/Windows login
  and an address in a prompt do not prove mailbox identity. Ask an account choice
  only when genuinely missing/ambiguous; never infer another account's authority.
- If the corporate connection is absent and a local read is needed, read
  `references/local-pilot.md`. For selected `.eml` files only, read
  `references/local-eml.md`. Other tasks do not load these references.
- For protected/partial source handling, read
  `../company-agent/references/business-protection.md` only when needed. Never
  bypass DRM, substitute another copy or store mail text in Memory/Knowledge.
- Draft replies in conversation. Before sending, show actual recipients, body
  and attachments, then use the tool's real permission confirmation. Do not add
  a duplicate chat approval to the same send. Changed content/recipients need new
  confirmation; actual refusal remains binding. The local pilot cannot send.
- Grouping in an answer does not move mail. For an actual archive/move/cleanup
  request only, read `references/mail-actions.md` and use supported corporate tools.
- Return the requested answer with source subject/date and unresolved decisions.
  State how many candidates/bodies were actually read and meaningful omissions,
  including truncation. Partial no-match does not prove absence. Never summarize
  an unread attachment or equate profile access with a completed mailbox search.
  Keep IDs, limits bookkeeping and learning receipts internal unless requested.
