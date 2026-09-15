"""Skill discovery receipts, not an authorization or semantic classifier.

Only observed successful reads count. Persist hashes/IDs, never task or Skill
content. A new prompt needs a choice, not another scan/read of unchanged files.
No Stop hook, permission allow, model call, or background watcher is used here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .paths import atomic_write_json
from .skill_catalog import MAX_CATALOG_BYTES
from .skill_registry import MAX_SKILL_BYTES, _canonical, _no_reparse, _read, _resolution
from .state import _locked_session, _stale_native_prompt, load_session, safe_session_id


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _snapshot(root: Path, project: Path, route: dict) -> dict:
    directory = root / "skill-catalogs" / _hash(_canonical(project).encode("utf-8"))
    catalog = directory / "SKILL_CATALOG.md"
    if _canonical(catalog) != route.get("catalog"):
        raise ValueError("작업 폴더의 스킬 목록을 다시 확인해 주세요.")
    _no_reparse(catalog)
    _no_reparse(catalog.with_suffix(".json"))
    data = json.loads(_read(catalog.with_suffix(".json"), MAX_CATALOG_BYTES) or b"{}")
    raw = _read(catalog, MAX_CATALOG_BYTES)
    if (data.get("revision") != route.get("revision") or data.get("project") != _canonical(project)
            or raw is None or _hash(raw) != data.get("catalogHash")):
        raise ValueError("스킬 목록이 바뀌었습니다. 다음 요청에서 새 목록을 확인해 주세요.")
    return data


def prepare(root: Path, project: Path, session_id: str, catalog: dict, *, prompt: str = "", compact: bool = False) -> dict:
    if not session_id:
        return {"status": "unavailable"}
    with _locked_session(session_id, root) as (state, path):
        if catalog.get("status") != "ready":
            state["skillWorkflow"] = {"status": "unavailable", "turn": state.get("turnId", "")}
            atomic_write_json(path, state)
            return {"status": "unavailable"}
        old = state.get("skillWorkflow", {})
        identity = {"catalog": _canonical(Path(catalog["path"])), "revision": catalog["revision"],
                    "project": _canonical(project)}
        same = all(old.get(key) == value for key, value in identity.items()) and not compact
        route = old if same else {**identity, "indexRead": False, "readSkills": {}}
        turn = state.get("turnId", "")
        if route.get("turn") != turn or compact:
            route.update(turn=turn, selected=None, fallback=None)
        if prompt:
            # Exact native slash invocations only, not a general opt-out guess.
            route["explicit"] = re.findall(r"(?<!\S)/([A-Za-z0-9][A-Za-z0-9:_-]{0,159})(?=\s|$)", prompt)[:8]
        state["skillWorkflow"] = route
        atomic_write_json(path, state)
        return {"status": "ready", "indexRead": route.get("indexRead", False),
                "selected": (route.get("selected") or {}).get("name"),
                "nextAction": "read-index" if not route.get("indexRead") else
                    ("execute-selected" if route.get("selected") or route.get("fallback") else "choose-skill"),
                "turn": turn}


def _allowed(item: dict, data: dict, route: dict) -> bool:
    invocation = str(item.get("invocation", "")).lstrip("/")
    explicit = route.get("explicit", [])
    # A fully qualified invocation identifies a candidate only if unique.
    matches = [x for x in data["skills"] if str(x.get("invocation", "")).lstrip("/") == invocation]
    if invocation and invocation in explicit and len(matches) == 1:
        return True
    candidates = [x for x in data["skills"] if x["name"].casefold() == item["name"].casefold()]
    return _resolution(item["name"].casefold(), candidates, data["preferences"]).get("selectedId") == item["id"]


def _current(item: dict, route: dict) -> bytes:
    file = Path(item["path"])
    _no_reparse(file)
    raw = _read(file, MAX_SKILL_BYTES)
    if raw is None or _hash(raw) != item["sha256"]:
        raise ValueError("선택한 스킬이 변경되었거나 삭제되었습니다. 새 요청에서 목록을 갱신해 주세요.")
    # Do not enable user-invocation-only skills through a manual file read.
    from .frontmatter import parse_frontmatter_text
    metadata, _ = parse_frontmatter_text(raw.decode("utf-8-sig"))
    if metadata.get("disable-model-invocation") is True:
        if str(item.get("invocation", "")).lstrip("/") not in route.get("explicit", []):
            raise ValueError("이 스킬은 사용자가 직접 호출할 때만 사용할 수 있습니다.")
    return raw


def _record_read(route: dict, key: str, response: Any, raw: bytes) -> bool:
    """Native Read reports range/total; partial reads do not claim full exposure."""
    if not isinstance(response, dict) or response.get("isError") or response.get("is_error"):
        return False
    file = response.get("file")
    if not isinstance(file, dict) or not isinstance(file.get("content"), str):
        return False
    lines = raw.decode("utf-8-sig").splitlines()
    content = file["content"].splitlines()
    if not content and file.get("numLines") == 1 and file["content"] == "":
        content = [""]
    start = file.get("startLine", 1)
    if type(start) is not int or start < 1 or not content or lines[start-1:start-1+len(content)] != content:
        return False
    end = start + len(content) - 1
    # Only matching whole lines count; a truncated response cannot unlock a
    # workflow. Support native Read paging without retaining any source text.
    receipts = route.setdefault("readRanges", {})
    receipt = receipts.get(key, {})
    ranges = receipt.get("ranges", []) if receipt.get("hash") == _hash(raw) else []
    merged: list[list[int]] = []
    for low, high in sorted(ranges + [[start, end]]):
        if merged and low <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], high)
        else:
            merged.append([low, high])
    receipts[key] = {"hash": _hash(raw), "ranges": merged[:128]}
    while len(receipts) > 40:
        del receipts[next(iter(receipts))]
    return merged == [[1, len(lines)]]


def observe(root: Path, project: Path, payload: dict) -> None:
    if payload.get("hook_event_name") != "PostToolUse" or payload.get("error") or payload.get("tool_error"):
        return
    if payload.get("tool_name") not in {"Read", "Skill"} or not payload.get("session_id"):
        return
    with _locked_session(str(payload["session_id"]), root) as (state, path):
        route = state.get("skillWorkflow")
        if not route or _stale_native_prompt(payload, state):
            return
        data = _snapshot(root, project, route)
        inputs = payload.get("tool_input") or {}
        response = payload.get("tool_response")
        if payload["tool_name"] == "Read":
            value = inputs.get("file_path")
            if not isinstance(value, str) or not Path(value).is_absolute():
                return
            file = Path(value)
            if _canonical(file) == route["catalog"]:
                if _record_read(route, "catalog", response, _read(file, MAX_CATALOG_BYTES) or b""):
                    route["indexRead"] = True
                atomic_write_json(path, state)
                return
            candidates = [x for x in data["skills"] if _canonical(Path(x["path"])) == _canonical(file)]
        else:
            # A successful native Skill event is a load receipt, not execution
            # permission. A namespaced/name collision is not guessed.
            if not isinstance(response, dict) or response.get("success") is not True:
                return
            invocation = str(inputs.get("skill", "")).lstrip("/")
            candidates = [x for x in data["skills"] if str(x.get("invocation", "")).lstrip("/") == invocation]
        if len(candidates) != 1 or not route.get("indexRead"):
            return
        item = candidates[0]
        if not _allowed(item, data, route):
            return
        raw = _current(item, route)
        if payload["tool_name"] == "Read" and not _record_read(route, item["id"], response, raw):
            atomic_write_json(path, state)
            return
        cache = route.setdefault("readSkills", {})
        cache[item["id"]] = item["sha256"]
        while len(cache) > 32:
            del cache[next(iter(cache))]
        from .frontmatter import parse_frontmatter_text
        metadata, _ = parse_frontmatter_text(raw.decode("utf-8-sig"))
        # Reading orchestration/coding advice must not replace a business
        # workflow or satisfy selection before a real task Skill is chosen.
        if metadata.get("company-agent-role") != "support":
            route.update(selected={key: item[key] for key in ("id", "name", "path", "sha256")}, fallback=None)
        atomic_write_json(path, state)


def select(root: Path, project: Path, session_id: str, turn: str, *, name: str | None = None,
           fallback: str | None = None) -> dict:
    with _locked_session(session_id, root) as (state, path):
        route = state.get("skillWorkflow", {})
        if not turn or turn != state.get("turnId") or turn != route.get("turn"):
            raise ValueError("현재 업무의 선택 정보가 아닙니다.")
        data = _snapshot(root, project, route)
        if not route.get("indexRead"):
            raise ValueError("먼저 이 폴더의 스킬 목록을 읽어 주세요.")
        if fallback == "no-relevant-skill" and name is None:
            route.update(fallback=fallback, selected=None)
        elif name and fallback is None:
            candidates = [x for x in data["skills"] if x["name"].casefold() == name.casefold() and _allowed(x, data, route)]
            if len(candidates) != 1:
                raise ValueError("사용할 스킬의 출처 또는 우선 설정을 확인해 주세요.")
            item = candidates[0]
            _current(item, route)
            if route.get("readSkills", {}).get(item["id"]) != item["sha256"]:
                raise ValueError("선택한 SKILL.md를 먼저 끝까지 읽어 주세요.")
            route.update(selected={key: item[key] for key in ("id", "name", "path", "sha256")}, fallback=None)
        else:
            raise ValueError("스킬 이름 또는 관련 스킬 없음 중 하나를 선택하세요.")
        atomic_write_json(path, state)
        return {"ok": True, "selected": (route.get("selected") or {}).get("name"), "fallback": route.get("fallback")}


def internal_command(command: str, session_id: str, state: dict, root: Path) -> bool:
    from .execution_contract import _trusted_arguments, _fields, _same
    args = _trusted_arguments(command)
    if not args or args[:2] != ["skill", "route"]:
        return False
    fields = _fields(args[2:], {"--session", "--turn", "--name", "--fallback", "--state-root"}, {"--session", "--turn"})
    return bool(fields is not None and fields["--session"] == safe_session_id(session_id)
                and fields["--turn"] == state.get("turnId")
                and (("--name" in fields) != ("--fallback" in fields))
                and ("--fallback" not in fields or fields["--fallback"] == "no-relevant-skill")
                and ("--state-root" not in fields or _same(fields["--state-root"], root)))


def preflight(root: Path, project: Path, payload: dict) -> dict:
    """Check preparation before execution; never authorize the tool itself."""
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        return {}
    state = load_session(session_id, root)
    route = state.get("skillWorkflow")
    if not route or _stale_native_prompt(payload, state):
        return {}  # older clients/standalone hooks retain their existing policy
    tool = payload.get("tool_name", "")
    if tool in {"Bash", "PowerShell"}:
        from .execution_contract import _trusted_arguments, _skill_lookup, classify_command, _words
        from .state import _is_own_verification_command, _is_own_work_command, _is_own_learning_command
        inputs = payload.get("tool_input") or {}
        command = str(inputs.get("command") or inputs.get("cmd") or "")
        args = _trusted_arguments(command)
        words = _words(command)
        if words in (["pwd"], ["git", "status"], ["git", "status", "--short"]):
            return {}
        if (args and tuple(args[:2]) in {("business", "doctor"), ("business", "runtime-check"), ("business", "mail-capabilities")}
                and classify_command(command) == "read_only"):
            return {}
        if (internal_command(command, session_id, state, root)
                or (args and len(args) > 1 and args[0] == "skill" and _skill_lookup(args[1:]))
                or (args and len(args) > 1 and args[0] == "skill" and args[1] in {"prefer", "prefer-incoming", "order", "reset"})
                or _is_own_verification_command(command, session_id, root)
                or _is_own_work_command(command, session_id, state, root)
                or _is_own_learning_command(command, session_id, state, root)):
            return {}
    elif tool not in {"Write", "Edit", "MultiEdit", "NotebookEdit", "Agent", "Task"} and not tool.startswith("mcp__"):
        return {}
    try:
        if route.get("turn") != state.get("turnId", ""):
            raise ValueError("Current request preparation is missing")
        data = _snapshot(root, project, route)
        if not route.get("indexRead"):
            reason = f"먼저 스킬 목록을 Read로 읽고 업무에 맞는 스킬을 선택하세요: {route['catalog']}"
        elif route.get("selected"):
            selected = route["selected"]
            item = next((x for x in data["skills"] if x["id"] == selected["id"]), None)
            if item and _allowed(item, data, route):
                _current(item, route)
                return {}
            reason = "스킬 우선 설정을 다시 확인해 주세요. 다른 출처로 임의 대체하지 마세요."
        elif route.get("fallback") == "no-relevant-skill":
            return {}
        else:
            reason = ("목록에서 업무에 맞는 SKILL.md를 Read로 읽으세요. 이미 읽었으면 cliCommand 뒤에 "
                      f"skill route --session {safe_session_id(session_id)} --turn {route.get('turn', '')} --name NAME을 붙여 재사용하세요. "
                      "관련 스킬이 정말 없을 때만 --name NAME 대신 --fallback no-relevant-skill을 쓰세요.")
    except (OSError, ValueError, KeyError, TypeError):
        reason = "스킬 목록 또는 선택한 파일이 바뀌었습니다. 새 요청에서 목록을 갱신해 주세요."
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": reason + " 내부 준비 단계이며 승인 요청이나 검증 실패로 보고하지 마세요."}}
