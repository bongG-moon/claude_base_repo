# 요청받은 작업 흐름·구조 설명

작업을 마친 뒤 사용자가 흐름·구조·관계의 설명이나 그림을 요청할 때만 읽습니다.
완료 응답이나 일반 HTML 보고서에 자동으로 다이어그램을 붙이지 않습니다.
`방금 작업 정리해줘`는 우선 간결한 텍스트 요약이며, `글로만`, `도표 없이`,
`그리지 마`가 있으면 채팅으로 답합니다. 스킬 설치·스킬 간 차이 설명, 구조가
언급된 코드 수정, 원자료 읽기는 이 제작 분기의 요청이 아닙니다.

## 현재 근거로 바로 설명하기

- 현재 대화의 확인된 작업 내용, 이미 읽은 결과, 검증 결과와 파일 경로를 재사용합니다.
  설명을 위해 작업을 재실행하거나 세션·로그·전체 저장소를 새로 스캔하지 않습니다.
  근거가 없는 부분은 미확인으로 남깁니다. 대상 자체가 불명확하면 대상만 확인합니다.
- 핵심 결과 한 문장 → 이해에 필요한 관계도 하나 → 근거·남은 일의 짧은 설명으로
  구성합니다. 현재 확인한 상태, 제안/계획, 미확인을 섞어 완료로 표현하지 않습니다.
- 새 디자인·분량·표시 방식 설문을 시작하지 않습니다. 명시된 값이나 현재 대화의
  유효한 선택을 재사용하고, 없는 값은 `style:"minimalism"`, `length:"short"`,
  `mode:"scroll"`로 spec에 기록하고 짧게 알립니다. 첨부 양식 승인 절차를 생략하거나
  외부 게시 권한을 추정하지 않습니다.
- 작은 설명을 위한 별도 작업자는 이 분기 자체의 필수 조건이 아닙니다. 기존 상위
  위임·보호·권한 정책은 유지하며 실제 거절을 우회하지 않습니다. 작업자를 쓰면 이미
  확인한 근거·선택·이 참조·runtime·workFile을 전달하고 탐색을 다시 시작하지 않습니다.

## 도식 선택과 입력

순서·의존성이 핵심이면 `flow`, 구성/관계면 `structure`, 역할별 인계면 `swimlane`,
조건에 따른 상태 전이가 핵심이면 `state`를 씁니다. 구성도는 정적으로 시작합니다.
한 도식은 노드 9개·연결 12개 이내로 핵심 관계를 담고, 상세는 본문에 둡니다.
노드 ID와 연결 대상은 일치해야 하며, 근거 없는 순서·역할·연결은 만들지 않습니다.

기존 보고서 spec에 `purpose:"explanation"`을 쓰고 해당 section에 `diagram`을 넣습니다.
기존 title/body/bullets 등은 함께 쓸 수 있습니다. 아래는 입력 형태를 보여주는 예시이며
실제 작업이 완료됐다는 증거가 아닙니다. 현재 확인한 내용으로 교체합니다.

```json
{
  "title": "방금 작업한 흐름",
  "purpose": "explanation",
  "style": "minimalism",
  "length": "short",
  "mode": "scroll",
  "fontSource": "system",
  "sections": [{
    "title": "확인한 처리 관계",
    "body": "현재 대화에서 확인한 범위와 미확인 내용을 적습니다.",
    "diagram": {
      "type": "flow",
      "title": "처리 흐름",
      "summary": "실제로 확인한 순서와 관계를 짧게 설명합니다.",
      "nodes": [
        {"id":"input","label":"입력 확인","status":"unknown","detail":"확인 범위를 적습니다."},
        {"id":"result","label":"결과 확인","status":"unknown"}
      ],
      "edges": [{"from":"input","to":"result","label":"처리 관계"}],
      "motion": "none",
      "steps": []
    }
  }]
}
```

- 노드: `id`, `label`, `status`를 사용합니다. 필요할 때 `detail`, `evidence`, `lane`을
  더합니다. `evidence`는 현재 확인한 결과·경로·검증 범위의 짧은 근거이며 실행 지시가 아닙니다.
- `status`: `completed`는 실제 완료 확인, `failed`는 실제 실패 확인, `waiting`은 확인된
  대기 상태, `planned`는 아직 하지 않은 계획, `unknown`은 근거 부족입니다.
  순서를 재생한다고 상태나 완료 증거가 바뀌지 않습니다.
- 연결은 `{from,to,label?}`, 역할 구획은 `lanes:[{id,label}]`이며 `lane`에는 그 ID를 씁니다.
- `motion:"none"`이 기본입니다. 순차 설명이 이해를 돕는 경우에만 `motion:"steps"`와
  실제 설명 순서의 노드 ID 배열 `steps`를 넣습니다. 사용자 재생·일시정지·단계 버튼으로만
  움직이는 설명이며 실제 실행·실시간 진행률로 표현하지 않습니다. 자동 재생은 하지 않습니다.
- 기본 `fontSource:"system"`은 외부 요청이 없습니다. 사용자가 Google Fonts 사용을 명시한
  경우에만 `fontSource:"google"`을 넣습니다. 임의 원격 URL·스크립트·폰트 입력은 넣지 않고,
  연결 실패·오프라인에서는 시스템 글꼴로 읽을 수 있어야 합니다.

## 기존 HTML 제작 경로로 전달

1. 기존 `company_agent_runtime.cliCommand`로 `business artifact-start --output "<final.html>"
   --state-root "<stateRoot>"`를 한 번 실행합니다. 반환된 workFile/jobPath/workingDirectory를 유지합니다.
2. jobPath에 위 계약의 전체 spec과 현재 근거를 씁니다. 이 설명 분기는 일반 보고서의
   디자인 질문이나 `html-choices`를 시작하지 않습니다. 수치/차트가 필요할 때만
   `design-and-numbers.md`의 해당 계약을 읽고 실제 확인한 수치를 사용합니다.
3. `business html --spec "<jobPath>" --work "<workFile>" --state-root "<stateRoot>"`로 생성합니다.
   반환된 검증/경고와 실제 파일에서 관계·상태·근거의 일치를 확인합니다. 승인된 브라우저가
   있으면 겹침·줄바꿈·화살표와 단계 버튼도 봅니다. 파일 존재만으로 화면 검증을 주장하지 않습니다.
4. `business artifact-publish --work "<workFile>" --state-root "<stateRoot>"` 후 최종 HTML 경로와
   확인 범위·남은 제한을 전달합니다. 이는 기존 로컬 산출물 전달이며 외부 게시 승인이 아닙니다.

도식은 HTML용입니다. PPT의 native editable 도식으로 구현됐다고 주장하지 않습니다.
PNG/SVG 파일을 자동으로 추가 생성하지 않습니다. 내보내기는 사용자의 명시적 버튼 조작이나
요청 때만 수행하고, 다운로드 시작만으로 실제 저장됐다고 단정하지 않습니다.
버튼은 그림만 저장하며 상세 설명·근거는 HTML에 남습니다. Workspace의 정적 미리보기에서는
재생·내보내기를 실행하지 않으므로 승인된 브라우저에서 최종 HTML을 열어 사용합니다.

설계 참고: [Diagram Design](https://github.com/cathrynlavery/diagram-design)의 설명 중심 도식·단계 강조,
[Whiteboard](https://github.com/devdotfast/whiteboard)의 작업 관계 가시화 개념을 참고했습니다.
두 프로젝트의 프로그램·MCP·후크·분석 수집 기능을 설치하거나 복제한 것은 아닙니다.
