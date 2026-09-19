"""Opt-in Cua readiness inspection, not a driver, installer or authorization.

Never launches a process, connects to MCP, captures a screen or reads credentials.
Only bounded local file paths are inspected; live connection evidence belongs to the
existing Claude bridge. File presence is NOT version, origin or execution proof.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re

SERVERS = ('cua-driver', 'cua-computer-use', 'cua')
READ_TOOLS = frozenset({'list_apps', 'get_window_state'})
WRITE_TOOLS = frozenset({'click', 'type_text'})
NAME = re.compile(r'[A-Za-z0-9_-]{1,80}\Z')


def driver_file(value):
    """Inspect one absolute local binary path. Never execute even a found file."""
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        return None
    value = value.strip().strip('"')
    # Avoid touching network shares, device namespaces or drive-relative paths.
    if value.startswith(('\\\\', '//')):
        return None
    path = Path(value)
    if not path.is_absolute() or path.name.casefold() not in {'cua-driver.exe', 'cua-driver'}:
        return None
    try:
        if os.name == 'nt':
            import ctypes
            # Skip mapped network drives too; avoid network metadata probes.
            if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) != 3:
                return None
        for part in (*reversed(path.parents), path):
            if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & 0x400):
                return None
        if not path.is_file():
            return None
        return str(path)
    except OSError:
        return None


def find_driver(value=None):
    if value:
        found = driver_file(value)
        return {'status': 'found' if found else 'not-found', 'path': found, 'basis': 'explicit-path'}
    # No recursive search, current-directory lookup, registry or home scan.
    for entry in os.environ.get('PATH', '').split(os.pathsep)[:64]:
        entry = entry.strip().strip('"')
        if not entry or not Path(entry).is_absolute() or entry.startswith(('\\\\', '//')):
            continue
        found = driver_file(str(Path(entry) / ('cua-driver.exe' if os.name == 'nt' else 'cua-driver')))
        if found:
            return {'status': 'found', 'path': found, 'basis': 'inherited-path'}
    return {'status': 'not-found', 'path': None, 'basis': 'inherited-path-limited'}


def readiness(connection=None, *, live=False, demo=False, driver_path=None, server_name=None):
    if server_name is not None and (not isinstance(server_name, str) or not NAME.fullmatch(server_name)):
        raise ValueError('MCP 이름은 현재 연결에 표시된 영문·숫자·밑줄·하이픈 이름으로 입력하세요.')
    result = {'schemaVersion': 1, 'status': 'unverified', 'demo': demo,
        'driver': {'status': 'not-checked'}, 'connection': {'status': 'not-observed'},
        'tools': [], 'canPrepareReadTrial': False, 'canPrepareInputTrial': False,
        'limits': ['준비 확인은 실제 조작 성공·모델 이미지 지원·회사 승인·Driver 버전 검증이 아닙니다.',
                   '자동 설치·MCP 등록·화면 캡처·클릭·설정 변경·모델 호출을 하지 않습니다.',
                   '로컬 실행과 모델로 전달되는 화면/도구 결과의 처리 범위는 다릅니다.'],
        'next': '관리자가 승인한 Driver와 MCP 연결이 필요합니다. 미설치를 오류로 보거나 자동 설치하지 않습니다.'}
    if demo:
        result['next'] = '화면 체험 모드에서는 실제 PC나 MCP 준비 상태를 조사하지 않습니다.'
        return result
    result['driver'] = find_driver(driver_path)
    if not live or not isinstance(connection, dict):
        result['next'] = '현재 실행 중인 CLI의 연결 보고가 없습니다. 과거 기록을 현재 연결로 취급하지 않습니다. 확인만 위해 AI 요청을 자동 전송하지 않습니다.'
        return result
    servers = connection.get('mcp')
    if not isinstance(servers, list):
        result['next'] = 'CLI가 MCP 목록을 제공하지 않았습니다. 미제공은 미설치와 다릅니다.'
        return result
    candidates = [s for s in servers[:128] if isinstance(s, dict) and isinstance(s.get('name'), str)
                  and NAME.fullmatch(s['name']) and s['name'] in ((server_name,) if server_name else SERVERS)]
    if not candidates:
        result['connection']['status'] = 'not-listed'
        result['next'] = '현재 CLI 보고 목록에 Cua 이름의 연결이 없습니다. 사용자 지정 이름이면 그 이름을 입력하고 다시 확인하세요. 설정 변경 후에는 새 CLI 연결이 필요합니다.'
        return result
    if len(candidates) != 1:
        result['connection'] = {'status': 'choose', 'names': sorted({s['name'] for s in candidates})}
        result['next'] = 'Cua 후보가 여러 개입니다. 사용할 MCP 이름 하나를 입력하세요. 임의로 선택하지 않습니다.'
        return result
    server = candidates[0]
    result['connection'] = {'status': 'connected' if server.get('status') == 'connected' else 'not-connected',
                            'name': server['name'], 'basis': 'current-cli-init'}
    if server.get('status') != 'connected':
        result['next'] = 'CLI가 해당 MCP를 연결됨으로 보고하지 않았습니다. 원래 CLI에서 연결 상태를 확인하세요.'
        return result
    raw = connection.get('tools')
    prefix = 'mcp__' + server['name'] + '__'
    names = [t.get('name') if isinstance(t, dict) else t for t in raw[:1024]] if isinstance(raw, list) else []
    tools = {t[len(prefix):] for t in names if isinstance(t, str) and t.startswith(prefix) and NAME.fullmatch(t[len(prefix):])}
    result['tools'] = sorted(tools)
    result['canPrepareReadTrial'] = READ_TOOLS.issubset(tools)
    result['canPrepareInputTrial'] = (READ_TOOLS | WRITE_TOOLS).issubset(tools)
    result['status'] = 'tools-observed' if result['canPrepareReadTrial'] else 'tools-unconfirmed'
    result['next'] = ('읽기 시험 예문을 준비할 수 있습니다. 연결 이름만으로 정품·로컬 실행 여부를 보증하지 않으며 회사 승인 후 보내세요.'
                      if result['canPrepareReadTrial'] else '필요한 읽기 도구가 CLI 보고에 없습니다. 지연 노출·버전 차이일 수 있으므로 없다고 단정하거나 임의 도구명을 실행하지 않습니다.')
    return result


def main():
    parser = argparse.ArgumentParser(description='Cua 파일 후보만 확인합니다. 실행·설치·화면 조작은 하지 않습니다.')
    parser.add_argument('--driver', help='승인된 cua-driver.exe의 절대 경로 (선택)')
    args = parser.parse_args()
    print(json.dumps(readiness(driver_path=args.driver), ensure_ascii=True))


if __name__ == '__main__':
    main()
