# 카드형 HTML과 편집 가능한 PPT

기본 자동 배치의 제한을 PowerPoint/전체 제작기의 제한이라고 설명하지 않는다.
둥근 카드·외부 그림자·알약 태그는 네이티브 도형, 글자는 텍스트로 만들 수 있다.
아래 경로는 기본 제공 코드이며 임의 Python/VBA 실행이 아니다. 수치·내용을 바꾸지 않는다.
현재 설치 버전이 불확실하거나 과거 기억에 “지원하지 않음”이 있으면
`business ppt-capabilities` 한 번으로 확인한다. 매 장마다 조회하지 않는다.

## 이미 HTML 디자인이 있는 경우: 그대로 배치 읽기

이미 선택한 디자인 지침을 재사용하며 목록을 다시 탐색하지 않는다. 사용자가 준
HTML을 표 중심으로 다시 그리지 않는다. 같은 artifact work에서 아래 job으로 초안→승인→PPT
명령을 사용한다. 입력 HTML과 만들어진 검토 HTML은 서로 다른 파일이다.

```json
{"creationMode":"reference","title":"임원 보고","purpose":"실적 보고",
 "audience":"임원","slideCount":5,
 "htmlSource":{"path":"C:/보고/카드형.html","selector":".slide","viewportWidth":1920}}
```

실제 목적·대상·장수를 사용한다. HTML을 이미 첨부했으면 캡처/색상 선택을 다시 묻지 않는다.
`htmlSource`에는 slides·referenceImages·다른 --template을 섞지 않는다.
`.slide` 기본 선택자, 필요 시 `.ppt-slide` 또는 `main > section`. 동일한 고정 크기 장이
1~60개 있어야 한다. 1920×1080은 960×540 포인트로 비율을 유지해 변환한다.
변환할 모든 장이 표시된 정적 HTML을 준비한다. 숨김 또는 이동·회전·확대/축소된
슬라이드는 자동으로 펼치거나 배치를 추측하지 않는다. 오류가 나면 같은 초안에서
고정 크기로 표시되도록 수정하고 확인한다. 원래 flex/grid 배치는 유지한다.

- 로컬 Edge/Chrome으로 실제 flex/grid 위치와 줄바꿈을 한 번 읽는다. 기본은 설치된
  Chrome 우선, 없으면 Edge. `browser:"edge"` 또는 `"chrome"`을 명시할 수도 있다.
  브라우저 실패/정책 거절 뒤 다른 경로로 자동 재시도하지 않는다.
- 소스 스크립트·외부 URL·프레임을 실행하지 않는다. 같은 폴더 내부의 CSS/PNG/JPEG만
  읽고 외부 연결은 CSP로 차단한다. 원래 사용자 브라우저/로그인 프로필을 사용하지 않는다.
- 카드·단색·둥근 모서리·외부 그림자·텍스트·PNG/JPEG를 네이티브 개체로 변환한다.
  HTML 표는 네이티브 표로 만들되 셀 색상은 PPT 테마를 사용한다.
- 줄바꿈을 유지하려고 텍스트는 줄/서식 단위로 나뉠 수 있다. PPT에서 편집 가능하나
  웹처럼 모든 문단이 자동 재배치되는 것은 아니다.
- CSS 막대는 편집 가능한 도형이지 데이터 연결 차트가 아니다. 데이터 편집이 필요한
  그래프는 아래 chart 개체와 실제 수치를 쓴다. 차트로 변환했다고 과장하지 않는다.
- script는 제거하고 정적 본문만 읽으며 동적 내용 누락 가능성을 알린다.
  SVG/canvas, 회전·필터·그라디언트/배경 이미지·다중/안쪽 그림자·병합 표 등
  미지원 요소는 이유를 반환한다. 해당 요소를 단순화하거나 개별 그림으로 쓸지 확인한다.
  슬라이드 전체 이미지로 몰래 대체하거나 사용자가 직접 완성하라고 떠넘기지 않는다.
