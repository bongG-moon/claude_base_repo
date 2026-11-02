"""서버 오류의 코드와 짧은 이유만 전달하고 인증값과 SQL 본문은 숨깁니다."""
from __future__ import annotations

import json
import re
from urllib.parse import quote


MAX_REASON_BYTES = 1024
_SQL_WORDS = re.compile(r'unknown\s+(?:column|table|database)|invalid\s+(?:identifier|column|number)|'
                        r'syntax\s+error|getting\s+syntax|mismatched\s+input|'
                        r'(?:table|column|database|relation)\s+.{0,200}?(?:not\s+found|does\s+not\s+exist|doesn.t\s+exist)|'
                        r'division\s+by\s+zero|cannot\s+resolve\s+(?:column|field)|'
                        r'(?:access|permission)\s+denied|insufficient\s+privileges', re.I)
_ORACLE_SQL = {'00900', '00904', '00907', '00911', '00918', '00923', '00933', '00936', '00942',
               '01031', '01476', '01722', '01756', '01843', '01861'}
_MYSQL_SQL = {'1052', '1054', '1064', '1142', '1146', '1149', '1227'}
_ASSIGNMENT = re.compile(r'''(?P<key>["']?(?:[\w.-]*?(?:token|secret|password|passwd|pwd|jwt|api[_-]?key|access[_-]?key|private[_-]?key|credential|authorization|connection[_-]?string|dsn|host)[\w.-]*)["']?)\s*[:=]\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|''|[^'\\])*'|[^\s,;)]+)''', re.I)


def _bounded(text):
    raw = text.encode('utf-8')
    if len(raw) <= MAX_REASON_BYTES:
        return text, False
    return raw[:MAX_REASON_BYTES - 3].decode('utf-8', errors='ignore') + '…', True


def _safe_code(value):
    if type(value) is int and 0 <= value <= 999999:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r'(?:ORA|DPY|DPI)-\d{3,6}|\d{1,6}', value, re.I):
        return value.upper()
    return None


def _values(secrets, params):
    candidates = list(secrets.values()) if isinstance(secrets, dict) else list(secrets or ())
    if isinstance(params, dict):
        for value in params.values():
            candidates.extend(value if isinstance(value, (list, tuple)) else (value,))
    result = set()
    for value in candidates:
        if isinstance(value, str) and value:
            result.update((value, value.replace("'", "''"), value.replace('"', '""'),
                           json.dumps(value, ensure_ascii=False)[1:-1], quote(value, safe='')))
    return sorted(result, key=len, reverse=True)


def _redact(text, secrets, params):
    for value in _values(secrets, params):
        text = text.replace(value, '[REDACTED]')
    # 헤더의 'Bearer <값>' 두 토큰을 먼저 지워 assignment가 Bearer만 먹지 않게 한다.
    text = re.sub(r'\bBearer\s+[^\s,;\'"}]+', 'Bearer [REDACTED]', text, flags=re.I)
    text = _ASSIGNMENT.sub(lambda match: match['key'] + '=[REDACTED]', text)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', '[JWT 생략]', text)
    text = re.sub(r'\b(?:https?|jdbc|oracle|mysql)://[^\s\'"<>]+', '[접속 주소 생략]', text, flags=re.I)
    text = re.sub(r'-----BEGIN .*?PRIVATE KEY-----.*', '[비밀키 생략]', text, flags=re.I | re.S)
    return text


def error_details(exc, *, stage='query', secrets=None, params=None, engine=None):
    """임의 예외의 전체 문자열은 반환하지 않고 확인 가능한 SQL 진단만 사용합니다."""
    code, text = None, ''
    try:
        # 큰 예외 문자열을 모델이나 파일에 그대로 저장하지 않습니다.
        text = str(exc)[:16_384] if exc is not None else ''
        oracle = re.search(r'\b(?:ORA|DPY|DPI)-\d{3,6}\b', text, re.I)
        if oracle:
            code = oracle[0].upper()
        if code is None:
            for key in ('full_code', 'errno', 'code', 'status_code'):
                code = _safe_code(getattr(exc, key, None))
                if code:
                    break
        if code is None and getattr(exc, 'args', None):
            code = _safe_code(exc.args[0])
            if code is None and not isinstance(exc.args[0], (str, int, float, bool)):
                for key in ('full_code', 'code'):
                    code = _safe_code(getattr(exc.args[0], key, None))
                    if code:
                        break
        if code is None:
            match = re.search(r'\b(?:err(?:or)?[_ ]?code|errno)\s*[:=]\s*(\d{1,6})\b', text, re.I)
            code = match[1] if match else None
    except Exception:
        # SDK 예외 속성과 __str__의 구현에 오류가 있어도 기존 오류를 덮지 않습니다.
        text = ''
    category = {'connect': 'connection', 'prepare': 'connection', 'import': 'dependency',
                'fetch': 'fetch', 'timeout': 'timeout'}.get(stage, 'query')
    if code in ('401', '403', '1044', '1045', 'ORA-01017', 'ORA-28000', 'ORA-28001'):
        category = 'authentication'
    generic = {'connection': '서버 연결에 실패했습니다. 접속 상태와 인증정보를 확인해 주세요.',
               'authentication': '인증 또는 접근 권한이 거절되었습니다. 인증정보와 사용 권한을 확인해 주세요.',
               'dependency': '조회 모듈을 불러오지 못했습니다. 설치한 모듈과 실행 환경을 확인해 주세요.',
               'fetch': '조회 결과를 끝까지 받지 못했습니다. 네트워크와 서버 상태를 확인해 주세요.',
               'timeout': '조회 제한 시간이 지났습니다. 서버 측 종료 여부와 조회 범위를 확인해 주세요.',
               'query': '서버가 조회를 완료하지 못했습니다. SQL과 조건, 조회 권한을 확인해 주세요.'}
    reason = generic[category]
    sql_diagnostic = category not in ('connection', 'authentication', 'dependency', 'timeout') and (
        (code is not None and (code.removeprefix('ORA-') in _ORACLE_SQL or code in _MYSQL_SQL)) or _SQL_WORDS.search(text))
    if sql_diagnostic:
        category = 'sql'
        # 첫 진단 행만 사용합니다. 뒤에 붙은 traceback/실행 SQL/바인드 값은 버립니다.
        if code and code.startswith('ORA-'):
            offset = text.find(code)
        else:
            match = _SQL_WORDS.search(text)
            offset = match.start() if match else 0
        reason = text[max(0, offset):].splitlines()[0] if text else generic['query']
        reason = re.split(r'\b(?:SQL|Query|Statement|Parameters?|Params|Bindings?|Traceback)\s*[:=]', reason, maxsplit=1, flags=re.I)[0]
        reason = re.sub(r'\bnear\s+(?:"(?:\\.|[^"\\])*"|\'(?:\\.|\'\'|[^\'\\])*\')', 'near [SQL 조각 생략]', reason, flags=re.I)
        reason = _redact(reason, secrets, params).strip() or generic['query']
    reason, truncated = _bounded(reason)
    return {'errorCode': code, 'category': category, 'stage': stage,
            'sanitizedReason': reason, 'retryable': False, 'truncated': truncated}


def detailed_message(message, details):
    """기존 안내를 유지하면서 확인된 SQL 오류의 이유만 덧붙입니다."""
    if details.get('category') == 'sql':
        return message + ' 원인: ' + details['sanitizedReason']
    if details.get('errorCode'):
        return message + ' 오류 코드: ' + details['errorCode']
    return message
