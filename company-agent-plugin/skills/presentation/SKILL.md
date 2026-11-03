---
name: presentation
description: 보고, 실적 발표, 제안용 PPT를 만들거나 수정합니다. 기존 양식과 한글 발표 구성을 반영하고, 글자와 도형을 편집할 수 있는 발표자료를 제작합니다.
---

# 발표자료 제작

현재 런타임의 `company_agent_runtime.cliCommand`와 `stateRoot`를 사용합니다. 설치 경로나 세션을 다시 탐색하지 않습니다. 이 경로는 기존 하네스의 **HTML 초안 → 승인 → PPT** 작업 공간을 유지합니다.

## 기본 흐름

1. **선택과 자료**: 기존 job/workFile, 목적, 청중, 장수와 스타일을 재사용합니다. 참고가 있으면 아래 해당 경로만 읽습니다. 새 제작에 참고도 스타일 지정도 없을 때만 [양식 선택](references/choices.md)을 한 번 제시합니다. `알아서/추천대로`는 바로 구성하며 아직 보지 않은 초안의 승인은 아닙니다.
2. **내용과 HTML 초안**: 새 job은 [기본 명세](references/schema.md)로 작성합니다. workFile이 없을 때만 `business artifact-start --output "<final.pptx>" --state-root "<stateRoot>"`를 실행하고 반환된 jobPath를 씁니다. `business ppt-design-preview --spec "<jobPath>" --work "<workFile>" --state-root "<stateRoot>"`로 모든 장의 초안을 만듭니다. 실제 사용한 `--template`은 최종 제작에도 유지합니다.
3. **검토와 제작**: 반환된 수치 검사와 `scenePreflight`를 재사용하고 경고가 있으면 관련 장만 확인합니다. 볼 수 있는 환경에서는 처음에는 모든 장, 수정 뒤에는 영향받은 장만 살핍니다. 클릭 가능한 HTML 링크와 장수를 보여 주고 실제 승인 후 반환된 `designReview`에 `confirmed:true`를 기록합니다. 같은 내용의 유효한 승인은 다시 묻지 않습니다. `business ppt --spec "<jobPath>" --work "<workFile>" --state-root "<stateRoot>"`로 제작하고, 확인 뒤 `business artifact-publish --work "<workFile>" --state-root "<stateRoot>"`가 반환한 최종 링크를 전달합니다.

## 필요한 경로만 읽기

| 현재 작업 | 참고자료 |
|---|---|
| PPT, HTML 또는 여러 장 이미지 참고 | [reference-inputs.md](references/reference-inputs.md). 관찰한 색 조합, 글꼴 역할, 표, 차트, 도형과 말투를 짧게 유지 |
| HTML 직접 변환, 자유 배치 또는 이미지 크기만 수정 | [native-layout.md](references/native-layout.md)의 해당 절. 부분 수정에 새 양식 질문을 시작하지 않음 |
| 복합 도형과 부분 글자 강조 | [advanced-shapes.md](references/advanced-shapes.md), 필요할 때만 `references/scene-example.json` |
| 승인/해시 오류 또는 원본 개체 유지 | [design-review.md](references/design-review.md) |
| 배치와 문장 품질 보완 / 재생성 비교 요청 | 각각 [design-and-quality.md](references/design-and-quality.md) / [rebuild-check.md](references/rebuild-check.md) |
| 대표 양식 저장 요청 / 작업 경로와 정리 문제 | 각각 [html-template.md](references/html-template.md) / [output-delivery.md](../company-agent/references/output-delivery.md) |

## 유지할 기준

한글 문체와 수치, 조건, 고정 문구를 보존합니다. 관계에 맞는 표, 차트, 흐름과 복합 도형을 사용하고 모든 장을 같은 카드로 단순화하지 않습니다. 글자, 색과 굵기, 도형과 그룹은 편집 가능해야 하며 표와 차트는 독립 개체로 둡니다. 전체 장 이미지로 대체하지 않습니다.

내용이나 HTML이 바뀌면 해당 초안을 갱신해 확인하며 승인값과 해시를 지어내지 않습니다. 화면을 못 봤으면 구조 검사와 구분합니다. 파일 오류만으로 DRM을 단정하지 않으며 실제 거절은 다른 경로로 우회하지 않습니다. 같은 workFile을 유지하고, 일반 제작에 추가 작업자, 반복 재빌드, 장별 승인이나 내부 JSON 작성 요청을 넣지 않습니다. 이미 읽은 지침과 검사 결과는 재사용합니다.
