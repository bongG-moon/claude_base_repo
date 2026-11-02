"""연결 설정을 로컬 브라우저에서 입력하고 저장하면 돌아옵니다."""
from __future__ import annotations


def show(store, engine, profile_id=None):
    if engine == 'demo':
        raise ValueError('실습에는 인증정보가 필요하지 않습니다. demo-init으로 시작해 주세요.')
    from .manager_ui import show as manager
    return manager(store, engine, profile_id, start_view='connection')
