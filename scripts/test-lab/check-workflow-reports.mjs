// Offline, generated-report QA. No user profile, network, model or application settings.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';
const [modules,out,...files]=process.argv.slice(2);
if(!modules||!out||!files.length)throw Error('Usage: node check-workflow-reports.mjs <modules> <output> <html...>');
const {chromium}=createRequire(path.join(path.resolve(modules),'_reports_qa.cjs'))('playwright');
await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const results=[];
try{
 for(const [i,file] of files.entries()){
  const page=await browser.newPage();const errors=[],network=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route(/^https?:/,route=>{network.push(route.request().url());return route.abort();});
  await page.goto(pathToFileURL(path.resolve(file)).href);
  await page.evaluate(()=>document.fonts.ready);
  if(!(await page.locator('h1').count()))throw Error('Missing report heading');
  const font=await page.evaluate(()=>({family:getComputedStyle(document.body).fontFamily,loaded:[...document.fonts].some(f=>f.family.includes('Noto')&&f.status==='loaded')}));
  if(!font.loaded||!font.family.includes('Noto'))throw Error('Noto Sans KR not loaded');
  for(const width of [1440,768,390]){
   await page.setViewportSize({width,height:1000});
   const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);
   if(overflow)throw Error(`Page overflow ${file} at ${width}`);
   await page.screenshot({path:path.join(out,`report-${i}-${width}.png`),fullPage:width===1440});
  }
  // Expanded learning content must remain readable, not only the collapsed cover.
  const explanation=page.locator('.detail').filter({has:page.locator('.formula-details')}).first();
  let explained=false;
  if(await explanation.count()){
   explained=true;
   await explanation.locator('details').evaluateAll(elements=>elements.forEach(element=>{element.open=true;}));
   for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:1000});
    await explanation.locator('.table-explanation').evaluate(element=>element.scrollIntoView({block:'start'}));
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);
    const clipped=await explanation.locator('pre.formula-code').evaluateAll(elements=>
     elements.some(element=>element.scrollWidth>element.clientWidth+2));
    if(overflow||clipped)throw Error(`Expanded formula overflow ${file} at ${width}`);
    await page.screenshot({path:path.join(out,`explanation-${i}-${width}.png`)});
   }
   if(!await explanation.locator('.formula-steps').count())throw Error('Missing plain-language formula explanation');
  }
  await page.emulateMedia({media:'print'});
  if(!await page.locator('h1').isVisible())throw Error('Print hides report');
  if(network.length||errors.length)throw Error(JSON.stringify({errors,network}));
  results.push({file:path.basename(file),font,viewports:[1440,768,390],expandedFormulaChecked:explained,networkRequests:0,errors});
  await page.close();
 }
 await fs.writeFile(path.join(out,'browser-results.json'),JSON.stringify(results,null,2));
 console.log(JSON.stringify(results));
}finally{await browser.close();}
