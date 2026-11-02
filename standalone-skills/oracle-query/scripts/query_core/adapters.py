"""조회 연결 경계. 실습은 SQLite만 사용하고 운영 드라이버는 필요할 때 불러온다."""
from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import math
import re
import sqlite3
import threading
import time
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlsplit

from .errors import detailed_message, error_details


class AdapterError(Exception):
    """인증값을 숨긴 사용자용 오류와 선택적인 짧은 서버 진단."""
    def __init__(self, code, message, details=None):
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(message)


def _error(code, message, exc=None, *, stage='query', secrets=None, params=None, engine=None):
    details = error_details(exc, stage=stage, secrets=secrets, params=params, engine=engine)
    return AdapterError(code, detailed_message(message, details), details)


def _seconds(value, maximum=3600):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        raise AdapterError('invalid_timeout', '조회 시간 제한을 확인해 주세요.')
    return float(value)


def _query_seconds(value, *, unbounded=False):
    if unbounded and value is None:
        return None
    return _seconds(value, maximum=threading.TIMEOUT_MAX - 1 if unbounded else 3600)


def _limit(value):
    if type(value) is not int or not 1 <= value <= 1_000_000:
        raise AdapterError('invalid_limit', '조회 행 한도는 1~1,000,000 사이여야 합니다.')
    return value


def _close(obj, method='close'):
    if obj is not None:
        try:
            getattr(obj, method)()
        except Exception:
            pass


def _sql(sql, params, engine, count=None):
    from .sql import bounded_sql, compile_for_engine
    if count is not None:
        sql = bounded_sql(sql, engine, count)
    statement, binds = compile_for_engine(sql, params, engine)
    if engine == 'sqlite':
        # 실습 DB에서만 자료형을 명시 변환합니다. 운영 드라이버의 날짜/숫자는 유지합니다.
        binds = {key: value.isoformat() if isinstance(value, (date, datetime)) else
                 str(value) if isinstance(value, Decimal) else value for key, value in binds.items()}
    return statement, binds


def _rows(cursor, count, deadline, expired, *, secrets=None, params=None, engine=None):
    read = 0
    while read < count:
        if expired.is_set() or (deadline is not None and time.monotonic() >= deadline):
            raise AdapterError('query_timeout', '조회 제한 시간이 지나 중단했습니다. 기간이나 조건을 줄여 주세요.')
        try:
            batch = cursor.fetchmany(min(500, count - read))
        except Exception as exc:
            code = 'query_timeout' if expired.is_set() or (deadline is not None and time.monotonic() >= deadline) else 'db_fetch'
            raise _error(code, '결과를 끝까지 받지 못했습니다. 제한 시간, 네트워크와 조회 상태를 확인해 주세요.', exc,
                         stage='timeout' if code == 'query_timeout' else 'fetch', secrets=secrets, params=params, engine=engine) from None
        if not batch:
            return
        for row in batch:
            if expired.is_set() or (deadline is not None and time.monotonic() >= deadline):
                raise AdapterError('query_timeout', '조회 제한 시간이 지나 중단했습니다. 기간이나 조건을 줄여 주세요.')
            read += 1
            yield tuple(row)


@contextmanager
def _deadline(seconds, cancel):
    """전체 실행 시간 경과 시 취소를 요청한다. 서버 종료를 보증하는 표시는 하지 않는다."""
    expired = threading.Event()
    if seconds is None:
        yield None, expired
        return
    end = time.monotonic() + _query_seconds(seconds, unbounded=True)

    def expire():
        expired.set()
        try:
            cancel()
        except Exception:
            pass

    timer = threading.Timer(seconds, expire)
    timer.daemon = True
    timer.start()
    try:
        yield end, expired
    finally:
        timer.cancel()


