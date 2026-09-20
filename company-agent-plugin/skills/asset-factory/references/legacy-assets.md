# 기존 개인 자산 유지보수

기존 Script Tool/일반 stdio MCP를 수정하거나 해당 형식을 명시 요청했을 때만 읽습니다. 새 재사용 업무 도구의 기본은 `platform-tools.md`입니다. 기존 자산을 자동 변환하거나 저장소를 옮기지 않습니다.

- Script Tool AssetSpec: `type: "script-tool"`, `name`, `description`, `code`, `input_schema`, `output_schema`, `reviewed_capabilities`. `asset create`와 `asset validate` 후 합성 JSON 입력으로 `asset test-tool --name "<이름>" --input "<JSON>" --timeout 30`을 실행합니다. 연결 요청이 있으면 정확한 반환 영수증으로 `asset activate-tool --name "<이름>" --receipt "<영수증>"`를 실행합니다. 생성되는 스킬 wrapper가 `asset run-tool`을 호출합니다.
- 기존 stdio MCP AssetSpec: `type: "mcp"`, `server_code`, 기존 나머지 필드. `format`은 생략합니다. 승인된 `mcp>=1.20,<2`에서 `asset test-mcp`의 initialize/list/health를 확인합니다. 이 결과만으로 모든 업무 함수가 검증되었다고 하지 않습니다. 업무 사례도 실제 시험합니다. 사용 요청이 있으면 `asset activate-mcp`로 영수증 기반 활성화, 네이티브 등록 후 Claude 재시작을 안내합니다.
- 소스·설정이 바뀌면 기존 영수증으로 활성화하지 않습니다. 승인된 Python 경로만 바뀐 경우에는 `asset rebind-mcp-runtime` 검증 후 다시 활성화합니다. 누락 의존성을 인터넷에서 자동 설치하지 않습니다.
- 스킬 생성이나 wrapper 활성화 전후에 같은 프로젝트로 `skill resolve`하여 충돌을 확인합니다. 우선 선택 저장은 사용자가 선택한 후보 ID와 범위로만 `skill prefer`를 사용합니다. 프로젝트 전용 후보를 개인 전체 기본값으로 저장하지 않습니다. 기존 이름을 임의로 덮어쓰거나 바꾸지 않습니다.
- create/test/activate/sync/run은 통합 스킬에서 선택한 `--storage-scope`와 `--project-root`를 동일하게 사용합니다. 회사 원본·타인의 설정·다른 플러그인·기존 우선순위는 보존합니다. 생성 성공, 시험 성공, 연결 성공은 구분해서 알립니다.
