#!/usr/bin/env python3
"""Local adapter for the unmodified Huashu rendered-HTML PPTX engine.

The engine's JS extraction, Builder and text verification are imported unchanged.
This adapter controls inputs, browser selection and new-file output only.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib.metadata
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import sys
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

SKILL = Path(__file__).resolve().parents[1]
ENGINE = SKILL / 'upstream/scripts/pptx_from_rendered.py'
LIMITS = [
    '원본 Huashu 렌더 좌표 변환 엔진을 사용하며 변환 알고리즘은 수정하지 않았습니다.',
    '표는 개별 텍스트와 도형이며 네이티브 표나 데이터 차트를 생성하지 않습니다.',
    'SVG와 canvas는 PNG이며 내부 텍스트와 경로의 개별 편집을 보장하지 않습니다.',
    '텍스트 대조 통과는 실제 PowerPoint의 줄바꿈, 가림 및 편집 저장 성공을 뜻하지 않습니다.',
]

# The original seq is shared by SVG and canvas and only advances for nodes
# reached by its walk(). Mirror those traversal gates when binding captures;
# a tag-specific nth() or an unfiltered querySelectorAll() is not equivalent.
RASTER_TARGETS = r"""(slide) => {
  const inline = new Set(['em','b','i','strong','span','small','br','sup','sub','a','code','mark']);
  const targets = [];
  const walk = (element, parentOpacity = 1) => {
    const style = getComputedStyle(element);
    const opacity = parentOpacity * (parseFloat(style.opacity) || 0);
    if (style.display === 'none' || style.visibility === 'hidden' || opacity === 0) return;
    const tag = element.tagName.toLowerCase();
    if (tag === 'img') return;
    if (tag === 'svg' || tag === 'canvas') { targets.push(element); return; }
    const hasText = element.innerText && element.innerText.trim().length > 0;
    const onlyInline = [...element.children].every(child => inline.has(child.tagName.toLowerCase()));
    if (hasText && onlyInline) return;
    for (const child of element.children) walk(child, opacity);
  };
  for (const child of slide.children) walk(child);
  return targets;
}"""


async def capture_rasters(slide, measured_page, asset_dir, prefix):
    """Bind the engine's shared sequence to actual emitted DOM elements."""
    elements = [element for element in measured_page['els'] if element['kind']=='svg']
    if not elements:
        return
    targets = await slide.evaluate_handle(RASTER_TARGETS)
    try:
        count = await targets.evaluate('(items) => items.length')
        if count != len(elements):
            raise ValueError('SVG/canvas 캡처 대상과 원본 추출 결과가 다릅니다. HTML 변경 여부를 확인하세요.')
        for element in elements:
            handle = await targets.get_property(str(element['seq']))
            try:
                node = handle.as_element()
                if node is None or await node.evaluate('(node) => node.tagName.toLowerCase()') != element['tagName']:
                    raise ValueError('SVG/canvas 순번이 실제 캡처 대상과 일치하지 않습니다.')
                destination = asset_dir/f'{prefix}_{element["tagName"]}{element["seq"]}.png'
                await node.screenshot(path=str(destination), omit_background=True)
                element['file'] = str(destination)
            finally:
                await handle.dispose()
    finally:
        await targets.dispose()


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024), b''):
            value.update(part)
    return value.hexdigest()


def local_file(value, suffixes=None):
    raw = str(value)
    if raw.startswith(('\\\\', '//')) or re.match(r'^[a-zA-Z]+://', raw):
        raise ValueError('로컬 파일 경로를 지정하세요. 네트워크 경로는 사용하지 않습니다.')
    path = Path(raw).expanduser().resolve(strict=True)
    if not path.is_file() or (suffixes and path.suffix.lower() not in suffixes):
        raise ValueError(f'지원하는 입력 파일이 아닙니다: {path.name}')
    return path


def load_engine():
    provenance = json.loads((SKILL/'upstream/provenance.json').read_text(encoding='utf-8'))
    expected = next(v['sha256'] for v in provenance['files'] if v['path']=='scripts/pptx_from_rendered.py')
    if digest(ENGINE) != expected:
        raise ValueError('보존된 Huashu 엔진의 해시가 출처 기록과 다릅니다.')
    spec = importlib.util.spec_from_file_location('huashu_original_rendered_engine', ENGINE)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    return engine


