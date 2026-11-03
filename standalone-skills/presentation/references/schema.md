# 내부 명세와 실행

PPT나 이미지 참고가 있을 때만 `referenceImages`와 `referenceStyle`을 추가합니다. 최대 60장의 전체 목록과 여러 장에서 합친 색 조합, 한글 서체, 여백, 표와 차트의 규칙 및 관찰 근거는 [reference-style.md](reference-style.md)의 계약을 따릅니다. 이미지에서 자동으로 추론하는 기능이 아니라 현재 호스트가 실제 확인한 규칙을 명세에 반영하는 흐름입니다.

JSON은 작업자가 만드는 내부 파일입니다. 사용자는 목적·자료·수정 의견을 대화로 전달하면 됩니다.
최종 사용자 결과는 PPT 하나이며 초안·명세는 작업 내부에 유지합니다.

```json
{
  "title":"교육 신청 현황", "creationMode":"new", "designPreset":"business", "compositionMode":"content-led",
  "purpose":"진행 현황 보고", "audience":"담당자", "slideCount":2,
  "presentationFont":"맑은 고딕", "presentationProfile":{"density":"presentation"},
  "slides":[
    {"title":"신청은 두 부서에서 진행됐습니다", "pageRole":"cover", "body":"가상 자료입니다.",
     "bullets":["부서별 수요 확인","후속 교육 일정 검토"]},
    {"title":"부서별 신청 현황", "pageRole":"detail",
     "table":{"headers":["부서","신청"],"rows":[["생산","12명"],["품질","8명"]]},
     "body":"신청 인원만 집계했습니다.","source":"실습 가상 자료"}
  ]
}
```

기본 페이지는 960×540pt입니다. `presentationFrame:{"width":960,"height":540}`로 명시할 수 있습니다.
기본 디자인은 business이며 monochrome / warm도 지원합니다. `presentationTheme`에 title/accent/text/muted/background/tint의
색을 `#` 없는 6자리 RGB로 지정할 수 있습니다. `presentationFont`는 PC에서 확인한 설치 글꼴 이름입니다.
직접 입력한 디자인은 `designDirection`에 사용자의 문장을 짧게 보존하고 실제 `presentationTheme`, `presentationFont`, `elements`에도 반영합니다. 문장만 기록하고 기본 카드 배치를 그대로 쓰지 않습니다. 추천을 선택하면 내용과 청중에 맞는 지원 preset과 배치를 정해 명시적으로 저장합니다.

## 장별 구성과 참고 양식의 기준값

새 장의 `pageRole`은 cover / key-message / comparison / workflow / timeline / detail / closing입니다. 목적과 자료에서 필요한 역할을 정하며 장마다 새 질문을 하지 않습니다. 각각 표지, 핵심 결론과 지표, 비교 영역, 실제 업무 분기, 날짜 비례 일정, 넓은 상세 표, 결론과 후속 행동을 만듭니다. 단순화가 목적이 아니며 복잡한 관계나 사용자 양식은 `elements`의 도형과 곡선, 글자와 그룹을 함께 사용합니다. `elements`, 명시한 contentOrder와 기존 job은 자동 역할로 덮지 않습니다.

`presentationProfile`은 같은 job에 보관하는 짧은 기준값입니다. `titleSize`, `bodySize`, `emphasisSize`, `annotationSize`, `tableSize`, `titleFont`, `bodyFont`, `margin`, `gap`, `density`를 받습니다. 단위는 pt이며 역할형 배치에 사용합니다. `density:"presentation"`은 발표용, `"reading"`은 읽기용입니다. 사용자가 이미 정한 목적과 원본 글꼴, 크기, 여백을 먼저 사용하며 별도 설문이나 새로운 설정 파일을 만들지 않습니다.

comparison은 `panels:[{title,body,bullets?}]` 2~3개를 비교합니다. workflow는 `workflow:{nodes,edges}`의 실제 연결만 그립니다. nodes는 1~8개이며 `{id,title,body?,shape?}`, edges는 최대 12개 `{from,to,label?}`입니다. 자동 배치는 순환 없는 4단계 이내이고 순환이나 더 복잡한 위치는 `elements`로 명시합니다. timeline은 `milestones:[{label,date,detail?}]` 2~7개이며 날짜는 실제 `YYYY-MM-DD`입니다. 날짜를 시간 비율로 배치하므로 확인되지 않은 날짜를 만들거나 같은 간격의 그림으로 바꾸지 않습니다. detail의 데이터 행은 17개 이하로 나누며 실제 공간도 확인합니다.

