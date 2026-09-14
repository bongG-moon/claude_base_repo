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
    if '인덱스가 배열 범위를 벗어' in error or 'Index was outside the bounds' in error:
        return {'category':'native_launcher_error','executionState':'unknown',
                'message':'Claude 실행 연결에서 오류가 발생했습니다. 실행 경로와 종료 방법을 확인해야 합니다.',
                'instruction':'Root cause is not confirmed. Do not delete npm wrappers, change PATH, suppress errors, or claim the session was saved. Compare /exit and Ctrl+C in the same user environment; collect runtime-check metadata only.'}
    return None


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
