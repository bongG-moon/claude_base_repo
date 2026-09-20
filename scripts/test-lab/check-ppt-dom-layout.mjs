// Synthetic DOM only: no user browser profile, source documents, Office or network.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const args = Object.fromEntries(process.argv.slice(2).reduce((xs, x, i, a) => {
  if (x.startsWith('--')) xs.push([x.slice(2), a[i + 1]]); return xs;
}, []));
if (!args.modules) throw Error('--modules must point to approved existing node_modules; nothing is installed');
const require = createRequire(path.join(path.resolve(args.modules), '_ppt_dom_test.cjs'));
const {chromium} = require('playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const source = await fs.readFile(path.join(root, 'company-agent-plugin/scripts/company_agent/ppt_dom_capture.js'), 'utf8');
const browser = await chromium.launch({channel: args.channel || 'msedge', headless: true});
let networkRequests = 0;
try {
  const page = await browser.newPage({viewport: {width: 1200, height: 900}});
  await page.route('**/*', route => { networkRequests++; return route.abort(); });
  const captured = [];
  async function measure(style, attributes = '') {
    await page.setContent(`<style>body{margin:0}.slide{width:960px;height:540px;${style}}
      .card{width:200px;height:100px;background:rgb(0,0,255)}</style>
      <section class="slide" ${attributes}><div class="card"></div></section>`);
    const before = await page.locator('.card').evaluate(node => {
      const rect = node.getBoundingClientRect(); return {x: rect.x, y: rect.y, w: rect.width, h: rect.height};
    });
    await page.addScriptTag({content: source.replace('__COMPANY_OPTIONS__', JSON.stringify({selector: '.slide', outputId: 'capture-result'}))});
    // The shipped code waits for load; trigger it only for this isolated fixture.
    await page.evaluate(() => window.dispatchEvent(new Event('load')));
    return {before, result: JSON.parse(await page.locator('#capture-result').textContent())};
  }
  for (const style of ['display:flex;align-items:center;justify-content:center', 'display:grid;place-items:center']) {
    const {before, result} = await measure(style);
    assert.equal(result.error, undefined, result.error);
    const shape = result.pages[0].elements.find(e => e.kind === 'shape');
    for (const key of ['x', 'y', 'w', 'h']) assert.ok(Math.abs(shape[key] - before[key]) < .01, `${style}: ${key} changed`);
    assert.deepEqual(before, {x: 380, y: 220, w: 200, h: 100});
    captured.push({display: style.split(';')[0], original: before, converted: {x: shape.x, y: shape.y, w: shape.w, h: shape.h}});
  }
  for (const [style, attributes] of [['display:none', ''], ['visibility:hidden', ''],
      ['transform:scale(.5)', ''], ['rotate:5deg', ''], ['display:block', 'hidden']]) {
    const {result} = await measure(style, attributes);
    assert.ok(result.error, `Ambiguous hidden/transformed slide silently accepted: ${style} ${attributes}`);
  }
  assert.equal(networkRequests, 0);
  console.log(JSON.stringify({preserved: captured, explicitRejections: 5, networkRequests, sourceFilesModified: false}));
} finally { await browser.close(); }