부분 강조, 분기 흐름과 복합 도형의 최소 예시는 [advanced-shapes.md](advanced-shapes.md)에 있습니다. 해당 기능이 필요한 경우에만 읽습니다.

`layout`: auto/summary/evidence/comparison/actions. `body`·`bullets`·`table`·`chart`·`image`를 사용합니다.
새 제작의 `compositionMode:"content-led"`는 layout을 지정하지 않은 장에서 실제 내용에 맞는 요약, 넓은 근거, 비교, 실행안 배치를 고릅니다. 명시한 layout/contentOrder/elements와 참고 양식의 배치를 바꾸는 옵션이 아닙니다. 기존 작업을 재개할 때 새로 끼워 넣지 않습니다.
chart는 type(column/bar/line/pie), categories, series(name/values)입니다. `contentOrder`는 해당 장에 존재하는
body/bullets/table/chart/image를 한 번씩 적습니다. 자동 배치가 공간을 초과하면 내용·장수 조정으로 해결하며 몰래 축소하지 않습니다.

일반 차트는 12항목, 4계열 이하를 지원합니다. 막대의 음수 값도 계열 색을 유지하고 항목명은 0축 바깥에 모든 항목을 표시합니다. 값 라벨은 6항목 이하에서 표시하며 선 차트는 점 위아래에 둡니다. 자동 라벨 생략을 끄는 설정이 긴 항목명이나 교차하는 선의 겹침까지 해결하지는 않으므로 기존 화면 검토에서 확인합니다. 긴 이름이나 밀집한 자료는 이름을 짧게 쓰거나 장을 나눕니다.

## 자유 배치, 카드와 그룹

한 장의 `elements`는 같은 장의 자동 body/bullets/table/chart 배치와 섞지 않습니다. 다만 **`elements` 목록 안에는** `kind:"table"`과 `kind:"chart"`를 도형·글자·선과 함께 넣을 수 있습니다. 표·차트는 별도 편집 개체로 두고 `group`을 지정하지 않습니다. 실제로 초안과 PPT를 만들 수 있는 최소 예시는 [scene-example.json](scene-example.json)입니다. 좌표·크기는 pt입니다.

표의 `tableStyle`은 `headerFill`, `headerText`, `bodyFill`, `bodyText`, `alternateFill`, `borderColor`에 `#` 없는 6자리 RGB를 쓰고 `borderWidth`(0~6pt), `fontSize`(6~48pt), `align`(left/center/right), `padding`(0~24pt), `headerBold`(true/false)를 지원합니다. 전체 job, 장, 표 개체 순으로 같은 항목을 덮어씁니다. 홀수 본문 행의 `alternateFill` 외 셀별 색·정렬·줄간격은 이 표 스타일에서 지정할 수 없습니다. `lineSpacing`은 별도 text 개체용입니다.

```json
{"title":"핵심 현황", "elements":[
  {"kind":"text","text":"교육 운영 현황","x":40,"y":20,"w":800,"h":50,"size":30,"bold":true},
  {"kind":"shape","group":"신청카드","x":40,"y":110,"w":380,"h":230,"shape":"roundRect","fill":"EEF4F7"},
  {"kind":"text","group":"신청카드","text":"신청 20명","x":65,"y":140,"w":330,"h":70,"size":26,"bold":true,"color":"17324D"},
  {"kind":"text","group":"신청카드","text":"두 부서 합계","x":65,"y":220,"w":330,"h":50,"size":18,"color":"30465B"}
]}
```

text는 size/bold/color/font/align(left/center/right)를 지정하며 같은 상자 안의 부분 강조는 `runs`를 사용합니다. 구간을 합친 문자열은 text와 같아야 합니다. 같은 그룹의 text/shape/line/path/image는 목록에서 연속으로 둡니다. 그룹 이름은 64자 이하의 글자, 숫자, 밑줄, 하이픈입니다. table/chart를 그룹에 섞지 않습니다.
shape는 기존 rect/roundRect/ellipse 외에 화살표, chevron, diamond, triangle, hexagon 등 16종을 지원합니다. line과 구조화한 path로 꺾은선과 Bézier 곡선을 편집 가능한 개체로 구성합니다. 전체 도형 목록과 좌표 규칙은 advanced-shapes.md를 사용하며 임의 PowerPoint 상수나 SVG 실행 코드를 넣지 않습니다.
image는 `image:{"path":"그림.png","alt":"설명"}`와 x/y/w/h, fit(contain/cover/stretch)를 지정합니다.
사용자 그림을 꽉 채우는 경우 cover 또는 stretch의 자르기/왜곡 차이를 설명하고 요청에 맞게 선택합니다.

