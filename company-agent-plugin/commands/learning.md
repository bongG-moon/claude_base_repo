---
description: 학습 내용을 확인하고 자동 학습을 일시 중지·재개하거나 개인 변경을 되돌립니다.
argument-hint: "[학습 내용, 일시 중지, 다시 시작, 또는 되돌릴 내용]"
---

# Personal learning controls

Default to Korean for all questions, choices and result explanations unless the user explicitly requests another language. Preserve exact identifiers and explain English tool results in Korean.

Use the installed `company_agent_runtime.cliCommand` prefix and active `stateRoot`.
Never assume `company-agent` is on PATH or select another installation's state.
User request: $ARGUMENTS

1. For a status/list/explanation request (including no arguments), run `company-agent learning status`.
   Show recent distilled observations, submitted/candidate/applied/deferred states,
   actual validation metadata, observational next-use assessments, rollback conflicts,
   and whether learning is enabled. Distinguish never submitted from a submitted
   no_candidates receipt. Accepted is not applied; provided-to-model is not proof of use.
   Translate IDs into short Korean titles; do not dump raw JSON. Listing does not authorize changes.
   Add `--session "<id>"` only when that exact current ID is already injected to
   show currentSubmission and memoryDelivery separately. Without it, global status
   is still available; never discover a session or infer absence of all Memory.
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

These are on-demand controls, not prerequisites for normal automatic learning.
Eligible feedback uses self-learning's single `learning submit` with the exact
current session/turn and canonical spec; no status/stage/checkpoint sequence.
Missing injected context defers only learning; never search settings, env or sessions.
