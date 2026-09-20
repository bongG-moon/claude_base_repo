# Markdown 안내서 포함 검증 — 2026-09-20

이 기록은 MD 포함 작업 시점의 검사입니다. 이후 글꼴·화면 디자인과 모바일 표를 변경한 현재 결과는 [가이드 화면·글꼴 검증](VALIDATION_GUIDE_DESIGN_2026-09-20.md)을 참고하세요.

## 반영 범위

- `docs/README.md`에 초보자용 안내 목차를 추가했습니다.
- `CLAUDE_CODE_BASICS.md`에 Claude Code와 Company Agent의 차이, 작업 폴더, 요청·승인·실행·확인, 기억과 대화, 사용량 관리의 기본 설명을 추가했습니다.
- 명령어·단축키는 공식 문서와 대조하고 내부 배포 버전·CLI·VS Code·Workspace에 따른 차이를 구분했습니다.
- 목차와 안내서 6개를 설치 ZIP의 `docs`와 플러그인의 `resources/manuals`에 포함합니다. Workspace ZIP에도 같은 안내서를 넣습니다.
- `scripts/build-manuals.mjs`가 같은 원본에서 통합 HTML과 설치용 MD를 생성합니다. MD 누락·불일치는 설치 ZIP 생성 전에 검출합니다.
- 첫 업무 화면과 설치 완료 안내에 MD 목차의 위치를 추가했습니다.
- JEV, 업무 스킬, 후크, 승인 정책, 활성 설치 환경은 변경하지 않았습니다. 안내서를 자동으로 모델 문맥에 주입하거나 모델을 호출하지 않습니다.

## 실제 확인한 결과

| 확인 | 결과 |
| --- | --- |
| 안내서 계약 테스트 | 14개 통과: 설치용 MD 7개, 원본 바이트 일치, UTF-8, 문서 간 링크, 빌더·설치 연결 |
| 시작하기 실습 테스트 | 6개 통과 |
| 초보자 설치 안내 테스트 | 8개 통과 |
| 명령어·단축키 정적 검사 | 통과 |
| 통합 가이드 브라우저 검사 | 1440·768·390px, 6부·50장, 80개 앵커, 예문 복사 7개, 인쇄, 이전 링크 5개 통과; 오류·외부 요청 없음 |
| 직접 화면 확인 | 새 기본 사용법의 데스크톱 화면과 명령어·단축키의 좁은 화면 2개 확인. 좁은 화면의 표는 가로 스크롤 영역으로 표시 |
| 설치 ZIP 회귀 검사 | 통과: MD 7개의 원본·ZIP·설치 payload 일치, 첫 업무 MD 링크, 누락·오래된 MD의 빌드 거부, 기존 출력 보존 |
| Workspace ZIP 검사 | 40개 파일이 원본과 일치; 실행 상태·인증 정보 미포함 |

브라우저 자동 검사는 27개 화면을 생성했으며, 모든 화면을 사람이 읽은 것으로 간주하지 않습니다. ZIP 회귀 검사는 임시 폴더에서 수행했으며 이 PC의 활성 Company Agent 설치를 변경하지 않았습니다.

## 재실행

```powershell
node scripts/build-manuals.mjs --modules "<승인된 node_modules 경로>" --check
python -X utf8 -m unittest discover -s tests -p test_handbook_contract.py -v
python -X utf8 -m unittest discover -s tests -p test_onboarding_practices.py -v
python -X utf8 -m unittest discover -s tests -p test_novice_setup_messages.py -v
node scripts/test-shortcuts-guide.mjs
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File deploy/Test-OfflineBundle.ps1 -KeepArtifacts
```

## 확인하지 않은 범위

- 사내 HCP 모델 응답, 사내 PC의 실제 재설치, DRM·메일은 이번 문서 변경의 실행 검증 범위가 아닙니다.
- 기존 1.4.17 설치와 공개 Release ZIP은 자동으로 갱신되지 않습니다. 이번 변경은 소스·로컬 패키지 검증까지이며 커밋·푸시·Release 게시를 수행하지 않았습니다.
