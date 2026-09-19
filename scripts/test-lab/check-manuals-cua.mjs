// Owned-app headless regression. No real model, MCP server or desktop driver.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
const args=Object.fromEntries(process.argv.slice(2).reduce((xs,x,i,a)=>{if(x.startsWith('--'))xs.push([x.slice(2),a[i+1]]);return xs;},[]));
if(!args.modules||!args.runtime)throw Error('--modules and --runtime required');
const runtime=JSON.parse(await fs.readFile(args.runtime,'utf8'));
const req=createRequire(path.join(path.resolve(args.modules),'_manual_cua_qa.cjs'));
const {chromium}=req('playwright');
const browser=await chromium.launch({channel:'msedge',headless:true});
const errors=[],external=[];
const output=path.join(runtime.output,'manual-cua-screenshots');await fs.mkdir(output,{recursive:true});
let sends=0,checks=0;
try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(new URL(runtime.url).origin))external.push(r.url());if(new URL(r.url()).pathname==='/api/send')sends++;});
  page.on('dialog',d=>d.accept()); // only isolated fixture UI confirmations
  await page.goto(runtime.url);
  const origin=new URL(runtime.url).origin;
  for(const [route,title] of [['handbook','Company Agent 핸드북'],['onboarding','Company Agent 처음부터 따라 하기'],['cua','Cua Driver 가능성 확인 안내']]){
    await page.goto(origin+'/manual/'+route);
    await page.getByRole('heading',{name:title,exact:true}).waitFor();
    if(await page.locator('script').count())throw Error('Manual has executable code');
    await page.screenshot({path:path.join(output,route+'-1440.png')});
    const links=await page.locator('a[href$=".html"]').evaluateAll(nodes=>[...new Set(nodes.map(n=>n.href))]);
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
  await page.getByRole('button',{name:'화면 조작 시험',exact:true}).click();
  await page.getByRole('button',{name:'설치 후보·현재 연결 확인',exact:true}).click();
  await page.getByText('MCP: 현재 CLI 연결 보고 없음',{exact:true}).waitFor();
  if(await page.getByRole('button',{name:'읽기 시험 예문을 입력창에 넣기',exact:true}).count())throw Error('Offered unavailable trial');
  await page.screenshot({path:path.join(output,'cua-unprepared-1440.png')});
  // Exercise positive rendering with explicitly synthetic evidence. The real
  // diagnostic logic is covered separately by Python/HTTP tests.
  await page.route('**/api/companion',async route=>{
    const r=route.request();if(r.method()!=='POST'||r.postDataJSON().action!=='computer-check')return route.continue();
    checks++;
    return route.fulfill({json:{status:'tools-observed',driver:{status:'found',path:'C:\\approved-fixture\\cua-driver.exe'},connection:{status:'connected',name:'cua-driver'},tools:['list_apps','get_window_state','click','type_text'],canPrepareReadTrial:true,canPrepareInputTrial:true,limits:['합성 연결 보고입니다. 실제 Driver 시험이 아닙니다.'],next:'가상 도구 노출 확인'}});
  });
  await page.getByRole('button',{name:'설치 후보·현재 연결 확인',exact:true}).click();
  await page.getByRole('button',{name:'읽기 시험 예문을 입력창에 넣기',exact:true}).waitFor();
  await page.screenshot({path:path.join(output,'cua-synthetic-ready-1440.png')});
  for(const width of [390,768]){
    await page.setViewportSize({width,height:900});
    await page.locator('#companion-dialog').evaluate(n=>n.scrollTop=0);
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Cua page overflow '+width);
    if(await page.locator('#companion-dialog').evaluate(n=>n.scrollWidth>n.clientWidth+1))throw Error('Cua dialog overflow '+width);
    await page.screenshot({path:path.join(output,'cua-synthetic-ready-'+width+'.png')});
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('button',{name:'읽기 시험 예문을 입력창에 넣기',exact:true}).click();
  const prompt=await page.locator('#prompt').inputValue();
  if(!prompt.includes('cua-driver')||!prompt.includes('클릭·입력·설정 변경은 하지 마'))throw Error('Read trial scope lost');
  await page.locator('#learn-open').click();
  await page.getByRole('button',{name:'화면 조작 시험',exact:true}).click();
  await page.getByRole('button',{name:'설치 후보·현재 연결 확인',exact:true}).click();
  await page.getByRole('button',{name:'입력 시험 예문을 입력창에 넣기',exact:true}).click();
  const inputPrompt=await page.locator('#prompt').inputValue();
  if(!inputPrompt.includes('2+3')||!inputPrompt.includes('내 답변을 기다려'))throw Error('Input trial confirmation lost');
  if(sends!==0)throw Error('Guide/check sent model request');
  if(errors.length||external.length)throw Error(JSON.stringify({errors,external}));
  console.log(JSON.stringify({manuals:3,manualViewports:[390,1440],panelViewports:[390,768,1440],checks,sends,errors,external,output}));
}finally{await browser.close();}
