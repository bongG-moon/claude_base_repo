"""P&T AI SQUARE receive-only client. Python 3.11+, standard library only."""
import argparse
import getpass
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import webbrowser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPCookieProcessor

DEFAULT_CONFIG = Path.home() / '.pt-ai-square' / 'client.json'


class ClientError(Exception):
    pass


class AuthenticationRequired(ClientError):
    pass


def open_auth_page(url, allow_http_origin=None):
    link = base_url(url, allow_http_origin) + '/local-access'
    try:
        opened = webbrowser.open(link)
    except Exception:
        opened = False
    return dict(authUrl=link, browserOpened=bool(opened))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward personal credentials to a login page/other host.
        return None


def base_url(value, allow_http_origin=None):
    if not isinstance(value, str) or any(ord(c) <= 32 for c in value) or '\\' in value:
        raise ClientError('서버 주소 형식을 확인하세요.')
    try:
        p = urlsplit(value)
        p.port
    except ValueError:
        raise ClientError('서버 주소 형식을 확인하세요.') from None
    if not p.hostname or p.username or p.password or p.query or p.fragment or p.scheme not in {'https', 'http'}:
        raise ClientError('인증정보·쿼리 없는 http(s) 서버 주소를 입력하세요.')
    if p.scheme == 'http' and p.hostname not in {'127.0.0.1', 'localhost', '::1'}:
        # Exact configured origin only, never a global "allow HTTP" switch.
        origin = p.scheme + '://' + p.netloc.lower()
        if allow_http_origin != origin:
            raise ClientError('HTTP에서는 KEY가 암호화되지 않습니다. 사내 주소를 확인하고 configure --url 주소 --allow-http로 해당 주소만 허용하세요.')
    return value.rstrip('/')


