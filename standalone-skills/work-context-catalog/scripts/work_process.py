"""Bounded requested steps and separately observed, redacted tool traces.

Only normalized noun phrases and known action labels leave this module. Tool
arguments, assistant output and full user requests are never exported evidence.
"""
from __future__ import annotations

from collections import Counter
import hashlib
from html.parser import HTMLParser
import re

MAX_REQUESTS = 96
MAX_STEPS = 8
ACTION_LABELS = {
    'read': '자료 읽기', 'dedupe': '중복 제거', 'filter': '대상 선별',
    'clean': '데이터 정리', 'aggregate': '집계·계산', 'join': '자료 연결',
    'analyze': '내용 분석', 'visualize': '도식화', 'write': '결과물 작성',
    'verify': '결과 확인', 'fix': '오류·내용 수정', 'publish': '저장·전달',
}
_PATTERNS = [
    ('dedupe', r'중복(?:\s*(?:신청|행|데이터))?(?:을|를)?\s*(?:제거|정리)|\b(?:remove\s+duplicates|deduplicate|dedup)\b'),
    ('read', r'읽(?:어|고|기|은|어서)|불러오|불러와|추출|\b(?:read|load|extract)\b'),
    ('filter', r'필터|추려|선별|제외|거르|\bfilter\b'),
    ('clean', r'전처리|정제|변환|정규화|정리|\b(?:clean|transform|normalize)\b'),
    ('aggregate', r'집계|합산|계산|\b(?:aggregate|calculate|group\s+by|sum)\b'),
    ('join', r'매칭|조인|병합|결합|연결|\b(?:join|merge|match)\b'),
    ('analyze', r'분석|파악|조회|검색|검토|\b(?:analyze|analyse|query|search|review)\b'),
    ('visualize', r'시각화|그려|그리(?:기|는|면|도록|자)|도식화'),
    ('write', r'작성|제작|생성|만들|만든|\b(?:create|write|generate|build)\b'),
    ('verify', r'검증|대조|비교|확인|테스트|점검|\b(?:validate|verify|compare|check|test)\b'),
    ('fix', r'수정|고쳐|개선|고치|\b(?:fix|update|repair)\b'),
    ('publish', r'배포|게시|전송|발송|저장|내보내|기억해|기억하|기억해둬|\b(?:publish|export|save|send|deploy)\b'),
]
ACTION = re.compile('|'.join('(?P<' + key + '>' + expression + ')' for key, expression in _PATTERNS), re.I)
GENERIC = {'자료', '데이터', '파일', '내용', '결과', '결과물', '표', '목록', '현황', '보고서', '리포트',
    '업무', '작업', '코드', '구조', '부분', '다음', '이번', '이전', '그것', '이것', '해당', '전체',
    '우선', '다시', '계속', '먼저', '나중', '함께', '관련', '기존', '직접', '새로운', '하나', '모든',
    '엑셀', 'excel', 'csv', 'xlsx', 'xlsm', 'html', 'ppt', 'pptx', 'pdf', 'json', 'python', 'md',
    'file', 'files', 'data', 'report', 'result', 'table', 'output'}
FILLER = {'줘', '주세요', '해줘', '해', '해주고', '해준', '하고', '해서', '한', '후', '뒤', '다음',
    '다음에', '그다음', '다음으로', '그리고', '또', '이제', '좀', '우선', '먼저', '바탕으로',
    '기반으로', '그', '위', '아래', '같은', '새', '별개로', '다른', '추가로', '최종', '알려줘',
    '보여줘', '될까', '가능할까', '있어', '있는', '전에', '되면', '부탁해',
    'a', 'an', 'the', 'and', 'then', 'please', 'this', 'that', 'into', 'to', 'for', 'from', 'after'}
SMALL_TALK = re.compile(r'날씨|농담|재미있는\s*이야기|심심|오늘\s*(?:기분|운세)|너는?\s*누구|점심\s*추천|저녁\s*추천')
WORK_CUES = re.compile(r'보고서|데이터|신청|매출|재고|계약|고객|프로젝트|업무|직원|교육|생산|품질|분석|자동화|개발|코드|도구|메일|회의|엑셀|csv|html|ppt|sql', re.I)
FAILURE = re.compile(r'실패|오류|안\s*(?:돼|되|열)|못\s*(?:열|했|하)|거절|차단')


