"""연결 설정을 로컬 브라우저에서 입력하고 저장하면 돌아옵니다."""
from __future__ import annotations


def show(store, engine, profile_id=None):
    if engine == 'demo':
        raise ValueError('실습에는 인증정보가 필요하지 않습니다. demo-init으로 시작해 주세요.')
    from .manager_ui import show as manager
    from .credentials import input_guidance
    result = manager(store, engine, profile_id, start_view='connection')
    status = 'saved' if result.get('status') == 'saved' else 'expired' if result.get('status') == 'expired' else 'cancelled'
    selected = result.get('profile', {}).get('id') or profile_id
    response = dict(result, credentialInput=input_guidance(engine, selected, status=status))
    if status in {'cancelled', 'expired'}:
        response['message'] = ('입력 시간이 지나 창을 닫았습니다.' if status == 'expired' else '인증정보 입력을 중지했습니다.') + ' 새 인증값은 저장하지 않았습니다. 채팅에 입력하지 않아도 되며, 창을 자동으로 다시 열지 않습니다.'
    return response
