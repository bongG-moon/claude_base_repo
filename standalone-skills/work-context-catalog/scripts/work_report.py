"""Offline work-asset report and matching Markdown; no model or network calls.

Only the collector's reduced evidence is rendered here. Requested steps and
observed tool calls remain separate, including when their timestamps overlap.
"""
from __future__ import annotations

import base64
import hashlib
import html
from pathlib import Path
import re


KINDS = {'skill': '스킬', 'instruction': '업무 지침', 'memory': '기억',
         'knowledge': '지식', 'reference': '참고 문서', 'configuration': '설정 위치'}
STATUS = {'returned': '응답 관찰', 'error': '오류 관찰', 'unconfirmed': '결과 미확인'}
DEFERRED = {
    'no_save_evidence': '자산 저장 근거 없음 · 전체 유형 분류에만 포함',
    'save_failed': '자산 저장 중 오류 관찰',
    'save_unconfirmed': '저장 응답 미확인',
    'ambiguous_save_evidence': '어느 업무를 저장했는지 미확인',
    'single_step': '한 단계만 관찰',
}
PURPOSE_BASES = {
    'invocation_description': '호출에 적힌 목적 · AI가 작성한 설명',
    'code_structure': '코드 구조에서 확인한 처리 · 실행 완료는 별도 확인',
    'target_metadata': '호출 대상·인자에서 확인한 용도',
}
EXCLUDED = {'non_work': '일상 대화로 보이는 요청', 'insufficient': '구체적인 동작 근거가 부족한 요청',
            'unspecified_target': '업무 대상을 특정하지 못한 요청', 'no_step_evidence': '단계 정보가 없는 세션'}
TOOL_EXPLANATIONS = {
    'read': '지정한 파일의 내용을 읽는 호출입니다.',
    'write': '파일을 새로 쓰는 호출입니다. 실제 산출물 내용은 이 보고서에서 검증하지 않았습니다.',
    'edit': '기존 파일 일부를 수정하는 호출입니다.',
    'glob': '파일 이름이나 경로 조건으로 찾는 호출입니다.',
    'grep': '파일 안에서 문자열을 찾는 호출입니다.',
    'skill': '해당 작업 절차를 불러오는 호출입니다. 그 절차의 실행 완료를 뜻하지 않습니다.',
    'agent': '추가 작업자에게 업무를 전달하는 호출입니다. 하위 작업자의 내부 동작은 포함하지 않습니다.',
    'askuserquestion': '사용자에게 선택이나 추가 정보를 요청하는 호출입니다.',
    'toolsearch': '사용할 수 있는 연결 도구를 찾는 호출입니다.',
}
GENERIC_WORDS = {'업무', '자료', '데이터', '결과', '보고서', '파일', '정리', '분석', '만들기',
                 'html', 'csv', 'excel', 'python', 'skill', 'data', 'report', 'workflow'}


def _text(value):
    return str(value if value is not None else '')


def esc(value):
    return html.escape(_text(value), quote=True)


def md(value):
    """Escape data as inline Markdown, including active HTML and link syntax."""
    value = html.escape(' '.join(_text(value).split()), quote=False)
    return re.sub(r'([\\`*_{}\[\]()#|>~])', r'\\\1', value)


def anchor(prefix, value):
    value = _text(value)
    if not re.fullmatch(r'[a-f0-9]{8,64}', value):
        value = hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]
    return prefix + '-' + value


def _origins(record):
    return list(dict.fromkeys(_text(o.get('root')) + '/' + _text(o.get('path'))
                            for o in record.get('origins', []) if isinstance(o, dict)))


def _steps(flow):
    return flow.get('steps', [])


def _flow_title(flow):
    return flow.get('asset_title') or flow.get('title', '')


def _input_output(flow):
    steps = _steps(flow)
    inputs = list(dict.fromkeys(_text(s.get('target')) for s in steps if s.get('action') == 'read'))
    outputs = list(dict.fromkeys(_text(s.get('target')) for s in steps if s.get('action') in ('write', 'publish')))
    return inputs, outputs


def _words(value):
    return {w.casefold() for w in re.findall(r'[가-힣A-Za-z0-9]{2,}', _text(value))
            if w.casefold() not in GENERIC_WORDS}


def definition_index(assets):
    """Tokenize each definition once per report, even with thousands of works."""
    return [(asset, _words(_text(asset.get('title')) + ' ' + _text(asset.get('description'))),
             re.sub(r'\s+', '', _text(asset.get('title')) + ' ' + _text(asset.get('description'))).casefold())
            for asset in assets if asset.get('kind') != 'configuration']


def related_definitions(flow, assets, index=None):
    """Lexical candidates, never an asserted rule or an execution dependency."""
    words = _words(flow.get('title', ''))
    for step in _steps(flow):
        words.update(_words(step.get('target', '')))
    matches = []
    subject = re.sub(r'\s+', '', _text(flow.get('title', ''))).casefold()
    for asset, tokens, compact in definition_index(assets) if index is None else index:
        found = sorted(words & tokens)
        if len(subject) >= 4 and subject not in GENERIC_WORDS and subject in compact and not found:
            found = [_text(flow.get('title'))]
        if found:
            matches.append((len(found), asset, found))
    matches.sort(key=lambda item: (-item[0], _text(item[1].get('title')), _text(item[1].get('id'))))
    return [(asset, words) for _, asset, words in matches[:8]]


def _events(episode):
    events = episode.get('execution_events', [])
    return sorted(events, key=lambda e: (e.get('ordinal', 0), _text(e.get('id'))))


def _event_note(event):
    if event.get('request_group_ambiguous') or len(event.get('request_ids', [])) > 1:
        return '같은 요청의 여러 업무가 공유하는 호출 · 단계별 연결 미확인'
    return '요청 이후 같은 대화에서 관찰 · 개별 단계와의 대응은 미확인'


def _status(event):
    return STATUS.get(event.get('status'), STATUS['unconfirmed'])


def _tool_explanation(event):
    name = _text(event.get('tool')).casefold()
    if name in TOOL_EXPLANATIONS:
        return TOOL_EXPLANATIONS[name]
    if name.startswith('mcp__'):
        return '연결된 외부 기능을 호출한 기록입니다. 도구 이름으로만 기능을 구분합니다.'
    if name in ('bash', 'powershell', 'exec_command', 'functions.exec_command'):
        return '로컬 명령 실행 호출입니다. 명령 본문과 인증정보는 내보내지 않습니다.'
    return '기록에 남은 도구 호출입니다. 내부 구현과 실제 업무 성공은 별도 확인이 필요합니다.'


def _known_events(flow):
    found = {}
    for episode in flow.get('episodes', []):
        for event in _events(episode):
            found.setdefault((_text(episode.get('session_id')), _text(event.get('id'))), event)
    return list(found.values())


