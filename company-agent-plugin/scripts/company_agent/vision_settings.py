"""Small, user-chosen vision configuration and one owned native Claude agent.

Only the vision setup/change path writes here. Ordinary text reads must not call
this module to inspect settings, enumerate models, or probe a provider.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

from .paths import atomic_write_json, atomic_write_text

DEFAULT_MODEL = "HCP-Vision-Latest"
_MAX_SETTINGS_BYTES = 16_384
_MAX_AGENT_BYTES = 32_768
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\[\]-]{0,159}\Z", re.ASCII)
_HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


def validate_model(model: str) -> str:
    if (
        not isinstance(model, str)
        or not _MODEL.fullmatch(model)
        or model.lower().startswith(("http:", "https:"))
        or "//" in model
        or any(part in {".", ".."} for part in model.split("/"))
    ):
        raise ValueError("비전 모델은 주소나 인증 정보가 아닌 정확한 모델 ID로 입력해 주세요.")
    return model


def _absolute(path: Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise ValueError("비전 설정과 Claude 설정 위치는 절대 경로여야 합니다.")
    # Do not resolve first: that would hide a symlink/junction in the input.
    if ".." in candidate.parts:
        raise ValueError("비전 설정 경로에 상위 폴더 이동을 사용할 수 없습니다.")
    return Path(os.path.abspath(candidate))


def _safe_path(path: Path) -> Path:
    candidate = _absolute(path)
    for part in (*reversed(candidate.parents), candidate):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise ValueError("연결된 폴더나 파일에는 비전 설정을 저장하지 않습니다.")
        if part != candidate and not stat.S_ISDIR(info.st_mode):
            raise ValueError("비전 설정의 상위 경로가 폴더가 아닙니다.")
    return candidate


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _agent_name(root: Path) -> str:
    digest = hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()[:8]
    return "company-harness-vision-" + digest


def _marker(agent: str) -> str:
    return "<!-- Company Harness managed vision agent: " + agent + " -->"


def _settings_path(root: Path) -> Path:
    return _safe_path(_safe_path(root) / "config" / "vision-model.json")


def _read_file(path: Path, limit: int) -> bytes | None:
    path = _safe_path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise ValueError("비전 설정 파일의 형식이나 크기가 올바르지 않습니다.")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("비전 설정 파일의 크기가 너무 큽니다.")
    return data


def read_settings(root: Path) -> dict:
    root = _safe_path(root)
    data = _read_file(_settings_path(root), _MAX_SETTINGS_BYTES)
    if data is None:
        return {}
    try:
        settings = json.loads(data.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("저장된 비전 설정을 읽지 못했습니다. 설정 파일을 확인해 주세요.") from exc
    required = {"schemaVersion", "model", "agent", "agentPath", "sha256", "modelUpdatedAt"}
    if (
        not isinstance(settings, dict)
        or set(settings) != required
        or type(settings["schemaVersion"]) is not int
        or settings["schemaVersion"] != 1
    ):
        raise ValueError("저장된 비전 설정 형식을 확인해 주세요.")
    validate_model(settings["model"])
    if settings["agent"] != _agent_name(root):
        raise ValueError("비전 설정의 저장 범위가 현재 저장소와 다릅니다.")
    if not isinstance(settings["agentPath"], str) or not isinstance(settings["sha256"], str):
        raise ValueError("저장된 비전 작업자 정보를 확인해 주세요.")
    agent_path = _safe_path(Path(settings["agentPath"]))
    if (
        agent_path.name != settings["agent"] + ".md"
        or agent_path.parent.name != "agents"
        or not _HASH.fullmatch(settings["sha256"])
    ):
        raise ValueError("저장된 비전 작업자 경로나 확인 값이 올바르지 않습니다.")
    try:
        updated_at = settings["modelUpdatedAt"]
        if not isinstance(updated_at, str) or len(updated_at) > 40:
            raise ValueError("invalid timestamp")
        parsed = datetime.fromisoformat(updated_at)
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError as exc:
        raise ValueError("저장된 비전 모델 변경 시각을 확인해 주세요.") from exc
    return settings


def _owned_bytes(settings: dict) -> bytes | None:
    data = _read_file(Path(settings["agentPath"]), _MAX_AGENT_BYTES)
    if data is None:
        return None
    if (
        hashlib.sha256(data).hexdigest() != settings["sha256"]
        or _marker(settings["agent"]).encode("utf-8") not in data
    ):
        raise ValueError("비전 작업자 파일이 직접 수정되었습니다. 개인 파일을 덮어쓰지 않았습니다.")
    return data


def _result(settings: dict, *, restart: bool = False, next_request: bool = False) -> dict:
    return {
        "status": "ready",
        "model": settings["model"],
        "agent": settings["agent"],
        "agentPath": settings["agentPath"],
        "backupModel": DEFAULT_MODEL,
        "restartMayBeRequired": restart,
        # A new user turn does not reliably refresh Claude's in-process agent
        # definitions. A newly created/changed definition needs a new session.
        "restartRequired": next_request,
        "nextRequestRequired": next_request,
        "modelUpdatedAt": settings["modelUpdatedAt"],
    }


def status(root: Path) -> dict:
    settings = read_settings(root)
    if not settings:
        return {"status": "needs_setup", "backupModel": DEFAULT_MODEL}
    if _owned_bytes(settings) is None:
        return {"status": "needs_setup", "reason": "agent_missing", "backupModel": DEFAULT_MODEL}
    return _result(settings)


def _agent_text(agent: str, model: str) -> str:
    template_path = Path(__file__).resolve().parents[2] / "agents" / "vision-worker.md"
    source = template_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    parts = source.split("---\n", 2)
    if len(parts) != 3 or parts[0]:
        raise ValueError("설치된 비전 작업자 양식을 확인해 주세요.")
    frontmatter, body = parts[1:]
    for field, value in (
        ("name", agent),
        ("model", json.dumps(model, ensure_ascii=True)),
        ("description", "사용자가 선택한 모델로 지정한 이미지와 화면만 읽고 한국어 텍스트를 반환합니다."),
    ):
        frontmatter, count = re.subn(r"(?m)^" + field + r":[^\n]*$", field + ": " + value, frontmatter)
        if count != 1:
            raise ValueError("설치된 비전 작업자 양식의 필수 항목이 올바르지 않습니다.")
    body = body.replace("company-agent:vision-worker", agent).replace(DEFAULT_MODEL, model)
    text = "---\n" + frontmatter + "---\n\n" + _marker(agent) + "\n" + body.lstrip("\n")
    if len(text.encode("utf-8")) > _MAX_AGENT_BYTES:
        raise ValueError("비전 작업자 양식이 너무 큽니다.")
    return text


def configure(root: Path, model: str, *, config_root: Path | None = None) -> dict:
    model = validate_model(model)
    root = _safe_path(root)
    config_root = _safe_path(config_root or Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"))
    agent = _agent_name(root)
    agents_dir = _safe_path(config_root / "agents")
    if agents_dir.exists() and not agents_dir.is_dir():
        raise ValueError("Claude 작업자 저장 위치가 폴더가 아닙니다.")
    agent_path = _safe_path(agents_dir / (agent + ".md"))
    settings_path = _settings_path(root)
    previous = read_settings(root)
    previous_bytes = _owned_bytes(previous) if previous else None
    same_file = bool(previous and _same_path(Path(previous["agentPath"]), agent_path))
    if previous_bytes is not None and not same_file:
        raise ValueError("이전 Claude 설정 위치에 비전 작업자가 있습니다. 다른 위치에 중복 생성하지 않았습니다.")
    existing = _read_file(agent_path, _MAX_AGENT_BYTES)
    if existing is not None and (not same_file or previous_bytes is None):
        raise ValueError("같은 이름의 개인 작업자 파일이 있습니다. 기존 파일을 덮어쓰지 않았습니다.")
    text = _agent_text(agent, model)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    settings = {"schemaVersion": 1, "model": model, "agent": agent, "agentPath": str(agent_path), "sha256": digest}
    if existing == text.encode("utf-8") and {key: previous.get(key) for key in settings} == settings:
        return _result(previous)
    settings["modelUpdatedAt"] = datetime.now(timezone.utc).isoformat()
    restart = not agents_dir.exists()
    # Check again after creating only the two required parent directories.
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    agents_dir.mkdir(parents=True, exist_ok=True)
    _safe_path(settings_path)
    _safe_path(agent_path)
    if _read_file(agent_path, _MAX_AGENT_BYTES) != existing or read_settings(root) != previous:
        raise ValueError("비전 설정 중 파일이 변경되었습니다. 새 내용을 덮어쓰지 않았습니다.")
    atomic_write_text(agent_path, text)
    try:
        atomic_write_json(settings_path, settings)
    except Exception:
        # A failed receipt write must not leave a changed owned agent paired
        # with an obsolete receipt. Restore only the exact bytes we just wrote.
        if _read_file(agent_path, _MAX_AGENT_BYTES) == text.encode("utf-8"):
            if existing is None:
                agent_path.unlink()
            else:
                atomic_write_text(agent_path, existing.decode("utf-8"))
        raise
    return _result(settings, restart=restart, next_request=True)
