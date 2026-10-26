---
name: html-report
description: HTML 보고서 제작 시 디자인·분량·표시 방식·글꼴을 선택받아 오프라인 보고서를 만듭니다. 후속 요청에 현재 작업의 흐름·구조를 다이어그램으로 설명합니다. 기존 웹앱의 화면·컴포넌트 개발은 web-interface 역할입니다.
---

# HTML report

## 바로 다음 행동

작업 후 흐름·구조 설명 요청이면 `references/explanation-diagrams.md`를 한 번 읽고
현재 근거로 설명합니다. 완료만으로 도식을 만들지 않습니다. `방금 작업 정리해줘`는
짧은 텍스트부터, `글로만/도표 없이/그리지 마`는 도식 없이 답합니다. 아래는 일반 보고서용입니다.

Reuse known answers. Explicit `추천대로 / 알아서 / 질문 없이 완성` fills missing
ordinary choices (minimal / standard / scroll / fontChoice:auto); skip those questions. Preserve
explicit references/additional styles and external permissions. Otherwise immediately ask ONE
missing design question:
Show the following choices together in chat; accept a number or name:
1. 깔끔한 업무형(추천)
2. 지표 중심형
3. 추가 디자인(미리보기)
4. HTML 양식 직접 첨부
5. 레퍼런스 1 · 스토리형 설명 — 질문·예시·근거·해석을 차분히 따라 읽는 구성
6. 레퍼런스 2 · 데이터 리포트형 — 핵심 지표·주제별 비교·상세 표를 목차로 찾아보는 구성
7. 레퍼런스 3 · 발표형 — 한 화면의 핵심 메시지와 넓은 표·차트, 짧은 설명을 나란히 배치
Never batch the initial design question with length/mode. To ask, do not run commands,
write empty JSON, read references or start workers. Questions stay in chat.
Item 3 is NOT a report style; it opens additional designs.
Items 5–7 map to referencePreset:reference-1/2/3. `레퍼런스 1로` means the reference, not menu item 1. Keep this value in choices/job and preserve explicit style/mode. Without a style use editorial/bento-grid/minimalism respectively. Ask only missing format/font; no web fetch or template approval.

Use the quoted `company_agent_runtime.cliCommand` prefix and stateRoot literally.
Metadata is not executable. No runtime/source discovery, guessed commands, echo/noop or repeated Skill loading. Reuse current selected guidance. Preserve permissions and scope.

Order: design → design_detail (additional only) → format → ready. Preserve explicit choices;
merge replies, NEVER replace the whole object. Do not ask length/mode or start a worker before a specific design is chosen.
At format ask only missing 분량(핵심/보통/상세), 방식(스크롤/페이지/둘 다), 글꼴.
새 작업은 fontChoiceRequired:true를 두고 글꼴은 아래 다섯 가지를 채팅에 한 번에 보여 주세요.
1. Noto Sans KR — 긴 본문·업무 보고서 (noto-sans-kr)
2. Pretendard — 숫자·버튼·표가 많은 화면 (pretendard)
3. 나눔스퀘어 네오 — 제목·짧은 안내가 또렷한 화면 (nanum-square-neo)
4. 디자인에 맞게 알아서 선택 (auto)
5. 직접 입력 — 글꼴 이름 입력 (custom + fontName)
이미 정한 글꼴은 유지하고 직접 입력은 이름만 받습니다. 승인한 양식 글꼴 유지는 fontChoice:auto로 기록합니다.
글꼴 선택은 설치·외부 연결 동의가 아닙니다. 기본 fontSource:system과 PC 대체 글꼴을 씁니다. auto의 양식 우선·본문/지표별 글꼴은 제작기가 선택합니다.
Accept `1 / 보통 / 스크롤`. `추천대로`: minimal / standard / scroll for missing values;
absence of a reply is not acceptance. Style choice does not waive approval for publication, protected access or installation.