def _purpose(event):
    """Show the evidence source beside intent; never turn it into an outcome."""
    if event.get('purpose_conflict') is True:
        return ('같은 호출의 목적 설명이 기록마다 달라 확인이 필요합니다.',
                '목적 미확인 · 서로 다른 설명 근거')
    value = event.get('purpose')
    if isinstance(value, dict) and value.get('basis') in PURPOSE_BASES:
        text = value.get('text')
        if isinstance(text, str) and text.strip() and len(text) <= 240:
            return text, PURPOSE_BASES[value['basis']]
    return ('구체적으로 무엇을 처리하려 했는지는 기록에서 확인하지 못했습니다.',
            '목적 미확인 · 도구 이름만으로 추정하지 않음')


def _definition_markdown(asset):
    lines = ['- **' + md(asset.get('title')) + '** · ' + md(KINDS.get(asset.get('kind'), '참고 문서')),
             '  - 정의 내용: ' + md(asset.get('description') or '제목만 확인했습니다. 세부 업무 규칙은 미확인입니다.'),
             '  - 자산 ID: ' + md(asset.get('id'))]
    lines.extend('  - 출처: ' + md(origin) for origin in _origins(asset))
    return lines


def _agent_label(report):
    environments = ' '.join(_text(root.get('environment')) for root in report.get('roots', []))
    claude, codex = 'Claude' in environments, 'Codex' in environments
    return 'Claude Code' if claude and not codex else 'Codex' if codex and not claude else 'Claude Code·Codex'


def _deferred_reason(flow):
    reason = flow.get('selection_reason', 'no_save_evidence')
    return DEFERRED.get(reason, '상세 흐름 선정 근거 미확인')


def _topic_summary(report):
    """Classify every retained session, including sessions not in detailed flows."""
    selected = {sid for f in report.get('work_analysis', {}).get('workflows', [])
                for sid in f.get('session_ids', [])}
    buckets = {}
    for session in report.get('sessions', []):
        for topic in dict.fromkeys(session.get('topics') or ['미분류']):
            row = buckets.setdefault(topic, {'total': 0, 'selected': 0})
            row['total'] += 1
            row['selected'] += session.get('id') in selected
    return sorted(buckets.items(), key=lambda item: (-item[1]['total'], item[0])), selected


def _asset_evidence(flow):
    """Returned persistence calls are selection evidence, never verified files."""
    evidence, seen = [], set()
    for episode in flow.get('episodes', []):
        for event in _events(episode):
            value = event.get('asset_change')
            key = (episode.get('session_id'), event.get('id'))
            if (key in seen or not isinstance(value, dict) or event.get('status') != 'returned'
                    or event.get('asset_change_conflict') or event.get('request_group_ambiguous')
                    or len(event.get('request_ids', [])) != 1):
                continue
            seen.add(key)
            evidence.append((episode.get('session_id'), event, value))
    return evidence


def _workflow_markdown(flow, assets, sessions, definitions_index=None, actor='Claude Code·Codex'):
    sid_map = {s.get('id'): s for s in sessions}
    inputs, outputs = _input_output(flow)
    lines = ['## ' + md(_flow_title(flow)), '',
             '- 업무 ID: ' + md(flow.get('id')),
             '- 자산 상태: 기록 기반 후보 · 업무 담당자 검토 전',
             '- 관찰 묶음: ' + str(flow.get('occurrences', len(flow.get('episodes', []))))
             + '회 · 완료 횟수나 근무 시간이 아닙니다.',
             '- 관찰한 업무 대상: ' + md(flow.get('title')),
             '- 요청된 입력 자료: ' + (' / '.join(md(v) for v in inputs) or '읽기 대상이 명시되지 않아 미확인'),
             '- 요청된 결과물: ' + (' / '.join(md(v) for v in outputs) or '결과물 형태가 명시되지 않아 미확인'),
             '- 실제 결과물 완성·정확성: 미검증', '', '### 상세 FLOW로 선정한 근거', '']
    for sid, event, value in _asset_evidence(flow):
        lines.append('- ' + md(KINDS.get(value.get('kind'), '자산')) + ' 생성·수정 호출의 응답 관찰 · '
                     + md(value.get('target') or event.get('target') or '대상 이름 미수집')
                     + ' / 세션 ' + md(sid) + ' / 호출 ' + md(event.get('id')))
    lines += ['', '저장 호출의 응답을 관찰한 업무입니다. 현재 파일의 존재·내용이나 저장 성공을 추가 확인한 것은 아닙니다.',
              '', '### 요청에서 확인한 처리 순서', '']
    for i, step in enumerate(_steps(flow), 1):
        lines.append(str(i) + '. ' + md(step.get('target')) + ' — ' + md(step.get('operation'))
                     + ' (요청 근거 ' + md(_text(step.get('request_id'))[:12]) + ')')
    lines += ['', '요청의 순서를 정리했습니다. 실제 실행 순서나 계산 의존성이 검증됐다는 뜻은 아닙니다.', '',
              '### ' + actor + '가 실제 호출한 동작', '',
              '응답 관찰은 도구 응답이 돌아왔다는 뜻입니다. 업무 성공을 의미하지 않습니다. '
              '명령·쿼리 본문, 도구 결과 본문, 이미지, 생각 과정은 포함하지 않습니다.', '']
    for index, episode in enumerate(flow.get('episodes', []), 1):
        session_id = episode.get('session_id', '')
        lines += ['#### 관찰 묶음 ' + str(index), '',
                  '- 묶음 ID: ' + md(episode.get('id')),
                  '- 세션 ID: ' + md(session_id),
                  '- 요청 ID: ' + ', '.join(md(r) for r in episode.get('request_ids', []))]
        for origin in _origins(sid_map.get(session_id, {})):
            lines.append('- 세션 출처: ' + md(origin))
        events = _events(episode)
        if events:
            lines += ['', '| 순서 | 하려던 일·처리 설명 | 설명 근거 | 관찰한 동작 · 도구 | 대상 | 결과 상태 | 호출 근거 |',
                      '| --- | --- | --- | --- | --- | --- | --- |']
            for event in events:
                purpose, basis = _purpose(event)
                lines.append('| ' + str(event.get('ordinal', 0)) + ' | '
                    + md(purpose) + ' | ' + md(basis) + ' | '
                    + md(event.get('operation')) + ' · ' + md(event.get('tool')) + ' | '
                    + md(event.get('target') or '대상 정보 미수집') + ' | ' + _status(event) + ' | '
                    + md(event.get('id')) + ' |')
            lines += ['', '호출은 해당 요청 이후의 기록과 연결했습니다. 각 요청 단계에 어떤 호출이 해당하는지는 자동 단정하지 않습니다. '
                      '처리 설명은 호출에 적힌 목적이나 코드·인자에서 확인한 범위입니다. 코드를 실행하거나 결과를 검증한 설명이 아닙니다.']
            for event in events:
                if event.get('request_group_ambiguous') or len(event.get('request_ids', [])) > 1:
                    lines += ['', '공유 호출 ' + md(event.get('id')) + ': ' + _event_note(event) + '.']
        else:
            lines += ['', '이 묶음에 연결할 실행 상세 근거가 없습니다. 이전 내보내기이거나 연결·수집 범위가 부족할 수 있습니다. 미실행으로 단정하지 않습니다.']
        if episode.get('execution_partial') or episode.get('partial'):
            lines += ['', '일부 기록만 확인했습니다. 목록 밖의 동작·결과는 미확인입니다.']
        lines.append('')
    lines += ['### 다른 진행 방식과 예외', '']
    sequences = {}
    for episode in flow.get('episodes', []):
        sequence = ' → '.join(_text(s.get('target')) + ' · ' + _text(s.get('operation')) for s in episode.get('steps', []))
        sequences.setdefault(sequence, []).append(_text(episode.get('session_id')))
    for index, (sequence, ids) in enumerate(sequences.items(), 1):
        lines.append('- 방식 ' + str(index) + ': ' + md(sequence))
        lines.append('  - 출처 세션: ' + ', '.join(md(v) for v in dict.fromkeys(ids)))
    errors = [e for e in _known_events(flow) if e.get('status') == 'error']
    if errors:
        for event in errors:
            lines.append('- 오류 관찰: ' + md(event.get('operation')) + ' · ' + md(event.get('tool'))
                         + ' / 근거 ' + md(event.get('id')) + '. 오류 원문과 원인은 미수집입니다.')
    if flow.get('failure_mentioned'):
        lines.append('- 사용자 요청에 오류·실패 언급이 있습니다. 실제 원인과 해결 여부는 미확인입니다.')
    if not errors and not flow.get('failure_mentioned'):
        lines.append('- 확인한 기록에 오류 근거가 없습니다. 전체 업무가 성공했다는 뜻은 아닙니다.')
    if flow.get('partial'):
        lines.append('- 요청·실행 목록에 일부 누락 가능성이 있습니다.')
    lines += ['', '### 연결해 볼 업무 지식·도메인 후보', '',
              '업무 대상과 문서 제목·설명의 단어가 겹친 후보입니다. 실제로 이 업무에 적용한 기준이나 검증된 도메인 규칙은 아닙니다.', '']
    candidates = related_definitions(flow, assets, definitions_index)
    if candidates:
        for asset, words in candidates:
            lines += _definition_markdown(asset)
            lines.append('  - 연결 근거 단어: ' + ', '.join(md(w) for w in words))
    else:
        lines.append('직접 연결할 정의를 찾지 못했습니다. 해당 업무의 용어·판정 기준을 새로 추정하지 않습니다.')
    lines += ['', '### 재사용 전에 사람이 확인할 내용', '',
              '- 입력 자료의 필수 열·범위와 실제 결과물 위치·정확성을 확인합니다.',
              '- 요청 순서와 실제 도구 호출을 비교해 업무 규칙·분기·예외를 확정합니다.',
              '- 위 지식 후보 중 실제 사용한 기준만 채택하고 출처를 유지합니다.',
              '- 이 문서는 재사용할 절차의 초안입니다. 실행 가능한 스킬이나 공식 규정으로 자동 등록하지 않습니다.', '']
    return lines


