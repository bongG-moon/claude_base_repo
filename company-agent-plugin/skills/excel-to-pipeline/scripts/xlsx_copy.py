"""필요한 셀과 선행 수식을 새 XLSX에 보존합니다. 원본 저장/복호화는 하지 않습니다."""
from __future__ import annotations

import datetime as dt
import os
import re
from collections import Counter, deque
from pathlib import Path

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.styles import Font, PatternFill
from openpyxl.styles.numbers import is_timedelta_format
from openpyxl.utils import FORMULAE, get_column_letter, range_boundaries
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.workbook.properties import CalcProperties


class CopySelectionError(ValueError):
    pass


# 이 함수들은 문자열이나 위치 계산으로 참조가 달라지므로 정적 셀 목록만으로 축소하지 않습니다.
DYNAMIC = {"INDIRECT", "OFFSET", "EVALUATE", "GET.CELL", "CALL", "REGISTER.ID"}
METADATA_DEPENDENT = {"SUBTOTAL", "AGGREGATE", "GETPIVOTDATA", "CELL", "INFO"}
BUILTINS = FORMULAE | {"XLOOKUP", "XMATCH", "FILTER", "UNIQUE", "SORT", "SORTBY", "LET", "IFS", "SWITCH", "TEXTJOIN", "CONCAT"}
RECTANGLE = re.compile(r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]*(?::\$?[A-Za-z]{1,3}\$?[1-9][0-9]*)?\Z")
AXIS_RANGE = re.compile(r"(?:\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}|\$?[1-9][0-9]*:\$?[1-9][0-9]*)\Z")


def _split_ref(text, current_sheet):
    if "!" not in text:
        return current_sheet, text
    sheet, reference = text.rsplit("!", 1)
    if sheet.startswith("'") and sheet.endswith("'"):
        sheet = sheet[1:-1].replace("''", "'")
    return sheet, reference


def _inside(address, bounds):
    col, row, _, _ = range_boundaries(address)
    left, top, right, bottom = bounds
    return (left or 1) <= col <= (right or 16384) and (top or 1) <= row <= (bottom or 1048576)


