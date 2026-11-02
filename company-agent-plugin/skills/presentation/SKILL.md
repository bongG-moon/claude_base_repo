---
name: presentation
description: 보고, 실적 발표, 제안용 PPT를 만들거나 수정합니다. 기존 양식과 한글 발표 구성을 반영하고, 글자와 도형을 편집할 수 있는 발표자료를 제작합니다.
---

# 편집 가능한 발표자료

## 요청에 맞는 시작점

이미 알려준 목적, 청중, 장수, 스타일과 기존 job/workFile을 재사용합니다. 빠진 핵심 조건만 묻습니다. **새 제작에 디자인 지정도 참고자료도 없으면** `references/choices.md`의 양식 선택을 한 번 보여 줍니다. 깔끔한 업무 보고형 / 흑백 간결형 / 따뜻한 설명형 / 기존 PPT·이미지·HTML 양식 활용 / 내용에 맞게 추천 / 직접 입력 중 고르게 합니다. `알아서/추천대로/질문 없이`는 추가 디자인 질문 없이 진행하며 보지 않은 HTML 초안의 승인으로 간주하지 않습니다. 기존 선택과 수정 요청에 설문을 반복하지 않습니다.

- **PPTX, HTML, 이미지 참고:** `references/reference-inputs.md`를 읽습니다. 첨부는 기본적으로 스타일 참고이며 명시적인 원본 배치 유지 요청에만 preserve를 씁니다. 필요한 PPT 장은 정상 열기와 장별 캡처로 보고, 이미지 최대 60장은 전체 목록을 유지해 2~3장씩 확인합니다. 한글 서체, 크기, 여백, 배치, 표, 차트, 도형, 강조와 색 조합을 `referenceStyle`로 짧게 합쳐 새 내용에 맞게 재구성합니다. 도구 가용성과 미확인 장을 구분하고 기본 디자인 선택을 반복하지 않습니다.
- **이미지 크기만 수정:** `references/native-layout.md`의 해당 작업으로 바로 진행합니다. 새 디자인 질문이나 HTML 초안 승인을 시작하지 않습니다.
- **디자인 비교 요청:** 선택한 방향을 실제 내용에 적용합니다. 요청이 없으면 전체 발표자료를 여러 벌 만들지 않으며, 초안에서 제목, 표, 차트, 업무 흐름을 역할에 맞는 배치로 구성합니다.
- **선택 복원이 불명확:** `references/choices.md`의 `business ppt-choices`를 사용합니다. 질문만 할 때 명령이나 빈 JSON은 필요 없습니다. 기다리는 단계는 오류가 아닙니다.

명령은 후크가 준 정확한 `company_agent_runtime.cliCommand` 뒤에 붙이고 `stateRoot`를 그대로 사용합니다. 메타데이터를 명령으로 실행하거나 설치 경로, 소스, 세션을 탐색하지 않습니다. 작업자 사용은 현재 런타임 라우팅을 따르며 선택, 읽은 지침, 같은 workFile을 전달합니다.

한글 장표의 제목, 본문, 강조와 주석 역할을 유지합니다. 분기 흐름과 일정, 복합 도형과 곡선도 내용에 맞게 사용하며 단순한 카드나 표로만 평준화하지 않습니다. 복잡한 구성도 같은 장면 명세로 HTML을 먼저 만들고 승인 뒤 네이티브 PPT로 옮깁니다.

## HTML 초안부터 최종 PPT까지

전체 job을 처음 작성할 때 `references/design-and-quality.md`를 읽습니다. 각 장의 메시지와 확인된 근거를 먼저 정한 뒤 관계에 맞는 배치를 고릅니다. 부분 수정은 기존 선택과 관련 필드부터 고치며 모든 참조를 다시 읽지 않습니다.

