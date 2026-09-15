# HTML 디자인 양식 구현 검토

## 조사한 서비스와 구현 기준

- [Glass UI 생성기](https://ui.glass/generator): 반투명 표면과 배경 흐림을 사용하는 유리형 서비스. 검색 결과의 설명은 확인했으나 직접 페이지 조회는 시간 초과였습니다.
- [Neumorphism.io](https://neumorphism.io/)와 [공개 저장소](https://github.com/adamgiebl/neumorphism): Soft UI 그림자 생성 서비스입니다.
- [Neobrutalism components](https://www.neobrutalism.dev/docs): 강한 테두리와 그림자가 드러나는 컴포넌트 사례입니다.
- [Magic UI Bento Grid](https://magicui.design/docs/components/bento-grid): 중요도에 따라 다른 크기의 구획으로 나누는 배치 사례입니다.
- [MDN backdrop-filter](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/backdrop-filter): 뒤쪽 픽셀을 흐리므로 표면이 투명/반투명이어야 효과가 보입니다. 부모의 불투명도 등은 배경 처리 범위에도 영향을 줍니다.
- [MDN box-shadow](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/box-shadow): 여러 그림자와 inset 그림자를 조합해 솟음/눌림을 표현합니다.
- [W3C 대비 기준](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html): 장식 효과보다 텍스트 식별을 우선합니다. 이 작업이 WCAG 전체 인증을 의미하지는 않습니다.

서비스·공식 문서의 원리를 참고해 자체 CSS를 작성했습니다. 외부 서비스 코드를 설치하거나 실행 시 인터넷에 연결하지 않습니다. 이 서비스의 화면과 완전히 같은 제품을 복제한 것은 아닙니다.

## 확인한 문제와 수정

1. 기본 HTML, 보고서 배치, 테마 파일에 양식별 규칙이 중복되어 있었습니다. 양식별 표현을 `report_styles.py`로 모았습니다.
2. 유리형 배경이 약하고 표면이 두꺼워 특징이 흐릿했습니다. 색 덩어리 배경, 반투명 표면, 22px 배경 흐림, 밝은 테두리를 조합했습니다.
3. 뉴모피즘은 같은 색의 배경/표면을 유지하고, 솟은 판·눌린 지표·솟은 차트의 그림자를 구분했습니다. 그림자가 겹치지 않도록 여백을 늘렸습니다.
4. 벤토형은 주요 지표 폭을 크게 하고 긴 표/차트는 전체 폭을 사용합니다. 에디토리얼·미니멀·브루탈리즘·자유양식도 구분선, 테두리, 여백 규칙을 한곳으로 정리했습니다.
5. 첨부 HTML 색상은 CSS에 존재해도 우선순위가 낮아 기본 테마에 밀렸습니다. 사용자 참고 양식의 검증된 설정이 실제 화면에 우선 적용되도록 수정했습니다.
6. 인쇄 시 표지의 강한 배경 규칙이 인쇄용 흰 배경을 이기던 문제를 수정했습니다. 브라우저 지원 부족/투명도 축소용 대체 스타일도 추가했습니다.

‘추가 디자인’ 선택 직후 8개 디자인을 보여주고 나중에 분량·보기 방식을 묻는 순서는 유지합니다. 개인 Memory, 모델/MCP 설정, 설치된 개인 Skill은 변경하지 않습니다.

## 검증 범위

신규 가상 자료로만 8개 보고서를 생성했습니다. 기존 사용자 HTML이나 회사 문서를 읽거나 덮어쓰지 않았습니다.

- Windows Edge의 격리된 헤드리스 브라우저에서 실제 CSS 결과를 검사했습니다. 스크립트 보호 정책은 그대로 적용합니다.
- 1440 / 768 / 390px에서 본문 가로 넘침, 지표 잘림을 검사했습니다.
- 8개 양식의 미리보기와 실제 비표지 보고서 판의 배경·그림자·모서리·흐림 값이 일치합니다. 축소된 미리보기의 글자 크기/구성까지 픽셀 단위로 같다는 뜻은 아닙니다.
- 페이지 전환, 5개 구역의 인쇄 표시, 흰색 인쇄 배경, 첨부 양식 색상/모서리 우선 적용을 검사했습니다.
- 브라우저 외부 요청 0건, JavaScript 오류 0건을 확인했습니다.
- 전체 자동 검사 637개 통과, 제외 0개(277.147초). 이후 작은 화면의 한글 단위 줄바꿈을 조정한 최종 코드로 보고서/첨부 양식 관련 검사 45개와 8개 테마 브라우저 검사를 다시 수행했습니다.
- 투명도 축소와 구형 브라우저 대체 규칙은 포함했습니다. 모든 구형 브라우저에서 실행한 것은 아닙니다.

재현 스크립트: `scripts/test-lab/build-theme-fixtures.py`, `scripts/test-lab/check-report-themes.mjs`.
검토용 결과: `build/theme-review-20260915-verified/` (가상 보고서, 화면 캡처, browser-results.json).

이번 변경은 HTML 보고서와 HTML 디자인 미리보기 대상입니다. PPT 렌더러의 유리 흐림 효과나 같은 재질을 새로 구현한 것은 아닙니다. 기존 GitHub Release/개인 PC 설치본에는 자동 적용되지 않으며 새 설치본 배포가 필요합니다.
