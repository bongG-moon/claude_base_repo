# HTML 내용 파일

JSON은 내부 명세이며 사용자에게 작성시키지 않습니다. 실행 명령은 SKILL.md의 `report.py build`입니다.

```json
{
  "title":"교육 신청 현황", "subtitle":"가상 예시 · 10월",
  "style":"minimal", "length":"standard", "mode":"scroll",
  "fontChoice":"noto-sans-kr", "fontSource":"system",
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
- `fontChoice`: noto-sans-kr / pretendard / nanum-square-neo / auto / custom. custom에는 `fontName`을 넣습니다.
- `fontSource`: system 기본. google은 외부 연결을 허용한 경우만 사용합니다.
- sections에는 title/body/bullets/table/chart/image를 필요한 만큼 넣습니다. image는 `{"path":"절대경로.png","alt":"설명"}`입니다.
- 표 `headers`와 각 `rows`의 열수를 맞춥니다. chart는 `type:column|bar|line|pie`, categories, series를 사용합니다.
  예: `{"type":"column","categories":["1월","2월"],"series":[{"name":"신청","values":[12,20]}]}`.
- `contentOrder`는 각 section의 body/bullets/table/chart/image 중 존재하는 항목을 정확히 한 번씩 적습니다. 제목·출처는 제외합니다.
- 사실 `op`: value/sum/ratio/difference/percent_change. table/chart 좌표는 0부터 셉니다.
  참조 `{"fact":"total"}`은 앞서 정의한 사실만 사용합니다. `{{fact:id}}`로 제목·본문·표·차트에 같은 값을 재사용합니다.
  `expected`와 `checks:[{"left":"a","right":"b"}]`는 알려진 대조값이 있을 때만 사용합니다.

HTML 양식 참고 명령은 원본을 실행하지 않고 색·글꼴·구획의 정적 특징을 추출합니다. 그 결과를
`htmlTemplate`에 넣는 흐름은 반환한 형식을 따릅니다. 픽셀 단위 복제나 임의 CSS 전체 호환을 보장하지 않습니다.
검사는 선언한 계산과 명세 구조만 확인하며, 자유문장 사실·데이터 정확성·브라우저 화면 전체의 확인은 아닙니다.
