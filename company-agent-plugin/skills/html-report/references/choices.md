# 추가 디자인, 첨부 양식, 선택 복원

선택이 이미 정해졌거나 자동 선택을 맡겼으면 이 문서는 필요 없습니다. 현재 분기만 적용하고 이미 받은 답은 합쳐서 유지합니다. 선택 전용 명세와 보고서 내용이 있는 전체 job은 구분합니다.

## 디자인이 아직 없을 때

다음 일곱 항목과 빠진 분량, 보기, 글꼴을 같은 응답에서 한 번에 보여주고 답을 기다립니다. 질문만 할 때 명령이나 빈 JSON은 필요 없습니다.

1. 깔끔한 업무형 (`minimalism`)
2. 지표 중심형 (`bento-grid`)
3. 추가 디자인(미리보기)
4. HTML 양식 직접 첨부
5. 레퍼런스 1: 스토리형 설명, 질문에서 사례와 근거로 이어지는 구성
6. 레퍼런스 2: 데이터 리포트형, 지표에서 상세 표로 이어지는 구성
7. 레퍼런스 3: 핵심 브리핑형, 판단과 비교 근거, 실행 조건을 정리하는 구성

`레퍼런스 1`은 메뉴 1번이 아닙니다. 5~7은 `referencePreset:reference-1/2/3`이며 지정 스타일이 없을 때만 editorial/bento-grid/minimalism을 적용합니다. 이후 스타일 질문은 반복하지 않습니다.

빠진 분량(핵심/보통/상세), 보기(스크롤/페이지/둘 다), 글꼴을 디자인과 함께 묻습니다. 글꼴은 Noto Sans KR(`noto-sans-kr`), Pretendard(`pretendard`), 나눔스퀘어 네오(`nanum-square-neo`), 디자인에 맞게 알아서(`auto`), 직접 입력(`custom`과 `fontName`) 다섯 항목입니다. 이미 받은 답은 유지하고 새 작업의 `fontChoiceRequired:true`를 설정합니다. `알아서/추천대로/질문 없이`는 빠진 값만 SKILL.md의 기본값으로 채우며 질문을 추가하지 않습니다.

첨부 양식은 미리보기 확인과 같은 질문에서 “기존에 정한 글꼴 유지 / 첨부 글꼴 따라가기 / 다른 글꼴” 중 미정인 것만 받습니다. 기존 글꼴 유지는 해당 `fontChoice`와 `fontName`을 보존하고, 첨부 글꼴 따라가기는 `fontChoice:auto`로 기록합니다. `auto`는 참고가 있을 때 참고 글꼴, 없을 때 디자인별 기본 글꼴입니다. 현재 요청에서 글꼴을 이미 명시했으면 다시 묻지 않습니다. 색감, 표, 배치 등 다른 참고 특징은 유지합니다.

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

## 완성 예제로 레퍼런스를 고를 때

`assets/design-picker.html`에는 세 레퍼런스의 **완성 예제 열기** 링크가 있습니다. 각각 `assets/examples/reference-1.html`, `reference-2.html`, `reference-3.html`이며 모두 가상 자료를 같은 보고서 생성기로 만든 예제입니다. 사용자에게 갤러리 또는 해당 파일의 클릭 가능한 절대 경로를 먼저 전달합니다. 링크 없이 “미리보기가 있다”고만 안내하지 않습니다.

레퍼런스 1은 원리와 사례 설명, 2는 지표와 데이터 탐색, 3은 판단과 실행 조건을 정리하는 핵심 브리핑입니다. 3의 기존 발표형 ID와 페이지 보기 호환은 유지합니다. 사용자가 보기만 원하면 추가 승인이나 선택 절차를 만들지 않습니다. 내용을 정할 때만 [레퍼런스 적용](report-references.md)을 읽고 이미 정한 색상, 글꼴, 분량과 보기 방식을 유지합니다.

## HTML 양식 첨부

