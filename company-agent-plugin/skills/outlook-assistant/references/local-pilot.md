# Read-only Classic Outlook pilot

Use installed `cliCommand` before `business mail-capabilities`, `mail-search`, or
`mail-read`; never execute `business` alone. Capabilities attaches only to already
running Classic Outlook. If unavailable, let the user open Outlook normally.
Reuse the selected account/stores. Multiple unresolved accounts require one choice.
Local profile mapping is not corporate identity verification; no send/archive.

Search: `business mail-search --spec "<job.json>" --state-root "<stateRoot>"`.
Spec: `account_smtp`, `store_ids`, explicit standalone `pst_store_ids`, `query`,
optional `folder_ids`, `include_subfolders`, `received_after`, `received_before`.
Default `limit:20`, `scan_limit:500`, `folder_limit:30`; hard maxima 50/2000/100.
Search matches literal subject/sender text only, case-insensitive: `AX TF` differs
from `AX-TF`. No body search, PST attachment or repeated whole-mailbox scan.

Dates include times and offsets: `2026-09-08T00:00:00+09:00`. Start is inclusive,
end exclusive; tomorrow midnight can include all of today. “Recent 3 days” means
last 72 hours in the PC timezone unless the user asked for calendar dates. State
the range briefly. Read `search_scope.timezone_assumptions` for offsetless input.
For `invalid_request`, inspect `stage`, `reason`, `bridge_called`; repair only the
invalid field. A date error is not evidence of a wrong account/PST. No timeout retry.

Read only relevant IDs with the same account/stores and
`message_refs:[{"store_id":"...","entry_id":"..."}]`, `include_body:true`.
Start with at most 5 needed messages; an explicit selection up to 20 is supported.
The actual local confirmation window approves that read's AI processing and
possible Claude transcript retention. Do not ask the same body question in chat
first and never supply `body_access_approved`; the CLI owns it. A changed selection
or operation needs its own guard. Specs contain IDs/options, no body text.

`body_char_limit` defaults to 4000 (max 12000); `total_body_char_limit` defaults
to 12000 (max 24000). Once exhausted, later bodies are not accessed. Outlook's
Body property itself returns a complete message locally; these limits bound what
is returned, not a streaming read inside Outlook. Attachments remain metadata only.
`result_char_limit` defaults to 32000 (4096–64000): the complete escaped CLI JSON,
including metadata/newline. It can further shorten bodies or omit whole items;
message IDs are never clipped. `output_budget` gives returned/omitted counts and
body characters. Inspect `body_status`, `body_truncated`, `partial_reasons` and
coverage. `body_read_count` is accessed bodies, not proof their full text survived
the output budget. Do not silently raise limits/refetch or call omitted text read.
Local results cover selected accessible items, not server-wide completeness;
sorting is newest-first within each folder, not globally. PST copies may duplicate.
