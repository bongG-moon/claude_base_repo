# 발표자료 디자인 참고 출처

2026-10-28에 아래 공개 원문을 확인하고 현재 제작기의 기능과 한국어 업무 보고에 맞게 기준을 다시 작성했습니다.
원문 전체, 실행기, 스타일 카탈로그를 배포본에 복사한 것은 아닙니다. 이 파일은 출처를 확인할 때만 읽습니다.

| 원문 | 반영한 부분 | 적용하지 않은 부분 |
| --- | --- | --- |
| [Huashu Design SKILL](https://github.com/alchaincyf/huashu-design/blob/master/SKILL.md), [deck 모듈](https://github.com/alchaincyf/huashu-design/blob/master/references/modules/deck.md) | 자료의 시각 규칙을 관찰해 재사용, 장표 역할에 따른 구성, 데이터의 관계에 맞는 시각자료, HTML 초안에서 네이티브 PPT 개체로 전달 | 매번 세 가지 시안, 무조건 브랜드 검색과 다운로드, 자동 PDF 추가, 취향 장부와 학습 스크립트, 업데이트 확인 |
| [Jinba consulting SKILL](https://github.com/carnot-tech/jinba-consulting-pptx-skill/blob/main/SKILL.md) | 메시지와 근거를 먼저 정한 뒤 배치 선택, 같은 기준으로 비교, 이전 보고서의 형식과 이번 사실 분리, 빈 공간을 가짜 자료로 채우지 않기 | 일본어 문장 규칙, 고정된 빈 면적 합격선, 항상 웹 조사, 장마다 별도 합의와 다중 에이전트 검토 |
| [Impeccable SKILL](https://github.com/pbakaus/impeccable/blob/main/skill/SKILL.src.md) | 사용자의 기존 디자인과 명시 요청 우선, 읽고 이해할 자료와 시선을 끌 자료의 역할 구분, 실제 렌더에서 문제를 모아 수정 | 설치기와 상시 후크, 전용 CLI, 별도 PRODUCT/DESIGN 파일 의무, 자동 기록 |

Huashu Design은 MIT (Copyright 2026 alchaincyf), Jinba는 MIT (Copyright 2026 Carnot AI Inc.),
Impeccable은 Apache-2.0으로 공개되어 있습니다. 링크의 최신 버전은 달라질 수 있습니다.
이번 반영은 작업 지침의 선택적 재작성이며 해당 프로젝트의 코드나 전체 기능을 내장했다는 뜻이 아닙니다.

색, 글꼴, 굵기와 그룹 편집은 현재 네이티브 제작기의 기능으로 유지합니다. 화면 이미지와 라이브러리
정적 검사를 실제 PowerPoint 편집 시험과 혼동하지 않습니다. 초안 승인과 최종 화면 확인은 기존 흐름에서
수행하며 새 질문, 상시 후크, 반복 모델 호출을 추가하지 않습니다.

## 2026-11-02 PPT Master 추가 검토

[PPT Master 고정 원문](https://github.com/hugohe3/ppt-master/tree/5e8856be0da8e6bc85c4aa28acc614478f7b7137/skills/ppt-master)의 구조와 지침을 읽고 현재 공유 제작기에 필요한 원칙만 독립 구현했습니다. MIT, Copyright (c) 2025–2026 Hugo He입니다. 전체 SVG 변환 엔진이나 스킬 본문을 복사하거나 자동 설치한 것이 아닙니다.

| 원문 | 선택적으로 적용한 부분 | 도입하지 않은 부분 |
|---|---|---|
| [native-shape-authoring.md](https://github.com/hugohe3/ppt-master/blob/5e8856be0da8e6bc85c4aa28acc614478f7b7137/skills/ppt-master/references/native-shape-authoring.md) | 실제 관계에 맞는 도형과 연결선, 같은 경로의 HTML과 네이티브 개체, 독립 편집 개체와 의미별 그룹 | 모든 Office 프리셋, 전용 SVG 생성 도구, Boolean 전체 엔진과 장별 강제 판단 기록 |
| [shared-standards-core.md](https://github.com/hugohe3/ppt-master/blob/5e8856be0da8e6bc85c4aa28acc614478f7b7137/skills/ppt-master/references/shared-standards-core.md), [executor-base.md](https://github.com/hugohe3/ppt-master/blob/5e8856be0da8e6bc85c4aa28acc614478f7b7137/skills/ppt-master/references/executor-base.md) | 같은 문장 안의 부분 강조, 한글 서체 역할과 줄바꿈, 장 역할별 구성과 정보 밀도, 참고 양식의 소수 기준값 재사용 | 별도 계획과 잠금 파일, 매 장의 역할 전환 배너와 추가 작업자, 고정 장수나 카드 금지의 일괄 강제 |
| [edit-native-pptx.md](https://github.com/hugohe3/ppt-master/blob/5e8856be0da8e6bc85c4aa28acc614478f7b7137/skills/ppt-master/workflows/edit-native-pptx.md), [visual-review.md](https://github.com/hugohe3/ppt-master/blob/5e8856be0da8e6bc85c4aa28acc614478f7b7137/skills/ppt-master/references/visual-review.md) | 바꾸지 않은 개체 보존, 고정 개체를 포함한 초안과 확인 범위 표시, 경고를 모아 영향받은 장만 보정 | 전체 round-trip 변환 엔진, 자동 웹 검색과 이미지 생성, 내레이션과 음성 복제, 반복 확인 단계 |

현재 제작기의 추가 다각형은 같은 좌표의 editable freeform이며 원본 프로젝트의 모든 프리셋 조정 핸들을 구현한 것은 아닙니다. 기존 양식의 HTML 투영은 지원 개체와 근사를 구분하며 실제 PowerPoint 렌더링과 동등하다고 주장하지 않습니다. 기존의 한 번의 양식 선택과 HTML 초안 승인 흐름을 유지하고 새 상시 후크나 모델 호출을 추가하지 않습니다.

## 2026-11-03 재검토

[PPT Master routing](https://github.com/hugohe3/ppt-master/blob/main/skills/ppt-master/workflows/routing.md)의 작업별 경로 분리와 기존 개체 보존 원칙, [Huashu deck](https://github.com/alchaincyf/huashu-design/blob/master/references/modules/deck.md)의 완성 HTML 좌표 기반 변환을 참고했습니다. 기존 시각 설계를 단순 카드로 재작성하지 않고 실제 HTML을 측정하며 사용자의 고정 한국어 양식을 별도 자산으로 제공합니다. 원본 구현을 통째로 포함한 것은 아니며 매번 다중 시안/웹 검색/추가 게이트를 도입하지 않습니다. 고정 크기, 한글 줄바꿈, 근거와 비교축, 정보 밀도와 실제 렌더 결과를 중심으로 검토합니다.
