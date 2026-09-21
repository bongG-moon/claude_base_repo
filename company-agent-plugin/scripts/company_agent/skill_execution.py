"""List-first preparation, never heuristic selection or fabricated load receipts.

Use the existing metadata snapshot. Only an observed unchanged body may be
reused; a shortlist miss still needs list review. No model call or body injection.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .paths import atomic_write_json
from .skill_task_context import _features
from .skill_decision import SkillDecision, decide_preparation
from .skill_workflow import _allowed, _current, _snapshot, _load_plan
from .state import _locked_session, load_session

MAX_REQUEST_CONTEXT_CHARS = 9_800
_DOMAIN_WORDS = {'slides': 'PPT', 'sheet': 'Excel', 'word': 'Word', 'html': 'HTML', 'mail': 'Outlook'}
_ACTION_WORDS = {'read': '읽기', 'make': '만들기', 'organize': '폴더 정리'}
_FOLLOWUP = re.compile(r'(?:그|해당|방금|아까|이전|같은|company|회사|공통).*(?:스킬|skill|읽|진행)|(?:스킬|skill).*(?:읽어|진행해)', re.I)


def native_load_required(project: Path) -> bool:
    """Leave configured loading restrictions to the host; never override them.

    Conservative: ANY explicit Read/Skill ask/deny or skill override keeps the
    native load path, even when a path-specific rule may concern another file.
    This is not a replacement for Claude's effective permission evaluation.
    """
    from .skill_registry import _json_read
    config = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')
    files = [config / 'settings.json', config / 'settings.local.json', config / 'managed-settings.json']
    files += [parent / '.claude' / name for parent in [project, *project.parents]
              for name in ('settings.json', 'settings.local.json')]
    if os.name == 'nt' and os.environ.get('ProgramFiles'):
        files.append(Path(os.environ['ProgramFiles']) / 'ClaudeCode/managed-settings.json')
    try:
        for file in dict.fromkeys(files):
            data = _json_read(file) or {}
            if data.get('skillOverrides'):
                return True
            permissions = data.get('permissions', {})
            if not isinstance(permissions, dict):
                return True
            for mode in ('ask', 'deny'):
                rules = permissions.get(mode, [])
                if not isinstance(rules, list):
                    return True
                if any(not isinstance(rule, str) or re.match(r'^(?:Read|Skill)(?:\(|$)', rule, re.I) for rule in rules):
                    return True
    except (OSError, ValueError, TypeError):
        return True
    return False


def routing_prompt(root: Path, project: Path, session: str, prompt: str) -> tuple[str, dict]:
    """Carry only finite intent labels on a short, explicit continuation.

    A new domain/action wins. No raw query, filename or conversation is saved.
    """
    from .skill_registry import _canonical
    domains, actions = _features(prompt)
    intent = {'domains': sorted(domains), 'actions': sorted(actions)}
    if not session or domains or len(prompt) > 140 or not _FOLLOWUP.search(prompt):
        return prompt, intent
    try:
        route = load_session(session, root).get('skillWorkflow', {})
    except (OSError, ValueError, TypeError):
        return prompt, intent
    if not isinstance(route, dict) or route.get('project') != _canonical(project):
        return prompt, intent
    old = route.get('skillIntent', {})
    if not isinstance(old, dict):
        return prompt, intent
    prior_domains = old.get('domains', [])
    prior_actions = old.get('actions', [])
    if (not isinstance(prior_domains, list) or not isinstance(prior_actions, list)
            or not prior_domains or not all(isinstance(x, str) and x in _DOMAIN_WORDS for x in prior_domains)
            or not all(isinstance(x, str) and x in _ACTION_WORDS for x in prior_actions)
            or (actions and not actions.issubset(set(prior_actions)))):
        return prompt, intent
    intent = {'domains': prior_domains, 'actions': sorted(actions) if actions else prior_actions}
    words = [_DOMAIN_WORDS[x] for x in intent['domains']] + [_ACTION_WORDS[x] for x in intent['actions']]
    return prompt + '\n' + ' '.join(words), intent


def prepare_execution(runtime: dict) -> tuple[dict, str]:
    """Suggest an existing load target; never equate delivery with selection."""
    hints = runtime.get('taskSkills', {})
    selection = runtime.get('skillSelection', {})
    if (not isinstance(hints, dict) or hints.get('status') in ('incomplete', 'check-catalog') or runtime.get('contextStatus')
            or selection.get('status') != 'ready' or selection.get('catalog', {}).get('status') != 'ready'):
        return {'mode': 'inspect', 'reason': 'catalog-not-complete'}, ''
    workflow = runtime.get('skillWorkflow', {})
    session = workflow.get('sessionId')
    if not session or not runtime.get('stateRoot') or not runtime.get('project'):
        return {'mode': 'inspect', 'reason': 'workflow-unavailable'}, ''
    root, project = Path(runtime['stateRoot']), Path(runtime['project'])
    try:
        route = load_session(session, root).get('skillWorkflow', {})
        if not isinstance(route, dict) or route.get('turn') != workflow.get('turn'):
            return {'mode': 'inspect', 'reason': 'stale-turn'}, ''
        data = _snapshot(root, project, route)
    except (OSError, ValueError, TypeError, KeyError):
        return {'mode': 'inspect', 'reason': 'catalog-unavailable'}, ''
    requested = route.get('explicit', []) + route.get('namedSkillChoices', [])
    if any(not any(x.get('invocation') == name or x.get('name') == name for x in data['skills']) for name in requested):
        # A user-named host Skill may exist outside the local catalogue. Never
        # substitute a keyword hit as a mandatory workflow in its place.
        return {'mode': 'inspect', 'reason': 'explicit-skill-outside-catalog'}, ''
    decision = decide_preparation(hints, data['skills'], route.get('explicit', []))
    chosen = route.get('requestChoice', {})
    selected_item = next((x for x in data['skills'] if x['id'] == chosen.get('id')), None)
    if selected_item and _allowed(selected_item, data, route):
        decision = SkillDecision('load', 'answered-choice', selected_item['id'])
    pending = route.get('pendingChoice', {})
    if pending and decision.mode != 'load':
        ids = pending.get('ids', [])
        items = [x for x in data['skills'] if x['id'] in ids]
        if 1 < len(items) == len(ids) <= 8:
            from .skill_task_context import load_target
            groups = {}
            for item in items:
                group = groups.setdefault(item['name'], {'name': item['name'], 'resolution': 'unresolved', 'candidates': []})
                group['candidates'].append({key: item.get(key, '') for key in ('id', 'name', 'source', 'path', 'invocation', 'description')}
                                           | {'load': load_target(item, data['skills'])})
            runtime['taskSkills'] = {'status': 'needs-choice', 'groups': list(groups.values()), 'competingIds': ids}
            decision = SkillDecision('choose', 'competing-workflows', choice_ids=tuple(ids))
    result = decision.plan()
    if ((decision.mode == 'load' or decision.choice_ids) and route.get('preparationCaution')
            and not (route.get('explicit') or route.get('namedSkillChoices'))):
        # Keep real catalogue hints visible, but do not turn a negated workflow
        # or a code diagnosis mentioning it into an execution prerequisite.
        return {'mode': 'select', 'reason': 'contextual-reference-needs-review'}, ''
    if decision.mode != 'load':
        if decision.choice_ids:
            result['choiceNames'] = list(dict.fromkeys(x['name'] for x in data['skills'] if x['id'] in decision.choice_ids))
        if decision.mode == 'review':
            result['catalogReviewed'] = bool(route.get('indexRead'))
        return result, ''
    try:
        item = next(x for x in data['skills'] if x['id'] == decision.candidate_id)
        if not _allowed(item, data, route):
            return {'mode': 'choose', 'reason': 'preference-changed'}, ''
        raw = _current(item, route)
        result = _load_plan(item, data, raw)
        if result.get('limitation'):
            return result, ''
        reads = route.get('readSkills', {})
        if not isinstance(reads, dict) or reads.get(item['id']) != item['sha256']:
            return result, ''
        # Permission settings and native-only semantics may have changed since
        # the last load. Never bypass them through cached/injected body text.
        if native_load_required(project):
            result['reason'] = 'host-loading-rules'
            return result, ''
        # Native-only semantics must be applied by Claude, not imitated by a
        # text injection (forks/models/tool restrictions/dynamic commands/etc).
        from .skill_registry import _frontmatter_field
        if result.get('nativeRequired') or _frontmatter_field(raw, 'company-agent-role') == 'support':
            result['reason'] = 'native-skill-semantics'
            return result, ''
        result.update(mode='reuse', basis='observed-body-load')
        return result, ''
    except (OSError, ValueError, TypeError, KeyError, StopIteration, UnicodeError):
        return {'mode': 'inspect', 'reason': 'selected-body-unavailable'}, ''


def record_execution(runtime: dict, execution: dict) -> None:
    """Persist bounded routing metadata, not a claim the model applied it."""
    workflow = runtime.get('skillWorkflow', {})
    session = workflow.get('sessionId')
    if not session:
        return
    try:
        with _locked_session(session, Path(runtime['stateRoot'])) as (state, path):
            route = state.get('skillWorkflow', {})
            if (not isinstance(route, dict) or route.get('turn') != workflow.get('turn')
                    or route.get('turn') != state.get('turnId')):
                return
            route['executionPlan'] = execution
            if execution.get('choiceIds'):
                route['pendingChoice'] = {'ids': execution['choiceIds'], 'names': execution.get('choiceNames', [])}
                route['requiredChoiceIds'] = execution['choiceIds']
            else:
                route.pop('pendingChoice', None)
            route['reviewProtocol'] = 1
            route.pop('providedSkills', None)  # Old delivery is not load evidence.
            if execution.get('mode') == 'reuse' and execution.get('basis') == 'observed-body-load':
                route['selected'] = {key: execution[key] for key in ('id', 'name', 'path', 'sha256')}
                route['fallback'] = None
            atomic_write_json(path, state)
    except (OSError, ValueError, KeyError, TypeError):
        pass  # Optional preparation cannot turn a valid request into a failure.
