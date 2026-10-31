"""Requested-only usability review. Summarize existing evidence, never collect live work.

This module is lazily imported by the CLI. It has no hook or scheduler entrypoint.
The console is a short receipt; the bounded offline HTML holds optional detail.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path

from . import __version__

TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')
MAX_CONSOLE_CHARS = 2400


def _total(rows, field):
    values = [row.get(field) for row in rows]
    return sum(values) if values and all(type(v) is int and v >= 0 for v in values) else None


def summarize(collected: dict, project: Path) -> dict:
    """Keep confirmed counts separate from improvement candidates and snapshots."""
    logs, states = collected['transcripts'], collected['states']
    fields = ('requests', 'toolCalls', 'toolErrors', 'repeatedFailedCalls', 'questionCalls',
              'repeatedQuestions', 'sameRangeReads', 'questionWaitMs', 'questionPairs')
    metrics = {key: _total(logs, key) for key in fields}
    metrics.update(transcriptSessions=len(logs),
                   # Summing session spans double-counts overlapping work. There is
                   # no total execution-time metric without a stronger contract.
                   observedSpanMs=logs[0].get('observedSpanMs') if len(logs) == 1 else None,
                   tokens={key: _total([row.get('tokens', {}) for row in logs], key) for key in TOKEN_FIELDS})
    hooks = [hook for row in states for hook in row.get('hooks', [])]
    measured_hooks = [h for h in hooks if type(h.get('elapsedMs')) is int]
    finished_hooks = [h for h in hooks if h.get('status') in {'failed', 'output-produced'}]
    observed_loads = [row for row in states if row.get('loadStatus') not in {None, 'unknown', 'not-observed'}]
    snapshots = {'sessions': len(states), 'toolFailures': _total(states, 'taskFailureCount'),
                 'slowPreparation': sum(h['elapsedMs'] >= 1000 for h in measured_hooks) if measured_hooks else None,
                 'failedPreparation': sum(h.get('status') == 'failed' for h in finished_hooks) if finished_hooks else None,
                 'maxContextChars': max((h['contextChars'] for h in hooks if type(h.get('contextChars')) is int), default=None),
                 'loadFailures': sum(row.get('loadStatus') in {'tool-failed', 'choice-unresolved', 'catalog-unavailable',
                                       'skill-path-unmatched', 'name-ambiguous'} for row in observed_loads) if observed_loads else None}
    candidates = []

    def add(code, title, count, detail, step, evidence, confidence='개선 후보'):
        if count:
            candidates.append({'code': code, 'title': title, 'count': count, 'detail': detail,
                               'nextStep': step, 'evidence': evidence, 'confidence': confidence})

    add('repeat-failure', '실패한 같은 동작을 다시 요청한 기록이 있어요', metrics['repeatedFailedCalls'],
        '같은 요청 안에서 실패 후 같은 도구와 입력을 다시 사용했습니다. 정상적인 재시도일 수도 있습니다.',
        '담당자는 처음 실패한 원인을 확인하고, 같은 실패가 계속될 때 반복 실행 대신 해결 방법을 안내하도록 점검하세요.',
        '현재 요청 안의 도구 입력 해시와 오류 응답을 연결한 관찰 수입니다.', '반복 호출 관찰')
    add('repeat-question', '같은 질문이 반복된 기록이 있어요', metrics['repeatedQuestions'],
        '같은 요청에서 동일한 선택 질문이 다시 호출됐습니다. 답변을 무시했거나 불필요했다는 뜻으로 단정하지 않습니다.',
        '이미 고른 내용을 다시 물었다면 담당자에게 이 보고서를 전달하세요. 사용자가 설정을 초기화할 필요는 없습니다.',
        'AskUserQuestion 입력이 같은 요청 안에서 동일한 경우만 셉니다.', '개선 후보')
    add('tool-error', '실행 오류를 먼저 살펴보면 좋아요', metrics['toolErrors'],
        '도구가 오류로 응답한 기록입니다. 이후 복구했는지와 최종 결과가 잘못됐는지는 이 수치만으로 알 수 없습니다.',
        '담당자는 오류가 난 동작을 먼저 좁혀 확인하세요. 결과를 이미 받았다면 같은 업무를 다시 실행하지 마세요.',
        '선택 기간에 호출과 오류 응답이 모두 확인된 도구 수입니다.', '오류 응답 관찰')
    add('preparation-failure', '최근 실행 준비를 확인해 주세요', (snapshots['failedPreparation'] or 0) + (snapshots['loadFailures'] or 0),
        '최근 저장된 준비 또는 스킬 불러오기 상태에 확인이 필요한 기록이 있습니다. 기간 전체의 실패 횟수는 아닙니다.',
        '담당자는 현재 설치와 사용한 스킬의 연결을 확인하세요. 개인 자료를 지우거나 재설치부터 할 필요는 없습니다.',
        '하네스가 마지막으로 남긴 상태만 사용한 제한된 관찰입니다.', '최근 상태')
    add('slow-preparation', '최근 준비 단계에 1초 이상 걸린 기록이 있어요', snapshots['slowPreparation'],
        '이는 하네스 내부 준비 시간이며 모델의 답변 시간이나 전체 작업 시간은 아닙니다. 반복 지연인지는 추가 표본이 필요합니다.',
        '담당자는 스킬 목록과 기억 검색의 준비 시간을 확인하세요. 모델을 바꾸기 전에 준비 단계부터 비교하는 것이 좋습니다.',
        '최근 SessionStart 또는 UserPromptSubmit 기록 중 1,000ms 이상인 표본입니다.', '최근 상태')
    add('repeat-read', '같은 범위를 다시 읽은 기록이 있어요', metrics['sameRangeReads'],
        '수정 결과를 확인하거나 대화 압축 후 다시 읽은 정상 동작일 수도 있습니다.',
        '변경되지 않은 자료의 재읽기가 많을 때만 재사용 방법을 점검하세요. 필요한 결과 확인은 유지합니다.',
        '같은 요청에서 파일 경로와 읽기 범위가 같았던 호출 수입니다. 경로와 내용은 보고서에 넣지 않습니다.', '개선 후보')
    has_data = bool(logs or states)
    coverage = collected['coverage']
    partial = coverage.get('status') == 'partial' or coverage.get('truncated') or coverage.get('warnings') or any(row.get('usageMissing') for row in logs)
    status = 'no-data' if not has_data else 'partial' if partial or not logs else 'observed'
    title = '먼저 확인할 부분을 정리했어요' if candidates else '지금 기록으로 확인할 수 있는 범위예요'
    if not has_data:
        title = '아직 분석할 기록이 부족해요'
    message = ('현재 업무 폴더의 해당 기간 기록을 찾지 못했습니다. 평소처럼 작업한 뒤 다시 요청해 주세요.' if not has_data else
               '관찰 근거가 있는 항목을 최대 3개로 추렸습니다. 확정된 원인이나 자동 수정 결과는 아닙니다.' if candidates else
               '수집한 기록에서 우선 확인할 후보를 찾지 못했습니다. 모든 기능이 정상이라는 보장은 아닙니다.')
    limitations = list(collected.get('constraints', [])) + [
        '사용자 대기와 모델 처리 시간을 모두 분리할 기록은 없습니다. 확인된 질문 대기만 따로 표시합니다.',
        '하네스 준비 기록은 최신 상태입니다. 선택 기간 전체의 평균이나 모든 오류를 대표하지 않습니다.',
        '누락된 토큰은 0으로 계산하지 않습니다. 문자 수를 토큰 수로 환산하거나 사내 비용을 추정하지 않습니다.',
        '동일 동작이나 질문의 반복은 개선 후보입니다. 실제 불편 여부와 원인은 담당자가 확인해야 합니다.',
        '이 보고서는 개인 기억과 스킬을 학습하거나 고치지 않으며, 대화를 압축하지 않습니다.',
    ]
    canonical = os.path.normcase(str(project.resolve()))
    return {'schemaVersion': 1, 'generatorVersion': __version__,
            'scopeKey': hashlib.sha256(canonical.encode('utf-8')).hexdigest(),
            'generatedAt': datetime.now(timezone.utc).isoformat(), 'window': collected['window'],
            'summary': {'status': status, 'title': title, 'message': message}, 'coverage': coverage,
            'metrics': metrics, 'snapshots': snapshots, 'findings': candidates[:3],
            'limitations': list(dict.fromkeys(limitations)), 'modelCalls': 0}


class _Previous(HTMLParser):
    value = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'meta' and attributes.get('name') == 'usability-report':
            if self.value is not None:
                raise ValueError('이전 보고서의 비교 정보가 중복되어 있습니다.')
            self.value = attributes.get('content', '')


def compare(report: dict, previous: Path) -> dict:
    """Report observed changes only; no causal efficiency claim across workloads."""
    from .skill_registry import _no_reparse
    previous = Path(previous).absolute()
    _no_reparse(previous)
    with previous.open('rb') as stream:
        raw = stream.read(512_001)
    if len(raw) > 512_000:
        raise ValueError('이전 보고서가 비교 가능한 크기를 초과합니다.')
    parser = _Previous()
    parser.feed(raw.decode('utf-8-sig'))
    try:
        if not parser.value or len(parser.value) > 32_000:
            raise ValueError()
        old = json.loads(base64.b64decode(parser.value, validate=True))
        if not isinstance(old, dict) or old.get('schemaVersion') != 1:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('이 기능에서 만든 이전 HTML 보고서를 선택해 주세요.') from None
    response = {'status': 'not-comparable', 'message': '같은 폴더와 같은 길이의 겹치지 않는 기간일 때 관찰 수치를 비교합니다.', 'rows': []}
    if old.get('scopeKey') != report['scopeKey'] or not isinstance(old.get('window'), dict):
        return response
    before, after = old['window'], report['window']
    try:
        end = datetime.fromisoformat(before['until'])
        start = datetime.fromisoformat(after['since'])
        comparable = before['days'] == after['days'] and end.tzinfo and start.tzinfo and end <= start
    except (ValueError, TypeError, KeyError):
        return response
    if not comparable:
        return response
    prior_metrics = old.get('metrics')
    if not isinstance(prior_metrics, dict):
        return response
    response.update(status='observational', message='서로 다른 기간에 관찰한 수치입니다. 업무와 기록량이 다를 수 있어 개선 효과나 절감률로 단정하지 않습니다.')
    for key, label in [('requests', '확인한 요청'), ('toolCalls', '도구 호출'), ('toolErrors', '오류 응답'),
                       ('repeatedFailedCalls', '실패 후 동일 호출'), ('repeatedQuestions', '같은 질문 반복')]:
        a, b = prior_metrics.get(key), report['metrics'].get(key)
        if type(a) is int and a >= 0 and type(b) is int and b >= 0:
            response['rows'].append({'label': label, 'before': a, 'after': b, 'unit': '건'})
    return response


def command(args) -> int:
    from .usability_sources import collect
    from .usability_report import write_report
    from .paths import user_state_root
    project = Path(args.project_root or os.environ.get('COMPANY_AGENT_CWD') or Path.cwd()).absolute()
    if not project.is_dir():
        raise ValueError('현재 업무 폴더를 확인해 주세요.')
    claude = Path(args.claude_root or os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude').absolute()
    root = Path(args.state_root).absolute() if args.state_root else user_state_root().absolute()
    report = summarize(collect(project, root, claude, days=args.days, logs=args.usage_log), project)
    if args.compare_to:
        report['comparison'] = compare(report, Path(args.compare_to))
    output = Path(args.output).absolute() if args.output else project / ('사용성-개선-보고서-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.html')
    write_report(output, report)
    # Only a bounded receipt reaches Claude. Full logs never become model input.
    receipt = {'ok': True, 'status': report['summary']['status'], 'message': report['summary']['message'],
               'reportPath': str(output), 'days': args.days, 'modelCalls': 0,
               'findings': [{'title': row['title'], 'count': row['count'], 'nextStep': row['nextStep']} for row in report['findings']],
               'partial': report['summary']['status'] != 'observed',
               'notice': '상세 기록과 수집 한계는 HTML에서 확인하세요. 보고서 작성으로 대화를 압축하거나 설정을 변경하지 않았습니다.'}
    text = json.dumps(receipt, ensure_ascii=False)
    if len(text) > MAX_CONSOLE_CHARS:
        receipt['findings'] = [{'title': row['title'], 'count': row['count']} for row in report['findings']]
        # An unusually long output path stays exact in the final receipt. Never
        # silently truncate it into a different file name.
        text = json.dumps(receipt, ensure_ascii=False)
    print(text)
    return 0


def register(subparsers):
    parser = subparsers.add_parser('usability-report', help='요청할 때만 기존 기록으로 사용성 개선 HTML을 만듭니다.')
    parser.add_argument('--project-root')
    parser.add_argument('--state-root')
    parser.add_argument('--claude-root')
    parser.add_argument('--days', type=int, default=7, choices=range(1, 31), metavar='1..30')
    parser.add_argument('--usage-log', action='append', default=[], type=Path)
    parser.add_argument('--output', help='새 HTML 파일 경로. 기존 파일은 덮어쓰지 않습니다.')
    parser.add_argument('--compare-to', help='이전에 생성한 HTML 보고서와 관찰 수치 비교')
    parser.set_defaults(func=command)
