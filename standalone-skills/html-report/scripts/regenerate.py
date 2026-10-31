"""Opt-in regeneration example: publish one complete run through a small pointer.

Only trusted, task-owned build functions belong here. This is not a runner for
commands embedded in source documents. The ordinary report.py stays unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

FORMAT = "html-report-generation-v1"
STATE = ".html-report-current.json"


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
    data = json.loads(path.read_text(encoding="utf-8-sig"))
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


def current(work):
    """Resolve and verify the complete run; never mix files from two runs."""
    work = _plain(work)
    state = _json(work / STATE)
    name = state.get("run")
    if (state.get("format") != FORMAT or not isinstance(name, str)
            or len(name) != 32 or any(c not in "0123456789abcdef" for c in name)):
        raise ValueError("이 도우미가 만든 정상본 기록이 아닙니다. 기존 파일을 보존했습니다.")
    run = _plain(work / ".report-runs" / name)
    files = _files(run)
    if (not files or files != state.get("sha256") or "report.html" not in files
            or "job.json" not in files or not any(p.startswith("evidence/") for p in files)):
        raise ValueError("정상본 묶음이 변경되었거나 일부 파일이 없습니다.")
    return {"ok": True, "outputPath": str(run / "report.html")}


def regenerate(input_path, work, build):
    """Call build(input_object, new_run_path), then switch the current pointer.

    build must create job.json, report.html and evidence/* only in new_run_path.
    A failed run is retained internally for diagnosis; no previous run is removed.
    File replacement is used only for this helper's validated state pointer, never
    for a user's report or for a directory. A lock rejects concurrent invocations.
    """
    data = _json(input_path)  # Parse before creating any candidate output.
    work = _plain(work)
    work.mkdir(parents=True, exist_ok=True)
    lock = _plain(work / ".html-report-regeneration.lock")
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    pending = None
    try:
        state = _plain(work / STATE)
        previous_state = state.read_bytes() if state.exists() else None
        if state.exists():
            current(work)  # Do not overwrite unrelated or changed files.
        runs = _plain(work / ".report-runs")
        runs.mkdir(exist_ok=True)
        run = runs / uuid.uuid4().hex
        run.mkdir()
        build(data, run)
        _json(run / "job.json")
        html = _plain(run / "report.html").read_text(encoding="utf-8")
        if "<html" not in html.lower() or "<body" not in html.lower():
            raise ValueError("완성된 HTML 문서가 없습니다.")
        files = _files(run)
        if not any(name.startswith("evidence/") for name in files):
            raise ValueError("완료 검사 근거가 없습니다.")
        payload = {"format": FORMAT, "run": run.name, "sha256": files}
        pending = work / (".html-report-current-" + uuid.uuid4().hex + ".tmp")
        with pending.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        _plain(state)
        if (state.read_bytes() if state.exists() else None) != previous_state:
            raise ValueError("생성 중 정상본 기록이 외부에서 변경되었습니다. 변경된 기록을 보존했습니다.")
        os.replace(pending, state)
        pending = None
        return {"ok": True, "outputPath": str(run / "report.html")}
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
        lock.unlink()


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
    parser.add_argument("--spec", type=Path, help="이미 작성한 report job JSON. 생략하면 현재 정상본 확인")
    args = parser.parse_args(argv)
    try:
        result = regenerate(args.spec, args.work, build_job) if args.spec else current(args.work)
    except (OSError, ValueError) as exc:
        result = {"ok": False, "code": "regeneration_failed", "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    # -B is also shown in the example to avoid bytecode beside input sources.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
