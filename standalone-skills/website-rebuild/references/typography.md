# 한글 웹/앱 UI 글자 기준

새 UI를 만들거나 글자 스타일을 고칠 때만 읽습니다. 기존 프로젝트 전체를 이 기준으로 다시 꾸미거나 별도 선택 질문을 추가하지 않습니다.

## 정해진 글꼴부터 유지

사용자가 명시한 글꼴과 참고 양식, 기존 앱 디자인 시스템이 기본값보다 우선합니다. 서로 충돌하지 않으면 기존 선택을 재사용합니다. 원본 화면을 재현하는 작업은 원본의 글꼴, 굵기, 자간과 줄 간격을 먼저 맞춥니다. 확인하지 못한 부분만 기본값으로 보완합니다.

- 정해진 기준이 없는 새 한국어 웹/앱 UI: **Pretendard**를 기본으로 사용합니다.
- 사용자가 다른 글꼴을 고르려 할 때만 `Noto Sans KR(긴 본문) / Pretendard(웹 UI) / 나눔스퀘어 네오(제목과 안내) / 디자인에 맞게 선택 / 직접 이름 입력`을 제시합니다. 이미 답했거나 추천을 맡겼으면 묻지 않습니다.
- `font-family: Pretendard`만 적는 것은 글꼴 파일을 제공한 것이 아닙니다. 기존 프로젝트의 로컬 글꼴 파일과 `@font-face` 또는 프레임워크 로더를 재사용하고 실제 경로, 적용 굵기와 로드 결과를 확인합니다.
- 새 글꼴 파일이 필요하면 현재 허용된 배포 방식과 라이선스에 맞춰 프로젝트 자산으로 제공합니다. 글꼴 선택만으로 외부 CDN, 시스템 글꼴 설치나 다른 앱 설정을 추가하지 않습니다. 파일을 제공할 수 없으면 대체 글꼴로 표시됨을 알립니다.
- 대체 글꼴 순서는 `Pretendard, Noto Sans KR, Malgun Gothic, Apple SD Gothic Neo, sans-serif`를 시작점으로 삼습니다. 명시적으로 Noto Sans KR를 선택했다면 그 글꼴을 맨 앞에 둡니다.

## 크기, 자간과 줄 간격

| 대상 | 새 UI의 시작값 | 적용할 때 볼 것 |
| --- | --- | --- |
| 본문과 설명 | 16px 이상, 400 | 여러 줄은 `line-height: 1.5`부터 확인 |
| 버튼, 입력과 표의 주 내용 | 14~16px, 400~600 | 조작 대상의 높이와 글자 크기를 구분 |
| 보조 라벨과 메타정보 | 12~14px | 12px은 하한이며 본문 전체를 작게 만들지 않기 |
| 제목 | 20 / 24 / 28 / 32px, 600~700 | `letter-spacing: -0.03em`은 한글 제목의 시작값 |
| 코드, ID와 숫자 | 내용에 맞는 크기, 자간 0 | 숫자 판독과 식별자 구분 우선 |

크기는 **12 / 14 / 16 / 18 / 20 / 24 / 28 / 32**처럼 적은 수의 짝수 단계로 시작합니다. 상대 단위로 구현하고 브라우저 기본 글자 크기를 임의로 줄이지 않습니다. 반응형 크기, 확대와 기존 양식까지 억지로 짝수 픽셀로 맞추지 않습니다.

이미지의 “두 줄 이상 letter-spacing 150%”는 문맥상 줄 간격입니다. 여러 줄 본문에 `line-height: 1.5`를 사용하며 `letter-spacing: 150%`로 구현하지 않습니다. 한 줄 라벨은 `line-height: normal` 또는 기존 자연스러운 높이를 쓰되, 줄 수를 재는 JavaScript는 넣지 않습니다. 한 줄이라도 화면이 좁아지면 자연스럽게 늘어날 수 있게 합니다.

제목의 `-0.03em`을 모든 글자에 일괄 적용하지 않습니다. 본문은 0부터, 조작 라벨은 0~-0.01em부터 보고 긴 한글, 작은 크기, 숫자의 가독성을 확인합니다. 선택한 서체의 원래 간격이나 원본 디자인이 더 적절하면 그것을 유지합니다.

## 기존 토큰에 맞춰 적용할 예제

아래는 기존 글꼴 로더가 실제 Pretendard 파일을 제공하는 경우의 시작점입니다. 파일이 없는데 이 CSS만 붙여 적용 완료라고 보고하지 않습니다. 프로젝트의 변수명과 컴포넌트 범위에 맞춰 옮기고 이미 정한 값은 유지합니다.

```css
.app-ui {
  --font-ui: "Pretendard", "Noto Sans KR", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
  --type-xs: .75rem;   /* 16px 기준 12px: 보조 정보 */
  --type-sm: .875rem;  /* 14px: 조작 라벨과 표 */
  --type-body: 1rem;   /* 16px: 기본 본문 */
  --type-title: 1.5rem; /* 24px: 구획 제목 */
  font-family: var(--font-ui);
  font-size: var(--type-body);
  line-height: 1.5;
  letter-spacing: 0;
  word-break: keep-all;
  overflow-wrap: anywhere;
}
.app-ui :is(button, input, select, textarea) { font: inherit; }
.app-ui .section-title {
  font-size: var(--type-title);
  font-weight: 700;
  line-height: 1.3;
  letter-spacing: -.03em;
}
.app-ui .control-label { font-size: var(--type-sm); line-height: normal; }
.app-ui .supporting-text { font-size: var(--type-xs); line-height: 1.5; }
.app-ui :is(code, pre, .identifier, .numeric) { letter-spacing: 0; }
.app-ui .numeric { font-variant-numeric: tabular-nums; }
/* 글자는 작아져도 버튼의 조작 영역까지 작게 만들지 않습니다. */
.app-ui .action-button { min-height: 44px; padding: .625rem 1rem; }
```

## 기존 화면 확인에 함께 넣을 항목

1. 글꼴 파일의 로드 성공과 실제 렌더링을 함께 확인합니다. `getComputedStyle(...).fontFamily`는 선언 목록이며 실제 사용 글꼴을 증명하지 않습니다. `document.fonts.ready`나 `document.fonts.check`만으로 성공을 단정하지 않습니다. 사용 가능한 도구로 FontFace 로드 결과와 렌더링된 글꼴을 확인하고, 확인할 수 없으면 그 범위를 알립니다.
2. 제목뿐 아니라 본문, 버튼, 입력, 표, SVG 차트 글자까지 같은 글자 토큰이 연결되는지 봅니다. 로컬 글꼴이 없거나 로드에 실패해도 대체 글꼴로 내용을 읽을 수 있어야 합니다.
3. 390px 안팎의 좁은 화면과 200% 확대에서 긴 한글, 두 줄 버튼, 숫자와 ID가 겹치거나 잘리지 않는지 봅니다. 고정 높이, `nowrap`, 말줄임으로 중요한 내용을 숨기지 않습니다. 넓은 표만 내부 스크롤을 허용합니다.
4. 작은 보조 글자의 대비와 키보드 포커스를 확인합니다. 클릭/터치 영역은 44px을 목표로 유지하고 기존 조밀한 UI는 실제 사용성과 함께 판단합니다. 글자 로딩을 긴 등장 효과로 감추지 않고 `prefers-reduced-motion`도 유지합니다.

이 확인은 기존 작성과 화면 검토 안에서 수행합니다. 매 요청마다 별도 검색, 상시 후크, 전체 화면 재검사나 추가 모델 호출을 만들지 않습니다.
