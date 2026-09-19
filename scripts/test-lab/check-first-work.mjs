// Local browser checks. No package download, live profile, or business execution.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, item, i, all) => {
  if (item.startsWith('--')) pairs.push([item.slice(2), all[i + 1]]);
  return pairs;
}, []));
if (!args.modules || !args.output || !args.report) throw new Error('--modules, --output and --report required');
const req = createRequire(path.join(path.resolve(args.modules), '_first_work_qa.cjs'));
const { chromium } = req('playwright');
await fs.mkdir(args.output, {recursive:true});
const browser = await chromium.launch({channel:'msedge',headless:true});
try {
  const context = await browser.newContext({permissions:['clipboard-read','clipboard-write']});
  const page = await context.newPage(), errors = [], external = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {if (/^https?:/.test(request.url())) external.push(request.url());});
  await page.goto(pathToFileURL(path.resolve('company-agent-plugin/resources/first-work.html')).href);
  if (await page.locator('[data-copy]').count() !== 7) throw new Error('Missing first-work choices');
  for (const button of await page.locator('[data-copy]').all()) {
    const target = await button.getAttribute('data-copy');
    await button.click();
    if ((await page.evaluate(()=>navigator.clipboard.readText())).replace(/\r\n/g,'\n') !==
        (await page.locator('#'+target).inputValue()).replace(/\r\n/g,'\n')) throw new Error('Copy mismatch: '+target);
  }
  // Exercise the manual selection fallback without granting extra permissions.
  await page.evaluate(()=>{
    Object.defineProperty(navigator,'clipboard',{value:undefined,configurable:true});
    document.execCommand=()=>false;
  });
  await page.locator('[data-copy]').first().click();
  if (!(await page.locator('#status').textContent()).includes('직접 복사')) throw new Error('Missing copy fallback');
  for (const width of [1280,390]) {
    await page.setViewportSize({width,height:900});
    await page.evaluate(()=>scrollTo(0,0));
    if (await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw new Error('Guide overflow');
    await page.screenshot({path:path.join(args.output,`first-work-${width}.png`)});
  }
  await page.goto(pathToFileURL(path.resolve(args.report)).href);
  for (const width of [1280,390]) {
    await page.setViewportSize({width,height:900});
    if (await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw new Error('Report overflow');
    await page.screenshot({path:path.join(args.output,`diagnostics-${width}.png`)});
  }
  if (errors.length || external.length) throw new Error(JSON.stringify({errors,external}));
  console.log(JSON.stringify({status:'passed',choices:7,widths:[1280,390],clipboard:true,manualFallback:true,externalRequests:0,pageErrors:0}));
} finally {await browser.close();}
