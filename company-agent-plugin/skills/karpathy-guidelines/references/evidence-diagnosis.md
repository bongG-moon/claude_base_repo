# Evidence-based diagnosis within the current work

1. Identify the exact observed failure and trace its entrypoint and relevant
   callers. Use the real input shape with safe synthetic data. Separate observed
   facts, hypotheses and unknowns; never name a definitive cause without evidence.
2. Prefer a small test or fixture CLI invocation that fails on THIS symptom, not
   merely process exit or file existence. For timing problems record a baseline
   and conditions. Avoid production writes or captured sensitive payloads.
3. Compare plausible causes with falsifiable checks, changing one variable at a
   time. Reuse existing checks and the current retry budget. Do not force three
   hypotheses for an obvious defect, narrate every hypothesis, or start an
   independent infinite loop. Denial/DRM stops that operation without workaround.
4. A diagnosis-only request remains read-only: report evidence and the proposed
   fix, without editing source, adding logs, or creating a persistent harness.
   With authorized repair, reproduce the bug before editing, fix the relevant
   shared cause and test affected callers, not only the example in the report.
5. Rerun the original symptom path and relevant regression tests. Preserve evidence
   of remaining failures. Clean up only your own temporary instrumentation within
   scope; never remove another person's files or necessary validation for brevity.
   Confirm a new regression check fails before the fix when feasible; otherwise
   label the missing baseline. Use the latest relevant result, including its exit
   status and skipped checks. A worker's success report is not independent proof.

If the environment cannot reproduce the issue, report what is confirmed, the
remaining uncertainty, and the smallest missing evidence. Do not fabricate a
passing test or request credentials in chat. Keep the final response focused on
the business result or actionable blocker. Learning remains the parent's single
meaningful-milestone process, not a second automatic review after diagnosis.
