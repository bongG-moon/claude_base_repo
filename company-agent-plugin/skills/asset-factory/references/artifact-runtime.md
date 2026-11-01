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