## HTML 직접 변환

`{"title":"자료","htmlSource":{"path":"원본.html","selector":".slide"}}`는 다른 slides/sections/template와 섞지 않습니다.
설치된 Chrome/Edge를 통해 스크립트가 제거된 정적 HTML의 배치를 읽습니다. 외부 리소스와 임의 JavaScript는 실행하지 않습니다.
글자·단순 도형·로컬 그림 등을 네이티브 개체로 옮기며 지원하지 않는 CSS는 확인 후 재구성합니다.
`data-ppt-group="카드"`를 사용하면 관련 구성 요소를 묶을 수 있습니다.

## 수치와 승인

facts는 value/sum/ratio/difference/percent_change, table/chart 좌표는 0부터 시작합니다.
`{{fact:id}}`로 제목과 본문에 같은 계산값을 넣고 원자료의 단위·기간과 대조합니다.
`{{fact:id.statement}}`는 명시한 label과 계산값, unit을 함께 표시합니다. 기존 숫자만의 바인딩은 그대로 지원합니다. 예산 10,000, 실적 7,186이면 차이 2,814를 예산으로 나눈 값의 label은 `예산 대비 미달률`, 실적으로 나눈 값의 label은 `실적 대비 예산 초과율`로 구분합니다. 각각 `예산 대비 미달률 28.14%`와 `실적 대비 예산 초과율 39.16%`가 됩니다. 실행기가 입력의 의미나 label을 자동 추측하지 않습니다.

필요할 때만 fact에 `period`(100자), `scope`, `exclusions`, `source`(각 500자), `denominator`(300자)를 넣습니다. 각각 기간, 포함 범위, 제외 조건, 출처, 분모입니다. `{{fact:id.denominator}}`처럼 주석에 그대로 재사용하며 모르는 필드는 생략합니다. facts가 있으면 기존 응답의 arithmetic 안에 `factHandoff`가 `{id, statement, 선언한 문맥 필드}` 목록으로 함께 반환됩니다. draft에서는 `validation.arithmetic.factHandoff`, build에서는 `arithmetic.factHandoff`를 기존 설명이나 작업자 인계에 재사용합니다. 별도 인계 파일, 모델 호출이나 확인 단계를 추가하지 않습니다. 이름과 계산값의 연결을 유지하는 기능이며 자유문장, 분모 설명의 사실 여부를 자동 검증하는 기능은 아닙니다.
자동 응답 목록은 최대 12개, 압축 JSON 기준 4,000자 안에서 완전한 행만 포함하며 `factHandoffOmitted`가 생략 개수를 알려줍니다. 전체 facts와 본문 바인딩은 그대로 유지합니다.

draft 결과의 `designReview`는 경로·명세 해시·초안 해시를 포함합니다. 실제 승인 후에만 그대로 복사하고
`confirmed:true`로 바꿉니다. 원본이나 초안을 바꾸면 build가 거절하므로 갱신된 초안을 먼저 확인합니다.
해시를 임의로 재계산해 이전 승인을 새 내용에 적용하지 않습니다.
build는 승인 누락, `false`, 문자열 `"true"`와 초안 또는 내용 변경을 거절합니다.
같은 승인 기록과 같은 초안을 재사용할 때는 다시 질문하지 않습니다. 실행기는 기록의 형식과 일치를
검사하며, 실제 사용자 답변이 있었는지는 대화를 진행하는 호스트가 확인해야 합니다.

초안 응답의 `scenePreflight`는 같은 장면에 대한 한 번의 경고 검사입니다. 글자 겹침이나 넘침을 모아 해당 장만 보정합니다. 의도한 배경이나 도식의 겹침을 오류로 단정하지 않으며 자동 글자 축소, 새 모델 호출과 장별 승인 절차를 추가하지 않습니다. `templatePreview`가 반환되면 원본 양식의 미지원 개체와 근사 범위도 함께 확인합니다. 구조 검사가 실제 PowerPoint 화면 검토를 대신하지 않습니다.
