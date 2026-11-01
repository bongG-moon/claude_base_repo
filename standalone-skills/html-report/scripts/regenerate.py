"""Opt-in regeneration: publish a complete run through one stable HTML entry.

Only trusted, task-owned build functions belong here. This is not a runner for
commands embedded in source documents. The ordinary report.py stays unchanged.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

FORMAT = "html-report-generation-v1"
STATE = ".html-report-current.json"
ENTRY_FORMAT = "html-report-generation-v2"
ENTRY = "report.html"
ATTEMPT = ".html-report-attempt.json"
ATTEMPT_FORMAT = "html-report-attempt-v1"


def _plain(path):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        if os.path.lexists(item):
            stat = item.lstat()
            if item.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise ValueError("재생성 경로에 링크 또는 재분석 지점을 사용할 수 없습니다.")
    return path


def _json(path):
    path = _plain(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("JSON 입력은 4MB 이하여야 합니다.")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except RecursionError:
        raise ValueError("JSON 입력의 중첩이 너무 깊습니다.") from None
    if not isinstance(data, dict):
        raise ValueError("JSON 입력은 객체여야 합니다.")
    return data


def _files(run):
    files = {}
    for path in sorted(run.rglob("*")):
        _plain(path)
        if path.is_file():
            files[path.relative_to(run).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def _entry_bytes(state):
    """The entry itself is the only commit record, so no second pointer can drift."""
    metadata = base64.b64encode(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).decode()
    target = ".report-runs/" + state["run"] + "/report.html"
    return ("<!doctype html>\n<!-- " + ENTRY_FORMAT + ":" + metadata + " -->\n"
            '<html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="refresh" content="0;url=' + target + '">'
            '<title>보고서 열기</title></head><body><p>최근에 완성한 보고서를 엽니다.</p>'
            '<p><a href="' + target + '">보고서 보기</a></p></body></html>\n').encode("utf-8")


def _entry_state(path):
    path = _plain(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("기존 HTML은 이 도우미의 진입 파일이 아닙니다. 기존 파일을 보존했습니다.")
    raw = path.read_bytes()
    prefix = ("<!doctype html>\n<!-- " + ENTRY_FORMAT + ":").encode()
    try:
        if not raw.startswith(prefix):
            raise ValueError()
        encoded = raw[len(prefix):].split(b" -->\n", 1)[0]
        state = json.loads(base64.b64decode(encoded, validate=True))
        _validate_state(state, ENTRY_FORMAT)
        if raw != _entry_bytes(state):
            raise ValueError()
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ValueError("기존 HTML은 이 도우미의 진입 파일이 아니거나 수정되었습니다. 기존 파일을 보존했습니다.") from None
    return state


def _validate_state(state, expected):
    if not isinstance(state, dict):
        raise ValueError("이 도우미가 만든 정상본 기록이 아닙니다. 기존 파일을 보존했습니다.")
    name = state.get("run")
    if (state.get("format") != expected or not isinstance(name, str)
            or len(name) != 32 or any(c not in "0123456789abcdef" for c in name)):
        raise ValueError("이 도우미가 만든 정상본 기록이 아닙니다. 기존 파일을 보존했습니다.")


def current(work):
    """Verify one complete run. Read v1 pointers, but never rewrite them."""
    work = _plain(work)
    entry = _plain(work / ENTRY)
    if entry.exists():
        state = _entry_state(entry)
    else:
        state = _json(work / STATE)
        _validate_state(state, FORMAT)
        entry = work / ".report-runs" / state["run"] / "report.html"
    run = _plain(work / ".report-runs" / state["run"])
    files = _files(run)
    if (not files or files != state.get("sha256") or "report.html" not in files
            or "job.json" not in files or not any(p.startswith("evidence/") for p in files)):
        raise ValueError("정상본 묶음이 변경되었거나 일부 파일이 없습니다.")
    return {"ok": True, "outputPath": str(run / "report.html"), "entryPath": str(entry)}


def _attempt(work, payload):
    """Best-effort status, not a success pointer. Never break an already committed run."""
    pending = None
    try:
        path = _plain(work / ATTEMPT)
        if path.exists() and _json(path).get("format") != ATTEMPT_FORMAT:
            raise ValueError("foreign status")
        record = {"format": ATTEMPT_FORMAT, "updatedAt": datetime.now(timezone.utc).isoformat(), **payload}
        pending = work / (".html-report-attempt-" + uuid.uuid4().hex + ".tmp")
        with pending.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
        pending = None
        return None
    except (OSError, ValueError):
        return "마지막 시도 상태를 저장하지 못했습니다. 정상본의 게시 결과와는 별개입니다."
    finally:
        if pending is not None:
            try:
                pending.unlink(missing_ok=True)
            except OSError:
                pass


def status(work):
    """Optional read-only diagnosis, without regenerating or loading a model."""
    work = _plain(work)
    result = {"ok": True, "lastAttempt": None, "lastSuccessful": None}
    if (work / ATTEMPT).exists():
        attempt = _json(work / ATTEMPT)
        if attempt.get("format") != ATTEMPT_FORMAT:
            raise ValueError("이 도우미가 만든 시도 상태가 아닙니다. 기존 파일을 보존했습니다.")
        result["lastAttempt"] = attempt
    if (work / ENTRY).exists() or (work / STATE).exists():
        try:
            result["lastSuccessful"] = current(work)
        except (OSError, ValueError):
            result["currentError"] = "이전 정상본이 변경되었거나 일부 파일이 없습니다."
    attempt = result["lastAttempt"]
    if attempt and attempt.get("status") == "running":
        current_run = Path(result["lastSuccessful"]["outputPath"]).parent.name if result["lastSuccessful"] else None
        # A crash after the single commit can leave the non-authoritative receipt behind.
        attempt["status"] = "complete" if attempt.get("run") == current_run else "running_or_interrupted"
        attempt["stage"] = "published" if attempt["status"] == "complete" else attempt.get("stage")
    return result


def regenerate(input_path, work, build):
    """Call build(input_object, new_run_path), then replace one stable HTML entry.

    build must create job.json, report.html and evidence/* only in new_run_path.
    A failed run is retained internally for diagnosis; no previous run is removed.
    File replacement is used only for this helper's validated entry, never for
    a user's report or for a directory. A lock rejects concurrent invocations.
    """
    work = _plain(work)
    work.mkdir(parents=True, exist_ok=True)
    lock = _plain(work / ".html-report-regeneration.lock")
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    pending = None
    phase = "input"
    attempt_id = uuid.uuid4().hex
    receipt = {"run": attempt_id, "status": "running", "stage": phase}
    try:
        _attempt(work, receipt)
        data = _json(input_path)  # Parse before creating any candidate output.
        phase = "prepare"
        state = _plain(work / STATE)
        entry = _plain(work / ENTRY)
        previous_state = state.read_bytes() if state.exists() else None
        previous_entry = entry.read_bytes() if entry.exists() else None
        if state.exists() or entry.exists():
            current(work)  # Do not overwrite unrelated or changed files.
        runs = _plain(work / ".report-runs")
        runs.mkdir(exist_ok=True)
        run = runs / attempt_id
        run.mkdir()
        phase = "build"
        _attempt(work, {**receipt, "stage": phase})
        build(data, run)
        phase = "validate"
        _json(run / "job.json")
        html = _plain(run / "report.html").read_text(encoding="utf-8")
        if "<html" not in html.lower() or "<body" not in html.lower():
            raise ValueError("완성된 HTML 문서가 없습니다.")
        files = _files(run)
        if not any(name.startswith("evidence/") for name in files):
            raise ValueError("완료 검사 근거가 없습니다.")
        payload = {"format": ENTRY_FORMAT, "run": run.name, "sha256": files}
        pending = work / (".html-report-current-" + uuid.uuid4().hex + ".tmp")
        phase = "publish"
        _attempt(work, {**receipt, "stage": phase})
        with pending.open("xb") as stream:
            stream.write(_entry_bytes(payload))
            stream.flush()
            os.fsync(stream.fileno())
        _plain(state)
        _plain(entry)
        if ((state.read_bytes() if state.exists() else None) != previous_state
                or (entry.read_bytes() if entry.exists() else None) != previous_entry):
            raise ValueError("생성 중 정상본 기록이 외부에서 변경되었습니다. 변경된 기록을 보존했습니다.")
        os.replace(pending, entry)
        pending = None
        result = {"ok": True, "outputPath": str(run / "report.html"), "entryPath": str(entry)}
        warning = _attempt(work, {**receipt, "status": "complete", "stage": "published"})
        if warning:
            result["warnings"] = [warning]
        return result
    except Exception as exc:
        _attempt(work, {**receipt, "status": "failed", "stage": phase, "errorType": type(exc).__name__})
        raise
    finally:
        if pending is not None:
            try:
                pending.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            lock.unlink()
        except OSError:
            pass


def build_job(data, run):
    """Runnable example: the input already is a report job, without analysis."""
    try:
        from visual_engine import business_artifacts
    except ImportError:
        # The harness copy uses its shipped engine, never an installed profile.
        scripts = Path(__file__).resolve().parents[3] / "scripts"
        if not (scripts / "company_agent" / "business_artifacts.py").is_file():
            raise ValueError("배포 ZIP 전체 또는 하네스의 스킬 폴더를 사용해 주세요.") from None
        sys.path.insert(0, str(scripts))
        from company_agent import business_artifacts
    (run / "job.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    result = business_artifacts.create_html(data, run / "report.html", require_choices=False)
    if not result.get("ok"):
        raise ValueError(result.get("message", "HTML 생성에 실패했습니다."))
    (run / "evidence").mkdir()
    (run / "evidence" / "validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="선택형 HTML 재생성 예제: 정상본 묶음 보존")
    parser.add_argument("--work", type=Path, required=True)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--spec", type=Path, help="이미 작성한 report job JSON. 생략하면 현재 정상본 확인")
    operation.add_argument("--status", action="store_true", help="재생성 없이 마지막 시도와 정상본 확인")
    args = parser.parse_args(argv)
    try:
        result = status(args.work) if args.status else regenerate(args.spec, args.work, build_job) if args.spec else current(args.work)
    except (OSError, ValueError) as exc:
        result = {"ok": False, "code": "regeneration_failed", "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    # -B is also shown in the example to avoid bytecode beside input sources.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
