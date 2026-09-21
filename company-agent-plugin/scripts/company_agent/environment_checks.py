"""Read-only preparation checks. Never start Office, install packages or connect."""
import importlib.util
import os
import sys


def _module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, OSError):
        return False


def _office(progid):
    if os.name != 'nt':
        return False
    import winreg
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + r'\CLSID', 0, winreg.KEY_READ | view):
                return True
        except OSError:
            pass
    return False


def inspect_environment():
    packages = {name: _module(name) for name in ('win32com', 'pptx')}
    office = {name: _office(progid) for name, progid in (
        ('powerpoint', 'PowerPoint.Application'), ('outlook', 'Outlook.Application'))}
    ready = lambda value: '준비 항목 있음 · 실제 파일 실행은 미확인' if value else '추가 준비 필요'
    return {'readOnly': True, 'python': sys.executable, 'packages': packages, 'officeRegistration': office,
            'features': [
                {'name': 'HTML 보고서', 'status': ready(True), 'requires': '현재 Python'},
                {'name': 'PPT 제작', 'status': ready(packages['pptx'] or office['powerpoint']), 'requires': 'python-pptx 또는 PowerPoint. 배치 유지에는 python-pptx, 미리보기에는 PowerPoint 필요'},
                {'name': 'Outlook 조회', 'status': '계정 연결 확인 필요' if office['outlook'] else '추가 준비 필요', 'requires': '실행 중인 Classic Outlook의 본인 계정 또는 사내 MCP'},
                {'name': 'DB·메일 발송·PST 이동', 'status': '사내 MCP 별도 연결 필요', 'requires': '인증·권한은 해당 서버에서 확인'},
                {'name': 'PDF·이미지 생성', 'status': '별도 지원 도구 확인 필요', 'requires': '기본 제공 기능에 포함되지 않음'}],
            'notice': '패키지와 Office 등록 정보만 확인했습니다. 실제 동작·DRM 허용·로그인·회사 정책 통과를 뜻하지 않습니다. 자동 다운로드·설치는 하지 않습니다.'}