class DemoBackend:
    """정해진 합성 테이블만 메모리에 생성한다. 사용자 파일과 운영 환경변수는 읽지 않는다."""
    def __init__(self, profile):
        variant = profile.get('demo_database', 'production')
        if variant not in ('production', 'quality'):
            raise AdapterError('demo_profile_unknown', '실습 DB는 production 또는 quality를 선택해 주세요.')
        self.connection = sqlite3.connect(':memory:', check_same_thread=False)
        multiplier = 1 if variant == 'production' else 2
        self.connection.executescript('''
            CREATE TABLE production_records(work_date TEXT, process TEXT, quantity INTEGER, lot_id TEXT);
            CREATE TABLE large_records(id INTEGER, work_date TEXT, quantity INTEGER);
            CREATE TABLE special_values(id INTEGER, label TEXT, quantity INTEGER);
            CREATE TABLE dual(dummy TEXT);
            INSERT INTO dual VALUES ('X');
        ''')
        rows = [('2026-09-01', 'DA', 100, 'LOT001'), ('2026-09-01', 'WB', 200, 'LOT002'),
                ('2026-09-02', 'DA', 130, 'LOT003'), ('2026-09-02', 'WB', 300, 'LOT004'),
                ('2026-10-01', 'DA', 150, 'LOT005'), ('2026-10-01', 'WB', 160, 'LOT006')]
        self.connection.executemany('INSERT INTO production_records VALUES (?,?,?,?)',
                                    [(a, b, c * multiplier, d) for a, b, c, d in rows])
        self.connection.executemany('INSERT INTO large_records VALUES (?,?,?)',
            ((i, '2026-09-%02d' % ((i % 28) + 1), i * multiplier) for i in range(1, 12006)))
        self.connection.executemany('INSERT INTO special_values VALUES (?,?,?)',
            [(1, '00123', 10), (2, '=1+1', 20), (3, '쉼표,줄\n바꿈', 30), (4, None, 0)])
        self.connection.commit()
        self.connection.execute('PRAGMA query_only=ON')

    def inspect(self, sql, params):
        statement, binds = _sql(sql, params, 'sqlite')
        try:
            # 정확한 건수는 가상 실습 데이터에서만 계산한다.
            with _deadline(5, self.connection.interrupt) as (end, expired):
                self.connection.set_progress_handler(lambda: int(expired.is_set() or time.monotonic() >= end), 1000)
                cursor = self.connection.execute('SELECT COUNT(*) FROM (' + statement + ')', binds)
                try:
                    value = cursor.fetchone()[0]
                finally:
                    cursor.close()
            return {'estimated_rows': None, 'exact_count': value,
                    'notes': ['가상 실습 데이터의 정확한 건수입니다. 운영 DB 성능 측정값이 아닙니다.']}
        except Exception as exc:
            raise _error('demo_sql', '실습 SQL을 확인해 주세요. 운영 DB 전용 구문은 실습에서 지원되지 않을 수 있습니다.', exc,
                         params=params, engine='sqlite') from None
        finally:
            self.connection.set_progress_handler(None, 0)

    @contextmanager
    def execute(self, sql, params, *, limit, timeout_seconds):
        count = _limit(limit) + 1
        statement, binds = _sql(sql, params, 'sqlite', count)
        cursor = None
        yielding = False
        try:
            with _deadline(_query_seconds(timeout_seconds, unbounded=True), self.connection.interrupt) as (end, expired):
                self.connection.set_progress_handler(lambda: int(expired.is_set() or (end is not None and time.monotonic() >= end)), 1000)
                cursor = self.connection.execute(statement, binds)
                yielding = True
                yield [c[0] for c in cursor.description], _rows(cursor, count, end, expired)
        except AdapterError:
            raise
        except Exception as exc:
            if yielding:
                raise
            raise _error('demo_sql', '실습 조회를 마치지 못했습니다. SQL과 제한 시간을 확인해 주세요.', exc,
                         params=params, engine='sqlite') from None
        finally:
            self.connection.set_progress_handler(None, 0)
            _close(cursor)

    def close(self):
        _close(self.connection)


def _oracle_number_handler(cursor, metadata):
    """Oracle NUMBER를 float로 먼저 바꾸지 않아 원래 소수 정밀도를 유지합니다."""
    driver = importlib.import_module('oracledb')
    if metadata.type_code is driver.DB_TYPE_NUMBER:
        return cursor.var(Decimal, arraysize=cursor.arraysize)
    return None