def prepare_copy(result, targets=None):
    """선택 범위에서 역방향으로 원천 셀을 모읍니다. 계산 성공 여부와 참조 추적은 별개입니다."""
    targets = list(dict.fromkeys(targets or []))
    records = {(c['sheet'], c['cell']): c for c in result['source_cells']}
    sheet_names = [s['name'] for s in result['sheets']]
    sheets = {s.casefold(): s for s in sheet_names}
    by_sheet = {s: [] for s in sheet_names}
    for key in records:
        by_sheet[key[0]].append(key)
    names = {(n.get('sheet'), n['name'].casefold()): n for n in result['workbook_structure'].get('names', [])}
    used_names, visited_names, keep, warnings = {}, set(), set(), Counter()
    referenced_sheets = set()
    warning_examples = []
    queue = deque()
    range_cache = {}

    def warn(kind, sheet, reference):
        warnings[kind] += 1
        if len(warning_examples) < 12:
            warning_examples.append({'kind': kind, 'sheet': sheet, 'reference': reference})

    def include(key):
        if key not in keep:
            keep.add(key)
            queue.append(key)

    def range_keys(sheet, reference):
        cache_key = sheet, reference
        if cache_key not in range_cache:
            address = reference.replace('$', '').upper()
            if ':' not in address:
                range_cache[cache_key] = [(sheet, address)] if (sheet, address) in records else []
                return range_cache[cache_key]
            bounds = range_boundaries(reference.replace('$', ''))
            left, top, right, bottom = bounds
            if (left or 1) > (right or 16384) or (top or 1) > (bottom or 1048576) or (right or 0) > 16384 or (bottom or 0) > 1048576:
                raise CopySelectionError('XLSX 사본의 참조 범위가 올바르지 않습니다: ' + reference)
            range_cache[cache_key] = [key for key in by_sheet[sheet] if _inside(key[1], bounds)]
        return range_cache[cache_key]

    def reference(text, sheet, is_target=False, depth=0):
        if depth > 40:
            raise CopySelectionError('이름 범위 참조가 너무 깊어 필요한 셀을 확정하지 못했습니다.')
        scope, address = _split_ref(text, sheet)
        if '#REF!' in text.upper():
            warn('broken_reference', sheet, text)
            return
        if '[' in scope or ']' in scope:
            if is_target:
                raise CopySelectionError('외부 파일을 XLSX 사본의 결과 범위로 지정할 수 없습니다.')
            warn('external_reference_not_resolved', sheet, text)
            return
        canonical = sheets.get(scope.casefold())
        if canonical is None:
            if is_target or ':' in scope:
                raise CopySelectionError('찾을 수 없거나 지원하지 않는 시트 범위입니다: ' + scope)
            warn('missing_sheet', sheet, text)
            return
        referenced_sheets.add(canonical)
        if RECTANGLE.fullmatch(address) or AXIS_RANGE.fullmatch(address):
            for key in range_keys(canonical, address):
                include(key)
            return
        if '[' in address or ']' in address or address.endswith('#') or address.startswith('@'):
            raise CopySelectionError('구조화/동적 참조를 확정하지 못해 사본을 축소하지 않았습니다: ' + text)
        key = (canonical, address.casefold()) if (canonical, address.casefold()) in names else (None, address.casefold())
        item = names.get(key)
        if not item:
            raise CopySelectionError('이름 또는 셀 참조를 확정하지 못해 사본을 만들지 않았습니다: ' + text)
        used_names[key] = item
        visit_key = key, canonical
        if visit_key not in visited_names:
            visited_names.add(visit_key)
            formula(item.get('text') or '', canonical, depth + 1)

    def formula(expression, sheet, depth=0):
        expression = expression if expression.startswith('=') else '=' + expression
        try:
            tokens = Tokenizer(expression).items
        except (TokenizerError, IndexError) as error:
            raise CopySelectionError('수식을 해석하지 못해 필요한 셀을 확정하지 못했습니다: ' + sheet) from error
        for token in tokens:
            if token.type == 'FUNC' and token.subtype == 'OPEN':
                name = token.value[:-1].upper().replace('_XLFN.', '').replace('_XLWS.', '')
                if name in METADATA_DEPENDENT or name.startswith('CUBE'):
                    raise CopySelectionError('필터/숨김/피벗 등 셀 이외 상태가 필요한 함수는 선택 사본에서 재현하지 않습니다: ' + name)
                if name in DYNAMIC or name not in BUILTINS:
                    raise CopySelectionError('동적 참조 또는 사용자 함수의 입력을 확정하지 못했습니다: ' + name)
            elif token.type == 'OPERAND' and token.subtype == 'RANGE':
                reference(token.value, sheet, depth=depth)
            elif token.type == 'OPERAND' and token.subtype == 'ERROR':
                warn('formula_error_token', sheet, token.value)

    if targets:
        tables = {t['id']: t for t in result['tables']}
        for target in targets:
            if target in tables:
                t = tables[target]
                reference(t['range'], t['sheet'], True)
            else:
                if '!' not in target:
                    raise CopySelectionError('사본 범위는 표 ID 또는 시트!A1:D20으로 지정하세요.')
                reference(target, sheet_names[0], True)
        while queue:
            key = queue.popleft()
            cell = records[key]
            if cell.get('formula'):
                formula(cell['formula'], key[0])
    else:
        # 결과가 지정되지 않았다면 값/수식이 있는 셀만 유지합니다. 업무상 불필요한 데이터라고 추정해 삭제하지 않습니다.
        keep = set(records)
        used_names = names.copy()
        referenced_sheets.update(sheet_names)
        for key in keep:
            expression = records[key].get('formula') or ''
            if '#REF!' in expression.upper():
                warn('broken_reference', key[0], key[1])
            if re.search(r'\[[^\]]+\][^!]*!', expression):
                warn('external_reference_not_resolved', key[0], key[1])
            if re.search(r'\b(?:SUBTOTAL|AGGREGATE|GETPIVOTDATA|CUBE\w*|CELL|INFO)\s*\(', expression, re.I):
                warn('metadata_dependent_formula_not_reproduced', key[0], key[1])
            if expression:
                try:
                    tokens = Tokenizer(expression).items
                    for token in tokens:
                        if token.type == 'FUNC' and token.subtype == 'OPEN':
                            name = token.value[:-1].upper().replace('_XLFN.', '').replace('_XLWS.', '')
                            if name in DYNAMIC or name not in BUILTINS:
                                warn('dynamic_or_user_function_not_verified', key[0], key[1])
                        elif token.type == 'OPERAND' and token.subtype == 'RANGE':
                            _, address = _split_ref(token.value, key[0])
                            if '[' in address or ']' in address or address.endswith('#') or address.startswith('@'):
                                warn('structured_or_spill_metadata_not_copied', key[0], key[1])
                except (TokenizerError, IndexError):
                    warn('formula_not_parsed', key[0], key[1])
        warn('all_populated_cells_no_target', '', '원하는 결과를 지정하면 필요한 선행 셀까지 좁힐 수 있습니다.')
    if not keep:
        raise CopySelectionError('선택한 범위에 보존할 데이터나 수식이 없습니다.')
    # 입력 숫자만 덩그러니 남지 않도록 이미 분석된 표의 해당 열 제목을 함께 둡니다.
    header_count = 0
    if targets:
        for table in result.get('tables', []):
            depth = table.get('header_rows', 0)
            if not depth:
                continue
            bounds = range_boundaries(table['range'])
            columns = {range_boundaries(a)[0] for s, a in keep if s == table['sheet'] and _inside(a, bounds)}
            for col in columns:
                for row in range(bounds[1], bounds[1] + depth):
                    key = table['sheet'], f'{get_column_letter(col)}{row}'
                    record = records.get(key)
                    if record and not record.get('formula') and key not in keep:
                        keep.add(key); header_count += 1
    # 이름이 정의된 시트와 명시적으로 참조된 빈 시트의 의미를 유지합니다.
    kept_sheets = {s for s, _ in keep}
    kept_sheets.update(n['sheet'] for n in used_names.values() if n.get('sheet'))
    # 실제로 참조하는 빈 시트는 남깁니다. 관련 없는 원본 시트는 선택 사본에서 제외합니다.
    kept_sheets.update(referenced_sheets)
    errors = Counter(str(records[k].get('value')) for k in keep if records[k].get('type') == 'e')
    if result.get('summary', {}).get('vba', {}).get('status') not in (None, 'no_vba'):
        warn('vba_not_copied', '', '매크로 코드와 실행 결과의 동등성은 포함하지 않습니다.')
    return {'cells': [records[k] for k in sorted(keep, key=lambda k: (sheet_names.index(k[0]), range_boundaries(k[1])[1], range_boundaries(k[1])[0]))],
            'sheets': [s for s in sheet_names if s in kept_sheets], 'names': list(used_names.values()),
            'epoch': result['workbook_structure'].get('epoch'),
            'receipt': {'targets': targets, 'selection': 'outputs_and_static_dependencies' if targets else 'all_populated_cells',
                        'source_cell_count': len(records), 'kept_cell_count': len(keep),
                        'formula_count': sum(bool(records[k].get('formula')) for k in keep), 'retained_header_cells': header_count,
                        'literal_error_counts': dict(errors), 'warnings': dict(warnings), 'warning_examples': warning_examples,
                        'formula_text_preserved': True, 'formula_results_recalculated': False,
                        'cached_formula_values_copied': False, 'macros_connections_images_copied': False,
                        'source_modified': False}}


