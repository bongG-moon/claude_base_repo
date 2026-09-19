// Interaction unit checks only: no browser launch, screenshots or visual claims.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html=fs.readFileSync(new URL('../company-agent-plugin/skills/html-report/assets/design-picker.html',import.meta.url),'utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
class Element {
  constructor(){this.attrs={};this.dataset={};this.handlers={};this.textContent='';this.value='';}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,v){this.handlers[k]=v;}
  focus(){focused=this;}
  select(){selected=this.value;}
}
let copied='',selected='',focused=null;
const elements={};
for(const id of ['length-choice','mode-choice','choice-result','copy-status','selected-design','copy-choice','additional-designs'])elements[id]=new Element();
elements['length-choice'].options=[{text:'기존 선택 유지'},{text:'핵심'},{text:'보통'},{text:'상세'}];elements['length-choice'].selectedIndex=0;elements['length-choice'].value='keep';
elements['mode-choice'].options=[{text:'기존 선택 유지'},{text:'스크롤'},{text:'페이지 넘김'},{text:'둘 다'}];elements['mode-choice'].selectedIndex=0;elements['mode-choice'].value='keep';
const buttons=[...html.matchAll(/data-choice="([^"]+)" data-label="([^"]+)"/g)].map(m=>{const b=new Element();b.dataset={choice:m[1],label:m[2]};return b;});
const navigator={clipboard:{async writeText(value){copied=value;}}};
const context=vm.createContext({document:{querySelectorAll:selector=>selector==='[data-choice]'?buttons:[],getElementById:id=>elements[id]},navigator,location:{hash:''},window:{addEventListener(){}}});
vm.runInContext(script,context);
assert.equal(buttons.length,13);
assert.match(html,/<details id="additional-designs" class="design-options">/);
assert.equal((html.match(/class="design-card"/g)||[]).length,10);
assert.match(elements['choice-result'].value,/미니멀리즘.*이미 정한 조건을 유지/);
assert.doesNotMatch(elements['choice-result'].value,/분량:|보기:/);
let checks=4;
for(const choice of [...new Set(buttons.map(b=>b.dataset.choice))]){
  const button=buttons.find(b=>b.dataset.choice===choice);button.handlers.click();
  assert.match(elements['choice-result'].value,choice==='template'?/HTML 양식/:new RegExp(button.dataset.label.replace(/[()]/g,'\\$&')));
  assert.equal(button.attrs['aria-pressed'],'true');
  assert.ok(buttons.filter(b=>b.dataset.choice!==choice).every(b=>b.attrs['aria-pressed']==='false'));
  checks++;
}
elements['length-choice'].selectedIndex=3;elements['length-choice'].value='detailed';elements['length-choice'].handlers.change();
elements['mode-choice'].selectedIndex=2;elements['mode-choice'].value='slides';elements['mode-choice'].handlers.change();
assert.match(elements['choice-result'].value,/상세.*페이지 넘김/);checks++;
buttons.find(b=>b.dataset.choice==='template').handlers.click();
assert.match(elements['choice-result'].value,/HTML 양식.*분량: 상세.*보기: 페이지 넘김/);checks++;
elements['length-choice'].value='keep';elements['length-choice'].selectedIndex=0;elements['length-choice'].handlers.change();
assert.doesNotMatch(elements['choice-result'].value,/분량:/);assert.match(elements['choice-result'].value,/보기: 페이지 넘김/);checks++;
await elements['copy-choice'].handlers.click();assert.equal(copied,elements['choice-result'].value);checks++;
navigator.clipboard.writeText=async()=>{throw Error('denied');};
await elements['copy-choice'].handlers.click();assert.equal(selected,elements['choice-result'].value);assert.equal(focused,elements['choice-result']);assert.match(elements['copy-status'].textContent,/Ctrl\+C/);checks++;
navigator.clipboard=undefined;await elements['copy-choice'].handlers.click();assert.match(elements['copy-status'].textContent,/자동 복사가 제한/);checks++;
console.log(JSON.stringify({status:'passed',checks,browserLaunched:false,visualVerified:false}));
