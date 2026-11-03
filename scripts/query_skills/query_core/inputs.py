"""조회 조건의 파일 입력과 인라인 JSON을 구분해 DB 호출 전에 설명합니다."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .store import safe_path

MAX_BYTES = 100_000


def read_cli_params(value=None, pairs=None):
    """PowerShell에서도 JSON 따옴표 없이 이름=값을 전달한다.

    문자열을 그대로 보존하고 자료형 변환은 저장 쿼리의 정의에 맡긴다.
    따라서 00123 같은 식별자의 앞자리 0도 손실되지 않는다.
    """
    if value is not None and pairs:
        raise InputError('params_conflict', '--params 파일과 --param 이름=값 중 한 방식만 사용해 주세요.')
    if value is not None:
        return read_params(value)
    result = {}
    for item in pairs or []:
        name, sep, content = item.partition('=')
        if not sep or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', name):
            raise InputError('params_invalid_pair', '--param은 이름=값 형식입니다. 예: --param fac_id=CJPKG')
        if name in result:
            raise InputError('params_duplicate_key', '같은 조회 조건을 두 번 지정하지 마세요.')
        result[name] = content
    if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > MAX_BYTES:
        raise InputError('params_too_large', '조회 조건은 100,000바이트 이내로 전달해 주세요.')
    return result


class InputError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise InputError('params_duplicate_key', '조회 조건 JSON에 같은 이름이 두 번 있습니다. 중복된 조건을 정리해 주세요.')
        value[key] = item
    return value


def _constant(value):
    raise InputError('params_invalid_json', 'NaN이나 Infinity 대신 유효한 JSON 숫자와 값을 사용해 주세요.')


def read_params(value):
    """`--params`는 현재 JSON 파일 경로 또는 JSON 객체 문자열을 받습니다."""
    if not isinstance(value, (str, Path)):
        raise InputError('params_input_required', '조회 조건을 JSON 파일 경로나 JSON 객체 문자열로 전달해 주세요.')
    inline = isinstance(value, str) and value.lstrip().startswith(('{', '['))
    if inline:
        raw = value.encode('utf-8')
    else:
        try:
            path = safe_path(value)
            with path.open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
        except FileNotFoundError:
            raise InputError('params_file_not_found', '조회 조건 파일을 찾지 못했습니다. --params에는 실제 JSON 파일 경로 또는 JSON 객체 문자열을 넣어 주세요. DB 조회는 아직 실행하지 않았습니다.') from None
        except (OSError, ValueError):
            raise InputError('params_file_unreadable', '조회 조건 파일을 열지 못했습니다. 파일 경로와 읽기 권한을 확인해 주세요. DB 조회는 아직 실행하지 않았습니다.') from None
    if len(raw) > MAX_BYTES:
        raise InputError('params_too_large', '조회 조건 JSON은 100,000바이트 이내로 전달해 주세요. 원본 데이터 전체를 조회 조건에 넣지 않습니다.')
    try:
        parsed = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs, parse_constant=_constant)
    except InputError:
        raise
    except json.JSONDecodeError as error:
        raise InputError('params_invalid_json', f'조회 조건 JSON의 {error.lineno}행 {error.colno}열 형식이 맞지 않습니다. DB 조회는 아직 실행하지 않았습니다.') from None
    except (UnicodeError, RecursionError, ValueError):
        raise InputError('params_invalid_json', '조회 조건을 UTF-8 JSON 객체로 전달해 주세요. DB 조회는 아직 실행하지 않았습니다.') from None
    if not isinstance(parsed, dict):
        raise InputError('params_not_object', '조회 조건은 이름과 값이 있는 JSON 객체여야 합니다. 예: {"start_date":"2026-11-01"}')
    return parsed
