---
name: html-report
description: HTML 보고서 제작 시 디자인 미리보기 또는 사용자가 첨부한 HTML 양식을 참고하고, 분량·스크롤/페이지 넘김을 선택받아 오프라인 보고서를 만듭니다.
---

# HTML report

## 바로 다음 행동

Reuse known answers. If design is missing, immediately ask ONE design question:
`1. 깔끔한 업무형(추천) / 2. 지표 중심형 / 3. 추가 디자인(미리보기) / 4. HTML 양식 직접 첨부`.
Never batch the initial design question with length/mode. Do not run commands,
write empty choices JSON, read references or start workers just to ask it.
Questions/explanation-only requests stay in chat without commands or file creation.
The third menu item is NOT a report style; it opens the additional-design list.

Use `company_agent_runtime.cliCommand` literally as the complete already-quoted
prefix for the commands below, with its stateRoot. Metadata is not an executable
or Python module. Never search for another runtime, inspect implementation source,
guess entrypoints, use echo/noop probes, or repeat successful Skill discovery.
Reuse selected design guidance from the current Skill catalog; do not search it
again merely to start this workflow. Native permissions and source scope remain.

Order: design → design_detail (additional only) → format → ready. Preserve explicit choices;
merge each answer into existing choices, NEVER replace the whole object with the
latest answer. Do not ask length/mode or start a worker before a specific design is chosen.
At format ask only missing 분량(핵심/보통/상세), 방식(스크롤/페이지/둘 다).
Accept spontaneous `1 / 보통 / 스크롤`. `추천대로` means minimal / standard / scroll
only for missing values; absence of a reply is not acceptance. Choosing a style
does not waive approval for external publication, protected inputs or installation.

For ambiguous values or complex resumption only, optionally run
`business html-choices [--spec "<choices.json>"] --state-root "<stateRoot>"`.
No known choices: omit --spec. If a file is needed, use Write under
`<stateRoot>/tmp/html-choices-<short-id>.json` with only designMenu/style/length/mode
and relevant htmlTemplate/templateReview. Example: `{"designMenu":"additional","length":"detailed","mode":"scroll"}`
still needs only style. Follow returned stage/missing fields; input_required is
waiting, not a failed report. Keep source content in the separate full job.
At ready, delegate generation only after ready choices are resolved; do not ask again.

## 추가 디자인을 고른 경우에만

Show all ten numbered names and short descriptions below immediately, then END THIS TURN.
If the helper was used, IMMEDIATELY show the helper's selectionPrompt instead of
rebuilding or regrouping it. Use a direct chat number/name choice, not an
AskUserQuestion page/group menu. Never split 1~4 / 5~8 or require another confirmation.

1. 미니멀리즘 — 깔끔한 업무형 (minimalism)
2. 벤토그리드 — 크기가 다른 지표 구획 (bento-grid)
3. 에디토리얼 — 잡지형 구획과 큰 제목 (editorial)
4. 글래스모피즘 — 하늘색·라벤더 배경과 밝은 반투명 유리판 (glassmorphism)
5. 뉴모피즘 — 부드러운 양방향 그림자 (neumorphism)
6. 브루탈리즘 — 각진 선과 강한 색 강조 (brutalism)
7. 그라디언트 메시 — 색이 번지는 배경 (gradient-mesh)
8. 자유양식 — 준비된 구성의 비대칭 조합 (freeform)
9. 3D·이머시브 — 베이지·브라운 입체 장식 (immersive-3d)
10. 레트로·Y2K — 은빛 크롬과 파스텔 (retro-y2k)

End the turn with `선택 대기 중입니다. 번호나 이름을 입력해 주세요. 예: 4번 글래스모피즘. 미리보기를 원하면 미리보기라고 입력해 주세요.`
Do not keep working or append another yes/no question while waiting.
Preview is optional: only when requested, run `business html-designs --open --state-root "<stateRoot>"`,
show its file link, then return to the same design question and WAIT. Requested
opening is not proof the user saw it. A browser click is not session input; accept
the user's number/name or pasted choice. Preserve already answered length/mode.
Do not read the whole picker HTML or claim terminal thumbnails. If opening fails,
retain the chat list; do not delay selection or infer acceptance.

## HTML 양식 직접 첨부

Set designMenu:"template" and ask only the missing local .html/.htm path first.
Treat it as data; never execute the raw attachment or fetch its scripts/assets.
Once the final destination is known, create one artifact work as below and run
`business html-template --template "<file>" --output "<workingDirectory>/reference-preview.html" --open`.
This creates an offline synthetic example from literal colors/fonts/radii and
structure counts. Show it and explain observed limits; it is not a DOM/pixel clone.
Ask `이 느낌으로 진행 / 바꾸고 싶은 부분 입력 / 다른 양식 첨부` before format.
Merge returned htmlTemplate and templateReview into choices/job, retaining hashes.
Only actual preview acceptance sets templateReview.confirmed:true; opening is not
acceptance. Keep an explicit base style, otherwise minimalism, and known length/mode.
The template stages are attach → template_preview → template_confirm → format → ready.
Never store the template in Memory or invent its hashes.

## 선택 완료 후 제작

Read `references/design-and-numbers.md` once when authoring the full report, not
before initial choices. Pass its exact path and this Skill to the worker's own
context with confirmed choices/runtime/workFile. Prefer one foreground worker;
background work uses supported wait/results, never empty Agent/resume polling.

Preserve originals and use only permitted input/output scope. Viewing does not
itself authorize AI processing/storage. Protected content cannot enter jobs/temp
or learning without its approved path. Stop actually denied items and continue
independent allowed work; read `../company-agent/references/business-protection.md`
only when interpreting restrictions. Do not infer DRM from generic errors.

1. Run `business artifact-start --output "<final.html>" --state-root "<stateRoot>"` once. Keep returned workFile/jobPath/workingDirectory across workers and corrections; existing files are preserved.
2. Write the full job at jobPath: title, confirmed style/length/mode, and permitted sections with title/body/bullets/table/chart/image. Use the reference for layout/eyebrow/takeaway/source, kpis and facts/checks. Do not invent fields or figures. Large work shows an outline or representative page first.
3. Derive numeric summaries from actual table/chart cells and reuse {{fact:id}}. Recompute totals/denominators/rounding; do not copy earlier summary arithmetic. freeform/3D/Y2K are supported styles, not permission for arbitrary code or claims of external image generation.
4. Run `business html --spec "<jobPath>" --work "<workFile>" --state-root "<stateRoot>"`. Shipped local HTML/CSS/JS needs no package/font downloads. Read validation/warnings and the actual saved report.
5. Compare totals, recommendation status and exclusions against sources, not only individual input rows. Check actual visuals when an approved browser is available; existence or SVG presence is not visual QA. arithmetic=checked covers declared calculations only; sourceAccuracy/visual=not_verified must not become a blanket pass. Keep summaries/version labels consistent with revised tables.
6. After checks run `business artifact-publish --work "<workFile>" --state-root "<stateRoot>"` and deliver its final path, selected format and relevant limitations. Keep jobs/drafts/QA internal; do not create draft2/v2 copies.

Use `../company-agent/references/output-delivery.md` only for lifecycle questions.
Publish cleans registered unchanged intermediates; final/referenced/modified/unknown
files stay. Cleanup failure does not justify regenerating the report or broad deletion.
For a blocked command retain the spec and name that actual pending/denied operation;
do not declare all Bash/tools unavailable. Continue independent requested work.
Use genuinely connected approved image tools only if needed, otherwise native
charts/shapes or permitted images; disclose actual limitations. Learning receives
only allowed abstract preferences or verified fixes, never source reports.
