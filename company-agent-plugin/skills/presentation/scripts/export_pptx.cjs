#!/usr/bin/env node
'use strict';
// Optional export of a saved, standalone HTML deck. No installs or browser downloads.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const zlib = require('node:zlib');
const { createRequire } = require('node:module');
const BUNDLE_SHA256 = 'df8fca27232864a4ad01d7ad8a5be1e867ab26b9562a3e5e66c8429b644256d4';
const BUNDLE = path.join(__dirname, '../assets/vendor/dom-to-pptx/dom-to-pptx.bundle.js');
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
class ExportError extends Error { constructor(code, message, detail) { super(message); this.code = code; this.detail = detail; } }
const fail = (code, message, detail) => { throw new ExportError(code, message, detail); };

// Small OOXML ZIP adapter: preserve every untouched member's compressed bytes.
// The converter emits ordinary ZIP (no encryption or ZIP64); no extra npm package is required.
function readZip(bytes) {
  let end = bytes.length - 22;
  while (end >= Math.max(0, bytes.length - 65557) && bytes.readUInt32LE(end) !== 0x06054b50) end--;
  if (end < 0 || end < bytes.length - 65557) fail('invalid_pptx_zip', 'PPTX ZIP 중앙 디렉터리가 없습니다.');
  const count = bytes.readUInt16LE(end + 10), offset = bytes.readUInt32LE(end + 16);
  if (count === 65535 || offset === 0xffffffff) fail('unsupported_pptx_zip', 'ZIP64 출력은 지원하지 않습니다.');
  const entries = []; let cursor = offset;
  for (let i = 0; i < count; i++) {
    if (bytes.readUInt32LE(cursor) !== 0x02014b50) fail('invalid_pptx_zip', 'PPTX ZIP 항목이 올바르지 않습니다.');
    const nameLength = bytes.readUInt16LE(cursor + 28), extraLength = bytes.readUInt16LE(cursor + 30), commentLength = bytes.readUInt16LE(cursor + 32);
    const nameBytes = bytes.subarray(cursor + 46, cursor + 46 + nameLength), localOffset = bytes.readUInt32LE(cursor + 42);
    const method = bytes.readUInt16LE(cursor + 10), compressedSize = bytes.readUInt32LE(cursor + 20), size = bytes.readUInt32LE(cursor + 24), flags = bytes.readUInt16LE(cursor + 8);
    if (flags & 1 || ![0, 8].includes(method) || size === 0xffffffff) fail('unsupported_pptx_zip', '암호화 또는 지원하지 않는 PPTX ZIP 형식입니다.');
    const dataOffset = localOffset + 30 + bytes.readUInt16LE(localOffset + 26) + bytes.readUInt16LE(localOffset + 28);
    entries.push({ name: nameBytes.toString('utf8'), nameBytes, flags: flags & ~8, method, time: bytes.readUInt16LE(cursor + 12), date: bytes.readUInt16LE(cursor + 14), crc: bytes.readUInt32LE(cursor + 16), size, compressed: bytes.subarray(dataOffset, dataOffset + compressedSize), attributes: bytes.readUInt32LE(cursor + 38) });
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}
function zipText(entry) { return (entry.method === 8 ? zlib.inflateRawSync(entry.compressed) : entry.compressed).toString('utf8'); }
const crcTable = Array.from({ length: 256 }, (_, n) => { for (let i = 0; i < 8; i++) n = n & 1 ? 0xedb88320 ^ (n >>> 1) : n >>> 1; return n >>> 0; });
function crc32(bytes) { let crc = 0xffffffff; for (const byte of bytes) crc = crcTable[(crc ^ byte) & 255] ^ (crc >>> 8); return (crc ^ 0xffffffff) >>> 0; }
function writeZip(entries, replacements) {
  const localParts = [], centralParts = []; let offset = 0;
  for (const original of entries) {
    const entry = { ...original };
    if (replacements.has(entry.name)) { const bytes = Buffer.from(replacements.get(entry.name), 'utf8'); entry.size = bytes.length; entry.crc = crc32(bytes); entry.compressed = entry.method === 8 ? zlib.deflateRawSync(bytes) : bytes; }
    const local = Buffer.alloc(30); local.writeUInt32LE(0x04034b50); local.writeUInt16LE(20, 4); local.writeUInt16LE(entry.flags, 6); local.writeUInt16LE(entry.method, 8); local.writeUInt16LE(entry.time, 10); local.writeUInt16LE(entry.date, 12); local.writeUInt32LE(entry.crc, 14); local.writeUInt32LE(entry.compressed.length, 18); local.writeUInt32LE(entry.size, 22); local.writeUInt16LE(entry.nameBytes.length, 26);
    const central = Buffer.alloc(46); central.writeUInt32LE(0x02014b50); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6); central.writeUInt16LE(entry.flags, 8); central.writeUInt16LE(entry.method, 10); central.writeUInt16LE(entry.time, 12); central.writeUInt16LE(entry.date, 14); central.writeUInt32LE(entry.crc, 16); central.writeUInt32LE(entry.compressed.length, 20); central.writeUInt32LE(entry.size, 24); central.writeUInt16LE(entry.nameBytes.length, 28); central.writeUInt32LE(entry.attributes, 38); central.writeUInt32LE(offset, 42);
    localParts.push(local, entry.nameBytes, entry.compressed); centralParts.push(central, entry.nameBytes); offset += local.length + entry.nameBytes.length + entry.compressed.length;
  }
  const central = Buffer.concat(centralParts), end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10); end.writeUInt32LE(central.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...localParts, central, end]);
}

