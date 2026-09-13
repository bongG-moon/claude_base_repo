# Company Agent 1.3.9

## 직원용 설치 파일

Assets의 **company-agent-1.3.9-2026.09.03.zip**을 받으세요.
GitHub가 자동 생성하는 Source code (zip/tar.gz)은 직원용 설치 파일이 아닙니다.

1. ZIP을 새 폴더에 압축 해제합니다.
2. `Install-CompanyAgent.cmd`를 실행합니다.
3. 기존 설치와 같은 범위를 선택하고 백업 후 업데이트합니다.
4. 완료 후 Claude Code를 닫았다 다시 엽니다.

Claude Code 2.1.220 이상과 회사에서 승인한 Python 3.11 이상이 설치되어 있어야 합니다.
기존 사내 SMALL/MEDIUM/LARGE 모델 설정과 MCP 연결을 재사용합니다.
개인 Memory·학습 이력·Skill·Knowledge는 기존 보존 절차에 따라 유지합니다.

## 주요 변경

- HTML 보고서에서 디자인만 먼저 질문합니다. ‘추가 디자인’을 고르면 즉시
  한국어 8가지 목록에서 고르고, 디자인을 확정한 뒤 남은 분량·보기 방식만 묻습니다.
  이미 알려준 ‘상세 / 스크롤’은 유지하며 작은 미리보기는 선택 사항입니다.
- HTML 공통 테마와 수치 대조, 편집 가능한 PPT 구성·표·차트 제작을 개선했습니다.
- 폴더별 Skill 목록과 우선순위 안내, 필요한 Skill 선택을 보완했습니다.
- 업무 단위 학습·완료 확인, 한국어 선택 안내와 불필요한 종료 메시지를 개선했습니다.
- 실제 Python·Claude 실행 위치 탐색과 설치 호환성, 기존 설정 보존을 보완했습니다.
- 상세 사용자 안내서, 단축키 검색 HTML, 채팅 실습 및 검증 안내를 포함합니다.

## 검증 및 한계

- Python 자동 검사 514개 통과, 제외 0개.
- 디자인 선택 화면 상호작용 17개, 단축키 안내 동작 16개 통과.
- 설치 패키지 회귀 검사와 압축파일 무결성 확인 완료.
- 실제 사내 모델의 대화 UI, 회사 Office·Outlook·DRM 통합 검증은 별도로 필요합니다.
  자동 검사 통과가 모든 업무의 성공이나 모든 실패의 자동 복구를 보증하지 않습니다.
- 새 메일 발송/PST 이동 서비스나 이미지 생성 서비스를 자동 설치하지 않습니다.
  보호·권한 제한은 우회하지 않습니다.

ZIP SHA-256:
`7a0ddf992dd5c857948f441536b45bbb2f9e8f54775566c0c84cf49fed4a7fba`

[업데이트 안내](https://github.com/bongG-moon/claude_base_repo/blob/v1.3.9/docs/UPDATE_1.3.9.md)
· [상세 사용자 안내서](https://github.com/bongG-moon/claude_base_repo/blob/v1.3.9/docs/USER_GUIDE.md)
· [검증 범위](https://github.com/bongG-moon/claude_base_repo/blob/v1.3.9/docs/VALIDATION_1.3.9.md)