class OracleBackend:
    def __init__(self, profile, secrets):
        self.profile, self.secrets = profile, secrets
        self.connection = None

    def _connect(self):
        if self.connection is not None:
            return self.connection
        if not all(isinstance(self.secrets.get(k), str) and self.secrets[k].strip()
                   for k in ('user', 'password', 'dsn')):
            raise AdapterError('auth_config', '등록한 DB의 인증정보가 부족합니다. 채팅에 보내지 말고 로컬 입력창에서 ID, 비밀번호와 DSN을 저장해 주세요.')
        try:
            driver = importlib.import_module('oracledb')
        except ImportError:
            raise AdapterError('dependency_missing', 'Oracle 조회에 필요한 python-oracledb를 설치해 주세요.') from None
        try:
            mode = self.profile.get('mode', 'thin')
            if mode not in ('thin', 'thick'):
                raise AdapterError('oracle_mode', 'Oracle 연결 방식은 thin 또는 thick이어야 합니다.')
            if mode == 'thick' and driver.is_thin_mode():
                driver.init_oracle_client(lib_dir=self.profile.get('client_lib_dir') or None)
            elif mode == 'thin' and not driver.is_thin_mode():
                raise AdapterError('oracle_mode', '다른 Oracle 연결 방식이 사용 중입니다. 조회 프로세스를 다시 시작해 주세요.')
            try:
                self.connection = driver.connect(user=self.secrets['user'], password=self.secrets['password'],
                    dsn=self.secrets['dsn'], tcp_connect_timeout=_seconds(self.profile.get('connect_timeout', 10), 120))
            except AdapterError:
                raise
            except Exception as exc:
                raise _error('db_connect', '등록한 DB에 연결하지 못했습니다. HyDAP(Chakra)실행 여부 및 MyAccess권한 확인 부탁드립니다. 접속 정보와 네트워크도 확인해 주세요.', exc,
                             stage='connect', secrets=self.secrets, engine='oracle') from None
            self.connection.autocommit = False
            return self.connection
        except AdapterError:
            raise
        except Exception as exc:
            raise _error('db_connect', '등록한 DB에 연결하지 못했습니다. 접속 정보, 네트워크와 조회 권한을 확인해 주세요.', exc,
                         stage='connect', secrets=self.secrets, engine='oracle') from None

    def inspect(self, sql, params):
        # EXPLAIN PLAN은 PLAN_TABLE 쓰기 권한이 필요하므로 읽기 전용 계정에 강제하지 않는다.
        _sql(sql, params, 'oracle')
        return {'estimated_rows': None, 'exact_count': None,
                'notes': ['Oracle 사전 건수는 미확인입니다. 전체 COUNT와 계획 테이블 기록은 자동 실행하지 않습니다.']}

    @contextmanager
    def execute(self, sql, params, *, limit, timeout_seconds):
        count = _limit(limit) + 1
        seconds = _seconds(timeout_seconds)
        statement, binds = _sql(sql, params, 'oracle', count)
        conn, cursor = self._connect(), None
        expired = threading.Event()
        yielding = False
        try:
            conn.call_timeout = max(1, int(seconds * 1000))
            with _deadline(seconds, conn.cancel) as (end, expired):
                cursor = conn.cursor()
                cursor.arraysize = min(500, count)
                cursor.outputtypehandler = _oracle_number_handler
                cursor.execute('SET TRANSACTION READ ONLY')
                cursor.execute(statement, binds)
                if cursor.description is None:
                    raise AdapterError('readonly_required', '조회 결과가 없는 명령은 실행할 수 없습니다.')
                yielding = True
                yield [str(c[0]) for c in cursor.description], _rows(cursor, count, end, expired, secrets=self.secrets, params=params, engine='oracle')
        except AdapterError:
            raise
        except Exception as exc:
            if yielding:
                raise
            if expired.is_set():
                raise _error('query_timeout', '조회 시간이 지나 취소를 요청했습니다. 서버 측 종료 여부는 별도 확인이 필요할 수 있습니다.', exc,
                             stage='timeout', secrets=self.secrets, params=params, engine='oracle') from None
            raise _error('db_query', 'Oracle 조회를 마치지 못했습니다. SQL, 조건과 조회 권한을 확인해 주세요.', exc,
                         secrets=self.secrets, params=params, engine='oracle') from None
        finally:
            _close(cursor)
            _close(conn, 'rollback')

    def close(self):
        _close(self.connection, 'rollback')
        _close(self.connection)
        self.connection = None


