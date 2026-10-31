"""이 스킬의 독립 조회 실행 진입점입니다."""
from pathlib import Path
import sys

# 현재 배포본의 실행 코드만 찾습니다. 다른 스킬이나 하네스 설치 위치를 탐색하지 않습니다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from query_core.cli import main

if __name__ == "__main__":
    raise SystemExit(main('demo'))
