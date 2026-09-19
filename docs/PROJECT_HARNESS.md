# 프로젝트 하네스 만들기

생성기 v3는 회사 기준과 개인 작업의 경계를 계약에 포함합니다. 부서 기준은 회사 관리 영역에 속하고 프로젝트는 적용 범위입니다. 별도 팀팩이나 세 번째 정책 계층을 만들지 않습니다. v1/v2 소유권 검증과 기존 백업·충돌 처리는 유지하며, 요청 없이 자동 업데이트하지 않습니다. 목표·입력·출력 중 빠진 정보만 먼저 확인합니다.

Company Agent를 설치한 사용자가 프로젝트 폴더에서 다음처럼 요청하면 됩니다.

> 이 프로젝트의 문서와 구조를 확인하고, 내가 매주 보고서를 만드는 일을 도와주는 하네스를 구성해줘. 필요한 정보가 없으면 쉬운 질문으로 물어봐줘.

`company-agent:project-harness` Skill이 프로젝트를 확인하고 목적, 작업 단계, 검증 기준을 구성합니다. 사용자는 JSON이나 모델 이름을 직접 입력할 필요가 없습니다. 대상 폴더나 결과물처럼 꼭 필요한 정보만 선택 또는 짧은 입력으로 묻습니다. 설치 범위 선택과 별개로, 이 Factory가 만드는 작업용 하네스는 선택한 프로젝트에 저장됩니다.

```text
프로젝트/
└─ .claude/
   ├─ agents/company-project-<이름>-*.md
   ├─ skills/company-project-<이름>/SKILL.md
   ├─ skills/company-project-<이름>-<단계>-task/SKILL.md
   ├─ rules/company-agent-project-harness.md
   └─ company-agent/
      ├─ project-harness.manifest.json
      └─ backups/project-harness/<실행별 ID>/
```

기존 프로젝트 `CLAUDE.md`, `.claude/settings*.json`, MCP 설정은 수정하지 않습니다. 새 규칙 파일이 프로젝트 하네스의 위치를 알려줍니다. 일반 Claude Code에서 프로젝트를 다시 열어도 생성된 Markdown Skill과 Agent를 사용할 수 있습니다. Company Agent로 실행하면 기존 개인 Memory와 Corporate Knowledge도 작업에서 활용하도록 안내합니다.

단순 정리는 SMALL, 일반 생산 작업은 MEDIUM, 복잡한 설계·원인 분석은 LARGE를 배정합니다. 이미 사내 모델에 연결된 `haiku`, `sonnet`, `opus` 별칭을 사용합니다. 메인 대화가 작업 결과를 모으고 독립 검증을 호출하며, 실패 시 기준을 넘긴 담당 작업만 최대 0–3회 수정합니다. 총 Agent 호출도 24회로 제한하도록 생성된 지침에 명시합니다.

개발자용 명령은 다음과 같습니다. 실제 프로젝트에 존재하는 경로를 사용해야 합니다.

```powershell
company-agent harness inspect --project "C:\Work\MyProject"
company-agent harness plan --project "C:\Work\MyProject" --spec "C:\Work\harness-spec.json"
company-agent harness apply --project "C:\Work\MyProject" --spec "C:\Work\harness-spec.json"
company-agent harness validate --project "C:\Work\MyProject"
```

`inspect`는 문서·프로젝트 설정·기존 Skill 목록을 제한된 범위에서 조회합니다. 파일 속 명령을 실행하지 않습니다. `plan`은 파일 내용과 충돌을 반환하며 프로젝트를 변경하지 않습니다. `apply`는 이전 manifest의 생성 파일과 해시를 비교하고 원래 소유한 파일만 변경합니다. 사용자가 직접 편집한 파일은 기본 보존됩니다. 재생성을 명확하게 선택한 경우에만 `conflictStrategy: replace-owned`로 백업 후 갱신합니다. 소유하지 않은 기존 파일은 이 옵션으로도 덮어쓸 수 없습니다. 변경 중 실패하면 쓰기를 완료한 파일들을 원복합니다.

`validate`는 생성 결과, 해시, 참조 경로를 확인하는 구조 검사입니다. 실제 LLM의 지침 준수, 내부 모델 선택, MCP 호출, 업무 품질은 프로젝트의 대표 작업으로 별도 실행해 확인해야 합니다. 이 기능은 Markdown 기반 설계 생성기이며 독립 프로세스 감시기나 OS 샌드박스가 아닙니다. DB SELECT 제한과 Outlook 본인 계정 제한은 사내에서 개발한 MCP가 집행해야 합니다.

## 참고한 공개 사례와 적용 범위

[revfactory/harness](https://github.com/revfactory/harness/tree/cceac68ea1d0ad198ef4b7b906cd238375836387)는 프로젝트 요구사항에서 전문 Agent와 Skill을 생성하는 메타 Skill입니다. 이 구현은 해당 프로젝트의 여섯 협업 패턴, 생성 후 점검, 사용자 피드백 반영 아이디어를 참고해 별도 작성했습니다. 원격 코드를 설치하거나 런타임에 의존하지 않으며, upstream 템플릿을 복사하지 않았습니다. 확인한 버전의 라이선스는 [Apache-2.0](https://github.com/revfactory/harness/blob/cceac68ea1d0ad198ef4b7b906cd238375836387/LICENSE)입니다.

참고한 [설계 패턴](https://github.com/revfactory/harness/blob/cceac68ea1d0ad198ef4b7b906cd238375836387/skills/harness/references/agent-design-patterns.md)은 pipeline, fan-out/fan-in, expert pool, producer-reviewer, supervisor, hierarchical delegation입니다. 사내 구현은 안정된 일반 subagent 방식을 기본으로 하고 모델을 난도별로 배정합니다. 계층형도 메인 대화가 두 단계 분해 결과를 받아 말단 작업을 직접 호출하므로 중첩 subagent 기능이 필요하지 않습니다.

[QA 가이드](https://github.com/revfactory/harness/blob/cceac68ea1d0ad198ef4b7b906cd238375836387/skills/harness/references/qa-agent-guide.md)에서 강조하는 연결 지점 점검을 생성 지침에 반영했습니다. 예를 들어 생산자가 반환한 필드와 소비자가 기대하는 필드를 함께 확인하도록 합니다. 공개 저장소가 제시하는 성능 향상 수치는 이 사내 구현의 측정 결과로 사용하지 않습니다.

향후 generatorVersion 변경 시 기존 manifest의 명시적 마이그레이션이 필요합니다. 현재 버전은 알 수 없는 manifest 또는 다른 생성 규칙의 해시를 임의로 신뢰하지 않고 중단합니다. 비정상 종료로 lock 파일이 남으면 다른 설치 작업이 실행 중이지 않은지 확인한 뒤 해당 `project-harness.lock` 하나만 제거하여 재시도합니다. 프로세스 강제 종료·전원 장애의 자동 복구는 제공하지 않으며, 실패 직전 백업 경로에서 복구할 수 있습니다.
