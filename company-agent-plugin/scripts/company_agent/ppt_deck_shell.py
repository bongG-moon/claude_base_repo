"""Shared offline presentation controls around an already composed slide scene.

The shell owns navigation and text editing, not slide colors, type or placement.
An edited download is a new HTML source. Its native scene remains a validated
baseline for the edit importer, but stale reusable-template metadata is removed.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import math
from html.parser import HTMLParser


CSS = r"""
html,body{height:100%;margin:0}body.deck-shell{overflow:hidden;background:#e7e8eb}
#deck-workspace{position:absolute;inset:0 0 68px;display:flex;min-width:0}
#deck-stage{flex:1;position:relative;min-width:0;min-height:0;overflow:hidden}
#deck-holder{position:absolute;left:50%;top:50%;width:var(--deck-w);height:var(--deck-h);transform:translate(-50%,-50%) scale(var(--deck-scale,1));transform-origin:center;box-shadow:0 6px 30px #0002}
#deck-slides{position:relative;width:100%;height:100%}
#deck-slides>.ppt-page{position:absolute;inset:0;width:100%;height:100%;margin:0;border:0;box-shadow:none;overflow:hidden;pointer-events:none;container-type:inline-size}
#deck-slides>.ppt-page>.ppt-slide{display:none;position:relative;width:100%;height:100%;aspect-ratio:auto;pointer-events:auto}
#deck-slides>.ppt-page>.ppt-slide.active{display:block}
#deck-slides .data-notes{display:none}
#deck-toolbar,#deck-notes,#deck-overview,#deck-toast{font:14px/1.5 'Malgun Gothic','Segoe UI',sans-serif;color:#333;box-sizing:border-box}
#deck-toolbar{position:absolute;inset:auto 0 0;min-height:68px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 18px;background:#fafafa;border-top:1px solid #ccc;z-index:50}
#deck-toolbar .deck-group{display:flex;align-items:center;gap:7px;min-width:0}
#deck-toolbar button,#deck-overview button,#deck-notes button{font:inherit;color:inherit;cursor:pointer;background:#fff;border:1px solid #c8c8c8;border-radius:5px;padding:6px 10px;min-height:34px}
#deck-toolbar button:disabled{opacity:.35;cursor:default}
#deck-toolbar button[aria-pressed=true]{background:#303030;color:white;border-color:#303030}
#deck-toolbar button:focus-visible,#deck-overview button:focus-visible,#deck-notes button:focus-visible{outline:3px solid #555;outline-offset:3px}
#deck-name{font-weight:700;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#deck-position{min-width:54px;text-align:center;font-variant-numeric:tabular-nums}
#deck-nav-pages{display:flex;gap:4px;max-width:240px;overflow-x:auto;padding:2px}
#deck-nav-pages button{min-width:30px;padding:5px 7px}
#deck-dirty{font-size:12px;color:#666;white-space:nowrap}
#deck-notes{display:none;width:340px;flex:none;overflow:auto;padding:20px;background:#fafafa;border-left:1px solid #ccc}
body.deck-notes-open #deck-notes{display:block}
#deck-notes h2{font-size:19px;margin:14px 0}#deck-note-text{white-space:pre-wrap;overflow-wrap:anywhere}
#deck-note-source{font-size:12px;overflow-wrap:anywhere;color:#666;border-top:1px solid #ddd;padding-top:12px}
#deck-notes-close{float:right}#deck-note-extra .data-notes{display:block;padding:8px 0;background:transparent}
#deck-notice{font-size:12px;margin-top:24px;padding-top:14px;border-top:1px solid #ddd;color:#555;white-space:pre-wrap}
#deck-overview{position:fixed;inset:0;display:none;background:#edededf7;padding:24px;overflow:auto;z-index:100}
#deck-overview.is-open{display:block}.deck-overview-bar{max-width:1400px;margin:0 auto 18px;display:flex;justify-content:space-between;align-items:center;gap:20px}
.deck-overview-bar h2{font-size:23px;margin:0}#deck-overview-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:20px;max-width:1400px;margin:auto}
#deck-overview .deck-thumb{padding:0;text-align:left;overflow:hidden;border-radius:6px;min-width:0}
#deck-overview .deck-thumb.selected{outline:3px solid #555;outline-offset:3px}
.deck-thumb-stage{position:relative;width:100%;aspect-ratio:var(--deck-ratio);overflow:hidden;pointer-events:none;background:#fff}
.deck-thumb-stage>.ppt-page{position:absolute;inset:0;margin:0;border:0;box-shadow:none;overflow:hidden;transform-origin:top left;container-type:inline-size}
.deck-thumb-stage .ppt-slide{display:block!important;position:relative;width:100%;height:100%;aspect-ratio:auto}
.deck-thumb-stage .data-notes{display:none}
.deck-thumb-caption{display:flex;justify-content:space-between;gap:12px;padding:9px 12px;border-top:1px solid #ddd;font-size:13px}
.deck-thumb-caption strong{white-space:nowrap}
#deck-toast{position:fixed;left:50%;bottom:84px;transform:translateX(-50%);max-width:85vw;padding:10px 16px;background:#222;color:#fff;border-radius:6px;opacity:0;pointer-events:none;z-index:150;transition:opacity .12s}
#deck-toast.visible{opacity:1}.deck-sr-only{position:absolute;left:-10000px;width:1px;height:1px;overflow:hidden}
body.deck-editing #deck-slides [data-edit]{outline:1px dashed #888;outline-offset:2px;cursor:text}
body.deck-editing #deck-slides [data-edit]:focus{outline:2px solid #555}
body.deck-chrome-hidden #deck-toolbar{display:none}body.deck-chrome-hidden #deck-workspace{bottom:0}
@media(max-width:1150px){#deck-name{display:none}#deck-toolbar{gap:6px;padding:8px}#deck-toolbar .deck-group{gap:5px}}
@media(max-width:850px){#deck-toolbar{flex-wrap:wrap;justify-content:center}#deck-toolbar .deck-tools{flex-wrap:wrap;justify-content:center}#deck-notes{position:absolute;right:0;top:0;bottom:0;width:min(340px,90vw);z-index:40;box-shadow:-5px 0 20px #0002}#deck-dirty{display:none}}
@media(max-width:600px){#deck-nav-pages{display:none}#deck-overview{padding:18px 12px}}
@media(prefers-reduced-motion:reduce){#deck-toast{transition:none}}
@media print{
  html,body.deck-shell{height:auto!important;width:auto!important;overflow:visible!important;background:white!important}
  #deck-toolbar,#deck-overview,#deck-notes,#deck-toast,#deck-status{display:none!important}
  #deck-workspace,#deck-stage,#deck-holder,#deck-slides{position:static!important;display:block!important;width:auto!important;height:auto!important;inset:auto!important;transform:none!important;overflow:visible!important;box-shadow:none!important}
  #deck-slides>.ppt-page{position:relative!important;display:block!important;inset:auto!important;width:var(--deck-print-w)!important;height:var(--deck-print-h)!important;margin:0!important;break-after:page;page-break-after:always;box-shadow:none!important}
  #deck-slides>.ppt-page:last-child{break-after:auto;page-break-after:auto}
  #deck-slides>.ppt-page>.ppt-slide{display:block!important;width:100%!important;height:100%!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  #deck-slides [data-edit]{outline:none!important}
}
"""


SCRIPT = r"""(() => {
'use strict';
const $ = selector => document.querySelector(selector);
const slides = [...document.querySelectorAll('#deck-slides > .ppt-page > .ppt-slide')];
const pages = slides.map(slide => slide.parentElement);
if (!slides.length) return;
const config = JSON.parse($('#deck-config').textContent);
const ids = slides.map((slide, i) => slide.dataset.slide || `P${String(i + 1).padStart(2, '0')}`);
const stage = $('#deck-stage');
let current = 0, editing = false, dirty = false, toastTimer;
let edited = document.body.dataset.pptEdited === '1';
const title = i => (slides[i].querySelector('[data-deck-title]')?.textContent || slides[i].dataset.title || `${i + 1}장`).trim();
function toast(text) {
  $('#deck-toast').textContent = text; $('#deck-toast').classList.add('visible');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#deck-toast').classList.remove('visible'), 3600);
}
function fit() {
  const toolbarHeight = document.body.classList.contains('deck-chrome-hidden') ? 0 : $('#deck-toolbar').offsetHeight;
  $('#deck-workspace').style.bottom = toolbarHeight + 'px';
  $('#deck-toast').style.bottom = (toolbarHeight + 16) + 'px';
  const r = stage.getBoundingClientRect(), pad = r.width < 700 ? 12 : 32;
  $('#deck-holder').style.setProperty('--deck-scale', String(Math.max(.02, Math.min((r.width-pad)/config.width, (r.height-pad)/config.height))));
  document.querySelectorAll('.deck-thumb-stage').forEach(el => {
    el.firstElementChild.style.transform = `scale(${el.clientWidth/config.width})`;
  });
}
function updateNotes() {
  const value = config.notes[ids[current]] || {};
  $('#deck-note-title').textContent = title(current);
  $('#deck-note-text').textContent = value.text || '발표 메모가 없습니다.';
  $('#deck-note-source').textContent = value.source ? '출처: ' + value.source : '';
  const extra = $('#deck-note-extra'); extra.replaceChildren();
  pages[current].querySelectorAll('.data-notes').forEach(node => {
    const clone = node.cloneNode(true); clone.open = true;
    clone.querySelectorAll('[id],[contenteditable]').forEach(n => {n.removeAttribute('id');n.removeAttribute('contenteditable');});
    extra.append(clone);
  });
}
function show(index, writeHash = true) {
  if (!Number.isInteger(index) || index < 0 || index >= slides.length) return;
  current = index;
  slides.forEach((slide, i) => {slide.classList.toggle('active', i===index);slide.setAttribute('aria-hidden',String(i!==index));});
  $('#deck-position').textContent = `${index+1} / ${slides.length}`;
  $('#deck-prev').disabled = index === 0; $('#deck-next').disabled = index === slides.length-1;
  document.querySelectorAll('#deck-nav-pages [data-goto]').forEach(button => {
    const selected = button.dataset.goto === ids[index]; button.setAttribute('aria-pressed', String(selected));
    if (selected) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
  });
  $('#deck-status').textContent = `${index+1}페이지. ${title(index)}`; updateNotes();
  if (writeHash) {try {history.replaceState(null,'','#'+ids[index]);} catch (_) {}}
}
function toggleNotes() {
  const active = document.body.classList.toggle('deck-notes-open');
  $('#deck-notes-toggle').setAttribute('aria-pressed',String(active)); $('#deck-notes').setAttribute('aria-hidden',String(!active)); fit();
}
function closeOverview() {
  $('#deck-workspace').inert = false; $('#deck-toolbar').inert = false;
  $('#deck-overview').classList.remove('is-open'); $('#deck-overview').setAttribute('aria-hidden','true'); $('#deck-overview-toggle').focus();
}
function openOverview() {
  const grid = $('#deck-overview-grid'); grid.replaceChildren();
  pages.forEach((page,i) => {
    const button = document.createElement('button'); button.type='button'; button.className='deck-thumb'+(i===current?' selected':'');
    button.setAttribute('aria-label',`${i+1}페이지 ${title(i)}로 이동`);
    const preview = document.createElement('div'); preview.className='deck-thumb-stage';
    const clone = page.cloneNode(true); clone.style.width=config.width+'px';clone.style.height=config.height+'px';clone.removeAttribute('id');
    clone.querySelectorAll('[id],[contenteditable],[tabindex]').forEach(n=>{n.removeAttribute('id');n.removeAttribute('contenteditable');n.removeAttribute('tabindex');});
    clone.querySelector('.ppt-slide').classList.add('active'); preview.append(clone);
    const caption=document.createElement('div');caption.className='deck-thumb-caption';
    const text=document.createElement('span');text.textContent=title(i);const number=document.createElement('strong');number.textContent=`${i+1} / ${slides.length}`;
    caption.append(text,number);button.append(preview,caption);button.addEventListener('click',()=>{show(i);closeOverview();});grid.append(button);
  });
  $('#deck-workspace').inert=true;$('#deck-toolbar').inert=true;
  $('#deck-overview').classList.add('is-open');$('#deck-overview').setAttribute('aria-hidden','false');fit();$('#deck-overview-close').focus();
}
function toggleEditing() {
  editing=!editing;document.body.classList.toggle('deck-editing',editing);
  document.querySelectorAll('#deck-slides [data-edit]').forEach(node=>{
    if(editing){node.setAttribute('contenteditable','true');node.setAttribute('spellcheck','false');}
    else node.removeAttribute('contenteditable');
  });
  $('#deck-edit-toggle').setAttribute('aria-pressed',String(editing));$('#deck-edit-toggle').textContent=editing?'편집 종료':'문구 편집';
  toast(editing?'점선 안의 문구를 수정하세요. 수정본을 저장하면 편집 내용을 보관할 수 있습니다.':'발표 모드로 돌아왔습니다.');
}
function changed() {
  dirty=true;edited=true;document.body.dataset.pptEdited='1';$('#deck-dirty').textContent='미저장 변경';updateNotes();
}
function saveHTML() {
  const root=document.documentElement.cloneNode(true), body=root.querySelector('body');
  body.classList.remove('deck-editing','deck-notes-open','deck-chrome-hidden');
  root.querySelectorAll('[contenteditable],[inert]').forEach(n=>{n.removeAttribute('contenteditable');n.removeAttribute('inert');});
  root.querySelectorAll('#deck-slides>.ppt-page>.ppt-slide').forEach((slide,i)=>{slide.classList.toggle('active',i===0);slide.setAttribute('aria-hidden',String(i!==0));});
  root.querySelector('#deck-overview').classList.remove('is-open');root.querySelector('#deck-overview').setAttribute('aria-hidden','true');root.querySelector('#deck-overview-grid').replaceChildren();
  root.querySelector('#deck-notes').setAttribute('aria-hidden','true');root.querySelector('#deck-note-extra').replaceChildren();
  root.querySelector('#deck-toast').classList.remove('visible');root.querySelector('#deck-toast').textContent='';root.querySelector('#deck-dirty').textContent='';
  root.querySelector('#deck-edit-toggle').setAttribute('aria-pressed','false');root.querySelector('#deck-edit-toggle').textContent='문구 편집';root.querySelector('#deck-notes-toggle').setAttribute('aria-pressed','false');
  if(edited){
    root.querySelectorAll('#company-agent-ppt-template').forEach(n=>n.remove());
    body.dataset.pptEdited='1';root.querySelector('#deck-notice').textContent='HTML 수정본입니다. PPTX 제작에는 이 파일로 변환 검토를 다시 진행합니다.';
  }
  const blob=new Blob(['<!doctype html>\n'+root.outerHTML],{type:'text/html;charset=utf-8'});
  const url=URL.createObjectURL(blob), link=document.createElement('a');link.href=url;
  link.download=(document.title.replace(/[\\/:*?"<>|]/g,'_')||'발표자료')+'_수정본.html';link.click();setTimeout(()=>URL.revokeObjectURL(url),5000);
  dirty=false;$('#deck-dirty').textContent='';toast(edited?'HTML 수정본입니다. PPTX 제작에는 이 파일로 변환 검토를 다시 진행합니다.':'독립 HTML 발표본을 저장했습니다.');
}
async function fullscreen(){try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch(_){toast('이 환경에서는 전체 화면이 제한될 수 있습니다.');}fit();}
ids.forEach((id,i)=>{const b=document.createElement('button');b.type='button';b.dataset.goto=id;b.textContent=String(i+1);b.setAttribute('aria-label',`${i+1}페이지`);b.addEventListener('click',()=>show(i));$('#deck-nav-pages').append(b);});
$('#deck-prev').addEventListener('click',()=>show(current-1));$('#deck-next').addEventListener('click',()=>show(current+1));
$('#deck-notes-toggle').addEventListener('click',toggleNotes);$('#deck-notes-close').addEventListener('click',toggleNotes);
$('#deck-overview-toggle').addEventListener('click',openOverview);$('#deck-overview-close').addEventListener('click',closeOverview);
$('#deck-edit-toggle').addEventListener('click',toggleEditing);$('#deck-save').addEventListener('click',saveHTML);
$('#deck-print').addEventListener('click',()=>window.print());$('#deck-fullscreen').addEventListener('click',fullscreen);
$('#deck-help').addEventListener('click',()=>toast('← → 이동 / 1~9 바로가기 / Home End / N 메모 / G 전체 보기 / E 편집 / F 전체 화면 / H 도구 숨김'));
document.addEventListener('keydown',event=>{
  const modal=$('#deck-overview').classList.contains('is-open');
  if(event.key==='Escape'){if(modal)closeOverview();else if(editing){event.target.blur();toggleEditing();}else if(document.body.classList.contains('deck-notes-open'))toggleNotes();else if(document.body.classList.contains('deck-chrome-hidden')){document.body.classList.remove('deck-chrome-hidden');fit();}return;}
  if(modal){if(event.key==='Tab'){const list=[...$('#deck-overview').querySelectorAll('button')],first=list[0],last=list.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}return;}
  if(event.target.closest('[contenteditable="true"],input,textarea,select')||event.ctrlKey||event.metaKey||event.altKey)return;
  const key=event.key.toLowerCase();
  if(['arrowright','pagedown',' '].includes(key)){event.preventDefault();show(current+1);}
  else if(['arrowleft','pageup'].includes(key)){event.preventDefault();show(current-1);}
  else if(key==='home'){event.preventDefault();show(0);}else if(key==='end'){event.preventDefault();show(slides.length-1);}
  else if(/^[1-9]$/.test(key)){event.preventDefault();show(Number(key)-1);}
  else if(key==='n')toggleNotes();else if(key==='g')openOverview();else if(key==='e')toggleEditing();else if(key==='f')fullscreen();
  else if(key==='h'){document.body.classList.toggle('deck-chrome-hidden');fit();}
});
$('#deck-slides').addEventListener('input',event=>{if(event.target.closest('[data-edit]'))changed();});
$('#deck-slides').addEventListener('paste',event=>{
  const target=event.target.closest('[data-edit]');if(!editing||!target)return;event.preventDefault();
  const selection=window.getSelection();if(!selection.rangeCount)return;const range=selection.getRangeAt(0);if(!target.contains(range.commonAncestorContainer))return;
  range.deleteContents();const node=document.createTextNode(event.clipboardData.getData('text/plain'));range.insertNode(node);range.setStartAfter(node);range.collapse(true);selection.removeAllRanges();selection.addRange(range);changed();
});
let touch;
stage.addEventListener('pointerdown',event=>{if(event.pointerType==='touch'&&!editing)touch={x:event.clientX,y:event.clientY};});
stage.addEventListener('pointerup',event=>{if(!touch)return;const dx=event.clientX-touch.x,dy=event.clientY-touch.y;touch=null;if(Math.abs(dx)>60&&Math.abs(dx)>Math.abs(dy)*1.5)show(current+(dx<0?1:-1));});
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
window.addEventListener('resize',fit);new ResizeObserver(fit).observe(stage);
window.addEventListener('hashchange',()=>{const i=ids.indexOf(location.hash.slice(1));if(i>=0)show(i,false);});
const start=ids.indexOf(location.hash.slice(1));show(start>=0?start:0,false);fit();document.fonts?.ready.then(fit);
window.deck={show,ids:ids.slice(),fit,save:saveHTML,get current(){return ids[current];},version:'shared-1'};
})();"""


class _Slides(HTMLParser):
    def __init__(self):
        super().__init__()
        self.count = 0

    def handle_starttag(self, tag, attrs):
        if 'ppt-slide' in dict(attrs).get('class', '').split():
            self.count += 1


def render_shell(*, title, slides_html, width, height, notes, extra_head='', metadata_html='', design_css=''):
    """Wrap validated, local slide markup; inputs other than title/notes are code-owned."""
    if (any(type(v) not in (int, float) or not math.isfinite(v) or not 100 <= v <= 10000
            for v in (width, height)) or not isinstance(slides_html, str)):
        raise ValueError('발표 화면 크기와 본문을 확인해 주세요.')
    parsed = _Slides(); parsed.feed(slides_html); parsed.close()
    if not 1 <= parsed.count <= 60:
        raise ValueError('HTML 발표본은 1~60장으로 작성해 주세요.')
    if not isinstance(notes, dict):
        raise ValueError('발표 메모는 장 ID별로 작성해 주세요.')
    normalized = {}
    for key, value in notes.items():
        if not isinstance(key, str) or not isinstance(value, (str, dict)):
            raise ValueError('발표 메모를 확인해 주세요.')
        entry = {'text': value} if isinstance(value, str) else value
        if any(not isinstance(entry.get(k, ''), str) for k in ('text', 'source')):
            raise ValueError('발표 메모와 출처는 일반 글자로 작성해 주세요.')
        normalized[key] = {k: entry.get(k, '') for k in ('text', 'source')}
    config = json.dumps({'width': width, 'height': height, 'notes': normalized}, ensure_ascii=True, separators=(',', ':'))
    config = config.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    digest = base64.b64encode(hashlib.sha256(SCRIPT.encode('utf-8')).digest()).decode('ascii')
    csp = f"default-src 'none'; script-src 'sha256-{digest}'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"
    style = f'--deck-w:{width}px;--deck-h:{height}px;--deck-ratio:{width}/{height};--deck-print-w:{width/72}in;--deck-print-h:{height/72}in'
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="Content-Security-Policy" content="{html.escape(csp,quote=True)}"><title>{html.escape(str(title))}</title>'
            f'<style>{design_css}\n{CSS}\n@page{{size:{width/72}in {height/72}in;margin:0}}</style>{extra_head}{metadata_html}</head>'
            f'<body class="deck-shell" data-ppt-draft="1" data-ppt-deck="1" style="{style}"><main id="deck-workspace">'
            f'<div id="deck-stage" aria-label="슬라이드 발표 영역"><div id="deck-holder"><div id="deck-slides">{slides_html}</div></div></div>'
            '<aside id="deck-notes" aria-label="발표 메모" aria-hidden="true"><button id="deck-notes-close" type="button">메모 닫기</button>'
            '<h2 id="deck-note-title"></h2><div id="deck-note-text"></div><p id="deck-note-source"></p><div id="deck-note-extra"></div>'
            '<p id="deck-notice">문구를 편집한 경우 수정본을 저장하세요. PPTX 제작에는 저장한 HTML로 변환 검토를 다시 진행합니다.</p></aside></main>'
            '<nav id="deck-toolbar" aria-label="발표 제어"><div class="deck-group">'
            f'<span id="deck-name">{html.escape(str(title))}</span><button id="deck-prev" type="button" aria-label="이전 페이지">‹</button>'
            f'<span id="deck-position">1 / {parsed.count}</span><button id="deck-next" type="button" aria-label="다음 페이지">›</button>'
            '<div id="deck-nav-pages" aria-label="페이지 바로가기"></div></div><div class="deck-group deck-tools">'
            '<button id="deck-overview-toggle" type="button">전체 보기</button><button id="deck-notes-toggle" type="button" aria-pressed="false">발표 메모</button>'
            '<button id="deck-edit-toggle" type="button" aria-pressed="false">문구 편집</button><button id="deck-save" type="button">수정본 저장</button>'
            '<button id="deck-print" type="button">인쇄</button><button id="deck-fullscreen" type="button">전체 화면</button>'
            '<button id="deck-help" type="button" aria-label="단축키 도움말">?</button><span id="deck-dirty" aria-live="polite"></span></div></nav>'
            '<div id="deck-overview" role="dialog" aria-modal="true" aria-hidden="true" aria-labelledby="deck-overview-title">'
            f'<div class="deck-overview-bar"><h2 id="deck-overview-title">전체 {parsed.count}장</h2><button id="deck-overview-close" type="button">닫기 / Esc</button></div>'
            '<div id="deck-overview-grid"></div></div><div id="deck-toast" role="status"></div><div id="deck-status" class="deck-sr-only" aria-live="polite"></div>'
            f'<script id="deck-config" type="application/json">{config}</script><script>{SCRIPT}</script></body></html>')
