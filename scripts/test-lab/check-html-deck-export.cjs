#!/usr/bin/env node
'use strict';
// Usage: node scripts/test-lab/check-html-deck-export.cjs [evidence-directory]
// NODE_PATH may point to existing playwright/playwright-core modules.
// PRESENTATION_TEST_BROWSER may name an existing Chrome/Edge/Chromium executable.
// No dependencies or browsers are installed. Only new synthetic evidence is written.
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const exporter = require(path.join(root, 'standalone-skills/presentation/scripts/export_pptx.cjs'));
const parent = path.resolve(process.argv[2] || path.join(root, '.smoke/html-deck-export'));
fs.mkdirSync(parent, { recursive: true });
const out = fs.mkdtempSync(path.join(parent, 'run-'));
const options = { timeout: 120000, ...(process.env.PRESENTATION_TEST_BROWSER ? { browser: process.env.PRESENTATION_TEST_BROWSER } : {}) };
const summary = { pass: false, output: out, checks: [], results: [] };

function fixture(rootVariables = true, secondWidth = 1600) {
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>Export fixture</title><style>
${rootVariables ? ':root{--slide-width:1600px;--slide-height:900px}' : ''}
body{margin:0}.slide{width:1600px;height:900px;position:relative;background:white;font:20px Arial,sans-serif}
.num{position:absolute;font-weight:bold;top:180px}h1{position:absolute;left:80px;top:50px;font-size:36px}
.line{position:absolute;left:80px;top:350px;width:250px;line-height:1.3}
</style></head><body onload="document.querySelector('h1').textContent='SOURCE SCRIPT EXECUTED'">
<main id="deck"><section class="slide" id="one"><h1>1600 by 900</h1>
<span class="num" style="left:100px">102</span><span class="num" style="left:200px">117</span><span class="num" style="left:300px">129</span>
<div style="position:absolute;left:90px;top:210px;width:250px;height:80px;background:#176c66"></div>
<p class="line">First line<br>Second line</p></section>
<section class="slide" id="two" style="width:${secondWidth}px"><h1>Second slide</h1>
<span style="position:absolute;left:1590px;top:300px;white-space:nowrap">Intentional source overflow</span></section></main>
<script>document.querySelector('h1').textContent='SOURCE SCRIPT EXECUTED';</script></body></html>`;
}

// Independent ZIP validation: inflate all entries and check their declared size/CRC.
function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function inspectPptx(file) {
  const bytes = fs.readFileSync(file), members = new Map();
  let end = bytes.length - 22;
  while (end >= Math.max(0, bytes.length - 65557) && bytes.readUInt32LE(end) !== 0x06054b50) end--;
  assert.ok(end >= 0, 'ZIP end directory exists');
  const count = bytes.readUInt16LE(end + 10);
  let cursor = bytes.readUInt32LE(end + 16);
  for (let index = 0; index < count; index++) {
    assert.equal(bytes.readUInt32LE(cursor), 0x02014b50);
    const method = bytes.readUInt16LE(cursor + 10), length = bytes.readUInt32LE(cursor + 20);
    const nameLength = bytes.readUInt16LE(cursor + 28), extraLength = bytes.readUInt16LE(cursor + 30), commentLength = bytes.readUInt16LE(cursor + 32);
    const name = bytes.toString('utf8', cursor + 46, cursor + 46 + nameLength), local = bytes.readUInt32LE(cursor + 42);
    assert.equal(bytes.readUInt32LE(local), 0x04034b50);
    const start = local + 30 + bytes.readUInt16LE(local + 26) + bytes.readUInt16LE(local + 28);
    const compressed = bytes.subarray(start, start + length);
    assert.ok(method === 0 || method === 8);
    const data = method === 8 ? zlib.inflateRawSync(compressed) : compressed;
    assert.equal(data.length, bytes.readUInt32LE(cursor + 24), `${name}: size`);
    assert.equal(crc32(data), bytes.readUInt32LE(cursor + 16), `${name}: CRC`);
    members.set(name, data.toString('utf8'));
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  const presentation = members.get('ppt/presentation.xml');
  const size = presentation.match(/<p:sldSz\b[^>]*\bcx="(\d+)"[^>]*\bcy="(\d+)"/);
  assert.ok(size, 'PowerPoint slide size exists');
  assert.deepEqual(size.slice(1).map(Number), [1600 * 9525, 900 * 9525]);
  const xml = members.get('ppt/slides/slide1.xml');
  const shapes = [...xml.matchAll(/<p:sp(?:\s[^>]*)?>[\s\S]*?<\/p:sp>/g)].map(match => match[0]);
  for (const label of ['102', '117', '129']) {
    const shape = shapes.find(value => value.includes(`<a:t>${label}</a:t>`));
    assert.ok(shape, `native text ${label}`);
    assert.match(shape, /<a:bodyPr\b[^>]*\bwrap="none"/, `${label} remains on one line`);
  }
  assert.ok(xml.includes('1600 by 900'));
  assert.ok(!xml.includes('SOURCE SCRIPT EXECUTED'));
  return { members: count, zipCrcValid: true, slideSizeEmu: size.slice(1).map(Number), numericLabelsNoWrap: ['102', '117', '129'] };
}

async function test() {
  for (const [name, vars, width] of [['custom', true, 1600], ['bbox', false, 1600], ['mixed', true, 1500]]) {
    const input = path.join(out, `${name}.html`), output = path.join(out, `${name}.pptx`);
    fs.writeFileSync(input, fixture(vars, width), { flag: 'wx' });
    const result = await exporter.run({ ...options, input, output });
    fs.writeFileSync(path.join(out, `${name}-result.json`), JSON.stringify(result, null, 2));
    if (name === 'mixed') {
      assert.equal(result.status, 'failed');
      assert.equal(result.code, 'inconsistent_slide_dimensions');
      assert.equal(fs.existsSync(output), false);
      assert.equal(result.sourcePreserved, true);
      summary.checks.push('mixed slide sizes rejected without output or source changes');
      summary.results.push({ name, code: result.code });
      continue;
    }
    assert.equal(result.status, 'ok', JSON.stringify(result));
    assert.equal(result.dimensions.width, 1600);
    assert.equal(result.dimensions.height, 900);
    assert.equal(result.dimensions.basis, vars ? 'root-css-variables' : 'first-slide-unscaled-bounds');
    assert.equal(result.sourcePreserved, true);
    assert.equal(result.sanitized.scripts, 1);
    assert.equal(result.sanitized.eventAttributes, 1);
    assert.equal(result.authoredScriptsExecuted, false);
    assert.equal(result.downloadsTriggered, 0);
    assert.deepEqual(result.blockedRequests, []);
    assert.deepEqual(result.pageErrors, []);
    assert.ok(!result.textLinePreservation.changes.some(change => change.text.includes('First line')));
    assert.ok(result.layoutWarnings.some(warning => warning.slide === 2));
    const zip = inspectPptx(output);
    summary.results.push({ name, dimensions: result.dimensions, wrapChanges: result.textLinePreservation.changed, ...zip });
    summary.checks.push(`${name}: 1600x900 native output, valid ZIP, numeric nowrap, explicit line break preserved, source overflow reported, scripts stripped, no external requests or downloads`);
    if (name === 'custom') {
      await assert.rejects(exporter.run({ ...options, input, output }), { code: 'output_exists' });
      summary.checks.push('existing PPTX output rejected without overwrite');
    }
  }
  summary.pass = true;
}
test().catch(error => { summary.error = error.stack || String(error); process.exitCode = 1; }).finally(() => {
  fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(summary, null, 2));
  console.log(JSON.stringify(summary, null, 2));
});
