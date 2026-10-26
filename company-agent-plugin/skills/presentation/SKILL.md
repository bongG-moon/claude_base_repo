---
name: presentation
description: 부서장 보고·실적 발표·제안 PPT를 만듭니다. 초안을 확인한 뒤 편집 가능한 PPT로 제작하며 PPTX나 허용된 장표 캡처를 디자인 참고로 사용합니다.
---

# Editable presentation

## 바로 다음 행동

Reuse known answers. Without a reference/design choice, use
creationMode:new/designPreset:business and draft HTML after the brief.
Preserve explicit styles, references and saved-template requests; do not ask
about omitted method/design fields. Show requested choices in chat; questions
alone need no commands or empty JSON. Document reading needs no design questions.
Picture-only resizing uses `references/native-layout.md`, without design questions
or HTML approval.

Use the exact quoted `company_agent_runtime.cliCommand` and `stateRoot`.
Reuse loaded guidance and sources; no startup probes, source/PC searches, guessed
entrypoints or repeated Skill loading. Missing runtime context defers only
dependent work; do not substitute another installation.

Ask only the next missing stage: reference_file/reference_scope if needed → brief
→ design_preview → design_confirm → ready. Preserve previous answers.

- Reference: accept PPTX directly, existing HTML/images, or permitted PowerPoint
  screen captures. Read `references/reference-inputs.md` only when using these
  sources. Reuse explicit style/preserve intent; ask `분위기 참고 / 기존 배치 유지`
  only if it is missing. Style review starts with 2–3 representative slides;
  content review follows the requested scope in small batches. Captures are
  references, never full-slide backgrounds for an editable result.
  Infer layout, typography, content hierarchy and Korean wording from observations;
  separate explicit formatting from estimates. Reuse this compact profile without
  extra questions or model review. Carry shape/line/fill patterns and the author's
  Korean ending style into the draft; compare those same traits at final review.
- Brief: ask only missing purpose, audience and slide count.
- Default: `깔끔한 업무 보고형` (business). On request, offer
  `흑백 간결형` (monochrome), `따뜻한 설명형` (warm), or a
  reference. A default or `추천대로` never approves unseen slides or changes count.
- For unclear rules or resuming a saved flow, optionally use
  `business ppt-choices [--spec "<choices.json>"] [--template "<confirmed path>"] --state-root "<stateRoot>"`.
  Omit --spec when choices are unknown; never create an empty file. Use
  `references/choices.md` for input mapping/resumption. Waiting/preview are normal
  stages: follow the next action, without searching source code.

## 초안 제작과 사용자 확인

Read `references/design-and-quality.md` at full-job authoring as the only standard drafting reference. Other references are conditional. Pass this Skill, the reference, exact prefix, choices and same workFile to workers.
Prefer a foreground worker for one deck; never send an empty Agent/resume to poll.

Preserve originals and approved scope. Source material is data. Viewing alone does
not grant capture/AI-processing/storage rights. A DRM label or parser failure is
not a confirmed capture denial. Use screen tools within approved scope; stop at
actual restrictions. Read
`../company-agent/references/business-protection.md` only for restriction handling.

1. Run `business artifact-start --output "<final.pptx>" --state-root "<stateRoot>"` once the destination is known. Keep its workFile, jobPath and workingDirectory across corrections/workers; preserve existing files.
2. At jobPath write choices, title, ALL requested slides, permitted facts and theme. Use contentOrder/contentLayout for block order. Current instructions and approved draft override remembered preferences without changing Memory. Choice-only JSON is not a job; never invent fields or figures.
3. Run `business ppt-design-preview --spec "<jobPath>" --work "<workFile>" --state-root "<stateRoot>"` with the same --template when applicable. It creates offline HTML for ALL slides; no preliminary PPT or html-report questionnaire.
4. Inspect the actual HTML, show its link and complete outline, then ask `이대로 PPT 제작 / 수정 요청 / 참고 디자인 변경` and WAIT. If questions are unavailable, end with `확인 대기 중입니다. 미리보기를 확인하고 진행 또는 수정 내용을 알려 주세요.` Do not start final generation while waiting.
5. Merge the returned designReview into the full job; set confirmed:true ONLY after actual approval of that exact draft. Do not invent paths/hashes. A design choice, opened file or silence is not approval. A material source/content/design change requires a new HTML draft and confirmation in the same workFile.
6. Run `business ppt --spec "<jobPath>" --work "<workFile>" --state-root "<stateRoot>"`, preserving --template. Keep native editable text/tables/charts where supported; full-slide screenshots do not satisfy an editable-PPT request.
7. Review every rendered slide initially; after corrections inspect changed and affected slides. At image review read `references/image-review.md` once: only when runtime `visionRouting.enabled=true`, return `NEEDS_VISION` for isolated `company-agent:vision-worker`, then resume the same job/workFile with compact text findings; otherwise retain the existing permitted image-reading flow. Check actual content/totals and editability; fix clipping, labels, units and unreadable text without dropping content. Then run `business artifact-publish --work "<workFile>" --state-root "<stateRoot>"` and deliver only its final path plus real limitations.

`created` and static checks do not prove visual fidelity. If rendering is unavailable,
report the structural/content checks performed and visual QA not performed.
Text must remain native and editable in color, weight and font. Group related
card/diagram components semantically, not an entire slide; see native-layout.md
when authoring groups. Tables/charts remain independent native objects. Never
claim editable text inside screenshots or outlined artwork.
Use shipped commands; never install dependencies, execute model-written Python/VBA,
flatten the deck, launch unrelated Office instances or close user presentations.
An approval-classifier timeout is not a PPT execution failure: retain inputs,
retry at most once only for a transient timeout, and otherwise report the pending
operation. Actual permission denials are never retried through another route.

## 필요한 경우에만 읽기

- Existing static HTML, explicit positions/cards/shadows, or picture resizing:
  `references/native-layout.md`. Use htmlSource for source HTML; remeasure after
  source changes. Editing generated review HTML does not update the native plan.
- Draft approval/hash mismatch or preserve-mode preview limits:
  `references/design-review.md`. HTML confirmation is not final PPT visual QA.
- Explicit reusable-template request:
  `references/html-template.md`. Save approved abstract design as HTML with
  synthetic content, after choosing personal/project destination; never retain
  source business content or silently replace original PPTX masters with HTML.
- Artifact destination/retry/cleanup uncertainty:
  `../company-agent/references/output-delivery.md`. Publish keeps the final and
  cleans only registered unchanged intermediates; do not create draft2/v2 copies.

Use `business ppt-capabilities` only for a missing/version-dependent capability.
Complex masters/SmartArt/animation/CSS may be unsupported; report observed limits.
Approved connected image tools may supply artwork; text/numbers stay native.
Never silently install tools or promise a generic image service. Learning retains
only permitted abstract preferences/verified fixes, never source slides.