function argumentsFor(argv) {
  const options = { output: 'presentation/outputs/발표본.pptx', timeout: 120000 };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--help' || arg === '-h') { options.help = true; continue; }
    if (arg === '--audit-only') { options.auditOnly = true; continue; }
    if (['--input', '--output', '--browser', '--node-modules', '--timeout', '--screenshots'].includes(arg)) {
      if (!argv[i + 1] || argv[i + 1].startsWith('--')) fail('invalid_arguments', `${arg} 값이 필요합니다.`);
      options[arg.slice(2)] = argv[++i];
    } else if (!arg.startsWith('-') && !options.input) options.input = arg;
    else fail('invalid_arguments', `알 수 없는 인자: ${arg}`);
  }
  options.timeout = Number(options.timeout);
  if (!Number.isFinite(options.timeout) || options.timeout < 1000 || options.timeout > 600000) fail('invalid_arguments', '--timeout은 1000~600000밀리초여야 합니다.');
  if (!options.help && !options.input) fail('invalid_arguments', '--input으로 저장된 독립 HTML 발표본을 지정하세요.');
  return options;
}

function resolvePlaywright(modulePath) {
  const attempts = [];
  const resolvers = [require];
  if (modulePath) {
    const directory = path.resolve(modulePath);
    resolvers.unshift(createRequire(path.join(directory, '__html_deck_resolver__.cjs')));
    for (const name of ['playwright', 'playwright-core']) {
      try { return { library: require(path.join(directory, name)), resolved: path.join(directory, name) }; }
      catch (error) { attempts.push(`${name}: ${error.code || 'load_failed'}`); }
    }
  }
  for (const resolver of resolvers) for (const name of ['playwright', 'playwright-core']) {
    try { return { library: resolver(name), resolved: resolver.resolve(name) }; }
    catch (error) { attempts.push(`${name}: ${error.code || 'load_failed'}`); }
  }
  fail('playwright_not_found', '설치된 playwright 또는 playwright-core를 찾지 못했습니다. 기존 node_modules 경로를 --node-modules 또는 NODE_PATH로 지정하세요. 자동 설치하지 않습니다.', attempts);
}

function resolveBrowser(explicit, chromium) {
  if (explicit) {
    const file = path.resolve(explicit);
    if (!fs.existsSync(file) || !fs.statSync(file).isFile()) fail('browser_not_found', '--browser 실행 파일이 없습니다.', file);
    return file;
  }
  const candidates = [];
  if (process.platform === 'win32') {
    for (const base of [process.env.PROGRAMFILES, process.env['PROGRAMFILES(X86)'], process.env.LOCALAPPDATA].filter(Boolean)) {
      candidates.push(path.join(base, 'Microsoft/Edge/Application/msedge.exe'), path.join(base, 'Google/Chrome/Application/chrome.exe'), path.join(base, 'Chromium/Application/chrome.exe'));
    }
  } else if (process.platform === 'darwin') {
    candidates.push('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge', '/Applications/Chromium.app/Contents/MacOS/Chromium');
  } else candidates.push('/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/microsoft-edge', '/usr/bin/chromium', '/usr/bin/chromium-browser');
  // executablePath only reports an existing expected location; it never installs a browser.
  try { candidates.push(chromium.executablePath()); } catch (_) { /* no bundled path */ }
  const found = candidates.find(file => file && fs.existsSync(file) && fs.statSync(file).isFile());
  if (!found) fail('browser_not_found', '설치된 Chrome/Edge/Chromium을 찾지 못했습니다. --browser로 기존 실행 파일을 지정하세요. 브라우저를 다운로드하지 않습니다.');
  return found;
}

