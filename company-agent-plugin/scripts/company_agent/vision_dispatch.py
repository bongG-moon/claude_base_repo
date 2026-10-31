"""Installed-scope model selection and one-shot, evidence-bound vision backup.

Only vision calls enter this module. No discovery, provider requests, credentials
or source images are read. Native Agent and tool permissions remain authoritative.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from . import vision_routing as routing
from .paths import atomic_write_json

MANAGED = re.compile(r'company-harness-vision-[a-f0-9]{8}')
BACKUP = re.compile(r'^\[company-vision-backup:([a-f0-9]{32})\]\n')


def _agent(name):
    return name == routing.VISION_AGENT or isinstance(name, str) and bool(MANAGED.fullmatch(name))


def relevant(payload):
    inputs = routing._inputs(payload)
    return bool(routing._image_read(payload) or payload.get('tool_name') in routing.CAPTURE_TOOLS
                or payload.get('agent_id') and _agent(payload.get('agent_type'))
                or payload.get('tool_name') in {'Agent', 'Task'} and _agent(inputs.get('subagent_type')))


def _snapshot_path(root, session):
    return root / 'tmp' / 'vision-model-connections' / (hashlib.sha256(session.encode()).hexdigest() + '.json')


def session_start(root, payload):
    # Native agents are cached for a live CLI connection (including subsequent
    # stream-json turns). Only an actual startup/resume establishes a revision.
    # No recurring UserPromptSubmit read, model probe, or ordinary Read lookup.
    session = payload.get('session_id')
    if payload.get('source') != 'startup' or not isinstance(session, str) or not session:
        return
    from .vision_settings import read_settings
    try:
        settings = read_settings(root)
        path = _snapshot_path(root, session)
        if settings and _safe_path(path):
            atomic_write_json(path, {'modelUpdatedAt': settings['modelUpdatedAt']})
    except (OSError, ValueError):
        pass  # A corrupt optional setting does not block ordinary work.


def connection_current(root, payload, config):
    session = payload.get('session_id')
    if not isinstance(session, str) or not session:
        return False
    path = _snapshot_path(root, session)
    try:
        if not _safe_path(path) or path.stat().st_size > 1024:
            return False
        data = json.loads(path.read_text(encoding='utf-8'))
        return isinstance(data, dict) and data.get('modelUpdatedAt') == config.get('modelUpdatedAt')
    except (OSError, ValueError):
        return False


def _normal(payload):
    normalized = {**payload}
    if _agent(payload.get('agent_type')):
        normalized['agent_type'] = routing.VISION_AGENT
    if payload.get('tool_name') in {'Agent', 'Task'} and _agent(routing._inputs(payload).get('subagent_type')):
        normalized['tool_input'] = {**routing._inputs(payload), 'subagent_type': routing.VISION_AGENT}
    return normalized


def setup_reason(root, plugin, payload):
    from .native_runtime import cli_command
    command = cli_command(plugin) + ' vision configure --state-root ' + json.dumps(root.as_posix(), ensure_ascii=False)
    return ('[이미지 모델 선택] 아직 이미지를 읽지 않았습니다. 처음 한 번만 사용자에게 한국어로 '
            '“이미지 확인에 사용할 실제 모델 ID를 입력하거나 HCP-Vision-Latest를 선택해 주세요. '
            '이 PC에 저장하며 모델 호출 장애 때만 HCP-Vision-Latest로 한 번 재시도합니다.”라고 물으세요. '
            '답을 받은 뒤 다음 명령에 --model "사용자가 고른 실제 ID"를 붙여 실행하세요: ' + command
            + ' 취소하면 실행하지 마세요. 표시 이름·모델 ID 추측, 모델 목록·인증·세션 탐색은 하지 마세요. '
            '이후 /company-agent:vision-model로 변경할 수 있습니다. 일반 모델·권한은 유지합니다.')


def _key(payload):
    session, cwd = payload.get('session_id'), payload.get('cwd')
    if not isinstance(session, str) or not session or not isinstance(cwd, str) or not cwd:
        return None
    return hashlib.sha256((session + '\0' + cwd.casefold()).encode()).hexdigest()


def _receipt(root, payload):
    key = _key(payload)
    if not key:
        return None
    prompt = routing._inputs(payload).get('prompt', '')
    match = BACKUP.match(prompt) if isinstance(prompt, str) else None
    token = match[1] if match else _failure_token(payload)
    return root / 'tmp' / 'vision-backup' / (key + '-' + token + '.json') if token else None


def _failure_token(payload):
    key = _key(payload)
    identifier = payload.get('tool_use_id')
    return hashlib.sha256((key + '\0' + str(identifier)).encode()).hexdigest()[:32] if key and identifier else None


def _safe_path(path):
    if path is None:
        return False
    from .vision_settings import _safe_path as checked_path
    try:
        checked_path(path)
        return True
    except (OSError, ValueError):
        return False


def _read_receipt(path):
    if not _safe_path(path):
        return {}
    try:
        if path.stat().st_size > 4096:
            return {}
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) and 0 <= time.time() - data.get('time', 0) < 300 else {}
    except (OSError, ValueError, TypeError):
        return {}


def _digest(prompt):
    return hashlib.sha256(prompt.encode('utf-8')).hexdigest()


def _consume(root, payload, config):
    inputs = routing._inputs(payload)
    prompt = inputs.get('prompt', '')
    match = BACKUP.match(prompt) if isinstance(prompt, str) else None
    if not match:
        return False
    path = _receipt(root, payload)
    data = _read_receipt(path)
    if (data.get('token') != match[1] or data.get('used') or data.get('model') != config.get('model')
            or data.get('digest') != _digest(prompt[match.end():])):
        return False
    claim = path.parent / (match[1] + '.used')
    if not _safe_path(claim):
        return False
    try:
        descriptor = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
    except OSError:
        return False
    atomic_write_json(path, {**data, 'used': True})
    return True


def preflight(root, plugin, payload):
    normalized = _normal(payload)
    # A running vision child never reconfigures models, recursively delegates,
    # or asks setup questions. Its native permissions still apply.
    if payload.get('agent_id'):
        return routing.preflight(normalized, active=True)
    from .vision_settings import status
    try:
        config = status(root)
    except (ValueError, OSError):
        return routing._deny('[이미지 모델 설정 확인] 저장된 전용 작업자와 설정이 일치하지 않습니다. '
                             '/company-agent:vision-model로 확인해 주세요. 기존 파일을 덮어쓰거나 임의 모델을 실행하지 마세요.')
    if not config.get('model'):
        return routing._deny(setup_reason(root, plugin, payload))
    profile = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')
    expected = profile / 'agents' / (config['agent'] + '.md')
    if os.path.normcase(str(expected.absolute())) != os.path.normcase(str(Path(config['agentPath']).absolute())):
        return routing._deny('[이미지 모델 프로필 확인] 선택한 모델은 다른 Claude 설정 위치에 저장되어 있습니다. '
                             '그 설정을 사용하는 Claude에서 새 대화를 열어 주세요. 다른 위치에 복제하거나 현재 설정을 바꾸지 않았습니다.')
    if not connection_current(root, payload, config):
        return routing._deny('[이미지 모델 연결 갱신] 모델 선택값은 저장되어 있습니다. '
                             'Claude를 다시 열어 새 연결에서 이어서 요청해 주세요. 앱에서는 현재 작업을 마친 뒤 새 대화를 여세요. '
                             '같은 연결에서 재시도·기존 모델 대체·설정 탐색은 하지 마세요. 일반 작업은 계속할 수 있습니다.')
    if os.environ.get('CLAUDE_CODE_SUBAGENT_MODEL_FORCE') == '1':
        return routing._deny('[이미지 모델 선택 제한] 이 실행 환경은 작업자 모델을 강제로 지정합니다. '
                             '선택한 이미지 모델 사용을 보장할 수 없어 실행하지 않았습니다. 담당자에게 확인해 주세요. 강제 설정은 변경하지 않습니다.')
    inputs = routing._inputs(payload)
    if payload.get('tool_name') in {'Agent', 'Task'}:
        prompt = inputs.get('prompt', '')
        backup = isinstance(prompt, str) and bool(BACKUP.match(prompt))
        if backup and not _consume(root, payload, config):
            return routing._deny('[비전 재시도 종료] 백업은 확인된 모델 호출 장애에 한 번만 사용합니다. '
                                 '추가 호출하지 말고 미확인 범위와 실패 사유를 알려 주세요.')
        result = routing.preflight(normalized, active=True)
        updated = result.get('hookSpecificOutput', {}).get('updatedInput') if result else None
        if updated is not None:
            updated['subagent_type'] = routing.VISION_AGENT if backup else config['agent']
            # Backup is bounded and synchronous; never resume a different worker.
            updated['run_in_background'] = False
        return result
    result = routing.preflight(normalized, active=True)
    if routing._image_read(payload) and result:
        from .vision_handoff import remember
        marker = remember(root, payload)
        result['hookSpecificOutput']['permissionDecisionReason'] = routing.handoff_reason(payload, marker)
    return result


def model_invocation_failure(payload, expected_model=None):
    """Only a host tool-failure envelope, never the worker's prose, qualifies."""
    error = payload.get('error')
    if not isinstance(error, str) or len(error) > 16000 or payload.get('is_interrupt'):
        return False
    # Parse the native CLI envelope, not arbitrary provider/model prose. The
    # reported model must be the requested one, not an organization override.
    match = re.search(r'Agent terminated early due to an API error:.*?'
                      r'\(error type ([a-z_]+), HTTP (\d{3}), request id [^,\r\n]{1,200}, '
                      r'model sent to the API: ([A-Za-z0-9._:/@+\[\]-]{1,160})\)', error, re.S)
    if not match or expected_model is not None and match[3] != expected_model:
        return False
    return (match[1], match[2]) in {('model_not_found', '404'), ('model_unavailable', '503'),
                                   ('overloaded_error', '529'), ('service_unavailable', '503')}


