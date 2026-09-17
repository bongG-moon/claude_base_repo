"""Skill-first preparation from the existing catalogue, without a tool gate.

One unambiguous, plain Skill body may be supplied before the model's first
action. This is context delivery, NOT a native Skill invocation, execution,
permission grant or proof of model adherence. No prompt/body text is persisted.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .frontmatter import parse_frontmatter_text
from .paths import atomic_write_json
from .skill_task_context import _features
from .skill_workflow import _allowed, _current, _snapshot
from .state import _locked_session, load_session

MAX_INLINE_BODY_CHARS = 8_000
MAX_REQUEST_CONTEXT_CHARS = 9_800
_PLAIN_FIELDS = {'name', 'description', 'status', 'metadata', 'license', 'compatibility', 'company-agent-role'}
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
    """Read at most the one resolved body; never choose between alternatives."""
    hints = runtime.get('taskSkills', {})
    groups = hints.get('groups', [])
    selection = runtime.get('skillSelection', {})
    if (hints.get('status') in {'incomplete', 'check-catalog'} or runtime.get('contextStatus')
            or selection.get('status') != 'ready' or selection.get('catalog', {}).get('status') != 'ready'):
        return {'mode': 'inspect', 'reason': 'catalog-not-complete'}, ''
    if not groups:
        return {'mode': 'general', 'reason': 'no-matching-candidate'}, ''
    if hints.get('status') == 'needs-choice':
        return {'mode': 'choose', 'reason': 'overlap-or-stale-preference'}, ''
    if len(groups) != 1 or hints.get('matchingGroups') != 1 or hints.get('moreInCatalog'):
        return {'mode': 'select', 'reason': 'compare-relevant-workflows'}, ''
    group = groups[0]
    if group.get('resolution') not in {'available', 'selected', 'explicit'} or len(group.get('candidates', [])) != 1:
        return {'mode': 'choose', 'reason': 'unresolved-choice'}, ''
    candidate = group['candidates'][0]
    result = {key: candidate.get(key, '') for key in ('id', 'name', 'source', 'path', 'invocation')}
    result.update(mode='load', load=candidate.get('load', {}))
    workflow = runtime.get('skillWorkflow', {})
    session = workflow.get('sessionId')
    if not session or not runtime.get('stateRoot') or not runtime.get('project'):
        return result, ''
    root, project = Path(runtime['stateRoot']), Path(runtime['project'])
    if native_load_required(project):
        result['reason'] = 'host-loading-rules'
        return result, ''
    try:
        state = load_session(session, root)
        route = state.get('skillWorkflow', {})
        if not isinstance(route, dict) or route.get('turn') != workflow.get('turn'):
            return {'mode': 'inspect', 'reason': 'stale-turn'}, ''
        data = _snapshot(root, project, route)
        item = next(x for x in data['skills'] if x['id'] == candidate['id'])
        if not _allowed(item, data, route):
            return {'mode': 'choose', 'reason': 'preference-changed'}, ''
        raw = _current(item, route)
        try:
            meta, body = parse_frontmatter_text(raw.decode('utf-8-sig'))
        except ValueError:
            result['reason'] = 'native-frontmatter-parser'
            return result, ''
        result['sha256'] = item['sha256']
        # Use the exact verified file, not a display-escaped metadata path.
        result['path'] = item['path']
        # Native-only semantics must be applied by Claude, not imitated by a
        # text injection (forks/models/tool restrictions/dynamic commands/etc).
        if (set(meta) - _PLAIN_FIELDS or '!`' in body or re.search(r'\$\{|\$ARGUMENTS|\$\d', body)
                or meta.get('company-agent-role') == 'support'):
            result['reason'] = 'native-skill-semantics'
            return result, ''
        reads = route.get('readSkills', {})
        if isinstance(reads, dict) and reads.get(item['id']) == item['sha256']:
            result.update(mode='reuse', basis='observed-body-load')
            return result, ''
        # A delivered body is distinct from Read/Skill evidence. Keep a small
        # reusable receipt, invalidated by compact/resume or actual file change.
        provided = route.get('providedSkills', {})
        if isinstance(provided, dict) and provided.get(item['id']) == item['sha256']:
            result.update(mode='reuse', basis='previous-output-not-receipt')
            return result, ''
        if len(body) > MAX_INLINE_BODY_CHARS or not body.strip():
            result['reason'] = 'native-load-for-large-body'
            return result, ''
        result.update(mode='provided', basis='hook-context-not-native-invocation')
        return result, body
    except (OSError, ValueError, TypeError, KeyError, StopIteration, UnicodeError):
        return {'mode': 'inspect', 'reason': 'selected-body-unavailable'}, ''


def body_context(execution: dict, body: str) -> str:
    if not body:
        return ''
    return ('[선택된 스킬 본문 — 먼저 이 절차를 적용]\n'
            f"스킬: {execution['name']}\n기준 폴더: {Path(execution['path']).parent}\n"
            '설치된 본문 전체입니다. 중복 로드하지 말고 필요한 참고 파일만 기준 폴더에서 읽으세요. '
            '사용자 요청·권한·회사 정책은 유지합니다.\n'
            + body + '\n[선택된 스킬 본문 끝]\n')


def record_execution(runtime: dict, execution: dict) -> None:
    """Only after the complete context fits; never fabricate a Read receipt."""
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
            if execution.get('mode') in {'provided', 'reuse'}:
                route['selected'] = {key: execution[key] for key in ('id', 'name', 'path', 'sha256')}
                route['fallback'] = None
                if execution['mode'] == 'provided':
                    cache = route.get('providedSkills', {})
                    cache = cache if isinstance(cache, dict) else {}
                    route['providedSkills'] = cache
                    cache[execution['id']] = execution['sha256']
                    while len(cache) > 16:
                        del cache[next(iter(cache))]
                    route['loadObservation'] = {'status': 'body-provided', 'turn': state.get('turnId'),
                                                'tool': 'HookContext'}
            atomic_write_json(path, state)
    except (OSError, ValueError, KeyError, TypeError):
        pass  # Optional preparation cannot turn a valid request into a failure.
