"""Remove only unchanged, individually registered artifact intermediates.

This is not a filesystem sweep. Registration happens only in the build that
created a new attempt; old workspaces and unknown files never acquire ownership.
All functions run under artifact_delivery's work lock. No model/service calls.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path, PurePosixPath
import re
import stat

from .business_safety import safe_path

MAX_FILES = 256
_HASH = re.compile(r'[a-f0-9]{64}')
_FILE = re.compile(r'attempts/[a-f0-9]{32}/(?:draft\.html|result\.(?:html|pptx)|review/slide-[0-9]+\.png)')
_STATES = ('device', 'inode', 'size', 'mtimeNs')


def _state(info):
    return dict(zip(_STATES, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)))


def _regular(info):
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_ino != 0
            and not getattr(info, 'st_file_attributes', 0) & 0x400)


def register(work, data, attempt, output, result):
    """Capture only explicit paths returned by this successful new build."""
    if data['schema'] != 2 or not result.get('ok'):
        return
    records = data.get('ownedFiles')
    if not valid_registry(records):
        return  # Never repair or infer ownership from an old/malformed record.
    declared = [(output, 'draft' if output.name == 'draft.html' else 'candidate')]
    previews = result.get('previews', [])
    if isinstance(previews, list):
        declared.extend((Path(p), 'review') for p in previews if isinstance(p, str))
    known = {r['path'] for r in records}
    for path, role in declared:
        if len(records) >= MAX_FILES:
            break
        try:
            path = safe_path(path, exists=True)
            relative = path.relative_to(work.parent).as_posix()
            if (not path.is_relative_to(attempt) or not _FILE.fullmatch(relative)
                    or relative in known):
                continue
            before = path.lstat()
            if not _regular(before):
                continue
            with path.open('rb') as stream:
                opened = os.fstat(stream.fileno())
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                after = os.fstat(stream.fileno())
            if _state(before) != _state(opened) or _state(before) != _state(after):
                continue
            if _state(path.lstat()) != _state(before):
                continue
            records.append({'path':relative, 'role':role, 'sha256':digest,
                            'state':_state(before)})
            known.add(relative)
        except (OSError, ValueError):
            # Failure to prove ownership keeps that file outside cleanup scope.
            continue


def valid_registry(records):
    if not isinstance(records, list) or len(records) > MAX_FILES:
        return False
    seen = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {'path','role','sha256','state'}:
            return False
        path, digest, snapshot = record['path'], record['sha256'], record['state']
        if (not isinstance(path, str) or not _FILE.fullmatch(path)
                or path in seen or not isinstance(digest, str) or not _HASH.fullmatch(digest)
                or not isinstance(snapshot, dict) or set(snapshot) != set(_STATES)
                or any(type(snapshot[k]) is not int or snapshot[k] < 0 for k in _STATES)
                or snapshot['inode'] == 0):
            return False
        name = PurePosixPath(path).name
        expected = 'draft' if name == 'draft.html' else 'review' if '/review/' in path else 'candidate'
        if record['role'] != expected:
            return False
        seen.add(path)
    return True


class _References(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.uncertain = False
        self.script = None
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.script = [] if dict(attrs).get('type', '').lower() != 'application/json' else None
        if tag == 'meta' and dict(attrs).get('http-equiv', '').lower() == 'refresh':
            self.uncertain = True
        for name, value in attrs:
            if name in ('src', 'href', 'poster', 'data', 'background', 'xlink:href', 'action'):
                value = (value or '').strip().lower()
                if value and not value.startswith(('#', 'data:', 'https:', 'http:', 'mailto:', 'tel:')):
                    self.uncertain = True
            if name in ('srcset', 'srcdoc') and value:
                self.uncertain = True

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            self.scripts.append(''.join(self.script).strip())
            self.script = None


def _html_dependencies_uncertain(output, text):
    """Retain all registered files if a local dependency cannot be ruled out.

    Dependencies can be indirect (CSS imports or scripts), so a partial URL
    parser must never claim that deleting an apparently unused asset is safe.
    Built-in generated HTML embeds its data; static references are still checked.
    """
    if output.suffix.lower() != '.html':
        return False
    try:
        parser = _References()
        parser.feed(text)
        parser.close()
        if parser.uncertain:
            return True
        from .business_artifacts import _JS
        if parser.script is not None or any(code not in ('', _JS.strip()) for code in parser.scripts):
            return True
        # CSS URLs, imports, and dynamic resource access are conservatively kept.
        for match in re.finditer(r'url\(\s*([\s\S]*?)\s*\)', text, re.I):
            value = match[1].strip(' \t\r\n\'"').lower()
            if not value.startswith(('#', 'data:', 'https:', 'http:')):
                return True
        return bool(re.search(r'@import|\b(?:fetch|XMLHttpRequest|importScripts|Worker)\s*\(|'
                              r'\bimport\b\s*(?:\(|[\w*{])|\.\s*(?:src|href)\s*=|'
                              r'setAttribute\s*\(\s*[\'"](?:src|href)', text, re.I))
    except (UnicodeError, ValueError):
        return True


@contextmanager
def _windows_handle(path, access, share, flags):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    handle = create(str(path), access, share, None, 3, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield handle, kernel
    finally:
        close(handle)


@contextmanager
def _windows_stream(handle, kernel):
    """Give Python only a duplicated handle; the caller keeps the original pin."""
    import ctypes
    from ctypes import wintypes
    import msvcrt
    duplicate = kernel.DuplicateHandle
    duplicate.argtypes = (wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                          ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    duplicate.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    process = kernel.GetCurrentProcess()
    copied = wintypes.HANDLE()
    if not duplicate(process, handle, process, ctypes.byref(copied), 0, False, 2):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(copied.value, os.O_RDONLY | os.O_BINARY)
    except Exception:
        kernel.CloseHandle(copied)
        raise
    with os.fdopen(fd, 'rb') as stream:
        yield stream


@contextmanager
def _verified_final(output, receipt):
    """Keep the verified final and its dependencies stable for the entire pass."""
    with ExitStack() as stack:
        for parent in reversed(output.parents):
            stack.enter_context(_windows_handle(parent, 0, 3, 0x02200000))
        safe_path(output, exists=True)
        handle, kernel = stack.enter_context(_windows_handle(output, 0x80000000, 1, 0x00200000))
        with _windows_stream(handle, kernel) as stream:
            info = os.fstat(stream.fileno())
            if not _regular(info) or info.st_size > 40 * 1024 * 1024:
                raise ValueError('Final file identity cannot be verified safely.')
            if hashlib.file_digest(stream, 'sha256').hexdigest() != receipt['sha256']:
                raise ValueError('Final file changed before cleanup acquired its handle.')
            text = ''
            if output.suffix.lower() == '.html':
                stream.seek(0)
                text = stream.read().decode('utf-8')
            dependencies = _html_dependencies_uncertain(output, text)
        yield dependencies


def _remove_windows(path, record):
    """Hash and delete the same handle, denying writers/deleters while checked.

    Pin ancestors against rename/replacement. Never clear read-only flags, change
    permissions, follow a reparse point, or force removal of an in-use file.
    """
    import ctypes
    from ctypes import wintypes
    with ExitStack() as stack:
        for parent in reversed(path.parents):
            stack.enter_context(_windows_handle(parent, 0, 3, 0x02200000))
        safe_path(path, exists=True)
        handle, kernel = stack.enter_context(_windows_handle(path, 0x80010000, 1, 0x00200000))
        with _windows_stream(handle, kernel) as stream:
            info = os.fstat(stream.fileno())
            if not _regular(info):
                return 'linked_or_unverified'
            if _state(info) != record['state']:
                return 'changed'
            if hashlib.file_digest(stream, 'sha256').hexdigest() != record['sha256']:
                return 'changed'
            if _state(os.fstat(stream.fileno())) != record['state']:
                return 'changed'
        class Disposition(ctypes.Structure):
            _fields_ = [('DeleteFile', ctypes.c_ubyte)]
        disposition = Disposition(True)
        remove = kernel.SetFileInformationByHandle
        remove.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
        remove.restype = wintypes.BOOL
        if not remove(handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
            raise ctypes.WinError(ctypes.get_last_error())
    return 'deleted'


def _remove_registered(path, record):
    try:
        safe_path(path)
        info = path.lstat()
    except FileNotFoundError:
        return 'missing'
    except ValueError:
        return 'linked_or_unverified'
    if not _regular(info):
        return 'linked_or_unverified'
    if _state(info) != record['state']:
        return 'changed'
    if os.name == 'nt':
        return _remove_windows(path, record)
    # This harness targets Windows. Without its checked-handle deletion
    # primitive, preserve the file rather than use a hash-then-unlink race.
    return 'unsupported_platform'


def _result(status, count=0, **counts):
    result = {'status':status, 'scope':'registered_intermediates_only',
              'registeredCount':count, 'deletedCount':0, 'missingCount':0,
              'retainedCount':0, 'failedCount':0, 'reasons':{}}
    result.update(counts)
    result['message'] = (f"등록된 임시 파일 {result['deletedCount']}개 정리, "
                         f"{result['retainedCount']}개 보존, {result['failedCount']}개 정리 보류"
                         f" (이미 없음 {result['missingCount']}개).")
    if status == 'legacy_retained':
        result['message'] = '이전 작업은 생성 파일 기록이 없어 임시 파일을 보존했습니다.'
    elif status == 'invalid_registry':
        result['message'] = '생성 파일 기록을 확인할 수 없어 임시 파일을 모두 보존했습니다.'
    return result


def run(work, data):
    """Caller has verified publication and holds the work lock."""
    if data['schema'] != 2:
        return _result('legacy_retained')
    records = data.get('ownedFiles')
    if not valid_registry(records):
        return _result('invalid_registry')
    if os.name != 'nt':
        return _result('partial', len(records), retainedCount=len(records),
                       reasons={'unsupported_platform':len(records)})
    with ExitStack() as stack:
        try:
            output = safe_path(data['output'], exists=True)
            dependencies = stack.enter_context(_verified_final(output, data['published']))
        except Exception:
            result = _result('final_unavailable', len(records), retainedCount=len(records),
                             reasons={'final_unavailable':len(records)})
            result['message'] = '최종 파일이 사용 중이거나 변경되어 등록된 임시 파일을 보존했습니다. 다시 제작할 필요는 없습니다.'
            return result
        return _clean_registered(work, records, output, dependencies)


def _clean_registered(work, records, output, dependencies):
    result = _result('completed', len(records))
    for record in records:
        try:
            # Lexical confinement is validated independently of resolution.
            path = work.parent.joinpath(*PurePosixPath(record['path']).parts)
            try:
                safe_path(path)
            except ValueError:
                result['retainedCount'] += 1
                result['reasons']['linked_or_unverified'] = result['reasons'].get('linked_or_unverified', 0) + 1
                continue
            path.lstat()  # Count already-missing paths accurately even for HTML dependencies.
            if path == output:
                reason = 'final_output'
            elif dependencies:
                reason = 'final_dependencies'
            else:
                reason = _remove_registered(path, record)
            category = 'deletedCount' if reason == 'deleted' else 'missingCount' if reason == 'missing' else 'retainedCount'
            result[category] += 1
            if category == 'retainedCount':
                result['reasons'][reason] = result['reasons'].get(reason, 0) + 1
        except FileNotFoundError:
            result['missingCount'] += 1
        except Exception:
            result['failedCount'] += 1
            result['reasons']['unavailable'] = result['reasons'].get('unavailable', 0) + 1
    status = 'partial' if result['retainedCount'] or result['failedCount'] else 'completed' if result['deletedCount'] else 'nothing_to_clean'
    return _result(status, **{k:v for k,v in result.items() if k not in ('status','message')})


def after_publish(work, data):
    """Cleanup is best-effort and can never turn a delivered result into failure."""
    try:
        return run(work, data)
    except Exception:
        result = _result('unavailable')
        result['message'] = '최종 파일은 전달했습니다. 임시 파일 정리는 보류했으며 다시 제작할 필요는 없습니다.'
        return result
