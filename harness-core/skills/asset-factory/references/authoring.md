# 개인 스킬의 한 원본 저장

주입된 cliCommand 뒤에 아래 인자를 붙입니다. stateRoot와 현재 프로젝트의 실제 경로를 그대로 사용하고 설치 경로를 찾거나 사용자에게 내부 ID를 요청하지 않습니다.

## 새로 저장

먼저 `skill resolve "<이름>" --project-root "<프로젝트>"`로 같은 이름을 확인합니다. 선택한 범위가 개인 전체이면 personal, 현재 프로젝트이면 project를 씁니다.

UTF-8 JSON 파일의 최소 명세:

```json
{"type":"skill","name":"weekly-summary","description":"주간 업무 자료를 같은 순서로 정리할 때 사용합니다.","instructions":"# 주간 업무 요약\n지정한 자료에서 진행과 미완료 항목을 구분하고 출처를 남깁니다."}
```

```text
asset create --spec "<명세.json>" --state-root "<stateRoot>" --storage-scope personal --project-root "<프로젝트>"
asset validate "<생성 응답의 path 폴더>"
```

필요한 references는 문자열 배열입니다. 실제 생성되는 references/reference-1.md 등의 경로로 연결합니다. 검증은 반환된 폴더를 받으며 effectivePath는 실제 SKILL.md 파일입니다.

## 같은 원본 수정

```text
asset inspect --name "<이름>" --state-root "<stateRoot>" --project-root "<프로젝트>"
asset update --name "<이름>" --instructions-file "<수정 본문.md>" --expected-sha256 "<조회 해시>" --state-root "<stateRoot>" --project-root "<프로젝트>"
```

inspect가 반환한 effectivePath를 읽습니다. 수정 본문에는 frontmatter를 넣지 않습니다. 이름과 범위, 도구 연결과 추가 frontmatter를 유지합니다. description은 바꿀 때만 명시합니다. 원본이 바뀌었으면 새 해시를 임의로 만들어 덮어쓰지 말고 실제 변경을 비교합니다. partial이면 변경된 부분과 백업 위치를 알려줍니다.

검증 성공은 본문과 연결 구조 확인이며 실제 업무 수행 성공과 다릅니다. 이미 확인된 업무 결과는 재사용하고 새 환경에서 실행하지 않은 부분은 미확인으로 남깁니다. 이 경로는 script-tool/MCP 생성과 활성화를 제공하지 않습니다.