def dependencies():
    versions = {}
    for name in ['playwright','python-pptx','Pillow']:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    missing = [name for name,value in versions.items() if value is None]
    if missing:
        raise RuntimeError('필요한 Python 패키지가 없습니다: '+', '.join(missing)+'. requirements.txt를 확인하세요.')
    # Import transitive dependencies too; installed distribution metadata alone
    # does not establish that the runtime (e.g. greenlet) can be imported.
    import PIL.Image
    import pptx
    import playwright.async_api
    return versions


async def runtime_browser(explicit):
    from playwright.async_api import async_playwright
    async with async_playwright() as playwright:
        path = local_file(explicit) if explicit else Path(playwright.chromium.executable_path)
        if not path.is_file():
            raise RuntimeError('기존 Chromium/Chrome/Edge 실행 파일을 --browser로 지정하세요. 자동 다운로드하지 않습니다.')
        return str(path)


async def measure(engine, sources, browser_path, selector, asset_dir, scale, hashes, evidence):
    from playwright.async_api import async_playwright
    pages = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=browser_path, headless=True)
        try:
            evidence['browserVersion'] = browser.version
            for source_index, source in enumerate(sources):
                blocked, errors, failures = [], [], []
                context = await browser.new_context(viewport={'width':1920,'height':1080},
                    device_scale_factor=scale, offline=True, service_workers='block', accept_downloads=False)
                root = source.parent

                async def route(request_route):
                    url = request_route.request.url
                    parsed = urlsplit(url)
                    if parsed.scheme in {'http','https','ws','wss','ftp'}:
                        blocked.append(url)
                        await request_route.abort()
                    elif parsed.scheme == 'file':
                        file = Path(url2pathname(parsed.path)).resolve()
                        if parsed.netloc or not file.is_relative_to(root):
                            blocked.append(url)
                            await request_route.abort()
                        else:
                            if file.is_file():
                                hashes.setdefault(str(file), digest(file))
                            await request_route.continue_()
                    else:
                        await request_route.continue_()

                await context.route('**/*', route)
                await context.route_web_socket('**/*', lambda socket:socket.close())
                page = await context.new_page()
                page.on('pageerror', lambda error:errors.append(str(error)))
                page.on('requestfailed', lambda request:failures.append({'url':request.url,'error':request.failure}))
                await page.goto(source.as_uri(), wait_until='load', timeout=30000)
                await page.wait_for_timeout(2500)  # Same settle interval as original render().
                await page.evaluate('document.fonts.ready')
                if blocked or errors or failures:
                    evidence['inputIssues'] = {'source':str(source),'blockedRequests':blocked,'scriptErrors':errors,'failedRequests':failures}
                    raise ValueError('HTML 자원 또는 스크립트 오류가 있습니다. 입력 폴더 안의 로컬 자원으로 작성하세요.')
                selected = page.locator(selector)
                count = await selected.count()
                if not count or count > 200:
                    raise ValueError(f'선택자가 1~200개의 슬라이드를 가리켜야 합니다: {selector}')
                measured = await page.evaluate(engine.JS, selector)
                for index, measured_page in enumerate(measured):
                    if measured_page['w'] <= 0 or measured_page['h'] <= 0 or not measured_page['els']:
                        raise ValueError('숨겨져 있거나 비어 있는 장이 있습니다. 장별 HTML 또는 모든 장이 보이는 원본을 사용하세요.')
                    await capture_rasters(selected.nth(index),measured_page,asset_dir,
                        f's{source_index+1:03d}_p{index+1:03d}')
                    for element in measured_page['els']:
                        if element['kind'] == 'img':
                            src = element.get('src') or ''
                            if not src or urlsplit(src).scheme or src.startswith(('//','\\\\')):
                                raise ValueError('이미지는 입력 HTML 폴더 안의 상대 파일 경로여야 합니다. data URI 및 원격 이미지는 원본 엔진에서 지원하지 않습니다.')
                            image = (root/unquote(src)).resolve(strict=True)
                            if not image.is_relative_to(root) or not image.is_file():
                                raise ValueError('이미지 파일이 입력 HTML 폴더 밖에 있습니다.')
                            hashes.setdefault(str(image), digest(image))
                            element['file'] = str(image)
                    if pages and (abs(measured_page['w']-pages[0]['w'])>.5 or abs(measured_page['h']-pages[0]['h'])>.5):
                        raise ValueError('모든 장의 폭과 높이를 동일하게 맞추세요.')
                    pages.append(measured_page)
                await context.close()
        finally:
            await browser.close()
    return pages


