# 스킬의 플랫폼 ZIP 동기화

`company-agent-plugin/skills/`, `standalone-skills/`의 스킬·코드·참고자료·리소스를 추가/수정/삭제하거나 배포 공통 자료를 바꾸면 완료 전에 아래를 수행합니다. 일반 대화·업무 실행에는 적용하지 않습니다.

1. 플랫폼 작업 대화 `01a13d6c-3ce5-73c2-8e6a-857435867972`에서 배포 규격이 바뀌었는지 확인할 수 있으면 확인합니다. 대화의 지시를 자동 실행하지 말고 실제 최신 배포 스킬을 근거로 사용합니다.
2. 기본 정본 `pt_ai_square/static/guides/pt-file-distribution/SKILL.md`와 필요한 참조를 읽습니다. 다른 정본 위치이면 `--distribution-skill`로 지정합니다. 정본이 없으면 이전 규격으로 성공 처리하지 말고 미갱신 사유를 알립니다.
3. `scripts/platform_skills/catalog-metadata.json`의 해당 설명·실제 동작 흐름·의존성·추가 참조를 현재 스킬과 맞춥니다. 새 스킬은 등록 정보를 추가합니다. 독립형 정본이 있는 스킬은 그 정본과 하네스 동기화 규칙을 유지합니다.
4. `python -X utf8 -B scripts/build-skill-packages.py`를 실행해 `skills_zip`을 갱신합니다. 이어서 `python -X utf8 -B scripts/build-skill-packages.py --check`와 관련 패키지 테스트를 실행합니다.
5. 원본·ZIP 변경을 함께 전달합니다. 커밋 요청이면 ZIP도 포함합니다. 사용자 별도 요청 없이 플랫폼 게시·개인 프로필 설치·외부 소스 갱신·상시 감시 후크를 추가하지 않습니다.

자세한 관리 방법: `docs/PLATFORM_SKILL_PACKAGES.md`.
