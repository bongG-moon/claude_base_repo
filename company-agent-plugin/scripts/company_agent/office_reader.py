"""Bounded, user-confirmed Office reads. No decryption, export, or parser fallback."""
from pathlib import Path
import json
import os
import re
import stat
import subprocess
import sys
import time
import hashlib

from .business_safety import safe_path, blocked_input
from .office_consent import authorize
from .paths import user_state_root
from .office_progress import Progress, run_helper

TYPES={'.xlsx':'excel','.csv':'excel','.pptx':'powerpoint','.docx':'word'}


class OfficeRequestError(ValueError):
    """Bounded validation evidence, without returning filesystem exceptions."""
    def __init__(self, code, field):
        super().__init__(code)
        self.code = code
        self.field = field


def normalize(spec):
    if not isinstance(spec,dict):
        raise ValueError('invalid request')
    allowed={'file','start','end','sheet','range','maxChars','protection','expectedCount'}
    if set(spec)-allowed:
        raise ValueError('unknown fields, permissions cannot be supplied in JSON')
    path=Path(spec.get('file',''))
    if not path.is_absolute() or '..' in path.parts:
        raise OfficeRequestError('invalid_office_path', 'file')
    if path.suffix.lower() not in TYPES:
        raise OfficeRequestError('unsupported_office_format', 'file')
    try:
        # Check path safety before distinguishing a missing file. Do not search
        # sibling folders or repair a model-reconstructed source path.
        path=safe_path(path)
        info=path.stat()
    except FileNotFoundError:
        raise OfficeRequestError('source_not_found', 'file') from None
    except ValueError:
        raise OfficeRequestError('invalid_office_path', 'file') from None
    except OSError:
        raise OfficeRequestError('source_metadata_unavailable', 'file') from None
    if not stat.S_ISREG(info.st_mode):
        raise OfficeRequestError('invalid_office_source', 'file')
    if info.st_size>100*1024*1024:
        raise OfficeRequestError('office_source_too_large', 'file')
    result={'file':str(path),'kind':TYPES[path.suffix.lower()],'maxChars':spec.get('maxChars',10000)}
    if 'expectedCount' in spec:
        count = spec['expectedCount']
        if result['kind']=='excel' or type(count) is not int or not 1<=count<=100000:
            raise OfficeRequestError('invalid_expected_count', 'expectedCount')
        result['expectedCount']=count
    if type(result['maxChars']) is not int or not 100<=result['maxChars']<=20000:
        raise OfficeRequestError('invalid_office_limit', 'maxChars')
    if result['kind']=='excel':
        if 'start' in spec or 'end' in spec:
            raise OfficeRequestError('invalid_office_range', 'start/end')
        sheet=spec.get('sheet',1)
        if not ((type(sheet) is int and 1<=sheet<=1000) or (isinstance(sheet,str) and 1<=len(sheet)<=31)):
            raise OfficeRequestError('invalid_office_range', 'sheet')
        address=spec.get('range','used')
        if address=='used':
            result.update(sheet=sheet,range='used')
            return result
        if not isinstance(address,str) or not re.fullmatch(r'[A-Z]{1,3}[1-9]\d{0,6}:[A-Z]{1,3}[1-9]\d{0,6}',address):
            raise OfficeRequestError('invalid_office_range', 'range')
        def cell(value):
            letters,row=re.fullmatch(r'([A-Z]+)(\d+)',value).groups()
            col=0
            for letter in letters: col=col*26+ord(letter)-64
            return col,int(row)
        c1,r1=cell(address.split(':')[0]); c2,r2=cell(address.split(':')[1])
        if not (c1<=c2<=16384 and r1<=r2<=1048576 and (c2-c1+1)<=20 and (r2-r1+1)<=200 and (c2-c1+1)*(r2-r1+1)<=2000):
            raise OfficeRequestError('invalid_office_range', 'range')
        result.update(sheet=sheet,range=address)
    else:
        if 'sheet' in spec or 'range' in spec: raise OfficeRequestError('invalid_office_range', 'sheet/range')
        start,end=spec.get('start',1),spec.get('end',5 if result['kind']=='powerpoint' else 20)
        if type(start) is not int or type(end) is not int or not 1<=start<=end<=100000 or end-start+1>50:
            raise OfficeRequestError('invalid_office_range', 'start/end')
        result.update(start=start,end=end)
    return result


def failed(code, message, status='blocked'):
    return {'ok':False,'status':status,'code':code,'message':message,
            'retryAllowed':False,'rawContentStored':False,'bypassSupported':False}