def render_markdown(report):
    """Same editable, source-linked asset document is saved and embedded in HTML."""
    analysis = report.get('work_analysis', {})
    assets, sessions = report.get('assets', []), report.get('sessions', [])
    definitions_index = definition_index(assets)
    lines = ['# 업무·도메인 자산 검토본', '',
             '- 문서 형식: work-context-assets / 1',
             '- 생성 시각: ' + md(report.get('generated_at') or '미기록'),
             '- 자료 상태: 기록 기반 후보 · 담당자 검토 전',
             '- 자동 합산 원본: catalog.json', '',
             '전체 세션은 업무 유형으로 분류하고, 스킬·기억·지식 저장 응답이 관찰된 업무만 상세 FLOW로 정리했습니다. '
             '요청과 실행, 도구 응답과 업무 성공을 구분합니다. 개인별 성과나 업무량을 평가하는 문서가 아닙니다.', '',
             '이 Markdown은 사람이 검토·편집하고 여러 업무의 설명을 모으는 자료입니다. '
             '중복을 구분한 자동 재집계에는 함께 생성한 catalog.json을 사용합니다. '
             '내용을 공유하기 전 업무 이름·파일 이름·정의 설명을 확인하세요.', '']
    topic_rows, selected = _topic_summary(report)
    lines += ['## 전체 세션의 큰 업무 유형', '',
              '상세 FLOW 선정 여부와 관계없이 포함한 모든 세션을 분류합니다. 한 세션이 여러 유형에 포함될 수 있으며, 분류 수는 업무량이 아닙니다.', '',
              '| 업무 유형 후보 | 전체 세션 | 상세 FLOW 연결 | 유형만 분류 |',
              '| --- | --- | --- | --- |']
    for topic, counts in topic_rows:
        lines.append('| ' + md(topic) + ' | ' + str(counts['total']) + ' | ' + str(counts['selected'])
                     + ' | ' + str(counts['total'] - counts['selected']) + ' |')
    lines += ['', '## 세션별 분류 근거', '', '| 세션 ID | 업무 유형 후보 | 정리 범위 | 출처 |',
              '| --- | --- | --- | --- |']
    for session in sessions:
        lines.append('| ' + md(session.get('id')) + ' | ' + md(', '.join(session.get('topics') or ['미분류']))
                     + ' | ' + ('상세 FLOW 연결' if session.get('id') in selected else '유형만 분류')
                     + ' | ' + md(' / '.join(_origins(session))) + ' |')
    lines.append('')
    workflows = analysis.get('workflows', [])
    if not workflows:
        lines += ['## 자산으로 남긴 업무 FLOW', '', '업무와 연결된 자산 저장 응답을 찾지 못해 상세 흐름으로 묶을 근거가 부족합니다. 저장된 자산이 없다는 뜻은 아닙니다. 발견한 정의와 수집 범위를 확인하세요.', '']
    for flow in workflows:
        lines += _workflow_markdown(flow, assets, sessions, definitions_index, _agent_label(report))
    lines += ['## 보류·제외 후보', '']
    ordinary = [f for f in analysis.get('deferred_work', []) if f.get('selection_reason') == 'no_save_evidence']
    if ordinary:
        lines.append('- 자산 저장 근거 없는 업무 묶음 ' + str(len(ordinary)) + '개: 상세 호출은 생략하고 전체 세션 분류에 포함했습니다.')
    for flow in analysis.get('deferred_work', []):
        if flow.get('selection_reason') != 'no_save_evidence':
            lines.append('- 보류: ' + md(flow.get('title')) + ' · ' + md(_deferred_reason(flow)) + ' / 업무 ID ' + md(flow.get('id')))
    for reason, count in analysis.get('excluded_candidates', {}).items():
        lines.append('- 제외 후보: ' + md(EXCLUDED.get(reason, reason)) + ' · ' + str(count))
    if not analysis.get('deferred_work') and not analysis.get('excluded_candidates'):
        lines.append('별도 보류·제외 후보 없음')
    lines += ['', '## 발견한 스킬·기억·지식의 정의', '',
              '정의 파일의 존재와 내용 요약입니다. 실제 사용·실행 성공을 뜻하지 않습니다.', '']
    definitions = [a for a in assets if a.get('kind') != 'configuration']
    for asset in definitions:
        lines += _definition_markdown(asset)
    if not definitions:
        lines.append('지정 범위에서 정의를 찾지 못했습니다.')
    lines += ['', '## 수집 범위와 누락', '']
    for root in report.get('roots', []):
        lines.append('- ' + md(root.get('id')) + ': ' + md(root.get('environment')) + ' (' + md(root.get('scope')) + ')')
    coverage = report.get('coverage', {})
    scan = coverage.get('session_scan', {})
    lines.append('- 세션 파일: 발견 ' + str(scan.get('files_found', 0)) + ', 읽기 ' + str(scan.get('files_scanned', 0))
                 + ', 포함 ' + str(scan.get('files_kept', 0)) + ', 부분 읽기 ' + str(scan.get('partial_files', 0)))
    for kind in ('session_filter_reasons', 'session_skip_reasons', 'warnings'):
        for reason, count in coverage.get(kind, {}).items():
            lines.append('- ' + md(reason) + ': ' + str(count))
    if coverage.get('limits'):
        lines += ['', '수집 상한 (파일·이벤트는 개수, bytes는 바이트):']
        lines += ['- ' + md(key) + ': ' + str(value) for key, value in coverage['limits'].items()]
    lines += ['', '알려진 현재 사용자 저장소와 지정한 범위만 확인했습니다. 원본 기록의 누락·수집 한도·지원하지 않는 형식이 있을 수 있습니다. '
              '일부 또는 이전 내보내기에 실행 상세가 없으면 미확인으로 남깁니다. '
              '원본은 수정하지 않았으며 다른 사람의 프로필이나 중앙 서버에 자동 접근·업로드하지 않습니다.', '']
    return '\n'.join(lines)


