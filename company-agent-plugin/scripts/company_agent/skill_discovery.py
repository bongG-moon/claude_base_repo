"""Bounded metadata-only selection index. No model call or keyword routing."""
from __future__ import annotations

import json
from pathlib import Path

from .paths import atomic_write_text
from .skill_registry import _no_reparse, _resolution

MAX_INDEX_CHARS = 6000
COLUMNS = ['name', 'source', 'description', 'priority', 'root', 'file', 'invocation', 'explicitOnly']


def _encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _rows(entries, preferences):
    groups = {}
    for item in entries:
        groups.setdefault(item['name'].casefold(), []).append(item)
    decisions = {name: _resolution(name, items, preferences) for name, items in groups.items()}
    roots, rows = [], []
    for item in entries:
        file = Path(item['path'])
        root = str(file.parent.parent)
        if root not in roots:
            roots.append(root)
        decision = decisions[item['name'].casefold()]
        status = decision['status']
        if status == 'selected':
            status = 'preferred' if decision.get('selectedId') == item['id'] else 'other-preferred'
        rows.append([item['name'], item['source'], item['description'] or '설명 없음: 본문 확인 필요',
                     status, roots.index(root), file.relative_to(Path(root)).as_posix(),
                     item['invocation'], bool(item.get('explicitOnly'))])
    return {'columns': COLUMNS, 'roots': roots, 'skills': rows}


def _write(file, value):
    _no_reparse(file)
    content = _encode(value)
    if not file.exists() or file.read_text(encoding='utf-8') != content:
        atomic_write_text(file, content)


def build_index(entries, preferences, revision, directory):
    """Keep complete descriptions. Large inventories expose every source/page."""
    common = {'revision': revision, 'count': len(entries)}
    full = {**common, 'mode': 'inline', **_rows(entries, preferences)}
    if len(_encode(full)) <= MAX_INDEX_CHARS:
        return full
    base = directory / 'pages' / revision[:16]
    sources = []
    for source in sorted({item['source'] for item in entries}):
        items = [item for item in entries if item['source'] == source]
        chunks, chunk = [], []
        for item in items:
            # Use global resolution below: a source page must not erase a
            # conflicting same-name candidate from another source.
            if chunk and len(_encode(_rows(chunk + [item], preferences))) > 4500:
                chunks.append(chunk)
                chunk = []
            chunk.append(item)
        if chunk:
            chunks.append(chunk)
        pages = []
        all_rows = _rows(entries, preferences)
        by_path = {str(Path(all_rows['roots'][row[4]]) / row[5]): row for row in all_rows['skills']}
        for number, chunk in enumerate(chunks, 1):
            rows = _rows(chunk, preferences)
            for row, item in zip(rows['skills'], chunk):
                row[3] = by_path[str(Path(item['path']))][3]
            filename = f'{source}-{number}.json'
            _write(base / filename, {**common, 'mode': 'page', **rows})
            pages.append({'file': filename, 'count': len(chunk), 'names': [x['name'] for x in chunk]})
        filename = f'{source}.json'
        _write(base / filename, {'revision': revision, 'source': source, 'pages': pages})
        sources.append({'source': source, 'count': len(items), 'file': filename,
                        'names': [item['name'] for item in items]})
    result = {**common, 'mode': 'pages', 'directory': str(base), 'sources': sources}
    if len(_encode(result)) > MAX_INDEX_CHARS:
        # Entire name lists move to their directories; never expose a top-N
        # prefix that could look like the complete set of available skills.
        for source in sources:
            source.pop('names')
        result['namesInDirectories'] = True
    if len(_encode(result)) > MAX_INDEX_CHARS:
        raise ValueError('Skill index paths exceed budget')
    return result


def for_context(index, root, session_id, *, force=False):
    if not session_id or force:
        return index
    from .state import load_session
    route = load_session(session_id, root).get('skillWorkflow', {})
    if not isinstance(route, dict):
        return index
    delivered = route.get('indexDelivery', {})
    if not isinstance(delivered, dict):
        return index
    if delivered.get('revision') == index['revision'] and delivered.get('mode') == index['mode']:
        return {'mode': 'reuse', 'revision': index['revision'], 'count': index['count'],
                'previousMode': index['mode']}
    return index


def record_delivery(index, root, session_id):
    if not session_id or index.get('mode') not in {'inline', 'pages'}:
        return
    from .state import _locked_session
    from .paths import atomic_write_json
    with _locked_session(session_id, root) as (state, path):
        route = state.get('skillWorkflow', {})
        if route.get('revision') != index['revision']:
            return
        route['indexDelivery'] = {'revision': index['revision'], 'mode': index['mode'],
                                  'evidence': 'output-produced-not-host-acknowledged'}
        # Legacy field names retained for compatibility. Output generation is
        # NOT host receipt, model application, or a Read/Skill load receipt.
        route['indexDelivered'] = index['mode'] == 'inline'
        atomic_write_json(path, state)
