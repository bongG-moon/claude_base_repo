"""인증값을 요청하는 위치를 통일합니다. 실제 키를 인자나 응답에 담지 않습니다."""
from __future__ import annotations

import re
from pathlib import Path
import sys


FIELDS = {'oracle': ['사용자 아이디', '비밀번호', 'DSN 접속 정보'],
          'datalake': ['사번', 'JWT Token', 'S3 Access Key', 'S3 Secret Key'],
          'ehub': ['사번', '개인 토큰']}
PROMPT = '인증정보는 채팅에 보내지 말고, 지금 여는 내 PC 입력창에 직접 입력해 주세요.'


def input_guidance(engine, profile_id=None, *, status='required'):
    if engine == 'demo':
        return {'method': 'not_required', 'status': 'not_required', 'chatInputAllowed': False,
                'retryAutomatically': False, 'nextAction': 'continue_work',
                'message': '가상 연습에는 인증정보가 필요하지 않습니다.'}
    if engine not in FIELDS:
        raise ValueError('지원하는 조회 종류를 선택해 주세요.')
    if profile_id is not None and (not isinstance(profile_id, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', profile_id)):
        raise ValueError('기존 연결의 정확한 식별자를 사용해 주세요.')
    arguments = ['auth', 'setup'] if engine == 'datalake' else ['profiles', 'setup']
    if profile_id is not None:
        arguments.extend(['--profile', profile_id])
    actionable = status in {'required', 'update_required'}
    message = ('인증정보가 필요합니다. 채팅으로 값을 요청하지 말고 현재 스킬의 scripts/query.py 뒤에 setupArgs를 붙여 입력창을 여세요. setupArgs 자체는 실행파일이 아닙니다. 실제로 창을 열기 전에 열었다고 말하지 마세요.'
               if actionable else '인증정보를 저장했습니다. 같은 값을 다시 요청하지 말고 작업을 계속하세요.'
               if status == 'saved' else '입력창을 사용하지 못했거나 입력을 중지했습니다. 채팅으로 인증값을 받거나 입력창을 자동 반복해서 열지 마세요.')
    return {'method': 'local_browser', 'status': status, 'chatInputAllowed': False,
            'retryAutomatically': False, 'profileId': profile_id, 'requiredFields': list(FIELDS[engine]) if actionable else [],
            'setupArgs': arguments if actionable else None,
            'nextAction': 'open_local_input' if actionable else 'continue_work' if status == 'saved' else 'wait_for_user',
            'message': message, 'beforeOpenMessage': PROMPT,
            'explicitEnvImportAllowed': engine == 'datalake'}


def attach_cli_action(result, state_root=None):
    guidance = result.get('credentialInput')
    if not isinstance(guidance, dict) or not guidance.get('setupArgs'):
        return result
    script = Path(__file__).resolve().parents[1] / 'query.py'
    if script.is_file():
        arguments = [sys.executable, '-X', 'utf8', '-B', str(script)]
        if state_root is not None:
            arguments.extend(['--state-root', str(Path(state_root).absolute())])
        guidance['commandArgv'] = arguments + guidance['setupArgs']
    return result


class CredentialSetupRequired(ValueError):
    def __init__(self, engine, profile_id=None):
        self.credential_input = input_guidance(engine, profile_id)
        command = 'auth setup' if engine == 'datalake' else 'profiles setup'
        super().__init__('연결 설정이 없습니다. 인증정보는 채팅에 입력하지 말고 ' + command + '으로 로컬 입력창을 열어 저장해 주세요.')


class CredentialInputUnavailable(ValueError):
    def __init__(self, engine, profile_id=None):
        self.credential_input = input_guidance(engine, profile_id, status='unavailable')
        super().__init__('기본 브라우저로 로컬 인증 입력창을 열지 못했습니다. 브라우저 실행 상태와 회사 정책을 확인해 주세요. 인증정보를 채팅에 보내지 마세요.')


def annotate_auth_error(error, engine, profile_id=None):
    if getattr(error, 'code', None) == 'auth_config':
        error.credential_input = input_guidance(engine, profile_id)
    elif getattr(error, 'code', None) in {'api_401', 'api_403'} or getattr(error, 'details', {}).get('category') == 'authentication':
        error.credential_input = input_guidance(engine, profile_id, status='update_required')
    return error