def _table(label, headers, rows, classes=''):
    return ('<div class="table ' + classes + '" role="region" tabindex="0" aria-label="' + esc(label) + '">'
            '<table><thead><tr>' + ''.join('<th scope="col">' + esc(h) + '</th>' for h in headers)
            + '</tr></thead><tbody>' + rows + '</tbody></table></div>')


def _source_link(session_id, label=None):
    return '<a href="#' + anchor('session', session_id) + '">' + esc(label or _text(session_id)[:12]) + '</a>'


def _event_rows(events, session_id):
    rows = []
    for event in events:
        status = event.get('status') if event.get('status') in STATUS else 'unconfirmed'
        purpose, basis = _purpose(event)
        rows.append('<tr><td><span class="ordinal">' + esc(event.get('ordinal', '')) + '</span></td><td><strong>'
            + esc(purpose) + '</strong><small class="purpose-basis">' + esc(basis)
            + '</small><code>' + esc(event.get('operation') or '도구 호출') + ' · ' + esc(event.get('tool'))
            + '</code></td><td>' + esc(event.get('target') or '대상 정보 미수집')
            + '</td><td><span class="status ' + status + '">' + _status(event) + '</span></td><td>'
            + _source_link(session_id) + '<small>호출 ' + esc(_text(event.get('id'))[:12]) + '</small><small>'
            + esc(_event_note(event)) + '</small></td></tr>')
    return ''.join(rows)


def _execution_html(flow, actor='Claude Code·Codex'):
    episodes = flow.get('episodes', [])
    count = len(_known_events(flow))
    chunks = ['<details class="execution-detail"><summary>' + esc(actor) + '가 실제 한 동작 보기'
              + '<span class="summary-count">' + str(count) + '개 호출 근거</span></summary>'
              '<p class="muted">요청 뒤에 기록된 실제 호출을 순서대로 확인합니다. '
              '하려던 일은 호출 설명 또는 코드·인자에서 확인한 범위로 풀어 썼습니다. '
              '‘응답 관찰’은 응답이 돌아왔다는 뜻이며 업무 성공을 뜻하지 않습니다. '
              '원문 명령·쿼리·결과와 하위 작업자의 내부 기록은 포함하지 않습니다.</p>']
    for index, episode in enumerate(episodes, 1):
        events = _events(episode)
        chunks.append('<details class="episode"' + (' open' if len(episodes) == 1 else '')
            + '><summary>관찰 묶음 ' + str(index) + ' · ' + str(len(events)) + '개 호출'
            + '</summary><p class="evidence-line">세션 ' + _source_link(episode.get('session_id'))
            + ' · 요청 근거 ' + esc(', '.join(_text(r)[:12] for r in episode.get('request_ids', []))) + '</p>')
        if events:
            chunks.append(_table('관찰 묶음 ' + str(index) + ' 실제 동작 표',
                ['순서', '하려던 일·처리 설명', '확인 가능한 대상', '결과 상태', '관찰 근거'],
                _event_rows(events, episode.get('session_id')), 'execution-table'))
        else:
            chunks.append('<p class="empty-state">이 묶음에 연결할 실행 상세 근거가 없습니다. 이전 내보내기이거나 '
                          '연결·수집 범위가 부족할 수 있습니다. 미실행으로 단정하지 않습니다.</p>')
        if episode.get('execution_partial') or episode.get('partial'):
            chunks.append('<p class="note">일부 기록만 확인했습니다. 목록 밖의 동작·결과는 미확인입니다.</p>')
        chunks.append('</details>')
    if not episodes:
        chunks.append('<p class="empty-state">연결 가능한 관찰 묶음이 없습니다.</p>')
    chunks.append('</details>')
    return ''.join(chunks)


def _domain_html(flow, assets, index=None):
    candidates = related_definitions(flow, assets, index)
    content = ''
    for asset, words in candidates:
        content += '<article class="domain-item"><h4><a href="#' + anchor('asset', asset.get('id')) + '">' + esc(asset.get('title')) + '</a></h4><p>'
        content += esc(asset.get('description') or '제목만 확인했습니다. 세부 업무 규칙은 미확인입니다.') + '</p><small>'
        content += esc(KINDS.get(asset.get('kind'), '참고 문서')) + ' · 연결 근거: ' + esc(', '.join(words)) + '</small></article>'
    return '<details class="domain-detail"><summary>재사용할 업무 지식·도메인 후보 보기</summary><p>업무 대상과 문서 제목·설명의 단어가 겹친 후보입니다. 실제 적용한 기준이나 검증된 규칙은 아닙니다.</p>' + ('<div class="domain-grid">' + content + '</div>' if content else '<p class="empty-state">직접 연결할 정의를 찾지 못했습니다. 용어·판정 기준을 새로 추정하지 않습니다.</p>') + '</details>'


