"""Metadata-only result review and explicit, snapshot-bound local cleanup.

Listing never opens JSONL/CSV data. Preparing and confirming a deletion streams
bytes only to verify ownership/change hashes; it never parses or returns rows.
Database profiles, SQL, credentials, external exports and unknown files are not
cleanup targets. No maintenance runs implicitly from query planning/execution.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid

from .store import atomic_json, fingerprint, read_json, safe_path

STALE_SECONDS = 24 * 60 * 60
PLAN_SECONDS = 15 * 60
ENGINES = {'oracle', 'datalake', 'ehub', 'demo'}
ID = re.compile(r'[0-9a-f]{32}')


def _id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('결과 또는 정리 준비 번호가 올바르지 않습니다.')
    return value


def _now(value):
    value = time.time() if value is None else value
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('조회 결과의 기준 시간을 확인해 주세요.')
    return float(value)


def result_label(query_name, source_name, created_at, result_id):
    def part(value):
        return re.sub(r'[\s<>:"/\\|?*\x00-\x1f]+', '_', str(value)).strip('_')[:32] or '결과'
    when = dt.datetime.fromtimestamp(created_at, dt.timezone.utc).strftime('%Y%m%d-%H%M%SZ')
    return f'{part(query_name)}_{part(source_name)}_{when}_{_id(result_id)[:8]}'


def _folder(store, result_id):
    root = safe_path(store.root / 'results')
    path = safe_path(root / _id(result_id))
    if path.parent != root or not path.is_dir():
        raise ValueError('저장된 결과 폴더를 확인할 수 없습니다.')
    _no_streams(root)
    _no_streams(path)
    return path


def _no_streams(path):
    """Unknown NTFS streams may be personal data on files OR directories."""
    if os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes
    class StreamData(ctypes.Structure):
        _fields_ = [('size', ctypes.c_longlong), ('name', wintypes.WCHAR * 296)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    first, next_stream, close = kernel.FindFirstStreamW, kernel.FindNextStreamW, kernel.FindClose
    first.argtypes, first.restype = [wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(StreamData), wintypes.DWORD], wintypes.HANDLE
    next_stream.argtypes, next_stream.restype = [wintypes.HANDLE, ctypes.POINTER(StreamData)], wintypes.BOOL
    close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
    data = StreamData()
    handle = first(str(path), 0, ctypes.byref(data), 0)
    if handle == ctypes.c_void_p(-1).value:
        if ctypes.get_last_error() == 38:  # ERROR_HANDLE_EOF: no streams
            return
        raise ValueError('파일의 추가 데이터 유무를 확인하지 못해 보존합니다.')
    try:
        while True:
            if data.name != '::$DATA':
                raise ValueError('추가 데이터가 있는 파일 또는 폴더는 보존합니다.')
            if not next_stream(handle, ctypes.byref(data)):
                if ctypes.get_last_error() != 38:
                    raise ValueError('파일의 추가 데이터 유무를 확인하지 못해 보존합니다.')
                break
    finally:
        close(handle)


def _stat(path):
    path = safe_path(path)
    _no_streams(path)
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise ValueError('일반 결과 파일이 아니거나 다른 경로와 공유된 파일입니다.')
    return {'size':value.st_size, 'mtimeNs':value.st_mtime_ns, 'ctimeNs':value.st_ctime_ns,
            'device':value.st_dev, 'inode':value.st_ino}


def _hash(path):
    before = _stat(path)
    digest = hashlib.sha256()
    with safe_path(path).open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    if before != _stat(path):
        raise ValueError('결과 파일이 변경되는 중입니다. 이번 정리에서 제외했습니다.')
    return dict(before, sha256=digest.hexdigest())


def _engine(store, metadata):
    engine = metadata.get('engine')
    if engine in ENGINES:
        return engine if (engine == 'demo') == bool(store.demo) else None
    if metadata.get('demo') is True and store.demo:
        return 'demo'
    # Older receipts did not have engine/DB/query IDs. The already-used local
    # plan remains authoritative only when its query hash matches the receipt.
    plan_id, query_hash = metadata.get('planId'), metadata.get('queryHash')
    if store.demo or not isinstance(plan_id, str) or not ID.fullmatch(plan_id) or not query_hash:
        return None
    with store.connect() as conn:
        row = conn.execute('SELECT body FROM plans WHERE id=?', (plan_id,)).fetchone()
    if row is None:
        return None
    proposal = json.loads(row['body'])
    if proposal.get('queryHash') == query_hash and proposal.get('engine') in ENGINES - {'demo'}:
        return proposal['engine']
    return None


def _metadata(store, result_id):
    folder = _folder(store, result_id)
    path = folder / 'metadata.json'
    _stat(path)
    metadata = read_json(path, limit=2 * 1024 * 1024)
    if metadata.get('resultId') != result_id or metadata.get('status') not in {'complete', 'partial', 'failed'}:
        raise ValueError('확인할 수 없는 결과 기록은 보존합니다.')
    created = metadata.get('createdAt')
    approximate = created is None
    if approximate:
        created = path.stat().st_mtime
    created = _now(created)
    return folder, metadata, created, approximate


def _managed_files(folder, metadata):
    expected = {'metadata.json'}
    if metadata['status'] != 'failed':
        if safe_path(metadata.get('dataFile', '')) != folder / 'data.jsonl':
            raise ValueError('결과 원본의 저장 경로를 확인할 수 없습니다.')
        expected.add('data.jsonl')
    elif metadata.get('dataAvailable') is not False:
        raise ValueError('실패한 결과의 파일 상태를 확인할 수 없습니다.')
    exports = metadata.get('managedExports', [])
    if not isinstance(exports, list) or len(exports) > 100:
        raise ValueError('내보낸 파일 기록을 확인할 수 없습니다.')
    for item in exports:
        if (not isinstance(item, dict) or set(item) != {'path', 'sha256', 'bytes'} or
                not re.fullmatch(r'exports/[^/\\:]+\.csv', item.get('path', '')) or
                not re.fullmatch(r'[a-f0-9]{64}', item.get('sha256', '')) or
                type(item.get('bytes')) is not int or item['bytes'] < 0 or item['path'] in expected):
            raise ValueError('관리 대상으로 확인되지 않은 내보내기 파일은 보존합니다.')
        expected.add(item['path'])
    actual = set()
    for entry in folder.iterdir():
        entry = safe_path(entry)
        if entry.name == 'exports' and entry.is_dir() and exports:
            _no_streams(entry)
            for exported in entry.iterdir():
                _stat(exported)
                actual.add('exports/' + exported.name)
        else:
            _stat(entry)
            actual.add(entry.name)
    if actual != expected:
        raise ValueError('추가되거나 누락된 파일이 있는 결과는 보존합니다.')
    states = {name:_stat(folder / name) for name in expected}
    if 'data.jsonl' in states:
        if type(metadata.get('dataBytes')) is not int or metadata['dataBytes'] != states['data.jsonl']['size']:
            raise ValueError('원본 크기가 기록과 다른 결과는 보존합니다.')
        if not metadata.get('dataSha256') and states['data.jsonl']['mtimeNs'] > states['metadata.json']['mtimeNs']:
            raise ValueError('이전 원본 파일이 수정되어 보존합니다.')
    return states


def _count(value):
    return value if type(value) is int and value >= 0 else 0


def _scan(store, engine, *, now, current_result_id=None):
    if engine not in ENGINES or (engine == 'demo') != bool(store.demo):
        raise ValueError('이 저장소에 맞는 조회 스킬을 선택해 주세요.')
    if current_result_id is not None:
        _id(current_result_id)
    root = safe_path(store.root / 'results')
    records, unreadable = [], 0
    if not root.exists():
        return records, unreadable
    for path in root.iterdir():
        if not ID.fullmatch(path.name):
            continue
        try:
            folder, metadata, created, approximate = _metadata(store, path.name)
            if _engine(store, metadata) != engine:
                continue
            try:
                files = _managed_files(folder, metadata)
                eligible = now - created >= STALE_SECONDS
                reason = None if eligible else 'recent'
                total_bytes = sum(v['size'] for v in files.values())
            except (OSError, ValueError):
                eligible, reason, total_bytes = False, 'unverified_files', 0
            records.append({'resultId':path.name, 'label':str(metadata.get('label') or result_label(metadata.get('queryName', '조회'), metadata.get('sourceName', 'DB'), created, path.name))[:180],
                            'sourceName':str(metadata.get('sourceName', ''))[:80], 'queryName':str(metadata.get('queryName', ''))[:80],
                            'createdAt':created, 'timeApproximate':approximate, 'status':metadata['status'],
                            'savedRows':_count(metadata.get('savedRows')), 'dataBytes':_count(metadata.get('dataBytes')),
                            'totalBytes':total_bytes, 'current':False, 'cleanupEligible':eligible, 'retainedReason':reason})
        except (OSError, ValueError, TypeError, OverflowError, json.JSONDecodeError):
            unreadable += 1
    records.sort(key=lambda item: (item['createdAt'], item['resultId']), reverse=True)
    for item in records:
        if item['resultId'] == current_result_id:
            item.update(current=True, cleanupEligible=False, retainedReason='current_result')
    return records, unreadable


def list_results(store, engine, *, limit=10, current_result_id=None, now=None):
    return _listing(store, engine, limit=limit, current_result_id=current_result_id, now=now, stale_only=False)


def list_candidates(store, engine, *, limit=10, current_result_id=None, now=None):
    return _listing(store, engine, limit=limit, current_result_id=current_result_id, now=now, stale_only=True)


def _listing(store, engine, *, limit, current_result_id, now, stale_only):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('결과 목록은 한 번에 1~100개까지 확인할 수 있습니다.')
    records, unreadable = _scan(store, engine, now=_now(now), current_result_id=current_result_id)
    selected = [item for item in records if item['cleanupEligible']] if stale_only else records
    return {'ok':True, 'results':selected[:limit], 'count':len(selected), 'returnedCount':min(limit, len(selected)),
            'totalBytes':sum(item['totalBytes'] for item in selected), 'reviewLimited':len(selected) > limit,
            'unverifiedCount':unreadable, 'staleAfterHours':24, 'dataRowsReturned':0}


def _snapshot(store, result_id):
    folder, metadata, _, _ = _metadata(store, result_id)
    expected = _managed_files(folder, metadata)
    files = {name:_hash(folder / name) for name in sorted(expected)}
    if expected != {name:{k:v for k,v in state.items() if k != 'sha256'} for name,state in files.items()}:
        raise ValueError('정리 준비 중 파일이 바뀌었습니다. 다시 확인해 주세요.')
    original_hash = metadata.get('dataSha256')
    if original_hash and files.get('data.jsonl', {}).get('sha256') != original_hash:
        raise ValueError('조회 후 원본 내용이 바뀌어 보존합니다.')
    for item in metadata.get('managedExports', []):
        if files[item['path']]['sha256'] != item['sha256'] or files[item['path']]['size'] != item['bytes']:
            raise ValueError('내보낸 파일이 변경되어 보존합니다.')
    return {'resultId':result_id, 'files':files}


def prepare_cleanup(store, engine, result_ids, *, current_result_id=None, now=None):
    now = _now(now)
    if not isinstance(result_ids, (list, tuple)) or not 1 <= len(result_ids) <= 100:
        raise ValueError('삭제할 이전 결과 번호를 1~100개 명시해 주세요.')
    ids = [_id(value) for value in result_ids]
    if len(set(ids)) != len(ids):
        raise ValueError('중복된 결과 번호는 제외하고 준비해 주세요.')
    records, _ = _scan(store, engine, now=now, current_result_id=current_result_id)
    eligible = {item['resultId'] for item in records if item['cleanupEligible']}
    if not set(ids) <= eligible:
        raise ValueError('현재 결과, 24시간 이내 결과 또는 확인되지 않은 파일은 삭제 목록에 넣지 않습니다.')
    snapshots = [_snapshot(store, value) for value in ids]
    body = {'schemaVersion':1, 'engine':engine, 'rootHash':fingerprint(str(safe_path(store.root))),
            'createdAt':now, 'nonce':uuid.uuid4().hex, 'currentResultId':current_result_id, 'snapshots':snapshots}
    # The reviewed ID is content-bound, so editing the plan cannot silently
    # substitute additional result IDs while retaining the user's approval.
    plan_id = fingerprint(body)[:32]
    folder = safe_path(store.root / 'result-cleanup-plans')
    folder.mkdir(exist_ok=True)
    target = safe_path(folder / (plan_id + '.json'))
    with target.open('x', encoding='utf-8') as out:
        json.dump(body, out, ensure_ascii=False, indent=2)
    return {'ok':True, 'status':'cleanup_confirmation_required', 'cleanupPlanId':plan_id, 'planId':plan_id,
            'resultIds':ids, 'count':len(ids), 'totalBytes':sum(state['size'] for snap in snapshots for state in snap['files'].values()),
            'expiresAt':now + PLAN_SECONDS, 'dataRowsReturned':0,
            'message':'표시한 이전 결과만 삭제합니다. 사용자가 동의한 뒤 이 정리 번호로 한 번 실행하세요.'}


def delete_cleanup(store, engine, plan_id, *, confirmed=False, now=None):
    if not confirmed:
        raise ValueError('이전 결과 삭제에 대한 사용자 확인이 필요합니다.')
    now = _now(now)
    plan_id = _id(plan_id)
    folder = safe_path(store.root / 'result-cleanup-plans')
    body = read_json(folder / (plan_id + '.json'), limit=8 * 1024 * 1024)
    if (fingerprint(body)[:32] != plan_id or body.get('schemaVersion') != 1 or body.get('engine') != engine or
            body.get('rootHash') != fingerprint(str(safe_path(store.root))) or
            not 0 <= now - _now(body.get('createdAt')) <= PLAN_SECONDS):
        raise ValueError('정리 준비가 바뀌었거나 15분이 지났습니다. 목록을 다시 확인해 주세요.')
    snapshots = body.get('snapshots')
    if not isinstance(snapshots, list) or not 1 <= len(snapshots) <= 100:
        raise ValueError('정리 목록을 확인할 수 없습니다.')
    # Exclusive claim makes repeated clicks/retries harmless. An interrupted
    # cleanup requires a fresh review and a fresh content-bound plan.
    claim = safe_path(folder / (plan_id + '.used'))
    try:
        with claim.open('x', encoding='ascii') as out:
            out.write(str(now))
    except FileExistsError:
        raise ValueError('이미 사용한 정리 준비입니다. 남은 결과를 다시 확인해 주세요.') from None
    deleted, retained, freed = [], [], 0
    for snapshot in snapshots:
        result_id = _id(snapshot.get('resultId'))
        try:
            current, _ = _scan(store, engine, now=now, current_result_id=body.get('currentResultId'))
            if result_id not in {item['resultId'] for item in current if item['cleanupEligible']}:
                raise ValueError('현재 사용 중이거나 다시 확인이 필요한 결과입니다.')
            if _snapshot(store, result_id) != snapshot:
                raise ValueError('확인 후 파일이 변경되어 보존합니다.')
            result_folder = _folder(store, result_id)
            # Metadata is last. Never recurse into or remove newly introduced
            # directories/files; they remain available after a partial failure.
            paths = sorted(snapshot['files'], key=lambda name: (name == 'metadata.json', name))
            for relative in paths:
                target = safe_path(result_folder / relative)
                if not target.is_relative_to(result_folder) or _hash(target) != snapshot['files'][relative]:
                    raise ValueError('삭제 직전 파일이 변경되어 남은 파일을 보존합니다.')
                target.unlink()
                freed += snapshot['files'][relative]['size']
            exports = safe_path(result_folder / 'exports')
            if exports.exists():
                _no_streams(exports)
                exports.rmdir()
            _no_streams(result_folder)
            result_folder.rmdir()
            deleted.append(result_id)
        except (OSError, ValueError):
            retained.append({'resultId':result_id, 'reason':'changed_or_protected'})
    return {'ok':True, 'status':'partial' if retained else 'deleted', 'deletedIds':deleted,
            'retained':retained, 'deletedBytes':freed, 'dataRowsReturned':0}


def register_export(store, result_id, output):
    folder, metadata, created, _ = _metadata(store, result_id)
    output = safe_path(output)
    if output.parent != folder / 'exports' or output.suffix.lower() != '.csv':
        raise ValueError('결과 폴더의 exports 안에서만 관리 대상으로 기록합니다.')
    state = _hash(output)
    entries = metadata.get('managedExports', [])
    if not isinstance(entries, list) or len(entries) >= 100:
        raise ValueError('관리할 내보내기 파일 수를 초과했습니다.')
    relative = output.relative_to(folder).as_posix()
    if any(item.get('path') == relative for item in entries):
        raise ValueError('이미 기록된 내보내기 파일입니다.')
    metadata['managedExports'] = entries + [{'path':relative, 'sha256':state['sha256'], 'bytes':state['size']}]
    # Preserve a legacy receipt's original age when first adding export tracking.
    metadata.setdefault('createdAt', created)
    atomic_json(folder / 'metadata.json', metadata)
