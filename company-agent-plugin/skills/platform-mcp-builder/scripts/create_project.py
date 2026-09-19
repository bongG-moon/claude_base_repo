"""Create a portable tools.py starter; never install, register or overwrite."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "template"
FILES = (
    "src/__init__.py", "src/mcp/__init__.py", "src/mcp/tools.py",
    "config.py", "local_server.py", "test_tools.py", "requirements-local.txt",
)


def create_project(destination: Path) -> dict:
    if not destination.is_absolute():
        raise ValueError("개발 폴더의 절대 경로를 지정하세요.")
    if os.path.lexists(destination):
        raise FileExistsError("기존 폴더/파일은 덮어쓰지 않습니다. 새 개발 폴더를 지정하세요.")
    # Resolve the existing parent once; never create an inferred directory tree.
    parent = destination.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("개발 폴더의 부모 경로가 폴더가 아닙니다.")
    target = parent / destination.name
    contents = {name: (TEMPLATE / name).read_bytes() for name in FILES}
    target.mkdir(exist_ok=False)
    for name, content in contents.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
    return {"status": "created", "directory": str(target),
            "portableTools": str(target / "src/mcp/tools.py"),
            "registered": False, "platformVerified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = create_project(args.destination)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc),
                          "checkDestination": str(args.destination)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
