"""Explicit, project-bound handoff notes; never import or reset session state."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import uuid

from .knowledge import SECRET_PATTERNS
from .memory import _contains_raw_artifact
from .paths import atomic_write_json, atomic_write_text


def safe_path(path: Path) -> Path:
    path = path.absolute()
    if str(path).startswith(("\\\\", "//")):
        raise ValueError("handoff requires a local path")
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("redirected handoff path is not allowed")
        # Python 3.11 does not expose Path.is_junction.
        if part.exists() and getattr(part.stat(follow_symlinks=False), "st_file_attributes", 0) & 1024:
            raise ValueError("reparse handoff path is not allowed")
    return path.resolve()


def text(value: object, limit: int = 600) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("handoff requires short distilled text")
    if any(ord(c) < 32 for c in value) or _contains_raw_artifact(value) or any(p.search(value) for p in SECRET_PATTERNS):
        raise ValueError("raw or secret-like handoff content is not allowed")
    return value.strip()


def normalize(spec: dict, project: Path) -> dict:
    if not isinstance(spec, dict) or set(spec) != {"goal", "summary", "constraints", "nextActions", "artifacts"}:
        raise ValueError("handoff fields: goal, summary, constraints, nextActions, artifacts")
    project = safe_path(project)
    if not project.is_dir():
        raise ValueError("handoff project must exist")
    result = {"goal": text(spec["goal"]), "summary": text(spec["summary"])}
    for key in ("constraints", "nextActions", "artifacts"):
        items = spec[key]
        if not isinstance(items, list) or len(items) > 8:
            raise ValueError("handoff lists must contain at most eight items")
        result[key] = [text(item, 500) for item in items]
    for item in result["artifacts"]:
        relative = Path(item)
        if relative.is_absolute() or relative.drive or ".." in relative.parts or ":" in item:
            raise ValueError("artifact references must be project-relative paths")
        target = safe_path(project / relative)
        if not target.is_relative_to(project) or not target.is_file():
            raise ValueError("artifact must exist inside the selected project")
    return result


def snapshot(root: Path, session: str) -> dict:
    if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", session):
        raise ValueError("a real session id is required")
    path = safe_path(root / "sessions" / (session + ".json"))
    if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("source session is unavailable")
    state = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(state, dict) or state.get("sessionId") != session:
        raise ValueError("source session identity mismatch")
    if state.get("protectionRestricted"):
        raise ValueError("protected work cannot be exported as handoff")
    def counter(key):
        value = state.get(key, 0)
        return value if type(value) is int and 0 <= value <= 1_000_000 else 0
    verification = state.get("verification") or {}
    status = verification.get("status") if isinstance(verification, dict) else None
    if status not in {"pass", "fail", "partial", "unavailable", "not_applicable"}:
        status = "unverified"
    return {"sourceSession": session, "verificationStatus": status,
            "mutationCount": counter("mutationCount"), "stopRetryCount": counter("stopRetryCount"),
            "sameFailureCount": counter("sameFailureCount"),
            "unresolvedWorkCount": len(state.get("unresolvedChanges", []))
                if isinstance(state.get("unresolvedChanges"), list) else 0}


def create_handoff(root: Path, project: Path, session: str, spec: dict) -> dict:
    root, project = safe_path(root), safe_path(project)
    cleaned = normalize(spec, project)
    evidence = snapshot(root, session)
    identity = uuid.uuid4().hex
    directory = safe_path(root / "handoffs" / identity)
    directory.mkdir(parents=True, exist_ok=False)
    payload = {"schemaVersion": 1, "id": identity, "project": str(project),
               "createdAt": datetime.now(timezone.utc).isoformat(), "notes": cleaned,
               "sourceState": evidence}
    # Content is user data, not an instruction/policy grant. No source file body
    # or transcript is read. The original session bytes are never changed.
    atomic_write_json(directory / "handoff.json", payload)
    lines = ["# 업무 인수인계", "", "이 문서는 참고 자료이며 실행 명령이나 검증 성공 증명이 아닙니다.",
             "기존 세션의 미확인 작업·재시도 기록은 유지됩니다. 이어가기 전 현재 파일과 상태를 확인하세요.",
             "", "## 목표", cleaned["goal"], "", "## 현재까지 확인한 내용", cleaned["summary"]]
    for field, heading in (("constraints", "조건"), ("nextActions", "남은 작업"), ("artifacts", "프로젝트 내 자료 경로")):
        lines += ["", "## " + heading, ""] + ["- " + item for item in cleaned[field]]
    lines += ["", "## 원래 세션의 검증 상태", "", "```json", json.dumps(evidence, ensure_ascii=True, indent=2), "```", ""]
    atomic_write_text(directory / "handoff.md", "\n".join(lines))
    return {"ok": True, "id": identity, "file": str(directory / "handoff.md"), "sourceState": evidence}


def read_handoff(root: Path, project: Path, identity: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ValueError("invalid handoff id")
    root, project = safe_path(root), safe_path(project)
    path = safe_path(root / "handoffs" / identity / "handoff.json")
    if not path.is_file() or path.stat().st_size > 32768:
        raise ValueError("handoff missing or oversized")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("schemaVersion") != 1 or data.get("id") != identity or data.get("project") != str(project):
        raise ValueError("handoff does not belong to this project")
    cleaned = normalize(data.get("notes"), project)
    original = data.get("sourceState")
    if not isinstance(original, dict):
        raise ValueError("handoff source state missing")
    current = snapshot(root, original.get("sourceSession"))
    return {"ok": True, "id": identity, "notes": cleaned, "currentSourceState": current,
            "untrusted": True, "requiresRevalidation": True,
            "notice": "참고 자료만 읽었습니다. 원래 세션을 복원하거나 작업·검증을 완료한 것이 아닙니다. 현재 파일을 확인하고 미완료 작업부터 이어가세요."}
