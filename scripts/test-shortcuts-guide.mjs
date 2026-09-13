// Headless unit checks only. This does not launch/automate a browser or verify layout.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const guide = new URL('../docs/Claude-Code-필수-사용법.html', import.meta.url);
const html = fs.readFileSync(guide, 'utf8');
assert.match(html, /<html lang="ko">/);
assert.match(html, /<meta charset="utf-8">/);
assert.doesNotMatch(html, /<(?:script|img|iframe)[^>]+src=|<link[^>]+href=|@import|url\(|\bfetch\(|XMLHttpRequest|localStorage|sessionStorage/i);
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
class Element {
  constructor(tag='div') { this.tagName=tag.toUpperCase(); this.children=[]; this.dataset={}; this.attrs={}; this.handlers={}; this.style={}; this.hidden=false; this.open=false; this.value=''; this.textContent=''; this.checked=false; }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(key,value) { this.attrs[key]=value; }
  addEventListener(name,handler) { this.handlers[name]=handler; }
  querySelector(tag) { return this.children.find(child=>child.tagName===tag.toUpperCase()); }
  focus() { document.activeElement=this; }
  select() { selected=this.value; }
  remove() {}
  scrollIntoView() {}
}
let selected='',clipboard='',copyAllowed=true;
const elements={};
for(const match of html.matchAll(/\bid="([^"]+)"/g)) { assert.ok(!elements[match[1]],'Duplicate static id'); elements[match[1]]=new Element(); }
elements.search.tagName='INPUT'; elements.essential.checked=true;
const filters=[...html.matchAll(/data-filter="([^"]+)"/g)].map(m=>{const e=new Element('button');e.dataset.filter=m[1];return e;});
const jumps=[...html.matchAll(/data-jump="([^"]+)"/g)].map(m=>{const e=new Element('button');e.dataset.jump=m[1];return e;});
const document={body:new Element('body'),activeElement:new Element(),handlers:{},getElementById:id=>elements[id],createElement:tag=>new Element(tag),querySelectorAll:selector=>selector==='[data-filter]'?filters:jumps,addEventListener(name,fn){this.handlers[name]=fn;},execCommand(name){assert.equal(name,'copy');if(copyAllowed)clipboard=selected;return copyAllowed;}};
const window={isSecureContext:true,handlers:{},addEventListener(name,fn){this.handlers[name]=fn;},print(){}};
const navigator={clipboard:{async writeText(value){clipboard=value;}}};
const context=vm.createContext({document,window,navigator,matchMedia:()=>({matches:true}),setTimeout:()=>1,clearTimeout:()=>{}});
vm.runInContext(script,context,{filename:'Claude-Code-필수-사용법.html'});
const read=code=>vm.runInContext(code,context);
const visible=()=>read('items.filter(i=>!i.card.hidden).map(i=>i.id)').join(',');
let checks=0;
function check(name,fn){fn();checks++;process.stdout.write(`PASS ${name}\n`);}
function search(text){elements.search.value=text;elements.search.handlers.input();}
check('20 entries, 8 essentials and valid source keys',()=>{assert.equal(read('items.length'),20);assert.equal(read('items.filter(i=>i.essential).length'),8);assert.equal(read('new Set(items.map(i=>i.id)).size'),20);assert.ok(read('items.every(i=>sources[i.source].startsWith("https://"))'));assert.match(elements.count.textContent,/8개/);});
check('Korean queue search includes a non-essential item',()=>{search('큐');assert.ok(visible().includes('queue'));assert.ok(visible().includes('unqueue'));});
check('Multiword Korean and case-insensitive shortcuts',()=>{search('멀티 세션');assert.equal(visible(),'multi');search('CTRL+O');assert.equal(visible(),'details');});
check('Whitespace in key search',()=>{search('ctrl o');assert.equal(visible(),'details');});
check('No-match and literal unsafe-looking input',()=>{search('<img src=x onerror=alert(1)>');assert.equal(visible(),'');assert.equal(elements.empty.hidden,false);});
check('Empty result can reveal all 20',()=>{elements.showAll.handlers.click();assert.equal(read('items.filter(i=>!i.card.hidden).length'),20);assert.equal(elements.empty.hidden,true);});
check('Category filter and aria state',()=>{filters.find(f=>f.dataset.filter==='parallel').handlers.click();assert.equal(read('items.filter(i=>!i.card.hidden).length'),4);assert.equal(filters.find(f=>f.dataset.filter==='parallel').attrs['aria-pressed'],'true');});
check('Category and search intersect',()=>{search('메일');assert.equal(visible(),'multi,worktree');});
check('Reset restores 8 essentials and focus',()=>{elements.reset.handlers.click();assert.equal(read('items.filter(i=>!i.card.hidden).length'),8);assert.equal(document.activeElement,elements.search);});
check('Scenario jump clears filters and opens relevant instructions',()=>{jumps.find(j=>j.dataset.jump==='queue').handlers.click();assert.equal(read('items.find(i=>i.id==="queue").details.open'),true);assert.equal(read('items.filter(i=>!i.card.hidden).length'),20);});
check('Page search shortcut does not hijack inputs or IME',()=>{let prevented=0;const event={key:'/',preventDefault(){prevented++;}};document.activeElement=new Element('div');document.handlers.keydown(event);assert.equal(prevented,1);document.handlers.keydown(event);assert.equal(prevented,1);document.activeElement=new Element('div');document.handlers.keydown({...event,isComposing:true});assert.equal(prevented,1);});
check('Escape clears only the page search',()=>{search('없는검색');document.activeElement=elements.search;document.handlers.keydown({key:'Escape'});assert.equal(elements.search.value,'');assert.equal(elements.empty.hidden,true);});
check('Printing expands visible details and restores prior state',()=>{search('줄바꿈');const before=read('items.map(i=>i.details.open)').join(',');window.handlers.beforeprint();assert.equal(read('items.find(i=>i.id==="newline").details.open'),true);window.handlers.afterprint();assert.equal(read('items.map(i=>i.details.open)').join(','),before);});
assert.equal(await read('copyText("복사 검사", document.createElement("button"))'),true);assert.equal(clipboard,'복사 검사');checks++;
window.isSecureContext=false;
assert.equal(await read('copyText("로컬 파일 복사", document.createElement("button"))'),true);assert.equal(clipboard,'로컬 파일 복사');checks++;
copyAllowed=false;
assert.equal(await read('copyText("권한 없음", document.createElement("button"))'),false);assert.match(elements.toast.textContent,/복사 권한이 없습니다/);checks++;
process.stdout.write(JSON.stringify({status:'passed',checks,externalDependencies:0,browserLaunched:false,layoutVerified:false})+'\n');
