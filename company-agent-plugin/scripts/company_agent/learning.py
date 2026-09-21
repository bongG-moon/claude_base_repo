"""Bounded, local, evidence-linked learning; never executes a learned instruction.

Reviews are authored by Claude, not ground truth. Tool counts, verification
markers and exact Skill reads come from hooks. No prompt/transcript is retained.
Only this module's generated preferences/checklist sections may be changed.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterator

from .frontmatter import dump_frontmatter, parse_frontmatter_text
from .knowledge import (SECRET_PATTERNS, EMAIL_PATTERN, WINDOWS_USER_PATH_PATTERN,
                        POSIX_USER_PATH_PATTERN, SESSION_VALUE_PATTERN)
from .memory import _contains_raw_artifact
from .paths import atomic_write_json, atomic_write_text
from .state import _interprocess_lock, _thread_lock_for, _locked_session

MAX_SPEC_BYTES = 16_384
MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 65_536
MAX_REVIEWS = 500
MAX_CANDIDATES = 200
MAX_CHANGES = 200
MAX_ASSESSMENTS = 500
MAX_ACTIVE_PREFERENCES = 100
MAX_MEMORY_FILES = 500
MAX_LEARNED_BLOCK_CHARS = 4_000
BEGIN = "<!-- company-agent-learning:begin -->"
END = "<!-- company-agent-learning:end -->"
_SLUG = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_UNSAFE_LESSON = re.compile(
    r"```|<script\b|\b(?:ignore|override|bypass|disable|skip)\b.{0,45}"
    r"\b(?:instructions?|policy|policies|permissions?|approval|security|verification|tests?|safety)\b|"
    r"(?:권한|승인|보안|검증|정책|테스트).{0,16}(?:무시|우회|해제|생략|비활성)|"
    r"\b(?:rm\s+-rf|Remove-Item|Set-ExecutionPolicy|Invoke-Expression|eval\s*\(|exec\s*\(|"
    r"os\.system|subprocess\.|curl\s|powershell\s|cmd\s+/c|python\s+-c)\b|"
    r"\b(?:INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|DROP\s+TABLE|GRANT\s+ALL)\b|"
    r"\b(?:send|forward)\b.{0,30}\b(?:without|automatically)\b|"
    r"(?:메일|이메일).{0,16}(?:무조건|확인 없이|자동 발송)|"
    r"\bsk-[A-Za-z0-9_-]{16,}\b|-----BEGIN .*PRIVATE KEY-----",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _bounded_text(value: Any, limit: int, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label} must be nonempty text of at most {limit} characters")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError(f"{label} contains control characters")
    if (_contains_raw_artifact(value) or _UNSAFE_LESSON.search(value)
            or any(p.search(value) for p in (*SECRET_PATTERNS, EMAIL_PATTERN,
                   WINDOWS_USER_PATH_PATTERN, POSIX_USER_PATH_PATTERN, SESSION_VALUE_PATTERN))):
        raise ValueError(f"{label} must be an abstract non-sensitive lesson, not raw data, code or a policy change")
    if BEGIN in value or END in value:
        raise ValueError("owned learning markers cannot appear in review text")
    return value.strip()


def _slug(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) > 64 or not _SLUG.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase safe slug of at most 64 characters")
    return value


def _keys(value: Any, required: set[str], optional: set[str], label: str) -> None:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
        raise ValueError(f"{label} has missing or unsupported fields")


def _validate(spec: Any) -> dict[str, Any]:
    try:
        size = len(json.dumps(spec, ensure_ascii=False).encode("utf-8"))
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("review must be bounded JSON") from exc
    if size > MAX_SPEC_BYTES:
        raise ValueError("review exceeds bounded input limit")
    _keys(spec, {"schemaVersion", "taskType", "outcome", "summary", "observations", "evaluations"},
          {"priorFeedback"}, "review")
    if type(spec["schemaVersion"]) is not int or spec["schemaVersion"] != 1:
        raise ValueError("unsupported learning schema version")
    _slug(spec["taskType"], "taskType")
    if not isinstance(spec["outcome"], str) or spec["outcome"] not in {"success", "failure", "partial", "unknown"}:
        raise ValueError("unsupported outcome")
    _bounded_text(spec["summary"], 400, "summary")
    for field, maximum in (("observations", 5), ("evaluations", 8)):
        if not isinstance(spec[field], list) or len(spec[field]) > maximum:
            raise ValueError(f"{field} must be a bounded list")
    observation_keys = set()
    skill_names = set()
    for item in spec["observations"]:
        _keys(item, {"kind", "key", "signal", "title", "body"}, {"skillName"}, "observation")
        if not isinstance(item["kind"], str) or item["kind"] not in {"preference", "skill"}:
            raise ValueError("unsupported observation kind")
        if not isinstance(item["signal"], str) or item["signal"] not in {"explicit_correction", "repeated_choice", "verified_fix"}:
            raise ValueError("unsupported observation signal")
        _slug(item["key"], "key")
        _bounded_text(item["title"], 120, "title")
        _bounded_text(item["body"], 700, "body")
        if item["kind"] == "skill":
            _slug(item.get("skillName"), "skillName")
            if item["skillName"] in skill_names:
                raise ValueError("only one skill observation per skillName is allowed in a review")
            skill_names.add(item["skillName"])
        elif "skillName" in item or item["signal"] == "verified_fix":
            raise ValueError("preference observations must reflect user choices, not a verified fix")
        identity = (item["kind"], item["key"], item.get("skillName", ""))
        if identity in observation_keys:
            raise ValueError("duplicate observation key in one turn")
        observation_keys.add(identity)
    evaluated = set()
    for item in spec["evaluations"]:
        _keys(item, {"skillName", "sha256", "verdict"}, set(), "evaluation")
        _slug(item["skillName"], "skillName")
        if not isinstance(item["sha256"], str) or not _HASH.fullmatch(item["sha256"]):
            raise ValueError("evaluation must identify a SHA256 revision")
        if not isinstance(item["verdict"], str) or item["verdict"] not in {"helpful", "neutral", "harmful", "unknown"}:
            raise ValueError("unsupported evaluation verdict")
        if item["skillName"] in evaluated:
            raise ValueError("duplicate skill evaluation")
        evaluated.add(item["skillName"])
    if "priorFeedback" in spec:
        prior = spec["priorFeedback"]
        _keys(prior, {"turnId", "verdict"}, {"changeId"}, "priorFeedback")
        if (not isinstance(prior["turnId"], str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", prior["turnId"])
                or not isinstance(prior["verdict"], str) or prior["verdict"] not in {"accepted", "corrected"}):
            raise ValueError("invalid prior feedback")
        if "changeId" in prior and (prior["verdict"] != "corrected" or not isinstance(prior["changeId"], str)
                                     or not re.fullmatch(r"[0-9a-f]{32}", prior["changeId"])):
            raise ValueError("priorFeedback changeId must identify one corrected learned change")
    # Detach the caller's mutable objects before entering the transaction.
    return json.loads(json.dumps(spec))


def _safe(path: Path, root: Path) -> Path:
    """Reject junctions/symlinks, including ancestor directories, before I/O."""
    root = root.absolute()
    path = path.absolute()
    if not path.is_relative_to(root):
        raise ValueError("learning path escaped personal state")
    for component in (path, *path.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("learning refuses reparse/symlink paths")
        if component != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError("learning ancestor is not a directory")
    return path


def _read(path: Path, root: Path, maximum: int = MAX_FILE_BYTES) -> str:
    _safe(path, root)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
        raise ValueError("learning file exceeds bounded read limit")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("learning file exceeds bounded read limit")
    return data.decode("utf-8")


def _write(path: Path, root: Path, content: str) -> None:
    _safe(path, root)
    atomic_write_text(path, content)


def _default() -> dict[str, Any]:
    return {"schemaVersion": 1, "reviews": [], "candidates": {}, "changes": [],
            "assessments": [], "rejectionFilter": "0" * 8192,
            "totals": {"reviews": 0, "trimmedReviews": 0,
                                          "trimmedChanges": 0, "trimmedAssessments": 0}}


def _load(root: Path) -> dict[str, Any]:
    path = _safe(root / "learning" / "state.json", root)
    if not path.exists():
        return _default()
    value = json.loads(_read(path, root, MAX_STATE_BYTES))
    _keys(value, set(_default()), set(), "learning state")
    if (value["schemaVersion"] != 1 or not isinstance(value["candidates"], dict)
            or not isinstance(value["totals"], dict)
            or any(not isinstance(value[key], list) for key in ("reviews", "changes", "assessments"))):
        raise ValueError("invalid or unsupported learning state")
    try:
        if not isinstance(value["rejectionFilter"], str) or not re.fullmatch(r"[0-9a-f]{8192}", value["rejectionFilter"]):
            raise ValueError("invalid rejected-lesson digest")
        for review in value["reviews"]:
            if (not isinstance(review, dict) or not _HASH.fullmatch(review["id"])
                    or not _HASH.fullmatch(review["sessionFingerprint"]) or not isinstance(review["turnId"], str)
                    or not isinstance(review["status"], str) or not isinstance(review["evidence"], dict)
                    or not isinstance(review["usedSkills"], list)):
                raise ValueError("invalid learning review row")
            _slug(review["taskType"], "taskType")
            _bounded_text(review["summary"], 400, "summary")
            if review["reportedOutcome"] not in {"success", "failure", "partial", "unknown"}:
                raise ValueError("invalid stored outcome")
            for count in ("failures", "verificationFailures", "toolCount"):
                if type(review["evidence"][count]) is not int or not 0 <= review["evidence"][count] <= 1_000_000:
                    raise ValueError("invalid learning evidence count")
        for key, candidate in value["candidates"].items():
            if not _HASH.fullmatch(key) or not isinstance(candidate, dict) or not isinstance(candidate["reviews"], list):
                raise ValueError("invalid learning candidate row")
            _slug(candidate["key"], "key")
            _bounded_text(candidate["title"], 120, "title")
            _bounded_text(candidate["body"], 700, "body")
            if not isinstance(candidate["status"], str):
                raise ValueError("invalid learning candidate status")
        for change in value["changes"]:
            if (not isinstance(change, dict) or not re.fullmatch(r"[0-9a-f]{32}", change["id"])
                    or not _HASH.fullmatch(change["beforeSha256"]) or not _HASH.fullmatch(change["afterSha256"])
                    or not _HASH.fullmatch(change["candidateId"]) or not isinstance(change["status"], str)):
                raise ValueError("invalid learning change row")
            _target(root, change)
            _slug(change["taskType"], "taskType")
            if (not _HASH.fullmatch(change["reviewId"]) or not _HASH.fullmatch(change["sessionFingerprint"])
                    or not isinstance(change["createdAt"], str)):
                raise ValueError("invalid learning change provenance")
            _bounded_text(change["title"], 120, "title")
            if change["kind"] == "skill":
                if (not isinstance(change["afterBlock"], str) or len(change["afterBlock"]) > MAX_LEARNED_BLOCK_CHARS
                        or _block(change["afterBlock"]) != change["afterBlock"]
                        or change["beforeBlock"] is not None and (not isinstance(change["beforeBlock"], str)
                            or len(change["beforeBlock"]) > MAX_LEARNED_BLOCK_CHARS)):
                    raise ValueError("invalid learned section backup")
                if "skillEntryKeys" in change:
                    keys = change["skillEntryKeys"]
                    if (not isinstance(keys, list) or len(keys) > 8
                            or len(keys) != len(_checklist_lines(change["afterBlock"]))):
                        raise ValueError("invalid learned checklist identities")
                    for key in keys:
                        if key is not None:
                            _slug(key, "stored checklist key")
            elif any(not isinstance(change[field], str) or len(change[field].encode("utf-8")) > MAX_FILE_BYTES
                     for field in ("beforeContent", "afterContent")):
                raise ValueError("invalid learned preference backup")
        for assessment in value["assessments"]:
            if (not isinstance(assessment, dict) or not isinstance(assessment["evidence"], dict)
                    or not re.fullmatch(r"[0-9a-f]{32}", assessment["changeId"])
                    or not _HASH.fullmatch(assessment["reviewId"])):
                raise ValueError("invalid learning assessment row")
            _slug(assessment["taskType"], "taskType")
            for field in ("failures", "verificationFailures", "toolCount"):
                if type(assessment["evidence"][field]) is not int:
                    raise ValueError("invalid assessment evidence")
        if any(type(number) is not int or number < 0 for number in value["totals"].values()):
            raise ValueError("invalid learning totals")
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("corrupt learning state; existing files preserved") from exc
    return value


def _rejection(data: dict[str, Any], identifier: str, *, add: bool = False) -> bool:
    # Fixed-size conservative tombstone digest: never forget a rejected lesson
    # when rolling metadata expires. Collisions can only defer extra lessons.
    bits = int(data["rejectionFilter"], 16)
    masks = [1 << (int(identifier[offset:offset + 8], 16) % 32768) for offset in (0, 8, 16)]
    present = all(bits & mask for mask in masks)
    if add:
        for mask in masks:
            bits |= mask
        data["rejectionFilter"] = f"{bits:08192x}"
    return present


def _trim(data: dict[str, Any]) -> None:
    for key, limit, counter in (("reviews", MAX_REVIEWS, "trimmedReviews"),
                                ("assessments", MAX_ASSESSMENTS, "trimmedAssessments")):
        surplus = max(0, len(data[key]) - limit)
        if surplus:
            del data[key][:surplus]
            data["totals"][counter] = data["totals"].get(counter, 0) + surplus
    # One write-ahead replacement may temporarily coexist with its active
    # predecessor. Its commit supersedes the predecessor before final trimming.
    prepared = sum(c["status"] == "prepared" for c in data["changes"])
    while len(data["changes"]) > MAX_CHANGES + min(prepared, 1):
        removable = next((i for i, change in enumerate(data["changes"])
                          if change["status"] not in {"active", "prepared"}), None)
        if removable is None:
            raise ValueError("active reversible learning change limit reached")
        del data["changes"][removable]
        data["totals"]["trimmedChanges"] = data["totals"].get("trimmedChanges", 0) + 1


def _save(root: Path, data: dict[str, Any]) -> None:
    _trim(data)
    rendered = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if len(rendered.encode("utf-8")) > MAX_STATE_BYTES:
        raise ValueError("learning state exceeds bounded storage limit")
    _write(root / "learning" / "state.json", root, rendered)


@contextmanager
def _locked(root: Path) -> Iterator[dict[str, Any]]:
    root = root.absolute()
    lock = _safe(root / "learning" / "state.lock", root)
    with _thread_lock_for(lock):
        with _interprocess_lock(lock):
            data = _load(root)
            recovered = False
            for change in data["changes"]:
                if change["status"] not in {"prepared", "rollback_prepared"}:
                    continue
                path = _target(root, change)
                try:
                    current = _read(path, root)
                    if change["status"] == "rollback_prepared":
                        change["status"] = "rolled_back" if _hash(current) == change.get("rollbackSha256") else "blocked_conflict"
                        if change["status"] == "rolled_back":
                            for candidate in data["candidates"].values():
                                if candidate.get("changeId") == change["id"]:
                                    candidate["status"] = "rejected"
                            _restore_previous_skill_owner(data, change, current)
                    else:
                        change["status"] = "active" if _hash(current) == change["afterSha256"] else "interrupted"
                        if change["status"] == "active":
                            for old in data["changes"]:
                                if old is not change and old["status"] == "active" and _target(root, old) == path:
                                    old["status"] = "superseded"
                except (OSError, ValueError, UnicodeError):
                    change["status"] = "blocked_conflict"
                recovered = True
            for review in data["reviews"]:
                if review["status"] == "processing":
                    review["status"] = "interrupted"
                    recovered = True
            if recovered:
                _save(root, data)
            yield data


def learning_enabled(root: Path) -> bool:
    try:
        path = _safe(root / "config" / "learning.json", root)
        if not path.exists():
            return True
        value = json.loads(_read(path, root, 2_048))
        return value == {"schemaVersion": 1, "enabled": True}
    except (OSError, ValueError, UnicodeError, TypeError):
        return False


def set_learning_enabled(root: Path, enabled: bool) -> dict[str, Any]:
    if type(enabled) is not bool:
        raise ValueError("enabled must be boolean")
    with _locked(root):
        path = _safe(root / "config" / "learning.json", root)
        atomic_write_json(path, {"schemaVersion": 1, "enabled": enabled})
    return {"enabled": enabled, "existingMemoriesAndSkillsPreserved": True}


def _evidence(session: dict[str, Any]) -> dict[str, Any]:
    def count(key: str) -> int:
        value = session.get(key, 0)
        return min(1_000_000, max(0, value)) if type(value) is int else 0
    verification = session.get("verification")
    status = verification.get("status") if isinstance(verification, dict) else None
    return {"toolCount": count("taskToolCount"), "failures": count("taskFailureCount"),
            "verificationFailures": count("taskVerificationFailures"),
            "verification": status if status in {"pass", "fail"} else "unknown",
            "verificationSource": "agent_recorded_marker_not_independent_test_execution"}


def _defer_reason(exc: Exception) -> str:
    if isinstance(exc, (OSError, UnicodeError)):
        return "personal source is unavailable or has invalid encoding; existing content preserved"
    message = str(exc)
    # Parser errors may quote original metadata or paths. Never copy them into
    # a distilled learning record; our own bounded static reasons remain useful.
    if "<memory>" in message or "frontmatter" in message.casefold() or "scalar" in message.casefold():
        return "personal source metadata is invalid; existing content preserved"
    try:
        return _bounded_text(message, 180, "deferred reason")
    except ValueError:
        return "personal source could not be safely updated; existing content preserved"


def _read_skill(root: Path, name: str, session: dict[str, Any]) -> tuple[Path, str, str]:
    _slug(name, "skillName")
    path = _safe(root / "personal-root" / ".claude" / "skills" / name / "SKILL.md", root)
    raw = _read(path, root)
    digest = _hash(raw)
    used = session.get("usedSkills", [])
    if not isinstance(used, list) or not any(
        isinstance(item, dict) and item.get("name") == name and item.get("sha256") == digest
        and Path(str(item.get("path", ""))).absolute() == path
        for item in used[:8]
    ):
        raise ValueError("skill must have been read this turn at its unchanged personal revision")
    metadata, _ = parse_frontmatter_text(raw)
    if metadata.get("name") not in {None, name}:
        raise ValueError("skill name does not match personal directory")
    return path, raw, digest


def _block(raw: str) -> str | None:
    if BEGIN not in raw and END not in raw:
        return None
    if raw.count(BEGIN) != 1 or raw.count(END) != 1 or raw.index(BEGIN) >= raw.index(END):
        raise ValueError("ambiguous owned learned section")
    return raw[raw.index(BEGIN):raw.index(END) + len(END)]


def _target(root: Path, change: dict[str, Any]) -> Path:
    if change["kind"] == "skill":
        name = _slug(change["skillName"], "skillName")
        return _safe(root / "personal-root" / ".claude" / "skills" / name / "SKILL.md", root)
    if change["kind"] != "preference" or not re.fullmatch(r"learning\.preference\.[0-9a-f]{24}", change["memoryId"]):
        raise ValueError("invalid learning target")
    return _safe(root / "memory" / "items" / (change["memoryId"] + ".md"), root)


def _checklist_lines(block: str | None) -> list[str]:
    return [line for line in (block or "").splitlines() if line.startswith("- ")]


def _skill_entry_keys(data: dict[str, Any], name: str, block: str | None) -> list[str | None]:
    """Recover legacy identities only from owned history, never from prose similarity."""
    lines = _checklist_lines(block)
    history = [c for c in data["changes"] if c["kind"] == "skill" and c["skillName"] == name]
    for change in reversed(history):
        if (_checklist_lines(change["afterBlock"]) == lines and "skillEntryKeys" in change):
            return list(change["skillEntryKeys"])
    identities: dict[str, set[str]] = {}
    for change in history:
        after = _checklist_lines(change["afterBlock"])
        if "skillEntryKeys" in change:
            pairs = zip(after, change["skillEntryKeys"])
        else:
            # Legacy versions appended one entry per change, with the same
            # bounded eight-entry window. Removed history cannot be invented.
            before = _checklist_lines(change["beforeBlock"])
            pairs = ((line, change["key"]) for line in after if line not in before)
        for line, key in pairs:
            if key is not None:
                identities.setdefault(line, set()).add(_slug(key, "stored checklist key"))
    return [next(iter(identities[line])) if len(identities.get(line, ())) == 1 else None for line in lines]


def _candidate_is_current(root: Path, data: dict[str, Any], observation: dict[str, Any], candidate_id: str) -> bool:
    """A retained candidate receipt is not proof that its lesson is still active."""
    try:
        if observation["kind"] == "preference":
            change = next((c for c in reversed(data["changes"]) if c["status"] == "active"
                           and c["candidateId"] == candidate_id), None)
            return change is not None and _hash(_read(_target(root, change), root)) == change["afterSha256"]
        name = observation["skillName"]
        owner = next((c for c in reversed(data["changes"]) if c["kind"] == "skill"
                      and c["status"] == "active" and c["skillName"] == name), None)
        if owner is None:
            return False
        block = _block(_read(_target(root, owner), root))
        if block is None or block.replace("\r\n", "\n") != owner["afterBlock"].replace("\r\n", "\n"):
            return False
        matching = [line for line, key in zip(_checklist_lines(block), _skill_entry_keys(data, name, block))
                    if key == observation["key"]]
        entry = f"- {observation['title']}: {' '.join(observation['body'].split())}"
        return matching == [entry]
    except (OSError, UnicodeError, ValueError):
        return False


def _human_conflict(root: Path, observation: dict[str, Any]) -> bool:
    folder = _safe(root / "memory" / "items", root)
    if not folder.exists():
        return False
    terms = set(re.findall(r"[\w]+", (observation["title"] + " " + observation["key"]).casefold()))
    count = 0
    with os.scandir(folder) as entries:
        for entry in entries:
            count += 1
            if count > MAX_MEMORY_FILES:
                raise ValueError("memory scan limit reached; existing preferences preserved")
            if not entry.name.casefold().endswith(".md"):
                continue
            metadata, body = parse_frontmatter_text(_read(Path(entry.path), root))
            if metadata.get("kind") != "preference" or metadata.get("status") != "active":
                continue
            if metadata.get("source") == "automatic_learning" and str(metadata.get("id", "")).startswith("learning.preference."):
                continue
            other = set(re.findall(r"[\w]+", str(metadata.get("title", "")).casefold()))
            if terms & other or observation["key"] in str(metadata.get("id", "")) or body.strip() == observation["body"].strip():
                return True
    return False


def _commit_change(root: Path, data: dict[str, Any], review: dict[str, Any], observation: dict[str, Any],
                   session: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    identifier = _hash(review["id"] + candidate_id)[:32]
    change: dict[str, Any] = {"id": identifier, "reviewId": review["id"], "turnId": review["turnId"],
                             "candidateId": candidate_id,
                             "sessionFingerprint": review["sessionFingerprint"], "taskType": review["taskType"],
                             "kind": observation["kind"], "key": observation["key"],
                             "title": observation["title"], "createdAt": _now(), "status": "prepared"}
    if observation["kind"] == "preference":
        if _human_conflict(root, observation):
            raise ValueError("existing human preference may overlap; automatic change deferred")
        memory_id = "learning.preference." + _hash(observation["key"])[:24]
        change["memoryId"] = memory_id
        path = _target(root, change)
        before = _read(path, root) if path.exists() else ""
        revision = 1
        if before:
            metadata, _ = parse_frontmatter_text(before)
            known = any(c.get("memoryId") == memory_id and (
                        c["status"] == "active" and c["afterSha256"] == _hash(before)
                        or c["status"] == "rolled_back" and c.get("rollbackSha256") == _hash(before)
                        and observation["signal"] == "explicit_correction")
                        for c in data["changes"])
            if metadata.get("source") != "automatic_learning" or not known:
                raise ValueError("existing learned preference was manually edited or has no owned revision")
            revision = int(metadata.get("revision", 0)) + 1
        active_preferences = {c.get("memoryId") for c in data["changes"] if c["status"] == "active" and c["kind"] == "preference"}
        if memory_id not in active_preferences and len(active_preferences) >= MAX_ACTIVE_PREFERENCES:
            raise ValueError("active preference limit reached; consolidate existing preferences first")
        rendered = dump_frontmatter({"kind": "preference", "id": memory_id, "title": observation["title"],
                                    "scope": "personal", "owner": "local-user", "source": "automatic_learning",
                                    "status": "active", "revision": revision, "updated_at": _now()}, observation["body"])
        change.update({"beforeContent": before, "afterContent": rendered})
    else:
        change["skillName"] = observation["skillName"]
        path, before, _ = _read_skill(root, observation["skillName"], session)
        prior_block = _block(before)
        if prior_block is not None and not any(c.get("skillName") == observation["skillName"] and c["status"] == "active"
                                               and str(c.get("afterBlock", "")).replace("\r\n", "\n") == prior_block.replace("\r\n", "\n")
                                               for c in data["changes"]):
            raise ValueError("learned section was manually edited or has no owned revision")
        entry = f"- {observation['title']}: {' '.join(observation['body'].split())}"
        keys = _skill_entry_keys(data, observation["skillName"], prior_block)
        if any(key is None for key in keys):
            raise ValueError("legacy checklist identity is unavailable; existing lessons preserved for review")
        entries = list(zip(_checklist_lines(prior_block), keys))
        position = next((i for i, (_, key) in enumerate(entries) if key == observation["key"]), len(entries))
        entries = [(line, key) for line, key in entries if key != observation["key"]]
        entries.insert(min(position, len(entries)), (entry, observation["key"]))
        entries = entries[-8:]
        lines = [line for line, _ in entries]
        new_block = BEGIN + "\n\n### Personal learned checklist\n\n" + "\n".join(lines) + "\n\n" + END
        if len(new_block) > MAX_LEARNED_BLOCK_CHARS:
            raise ValueError("learned checklist is full; consolidate existing lessons first")
        rendered = before.replace(prior_block, new_block, 1) if prior_block else before + "\n\n" + new_block + "\n"
        if len(rendered.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("skill exceeds bounded size after learning")
        change.update({"beforeBlock": prior_block, "afterBlock": new_block,
                       "skillEntryKeys": [key for _, key in entries]})
    change.update({"beforeSha256": _hash(before), "afterSha256": _hash(rendered)})
    active = [c for c in data["changes"] if c["status"] in {"active", "prepared"}]
    if len(active) >= MAX_CHANGES and not any(_target(root, old) == path for old in active):
        raise ValueError("active reversible change limit reached")
    # Write-ahead record contains only generated content, never whole Skill bodies.
    data["changes"].append(change)
    _save(root, data)
    latest = _read(path, root) if path.exists() else ""
    if _hash(latest) != change["beforeSha256"]:
        change["status"] = "blocked_conflict"
        _save(root, data)
        raise ValueError("personal file changed during review; manual changes preserved")
    _write(path, root, rendered)
    for old in data["changes"]:
        if old is not change and old["status"] == "active" and _target(root, old) == path:
            old["status"] = "superseded"
    change["status"] = "active"
    _save(root, data)
    return {"id": identifier, "kind": change["kind"], "title": change["title"], "status": "active"}


def _restore_previous_skill_owner(data: dict[str, Any], change: dict[str, Any], rendered: str) -> None:
    if change["kind"] != "skill" or change["beforeBlock"] is None:
        return
    restored = _block(rendered)
    for old in reversed(data["changes"]):
        if (old["status"] == "superseded" and old.get("skillName") == change["skillName"]
                and old.get("afterBlock") == change["beforeBlock"] and restored == change["beforeBlock"]):
            old["status"] = "active"
            # The original revision hash remains immutable for audit. The
            # effective restored hash includes preserved outside-section edits.
            old["currentSha256"] = _hash(rendered)
            break


def _rollback(root: Path, data: dict[str, Any], change: dict[str, Any], reason: str) -> dict[str, Any]:
    if change["status"] != "active":
        return {"id": change["id"], "status": change["status"], "changed": False}
    path = _target(root, change)
    try:
        current = _read(path, root)
        if change["kind"] == "preference":
            if _hash(current) != change["afterSha256"]:
                raise ValueError("learned preference has manual changes")
            metadata, body = parse_frontmatter_text(current)
            metadata["status"] = "inactive"
            metadata["updated_at"] = _now()
            rendered = dump_frontmatter(metadata, body)
        else:
            current_block = _block(current)
            if current_block is None or current_block.replace("\r\n", "\n") != change["afterBlock"].replace("\r\n", "\n"):
                raise ValueError("learned skill section has manual or newer changes")
            if change["beforeBlock"] is None and _hash(current) == change["afterSha256"]:
                rendered = current.removesuffix("\n\n" + change["afterBlock"] + "\n")
            else:
                rendered = current.replace(current_block, change["beforeBlock"] or "", 1)
        change["status"] = "rollback_prepared"
        change["rollbackSha256"] = _hash(rendered)
        change["rollbackReason"] = reason
        _rejection(data, change["candidateId"], add=True)
        _save(root, data)
        if _read(path, root) != current:
            raise ValueError("personal file changed during rollback")
        _write(path, root, rendered)
        change["status"] = "rolled_back"
        change["rollbackReason"] = reason
        change["rolledBackAt"] = _now()
        for candidate in data["candidates"].values():
            if candidate.get("changeId") == change["id"]:
                candidate["status"] = "rejected"
        _restore_previous_skill_owner(data, change, rendered)
        return {"id": change["id"], "status": "rolled_back", "changed": True}
    except (OSError, UnicodeError, ValueError):
        change["status"] = "blocked_conflict"
        change["rollbackReason"] = "manual_or_newer_revision_preserved"
        return {"id": change["id"], "status": "blocked_conflict", "changed": False}


def rollback_change(root: Path, change_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", str(change_id)):
        raise ValueError("invalid learning change id")
    with _locked(root) as data:
        change = next((c for c in data["changes"] if c["id"] == change_id), None)
        if change is None:
            raise ValueError("learning change is not in retained reversible history")
        result = _rollback(root, data, change, "user_requested")
        _save(root, data)
        return result


def _assess(root: Path, data: dict[str, Any], review: dict[str, Any], spec: dict[str, Any],
            session: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for evaluation in spec["evaluations"]:
        try:
            _, _, digest = _read_skill(root, evaluation["skillName"], session)
        except (OSError, ValueError, UnicodeError):
            results.append({"skillName": evaluation["skillName"], "status": "unsubstantiated_revision"})
            continue
        if digest != evaluation["sha256"]:
            results.append({"skillName": evaluation["skillName"], "status": "unsubstantiated_revision"})
            continue
        change = next((c for c in reversed(data["changes"]) if c["kind"] == "skill" and c["status"] == "active"
                       and c["skillName"] == evaluation["skillName"] and c.get("currentSha256", c["afterSha256"]) == digest
                       and c["reviewId"] != review["id"]), None)
        if not change:
            continue
        baseline = [r for r in data["reviews"] if r["taskType"] == review["taskType"] and r["id"] != review["id"]
                    and any(u.get("name") == evaluation["skillName"] and u.get("sha256") == change["beforeSha256"]
                            for u in r.get("usedSkills", []))][-20:]
        baseline = list({r.get("workFingerprint", r["id"]): r for r in baseline
                         if r.get("workFingerprint", r["id"]) != review.get("workFingerprint", review["id"])}.values())
        after = [a for a in data["assessments"] if a.get("changeId") == change["id"]
                 and a.get("taskType") == review["taskType"]][-19:]
        work_fingerprint = review.get("workFingerprint", review["id"])
        # Re-evaluation may amend the verdict but cannot create independent
        # samples from repeated replies in one work unit.
        after = list({a.get("workFingerprint", a["reviewId"]): a for a in after
                      if a.get("workFingerprint", a["reviewId"]) != work_fingerprint}.values())
        assessment = {"changeId": change["id"], "reviewId": review["id"], "taskType": review["taskType"],
                      "workFingerprint": work_fingerprint,
                      "skillName": evaluation["skillName"], "sha256": digest, "verdict": evaluation["verdict"],
                      "verdictSource": "agent_interpretation", "evidence": review["evidence"],
                      "baselineSamples": len(baseline), "afterSamples": len(after) + 1,
                      "confidence": "observational" if len(baseline) >= 3 and len(after) >= 2 else "insufficient_data",
                      "causalClaim": False, "status": "recorded"}
        if baseline:
            assessment["baselineAverageFailures"] = sum(r["evidence"]["failures"] + r["evidence"]["verificationFailures"] for r in baseline) / len(baseline)
            assessment["afterAverageFailures"] = sum(a["evidence"]["failures"] + a["evidence"]["verificationFailures"] for a in after + [assessment]) / (len(after) + 1)
        if evaluation["verdict"] == "harmful":
            assessment["rollback"] = _rollback(root, data, change, "next_use_reported_harmful")
        data["assessments"] = [a for a in data["assessments"] if not
            (a.get("changeId") == change["id"] and a.get("taskType") == review["taskType"] and
             a.get("workFingerprint", a.get("reviewId")) == work_fingerprint)]
        data["assessments"].append(assessment)
        results.append(assessment)
    prior = spec.get("priorFeedback")
    if prior:
        if prior["turnId"] != session.get("previousTurnId"):
            raise ValueError("priorFeedback must reference the immediately previous user turn")
        previous = next((r for r in reversed(data["reviews"]) if r["turnId"] == prior["turnId"]
                         and r["sessionFingerprint"] == review["sessionFingerprint"]), None)
        if previous:
            previous["userFeedback"] = prior["verdict"]
            if prior["verdict"] == "corrected" and "changeId" in prior:
                for change in data["changes"]:
                    if change["id"] == prior["changeId"] and change["reviewId"] == previous["id"] and change["status"] == "active":
                        results.append({"priorFeedback": "corrected", "rollback": _rollback(root, data, change, "next_turn_user_correction")})
    return results


def _submit_locked(root: Path, session_id: str, turn_id: str, spec: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(turn_id, str) or not turn_id or session.get("turnId") != turn_id:
        raise ValueError("stale or unknown learning turn; submit the current turn only")
    if spec.get("priorFeedback", {}).get("turnId", session.get("previousTurnId")) != session.get("previousTurnId"):
        raise ValueError("priorFeedback must reference the immediately previous user turn")
    if not learning_enabled(root):
        return {"status": "disabled", "changes": [], "assessments": []}
    if session.get("protectionRestricted"):
        # Protected-source turns may finish, but cannot feed free text or
        # evaluations into automatic personal learning. Existing state survives.
        spec = {"schemaVersion": 1, "taskType": "protected-material", "outcome": "partial",
                "summary": "보호 또는 접근 제한 항목을 제외했습니다. 이 세션의 자동 개인화 자료는 저장하지 않았습니다.",
                "observations": [], "evaluations": []}
    review_id = _hash(session_id + "\0" + turn_id)
    with _locked(root) as data:
        if session.get("learningDeferredReason") == "late-business-activity":
            raise ValueError("business activity followed the recorded review; learning remains deferred until the next user turn")
        existing = next((r for r in data["reviews"] if r["id"] == review_id), None)
        if existing:
            # An interrupted first review may predate the session-side identity
            # write. The persisted review remains the authority for that turn.
            if existing["taskType"] != spec["taskType"]:
                raise ValueError(f"taskType mismatch for existing review; use taskType '{existing['taskType']}'")
            return {"status": "duplicate" if existing["status"] == "complete" else "deferred",
                    "reviewId": review_id, "originalStatus": existing["status"],
                    "changes": [], "assessments": []}
        if session.get("learningStatus") in {"complete", "completed", "skipped", "disabled"}:
            raise ValueError("learning is already closed for this turn")
        evidence = _evidence(session)
        mutation_count = session.get("mutationCount", 0)
        if (type(mutation_count) is not int or mutation_count < 0
                or mutation_count > 0 and evidence["verification"] != "pass"
                and not (type(session.get("sameFailureCount")) is int and session["sameFailureCount"] >= 2)
                and not (type(session.get("stopRetryCount")) is int and session["stopRetryCount"] >= 2)):
            raise ValueError("finish the required bounded verification before submitting learning")
        prior = spec.get("priorFeedback")
        if prior and "changeId" in prior:
            previous = next((r for r in reversed(data["reviews"]) if r["turnId"] == prior["turnId"]
                             and r["sessionFingerprint"] == _hash(session_id)), None)
            if previous is None or not any(c["id"] == prior["changeId"] and c["reviewId"] == previous["id"]
                                           and c["status"] == "active" for c in data["changes"]):
                raise ValueError("priorFeedback changeId must be an active change from the previous user turn")
        used = [{"name": item["name"], "sha256": item["sha256"]} for item in session.get("usedSkills", [])[:8]
                if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("sha256"), str)
                and _SLUG.fullmatch(item["name"]) and _HASH.fullmatch(item["sha256"])]
        review = {"id": review_id, "sessionFingerprint": _hash(session_id), "turnId": turn_id, "at": _now(),
                  "status": "processing", "taskType": spec["taskType"], "reportedOutcome": spec["outcome"],
                  "summary": spec["summary"], "evidence": _evidence(session), "usedSkills": used}
        if isinstance(session.get("work"), dict):
            review["workFingerprint"] = _hash(session_id + "\0work\0" + session["work"]["id"])
        data["reviews"].append(review)
        data["totals"]["reviews"] += 1
        _save(root, data)
        assessments = _assess(root, data, review, spec, session)
        changes = []
        for observation in spec["observations"]:
            candidate_id = _hash(json.dumps([observation["kind"], observation["key"], observation.get("skillName"),
                                            observation["title"], observation["body"]], ensure_ascii=False))
            candidate = data["candidates"].get(candidate_id)
            if candidate is None:
                if len(data["candidates"]) >= MAX_CANDIDATES:
                    oldest = min(data["candidates"], key=lambda key: data["candidates"][key].get("lastSeen", ""))
                    del data["candidates"][oldest]
                candidate = {"kind": observation["kind"], "key": observation["key"], "title": observation["title"],
                             "body": observation["body"], "reviews": [], "choiceReviews": [],
                             "status": "rejected" if _rejection(data, candidate_id) else "observing"}
                owned_active = next((c for c in data["changes"] if c["status"] == "active"
                                     and c["candidateId"] == candidate_id), None)
                if owned_active is not None:
                    candidate.update({"status": "active", "changeId": owned_active["id"]})
                data["candidates"][candidate_id] = candidate
            if review_id not in candidate["reviews"]:
                candidate["reviews"] = (candidate["reviews"] + [review_id])[-8:]
            candidate["lastSeen"] = _now()
            candidate["signal"] = observation["signal"]
            if candidate["status"] == "active" and not _candidate_is_current(root, data, observation, candidate_id):
                candidate["status"] = "observing"
                # Votes collected before a newer correction cannot outweigh
                # that correction on the first later inferred choice.
                candidate["choiceReviews"] = []
            # Several corrections/retries in one business task are one sample,
            # even if the model submits them in different user turns.
            choice_id = _hash(session_id + "\0work\0" + session["work"]["id"]) if isinstance(session.get("work"), dict) else review_id
            if observation["signal"] == "repeated_choice" and choice_id not in candidate.get("choiceReviews", []):
                candidate["choiceReviews"] = (candidate.get("choiceReviews", []) + [choice_id])[-8:]
            evidence = review["evidence"]
            eligible = (observation["signal"] == "explicit_correction"
                        or observation["signal"] == "repeated_choice" and len(candidate.get("choiceReviews", [])) >= 2
                        or observation["signal"] == "verified_fix" and evidence["verification"] == "pass"
                        and evidence["failures"] + evidence["verificationFailures"] > 0)
            if not eligible or candidate["status"] in {"active", "rejected"}:
                changes.append({"kind": observation["kind"], "key": observation["key"], "status": candidate["status"]})
                continue
            try:
                change = _commit_change(root, data, review, observation, session, candidate_id)
                changes.append(change)
                candidate.update({"status": "active", "changeId": change["id"]})
            except (OSError, ValueError, UnicodeError) as exc:
                candidate["status"] = "deferred"
                candidate["reason"] = _defer_reason(exc)
                changes.append({"kind": observation["kind"], "key": observation["key"], "status": "deferred", "reason": candidate["reason"]})
        review["status"] = "complete"
        _save(root, data)
        return {"status": "accepted", "reviewId": review_id, "changes": changes, "assessments": assessments,
                "evidence": review["evidence"], "rawSessionStored": False}


def submit_review(root: Path, session_id: str, turn_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    spec = _validate(spec)
    _safe(root / "sessions", root)
    # Consistent lock order: session first, then learning. begin_turn cannot
    # replace the user-turn evidence halfway through a review or activation.
    with _locked_session(session_id, root) as (session, path):
        from .work import merge_observations, review_finished, task_type
        if session.get("turnId") != turn_id:
            raise ValueError("stale or unknown learning turn; submit the current turn only")
        if not learning_enabled(root):
            return {"status": "disabled", "changes": [], "assessments": []}
        if session.get("protectionRestricted"):
            return {"status": "disabled", "reason": "protected_session", "changes": [], "assessments": []}
        if session.get("learningDeferredReason") == "late-business-activity":
            raise ValueError("business activity followed the recorded review; learning remains deferred until the next user turn")
        work = session.get("work") or {}
        if (work and session.get("learningStatus") != "complete" and
                (work.get("status") != "complete" or not work.get("reviewRequested"))):
            raise ValueError("learning requires a completed work milestone with new evidence; stage unfinished feedback instead")
        identity = task_type(work, spec["taskType"])
        spec["observations"] = merge_observations(work.get("pending", []), spec["observations"], work.get("processed", []))
        # Revalidate persisted candidates too; local state is not trusted input.
        spec = _validate(spec)
        evidence_session = dict(session)
        if work:
            evidence_session["taskToolCount"] = max(session.get("taskToolCount", 0), work.get("toolCount", 0))
            evidence_session["taskFailureCount"] = max(session.get("taskFailureCount", 0), work.get("failures", 0))
            evidence_session["taskVerificationFailures"] = max(session.get("taskVerificationFailures", 0), work.get("verificationFailures", 0))
            evidence_session["usedSkills"] = list({item["name"]: item for item in
                work.get("usedSkills", []) + session.get("usedSkills", [])}.values())[-8:]
        # A caller that discovers no reusable evidence creates no empty ledger
        # row. Still require current identity and completed verification.
        if (not spec["observations"] and not spec["evaluations"] and not spec.get("priorFeedback")
                and session.get("learningStatus") != "complete"):
            if session.get("turnId") != turn_id:
                raise ValueError("stale learning turn")
            if session.get("mutationCount", 0) and (session.get("verification") or {}).get("status") != "pass":
                raise ValueError("verify business changes before closing the milestone")
            result = {"status": "skipped", "reason": "no_new_evidence", "changes": [], "assessments": []}
        else:
            result = _submit_locked(root, session_id, turn_id, spec, evidence_session)
        if result["status"] in {"accepted", "duplicate", "skipped"}:
            if work:
                work["taskType"] = identity
            session["learningStatus"] = "complete"
            session["learningCompletedAt"] = _now()
            review_finished(session, spec["observations"])
            atomic_write_json(path, session)
        elif result["status"] == "deferred":
            if work:
                work["taskType"] = identity
            session["learningStatus"] = "deferred"
            session["learningDeferredReason"] = "interrupted-review"
            atomic_write_json(path, session)
        return result


def _change_summary(change: dict[str, Any]) -> dict[str, Any]:
    result = {key: change[key] for key in ("id", "kind", "title", "status", "createdAt", "taskType", "turnId")}
    if change["kind"] == "skill":
        result.update({"skillName": change["skillName"],
                       "sha256": change.get("currentSha256", change["afterSha256"])})
    else:
        result["memoryId"] = change["memoryId"]
    return result


def learning_status(root: Path, *, session: dict[str, Any] | None = None) -> dict[str, Any]:
    # Status is read-only: it does not create folders or recover transactions.
    data = _load(root)
    relevant: list[dict[str, Any]] = []
    if isinstance(session, dict):
        used = list({item["name"]: item for item in (session.get("work") or {}).get("usedSkills", []) +
                     session.get("usedSkills", []) if isinstance(item, dict) and "name" in item}.values())[-8:]
        if isinstance(used, list):
            for observed in used[:8]:
                if not isinstance(observed, dict):
                    continue
                match = next((c for c in reversed(data["changes"]) if c["kind"] == "skill" and c["status"] == "active"
                              and c["skillName"] == observed.get("name")
                              and c.get("currentSha256", c["afterSha256"]) == observed.get("sha256")), None)
                if match is not None and not any(item["id"] == match["id"] for item in relevant):
                    relevant.append(_change_summary(match))
        session_id, previous = session.get("sessionId"), session.get("previousTurnId")
        if isinstance(session_id, str) and 0 < len(session_id) <= 100 and isinstance(previous, str) and previous:
            previous_changes = [c for c in data["changes"] if c["sessionFingerprint"] == _hash(session_id)
                                and c["turnId"] == previous][-5:]
            for change in previous_changes:
                if not any(item["id"] == change["id"] for item in relevant):
                    relevant.append(_change_summary(change))
    from .work import task_type
    return {"enabled": learning_enabled(root), "schemaVersion": 1, "totals": data["totals"],
            "workTaskType": task_type((session or {}).get("work") or {}),
            "retainedReviews": len(data["reviews"]), "candidateCount": len(data["candidates"]),
            "activeChanges": sum(c["status"] == "active" for c in data["changes"]),
            "recentCandidates": [{"key": c["key"], "kind": c["kind"], "title": c["title"], "body": c["body"],
                                  "signal": c.get("signal"), "observedUserTurns": len(c["reviews"]),
                                  "userChoiceTurns": len(c.get("choiceReviews", [])),
                                  "status": c["status"], "reason": c.get("reason")}
                                 for c in sorted(data["candidates"].values(), key=lambda c: c.get("lastSeen", ""))[-10:]],
            "recentReviews": [{key: r[key] for key in ("taskType", "summary", "reportedOutcome", "evidence", "status")}
                              for r in data["reviews"][-5:]],
            "recentChanges": [_change_summary(c) for c in data["changes"][-10:]],
            "relevantChanges": relevant[:13],
            "recentAssessments": data["assessments"][-5:],
            "retention": {"reviewWindow": MAX_REVIEWS, "candidateWindow": MAX_CANDIDATES,
                          "changeWindow": MAX_CHANGES, "assessmentWindow": MAX_ASSESSMENTS,
                          "rejectedLessons": "persistent_bounded_conservative_digest",
                          "originalMemoryAndSkillFilesPruned": False},
            "claims": {"rawSessionStored": False, "modelWeightsTrained": False,
                       "evaluationIsObservational": True, "verificationMarkerIsAgentReported": True}}
