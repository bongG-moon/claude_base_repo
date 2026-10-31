"""선택한 폴더를 계획대로 정리합니다. 하위 탐색/삭제/덮어쓰기는 없습니다."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

CATEGORIES = {
    "문서": {".pdf", ".doc", ".docx", ".txt", ".md", ".hwp", ".hwpx"},
    "표자료": {".csv", ".tsv", ".xls", ".xlsx", ".xlsm"},
    "발표자료": {".ppt", ".pptx", ".pptm"},
    "이미지": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"},
    "압축자료": {".zip", ".7z", ".tar", ".gz"},
}
MAX_SIZE = 256 * 1024 * 1024


class DestinationParentConflict(ValueError):
    pass


def checked(path: Path, *, directory=False) -> Path:
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")) or ".." in path.parts:
        raise ValueError("실제 로컬 절대경로를 지정하세요.")
    for part in (path, *path.parents):
        if os.path.lexists(part) and (part.is_symlink() or getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("연결된 파일·폴더는 정리하지 않습니다.")
    if directory and not path.is_dir():
        raise ValueError("대상 폴더가 없습니다.")
    return path


def check_destination(target: Path) -> None:
    checked(target.parent)
    if os.path.lexists(target.parent) and not target.parent.is_dir():
        raise DestinationParentConflict(f"목적지 부모 경로가 폴더가 아닙니다: {target.parent.name}")
    checked(target)
    if os.path.lexists(target):
        raise ValueError("목적지에 같은 이름이 있습니다.")


def fingerprint(path: Path) -> dict:
    checked(path)
    if not path.is_file() or path.stat().st_size > MAX_SIZE:
        raise ValueError("파일이 없거나 256 MiB보다 큽니다.")
    before = path.stat()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("파일이 확인 중 변경되었습니다.")
    return {"size": after.st_size, "sha256": digest}


def save_new(path: Path, data: dict) -> None:
    checked(path)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def load(path: Path) -> dict:
    checked(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError("정리 기록이 너무 큽니다.")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("지원하지 않는 정리 기록입니다.")
    return value


def plan(folder: Path) -> dict:
    checked(folder, directory=True)
    # 상한을 넘기면 일부 파일만 정리한 사실을 놓치지 않도록 계획을 중단합니다.
    entries = []
    for child in folder.iterdir():
        entries.append(child)
        if len(entries) > 500:
            raise ValueError("폴더 항목이 500개를 초과합니다. 범위를 나누어 지정하세요.")
    moves, skipped, blocked = [], [], []
    for path in sorted(entries, key=lambda p: p.name.casefold()):
        category = next((name for name, exts in CATEGORIES.items() if path.suffix.lower() in exts), None)
        try:
            checked(path)
            if not path.is_file() or not category:
                skipped.append({"name": path.name, "reason": "하위 폴더 또는 분류 대상 아님"})
                continue
            target = folder / category / path.name
            check_destination(target)
            moves.append({"name": path.name, "category": category, **fingerprint(path)})
        except (OSError, ValueError) as exc:
            issue = {"name": path.name, "reason": str(exc)}
            skipped.append(issue)
            if isinstance(exc, DestinationParentConflict):
                blocked.append(issue)
    return {"version": 1, "kind": "plan", "folder": str(folder), "moves": moves,
            "skipped": skipped, "blocked": blocked}


def validate_moves(data: dict) -> tuple[Path, list]:
    folder = checked(Path(data["folder"]), directory=True)
    moves = data["moves"]
    if not isinstance(moves, list) or len(moves) > 500:
        raise ValueError("이동 항목 수가 올바르지 않습니다.")
    names = set()
    for row in moves:
        name, category = row.get("name"), row.get("category")
        if not isinstance(name, str) or not name or any(c in name for c in '/\\:') or name in (".", ".."):
            raise ValueError("기록에 잘못된 파일 이름이 있습니다.")
        if category not in CATEGORIES or Path(name).suffix.lower() not in CATEGORIES[category]:
            raise ValueError("기록의 분류가 파일과 일치하지 않습니다.")
        if name.casefold() in names or not isinstance(row.get("sha256"), str) or len(row["sha256"]) != 64:
            raise ValueError("기록에 중복 또는 잘못된 파일 정보가 있습니다.")
        names.add(name.casefold())
    return folder, moves


def move_one(source: Path, target: Path, expected: dict) -> None:
    checked(source)
    check_destination(target)
    if fingerprint(source) != {"size": expected["size"], "sha256": expected["sha256"]}:
        raise ValueError("계획 후 파일이 변경되었습니다.")
    target.parent.mkdir(exist_ok=True)
    checked(target.parent, directory=True)
    # Windows rename은 기존 목적지가 있으면 실패합니다. 다른 OS는 link로 덮어쓰기를 막습니다.
    if os.name == "nt":
        os.rename(source, target)
        return
    os.link(source, target, follow_symlinks=False)
    try:
        source.unlink()
    except OSError:
        target.unlink()
        raise


def execute(data: dict, output: Path, *, undo=False) -> dict:
    expected_kind = "receipt" if undo else "plan"
    if data.get("kind") != expected_kind:
        raise ValueError("요청에 맞는 계획/이동기록 파일이 아닙니다.")
    folder, moves = validate_moves(data)
    if undo:
        moves = list(reversed(moves))
    blocked = [] if undo else data.get("blocked", [])
    if not isinstance(blocked, list) or any(not isinstance(row, dict) for row in blocked):
        raise ValueError("계획의 차단 항목이 올바르지 않습니다.")
    # 이동보다 먼저 독점적으로 기록 파일을 확보합니다. 기존 기록은 덮어쓰지 않습니다.
    result = {"version": 1, "kind": "undo" if undo else "receipt", "folder": str(folder),
              "moves": [], "failures": [], "phase": "preflight", "plannedCount": len(moves) + len(blocked)}
    checked(output)
    with output.open("x", encoding="utf-8", newline="\n") as log:
        def flush():
            recorded = {row.get("name") for row in result["moves"] + result["failures"]}
            result["notAttemptedCount"] = result["plannedCount"] - len(recorded)
            log.seek(0)
            json.dump(result, log, ensure_ascii=False, indent=2)
            log.truncate()
            log.flush()
            os.fsync(log.fileno())
        flush()
        # 차단 항목을 조용히 제외한 부분 실행은 하지 않습니다. 수정한 새 계획이 필요합니다.
        result["failures"].extend(blocked)
        for row in moves:
            target = folder / row["name"] if undo else folder / row["category"] / row["name"]
            try:
                check_destination(target)
            except (OSError, ValueError) as exc:
                result["failures"].append({"name": row["name"], "reason": str(exc)})
        if result["failures"]:
            flush()
            return result
        result["phase"] = "execution"
        for row in moves:
            source, target = folder / row["name"], folder / row["category"] / row["name"]
            if undo:
                source, target = target, source
            try:
                move_one(source, target, row)
                result["moves"].append(row)
                flush()
            except (OSError, ValueError) as exc:
                result["failures"].append({"name": row["name"], "reason": str(exc)})
                flush()
                break
        flush()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan"); p.add_argument("--folder", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("apply"); p.add_argument("--plan", type=Path, required=True); p.add_argument("--receipt", type=Path, required=True)
    p = sub.add_parser("undo"); p.add_argument("--receipt", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            result = plan(args.folder); save_new(args.output, result)
        elif args.command == "apply":
            result = execute(load(args.plan), args.receipt)
        else:
            result = execute(load(args.receipt), args.output, undo=True)
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result.get("failures") else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
