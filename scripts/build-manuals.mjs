// One standalone, script-free reader; authored Markdown remains modular.
// node scripts/build-manuals.mjs --modules <approved node_modules> [--check]
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const i=process.argv.indexOf('--modules');
if(i<0||!process.argv[i+1])throw Error('Provide approved --modules; no dependencies are downloaded.');
const req=createRequire(path.join(path.resolve(process.argv[i+1]),'_manual_builder.cjs'));
const {marked}=await import(pathToFileURL(req.resolve('marked')).href);
const output='Company-Agent-Guide.html';
const books=[
  {id:'onboarding',label:'01 · 준비물 없이 따라 하기',source:'ONBOARDING_COURSE.md',legacy:'Company-Agent-Onboarding.html'},
  {id:'usage',label:'02 · 업무별 사용법',source:'USER_GUIDE.md',legacy:'Company-Agent-사용자-안내서.html'},
  {id:'handbook',label:'03 · 기억·스킬·하네스 이해',source:'COMPANY_AGENT_HANDBOOK.md',legacy:'Company-Agent-Handbook.html'},
  {id:'commands',label:'04 · Claude Code 명령어',source:'CLAUDE_CODE_COMMANDS.md',legacy:'Claude-Code-필수-사용법.html'},
  {id:'cua',label:'05 · 선택: 화면 조작 시험',source:'CUA_DRIVER_PILOT.md',legacy:'Company-Agent-Cua-Pilot.html'},
];
const esc=x=>x.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const csp="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; script-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'";
const style=`
:root{color-scheme:light;--ink:#203a38;--muted:#536965;--line:#dce5df;--accent:#246858}
*{box-sizing:border-box}body{margin:0;background:#f3f5f1;color:var(--ink);font:16px/1.85 'Malgun Gothic','맑은 고딕',sans-serif;word-break:keep-all;overflow-wrap:anywhere}
a{color:var(--accent);text-underline-offset:4px}a:focus-visible,[tabindex]:focus-visible,summary:focus-visible{outline:3px solid #4583a4;outline-offset:3px}.skip{position:absolute;left:16px;top:-80px}.skip:focus{top:10px;background:white;padding:12px;z-index:2}
.layout{max-width:1450px;margin:auto;padding:32px;display:grid;grid-template-columns:260px minmax(0,1fr);gap:32px}aside{position:sticky;top:24px;align-self:start;max-height:calc(100vh - 48px);overflow:auto}aside strong{font-size:23px}aside p{font-size:13px;color:var(--muted)}nav a{display:block;padding:5px 0;font-size:13px;text-decoration:none}nav a:hover{text-decoration:underline}nav details{border-bottom:1px solid var(--line);padding:10px 0}nav summary{cursor:pointer;font-weight:bold;font-size:14px}nav details a{padding-left:10px}
main{min-width:0}header,.book{background:white;border:1px solid var(--line);border-radius:16px;padding:36px 40px;margin-bottom:24px}.eyebrow{font-size:12px;letter-spacing:.1em;color:var(--accent);font-weight:bold}h1{font-size:34px;line-height:1.4;margin:12px 0}h2{font-size:27px;line-height:1.5;margin:0 0 18px}h3{font-size:22px;line-height:1.5;border-top:1px solid var(--line);padding-top:26px;margin-top:40px}h4{font-size:18px}h2,h3,h4{scroll-margin-top:24px}p{margin:14px 0}li{margin:8px 0}pre{background:#f1f6f2;border-left:3px solid #88b2a2;border-radius:4px;padding:18px 20px;white-space:pre-wrap;overflow-wrap:anywhere;tab-size:2}code{font-family:Consolas,'Malgun Gothic',monospace;font-size:.92em}pre code{display:block;user-select:all}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:580px;font-size:14px;line-height:1.7}td,th{border:1px solid var(--line);text-align:left;padding:12px;vertical-align:top}th{background:#eaf1eb}small,footer{color:var(--muted);font-size:12px}footer{padding:0 20px 28px}.back{font-size:13px}.paths{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:22px 0}.paths a{padding:16px;border:1px solid var(--line);border-radius:10px;text-decoration:none;background:#f7faf6;font-size:14px}.paths b{display:block;margin-bottom:5px}.notice{border-left:3px solid #b1a77f;padding-left:14px;color:var(--muted);font-size:14px}
@media(max-width:800px){.layout{display:block;padding:14px}aside{position:static;max-height:none;margin:0 0 24px}header,.book{padding:24px 20px}h1{font-size:27px}h2{font-size:24px}h3{font-size:21px}.paths{grid-template-columns:1fr}}
@media print{body{background:white;font-size:10pt}.layout{display:block;padding:0}aside,.skip,.back,.paths{display:none}header,.book{border:0;padding:0}h1{font-size:22pt}h2{font-size:18pt;break-before:page}h3{font-size:14pt;break-after:avoid}h4{break-after:avoid}table{min-width:0;font-size:9pt}thead{display:table-header-group}tr,pre{break-inside:avoid}.table-wrap{overflow:visible}a{color:inherit}@page{size:A4;margin:18mm}}
`;
const head=(title,metadata='')=>`<!doctype html>\n<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${metadata}<meta http-equiv="Content-Security-Policy" content="${csp}"><title>${esc(title)}</title><style>${style}</style></head>`;
function emit(name,html){
  for(const folder of ['docs','company-agent-plugin/resources/manuals']){
    const dest=path.join(root,folder,name);
    if(process.argv.includes('--check')){
      if(!fs.existsSync(dest)||fs.readFileSync(dest,'utf8')!==html)throw Error('Manual needs rebuilding: '+folder+'/'+name);
    }else{fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest,html,'utf8');}
  }
}
for(const book of books){
  const text=fs.readFileSync(path.join(root,'docs',book.source),'utf8').replace(/\r\n/g,'\n');
  book.title=text.match(/^# (.+)$/m)[1];
  book.headings=[...text.matchAll(/^## (.+)$/gm)].map(x=>x[1]);
  book.sha=createHash('sha256').update(text).digest('hex');
  let n=0,body=marked.parse(text,{gfm:true});
  body=body.replace(/<h([1-5])>(.*?)<\/h\1>/g,(_,level,t)=>{
    if(level==='1')return `<h2 id="${book.id}">${t}</h2>`;
    const id=level==='2'?` id="${book.id}-section-${++n}"`:'';
    return `<h${Number(level)+1}${id}>${t}</h${Number(level)+1}>`;
  }).replace(/<table>/g,'<div class="table-wrap" tabindex="0" role="region" aria-label="안내 표"><table>').replace(/<\/table>/g,'</table></div>')
    .replace(/<a href="([^"/:#]+\.(?:md|html))">([\s\S]*?)<\/a>/g,(_,file,t)=>{
      const dest=books.find(b=>b.source===file||b.legacy===file);
      if(dest)return `<a href="#${dest.id}">${t}</a>`;
      return `${t} <small>(담당자용 소스 문서 ${esc(file)})</small>`;
    });
  if(n!==book.headings.length||/<(?:script|iframe|object|img)\b|\son\w+=/i.test(body))throw Error('Unexpected active content in '+book.source);
  book.body=body;
}
const toc=books.map(b=>`<details${b.id==='onboarding'?' open':''}><summary>${esc(b.label)}</summary><a href="#${b.id}">이 안내부터 보기</a>${b.headings.map((h,i)=>`<a href="#${b.id}-section-${i+1}">${esc(h)}</a>`).join('')}</details>`).join('');
const metadata=books.map(b=>`<meta name="source-sha256" data-file="${b.source}" content="${b.sha}">`).join('');
const html=head('Company Agent 통합 가이드',metadata)+`<body><a class="skip" href="#content">본문으로 이동</a><div class="layout"><aside><strong>Company Agent</strong><p>온보딩부터 업무 활용까지<br>하나로 보는 사용 가이드</p><p>찾기: Ctrl+F · 인쇄/PDF: Ctrl+P<br>예문 상자를 선택한 뒤 Ctrl+C로 복사<br>문서 열기는 AI 호출이나 작업 실행이 아닙니다.</p><nav aria-label="목차">${toc}</nav></aside><main id="content"><header id="start"><span class="eyebrow">LOCAL · OFFLINE · KOREAN</span><h1>Company Agent 통합 가이드</h1><p>파일이 없어도, 명령어를 몰라도.<br>작은 가상 업무 하나부터 시작해 보세요.</p><div class="paths"><a href="#onboarding-section-2"><b>처음이라면</b>가상 자료 만들기 → 실제 읽기</a><a href="#usage"><b>바로 일하려면</b>보고서·회의·비교 요청 예문</a><a href="#commands"><b>명령어가 궁금하면</b>입력·중단·압축·다시 시작</a></div><p class="notice">회사 공통 / 개인 전체 / 이 프로젝트를 구분합니다. 새 기억·스킬 저장은 개인 전체 또는 이 프로젝트를 선택합니다. 모든 실습은 선택이며 회사 자료·참고 PPT가 없어도 시작할 수 있습니다.</p><p>온보딩, 업무별 사용법, 스킬·후크 핸드북, Claude Code 명령어, 선택적 Cua 시험 안내가 모두 이 HTML 안에 있습니다. 다른 문서를 내려받지 않아도 읽을 수 있습니다. 외부 참고 링크는 직접 선택했을 때만 열립니다.</p></header>${books.map(b=>`<section class="book" aria-labelledby="${b.id}">${b.body}<p class="back"><a href="#start">처음 안내로 돌아가기 ↑</a></p></section>`).join('')}<footer>수정용 원본: ${books.map(b=>b.source).join(' · ')}<br>자동 생성된 오프라인 통합본입니다. 외부 요청·스크립트 실행·자동 저장·모델 호출이 없으며 후크에 전체 내용을 주입하지 않습니다.</footer></main></div></body></html>\n`;
emit(output,html);
// Small navigation-only compatibility pages. Old bookmarks stay useful; no
// automatic redirects, scripts, duplicated instructions or additional manuals.
for(const b of books){
  const legacy=head(b.title+' — 통합 가이드로 이동')+`<body><main class="book"><h1>안내서를 하나로 합쳤습니다</h1><p>온보딩·사용법·명령어를 아래 통합 가이드 한 파일에서 읽으세요.</p><p><a href="${output}#${b.id}">${esc(b.title)} 열기</a></p><nav aria-label="이전 목차">${b.headings.map((h,i)=>`<a id="section-${i+1}" href="${output}#${b.id}-section-${i+1}">${esc(h)}</a>`).join('')}</nav></main></body></html>\n`;
  emit(b.legacy,legacy);
}
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
if(new Set(ids).size!==ids.length)throw Error('Duplicate guide anchors');
for(const [,id]of html.matchAll(/href="#([^"]+)"/g))if(!ids.includes(id))throw Error('Missing guide anchor '+id);
console.log(`${output}: ${books.length} parts, ${books.reduce((n,b)=>n+b.headings.length,0)} chapters, ${Buffer.byteLength(html)} bytes; 5 compatibility links`);
