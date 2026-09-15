# Internal completion procedure

Read this only before finalizing changed work or when the Company Agent Stop
notice asks for completion checking. This is an execution reference, not text
to copy into progress messages or the final answer. A reminder is not evidence
that a test failed. The native CLI may show its own brief hook status.

## Resolve the current context

Use the exact `company_agent_runtime.cliCommand` and `stateRoot`; replace the
`company-agent` prefix in examples with that full, already-quoted command.
Use the current `company_agent_session_id` supplied by route context, never an
invented or previously remembered session. If current status is needed, run
`company-agent session status --session "<id>"`.
If the context, reference, or required command cannot be read/executed, do not
guess a path or forge a receipt. State the actual missing capability briefly.

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
- Code changes need relevant tests/static checks. Documents need actual content
  and source-constraint checks. File moves need receipts and actual paths.
  Seeing a filename is not proof of correct content.
- After an observed successful check, record:
  `company-agent session verify --session "<id>" --status pass --summary "<short evidence>"`.
- Record a genuinely failed check with `--status fail`. Permission denial,
  approval waiting or missing capability is `--status unavailable`, or `partial`
  when some checks really ran. Preserve outstanding changes and explain only
  the relevant limitation. Never ask the user to run internal marker commands.
- A verification failure calls for the smallest repair. Start a fresh worker,
  not a resume of the failed one, with goal, constraints, current paths, failed
  check and observations in at most 2,000 characters. Keep the model floor and
  remaining retry budget. Inspect current files first. This is not conversation
  rewind or file rollback. Check external-action receipts before any permitted
  retry; do not resend mail because a worker restarted.
- Maximum two corrective continuations/equivalent failures; do not reset the
  counters, repeat denied commands, delegate around a denial, or claim success
  when the budget is exhausted. No new evidence means no futile repeat.

## Learn only at a meaningful milestone

A Stop reminder never creates permission to finish an unfinished task or start
an empty review. For a genuinely completed work with pending reusable feedback
or an eligible next-use assessment, read `../../self-learning/SKILL.md` and its
required schema reference. Run `company-agent learning status --session "<id>"`
to get the actual current turn and milestone status. Do not invent IDs.

Only a successfully completed checkpoint may be reviewed. If a Stop reminder
already requested that review, inspect its pending status instead of making a
new work or resetting the checkpoint. Write the distilled spec with Write to
`<stateRoot>/tmp/learning-review-<turnId>.json`, then run
`company-agent learning review --session "<id>" --turn "<turnId>" --spec "<path>"`.
Never use a bare `learning` executable. Keep the fixed review-attempt budget.
Skip already complete/deferred/disabled reviews. No reusable evidence: follow
the self-learning contract, never manufacture a preference or an empty ritual.
Never store transcripts, tool outputs, raw mail, credentials or one-time values.
Learning cannot clear verification failures or repeat external business actions.

## Return to the user's requested result

Do not narrate check markers, checkpoint/review calls, pass/fail labels, accepted
reviews, no-observation receipts, or this procedure in progress/final text.
After the bounded internal work, deliver the original requested answer/file.
Keep actual failures, excluded protected content and needed approval visible in
plain language. Detailed checks are appropriate when the user explicitly asks.