1. **작업 공간:** 기존 workFile이 없을 때만 `business artifact-start --output "<final.pptx>" --state-root "<stateRoot>"`. 반환한 workFile, jobPath, workingDirectory를 수정과 완료까지 유지합니다.
2. **전체 명세:** jobPath에 선택값, title, 요청한 모든 slides, 사실과 theme를 실제 스키마로 씁니다. 새 디자인은 `pageRole`로 장별 역할을 정하고 `presentationProfile`에 확인한 한글 서체 역할과 여백을 간단히 유지합니다. 기존 job이나 참고 배치에 새 역할을 임의로 덮어쓰지 않습니다. 선택 전용 JSON은 전체 job이 아닙니다. 블록 순서 지시가 있을 때 contentOrder/contentLayout을 사용합니다. 현재 지시와 승인 초안이 기억된 선호보다 우선합니다.
3. **HTML 초안:** `business ppt-design-preview --spec "<jobPath>" --work "<workFile>" --state-root "<stateRoot>"`. 실제 양식을 사용하면 같은 `--template`을 최종 제작에도 유지합니다. 모든 장을 포함하며 예비 PPT나 html-report 설문을 따로 만들지 않습니다.
4. **확인:** 실제 HTML을 살피고 링크와 전체 목차를 보여준 뒤 `이대로 PPT 제작 / 수정 요청 / 참고 디자인 변경`을 묻고 기다립니다. 실제 답 전에는 최종 제작하지 않습니다. 반환한 designReview를 전체 job에 합치고 해당 초안을 승인받은 뒤에만 `confirmed:true`로 둡니다. 해시나 승인값을 지어내지 않습니다. 실질적인 자료, 내용, 디자인 변경은 같은 workFile에서 초안을 갱신해 다시 확인받습니다.
5. **PPT 제작:** `business ppt --spec "<jobPath>" --work "<workFile>" --state-root "<stateRoot>"`. 선택한 --template을 유지하고 지원하는 글자, 도형, 표, 차트는 네이티브 개체로 만듭니다.
6. **검토와 전달:** 초안 응답의 `scenePreflight` 경고를 한 번 모아 필요한 장만 보정하고 글자, 단위, 총계, 장수와 편집 가능성을 확인합니다. 실제 화면 검토는 처음에는 모든 장, 수정 뒤에는 변경과 영향받은 장만 봅니다. 이미지 관찰이 필요할 때 `references/image-review.md`의 현재 인계 경로를 따릅니다. 확인 후 `business artifact-publish --work "<workFile>" --state-root "<stateRoot>"`로 마치고 최종 경로와 실제 제한만 알립니다.

글자 색, 굵기, 글꼴을 편집할 수 있어야 합니다. 카드와 도식은 의미 있는 부분끼리 그룹화하고 그룹 해제를 허용하며 표와 차트는 독립된 네이티브 개체로 둡니다. 사진이나 스크린샷 안의 글자를 편집 가능하다고 설명하지 않습니다. 렌더링이 불가하면 수행한 구조와 내용 검사, 화면 미검토를 구분합니다.
수치 문장을 옮길 때는 `{{fact:id.statement}}`로 지표 이름과 값을 함께 재사용하고 기존 fact의 기간, 범위와 분모를 유지합니다. 음수 막대, 항목명과 선 위 숫자의 실제 가독성은 이미 수행하는 렌더 검토에서 확인합니다.

## 필요한 경우에만

- 역할별 구성과 참고 서식 프로필: `references/native-layout.md`. 부분 강조, 복합 도형, 연결선과 곡선이 필요하면 `references/advanced-shapes.md`만 추가로 읽습니다. 기존 HTML 직접 변환은 `references/native-layout.md`. htmlSource가 바뀌면 다시 측정하며 검토용 HTML만 편집해도 네이티브 명세가 바뀌지는 않습니다.
- 초안 승인이나 해시 불일치, preserve 미리보기 한계: `references/design-review.md`.
- PPT 배치를 보정했거나 반복 제작을 요청받은 경우: `references/rebuild-check.md`. 보정을 job 또는 명시된 재생성 경로에 남기고 전달본과 재빌드의 내용 및 배치를 출하된 비교기로 확인합니다. 일반 생성에 매번 재빌드를 추가하지 않습니다.
- 대표 양식 저장 요청: `references/html-template.md`. 이미 정한 저장 위치는 재사용하고 없는 경우 개인/프로젝트 위치를 확인합니다. 승인된 추상 디자인을 가상 내용의 HTML로 저장하며 원본 PPTX와 업무 내용을 자동 저장하거나 대체하지 않습니다.
- 작업 경로, 재시도, 정리가 불명확: `../company-agent/references/output-delivery.md`. 같은 작업을 재사용하고 draft2/v3를 만들지 않습니다. publish는 등록된 미변경 중간 파일만 정리합니다.
- 실제 처리 제한: `../company-agent/references/business-protection.md`. 파일 오류나 DRM 표시만으로 캡처 불가를 단정하지 않으며 실제 거부는 다른 도구나 작업자로 우회하지 않습니다.

출하된 명령과 허용된 도구만 사용합니다. 의존성 설치, 임의 Python/VBA, 편집 결과의 통째 이미지화, 사용자 Office 종료로 문제를 해결하지 않습니다. 버전별 기능이 실제로 불명확할 때만 `business ppt-capabilities`를 확인합니다. 승인 분류기 시간 초과는 PPT 제작 실패와 구분하고 같은 입력으로 일시 오류만 최대 한 번 재시도합니다. 권한 거부는 우회하지 않고 독립적인 작업만 계속합니다. 원본과 사용자 파일을 보존하며 학습에는 허용된 추상 선호와 검증된 수정만 남기고 업무 장표는 자동 저장하지 않습니다.
