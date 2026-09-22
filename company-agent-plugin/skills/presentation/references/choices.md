# PPT 선택값과 재개

단순 첫 질문은 SKILL 본문에서 바로 묻는다. 이 문서는 선택 규칙이 모호하거나
기존 작업을 재개할 때만 읽는다. 다른 SKILL이나 참조를 연쇄로 다시 읽지 않는다.

명령은 전달된 `company_agent_runtime.cliCommand` 전체 문자열 뒤에 붙인다.
Python 모듈 이름·소스 경로를 추측하지 않는다. 초기 질문 확인에는 파일이 필요 없다.

```text
business ppt-choices --state-root "<stateRoot>"
business ppt-choices --spec "<choices.json>" --state-root "<stateRoot>"
```

실제로 지정된 양식이 있으면 `--template "<PPTX 또는 저장한 대표 HTML 경로>"`를 붙인다.
선택값을 파일로 유지할 필요가 있을 때만 Write로
`<stateRoot>/tmp/ppt-choices-<short-id>.json`을 만든다. 다음은 형식 예시이며
사용자의 알려진 값만 넣는다. 예시 내용을 사용자 답변으로 간주하지 않는다.

```json
{"creationMode":"new","purpose":"실적 보고","audience":"부서장","slideCount":5,"designPreset":"business"}
```

| 사용자 선택 | 값 |
|---|---|
| 새 디자인 | creationMode: new |
| 참고 캡처·기존 PPT | creationMode: reference |
| 저장한 HTML 대표 양식 | creationMode: saved + 실제 --template |
| PPTX 분위기 참고 / 기존 배치 유지 | referenceMode: style / preserve |
| 깔끔한 업무 보고형 / 흑백 간결형 / 따뜻한 설명형 | designPreset: business / monochrome / warm |

공통 선택값은 creationMode, referenceMode(해당 시), purpose, audience,
slideCount, designPreset(새 디자인)이다. 참고 이미지는 referenceImages에 실제
PNG/JPEG 경로 1–3개로 유지한다. 캡처와 저장 HTML은 style이며 preserve는 PPTX용이다.
기존 정적 HTML은 htmlSource:{path,selector?,viewportWidth?}를 유지한다.
slides/referenceImages/다른 --template과 섞지 않는다.

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
