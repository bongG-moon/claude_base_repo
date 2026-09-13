// Build a standalone offline reader. No runtime downloads or user-data storage.
// node scripts/build-validation-chat-set.mjs --modules <approved node_modules>
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const index = process.argv.indexOf('--modules');
if (index < 0 || !process.argv[index + 1]) throw new Error('Supply approved --modules; no download is performed.');
const runtimeRequire = createRequire(path.join(path.resolve(process.argv[index + 1]), '_validation_builder.cjs'));
const { marked } = await import(pathToFileURL(runtimeRequire.resolve('marked')).href);
const source = fs.readFileSync(path.join(root, 'docs/VALIDATION_CHAT_SET.md'), 'utf8');
const escape = text => String(text).replace(/[&<>"']/g, value => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[value]));
const cases = [...source.matchAll(/^## (T\d{2}) (.+)$/gm)];
if (cases.length !== 34 || cases.some((match, i) => match[1] !== `T${String(i + 1).padStart(2, '0')}`)) throw new Error('Expected unique T01 through T34.');
let body = marked.parse(source, {gfm:true});
let heading = 0;
const toc = [];
body = body.replace(/<h2>(.*?)<\/h2>/g, (_, title) => {
  const id = `section-${++heading}`;
  toc.push(`<a href="#${id}">${title}</a>`);
  return `<h2 id="${id}" tabindex="-1">${title}</h2>`;
});
body = body.replace(/<table>/g, '<div class="table-scroll"><table>').replace(/<\/table>/g, '</table></div>');
const version = source.match(/대상 버전 ([\d.]+)/)?.[1];
if (!version) throw new Error('Missing declared version.');
const html = `<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>Company Agent ${escape(version)} · 운영 검증 채팅 ${cases.length}선</title>
<style>
:root{color-scheme:light;--ink:#172d43;--accent:#156270;--line:#d4e1e5}*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}body{margin:0;background:#f3f7f8;color:var(--ink);font:16px/1.8 'Malgun Gothic',system-ui,sans-serif}a{color:var(--accent)}.layout{display:grid;grid-template-columns:275px minmax(0,900px);gap:36px;max-width:1280px;margin:auto;padding:32px 24px}aside{position:sticky;top:24px;max-height:94vh;overflow:auto;align-self:start}aside a{display:block;padding:6px 10px;font-size:13px;text-decoration:none;border-radius:6px}aside a:hover,aside a:focus-visible{background:#dceef0}aside strong{font-size:20px}main{min-width:0;background:white;padding:36px 44px;border:1px solid var(--line);border-radius:16px}h1{font-size:32px;line-height:1.4;margin-top:0}h2{margin-top:56px;padding-top:20px;border-top:2px solid var(--line);font-size:24px}h3{font-size:19px}h1,h2,h3,p,li{overflow-wrap:anywhere}p,li{max-width:80ch}li{margin:8px 0}pre{position:relative;background:#edf5f6;border-left:4px solid var(--accent);border-radius:8px;padding:58px 20px 20px;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8;font-size:15px}pre code{font-family:inherit;padding:0;background:none}code{background:#edf2f6;padding:2px 5px;border-radius:4px}button{font:inherit;font-size:13px;cursor:pointer;color:white;background:var(--accent);border:0;border-radius:6px;padding:7px 12px}pre button{position:absolute;right:12px;top:10px}button:focus-visible,a:focus-visible{outline:3px solid #d77829;outline-offset:3px}.table-scroll{overflow:auto}table{border-collapse:collapse;min-width:430px;width:100%;font-size:14px}th,td{padding:10px;text-align:left;border-bottom:1px solid var(--line)}th{background:#edf5f6}.notice{background:#e6f2ef;border:1px solid #b8d6d0;padding:14px 18px;border-radius:8px;font-size:14px}#copy-status{font-size:13px;min-height:24px}details summary{cursor:pointer;font-weight:700}footer{font-size:13px;margin-top:40px;color:#506778}
@media(max-width:850px){.layout{display:block;padding:16px}aside{position:static;max-height:none;margin-bottom:20px}aside nav{max-height:220px;overflow:auto}main{padding:22px 18px}h1{font-size:26px}h2{font-size:21px}pre{padding-left:14px;padding-right:14px}}@media print{aside,button,.notice,#copy-status{display:none}.layout{display:block;padding:0}main{padding:0;border:0}body{background:white;font-size:11pt}pre{padding:12px;break-inside:avoid}h2{break-after:avoid}a{color:inherit}}
</style></head><body><div class="layout"><aside><strong>운영 검증 ${cases.length}선</strong><p>${escape(version)} · 아직 미실행</p><details open><summary>시험 목록</summary><nav>${toc.join('')}</nav></details><p id="copy-status" role="status" aria-live="polite"></p></aside><main><div class="notice">회색 상자의 요청만 하나씩 복사하세요. 정상 기준과 전체 문서는 Claude에 먼저 주지 마세요. 결과는 별도 결과지나 이 대화에 기록합니다. 이 페이지는 입력 내용을 저장하거나 외부로 전송하지 않습니다.</div>${body}<footer>Markdown 원본: docs/VALIDATION_CHAT_SET.md · 결과지: docs/VALIDATION_RESULTS_TEMPLATE.md<br>문서 제공은 실제 운영 검증 완료를 의미하지 않습니다.</footer></main></div>
<script>
document.querySelectorAll('pre').forEach((pre, index) => {
  const code = pre.querySelector('code');
  if (!code) return;
  const button = document.createElement('button');
  button.type = 'button'; button.textContent = '요청 복사'; button.setAttribute('aria-label', (index + 1) + '번째 상자 복사');
  button.addEventListener('click', async () => {
    let copied = false;
    try { await navigator.clipboard.writeText(code.textContent); copied = true; } catch (_) {
      const selection = window.getSelection(); const range = document.createRange(); range.selectNodeContents(code);
      selection.removeAllRanges(); selection.addRange(range);
      try { copied = document.execCommand('copy'); } catch (_) {}
      if (copied) selection.removeAllRanges();
    }
    document.getElementById('copy-status').textContent = copied ? '복사했습니다. 해당 요청 한 개만 Claude에 붙여 넣으세요.' : '자동 복사가 제한됩니다. 상자 내용을 직접 선택해 복사하세요.';
    button.textContent = copied ? '복사됨' : '직접 복사';
  }); pre.append(button);
});
</script></body></html>`;
const output = path.join(root, 'docs/Company-Agent-운영-검증-채팅.html');
fs.writeFileSync(output, html, 'utf8');
console.log(JSON.stringify({output, cases:cases.length, prompts:[...source.matchAll(/^\x60\x60\x60text$/gm)].length, bytes:Buffer.byteLength(html)}));
