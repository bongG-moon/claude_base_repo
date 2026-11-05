# HTML 내용 파일

JSON은 내부 명세이며 사용자에게 작성시키지 않습니다. 실행 명령은 SKILL.md의 `report.py build`입니다.

PPT나 이미지 참고가 있을 때만 `referenceImages`와 `referenceStyle`을 추가합니다. 이미지 전체 목록과 여러 장에서 합친 색 조합, 한글 서체, 여백, 표와 차트의 규칙 및 근거는 [reference-style.md](reference-style.md)의 공통 계약을 따릅니다. 기존 style, 글꼴, 분량과 표시 방식의 명시 선택은 유지합니다.

```json
{
  "title":"교육 신청 현황", "subtitle":"가상 예시 · 10월",
  "style":"minimal", "length":"standard", "mode":"scroll",
  "fontChoice":"noto-sans-kr",
  "facts":[{"id":"total","label":"신청","unit":"명","op":"sum","inputs":[{"table":[0,0,1]},{"table":[0,1,1]}]}],
  "sections":[{
    "title":"신청자는 {{fact:total}}명입니다",
    "table":{"headers":["부서","인원"],"rows":[["생산",12],["품질",8]]},
    "body":"두 부서의 신청 현황입니다.", "contentOrder":["table","body"],
    "source":"가상 실습 자료"
  }]
}
```

- `length`: short / standard / detailed, `mode`: scroll / slides / both. 본문 분량은 직접 맞춥니다.
- `referencePreset`: 선택한 경우에만 reference-1(스토리형 설명) / reference-2(데이터 리포트형) / reference-3(핵심 브리핑형, 기존 발표형 ID 유지). 미지정 작업은 기존과 같습니다. 기존 style·fontChoice·length·mode는 유지하고 sections의 내용 흐름도 해당 구성에 맞춰 작성합니다.
- `motion`: subtle 기본 / none. 페이지와 선택한 사례의 전환, 버튼 피드백을 짧게 표시하며 움직임 줄이기와 인쇄에서는 꺼집니다. 스크롤 내용은 즉시 보입니다.
- `fontChoice`: noto-sans-kr / pretendard / nanum-square-neo / auto / custom. custom에는 `fontName`을 넣습니다.
- `fontSource`: 생략하면 Noto Sans KR와 Pretendard는 동봉 글꼴을 HTML에 넣습니다(bundled). system은 PC 글꼴만 사용하는 명시 선택이고 google은 외부 연결을 허용한 경우만 사용합니다. 다른 글꼴과 첨부 양식은 기존 설정을 보존합니다. `typography.availability:embedded_not_rendered`는 파일 포함을 뜻하며 실제 화면 확인을 뜻하지 않습니다.
- sections에는 title/body/bullets/table/chart/image를 필요한 만큼 넣습니다. image는 `{"path":"절대경로.png","alt":"설명"}`입니다.
- 각 section의 `layout`: cover / summary / dashboard / split / table. 첫 결론·현황·비교·상세를 구분하며 전체 style은 바꾸지 않습니다.
- `takeaway`는 제목 근처 핵심 문장, `source`는 출처·집계 범위·단위·기간입니다. 차트 다음 해석은 takeaway 대신 body와 contentOrder로 배치합니다.
- `kpis`는 계산된 facts를 참조하는 `[{"fact":"total","note":"집계 조건"}]` 형식입니다. 별도 임의 value를 넣지 않습니다.
- 표 `headers`와 각 `rows`의 열수를 맞춥니다. chart는 `type:column|bar|line|pie`, categories, series를 사용합니다.
  차트 항목을 가리키거나 누르면 전체 항목명, 계열명과 실제 수치를 표시하고 해당 항목을 강조합니다. Tab으로 진입한 뒤 방향키, Home/End로 이동하고 Esc로 닫습니다. 원형 차트는 비중도 표시합니다. 기본 동작이므로 툴팁용 질문이나 외부 라이브러리를 추가하지 않습니다. 전체 수치는 아래 원자료 표에도 유지합니다.
  짧은 ID와 날짜, 기간은 의미 단위를 한 줄로 표시합니다. 필요한 열은 `table.columnTypes`에 headers 순서대로 auto / text / id / date / period를 지정합니다. 생략하면 명확한 제목만 자동 구분하며 자세한 예제는 [데이터 표](data-tables.md)를 봅니다.
  예: `{"type":"column","categories":["1월","2월"],"series":[{"name":"신청","values":[12,20]}]}`.
- `contentOrder`는 각 section의 body/bullets/table/chart/image 중 존재하는 항목을 정확히 한 번씩 적습니다. 제목·출처는 제외합니다.
  지정하면 세로 배치가 우선합니다. `contentLayout`은 `vertical`만 지원하며 생략할 수 있습니다. 좌우 비교는 contentOrder 없이 layout:split을 사용합니다.
- 사실 `op`: value/sum/ratio/difference/percent_change. table/chart 좌표는 0부터 셉니다.
  참조 `{"fact":"total"}`은 앞서 정의한 사실만 사용합니다. `{{fact:id}}`로 제목·본문·표·차트에 같은 값을 재사용합니다.
  `expected`와 `checks:[{"left":"a","right":"b"}]`는 알려진 대조값이 있을 때만 사용합니다.

