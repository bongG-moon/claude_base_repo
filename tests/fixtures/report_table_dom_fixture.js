// Synthetic DOM for controller behavior only. This does not verify rendering.
class TestElement {
  constructor(tag) { this.tagName=tag; this.children=[]; this.dataset={}; this.attrs={}; this.handlers={}; this.hidden=false; this.disabled=false; this.value=''; this._text=''; this.style={setProperty(k,v){this[k]=String(v)}}; }
  set textContent(value) { this._text=String(value); this.replaceChildren(); }
  get textContent() { return this._text+this.children.map(c=>c.textContent).join(''); }
  append(...nodes) { for(const node of nodes){node.remove();node.parent=this;this.children.push(node);} }
  prepend(...nodes) { for(const node of nodes){node.remove();node.parent=this;}this.children.unshift(...nodes); }
  replaceChildren(...nodes) { for(const c of this.children)c.parent=null;this.children=[];this.append(...nodes); }
  remove(){if(this.parent){this.parent.children=this.parent.children.filter(c=>c!==this);this.parent=null;}}
  setAttribute(k,v){this.attrs[k]=String(v);}
  removeAttribute(k){delete this.attrs[k];}
  addEventListener(event,fn){this.handlers[event]=fn;}
  click(){if(!this.disabled)this.handlers.click?.();}
  get cells(){return this.children.filter(c=>['td','th'].includes(c.tagName));}
  get rows(){return this.children.filter(c=>c.tagName==='tr');}
  get tBodies(){return this.children.filter(c=>c.tagName==='tbody');}
  get tHead(){return this.children.find(c=>c.tagName==='thead');}
  get options(){return this.children.filter(c=>c.tagName==='option');}
  get selectedOptions(){return this.options.filter(c=>c.value===this.value);}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  querySelectorAll(selector){const matches=c=>selector.startsWith('.')?String(c.className||'').split(' ').includes(selector.slice(1)):c.tagName===selector;return this.children.flatMap(c=>[...(matches(c)?[c]:[]),...c.querySelectorAll(selector)]);}
}
function fixture(count){
  const root=new TestElement('div'),wrap=new TestElement('div'),table=new TestElement('table');wrap.className='table-wrap';wrap.append(table);root.append(wrap);
  const head=new TestElement('thead'),hr=new TestElement('tr'),body=new TestElement('tbody');head.append(hr);table.append(head,body);
  for(const h of ['ID','부서','수량']){const cell=new TestElement('th');cell.textContent=h;hr.append(cell);}
  for(let i=0;i<count;i++){const row=new TestElement('tr');for(const [j,v] of ['ID-'+i,['생산','품질'][i%2],String(count-i)].entries()){const cell=new TestElement('td');cell.textContent=v;if(j===2)cell.dataset.kind='number';row.append(cell);}body.append(row);}
  return {root,table,body,headers:hr.cells};
}
const fixtures=[fixture(4),fixture(60)],downloads=[],events={};
global.document={body:new TestElement('body'),createElement:tag=>new TestElement(tag),querySelectorAll:()=>fixtures.map(f=>f.root)};
global.window={addEventListener:(name,fn)=>(events[name]??=[]).push(fn)};
global.URL={createObjectURL:blob=>{downloads.push(blob);return 'blob:synthetic'},revokeObjectURL:()=>{}};
global.setTimeout=fn=>fn();
