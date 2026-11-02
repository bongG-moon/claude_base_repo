"""요청한 상위 일부 행만 짧게 보여 주는 로컬 결과 미리보기."""
from __future__ import annotations

import json
import re

from .store import read_json, safe_path

MAX_ROWS = 20
MAX_COLUMNS = 40
MAX_CHARS = 8_000
MAX_LINE_BYTES = 16 * 1024 * 1024


def result_metadata(store, engine, result_id):
    if not isinstance(result_id, str) or not re.fullmatch(r'[0-9a-f]{32}', result_id):
        raise ValueError('결과 번호가 올바르지 않습니다.')
    folder = safe_path(store.root / 'results' / result_id)
    metadata = read_json(folder / 'metadata.json', limit=2 * 1024 * 1024)
    if metadata.get('resultId') != result_id or metadata.get('engine') != engine:
        raise ValueError('이 스킬에서 만든 결과를 선택해 주세요.')
    if metadata.get('status') == 'failed' or metadata.get('dataAvailable') is False:
        return metadata, None
    data = safe_path(folder / 'data.jsonl')
    if safe_path(metadata.get('dataFile', '')) != data or not data.is_file():
        raise ValueError('조회 결과 파일 위치를 확인해 주세요. 다른 파일로 대신하지 않았습니다.')
    columns = metadata.get('columns')
    if (not isinstance(columns, list) or not 1 <= len(columns) <= 500
            or not all(isinstance(name, str) and len(name) <= 256 for name in columns)):
        raise ValueError('저장된 조회 결과의 컬럼 정보를 확인해 주세요.')
    if type(metadata.get('savedRows')) is not int or not 0 <= metadata['savedRows'] <= 1_000_000:
        raise ValueError('저장된 조회 결과의 행 수를 확인해 주세요.')
    if type(metadata.get('dataBytes')) is not int or data.stat().st_size != metadata['dataBytes']:
        raise ValueError('저장된 조회 결과 파일이 변경되었습니다. 다시 조회하거나 원본을 확인해 주세요.')
    return metadata, data


def _size(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False))


def preview_result(store, engine, result_id, *, rows=5, columns=None):
    if type(rows) is not int or not 1 <= rows <= MAX_ROWS:
        raise ValueError('미리보기는 상위 1~20행으로 요청해 주세요.')
    metadata, data = result_metadata(store, engine, result_id)
    if data is None:
        return {'ok': False, 'status': 'result_failed', 'outcome': 'error', 'resultId': result_id,
                'message': '실패한 조회에는 미리볼 데이터가 없습니다.',
                'errorDetails': metadata.get('errorDetails', {}), 'dataRowsReturned': 0}
    names = metadata['columns']
    if columns is None:
        selected = list(range(min(MAX_COLUMNS, len(names))))
    else:
        if (not isinstance(columns, list) or not 1 <= len(columns) <= MAX_COLUMNS
                or not all(isinstance(name, str) for name in columns) or len(set(columns)) != len(columns)):
            raise ValueError('미리볼 컬럼을 중복 없이 1~40개 선택해 주세요.')
        if any(names.count(name) != 1 for name in columns):
            raise ValueError('실제 컬럼 이름을 확인해 주세요. 이름이 겹치면 조회 SQL에 별칭을 지정해 주세요.')
        selected = [names.index(name) for name in columns]
    labels = [names[index][:128] for index in selected]
    when = metadata.get('executedAt')
    result = {'ok': True, 'status': 'preview', 'resultId': result_id,
              'executedAt': when[:40] if isinstance(when, str) else None, 'source': 'saved-result',
              'savedRows': metadata['savedRows'], 'complete': metadata.get('complete') is True,
              'outcome': 'empty' if metadata['savedRows'] == 0 else 'data',
              'columnCount': len(names), 'columns': labels, 'rows': [],
              'columnsTruncated': len(selected) < len(names) or labels != [names[index] for index in selected],
              'cellsTruncated': False, 'previewTruncated': metadata['savedRows'] > rows,
              'dataRowsReturned': 0,
              'message': '저장 결과의 상위 일부 행입니다. 실시간 재조회 결과로 설명하지 마세요.'}
    remaining = max(16, MAX_CHARS - _size(result) - 100)
    cell_limit = max(16, min(512, remaining // max(1, len(selected)) - 12))
    with data.open('rb') as stream:
        for _ in range(min(rows, metadata['savedRows'])):
            raw = stream.readline(MAX_LINE_BYTES + 1)
            if not raw:
                raise ValueError('저장된 행 수와 실제 결과 파일이 다릅니다.')
            if len(raw) > MAX_LINE_BYTES:
                result['previewTruncated'] = True
                result['message'] = '한 행이 커서 미리보기를 줄였습니다. Python으로 필요한 컬럼만 처리해 주세요.'
                break
            try:
                row = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ValueError('조회 결과 파일의 행 형식을 확인해 주세요.') from None
            if not isinstance(row, list) or len(row) != len(names):
                raise ValueError('조회 결과 파일의 컬럼 수가 다릅니다.')
            selected_values = []
            for index in selected:
                value = row[index]
                if isinstance(value, str) and len(value) > cell_limit:
                    value = value[:cell_limit] + '…'
                    result['cellsTruncated'] = result['previewTruncated'] = True
                elif value is not None and not isinstance(value, (str, int, float, bool)):
                    raise ValueError('미리보기를 지원하지 않는 결과 자료형입니다.')
                selected_values.append(value)
            result['rows'].append(selected_values)
            result['dataRowsReturned'] = len(result['rows'])
            if _size(result) > MAX_CHARS:
                result['rows'].pop()
                result['dataRowsReturned'] = len(result['rows'])
                result['previewTruncated'] = True
                break
    result['previewTruncated'] |= len(result['rows']) < min(rows, metadata['savedRows'])
    return result