class _VisibleRequest(HTMLParser):
    """Keep visible request text, not pasted HTML attributes or script source."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden.append(tag)

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _visible_request(text):
    if '<' not in text:
        return text
    parser = _VisibleRequest()
    parser.feed(text)
    parser.close()
    return ' '.join(parser.parts)


def phrase(text, clean, limit=64):
    """Extract a compact target label; never retain imperative request prose."""
    text = clean(text, 320)
    text = re.sub(r'\[[^\]]*(?:가림|숨김)[^\]]*\]', ' ', text)
    text = re.sub(r'(?i)\b(?:token|password|secret|authorization|api[_ -]?key)\b\s*[=:]?', ' ', text)
    words = re.findall(r'[가-힣A-Za-z0-9][가-힣A-Za-z0-9_.-]*', text)
    result = []
    for word in words:
        word = re.sub(r'(?:에서는|으로부터|에서|으로|까지|에게|처럼|을|를|은|는|의|에|로|과|와)$', '', word)
        word = re.sub(r'^(?:하고|해서|해주고|한뒤|한후|해줘)', '', word)
        if len(word) < 2 or word in FILLER or re.fullmatch(r'\d+', word):
            continue
        # Long identifiers and encoded snippets cannot become task names.
        if len(word) > 28 or re.fullmatch(r'[a-fA-F0-9]{16,}', word):
            continue
        result.append(word)
    return ' '.join(result[-7:])[:limit]


def subject_key(target):
    words = []
    for word in re.findall(r'[가-힣A-Za-z0-9_-]+', target.casefold()):
        word = re.sub(r'\.?(?:csv|xlsx|xlsm|html|pptx|pdf)$', '', word)
        if word not in GENERIC and word not in FILLER and len(word) > 1 and not re.search(r'었어$|했어$|못했', word):
            words.append(word)
    return ' '.join(words[:4])[:60]


def request_steps(text, clean):
    """Normalize explicit actions in source order; no implicit pipeline stages."""
    # Code, attached context and long values are not natural-language tasks.
    text = _visible_request(re.sub(r'```[\s\S]*?```', ' ', text[:32000]))
    if not text.strip():
        return {'kind': 'insufficient', 'subject': '', 'steps': [], 'failure': False}
    if SMALL_TALK.search(text) and not WORK_CUES.search(text):
        return {'kind': 'non_work', 'subject': '', 'steps': [], 'failure': False}
    if re.search(r'(?:아직\s*)?실행하지\s*마|만약.+(?:순서|방법|가능)|(?:가능한지|할\s*수\s*있는지)\s*(?:알려|설명)', text):
        return {'kind': 'insufficient', 'subject': '', 'steps': [], 'failure': False}
    actions = list(ACTION.finditer(text))
    steps, end, subject = [], 0, ''
    for match_index, match in enumerate(actions[:MAX_STEPS]):
        english = bool(re.match('[A-Za-z]', match.group()))
        # "집계 오류를 확인" requests verification, not another aggregation.
        # Keep the noun phrase as the next action's target.
        if match.lastgroup != 'read' and re.match(r'\s*(?:오류|결과|방법|기능|과정|도구|규칙|원인|기준|여부|항목|보고서|자료|내용)(?=을|를|의|\s|$)', text[match.end():match.end()+30]):
            continue
        if re.match(r'(?:을|를)?\s*(?:(?:하지|지)\s*(?:마|말)|(?:하지는|지는)\s*마|(?:하지|지)\s*않|안\s*하)', text[match.end():match.end()+30]):
            end = match.end()
            continue
        if english and re.search(r"\b(?:do not|don't|never)\s*$", text[max(0, match.start()-20):match.start()], re.I):
            end = match.end()
            continue
        raw_target = text[end:match.start()]
        if english:
            next_start = actions[match_index + 1].start() if match_index + 1 < len(actions) else len(text)
            raw_target = text[match.end():next_start]
        # An explicit sentence or topic switch starts a new target phrase.
        chunks = re.split(r'[\n;!?]|\.(?=\s|$)|(?:별개로|다른 업무로|다른 작업으로)', raw_target)
        raw_target = chunks[0] if english else chunks[-1]
        target = phrase(raw_target, clean)
        action = match.lastgroup
        if not target:
            target = steps[-1]['target'] if steps else ''
        key = subject_key(target)
        if not subject and key:
            subject = key
        if action == 'dedupe':
            target = (target + ' 중복 항목').strip()
        # A label alone is deliberately not a claim about an algorithm, file or completion.
        steps.append({'action': action, 'target': target or '앞선 자료',
                      'operation': ACTION_LABELS[action], 'evidence': 'user_request'})
        end = match.end()
    if not steps:
        return {'kind': 'insufficient', 'subject': '', 'steps': [], 'failure': bool(FAILURE.search(text))}
    return {'kind': 'work', 'subject': subject, 'steps': steps,
            'failure': bool(FAILURE.search(text)), 'partial': len(actions) > MAX_STEPS,
            'continuation': bool(re.match(r'\s*(?:그다음|그 다음|이어서|위 (?:자료|내용|결과)|그 (?:자료|내용|결과)|다음으로)', text)),
            'explicit_switch': bool(re.search(r'별개로|다른 업무|다른 작업|새 업무|새 작업', text[:160])),
            'asset_followup': bool(re.search(r'^(?:\s*(?:좋아|응)[,.]?\s*)?(?:이|위|방금|앞선)\s*(?:작업|업무|과정|방식|내용|결과)', text)
                and re.search(r'스킬|기억|지식|skill|memory|knowledge', text, re.I)
                and re.search(r'만들|생성|저장|남겨|기억해|기억하|create|save', text, re.I))}


def sanitize_request(record, clean):
    """Validate imported summaries without trusting precomputed workflow claims."""
    if not isinstance(record, dict) or not re.fullmatch(r'[a-f0-9]{64}', str(record.get('id', ''))):
        raise ValueError('invalid work request')
    if record.get('kind') not in ('work', 'non_work', 'insufficient'):
        raise ValueError('invalid work request kind')
    steps = record.get('steps', [])
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        raise ValueError('invalid workflow steps')
    if (record['kind'] == 'work') != bool(steps):
        raise ValueError('inconsistent work request steps')
    output = []
    for step in steps:
        if not isinstance(step, dict) or step.get('action') not in ACTION_LABELS:
            raise ValueError('invalid workflow action')
        output.append({'action': step['action'], 'target': clean(step.get('target', ''), 64),
                       'operation': ACTION_LABELS[step['action']], 'evidence': 'user_request'})
    ordinal = record.get('ordinal', 0)
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
        raise ValueError('invalid workflow order')
    return {'id': record['id'], 'ordinal': ordinal, 'kind': record['kind'],
            'subject': clean(record.get('subject', ''), 60), 'steps': output,
            'failure': bool(record.get('failure')), 'partial': bool(record.get('partial')),
            'continuation': bool(record.get('continuation')),
            'explicit_switch': bool(record.get('explicit_switch')),
            'asset_followup': bool(record.get('asset_followup'))}


def _asset_changes(events):
    """Reduce already validated persistence evidence; never infer save success."""
    result = []
    for event in events:
        change = event.get('asset_change')
        if (event.get('asset_change_conflict') or not isinstance(change, dict)
                or change.get('kind') not in ('skill', 'memory', 'knowledge')
                or change.get('operation') != 'create_or_update'):
            continue
        result.append({'event_id': event['id'], 'kind': change['kind'],
            'status': event.get('status', 'unconfirmed'),
            'target': change.get('target', event.get('target', '')),
            'basis': change.get('basis', ''),
            'ambiguous': bool(event.get('request_group_ambiguous') or len(event.get('request_ids', [])) != 1)})
    return result


def _selection(changes):
    if any(c['status'] == 'returned' and not c['ambiguous'] for c in changes):
        return 'saved_asset'
    if any(c['ambiguous'] for c in changes):
        return 'ambiguous_save_evidence'
    if any(c['status'] == 'unconfirmed' for c in changes):
        return 'save_unconfirmed'
    if changes:
        return 'save_failed'
    return 'no_save_evidence'


def _asset_title(changes):
    """Display observed asset names; never infer their domain from a filename."""
    labels = {'skill': '스킬 생성·수정', 'memory': '기억 저장·수정', 'knowledge': '지식 저장·수정'}
    named = []
    for change in changes:
        if change['status'] != 'returned' or change['ambiguous']:
            continue
        target = change.get('target', '')
        # Generic entry filenames are not useful asset names. Their kind is
        # still shown as a safe fallback without inventing a business subject.
        if (not isinstance(target, str) or target.casefold() in ('skill.md', 'memory.md')
                or not re.fullmatch(r'[가-힣A-Za-z0-9 ._():-]{1,100}', target)
                or target.startswith('[')):
            continue
        value = (target, change['kind'])
        if value not in named:
            named.append(value)
    if named:
        names = ' / '.join(target for target, _ in named[:2])
        if len(named) > 2:
            names += ' 외 ' + str(len(named) - 2) + '개'
        kinds = list(dict.fromkeys(labels[kind] for _, kind in named))
        return names + ' · ' + ' · '.join(kinds)
    kinds = list(dict.fromkeys(labels[c['kind']] for c in changes
                              if c['status'] == 'returned' and not c['ambiguous']))
    return ' · '.join(kinds)


def summarize_work(sessions, assets=None):
    """Separate concrete tasks, count distinct observed episodes, retain provenance.

    All sessions remain available to broad classification. Detailed flows require
    a returned, unambiguous skill/memory/knowledge persistence invocation. A
    returned tool response is not a verification of the resulting saved asset.
    Requests without new targets may extend the current episode. An explicit
    "save this work as a skill" follow-up also stays with its observed work.
    """
    groups, candidates, excluded_sources = {}, Counter(), {}
    asset_events, linked_assets = {}, set()
    def exclude(reason, session_id):
        candidates[reason] += 1
        sources = excluded_sources.setdefault(reason, [])
        if session_id not in sources and len(sources) < 20:
            sources.append(session_id)
    for session in sessions:
        for change in _asset_changes(session.get('execution_events', [])):
            asset_events[(session['id'], change['event_id'])] = change
        requests = session.get('work_requests', [])
        if not requests:
            exclude('no_step_evidence', session['id'])
            continue
        episodes, current = [], None
        execution_by_request = {}
        for event in session.get('execution_events', []):
            for request_id in event['request_ids']:
                execution_by_request.setdefault(request_id, []).append(event)
        for request in sorted(requests, key=lambda r: r['ordinal']):
            if request['kind'] != 'work':
                exclude(request['kind'], session['id'])
                continue
            subject = subject_key(request['subject'])
            shared_target = bool(current) and bool((set(subject.split()) & set(current['subject'].split())) - GENERIC)
            continuing = request.get('continuation') and shared_target and request['steps'][0]['action'] not in ('read', 'analyze')
            if (not subject or continuing or request.get('asset_followup')) and current and not request.get('explicit_switch'):
                subject = current['subject']
            if not subject:
                exclude('unspecified_target', session['id'])
                continue
            # Subsequent requests may name an output but should only inherit an
            # existing task when their target is generic, never via shared tools.
            if current is None or subject.replace(' ', '') != current['subject'].replace(' ', '') or request.get('explicit_switch'):
                current = {'subject': subject, 'requests': [], 'steps': [], 'failure': False, 'partial': False}
                episodes.append(current)
            current['requests'].append(request['id'])
            current['failure'] |= request.get('failure', False)
            current['partial'] |= request.get('partial', False)
            for step in request['steps']:
                item = dict(step, request_id=request['id'], request_ordinal=request['ordinal'])
                if not current['steps'] or (item['action'], item['target']) != (current['steps'][-1]['action'], current['steps'][-1]['target']):
                    current['steps'].append(item)
        for episode in episodes:
            # Same subject with unrelated operation families is not a repeated
            # process. Stable first operation makes deterministic grouping cheap.
            first_action = episode['steps'][0]['action']
            observed = {event['id']: event for request_id in episode['requests']
                        for event in execution_by_request.get(request_id, [])}
            execution = sorted(observed.values(), key=lambda event: (event['ordinal'], event['id']))
            changes = _asset_changes(execution)
            selection = _selection(changes)
            # An unrelated, unsaved occurrence must not inherit a saved occurrence's
            # detail eligibility merely because the task label matches.
            group_key = episode['subject'].replace(' ', '') + ':' + first_action + ':' + selection
            group = groups.setdefault(group_key, {'id': hashlib.sha256(group_key.encode()).hexdigest()[:16],
                'title': episode['subject'], 'episodes': [], 'session_ids': [], 'request_count': 0,
                'tools': {}, 'origins': [], 'failure_mentioned': False, 'partial': False,
                '_episode_ids': set(), '_source_sessions': set(), '_origin_keys': set(),
                '_execution_ids': set(), 'execution_partial': False,
                'selection_reason': selection, 'asset_evidence': []})
            episode_id = hashlib.sha256((session['id'] + ':' + episode['requests'][0]).encode()).hexdigest()
            if episode_id in group['_episode_ids']:
                continue
            group['_episode_ids'].add(episode_id)
            group['_execution_ids'].update(session['id'] + ':' + event['id'] for event in execution)
            group['execution_partial'] |= session.get('execution_partial', False)
            group['episodes'].append({'id': episode_id, 'session_id': session['id'],
                'request_ids': episode['requests'], 'steps': episode['steps'][:32],
                'partial': episode['partial'] or len(episode['steps']) > 32,
                'execution_events': execution, 'execution_partial': session.get('execution_partial', False),
                'request_group_ambiguous': any(event['request_group_ambiguous'] for event in execution)})
            for change in changes:
                group['asset_evidence'].append(dict(change, session_id=session['id'], episode_id=episode_id))
                if selection == 'saved_asset' and not change['ambiguous']:
                    linked_assets.add((session['id'], change['event_id']))
            group['request_count'] += len(episode['requests'])
            group['failure_mentioned'] |= episode['failure']
            group['partial'] |= episode['partial'] or len(episode['steps']) > 32 or session.get('workflow_partial', False)
            if session['id'] not in group['_source_sessions']:
                group['_source_sessions'].add(session['id'])
                group['session_ids'].append(session['id'])
                for origin in session['origins']:
                    origin_key = (origin['root'], origin['path'])
                    if origin_key not in group['_origin_keys']:
                        group['_origin_keys'].add(origin_key)
                        group['origins'].append(origin)
            # A flow's tool counts describe its own episodes, not other work that
            # happens to share the same conversation.
            for event in execution:
                group['tools'].setdefault(event['tool'], set()).add(session['id'] + ':' + event['id'])
    workflows, deferred = [], []
    for group in groups.values():
        group.pop('_episode_ids')
        group.pop('_source_sessions')
        group.pop('_origin_keys')
        group['execution_count'] = len(group.pop('_execution_ids'))
        group['session_ids'].sort()
        # Choose an actual recorded sequence, never union incompatible sequences.
        representative = max(group['episodes'], key=lambda e: len(e['steps']))
        group['steps'] = representative['steps']
        group['representative_session'] = representative['session_id']
        group['occurrences'] = len(group['episodes'])
        group['sequence_variants'] = len({tuple((s['action'], s['target'].replace(' ', '').casefold()) for s in e['steps']) for e in group['episodes']})
        group['tools'] = {name: len(ids) for name, ids in group['tools'].items()}
        distinct = len({(s['action'], s['target']) for s in group['steps']})
        group['structure_reason'] = 'process' if distinct >= 2 else 'repeated' if group['occurrences'] >= 2 else 'single_step'
        if group['selection_reason'] == 'saved_asset':
            group['request_subject'] = group['title']
            group['asset_title'] = _asset_title(group['asset_evidence'])
            workflows.append(group)
        else:
            # Broad-only work does not duplicate hundreds of tool traces in the
            # detailed report. The source session remains in the catalog.
            group.pop('episodes')
            group.pop('steps')
            group.pop('tools')
            deferred.append(group)
    workflows.sort(key=lambda g: (-g['occurrences'], -len(g['steps']), g['title']))
    deferred.sort(key=lambda g: (g['selection_reason'], -g['occurrences'], g['title']))
    changes = list(asset_events.values())
    return {'workflows': workflows, 'deferred_work': deferred, 'excluded_candidates': dict(candidates),
            'excluded_sources': excluded_sources,
            'method': 'normalized_user_request_order', 'completion': 'not_inferred',
            'selection_policy': 'saved_assets',
            'asset_activity': {'observed_changes': len(changes),
                'by_kind': dict(Counter(c['kind'] for c in changes)),
                'by_status': dict(Counter(c['status'] for c in changes)),
                'flow_linked_changes': len(linked_assets),
                'unlinked_changes': len(asset_events.keys() - linked_assets),
                'definition_assets': sum(a.get('kind') in ('skill', 'memory', 'knowledge') for a in (assets or []))}}
