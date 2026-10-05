"""Bind skill-choice answers to the question observed before the host UI.

Workspace/SDK can add answers to updatedInput. That is not model-authored
input if the same call was first observed without answers. Store only bounded
hash receipts, not questions/answers. Call under the existing session lock.
"""
from __future__ import annotations

import hashlib
import json

KEY = 'skillQuestionReceipts'
MAX_RECEIPTS = 4


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def _questions(value) -> str | None:
    if not isinstance(value, list) or not 1 <= len(value) <= 4:
        return None
    if any(not isinstance(q, dict) or not isinstance(q.get('options'), list)
           or not 1 <= len(q['options']) <= 4 for q in value):
        return None
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return _digest(value) if len(raw) <= 32768 else None
    except (TypeError, ValueError, RecursionError, UnicodeError):
        return None


def _call(payload: dict) -> str | None:
    value = payload.get('tool_use_id')
    if isinstance(value, str) and 0 < len(value) <= 256:
        try:
            return _digest(value)
        except UnicodeError:
            pass
    return None


def _context(state: dict, route: dict) -> str:
    return _digest([state.get('turnId'), route.get('turn'), route.get('revision'),
                    route.get('catalog'), state.get('nativePromptSha256')])


def pending(route: dict) -> bool:
    plan = route.get('executionPlan')
    host = route.get('hostChoice')
    plan = plan if isinstance(plan, dict) else {}
    host = host if isinstance(host, dict) else {}
    return bool(plan.get('choiceIds') or (host.get('selected') is not True
                and host.get('turn') == route.get('turn')
                and host.get('revision') == route.get('revision') and host.get('targetId')))


def prepare(state: dict, route: dict, payload: dict, language_result: dict) -> bool:
    if not pending(route) or not route.get('turn') or route['turn'] != state.get('turnId'):
        return False
    output = language_result.get('hookSpecificOutput', {})
    if output.get('permissionDecision') == 'deny':
        return False
    key = _call(payload)
    if not key:
        return False  # Legacy hosts without call IDs keep result-only handling.
    book = state.get(KEY)
    if not isinstance(book, dict) or book.get('version') != 1 or not isinstance(book.get('calls'), dict):
        book = state[KEY] = {'version': 1, 'calls': {}}
    calls = book['calls']
    if key in calls:
        # Do not replace the first observation (including consumed/invalid ones)
        # when a host repeats PreToolUse with its updatedInput.
        return False
    inputs = payload.get('tool_input') or {}
    updated = output.get('updatedInput', inputs)
    if not isinstance(inputs, dict) or not isinstance(updated, dict):
        calls[key] = {'eligible': False, 'consumed': False}
        while len(calls) > MAX_RECEIPTS:
            del calls[next(iter(calls))]
        return True
    hashes = [_questions(inputs.get('questions')), _questions(updated.get('questions'))]
    calls[key] = {'context': _context(state, route), 'questions': list(dict.fromkeys(hashes)),
                  'eligible': 'answers' not in inputs and all(hashes), 'consumed': False}
    while len(calls) > MAX_RECEIPTS:
        del calls[next(iter(calls))]
    return True


def consume(state: dict, route: dict, payload: dict) -> dict | None:
    """Return trusted parser input, or None. Never create a selection here."""
    inputs = payload.get('tool_input') or {}
    book = state.get(KEY)
    response = payload.get('tool_response')
    failed = (payload.get('hook_event_name') != 'PostToolUse' or payload.get('error')
              or payload.get('tool_error') or payload.get('is_interrupt')
              or not isinstance(inputs, dict)
              or not isinstance(response, dict) or response.get('success') is False
              or response.get('isError') or response.get('is_error'))
    if KEY not in state:
        # Older CLI sessions may have no Pre receipt. Preserve only the old
        # result-only shape; an unbound updatedInput.answers is never trusted.
        return inputs if not failed and 'answers' not in inputs else None
    if not isinstance(book, dict) or book.get('version') != 1 or not isinstance(book.get('calls'), dict):
        return None
    record = book['calls'].get(_call(payload))
    if not isinstance(record, dict) or record.get('consumed'):
        return None
    record['consumed'] = True  # Keep a tombstone; replay must not become legacy.
    if (failed or not record.get('eligible') or record.get('context') != _context(state, route)
            or route.get('turn') != state.get('turnId')
            or not isinstance(record.get('questions'), list)
            or _questions(inputs.get('questions')) not in record['questions']):
        return None
    if ('questions' in response and _questions(response['questions']) not in record['questions']):
        return None
    answers = response.get('answers')
    if not isinstance(answers, dict) or not answers or ('answers' in inputs and inputs['answers'] != answers):
        return None
    return {key: value for key, value in inputs.items() if key != 'answers'}
