# 스킬을 만들거나 실제 원본을 수정하기

현재 요청의 입력, 결과, 저장 범위를 재사용합니다. 스킬 하나에 주된 역할과 구분되는
사용 조건을 둡니다. 기본 순서는 짧게, 분기 설명은 필요할 때 읽는 참조로 작성합니다.
회사 지식, 전체 대화, 이 안내서를 생성 스킬에 그대로 넣지 않습니다.

아래 명령은 모두 제공된 `cliCommand` 문자열 뒤에 붙입니다. `<stateRoot>`와
`<프로젝트>`는 실제 값이며 사용자에게 내부 경로를 찾아오게 하지 않습니다.

## 새 스킬

이름 충돌을 확인한 뒤 UTF-8 AssetSpec을 만듭니다. 최소 형식:

```json
{
  "type": "skill",
  "name": "weekly-summary",
  "description": "주간 업무 자료로 요약 보고서를 만들 때 사용합니다.",
  "instructions": "# 주간 업무 요약\n사용자가 지정한 자료만 읽고 출처와 미확인 범위를 표시합니다."
}
```

```text
asset create --spec "<명세.json>" --state-root "<stateRoot>" --storage-scope personal --project-root "<프로젝트>"
asset validate "<생성 결과의 path 폴더>"
```

`personal`은 예시입니다. 이미 고른 범위가 프로젝트이면 `project`를 사용합니다.
`asset validate`는 생성 결과의 `path` 폴더를 받습니다. `effectivePath`는 읽거나
수정할 `SKILL.md` 파일이므로 검증 인자로 쓰지 않습니다. 저장 범위나 state-root
인자도 붙이지 않습니다. 새 스킬을 사용하는 데 MCP 활성화는 필요하지 않습니다.

추가 참조가 필요한 경우 AssetSpec `references`는 **문자열 배열**입니다. 생성 경로는
`references/reference-1.md`, `reference-2.md`입니다. 이 실제 이름을 링크하며 임의
이름이나 객체 필드를 만들지 않습니다. references를 생략하면 기존 파일을 보존합니다.
명시 목록의 삭제 대상도 관리 소유권과 변경 없는 해시가 확인된 파일만 정리됩니다.
사용자 수정 파일이나 관리 밖 파일은 보존하고 알립니다.

## 기존 스킬

```text
asset inspect --name "<이름>" --state-root "<stateRoot>" --project-root "<프로젝트>"
```

`effectivePath`를 직접 읽어 수정합니다. `bodyIncluded: false`인 메타데이터 조회는
본문 로드가 아닙니다. 범위를 생략하면 현재 프로젝트와 개인 중 기존 한 원본을
유지하며 동명 충돌이 있을 때만 선택받습니다.

수정한 **frontmatter 없는 본문**을 UTF-8 파일에 준비합니다.

```text
asset update --name "<이름>" --instructions-file "<본문.md>" --expected-sha256 "<조회 해시>" --state-root "<stateRoot>" --project-root "<프로젝트>"
```

기존 이름, 범위, 추가 frontmatter, 참조, 도구 연결은 보존합니다. 설명을 바꿀 때만
`--description`을 추가합니다. inspect 범위 밖의 조상 프로젝트나 외부 스킬은
카탈로그의 정확한 원본을 사용하며 새 사본으로 대체하지 않습니다.
`status: partial`이면 변경 파일과 backupPath를 알리고 비교한 뒤 복구하거나 재시도합니다.
작성용 AssetSpec이나 사본은 자동 동기화 원본이 아닙니다.

## 필요한 확인만

상대 참조와 실제 명령 형식, 누락 입력과 후속 수정 흐름을 확인합니다. 순수 문서형
스킬에 실행 도구 시험이나 새 Stop 후크를 붙이지 않습니다. 실행 코드가 있다면 합성
정상/오류 사례로 시험하고 실제 실행과 정적 검사를 구분합니다. 비밀값은 문서와 로그에
넣지 않습니다. 프로젝트 하네스의 에이전트는 생성기가 관리하며 필드를 임의로 만들지 않습니다.

새 스킬은 native 위치에 하나의 원본으로 저장되고 `/<이름>`으로 사용합니다. 현재 목록에
없으면 `/reload-skills` 또는 새 대화에서 확인합니다. `user-invocable` 등 기존 조건과
private 스킬의 호출 방식은 유지하며 파일 검증만으로 실제 호출 성공을 주장하지 않습니다.

## 파일을 생성하는 실행 코드일 때만

업무 루트를 입력 또는 실행 파일 위치에서 절대경로로 확정하고 존재하는 폴더인지 확인합니다. `cd` 실패 뒤 명령을 이어 쓰지 않습니다. 하위 프로세스에는 `cwd=work_root`를 지정하고, 입력 자료 폴더를 작업 폴더처럼 사용하지 않습니다.

```python
from pathlib import Path
from tempfile import TemporaryDirectory
# 입력 업무 폴더를 먼저 확인하고, 임시 결과도 그 안에서만 만듭니다.
work_root = Path(work_folder).resolve(strict=True)
if not work_root.is_dir():
    raise NotADirectoryError('업무 폴더를 확인해 주세요.')
staging = work_root / '.build'
staging.mkdir(exist_ok=True)
with TemporaryDirectory(dir=staging, prefix='run-') as stage:
    # 입력 검증 → 임시 결과 작성 → 완성 검사 후 게시 순서로 구현합니다.
    # 실패하면 이전 정상 결과를 지우지 않습니다.
    pass
```

읽기 전용 자료를 import할 때는 `python -B` 또는 import 전 `sys.dont_write_bytecode = True`로 입력 폴더의 `__pycache__` 생성을 막습니다. 재생성 코드는 정상본을 먼저 삭제하지 말고 같은 실행의 결과/명세/근거를 함께 게시하며 실패 시 복원합니다. 새 실행과 실패 주입 검사는 이 재생성기를 만드는 때만 수행합니다. 오류 테스트는 단순한 예외 발생이 아닌 오류 코드와 실패 원인, 기존 결과 보존까지 확인합니다.
