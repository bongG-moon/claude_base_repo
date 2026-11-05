// Browser verification of local report charts. Uses synthetic fixtures only.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(process.argv[2]||'.smoke/html-chart-usability-20261105');
const executable=process.env.REPORT_TEST_BROWSER;
const results={pass:false,cases:[],errors:[],externalRequests:[]};
(async()=>{
 const browser=await chromium.launch({headless:true,...(executable?{executablePath:executable}:{})});
 try{
  for(const style of ['minimalism','bento-grid'])for(const width of [1440,390]){
   const context=await browser.newContext({viewport:{width,height:1050},hasTouch:width===390});
   await context.route('**/*',route=>{results.externalRequests.push(route.request().url());route.abort();});
   const page=await context.newPage();page.on('pageerror',e=>results.errors.push(String(e)));
   await page.setContent(fs.readFileSync(path.join(root,style+'.html'),'utf8'));await page.evaluate(()=>document.fonts.ready);
   assert.equal(await page.locator('.chart-frame').count(),4);
   const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
   assert.equal(overflow,false,style+' '+width+' page overflow');
   for(let i=0;i<4;i++){
    const frame=page.locator('.chart-frame').nth(i),points=frame.locator('.chart-point'),tooltip=frame.locator('.chart-tooltip');
    await points.first().focus();await tooltip.waitFor({state:'visible'});
    assert.equal(await tooltip.textContent(),await points.first().getAttribute('data-chart-label'));
    const first=await tooltip.textContent();await points.first().press('ArrowRight');
    assert.equal(await tooltip.textContent(),await points.nth(1).getAttribute('data-chart-label'));assert.notEqual(await tooltip.textContent(),first);
    assert.equal(await frame.locator('.chart-point.is-active').count(),1);
    await page.keyboard.press('End');assert.equal(await tooltip.textContent(),await points.last().getAttribute('data-chart-label'));
    await page.keyboard.press('Escape');assert.equal(await tooltip.isVisible(),false);
   }
   const frame=page.locator('.chart-frame').first(),first=frame.locator('.chart-point').first(),tip=frame.locator('.chart-tooltip');
   await first.locator('.chart-mark').hover();await tip.waitFor({state:'visible'});
   await first.locator('.chart-mark').click();assert.equal(await tip.isVisible(),true);
   await page.locator('.report-name').click();assert.equal(await tip.isVisible(),false);
   // On a page deck the chart's keys must not switch report sections.
   await page.locator('#toggle-view').click();await first.focus();await first.press('ArrowRight');
   assert.equal(await page.locator('main>.section.active').getAttribute('id'),'section-1');
   await page.locator('#toggle-view').click();
   const sizes=await first.evaluate(point=>{
    const svg=point.closest('svg'),section=point.closest('.section'),axis=svg.querySelector('text'),r=svg.getBoundingClientRect();
    return {title:parseFloat(getComputedStyle(section.querySelector('h2')).fontSize),axis:parseFloat(getComputedStyle(axis).fontSize)*r.width/svg.viewBox.baseVal.width,chartWidth:r.width};
   });
   assert.ok(sizes.title>sizes.axis*1.5);assert.ok(sizes.axis>=11.9&&sizes.axis<=12.1);assert.ok(sizes.chartWidth<=800.1);
   const cell=page.locator('.section.data-panel tbody td').first();
   assert.equal(await cell.evaluate(el=>getComputedStyle(el).fontSize),'14px');
   await first.focus();await tip.waitFor({state:'visible'});
   const box=await tip.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width+.1);
   await page.screenshot({path:path.join(root,style+'-'+width+'.png'),fullPage:false});
   if(width===390){await first.press('Escape');await first.locator('.chart-mark').tap();assert.equal(await tip.isVisible(),true);}
   await page.emulateMedia({media:'print'});assert.equal(await tip.isVisible(),false);
   results.cases.push({style,width,charts:4,keyboard:true,hover:true,touch:width===390,headingHierarchy:sizes,tableFont:14,pageOverflow:false,printTooltipHidden:true});
   await context.close();
  }
  assert.equal(results.errors.length,0);assert.equal(results.externalRequests.length,0);results.pass=true;
 }catch(error){results.error=String(error.stack||error);process.exitCode=1;}
 finally{await browser.close();fs.writeFileSync(path.join(root,'browser-verification.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));}
})();
