"""Conversation consent for one bounded Office read, not a permission bypass.

Only native user-input events can record an answer. CLI/spec flags cannot grant
consent. Like the other local receipts, this assumes a trusted local state root;
it is not an OS security boundary against a process running as the same user.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time

from .business_safety import safe_path
from .paths import atomic_write_json
from .state import _locked_session, _stale_native_prompt

TTL = 15 * 60
APPROVE = '이 범위 읽기 승인'
CANCEL = '취소'


def _session(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', value) and value != 'unknown-session'


def _project(cwd):
    return str(safe_path(cwd, exists=True)).casefold()


def _fresh(receipt, cwd):
    return (isinstance(receipt, dict) and receipt.get('project') == _project(cwd)
            and isinstance(receipt.get('created'), (int, float))
            and 0 <= time.time() - receipt['created'] <= TTL)


def question(request):
    if request['kind'] == 'excel':
        scope = f"시트 {request['sheet']}, 범위 {request['range']} (최대 200행·20열·2,000셀)"
    else:
        unit = '슬라이드' if request['kind'] == 'powerpoint' else '문단'
        scope = f"{unit} {request['start']}~{request['end']}"
    return (f"다음 문서를 읽어 Claude에서 정리할까요?\n파일: {request['file']}\n"
            f"읽을 범위: {scope}, 최대 {request['maxChars']:,}자\n"
            '회사에서 AI 처리·대화 기록 보존을 허용한 자료만 승인해 주세요. '
            '원본은 저장·변환하지 않고 본문을 별도 Memory/Knowledge에 저장하지 않습니다. '
            'Office 임시 파일과 Claude 대화 기록은 남을 수 있으며, 승인이 회사 정책·접근 권한을 대신하지 않습니다.')


def authorize(request, *, root, session_id='', cwd=None):
    """Return None only when consuming a matching, unexpired user answer."""
    cwd = cwd or Path.cwd()
    if not _session(session_id):
        return {'ok': False, 'status': 'input_required', 'code': 'conversation_session_required',
                'message': 'Claude 대화에서 현재 company_agent_session_id를 --session에 넣어 다시 요청하세요. 별도 승인 창은 열지 않았습니다.',
                'sourceOpened': False}
    safe_path(root)
    source = safe_path(request['file'], exists=True)
    info = source.stat()
    signature = hashlib.sha256(json.dumps([request, info.st_size, info.st_mtime_ns, info.st_ino],
                                          sort_keys=True, ensure_ascii=True).encode('ascii')).hexdigest()
    with _locked_session(session_id, root) as (state, path):
        safe_path(path)
        receipt = state.get('officeReadConsent')
        same = _fresh(receipt, cwd) and receipt.get('signature') == signature
        if same and receipt.get('status') == 'approved':
            receipt['status'] = 'consumed'
            atomic_write_json(path, state)
            return None
        if same and receipt.get('status') == 'cancelled':
            return {'ok': False, 'status': 'cancelled', 'message': '문서 읽기를 취소했습니다. Office는 열지 않았습니다.', 'sourceOpened': False}
        if not same or receipt.get('status') != 'pending':
            receipt = {'signature': signature, 'project': _project(cwd), 'created': time.time(),
                       'status': 'pending', 'question': question(request), 'toolUseId': None}
            state['officeReadConsent'] = receipt
            atomic_write_json(path, state)
        return {'ok': False, 'status': 'input_required', 'code': 'office_read_consent', 'sourceOpened': False,
                'message': '아래 질문을 Claude 대화에서 보여주고 답변을 기다리세요. 오류·권한 실패가 아닙니다.',
                'questions': [{'header': '문서 읽기', 'question': receipt['question'], 'multiSelect': False,
                               'options': [{'label': APPROVE, 'description': '표시된 파일·범위만 읽어 현재 대화에서 처리합니다.'},
                                           {'label': CANCEL, 'description': '문서를 열지 않고 중단합니다.'}]}],
                'next': 'AskUserQuestion으로 questions를 그대로 표시하세요. 도구가 없으면 질문을 그대로 보여주고 승인/취소 답변을 기다리세요. 승인 후 같은 --session과 범위로 한 번만 다시 실행하세요. 승인 값을 직접 쓰거나 다른 작업자에게 질문을 넘기지 마세요.'}


def observe(root, cwd, payload):
    """Bind native question dispatch/result; accept a narrow plain-chat fallback."""
    session = payload.get('session_id')
    event = payload.get('hook_event_name')
    if not _session(session) or event not in {'PreToolUse', 'PostToolUse', 'UserPromptSubmit'}:
        return ''
    if event != 'UserPromptSubmit' and payload.get('tool_name') != 'AskUserQuestion':
        return ''
    with _locked_session(session, root) as (state, path):
        receipt = state.get('officeReadConsent')
        if not _fresh(receipt, cwd):
            return ''
        if _stale_native_prompt(payload, state):
            return ''
        if receipt.get('status') != 'pending':
            if event == 'UserPromptSubmit':
                # A new instruction/revocation must not leave an earlier,
                # unconsumed approval available to a later worker.
                state.pop('officeReadConsent', None)
                atomic_write_json(path, state)
            return ''
        inputs = payload.get('tool_input') or {}
        answer = None
        if event == 'PreToolUse':
            # Answers supplied in input are programmatic, not a fresh user click.
            questions = inputs.get('questions', [])
            receipt['toolUseId'] = None
            if (not inputs.get('answers') and isinstance(questions, list)
                    and len(questions) == 1 and isinstance(questions[0], dict)
                    and questions[0].get('question') == receipt['question']
                    and questions[0].get('multiSelect', False) is False
                    and [o.get('label') for o in questions[0].get('options', []) if isinstance(o, dict)] == [APPROVE, CANCEL]):
                receipt['toolUseId'] = payload.get('tool_use_id')
            atomic_write_json(path, state)
            return ''
        if event == 'PostToolUse':
            response = payload.get('tool_response')
            if (not receipt.get('toolUseId') or payload.get('tool_use_id') != receipt['toolUseId']
                    or payload.get('error') or payload.get('tool_error')
                    or not isinstance(response, dict) or response.get('isError') or response.get('is_error')):
                return ''
            answers = response.get('answers')
            if isinstance(answers, dict):
                answer = answers.get(receipt['question'])
        else:
            # Any other new instruction invalidates a pending question. Never
            # extract an approval substring from quoted documents or long text.
            text = payload.get('prompt', payload.get('user_prompt', ''))
            text = text.strip() if isinstance(text, str) else ''
            answer = APPROVE if text in {APPROVE, '승인', '승인합니다', '네, 승인합니다'} else CANCEL if text in {CANCEL, '읽기 취소', '아니요'} else None
            if answer is None:
                state.pop('officeReadConsent', None)
                atomic_write_json(path, state)
                return ''
        if not isinstance(answer, str) or answer not in {APPROVE, CANCEL}:
            return ''
        receipt['status'] = 'approved' if answer == APPROVE else 'cancelled'
        receipt.pop('toolUseId', None)
        atomic_write_json(path, state)
        return ('문서 읽기 승인 답변을 확인했습니다. 동일 세션·파일·범위로 office-read를 한 번 실행하세요.'
                if answer == APPROVE else '사용자가 문서 읽기를 취소했습니다. 문서를 열거나 다시 승인 요청하지 마세요.')
