# 기존 기억의 이전 내용 복원

“방금 수정 전으로 돌려줘”처럼 **내용 복원 요청이 있을 때만** 사용합니다. 일반 저장과 조회는 이 절차가 필요하지 않습니다.

1. 같은 기억 ID와 원래 `storageScope`를 유지합니다. 현재 문맥의 수정 영수증을 재사용하되 모호한 대상이나 이후 수정이 있으면 복원할 차이만 확인합니다.
2. 정확한 cliCommand 접두부로 `company-agent memory history --id "<id>" --state-root "<stateRoot>" --storage-scope personal --project-root "<project>"`를 실행합니다. 프로젝트 기억이면 personal을 project로 바꿉니다. 여기서 실제 보존된 이전 revision과 현재 revision/sha256를 확인합니다.
3. `company-agent memory restore --id "<id>" --revision <target> --expected-revision <current> --expected-sha256 "<current hash>" --state-root "<stateRoot>" --storage-scope personal --project-root "<project>"`로 조건부 복원합니다. 최신 내용을 몰래 덮어쓰기 위해 새 해시를 채택하거나 조건을 빼지 않습니다.
4. 이전 내용으로 새 revision이 만들어지며 이후 이력은 삭제되지 않습니다. `persisted-content-verified` 영수증이면 별도 재조회/검증 호출 없이 실제 결과를 알립니다. snapshot이 없거나 무결성 기록이 맞지 않으면 복원됐다고 하지 않습니다. 오래된 백업의 무결성 기록을 새로 만들어 넣지 않습니다. 사용자가 내용을 검토한 뒤 별도 수정 요청을 할 수는 있습니다.

`learning rollback`은 자동 선호 적용을 중지하거나 엔진 소유 스킬 체크리스트를 돌리는 기능입니다. 기억의 이전 본문을 복원하지 않습니다. 자동 학습 이력의 beforeContent도 memory history의 복원 가능한 revision으로 간주하지 않습니다. 로컬 해시는 진위 서명이 아닙니다.