def _request_failure(spec, error):
    messages={
        'source_not_found':'지정한 경로에 파일이 없습니다. 요청에 첨부된 정확한 경로와 비교하세요. 경로를 추측해 바꾸거나 인코딩·DRM 문제로 단정하지 마세요.',
        'invalid_office_path':'지원하지 않는 파일 경로입니다. 링크·네트워크 경로가 아닌 원본의 정확한 로컬 절대 경로를 지정하세요.',
        'unsupported_office_format':'지원하지 않는 확장자입니다. xlsx/csv/pptx/docx만 지원합니다.',
        'invalid_office_source':'지정한 경로가 일반 파일이 아닙니다. 원본 파일의 정확한 경로를 확인하세요.',
        'source_metadata_unavailable':'파일 정보를 확인하지 못했습니다. Office에서 문서를 열지 않았으며 문서 접근 권한은 아직 확인하지 않았습니다.',
        'office_source_too_large':'파일 크기가 읽기 한도 100MB를 넘습니다. 문서를 열지 않았습니다.',
        'invalid_office_range':'읽을 범위를 확인하세요. Excel은 시트와 셀 범위(최대 200행·20열·2,000셀), PPT/Word는 시작·끝(최대 50개)을 지정합니다.',
        'invalid_office_limit':'maxChars는 100~20,000 사이 정수여야 합니다.',
        'invalid_expected_count':'expectedCount는 PPT/Word에만 지정하는 1~100,000 사이 정수입니다.',
        'invalid_office_request':'읽기 요청 형식이 잘못되었습니다. 파일·범위 값과 허용된 항목을 확인하세요.',
    }
    code=error.code if isinstance(error,OfficeRequestError) else 'invalid_office_request'
    result={**failed(code,messages[code],'failed'), 'sourceOpened':False,
            'documentAccess':'not_checked', 'failureKind':'request_validation'}
    if isinstance(error,OfficeRequestError):
        result['diagnostics']={'field':error.field}
        # Echo only the caller's source identity, never another discovered path
        # or OS exception. This is metadata, not document content.
        source=spec.get('file') if isinstance(spec,dict) else None
        if error.field=='file' and isinstance(source,(str,Path)) and len(str(source))<=32768:
            result['diagnostics']['requestedFile']=str(source)
    return result


def _invoke(request, *, progress=None):
    scripts=Path(__file__).resolve().parents[1]
    # Keep the selected user's installed packages, but ignore PYTHON* overrides
    # and do not import modules from the caller's working directory.
    helper='Read-CompanyExcel.py' if request.get('kind')=='excel' else 'Read-CompanyOffice.py'
    command=[sys.executable,'-E','-P',str(scripts/helper)]
    proc=run_helper(command, json.dumps(request,ensure_ascii=True).encode('ascii'),
                    timeout=60, progress=progress or Progress(enabled=False))
    if proc.returncode or len(proc.stdout)>2*1024*1024:
        raise ValueError('invalid helper response')
    result=json.loads(proc.stdout.decode('utf-8-sig'))
    if not isinstance(result,dict): raise ValueError('invalid helper response')
    return result


def read_office(spec, *, progress=None, state_root=None, session_id='', cwd=None):
    progress = progress or Progress(enabled=False)
    progress.begin('request')
    try:
        result = _read_office(spec, progress, state_root=state_root, session_id=session_id, cwd=cwd)
    finally:
        timing = progress.finish()
    result.setdefault('diagnostics', {})['progress'] = timing
    return result


