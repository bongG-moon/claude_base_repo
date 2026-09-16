// Development-only rendering of fresh synthetic fixtures in an isolated browser.
// No file URLs, user profiles, downloads, network access or Office automation.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const args = Object.fromEntries(process.argv.slice(2).reduce((o,v,i,a)=>{if(v.startsWith('--'))o.push([v.slice(2),a[i+1]]);return o;},[]));
if(!args.modules || !args.fixtures) throw Error('--modules and --fixtures required');
const req=createRequire(path.join(path.resolve(args.modules),'_report_qa.cjs'));
const {chromium}=req('playwright');
const root=path.resolve(args.fixtures), styles=JSON.parse(await fs.readFile(path.join(root,'fixtures.json'),'utf8')).styles;
const browser=await chromium.launch({channel:'msedge',headless:true});
const results=[], external=[], errors=[];
try {
  const context=await browser.newContext();
  await context.route('**/*',route=>{external.push(route.request().url());return route.abort();});
  let page=await context.newPage();
  const load=async html=>{
    // document.write/setContent retains a document's earlier CSP. Use a fresh
    // document for each fixture, as a real navigation would; never bypass CSP.
    const viewport=page.viewportSize();
    await page.close();page=await context.newPage();
    if(viewport)await page.setViewportSize(viewport);
    await page.emulateMedia({media:'screen',reducedMotion:'reduce'});
    page.on('pageerror',e=>errors.push(e.message));
    page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
    await page.setContent(html);
  };
  const sample=async selector=>page.locator(selector).first().evaluate(el=>{
    const s=getComputedStyle(el);return {bg:s.backgroundColor,image:s.backgroundImage,shadow:s.boxShadow,
      blur:s.backdropFilter,radius:s.borderRadius,ink:s.color,border:s.borderTopWidth,font:s.fontFamily};});
  for(const style of styles){
    await page.setViewportSize({width:1440,height:1050});
    await page.emulateMedia({media:'screen',reducedMotion:'reduce'});
    await load(await fs.readFile(path.join(root,style+'.html'),'utf8'));
    await page.evaluate(()=>document.fonts.ready);
    const section=await sample('.section:not(.layout-cover)'), cell=await sample('.kpi');
    assert.equal(await page.locator('main>.section').count(),5);
    assert.equal(await page.locator('.kpi-value').first().textContent(),'530백만원');
    if(style==='glassmorphism'){
      assert.match(section.blur,/blur\(14px\)/);assert.match(section.bg,/rgba/);
      const alpha=color=>Number(color.match(/rgba\([^,]+,[^,]+,[^,]+,\s*([\d.]+)\)/)?.[1] ?? 1);
      assert.ok(alpha(section.bg)<=0.2,'Glass panel must not become a milky white card');
      assert.ok(alpha(cell.bg)<=0.16,'Nested KPI must not stack opaque white layers');
      const background=(await sample('body')).image;
      assert.match(background,/rgb\(208, 198, 242\)/,'Reference lavender backdrop');
      assert.match(background,/rgb\(166, 223, 252\)/,'Reference sky blue backdrop');
      assert.match((await sample('body')).image,/radial-gradient/);assert.equal(section.border,'1px');
      for(const material of [section.bg,cell.bg]){
        const channels=[...material.matchAll(/rgba?\((\d+),\s*(\d+),\s*(\d+)/g)];
        assert.ok(channels.length,'Glass panes stay white over the pastel background');
        for(const [,r,g,b] of channels){assert.equal(r,g,'Glass red/green tint');assert.equal(g,b,'Glass green/blue tint');}
      }
    }
    if(style==='neumorphism'){
      assert.equal(section.bg,(await sample('body')).bg);assert.match(section.shadow,/-14px -14px/);
      assert.match(cell.shadow,/inset/);assert.equal(section.border,'0px');
    }
    if(style==='brutalism'){assert.equal(section.border,'3px');assert.equal(section.radius,'0px');assert.match(section.shadow,/8px 8px 0px/);}
    if(style==='bento-grid'){
      const widths=await page.locator('.kpi').evaluateAll(els=>els.slice(0,2).map(x=>x.getBoundingClientRect().width));
      assert.ok(widths[0]>widths[1]*1.7,'Bento must have unequal spans');
    }
    const reportTheme={section,cell};
    await page.screenshot({path:path.join(root,style+'-desktop.png'),fullPage:false});
    await page.locator('#toggle-view').click();
    assert.equal(await page.locator('main>.section:visible').count(),1,JSON.stringify(await page.evaluate(()=>({view:document.body.dataset.view,active:document.querySelectorAll('.section.active').length,styles:[...document.querySelectorAll('.section')].map(e=>getComputedStyle(e).display)}))));
    await page.locator('#next').click();
    assert.match(await page.locator('.section.active h2').textContent(),/6월/);
    await page.locator('#toggle-view').click();
    for(const width of [768,390]){
      await page.setViewportSize({width,height:900});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,style+' page overflow '+width);
      const clipped=await page.locator('.kpi').evaluateAll(els=>els.filter(e=>e.scrollWidth>e.clientWidth+1).length);
      assert.equal(clipped,0,style+' KPI clipping '+width);
      const splitUnits=await page.locator('.kpi-unit').evaluateAll(els=>els.filter(e=>e.getClientRects().length>1).length);
      assert.equal(splitUnits,0,style+' broken Korean unit '+width);
      if(width===390)await page.screenshot({path:path.join(root,style+'-mobile.png'),fullPage:false});
    }
    await page.emulateMedia({media:'print'});
    assert.equal(await page.locator('main>.section:visible').count(),5);
    assert.equal((await sample('.section')).shadow,'none');
    assert.equal((await sample('.section')).bg,'rgb(255, 255, 255)');
    assert.equal((await sample('.kpi-value')).ink,'rgb(23, 33, 50)','Print KPI contrast '+style);
    await page.emulateMedia({media:'screen'});
    await page.setViewportSize({width:1440,height:1050});
    await load(await fs.readFile(path.join(root,'picker.html'),'utf8'));
    assert.equal(await page.locator('#additional-designs').getAttribute('open'),null);
    await page.locator('#additional-designs>summary').click();
    const preview='.style-preview[data-style="'+style+'"]';
    const actual=await sample(preview+' .section');
    const referenceMaterial=['editorial','immersive-3d','retro-y2k'].includes(style)?await (async()=>{
      await load(await fs.readFile(path.join(root,style+'.html'),'utf8'));
      return await sample('.layout-cover');
    })():reportTheme.section;
    // Compare shared material properties, not deliberately reduced thumbnail type.
    for(const key of ['bg','image','shadow','radius','blur'])assert.equal(actual[key],referenceMaterial[key],style+' preview '+key);
    results.push({style,reportTheme,widths:[1440,768,390],previewMatches:true,print:true,pageNavigation:true});
  }
  await load(await fs.readFile(path.join(root,'picker.html'),'utf8'));
  await page.locator('#additional-designs>summary').click();
  assert.equal(await page.locator('.design-card').count(),styles.length);
  await page.screenshot({path:path.join(root,'picker-gallery.png'),fullPage:true});
  for(const style of styles){
    await page.locator('.design-card button[data-choice="'+style+'"]').click();
    assert.equal(await page.locator('.design-card button[data-choice="'+style+'"]').getAttribute('aria-pressed'),'true');
    assert.doesNotMatch(await page.locator('#choice-result').inputValue(),/분량:|보기:/);
  }
  await page.locator('#length-choice').selectOption('detailed');
  await page.locator('#mode-choice').selectOption('slides');
  await page.locator('.design-card button[data-choice="glassmorphism"]').click();
  assert.match(await page.locator('#choice-result').inputValue(),/글래스모피즘.*상세.*페이지 넘김/);
  for(const width of [768,390]){
    await page.setViewportSize({width,height:900});
    await page.waitForTimeout(60);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'Picker overflow '+width);
    const clipped=await page.locator('.mini-window').evaluateAll(boxes=>boxes.some(box=>{
      const frame=box.getBoundingClientRect(),preview=box.querySelector('.style-preview').getBoundingClientRect();
      return preview.width>frame.width+1 || preview.height>frame.height+1;
    }));
    assert.equal(clipped,false,'Preview thumbnail should fit its card');
  }
  await load(await fs.readFile(path.join(root,'reference-report.html'),'utf8'));
  assert.equal((await sample('.section')).bg,'rgb(255, 238, 221)');
  assert.equal((await sample('.section')).radius,'9px');
  assert.equal((await sample('.kpi-value')).ink,'rgb(118, 51, 20)');
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  const report={styles:results,pickerDirectSelection:true,pickerResponsive:true,referenceOverridesPreset:true,externalRequests:external,jsErrors:errors};
  await fs.writeFile(path.join(root,'browser-results.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({styles:results.length,referenceOverridesPreset:true,externalRequests:0,jsErrors:0}));
  await context.close();
} finally {await browser.close();}