class Client:
    def __init__(self, url, token='', timeout=30, opener=None, allow_http_origin=None):
        self.url = base_url(url, allow_http_origin)
        self.allow_http_origin = allow_http_origin
        if token and not re.fullmatch(r'ptsq_[A-Za-z0-9_-]{43}', token):
            raise ClientError('인증키 형식을 확인하세요.')
        self.token = token
        self.timeout = timeout
        self.opener = opener or build_opener(NoRedirect(), HTTPCookieProcessor())

    def open(self, path, data=None, extra_headers=None):
        if not path.startswith('/') or path.startswith('//') or '\\' in path:
            raise ClientError('서버 응답에 잘못된 API 경로가 포함되어 있습니다.')
        headers = {'Accept': 'application/json, application/octet-stream', 'User-Agent': 'PTAISquare-Receiver/1'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        headers.update(extra_headers or {})
        try:
            return self.opener.open(Request(self.url + path, data=data, headers=headers), timeout=self.timeout)
        except HTTPError as e:
            messages = {401:'연결 KEY가 없거나 재발급·취소·기존 만료일로 사용할 수 없습니다. 웹 상단 KEY 아이콘에서 상태를 확인하세요.',
                        403:'키의 허용 작업과 도구 조회·관리 권한을 확인하세요.',
                        404:'도구 또는 배포 파일을 찾을 수 없습니다.',
                        409:'현재 상태에서는 받을 수 없습니다. 더미 모드인지 확인하세요.',
                        503:'서버 또는 데이터베이스를 확인할 수 없습니다.'}
            error_type = AuthenticationRequired if e.code == 401 else ClientError
            raise error_type(messages.get(e.code, f'서버 요청 실패 (HTTP {e.code}).')) from None
        except (URLError, TimeoutError, OSError):
            raise ClientError('서버에 연결하지 못했습니다. 주소·네트워크·인증서를 확인하세요.') from None

    def get(self, path):
        with self.open(path) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ClientError('서버 응답이 너무 큽니다.')
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ClientError('서버가 JSON 대신 다른 응답을 반환했습니다. 주소와 인증을 확인하세요.') from None
        if not isinstance(data, dict):
            raise ClientError('서버 응답 형식이 올바르지 않습니다.')
        return data

    def search(self, query='', kind='', offset=0, limit=20, org_id=''):
        return self.get('/api/catalog?' + urlencode(dict(q=query, type=kind, offset=offset, limit=limit, orgId=org_id)))

    def details(self, tool_id):
        return self.get(f'/api/tools/{positive(tool_id)}')

    def check(self, tool_id, release):
        return self.get(f'/api/tools/{positive(tool_id)}/version-check?release={positive(release)}')

    def download(self, tool_id, output, update=False):
        tool_id = positive(tool_id)
        manifest = self.get(f'/api/tools/{tool_id}/manifest')
        if manifest.get('toolId') != tool_id:
            raise ClientError('배포 정보의 도구 ID가 다릅니다.')
        release = positive(manifest.get('release'))
        if not manifest.get('downloadUrl'):
            return dict(downloaded=False, toolId=tool_id, release=release,
                        reason='파일형 도구가 아닙니다. show 명령으로 연결·설치 안내를 확인하세요.',
                        installed=False)
        path = f'/download/{tool_id}/{release}'
        if manifest['downloadUrl'] != path:
            raise ClientError('배포 파일 경로가 올바르지 않습니다.')
        sha = manifest.get('sha256')
        size = manifest.get('bytes')
        if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha) or type(size) is not int or size < 0:
            raise ClientError('파일 검증 정보가 올바르지 않습니다.')
        # Never use an untrusted filename as a filesystem path (including ADS).
        original = manifest.get('filename', '')
        suffix = Path(original).suffix.lower() if isinstance(original, str) else ''
        if suffix not in {'.zip', '.axextension', '.exe', '.msi', '.ps1', '.md'}:
            suffix = '.bin'
        folder = Path(output).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f'tool-{tool_id}-v{release}{suffix}'
        if destination.exists() or destination.is_symlink():
            raise ClientError(f'같은 파일이 이미 있습니다. 다른 저장 폴더를 선택하세요: {destination.name}')
        temp = None
        try:
            with tempfile.NamedTemporaryFile(prefix='.square-', suffix='.part', dir=folder, delete=False) as f:
                temp = Path(f.name)
                digest = hashlib.sha256()
                received = 0
                with self.open(path + ('?purpose=update' if update else '')) as response:
                    while chunk := response.read(1024 * 1024):
                        received += len(chunk)
                        if received > size:
                            raise ClientError('서버 파일이 배포 정보보다 큽니다. 저장하지 않았습니다.')
                        digest.update(chunk)
                        f.write(chunk)
                if received != size or digest.hexdigest() != sha:
                    raise ClientError('파일 크기 또는 SHA-256이 다릅니다. 불완전한 파일을 삭제했습니다.')
                f.flush()
                os.fsync(f.fileno())
            # Recheck permissions and active release after streaming. No blind retry.
            current = self.get(f'/api/tools/{tool_id}/manifest')
            if (current.get('release'), current.get('sha256')) != (release, sha):
                raise ClientError('다운로드 중 배포 버전이 변경되었습니다. 다시 확인 후 받아주세요.')
            # Windows rename refuses replacement; POSIX link provides that contract.
            if os.name == 'nt':
                os.rename(temp, destination)
            else:
                os.link(temp, destination)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
        return dict(downloaded=True, toolId=tool_id, release=release, file=str(destination),
                    originalFilename=original, sha256=sha, bytes=size, installed=False,
                    notice='파일 수신과 원본 일치 여부만 확인했습니다. 코드 안전성·실행 검증은 아닙니다.')


