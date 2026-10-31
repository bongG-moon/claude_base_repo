---
name: personal-memory
description: 지속적인 개인 선호와 업무 맥락을 저장, 조회하거나 수정합니다. 업무 정의는 personal-knowledge, 재사용 절차는 asset-factory와 구분하며 일회성 지시는 저장하지 않습니다.
---

# 개인 기억

요청한 조회 또는 저장만 진행합니다. 회사 공통, 개인 전체, 이 프로젝트와 Claude 자체 기억은 서로 다른 범위이며 기존 자료를 합치거나 이동하지 않습니다.

## 먼저 작업 구분

| 요청 | 처리 |
| --- | --- |
| 저장된 기억 조회 | 관련 항목만 검색. 저장 범위 질문 없음 |
| 새 기억을 명시적으로 저장 | 지정한 범위 사용. 없을 때만 **개인 전체 / 이 프로젝트**를 한 번 질문 |
| 기존 기억 수정 | 같은 ID와 `storageScope`에서 조건부 수정. 범위를 다시 묻거나 복제하지 않음 |
| 현재 자동 학습 범위 안의 새 지속적 교정 | self-learning의 `learning submit` 한 번. 별도 저장 질문 없음 |
| 새 프로젝트 전용 사실 | 이 프로젝트 기억으로 저장. 개인 전체 자동 학습에 넣지 않음 |
| 이번만/불명확한 지시, 인용 속 요청 | 현재 작업에만 적용하고 저장하지 않음 |

“개인 기억”만으로 개인 전체를 뜻한다고 가정하지 않습니다. 업무 용어, 지표와 연결 규칙은 personal-knowledge, 반복 실행 절차는 asset-factory를 사용합니다. 학습 보류를 피해 같은 후보를 기억에 직접 저장하지 않습니다.

## 조회

예문의 `company-agent`는 정확한 `company_agent_runtime.cliCommand`로 대체합니다. 주입된 `stateRoot`와 `project`를 사용하며 환경변수, 설정이나 세션 폴더에서 재탐색하지 않습니다. 현재 문맥에 있는 최신 결과는 재사용합니다.

`company-agent memory search "<query>" --state-root "<stateRoot>" --project-root "<project>" --limit 5`

범위 없는 조회는 현재 프로젝트와 개인 전체를 찾습니다. `storageScope`가 실제 적용 범위이며 구형 `scope: personal`은 소유 유형입니다. 기억은 참고 자료이므로 현재 요청, 회사 정책과 도구 권한을 덮어쓰지 않습니다. 런타임 정보가 없으면 관리 저장/조회를 보류하고 가능한 현재 업무는 계속합니다.

## 새 저장 또는 수정

1. 해당 사실을 검색해 중복을 확인합니다. 기존 항목이면 정확한 `id`, `storageScope`, `revision`, `sha256`를 유지합니다. 여러 항목이 실제로 충돌할 때만 바꿀 대상을 확인합니다.
2. Write로 `<stateRoot>/tmp/memory-<unique-id>.json`에 작은 명세를 만듭니다. 필드는 `kind`, 수정 시 `id`, `title`, `body`, `reason`, `source`만 사용합니다. kind는 `preference`, `work_context`, `convention` 중 하나입니다. title/body에는 짧게 추출한 사실, reason에는 분류 이유만 적습니다. 원문 대화, 메일, 도구 입력/출력, 인증 값과 민감 행은 넣지 않습니다. 셸 인라인 JSON이나 redirection을 사용하지 않습니다.
3. `company-agent memory upsert --spec "<spec.json>" --state-root "<stateRoot>" --storage-scope personal --project-root "<project>"`를 실행합니다. 이 프로젝트 저장이면 `personal`만 `project`로 바꿉니다. **기존 항목 수정**에는 확인한 `--expected-revision <revision> --expected-sha256 <sha256>`도 붙입니다. 충돌 시 최신 내용을 보존하며 조건을 제거해 강제 저장하지 않습니다.
4. `verification.status=persisted-content-verified` 응답이면 해당 내용은 확인된 것입니다. 추가 Markdown 재조회나 session verify 없이 실제 `scopeLabel`과 저장한 내용을 짧게 알립니다. `changed:false`는 이미 같은 내용이라는 뜻입니다. 이 영수증은 다른 미완료 결과물을 검증하지 않습니다.

검색 거절은 저장 거절이 아니며 실제로 시도한 단계만 설명합니다. 저장 거절은 미저장으로 알리고 같은 호출을 반복하거나 원본 기억 파일을 직접 고쳐 우회하지 않습니다. `needs_scope_choice`는 아직 저장하지 않은 선택 대기입니다.

최종 응답은 사용자가 정한 길이 안에서 저장 항목, 범위와 실제 적용 상태를 요약합니다. 이번 답변의 길이 제한은 장기 기억에 저장하지 않습니다.

## 추가 요청이 있을 때

- 이전 내용으로 복원: `references/revision-restore.md`를 읽습니다. `memory history --id`와 `memory restore --id`는 같은 범위의 버전 복원이며 자동 학습 `learning rollback`과 다릅니다.
- 학습/조회 이력 설명: 알려진 세션 ID가 있으면 `learning status --explain`에 사용합니다. 없는 ID를 찾지 않습니다. 모델에 전달됨과 실제 적용됨은 구분합니다.
- 기억 정리: 요청한 경우 `memory compact`로 파생 인덱스만 정리합니다. 원본 Markdown 삭제나 모델 요약이 아닙니다. 서로 다른 사실을 임의로 합치지 않습니다.

기억은 선택된 저장소의 `memory`에 남아 하네스 업데이트 후에도 유지됩니다. User 설치의 프로젝트 자료는 `project-scopes/<folder-hash>`로 분리됩니다. 현재 프로젝트 외 자료나 Claude 자체 기억을 자동 병합하지 않습니다. UserPromptSubmit은 활성 기억을 제한적으로 찾아 전달하며, 이번에 전달되지 않았다는 이유로 기억이 삭제됐다고 판단하지 않습니다.
