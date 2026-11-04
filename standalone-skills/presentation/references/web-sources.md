# 웹 조사와 적용 범위

2026-11-04 공식 소스의 동작, 의존성과 라이선스를 확인했습니다. 실행할 때마다 웹을 검색하는 지침이 아닙니다.

- [Frontend Slides](https://github.com/zarazhangrui/frontend-slides/tree/9906a34d640d2111f724544cbc50f7f130569ae1): 자유 HTML/CSS 제작, 장표 단위 가독성과 화면 맞춤을 참고했습니다.
- [Frontend Slides Editable](https://github.com/archlizheng/frontend-slides-editable/tree/e5663e6a0bdc2c2a673198bab3fb61036a7f20ee): 콘텐츠와 편집 UI 분리, 개체 이동/크기, 되돌리기, 장표 순서와 저장 방식을 참고했습니다.
- [Frontend Slides 편집기 분리판](https://github.com/wengzige/frontend-slides/tree/372a7570a50bd19253570e6229cef5caddca4d27): 일반 DOM을 유지하고 편집한 속성만 기록하는 방식을 참고했습니다.
- [Huashu Design](https://github.com/alchaincyf/huashu-design/tree/b2460b031c33ff32d2bf3b97263527daa231e4de): 참고 스타일 관찰과 HTML을 시각적 정본으로 유지하는 원칙을 참고했습니다.

새 `slides.py`와 `html-deck-editor.*`는 위 설계 원칙을 참고한 독자 코드입니다. 원본 편집기 코드를 복사하거나 상시 후크, 자동 버전 조회, 외부 폰트/미디어 fetch를 포함하지 않습니다.

선택형 PPTX 내보내기는 [dom-to-pptx](https://github.com/atharva9167j/dom-to-pptx)의 공식 npm 2.1.2 번들을 사용합니다. MIT 라이선스, 버전과 SHA-256은 `assets/vendor/dom-to-pptx/`에 포함합니다. Node 전용 설치기의 자동 브라우저 다운로드는 사용하지 않고 기존 로컬 브라우저에서 번들 API를 호출합니다. SVG는 그림이며 네이티브 차트 데이터로 변환된다는 뜻이 아닙니다.

Dashi의 최신 [PPTX 엔진 라이선스](https://github.com/chuspeeism/dashi-ppt-skill/blob/21dc7e5fc8c3a0d7f6a94948153dd1ee954f4e64/skills/dashi-ppt/project/packages/html-deck-to-pptx/LICENSE)는 별도 추출 사용을 제한하므로 제품에 복사하지 않았습니다. 공식 도구 자체의 비교 실행과 엔진을 분리해 배포하는 것은 다릅니다.
