"""Bounded GET/JSON page-number query; no credential, URL or records in logs."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
SENSITIVE = re.compile(r'(?:token|secret|password|passwd|api[_-]?key|authorization|session|cookie|credential|csrf|signature)', re.I)
ENV_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
PAGE_TOKEN_NAME = re.compile(r'^(?:page|next)[_-]?token$', re.I)
SECRET_FIELDS = frozenset({
    'password', 'passwd', 'pwd', 'secret', 'clientsecret', 'secretkey', 'privatekey',
    's3secretkey', 's3secretaccesskey', 'secretaccesskey', 's3accesskey', 'awsaccesskeyid',
    'apikey', 'xapikey', 'auth', 'authkey', 'authentication', 'authorization',
    'proxyauthorization', 'bearer', 'bearertoken', 'cookie',
    'setcookie', 'session', 'sessionid', 'sessiontoken', 'phpsessid', 'jsessionid',
    'token', 'accesstoken', 'refreshtoken', 'idtoken', 'jwttoken', 'jwt',
    'csrf', 'csrftoken', 'xsrf', 'xsrftoken', 'xcsrftoken', 'xauthtoken',
    'pagetoken', 'nexttoken', 'cursor', 'nextcursor',
})


def redact_records(records):
    """Hide identifiable credential fields recursively, preserving other data."""
    count = 0
    def visit(value):
        nonlocal count
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                normalized = re.sub(r'[^a-z0-9]', '', str(key).lower())
                if normalized in SECRET_FIELDS:
                    result[key] = '[민감정보 숨김]'
                    count += 1
                else:
                    result[key] = visit(item)
            return result
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value
    return visit(records), count


class Stop(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def params_from_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.fragment:
        raise Stop('invalid_url', 'HTTP(S) 주소만 사용하고 URL에 인증 정보나 조각 식별자를 넣지 마세요.')
    try:
        p.port  # validate malformed port
    except ValueError:
        raise Stop('invalid_url', '포트가 올바르지 않습니다.') from None
    params = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
    if any(SENSITIVE.search(k) for k, _ in params):
        raise Stop('sensitive_parameter', '주소에 인증 관련 값을 넣지 마세요.')
    return p._replace(query='').geturl(), params


def main(argv=None):
    ap = argparse.ArgumentParser(description='허용된 GET JSON 자료를 제한된 페이지로 조회합니다.')
    ap.add_argument('--url', required=True)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--items-path', default='data', help='JSON 배열 위치. 최상위 배열은 .')
    ap.add_argument('--page-param', default='page')
    ap.add_argument('--page-size-param', default='limit')
    ap.add_argument('--cursor-param', help='커서 페이징의 쿼리 파라미터 이름')
    ap.add_argument('--next-cursor-path', help='다음 커서가 있는 JSON 필드 경로')
    ap.add_argument('--start-page', type=int, default=1)
    ap.add_argument('--page-size', type=int, default=100)
    ap.add_argument('--max-pages', type=int, default=5)
    ap.add_argument('--max-rows', type=int, default=500)
    ap.add_argument('--timeout', type=int, default=30)
    ap.add_argument('--param', action='append', default=[])
    ap.add_argument('--bearer-env')
    ap.add_argument('--preview', type=int, default=0)
    args = ap.parse_args(argv)
    try:
        if not (1 <= args.page_size <= 1000 and 1 <= args.max_pages <= 100 and 1 <= args.max_rows <= 10000 and 1 <= args.timeout <= 120 and 0 <= args.preview <= 5 and args.start_page >= 0):
            raise Stop('invalid_limit', '페이지, 건수 또는 대기 시간 범위를 확인해 주세요.')
        cursor_mode = bool(args.cursor_param or args.next_cursor_path)
        if cursor_mode and not (args.cursor_param and args.next_cursor_path):
            raise Stop('invalid_parameter', '커서 파라미터 이름과 다음 커서 위치를 함께 지정하세요.')
        active_page_param = args.cursor_param if cursor_mode else args.page_param
        if not active_page_param or not args.page_size_param or active_page_param == args.page_size_param:
            raise Stop('invalid_parameter', '페이지와 페이지 크기의 서로 다른 파라미터 이름이 필요합니다.')
        if (SENSITIVE.search(active_page_param) and not (cursor_mode and PAGE_TOKEN_NAME.fullmatch(active_page_param))) or SENSITIVE.search(args.page_size_param):
            raise Stop('sensitive_parameter', '인증 관련 이름을 페이지 파라미터로 사용할 수 없습니다.')
        base, params = params_from_url(args.url)
        for item in args.param:
            key, sep, value = item.partition('=')
            if not sep or not key or SENSITIVE.search(key):
                raise Stop('invalid_parameter', '일반 필터는 이름=값 형식으로 지정하고 인증 값은 넣지 마세요.')
            params.append((key, value))
        if any(k in {active_page_param, args.page_size_param} for k, _ in params):
            raise Stop('invalid_parameter', '페이지 파라미터를 중복 지정하지 마세요.')
        auth = None
        if args.bearer_env:
            if not ENV_NAME.fullmatch(args.bearer_env):
                raise Stop('invalid_env', '환경 변수 이름을 확인해 주세요.')
            auth = os.environ.get(args.bearer_env)
            if not auth:
                raise Stop('auth_missing', '인증용 환경 변수를 직접 설정한 후 다시 실행해 주세요.')
            if len(auth) > 4096 or not auth.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in auth):
                raise Stop('auth_invalid', '인증용 환경 변수의 형식을 확인해 주세요.')
            origin = urllib.parse.urlsplit(base)
            if origin.scheme != 'https' and origin.hostname not in ('127.0.0.1', '::1'):
                raise Stop('insecure_transport', '인증 조회는 HTTPS가 필요합니다. 로컬 실습은 127.0.0.1 또는 ::1만 허용합니다.')
        output = args.output.absolute()
        if output.exists():
            raise Stop('output_exists', '기존 결과를 덮어쓰지 않습니다. 새 파일을 지정해 주세요.')
        # Do not create directories until the complete requested request finishes.
        if not output.parent.is_dir():
            raise Stop('output_parent_missing', '먼저 새 결과 폴더를 준비해 주세요.')
        for p in (output, *output.parents):
            if p.exists() and (p.is_symlink() or getattr(p.lstat(), 'st_file_attributes', 0) & 0x400):
                raise Stop('output_link', '연결된 폴더에는 결과를 저장하지 않습니다.')
        opener = urllib.request.build_opener(NoRedirect)
        rows, pages, seen, total_bytes = [], 0, set(), 0
        cursor, seen_cursors = None, set()
        complete, reason = False, 'page_limit'
        for offset in range(args.max_pages):
            query = params + [(args.page_size_param, str(args.page_size))]
            if not cursor_mode:
                query.append((args.page_param, str(args.start_page + offset)))
            elif cursor is not None:
                query.append((args.cursor_param, cursor))
            req = urllib.request.Request(base+'?'+urllib.parse.urlencode(query), headers={'Accept':'application/json'})
            if auth:
                req.add_header('Authorization', 'Bearer ' + auth)
            try:
                with opener.open(req, timeout=args.timeout) as response:
                    raw = response.read(MAX_BYTES + 1)
            except urllib.error.HTTPError as error:
                raise Stop('http_error', f'조회가 중단됐습니다. HTTP {error.code}; 인증·접근 권한과 요청 범위를 확인해 주세요.') from None
            except (urllib.error.URLError, OSError, ValueError):
                raise Stop('connection_error', '연결에 실패했습니다. 주소와 허용된 네트워크를 확인해 주세요.') from None
            if len(raw) > MAX_BYTES:
                raise Stop('response_too_large', '단일 응답이 안전 한도를 넘어 중단했습니다.')
            total_bytes += len(raw)
            if total_bytes > MAX_TOTAL_BYTES:
                raise Stop('response_too_large', '전체 응답이 안전 한도를 넘어 중단했습니다.')
            if auth and auth.encode('ascii') in raw:
                raise Stop('credential_in_response', '응답에 인증값이 포함되어 저장하거나 표시하지 않고 중단했습니다.')
            try:
                response_data = json.loads(raw)
                if auth and auth in json.dumps(response_data, ensure_ascii=False):
                    raise Stop('credential_in_response', '응답에 인증값이 포함되어 저장하거나 표시하지 않고 중단했습니다.')
                data = response_data
                for part in ([] if args.items_path == '.' else args.items_path.split('.')):
                    data = data[part]
            except (ValueError, TypeError, KeyError, IndexError):
                raise Stop('invalid_response', 'JSON 배열의 위치가 확인한 응답 구조와 다릅니다.') from None
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise Stop('invalid_response', '지정한 결과가 객체 배열이 아닙니다.')
            next_cursor = None
            if cursor_mode:
                try:
                    next_cursor = response_data
                    for part in args.next_cursor_path.split('.'):
                        next_cursor = next_cursor[part]
                except (TypeError, KeyError, IndexError):
                    raise Stop('invalid_response', '다음 커서 필드가 확인한 응답 구조와 다릅니다.') from None
                if next_cursor not in (None, ''):
                    if isinstance(next_cursor, bool) or not isinstance(next_cursor, (str, int)):
                        raise Stop('invalid_response', '다음 커서 형식이 올바르지 않습니다.')
                    next_cursor = str(next_cursor)
                    if len(next_cursor) > 2048 or any(ord(c) < 32 for c in next_cursor) or next_cursor.lower().startswith(('http:', 'https:', '//')):
                        raise Stop('invalid_response', '주소가 아닌 페이지 커서만 지원합니다.')
            pages += 1
            fingerprint = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8')).digest()
            if data and fingerprint in seen:
                reason = 'repeated_page'; break
            seen.add(fingerprint)
            remaining = args.max_rows-len(rows)
            rows.extend(data[:remaining])
            if len(data) > remaining:
                reason = 'row_limit'; break
            if cursor_mode and next_cursor in (None, ''):
                complete, reason = True, 'end_of_results'; break
            if not cursor_mode and len(data) < args.page_size:
                complete, reason = True, 'end_of_results'; break
            if len(rows) >= args.max_rows:
                reason = 'row_limit'; break
            if cursor_mode:
                if next_cursor in seen_cursors:
                    reason = 'repeated_cursor'; break
                seen_cursors.add(next_cursor)
                cursor = next_cursor
        rows, masked_count = redact_records(rows)
        encoded = ''.join(json.dumps(row, ensure_ascii=False, separators=(',', ':'))+'\n' for row in rows).encode('utf-8')
        try:
            fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(encoded)
            except BaseException:
                output.unlink(missing_ok=True)
                raise
        except OSError:
            raise Stop('output_unavailable', '결과를 새 파일로 저장하지 못했습니다.') from None
        result = {'ok': True, 'rows': len(rows), 'pages': pages, 'complete': complete, 'redacted_fields': masked_count,
                  'stop_reason': reason, 'output': str(output)}
        if args.preview:
            result['preview'] = rows[:args.preview]
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Stop as error:
        print(json.dumps({'ok':False,'code':error.code,'message':str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
