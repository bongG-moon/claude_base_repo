// Unit fixture for shipped DOM capture; no browser, network or user profile.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../../company-agent-plugin/scripts/company_agent/ppt_dom_capture.js', import.meta.url),'utf8');
const defaults = {display:'block',visibility:'visible',contentVisibility:'visible',transform:'none',
  translate:'none',rotate:'none',scale:'none',filter:'none',clipPath:'none',backgroundImage:'none',
  opacity:'1',backgroundColor:'rgba(0,0,0,0)',borderTopColor:'rgba(0,0,0,0)',borderTopWidth:'0px',
  borderRightColor:'rgba(0,0,0,0)',borderRightWidth:'0px',borderBottomColor:'rgba(0,0,0,0)',borderBottomWidth:'0px',
  borderLeftColor:'rgba(0,0,0,0)',borderLeftWidth:'0px',borderTopLeftRadius:'0px',boxShadow:'none',
  textTransform:'none',letterSpacing:'0px',fontSize:'24px',fontWeight:'700',fontFamily:'"Malgun Gothic"',
  color:'rgb(23,59,94)',fontStyle:'normal',textDecorationLine:'none',zIndex:'auto'};
function element(tag, group, children=[], styles={}) {
  return {nodeType:1,tagName:tag,childNodes:children,hidden:false,group,styles,
    getAttribute: key => key==='data-ppt-group'?group:null,
    querySelector: () => null, contains(other) {return children.some(c=>c===other||c.contains?.(other));},
    getBoundingClientRect: () => tag==='SECTION'?{left:0,top:0,width:960,height:540}:{left:40,top:100,width:350,height:200}};
}
function capture(slide) {
  let onLoad, output;
  const document = {querySelectorAll:()=>[slide],createElement:()=>({}),body:{append:node=>{output=node.textContent;}},
    createRange:()=>{let start,end; return {setStart:(_,v)=>{start=v;},setEnd:(_,v)=>{end=v;},
      getBoundingClientRect:()=>({left:60+start*16,top:120,right:60+end*16,bottom:150,width:(end-start)*16,height:30})};}};
  vm.runInNewContext(source.replace('__COMPANY_OPTIONS__',JSON.stringify({selector:'.slide',outputId:'result'})),
    {document,Node:{ELEMENT_NODE:1,TEXT_NODE:3},window:{addEventListener:(_,f)=>{onLoad=f;}},
     getComputedStyle:(node,pseudo)=>pseudo?{content:'none'}:{...defaults,...node.styles}});
  onLoad(); return JSON.parse(output);
}
const text = value => ({nodeType:3,textContent:value,length:value.length});
const card = () => element('DIV','실적카드',[text('신청 현황')],{backgroundColor:'rgb(238,243,248)'});
let result = capture(element('SECTION',null,[card()]));
assert.equal(result.error,undefined);
assert.deepEqual(result.pages[0].elements.map(e=>[e.kind,e.group]),[['shape','실적카드'],['text','실적카드']]);
assert.equal(result.pages[0].elements[1].bold,true);
assert.equal(result.pages[0].elements[1].color,'173B5E');
assert.equal(result.pages[0].elements[1].font,'Malgun Gothic');
result = capture(element('SECTION',null,[element('DIV',null,[text('본문')])]));
assert.equal(result.pages[0].elements[0].group,undefined);
for (const slide of [element('SECTION','전체',[card()]),
  element('SECTION',null,[element('DIV','상위',[card()])]),
  element('SECTION',null,[element('DIV','카드',[element('TABLE',null)])])]) {
  assert.ok(capture(slide).error);
}
console.log('PPT DOM groups: 9 assertions passed (synthetic DOM, no browser).');
