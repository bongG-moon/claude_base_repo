---
name: html-report
description: 디자인·분량·스크롤 또는 페이지 넘김 방식을 선택받아 인터넷 없이 열리는 HTML 업무 보고서를 만들고 확인합니다.
---

# HTML report

For HTML work only, read `references/design-and-numbers.md` before delegating or
building. Pass its path to the worker and require that worker to read it too.
Inspect the current Skill catalog for a relevant installed design/reference Skill;
honor source preferences and read the selected instructions when available.
Do not assume such a Skill exists, install one automatically, or load every Skill.
Reuse compatible layout/type/spacing guidance in the bounded report specification;
never execute downloaded code or bypass a denied action to satisfy a design Skill.

Read `../company-agent/references/business-protection.md`. Reuse explicit user
preferences and approved inputs; ask only missing choices. The FIRST design
question has exactly these three options: `1. 깔끔한 업무형(추천)`,
`2. 지표 중심형`, `3. 추가 디자인(미리보기)`.
Do not expand all eight designs, explanations or previews in that initial question.
The third option opens a choice flow; it is NOT a report style and never maps to freeform.
Question order is mandatory: design -> design_detail (only for 추가 디자인) ->
format -> ready. Never batch the initial design question with length or mode.
When using AskUserQuestion, send ONE design question, wait for its answer, and
finish the design branch in a separate call BEFORE asking format questions.
When the user chooses 추가 디자인, IMMEDIATELY show the eight numbered names and
short Korean descriptions from the reference in chat and accept a number/name.
Do not ask length/mode in that message or tool call. If the question widget cannot
fit eight options, use a plain numbered chat list; do not silently drop designs.
Offer a small-preview file link alongside the list using `business html-designs`
with the exact installed cliCommand and stateRoot. Opening it is OPTIONAL: the
user can choose directly in chat. If that command is blocked, keep the chat list
available without bypassing the restriction or delaying selection for a preview.
The HTML's additional-design disclosure starts closed. It is not an inline widget
in Claude's terminal; a click is NOT automatically synced to the session. The user
must paste its selected sentence back. Never infer a selection from a click.
The picker's length/mode default to 기존 선택 유지; preserve known choices.
Do not read the whole HTML into context or pretend the terminal shows thumbnails.

Before asking choices, run `business html-choices --spec "<choices.json>"
--state-root "<stateRoot>"` through the exact installed cliCommand. Keep this small
ordinary-input JSON in an allowed temporary/project location, not durable memory.
Include only confirmed style/length/mode; when 추가 디자인 is requested, set
`designMenu:"additional"` and omit style until a specific design is chosen.
Follow the returned stage and missing fields, not a generic three-question form.
Merge subsequent answers into the existing choices; NEVER replace the whole object
with just the newest answer. design_detail has only style missing, even when
length/mode are still unknown. At format, ask only missing length/mode (these two
may be grouped). At ready, build without asking again. Pass confirmed choices to
the worker and delegate generation only after ready. A blocked helper does not
authorize bypassing it or inventing choices; retain inputs and report that blocker.
Example recovery: {designMenu:"additional",length:"detailed",mode:"scroll"}
asks only the specific design; selecting glassmorphism then goes straight to ready.

Accept a spontaneous combined reply such as `1 / 보통 / 스크롤`, but do not
prompt for all three together before resolving design. `추천대로` means minimal /
standard / scroll ONLY for choices not already explicit or reliably remembered.
The absence of a reply is not acceptance. Preserve explicit choices and do not
ask again. Once the user selects or accepts a recommendation, proceed without
a redundant approval for that same choice. Include style, length and mode in
the JSON. `input_required` means ask only missing fields, not retry with guessed
defaults. Internal API compatibility defaults do not authorize skipping user choices.
This does not waive approval for external publication, protected inputs, package
installation, or other separately controlled actions. Still show an outline first
for large work as described below.

After design is final, ask missing 분량(핵심/보통/상세), 방식(스크롤/페이지/둘 다). Supported style IDs:
`minimal`, `editorial`, `bento`, `glassmorphism`, `brutalism`, `neumorphism`,
`gradient-mesh`, `freeform`. Length is content planning, not a token count.
The freeform preset is a starting style, not arbitrary user-supplied JavaScript.

Write a bounded JSON job from permitted material only:
`{title, subtitle?, style, mode:"scroll"|"slides"|"both",
length:"short"|"standard"|"detailed", sections:[{title, body?, bullets?,
table?:{headers:[],rows:[]}, chart?:{type:"column",categories:[],
series:[{name:"...",values:[]}]}, image?:{path:"<local approved image>",alt:"..."}}]}`.
HTML also supports `layout`, `eyebrow`, `takeaway`, `source`, bound `kpis`, and
top-level `facts`/`checks`; use the exact schema in the reference, not guessed keys.
For numeric reports, derive totals and rates from table/chart cell references,
reuse `{{fact:id}}` in summaries, and cross-check duplicated totals across views.
Do not copy previously generated summary arithmetic without recomputing it.
Do not fabricate numbers; include sources in section text. For large work show
an outline or representative page before creating all sections.

Use `business html --spec "<job.json>" --output "<new output.html>" --state-root
"<stateRoot>"` via the exact runtime cliCommand. It uses shipped local HTML/CSS/JS,
does not install packages or download fonts, and never overwrites an existing
output. Evaluate returned validation/warnings; inspect the actual result when an
approved browser/rendering path is available. Do not claim visual QA without it.
Read the saved report and compare its figures, recommendation status and required
exclusions against the source. Check totals, denominators, rounding and summary
claims, not only individual input rows. Glob/file existence is not content verification.
`validation.arithmetic=checked` verifies declared calculations only, not the source,
free prose or visuals. Never turn `sourceAccuracy`/`visual=not_verified` into a
blanket pass. Record partial/unavailable for missing required checks and explain
only user-relevant limitations. Do not mark an SVG present as visually inspected.
If revising, keep version labels and summary text consistent with changed tables.

If this command needs approval, distinguish that specific pending/denied command
from the availability of Bash as a whole. Do not describe all tools as blocked.
Keep the prepared specification and ask for the missing approval in plain language;
do not replace a denied factory execution with a hand-written generator or direct
HTML Write merely to accomplish the same denied operation. Continue only unrelated
already permitted work, such as a separately requested draft message. A missing
dependency and an explicit permission denial are different conditions.

Use approved connected image MCPs only if images are needed and actually available.
Do not replace SMALL/MEDIUM/LARGE aliases with an image endpoint. If no tool exists
or an ordinary service failure occurs, use native charts/shapes or approved images
and explain the fallback. A DRM/permission refusal is not a fallback opportunity.
Image input understanding and image generation are separate capabilities.

Deliver the output path, chosen format, any excluded input and honest validation.
When unrestricted, feed only abstract style/length preferences and verified fixes
to the existing learning flow, not source content or complete reports.
