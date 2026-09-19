// Own local offline HTML only. No model calls, installs, or live user profile.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const args=Object.fromEntries(process.argv.slice(2).reduce((pairs,x,i,a)=>{if(x.startsWith('--'))pairs.push([x.slice(2),a[i+1]]);return pairs;},[]));
if(!args.modules||!args.output)throw Error('--modules and --output required');
const req=createRequire(path.join(path.resolve(args.modules),'_guide_qa.cjs'));
const {chromium}=req('playwright');
const browser=await chromium.launch({channel:args.browser||'chrome',headless:true});
await fs.mkdir(args.output,{recursive:true});
const errors=[],external=[];
try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/^https?:/.test(r.url()))external.push(r.url());});
  // Copy only the canonical reader: prove it does not depend on sibling files.
  const single=path.join(args.output,'standalone-guide.html');
  await fs.copyFile('docs/Company-Agent-Guide.html',single);
  await page.goto(pathToFileURL(path.resolve(single)).href);
  await page.getByRole('heading',{name:'Company Agent 통합 가이드',exact:true}).waitFor();
  if(await page.locator('script,iframe,img,link').count())throw Error('External/runtime dependency in guide');
  const links=await page.locator('a[href^="#"]').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')));
  for(const link of links)if(await page.locator(link).count()!==1)throw Error('Missing/duplicate anchor '+link);
  const targets=['start','onboarding-section-2','onboarding-section-3','onboarding-section-7','onboarding-section-8','onboarding-section-9','commands-section-2'];
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:1000});
    for(const target of targets){
      await page.locator('#'+target).scrollIntoViewIfNeeded();
      if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Page overflow '+width+' '+target);
      await page.screenshot({path:path.join(args.output,target+'-'+width+'.png')});
    }
  }
  await page.setViewportSize({width:1440,height:1000});
  const prompt=page.locator('pre code').filter({hasText:'온보딩용 가상 자료를 온보딩_가상자료.md'}).first();
  await prompt.click();
  const selected=await page.evaluate(()=>window.getSelection().toString());
  if(!selected.includes('목표 합계 300')||!selected.includes('기억이나 회사 지식에는 저장하지 마'))throw Error('Prompt cannot be selected as one block');
  await page.emulateMedia({media:'print'});
  await page.pdf({path:path.join(args.output,'guide-print.pdf'),format:'A4',printBackground:true});
  await page.emulateMedia({media:'screen'});
  const installed=path.resolve('company-agent-plugin/resources/manuals');
  for(const filename of ['Company-Agent-Onboarding.html','Company-Agent-Handbook.html','Company-Agent-Cua-Pilot.html','Company-Agent-사용자-안내서.html','Claude-Code-필수-사용법.html']){
    await page.goto(pathToFileURL(path.join(installed,filename)).href);
    await page.locator('a').first().click();
    await page.getByRole('heading',{name:'Company Agent 통합 가이드',exact:true}).waitFor();
  }
  await page.goto(pathToFileURL(path.resolve('company-agent-plugin/resources/first-work.html')).href);
  await page.getByRole('link',{name:'통합 가이드 · 준비물 없이 시작하기',exact:true}).click();
  await page.getByRole('heading',{name:'Company Agent 통합 가이드',exact:true}).waitFor();
  if(errors.length||external.length)throw Error(JSON.stringify({errors,external}));
  console.log(JSON.stringify({standalone:true,parts:5,viewports:[1440,768,390],screenshots:targets.length*3,anchors:links.length,legacyLinks:5,promptSelection:true,print:true,external,errors}));
}finally{await browser.close();}
