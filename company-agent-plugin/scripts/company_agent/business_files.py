"""Preview-first local file organization; bounded, no delete or overwrite tools."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any

from .business_safety import cancelled, confirm_action, failure_result, safe_path
from .paths import atomic_write_json

GROUPS = {"문서": {".pdf", ".doc", ".docx", ".txt", ".md", ".hwp", ".hwpx"},
          "표자료": {".xlsx", ".xls", ".csv", ".tsv"}, "발표자료": {".ppt", ".pptx"},
          "이미지": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}, "압축자료": {".zip", ".7z"}}


def _fingerprint(path: Path) -> dict[str, Any]:
    before = path.stat()
    if before.st_size > 256 * 1024 * 1024:
        raise ValueError("Files larger than 256 MiB are excluded from the first organizer release.")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("File changed while preparing the plan.")
    return {"size": after.st_size, "mtimeNs": after.st_mtime_ns, "sha256": digest.hexdigest()}


def _root(value: Path) -> Path:
    root = safe_path(value, exists=True)
    if not root.is_dir() or root == Path(root.anchor) or root == Path.home():
        raise ValueError("Choose one specific work folder, not a drive or user-profile root.")
    if any(part.casefold() in {".git", ".claude", "windows", "program files", "program files (x86)",
                              "companyagent", "company-agent-plugin"} for part in root.parts):
        raise ValueError("Application, source-control and agent settings folders are excluded.")
    return root


def _job(root: Path, job_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("Invalid plan identifier.")
    return safe_path(safe_path(root) / "business" / "file-plans" / (job_id + ".json"))


def create_plan(state: Path, folder: Path) -> dict[str, Any]:
    root = _root(folder)
    items = sorted(root.iterdir(), key=lambda p: p.name.casefold())
    if len(items) > 500:
        raise ValueError("Choose a smaller folder (at most 500 direct entries). Nothing was moved.")
    operations, skipped = [], []
    for item in items:
        group = next((name for name, endings in GROUPS.items() if item.suffix.lower() in endings), None)
        try:
            source = safe_path(item, exists=True)
            if not source.is_file() or not group:
                continue
            destination = safe_path(root / group / source.name)
            if destination.exists():
                skipped.append({"name": item.name, "code": "destination_exists"})
                continue
            operations.append({"source": source.name, "destination": group + "/" + source.name,
                               "fingerprint": _fingerprint(source)})
        except (OSError, ValueError) as exc:
            skipped.append({"name": item.name, "code": failure_result(exc)["code"]})
    job_id = uuid.uuid4().hex
    plan = {"schemaVersion": 1, "planId": job_id, "root": str(root), "status": "planned",
            "operations": operations, "skipped": skipped, "completed": []}
    atomic_write_json(_job(state, job_id), plan)
    return {"ok": True, **plan, "message": "정리안만 만들었습니다. 파일은 이동하지 않았습니다. 실행 시 별도 확인 창이 표시됩니다."}


def _operation_paths(root: Path, op: dict[str, Any]) -> tuple[Path, Path]:
    source_name, dest_name = str(op["source"]), str(op["destination"])
    if Path(source_name).name != source_name or any(c in source_name for c in ("/", "\\", ":")):
        raise ValueError("Invalid source path in plan.")
    if dest_name not in [group + "/" + source_name for group in GROUPS]:
        raise ValueError("Invalid destination in plan.")
    return safe_path(root / source_name), safe_path(root / dest_name)


@contextmanager
def _plan_lock(state: Path, job_id: str):
    if os.name != "nt":
        raise ValueError("File execution is Windows-only.")
    import msvcrt
    path = _job(state, job_id)
    if not path.is_file():
        raise ValueError("The selected plan does not exist.")
    lock = safe_path(path.with_suffix(".lock"))
    with lock.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ValueError("This plan is already running. Wait for its result before retrying.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def run_plan(state: Path, job_id: str, *, undo: bool = False) -> dict[str, Any]:
    with _plan_lock(state, job_id):
        return _run_plan(state, job_id, undo=undo)


def _run_plan(state: Path, job_id: str, *, undo: bool = False) -> dict[str, Any]:
    path = _job(state, job_id)
    plan = json.loads(path.read_text(encoding="utf-8-sig"))
    if plan.get("planId") != job_id or plan.get("schemaVersion") != 1:
        raise ValueError("Unsupported plan.")
    if not undo and plan.get("status") != "planned":
        raise ValueError("This plan has already run. Inspect its result or request undo; do not rerun it.")
    root = _root(Path(plan["root"]))
    # Reconcile an intent left by interruption between rename and receipt save.
    # This only repairs metadata after verifying exact bytes; it never moves a
    # file without the preview/approval below.
    pending = plan.get("pendingOperation")
    if pending:
        op = pending["operation"]
        old, new = _operation_paths(root, op)
        source, destination = (new, old) if pending.get("undo") else (old, new)
        if not source.exists() and destination.is_file() and _fingerprint(destination) == op["fingerprint"]:
            if pending.get("undo"):
                plan["completed"] = [item for item in plan["completed"] if item != op]
            elif op not in plan["completed"]:
                plan["completed"].append(op)
        elif not (source.is_file() and not destination.exists() and _fingerprint(source) == op["fingerprint"]):
            raise ValueError("Interrupted move has ambiguous file state; inspect the original plan before recovery.")
        plan.pop("pendingOperation", None)
        atomic_write_json(path, plan)
    operations = plan.get("completed", []) if undo else plan.get("operations", [])
    if not isinstance(operations, list) or len(operations) > 500:
        raise ValueError("Invalid operation count.")
    checked = []
    for op in operations:
        source, destination = _operation_paths(root, op)
        if undo:
            source, destination = destination, source
        checked.append((op, source, destination))
    if not checked:
        return {"ok": True, "status": "no_changes", "message": "이동할 파일이 없습니다."}
    title = "파일 정리 되돌리기" if undo else "파일 정리 실행 확인"
    details = title + "\n폴더: " + str(root) + "\n삭제·덮어쓰기는 하지 않습니다.\n\n" + "\n".join(
        str(source.relative_to(root)) + "  →  " + str(destination.relative_to(root)) for _, source, destination in checked)
    if not confirm_action(title, details):
        return cancelled()
    # Reject a plan swapped while the user was reading its preview.
    if json.loads(path.read_text(encoding="utf-8-sig")) != plan:
        raise ValueError("The plan changed. Prepare a new preview.")
    if os.name != "nt":
        raise ValueError("File execution is Windows-only to preserve no-overwrite rename semantics.")
    done, failures = [], []
    plan["status"] = "undo_running" if undo else "running"
    atomic_write_json(path, plan)
    for op, source, destination in checked:
        try:
            safe_path(source, exists=True)
            safe_path(destination)
            if destination.exists():
                raise ValueError("Destination exists. No overwrite allowed.")
            if _fingerprint(source) != op["fingerprint"]:
                raise ValueError("The file changed. Prepare a new preview.")
            destination.parent.mkdir(exist_ok=True)
            safe_path(source, exists=True)
            safe_path(destination)
            plan["pendingOperation"] = {"operation": op, "undo": undo}
            atomic_write_json(path, plan)
            # Same root/local volume only. Windows rename never replaces a file.
            source.rename(destination)
            done.append(op)
            if undo:
                plan["completed"] = [old for old in plan["completed"] if old != op]
            else:
                plan["completed"].append(op)
            plan.pop("pendingOperation", None)
            atomic_write_json(path, plan)
        except (OSError, ValueError) as exc:
            failures.append({"name": source.name, **failure_result(exc)})
            if plan.get("pendingOperation"):
                # Preserve intent and stop on an uncertain move; a later undo
                # reconciles it. Never overwrite the pending journal with the
                # next operation after a filesystem/receipt error.
                break
    plan["status"] = "partial" if failures else "undone" if undo else "completed"
    plan["failures"] = failures
    atomic_write_json(path, plan)
    return {"ok": not failures, "status": plan["status"], "planId": job_id,
            "changedCount": len(done), "failures": failures,
            "message": f"{len(done)}개 파일을 처리했습니다. {len(failures)}개는 처리하지 못했습니다. 삭제·덮어쓰기는 하지 않았습니다."}
