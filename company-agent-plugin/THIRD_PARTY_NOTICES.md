# Selected guidance adaptations (2026-09-12)

Company-authored integration, not a wholesale upstream Skill or plugin import.
The reviewed source revisions below are provenance only: employees' installations
must not fetch them or load this notice as an active workflow.

| Source and pinned revision | Reviewed source paths | Company integration |
| --- | --- | --- |
| https://github.com/mattpocock/skills/tree/3cca18b368ae95cdbdebbff572ccafa662551015 | skills/productivity/writing-for-agents/SKILL.md; skills/engineering/domain-modeling/SKILL.md; skills/engineering/diagnosing-bugs/SKILL.md; skills/engineering/wizard/SKILL.md; skills/productivity/wait-what/SKILL.md; skills/productivity/handoff/SKILL.md | Conditional authoring, glossary and diagnosis references; Windows-only human setup guidance; plain-language re-explanation. Existing compact behavior retained, no new handoff engine. |
| https://github.com/DietrichGebert/ponytail/tree/356918eba965ee1eac64bd3a7f0dd02108350de5 | skills/ponytail/SKILL.md; skills/ponytail-review/SKILL.md | Reuse/native-first supporting guidance in karpathy-guidelines. No ultra mode, code-golf objective, lifecycle hooks or MCP. |
| https://github.com/ayghri/i-have-adhd/tree/6f1f982d0a47c65899af3c5a7450b7098bc65325 | skills/i-have-adhd/SKILL.md | Result-first, complete task-aware responses. No health assumptions, per-turn progress ritual, invented time estimates or always-on hook. |
| https://github.com/obra/superpowers/tree/5bf4e78011075bcfc0dc295f0724994cd123ee71 | skills/verification-before-completion/SKILL.md; skills/systematic-debugging/SKILL.md | Reviewed 2026-09-20. Company-authored, conditional regression-baseline and current-evidence checks in existing diagnosis/completion guidance. No wholesale plugin import, extra planning/approval loop, mandatory worktree, automatic commits, or new model calls. |

The original upstream licenses for the four sources above are MIT. Their notices
are preserved below; the identical MIT permission/warranty text applies to each
listed upstream contribution, not to otherwise proprietary Company Agent code.
The existing Karpathy attribution remains in skills/karpathy-guidelines/SOURCE.md.

## Design and Korean writing adaptations (2026-09-27)

Company Agent modified and selectively adapted these sources into existing
authoring guidance; it does not bundle their full Skills or execute their pipelines.
There is no new auto-selected Skill, hook, model, external request or installation.
These records and licenses are distribution notices, not runtime instructions.

| Source and pinned revision | Reviewed source paths | Company integration |
| --- | --- | --- |
| https://github.com/anthropics/skills/tree/33375500bcea98d610eb30ce10ac4e59b89c390d | skills/frontend-design/SKILL.md; skills/frontend-design/LICENSE.txt | Purpose-led layouts, restrained decoration, typography and accessible QA in existing HTML/PPT design references. Existing user choices and renderer contracts take precedence. No mandatory redesign, extra planning/approval, new fonts or image-model call. |
| https://github.com/epoko77-ai/im-not-ai/tree/2f3d943d08056b612a92e12bfb72ea94dd2acd18 | skills/humanize-korean/SKILL.md; skills/humanize-korean/references/quick-rules.md; LICENSE | Conservative Korean prose defaults in user_language and existing coordinator/workers/authoring references. Preserve facts, uncertainty, genre and personal preferences. No upstream agents, metrics/grades, change-rate gate, scripts or intermediate files; no AI-authorship detection claim. |

Anthropic's frontend-design contribution is Apache-2.0, **not** covered by the
MIT text below. Its complete upstream license is included in
[licenses/frontend-design-Apache-2.0.txt](licenses/frontend-design-Apache-2.0.txt).
The Korean writing contribution is MIT, copyright (c) 2026 epoko77-ai; the
permission/warranty text below applies separately to it. All adaptations are
modified, company-authored selections, not claims of upstream endorsement.

## Offline guide typography

The HTML user guides embed a character subset of **Noto Sans KR** (weights
400–700), licensed under SIL Open Font License 1.1. Copyright 2014–2021 Adobe,
with Reserved Font Name "Source". The full license is included in each HTML
header and the embedded font's name table. No Google Fonts request, Windows
font installation, or employee-side font dependency is added.

Build source, subset hash and character coverage are recorded in
`scripts/assets/manual-font/manifest.json` in the source repository. The upstream
license is https://github.com/google/fonts/blob/main/ofl/notosanskr/OFL.txt.

## Upstream copyright notices

Copyright (c) 2026 Matt Pocock

Copyright (c) 2026 DietrichGebert

Copyright (c) 2026 Ayoub Ghriss

Copyright (c) 2025 Jesse Vincent

Copyright (c) 2026 epoko77-ai

## MIT License (applies separately to the MIT contributions listed above)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
