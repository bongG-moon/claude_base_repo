"""Local, static HTML -> native scene. No source scripts, network or new packages.

An explicit supported backend, never a fallback for denied browser/Office access.
Only the shipped DOM measurement script executes in an isolated browser profile.
"""
from __future__ import annotations

import base64
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid
from urllib.parse import unquote, urlsplit

from .business_artifacts import ArtifactError, _source, _image
from .ppt_scene import elements, ink


def browser_path(choice='auto'):
    candidates=[]
    if os.name=='nt':
        paths={'chrome':'Google/Chrome/Application/chrome.exe','edge':'Microsoft/Edge/Application/msedge.exe'}
        # Prefer Chromium's console-compatible build when both are installed.
        # There is no retry/fallback after a browser failure or access denial.
        for name in (('chrome','edge') if choice=='auto' else (choice,)):
            for variable in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'):
                root=os.environ.get(variable)
                if root: candidates.append(Path(root)/paths[name])
    else:
        names=('microsoft-edge',) if choice=='edge' else ('chromium','chromium-browser','google-chrome') if choice=='chrome' else ('chromium','chromium-browser','google-chrome','microsoft-edge')
        candidates=[Path(p) for name in names if (p:=shutil.which(name))]
    return next((p for p in candidates if p.is_file()),None)


