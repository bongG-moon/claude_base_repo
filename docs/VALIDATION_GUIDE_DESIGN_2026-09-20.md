# 가이드 화면·글꼴 검증 — 2026-09-20

## 반영 범위

- 통합 HTML의 제목, 목차, 본문 폭, 여백, 표, 예문, 성공·문제 안내의 시각적 구분을 정리했습니다.
- 좁은 화면에서는 접이식 목차와 항목별 표 카드로 표시합니다. 기존 문서 링크와 장별 앵커는 유지합니다.
- 한글 조사와 붙어 강조 구문이 그대로 표시되던 본문 6곳을 원본 Markdown에서 수정했습니다.
- Noto Sans KR 400–700을 약 90KiB의 안내서 전용 WOFF로 포함했습니다. 글꼴 설치나 외부 다운로드 없이 HTML 한 파일에서 표시합니다.
- 원본 글꼴·서브셋 해시, 포함 문자, 출처와 OFL을 빌드 자산에 기록했습니다. 새 문자가 서브셋에 없으면 빌드를 실패시켜 조용한 대체 글꼴 사용을 막습니다.
- 통합 HTML, 이전 링크용 HTML 5개, 설치 첫 화면에 같은 글꼴을 적용했습니다. 안내서를 스킬·후크 문맥에 추가하지 않았습니다.

## 실제 확인한 결과

| 확인 | 결과 |
| --- | --- |
| 직접 브라우저 확인 | 320·390·768·1440px에서 대표 화면 확인. 제목, 모바일 목차, 명령어 표, 스킬 표, 요청 예문, 기본 사용법, 첫 업무 화면을 나누어 검사 |
| 렌더링 | Noto Sans KR 로드 완료, 대체 문자와 노출된 강조 구문 없음, 검사한 화면의 가로 넘침 없음 |
| 이동 | 모바일 목차 펼침과 장 이동, 첫 업무 화면에서 통합 가이드 이동 확인. 통합 가이드의 중복 ID·누락된 내부 앵커 없음 |
| 브라우저 오류 | 확인한 탭의 경고·오류 로그 없음 |
| 정적·동작 검사 | 글꼴·화면 계약 4개, 안내서 계약 14개, 시작하기 실습 6개 통과 |
| 생성물 일치 | `build-manuals.mjs --check`, 첫 업무 화면 재생성 일치, 명령어·단축키 정적 검사 통과 |
| 설치 ZIP 회귀 검사 | `Test-OfflineBundle.ps1 -KeepArtifacts` 통과. 임시 폴더에서 검증했으며 활성 설치는 변경하지 않음 |
| 최종 소스 패키지 | 별도 로컬 검사용 ZIP 생성. 가이드 HTML 12개가 현재 원본과 바이트 단위로 일치하고 첫 업무 화면 2개에 내장 글꼴 포함 |

브라우저 제어의 로컬 파일 URL 제약으로 같은 생성물을 루프백 HTTP에서 열어 검수했습니다. 화면 검수에는 외부 서버나 외부 글꼴을 사용하지 않았습니다.

검사용 ZIP: `.smoke/guide-design-20260920/company-agent-guide-design.zip`

SHA-256: `3300780d34d9efd09fffea4942e70b264f4ff81fb674d08c1ebc288b80c86f5b`

## 검증 범위의 한계

- 전체 50장의 모든 화면을 시각적으로 검사한 것은 아닙니다. 대표 화면 직접 확인과 전체 생성물의 문자·링크·구조 검사를 함께 수행했습니다.
- 인쇄 레이아웃은 정적 검사만 했습니다. 이번 디자인의 실제 인쇄·PDF 출력과 모든 보조기기 조합은 시험하지 않았습니다.
- 브라우저 회귀 검사 스크립트의 글꼴·문자·넘침 검사를 보강했지만, 이번 실행의 시각적 근거는 브라우저 직접 조작과 화면 확인입니다.
- 사내 PC의 실제 재설치, 기존 설치·공개 Release 갱신, 커밋·푸시는 수행하지 않았습니다.

## 재검사

```powershell
node scripts/build-manuals.mjs --modules "<승인된 node_modules 경로>" --check
python -X utf8 -m unittest discover -s tests -p test_guide_presentation.py -v
python -X utf8 -m unittest discover -s tests -p test_handbook_contract.py -v
python -X utf8 -m unittest discover -s tests -p test_onboarding_practices.py -v
node scripts/test-shortcuts-guide.mjs
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File deploy/Test-OfflineBundle.ps1 -KeepArtifacts
```