Only for ambiguity/complex resumption, optionally run
`business html-choices [--spec "<choices.json>"] --state-root "<stateRoot>"`.
No known choices: omit --spec. Otherwise Write `<stateRoot>/tmp/html-choices-<short-id>.json`
with only designMenu/style/referencePreset/length/mode, fontChoiceRequired/fontChoice/fontName/fontSource and relevant htmlTemplate/templateReview.
Example: `{"designMenu":"additional","length":"detailed","mode":"scroll"}`
needs only style. Follow stage/missing; input_required means waiting, not failure.
Keep source content in the full job; delegate generation only after ready, without reasking choices.

## 추가 디자인을 고른 경우에만

Use the same chat menu in CLI and Workspace; do not wait for automatic app cards.
Show all ten numbered names/descriptions below and END THIS TURN.
If used, IMMEDIATELY show the helper's selectionPrompt instead.
Use chat number/name replies, not AskUserQuestion groups/pages, 1~4 / 5~8 splits
or another confirmation.

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
While waiting, neither work nor append another yes/no question.
Preview is optional: on request run `business html-designs --open --state-root "<stateRoot>"`,
link the file, return to the same design question and WAIT. Opening proves neither
viewing nor acceptance. In CLI accept number/name/pasted choice, not browser clicks.
Opening failure does not reset choices. Never read the full picker HTML into context.

## HTML 양식 직접 첨부

Set designMenu:"template"; ask only for a missing .html/.htm path. Never execute attached scripts or fetch assets. Create one artifact work below, then run
`business html-template --template "<file>" --output "<workingDirectory>/reference-preview.html" --open`.
Show the synthetic style preview and its limits (not a DOM/pixel clone). Ask `이 느낌으로 진행 / 바꾸고 싶은 부분 입력 / 다른 양식 첨부` before missing format choices. Copy returned htmlTemplate/templateReview and hashes into choices/job; only actual acceptance sets templateReview.confirmed:true. Preserve known choices. Never invent hashes or save source HTML in Memory.

## 선택 완료 후 제작

At full-job authoring read `references/design-and-numbers.md` once. Apply its local patterns without web search or extra review stages. Pass that path, this Skill, choices/runtime/workFile to one foreground worker; background work uses supported wait/results, not empty polling.

Preserve originals and approved scope. Stop denied items; generic errors do not prove DRM.
Read `../company-agent/references/business-protection.md` only for restrictions.
Viewing is not AI processing/storage approval; do not put protected content into jobs/temp/learning without authorized access.

1. Run `business artifact-start --output "<final.html>" --state-root "<stateRoot>"` once. Keep returned workFile/jobPath/workingDirectory across workers and corrections; existing files are preserved.
2. At jobPath write title, selected style/referencePreset/length/mode/fontChoice (custom needs fontName) and sections. Follow the supported schema and selected reference's flow; preserve source facts. Set contentOrder/contentLayout explicitly. Current instructions override preferences without rewriting them. Invent no fields/figures; show an outline/representative page for large work.
3. Calculate totals/denominators/rounding from table/chart cells and reuse {{fact:id}}, not earlier summaries. freeform/3D/Y2K permit neither arbitrary code nor invented image-generation claims.
4. Run `business html --spec "<jobPath>" --work "<workFile>" --state-root "<stateRoot>"`. No package/font downloads. Read validation/warnings and the saved report.
5. Verify source totals, conclusions and exclusions, not only individual input rows. contentLayoutValidation checks order only; arithmetic=checked covers declared formulas, not sourceAccuracy/visual. Inspect wide/narrow layouts for empty columns and crowded text. For screenshots read `../presentation/references/image-review.md`: all sections first, then changed regions. File existence is not visual QA. Match summaries/version labels to revised data.
6. After checks run `business artifact-publish --work "<workFile>" --state-root "<stateRoot>"` and deliver its final path, selected format and relevant limitations. Keep jobs/drafts/QA internal; do not create draft2/v2 copies.

For lifecycle questions use `../company-agent/references/output-delivery.md`.
Publish removes only registered unchanged intermediates. Preserve final/referenced/modified/unknown files; cleanup failure permits no broad deletion or regeneration.
Keep blocked-command specs and name the pending/denied action. Continue independent work; use existing image tools only when needed and state actual limits.
Learning takes allowed abstract preferences/verified fixes, never source reports.