## 숫자와 집계 범위 재사용

데이터 분석에서 필요할 때만 fact에 `period`(100자), `scope`, `exclusions`, `source`(각 500자), `denominator`(300자)를 짧은 문자열로 넣습니다. 각각 기준 기간, 포함 범위, 제외 조건, 출처, 분모의 뜻입니다. 지정한 값은 비어 있으면 안 되며 모르는 필드는 생략합니다. `{{fact:total.scope}}`처럼 표와 주석에서 같은 값을 참조합니다. `label`, `unit`, `valueWithUnit`도 참조할 수 있고 기존 `{{fact:total}}`는 숫자만 표시합니다.

예: 전체 이익률 `34.3%`는 `scope:"D03 전체, Unknown 포함"`, 계획 이익률 `34.4%`는 `scope:"계획 대상만", exclusions:"Unknown 제외"`로 서로 다른 fact에 둡니다. 범위가 다른 값을 같은 지표로 덮어쓰거나 서로 같아야 한다는 check를 넣지 않습니다. 필터가 바뀌어도 고정 KPI는 전체 기준임을 표시하며 필터 연동 KPI로 오해시키지 않습니다.

Excel 결과를 HTML이나 PPT에 넘길 때는 기존 job 또는 summary 안에 이 값과 근거를 유지합니다. 별도 인계 파일을 매번 만들거나 원자료 전체를 재조회하지 않습니다. 출처나 범위는 선언된 설명을 재사용하는 기능이며 자동으로 사실 여부를 검증하지 않습니다.

HTML 양식 참고 명령은 원본을 실행하지 않고 색·글꼴·구획의 정적 특징을 추출합니다. 그 결과를
`htmlTemplate`에 넣는 흐름은 반환한 형식을 따릅니다. 픽셀 단위 복제나 임의 CSS 전체 호환을 보장하지 않습니다.
검사는 선언한 계산과 명세 구조만 확인하며, 자유문장 사실·데이터 정확성·브라우저 화면 전체의 확인은 아닙니다.


## 데이터 표 기본 동작

한 표는 최대 5,000행과 64열이며 전체 명세는 실행기의 크기 제한을 따릅니다. 숫자는 숫자, ID는 문자열로 둡니다. `table.interactive`는 기본 true이고 명시적으로 false이면 정적 비교표를 만듭니다. 데이터가 있으면 검색, 범주 필터, 정렬, 표시 열, 초기화와 범위별 CSV를 제공하고 26행 이상이면 25/50/100행 페이지 이동을 제공합니다. 자세한 범위는 [데이터 표](data-tables.md)를 따릅니다. 페이지의 `mode:slides`와 표 안의 페이지 이동은 독립적입니다.

## 필요한 보고서에만 사례 선택과 상세 설명

같은 규칙에서 입력이나 예외에 따라 처리가 달라지는 경우 `section.scenarios`를 넣습니다. 사례를 선택하면 입력, 처리 순서와 결과가 함께 바뀝니다. `details`는 보조 근거를 펼쳐 보는 목록입니다. 표와 짧은 설명만으로 충분하면 둘 다 생략합니다.

```json
{
  "title":"신청 자료의 확인 기준", "style":"minimalism", "length":"standard", "mode":"scroll",
  "fontChoice":"auto",
  "sections":[{
    "title":"누락 여부에 따라 다음 조치가 달라집니다",
    "scenarios":{"title":"사례를 선택하세요","items":[
      {"label":"자료 완비","input":"출석과 제출 기록이 모두 있음",
       "steps":["같은 신청 번호로 기록 연결","기준일과 조건 확인"],"output":"수료 후보로 표시"},
      {"label":"자료 누락","input":"제출 기록이 비어 있음",
       "steps":["빈 값과 미제출 확정 구분","담당자 확인 항목 표시"],"output":"보완 확인 대상으로 표시"}
    ]},
    "details":[{"title":"빈 값은 미제출 확정이 아닙니다",
      "body":"기록 지연 또는 연결 누락일 수 있으므로 확인 전까지 상태를 단정하지 않습니다."}]
  }]
}
```

- `scenarios.title`은 선택이며 180자 이하입니다. `items`는 2~8개, 각 사례에 `label`(서로 다른 이름, 80자 이하), `input`과 `output`(각 2,400자 이하), `steps`(1~10개, 각 800자 이하)가 필요합니다.
- `details`는 최대 12개입니다. 각 항목은 `title`(180자 이하)와 내용이 있는 `body`(6,000자 이하) 또는 `bullets`(최대 20개, 각 1,000자 이하)를 갖습니다.
- 값은 일반 텍스트이며 HTML과 JavaScript를 실행하지 않습니다. 입력 제한을 넘으면 내용을 자르지 않고 오류로 알립니다.
- 표시 순서는 기존 본문 → 사례 → 상세 설명 → 출처입니다. `contentOrder`에 이 두 필드를 넣지 않습니다. 핵심 결론과 필수 조건을 상세 펼침 안에만 숨기지 않습니다.
- 스크립트가 실행되지 않으면 모든 사례를 읽을 수 있고, 인쇄에서는 사례와 상세를 모두 펼칩니다. 선택은 로컬 화면만 바꾸며 네트워크 호출이나 데이터 저장을 하지 않습니다.
