// Owned-app headless regression. No real model, MCP server or desktop driver.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
const args=Object.fromEntries(process.argv.slice(2).reduce((xs,x,i,a)=>{if(x.startsWith('--'))xs.push([x.slice(2),a[i+1]]);return xs;},[]));
if(!args.modules||!args.runtime)throw Error('--modules and --runtime required');
const runtime=JSON.parse(await fs.readFile(args.runtime,'utf8'));
const req=createRequire(path.join(path.resolve(args.modules),'_manual_qa.cjs'));
const {chromium}=req('playwright');
const browser=await chromium.launch({channel:'msedge',headless:true});
const errors=[],external=[];
const output=path.join(runtime.output,'manual-screenshots');await fs.mkdir(output,{recursive:true});
let sends=0;
try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(new URL(runtime.url).origin))external.push(r.url());if(new URL(r.url()).pathname==='/api/send')sends++;});
  page.on('dialog',d=>d.accept()); // only isolated fixture UI confirmations
  await page.goto(runtime.url);
  const origin=new URL(runtime.url).origin;
  for(const [route,title] of [['guide','Company Agent 통합 가이드'],['handbook','Company Agent 핸드북'],['onboarding','Company Agent 시작하기'],['usage','Company Agent 업무별 사용 가이드'],['commands','Claude Code 명령어·단축키']]){
    await page.goto(origin+'/manual/'+route);
    await page.getByRole('heading',{name:title,exact:true}).waitFor();
    if(await page.locator('script').count())throw Error('Manual has executable code');
    await page.screenshot({path:path.join(output,route+'-1440.png')});
    const links=await page.locator('a[href*=".html"]').evaluateAll(nodes=>[...new Set(nodes.map(n=>n.href.split('#')[0]))]);
    for(const link of links){const r=await page.request.get(link);if(r.status()!==200)throw Error('Broken manual link '+link);}
    await page.setViewportSize({width:390,height:844});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Page overflow on phone: '+route);
    await page.screenshot({path:path.join(output,route+'-390.png')});
    await page.setViewportSize({width:1440,height:1000});
  }
  await page.goto(runtime.url);
  await page.locator('#choose-folder').click();
  await page.locator('#folder-input').fill(runtime.workspace);
  await page.locator('#trust').check();
  await page.locator('#confirm-folder').click();
  await page.locator('#folder-dialog').waitFor({state:'hidden'});
  await page.locator('#learn-open').click();
  await page.getByRole('heading',{name:'1. 자료 하나 읽기',exact:true}).waitFor();
  if(await page.getByRole('button',{name:'화면 조작 시험',exact:true}).count())throw Error('Removed screen-control menu is still visible');
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:900});
    await page.locator('#companion-dialog').evaluate(n=>n.scrollTop=0);
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Guide page overflow '+width);
    if(await page.locator('#companion-dialog').evaluate(n=>n.scrollWidth>n.clientWidth+1))throw Error('Guide dialog overflow '+width);
    await page.screenshot({path:path.join(output,'workspace-guide-'+width+'.png')});
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('button',{name:'입력창에 넣기',exact:true}).first().click();
  const prompt=await page.locator('#prompt').inputValue();
  if(!prompt.includes('실습_가상자료.md'))throw Error('Getting-started prompt missing');
  if(sends!==0)throw Error('Guide sent model request without user action');
  if(errors.length||external.length)throw Error(JSON.stringify({errors,external}));
  console.log(JSON.stringify({manuals:1,legacyRoutes:4,manualViewports:[390,1440],panelViewports:[390,768,1440],promptPrepared:true,sends,errors,external,output}));
}finally{await browser.close();}