def positive(value):
    if type(value) is not int or not 1 <= value <= 999999999:
        raise ClientError('도구 ID와 배포 번호는 양의 정수여야 합니다.')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description='P&T AI SQUARE 검색·조회·다운로드 (업로드·설치·실행 없음)')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG, help='주소 설정 JSON 경로')
    parser.add_argument('--authenticate', action='store_true', help='인증키를 화면에 표시하지 않고 직접 입력')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('auth', help='인증키 발급·관리 화면 열기')
    configure = sub.add_parser('configure', help='서버 주소 설정 (인증키 저장 안 함)')
    configure.add_argument('--url', required=True)
    configure.add_argument('--allow-http', action='store_true', help='이 사내 HTTP 주소에 KEY가 암호화 없이 전송됨을 확인하고 허용')
    search = sub.add_parser('search', help='도구 검색')
    search.add_argument('query', nargs='?', default='')
    search.add_argument('--type', default='', choices=['', 'MCP/Tool', 'Skill', '플러그인/하네스'])
    search.add_argument('--org-id', default='')
    search.add_argument('--offset', type=int, default=0)
    search.add_argument('--limit', type=int, default=20)
    for name in ['show', 'download', 'check']:
        cmd = sub.add_parser(name)
        cmd.add_argument('tool_id', type=int)
        if name == 'download':
            cmd.add_argument('--output', type=Path, default=Path.cwd() / 'downloads')
            cmd.add_argument('--update', action='store_true', help='업데이트 수신: 다운로드 집계에서 제외')
        if name == 'check':
            cmd.add_argument('--release', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'configure':
            parsed = urlsplit(args.url)
            allowed = 'http://' + parsed.netloc.lower() if args.allow_http and parsed.scheme == 'http' else None
            value = base_url(args.url, allowed)
            args.config.parent.mkdir(parents=True, exist_ok=True)
            args.config.write_text(json.dumps(dict(baseUrl=value, allowHttpOrigin=allowed), ensure_ascii=False, indent=2), encoding='utf-8')
            result = dict(config=str(args.config.resolve()), baseUrl=value, httpWarning='KEY가 암호화 없이 이 주소로 전송됩니다.' if allowed else None)
        else:
            if not args.config.exists():
                raise ClientError('먼저 configure --url 서버주소 명령으로 주소를 설정하세요.')
            config = json.loads(args.config.read_text(encoding='utf-8-sig'))
            if not isinstance(config, dict) or not isinstance(config.get('baseUrl'), str):
                raise ClientError('설정 파일의 baseUrl을 확인하세요.')
            allowed = config.get('allowHttpOrigin')
            url = base_url(config['baseUrl'], allowed)
            if args.command == 'auth':
                print(json.dumps(open_auth_page(url, allowed), ensure_ascii=False))
                return 0
            token = os.environ.get('PTAI_API_TOKEN', os.environ.get('PTAI_READ_TOKEN', '')).strip()
            if args.authenticate or (not token and urlsplit(url).hostname not in {'127.0.0.1', 'localhost', '::1'}):
                auth_info = open_auth_page(url, allowed) if not token else {}
                if not sys.stdin.isatty():
                    raise ClientError('인증키 발급 화면: '+auth_info.get('authUrl', url+'/local-access')+' · 사용자 터미널에서 입력하거나 PTAI_API_TOKEN을 설정하세요. 대화창에 보내지 마세요.')
                token = getpass.getpass('다운로드 인증키 (화면에 표시되지 않음): ').strip()
            client = Client(url, token, allow_http_origin=allowed)
            if args.command == 'search':
                result = client.search(args.query, args.type, args.offset, args.limit, args.org_id)
            elif args.command == 'show':
                result = client.details(args.tool_id)
            elif args.command == 'check':
                result = client.check(args.tool_id, args.release)
            else:
                result = client.download(args.tool_id, args.output, update=args.update)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except AuthenticationRequired as error:
        print(json.dumps(dict(error=str(error), **open_auth_page(url, allowed)), ensure_ascii=False), file=sys.stderr)
        return 1
    except (ClientError, OSError, ValueError, EOFError, HTTPException):
        # Do not dump URLs with credentials, response bodies, environment, or tracebacks.
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, ClientError) else '설정 읽기·파일 저장·네트워크 수신에 실패했습니다. 설정과 저장 경로를 확인하세요.'
        print(json.dumps(dict(error=message), ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
