"""One fixed Excel recipe: xlwings -> owned Excel -> bounded range -> DataFrame.

Not a decryption library. Actual open/read denials stop; no other reader is tried.
"""
import importlib
import json
import sys


def denied(exc):
    values=[getattr(exc,'hresult',None),getattr(exc,'winerror',None)]
    info=getattr(exc,'excepinfo',None)
    if isinstance(info,tuple) and len(info)>5: values.append(info[5])
    return (isinstance(exc,PermissionError) or any(v in (5,-2147024891,2147942405) for v in values)
            or any(t in str(exc).casefold() for t in ('access denied','access is denied','permission denied','액세스가 거부','접근이 거부')))


def permission_status(book):
    """An unavailable optional Office IRM API is not a document-open refusal.

Do not infer third-party DRM permission from this API. Keep any actual denial or
reported Office restriction binding; never change the permissions object.
"""
    try:
        permission=book.api.Permission
        if permission is None: return 'unavailable'
        enabled=permission.Enabled
        if enabled is None: return 'unavailable'
        return 'restricted' if enabled else 'not_restricted_by_office_irm'
    except Exception as exc:
        if denied(exc): return 'denied'
        codes=[getattr(exc,'hresult',None)]
        info=getattr(exc,'excepinfo',None)
        if isinstance(info,tuple) and len(info)>5: codes.append(info[5])
        if isinstance(exc,AttributeError) or any(code in (-2147467259,2147500037,-2147352573) for code in codes):
            return 'unavailable'
        raise


def _read(request,xw,pd):
    app=book=scratch=None
    stage='application'
    result={'ok':False,'code':'office_read_failed','stage':stage}
    try:
        # Bind the book to THIS instance. Never use xw.Book(), which can attach to
        # the user's already-open workbook in another Excel instance.
        app=xw.App(visible=False,add_book=False)
        app.api.AutomationSecurity=3
        scratch=app.books.add()
        app.calculation='manual'
        stage='open'
        book=app.books.open(request['file'],read_only=True,update_links=False,add_to_mru=False)
        stage='permission'
        permission=permission_status(book)
        if permission in ('restricted','denied'):
            return {'ok':False,'code':'protected_input','stage':stage}
        stage='read'
        sheet=book.sheets[request['sheet']-1] if type(request['sheet']) is int else book.sheets[request['sheet']]
        selected=sheet.used_range if request['range']=='used' else sheet.range(request['range'])
        row,col=selected.row,selected.column
        original_rows,original_cols=selected.rows.count,selected.columns.count
        cols=min(original_cols,20)
        rows=min(original_rows,200,2000//max(cols,1))
        truncated=rows<original_rows or cols<original_cols
        if truncated:
            selected=sheet.range((row,col),(row+rows-1,col+cols-1))
        # Keep the first row and first column as data instead of guessing a header
        # or using business data as an index. Do not manufacture an index column.
        frame=selected.options(pd.DataFrame,header=False,index=False).value
        if not isinstance(frame,pd.DataFrame) or frame.shape!=(rows,cols):
            raise ValueError('unexpected DataFrame shape')
        items=[]; remaining=request['maxChars']
        for ri,values in enumerate(frame.itertuples(index=False,name=None),row):
            for ci,value in enumerate(values,col):
                if pd.isna(value): continue
                text=str(value)
                if not text.strip(): continue
                if remaining<=0:
                    truncated=True
                    break
                take=min(len(text),remaining)
                items.append({'location':f'R{ri}C{ci}','text':text[:take]})
                if take<len(text): truncated=True
                remaining-=take
            if remaining<=0:
                truncated=True
                break
        result={'ok':True,'items':items,'truncated':truncated,
                'coverage':{'kind':'xlwings-dataframe','sheet':sheet.name,'requestedRange':request['range'],
                            'firstRow':row,'firstColumn':col,'rows':rows,'columns':cols,
                            'officePermissionApi':permission,'thirdPartyDrmAuthorization':'not_determined'}}
    except Exception as exc:
        result={'ok':False,'code':'permission_denied' if denied(exc) else 'office_read_failed','stage':stage}
    finally:
        # Close only books we opened; do not save, kill Excel, or close user books.
        for owned in (book,scratch):
            if owned is not None:
                try: owned.close()
                except Exception: pass
        if app is not None:
            try:
                if len(app.books)==0: app.quit()
            except Exception: pass
    return result


def read_excel(request):
    from .office_reader import normalize
    from .business_safety import blocked_input
    if not isinstance(request,dict): return {'ok':False,'code':'invalid_request'}
    if blocked_input(request): return {'ok':False,'code':'protected_input'}
    try:
        request=normalize({k:v for k,v in request.items() if k!='kind'})
        if request['kind']!='excel': raise ValueError('not Excel')
    except (ValueError,TypeError,OSError):
        return {'ok':False,'code':'invalid_request'}
    try:
        xw=importlib.import_module('xlwings')
        pd=importlib.import_module('pandas')
    except ImportError:
        return {'ok':False,'code':'excel_dependencies_missing','stage':'dependencies'}
    return _read(request,xw,pd)


def main():
    try:
        raw=sys.stdin.buffer.read(32769)
        if len(raw)>32768: raise ValueError('request too large')
        result=read_excel(json.loads(raw.decode('utf-8-sig')))
    except (ValueError,TypeError,OSError):
        result={'ok':False,'code':'invalid_request'}
    # ASCII JSON preserves Korean without relying on terminal code pages.
    print(json.dumps(result,ensure_ascii=True))
    return 0