def _read_office(spec, progress, *, state_root=None, session_id='', cwd=None):
    restricted=blocked_input(spec) if isinstance(spec,dict) else None
    if restricted:
        return restricted
    try:
        request=normalize(spec)
    except (ValueError,TypeError,OSError) as error:
        return _request_failure(spec,error)
    if os.name!='nt':
        return failed('office_unavailable','Windows에 설치된 Office가 필요한 기능입니다.','unavailable')
    progress.begin('conversation_consent')
    try:
        consent_source = safe_path(request['file']).stat()
    except FileNotFoundError:
        return _request_failure(spec,OfficeRequestError('source_not_found','file'))
    except ValueError:
        return _request_failure(spec,OfficeRequestError('invalid_office_path','file'))
    except OSError:
        return _request_failure(spec,OfficeRequestError('source_metadata_unavailable','file'))
    consent = authorize(request, root=state_root or user_state_root(), session_id=session_id, cwd=cwd)
    if consent is not None:
        return consent
    try:
        # The request is data only. No code, passwords, permission flags or export paths.
        progress.begin('source_check')
        path=safe_path(request['file'],exists=True)
        before=path.stat()
        if ((consent_source.st_size, consent_source.st_mtime_ns, consent_source.st_ino)
                != (before.st_size, before.st_mtime_ns, before.st_ino)):
            return failed('source_changed','승인 확인 중 원본이 변경되어 문서를 열지 않았습니다. 저장을 마친 뒤 다시 확인해 주세요.')
        fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()
        started=time.perf_counter()
        progress.begin('dependencies')
        result=_invoke(request, progress=progress)
        elapsed=round((time.perf_counter()-started)*1000)
        progress.begin('source_verify')
        after=path.stat()
        if ((before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino)
                or hashlib.sha256(path.read_bytes()).hexdigest()!=fingerprint):
            return failed('source_changed','읽는 중 원본이 변경되어 결과를 사용하지 않았습니다. 저장을 마친 뒤 다시 요청해 주세요.')
        if result.get('ok') is not True:
            code=result.get('code')
            messages={
                'protected_input':'Office에서 권한 제한을 감지해 내용을 읽지 않았습니다.',
                'protection_unknown':'Office 권한 상태를 확인할 수 없어 내용을 읽지 않았습니다.',
                'office_unavailable':'해당 Office 프로그램을 사용할 수 없습니다.',
                'excel_dependencies_missing':'현재 Company Agent가 사용하는 Python에 xlwings와 pandas가 필요합니다. 다른 방식으로 바꾸거나 인터넷에서 자동 설치하지 않았습니다.',
                'office_dependencies_missing':'현재 Company Agent가 사용하는 Python에 pywin32가 필요합니다. 다른 방식으로 바꾸거나 인터넷에서 자동 설치하지 않았습니다.',
                'permission_denied':'Office에서 파일 열기 또는 읽기를 거절했습니다.',
                'office_busy':'연결된 Excel에 다른 문서가 있어 작업을 중단했습니다. 사용 중인 문서는 변경하지 않았습니다.',
                'document_open':'이 Office 실행 환경에서 이미 열린 문서는 자동으로 닫거나 다시 열지 않습니다. 문서를 저장·닫은 뒤 요청해 주세요.',
                'office_read_failed':'Office에서 문서를 읽지 못했습니다. 보호·형식·인증 중 어느 원인인지는 확인되지 않았습니다.',
                'invalid_request':'Office 읽기 요청의 형식이나 범위를 확인해 주세요.',
                'source_mismatch':'Office가 요청한 경로와 다른 문서를 열어 결과를 사용하지 않았습니다.',
            }
            response=failed(code if code in messages else 'office_read_failed',messages.get(code,messages['office_read_failed']))
            if result.get('stage') in {'request','application','open','permission','read','dependencies'}:
                response['stage']=result['stage']
            return response
        items=result.get('items')
        if not isinstance(items,list) or len(items)>2000 or len(json.dumps(items,ensure_ascii=False))>1000000:
            raise ValueError('invalid content response')
        total=0
        for item in items:
            if (not isinstance(item,dict) or not {'location','text'}<=set(item)<= {'location','text','structure'}
                    or not all(isinstance(item[k],str) for k in ('location','text'))):
                raise ValueError('invalid item')
            if 'structure' in item and (not isinstance(item['structure'],dict) or len(json.dumps(item['structure']))>2000):
                raise ValueError('invalid structure')
            if len(item['location'])>200: raise ValueError('invalid location')
            total+=len(item['text'])
        if total>request['maxChars']: raise ValueError('content limit exceeded')
        coverage=result.get('coverage') or {}
        mismatch='expectedCount' in request and coverage.get('total')!=request['expectedCount']
        return {'ok':True,'status':'partial' if result.get('truncated') or mismatch else 'read',
                'kind':request['kind'],'items':items,'truncated':bool(result.get('truncated')),
                'coverage':result.get('coverage'),'sourceSaved':False,'rawContentStored':False,
                'diagnostics':{**result.get('diagnostics',{}), 'sourceSha256':fingerprint, 'helperElapsedMs':elapsed,
                               'expectedCount':request.get('expectedCount'), 'countMismatch':mismatch},
                'transcriptRetention':'tool_output_may_be_retained','bypassSupported':False,
                'drmAuthorization':'not_proven_by_office_success',
                'message':('예상 개수와 Office가 보고한 개수가 다릅니다. 동일 파일 경로·해시·실행 환경을 비교해야 하며 DRM 때문이라고 단정할 수 없습니다.' if mismatch else
                           '선택 범위의 내용과 구조를 읽었습니다. coverage의 범위·제외 개체를 확인하세요. 전체 파일 읽기나 DRM 차단/허용의 증거는 아닙니다.')}
    except subprocess.TimeoutExpired:
        return {**failed('office_timeout','Office 읽기 제한 60초를 넘어 중단했습니다. diagnostics.progress.lastStage에서 지연 구간을 확인하세요. 보안·인증 창을 확인하고 반복 실행하지 마세요. Office는 강제 종료하지 않았습니다.','unavailable'), 'stage': progress.stage}
    except (OSError,ValueError,TypeError):
        return failed('office_read_failed','Office 읽기를 완료하지 못했습니다. 원본은 저장하지 않았습니다.','failed')
