---
name: presentation
description: 부서장 보고·실적 발표·제안 PPT를 만듭니다. 기존 양식과 디자인 스킬을 참고하고 큰 핵심 수치·편집 가능한 표와 차트·슬라이드별 배치 및 수치 대조를 적용합니다.
---

# Editable presentation

Use this Skill to create/edit a deck. For reading or summarizing an existing
corporate Office document without creating slides, use the selected office-reader
workflow instead; do not ask presentation design/slide-count questions for a read.
Template geometry inspection below is a separate authoring operation,
not a replacement for corporate document reading.

For PPT work, read `references/design-and-quality.md` BEFORE drafting or delegating.
Pass that exact path and the selected design references to the worker; require
the worker to read them. Inspect the current catalog for a relevant installed
presentation/design Skill, honor saved source preferences, and read only selected
instructions. Do not install a Skill automatically or load the whole registry.
Compatible design guidance informs the bounded job, never unrestricted code execution.
PPT output is not a text outline exported to slides. Use a clear conclusion,
readable evidence and deliberate composition; do not claim all styles/templates
are exactly reproducible by the built-in factory.

Read `../company-agent/references/business-protection.md` first. Ask only missing
purpose/audience, slide count and template choice. Retain original files.
Before building, run `business ppt-choices --spec "<choices.json>" [--template
"<confirmed reference.pptx>"] --state-root "<stateRoot>"` using the installed
cliCommand. Follow ONLY the returned stage. AskUserQuestion must not bundle the
method or reference-file question with later audience/count questions.
First offer: 새 디자인 / 기존 PPT·회사 양식 첨부 / 저장한 내 양식.
For reference/saved, request the actual file immediately, then ask 분위기 참고 /
기존 배치 유지. Only then ask missing purpose/audience/slideCount. Merge answers;
do not discard known values or assume a saved template exists. The helper checks
question order, not user authorization or the existence of an unprovided file.
Keep the selected creationMode (new/reference/saved), referenceMode (style/preserve),
purpose, audience and slideCount in the final job. CLI rejects missing choices or
silently changed slide counts. Internal Python defaults are compatibility only.
New mode needs no template, but DOES need a specific designPreset: business /
monochrome / warm. Use the helper's three Korean designOptions plus `참고 PPT
첨부로 변경` in AskUserQuestion. A known `새 디자인` skips only the method question,
not design selection. Preserve explicit style requests; if none of these presets
fits, ask for a reference or apply confirmed presentationTheme overrides rather
than claiming an unsupported layout. `추천대로` may select business, but does not
approve unseen slides. Keep only the six choice fields in
`<stateRoot>/tmp/ppt-choices-<short-id>.json`; full slides/facts/review belong in
a separate job file. Choice metadata alone is not a generated PPT or failed test.

## Representative design and approval

Follow method -> reference_file/reference_scope when needed -> brief -> design
(new only) -> design_preview -> design_confirm -> ready. A new design selection
does not authorize final generation. Read `references/design-review.md` at
design_preview; generate only the representative draft through the documented
helper, show the complete outline and actual slide preview, then WAIT for the
user's confirmation. A phrase like `남색 제목의 업무형` is not a visual preview.
Use AskUserQuestion (이대로 제작 / 수정 요청 / 참고 PPT로 변경); if unavailable,
end the turn with `확인 대기 중입니다. 미리보기를 확인하고 진행 또는 수정 내용을 알려 주세요.`
Do not launch the final-build worker while awaiting confirmation. An explicit
request for approval before building always remains in force.

Use `business doctor` for runtime hints and `business ppt-inspect --template
"<source.pptx>"` for allowed template structure. Inspection failure may mean DRM
or an unsupported/corrupt format: do not assert a cause without evidence.
For actual design analysis run `business ppt-analyze --template "<source.pptx>"`.
It returns declared colors/fonts and shape geometry, NOT a guarantee that inherited
styles were fully resolved. Read only relevant slides. For allowed previews use
`business ppt-preview --template "<source.pptx>" --output "<new preview folder>"`.
This uses a temporary copy and installed PowerPoint only. If it fails, report the
limit and which slides were actually previewed.
For style reference apply verified tokens to presentationTheme and an available
font to presentationFont. Preserve mode uses templateSlides slot mapping described
in the reference. If unsupported, ask whether the user wants style reference;
do not silently switch modes. Store abstract style preferences in existing personal
Knowledge only when allowed; do not retain the original company deck by default.

Prepare permitted content as JSON:
`{title, subtitle?, style:"minimal", slides:[{title,body?,bullets?,
table?:{headers:[],rows:[]},chart?:{type:"column"|"bar"|"line"|"pie",
categories:[],series:[{name:"...",values:[]}]},image?:{path:"...",alt:"..."}}]}`.
Show the outline and representative design for substantial work. Existing image
assets may be inserted, but text/tables/charts must remain native editable objects
where supported. Creating a full-slide screenshot does not meet editable-PPT goals.
The reference defines `eyebrow`, `takeaway`, `source`, bound `kpis`, `facts`,
`checks` and `presentationTheme`. Use those exact fields, not invented positioning
or styling keys. Numeric summaries must reuse calculated table/chart values.

Run `business ppt --spec "<job.json>" --output "<new.pptx>" [--template
"<source.pptx>"] --state-root "<stateRoot>"` using the installed cliCommand.
Python dispatches to an already available library or the packaged PowerPoint COM
helper. Do not pip-install dependencies, execute model-written Python/VBA, start
an unrelated Office instance, or close user presentations.
This prohibition includes `cat > /tmp/ppt_com.py`, here-doc Python, inline COM,
and unsupported generator entrypoints. If a selected external Skill recommends those paths, adapt its design principles to
the shipped API or report the missing capability. A list lookup alone never proves
this Skill was read; pass its full path and the confirmed choices to the worker.
On a classifier timeout, it is the approval check that failed, not PPT execution.
Keep inputs, retry at most once for a transient outage, then leave the operation
pending with one Korean sentence. Do not narrate learning.
If rendering is unavailable or prohibited, say that visual validation was not
performed. Ordinary static checks do not prove perfect template reproduction.

Inspect editability/validation/warnings, handle partial outputs, then deliver a
new file with precise limitations. SmartArt, animations, masters and arbitrary
complex source layouts are not universally reconstructible by this pilot.
Render and visually inspect EVERY slide when the approved route is available.
Check title/table readability, chart labels/units, clipping and source totals.
Use validation.quality issues as findings, not proof of visual fidelity. An optional
approved Archforge adapter can augment checks; absence must be disclosed, never
auto-install it. Font/position estimates cannot replace inspecting every slide.
`created` means saved and rendered, not visually approved. A geometry estimate
does not certify typography. If anything is too dense, shorten without losing
required content or ask to split the slide; never silently shrink it to tiny text.

If image generation is needed, discover a genuinely connected approved MCP and
read its schema. Use it only for artwork/backgrounds, not precise chart numbers
or slide text. No available image tool or ordinary timeout may fall back to
native shapes/charts with notice. Report the actual image generation result.
Do not claim a generic image provider has been configured by installing this Skill.

Finish bounded verification and learning. Store reusable abstract design choices
only when allowed, never protected slide content or a complete source deck.
