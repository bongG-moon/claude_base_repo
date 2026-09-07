// Build a standalone offline reader from the maintained Korean guide.
// Usage: node scripts/build-user-guide.mjs --modules <approved node_modules>
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const moduleIndex = process.argv.indexOf('--modules');
if (moduleIndex < 0 || !process.argv[moduleIndex + 1]) {
  throw new Error('Provide --modules with the approved node_modules directory. No packages are downloaded.');
}
const moduleRoot = path.resolve(process.argv[moduleIndex + 1]);
const runtimeRequire = createRequire(path.join(moduleRoot, '_guide_builder.cjs'));
const { marked } = await import(pathToFileURL(runtimeRequire.resolve('marked')).href);
const source = fs.readFileSync(path.join(root, 'docs', 'USER_GUIDE.md'), 'utf8');
const version = source.match(/대상 버전 (\d+\.\d+\.\d+)/)?.[1];
if (!version) throw new Error('Guide must declare its matching feature version.');
const escape = value => String(value).replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[char]);
const headings = [...source.matchAll(/^## (.+)$/gm)].map((match, index) => ({
  id: `chapter-${index + 1}`, title: match[1],
}));
let headingIndex = 0;
let body = marked.parse(source, { gfm: true, breaks: false });
body = body.replace(/<h2>(.*?)<\/h2>/g, (_match, title) => {
  const heading = headings[headingIndex++];
  return `<h2 id="${heading.id}" tabindex="-1">${title}</h2>`;
});
body = body.replace(/<table>/g, '<div class="table-scroll" role="region" aria-label="비교표" tabindex="0"><table>')
  .replace(/<\/table>/g, '</table></div>');
// Keep this file useful when mailed alone: repository references are labels,
// not dead file:// links to Markdown files that may not accompany the reader.
body = body.replace(/<a href="([A-Z_]+\.md)">([^<]+)<\/a>/g,
  (_match, file, label) => `${label} <span class="source-label">소스 저장소 docs/${escape(file)}</span>`);