- 승인된 변환 배치는 검토 HTML에 저장한다. PPT 제작 때 브라우저를 다시 띄우지 않는다.
  소스 HTML/CSS/그림 또는 초안 해시가 달라지면 새 초안이 필요하다.

## 새 디자인·세밀한 위치: slides[].elements

자동 배치 body/table/chart 대신 한 장의 모든 내용을 elements로 작성한다.
제목도 text 개체에 담는다. 단위는 페이지 포인트, 기본 960×540. 입력 순서가 겹침 순서다.

```json
{"title":"핵심 내용","elements":[
 {"kind":"shape","shape":"roundRect","x":48,"y":100,"w":410,"h":230,
  "fill":"FFFFFF","radius":14,"border":"E1E5EA","borderWidth":1,
  "shadow":{"color":"000000","opacity":0.16,"x":0,"y":4,"blur":10}},
 {"kind":"text","text":"핵심 내용","x":72,"y":120,"w":350,"h":44,
  "size":28,"bold":true,"color":"173B5E"},
 {"kind":"shape","shape":"roundRect","x":72,"y":180,"w":120,"h":32,
  "radius":16,"fill":"173B5E"},
 {"kind":"text","text":"검토 필요","x":76,"y":184,"w":112,"h":24,
  "size":16,"color":"FFFFFF","align":"center"}
]}
```

shape: rect/roundRect/ellipse, fill(RGB 또는 null), opacity(0~1), border,
borderWidth, radius, shadow(x/y/blur/color/opacity). text: text/size/color/bold,
italic/underline/align(left/center/right)/wrap/lineSpacing/font.
image: 같은 x/y/w/h + `image:{path,alt}`와 `fit:"contain"|"cover"|"stretch"`.
table/chart: 같은 x/y/w/h + 기존 table/chart 데이터. table은 size와 선택적인
columnWidths/rowHeights를 받는다. 각각 영역 너비/높이와 합계가 같아야 한다.
페이지 배경은 slides[].background(여섯 자리 RGB). 알약은 radius=min(w,h)/2인 roundRect다.
서로 겹치거나 잘리지 않는 배치는 최종 PowerPoint 렌더링으로 확인한다.

## 이미지 전체 화면 / 기존 PPT의 그림만 크기 수정

사용자가 이미지형을 명시했을 때만 새 장의 `imageLayout:"full-slide"`,
`imageFit:"cover"`를 사용한다. cover는 비율 유지+중앙 자르기, contain은 전체 보기+
여백, stretch는 비율 변경이다. 정확한 크기의 그림이면 cover도 잘리지 않는다.

이미 있는 PPT는 재제작/HTML 승인 질문 없이 새 출력 artifact work와 다음 job을 사용한다.

```json
{"file":"C:/보고/원본.pptx","fit":"cover","slides":[1,2,3,4,5]}
```

`business ppt-fit-images --spec "<jobPath>" --work "<workFile>" --state-root "<stateRoot>"`

각 장의 그림이 하나면 그 그림만 수정한다. 여러 그림이면 `business ppt-analyze --template`
결과의 실제 번호로 `shapeIds:{"1":[4],"2":[7]}`을 지정한다. 임의로 로고까지 확대하지 않는다.
선택적인 `box:{x,y,w,h}`는 특정 영역 맞춤이며 기본은 슬라이드 전체다.
회전·보호/외부 연결·지원하지 않는 파일은 제한을 그대로 알린다. 원본은 보존한다.
미리보기 확인 후 artifact-publish로 결과 하나만 전달한다. 그림 속 글자는 여전히 이미지다.

이 고급 제작/수정은 기존 python-pptx가 필요하다. 없으면 그 의존성만 알린다.
“카드는 포기”, “이미지 크기 지정 불가”, “직접 그림을 넣으세요”를 기본 응답으로 쓰지 않는다.
