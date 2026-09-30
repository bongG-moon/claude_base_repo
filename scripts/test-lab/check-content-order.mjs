// Development-only synthetic fixtures; no user profile, network, Office, or LLM.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const args=Object.fromEntries(process.argv.slice(2).reduce((out,v,i,a)=>{if(v.startsWith('--'))out.push([v.slice(2),a[i+1]]);return out;},[]));
if(!args.modules || !args.python) throw Error('--modules and --python must name existing approved runtimes');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const require=createRequire(path.join(path.resolve(args.modules),'_content_order.cjs'));
const {chromium}=require('playwright');
const source=String.raw`
import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'company-agent-plugin/scripts'))
from company_agent import business_artifacts as a
fixtures=[]
with tempfile.TemporaryDirectory() as directory:
 for style in a.STYLES:
  target=Path(directory)/(style+'.html')
  spec={'style':style,'title':'본문 순서 확인','sections':[{'title':'지원 현황','layout':'split','table':{'headers':['과정','신청자'],'rows':[['입문','20'],['심화','12']]},'body':'입문 과정의 신청자가 많습니다. 심화 과정의 일정은 확인이 필요합니다.','contentOrder':['table','body']}]}
  result=a.create_html(spec,target)
  assert result['ok'],result
  fixtures.append({'style':style,'html':target.read_text(encoding='utf-8')})
print(json.dumps(fixtures,ensure_ascii=False))
`;
const generated=spawnSync(args.python,['-X','utf8','-B','-c',source,root],{encoding:'utf8',maxBuffer:8*1024*1024});
assert.equal(generated.status,0,generated.stderr);
const fixtures=JSON.parse(generated.stdout);
const browser=await chromium.launch({channel:'msedge',headless:true});
const results=[], external=[], errors=[];
try{
 const context=await browser.newContext();
 await context.route('**/*',r=>{external.push(r.request().url());return r.abort();});
 for(const fixture of fixtures){
  const page=await context.newPage();
  page.on('pageerror',e=>errors.push(e.message));
  await page.setContent(fixture.html);
  for(const [width,media] of [[1440,'screen'],[768,'screen'],[390,'screen'],[1000,'print']]){
   await page.setViewportSize({width,height:1100});
   await page.emulateMedia({media,reducedMotion:'reduce'});
   const value=await page.locator('[data-content-layout]').evaluate(el=>{
    const blocks=[...el.children].map(e=>{const r=e.getBoundingClientRect();return {name:e.dataset.contentBlock,x:r.x,y:r.y,w:r.width,h:r.height};});
    return {blocks,display:getComputedStyle(el).display,direction:getComputedStyle(el).flexDirection,
     pageOverflow:document.documentElement.scrollWidth>innerWidth+1};
   });
   assert.deepEqual(value.blocks.map(b=>b.name),['table','body']);
   assert.equal(value.direction,'column',fixture.style+' '+media);
   assert.ok(value.blocks[0].y+value.blocks[0].h<=value.blocks[1].y+.5,fixture.style+' table must be above summary '+width+' '+media);
   assert.equal(value.pageOverflow,false,fixture.style+' overflow '+width);
   results.push({style:fixture.style,width,media,order:'table -> body',vertical:true});
  }
  await page.close();
 }
 assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
 const output=path.join(root,'.smoke','content-order-20261001');
 await fs.mkdir(output,{recursive:true});
 await fs.writeFile(path.join(output,'browser-results.json'),JSON.stringify({results,externalRequests:external,jsErrors:errors},null,2));
 console.log(JSON.stringify({styles:fixtures.length,cases:results.length,externalRequests:0,jsErrors:0}));
 await context.close();
}finally{await browser.close();}
