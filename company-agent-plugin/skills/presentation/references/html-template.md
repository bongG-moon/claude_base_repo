# HTML 대표 양식 저장과 재사용

일회성 업무 초안은 내부 작업 공간에 저장된다. 반복 사용할 대표 디자인은
승인된 job으로 별도 저장한다. 초안과 대표 양식은 같은 파일이 아니다.

사용자가 재사용 양식을 원하면 저장 위치만 확인한다. **내 PC에서 개인적으로 사용** /
**이 프로젝트에서만 사용** 중 이미 정한 범위는 다시 묻지 않는다. 개인 경로는 실제
등록된 사용자 상태 경로 아래 사용자 지정 폴더, 프로젝트는 현재 프로젝트의 사용자
지정 폴더를 쓴다. 없는 폴더는 선택 후 만든다. 회사 공통 플러그인·정책을 고치지 않는다.
저장했다고 개인 Memory/Knowledge나 전체 프로젝트 설정에 자동 등록하지 않는다.

```text
business artifact-start --output "선택한-폴더/대표-양식.html" --state-root "<stateRoot>"
business ppt-template --spec "승인된-job.json" --work "<양식의 workFile>" --state-root "<stateRoot>"
business artifact-publish --work "<양식의 workFile>" --state-root "<stateRoot>"
```

양식 저장은 사용자가 추가로 요청했을 때만 별도 작업으로 만든다. 양식을 확인한 뒤
artifact-publish로 전달한다. 원래 초안에 `--template`을 사용했다면 ppt-template에 동일한 인자를 전달한다. 아직 승인하지 않았거나
내용·참고 자료·초안이 바뀌면 먼저 새 HTML 초안을 확인한다. 저장 과정에 추가 모델
호출·Office 실행·외부 서비스가 없다. 기존 파일도 덮어쓰지 않는다.

생성되는 HTML 한 파일에는 가상 예시와 검증 가능한 디자인 메타데이터가 들어간다.
기본 자동 배치는 3장 예시와 색상·글꼴·페이지 규격·공통 배치 버전을 저장한다.
HTML 직접 변환/자유 배치는 장별 카드·그림자·태그·텍스트 위치도 저장한다.
실제 업무 본문·수치·파일 경로·캡처·
원본 PPT·승인 기록은 넣지 않는다. 글자/표/차트는 가상 값, 그림은 빈 사각형으로 바꾼다.
임의 CSS 전체/스크립트를 저장한다고 설명하지 않는다. 기존 PPTX 개체/마스터 유지 모드는 원본이 필요하므로
이 명령으로 몰래 일반 디자인 양식으로 바꾸지 않는다.

다음 작업에서는 `creationMode:"saved"`와 새 목적·대상·장수·slides를 지정한다.

```text
business ppt-design-preview --spec "새-job.json" --template "대표-양식.html" --work "<새 작업의 workFile>"
```

자유 배치 양식은 `business ppt-analyze --template "대표-양식.html"`로 장별 슬롯 수를
확인한다. 새 slides에 `layoutIndex:1`(1부터), `texts:[...]`를 넣고 빈 슬롯은 빈 문자열로
지정한다. 표/차트 슬롯이 있으면 charts/tables 배열에 새 데이터를 지정한다. 개수 불일치는
내용을 생략하지 않고 중단한다. 직접 elements를 지정해서 새 배치로 조정할 수도 있다.
새 초안 승인 후 `business ppt`에도 같은 `--template`을 전달한다. 생성기는 저장한 HTML을
실행하지 않고 검증된 메타데이터만 읽는다. 일반 HTML은 `--template`으로 쓰지 않고
`native-layout.md`의 htmlSource로 먼저 변환한다. 지원하지 않는 CSS는 실제 제한을 알린다.
