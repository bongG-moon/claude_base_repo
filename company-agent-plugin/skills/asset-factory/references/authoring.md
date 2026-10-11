# Lean Skill and project-workflow authoring

Use only for a requested Skill/project harness. Keep the parent's commands, ownership checks and validation.

1. Reuse the request, project facts and selected capabilities. Define input, output,
   scope and observable completion criteria. Ask only for a choice that changes the result.
   No exhaustive interview, automatic tracker, new plugin or redundant planning.
2. Give each Skill one primary job with distinct triggers and exclusions, not synonyms
   or instructions to run every time. Related cases can share a Skill; references need no Skill name.
3. Keep ordered steps and safety boundaries in the main file. Link branch-specific
   details conditionally; unconditional imports consume context. Do not inline corporate
   knowledge, transcripts or this guide. Preserve provenance and license notices separately.
   AssetSpec `references` is an array of text strings; the factory writes them as
   `references/reference-1.md`, `reference-2.md`, and so on. Link those actual
   generated names, not invented filenames or unsupported reference objects.
   Omitted `references` preserves files. An explicit list removes obsolete files only
   with factory ownership and unchanged hashes; preserve/report untracked or edited files.
4. Give each step a checkable exit: read-back, test or required user decision. Separate
   structure checks from real execution. Use canonical commands; keep secrets out of text/logs.
5. Review normal/missing input, conflicting Skills, denied capability and follow-ups.
   Check relative references, package boundaries, name collisions and actual tests.
   Static text review alone cannot prove model behavior. No second Stop gate.

Project harnesses reuse relevant knowledgePaths and documented spec fields. Do
not invent frontmatter or JSON fields. Include necessary stages only; the factory owns its generated agents.
New Skills use current Claude config/skills or project/.claude/skills, with one canonical source.
Keep legacy private Skills and Memory/tools in their existing stores; do not copy or move them.
Project-native Skills can travel with the shared folder. Preserve third-party Skills and installed core.

For existing updates, `asset inspect --name` locates `effectivePath`; read that source.
Inspect metadata/hash (`bodyIncluded: false`) is not a body-load receipt. Use the revised
body with `asset update --name --instructions-file --expected-sha256`. Preserve name,
scope, extra frontmatter, references and tool bindings. Dependency guidance occurs once.
Do not ask users to regenerate AssetSpec or copy folders; authoring inputs are not watched sources.
If saving returns `status: partial`, report the changed file and backupPath; compare them before retry or recovery.
For native Skills outside inspect's current profile/project, use the catalogue's exact file; preserve native metadata and never create a replacement copy. Separate structure checks from native invocation tests.

New native Skills use `/<name>`; missing entries may need `/reload-skills` or a new session.
Preserve user-invocable and other host semantics. Existing private Skills keep the company command/natural-language entry. Do not claim live host discovery from file validation alone.
