"""한 개의 새 native 스킬 원본을 생성합니다. 설정/후크/연결은 바꾸지 않습니다."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re


def reject_links(path: Path) -> None:
    for item in (path, *path.parents):
        if os.path.lexists(item) and (item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("연결된 경로 대신 실제 폴더를 지정하세요.")


def create(destination: Path, name: str, description: str, body: Path) -> dict:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise ValueError("이름은 64자 이내 영문 소문자·숫자·하이픈입니다.")
    if not description.strip() or len(description) > 1000 or "\n" in description:
        raise ValueError("설명은 한 줄로 1~1000자입니다.")
    if not destination.is_absolute() or not destination.parent.is_dir():
        raise ValueError("기존 부모 폴더 아래 새 스킬 폴더의 절대경로를 지정하세요.")
    reject_links(destination)
    if os.path.lexists(destination):
        raise FileExistsError("같은 폴더가 있습니다. 기존 원본을 확인하고 그 파일을 수정하세요.")
    if body.stat().st_size > 128_000:
        raise ValueError("본문이 너무 큽니다. 필요한 참고자료로 나누세요.")
    text = body.read_text(encoding="utf-8-sig").strip()
    if not text or text.startswith("---"):
        raise ValueError("body에는 frontmatter를 제외한 본문만 넣으세요.")
    content = f"---\nname: {name}\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n\n{text}\n"
    destination.mkdir()
    with (destination / "SKILL.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    return {"status": "created", "path": str(destination / "SKILL.md"), "registeredInSession": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--body", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = create(args.destination, args.name, args.description, args.body)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