class StaticHTML(HTMLParser):
    """Positive tag/attribute allowlist; source CSS cannot execute script under CSP."""
    tags=set('html head body title style section main article header footer aside div span p h1 h2 h3 h4 h5 h6 b strong i em u small sup sub br hr ul ol li table thead tbody tfoot tr th td colgroup col img pre code a figure figcaption'.split())
    void={'br','hr','col','img'}

    def __init__(self,path):
        super().__init__(convert_charrefs=True)
        self.path=path; self.parts=[]; self.dependencies={}; self.skip=False; self.in_style=False; self.scripts_removed=False

    def asset(self,value,suffixes):
        parsed=urlsplit(value)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ArtifactError('html_external_resource','외부 리소스는 가져오지 않습니다. HTML과 같은 폴더 안의 로컬 자료로 준비해 주세요.')
        path=_source(self.path.parent/unquote(parsed.path),suffixes)
        if not path.is_relative_to(self.path.parent):
            raise ArtifactError('html_external_resource','HTML 폴더 밖의 참조 자료는 자동으로 읽지 않습니다.')
        self.dependencies[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if self.skip:
            return
        if tag=='script':
            self.skip=True; self.scripts_removed=True
            return
        if tag in ('iframe','object','embed','video','audio','canvas','svg'):
            raise ArtifactError('html_dynamic_unsupported','SVG·canvas·외부 프레임은 자동 실행하지 않습니다. 정적 HTML 또는 승인된 개별 그림으로 준비해 주세요.')
        if tag=='link':
            if values.get('rel')!='stylesheet': return
            path=self.asset(values.get('href',''),('.css',))
            text=path.read_text(encoding='utf-8-sig')
            if len(text)>512*1024: raise ValueError('stylesheet too large')
            self.check_css(text)
            self.parts.append('<style>'+text.replace('</','<\\/')+'</style>')
            return
        if tag in ('meta','base'): return
        if tag not in self.tags:
            raise ArtifactError('html_element_unsupported','지원하지 않는 HTML 요소가 있습니다. 정적 슬라이드 본문으로 준비해 주세요.')
        clean=[]
        for key,value in attrs:
            if key in ('class','id','style','lang','dir','colspan','rowspan','width','height','alt'):
                if key=='style': self.check_css(value or '')
                clean.append((key,value or ''))
        if tag=='img':
            value=values.get('src','')
            if value.startswith('data:image/'):
                if not re.fullmatch(r'data:image/(png|jpeg);base64,[A-Za-z0-9+/=]+',value) or len(value)>14*1024*1024:
                    raise ArtifactError('invalid_image','HTML 그림은 10MB 이하 PNG/JPEG여야 합니다.')
            else:
                image=_image({'path':str(self.asset(value,('.png','.jpg','.jpeg')))})
                value=f'data:{image["mime"]};base64,{image["data"]}'
            clean.append(('src',value))
        if tag=='style': self.in_style=True
        self.parts.append('<'+tag+''.join(f' {k}="{html.escape(v,quote=True)}"' for k,v in clean)+'>')

    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.void: self.handle_endtag(tag)

    def handle_endtag(self,tag):
        if self.skip:
            if tag=='script': self.skip=False
            return
        if tag=='style': self.in_style=False
        if tag in self.tags and tag not in self.void: self.parts.append(f'</{tag}>')

    def handle_data(self,value):
        if self.skip: return
        if self.in_style: self.check_css(value)
        self.parts.append(value if self.in_style else html.escape(value))

    @staticmethod
    def check_css(value):
        # External/image CSS resources are intentionally not resolved. CSP remains
        # the network boundary even for unfamiliar/escaped CSS spellings.
        if re.search(r'@import|url\s*\(',value,re.I):
            raise ArtifactError('html_external_resource','CSS 외부 참조/배경 그림은 지원하지 않습니다. 같은 폴더 CSS와 실제 img 요소로 준비해 주세요.')


def source_document(value):
    if not isinstance(value,dict) or set(value)-{'path','selector','viewportWidth','browser'} or not isinstance(value.get('path'),str) or value.get('browser','auto') not in ('auto','edge','chrome'):
        raise ArtifactError('invalid_html_source','htmlSource에는 로컬 path와 선택적인 selector, viewportWidth만 지정하세요.')
    source=_source(Path(value['path']),('.html','.htm'))
    if source.stat().st_size>10*1024*1024:
        raise ArtifactError('html_too_large','HTML은 10MB 이하로 준비해 주세요.')
    selector=value.get('selector','.slide')
    if not isinstance(selector,str) or not re.fullmatch(r'[.#]?[A-Za-z][\w-]*(?:[ >]+[.#]?[A-Za-z][\w-]*)*',selector) or len(selector)>100:
        raise ArtifactError('invalid_html_selector','슬라이드 선택자는 .slide, .ppt-slide 또는 main > section 같은 단순 선택자입니다.')
    viewport=value.get('viewportWidth',1920)
    if type(viewport) is not int or not 600<=viewport<=3840:
        raise ArtifactError('invalid_html_source','viewportWidth는 600~3840 정수입니다.')
    raw=source.read_bytes()
    reader=StaticHTML(source)
    reader.feed(raw.decode('utf-8-sig')); reader.close()
    return reader,{'path':str(source),'sha256':hashlib.sha256(raw).hexdigest(),'dependencies':reader.dependencies},selector,viewport


def fingerprint(value):
    return source_document(value)[1]


class _Result(HTMLParser):
    def __init__(self,marker):
        super().__init__(); self.marker=marker; self.active=False; self.value=''
    def handle_starttag(self,tag,attrs):
        if tag=='pre' and dict(attrs).get('id')==self.marker: self.active=True
    def handle_endtag(self,tag):
        if tag=='pre': self.active=False
    def handle_data(self,text):
        if self.active: self.value+=text


def capture(value,palette,font):
    reader,source,selector,viewport=source_document(value)
    browser=browser_path(value.get('browser','auto'))
    if browser is None:
        raise ArtifactError('html_layout_engine_unavailable','정적 HTML 배치 확인에 사용할 Edge/Chrome이 없습니다. 자동 설치나 전체 슬라이드 이미지 대체는 하지 않았습니다.')
    marker='company-layout-'+uuid.uuid4().hex
    script=Path(__file__).with_name('ppt_dom_capture.js').read_text(encoding='utf-8').replace('__COMPANY_OPTIONS__',json.dumps({'selector':selector,'outputId':marker}))
    digest=base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    csp=f"default-src 'none'; script-src 'sha256-{digest}'; style-src 'unsafe-inline'; img-src data:; font-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'"
    content=''.join(reader.parts)
    # Put the restrictive policy before any source markup. The source cannot supply
    # a base, refresh, script, event handler, frame, executable URL or weaker CSP.
    document='<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="'+html.escape(csp,quote=True)+'">'+content+'<script>'+script+'</script>'
    with tempfile.TemporaryDirectory(prefix='company-html-layout-',ignore_cleanup_errors=True) as temp:
        work=Path(temp); path=work/'static.html'; path.write_text(document,encoding='utf-8')
        try:
            process=subprocess.run([str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
                    '--disable-background-networking','--disable-extensions','--disable-component-update','--disable-sync',
                    '--metrics-recording-only','--user-data-dir='+str(work/'profile'),f'--window-size={viewport},1200',
                    '--dump-dom',path.as_uri()],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired:
            raise ArtifactError('html_layout_timeout','HTML 배치 확인 시간이 초과됐습니다. 사용자 브라우저를 종료하거나 다른 접근 경로로 우회하지 않았습니다.') from None
        if process.returncode or len(process.stdout)>32*1024*1024:
            raise ArtifactError('html_layout_failed','로컬 HTML 배치 확인에 실패했습니다. 브라우저 정책/접근 제한을 우회하지 않았습니다.')
        parser=_Result(marker); parser.feed(process.stdout.decode('utf-8-sig')); parser.close()
        if not parser.value:
            raise ArtifactError('html_layout_failed','브라우저의 HTML 배치 결과를 받지 못했습니다. 실행 허용 여부를 확인해 주세요.')
        result=json.loads(parser.value)
    if result.get('error'):
        raise ArtifactError('html_layout_unsupported',result['error'])
    from .ppt_html import frame_size
    frame=frame_size({k:result[k] for k in ('width','height')})
    pages=[]
    for page in result['pages']:
        pages.append({'title':page['title'],'background':ink(page['background'],palette),
                      'elements':elements(page['elements'],frame['width'],frame['height'],palette,embedded=True)})
    if source!=fingerprint(value):
        raise ArtifactError('html_source_changed','HTML 또는 참조 그림이 처리 중 변경되었습니다. 다시 확인해 주세요.')
    warnings=result.get('warnings',[])+['HTML의 CSS 막대·선은 편집 가능한 도형이며 데이터 연결 차트는 아닙니다. 데이터 차트는 chart 개체로 지정하세요.']
    if reader.scripts_removed:
        warnings.append('HTML 스크립트를 실행하지 않고 정적 본문만 옮겼습니다. 스크립트가 생성하는 내용은 포함되지 않습니다.')
    return {**frame,'pages':pages,'font':font,'theme':palette,'source':source,'warnings':warnings}
