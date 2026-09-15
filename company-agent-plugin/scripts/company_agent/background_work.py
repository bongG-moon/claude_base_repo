"""Bounded execution metadata, never worker prompts or document contents."""
from __future__ import annotations

import re
import time

_ACTIVE = {"running", "pending", "queued", "in_progress"}
_TERMINAL = {"completed", "failed", "stopped", "cancelled", "killed"}
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_LEASE = 1800  # Old clients without a live registry must not defer forever.


def _identifier(value):
    return value if isinstance(value, str) and _ID.fullmatch(value) else None


def _status(value):
    return value if isinstance(value, str) else ""


def observe(state, payload, failed):
    now = time.time()
    entries = state.get("backgroundWork", {})
    entries = {key: stamp for key, stamp in entries.items()
               if _identifier(key) and isinstance(stamp, (int, float))
               and 0 <= now - stamp < _LEASE} if isinstance(entries, dict) else {}
    response = payload.get("tool_response")
    inputs = payload.get("tool_input")
    inputs = inputs if isinstance(inputs, dict) else {}
    if isinstance(response, dict) and not failed:
        tool = payload.get("tool_name")
        if tool in {"Agent", "Task"} and (response.get("isAsync") is True or inputs.get("run_in_background") is True):
            identity = _identifier(response.get("agentId") or response.get("task_id"))
            if identity and _status(response.get("status")) not in _TERMINAL:
                entries[identity] = now
        elif tool == "TaskOutput":
            task = response.get("task")
            task = task if isinstance(task, dict) else response
            identity = _identifier(task.get("task_id") or task.get("id") or inputs.get("task_id"))
            if identity in entries:
                if _status(task.get("status")) in _TERMINAL:
                    entries.pop(identity, None)
                elif _status(task.get("status")) in _ACTIVE:
                    entries[identity] = now
    state["backgroundWork"] = dict(list(entries.items())[-32:])


def is_running(payload, state):
    tasks = payload.get("background_tasks")
    if isinstance(tasks, list):
        # The current native registry is authoritative, including an empty list.
        # Monitors/cron schedules must not suppress ordinary completion checks.
        return any(isinstance(item, dict) and _identifier(item.get("id"))
                   and _status(item.get("type")) in {"subagent", "shell"}
                   and _status(item.get("status")) in _ACTIVE for item in tasks)
    entries = state.get("backgroundWork", {})
    now = time.time()
    return isinstance(entries, dict) and any(
        _identifier(key) and isinstance(stamp, (int, float)) and 0 <= now - stamp < _LEASE
        for key, stamp in entries.items())
