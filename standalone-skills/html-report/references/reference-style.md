# 여러 참고 이미지의 스타일을 새 내용에 적용

참고자료가 있을 때만 읽습니다. 첨부 PPT와 장표 이미지는 기본적으로 스타일 참고입니다.
원본 배치와 개체를 그대로 유지하라는 명시 요청만 PPT의 preserve 방식으로 처리합니다.
참고가 있으면 기본 디자인 선택을 다시 묻지 않습니다. 명시한 색, 글꼴, 장수와 내용 조건이 우선합니다.

HTML의 새 참고 양식에서는 글꼴 처리만 미정이면 기존 사용자 글꼴 유지, 참고 글꼴 따라가기, 직접 입력 중 하나를 분량과 보기 선택에 합쳐 한 번 묻습니다. 유지할 글꼴은 `fontChoice`와 필요한 `fontName`, 참고 글꼴은 `fontChoice:auto`로 기록합니다. 현재 요청에서 이미 명시한 글꼴은 묻거나 바꾸지 않습니다. 이 선택은 다른 관찰 특징을 바꾸지 않습니다.

## 확인 범위와 작은 묶음

- `referenceImages`는 실제 로컬 PNG/JPEG/WebP 절대경로를 순서대로 최대 60개 유지합니다. 처음 3장만 남기거나 나머지를 버리지 않습니다.
- 필요한 PPT 각 장을 정상 열람 또는 현재 허용된 화면 도구로 열고 캡처합니다. 이미 열린 문서는 정확한 파일을 확인한 뒤 재사용합니다. 실제 도구 이름과 가용성을 확인하며 존재하지 않는 열기, 다음 장, 캡처 도구를 만들어 호출하지 않습니다.
- 보호 PPT는 정상 PowerPoint 열기와 장 이동 후 허용된 화면을 캡처합니다. 파일 Export를 화면 캡처라 하지 않으며 DRM 해제, 복호화나 실제 거절 뒤 다른 도구로 우회하지 않습니다. 도구가 없으면 해당 범위를 미확인으로 남깁니다.
- 원본 파일, 원본 장 번호, 캡처 경로와 확인 상태를 현재 job의 `referenceStyle.evidence`에 짧게 연결합니다. 캡처 계획, 구조 분석, 이미지 확인은 서로 구분합니다.
- 이미지는 한 번에 2~3장씩 봅니다. 반복 스타일은 공통 규칙으로 합치고 새로운 배치, 색 조합과 충돌만 덧붙입니다. 같은 파일 버전의 기존 관찰을 재사용하고 이미지나 OCR 전문을 매번 다시 보내지 않습니다.
- 검은 화면, 빈 이미지, 같은 장의 중복 캡처, 잘린 글과 누락 장은 읽은 것으로 기록하지 않습니다. 총 공급 범위, 실제 확인 범위, 미확인 범위와 이유를 짧게 남깁니다. 단순히 비슷한 장이라는 이유로 중복 캡처라 단정하지 않습니다.

## 관찰할 스타일

한글 제목, 본문, 수치와 주석의 서체 역할 및 크기 비율, 굵기와 부분 강조를 봅니다.
여백, 정렬, 열 구성, 정보 밀도, 표 헤더와 교차행, 테두리와 셀 간격, 차트 계열과 범례,
격자와 수치 위치, 도형과 연결선, 제목과 본문의 말투를 함께 정리합니다.

색은 하나의 강조색으로 줄이지 않습니다. 배경과 글자 대비, 주색과 보조색의 역할,
표 헤더와 본문의 조합, 교차행, 차트 계열 색과 강조색의 반복 관계를 유지합니다.
색상이나 글꼴 이름과 정확한 pt 값이 이미지에 보이지 않으면 확정 사실로 쓰지 않습니다.
눈으로 추정한 값과 새 결과에서 선택한 구현값을 `evidence.uncertain`에 구분합니다.

## 현재 job의 referenceStyle

