# 한글 부분 강조와 복잡한 편집 개체

부분 강조, 업무 분기나 곡선이 필요한 장에서만 읽습니다. 사용자에게 아래 내부 명세를 입력하게 하지 않습니다. 같은 장면 명세에서 전체 HTML 초안을 먼저 만들고 실제 승인 뒤 PPT를 만듭니다. 복잡한 구성도 화면 이미지 한 장으로 평탄화하지 않습니다.

## 같은 문장 안의 부분 강조

text 개체의 `runs`는 text/size/color/bold/font/italic/underline을 구간별로 받습니다. 구간의 text를 이어 붙인 값은 개체 text와 정확히 같아야 합니다. 읽은 수치와 고정 문구를 줄이거나 바꾸지 않습니다. 한글은 동아시아 서체와 `ko-KR` 언어를 유지하며 제목과 본문의 글꼴 역할을 구분합니다.

```json
{"kind":"text","x":48,"y":100,"w":820,"h":60,"size":26,"font":"맑은 고딕",
 "text":"신청 120명 중 98명 확인",
 "runs":[{"text":"신청 120명 중 "},{"text":"98명","bold":true,"color":"087F8C"},{"text":" 확인"}]}
```

위 숫자는 명세 형식 설명용 가상 값입니다. 실제 제작은 제공된 원자료를 사용합니다. 구간 서식은 HTML과 PPT에 동일하게 전달되며 PowerPoint에서 개별 글자의 색과 굵기를 수정할 수 있습니다. 글자가 길어지면 의미 단위 줄바꿈과 상자 폭, 주변 공간을 먼저 조정하고 자동으로 글자를 계속 줄이지 않습니다.

## 장별 역할을 사용하는 분기 업무 흐름

다음은 순환 없는 가상 검토 절차입니다. 실제 선후 관계만 edges로 지정하며 병렬 항목을 임의로 직렬 흐름으로 바꾸지 않습니다. 순환, 4단계 초과, 더 복잡한 배치는 elements에 좌표와 선을 명시합니다.

```json
{"pageRole":"workflow","title":"변경 여부에 따라 검토 절차를 구분합니다",
 "workflow":{"nodes":[
   {"id":"read","title":"원본 확인","shape":"parallelogram"},
   {"id":"decide","title":"변경 여부","shape":"diamond"},
   {"id":"edit","title":"내용 수정","shape":"roundRect"},
   {"id":"keep","title":"원본 유지","shape":"hexagon"},
   {"id":"review","title":"결과 확인","shape":"chevron"}],
  "edges":[{"from":"read","to":"decide"},
           {"from":"decide","to":"edit","label":"변경"},
           {"from":"decide","to":"keep","label":"유지"},
           {"from":"edit","to":"review"},{"from":"keep","to":"review"}]}}
```

## 자유 배치의 도형, 연결선과 곡선

단위는 pt이며 x/y/w/h는 장표 내 배치 상자입니다. 같은 장의 elements에 제목, 도형, 글자와 선을 함께 담습니다. 본문 자동 배치와 섞어 일부 내용이 빠지게 하지 않습니다. 복잡함은 도형 개수보다 실제 관계, 영역과 강조에 맞춰 결정합니다.

지원 shape는 `rect`, `roundRect`, `ellipse`, `rightArrow`, `leftArrow`, `upArrow`, `downArrow`, `leftRightArrow`, `chevron`, `diamond`, `triangle`, `hexagon`, `parallelogram`, `trapezoid`, `pentagon`, `octagon`입니다. 기존 3종은 네이티브 프리셋이고 추가 다각형은 HTML과 같은 좌표의 편집 가능한 freeform입니다. Office 프리셋의 조정 핸들까지 제공한다고 설명하지 않습니다.

```json
{"title":"곡선과 연결선을 편집 가능한 개체로 구성합니다","elements":[
 {"kind":"shape","shape":"chevron","group":"단계","x":48,"y":100,"w":250,"h":100,"fill":"EEF4F7","border":"087F8C","borderWidth":1.5},
 {"kind":"text","group":"단계","text":"자료 확인","x":110,"y":132,"w":140,"h":40,"size":22,"bold":true,"font":"맑은 고딕"},
 {"kind":"line","x":305,"y":145,"w":120,"h":80,"points":[[0,0],[60,0],[60,80],[120,80]],"border":"087F8C","borderWidth":2,"endArrow":"triangle"},
 {"kind":"path","x":440,"y":100,"w":420,"h":180,"commands":[["M",0,120],["C",100,0,300,180,420,30]],"closed":false,"fill":"none","border":"087F8C","borderWidth":2}
]}
```

line의 points는 상자 내부 로컬 `[x,y]` 좌표이며 2점은 네이티브 직선, 그 이상은 편집 가능한 꺾은 경로입니다. 시작과 끝의 `startArrow`/`endArrow`는 `none` 또는 `triangle`입니다. 선은 개별 편집 가능하며 도형을 움직이면 끝점이 자동으로 다시 붙는 연결점 기능까지 있다고 설명하지 않습니다.

path는 로컬 좌표의 구조화한 `commands`를 사용합니다. `M`은 시작, `L`은 직선, `C`는 제어점 2개의 3차 곡선, `Q`는 제어점 1개의 2차 곡선, `Z`는 닫기입니다. 임의 SVG 문자열, script나 실행 코드는 받지 않습니다. points 목록과 closed로 직접 다각형을 지정할 수도 있습니다. 열린 경로는 fill:none으로 둡니다. 길고 복잡한 경로는 점이나 명령을 256개 이내로 나누며 모든 점을 상자 안에 둡니다.

같이 움직일 text/shape/line/path/image에는 같은 group을 지정하고 목록에서 연속 배치합니다. 표와 차트는 독립 네이티브 개체로 둡니다. 전체 장을 하나의 그룹이나 그림으로 만들지 않으며 사용자가 그룹을 해제해 내부 글자와 도형을 편집할 수 있어야 합니다.

## 초안에서 확인할 것

복잡한 도형도 HTML과 PPT가 같은 좌표, 경로와 글자 구간을 사용합니다. scenePreflight 경고를 한 번 모아 해당 장의 겹침과 넘침을 확인하고 필요한 부분만 보정합니다. 사진 내부 글자나 원본의 미지원 효과를 편집 가능한 개체라고 설명하지 않습니다. HTML과 PowerPoint의 서체 표시 및 렌더링 차이는 실제 화면에서 별도로 확인합니다. 파일 생성과 구조 검사를 실제 PowerPoint 편집 시험으로 표시하지 않습니다.
