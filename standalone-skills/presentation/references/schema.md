# 내부 명세와 실행

JSON은 작업자가 만드는 내부 파일입니다. 사용자는 목적·자료·수정 의견을 대화로 전달하면 됩니다.
최종 사용자 결과는 PPT 하나이며 초안·명세는 작업 내부에 유지합니다.

```json
{
  "title":"교육 신청 현황", "creationMode":"new", "designPreset":"business",
  "purpose":"진행 현황 보고", "audience":"담당자", "slideCount":2,
  "slides":[
    {"title":"신청은 두 부서에서 진행됐습니다", "layout":"summary", "body":"가상 자료입니다.",
     "bullets":["부서별 수요 확인","후속 교육 일정 검토"]},
    {"title":"부서별 신청 현황", "layout":"evidence",
     "table":{"headers":["부서","신청"],"rows":[["생산","12명"],["품질","8명"]]},
     "body":"신청 인원만 집계했습니다.","contentOrder":["table","body"],"source":"실습 가상 자료"}
  ]
}
```

기본 페이지는 960×540pt입니다. `presentationFrame:{"width":960,"height":540}`로 명시할 수 있습니다.
기본 디자인은 business이며 monochrome / warm도 지원합니다. `presentationTheme`에 title/accent/text/muted/background/tint의
색을 `#` 없는 6자리 RGB로 지정할 수 있습니다. `presentationFont`는 PC에서 확인한 설치 글꼴 이름입니다.

`layout`: auto/summary/evidence/comparison/actions. `body`·`bullets`·`table`·`chart`·`image`를 사용합니다.
chart는 type(column/bar/line/pie), categories, series(name/values)입니다. `contentOrder`는 해당 장에 존재하는
body/bullets/table/chart/image를 한 번씩 적습니다. 자동 배치가 공간을 초과하면 내용·장수 조정으로 해결하며 몰래 축소하지 않습니다.

## 자유 배치, 카드와 그룹

한 장의 `elements`는 자동 body/bullets/table/chart 배치와 섞지 않습니다. 좌표·크기는 pt입니다.

```json
{"title":"핵심 현황", "elements":[
  {"kind":"text","text":"교육 운영 현황","x":40,"y":20,"w":800,"h":50,"size":30,"bold":true},
  {"kind":"shape","group":"신청카드","x":40,"y":110,"w":380,"h":230,"shape":"roundRect","fill":"EEF4F7"},
  {"kind":"text","group":"신청카드","text":"신청 20명","x":65,"y":140,"w":330,"h":70,"size":26,"bold":true,"color":"17324D"},
  {"kind":"text","group":"신청카드","text":"두 부서 합계","x":65,"y":220,"w":330,"h":50,"size":18,"color":"30465B"}
]}
```

text는 size/bold/color/font/align(left/center/right)를 지정합니다. 같은 그룹의 text/shape/image는 목록에서
연속으로 둡니다. 그룹 이름은 64자 이하의 글자·숫자·밑줄·하이픈입니다. table/chart를 그룹에 섞지 않습니다.
shape 지원 이름은 실행기의 오류가 반환하는 범위를 따르며 임의 PowerPoint 상수를 넣지 않습니다.
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
draft 결과의 `designReview`는 경로·명세 해시·초안 해시를 포함합니다. 실제 승인 후에만 그대로 복사하고
`confirmed:true`로 바꿉니다. 원본이나 초안을 바꾸면 build가 거절하므로 갱신된 초안을 먼저 확인합니다.
해시를 임의로 재계산해 이전 승인을 새 내용에 적용하지 않습니다.
