"""Bounded work milestones; no raw prompts, timed daemon or implicit success."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from .paths import atomic_write_json


def new_work() -> dict:
    return {"id": uuid.uuid4().hex, "status": "active", "reviewRequested": False,
            "closed": False, "taskType": None,
            "pending": [], "usedSkills": [], "toolCount": 0, "failures": 0,
            "verificationFailures": 0, "processed": [], "revision": 0}


def observation_id(item: dict) -> str:
    return hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def task_type(work: dict, incoming: str | None = None) -> str | None:
    """Validate a bounded identity without silently relabeling an existing work.

    Legacy work has no identity until its next valid staged or accepted review.
    Do not infer an identity from arbitrary titles or sensitive observation text.
    """
    from .learning import _slug
    existing = work.get("taskType")
    if existing is not None:
        _slug(existing, "stored work.taskType")
    if incoming is not None:
        _slug(incoming, "taskType")
        if existing is not None and incoming != existing:
            raise ValueError(f"taskType mismatch for current work; use taskType '{existing}'. Start new work only for a genuinely different task")
    return existing if existing is not None else incoming


def merge_observations(first: list, second: list, processed: list = ()) -> list:
    merged = {}
    for item in first + second:
        # Repeated observations in one work are not independent evidence. A
        # fresh explicit correction can, however, restore a previous value
        # (A -> B -> A); the learning ledger compares it with the current file.
        if observation_id(item) in processed and item["signal"] != "explicit_correction":
            continue
        identity = (item["kind"], item.get("skillName") if item["kind"] == "skill" else item["key"])
        previous = merged.get(identity)
        if previous and previous != item and item["signal"] != "explicit_correction":
            raise ValueError("conflicting pending feedback; reconcile explicitly before staging")
        merged[identity] = item
    if len(merged) > 5:
        raise ValueError("at most five pending lessons; consolidate before staging; previous candidates preserved")
    return list(merged.values())


def checkpoint(root: Path, session_id: str, turn_id: str, status: str, *,
               new: bool = False, learn: bool = False, spec: dict | None = None) -> dict:
    from .state import _locked_session, _collect_learning_observations
    from .learning import _validate
    if status not in {"active", "waiting", "complete", "cancelled"}:
        raise ValueError("invalid work status")
    # Same bounded/redacted contract as permanent learning. Never buffer raw text.
    validated = _validate(spec) if spec is not None else None
    observations = validated["observations"] if validated is not None else []
    with _locked_session(session_id, root) as (state, path):
        if state.get("turnId") != turn_id:
            raise ValueError("work checkpoint must belong to the current turn")
        work = state.setdefault("work", new_work())
        if new:
            unresolved = state.get("mutationCount", 0) and (state.get("verification") or {}).get("status") != "pass"
            exhausted = state.get("stopRetryCount", 0) >= 2 or state.get("sameFailureCount", 0) >= 2
            if work.get("pending") or (unresolved and not (exhausted and (work.get("closed") or work.get("status") in {"complete", "cancelled"}))):
                raise ValueError("finish/cancel pending learning and resolve verification before new work")
            if unresolved:
                history = state.setdefault("unresolvedChanges", [])
                if len(history) >= 8:
                    raise ValueError("unresolved work limit reached; review outstanding changes before new work")
                history.append({"workId": work["id"], "mutationCount": state["mutationCount"],
                                "verificationStatus": (state.get("verification") or {}).get("status", "unverified"),
                                "reason": "bounded_attempts_exhausted_not_resolved"})
                state.update(mutationCount=0, verification=None, stopRetryCount=0, sameFailureCount=0,
                             lastFailureFingerprint=None)
            work = state["work"] = new_work()
            state.update(taskToolCount=0, taskFailureCount=0, taskVerificationFailures=0, usedSkills=[])
        enabled = _collect_learning_observations(state, root)
        if enabled and not state.get("protectionRestricted"):
            identity = task_type(work, validated["taskType"] if validated is not None else None)
            work["pending"] = merge_observations(work.get("pending", []), observations, work.get("processed", []))
            work["taskType"] = identity
        else:
            work["pending"] = []
        if status == "cancelled":
            work["pending"] = []
        work["status"] = status
        work["closed"] = status in {"complete", "cancelled"}
        work["reviewRequested"] = bool(enabled and not state.get("protectionRestricted") and
                                       status == "complete" and (learn or work["pending"]))
        # A late checkpoint cannot manufacture another review for the same turn.
        if state.get("learningStatus") != "complete" and work["reviewRequested"]:
            state["learningStatus"] = "pending"
        atomic_write_json(path, state)
        return {"ok": True, "workId": work["id"], "status": status, "taskType": task_type(work),
                "pendingCount": len(work["pending"]), "reviewRequested": work["reviewRequested"],
                "unresolvedWorkCount": len(state.get("unresolvedChanges", []))}


def review_finished(state: dict, observations: list) -> None:
    work = state.get("work")
    if not isinstance(work, dict):
        return
    work["processed"] = list(dict.fromkeys(work.get("processed", []) +
                             [observation_id(item) for item in observations]))[-64:]
    work["pending"] = []
    work["reviewRequested"] = False
    work["status"] = "complete"
    work["closed"] = True
    work.update(toolCount=0, failures=0, verificationFailures=0, usedSkills=[])


def context(state: dict) -> dict:
    work = state.get("work") or {}
    return {"id": work.get("id"), "status": work.get("status", "active"), "taskType": task_type(work),
            "unresolvedWorkCount": len(state.get("unresolvedChanges", [])),
            "pendingCount": len(work.get("pending", [])),
            "reviewRequested": bool(work.get("reviewRequested")),
            "pendingRetrieval": "learning status --session <current-session>"}


def resolve_unfinished(root: Path, session_id: str, turn_id: str, work_id: str) -> dict:
    """Link a newly verified remediation to one archived obligation.

    Never delete evidence or claim all prior work was repaired. The actual
    remediation's deterministic check is supplied via normal session verify.
    """
    from .state import _locked_session
    with _locked_session(session_id, root) as (state, path):
        if state.get("turnId") != turn_id:
            raise ValueError("resolution requires the current turn")
        verification = state.get("verification") or {}
        if verification.get("status") != "pass" or verification.get("at", "") < state.get("turnStartedAt", ""):
            raise ValueError("inspect/remediate the named prior work and record a current verification first")
        outstanding = state.get("unresolvedChanges", [])
        selected = next((item for item in outstanding if item.get("workId") == work_id), None)
        if selected is None:
            raise ValueError("unknown unresolved work ID")
        history = state.get("resolvedChanges", [])
        if len(history) >= 64:
            raise ValueError("resolved history is full; preserve records for administrator review")
        state["resolvedChanges"] = history + [{**selected, "resolution": "current_verification_linked",
            "resolvedAt": verification["at"], "resolutionTurnId": turn_id}]
        state["unresolvedChanges"] = [item for item in outstanding if item is not selected]
        atomic_write_json(path, state)
        return {"ok": True, "resolvedWorkId": work_id, "unresolvedWorkCount": len(state["unresolvedChanges"])}
