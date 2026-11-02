"""Optional startup check. Does not install, download artifacts, or modify files.

Pass a personal connection key explicitly, or supply an authenticated HTTP opener.
Browser login is NOT automatically inherited by a Python process.
"""
import json
import re
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # The API has a fixed address. Never forward a key to a redirect target.
        return None


def check_version(base_url, tool_id, installed_release, *, token='', opener=None, timeout=2.0, allow_http_origin=None):
    """Return a notice for the host UI; never write to stdout or persist a key.

    A key uses the built-in non-redirecting transport. A custom opener is supported
    for existing authenticated clients, but cannot be combined with token.
    """
    parsed=urlsplit(base_url)
    if (parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or '\\' in base_url or any(ord(c)<=32 for c in base_url)
            or (parsed.scheme=='http' and parsed.hostname not in {'localhost','127.0.0.1','::1'}
                and allow_http_origin != 'http://' + parsed.netloc.lower())):
        raise ValueError('Use HTTPS or an explicitly acknowledged exact HTTP origin, without credentials/query/fragment.')
    if any(type(n) is not int or not 0<n<1000000000 for n in [tool_id,installed_release]):
        raise ValueError('tool_id and installed_release must be positive release identifiers.')
    if not 0<timeout<=10:raise ValueError('Use a bounded timeout of 0–10 seconds.')
    if not isinstance(token,str) or (token and not re.fullmatch(r'ptsq_[A-Za-z0-9_-]{43}',token)):
        raise ValueError('Use a valid personal connection key.')
    if token and opener is not None:
        raise ValueError('Use either a connection key or an authenticated opener, not both.')
    url=f'{base_url.rstrip("/")}/api/tools/{tool_id}/version-check?release={installed_release}'
    headers={'Accept':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    try:
        with (opener or build_opener(_NoRedirect())).open(Request(url,headers=headers),timeout=timeout) as response:
            raw=response.read(65537)
        if len(raw)>65536:raise ValueError('Oversized response')
        data=json.loads(raw)
        if (not isinstance(data,dict) or data.get('schemaVersion')!=1
                or data.get('toolId')!=tool_id or data.get('installedRelease')!=installed_release
                or data.get('status') not in {'current','update_available','rollback_available','unknown_release'}
                or type(data.get('activeRelease')) is not int or data['activeRelease']<1
                or not isinstance(data.get('message'),str) or data.get('checkOnly') is not True):
            raise ValueError('Invalid version response')
        return data
    except HTTPError as error:
        status={401:'authentication_required',403:'permission_required',404:'not_found'}.get(error.code,'unavailable')
        messages={'authentication_required':'버전 확인 인증이 필요합니다. 연결 KEY가 취소·재발급되었는지 확인하고 새 KEY 또는 정상 인증 클라이언트를 연결해 주세요.',
                  'permission_required':'이 도구의 조회 권한이 필요합니다.',
                  'not_found':'공유 목록에서 도구를 찾을 수 없습니다.',
                  'unavailable':'서버에서 버전을 확인하지 못했습니다. 최신 버전 여부는 알 수 없습니다.'}
        return dict(status=status,message=messages[status],checkOnly=True)
    except (URLError,OSError,ValueError,HTTPException):
        return dict(status='unavailable',message='지금은 버전을 확인할 수 없습니다. 최신 버전 여부는 알 수 없습니다.',checkOnly=True)