`designMenu:"template"`로 두고 없는 .html/.htm 경로만 받습니다. 기존 workFile이 없을 때만 SKILL.md의 artifact-start를 한 번 실행한 뒤 다음 명령을 사용합니다.

`business html-template --template "<file>" --output "<workingDirectory>/reference-preview.html" --open`

생성 직후 반환된 `previewLink`를 채팅에 표시하고 `previewPath`도 함께 안내합니다. 링크가 열리지 않으면 파일 탐색기에서 해당 HTML을 두 번 클릭하도록 알려 줍니다. “미리보기를 만들었습니다”만 말하고 위치를 생략하지 않습니다. `previewCreated:false`이면 분석만 수행한 것이며 미리보기를 만들었다고 하지 않습니다. 자동 열기를 요청했더라도 실제 창 표시를 확인한 것으로 설명하지 않습니다.

참고 파일은 10MiB 미만(10,485,760바이트 미만)입니다. 도우미의 `layoutHints`는 정적 구조의 단서이며 실제 화면 확인과 구분합니다. 원본 HTML 전체를 모델에 읽어 넣거나 외부 자원, 원본 스크립트를 실행하지 않습니다. 결과는 정적 특징을 보여주는 가상 내용 미리보기이며 원본 복제가 아닙니다. `이 느낌으로 진행 / 바꾸고 싶은 부분 / 다른 양식`과 아직 빠진 분량, 보기, 글꼴 선택을 같은 질문에서 받습니다. 반환된 htmlTemplate, templateReview와 해시를 같은 job에 합치고 실제 승인 뒤에만 `templateReview.confirmed:true`로 둡니다. 이미 답한 항목은 반복하지 않습니다. 해시를 만들거나 원문을 Memory에 저장하지 않습니다.

## 선택 도우미가 필요한 경우

런타임 cliCommand 뒤에 `business html-choices [--spec "<choices.json>"] --state-root "<stateRoot>"`를 붙입니다. 알려진 선택이 없으면 --spec을 생략합니다. 있다면 `<stateRoot>/tmp/html-choices-<short-id>.json`에 designMenu/style/referencePreset/length/mode, fontChoiceRequired/fontChoice/fontName/fontSource와 해당 htmlTemplate/templateReview만 넣습니다. 본문과 원자료는 전체 job에 둡니다.

예를 들어 `{"designMenu":"additional","length":"detailed","mode":"scroll","fontChoice":"auto"}`는 스타일만 빠진 상태입니다. `missing`의 항목을 현재 질문에 함께 넣고 `preservedChoices`는 유지합니다. input_required는 실패가 아닌 선택 대기입니다. 디자인이나 추가 디자인 질문에서 분량, 보기, 글꼴도 함께 답할 수 있으며 양식은 실제 미리보기 확인에 이 항목을 합칩니다. 모든 값이 있으면 ready입니다. 같은 선택을 위해 본문, 목록, 소스 코드를 다시 탐색하지 않습니다.
# 기본 글꼴과 미리보기

기존 선택과 참고 양식이 우선입니다. 별도 지정이 없는 설명형은 Noto Sans KR, 지표형은
Pretendard이며 배포된 글꼴을 사용합니다. 선택 화면에서 글꼴을 바꾸면 축소 예시에도
즉시 반영합니다. 10가지 디자인의 완성 예제 링크는 각 양식의 기본 글꼴로 열립니다.
갤러리는 글꼴 파일을 공유하고 실제 생성 HTML에는 선택한 글꼴 하나만 넣습니다.
fontSource:system은 기존 PC 글꼴만 쓰려는 명시 선택이며 그대로 유지합니다.
직접 입력과 나눔스퀘어 네오는 PC에 없으면 대체 글꼴로 표시될 수 있습니다.
글꼴 base64나 전체 HTML을 검증 목적으로 모델에게 읽히지 않고, job과 생성 결과의
typography 메타데이터를 확인합니다. 파일 포함과 실제 렌더링 확인은 구분합니다.