def result_context(root, payload, event):
    normalized = _normal(payload)
    if payload.get('agent_id'):
        return routing.result_context(event, normalized, active=True)
    inputs = routing._inputs(payload)
    error = payload.get('error')
    # Native agent resolution failed BEFORE any model request. It is not an
    # unavailable VLM/API and must not trigger HCP backup or agent creation.
    if (event == 'PostToolUseFailure' and payload.get('tool_name') in {'Agent', 'Task'}
            and _agent(inputs.get('subagent_type')) and isinstance(error, str)
            and len(error) <= 16000
            and error.startswith("Agent type '" + inputs['subagent_type'] + "' not found.")):
        return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext':
                '현재 Claude 연결에 이미지 작업자가 없어 모델 호출 전에 종료됐습니다. 이미지·모델 장애로 판단하지 마세요. '
                '같은 Agent 재시도·백업 모델 호출·설정 탐색·자동 재활성화는 하지 마세요. '
                '플러그인을 끈 경우 이전 대화의 인계 지시를 재사용하지 말고 현재 제공되는 기능만 사용하세요. '
                '켜서 사용하려는 경우 설정 적용 후 새 연결이 필요합니다. 재연결은 이전 대화 내용을 지우지 않습니다.'}}
    result = routing.result_context(event, normalized, active=True)
    if result is None or event != 'PostToolUseFailure' or not model_invocation_failure(payload):
        return result
    from .vision_settings import status
    try:
        config = status(root)
    except (OSError, ValueError):
        return result
    if (not model_invocation_failure(payload, config.get('model'))
            or not connection_current(root, payload, config)
            or os.environ.get('CLAUDE_CODE_SUBAGENT_MODEL_FORCE') == '1'):
        return result
    inputs = routing._inputs(payload)
    prompt = inputs.get('prompt')
    # A backup failure, same-model failure or incomplete host context stops here.
    if (config.get('model') == routing.VISION_MODEL or inputs.get('subagent_type') != config.get('agent')
            or not isinstance(prompt, str) or not prompt or len(prompt) > 8000 or BACKUP.search(prompt)
            or not payload.get('tool_use_id')):
        return result
    path = _receipt(root, payload)
    if not _safe_path(path):
        return result
    failure_id = hashlib.sha256(str(payload['tool_use_id']).encode()).hexdigest()
    old = _read_receipt(path)
    if old.get('failure') == failure_id:
        return result
    token = _failure_token(payload)
    atomic_write_json(path, {'time': time.time(), 'failure': failure_id, 'model': config['model'],
                            'digest': _digest(prompt), 'token': token, 'used': False})
    retry = {'subagent_type': routing.VISION_AGENT, 'description': '이미지 모델 백업 한 번',
             'prompt': '[company-vision-backup:' + token + ']\n' + prompt, 'run_in_background': False}
    return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext':
            '선택한 모델 호출 장애를 확인했습니다. HCP-Vision-Latest 백업으로 다음 Agent를 한 번만 호출하세요: '
            + json.dumps(retry, ensure_ascii=False) + ' 실패하면 중단합니다. 저장한 선택값·메인 모델·권한은 변경하지 마세요.'}}