def _flow_html(flow, assets, index=None, actor='Claude Code·Codex'):
    steps = _steps(flow)
    inputs, outputs = _input_output(flow)
    badges = '<span class="badge">자산 저장 응답이 관찰된 업무</span>'
    if flow.get('failure_mentioned'):
        badges += '<span class="badge caution">오류·실패 언급</span>'
    if flow.get('partial'):
        badges += '<span class="badge caution">일부 기록</span>'
    sequence = ''.join('<li class="workflow-step"><span class="step-number">' + str(i + 1)
        + '</span><h4>' + esc(s.get('target')) + '</h4><p>' + esc(s.get('operation'))
        + '</p><small>요청 ' + str(s.get('request_ordinal', 0) // 100) + '에서 확인</small></li>' for i, s in enumerate(steps))
    variants = ''
    if flow.get('sequence_variants', 0) > 1:
        variants = '<details class="variants"><summary>관찰된 진행 방식 ' + str(flow['sequence_variants']) + '종 비교</summary><ul>'
        seen = set()
        for episode in flow.get('episodes', []):
            text = ' → '.join(_text(s.get('target')) + ' · ' + _text(s.get('operation')) for s in episode.get('steps', []))
            if text not in seen:
                variants += '<li>' + esc(text) + '<small>출처 ' + _source_link(episode.get('session_id')) + '</small></li>'
                seen.add(text)
        variants += '</ul></details>'
    tools = ', '.join(_text(k) + ' ' + str(v) + '회' for k, v in flow.get('tools', {}).items()) or '관찰된 호출 없음'
    evidence = '<div class="note"><strong>상세 FLOW 선정 근거</strong><ul>'
    for sid, event, value in _asset_evidence(flow):
        evidence += '<li>' + esc(KINDS.get(value.get('kind'), '자산')) + ' 생성·수정 · ' + esc(value.get('target') or event.get('target') or '대상 이름 미수집') + ' · 응답 관찰 <small>세션 ' + _source_link(sid) + ' / 호출 ' + esc(_text(event.get('id'))[:12]) + '</small></li>'
    evidence += '</ul><small>호출 응답을 확인한 근거입니다. 현재 파일의 존재·내용이나 저장 성공을 추가 검증한 것은 아닙니다.</small></div>'
    return '<article class="workflow-card card" id="' + anchor('work', flow.get('id')) + '"><div class="flow-heading"><div><div class="badges">' + badges + '</div><h3>' + esc(_flow_title(flow)) + '</h3><small>업무 ID ' + esc(flow.get('id')) + '</small></div><div class="frequency"><strong>' + str(flow.get('occurrences', 0)) + '</strong><span>관찰 묶음</span></div></div><div class="flow-summary"><div><span>요청된 입력 자료</span><b>' + esc(' / '.join(inputs) or '읽기 대상 미확인') + '</b></div><div><span>요청된 결과물</span><b>' + esc(' / '.join(outputs) or '결과물 형태 미확인') + '</b></div><div><span>결과물 완성·정확성</span><b>실행 결과 미확인</b></div></div><h4 class="flow-label">요청한 업무 흐름</h4><p class="flow-caption">요청에서 확인한 순서입니다. 실제 호출 내역은 아래 ‘실제 한 동작 보기’에서 확인하세요.</p><ol class="workflow-steps" aria-label="' + esc(flow.get('title')) + ' 요청 진행 순서">' + sequence + '</ol>' + evidence + _execution_html(flow, actor) + variants + _domain_html(flow, assets, index) + '<details class="flow-evidence"><summary>출처와 관찰 범위</summary><p>관련 세션: ' + ', '.join(_source_link(s) for s in flow.get('session_ids', [])) + '</p><p>' + '<br>'.join('<code>' + esc(o) + '</code>' for o in _origins(flow)) + '</p><p>이 업무의 요청 구간에서 관찰한 도구 호출 (개별 단계와 직접 연결은 미확인): ' + esc(tools) + '</p><p>실제 호출 상세는 요청 이후 같은 대화의 기록을 연결한 것입니다. 개별 처리 단계에 자동 대응하거나 업무 성공으로 판단하지 않습니다.</p></details></article>'


CSS = r"""
/* AX Workspace guide: calm paper surfaces, purple links, Korean reading rhythm. */
:root{color-scheme:light;--ink:#292d42;--muted:#626a80;--accent:#6257be;--line:#e0e2e7;--paper:#fff;--canvas:#f6f6f7}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:24px}
body{margin:0;background:var(--canvas);color:var(--ink);font:15px/1.85 'Noto Sans KR','Malgun Gothic',sans-serif;word-break:keep-all;overflow-wrap:anywhere}
main{max-width:1120px;margin:auto;padding:40px 32px 72px;min-width:0}
a{color:var(--accent);text-underline-offset:4px}
h1,h2,h3,h4{line-height:1.45;letter-spacing:-.035em}
h1{font-size:clamp(28px,3.7vw,38px);margin:14px 0 12px;text-wrap:balance}
h2{font-size:25px;margin:0 0 16px}h3{font-size:21px;margin:12px 0 6px}h4{font-size:15px;margin:12px 0 8px}
p{margin:12px 0}.muted,small{color:var(--muted)}small{font-size:12px;line-height:1.8}
.hero{padding:0 4px 10px}.hero-brand{display:flex;align-items:center;gap:10px}
.brand-mark{display:grid;place-items:center;width:34px;height:34px;border-radius:11px;background:var(--accent);color:#fff;font-weight:700;font-size:13px;box-shadow:0 3px 10px #6257be20}
.eyebrow{font-size:11px;letter-spacing:.13em;color:var(--accent);font-weight:700}.lead{color:var(--muted);font-size:16px}
section{scroll-margin-top:24px;margin-top:28px;min-width:0}
.quick-start{background:var(--paper);border:1px solid var(--line);border-radius:22px;padding:25px 26px 20px;margin-top:18px}
.quick-heading{display:flex;align-items:baseline;justify-content:space-between;gap:12px 24px;flex-wrap:wrap;margin-bottom:18px}
.quick-heading h2{font-size:21px;margin:0}.quick-heading p{margin:0;font-size:12px;color:var(--muted)}
.quick-steps{list-style:none;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px;padding:0;margin:0}
.quick-steps>li{margin:0;min-width:0;padding:17px 18px;border:1px solid var(--line);border-radius:15px;background:white}
.quick-steps h3{display:flex;align-items:center;gap:9px;font-size:14px;margin:0 0 12px}
.step-number{display:grid;place-items:center;flex:none;width:26px;height:26px;border-radius:8px;background:#f0f0f3;color:var(--accent);font-size:12px;font-weight:700}
.quick-steps p{font-size:13px;margin:10px 0}.quick-steps small{font-size:11px;display:block;margin-top:9px}
.quick-link,.download{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);background:white;color:var(--accent);padding:4px 10px;border-radius:8px;text-decoration:none;font-size:12px;font-weight:600}
.quick-link:hover,.download:hover{background:#f8f7fc;border-color:#c8c3e5}
.overview-counts{display:flex;flex-wrap:wrap;gap:6px 20px;margin:16px 0 0;padding:0;list-style:none;font-size:12px;color:var(--muted)}
.overview-counts li{margin:0}.overview-counts strong{color:var(--ink);font-weight:600}
.guide-nav{margin:20px 0 28px;padding:0 18px;border:1px solid var(--line);border-radius:15px;background:white}
.guide-nav>summary{padding:13px 0;color:var(--accent);font-size:13px}
.guide-nav nav{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px 22px;padding:0 0 16px}
.guide-nav nav a{display:flex;gap:7px;align-items:center;font-size:12px;text-decoration:none;padding:5px 0;min-width:0}
.guide-nav nav a::before{content:'\2197';color:#9991bd;flex:none}
.card{background:var(--paper);border:1px solid var(--line);border-radius:20px;padding:28px}
.report-section>h2{display:flex;align-items:center;gap:12px}
.report-section>h2::before{content:'';display:block;flex:none;width:4px;height:24px;background:#c4c3cd;border-radius:4px}
.section-lead{color:var(--muted);margin:0 0 20px;font-size:14px}
.workflow-card{margin-top:20px;min-width:0;padding:22px;border-radius:15px}
.flow-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.flow-heading>div:first-child{min-width:0}
.badges{display:flex;flex-wrap:wrap;gap:7px}.badge{display:inline-block;padding:3px 9px;border:1px solid #e1ddf0;background:#f8f7fc;color:var(--accent);border-radius:8px;font-size:11px}
.badge.caution{color:#8c5e29;background:#fffaf0;border-color:#eee0c7}
.frequency{text-align:right;flex:none}.frequency strong{display:block;font-size:24px;color:var(--accent);line-height:1.5}.frequency span{font-size:11px;color:var(--muted)}
.flow-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;border-bottom:1px solid var(--line);padding:0 0 20px;margin:20px 0 24px}
.flow-summary>div{min-width:0}.flow-summary span{display:block;font-size:11px;color:var(--muted);margin-bottom:6px}.flow-summary b{font-size:13px;font-weight:600}
.flow-label{font-size:15px;margin:0}.flow-caption{font-size:12px;color:var(--muted);margin:5px 0 17px}
.workflow-steps{list-style:none;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:28px 20px;padding:0;margin:0 0 28px}
.workflow-step{position:relative;margin:0;padding:17px 16px;min-width:0;border:1px solid var(--line);border-radius:13px;background:white}
.workflow-step h4{margin:12px 0 7px;font-size:14px}.workflow-step p{font-size:13px;margin:0 0 7px}.workflow-step small{font-size:11px}
.workflow-step:not(:last-child)::after{content:'→';position:absolute;right:-17px;top:50%;color:#928bb8}
.workflow-step:nth-child(4n):not(:last-child)::after{content:'다음 줄 ↓';font-size:10px;top:auto;right:0;bottom:-24px}
.workflow-step:nth-child(4n+1):last-child{grid-column:span 4}.workflow-step:nth-child(4n+2):last-child{grid-column:span 3}.workflow-step:nth-child(4n+3):last-child{grid-column:span 2}
details{border-top:1px solid var(--line);padding:15px 13px}summary{cursor:pointer;font-weight:600;font-size:14px}
details[open]>summary{color:var(--accent)}details p{color:var(--muted);font-size:13px}
.summary-count{display:inline-block;font-size:11px;font-weight:400;margin-left:12px;color:var(--muted)}
.episode{margin:14px 0 0;padding:14px 16px;border:1px solid var(--line);border-radius:12px;background:white}.episode>summary{font-size:13px}.evidence-line{font-size:11px}
.table{max-height:520px;max-width:100%;overflow:auto;border:1px solid var(--line);border-radius:13px;margin:16px 0;background:white;scrollbar-color:#b5b1ce #f3f3f7;scrollbar-width:thin}
table{width:100%;min-width:860px;table-layout:fixed;border-collapse:collapse;font-size:14px}
th,td{text-align:left;vertical-align:top;padding:13px 14px;border-bottom:1px solid #e6e7ec;word-break:keep-all;overflow-wrap:break-word}
th{position:sticky;top:0;z-index:1;background:#f4f4f6;color:#525c77;font-size:12px;box-shadow:0 1px 0 var(--line)}
th:nth-child(1){width:27%}th:nth-child(2){width:16%}th:nth-child(3){width:27%}th:nth-child(4){width:30%}
td small,td code{display:block;margin-top:5px}tbody tr:nth-child(even){background:#fafafa}tbody tr:hover{background:#f5f3fc}tbody tr:last-child td{border-bottom:0}
code{font:inherit;font-size:12px;color:#56536c;word-break:normal;overflow-wrap:anywhere}
.execution-table table{min-width:1080px}.execution-table th:nth-child(1){width:6%}.execution-table th:nth-child(2){width:40%}.execution-table th:nth-child(3){width:16%}.execution-table th:nth-child(4){width:12%}.execution-table th:nth-child(5){width:26%}.execution-table td small{font-size:11px}.execution-table td strong{font-size:13px;font-weight:500;line-height:1.85}.purpose-basis{color:var(--accent)}
.ordinal{font-variant-numeric:tabular-nums;color:var(--accent);font-weight:700}.status{display:inline-block;font-size:11px;border-radius:8px;background:#eeedf2;padding:3px 7px;white-space:nowrap}
.status.error{background:#f9ebe8;color:#924b42}.status.returned{background:#eeedf8;color:#5d538e}.status.unconfirmed{color:#646879}
.domain-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.domain-item{min-width:0;border:1px solid var(--line);border-radius:12px;padding:17px}.domain-item:last-child:nth-child(odd){grid-column:1/-1}.domain-item h4{margin:0}.domain-item p{margin:8px 0;font-size:13px}.domain-item small{font-size:11px}
.note{background:white;border:1px solid var(--line);border-left:3px solid #b7bbc6;padding:14px 17px;border-radius:12px;margin-top:18px;color:var(--muted);font-size:13px}
.empty-state{padding:18px;border:1px dashed #d6d4df;border-radius:12px;background:#fafafb;color:var(--muted);font-size:13px}
.excluded-list{padding:0;list-style:none;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.excluded-list>li{border:1px solid var(--line);border-radius:12px;padding:13px 16px;font-size:13px;min-width:0}.excluded-list>li:last-child:nth-child(odd){grid-column:1/-1}.excluded-list b{margin-left:10px}.excluded-list details{padding-bottom:0;margin-top:8px}
.roots{display:flex;flex-wrap:wrap;gap:10px}.root{flex:1 1 200px;min-width:0;padding:15px;border:1px solid var(--line);border-radius:12px;font-size:13px}.root span{display:block;font-size:12px;color:var(--muted)}.table-hint{font-size:12px;color:var(--muted)}
ul{padding-left:22px}li{margin:7px 0}li::marker{color:#8580a7}.flow-evidence code{display:inline}.flow-evidence p{font-size:12px}
.asset-row:target,tr:target{background:#f0edf9;outline:2px solid var(--accent);outline-offset:-2px;scroll-margin-top:55px}
footer{margin-top:36px;padding:20px 4px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}footer pre{white-space:pre-wrap;font:inherit}
a:focus-visible,summary:focus-visible,.table:focus-visible{outline:3px solid var(--accent);outline-offset:4px}
@media(max-width:900px){main{padding:28px 22px 55px}.card{padding:22px}.quick-steps{grid-template-columns:1fr}.quick-steps>li{padding:16px 18px}.guide-nav nav{grid-template-columns:repeat(2,minmax(0,1fr))}.workflow-steps{grid-template-columns:repeat(2,minmax(0,1fr))}.workflow-step:nth-child(n):last-child{grid-column:span 1}.workflow-step:nth-child(2n+1):last-child{grid-column:span 2}.workflow-step:nth-child(2n):not(:last-child)::after{content:'다음 줄 ↓';font-size:10px;top:auto;right:0;bottom:-24px}.flow-summary{gap:13px}}
@media(max-width:620px){body{font-size:14px}main{padding:22px 15px 45px}h1{font-size:27px}h2{font-size:22px}h3{font-size:20px}.lead{font-size:14px}.card,.quick-start{padding:20px 17px;border-radius:17px}.workflow-card{padding:17px 12px}.flow-heading{gap:8px}.frequency strong{font-size:23px}.flow-summary{grid-template-columns:1fr;gap:12px}.flow-summary>div{display:grid;grid-template-columns:100px minmax(0,1fr);gap:10px}.flow-summary span{margin:0}.workflow-steps{grid-template-columns:minmax(0,1fr);gap:25px}.workflow-step:nth-child(n):last-child{grid-column:span 1}.workflow-step:not(:last-child)::after,.workflow-step:nth-child(4n):not(:last-child)::after,.workflow-step:nth-child(2n):not(:last-child)::after{content:'↓';font-size:16px;right:50%;top:auto;bottom:-24px}.workflow-step{padding:15px;display:grid;grid-template-columns:26px minmax(0,1fr);column-gap:12px}.workflow-step h4{margin:3px 0 6px}.workflow-step p,.workflow-step small{grid-column:2}.workflow-step p{margin-bottom:3px}.domain-grid,.excluded-list{grid-template-columns:1fr}.episode{padding:12px 10px}.table{max-height:420px}.summary-count{display:block;margin-left:0}.guide-nav nav{gap:6px 12px}.overview-counts{gap:6px 14px}.workflow-card details{padding:14px 0}section{margin-top:26px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{body{background:white;font-size:10pt}main{padding:0;max-width:none}.quick-start,.guide-nav{display:none}.card{break-inside:avoid}.table{max-height:none;overflow:visible}table,.execution-table table{min-width:0;table-layout:auto}th{position:static}th,td{font-size:9px;padding:6px}h2,h3{break-after:avoid}details{display:block}.workflow-steps{grid-template-columns:repeat(2,minmax(0,1fr))}.domain-grid{display:block}a{color:inherit}}
"""


def render_report(report):
    font = Path(__file__).resolve().parents[1] / 'assets/NotoSansKR-Variable.woff'
    font_css, font_license = '', ''
    if font.is_file():
        license_file = font.with_name('OFL.txt')
        if not license_file.is_file():
            raise ValueError('Bundled font license missing')
        font_css = "@font-face{font-family:'Noto Sans KR';font-style:normal;font-weight:100 900;src:url(data:font/woff;base64," + base64.b64encode(font.read_bytes()).decode() + ") format('woff')}"
        font_license = '<details><summary>글꼴 라이선스</summary><pre>' + esc(license_file.read_text(encoding='utf-8')) + '</pre></details>'

    analysis = report.get('work_analysis', {})
    assets, sessions = report.get('assets', []), report.get('sessions', [])
    counts, coverage = report.get('summary', {}), report.get('coverage', {})
    markdown = base64.b64encode(render_markdown(report).encode('utf-8')).decode()
    definitions_index = definition_index(assets)
    flows = ''.join(_flow_html(flow, assets, definitions_index, _agent_label(report)) for flow in analysis.get('workflows', []))
    if not flows:
        flows = '<div class="empty-state">업무와 연결된 자산 저장 응답을 찾지 못해 상세 흐름으로 묶을 근거가 부족합니다. 저장된 자산이 없다는 뜻은 아닙니다. 아래 정의 목록과 수집 범위를 확인하세요.</div>'
    excluded = ''.join('<li>' + esc(EXCLUDED.get(reason, reason)) + '<b>' + str(count) + '</b><details><summary>관련 세션 확인</summary><p>' + ', '.join(_source_link(s) for s in analysis.get('excluded_sources', {}).get(reason, [])) + '</p></details></li>' for reason, count in analysis.get('excluded_candidates', {}).items())
    pending = [f for f in analysis.get('deferred_work', []) if f.get('selection_reason') != 'no_save_evidence']
    ordinary_count = len(analysis.get('deferred_work', [])) - len(pending)
    deferred = ''.join('<tr><td>' + esc(f.get('title')) + '</td><td>' + esc(_deferred_reason(f)) + '</td><td>' + str(f.get('occurrences', 0)) + '</td><td>' + _source_link(f.get('representative_session')) + '</td></tr>' for f in pending)
    rows = ''.join('<tr class="asset-row" id="' + anchor('asset', a.get('id')) + '"><td><strong>' + esc(a.get('title')) + '</strong><small>' + esc(a.get('description')) + '</small></td><td>' + esc(KINDS.get(a.get('kind'), '참고 문서')) + '</td><td>' + esc(', '.join(a.get('topics', []))) + '</td><td>' + '<br>'.join('<code>' + esc(o) + '</code>' for o in _origins(a)) + '</td></tr>' for a in assets)
    topics, selected = _topic_summary(report)
    topic_rows = ''.join('<tr><td>' + esc(t) + '</td><td>' + str(c['total']) + '</td><td>' + str(c['selected']) + '</td><td>' + str(c['total'] - c['selected']) + '</td></tr>' for t, c in topics)
    session_rows = ''.join('<tr id="' + anchor('session', s.get('id')) + '"><td>' + esc(_text(s.get('id'))[:12]) + '</td><td>' + esc(', '.join(s.get('topics') or ['미분류'])) + '</td><td>' + ('상세 FLOW 연결' if s.get('id') in selected else '유형만 분류') + '</td><td>' + '<br>'.join(esc(o) for o in _origins(s)) + '</td></tr>' for s in sessions)
    roots = ''.join('<div class="root"><b>' + esc(r.get('id')) + '</b><span>' + esc({'project': '프로젝트', 'profile': '개인 AI 설정', 'state': '관리형 상태 저장소', 'import': '검토한 내보내기'}.get(r.get('scope'), r.get('scope'))) + '</span><span>' + esc(r.get('environment')) + '</span></div>' for r in report.get('roots', []))
    warnings = ''.join('<li>' + esc(k) + ' · ' + str(v) + '건</li>' for k, v in coverage.get('warnings', {}).items()) or '<li>명시한 한도 안에서 별도 읽기 경고 없음</li>'
    scan = coverage.get('session_scan', {})
    scan_text = '세션 파일 발견 ' + str(scan.get('files_found', 0)) + ' · 읽기 ' + str(scan.get('files_scanned', 0)) + ' · 포함 ' + str(scan.get('files_kept', 0)) + ' · 부분 읽기 ' + str(scan.get('partial_files', 0))
    filters = ' / '.join(_text(k) + ': ' + str(v) for kind in ('session_filter_reasons', 'session_skip_reasons') for k, v in coverage.get(kind, {}).items()) or '별도 제외 없음'
    activity = analysis.get('asset_activity', {})
    page = ['<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; font-src data:; base-uri \'none\'; form-action \'none\'"><title>업무·도메인 자산</title><style>', font_css, CSS, '</style></head><body><main>']
    page += ['<header class="hero"><div class="hero-brand"><span class="brand-mark" aria-hidden="true">W</span><span class="eyebrow">WORK CONTEXT · 업무 자산</span></div><h1>남겨 둔 업무 방식에서 재사용할 흐름 찾기</h1><p class="lead">전체 사용 기록은 크게 분류하고, 스킬·기억·지식으로 남기는 작업을 중심으로 자세히 살펴봅니다.</p></header>',
        '<section class="quick-start" id="report-start" aria-labelledby="report-start-title"><div class="quick-heading"><h2 id="report-start-title">두 범위로 나눠 읽는 업무 보고서</h2><p>전체 유형 → 자산 중심 FLOW → 재사용할 문서</p></div><ol class="quick-steps">',
        '<li><h3><span class="step-number" aria-hidden="true">1</span>전체 업무 유형</h3><a class="quick-link" href="#sessions">큰 분류 보기</a><p>자산을 저장하지 않은 세션도 업무 유형에 포함합니다. 모든 호출을 상세 FLOW로 펼치지는 않습니다.</p></li>',
        '<li><h3><span class="step-number" aria-hidden="true">2</span>자산 중심 업무 FLOW</h3><a class="quick-link" href="#workflows">상세 흐름 보기</a><p>스킬·기억·지식 생성·수정 호출의 응답이 관찰된 업무를 골랐습니다. 하려던 일과 실제 도구 동작도 함께 봅니다.</p><small>스킬 불러오기만으로 선정하지 않습니다.</small></li>',
        '<li><h3><span class="step-number" aria-hidden="true">3</span>팀의 업무 지식으로 정리</h3><a id="download-markdown" class="download" href="data:text/markdown;charset=utf-8;base64,', markdown, '" download="업무자산.md">업무 자산 Markdown 받기 <span aria-hidden="true">↓</span></a><p>문서에 기준과 예외를 보완해 다른 사람과 재사용하세요.</p></li></ol>',
        '<ul class="overview-counts" aria-label="이번 보고서에서 확인한 범위"><li><strong>전체 세션 ', str(len(sessions)), '개</strong> · 큰 분류</li><li><strong>상세 FLOW ', str(len(analysis.get('workflows', []))), '개</strong> · 자산 저장 응답 근거</li><li><strong>자산 정의 ', str(counts.get('defined_assets', 0)), '개</strong> · 파일 발견</li></ul></section>',
        '<details class="guide-nav" open><summary>필요한 내용 바로 찾기</summary><nav aria-label="보고서 목차"><a href="#sessions">전체 세션의 큰 분류</a><a href="#workflows">자산 중심 업무 FLOW</a><a href="#domain-assets">발견한 스킬·지식·기억</a><a href="#deferred">저장·연결 미확인</a><a href="#coverage">수집 범위</a></nav></details>',
        '<section class="report-section card" id="sessions"><h2>전체 세션의 큰 업무 유형</h2><p class="section-lead">상세 FLOW 선정 여부와 관계없이 포함한 모든 세션을 분류합니다. 한 세션에 여러 유형이 있으면 중복 집계하며, 세션 수는 업무량이나 성과가 아닙니다.</p>',
        _table('전체 세션 업무 유형 표', ['업무 유형 후보', '전체 세션', '상세 FLOW 연결', '유형만 분류'], topic_rows or '<tr><td colspan="4">분류할 세션이 없습니다.</td></tr>'),
        '<details><summary>세션별 분류·출처 확인</summary>', _table('세션 관찰 표', ['세션 근거', '업무 유형 후보', '정리 범위', '출처'], session_rows or '<tr><td colspan="4">포함할 세션 근거가 없습니다.</td></tr>'), '</details></section>',
        '<section class="report-section card" id="workflows"><h2>자산 중심 업무 FLOW</h2><p class="section-lead">스킬·기억·지식 저장 응답을 해당 업무 요청과 연결했습니다. 같은 세션의 무관한 작업은 합치지 않으며, 저장 호출의 응답이 현재 자산의 존재나 정확성을 보증하지는 않습니다.</p>', flows, '</section>',
        '<section class="report-section card" id="domain-assets"><h2>발견한 스킬·지식·기억</h2><p>지정 범위에 현재 남아 있는 정의입니다. 생성한 세션을 확인하지 못해도 목록에 남깁니다. 정의가 있다는 이유로 사용 절차나 실행 FLOW를 추측하지 않습니다.</p><p class="table-hint">표 안에서 가로·세로로 스크롤할 수 있습니다. 키보드로는 표를 선택한 뒤 방향키를 사용하세요.</p>',
        _table('스킬 지식 기억 출처 표', ['자산', '종류', '분류 후보', '출처'], rows or '<tr><td colspan="4">지정 범위에서 자산을 찾지 못했습니다.</td></tr>'), '</section>',
        '<section class="report-section card" id="deferred"><h2>저장·연결을 확인하지 못한 기록</h2><p>자산 저장 근거가 없는 업무 묶음 ', str(ordinary_count), '개는 전체 유형 분류에만 포함했습니다. 실패·응답 미확인·여러 업무가 섞인 저장은 아래에 구분합니다.</p>',
        _table('보류한 업무 표', ['업무 대상', '보류 이유', '관찰 묶음', '출처'], deferred) if deferred else '<p class="muted">별도의 저장 실패·응답 미확인 묶음은 없습니다.</p>',
        '<p class="muted">자산 생성·수정 호출 ', str(activity.get('observed_changes', 0)), '개 중 업무 연결 미확인 ', str(activity.get('unlinked_changes', 0)), '개. 근거가 부족한 기록으로 상세 절차를 채우지 않습니다.</p><details><summary>일상 대화·단계 근거 부족 후보</summary><ul class="excluded-list">', excluded or '<li>별도 제외 후보 없음</li>', '</ul></details></section>',
        '<section class="report-section card" id="coverage"><h2>수집 범위와 누락</h2><div class="roots">', roots, '</div><p>', esc(scan_text), '</p><p class="muted">', esc(filters), '</p><ul>', warnings, '</ul><div class="note">지정 폴더와 확인된 현재 사용자 세션 저장소만 관찰했습니다. 옛 기록의 저장 근거가 없으면 상세 FLOW에서 제외되지만 전체 유형 분류에는 남습니다. 공유 전 업무 이름·파일 이름·정의 설명을 검토하세요.</div></section>',
        '<footer>로컬 생성 · 원본 수정 및 업로드 없음 · 추가 모델 호출 없음 · 재집계 자료: catalog.json<br>기록의 정의·저장 응답·실제 성공은 서로 다릅니다. 실행 가능한 스킬이나 공식 규정으로 자동 등록하지 않습니다.', font_license, '</footer></main></body></html>']
    return ''.join(page)
