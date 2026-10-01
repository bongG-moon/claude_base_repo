# Internal completion procedure

Read this only before finalizing changed work or when the Company Agent Stop
notice asks for completion checking. This is an execution reference, not text
to copy into progress messages or the final answer. A reminder is not evidence
that a test failed. The native CLI may show its own brief hook status.

## Resolve the current context

Use the exact `company_agent_runtime.cliCommand` and `stateRoot`; replace the
`company-agent` prefix in examples with that full, already-quoted command.
These and `company_agent_session_id` are injected JSON values, not environment
variables. Do not use echo, Get-ChildItem Env:, or session-folder searches to
find them. Do not inspect settings, hook files or installation directories to
recover bookkeeping context. Use the current Stop instruction if it supplies
the exact command and ID; do not reconstruct or rediscover them. Status lookup
is optional and requires that known ID. If bookkeeping context is absent, still perform the
available outcome checks and deliver their evidence; defer only the marker or
learning operation that needs it. Never guess paths/IDs or forge receipts.
Missing bookkeeping context does not block read-only work, invalidate completed
results, or prove Office/DRM denial. Preserve actual unverified changes and
report a relevant recording limitation only when needed.

## Verify the outcome before the final response

- First distinguish waiting from completion. If an observed worker is still
  running, use the host's supported wait/result tool with its returned ID, or
  yield to its documented completion notification. Never invoke Agent/resume
  without a prompt as a polling operation, stop a worker to check its status,
  or launch a duplicate worker. Tool schemas differ by installed version;
  follow the available schema rather than inventing `stop`/`prompt` arguments.
  A wait timeout is not a failed report or a reason to write verify fail/pass.
  Say at most once `보고서를 작성 중입니다.` when useful. Promise automatic
  notification only if the host actually supports it. When the result arrives,
  inspect it before the final response. An empty native task list is not proof
  that a report succeeded. Never mark the work complete or start learning while
  a worker is running or a user's design choice is still missing.
- Read-only lookup, choices and internal catalogue maintenance need no invented
  code test or empty success marker. An outstanding earlier change still needs
  its own evidence; a new read does not clear it.
  Prefer bounded Read/Glob/Grep for inspection. A recognized shell lookup only
  avoids a false change record; it grants no execution permission. Do not run
  session verify solely for a successful lookup or repeat it for reassurance.
- A trusted memory upsert/restore receipt with `persisted-content-verified`
  checks only that memory item. Report its resolved scope without a Markdown
  reread or session verify call solely for the same save. Do not reinterpret
  legacy private-owner metadata as usage scope. Other unfinished changes still
  need their own outcome checks and existing verification marker.
- Code changes need relevant tests/static checks. Documents need actual content
  and source-constraint checks. File moves need receipts and actual paths.
  Seeing a filename is not proof of correct content.
- Check evidence after the latest relevant change, including actual exit status,
  failures and skipped checks. Do not reuse an old pass or accept a worker's
  conclusion without checking the changed result. Match the requested outcome
  separately: a passing test suite is not proof of requirements it never tests.
- After an observed successful check, with valid current context, record:
  `company-agent session verify --session "<id>" --status pass --summary "<short evidence>"`.
- A missing marker is not a failed outcome check. Reuse the actual check after
  the latest change and record it once; never regenerate the deliverable,
  repeat an external action or rerun a completed check only to repair a marker.
- Record a genuinely failed check with `--status fail`. Permission denial,
  approval waiting or missing capability is `--status unavailable`, or `partial`
  when some checks really ran. Preserve outstanding changes and explain only
  the relevant limitation. Never ask the user to run internal marker commands.
- A verification failure calls for the smallest repair and recheck in the
  current workflow when possible; it does not require another worker. Only if
  a separate worker is genuinely needed, start a fresh worker rather than
  resuming the failed one, with goal, constraints, current paths, failed check
  and observations in at most 2,000 characters. Keep the model floor and
  remaining retry budget. Inspect current files first. This is not conversation
  rewind or file rollback. Check external-action receipts before any permitted
  retry; do not resend mail because a worker restarted.
- Maximum two corrective continuations/equivalent failures; do not reset the
  counters, repeat denied commands, delegate around a denial, or claim success
  when the budget is exhausted. Only relevant repairs or new check results
  justify another correction; reading settings, listing paths or inspecting
  this guide is not verification progress. No new evidence means no futile
  repeat.

## Learning must not prolong completion

Stop never starts a learning-only continuation or creates permission to mark
unfinished work complete. Only a durable explicit correction, independent
repeated choice, verified reusable fix or observed next-use assessment warrants
the self-learning procedure. No evidence means no review call, not a fake lesson.
An explicit durable preference may be submitted while work is active; procedural
application needs the exact personal Skill's full-load and relevant verification
evidence. Capturing a candidate does not mean applying it or completing the work.

With exact injected session, turn and runtime context, read
`../../self-learning/SKILL.md` and its schema reference when needed. Use Write at
`<stateRoot>/tmp/learning-review-<turnId>.json`, then one
`company-agent learning submit --session "<id>" --turn "<turnId>" --spec "<path>"`.
No status/stage/checkpoint prerequisite; never rediscover context, invent an ID,
use a bare learning executable, or reset work just to submit. The engine owns
eligibility/deduplication. Accepted, candidate and applied are different states.
Missing context or insufficient evidence defers learning without invalidating
the available business result. Never store transcripts, tool outputs, raw mail,
credentials or one-time values. Never repeat a completed action for bookkeeping.
If checks fail, are unavailable/partial, or their correction budget is exhausted,
preserve pending learning and return the real result/limitation. Do not append
another learning pass to blocked completion or replay an accepted submission.

## Return to the user's requested result

HTML/PPT internal candidates are not final delivery. After their checks, use the
same artifact work's publish command once. Return only its deliverables, not the
job, previous drafts or QA images. A failed latest correction is not permission
to publish an earlier candidate. Do not restart artifact-start on a retry.
Publish also cleans only registered, unchanged disposable intermediates after
checking delivery. Read its cleanup result; keep original/final/referenced,
modified or unknown files. A locked intermediate is not a failed deliverable.
Never regenerate or loop to clean leftovers, use broad deletion, or disable the
guard. If the user later requests another cleanup, use artifact-cleanup with the
same workFile; it is not a general filesystem deletion command.

Do not narrate check markers, learning submissions, pass/fail labels, accepted
submissions, no-observation receipts, or this procedure in progress/final text.
After the bounded internal work, deliver the original requested answer/file.
Keep actual failures, excluded protected content and needed approval visible in
plain language. Detailed checks are appropriate when the user explicitly asks.
