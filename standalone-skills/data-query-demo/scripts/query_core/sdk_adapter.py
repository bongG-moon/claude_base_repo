"""원본 사내 LakeHouse SDK 경계. SDK 결과는 전체 DataFrame으로 수신한다."""
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import date, datetime, time as datetime_time
from decimal import Decimal
import importlib
import json
import logging
import math
import re
import threading

from .adapters import AdapterError, _limit, _query_seconds
from .sql import bounded_sql, compile_for_sdk, sdk_metadata_sql

TOKEN_PAGE = 'https://lake.skhynix.com/myprofile/mykey'
_SDK_LOCK = threading.RLock()
_PROPERTY = re.compile(r'''(?P<key>"(?:\\.|""|[^"\\])*"|'(?:\\.|''|[^'\\])*'|[A-Za-z_][A-Za-z0-9_.-]*)\s*(?P<op>=|:)\s*(?:"(?:\\.|""|[^"\\])*"|'(?:\\.|''|[^'\\])*'|[^\s,;)}]+)''')
_SENSITIVE_KEY = re.compile(r'token|secret|password|passwd|access[_-]?key|private[_-]?key|credential', re.I)


class _Discard:
    """SDK 진단 출력은 크기에 관계없이 저장하지 않는다."""
    encoding = 'utf-8'
    errors = 'replace'

    @property
    def buffer(self):
        return self

    def write(self, value):
        return len(value)

    def flush(self):
        pass

    def isatty(self):
        return False


@contextmanager
def _quiet_sdk():
    # SDK가 기존 stderr logging handler를 사용해도 인증정보가 노출되지 않는다.
    # CLI 요청 하나 안에서 SDK 호출을 직렬화하며 전역 환경변수는 바꾸지 않는다.
    with _SDK_LOCK:
        previous = logging.root.manager.disable
        logging.disable(max(previous, logging.CRITICAL))
        try:
            with redirect_stdout(_Discard()), redirect_stderr(_Discard()):
                yield
        finally:
            logging.disable(previous)


def _failure_details(exc, default='db_query'):
    statuses = [getattr(exc, name, None) for name in ('status_code', 'status', 'code')]
    response = getattr(exc, 'response', None)
    if response is not None:
        statuses.append(getattr(response, 'status_code', None))
    for status in (401, 403):
        if status in statuses or str(status) in statuses:
            return AdapterError(f'api_{status}', f'LakeHouse 인증 또는 조회 권한을 확인해 주세요. 토큰 재발급: {TOKEN_PAGE}')
    # 일부 SDK 버전은 상태를 예외 텍스트로만 준다. 원문은 절대 반환하지 않는다.
    try:
        status = re.search(r'(?<!\d)(401|403)(?!\d)', str(exc)[:2048])
    except Exception:
        status = None
    if status:
        return AdapterError(f'api_{status.group(1)}', f'LakeHouse 인증 또는 조회 권한을 확인해 주세요. 토큰 재발급: {TOKEN_PAGE}')
    return AdapterError(default, 'LakeHouse SDK 조회를 마치지 못했습니다. 접속 정보, 네트워크와 조회 권한을 확인해 주세요.')


def _failure(exc, default='db_query'):
    # 예외 객체의 사용자 정의 속성/문자열 변환이 진단을 출력해도 버린다.
    with _quiet_sdk():
        try:
            return _failure_details(exc, default)
        except Exception:
            return AdapterError(default, 'LakeHouse SDK 요청을 마치지 못했습니다. 접속 설정과 조회 권한을 확인해 주세요.')


def _dependency_error():
    return AdapterError('dependency_missing', '사내 Nexus에서 제공하는 LakeHouse SDK와 pandas 등 해당 의존성을 설치해 주세요. 공개 PyPI의 동명 패키지를 대신 설치하지 마세요.')


