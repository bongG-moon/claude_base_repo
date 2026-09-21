"""Local execution observations, independent of selection and body loading.

Consumed only by diagnostics, never by permission/Stop/selection decisions.
No business/output-file reads, model calls, commands, transcripts, or output
paths. Command identity uses the existing local entrypoint checks. A runtime's
success report is not proof of document coverage or output quality.
"""
from __future__ import annotations

import json

from .skill_decision import NEXT_ACTIONS


# Observe known business invocations, not metadata/help/choice preparation.
# This is NOT a skill-name -> command dispatcher and never invokes anything.
OPERATIONS = frozenset({'html', 'ppt', 'ppt-preview', 'ppt-design-preview', 'ppt-template', 'ppt-fit-images',
                       'ppt-inspect', 'ppt-analyze', 'html-template', 'eml-read', 'artifact-publish',
                       'mail-read', 'mail-search', 'files-execute', 'files-undo'})
MAX_RESULT_CHARS = 65_536
BODY_LABELS = {'loaded': '본문 로드 관찰', 'reused': '이 대화에서 읽은 동일 본문 재사용',
               'host-loaded': '호스트 스킬 로드 관찰(로컬 목록 밖)',
               'not-observed': '본문 로드 미관찰'}
RESULT_LABELS = {
    'not-observed': '업무 실행 결과 미관찰',
    'not-performed': '도구 미실행(승인 거절 또는 승인 판단 불가)',
    'failed': '실행 오류 관찰(일부 동작 여부는 별도 확인)',
    'interrupted': '중단 관찰(일부 동작 여부는 별도 확인)',
    'partial': '실행기 부분 완료 보고', 'cancelled': '실행기 취소 보고',
    'blocked': '실행기 제한 보고', 'input-required': '실행기 입력 대기 보고',
    'reported-success': '실행기 성공 보고(내용·범위 검증과 별개)',
    'result-unavailable': '도구 응답 관찰, 업무 결과 해석은 미확인',
}


def _mapping(value):
    return value if isinstance(value, dict) else {}


def body_status(route: dict, turn: str) -> str:
    selected = _mapping(route.get('selected'))
    observed = _mapping(route.get('loadObservation'))
    loaded = _mapping(route.get('lastBodyLoad'))
    reads = _mapping(route.get('readSkills'))
    sha = selected.get('sha256')
    if isinstance(sha, str) and sha and isinstance(selected.get('id'), str) and reads.get(selected['id']) == sha:
        if loaded.get('turn') == turn and loaded.get('id') == selected.get('id') and loaded.get('sha256') == sha:
            return 'loaded'
        plan = _mapping(route.get('executionPlan'))
        if plan.get('mode') == 'reuse' and plan.get('basis') == 'observed-body-load' and plan.get('id') == selected.get('id'):
            return 'reused'
    if observed.get('turn') == turn and observed.get('status') == 'native-skill-outside-catalog':
        return 'host-loaded'
    return 'not-observed'


def _result_status(payload: dict, not_performed: bool) -> str:
    if not_performed:
        return 'not-performed'
    response = _mapping(payload.get('tool_response'))
    if response.get('interrupted') is True:
        return 'interrupted'
    if (payload.get('hook_event_name') == 'PostToolUseFailure' or payload.get('error') or payload.get('tool_error')
            or response.get('isError') is True or response.get('is_error') is True):
        return 'failed'
    for key in ('exitCode', 'exit_code'):
        if type(response.get(key)) is int and response[key] != 0:
            return 'failed'
    # No tail scans, lossy parsing, or opening a redirected output file. Large
    # or unfamiliar host responses remain unknown rather than claiming success.
    stdout = response.get('stdout')
    if not isinstance(stdout, str) or len(stdout) > MAX_RESULT_CHARS:
        return 'result-unavailable'
    try:
        result = json.loads(stdout)
    except (ValueError, RecursionError):
        return 'result-unavailable'
    if not isinstance(result, dict):
        return 'result-unavailable'
    status = result.get('status')
    partial = {'partial': 'partial', 'cancelled': 'cancelled', 'blocked': 'blocked',
               'input_required': 'input-required'}
    if isinstance(status, str) and status in partial:
        return partial[status]
    if result.get('ok') is False:
        return 'failed'
    if result.get('ok') is True:
        return 'reported-success'
    return 'result-unavailable'


def observe_business_result(state: dict, payload: dict, *, not_performed: bool = False) -> None:
    """Join the existing state write; latest observation only, no extra hook."""
    route = _mapping(state.get('skillWorkflow'))
    turn = state.get('turnId')
    if (not turn or route.get('turn') != turn or payload.get('tool_name') not in {'Bash', 'PowerShell'}
            or payload.get('hook_event_name') not in {'PostToolUse', 'PostToolUseFailure'}):
        return
    inputs = _mapping(payload.get('tool_input'))
    command = inputs.get('command') or inputs.get('cmd') or ''
    if not isinstance(command, str) or len(command) > 16_384 or 'business' not in command:
        return
    from .execution_contract import _trusted_arguments
    args = _trusted_arguments(command)
    if not args or len(args) < 2 or args[0] != 'business' or args[1] not in OPERATIONS or '--help' in args or '-h' in args:
        return
    route['businessObservation'] = {
        'turn': turn, 'operation': args[1], 'status': _result_status(payload, not_performed),
        'bodyAtResponse': body_status(route, turn),
    }


def workflow_progress(state: dict) -> dict:
    """Allowlisted diagnostic projection; never infer success from a load."""
    turn = state.get('turnId')
    route = _mapping(state.get('skillWorkflow'))
    route = route if turn and route.get('turn') == turn else {}
    plan = _mapping(route.get('executionPlan'))
    mode = plan.get('mode')
    mode = mode if isinstance(mode, str) and mode in NEXT_ACTIONS else 'unknown'
    body = body_status(route, turn) if route else 'not-observed'
    observed = _mapping(route.get('businessObservation'))
    observed = observed if route and observed.get('turn') == turn else {}
    operation, status, at_response = observed.get('operation'), observed.get('status'), observed.get('bodyAtResponse')
    if not isinstance(operation, str) or operation not in OPERATIONS:
        operation, status, at_response = None, None, None
    status = status if isinstance(status, str) and status in RESULT_LABELS else 'not-observed'
    at_response = at_response if isinstance(at_response, str) and at_response in BODY_LABELS else 'not-observed'
    return {'decision': mode, 'body': body, 'bodyMessage': BODY_LABELS[body],
            'operation': operation, 'execution': status, 'executionMessage': RESULT_LABELS[status],
            'bodyAtResponse': at_response, 'bodyAtResponseMessage': BODY_LABELS[at_response],
            'skillApplication': 'not-verified', 'resultQuality': 'not-verified'}
