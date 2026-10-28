# 추가 디자인, 첨부 양식, 선택 복원

SKILL.md의 일반 선택만으로 진행할 수 있으면 이 문서는 필요 없습니다. 현재 분기만 적용하고 이미 받은 답은 합쳐서 유지합니다. 선택 전용 명세와 보고서 내용이 있는 전체 job은 구분합니다.

## 추가 디자인을 골랐고 특정 스타일은 아직 없을 때

CLI와 Workspace 모두 아래 목록을 채팅에 한 번에 보여주고 답을 기다립니다. 질문 도구의 네 항목 제한에 맞춰 목록을 나누거나 추가 확인 질문을 만들지 않습니다.

1. 미니멀리즘 — 깔끔한 업무형 (`minimalism`)
2. 벤토그리드 — 크기가 다른 지표 구획 (`bento-grid`)
3. 에디토리얼 — 잡지형 구획과 큰 제목 (`editorial`)
4. 글래스모피즘 — 하늘색, 라벤더 배경과 밝은 유리판 (`glassmorphism`)
5. 뉴모피즘 — 부드러운 양방향 그림자 (`neumorphism`)
6. 브루탈리즘 — 각진 선과 강한 색 강조 (`brutalism`)
7. 그라디언트 메시 — 색이 번지는 배경 (`gradient-mesh`)
8. 자유양식 — 준비된 구성의 비대칭 조합 (`freeform`)
9. 3D, 이머시브 — 베이지와 브라운 입체 장식 (`immersive-3d`)
10. 레트로, Y2K — 은빛 크롬과 파스텔 (`retro-y2k`)

`번호나 이름을 입력해 주세요. 미리보기를 원하면 미리보기라고 입력해 주세요.`로 응답을 마칩니다. 이미 특정 스타일을 알려줬다면 이 메뉴를 생략합니다. 미리보기 요청에만 `business html-designs --open --state-root "<stateRoot>"`를 실행하고 링크를 보여준 뒤 같은 선택을 받습니다. 전체 미리보기 HTML을 모델 입력으로 읽지 않습니다. 창 열기 성공이나 실패는 선택을 대신하거나 초기화하지 않습니다.

## HTML 양식 첨부

`designMenu:"template"`로 두고 없는 .html/.htm 경로만 받습니다. 기존 workFile이 없을 때만 SKILL.md의 artifact-start를 한 번 실행한 뒤 다음 명령을 사용합니다.

`business html-template --template "<file>" --output "<workingDirectory>/reference-preview.html" --open`

외부 자원이나 원본 스크립트를 실행하지 않습니다. 결과는 색과 글꼴 등의 정적 특징을 보여주는 가상 내용 미리보기이며 원본 DOM이나 픽셀 복제가 아닙니다. `이 느낌으로 진행 / 바꾸고 싶은 부분 입력 / 다른 양식 첨부`를 묻고 실제 확인한 답을 기다립니다. 반환된 htmlTemplate, templateReview와 해시를 그대로 전체 job에 합치며 해당 미리보기 승인 뒤에만 `templateReview.confirmed:true`로 둡니다. 이후 빠진 분량, 방식, 글꼴만 확인하고 같은 workFile로 제작합니다. 해시를 만들거나 원본 HTML을 Memory에 저장하지 않습니다.

## 선택 도우미가 필요한 경우

런타임 cliCommand 뒤에 `business html-choices [--spec "<choices.json>"] --state-root "<stateRoot>"`를 붙입니다. 알려진 선택이 없으면 --spec을 생략합니다. 있다면 `<stateRoot>/tmp/html-choices-<short-id>.json`에 designMenu/style/referencePreset/length/mode, fontChoiceRequired/fontChoice/fontName/fontSource와 해당 htmlTemplate/templateReview만 넣습니다. 본문과 원자료는 전체 job에 둡니다.

예를 들어 `{"designMenu":"additional","length":"detailed","mode":"scroll"}`은 스타일만 빠진 상태입니다. 반환한 stage/missing과 preservedChoices를 따릅니다. input_required는 실패가 아닌 선택 대기입니다. stage는 design → design_detail(추가 디자인만) → format → ready이며 양식은 template_attach → template_preview → template_confirm 단계를 먼저 거칩니다. 도우미 출력을 읽으면 같은 선택을 위해 본문, 목록, 소스 코드를 다시 탐색하지 않습니다.