def _endpoint(value):
    if not isinstance(value, str) or not value or any(c in value for c in '/?#@\\'):
        raise AdapterError('cluster_endpoint', '클러스터 접속 주소 형식을 확인해 주세요.')
    try:
        parsed = urlsplit('//' + value)
        if not parsed.hostname or not parsed.port or parsed.username or parsed.password:
            raise ValueError()
        return parsed.hostname, parsed.port
    except ValueError:
        raise AdapterError('cluster_endpoint', '클러스터 접속 주소 형식을 확인해 주세요.') from None


def _candidates(body):
    if not isinstance(body, dict):
        raise AdapterError('api_format', '클러스터 응답 형식이 예상과 다릅니다.')
    if 'status' in body and 'content' not in body:
        return [body]
    content = body.get('content')
    if isinstance(content, list) and all(isinstance(c, dict) for c in content):
        return content
    raise AdapterError('api_format', '클러스터 응답 형식이 예상과 다릅니다.')


class LakeBackend:
    def __init__(self, profile, secrets):
        self.profile, self.secrets = profile, secrets
        self.connection = None

    def _prepare_cluster(self):
        if self.profile.get('allow_cluster_start') is not True:
            raise AdapterError('cluster_start_confirmation_required', '연결 준비가 클러스터를 시작할 수 있습니다. 연결 설정에서 해당 동작을 허용해 주세요.')
        base = self.profile.get('api_base', '')
        if not isinstance(base, str):
            raise AdapterError('api_config', 'LakeHouse 서버 주소를 설정해 주세요.')
        try:
            parsed = urlsplit(base)
        except ValueError:
            raise AdapterError('api_config', 'LakeHouse 서버 주소를 확인해 주세요.') from None
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise AdapterError('api_config', 'LakeHouse 서버 주소를 확인해 주세요.')
        if parsed.scheme == 'http' and self.profile.get('allow_http') is not True:
            raise AdapterError('http_confirmation_required', '이 서버는 HTTP 주소입니다. 회사에서 사용하는 주소인지 확인한 뒤 연결 설정에서 허용해 주세요.')
        if not all(isinstance(self.secrets.get(k), str) and self.secrets[k].strip() for k in ('user_id', 'token')):
            raise AdapterError('auth_config', 'LakeHouse 사번과 토큰이 필요합니다. 채팅에 보내지 말고 로컬 입력창에서 저장해 주세요.')
        try:
            requests = importlib.import_module('requests')
        except ImportError:
            raise AdapterError('dependency_missing', 'LakeHouse 조회에 필요한 requests를 설치해 주세요.') from None
        deadline = time.monotonic() + _seconds(self.profile.get('prepare_timeout', 120), 300)
        cluster_name = self.profile.get('cluster', '')
        if not isinstance(cluster_name, str):
            raise AdapterError('cluster_config', '클러스터 이름을 확인해 주세요.')
        headers = {'Authorization': 'Bearer ' + self.secrets['token'],
                   'accept': 'application/json', 'comment': 'lake-python-sdk'}
        try:
            with requests.Session() as session:
                # 기존 프로세스의 프록시/인증 환경으로 자격증명이 전송되지 않도록 명시한다.
                session.trust_env = False
                while time.monotonic() < deadline:
                    remaining = max(.1, deadline - time.monotonic())
                    response = session.get(base.rstrip('/') + '/runtime/cluster/starrocks/running',
                        params={'name': cluster_name or 'None'}, headers=headers, allow_redirects=False,
                        timeout=(min(5, remaining), min(15, remaining)), stream=True,
                        verify=self.profile.get('tls_ca') or True)
                    try:
                        code = response.status_code
                        if code in (401, 403):
                            raise AdapterError('api_' + str(code), '인증 또는 클러스터 사용 권한을 확인해 주세요.')
                        if code != 200:
                            raise AdapterError('api_response', '클러스터 준비 요청을 처리하지 못했습니다. 서버 주소와 상태를 확인해 주세요.')
                        payload = bytearray()
                        for chunk in response.iter_content(8192):
                            payload.extend(chunk)
                            if len(payload) > 1_048_576 or time.monotonic() >= deadline:
                                raise AdapterError('api_limit', '클러스터 응답이 크거나 준비 제한 시간이 지났습니다.')
                        try:
                            body = json.loads(payload)
                        except (ValueError, UnicodeError):
                            raise AdapterError('api_format', '클러스터 응답 형식이 예상과 다릅니다.') from None
                        choices = _candidates(body)
                    finally:
                        response.close()
                    if cluster_name:
                        choices = [c for c in choices if c.get('name') == cluster_name]
                    else:
                        defaults = [c for c in choices if c.get('isDefault') is True or c.get('is_default') is True]
                        choices = defaults or choices
                    if len(choices) > 1:
                        raise AdapterError('cluster_ambiguous', '클러스터가 여러 개입니다. 연결 설정에서 사용할 이름을 지정해 주세요.')
                    if choices and choices[0].get('status') == 'RUNNING':
                        endpoints = choices[0].get('endpoints')
                        if not isinstance(endpoints, dict):
                            raise AdapterError('cluster_endpoint', '클러스터 접속 주소가 응답에 없습니다.')
                        addresses = []
                        for key in ('jdbc-internal', 'jdbc-external'):
                            if endpoints.get(key):
                                endpoint = _endpoint(endpoints[key])
                                if endpoint not in addresses:
                                    addresses.append(endpoint)
                        if not addresses:
                            raise AdapterError('cluster_endpoint', '클러스터 접속 주소가 응답에 없습니다.')
                        return addresses
                    time.sleep(min(1, max(0, deadline - time.monotonic())))
        except AdapterError:
            raise
        except Exception as exc:
            raise _error('api_network', '클러스터에 연결하지 못했습니다. 네트워크, 인증서와 서버 응답을 확인해 주세요.', exc,
                         stage='prepare', secrets=self.secrets, engine='starrocks') from None
        raise AdapterError('cluster_timeout', '클러스터 준비 시간이 지났습니다. 포털에서 상태를 확인해 주세요.')

    def _connect(self):
        if self.connection is not None:
            return self.connection
        # 의존성이 없으면 클러스터를 시작하기 전에 멈춘다.
        try:
            driver = importlib.import_module('mysql.connector')
        except ImportError:
            raise AdapterError('dependency_missing', 'LakeHouse 조회에 필요한 mysql-connector-python을 설치해 주세요.') from None
        endpoints = self._prepare_cluster()
        last_error = None
        for host, port in endpoints:
            try:
                options = dict(host=host, port=port, user=self.secrets['user_id'], password=self.secrets['token'],
                    use_pure=True, auth_plugin='mysql_clear_password', ssl_disabled=False,
                    ssl_verify_cert=True, ssl_verify_identity=True, allow_local_infile=False,
                    connection_timeout=max(1, int(_seconds(self.profile.get('connect_timeout', 10), 120))),
                    read_timeout=None if self.profile.get('engine') == 'datalake' else 60,
                    write_timeout=None if self.profile.get('engine') == 'datalake' else 60)
                if self.profile.get('tls_ca'):
                    options['ssl_ca'] = self.profile['tls_ca']
                self.connection = driver.connect(**options)
                cursor = self.connection.cursor()
                try:
                    cursor.execute("SET CATALOG = 'lake_catalog'")
                finally:
                    _close(cursor)
                return self.connection
            except Exception as exc:
                last_error = exc
                _close(self.connection)
                self.connection = None
        raise _error('db_connect', 'LakeHouse 조회 연결을 만들지 못했습니다. 네트워크, 인증서와 조회 권한을 확인해 주세요.', last_error,
                     stage='connect', secrets=self.secrets, engine='starrocks') from None

    def inspect(self, sql, params):
        statement, binds = _sql(sql, params, 'starrocks')
        conn, cursor = self._connect(), None
        try:
            with _deadline(5, conn.close) as (end, expired):
                cursor = conn.cursor()
                # Datalake는 서버의 원래 세션 제한을 바꾸지 않습니다.
                # 계획 확인은 클라이언트의 짧은 실패 감지만 적용합니다.
                if self.profile.get('engine') != 'datalake':
                    cursor.execute('SET query_timeout = 5')
                cursor.execute('EXPLAIN COSTS ' + statement, binds)
                highest = None
                # 실행계획 원문과 필터 상수는 반환하지 않는다.
                for row in _rows(cursor, 500, end, expired, secrets=self.secrets, params=params, engine='starrocks'):
                    for value in row:
                        for match in re.finditer(r'cardinality\s*[:=]\s*(\d[\d,]*(?:\.\d+)?(?:e[+-]?\d+)?)', str(value), re.I):
                            parsed = float(match.group(1).replace(',', ''))
                            if not math.isfinite(parsed):
                                continue
                            number = math.ceil(parsed)
                            highest = number if highest is None else max(highest, number)
                return {'estimated_rows': None, 'exact_count': None, 'plan_max_rows': highest,
                        'notes': ['실행계획의 최대 단계 추정치는 결과 건수나 정확한 스캔 건수가 아닙니다.']}
        except AdapterError:
            raise
        except Exception as exc:
            # 계획 조회 실패를 본 조회 성공이나 0건으로 바꾸지 않는다.
            raise _error('plan_unavailable', '사전 실행계획을 확인하지 못했습니다. 운영 버전과 조회 권한을 확인해 주세요.', exc,
                         secrets=self.secrets, params=params, engine='starrocks') from None
        finally:
            _close(cursor)

    @contextmanager
    def execute(self, sql, params, *, limit, timeout_seconds):
        count = _limit(limit) + 1
        unbounded = self.profile.get('engine') == 'datalake'
        seconds = _query_seconds(timeout_seconds, unbounded=unbounded)
        statement, binds = _sql(sql, params, 'starrocks', count)
        conn, cursor = self._connect(), None
        expired = threading.Event()
        yielding = False
        try:
            conn.read_timeout = None if seconds is None else max(1, math.ceil(seconds))
            conn.write_timeout = None if seconds is None else max(1, math.ceil(seconds))
            with _deadline(seconds, conn.close) as (end, expired):
                cursor = conn.cursor()
                if not unbounded:
                    cursor.execute('SET query_timeout = ' + str(max(1, math.ceil(seconds))))
                cursor.execute(statement, binds)
                if cursor.description is None:
                    raise AdapterError('readonly_required', '조회 결과가 없는 명령은 실행할 수 없습니다.')
                yielding = True
                yield [str(c[0]) for c in cursor.description], _rows(cursor, count, end, expired, secrets=self.secrets, params=params, engine='starrocks')
        except AdapterError:
            raise
        except Exception as exc:
            if yielding:
                raise
            if expired.is_set():
                raise _error('query_timeout', '조회 시간이 지나 연결 종료를 요청했습니다. 서버 쿼리는 서버 시간 제한까지 남을 수 있습니다.', exc,
                             stage='timeout', secrets=self.secrets, params=params, engine='starrocks') from None
            raise _error('db_query', 'LakeHouse 조회를 마치지 못했습니다. SQL, 조건과 조회 권한을 확인해 주세요.', exc,
                         secrets=self.secrets, params=params, engine='starrocks') from None
        finally:
            _close(cursor)

    def close(self):
        _close(self.connection)
        self.connection = None


@contextmanager
def open_backend(profile, secrets, *, demo=False, timeout_seconds=60):
    """선택한 연결만 연다. 실패한 운영 연결을 실습 데이터로 바꾸지 않는다."""
    engine = profile.get('engine')
    if engine not in ('oracle', 'datalake', 'ehub'):
        raise AdapterError('engine_unknown', '조회 종류를 확인해 주세요.')
    _query_seconds(timeout_seconds, unbounded=engine == 'datalake')
    if demo is True:
        backend = DemoBackend(profile)
    elif engine == 'datalake':
        from .sdk_adapter import LakeHouseSDKBackend
        backend = LakeHouseSDKBackend(profile, secrets)
    else:
        backend = OracleBackend(profile, secrets) if engine == 'oracle' else LakeBackend(profile, secrets)
    try:
        yield backend
    except AdapterError as error:
        if demo is not True:
            from .credentials import annotate_auth_error
            annotate_auth_error(error, engine, profile.get('id'))
        raise
    finally:
        backend.close()
