"""필요할 때만 SDK로 테이블 메타데이터를 확인하고 짧은 요약을 전달합니다."""
from __future__ import annotations

import json
import re
import uuid

from .store import atomic_json, safe_path


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]{0,255}', value):
        raise ValueError('스키마와 테이블 이름은 실제 확인한 식별자로 입력해 주세요.')
    return '`' + value + '`'


def discover(store, engine, args):
    if engine != 'datalake' or store.demo:
        raise ValueError('Datalake SDK 테이블 탐색에서만 사용할 수 있습니다.')
    profile = store.datalake_profile(getattr(args, 'profile', None))
    from .sql import compile_for_sdk
    limit = getattr(args, 'limit', 100)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('탐색 결과는 한 번에 1~100개로 확인해 주세요.')
    if args.action == 'tables':
        pattern = args.like
        if not isinstance(pattern, str) or not 1 <= len(pattern) <= 256:
            raise ValueError('테이블 검색어를 1~256자로 입력해 주세요.')
        literal = compile_for_sdk('SELECT :pattern', {'pattern': pattern})[len('SELECT '):]
        statement = 'SHOW TABLES FROM `lake_catalog`.' + _identifier(args.schema) + ' LIKE ' + literal
    elif args.action in {'describe', 'show-create'}:
        parts = args.table.split('.')
        if len(parts) != 3 or parts[0] != 'lake_catalog':
            raise ValueError('테이블은 lake_catalog.스키마.테이블 형식으로 입력해 주세요.')
        statement = ('DESCRIBE ' if args.action == 'describe' else 'SHOW CREATE TABLE ') + '.'.join(map(_identifier, parts))
    elif args.action == 'explain':
        source = safe_path(args.sql_file)
        with source.open('rb') as stream:
            raw = stream.read(40_001)
        if len(raw) > 40_000:
            raise ValueError('실행계획 SQL은 40,000바이트 이하로 입력해 주세요.')
        statement = 'EXPLAIN ' + compile_for_sdk(raw.decode('utf-8-sig'), {})
    else:
        raise ValueError('지원하는 테이블 탐색을 선택해 주세요.')
    from .adapters import open_backend
    with open_backend(profile, store.secrets(profile['id']), timeout_seconds=None) as backend:
        result = backend.metadata(statement, max_rows=limit)
    from .core import _cell
    result['rows'] = [[_cell(value) for value in row] for row in result['rows']]
    # 전체 메타정보는 로컬에 남기고 모델에는 완전한 행 단위로 짧게 전달합니다.
    path = safe_path(store.root / 'discovery' / (uuid.uuid4().hex + '.json'))
    atomic_json(path, result)
    columns = [name[:128] for name in result['columns'][:40]]
    shortened = columns != result['columns']
    rows = []
    for row in result['rows']:
        preview = []
        for value in row[:len(columns)]:
            if isinstance(value, str) and len(value) > 2000:
                value = value[:2000] + '…'
                shortened = True
            preview.append(value)
        if len(json.dumps({'columns': columns, 'rows': rows + [preview]}, ensure_ascii=False)) > 8000:
            break
        rows.append(preview)
    truncated = shortened or len(rows) != len(result['rows']) or not result['complete']
    return {'ok': True, 'kind': result['kind'], 'sourceName': profile['name'],
            'columns': columns, 'rows': rows, 'metadataRowsReturned': len(rows),
            'complete': not truncated, 'previewTruncated': truncated, 'metadataFile': str(path),
            'dataRowsReturned': 0,
            'message': '테이블 메타데이터만 확인했습니다. 기간이나 원래 조회 조건은 변경하지 않았습니다.'}
