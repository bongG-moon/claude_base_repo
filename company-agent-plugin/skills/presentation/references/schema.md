# 기본 발표 명세

새 job을 만들 때 읽습니다. 기존 job을 수정할 때는 다시 읽지 않고 필요한 필드만 바꿉니다. JSON은 작업자가 관리하며 사용자에게 작성을 요구하지 않습니다.

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

예제의 가상 자료를 이번 자료로 교체합니다. 장수는 `slides`와 맞추고 장마다 메시지, 근거와 관계에 맞는 배치를 정합니다. 표지, 본문과 결론을 같은 카드 반복으로 만들지 않습니다. 기본 화면과 편집 기능은 제작기가 붙이므로 CSS/JavaScript를 다시 작성하지 않습니다.

## 일반 제작에서 쓰는 필드

- `designPreset`: business / monochrome / warm. 직접 지정한 방향은 `designDirection`에 보존하고 실제 색, 글꼴과 배치에도 반영합니다. 이미 정한 선택을 바꾸지 않습니다.
- `presentationFont`: 사용 가능한 한글 글꼴 이름. `presentationTheme`은 title/accent/text/muted/background/tint에 `#` 없는 6자리 RGB를 지정합니다. 참고에서 관찰한 역할별 색과 서체가 우선입니다.
- 각 장은 `title`과 필요한 `body`, `bullets`, `table`, `chart`, `image`, `source`를 담습니다. `chart`는 `type`(column/bar/line/pie), `categories`, `series:[{name,values}]`입니다. 12항목, 4계열을 넘으면 의미를 보존해 나눕니다. 이미지는 `image:{"path":"그림.png","alt":"설명"}`입니다.
- `pageRole`: cover / key-message / comparison / workflow / timeline / detail / closing. 실제 자료에 필요한 역할만 씁니다. 비교 패널, 흐름의 nodes/edges, 일정과 서식 프로필은 아래 상세 명세에서 해당 절을 확인합니다. 자동 배치가 공간을 넘으면 장이나 내용을 나누고 몰래 글자를 축소하지 않습니다.

`pageRole`은 전달 목적이며 표나 차트를 금지하지 않습니다. `layout`을 명시하면 일반 표/차트/이미지는 그 배치를 우선하고, 명시하지 않으면 실제 자료에 맞춰 구성합니다. `chart`와 `table`을 함께 넣어도 역할을 지우지 않습니다. `workflow`, `milestones`, `panels`는 관계 자료이므로 해당 역할을 사용하며 자유 배치와 섞어 내용을 숨기지 않습니다.

표는 고정 10행 제한 대신 글자 크기와 셀 높이를 측정합니다. 넘치는 행은 원본 순서대로 이어지는 장에 자동 분할하며 `pagination`의 실제 장수를 함께 안내합니다. 행 병합, 삭제나 글자 축소로 맞추지 않습니다. 한 셀 자체가 한 장보다 크면 오류에 표시된 셀 내용을 별도 장에 나눕니다. 기본 주석은 11pt이며 참고 양식의 명시 크기는 유지합니다.

## 요청한 경우에만 확장

| 필요한 기능 | 읽을 위치 |
|---|---|
| 역할별 입력, 크기/여백, 좌표, 표 스타일, 계산값과 기간/분모 | [native-layout.md](native-layout.md)의 해당 절. 계산 바인딩은 [design-and-quality.md](design-and-quality.md)의 수치 절 |
| 복합 도형과 부분 글자 강조 | [advanced-shapes.md](advanced-shapes.md) |
| 기존 PPT/이미지의 색 조합과 서체, 표 구성 | [reference-style.md](reference-style.md) |
| 완성된 HTML 또는 문구 편집 후 저장본 사용 | [native-layout.md](native-layout.md)의 HTML 변환 절 |

## 실행 결과와 PPTX 승인

`ppt-design-preview` 응답의 `scenePreflight`와 수치 검사 결과를 재사용합니다. 경고는 필요한 장만 한 번 확인하며 경고를 지우려고 반복 보정하지 않습니다. 구조 검사는 화면 검토를 대신하지 않습니다.

현재 HTML에 대한 실제 승인 뒤 `ppt-design-preview`가 반환한 `designReview`를 그대로 job에 합치고 `confirmed:true`로 둡니다. `ppt`가 경로와 해시를 검사하므로 사람이 검증을 반복하지 않습니다. 동일 내용의 승인 기록은 재사용하고 변경된 내용에 이전 승인을 옮기거나 해시를 새로 만들어 맞추지 않습니다.
