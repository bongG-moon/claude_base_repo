---
name: file-organizer
description: Preview and organize a selected Windows work folder with an explicit local approval window, no deletion or overwrite, and receipt-based undo. Use for downloads or folder cleanup requests.
---

# File organizer

Read `../company-agent/references/business-protection.md` first. Resolve existing
same-name preferences; use the active runtime cliCommand and stateRoot.

1. Ask only for the missing target folder. First release handles direct files in
   one local folder (at most 500 entries, each file at most 256 MiB). It groups by
   extension into 문서/표자료/발표자료/이미지/압축자료. Existing child folders,
   unclassified files, executable files and duplicates stay where they are.
   For semantic/monthly/custom grouping explain this limit; do not claim the
   fixed organizer implements it or silently run a custom shell move instead.
2. Run `business files-plan --state-root "<stateRoot>" --folder "<target>"`.
   This records a plan in personal state but does not move work files. Show the
   exact source/destination summary and exclusions, then ask execute/edit/cancel.
3. Only when execution is requested, run `business files-execute --state-root
   "<stateRoot>" --plan "<returned planId>"`. A Windows confirmation window lists
   the actual operations. The user must approve it; never simulate a click,
   supply an approval flag, bypass it, or ask them to disable security settings.
4. Report counts and failures accurately. A blocked file does not justify a retry
   through another command. Changed files/destination conflicts need a new plan.
5. On explicit undo, run `business files-undo --state-root "<stateRoot>" --plan
   "<id>"`. Explain that files changed since the move or conflicting destinations
   cannot be automatically restored. Empty category folders may remain. This is
   not a global transaction or a recovery mechanism for external edits/crashes.

Do not delete files or rename existing folders. Follow safety and original scope
even if a lower-tier worker or remembered preference recommends a shortcut.
