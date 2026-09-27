"""Current-request choices for successful native Skills outside the file catalogue.

The host can expose built-in/remote skills without a local SKILL.md. Their
observed invocation is evidence of a load, not a catalogue entry, relevance
judgement, reusable body receipt or permission grant. This module does no IO.
"""
from __future__ import annotations

import re

_INVOCATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,159}\Z")
_NEGATIVE = re.compile(r"말고|대신|취소|아니|안\s*쓸|쓰지|하지\s*마|둘\s*다|모두|"
                       r"\b(?:not|cancel|instead|never|none|neither|both)\b", re.I)


def _current(route: dict) -> dict | None:
    choice = route.get('hostChoice')
    if (isinstance(choice, dict) and choice.get('turn') == route.get('turn')
            and choice.get('revision') == route.get('revision')
            and _INVOCATION.fullmatch(str(choice.get('invocation', '')))
            and isinstance(choice.get('targetId'), str)):
        return choice
    return None


def _target(choice: dict, data: dict) -> dict | None:
    items = [item for item in data.get('skills', []) if item.get('id') == choice['targetId']]
    return items[0] if len(items) == 1 else None


def _guidance(choice: dict, target: dict) -> str:
    return (f"[스킬 선택] 이미 불러온 {choice['invocation']}와 목록의 "
            f"{target.get('invocation') or target['name']} 중 이번 업무에 사용할 것을 "
            "한국어로 한 번 물으세요. 같은 역할인지 설명을 비교하고, 두 이름을 선택지에 표시하세요. "
            "디자인 보조만 필요하면 제작 스킬을 선택하고 필요한 보조만 재사용하세요. "
            "선택 전 재작성·중복 로드하지 마세요. 권한 승인은 별도입니다.")


def register(route: dict, invocation: str, data: dict) -> str | None:
    """Call only after a successful, unique native load outside the catalogue."""
    if not isinstance(invocation, str) or not _INVOCATION.fullmatch(invocation):
        return None
    if invocation in route.get('explicit', []) or invocation in route.get('namedSkillChoices', []):
        return None
    plan = route.get('executionPlan', {})
    if plan.get('mode') not in {'load', 'reuse'}:
        return None
    choice = {'invocation': invocation, 'targetId': plan.get('id'),
              'turn': route.get('turn'), 'revision': route.get('revision'), 'selected': False}
    target = _target(choice, data)
    if not target or not route.get('turn') or not route.get('revision'):
        return None
    if any(item.get('invocation') == invocation for item in data.get('skills', [])):
        return None  # Known skills follow the catalogue's normal choice rules.
    named = route.get('explicit', []) + route.get('namedSkillChoices', [])
    selected = route.get('selected') or {}
    prepared = next((item for item in data.get('skills', []) if item.get('id') == selected.get('id')
                     and (item['id'] == target['id'] or item.get('name') in named or item.get('invocation') in named
                          or route.get('turnChoices', {}).get(item.get('name', '').casefold()) == item['id'])
                     and item.get('sha256') and route.get('readSkills', {}).get(item['id']) == item['sha256']), None)
    if (prepared or any(target.get(key) in named for key in ('name', 'invocation'))
            or route.get('turnChoices', {}).get(target.get('name', '').casefold()) == target['id']):
        return (f"{invocation} 로드를 확인했습니다. 이미 선택한 제작 절차를 유지하고, "
                "이 스킬은 필요한 보조 기능일 때만 사용하세요. 두 절차를 모두 실행할 필요는 없습니다.")
    if _current(route):
        return None  # Repeated loads cannot replace an unresolved/user-made choice.
    route['hostChoice'] = choice
    return _guidance(choice, target)


def chosen(route: dict) -> bool:
    choice = _current(route)
    return bool(choice and choice.get('selected') is True)


def checkpoint(route: dict, data: dict) -> dict | None:
    """Return only a workflow-choice denial, never an authorization/allow."""
    choice = _current(route)
    if not choice or choice.get('selected') is True:
        return None
    target = _target(choice, data)
    if not target:
        return None
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                  'permissionDecisionReason': _guidance(choice, target)}}


def _identity(text: str, choice: dict, target: dict) -> str | None:
    if not isinstance(text, str) or len(text) > 1000 or _NEGATIVE.search(text):
        return None
    def has(value):
        return bool(value and re.search(r'(?<![A-Za-z0-9:_-])' + re.escape(value)
                                       + r'(?![A-Za-z0-9:_-])', text, re.I))
    host = has(choice['invocation'])
    local = any(has(target.get(key)) for key in ('id', 'name', 'invocation'))
    return 'host' if host and not local else 'local' if local and not host else None


def _short_identity(text: str, choice: dict, target: dict) -> str | None:
    kind = _identity(text, choice, target)
    values = [choice['invocation']] if kind == 'host' else [target.get(key) for key in ('id', 'name', 'invocation')]
    suffix = r'\s*(?:스킬)?\s*(?:로|으로|을|를)?\s*(?:(?:선택|사용|진행)(?:해줘|해주세요|할게요|합니다)?|해줘|해주세요)?[.!]?'
    return kind if kind and any(value and re.fullmatch(re.escape(value) + suffix, text.strip(), re.I)
                               for value in values) else None


def observe_answer(route: dict, data: dict, inputs: dict, response) -> dict | None:
    """Accept actual returned answers to exactly two identifiable options only."""
    choice = _current(route)
    if (not choice or choice.get('selected') is True or 'answers' in inputs
            or not isinstance(response, dict) or response.get('success') is False
            or response.get('isError') or response.get('is_error')):
        return None
    target = _target(choice, data)
    questions, answers = inputs.get('questions'), response.get('answers')
    if not target or not isinstance(questions, list) or not isinstance(answers, dict):
        return None
    observed = set()
    for question in questions[:4]:
        if not isinstance(question, dict) or question.get('multiSelect'):
            continue
        options = question.get('options')
        answer = answers.get(question.get('question'))
        if not isinstance(options, list) or len(options) != 2 or not isinstance(answer, str):
            continue
        mapping = {}
        for option in options:
            if not isinstance(option, dict) or not isinstance(option.get('label'), str):
                continue
            kind = _identity(option['label'] + ' ' + str(option.get('description', '')), choice, target)
            if kind:
                mapping[option['label']] = kind
        if len(mapping) != 2 or set(mapping.values()) != {'host', 'local'} or _NEGATIVE.search(answer):
            continue
        kind = mapping.get(answer) or _short_identity(answer, choice, target)
        if kind:
            observed.add(kind)
    if len(observed) != 1:
        return None
    kind = observed.pop()
    if kind == 'host':
        choice['selected'] = True
        return {'kind': 'host'}
    return {'kind': 'local', 'id': choice['targetId']}


def continuation(route: dict, prompt: str, newturn: str, newrevision: str) -> dict | None:
    """Carry a short exact-name reply, not numeric guesses or a new task."""
    choice = _current(route)
    if (not choice or newrevision != choice['revision'] or not newturn
            or not isinstance(prompt, str) or len(prompt) > 180 or _NEGATIVE.search(prompt)):
        return None
    plan = route.get('executionPlan', {})
    target = {'id': choice['targetId'], 'name': plan.get('name'), 'invocation': plan.get('invocation')}
    kind = _short_identity(prompt, choice, target)
    if not kind:
        return None
    return {**choice, 'turn': newturn, 'revision': newrevision, 'selected': kind == 'host'}
