# PPT 선택값과 재개

새 제작에 참고 양식도 디자인 지정도 없으면 아래 선택을 한 번 보여준다. 목적, 대상, 장수 중 모르는 항목도 같은 질문에 묶는다. 이미 정한 스타일, 첨부 양식과 기존 작업은 재질문하지 않는다. `알아서`, `추천대로`, `질문 없이`는 내용에 맞게 추천해 진행한다. 다른 SKILL이나 참조를 연쇄로 다시 읽지 않는다.

| 선택 | 설명 |
|---|---|
| 깔끔한 업무 보고형 | 흰 배경과 남색 제목, 청록 강조. 실적과 의사결정 보고 |
| 흑백 간결형 | 흑백 대비와 절제된 장식. 숫자, 표와 논리 중심 |
| 따뜻한 설명형 | 크림 배경과 차분한 갈색. 교육과 과정 설명 |
| 기존 양식 활용 | PPT, 장표 이미지 또는 HTML을 참고해 익숙한 스타일 유지 |
| 내용에 맞게 추천 | 자료와 청중에 맞는 구성과 강조를 선택 |
| 직접 입력 | 색, 글꼴, 분위기와 배치를 자유롭게 지정 |

번호나 이름으로 답할 수 있게 하며 현재 선택 도구의 항목 수 제한 때문에 선택지를 없애지 않는다. 필요하면 간결한 번호 목록을 사용한다. 양식 비교는 이번 자료를 여러 벌 만드는 것이 아니다. 실제 선택 뒤 해당 디자인의 시각 규칙을 내용에 맞는 표, 비교, 흐름과 결론 장에 적용한다.

명령은 전달된 `company_agent_runtime.cliCommand` 전체 문자열 뒤에 붙인다.
Python 모듈 이름·소스 경로를 추측하지 않는다. 초기 질문 확인에는 파일이 필요 없다.

```text
business ppt-choices --state-root "<stateRoot>"
business ppt-choices --spec "<choices.json>" --state-root "<stateRoot>"
```

실제로 지정된 양식이 있으면 `--template "<PPTX 또는 저장한 대표 HTML 경로>"`를 붙인다.
선택값을 파일로 유지할 필요가 있을 때만 Write로
`<stateRoot>/tmp/ppt-choices-<short-id>.json`을 만든다. 다음은 형식 예시이며
사용자의 알려진 값과 적용한 기본값만 넣는다. 예시 목적·장수를 사용자 답변으로 간주하지 않는다.

```json
{"creationMode":"new","purpose":"실적 보고","audience":"부서장","slideCount":5,"designPreset":"business"}
```

| 사용자 선택 | 값 |
|---|---|
| 새 디자인 | creationMode: new |
| 참고 캡처·기존 PPT | creationMode: reference |
| 저장한 HTML 대표 양식 | creationMode: saved + 실제 --template |
| PPTX나 이미지 첨부 / 명시적인 기존 배치 유지 | referenceMode: style 기본 / preserve 명시 |
| 깔끔한 업무 보고형 / 흑백 간결형 / 따뜻한 설명형 | designPreset: business / monochrome / warm |
| 내용에 맞게 추천 | new + 실제 선택한 지원 preset/theme |
| 직접 입력 | designDirection에 요청 보존, 지원 theme/font/elements에 실제 반영 |

공통 선택값은 creationMode, referenceMode(해당 시), purpose, audience,
slideCount, designPreset(새 디자인)이다. 참고 이미지는 referenceImages에 실제
PNG/JPEG/WebP 절대경로를 최대 60개까지 유지하고 2~3장씩 확인한다. 첨부는 style이 기본이며 preserve는 명시적인 PPTX 원본 개체 유지 요청에만 쓴다. 여러 이미지의 공통 스타일과 근거는 `referenceStyle`에 짧게 합친다. 참고가 있으면 기본 스타일 선택이나 유지 범위 질문을 반복하지 않는다.
기존 정적 HTML은 htmlSource:{path,selector?,viewportWidth?}를 유지한다.
slides/referenceImages/다른 --template과 섞지 않는다.
실제 참고 파일이 있으면 reference로 진행하며, 명시한 reference/saved 요청의 파일이 없을 때는 첨부를 기다린다. 선택 전의 누락을 기본값으로 확정하지 않는다. 추천을 선택한 뒤에는 새 설문 없이 지원 preset과 내용을 맞춰 전체 job에 기록한다.

입력값은 누적해서 합친다. 새 답변 하나 때문에 기존 선택·referenceImages·htmlSource·
designReview를 지우지 않는다. helper의 selection은 선택값이며 전체 job이나
사용자 승인 증거가 아니다. 반환값에 없는 기존 상태도 임의로 삭제하지 않는다.

- input_required: 해당 stage의 빠진 항목만 질문하고 실제 응답을 기다린다.
- design_preview / preview_required: 실패가 아니다. 전체 장수의 job을 작성하고
  같은 artifact work로 HTML 초안을 만든다. 선택용 파일을 곧바로 제작 명세로 쓰지 않는다.
  nextAction=prepare_full_job이면 contentRequirement의 field/requiredCount에 맞춰
  본문을 준비한다. create_html_preview이면 해당 전체 job으로 초안 명령을 실행한다.
- design_confirm: 최신 실제 HTML을 보여주고 승인 또는 수정을 기다린다.
- ready: full job의 choices와 최신 designReview를 유지하고 승인된 제작 단계로 간다.

초안 응답의 designReview를 전체 job에 병합하고, 확인받은 뒤 confirmed만 true로
바꾼다. 같은 workFile/jobPath를 계속 쓴다. 선택 도우미를 다시 부르기 위해
매번 full job을 분해하거나 승인된 초안을 새 work로 복사하지 않는다.
helper는 순서를 점검할 뿐 실제 사용자 동의나 미제공 파일의 존재를 보증하지 않는다.
invalid_choice이면 field와 allowedValues/expected에 맞춰 그 항목만 고친다.
regenerate_html_preview이면 같은 work에서 초안을 다시 만든다. 오류를 알아내기
위해 패키지 소스나 실행 파일을 탐색하거나 불변 입력으로 명령을 반복하지 않는다.

양식의 색감과 장별 배치는 별개다. 같은 색감 안에서도 pageRole에 따라 표지, 핵심 메시지, 비교, 업무 분기, 날짜 비례 일정, 상세 표와 결론을 다르게 구성한다. 선택용 가상 갤러리는 세 색감과 일곱 장 역할의 21개 예시이며, 사용자가 비교를 원할 때만 만든다. 해당 예시를 실제 업무 내용이나 승인 기록으로 사용하지 않는다.
