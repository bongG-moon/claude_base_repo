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
  const page=await browser.newPage({viewport:{width:1440,height:1000},permissions:['clipboard-read','clipboard-write']});
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/^https?:/.test(r.url()))external.push(r.url());});
  // Copy only the release attachment: prove it does not need sibling files.
  const single=path.join(args.output,'standalone-guide.html');
  await fs.copyFile('docs/Company-Agent-사용자-안내서.html',single);
  await page.goto(pathToFileURL(path.resolve(single)).href);
  await page.getByRole('heading',{name:'Company Agent 사용자 안내서',exact:true}).waitFor();
  await page.getByRole('heading',{name:'Company Agent 시작하기',exact:true}).waitFor();
  await page.evaluate(()=>document.fonts.ready);
  const fontState=await page.evaluate(()=>({family:getComputedStyle(document.body).fontFamily,
    faces:[...document.fonts].map(f=>({family:f.family,status:f.status}))}));
  if(!fontState.family.startsWith('"Noto Sans KR"')||!fontState.faces.some(f=>f.family==='Noto Sans KR'&&f.status==='loaded'))throw Error('Offline Noto Sans KR not loaded');
  const brokenProse=await page.locator('p,li,td,h2,h3,h4').evaluateAll(nodes=>nodes.filter(n=>n.innerText.includes('**')||n.innerText.includes('\uFFFD')).map(n=>n.innerText));
  if(brokenProse.length)throw Error('Unrendered prose: '+JSON.stringify(brokenProse));
  const visible=await page.locator('body').innerText();
  for(const phrase of ['온보딩','내 하네스에서 여는 곳','수정용 원본:','담당자용 소스 문서','문서와 구현을 함께 관리하기']){
    if(visible.includes(phrase))throw Error('Internal or difficult wording in guide: '+phrase);
  }
  if(await page.locator('script,iframe,img,link').count())throw Error('External/runtime dependency in guide');
  const links=await page.locator('a[href^="#"]').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')));
  for(const link of links)if(await page.locator(link).count()!==1)throw Error('Missing/duplicate anchor '+link);
  const parts=await page.locator('section.book').count();
  if(parts!==6)throw Error('Missing guide part');
  await page.getByRole('heading',{name:'디자인 용어 참고',exact:true}).waitFor();
  const targets=['start','onboarding-section-2','onboarding-section-3','onboarding-section-7','onboarding-section-8','onboarding-section-9','basics','handbook-section-4','handbook-section-7','commands-section-1','commands-section-2','design','design-section-3','design-section-8','design-section-9'];
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:1000});
    for(const target of targets){
      await page.locator('#'+target).scrollIntoViewIfNeeded();
      if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Page overflow '+width+' '+target);
      if(await page.locator('pre,.table-wrap,h2,h3,h4').evaluateAll(nodes=>nodes.some(n=>n.scrollWidth>n.clientWidth+1)))throw Error('Clipped block '+width+' '+target);
      await page.screenshot({path:path.join(args.output,target+'-'+width+'.png')});
    }
  }
  await page.setViewportSize({width:1440,height:1000});
  const prompt=page.locator('pre code').filter({hasText:'실습용 가상 자료를 실습_가상자료.md'}).first();
  await prompt.click();
  const selected=await page.evaluate(()=>window.getSelection().toString());
  if(!selected.includes('목표 합계 300')||!selected.includes('기억이나 회사 지식에는 저장하지 마'))throw Error('Prompt cannot be selected as one block');
  await page.emulateMedia({media:'print'});
  await page.pdf({path:path.join(args.output,'guide-print.pdf'),format:'A4',printBackground:true});
  await page.emulateMedia({media:'screen'});
  const installed=path.resolve('company-agent-plugin/resources/manuals');
  const readers=(await fs.readdir(installed)).filter(name=>name.endsWith('.html'));
  if(readers.length!==1||readers[0]!=='Company-Agent-사용자-안내서.html')throw Error('Duplicate installed readers');
  await page.goto(pathToFileURL(path.join(installed,'Company-Agent-사용자-안내서.html')).href+'#section-6');
  await page.getByRole('heading',{name:'Company Agent 사용자 안내서',exact:true}).waitFor();
  if(await page.locator('#usage-section-6 #section-6').count()!==1)throw Error('Missing old user-guide bookmark');
  const markdown=await fs.readFile(path.join(installed,'README.md'),'utf8');
  if(!['CLAUDE_CODE_BASICS.md','CLAUDE_CODE_COMMANDS.md','DESIGN_TERMS.md'].every(name=>markdown.includes(name)))throw Error('Incomplete Markdown contents');
  if(errors.length||external.length)throw Error(JSON.stringify({errors,external}));
  console.log(JSON.stringify({standalone:true,parts,markdownIndex:true,embeddedFont:'Noto Sans KR',brokenProse:0,viewports:[1440,768,390],screenshots:targets.length*3,anchors:links.length,readers:1,userGuideBookmarks:true,promptSelection:true,print:true,external,errors}));
}finally{await browser.close();}
