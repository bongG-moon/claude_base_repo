"""Bounded Office structure extraction; uses existing COM objects, never opens files."""
import math


def optional(call):
    """Ignore unsupported layout APIs, never swallow an access denial."""
    try:
        return call()
    except Exception as exc:
        codes = [getattr(exc, 'hresult', None), getattr(exc, 'winerror', None)]
        info = getattr(exc, 'excepinfo', None)
        if isinstance(info, tuple) and len(info) > 5:
            codes.append(info[5])
        if isinstance(exc, PermissionError) or any(c in (5, -2147024891, 2147942405) for c in codes):
            raise
        return None


def number(value):
    return round(value, 2) if type(value) in (int, float) and math.isfinite(value) else None


def bounds(shape):
    values = [number(optional(lambda p=p: getattr(shape, p))) for p in ('Left', 'Top', 'Width', 'Height')]
    return {'left': values[0], 'top': values[1], 'width': values[2], 'height': values[3], 'unit': 'pt'}


class TextCollector:
    def __init__(self, limit):
        self.remaining = limit
        self.items = []
        self.truncated = False
        self.visited = 0

    @property
    def full(self):
        return self.remaining <= 0 or self.visited >= 2000

    def add(self, location, value, structure=None):
        if self.full:
            self.truncated = True
            return
        self.visited += 1
        text = str(value if value is not None else '').strip('\r\x07')
        # Sparse cells preserve their row/column addresses; never shift columns.
        if not text.strip():
            return
        take = min(len(text), self.remaining)
        item = {'location': location, 'text': text[:take]}
        if structure:
            item['structure'] = structure
        self.items.append(item)
        self.remaining -= take
        self.truncated |= take < len(text)


def extract_document(document, request):
    output = TextCollector(request['maxChars'])
    word = request['kind'] == 'word'
    collection = document.Paragraphs if word else document.Slides
    total = collection.Count
    start = request['start']
    if start > total:
        return {'ok': False, 'code': 'invalid_request', 'stage': 'read'}
    last = min(request['end'], total)
    unsupported = 0
    shape_visits = 0
    last_read = start - 1
    complete_through = start - 1

    def visit(shape, location, slide, depth=0):
        nonlocal unsupported, shape_visits
        if output.full or shape_visits >= 2000 or depth > 8:
            output.truncated = True
            return
        shape_visits += 1
        meta = {'slide': slide, 'bounds': bounds(shape)}
        if optional(lambda: shape.Type) == 6:  # msoGroup
            children = shape.GroupItems
            output.truncated |= children.Count > 200
            for child in range(1, min(children.Count, 200) + 1):
                visit(children.Item(child), f'{location}/group:{child}', slide, depth + 1)
                if output.full or shape_visits >= 2000:
                    break
        elif shape.HasTable:
            table = shape.Table
            rows, cols = table.Rows.Count, table.Columns.Count
            output.truncated |= rows > 100 or cols > 20
            for row in range(1, min(rows, 100) + 1):
                for col in range(1, min(cols, 20) + 1):
                    cell = table.Cell(row, col).Shape
                    output.add(f'{location}/R{row}C{col}', cell.TextFrame.TextRange.Text,
                               {**meta, 'type': 'table-cell', 'table': location,
                                'row': row, 'column': col, 'rows': rows, 'columns': cols})
                    if output.full:
                        return
        elif shape.HasTextFrame:
            output.add(location, shape.TextFrame.TextRange.Text, {**meta, 'type': 'text'})
        else:
            unsupported += 1

    for i in range(start, last + 1):
        part = collection.Item(i)
        last_read = i
        was_truncated = output.truncated
        if word:
            area = part.Range
            meta = {'type': 'paragraph', 'paragraph': i}
            position = optional(lambda: area.Start)
            if type(position) is int:
                meta['characterStart'] = position
            page = optional(lambda: area.Information(3))  # wdActiveEndPageNumber
            if type(page) is int and page > 0:
                meta['page'] = page
            level = optional(lambda: part.OutlineLevel)
            if type(level) is int and 1 <= level <= 9:
                meta['headingLevel'] = level
            in_table = optional(lambda: area.Information(12))  # wdWithInTable
            cell_count = optional(lambda: area.Cells.Count) if in_table is True or in_table == -1 else 0
            if type(cell_count) is int and cell_count > 0:
                cell = area.Cells.Item(1)
                meta.update(type='table-cell', row=int(cell.RowIndex), column=int(cell.ColumnIndex),
                            table=f'table-at:{cell.Range.Tables.Item(1).Range.Start}')
            output.add(f'paragraph:{i}', area.Text, meta)
        else:
            shapes = part.Shapes
            output.truncated |= shapes.Count > 200
            for j in range(1, min(shapes.Count, 200) + 1):
                visit(shapes.Item(j), f'slide:{i}/shape:{j}', i)
                if output.full or shape_visits >= 2000:
                    break
        if output.full or shape_visits >= 2000 or (output.truncated and not was_truncated):
            output.truncated = True
            break  # never jump over an incompletely read unit
        complete_through = i

    limited = output.truncated
    output.truncated |= last_read < total
    coverage = {'kind': 'paragraphs-with-table-coordinates' if word else 'text-tables-and-groups-with-bounds',
                'unit': 'paragraph' if word else 'slide', 'start': start, 'end': last_read,
                'total': total, 'completeThrough': complete_through,
                'nextStart': (last_read if limited else last_read + 1) if output.truncated else None,
                'limitReached': limited, 'unsupportedShapes': unsupported, 'reader': 'pywin32',
                'countMeaning': 'Office-reported count; not proof of DRM blocking',
                'excluded': ['headers', 'footers', 'floating-shapes', 'comments'] if word else
                            ['image-text', 'SmartArt', 'chart-data', 'notes'],
                'layoutMeaning': 'logical table/paragraph coordinates' if word else
                                 'Office-reported bounds in points; not rendered-image analysis'}
    if not word:
        coverage['slideSize'] = {
            'width': number(optional(lambda: document.PageSetup.SlideWidth)),
            'height': number(optional(lambda: document.PageSetup.SlideHeight)), 'unit': 'pt'}
    return {'ok': True, 'items': output.items, 'truncated': output.truncated, 'coverage': coverage}