const toc = headings.map(item => `<li><a href="#${item.id}">${escape(item.title)}</a></li>`).join('\n');
const promptCount = [...source.matchAll(/^```text$/gm)].length;
const html = `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="코딩에 익숙하지 않은 직원을 위한 Company Agent ${version} 사용 안내서. 업무 예문과 개인 기억, 회사 지식, 자동 학습과 반복업무 활용 방법.">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; font-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>Company Agent 사용자 안내서</title>
<style>
:root{color-scheme:light;--ink:#172630;--muted:#516370;--blue:#245d79;--line:#d8e1e6;--paper:#fff;--wash:#f2f5f7}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:34px}body{margin:0;background:var(--wash);color:var(--ink);font:17px/1.88 'Malgun Gothic','맑은 고딕',Arial,sans-serif;word-break:keep-all;overflow-wrap:anywhere}
a{color:var(--blue);text-underline-offset:4px}button,input{font:inherit}button{cursor:pointer}button:focus-visible,a:focus-visible,input:focus-visible,[tabindex]:focus-visible{outline:3px solid #3186ad;outline-offset:4px}
.skip{position:fixed;top:-90px;left:20px;background:white;padding:8px;z-index:8}.skip:focus{top:10px}
.layout{max-width:1430px;margin:auto;display:grid;grid-template-columns:288px minmax(0,1fr);gap:36px;padding:28px 28px 64px}
aside{position:sticky;top:24px;align-self:start;max-height:calc(100vh - 48px);overflow:auto;padding:6px 9px 12px 2px}
.brand{font-weight:750;letter-spacing:-.5px;font-size:21px;color:#000}.edition{color:var(--muted);font-size:13px;margin:2px 0 22px}.nav-title{font-size:14px;font-weight:700;margin:0 0 6px;color:#000}
#toc-filter{width:100%;border:1px solid #bccad2;background:#fff;border-radius:6px;padding:7px 10px;font-size:14px;margin:3px 0 12px}
nav ol{list-style:none;margin:0;padding:0}nav li{margin:0}nav a{display:block;padding:7px 8px;text-decoration:none;color:#364e5d;font-size:14px;line-height:1.5;border-radius:5px}nav a:hover,nav a[aria-current=true]{background:#e3ecf1;color:#153d53}nav a[aria-current=true]{font-weight:700}
.nav-footer{font-size:12px;color:var(--muted);margin-top:20px}.tools{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 18px;align-items:center}.tools button,.tools a{font-size:13px;line-height:1.5;border:1px solid #b9cbd5;border-radius:5px;background:#fff;color:#284e63;padding:7px 10px;text-decoration:none}.tools span{margin-left:auto;font-size:12px;color:var(--muted)}
main{min-width:0}article{background:var(--paper);padding:50px 58px 64px;border:1px solid #e0e6e9;border-radius:10px;box-shadow:0 5px 26px #21394d06}
h1,h2,h3{color:#000;line-height:1.5;letter-spacing:-.55px;word-break:keep-all}h1{font-size:34px;margin:0 0 10px;font-weight:800}h1+p{font-size:20px;margin:0 0 12px;color:#344d5c}h1+p+p{font-size:13px;color:var(--muted);margin:0 0 30px}h2{font-size:26px;margin:64px 0 21px;padding-top:7px}h3{font-size:20px;margin:32px 0 12px}p{margin:0 0 18px}strong{font-weight:750}ul,ol{padding-left:1.5em;margin:12px 0 24px}li{margin-bottom:9px}li>p{margin:0 0 7px}
.table-scroll{overflow-x:auto;margin:20px 0 26px}table{border-collapse:collapse;width:100%;font-size:15px;line-height:1.7;min-width:540px}th,td{border:1px solid #d9d9d9;text-align:left;padding:13px 15px;vertical-align:middle}th{background:#deebf2;color:#000;font-weight:700}th:first-child,td:first-child{width:24%}td:nth-child(2){width:35%}tbody tr:nth-child(even){background:#f8fafb}
code{font-family:'Malgun Gothic','맑은 고딕',Consolas,monospace;font-size:.92em}p code,li code,td code{background:#f0f3f5;border-radius:3px;padding:1px 4px}
.example{margin:22px 0 27px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:12px 0 14px}.example-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:9px}.example-label{font-size:12px;font-weight:700;color:#496575;letter-spacing:.15px}.copy{border:1px solid #beced7;border-radius:5px;background:#fff;color:#315267;font-size:12px;line-height:1.4;padding:6px 10px;white-space:nowrap}.copy:hover{background:#edf4f7}.example pre{white-space:pre-wrap;overflow-wrap:anywhere;word-break:normal;margin:0;font-size:15px;line-height:1.9;color:#223b4b}.example pre code{font:inherit}pre{white-space:pre-wrap;overflow-wrap:anywhere}blockquote{margin:20px 0;padding-left:20px;color:var(--muted)}.source-label{display:block;font-size:12px;color:var(--muted)}
.endnote{font-size:12px;color:var(--muted);margin:22px 3px 0}#copy-status{min-height:22px;font-size:13px;color:#315267;margin-bottom:7px}#no-results{font-size:13px;color:var(--muted)}
@media(max-width:1100px){.layout{grid-template-columns:230px minmax(0,1fr);gap:20px;padding:20px}article{padding:36px}h1{font-size:29px}h2{font-size:24px}}
@media(max-width:760px){.layout{display:block;padding:16px 12px 40px}aside{position:static;max-height:none;padding:0;margin:0 0 20px}.brand{font-size:19px}.edition{margin-bottom:12px}nav ol{columns:2;column-gap:10px}nav a{font-size:13px;break-inside:avoid}nav li{break-inside:avoid}.nav-footer{display:none}article{padding:28px 23px}h1{font-size:27px}h2{font-size:23px;margin-top:48px}h3{font-size:19px}body{font-size:16px}.tools span{width:100%;margin:0}.example pre{font-size:14px}table{font-size:14px}}
@media print{html{scroll-behavior:auto}body{background:white;font-size:10.5pt;line-height:1.65;word-break:keep-all}.layout{display:block;padding:0;max-width:none}aside,.tools,#copy-status,.copy,.skip,.endnote{display:none}article{padding:0;border:0;box-shadow:none}h1{font-size:23pt}h2{font-size:16pt;margin:25pt 0 12pt;break-after:avoid}h3{font-size:12pt;margin:16pt 0 8pt;break-after:avoid}p{margin-bottom:9pt;orphans:3;widows:3}table{font-size:9pt;min-width:0;line-height:1.5}th,td{padding:7pt}thead{display:table-header-group}tr{break-inside:avoid}.table-scroll{overflow:visible}.example{break-inside:avoid;margin:12pt 0;padding:8pt 0}.example pre{font-size:10pt;line-height:1.6}.example-label{font-size:8pt}li{margin-bottom:5pt}a{color:inherit;text-decoration:none}@page{size:A4;margin:19mm 18mm}}
</style>
</head>
<body id="top">
<a class="skip" href="#guide">본문으로 이동</a>
<div class="layout">
<aside aria-label="안내서 목차">
<div class="brand">Company Agent</div><div class="edition">직원용 사용 안내서 · ${version}</div>
<label class="nav-title" for="toc-filter">필요한 내용 찾기</label>
<input id="toc-filter" type="search" placeholder="예: 기억, 메일, 프로젝트" autocomplete="off">
<nav aria-label="목차"><ol>${toc}</ol><p id="no-results" hidden>찾는 장이 없으면 Ctrl+F로 본문을 검색하세요.</p></nav>
<p class="nav-footer">이 파일은 인터넷 연결 없이 읽을 수 있습니다.<br>문서를 여는 것만으로 설치나 설정 변경은 일어나지 않습니다.</p>
</aside>
<main>
<div class="tools"><button id="print" type="button">인쇄 또는 PDF로 저장</button><a href="#chapter-1">처음 시작하기</a><a href="#chapter-19">짧은 요청 모음</a><span>본문 검색 Ctrl+F · 예문 복사 가능</span></div>
<div id="copy-status" role="status" aria-live="polite"></div>
<article id="guide" aria-label="Company Agent 상세 사용자 안내">${body}</article>
<p class="endnote">${version} 사용 안내 · 개인 자료나 회사 자료를 외부로 전송하지 않는 독립 문서입니다. <a href="#top">맨 위로</a></p>
</main>
</div>
<script>
(() => {
  const status = document.getElementById('copy-status');
  let timer;
  document.querySelectorAll('article pre').forEach((pre, index) => {
    const original = pre.textContent;
    const isPath = /^C:\\\\/.test(original.trim()) && original.trim().split('\\n').length === 1;
    const wrapper = document.createElement('div'); wrapper.className = 'example';
    const head = document.createElement('div'); head.className = 'example-head';
    const label = document.createElement('span'); label.className = 'example-label';
    label.textContent = isPath ? '저장 위치 예시' : 'Claude Code에 입력하는 예문';
    const button = document.createElement('button'); button.className = 'copy'; button.type = 'button';
    button.textContent = isPath ? '경로 복사' : '예문 복사';
    button.setAttribute('aria-label', (isPath ? '경로 예시 ' : '요청 예문 ') + (index + 1) + ' 복사');
    button.addEventListener('click', async () => {
      let copied = false;
      try { await navigator.clipboard.writeText(original.trim()); copied = true; } catch (_) {
        const field = document.createElement('textarea'); field.value = original.trim();
        field.style.cssText = 'position:fixed;left:-9999px;top:0'; document.body.appendChild(field);
        field.select(); try { copied = document.execCommand('copy'); } catch (_) {} field.remove(); button.focus();
      }
      button.textContent = copied ? '복사 완료' : '직접 선택해 복사';
      status.textContent = copied ? '복사했습니다. Claude Code 대화 입력창에 붙여 넣어 주세요.' : '복사가 제한된 환경입니다. 예문을 직접 선택하고 Ctrl+C를 눌러 주세요.';
      clearTimeout(timer); timer = setTimeout(() => { status.textContent = ''; }, 6000);
      setTimeout(() => { button.textContent = isPath ? '경로 복사' : '예문 복사'; }, 2500);
    });
    head.append(label, button); pre.before(wrapper); wrapper.append(head, pre);
  });
  document.getElementById('print').addEventListener('click', () => window.print());
  document.getElementById('toc-filter').addEventListener('input', event => {
    const value = event.target.value.trim().toLowerCase(); let count = 0;
    document.querySelectorAll('nav li').forEach(li => { li.hidden = !li.textContent.toLowerCase().includes(value); if (!li.hidden) count++; });
    document.getElementById('no-results').hidden = count > 0;
  });
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) {
        document.querySelectorAll('nav a').forEach(link => link.setAttribute('aria-current', String(link.hash === '#' + entry.target.id)));
      }
    }, { rootMargin: '0px 0px -70% 0px' });
    document.querySelectorAll('h2[id]').forEach(heading => observer.observe(heading));
  }
})();
</script>
</body>
</html>
`;
if (headingIndex !== headings.length || /<(?:img|script)[^>]+src=["']https?:/i.test(html)) {
  throw new Error('Guide integrity check failed.');
}
const output = path.join(root, 'docs', 'Company-Agent-사용자-안내서.html');
fs.writeFileSync(output, html, 'utf8');
console.log(JSON.stringify({ output, chapters: headings.length, codeBlocks: promptCount, bytes: Buffer.byteLength(html) }));
