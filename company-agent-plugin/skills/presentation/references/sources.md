# Selected research, not a bundle of extra Skills

Reviewed 2026-09-14. The existing Company Agent presentation Skill remains the only
added workflow surface: no extra lifecycle hooks or global plugin registrations.
Implementation is Company-authored. No upstream source files or Skill bodies are
redistributed here. Only the following design patterns informed it:

| Primary repository / reviewed revision | Used selectively |
| --- | --- |
| https://github.com/cskwork/superoffice-skills/tree/48e595b5c5805241fcfd3b04679285d2996cf419 | Korean business briefing and separating brand choices from content. MIT upstream. |
| https://github.com/CxyZyr/PPTX-Template-Skills/tree/e3139a08b4bf96bb2cda0046b8d3627e69737f11 | Analyze reference objects before mapping new content to native slots. MIT upstream. |
| https://github.com/Love-Ash/archforge/tree/1cf93325fd40ba364396dbfcca4b06790cb90010 | Optional CJK-oriented quality checker, version 0.11.0 adapter. MIT upstream. |

Archforge is not bundled or downloaded. An administrator may separately provision
the reviewed package and dependencies after approval. The adapter uses isolated
Python, a temporary working directory, --no-config, a 30-second timeout and bounded
JSON parsing. Only counts/status are returned; raw slide text is not stored.
Warnings or incomplete checks are not labeled clean just because process exit is 0.
The default requires no Archforge; native-object checks still run with python-pptx.
An upstream license does not prove suitability, safety, or corporate approval.

No Anthropic pptx Skill source is copied: its redistribution terms require separate
review. No image-only deck generator is installed as an editable PPT solution.

Safety-classifier error reference:
https://code.claude.com/docs/en/errors#auto-mode-cannot-determine-the-safety-of-an-action
This is an approval-service failure, not permission to substitute a different tool.
