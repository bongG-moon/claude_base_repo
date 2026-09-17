"""Fixed Word/PowerPoint reads through installed Office, not file parsers."""
import importlib
import json
import os
import sys
import time
from types import SimpleNamespace

from .excel_xlwings import denied, permission_status


from .office_structure import TextCollector, extract_document as _extract
from .office_progress import helper_stage


def _read(request, client, com):
    app = document = None
    security = links = None
    initialized = False
    stage = 'application'
    clock = time.perf_counter()
    timings = {}
    word = request['kind'] == 'word'
    try:
        helper_stage('application')
        com.CoInitialize()
        initialized = True
        app = client.DispatchEx('Word.Application' if word else 'PowerPoint.Application')
        documents = app.Documents if word else app.Presentations
        # DispatchEx does not establish exclusive ownership of every Office app.
        # Never close a source that the user already had open.
        for i in range(1, documents.Count + 1):
            if os.path.normcase(documents.Item(i).FullName) == os.path.normcase(request['file']):
                return {'ok': False, 'code': 'document_open', 'stage': stage}
        security = app.AutomationSecurity
        app.AutomationSecurity = 3
        stage = 'open'
        helper_stage(stage)
        if word:
            links = app.Options.UpdateLinksAtOpen
            app.Options.UpdateLinksAtOpen = False
            document = documents.Open(request['file'], False, True, False)
        else:
            document = documents.Open(request['file'], -1, 0, 0)
        stage = 'permission'
        helper_stage(stage)
        timings['openMs'] = round((time.perf_counter() - clock) * 1000)
        actual = getattr(document, 'FullName', None)
        if isinstance(actual, str) and os.path.normcase(os.path.abspath(actual)) != os.path.normcase(os.path.abspath(request['file'])):
            return {'ok': False, 'code': 'source_mismatch', 'stage': 'open'}
        permission = permission_status(SimpleNamespace(api=document))
        if permission in ('restricted', 'denied'):
            return {'ok': False, 'code': 'protected_input', 'stage': stage}
        stage = 'read'
        helper_stage(stage)
        result = _extract(document, request)
        if result['ok']:
            result['coverage'].update(officePermissionApi=permission,
                                      thirdPartyDrmAuthorization='not_determined')
            result['diagnostics'] = {'sourcePath': request['file'], 'openedPath': actual if isinstance(actual, str) else None,
                                     'openMode': 'read-only, no window', 'python': sys.executable,
                                     'officeVersion': str(app.Version) if isinstance(app.Version, str) else None,
                                     'timingMs': {**timings, 'throughRead': round((time.perf_counter()-clock)*1000)}}
        return result
    except Exception as exc:
        return {'ok': False, 'code': 'permission_denied' if denied(exc) else 'office_read_failed',
                'stage': stage, 'errorType': type(exc).__name__}
    finally:
        helper_stage('close')
        if document is not None:
            try:
                if word:
                    document.Close(0)
                else:
                    document.Saved = -1  # discard any dirty flag; never Save/SaveAs
                    document.Close()
            except Exception:
                pass
        if app is not None:
            if links is not None:
                try: app.Options.UpdateLinksAtOpen = links
                except Exception: pass
            if security is not None:
                try: app.AutomationSecurity = security
                except Exception: pass
            # Never Quit/kill a potentially shared Word/PowerPoint process.
        document = app = None
        if initialized:
            com.CoUninitialize()


def read_document(request):
    from .office_reader import normalize
    from .business_safety import blocked_input
    if not isinstance(request, dict): return {'ok': False, 'code': 'invalid_request'}
    if blocked_input(request): return {'ok': False, 'code': 'protected_input'}
    try:
        request = normalize({k: v for k, v in request.items() if k != 'kind'})
        if request['kind'] not in ('word', 'powerpoint'): raise ValueError('not Word/PPT')
    except (ValueError, TypeError, OSError):
        return {'ok': False, 'code': 'invalid_request'}
    try:
        helper_stage('dependencies')
        client = importlib.import_module('win32com.client')
        com = importlib.import_module('pythoncom')
    except ImportError:
        return {'ok': False, 'code': 'office_dependencies_missing', 'stage': 'dependencies'}
    return _read(request, client, com)


def main():
    try:
        raw = sys.stdin.buffer.read(32769)
        if len(raw) > 32768: raise ValueError('request too large')
        result = read_document(json.loads(raw.decode('utf-8-sig')))
    except (ValueError, TypeError, OSError):
        result = {'ok': False, 'code': 'invalid_request'}
    print(json.dumps(result, ensure_ascii=True))
    return 0