class LakeHouseSDKBackend:
    """SDK 생성과 execute_pd 호출만 수행하며 임의 SQL 쓰기는 허용하지 않는다."""
    def __init__(self, profile, secrets):
        self.profile, self.secrets = dict(profile), dict(secrets)
        self.client = None
        self._closed = False

    def _configuration(self):
        required = ('user_id', 'token', 's3_access_key', 's3_secret_key')
        if not all(isinstance(self.secrets.get(key), str) and self.secrets[key].strip() for key in required):
            raise AdapterError('auth_config', 'Datalake SDK의 LAKEHOUSE_USER_ID, LAKEHOUSE_TOKEN, LAKEHOUSE_S3_ACCESS_KEY와 LAKEHOUSE_S3_SECRET_KEY를 설정해 주세요. 토큰 재발급: ' + TOKEN_PAGE)
        environment = self.profile.get('lake_type', 'prod')
        if environment not in ('prod', 'dev'):
            raise AdapterError('lakehouse_type', 'LAKEHOUSE_TYPE은 prod 또는 dev로 지정해 주세요.')
        return required, environment

    def _connect(self):
        if self._closed:
            raise AdapterError('db_closed', '종료한 SDK 연결은 다시 사용할 수 없습니다.')
        if self.client is not None:
            return self.client
        required, environment = self._configuration()
        try:
            with _quiet_sdk():
                driver = importlib.import_module('lakes.client')
        except ImportError:
            raise _dependency_error() from None
        except Exception as exc:
            raise _failure(exc, 'sdk_import') from None
        try:
            with _quiet_sdk():
                self.client = driver.LakeHouse(**{key: self.secrets[key] for key in required},
                                              type=environment, spark=False)
        except Exception as exc:
            raise _failure(exc, 'db_connect') from None
        return self.client

    def inspect(self, sql, params):
        self._configuration()
        compile_for_sdk(sql, params)
        return {'estimated_rows': None, 'exact_count': None,
                'notes': ['SDK 사전 건수는 미확인입니다. COUNT와 결과 조회를 사전에 실행하지 않습니다.',
                          'SDK는 서버 행 제한을 적용한 결과 전체를 DataFrame으로 메모리에 받습니다. 파일 용량 제한은 SDK 수신 메모리를 제한하지 않습니다.']}

    def _frame(self, statement):
        client = self._connect()
        try:
            with _quiet_sdk():
                pandas = importlib.import_module('pandas')
                frame = client.execute_pd(query=statement)
                if not isinstance(frame, pandas.DataFrame):
                    raise AdapterError('sdk_format', 'SDK가 DataFrame 조회 결과를 반환하지 않았습니다.')
                columns = list(frame.columns)
                if not columns or len(columns) > 500 or not all(isinstance(c, str) and len(c) <= 256 for c in columns):
                    raise AdapterError('sdk_format', 'SDK 결과 컬럼 형식을 확인해 주세요.')
                iterator = frame.itertuples(index=False, name=None)
        except AdapterError:
            raise
        except ImportError:
            raise _dependency_error() from None
        except Exception as exc:
            raise _failure(exc) from None
        return frame, pandas, columns, iterator

    @contextmanager
    def execute(self, sql, params, *, limit, timeout_seconds):
        count = _limit(limit) + 1
        seconds = _query_seconds(timeout_seconds, unbounded=True)
        if seconds is not None:
            raise AdapterError('sdk_timeout_unsupported', '이 SDK에는 조회 시간 제한과 취소 API가 확인되지 않았습니다. 시간 지정을 생략하거나 해당 기능을 지원하는 조회 방법을 사용해 주세요.')
        # SDK의 임의 write 허용 환경변수와 관계없이 SELECT 검사를 먼저 수행한다.
        statement = compile_for_sdk(bounded_sql(sql, 'datalake', count), params)
        frame, pandas, columns, iterator = self._frame(statement)
        rows = self._rows(iterator, pandas, count)
        try:
            yield columns, rows
        finally:
            # DataFrame을 백엔드나 전역에 보관하지 않는다. 사용자 결과 파일은 건드리지 않는다.
            rows.close()
            iterator = frame = None

    def metadata(self, sql, *, max_rows=100):
        if type(max_rows) is not int or not 1 <= max_rows <= 100:
            raise AdapterError('invalid_limit', '테이블 탐색은 1~100행 범위로 요청해 주세요.')
        statement, kind = sdk_metadata_sql(sql)
        frame, pandas, columns, iterator = self._frame(statement)
        try:
            rows = list(self._rows(iterator, pandas, max_rows + 1))
            return {'columns': [self._redact(c) for c in columns],
                    'rows': [tuple(self._redact(v) if isinstance(v, str) else v for v in row) for row in rows[:max_rows]],
                    'complete': len(rows) <= max_rows, 'kind': kind}
        finally:
            iterator = frame = None

    def _redact(self, text):
        def redact_property(match):
            if _SENSITIVE_KEY.search(match['key']):
                return match['key'] + match['op'] + "'[REDACTED]'"
            return match[0]
        text = _PROPERTY.sub(redact_property, text)
        # 이미 알려진 인증정보가 일반 DDL 값이나 오류 안내 컬럼에 있어도 숨긴다.
        variants = set()
        for value in self.secrets.values():
            if isinstance(value, str) and value:
                variants.update((value, value.replace("'", "''"), value.replace('"', '""'), json.dumps(value)[1:-1]))
        for value in sorted(variants, key=len, reverse=True):
            text = text.replace(value, '[REDACTED]')
        return text

    @staticmethod
    def _value(value, pandas):
        if value is None or value is pandas.NA or value is pandas.NaT:
            return None
        if type(value).__module__.startswith('numpy') and hasattr(value, 'item'):
            kind = getattr(getattr(value, 'dtype', None), 'kind', None)
            if kind == 'M':
                # datetime64[ns].item()은 날짜 대신 epoch 정수를 반환한다.
                value = pandas.Timestamp(value)
                return None if value is pandas.NaT else value
            if kind == 'm':
                raise AdapterError('sdk_format', '기간 자료형은 자동 저장하지 않습니다. 필요한 단위의 숫자나 문자열 컬럼으로 조회해 주세요.')
            value = value.item()
        if isinstance(value, float) and math.isnan(value):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            raise AdapterError('sdk_format', '유한한 숫자가 아닌 SDK 결과 값이 있습니다.')
        if value is None or isinstance(value, (str, int, float, bool, Decimal, date, datetime, datetime_time)):
            return value
        raise AdapterError('sdk_format', '자동 저장하지 않는 SDK 결과 자료형이 있습니다. 일반 컬럼만 선택해 주세요.')

    @classmethod
    def _rows(cls, iterator, pandas, count):
        for _ in range(count):
            try:
                with _quiet_sdk():
                    row = next(iterator)
                    values = tuple(cls._value(value, pandas) for value in row)
            except StopIteration:
                return
            except AdapterError:
                raise
            except Exception as exc:
                raise _failure(exc, 'db_fetch') from None
            yield values

    def close(self):
        if self._closed:
            return
        self._closed = True
        client, self.client = self.client, None
        try:
            with _quiet_sdk():
                close = getattr(client, 'close', None)
                if callable(close):
                    close()
        except Exception:
            pass
