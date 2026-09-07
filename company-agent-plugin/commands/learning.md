---
description: Show what Company Agent learned, pause or resume automatic learning, and safely undo one automatic personal change.
argument-hint: "[학습 내용, 일시 중지, 다시 시작, 또는 되돌릴 내용]"
---

# Personal learning controls

Use the installed `company_agent_runtime.cliCommand` prefix and active `stateRoot`.
Never assume `company-agent` is on PATH or select another installation's state.
User request: $ARGUMENTS

1. For a status/list/explanation request (including no arguments), run `company-agent learning status`.
   Show recent distilled observations, candidate vs applied changes, actual validation
   metadata, observational next-use assessments, rollback conflicts, and whether learning is enabled.
   Translate IDs into short Korean titles; do not dump raw JSON. Listing does not authorize changes.
2. If the user explicitly requests a pause, run `company-agent learning pause`.
   Explain that existing Memory and Skills remain and can still be used; future automatic
   review/application is paused, not deleted. Explicit "기억해줘" still uses personal-memory.
3. If the user explicitly requests resuming, run `company-agent learning resume`.
   Explain that subsequent turns resume review; past full transcripts are not scanned.
4. For an undo request, identify the exact automatic change from status. Ask only if the
   target is ambiguous, using up to three short options. Then run
   `company-agent learning rollback --change "<exact change ID>"`.
   Report the returned outcome. A manual edit or hash conflict must not be overwritten.
   A preference undo deactivates the current automatic entry (it does not
   reactivate an older preference); a Skill undo restores its previous owned
   checklist section. Explain that distinction before calling either restored.
   This does not undo business files, mail, DB, company rules, or another plugin.
5. If the user asks to forget a preference, distinguish deactivating the current learned
   entry from deleting all historical records. Use a targeted rollback for an active
   automatic change; don't delete the learning directory or unrelated personal memory.

Scope belongs to the currently selected User/Project state. Do not silently copy
preferences between installations. Safety/credentials and current user requests
always outrank learned text. Never promise an independent correctness proof from
model-supplied judgments or a statistical improvement from a single example.