def _restore_value(record):
    value = record.get('value')
    if record.get('type') == 'd' and isinstance(value, str):
        if is_timedelta_format(record.get('number_format', '')):
            from project_runtime import _decode
            return _decode(value, {'kind': 'duration'})
        try:
            return dt.datetime.fromisoformat(value)
        except ValueError:
            return dt.time.fromisoformat(value)
    return value


def write_copy(prepared, destination):
    """좌표를 옮기지 않아 원래 수식 참조를 유지합니다. 새 파일만 독점 생성합니다."""
    destination = Path(destination).absolute()
    if destination.suffix.lower() != '.xlsx':
        raise CopySelectionError('새 사본의 확장자는 .xlsx여야 합니다.')
    for p in (destination, *destination.parents):
        if p.is_symlink() or p.exists() and getattr(p.lstat(), 'st_file_attributes', 0) & 0x400:
            raise CopySelectionError('링크나 연결된 폴더에는 XLSX 사본을 만들지 않습니다.')
    if destination.exists():
        raise CopySelectionError('기존 파일을 덮어쓰지 않습니다: ' + str(destination))
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    try:
        if prepared.get('epoch'):
            wb.epoch = dt.datetime.fromisoformat(prepared['epoch'])
        wb.calculation = CalcProperties(calcMode='manual', fullCalcOnLoad=False, forceFullCalc=False)
        for name in prepared['sheets']:
            ws = wb.create_sheet(name); ws.sheet_view.showGridLines = True
        for record in prepared['cells']:
            cell = wb[record['sheet']][record['cell']]
            cell.value = record.get('formula') or _restore_value(record)
            # =로 시작하는 원본 문자열도 수식으로 바꾸지 않습니다.
            cell.data_type = 'f' if record.get('formula') else record.get('type', 'n')
            cell.number_format = record.get('number_format') or 'General'
            cell.font = Font(name='맑은 고딕', size=10, color='1F2937')
            if cell.row == 1:
                cell.font = Font(name='맑은 고딕', size=10, bold=True, color='FFFFFF')
                cell.fill = PatternFill('solid', fgColor='243C55')
        for item in prepared['names']:
            owner = wb if item.get('sheet') is None else wb[item['sheet']]
            owner.defined_names.add(DefinedName(item['name'], attr_text=item['text']))
        for ws in wb:
            ws.freeze_panes = 'A2'
            for col in range(1, ws.max_column + 1):
                ws.column_dimensions[get_column_letter(col)].width = 16
        destination.parent.mkdir(parents=True, exist_ok=True)
        # O_EXCL은 검사 이후에 같은 이름의 파일이 생겨도 덮어쓰지 않게 합니다.
        handle = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(handle, 'wb') as stream:
                wb.save(stream)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    finally:
        wb.close()
    return {**prepared['receipt'], 'path': str(destination), 'bytes': destination.stat().st_size}
