# Lean Skill and project-workflow authoring

Use only while creating or repairing a requested Skill/project harness. Keep the
selected parent factory's commands, ownership checks and validation unchanged.

1. Reuse the request, project facts and selected existing capabilities. Define the
   input, requested output, scope and observable completion criteria before text.
   Ask only for a missing choice that materially changes the result. No exhaustive
   interview, automatic tracker setup, new plugin, or redundant planning process.
2. Give each Skill one primary job. Its description states distinct trigger cases
   and exclusions, not keyword synonyms or an instruction to run on every task.
   Related cases can share one Skill; a reference file does not need a Skill name.
3. Keep necessary ordered steps and safety boundaries in the main file. Put branch-
   specific examples and details behind relative links with an explicit condition
   to read them. An unconditional import still consumes context. Do not inline
   corporate knowledge, transcripts or this authoring guide into every generated
   Skill. Preserve required provenance and license notices outside active guidance.
   AssetSpec `references` is an array of text strings; the factory writes them as
   `references/reference-1.md`, `reference-2.md`, and so on. Link those actual
   generated names, not invented filenames or unsupported reference objects.
4. Give each step a checkable exit: an actual read-back, test result or user decision
   where required. Distinguish structural validation from real task execution.
   Reuse canonical runtime commands rather than inventing aliases. Keep secrets out
   of prompts, examples, generated instructions and logs.
5. Review normal input, missing input, conflicting existing Skill, denied capability,
   and follow-up behavior. Verify relative references resolve inside the intended
   package, filenames/names do not collide, and applicable tests actually run.
   Static text review alone cannot prove model behavior. No second Stop gate.

For project harnesses, reuse existing relevant knowledgePaths and the documented
factory spec fields. Do not invent frontmatter or JSON fields to enforce this
checklist. Include only necessary stages; the factory owns its generated agents.
User State remains the destination for personal assets. This reference never
authorizes changing a preferred third-party Skill or the common installed core.
