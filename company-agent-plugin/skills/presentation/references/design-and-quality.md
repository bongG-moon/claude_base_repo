# PPT 디자인과 수치 확인

<!-- Company Agent adaptation, 2026-09-27; selected frontend-design principles, modified; see ../../../THIRD_PARTY_NOTICES.md. -->

선택이 끝나 전체 job을 작성할 때 읽는다. 이미 받은 선택과 불러온 디자인 지침을
재사용한다. 이 문서는 질문·Skill 선택·런타임 탐색을 다시 시작하는 절차가 아니다.
본문의 HTML 초안 → 실제 승인 → 편집 가능한 PPT 흐름을 유지한다.
캡처는 디자인 참고이며 전체 슬라이드 배경으로 붙이지 않는다.

양식 없는 업무형 구성은 [consulting-pptx-skill](https://github.com/carnot-tech/consulting-pptx-skill)의
결론 우선·근거 중심 원칙을 참고해 기존 제작기에 맞게 구현했다. 원본 엔진·전체 규칙을
설치하지 않으며 한국어 독자와 사용자 양식이 우선이다. 추가 모델 검토를 매번 실행하지 않는다.

## PPTX 참고 양식이 있을 때만

지정 PPTX의 선언 색상·글꼴·개체 위치가 필요하면 ppt-analyze를 한 번 사용한다.
같은 정보를 얻으려고 ppt-inspect도 연달아 실행하지 않는다.
저장한 HTML 대표 양식은 제작기가 읽으므로 PPTX 분석 명령을 쓰지 않는다.
`business ppt-analyze --template`로 선언된 색상·글꼴·개체 위치를 분석하고,
`business ppt-preview --template "원본.pptx" --output "<workingDirectory>/reference-preview"`로
허용된 PowerPoint 이미지 출력을 사용한다. 승인된 Office 열람 수단이 없으면
구조만 확인했다고 명시하고 색상·배치를 정확히 따라 했다고 말하지 않는다.
좋지 않다고 제시한 결과물은 디자인 정답이 아니다. 그 파일의 요구 내용은 보존하되
실제 참고 양식과 사용자의 개선 요청을 기준으로 새 파일에 재구성한다.

## 내용에 맞는 구성

- 첫 장은 이미 알려준 독자·목적·핵심 결정에 맞춘다. 업무 보고는 가능하면 `layout:summary`로 결론형 제목과 필요한 근거부터 읽히게 한다. body는 핵심 설명, bullets는 나란히 읽는 요점, takeaway는 강조할 한 문장이다. 실제 지표가 있을 때만 최대 3개와 차트를 쓴다.
- 근거(`evidence`): 표·차트에 넓은 영역을 주고 짧은 설명을 옆에 둔다. takeaway는 근거 아래 시사점이다. 표 아래 본문처럼 요청한 순서가 있으면 contentOrder를 우선한다.
- 비교(`comparison`): 두 시각 자료를 같은 폭으로 놓고 공통 본문을 아래에 둔다. 설명만 있으면 body와 bullets를 두 영역으로 나눈다. 비교 축·기간·단위를 맞추며 결론을 자료보다 강하게 쓰지 않는다.
- 실행·후속 확인(`actions`): 항목·확인할 내용·현재 상태의 표를 넓게 놓고 설명을 아래에 둔다. takeaway에는 실제 결정·확인할 사항을 적는다. 미정인 담당자나 날짜는 만들지 않는다.

사용자 양식과 확인된 선호를 우선하며 기존 구성·테마 범위에서 읽기 순서를 잡는다.
제목·표·차트를 같은 구획에 반복하거나 의미 없는 번호·eyebrow·장식 카드를 덧붙이지 않는다.
관계도를 요청받지 않았고 표만으로 충분하면 표를 쓰며 제목·본문·출처의 역할을 크기·여백·대비로 구분한다.
기본 제목 30pt, 본문 18pt 이상, 표 16pt, 출처 10pt. 글자를 계속 줄여 맞추지 않는다.
가독성 점검에서 거절되면 핵심 내용과 요청 장수를 함께 지킬 수 있도록 요약하거나
필요한 장수 변경만 물어본다. 일부 행이나 확인 과제를 몰래 버리지 않는다.
직접 쓰는 한국어 제목·본문·표시 문구는 job 작성 중, 렌더와 승인 전에 다듬는다.
`{{fact:id}}`, 수치·날짜·단위·표 원문·코드·인용은 보존하고 사실·부정·조건·추정·의무의 강도를 바꾸지 않는다.

## 실제 지원 JSON

```json
{
  "title": "실적 보고",
  "facts": [
    {"id":"actual","label":"실적","unit":"백만원","op":"sum","inputs":[{"chart":[0,0,0]},{"chart":[0,0,1]}]},
    {"id":"target","op":"value","inputs":[300]},
    {"id":"rate","label":"달성률","unit":"%","op":"ratio","decimals":2,"inputs":[{"fact":"actual"},{"fact":"target"}]}
  ],
  "slides": [{
    "layout":"summary",
    "eyebrow":"실적 종합",
    "title":"목표 대비 {{fact:rate}}% 달성",
    "takeaway":"실적 {{fact:actual}}백만원. 증가 원인은 추가 확인이 필요합니다.",
    "kpis":[{"fact":"actual"},{"fact":"rate"}],
    "chart":{"type":"column","title":"월별 실적 · 백만원","categories":["7월","8월"],"series":[{"name":"실적","values":[175,210]}]},
    "body":"금액의 변화와\n원인을 구분합니다.",
    "source":"실습용 가상 수치"
  }]
}
```

기존 body/bullets/table/chart/image도 호환된다. layout을 생략하거나 auto를 쓰면 기존
자동 배치다. summary/evidence/comparison/actions는 위의 서로 다른 배치를 사용하며
한글 제목은 30pt에서 최대 두 줄을 허용한다. 양식 없는 업무 보고는 내용에 맞는 layout을
작성하되 이미 정한 양식·순서·분량을 우선한다. 자유 배치는 `native-layout.md`의 elements 좌표를 사용한다. 지표는 fact ID만 받으며 수치를 따로
복사하지 않는다. 표 10행·8열, 차트 12항목·4계열은 상한일 뿐이며 실제 글자량이
많으면 그 이하에서도 나눠야 한다. 원형 차트는 작은 항목 수에만 사용한다.

표 아래 요약 요청은 그 장에 `contentOrder:["table","body"]`를 넣는다.
`contentLayout:"vertical"`은 생략 가능하며 body/bullets/chart/table/image 중 실제 존재하는
본문 항목을 모두 한 번씩 적는다. 제목·takeaway·KPI·출처는 제외하므로 표 아래 설명은 body에 쓴다.
HTML 초안과 PPT가 같은 네이티브 세로 배치를 사용한다. 공간이 부족하면 자동으로 좌우 배치나
작은 글자로 바꾸지 않고 거절하므로 요약·장수 조정만 확인한다. 명세가 없으면 기존 배치다.
elements·HTML 원본 변환·기존 개체 유지 방식에는 이 필드를 섞지 말고 실제 승인할 원본 좌표를 고친다.
"두 문장"은 body 작성 시 직접 지키며 문장 수를 자동 검증했다고 말하지 않는다.
승인한 대안 배치는 현재 작업의 기준이다. 장기 선호를 승인 후 다시 적용하거나 기억까지 바꾸지 않는다.
`contentLayoutValidation`의 shared-scene-coordinates는 초안 좌표 검사,
pptx-native-coordinates는 저장된 편집 가능 개체의 위치 검사다. 실제 시각 가독성 확인과 다르다.

facts의 op는 value/sum/ratio/difference/percent_change. table/chart 위치는
0부터 시작하는 [장, 행 또는 계열, 열 또는 항목]이다. 먼저 정의된 fact만 참조한다.
expected를 지정하면 계산값과 대조한다. 중복 집계가 있으면
`"checks":[{"left":"monthlyTotal","right":"teamTotal"}]`로 총계를 비교한다.
요약·제목·표에는 `{{fact:id}}`를 사용한다. 이전 요약 문서의 총계를 재사용하지 않는다.
이름·단위까지 맞춰야 하면 `{{fact:id.label}}`, `{{fact:id.unit}}`, `{{fact:id.valueWithUnit}}`를 쓴다.
선택 필드 `period`를 정의한 지표는 `{{fact:id.period}}`로 기간을 재사용하며, 정의 없이 기간을 참조하면 중단한다.
제목·본문·표·차트 제목/항목/범례에 적용된다. 금액과 비율은 열 또는 단위를 구분하고, 정정 시 기간·분모도 대조한다.
이 기능은 선언값을 재사용할 뿐 자유문장의 의미나 실제 원본의 지표·단위 일치를 자동 판정하지 않는다.
원자료 파일 두 개가 같은 내용의 대체본이면 둘을 중복 집계하지 않는다.

색상을 확인했다면 presentationTheme에 title/accent/text/muted/background/tint
중 필요한 항목만 # 없는 여섯 자리 색상으로 지정한다. 기본 폰트는 맑은 고딕이다.
분위기 참고 방식은 테마·마스터를 보존하되 본문을 새로 배치한다. `presentationFont`에
확인된 설치 글꼴을 넣을 수 있다. Noto Sans KR나 승인된 글꼴 선호도 이 범위에서 존중하며 외부 폰트를 자동 로드하거나 설치하지 않는다.
배치 유지 방식은 아래 명세로 원본 개체를 교체한다. 모든 개체의 완전 복제를 보장하지 않는다.
복잡한 양식은 지원 가능한 정도를 먼저 설명한다. 입력 HTML style 이름이 PPT에
동일한 CSS 효과를 주는 것은 아니다.

## 제출 전 필수 확인

### 기존 배치 유지 명세

`creationMode:"reference"` 또는 `"saved"`, `referenceMode:"preserve"`와 함께
기존 slides/sections 내용과 같은 수의 `templateSlides`를 제공한다.

```json
{"creationMode":"reference","referenceMode":"preserve","purpose":"실적 보고",
 "audience":"부서장","slideCount":1,
 "slides":[{"title":"이번 달 결과","body":"확인된 핵심 내용"}],
 "templateSlides":[{"sourceSlide":0,"title":2,"body":3,"keepShapeIds":[4]}]}
```

sourceSlide는 원본의 0부터 시작하는 장 번호다. title/body/table/chart는 분석에서 확인한
해당 장의 실제 shapeId다. 순서·모양·색·글꼴을 유지하고 지정 내용만 바꾼다.
같은 원본 장을 여러 번 복제하는 기능은 지원하지 않는다. 분석의 slideN.xml 숫자만으로
순서를 추측하지 말고 실제 원본 순서와 개체를 확인한다.
교체하지 않을 로고·고정 문구만 keepShapeIds로 명시한다. 이전 업무 숫자나 문장이 남는
개체를 단순히 통과시키려고 유지 목록에 넣지 않는다. 보고서의 새 본문과 구분해 확인한다.
표는 같은 행·열 수, 차트는 지원하는 일반 유형과 같은 계열 수가 필요하다.
병합 셀·그룹·여러 문단·혼합 글꼴 칸과 추가 KPI 배치는 지원하지 않으면 중단한다.
원본 발표자 노트는 새 복사본에서 제거한다. 원본 파일 자체는 변경하지 않는다.
실제 시각적 일치, 숨겨진 개체·이미지 속 이전 내용까지는 사용자가 확인할 수 있게
미리보기를 함께 제공한다. 글자를 줄여 억지로 넣거나 일부 데이터를 생략하지 않는다.

### 품질 확인

1. 허용된 미리보기를 볼 수 있으면 첫 검토에서는 생성된 모든 장을 실제로 읽는다. `image-review.md`의 작은 묶음·상세 확인 방식을 적용한다. 파일 존재는 시각 검증이 아니며 이미지 생성 모델을 필수 호출하지 않는다.
2. 제목 줄바꿈·표 셀 잘림·겹침·범례·단위·여백·대비를 확인한다. HTML 초안의 좁은 화면·키보드 포커스·인쇄 보기와 실제 PPT 화면은 구분한다.
3. 출력 파일의 표·차트·요약을 원자료와 비교한다. 합계·분모·반올림도 확인한다.
4. 네이티브 표/차트가 있어야 편집 가능하다고 설명한다. 이미지로 만든 차트는 제외한다.
5. 같은 workFile 내부에서 수정하고 변경 장과 영향받은 장을 다시 확인한다. 공통 양식이 바뀌거나 영향 범위가 불명확하면 모든 장을 다시 확인한다. 최종 전달은 한 번이며 이전 원본은 보존한다.

arithmetic 검사는 선언한 계산만 검증한다. 원자료의 진위, 자유문장 숫자, 원인은
별도 확인한다. visualReview=required는 제작 완료가 아니라 육안 검토가 남았다는 뜻이다.
렌더링을 사용할 수 없으면 수행한 구조·내용 검사와 화면 미검증을 구분하며 승인 단계를 생략하지 않는다.
PowerPoint 출력 또는 차트 삽입 결과와 오류를 실제 확인한 대로 알린다. Python 라이브러리가
없으면 기존 PowerPoint/Excel 기능으로 생성하지만 그 환경에서도 차트 삽입이
가능해야 한다. 실패를 성공으로 바꾸거나 표만 남기고 완성했다고 말하지 않는다.
미검증 사항은 사용자에게 필요한 한 문장만 설명하고 내부 학습/검증 상태는 출력하지 않는다.
