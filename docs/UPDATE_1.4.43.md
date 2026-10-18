# Company Harness 1.4.43

엑셀 분석 결과를 `DATA`와 `PROCESS`로 나눈 실행 가능한 Python 프로젝트로 만듭니다. 사용자가 수정할 코드에는 쉬운 한국어 주석을 추가합니다.

## 달라지는 점

- `DATA/sources.py`는 입력 파일 위치, `DATA/load.py`는 Excel·Python·JSON 등 자료를 불러오는 부분입니다.
- `PROCESS/pipeline.py`는 저장한 수식 규칙의 Python 계산, `PROCESS/table_steps.py`는 표별 추가 정리·결합·집계를 담당합니다.
- `main.py`로 실행하고 결과는 `outputs` 아래 새 폴더에 저장합니다. `README.md`에 실행법과 수정 위치를 설명합니다.
- 같은 행·열 배치와 수식 구조라면 DATA만 바꾸고 PROCESS를 재사용합니다. 행 증가·열 이동·수식 변경은 자동으로 무시하지 않고 변경 부분을 재검토합니다.
- 정상 파일 직접 읽기, 필요한 파일만 xlwings 사용, 원본·대소문자 보존, 표별 5행·전체 12,000자 모델 요약 제한은 유지합니다. 새로운 후크나 추가 모델 호출은 없습니다.

```text
이 엑셀을 DATA와 PROCESS로 나뉜 Python 프로젝트로 만들어줘.
DATA만 바꿔 같은 처리를 다시 실행할 수 있게 하고,
코딩을 몰라도 역할과 수정할 곳을 이해할 한국어 주석을 넣어줘.
```

모든 수식이나 VBA를 업무별 Python 코드로 자동 번역하는 기능은 아닙니다. 지원 수식은 Python 계산기로 재실행하며, VBA 업무 이전은 추출한 원문 검토 후 별도로 구현·비교합니다. 사내 DRM 실제 파일과 원본 VBA 실행은 운영환경 확인이 필요합니다.

## 배포

- 직원 설치: `Company-Harness-Setup.exe`
- ZIP 대체 설치: `company-agent-1.4.43-2026.09.03.zip`
- 단독 안내서: `Company-Agent-User-Guide.html`
- 사내 GitLab 게시 준비: `Company-Harness-GitLab-Delivery-1.4.43.zip`

기존과 같은 범위에 설치한 뒤 Claude Code를 다시 엽니다. 개인 자료·모델·MCP 설정을 초기화하지 않습니다. EXE는 코드 서명되지 않았으므로 회사 실행 정책을 따르세요. GitLab 묶음은 담당자 게시용이며 자동 업로드하지 않습니다.

이번 배포는 엑셀 스킬 변경만 포함합니다. 별도 개발 중인 Workspace UI·화면 전환·비전 변경은 제외하고 이전 Release는 보존합니다. ZIP 뒤 날짜는 회사 지식팩 버전입니다.
