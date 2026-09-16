"""Per-request hints from the existing inventory, not a semantic router.

No file-type dispatch, body loading, model call, permissions or preference writes.
An unresolved name keeps all its alternatives, never just its top-scored one.
"""
from __future__ import annotations

from collections import defaultdict
import json
import re

from .skill_registry import _resolution

MAX_TASK_SKILL_CHARS = 3000
TASK_SKILL_RULE = (
    '업무 실행 전에 taskSkills 후보 설명과 전체 skillIndex를 비교하고 필요한 SKILL.md만 Read로 읽으세요. '
    '후보는 검색 힌트이지 자동 선택이나 전체 목록이 아닙니다. 읽기와 생성처럼 서로 다른 단계의 스킬은 중복이 아닙니다. '
    '같은 업무를 수행할 후보가 겹치고 명시 선택·저장된 우선 설정이 없으면 AskUserQuestion으로 '
    '이름·출처·차이를 한국어로 보여주고 하나를 물으세요. 도구가 없으면 질문 후 답변을 기다리세요. '
    '사용자 대신 선택하지 말고 /company-agent:skills 실행을 사용자에게 떠넘기지 마세요. '
    '답을 받으면 cliCommand 뒤에 skill choose --session SESSION --turn TURN --candidate ID를 붙여 '
    '이번 요청의 선택만 기록한 뒤 반환된 readPath를 읽으세요. 이미 읽은 동일 본문은 재사용하세요. '
    '기본값·프로젝트 우선 설정 저장은 별도 요청이 있을 때만 합니다. '
    '후보가 없거나 불완전하면 전체 목록을 확인하며, 본문을 읽지 않은 채 임의 코드로 대체하지 마세요.'
)


def task_candidates(inventory: dict, prompt: str) -> dict:
    if not prompt.strip():
        return {}
    if not inventory.get('complete', False):
        return {'status': 'incomplete', 'groups': [], 'nextAction': 'check-catalog'}
    items = [x for x in inventory.get('skills', []) if not x.get('incoming')]
    explicit = re.findall(r'(?<!\S)/([A-Za-z0-9][A-Za-z0-9:_-]{0,159})(?=\s|$)', prompt)
    words = re.findall(r'[a-z0-9_-]{2,}|[가-힣]{2,}', prompt[:2000].casefold())[:64]
    # Korean particles are not whitespace-delimited. Bigrams are weak search
    # evidence only; never a decision to execute a workflow.
    grams = {word[i:i+2] for word in words if re.fullmatch('[가-힣]+', word)
             for i in range(len(word)-1)}
    def score(item):
        name = str(item.get('name', '')).casefold()
        text = name + ' ' + str(item.get('description', '')).casefold()
        return sum(4 + 2 * (word in name) for word in set(words) if word in text) + sum(g in text for g in grams)
    groups = defaultdict(list)
    for item in items:
        groups[item['name'].casefold()].append(item)
    ranked = []
    preferences = inventory.get('effectivePreferences', {'skills': {}, 'sourceOrder': []})
    for name, candidates in groups.items():
        resolution = _resolution(name, candidates, preferences)
        named = [x for x in candidates if x.get('invocation') in explicit]
        if len(named) == 1:
            options, status = named, 'explicit'
        elif resolution.get('selectedId') and resolution['status'] != 'stale-choice':
            options = [x for x in candidates if x['id'] == resolution['selectedId']]
            status = resolution['status']
        else:
            options, status = candidates, resolution['status']
        eligible = [x for x in options if not x.get('explicitOnly') or x.get('invocation') in explicit]
        rank = max((score(x) for x in eligible), default=0)
        if not eligible or (not rank and not named):
            continue
        # Do not silently drop manual-only alternatives from an unresolved group.
        rows = [{key: x.get(key, '') for key in ('id', 'name', 'source', 'path', 'invocation', 'explicitOnly')}
                | {'description': ' '.join(x.get('description', '').split())[:240]} for x in options]
        ranked.append((10000 if named else rank, {'name': name, 'resolution': status, 'candidates': rows}))
    ranked.sort(key=lambda x: (-x[0], x[1]['name']))
    result = {'status': 'candidates' if ranked else 'no-keyword-match',
              'groups': [], 'matchingGroups': len(ranked), 'shortlistOnly': True}
    for _, group in ranked[:3]:
        result['groups'].append(group)
        if len(json.dumps(result, ensure_ascii=False, separators=(',', ':'))) > MAX_TASK_SKILL_CHARS - 128:
            result['groups'].pop()
            result['moreInCatalog'] = True
            break
    if any(g['resolution'] in {'unresolved', 'stale-choice'} for g in result['groups']):
        result['status'] = 'needs-choice'
    if ranked and not result['groups']:
        result['status'] = 'check-catalog'
    return result
