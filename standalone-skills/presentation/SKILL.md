---
name: presentation
description: 한국어 발표자료와 슬라이드를 만듭니다. 기존 PPT와 이미지의 스타일을 참고해 브라우저에서 문구를 편집하고 저장하는 발표본을 제공하며 요청하면 편집 가능한 PPTX로 내보냅니다.
---

# 편집 가능한 HTML 발표본

기본 결과는 페이지 이동, 전체 보기, 발표 메모, 문구 편집, 수정본 저장과 인쇄가 있는 HTML입니다. 조작 방식은 유지하고 디자인과 내용만 바꿉니다. HTML만 요청하면 이 파일로 마칩니다.

`스킬폴더`는 배포 ZIP 전체를 설치한 이 문서의 폴더입니다. 작업 디렉터리는 업무 폴더로 유지하고 Python과 `requirements.txt`의 의존성을 사용합니다. 하네스, 세션 ID나 전용 작업자는 필요하지 않습니다.

## 기본 흐름

1. **요청과 자료 확인**: 기존 job, 목적, 장수와 선택을 재사용합니다. 참고 파일이 있으면 아래 해당 경로만 사용합니다. 참고도 스타일 지정도 없을 때만 [양식 선택](references/choices.md)을 한 번 제시합니다. `알아서/추천대로`는 바로 구성합니다.
2. **HTML 제작**: 새 job은 [기본 명세](references/schema.md)로 작성하고, 수정은 기존 job의 해당 부분만 바꿉니다. `python "스킬폴더/scripts/presentation.py" draft --spec "job.json" --output "발표본.html"`을 실행합니다. 다시 생성할 때는 새 결과 파일명을 지정해 이전 초안을 보존합니다. 실제 사용한 `--template`은 이후에도 유지합니다. 반환된 검사 결과를 재사용하고 경고가 있으면 관련 장만 확인합니다. 볼 수 있는 환경에서는 처음에는 전체 장, 수정 뒤에는 영향받은 장을 살핍니다.
3. **전달**: 클릭 가능한 HTML 링크, 장수와 `문구 편집 → 수정본 저장` 방법을 알립니다. PPTX도 요청했다면 현재 HTML의 실제 승인 후 반환된 `designReview`에 `confirmed:true`를 기록하고 `python "스킬폴더/scripts/presentation.py" build --spec "job.json" --output "발표자료.pptx"`를 실행합니다. 같은 내용의 유효한 승인은 다시 묻지 않습니다.

## 필요한 경로만 읽기

| 현재 작업 | 참고자료 |
|---|---|
| PPT 또는 여러 장 이미지의 스타일 참고 | [reference-inputs.md](references/reference-inputs.md). 정상 파일 분석과 허용된 앱 열기/장별 캡처를 구분하고, 관찰한 색 조합, 서체 역할, 표, 도형과 말투를 짧게 유지 |
| 외부 HTML 변환 또는 편집 후 저장한 HTML을 PPTX로 | [html-deck.md](references/html-deck.md). 저장한 HTML이 새 원본이며 이전 job과 승인으로 덮어쓰지 않음 |
| 제공한 흑백 고정 양식을 명시적으로 선택 | [korean-report-deck.md](references/korean-report-deck.md). 다른 디자인에 흑백을 강제하지 않음 |
| 복합 도형, 부분 강조, 자유 배치 | [advanced-shapes.md](references/advanced-shapes.md)와 필요한 경우 `references/scene-example.json` |
| 배치나 문장 품질 보완 / 재생성 비교 요청 | 각각 [design.md](references/design.md) / [rebuild-check.md](references/rebuild-check.md) |

## 유지할 기준

한글 문체와 수치, 조건, 고정 문구를 보존합니다. 관계에 맞는 표, 차트, 흐름과 복합 도형을 사용하며 모든 장을 같은 카드로 단순화하지 않습니다. PPTX의 글자, 색과 굵기, 도형, 표와 그룹은 편집 가능하게 만들고 전체 장 이미지로 대체하지 않습니다.

승인값과 해시를 지어내지 않습니다. HTML이나 내용이 바뀌었으면 해당 초안을 갱신해 확인합니다. 화면을 못 봤으면 구조 검사와 구분합니다. 파일 오류만으로 DRM을 단정하지 않으며 실제 권한 거절은 우회하지 않습니다. 이미지는 실제 비전 기능으로 확인하고 base64를 읽어 추측하지 않습니다. 내부 JSON을 사용자에게 작성시키거나 일반 제작에 별도 검토 작업자, 반복 재빌드, 하네스 확인 명령을 추가하지 않습니다.
