# 아직 정하지 않은 선택만

기존 선택이나 참고 양식으로 시작할 수 있으면 이 문서를 읽지 않습니다. `알아서/추천대로/질문 없이`를 요청하면 SKILL.md의 기본값으로 빠진 항목만 채웁니다. 수정 요청에 설문을 다시 시작하지 않습니다.

## 디자인이 없을 때

다음 목록을 한 번에 보여주고 번호나 이름으로 답을 받습니다. 질문을 위해 빈 명세나 CLI 호출을 만들지 않습니다.

1. 깔끔한 업무형 (`minimalism`)
2. 지표 중심형 (`bento-grid`)
3. 추가 디자인: 10가지 중 선택
4. HTML 양식 참고
5. 레퍼런스 1: 스토리형 설명, 질문에서 사례와 근거로 이어지는 구성
6. 레퍼런스 2: 데이터 리포트형, 지표에서 상세 표로 이어지는 구성
7. 레퍼런스 3: 핵심 브리핑형, 판단과 비교 근거, 실행 조건을 정리하는 구성

`레퍼런스 1`은 메뉴 1번이 아닙니다. 5~7은 `referencePreset:reference-1/2/3`을 사용하고 지정 스타일이 없을 때만 editorial/bento-grid/minimalism을 적용합니다. 이후 스타일 질문은 반복하지 않습니다. 구성 작성 때만 [report-references.md](report-references.md)의 선택 항목을 봅니다.

추가 디자인을 원할 때만 [design.md](design.md)의 디자인 목록을 한 번에 제시합니다. 예시를 원하면 `assets/design-picker.html`의 클릭 가능한 절대 경로를 전달합니다. 예제 HTML 전체를 모델 입력으로 읽지 않습니다. 첨부 HTML은 [html-template.md](html-template.md), PPT나 이미지는 [reference-style.md](reference-style.md)로 이어갑니다.

## 디자인이 정해진 다음

빠진 분량(핵심/보통/상세), 보기(스크롤/페이지/둘 다)와 글꼴만 한 번에 묻습니다. 이미 정한 값은 유지하며 새 작업의 `fontChoiceRequired:true`를 설정합니다.

| 글꼴 선택 | 명세 |
|---|---|
| Noto Sans KR: 긴 본문 | `fontChoice:noto-sans-kr` |
| Pretendard: 지표와 표 | `fontChoice:pretendard` |
| 나눔스퀘어 네오: 제목과 안내 | `fontChoice:nanum-square-neo` |
| 디자인에 맞게 알아서 선택 | `fontChoice:auto` |
| 직접 입력 | `fontChoice:custom`, `fontName`에 이름 |

승인한 참고 글꼴 유지도 `auto`입니다. 양식이 없으면 본문형은 Noto Sans KR, 지표형은 Pretendard를 동봉 파일로 HTML에 넣습니다. 직접 입력과 나눔스퀘어 네오는 PC에 없으면 대체 글꼴로 보입니다. PC 설치나 외부 접속은 추가하지 않으며 `fontSource:google`은 외부 연결을 허용했을 때만 씁니다. 생성 결과의 글꼴 정보와 실제 화면 확인은 구분합니다.