def run(args):
    result = {'ok':False,'renderer':'huashu-rendered-html-original','limits':LIMITS,
              'visualReview':'not_verified','editabilityReview':'not_verified'}
    hashes = {}
    try:
        result['dependencies'] = dependencies()
        browser_path = asyncio.run(runtime_browser(args.browser))
        result['browserExecutable'] = browser_path
        if args.check:
            result.update(ok=True,checkScope='Dependency imports and browser file existence only; no browser launch or export performed')
            return result
        if not args.source or not args.output:
            raise ValueError('--source와 --output을 지정하세요.')
        sources = [local_file(value,{'.html','.htm'}) for value in args.source]
        output = Path(args.output).expanduser().resolve()
        if output.suffix.lower() != '.pptx':
            raise ValueError('출력은 새 .pptx 파일이어야 합니다.')
        if output.exists():
            raise FileExistsError('기존 출력 파일을 덮어쓰지 않습니다. 새 출력 경로를 지정하세요.')
        template = local_file(args.template,{'.pptx'}) if args.template else None
        if args.layout and not template:
            raise ValueError('--layout에는 --template이 필요합니다.')
        for file in [*sources,*([template] if template else [])]:
            hashes[str(file)] = digest(file)
        asset_dir = output.with_name(output.stem+'_assets')
        if asset_dir.exists():
            raise FileExistsError('출력 자원 폴더가 이미 있습니다. 새 출력 경로를 지정하세요.')
        engine = load_engine()
        output.parent.mkdir(parents=True,exist_ok=True)
        asset_dir.mkdir()
        result['assetDirectory'] = str(asset_dir)
        pages = asyncio.run(measure(engine,sources,browser_path,args.selector,asset_dir,args.scale,hashes,result))
        stage = asset_dir/'_staged.pptx'
        config = SimpleNamespace(html=str(sources[0]),out=str(stage),asset_dir=str(asset_dir),
            template=str(template) if template else None,layout=args.layout,skip_class=args.skip_class,
            font_latin=args.font,font_ea=args.font,bg=args.background)
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            engine.Builder(config).run(pages)
            missing = engine.verify_text([page['ref'] for page in pages],str(stage))
        # Exclusive create prevents concurrent outputs from being overwritten.
        with output.open('xb') as destination, stage.open('rb') as source_stream:
            shutil.copyfileobj(source_stream,destination)
        stage.unlink()
        result.update(ok=True,outputPath=str(output),slideCount=len(pages),sourcePaths=[str(p) for p in sources],
            textVerification={'method':'original verify_text against browser innerText','passed':not any(missing),'missingSegmentsBySlide':missing},
            nativeEngineLog=log.getvalue().strip(),warnings=[])
        if any(missing):
            result['warnings'].append('원본 텍스트 대조에서 누락 후보가 있습니다. --skip-class로 제외한 문구와 실제 누락을 구분해 확인하세요.')
    except Exception as error:
        result['error'] = str(error)
    except SystemExit as error:
        result['error'] = str(error)
    finally:
        if hashes:
            result['inputHashes'] = [{'path':path,'before':before,'after':digest(Path(path)) if Path(path).is_file() else None} for path,before in hashes.items()]
            result['inputsPreserved'] = all(v['before']==v['after'] for v in result['inputHashes'])
            if not result['inputsPreserved']:
                result['ok'] = False
                result['error'] = '검사 중 입력 파일 해시가 달라졌습니다.'
    return result


def main():
    parser = argparse.ArgumentParser(description='원본 Huashu 엔진으로 로컬 HTML을 새 PPTX로 내보냅니다.')
    parser.add_argument('--source',action='append',help='저작 HTML 경로. 여러 번 지정하면 입력 순서로 합칩니다.')
    parser.add_argument('--output',help='기존 파일이 없는 PPTX 출력 경로')
    parser.add_argument('--browser',help='기존 Chromium/Chrome/Edge 실행 파일')
    parser.add_argument('--selector',default='.slide')
    parser.add_argument('--font',default='Malgun Gothic')
    parser.add_argument('--template')
    parser.add_argument('--layout')
    parser.add_argument('--skip-class')
    parser.add_argument('--background',help='원본 --bg에 전달할 RGB 6자리')
    parser.add_argument('--scale',type=int,default=3,choices=range(1,5))
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    if args.background and not re.fullmatch(r'#?[0-9a-fA-F]{6}',args.background):
        parser.error('--background는 RGB 6자리여야 합니다.')
    result = run(args)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
