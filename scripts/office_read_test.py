#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""사내 파일 읽기 독립 시험. 이 파일 하나만 복사해서 사용하세요.

실행: python office_read_test.py
준비물 확인만: python office_read_test.py --check
파일 지정: python office_read_test.py "C:\\work\\자료.xlsx"

Excel/CSV: xlwings + pandas / PPTX·DOCX: pywin32 / PDF: pypdf
Windows·Python 3.11 이상. Office 형식은 해당 데스크톱 Office가 필요합니다.
외부 전송, 자동 패키지 설치, 원본 저장, 본문 로그 저장을 하지 않습니다.
결과 내용은 현재 터미널에 표시됩니다. 회사에서 허용한 파일만 시험하세요.
PDF는 1.4.1 하네스에 없던 별도 시험 경로이며 Acrobat/DRM 연동이 아닙니다.
"""
import argparse
import hashlib
import importlib
import importlib.util
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time
import json

KINDS = {'.xlsx': 'excel', '.csv': 'excel', '.pptx': 'powerpoint', '.docx': 'word', '.pdf': 'pdf'}
ENGINES = {'excel': 'xlwings → Excel → DataFrame', 'powerpoint': 'pywin32 → PowerPoint',
           'word': 'pywin32 → Word', 'pdf': 'pypdf (PDF 글자 직접 읽기)'}
REQUIRED = {'excel': ('xlwings', 'pandas'), 'powerpoint': ('win32com.client', 'pythoncom'),
            'word': ('win32com.client', 'pythoncom'), 'pdf': ('pypdf',)}


# BEGIN SHARED OFFICE STRUCTURE (kept identical by regression test)
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
# END SHARED OFFICE STRUCTURE


class StopRead(Exception):
    pass


def check_permission(document):
    """Office IRM 부가 정보. 미지원은 DRM 탐지나 접근 허가를 뜻하지 않습니다."""
    try:
        permission = document.Permission
        if permission is None or permission.Enabled is None:
            return '확인 정보 미제공 (DRM 허가/차단 판정 아님)'
        if permission.Enabled:
            raise StopRead('Office에서 권한 제한을 보고하여 중단했습니다.')
        return 'Office IRM 제한 보고 없음 (회사 DRM·추출 권한은 별도)'
    except StopRead:
        raise
    except Exception as exc:
        codes = [getattr(exc, 'hresult', None)]
        extra = getattr(exc, 'excepinfo', None)
        if isinstance(extra, tuple) and len(extra) > 5:
            codes.append(extra[5])
        if isinstance(exc, PermissionError) or any(c in (-2147024891, 2147942405) for c in codes):
            raise StopRead('Office 권한 조회가 거절되었습니다.') from None
        if isinstance(exc, AttributeError) or any(c in (-2147467259, 2147500037, -2147352573) for c in codes):
            return '확인 API 미지원 (DRM 허가/차단 판정 아님)'
        raise


class Preview:
    def __init__(self, start=1, end=None, max_chars=3000):
        self.parts = []
        self.structures = []
        self.start, self.end = start, end
        self.remaining = max_chars
        self.visited = 0
        self.truncated = False

    @property
    def full(self):
        return self.remaining <= 0 or self.visited >= 2000

    def add(self, location, value, structure=None):
        if self.full:
            self.truncated = True
            return
        self.visited += 1
        text = str(value if value is not None else '').strip('\r\x07')
        if not text.strip():
            return
        take = min(len(text), self.remaining)
        self.parts.append((location, text[:take]))
        self.structures.append(structure)
        self.remaining -= take
        self.truncated |= take < len(text)


def read_excel(path, preview, progress):
    import xlwings as xw
    import pandas as pd
    app = book = scratch = None
    try:
        progress['stage'] = 'Excel 실행'
        app = xw.App(visible=False, add_book=False)
        app.api.AutomationSecurity = 3
        scratch = app.books.add()
        app.calculation = 'manual'
        progress['stage'] = '파일 열기'
        # xw.Book(path)가 아니라 이 시험에서 만든 Excel에 파일을 연결합니다.
        book = app.books.open(str(path), read_only=True, update_links=False, add_to_mru=False)
        progress['opened'] = True
        progress['stage'] = '권한 정보 확인'
        progress['permission'] = check_permission(book.api)
        progress['stage'] = '셀 읽기'
        sheet = book.sheets[0]
        used = sheet.used_range
        rows, cols = min(used.rows.count, 20), min(used.columns.count, 10)
        area = sheet.range((used.row, used.column), (used.row + rows - 1, used.column + cols - 1))
        df = area.options(pd.DataFrame, header=False, index=False).value
        progress['scope'] = f'첫 시트 {sheet.name}, 사용 영역 시작부터 {rows}행 × {cols}열'
        for ri, values in enumerate(df.itertuples(index=False, name=None), used.row):
            for ci, value in enumerate(values, used.column):
                if not pd.isna(value):
                    preview.add(f'R{ri}C{ci}', value, {'type':'table-cell','row':ri,'column':ci})
                if preview.full: break
            if preview.full: break
        preview.truncated |= used.rows.count > rows or used.columns.count > cols
    finally:
        for owned in (book, scratch):
            if owned is not None:
                try: owned.close()
                except Exception: progress['cleanupWarning'] = True
        if app is not None:
            try:
                if len(app.books) == 0: app.quit()
            except Exception: progress['cleanupWarning'] = True


def read_office(path, kind, preview, progress):
    import pythoncom
    import win32com.client
    app = document = None
    security = links = None
    is_word = kind == 'word'
    started = time.perf_counter()
    progress['timingMs'] = {}
    pythoncom.CoInitialize()
    try:
        progress['stage'] = 'Word 실행' if is_word else 'PowerPoint 실행'
        app = win32com.client.DispatchEx('Word.Application' if is_word else 'PowerPoint.Application')
        documents = app.Documents if is_word else app.Presentations
        for i in range(1, documents.Count + 1):
            if os.path.normcase(documents.Item(i).FullName) == os.path.normcase(str(path)):
                raise StopRead('이미 열려 있는 원본입니다. 먼저 저장하고 닫은 뒤 시험하세요.')
        security = app.AutomationSecurity
        app.AutomationSecurity = 3
        progress['stage'] = '파일 열기'
        if is_word:
            links = app.Options.UpdateLinksAtOpen
            app.Options.UpdateLinksAtOpen = False
            document = documents.Open(str(path), False, True, False)
        else:
            document = documents.Open(str(path), -1, 0, 0)
        progress['opened'] = True
        progress['timingMs']['open'] = round((time.perf_counter()-started)*1000)
        if os.path.normcase(os.path.abspath(document.FullName)) != os.path.normcase(str(path.resolve())):
            raise StopRead('Office가 요청한 경로와 다른 문서를 열었습니다. 결과를 사용하지 않습니다.')
        progress['stage'] = '권한 정보 확인'
        progress['permission'] = check_permission(document)
        progress['stage'] = '본문 읽기'
        extracted = extract_document(document, {'kind': kind, 'start': preview.start,
                                      'end': preview.end or (preview.start + (19 if is_word else 2)),
                                      'maxChars': preview.remaining})
        if not extracted['ok']:
            raise StopRead('요청한 시작 번호가 Office에서 확인된 범위를 벗어났습니다.')
        preview.parts.extend((item['location'], item['text']) for item in extracted['items'])
        preview.structures = [item.get('structure') for item in extracted['items']]
        preview.truncated |= extracted['truncated']
        progress['coverage'] = extracted['coverage']
        progress['openedPath'] = str(document.FullName)
        progress['scope'] = f"{extracted['coverage']['start']}~{extracted['coverage']['end']} / Office 보고 전체 {extracted['coverage']['total']} ({extracted['coverage']['unit']})"
    finally:
        if document is not None:
            try:
                if is_word: document.Close(0)
                else:
                    document.Saved = -1
                    document.Close()
            except Exception: progress['cleanupWarning'] = True
        if app is not None:
            try:
                if links is not None: app.Options.UpdateLinksAtOpen = links
                if security is not None: app.AutomationSecurity = security
            except Exception: progress['cleanupWarning'] = True
        # 전체 Quit/강제 종료는 하지 않습니다. 빈 Office 창/프로세스가 남을 수 있습니다.
        document = app = None
        pythoncom.CoUninitialize()


def read_pdf(path, preview, progress):
    from pypdf import PdfReader
    progress['stage'] = 'PDF 열기'
    with path.open('rb') as source:
        header = source.read(1024)
        source.seek(max(0, path.stat().st_size-8192))
        tail = source.read(8192)
        progress['pdfDiagnostics'] = {'bytes': path.stat().st_size,
                                    'pdfHeaderFound': b'%PDF-' in header,
                                    'eofMarkerFound': b'%%EOF' in tail,
                                    'reader': 'pypdf (not Office or Acrobat)'}
        if b'%PDF-' not in header:
            raise StopRead('일반 PDF 헤더(%PDF-)를 찾지 못했습니다. 확장자만 PDF이거나 파일이 불완전하거나 별도 포장 형식일 수 있습니다. DRM이라고 단정할 수 없습니다. 회사에서 허용한 PDF 뷰어로 동일 파일이 열리는지 확인하세요. 다른 추출 방식은 자동 시도하지 않았습니다.')
        source.seek(0)
        pdf = PdfReader(source)
        progress['opened'] = True
        if pdf.is_encrypted:
            raise StopRead('암호화/권한 설정 PDF입니다. 이 시험은 암호 해제나 제한 우회를 하지 않습니다.')
        progress['stage'] = 'PDF 글자 읽기'
        count = min(len(pdf.pages), preview.end or (preview.start+2))
        if preview.start > count: raise StopRead('요청 범위가 PDF 페이지 수를 벗어났습니다.')
        progress['scope'] = f'{preview.start}~{count} / 전체 {len(pdf.pages)}쪽 (OCR·Acrobat 연동 아님)'
        for i in range(preview.start-1, count):
            page = pdf.pages[i]
            preview.add(f'{i+1}쪽', (page.extract_text(extraction_mode='layout') or '') if '/Contents' in page else '')
            if preview.full: break
        preview.truncated |= len(pdf.pages) > count


def read_once(path, options=None):
    """One attempt; no fallback reader and no persisted source content."""
    result = {'ok': False, 'opened': False, 'stage': '모듈 확인'}
    started=time.perf_counter()
    preview = Preview(**(options or {}))
    try:
        kind = KINDS[path.suffix.lower()]
        for name in REQUIRED[kind]:
            importlib.import_module(name)
        if kind == 'excel': read_excel(path, preview, result)
        elif kind == 'pdf': read_pdf(path, preview, result)
        else: read_office(path, kind, preview, result)
        result.update(ok=True, parts=preview.parts, structures=preview.structures, truncated=preview.truncated or preview.full)
    except (ImportError, ModuleNotFoundError) as exc:
        result['message'] = f'필요한 모듈을 사용할 수 없습니다: {getattr(exc, "name", None) or "모듈 의존성"}. 자동 설치하지 않았습니다.'
    except StopRead as exc:
        result['message'] = str(exc)
    except Exception as exc:
        result['message'] = ('PDF 내부 구조/스트림을 파서가 읽지 못했습니다. 파일 손상·불완전 다운로드·비표준 PDF 등을 확인해야 합니다. 이 오류만으로 DRM이라고 단정할 수 없습니다. Office COM과는 별도 경로이며 자동 복구·다른 파서 재시도는 하지 않았습니다.'
                             if type(exc).__name__ in ('PdfStreamError','PdfReadError','EmptyFileError') else
                             '읽기를 완료하지 못했습니다. DRM·파일 형식·Office 구성 중 원인을 아직 단정할 수 없습니다.')
        result['errorType'] = type(exc).__name__
        result['hresult'] = getattr(exc, 'hresult', None)
        # Raw COM descriptions can contain document text or confidential paths.
    result['elapsedMs']=round((time.perf_counter()-started)*1000)
    result['python']=sys.executable
    return result


def _worker(path, channel, options=None):
    try:
        # Third-party diagnostic output is not mixed with source previews.
        with open(os.devnull, 'w') as quiet:
            sys.stdout = sys.stderr = quiet
            channel.send(read_once(Path(path), options))
    finally:
        channel.close()


def run_test(path, timeout=60, options=None):
    """A hung reader is bounded; never terminate the user's Office process."""
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    context = mp.get_context('spawn')
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(str(path), child, options))
    try:
        process.start()
        child.close()
        if not parent.poll(timeout):
            return {'ok': False, 'opened': None, 'stage': '응답 대기',
                    'message': f'{timeout}초 동안 완료되지 않았습니다. Office 인증/보안 창을 확인하세요. Office는 강제 종료하지 않았으며 정리·설정 복원 여부는 미확인입니다.'}
        result = parent.recv()
        unchanged = hashlib.sha256(path.read_bytes()).hexdigest() == before
        result['sourceUnchanged'] = unchanged
        result['sourceSha256'] = before
        if not unchanged:
            result.pop('parts', None)
            result.update(ok=False, message='시험 중 원본 바이트가 달라져 결과 내용을 표시하지 않았습니다.')
        return result
    except (EOFError, OSError) as exc:
        return {'ok': False, 'stage': '시험 실행', 'message': '파일 접근 또는 시험 프로세스 응답을 확인하지 못했습니다.', 'errorType': type(exc).__name__}
    finally:
        child.close()
        parent.close()
        if process.pid is not None:
            process.join(1)
            if process.is_alive():
                process.terminate()  # only this program's Python child, NOT Office
                process.join(2)


