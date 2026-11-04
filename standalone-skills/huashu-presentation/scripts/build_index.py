#!/usr/bin/env python3
"""Create a Korean one-slide-at-a-time shell from the preserved Huashu shell."""
from pathlib import Path
import argparse
import hashlib
import html
import json
import re

SKILL = Path(__file__).resolve().parents[1]


def build(slides, output, width=1920, height=1080, title='발표자료'):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('기존 발표 화면을 덮어쓰지 않습니다. 새 출력 경로를 지정하세요.')
    if output.suffix.lower() not in {'.html','.htm'}:
        raise ValueError('출력은 새 HTML 파일이어야 합니다.')
    if width<320 or height<180:
        raise ValueError('실제 슬라이드 폭과 높이를 지정하세요.')
    items=[]
    for value in slides:
        source=Path(value).resolve(strict=True)
        if not source.is_file() or source.suffix.lower() not in {'.html','.htm'} or not source.is_relative_to(output.parent):
            raise ValueError('각 슬라이드는 발표 화면 폴더 안의 로컬 HTML이어야 합니다.')
        items.append({'file':source.relative_to(output.parent).as_posix(),'label':html.escape(source.stem)})
    if not items:
        raise ValueError('--slide로 최소 한 장을 지정하세요.')
    original=SKILL/'upstream/assets/deck_index.html'
    provenance=json.loads((SKILL/'upstream/provenance.json').read_text(encoding='utf-8'))
    expected=next(v['sha256'] for v in provenance['files'] if v['path']=='assets/deck_index.html')
    if hashlib.sha256(original.read_bytes()).hexdigest()!=expected:
        raise ValueError('보존된 Huashu 모음 화면의 해시가 출처 기록과 다릅니다.')
    source=original.read_text(encoding='utf-8')
    manifest=json.dumps(items,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e')
    source,count=re.subn(r'window\.DECK_MANIFEST\s*=\s*\[.*?\];',lambda _:f'window.DECK_MANIFEST = {manifest};',source,count=1,flags=re.S)
    if count!=1:
        raise ValueError('원본의 슬라이드 목록 위치를 찾지 못했습니다.')
    source=source.replace('window.DECK_WIDTH = 1920;',f'window.DECK_WIDTH = {width};')
    source=source.replace('window.DECK_HEIGHT = 1080;',f'window.DECK_HEIGHT = {height};')
    source=source.replace('// window.DECK_OVERVIEW = \'grid\';',"window.DECK_OVERVIEW = 'grid';")
    source=source.replace('<html lang="zh-CN">','<html lang="ko">')
    source=source.replace('<title>Deck · Multi-file Slide Index</title>',f'<title>{html.escape(title)}</title>')
    source=source.replace('▶ 开始演示','발표로 돌아가기').replace('⊞ 概览','전체 보기')
    source=source.replace('Overview · 点击任意页进入演示','전체 보기: 장을 선택하면 발표로 돌아갑니다')
    source=source.replace('<div class="nav-zone left"  id="navL"><div class="nav-hint">‹</div></div>',
        '<button type="button" class="nav-zone left" id="navL" aria-label="이전 장">이전</button>')
    source=source.replace('<div class="nav-zone right" id="navR"><div class="nav-hint">›</div></div>',
        '<button type="button" class="nav-zone right" id="navR" aria-label="다음 장">다음</button>')
    source=source.replace('<script>', '<script>\n// Korean presentation adapter: default to one visible slide.\nif (!/^#\\d+$/.test(location.hash)) history.replaceState(null, "", "#1");',1)
    print_frames="deck.forEach(item => { const f = document.createElement('iframe'); f.src = item.file; printStack.appendChild(f); });"
    source=source.replace("printStack.innerHTML = ''; "+print_frames,"",1)
    source=source.replace("printStack.innerHTML = ''; printStack.style.display = 'none'","printStack.style.display = 'none'",1)
    source=source.replace("window.addEventListener('beforeprint',",print_frames+"\n  window.addEventListener('beforeprint',",1)
    # These changes affect only the newly generated presentation shell, not the
    # archived upstream source or the content HTML / PPTX conversion engine.
    overrides=f'''<style>
html,body{{font-family:"Malgun Gothic","맑은 고딕",sans-serif}}
body[data-mode="present"] #ov-grid,body[data-mode="present"] #ov-gallery{{display:none}}
.nav-zone{{top:auto;bottom:20px;width:68px;height:38px;border:0;border-radius:6px;background:#142b3a;color:white;font-family:inherit;font-size:16px}}
.nav-zone.left{{left:calc(50% - 76px)}}.nav-zone.right{{right:calc(50% - 76px)}}
.overview-btn{{opacity:1}}.counter{{opacity:1}}
@media print{{@page{{size:{width}px {height}px;margin:0}}.print-stack iframe{{width:{width}px;height:{height}px;break-after:page}}}}
</style>'''
    source=source.replace('</head>',overrides+'\n</head>',1)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8',newline='\n') as destination:
        destination.write(source)
    return {'ok':True,'outputPath':str(output),'slideCount':len(items),'defaultView':'one-slide',
        'upstreamSourceModified':False,'visualReview':'not_verified',
        'features':['previous/next buttons','left/right keys','page counter','separate overview','all-slide print']}


def main():
    parser=argparse.ArgumentParser(description='장별 HTML을 한 화면 한 장씩 넘기는 한국어 발표 화면으로 묶습니다.')
    parser.add_argument('--slide',action='append',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--width',type=int,default=1920)
    parser.add_argument('--height',type=int,default=1080)
    parser.add_argument('--title',default='발표자료')
    args=parser.parse_args()
    try:
        result=build(args.slide,args.output,args.width,args.height,args.title)
    except Exception as error:
        result={'ok':False,'error':str(error)}
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
