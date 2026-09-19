"""Small failure categories; no transcript persistence or permissions changes."""
from pathlib import Path
import json
import subprocess
import re


def classifier_unavailable(payload):
    return (isinstance(payload,dict) and payload.get('hook_event_name') == 'PostToolUseFailure'
            and payload.get('tool_name') in {'Bash','PowerShell'}
            and isinstance(payload.get('error'),str)
            and bool(re.match(r'^[\w./:\[\]-]{1,200} is temporarily unavailable \(timed out\), so auto mode cannot determine the safety of (?:Bash|PowerShell) right now\.',payload['error'])))


def failure_hint(payload):
    if not isinstance(payload,dict) or payload.get('hook_event_name') != 'PostToolUseFailure':
        return None
    error=payload.get('error','')
    if not isinstance(error,str):
        return None
    error=error[:20000]
    if classifier_unavailable(payload):
        return {'category':'approval_classifier_timeout','executionState':'not_approved_by_this_attempt',
                'message':'실행 전 안전 확인이 지연되어 해당 작업을 기다리고 있습니다.',
                'instruction':'This is a safety-classifier timeout, not a PPT or Bash execution timeout. Do not rewrite the operation, switch tools, or disable permissions to get around it. Retry at most once after a brief pause only for this transient outage, never for a denial; if it persists, leave this operation pending. Continue unrelated permitted reads. Do not report verify fail or run learning for this outage. Preserve prepared inputs, inspect earlier-attempt outputs before any later retry, and tell the user only the short Korean pending message. Native UI errors cannot be hidden by this hook.'}
    # Real permission/protection failures must not become code-retry advice.
    if payload.get('is_interrupt') or re.search(r'denied|not (?:allowed|approved)|cancelled|canceled|권한|거절|취소|보호 제한', error, re.I):
        return None
    tool = payload.get('tool_name')
    if tool in {'Bash', 'PowerShell'} and 'Traceback (most recent call last):' in error:
        exact = bool(re.search(r'(?m)^re\.(?:error|PatternError):', error))
        partial = bool(re.search(r'[\\/]re[\\/]__init__\.py["\'], line \d+, in compile', error))
        if exact or partial:
            return {'category': 'python_regex_error' if exact else 'python_regex_trace_incomplete',
                    'executionState': 'failed_partial_effects_unknown',
                    'message': '정규식 처리 오류입니다.' if exact else '정규식 처리 중 오류가 보이지만 마지막 예외 문장이 필요합니다.',
                    'instruction': '인코딩·경로·Write 실패로 단정하지 마세요. 마지막 예외 문장과 해당 패턴을 확인하세요. '
                        '소스는 UTF-8 파일로 작성·Read 확인하고 Python -X utf8로 직접 실행하세요. 중첩된 -Command/-c로 다시 감싸지 마세요. '
                        '문자열 검색은 re.escape, 구조화 자료는 해당 파서를 사용하세요. 의도한 패턴과 정규식 특수문자를 포함한 입력으로 부작용 없는 검사부터 하세요. '
                        '오류 이전의 파일 생성·변경 여부를 확인해 중복 실행을 막고 실제 권한 거절은 유지하세요.'}
    if tool == 'Write' and error.strip():
        return {'category': 'write_failed', 'executionState': 'failed_partial_effects_unknown',
                'message': '파일 쓰기 결과를 확인해야 합니다.',
                'instruction': '실패 응답과 요청한 정확한 절대경로를 확인하고 필요하면 해당 파일만 Read하세요. '
                    '파일 없음·부모 폴더 없음·잘못된 경로·인코딩 오류를 구분하고 근거 없이 한글 경로 문제로 단정하지 마세요. '
                    '경로를 임의로 바꾸거나 긴 코드를 인라인으로 전환하지 마세요. 실제 거절은 다른 도구로 재시도하지 마세요. '
                    '성공한 기존 쓰기는 반복하지 말고 확인된 원인만 수정하세요.'}
    if '인덱스가 배열 범위를 벗어' in error or 'Index was outside the bounds' in error:
        return {'category':'native_launcher_error','executionState':'unknown',
                'message':'Claude 실행 연결에서 오류가 발생했습니다. 실행 경로와 종료 방법을 확인해야 합니다.',
                'instruction':'Root cause is not confirmed. Do not delete npm wrappers, change PATH, suppress errors, or claim the session was saved. Compare /exit and Ctrl+C in the same user environment; collect runtime-check metadata only.'}
    return None


def recovery_hint_once(payload, hint, root=None):
    """At most one short recovery hint per category/turn; store no error/code."""
    if not hint or hint.get('category') not in {'python_regex_error', 'python_regex_trace_incomplete', 'write_failed'}:
        return hint
    session = payload.get('session_id')
    if not session:
        return hint
    from .state import _locked_session, _stale_native_prompt
    from .paths import atomic_write_json, user_state_root
    with _locked_session(str(session), root or user_state_root()) as (state, path):
        if _stale_native_prompt(payload, state):
            return None
        turn = state.get('turnId', '')
        receipt = state.get('executionRecovery', {})
        previous = receipt.get('categories', []) if isinstance(receipt, dict) and receipt.get('turn') == turn else []
        categories = [x for x in previous if isinstance(x, str) and x in {'python_regex', 'write_failed'}] if isinstance(previous, list) else []
        category = 'python_regex' if hint['category'].startswith('python_regex') else 'write_failed'
        if category in categories:
            return None
        state['executionRecovery'] = {'turn': turn, 'categories': [*categories, category][-2:]}
        atomic_write_json(path, state)
    return hint


def inspect_runtime():
    from .business_artifacts import _windows_powershell
    shell=_windows_powershell()
    if not shell:
        return {'ok':False,'status':'unavailable','message':'Windows PowerShell 진단을 실행할 수 없습니다.'}
    script=Path(__file__).resolve().parents[1]/'Inspect-ClaudeRuntime.ps1'
    try:
        proc=subprocess.run([shell,'-NoLogo','-NoProfile','-NonInteractive','-File',str(script)],
                            capture_output=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        result=json.loads(proc.stdout.decode('utf-8-sig'))
        if proc.returncode or not isinstance(result,dict):
            raise ValueError('invalid result')
        return result
    except (OSError,ValueError,subprocess.TimeoutExpired):
        return {'ok':False,'status':'unavailable','message':'실행 위치 진단을 완료하지 못했습니다. 설정은 변경하지 않았습니다.'}
