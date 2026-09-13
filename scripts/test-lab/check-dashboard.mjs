// Development-only browser QA, using the approved dependency runtime. No downloads.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const args = Object.fromEntries(process.argv.slice(2).reduce((out, v, i, all) => {
  if (v.startsWith('--')) out.push([v.slice(2), all[i + 1]]);
  return out;
}, []));
if (!args.modules || !args.lab || !args.output) throw new Error('--modules, --lab, --output required');
const req = createRequire(path.join(path.resolve(args.modules), '_lab_check.cjs'));
const { chromium } = req('playwright');
await fs.mkdir(args.output, { recursive: true });
const browser = await chromium.launch({channel: 'msedge', headless: true});
try {
  const context = await browser.newContext({acceptDownloads:true, permissions:['clipboard-read','clipboard-write']});
  const page = await context.newPage();
  const errors = [], external = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {if (/^https?:/.test(request.url())) external.push(request.url());});
  await page.goto(pathToFileURL(path.resolve(args.lab, '00_START_HERE.html')).href);
  if (await page.locator('article').count() !== 35) throw new Error('Missing cases');
  if (await page.locator('.copy').count() !== 55) throw new Error('Missing prompts');
  if (await page.locator('article select').evaluateAll(els=>els.some(e=>e.value!=='미실행'))) throw new Error('Premature verdict');
  for (const width of [1280, 390]) {
    await page.setViewportSize({width, height:900});
    const overflow = await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    if (overflow) throw new Error('Page overflow at '+width);
    await page.screenshot({path:path.join(args.output,`dashboard-${width}.png`),fullPage:false});
  }
  await page.setViewportSize({width:1280,height:900});
  await page.locator('#T09 .copy').click();
  await page.waitForFunction(()=>document.getElementById('status').textContent.includes('요청 하나를 복사했습니다'));
  const copied = await page.evaluate(()=>navigator.clipboard.readText());
  const expected = await page.locator('#T09-1').textContent();
  if (copied.replace(/\r\n/g,'\n') !== expected.replace(/\r\n/g,'\n')) throw new Error('Clipboard differs from prompt (lengths '+copied.length+'/'+expected.length+')');
  await page.locator('#filter').selectOption('external');
  if (await page.locator('article:visible').count() !== 9) throw new Error('Wrong external filter');
  await page.locator('#filter').selectOption('all');
  await page.locator('#T01 select').selectOption('판단보류');
  await page.locator('#note-T01').fill('UI TEST ONLY: <script>not executed</script>');
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#download').click();
  const download = await downloadPromise;
  const downloaded = path.join(args.output,'ui-download-test.md');
  await download.saveAs(downloaded);
  const result = await fs.readFile(downloaded,'utf8');
  if (!result.includes('판정: 판단보류') || !result.includes('UI TEST ONLY') || (result.match(/^## /gm)||[]).length!==35) throw new Error('Download is incomplete');
  if (errors.length || external.length) throw new Error(JSON.stringify({errors, external}));
  const report = {cases:35,prompts:55,widths:[1280,390],clipboardExact:true,downloadCases:35,externalRequests:external,jsErrors:errors};
  await fs.writeFile(path.join(args.output,'browser-results.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
  await context.close();
} finally {await browser.close();}
