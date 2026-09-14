"""Fixed Word/PowerPoint reads through installed Office, not file parsers."""
import importlib
import json
import os
import sys
from types import SimpleNamespace

from .excel_xlwings import denied, permission_status


class TextCollector:
    def __init__(self, limit):
        self.remaining = limit
        self.items = []
        self.truncated = False
        self.visited = 0

    def add(self, location, value):
        if self.full:
            self.truncated = True
            return
        self.visited += 1
        text = str(value or '').strip('\r\x07')
        if not text.strip():
            return
        take = min(len(text), self.remaining)
        self.items.append({'location': location, 'text': text[:take]})
        self.remaining -= take
        self.truncated |= take < len(text)

    @property
    def full(self):
        return self.remaining <= 0 or self.visited >= 2000


def _extract(document, request):
    output = TextCollector(request['maxChars'])
    word = request['kind'] == 'word'
    collection = document.Paragraphs if word else document.Slides
    total = collection.Count
    if request['start'] > total:
        return {'ok': False, 'code': 'invalid_request', 'stage': 'read'}
    last = min(request['end'], total)
    unsupported = 0
    for i in range(request['start'], last + 1):
        part = collection.Item(i)
        if word:
            output.add(f'paragraph:{i}', part.Range.Text)
        else:
            shapes = part.Shapes
            output.truncated |= shapes.Count > 200
            for j in range(1, min(shapes.Count, 200) + 1):
                shape = shapes.Item(j)
                if shape.HasTable:
                    table = shape.Table
                    rows, cols = table.Rows.Count, table.Columns.Count
                    output.truncated |= rows > 100 or cols > 20
                    for r in range(1, min(rows, 100) + 1):
                        for c in range(1, min(cols, 20) + 1):
                            output.add(f'slide:{i}/shape:{j}/R{r}C{c}',
                                       table.Cell(r, c).Shape.TextFrame.TextRange.Text)
                            if output.full: break
                        if output.full: break
                elif shape.HasTextFrame:
                    output.add(f'slide:{i}/shape:{j}', shape.TextFrame.TextRange.Text)
                else:
                    unsupported += 1
                if output.full:
                    output.truncated = True
                    break
        if output.full:
            output.truncated = True
            break
    return {'ok': True, 'items': output.items, 'truncated': output.truncated,
            'coverage': {'kind': 'main-story-paragraphs-only' if word else 'top-level-text-and-tables-only',
                         'start': request['start'], 'end': last, 'total': total,
                         'unsupportedShapes': unsupported, 'reader': 'pywin32'}}


def _read(request, client, com):
    app = document = None
    security = links = None
    initialized = False
    stage = 'application'
    word = request['kind'] == 'word'
    try:
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
        if word:
            links = app.Options.UpdateLinksAtOpen
            app.Options.UpdateLinksAtOpen = False
            document = documents.Open(request['file'], False, True, False)
        else:
            document = documents.Open(request['file'], -1, 0, 0)
        stage = 'permission'
        permission = permission_status(SimpleNamespace(api=document))
        if permission in ('restricted', 'denied'):
            return {'ok': False, 'code': 'protected_input', 'stage': stage}
        stage = 'read'
        result = _extract(document, request)
        if result['ok']:
            result['coverage'].update(officePermissionApi=permission,
                                      thirdPartyDrmAuthorization='not_determined')
        return result
    except Exception as exc:
        return {'ok': False, 'code': 'permission_denied' if denied(exc) else 'office_read_failed',
                'stage': stage}
    finally:
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