async function run(options) {
  const input = path.resolve(options.input), output = path.resolve(options.output);
  let sourceBytes;
  try {
    if (!fs.statSync(input).isFile()) fail('invalid_input', '입력은 HTML 파일이어야 합니다.');
    if (fs.statSync(input).size > 20 * 1024 * 1024) fail('input_too_large', 'HTML 파일은 20MB 이하여야 합니다.');
    sourceBytes = fs.readFileSync(input);
  } catch (error) { if (error instanceof ExportError) throw error; fail('input_not_found', '입력 HTML 파일을 읽을 수 없습니다.', error.code); }
  if (input === output) fail('source_output_conflict', '원본 HTML과 출력 경로는 달라야 합니다.');
  if (path.extname(output).toLowerCase() !== '.pptx') fail('invalid_output', '출력 확장자는 .pptx여야 합니다.');
  if (!options.auditOnly && fs.existsSync(output)) fail('output_exists', '기존 출력은 덮어쓰지 않습니다. 새 --output 경로를 지정하세요.', output);
  const screenshots = options.screenshots ? path.resolve(options.screenshots) : null;
  if (screenshots && (!options.auditOnly || fs.existsSync(screenshots))) fail('invalid_screenshot_directory', '화면 검사 시에만 기존에 없는 --screenshots 폴더를 지정하세요.');
  if (!fs.existsSync(BUNDLE)) fail('bundle_missing', '배포된 dom-to-pptx browser bundle이 없습니다.');
  const bundleBytes = fs.readFileSync(BUNDLE);
  if (sha256(bundleBytes) !== BUNDLE_SHA256) fail('bundle_integrity_failed', '동봉 변환 라이브러리의 SHA-256이 고정 버전과 다릅니다.');
  const playwright = resolvePlaywright(options['node-modules']);
  const browserPath = resolveBrowser(options.browser, playwright.library.chromium);
  const result = {
    status: 'failed', stage: 'browser_launch', input, output,
    sourceSha256Before: sha256(sourceBytes), browser: browserPath, playwright: playwright.resolved,
    library: { name: 'dom-to-pptx', version: '2.1.2', sha256: BUNDLE_SHA256 },
    blockedRequests: [], pageErrors: [], browserWarnings: [], downloadsTriggered: 0,
    limitations: [
      '글꼴은 PPTX에 자동 포함하지 않습니다. 받는 컴퓨터의 설치 글꼴에 따라 표시가 달라질 수 있습니다.',
      'SVG는 벡터 그림으로 보존하며 Office의 Convert to Shape가 필요할 수 있습니다. 네이티브 차트 데이터 개체로 변환하지 않습니다.',
      '복잡한 CSS 효과는 그림으로 변환되거나 차이가 생길 수 있습니다. 네이티브 개체 수와 실제 화면은 생성된 PPTX를 별도로 확인하세요.'
    ]
  };
  let browser;
  try {
    try { browser = await playwright.library.chromium.launch({ executablePath: browserPath, headless: true }); }
    catch (error) { fail('browser_launch_failed', '설치된 브라우저를 시작하지 못했습니다.', String(error.message)); }
    const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1, acceptDownloads: false, serviceWorkers: 'block' });
    await context.route('**/*', route => {
      const url = route.request().url();
      if (/^(data:|blob:)/i.test(url)) return route.continue();
      result.blockedRequests.push(url.slice(0, 500)); return route.abort('blockedbyclient');
    });
    const page = await context.newPage();
    page.on('pageerror', error => result.pageErrors.push(error.message));
    page.on('console', message => { if (['warning', 'error'].includes(message.type()) && result.browserWarnings.length < 30) result.browserWarnings.push(message.text().slice(0, 500)); });
    page.on('download', download => { result.downloadsTriggered++; download.cancel().catch(() => {}); });
    result.stage = 'sanitize';
    const scriptHash = crypto.createHash('sha256').update(bundleBytes).digest('base64');
    const prepared = await page.evaluate(({ source, scriptHash }) => {
      // DOMParser's document is inert. No source scripts are adopted into the live page.
      const documentCopy = new DOMParser().parseFromString(source, 'text/html');
      const removed = { scripts: 0, activeElements: 0, eventAttributes: 0, javascriptUrls: 0, editorUi: 0 };
      const assets = [];
      const resource = (url, location) => {
        const value = String(url || '').trim();
        if (value && !value.startsWith('#') && !/^data:/i.test(value)) assets.push({ location, url: value.slice(0, 300) });
      };
      function cleanTree(root) {
        root.querySelectorAll('template').forEach(template => cleanTree(template.content));
        root.querySelectorAll('script').forEach(node => { removed.scripts++; node.remove(); });
        root.querySelectorAll('iframe,frame,frameset,object,embed,applet,portal,fencedframe,base,form,animate,set,animateTransform,animateMotion,link[rel="modulepreload"],link[rel="preload"],link[rel="prefetch"]').forEach(node => { removed.activeElements++; node.remove(); });
        root.querySelectorAll('meta[http-equiv]').forEach(node => node.remove());
        root.querySelectorAll('*').forEach(node => {
          for (const attribute of Array.from(node.attributes)) {
            if (/^on/i.test(attribute.name)) { node.removeAttribute(attribute.name); removed.eventAttributes++; }
            else if (['href', 'xlink:href', 'src', 'action', 'formaction'].includes(attribute.name.toLowerCase()) && /^\s*javascript:/i.test(attribute.value)) { node.removeAttribute(attribute.name); removed.javascriptUrls++; }
          }
          const tag = node.tagName.toLowerCase();
          if (['img', 'source', 'audio', 'video', 'track', 'input'].includes(tag)) resource(node.getAttribute('src'), `${tag}[src]`);
          if (tag === 'video') resource(node.getAttribute('poster'), 'video[poster]');
          if (['image', 'use'].includes(tag)) resource(node.getAttribute('href') || node.getAttribute('xlink:href'), `${tag}[href]`);
          if (node.hasAttribute('srcset')) { assets.push({ location: `${tag}[srcset]`, url: 'srcset is not supported; bundle a single data URL image first' }); node.removeAttribute('srcset'); }
          if (tag === 'link' && /stylesheet/i.test(node.getAttribute('rel') || '')) { resource(node.getAttribute('href'), 'link[stylesheet]'); node.remove(); }
        });
      }
      cleanTree(documentCopy);
      const deck = documentCopy.querySelector('main#deck');
      if (!deck) return { error: 'main#deck이 없습니다.', removed, assets };
      const viewport = documentCopy.querySelector('#hd-viewport');
      if (viewport && viewport.contains(deck)) viewport.replaceWith(deck);
      documentCopy.querySelectorAll('[data-hd-ui],#hd-editor,.hd-selection').forEach(node => { removed.editorUi++; node.remove(); });
      documentCopy.body.classList.remove('hd-ready', 'hd-editing');
      documentCopy.documentElement.style.removeProperty('--hd-toolbar-height');
      const slides = Array.from(deck.children).filter(node => node.matches('section.slide'));
      slides.forEach(slide => {
        slide.classList.remove('hd-current', 'hd-hidden');
        slide.removeAttribute('hidden');
        slide.querySelectorAll('[contenteditable],[data-hd-editable]').forEach(node => { node.removeAttribute('contenteditable'); node.removeAttribute('data-hd-editable'); });
      });
      documentCopy.querySelectorAll('style,[style]').forEach(node => {
        const css = node.tagName.toLowerCase() === 'style' ? node.textContent : node.getAttribute('style');
        for (const match of css.matchAll(/url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*))\s*\)/gi)) resource(match[1] ?? match[2] ?? match[3], 'CSS url()');
        if (/@import\b/i.test(css)) assets.push({ location: 'CSS @import', url: 'CSS imports must be bundled first' });
      });
      const csp = documentCopy.createElement('meta'); csp.httpEquiv = 'Content-Security-Policy';
      csp.content = `default-src 'none'; script-src 'sha256-${scriptHash}'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'`;
      documentCopy.head.prepend(csp);
      const staticStyle = documentCopy.createElement('style');
      staticStyle.textContent = `html,body{margin:0!important;padding:0!important;overflow:visible!important}main#deck{height:auto!important;display:block!important;position:static!important;transform:none!important;scale:none!important;translate:none!important;zoom:1!important}main#deck>section.slide{flex:none!important;margin:0!important;position:relative!important;left:auto!important;top:auto!important;transform:none!important;translate:none!important;rotate:none!important;scale:none!important;zoom:1!important;visibility:visible!important;opacity:1!important;animation:none!important;transition:none!important}main#deck>section.slide aside.notes,main#deck>section.slide .speaker-notes,main#deck>section.slide [data-notes]{display:none!important}`;
      documentCopy.head.append(staticStyle);
      return { html: '<!DOCTYPE html>\n' + documentCopy.documentElement.outerHTML, slideCount: slides.length, svgCount: deck.querySelectorAll('svg').length, removed, assets };
    }, { source: sourceBytes.toString('utf8'), scriptHash });
    result.sanitized = prepared.removed;
    if (prepared.error || !prepared.slideCount) fail('invalid_deck', prepared.error || 'section.slide가 없습니다.');
    if (prepared.assets.length) fail('non_standalone_assets', '외부 또는 상대 경로 자산은 읽지 않습니다. slides.py로 자산을 포함한 독립 HTML을 먼저 만드세요.', prepared.assets.slice(0, 30));
    result.slideCount = prepared.slideCount; result.svgCount = prepared.svgCount;
    result.stage = 'static_render';
    await page.setContent(prepared.html, { waitUntil: 'load', timeout: 30000 });
    await page.evaluate(async () => {
      for (const slide of document.querySelectorAll('main#deck > section.slide')) if (getComputedStyle(slide).display === 'none') slide.style.setProperty('display', 'block', 'important');
      await Promise.race([document.fonts.ready, new Promise((_, reject) => setTimeout(() => reject(Error('Font loading timeout')), 15000))]);
    });
    const dimensions = await page.evaluate(() => {
      const rootStyle = getComputedStyle(document.documentElement), first = document.querySelector('main#deck > section.slide');
      const rawWidth = rootStyle.getPropertyValue('--slide-width').trim(), rawHeight = rootStyle.getPropertyValue('--slide-height').trim();
      const pixels = value => /^\d+(?:\.\d+)?px$/.test(value) ? parseFloat(value) : null;
      const width = pixels(rawWidth), height = pixels(rawHeight), box = first.getBoundingClientRect();
      return width && height ? { width, height, basis: 'root-css-variables', rawWidth, rawHeight } : { width: box.width, height: box.height, basis: 'first-slide-unscaled-bounds', rawWidth, rawHeight };
    });
    if (![dimensions.width, dimensions.height].every(n => Number.isFinite(n) && n > 0 && n <= 20000)) fail('invalid_slide_dimensions', '슬라이드의 실제 너비와 높이를 확인할 수 없습니다.', dimensions);
    await page.setViewportSize({ width: Math.ceil(dimensions.width), height: Math.ceil(dimensions.height) });
    result.dimensions = dimensions;
    result.slideSizes = await page.locator('main#deck > section.slide').evaluateAll(nodes => nodes.map(node => ({ id: node.id || null, width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height })));
    if (result.slideSizes.some(size => Math.abs(size.width - dimensions.width) > 1 || Math.abs(size.height - dimensions.height) > 1)) fail('inconsistent_slide_dimensions', '모든 슬라이드의 실제 크기가 같아야 하며 선언한 크기와 일치해야 합니다. 원본 크기를 강제로 바꾸지 않습니다.', { dimensions, slides: result.slideSizes });
    if (result.blockedRequests.length || result.pageErrors.length) fail('static_render_failed', '정적 HTML에 차단된 요청 또는 렌더 오류가 있습니다.', { blockedRequests: result.blockedRequests, pageErrors: result.pageErrors });
    // Measure the original static layout once. Do not alter author text, fonts, widths or heights.
    const measured = await page.evaluate(({ auditOnly }) => {
      const normalize = text => text.replace(/\s+/g, ' ').trim();
      return Array.from(document.querySelectorAll('main#deck > section.slide')).map((slide, index) => {
        const bounds = slide.getBoundingClientRect(), candidates = [], overflow = [], htmlTexts = [], unhandledMultiline = [];
        for (const element of slide.querySelectorAll('*')) {
          if (!(element instanceof HTMLElement) || element.closest('svg,aside.notes,.speaker-notes') || (element.closest('[data-notes]') && element.closest('[data-notes]') !== slide)) continue;
          const text = normalize(element.textContent || ''); if (!text || text.length > 160) continue;
          const style = getComputedStyle(element), box = element.getBoundingClientRect();
          if (style.display === 'none' || style.visibility === 'hidden' || !box.width || !box.height) continue;
          const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT), rects = [];
          for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            if (!node.textContent.trim()) continue;
            const range = document.createRange(); range.selectNodeContents(node);
            for (const rect of range.getClientRects()) if (rect.width > .1 && rect.height > .1) rects.push({ x: rect.left - bounds.left, y: rect.top - bounds.top, width: rect.width, height: rect.height });
          }
          if (!rects.length) continue;
          if ((element.hasAttribute('data-edit') || /^(H[1-6]|P|TD|TH|LI)$/.test(element.tagName)) && !element.querySelector('[data-edit]')) {
            for (const r of rects) htmlTexts.push({text, left:r.x+bounds.left, top:r.y+bounds.top, right:r.x+r.width+bounds.left, bottom:r.y+r.height+bounds.top});
          }
          const outside = rects.some(r => r.x < -1 || r.y < -1 || r.x + r.width > bounds.width + 1 || r.y + r.height > bounds.height + 1);
          const clipped = (element.clientWidth > 0 && element.scrollWidth > element.clientWidth + 2) || (element.clientHeight > 0 && element.scrollHeight > element.clientHeight + 2);
          if (outside || clipped) { if (overflow.length < 20) overflow.push({ tag: element.tagName.toLowerCase(), id: element.id || null, text: text.slice(0, 80), outsideSlide: outside, elementOverflow: clipped }); }
          if (outside) continue;
          if (element.closest('table') || style.writingMode !== 'horizontal-tb') continue;
          const lines = [];
          for (const rect of rects.sort((a, b) => a.y - b.y)) {
            const line = lines.find(l => Math.min(l.bottom, rect.y + rect.height) - Math.max(l.top, rect.y) > Math.min(l.bottom - l.top, rect.height) * .4);
            if (line) { line.top = Math.min(line.top, rect.y); line.bottom = Math.max(line.bottom, rect.y + rect.height); }
            else lines.push({ top: rect.y, bottom: rect.y + rect.height });
          }
          // Capture browser line boundaries only when all inline text is exact
          // and uses supported, same-sized inline styling; do not guess whitespace.
          const textWalker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT), nodes=[];
          for(let node=textWalker.nextNode();node;node=textWalker.nextNode()) nodes.push(node);
          const raw=nodes.map(n=>n.textContent).join('');
          let lineBreakOffsets=[];
          const explicitBreaks=element.querySelectorAll('br').length;
          const safeInline=Array.from(element.querySelectorAll('*')).every(n=>n.tagName==='BR' || (['STRONG','B','EM','I','SPAN','U','S'].includes(n.tagName) && Math.abs(parseFloat(getComputedStyle(n).fontSize)-parseFloat(style.fontSize))<.5));
          if (lines.length > 1 && nodes.length && raw === text && !/\s{2,}/.test(text) && safeInline) {
            let lastTop=null, globalOffset=0;
            for (const node of nodes) {
              for (let offset=0;offset<node.textContent.length;) {
                const width=node.textContent.codePointAt(offset)>0xffff?2:1;
                const charRange=document.createRange(); charRange.setStart(node,offset); charRange.setEnd(node,offset+width);
                const r=charRange.getBoundingClientRect();
                if (r.width && r.height && node.textContent.slice(offset,offset+width).trim()) {
                  if (lastTop!==null && r.top>lastTop+Math.max(2,parseFloat(style.fontSize)*.3)) lineBreakOffsets.push(globalOffset+offset);
                  lastTop=r.top;
                }
                offset+=width;
              }
              globalOffset+=node.textContent.length;
            }
          }
          if (lines.length !== 1 && !lineBreakOffsets.length && !explicitBreaks) {
            if (element.hasAttribute('data-edit') && !element.querySelector('br') && unhandledMultiline.length<20)
              unhandledMultiline.push(text.slice(0,120));
            continue;
          }
          candidates.push({ text, lineBreakOffsets, explicitBreaks, clipped, lineHeight:parseFloat(style.lineHeight)||null, elementX: box.left - bounds.left, elementY: box.top - bounds.top, x: Math.min(...rects.map(r => r.x)), y: Math.min(...rects.map(r => r.y)), width: Math.max(...rects.map(r => r.x + r.width)) - Math.min(...rects.map(r => r.x)), height: lines[0].bottom - lines[0].top, fontSize: parseFloat(style.fontSize) });
          // Some converters emit each explicit <br> line as its own text shape.
          // Record only text nodes that have exactly one observed line.
          if (explicitBreaks) for (const node of nodes) {
            const content=normalize(node.textContent||''); if(!content) continue;
            const range=document.createRange();range.selectNodeContents(node);
            const pieces=Array.from(range.getClientRects()).filter(r=>r.width>.1&&r.height>.1);
            if(pieces.length!==1) continue;
            const r=pieces[0];
            candidates.push({text:content,lineBreakOffsets:[],explicitBreaks:0,clipped:false,lineHeight:parseFloat(style.lineHeight)||null,
              elementX:r.left-bounds.left,elementY:r.top-bounds.top,x:r.left-bounds.left,y:r.top-bounds.top,width:r.width,height:r.height,fontSize:parseFloat(style.fontSize)});
          }
        }
        // SVG text/connector intersections are invisible to ordinary DOM scroll checks.
        // This is a review hint, not a proof of a visual defect.
        const svgIntersections = [];
        for (const svg of auditOnly ? slide.querySelectorAll('svg') : []) {
          const texts = Array.from(svg.querySelectorAll('text')).filter(t => (t.textContent || '').trim()).map(t => ({node:t,text:normalize(t.textContent),box:t.getBoundingClientRect()}));
          for (const t of htmlTexts) texts.push({node:null,text:t.text,box:t});
          const lines = Array.from(svg.querySelectorAll('path,line,polyline')).slice(0, 500);
          for (const textNode of texts.slice(0, 300)) {
            const tb = textNode.box;
            if (tb.right <= tb.left || tb.bottom <= tb.top) continue;
            for (const line of lines) {
              const style = getComputedStyle(line);
              if (style.stroke === 'none' || style.strokeWidth === '0px' || !line.getTotalLength) continue;
              try {
                const length = line.getTotalLength(), matrix = line.getScreenCTM();
                if (!matrix || !Number.isFinite(length) || length <= 0) continue;
                const count = Math.max(2, Math.min(100, Math.ceil(length / 3)));
                let hit = false;
                for (let n = 0; n <= count; n++) {
                  const p = line.getPointAtLength(length * n / count), point = new DOMPoint(p.x,p.y).matrixTransform(matrix);
                  if (point.x > tb.left + 1 && point.x < tb.right - 1 && point.y > tb.top + 1 && point.y < tb.bottom - 1) { hit = true; break; }
                }
                if (hit) { svgIntersections.push({text:textNode.text.slice(0,80), tag:line.tagName.toLowerCase()}); break; }
              } catch (_) { /* unsupported SVG geometry is checked visually */ }
            }
            if (svgIntersections.length >= 20) break;
          }
        }
        const textIntersections = [];
        for (let i=0; auditOnly && i<htmlTexts.length && textIntersections.length<20; i++) for (let j=i+1; j<htmlTexts.length && textIntersections.length<20; j++) {
          const a=htmlTexts[i], b=htmlTexts[j];
          if (a.text === b.text) continue;
          if (Math.min(a.right,b.right)-Math.max(a.left,b.left)>2 && Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>2)
            textIntersections.push([a.text.slice(0,60),b.text.slice(0,60)]);
        }
        const tables = Array.from(slide.querySelectorAll('table')).map(table => {
          const tb=table.getBoundingClientRect();
          return { x:tb.left-bounds.left, y:tb.top-bounds.top, width:tb.width, height:tb.height,
            rows:Array.from(table.rows).map(row => ({height:row.getBoundingClientRect().height,
              cells:Array.from(row.cells).map(cell => {const cs=getComputedStyle(cell), cb=cell.getBoundingClientRect();
                return {width:cb.width,colSpan:cell.colSpan,rowSpan:cell.rowSpan,
                  left:parseFloat(cs.paddingLeft)||0,right:parseFloat(cs.paddingRight)||0,
                  top:parseFloat(cs.paddingTop)||0,bottom:parseFloat(cs.paddingBottom)||0};})}))};
        });
        return { slide: index + 1, candidates, tables, unhandledMultiline, overflow, svgIntersections, textIntersections, scrollOverflow: slide.scrollWidth > slide.clientWidth + 2 || slide.scrollHeight > slide.clientHeight + 2 };
      });
    }, {auditOnly: !!options.auditOnly});
    result.layoutWarnings = measured.filter(m => m.overflow.length || m.scrollOverflow || m.svgIntersections.length || m.textIntersections.length).map(m => ({ slide: m.slide, code: (m.overflow.length || m.scrollOverflow) ? 'source_layout_overflow' : 'source_layout_collision', scrollOverflow: m.scrollOverflow, examples: m.overflow, svgIntersections: m.svgIntersections, textIntersections: m.textIntersections, action: 'Possible issues; visually inspect. Original content and layout were not changed.' }));
    if (options.auditOnly) {
      result.screenshots = [];
      if (screenshots) {
        fs.mkdirSync(screenshots, { recursive: false });
        const slides = page.locator('main#deck > section.slide');
        for (let i = 0; i < result.slideCount; i++) {
          const file = path.join(screenshots, `slide-${String(i + 1).padStart(2, '0')}.png`);
          await slides.nth(i).screenshot({path: file, animations:'disabled'});
          result.screenshots.push(file);
        }
      }
      result.status = 'ok'; result.stage = 'audit_complete';
      result.authoredScriptsExecuted = false; result.browserDownloaded = false;
      return result;
    }
    result.stage = 'library_load';
    await page.addScriptTag({ content: bundleBytes.toString('utf8') });
    if (!await page.evaluate(() => typeof window.domToPptx?.exportToPptx === 'function')) fail('library_load_failed', '동봉 라이브러리 API가 초기화되지 않았습니다.');
    result.stage = 'convert';
    const encoded = await page.evaluate(async ({ timeout, dimensions }) => {
      const operation = async () => {
        const slides = Array.from(document.querySelectorAll('main#deck > section.slide'));
        const blob = await window.domToPptx.exportToPptx(slides, { skipDownload: true, autoEmbedFonts: false, svgAsVector: true, width: dimensions.width / 96, height: dimensions.height / 96 });
        if (!(blob instanceof Blob)) throw Error('exportToPptx did not return a Blob');
        const bytes = new Uint8Array(await blob.arrayBuffer());
        const chunks = []; for (let i = 0; i < bytes.length; i += 32768) chunks.push(String.fromCharCode(...bytes.subarray(i, i + 32768)));
        return btoa(chunks.join(''));
      };
      return Promise.race([operation(), new Promise((_, reject) => setTimeout(() => reject(Error('Conversion timeout')), timeout))]);
    }, { timeout: options.timeout, dimensions });
    if (result.blockedRequests.length || result.downloadsTriggered) fail('conversion_side_effect_blocked', '변환 중 외부 요청 또는 자동 다운로드가 감지되어 결과를 저장하지 않았습니다.', { blockedRequests: result.blockedRequests, downloadsTriggered: result.downloadsTriggered });
    let bytes = Buffer.from(encoded, 'base64');
    if (bytes.length < 100 || bytes.readUInt32LE(0) !== 0x04034b50) fail('invalid_pptx_result', '변환 결과가 PPTX ZIP 파일이 아닙니다.');
    result.stage = 'preserve_text_lines';
    const entries = readZip(bytes), slideEntries = entries.filter(entry => /^ppt\/slides\/slide\d+\.xml$/.test(entry.name));
    const corrected = await page.evaluate(({ slides, measured }) => {
      const a = 'http://schemas.openxmlformats.org/drawingml/2006/main', p = 'http://schemas.openxmlformats.org/presentationml/2006/main';
      const normalize = text => text.replace(/\s+/g, ' ').trim(), patches = [], changes = [], textSkipped = [], tableChanges = [], tableSkipped = [];
      for (const entry of slides) {
        const number = Number(entry.name.match(/slide(\d+)\.xml$/)[1]), measurements = measured[number - 1]?.candidates || [];
        const xml = new DOMParser().parseFromString(entry.xml, 'application/xml');
        if (xml.querySelector('parsererror')) throw Error('Generated slide XML could not be parsed');
        let changed = false;
        const sourceTables=measured[number-1]?.tables || [], usedTables=new Set();
        for (const frame of xml.getElementsByTagNameNS(p,'graphicFrame')) {
          const table=frame.getElementsByTagNameNS(a,'tbl')[0], transform=frame.getElementsByTagNameNS(p,'xfrm')[0];
          if (!table || !transform) continue;
          const off=transform.getElementsByTagNameNS(a,'off')[0]; if(!off) continue;
          const x=Number(off.getAttribute('x'))/9525,y=Number(off.getAttribute('y'))/9525;
          const ranked=sourceTables.map((t,i)=>({...t,index:i,distance:Math.hypot(t.x-x,t.y-y)})).filter(t=>!usedTables.has(t.index)).sort((a,b)=>a.distance-b.distance);
          const match=ranked[0];
          const rows=Array.from(table.children).filter(n=>n.localName==='tr');
          const grid=Array.from(table.getElementsByTagNameNS(a,'gridCol'));
          if (!match || match.distance>5 || rows.length!==match.rows.length || !rows.length ||
              match.rows.some((r,i)=>r.cells.length!==Array.from(rows[i].children).filter(n=>n.localName==='tc').length || r.cells.some(c=>c.colSpan!==1 || c.rowSpan!==1)) ||
              grid.length!==match.rows[0].cells.length || match.rows.some(r=>r.height<=0)) {
            if (match && match.distance<=5) usedTables.add(match.index);
            tableSkipped.push({slide:number,reason:'ambiguous table position, spans, rows or columns; no geometry changed'}); continue;
          }
          usedTables.add(match.index);
          for (let i=0;i<grid.length;i++) grid[i].setAttribute('w',String(Math.max(1,Math.round(match.rows[0].cells[i].width*9525))));
          for (let i=0;i<rows.length;i++) {
            rows[i].setAttribute('h',String(Math.max(1,Math.round(match.rows[i].height*9525))));
            const cells=Array.from(rows[i].children).filter(n=>n.localName==='tc');
            for(let j=0;j<cells.length;j++) {
              const props=Array.from(cells[j].children).find(n=>n.localName==='tcPr'); if(!props) continue;
              const padding=match.rows[i].cells[j];
              for(const [attribute,key] of [['marL','left'],['marR','right'],['marT','top'],['marB','bottom']])
                props.setAttribute(attribute,String(Math.max(0,Math.round(padding[key]*9525))));
            }
          }
          changed=true; tableChanges.push({slide:number,rows:rows.length,columns:grid.length,matchedDistancePx:Math.round(match.distance*100)/100});
        }
        sourceTables.forEach((_,index) => {
          if (!usedTables.has(index)) tableSkipped.push({slide:number,reason:'source HTML table was not matched to an editable PPTX table'});
        });
        for (const shape of xml.getElementsByTagNameNS(p, 'sp')) {
          if (shape.parentElement?.localName === 'grpSp') continue; // Group coordinates require a separate transform mapping.
          const body = Array.from(shape.children).find(n => n.localName === 'txBody'); if (!body) continue;
          if (body.getElementsByTagNameNS(a, 'br').length) continue;
          const paragraphs=Array.from(body.getElementsByTagNameNS(a,'p'));
          const text = normalize(Array.from(body.getElementsByTagNameNS(a, 't')).map(n => n.textContent).join('')); if (!text) continue;
          const properties = body.getElementsByTagNameNS(a, 'bodyPr')[0], transform = shape.getElementsByTagNameNS(a, 'xfrm')[0];
          if (!properties || !transform || transform.hasAttribute('rot') || (properties.hasAttribute('vert') && properties.getAttribute('vert') !== 'horz')) continue;
          const alreadyNoWrap=properties.getAttribute('wrap')==='none';
          const off = transform.getElementsByTagNameNS(a, 'off')[0]; if (!off) continue;
          const x = Number(off.getAttribute('x')) / 9525, y = Number(off.getAttribute('y')) / 9525;
          const matches = measurements.filter(m => m.text === text).map(m => ({ ...m, distance: Math.min(Math.hypot(m.x - x, m.y - y), Math.hypot(m.elementX - x, m.elementY - y)) })).sort((m, n) => m.distance - n.distance);
          const match = matches[0]; if (!match || match.distance > Math.max(4, match.fontSize * .8)) continue;
          let spacingChanged=false;
          if (paragraphs.length===1) {
            const para=paragraphs[0], spacing=para.getElementsByTagNameNS(a,'spcPts')[0];
            const sizes=Array.from(para.getElementsByTagNameNS(a,'rPr')).map(n=>Number(n.getAttribute('sz'))).filter(Number.isFinite);
            const largest=Math.max(0,...sizes), expected=Math.round((match.lineHeight||0)*75);
            if (spacing && largest && Number(spacing.getAttribute('val'))<largest && expected>=largest && expected<=30000) {
              spacing.setAttribute('val',String(expected)); spacingChanged=true; changed=true;
              changes.push({slide:number,shapeId:shape.getElementsByTagNameNS(p,'cNvPr')[0]?.getAttribute('id'),text:text.slice(0,160),change:'match browser line height for mixed text sizes',matchedDistancePx:Math.round(match.distance*100)/100});
            }
          }
          if(match.clipped || alreadyNoWrap) continue; // Never suppress wrapping of a visibly clipped source element.
          if (paragraphs.length !== 1) {
            if (match.explicitBreaks && paragraphs.length===match.explicitBreaks+1) {
              properties.setAttribute('wrap','none');changed=true;
              changes.push({slide:number,shapeId:shape.getElementsByTagNameNS(p,'cNvPr')[0]?.getAttribute('id'),text:text.slice(0,160),change:'preserve explicit browser breaks without rewrap',matchedDistancePx:Math.round(match.distance*100)/100});
            } else textSkipped.push({slide:number,text:text.slice(0,120),reason:'multiple PPT paragraphs could not be matched to source breaks'});
            continue;
          }
          // Split text runs only when their exact concatenation matches the DOM.
          // Clone each original run so bold/color and other formatting survive.
          if (match.lineBreakOffsets?.length) {
            const para=body.getElementsByTagNameNS(a,'p')[0];
            const runs=Array.from(para.children).filter(n=>n.localName==='r');
            const values=runs.map(run=>Array.from(run.getElementsByTagNameNS(a,'t')));
            if (!runs.length || values.some(v=>v.length!==1) || values.map(v=>v[0].textContent).join('')!==match.text || Array.from(para.children).some(n=>!['pPr','r','endParaRPr'].includes(n.localName))) {
              textSkipped.push({slide:number,text:match.text.slice(0,120),reason:'PPT text run structure is ambiguous; formatting left unchanged'}); continue;
            }
            const breaks=new Set(match.lineBreakOffsets); let offset=0;
            for (let n=0;n<runs.length;n++) {
              const run=runs[n], value=values[n][0].textContent, fragment=xml.createDocumentFragment();
              let segment=0;
              for (let i=0;i<value.length;i++) if(breaks.has(offset+i)) {
                if(i>segment) {
                  const part=run.cloneNode(true), t=part.getElementsByTagNameNS(a,'t')[0]; t.textContent=value.slice(segment,i);
                  t.setAttributeNS('http://www.w3.org/XML/1998/namespace','xml:space','preserve');fragment.appendChild(part);
                }
                fragment.appendChild(xml.createElementNS(a,'a:br'));segment=i;
              }
              if(segment<value.length) {
                const part=run.cloneNode(true), t=part.getElementsByTagNameNS(a,'t')[0]; t.textContent=value.slice(segment);
                t.setAttributeNS('http://www.w3.org/XML/1998/namespace','xml:space','preserve');fragment.appendChild(part);
              }
              para.insertBefore(fragment,run);para.removeChild(run);offset+=value.length;
            }
          }
          properties.setAttribute('wrap', 'none'); changed = true;
          changes.push({ slide: number, shapeId: shape.getElementsByTagNameNS(p, 'cNvPr')[0]?.getAttribute('id'), text: text.slice(0, 160), change: match.lineBreakOffsets?.length ? 'preserve browser line breaks and disable rewrap' : 'wrap=square to wrap=none', matchedDistancePx: Math.round(match.distance * 100) / 100 });
        }
        if (changed) patches.push({ name: entry.name, xml: new XMLSerializer().serializeToString(xml) });
      }
      return { patches, changes, textSkipped, tableChanges, tableSkipped };
    }, { slides: slideEntries.map(entry => ({ name: entry.name, xml: zipText(entry) })), measured });
    const textSkipped = corrected.textSkipped.concat(measured.flatMap(m=>m.unhandledMultiline.map(text=>({slide:m.slide,text,reason:'complex source text cannot be safely matched; formatting left unchanged'}))));
    result.textLinePreservation = { method: 'OOXML nowrap for measured single lines; exact matching plain and inline-styled multiline text keeps measured browser breaks and original text-run formatting. Complex structures, shape bounds and font sizes are unchanged.', changed: corrected.changes.length, changes: corrected.changes, skipped:textSkipped.slice(0,50), skippedCount:textSkipped.length };
    if (textSkipped.length) {
      result.limitations.push('일부 여러 줄 복합 서식은 줄바꿈을 자동 보정하지 않았습니다. 해당 장의 실제 PPT 화면을 확인하세요.');
      for (const skipped of textSkipped.slice(0,20)) result.layoutWarnings.push({slide:skipped.slide,code:'multiline_text_unverified',text:skipped.text,action:'원문과 서식을 유지했습니다. 실제 PPT 화면을 확인하세요.'});
    }
    result.tableGeometry = {method:'Native table row/column dimensions and cell padding are matched to browser pixels for unmerged tables only.', changed:corrected.tableChanges, skipped:corrected.tableSkipped};
    if (corrected.tableSkipped.length) {
      result.limitations.push('일부 표는 병합 셀 또는 불명확한 위치로 브라우저 표 크기를 자동 반영하지 못했습니다. 해당 장의 실제 PPT 화면을 확인하세요.');
      for (const skipped of corrected.tableSkipped) result.layoutWarnings.push({slide:skipped.slide,code:'table_geometry_unverified',action:'실제 PPT 화면에서 표와 글자 잘림을 확인하세요.',reason:skipped.reason});
    }
    if (corrected.patches.length) bytes = writeZip(entries, new Map(corrected.patches.map(patch => [patch.name, patch.xml])));
    result.stage = 'write';
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, bytes, { flag: 'wx' });
    result.bytes = bytes.length; result.outputSha256 = sha256(bytes); result.status = 'ok'; result.stage = 'complete';
    result.fontsEmbedded = false; result.authoredScriptsExecuted = false; result.browserDownloaded = false;
  } catch (error) {
    result.code = error.code || ({ browser_launch: 'browser_launch_failed', sanitize: 'sanitize_failed', static_render: 'static_render_failed', library_load: 'library_load_failed', convert: 'conversion_failed', preserve_text_lines: 'text_line_preservation_failed', write: 'output_write_failed' }[result.stage] || 'export_failed');
    result.message = error.message; if (error.detail !== undefined) result.detail = error.detail;
  } finally {
    if (browser) await browser.close().catch(() => {});
    result.sourceSha256After = sha256(fs.readFileSync(input));
    result.sourcePreserved = result.sourceSha256Before === result.sourceSha256After;
    if (!result.sourcePreserved) { result.status = 'failed'; result.code = 'source_changed_during_export'; result.message = '검사 중 원본 HTML이 다른 내용으로 변경되었습니다.'; }
  }
  return result;
}

async function main() {
  try {
    const options = argumentsFor(process.argv.slice(2));
    if (options.help) {
      console.log(JSON.stringify({ usage: 'node export_pptx.cjs --input saved.html [--output 발표본.pptx | --audit-only --screenshots 새폴더] [--browser /path/to/chrome] [--node-modules /existing/node_modules] [--timeout 120000]', requirements: ['Node.js 18+', 'Existing playwright or playwright-core', 'Existing Chrome, Edge or Chromium'], installs: false, sourceScripts: 'removed', assets: 'embedded data URLs only; relative and network resources rejected', overwrite: false }, null, 2));
      return;
    }
    const result = await run(options); console.log(JSON.stringify(result, null, 2));
    if (result.status !== 'ok') process.exitCode = 1;
  } catch (error) { console.log(JSON.stringify({ status: 'failed', stage: 'preflight', code: error.code || 'preflight_failed', message: error.message, ...(error.detail !== undefined ? { detail: error.detail } : {}) }, null, 2)); process.exitCode = 1; }
}
if (require.main === module) main();
module.exports = { argumentsFor, resolvePlaywright, resolveBrowser, run };