def resolve_source(value):
    path = Path(value.strip().strip('"').strip("'")).expanduser()
    if not path.is_absolute(): path = Path.cwd() / path
    path = path.resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in KINDS:
        raise ValueError('지원 형식: .xlsx, .csv, .pptx, .docx, .pdf')
    if path.stat().st_size > 100 * 1024 * 1024:
        raise ValueError('이 간단 시험은 100MB 이하 파일만 받습니다.')
    return path


def show(result):
    print('\n결과:', '읽기 완료' if result['ok'] else '미완료')
    print('파일 열기:', {True: '성공', False: '완료 전 중단', None: '미확인'}.get(result.get('opened')))
    print('단계:', result.get('stage', '미확인'))
    for key, label in (('scope','읽은 범위'), ('permission','부가 권한 정보'),
                       ('message','안내'), ('errorType','오류 종류'), ('hresult','오류 코드'),
                       ('pdfDiagnostics','PDF 형식 확인'), ('elapsedMs','읽기 시간(ms)'),
                       ('sourceSha256','원본 비교용 SHA256'), ('python','실행 Python'), ('coverage','읽은 구조와 범위')):
        if result.get(key) is not None: print(f'{label}: {result[key]}')
    if 'sourceUnchanged' in result:
        print('원본 바이트:', '유지' if result['sourceUnchanged'] else '변경 감지')
    if result.get('cleanupWarning'): print('주의: 열었던 문서 정리 또는 설정 복원을 확인하지 못했습니다.')
    if result['ok']:
        if not result.get('parts'):
            print('선택 범위에서 글자가 반환되지 않았습니다. 빈 문서/스캔/미지원 개체/인코딩 등을 확인하세요. DRM 때문이라고 단정할 수 없습니다.')
        else:
            print('--- 내용 미리보기: 현재 터미널에만 표시 ---')
            for index, (location, text) in enumerate(result['parts']):
                print(f'[{location}] {text}')
                structures=result.get('structures', [])
                if index<len(structures) and structures[index]:
                    print('  구조:', json.dumps(structures[index], ensure_ascii=False))
        print('일부 범위 또는 분량 제한에 걸린 결과입니다.' if result.get('truncated') else '선택한 범위를 확인했습니다.')
        print('그림·차트 등 미지원 요소는 제외되며 문서 전체 확인이나 DRM 해제 성공을 뜻하지 않습니다.')


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser(description='독립 파일 읽기 시험: Excel/xlwings, PPT·Word/pywin32, PDF/pypdf')
    parser.add_argument('files', nargs='*', help='시험할 파일 경로. 없으면 한국어로 입력을 받습니다.')
    parser.add_argument('--check', action='store_true', help='필요 모듈만 확인하고 종료')
    parser.add_argument('--start', type=int, default=1, help='시작 슬라이드/문단/PDF 페이지 번호')
    parser.add_argument('--end', type=int, help='끝 번호. 한 번에 최대 50개')
    parser.add_argument('--max-chars', type=int, default=3000, help='표시 글자 한도 (100~20000)')
    args = parser.parse_args()
    if (not 100<=args.max_chars<=20000 or not 1<=args.start<=100000 or
            (args.end is not None and not args.start<=args.end<=min(args.start+49,100000))):
        parser.error('범위는 시작 이상, 최대 50개이며 글자 한도는 100~20000입니다.')
    print('사내 파일 읽기 시험 / Python:', sys.executable)
    if args.check:
        for kind, names in REQUIRED.items():
            missing = []
            for name in names:
                try: importlib.import_module(name)
                except (ImportError, OSError): missing.append('pywin32' if name in ('win32com.client','pythoncom') else name)
            print(f'{ENGINES[kind]}: ' + ('모듈 준비됨 (실제 파일 열기는 아직 미확인)' if not missing else '필요: ' + ', '.join(sorted(set(missing)))))
        return 0
    if os.name != 'nt':
        print('이 시험 파일은 Windows용입니다.'); return 1
    print('원본 저장·외부 전송·자동 설치 없음. 본문이 이 창에 표시됩니다. 허용된 파일만 시험하세요.')
    print('PDF는 직접 글자 읽기이며 어제 하네스의 Office 경로와 다릅니다. 스캔/OCR/DRM 해제를 지원하지 않습니다.')
    pending = list(args.files)
    failed = False
    while True:
        value = pending.pop(0) if pending else ('' if args.files else input('\n파일 경로를 붙여 넣으세요 (따옴표 가능, Enter=종료): '))
        if not value.strip(): break
        try: path = resolve_source(value)
        except (OSError, ValueError) as exc:
            print('파일 경로/형식 확인 필요:', str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
            failed = True; continue
        print('방식:', ENGINES[KINDS[path.suffix.lower()]])
        print('파일:', path)
        if input('이 파일의 앞부분을 읽어 이 창에 표시할까요? [y/예, Enter=취소]: ').strip().lower() not in ('y','yes','예'):
            print('취소했습니다.'); continue
        print('읽는 중입니다. 최대 60초 기다립니다. Office 인증 창이 뜨면 직접 확인하세요.')
        try: result = run_test(path, options={'start':args.start, 'end':args.end, 'max_chars':args.max_chars})
        except OSError as exc:
            result = {'ok': False, 'stage': '원본 접근', 'message': '원본 파일을 읽을 수 없습니다.', 'errorType': type(exc).__name__}
        show(result)
        failed |= not result['ok']
    return int(failed)


if __name__ == '__main__':
    mp.freeze_support()
    try: raise SystemExit(main())
    except (KeyboardInterrupt, EOFError): print('\n시험을 종료했습니다.')