별도 분석 파일, 설문, 모델 설정이나 상시 후크를 추가하지 않습니다. 실제 관찰한 필드만
현재 job의 `referenceStyle`에 넣고 모르는 필드는 생략합니다. 숫자 크기는 PPT에서 pt,
HTML에서 px이므로 화면을 보고 대상 산출물에 맞게 환산한 값은 추정임을 근거에 씁니다.

대상 엔진의 실제 범위도 지킵니다. PPT 역할 프로필에 적용하는 제목은 16~60pt, 본문은
10~32pt, 주석은 8~18pt이며 바깥 여백은 20pt 이상에서 페이지 크기가 허용하는 범위,
간격은 8~60pt입니다. HTML의 px 값을 PPT에 그대로 복사하거나 자동 축소될 것으로
가정하지 않습니다. 범위를 벗어나면 새 내용과 페이지 크기에 맞는 값을 명시해 조정합니다.

| 필드 | 지원 값과 역할 |
|---|---|
| colors | bg, surface, text, muted, primary, secondary, border, tint 및 series 배열. 색은 # 선택 가능한 6자리 HEX |
| typography | headingFont, bodyFont, titleSize, bodySize, captionSize |
| spacing | outer, gap, radius |
| table | headerFill, headerText, bodyFill, bodyText, alternateFill, borderColor, borderWidth, headerBold, fontSize, align, padding |
| chart | seriesColors, legendPosition, fontSize, labelSize, gridColor, showGrid, marker, lineWidth |
| patterns | layout, tables, charts, shapes, emphasis, writing. 각 항목은 500자 이하의 짧은 관찰 규칙 |
| evidence | 최대 60개. 각 항목은 source, scope, observed 배열, uncertain 배열. 원본과 범위, 확인 사실과 미확인을 짧게 연결 |

예시는 이미 관찰한 값을 기록하는 형식입니다. 예시 색과 글꼴을 무관한 참고자료에 기본값으로 넣지 않습니다.

```json
{
  "referenceImages": ["C:/작업/참고-01.png", "C:/작업/참고-02.webp"],
  "referenceStyle": {
    "colors": {"bg":"FFFFFF","text":"23334A","primary":"234E70","secondary":"F0B34B","series":["234E70","F0B34B"]},
    "typography": {"headingFont":"맑은 고딕","bodyFont":"맑은 고딕"},
    "table": {"headerFill":"234E70","headerText":"FFFFFF","alternateFill":"EFF3F7"},
    "patterns": {"layout":"제목 아래 결론, 넓은 근거 영역","emphasis":"핵심 수치만 보조색으로 강조"},
    "evidence": [
      {"source":"C:/작업/참고-01.png","scope":"원본 1장, 이미지 확인","observed":["남색 제목과 노랑 수치 강조"],"uncertain":["정확한 서체는 이미지로 확인할 수 없어 설치된 맑은 고딕 선택"]},
      {"source":"C:/작업/참고-02.webp","scope":"원본 2장, 이미지 확인","observed":["짙은 표 헤더와 밝은 교차행"],"uncertain":["원본의 정확한 색상값은 시각 추정"]}
    ]
  }
}
```

`patterns`는 작성 시 배치와 네이티브 개체를 구성하는 관찰 메모이며 자동 픽셀 복제 명령이 아닙니다.
사용자가 정한 필드와 기존 job의 명시값을 유지하고, 관찰한 규칙으로 미지정 값을 채웁니다.
PPT는 지원하는 글자, 도형, 표와 차트를 편집 가능한 개체로 구성합니다. HTML도 표와 차트의
실제 기능과 읽기 흐름을 유지합니다. 새 내용의 길이와 관계에 맞게 재배치하며 캡처를
전체 배경에 붙이는 방식으로 재구성을 대신하지 않습니다.

같은 검토에서 제목과 본문 역할, 표와 차트의 스타일, 여백, 도형과 강조, 색 조합이
이어지는지 확인합니다. 실제와 다른 근사, 미지원 효과와 미확인 범위만 짧게 알립니다.
원본 내용, 캡처나 OCR 전문을 개인 메모리와 프로필에 자동 저장하지 않습니다.
