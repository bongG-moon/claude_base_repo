"""Offline questionnaire generator. Collects non-sensitive setup inputs, never installs.

This module is also copied as a standalone helper; keep imports stdlib-only.
Secret detection is best effort, not a data-loss-prevention or encryption system.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Callable


_NAME = re.compile(r"[a-z][a-z0-9-]{1,62}\Z")
_PRIVATE = re.compile(
    r"password|passwd|secret|token|credential|api.?key|private.?key|access.?key|"
    r"비밀번호|암호|비밀|토큰|인증.?정보|주민.?번호|건강.?정보|계좌.?번호", re.I
)
_SECRET_VALUE = re.compile(r"-----BEGIN .*PRIVATE KEY|\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}|Bearer\s+\S+", re.I)
_LIMIT = 64 * 1024


def _plain(value: object, name: str, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name}: non-empty text up to {maximum} characters required")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{name}: control characters are forbidden")
    return value.strip()


def validate_spec(spec: object) -> dict:
    if not isinstance(spec, dict) or set(spec) != {"name", "title", "steps"}:
        raise ValueError("spec requires exactly name, title, steps; executable fields are forbidden")
    name = _plain(spec["name"], "name", 63)
    if not _NAME.fullmatch(name):
        raise ValueError("name must be a lower-case slug of 2-63 characters")
    title = _plain(spec["title"], "title")
    steps = spec["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
        raise ValueError("steps must contain 1-20 questions")
    result, seen = [], set()
    for step in steps:
        if not isinstance(step, dict) or not {"id", "label", "kind", "required"} <= set(step):
            raise ValueError("each step requires id, label, kind, required")
        if set(step) - {"id", "label", "kind", "required", "choices"}:
            raise ValueError("unknown step fields are forbidden")
        field = _plain(step["id"], "id", 63)
        label = _plain(step["label"], "label")
        if not _NAME.fullmatch(field) or field in seen:
            raise ValueError("step ids must be unique lower-case slugs")
        # Also reject generic key fields, whose intended contents are ambiguous.
        if _PRIVATE.search(field + " " + label) or re.search(r"(^|[-_])key($|[-_])", field, re.I):
            raise ValueError("sensitive or credential questions are forbidden")
        if step["kind"] not in ("text", "choice", "path") or type(step["required"]) is not bool:
            raise ValueError("kind must be text/choice/path; required must be boolean")
        clean = {"id": field, "label": label, "kind": step["kind"], "required": step["required"]}
        if step["kind"] == "choice":
            choices = step.get("choices")
            if not isinstance(choices, list) or not 2 <= len(choices) <= 8:
                raise ValueError("choice requires 2-8 choices")
            clean["choices"] = [_plain(item, "choice") for item in choices]
            if len(set(clean["choices"])) != len(choices):
                raise ValueError("choices must be unique")
            if any(_PRIVATE.search(item) or _SECRET_VALUE.search(item) for item in clean["choices"]):
                raise ValueError("sensitive or credential choices are forbidden")
        elif "choices" in step:
            raise ValueError("choices are only valid for choice steps")
        seen.add(field)
        result.append(clean)
    return {"name": name, "title": title, "steps": result}


def _safe_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    if str(path).startswith(("\\\\", "//")):
        raise ValueError("UNC/network paths are not allowed")
    for part in [path, *path.parents]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("symbolic links and reparse points are not allowed")
    return path


def _read_json(path: Path) -> object:
    _safe_path(path)
    if path.stat().st_size > _LIMIT:
        raise ValueError("questionnaire file is too large")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_answers(directory: Path, values: dict) -> Path:
    directory = _safe_path(directory)
    destination = _safe_path(directory / "answers.json")
    descriptor, temporary = tempfile.mkstemp(prefix=".answers-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(values, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _safe_path(destination)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def create_setup_helper(root: Path, spec: dict) -> dict:
    """Create a standalone, non-executing questionnaire under the supplied state root."""
    spec = validate_spec(spec)
    encoded_spec = json.dumps(spec, ensure_ascii=False, indent=2) + "\n"
    if len(encoded_spec.encode("utf-8")) > _LIMIT:
        raise ValueError("questionnaire file is too large")
    root = _safe_path(root)
    directory = _safe_path(root / "setup-helpers" / spec["name"])
    directory.parent.mkdir(parents=True, exist_ok=True)
    _safe_path(directory.parent)
    directory.mkdir(exist_ok=False)
    # No template interpolation: questionnaire content is data, never Python code.
    (directory / "spec.json").write_text(encoded_spec, encoding="utf-8")
    (directory / "helper.py").write_text(Path(__file__).read_text(encoding="utf-8-sig"), encoding="utf-8")
    return {"status": "created", "directory": str(directory), "helperPath": str(directory / "helper.py"),
            "specPath": str(directory / "spec.json"), "answersPath": str(directory / "answers.json"),
            "installsSoftware": False}


def _answer(step: dict, value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("응답은 문자열이어야 합니다.")
    if not value:
        if step["required"]:
            raise ValueError("필수 항목입니다. 값을 입력하거나 /cancel로 취소해 주세요.")
        return ""
    try:
        value = _plain(value, "answer", 500)
    except ValueError as exc:
        raise ValueError("답변은 제어 문자 없이 500자 이내로 입력해 주세요.") from exc
    if _SECRET_VALUE.search(value) or _PRIVATE.search(value):
        raise ValueError("민감 정보로 의심되어 저장하지 않습니다. 비밀값 없이 다시 입력해 주세요.")
    if step["kind"] == "choice" and value not in step["choices"]:
        raise ValueError("표시된 선택지의 번호를 입력해 주세요.")
    if step["kind"] == "path":
        if not Path(value).is_absolute():
            raise ValueError("존재하는 PC 로컬 폴더의 전체 경로를 입력해 주세요.")
        try:
            target = _safe_path(Path(value))
        except ValueError as exc:
            raise ValueError("연결 경로나 네트워크 폴더는 사용할 수 없습니다. PC 로컬 폴더를 선택해 주세요.") from exc
        if not target.is_dir():
            raise ValueError("존재하는 PC 로컬 폴더를 입력해 주세요.")
        value = str(target)
    return value


def run_helper(directory: Path, *, check: bool = False,
               input_fn: Callable[[str], str] = input,
               output_fn: Callable[[str], None] = print) -> dict:
    """Validate, collect and explicitly confirm answers. Never launch an installer."""
    directory = _safe_path(directory)
    spec = validate_spec(_read_json(directory / "spec.json"))
    if sys.version_info < (3, 11) or sys.platform != "win32":
        raise ValueError("Windows와 Python 3.11 이상이 필요합니다.")
    previous_path = _safe_path(directory / "answers.json")
    previous = _read_json(previous_path) if previous_path.exists() else {}
    if not isinstance(previous, dict) or set(previous) - {step["id"] for step in spec["steps"]}:
        raise ValueError("기존 응답 파일의 형식이 다릅니다. 내용을 확인해 주세요.")
    invalid_previous = []
    for step in spec["steps"]:
        if step["id"] in previous:
            try:
                _answer(step, previous[step["id"]])
            except ValueError:
                invalid_previous.append(step["id"])
    if check:
        return {"status": "ready_with_reentry" if invalid_previous else "ready",
                "questionCount": len(spec["steps"]), "hasPreviousAnswers": bool(previous),
                "reentryFields": invalid_previous, "installsSoftware": False}
    output_fn(spec["title"])
    output_fn("이 도우미는 설정 답변만 저장합니다. 설치나 명령 실행은 하지 않습니다.")
    output_fn("비밀번호·인증키·개인/업무 민감 정보는 입력하지 마세요. 자동 탐지는 완전하지 않으며 답변은 평문 저장됩니다.")
    output_fn("기존 답변은 직접 확인 후 유지/변경할 수 있습니다. 언제든 /cancel로 취소할 수 있습니다.")
    def ask(prompt: str) -> str:
        value = input_fn(prompt).strip()
        if value.casefold() == "/cancel":
            raise KeyboardInterrupt
        return value
    answers = {}
    try:
        for number, step in enumerate(spec["steps"], 1):
            output_fn(f"[{number}/{len(spec['steps'])}] {step['label']}")
            if step["id"] in invalid_previous:
                output_fn("이전 값은 현재 사용할 수 없어 다시 입력해야 합니다. 이전 값은 표시하지 않습니다.")
            elif step["id"] in previous:
                output_fn("이전 값: " + previous[step["id"]])
                while True:
                    selection = ask("1: 이 값 유지 / 2: 변경 / /cancel: 취소: ")
                    if selection in ("1", "2"):
                        break
                    output_fn("1 또는 2를 입력해 주세요.")
                if selection == "1":
                    answers[step["id"]] = previous[step["id"]]
                    continue
            if step["kind"] == "choice":
                for index, choice in enumerate(step["choices"], 1):
                    output_fn(f"{index}. {choice}")
            while True:
                value = ask("입력 (/cancel: 취소): ")
                if step["kind"] == "choice" and value.isascii() and value.isdigit() and 1 <= int(value) <= len(step["choices"]):
                    value = step["choices"][int(value) - 1]
                try:
                    answers[step["id"]] = _answer(step, value)
                    break
                except ValueError as exc:
                    output_fn(str(exc))
        output_fn("저장할 답변:")
        for step in spec["steps"]:
            output_fn(f"- {step['label']}: {answers[step['id']]}")
        while True:
            decision = ask("1: 위 답변 저장 / 2: 저장하지 않고 종료: ")
            if decision in ("1", "2"):
                break
            output_fn("1 또는 2를 입력해 주세요.")
        if decision == "2":
            return {"status": "cancelled", "saved": False}
    except (EOFError, KeyboardInterrupt):
        return {"status": "cancelled", "saved": False}
    destination = _write_answers(directory, answers)
    return {"status": "saved", "answersPath": str(destination), "installsSoftware": False}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description="오프라인 설정 입력 도우미 (설치 실행 없음)")
    parser.add_argument("--check", action="store_true", help="입력 없이 실행 조건과 질문 형식 확인")
    arguments = parser.parse_args()
    try:
        result = run_helper(Path(__file__).parent, check=arguments.check)
        if arguments.check:
            print(json.dumps(result, ensure_ascii=True))  # Machine-readable preflight contract.
        elif result["status"] == "cancelled":
            print("저장하지 않고 종료했습니다. 기존 답변은 유지했습니다.")
        else:
            print("답변을 저장했습니다. 설치나 설정 변경은 실행하지 않았습니다.")
            print("저장 위치: " + result["answersPath"])
        return 2 if result["status"] == "cancelled" else 0
    except (ValueError, OSError, TypeError) as exc:
        if arguments.check:
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=True))
        else:
            print("입력 도우미를 완료하지 못했습니다. 질문 파일 형식·실행 조건·저장 폴더 권한을 확인해 주세요. 기존 자료를 삭제하거나 보안 설정을 해제하지 마세요.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
