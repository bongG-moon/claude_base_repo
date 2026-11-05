"""Offline local HTTP server exercises the actual CLI without external data."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'query_get.py'
SECRET = 'LOCAL_TEST_SECRET_DO_NOT_LOG'


class Handler(BaseHTTPRequestHandler):
    calls = []
    def log_message(self, *args): pass
    def do_GET(self):
        parsed = urlsplit(self.path); query = parse_qs(parsed.query)
        self.calls.append((parsed.path, query, self.headers.get('Authorization')))
        if parsed.path == '/redirect':
            self.send_response(302); self.send_header('Location', '/secret'); self.end_headers(); return
        if parsed.path == '/denied':
            self.send_response(403); self.end_headers(); self.wfile.write(SECRET.encode()); return
        if parsed.path == '/echo-token':
            self.send_response(200); self.end_headers(); self.wfile.write(json.dumps({'result':{'items':[{'value':SECRET}]}}).encode()); return
        if parsed.path == '/echo-escaped':
            escaped=''.join('\\u%04x' % ord(c) for c in SECRET)
            self.send_response(200);self.end_headers();self.wfile.write(('{"result":{"items":[{"value":"'+escaped+'"}]}}').encode());return
        page = int(query.get('page', ['1'])[0]); size = int(query.get('limit', ['2'])[0])
        source = [{'id': n, 'name': f'설비-{n}'} for n in range(1, 6)]
        if parsed.path in ('/cursor','/repeat-cursor','/bad-cursor'):
            token = query.get('cursor', query.get('pageToken', ['']))[0]
            start = {'':0, 'next-2':2, 'next-4':4}.get(token,0)
            data = source[start:start+size]
            next_value = ('next-2' if start == 0 else 'next-4' if start == 2 else None)
            if parsed.path == '/repeat-cursor': next_value = 'next-2'
            if parsed.path == '/bad-cursor': next_value = 'https://example.invalid/secret'
            body=json.dumps({'result':{'items':data},'paging':{'next':next_value}},ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body);return
        if parsed.path == '/preview-sensitive':
            body=json.dumps({'result':{'items':[{'id':1,'token_count':7,'nested':{'api_key':'MASK_THIS_SECRET','records':[{'password':'MASK_PASSWORD','cursor':'MASK_CURSOR','value':'normal'}]}}]}},ensure_ascii=False).encode()
            self.send_response(200);self.end_headers();self.wfile.write(body);return
        data = source[(page-1)*size:page*size] if parsed.path != '/repeat' else source[:size]
        body = json.dumps({'result':{'items':data}},ensure_ascii=False).encode()
        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(body)


def call(base, output, *extra, env=None):
    command=[sys.executable,'-X','utf8','-B',str(SCRIPT),'--url',base,'--items-path','result.items',
             '--page-size','2','--max-pages','5','--output',str(output),*extra]
    return subprocess.run(command,text=True,encoding='utf-8',capture_output=True,env=env,timeout=20)


def test_mock_server(tmp_path):
    Handler.calls=[]
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    try:
        output=tmp_path/'all.jsonl'
        env=os.environ.copy();env['WEB_QUERY_TEST_TOKEN']=SECRET
        done=call(base+'/data',output,'--bearer-env','WEB_QUERY_TEST_TOKEN',env=env)
        assert done.returncode == 0, done.stderr
        result=json.loads(done.stdout)
        assert (result['rows'],result['pages'],result['complete']) == (5,3,True)
        assert [json.loads(line)['id'] for line in output.read_text(encoding='utf-8').splitlines()] == [1,2,3,4,5]
        assert all(headers == 'Bearer '+SECRET for path,query,headers in Handler.calls if path=='/data')
        assert SECRET not in done.stdout+done.stderr and '설비-' not in done.stdout

        limited=call(base+'/data',tmp_path/'limited.jsonl','--max-pages','1')
        assert json.loads(limited.stdout)['complete'] is False
        assert json.loads(limited.stdout)['stop_reason']=='page_limit'
        repeat=call(base+'/repeat',tmp_path/'repeat.jsonl')
        assert json.loads(repeat.stdout)['stop_reason']=='repeated_page'
        assert json.loads(repeat.stdout)['rows']==2
        cursor=call(base+'/cursor',tmp_path/'cursor.jsonl','--cursor-param','cursor','--next-cursor-path','paging.next')
        assert cursor.returncode==0, cursor.stderr
        assert (json.loads(cursor.stdout)['rows'],json.loads(cursor.stdout)['pages'],json.loads(cursor.stdout)['complete'])==(5,3,True)
        assert [json.loads(line)['id'] for line in (tmp_path/'cursor.jsonl').read_text(encoding='utf-8').splitlines()] == [1,2,3,4,5]
        page_token=call(base+'/cursor',tmp_path/'page-token.jsonl','--cursor-param','pageToken','--next-cursor-path','paging.next')
        assert page_token.returncode==0 and json.loads(page_token.stdout)['rows']==5
        assert 'next-2' not in page_token.stdout+page_token.stderr
        repeated=call(base+'/repeat-cursor',tmp_path/'repeat-cursor.jsonl','--cursor-param','cursor','--next-cursor-path','paging.next')
        assert json.loads(repeated.stdout)['stop_reason']=='repeated_cursor'
        assert json.loads(repeated.stdout)['complete'] is False
        bad=call(base+'/bad-cursor',tmp_path/'bad-cursor.jsonl','--cursor-param','cursor','--next-cursor-path','paging.next')
        assert bad.returncode==2 and json.loads(bad.stderr)['code']=='invalid_response'
        assert not (tmp_path/'bad-cursor.jsonl').exists()

        denied=call(base+'/denied',tmp_path/'denied.jsonl','--bearer-env','WEB_QUERY_TEST_TOKEN',env=env)
        assert denied.returncode==2 and json.loads(denied.stderr)['code']=='http_error'
        assert SECRET not in denied.stderr and not (tmp_path/'denied.jsonl').exists()
        echoed=call(base+'/echo-token',tmp_path/'echo.jsonl','--bearer-env','WEB_QUERY_TEST_TOKEN',env=env)
        assert echoed.returncode==2 and json.loads(echoed.stderr)['code']=='credential_in_response'
        assert SECRET not in echoed.stderr+echoed.stdout and not (tmp_path/'echo.jsonl').exists()
        escaped=call(base+'/echo-escaped',tmp_path/'echo-escaped.jsonl','--bearer-env','WEB_QUERY_TEST_TOKEN',env=env)
        assert escaped.returncode==2 and json.loads(escaped.stderr)['code']=='credential_in_response'
        assert SECRET not in escaped.stdout+escaped.stderr and not (tmp_path/'echo-escaped.jsonl').exists()
        preview=call(base+'/preview-sensitive',tmp_path/'preview.jsonl','--preview','1')
        assert preview.returncode==0 and 'MASK_THIS_SECRET' not in preview.stdout+preview.stderr
        assert json.loads(preview.stdout)['preview'][0]['nested']['api_key']=='[민감정보 숨김]'
        output_record=json.loads((tmp_path/'preview.jsonl').read_text(encoding='utf-8'))
        assert json.loads(preview.stdout)['redacted_fields']==3
        assert output_record['nested']['api_key']=='[민감정보 숨김]'
        assert output_record['nested']['records'][0] == {'password':'[민감정보 숨김]','cursor':'[민감정보 숨김]','value':'normal'}
        assert output_record['id']==1 and output_record['token_count']==7
        assert all(secret not in (tmp_path/'preview.jsonl').read_text(encoding='utf-8') for secret in ('MASK_THIS_SECRET','MASK_PASSWORD','MASK_CURSOR'))
        redirected=call(base+'/redirect',tmp_path/'redirect.jsonl')
        assert redirected.returncode==2 and '/secret' not in [c[0] for c in Handler.calls]
        assert not (tmp_path/'redirect.jsonl').exists()
        unsafe=call(base+'/data?token='+SECRET,tmp_path/'unsafe.jsonl')
        assert unsafe.returncode==2 and SECRET not in unsafe.stdout+unsafe.stderr
        assert json.loads(unsafe.stderr)['code']=='sensitive_parameter'
        before=output.read_bytes()
        existing=call(base+'/data',output)
        assert existing.returncode==2 and output.read_bytes()==before
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)


def test_authenticated_transport_is_checked_before_request(tmp_path, monkeypatch, capsys):
    spec=importlib.util.spec_from_file_location('query_get',SCRIPT)
    query=importlib.util.module_from_spec(spec);spec.loader.exec_module(query)
    monkeypatch.setenv('WEB_QUERY_TEST_TOKEN',SECRET)
    def should_not_open(*args, **kwargs):
        raise AssertionError('network must not be attempted')
    monkeypatch.setattr(query.urllib.request, 'build_opener', should_not_open)
    for url in ('http://example.test/data','http://127.0.0.1.example.test/data'):
        result=query.main(['--url',url,'--output',str(tmp_path/'denied.jsonl'),'--bearer-env','WEB_QUERY_TEST_TOKEN'])
        out=capsys.readouterr()
        assert result==2 and json.loads(out.err)['code']=='insecure_transport'
        assert SECRET not in out.err+out.out and not (tmp_path/'denied.jsonl').exists()


def test_https_and_ipv6_loopback_auth_are_allowed_without_external_network(tmp_path, monkeypatch, capsys):
    spec=importlib.util.spec_from_file_location('query_get',SCRIPT)
    query=importlib.util.module_from_spec(spec);spec.loader.exec_module(query)
    monkeypatch.setenv('WEB_QUERY_TEST_TOKEN',SECRET)
    observed=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):return b'{"data":[{"id":42}]}'
    class FakeOpener:
        def open(self,request,timeout):
            observed.append((request.full_url,request.get_header('Authorization')))
            return Response()
    monkeypatch.setattr(query.urllib.request, 'build_opener', lambda *args:FakeOpener())
    for i,url in enumerate(('https://example.test/data','http://[::1]:10000/data')):
        output=tmp_path/f'allowed-{i}.jsonl'
        result=query.main(['--url',url,'--output',str(output),'--bearer-env','WEB_QUERY_TEST_TOKEN','--page-size','2'])
        out=capsys.readouterr()
        assert result==0 and json.loads(out.out)['complete'] is True
        assert json.loads(output.read_text(encoding='utf-8'))=={'id':42}
        assert SECRET not in out.err+out.out
    assert len(observed)==2 and all(header=='Bearer '+SECRET for _,header in observed)
