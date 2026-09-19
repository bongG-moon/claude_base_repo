// Offline, script-free manuals using an already approved marked dependency.
// node scripts/build-manuals.mjs --modules <node_modules> [--check]
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
const files={
  'COMPANY_AGENT_HANDBOOK.md':'Company-Agent-Handbook.html',
  'ONBOARDING_COURSE.md':'Company-Agent-Onboarding.html',
  'CUA_DRIVER_PILOT.md':'Company-Agent-Cua-Pilot.html',
};
const esc=x=>x.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
for(const[source,output]of Object.entries(files)){
  const text=fs.readFileSync(path.join(root,'docs',source),'utf8').replace(/\r\n/g,'\n');
  const title=text.match(/^# (.+)$/m)[1], headings=[...text.matchAll(/^## (.+)$/gm)].map(x=>x[1]);
  let n=0,body=marked.parse(text,{gfm:true});
  body=body.replace(/<h2>(.*?)<\/h2>/g,(_,t)=>`<h2 id="section-${++n}">${t}</h2>`)
    .replace(/<table>/g,'<div class="table-wrap" tabindex="0" role="region" aria-label="안내 표"><table>')
    .replace(/<\/table>/g,'</table></div>')
    .replace(/<a href="([^"/:]+\.md)">([^<]+)<\/a>/g,(_,f,t)=>files[f]?`<a href="${files[f]}">${t}</a>`:`${t} <small>(소스 문서 ${esc(f)})</small>`);
  if(n!==headings.length||/<(?:script|iframe|object|img)\b|\son\w+=/i.test(body))throw Error('Unexpected active content in '+source);
  const sha=createHash('sha256').update(text).digest('hex');
  const html=`<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="source-sha256" content="${sha}"><meta name="source-file" content="${source}">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; script-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>${esc(title)}</title><style>
:root{color-scheme:light;--ink:#223a42;--muted:#526b74;--line:#dce4e5;--accent:#25695c}
*{box-sizing:border-box}body{margin:0;background:#f5f7f6;color:var(--ink);font:16px/1.85 'Malgun Gothic','맑은 고딕',sans-serif;word-break:keep-all;overflow-wrap:anywhere}
a{color:var(--accent);text-underline-offset:4px}a:focus-visible,[tabindex]:focus-visible{outline:3px solid #4583a4;outline-offset:3px}.skip{position:absolute;left:16px;top:-80px}.skip:focus{top:10px;background:white;padding:12px}
.layout{max-width:1440px;margin:auto;padding:32px;display:grid;grid-template-columns:250px minmax(0,1fr);gap:32px}aside{position:sticky;top:24px;align-self:start;max-height:calc(100vh - 48px);overflow:auto}aside strong{font-size:23px}aside p{font-size:13px;color:var(--muted)}nav a{display:block;padding:7px 0;font-size:14px;text-decoration:none}nav a:hover{text-decoration:underline}.books{border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:18px}
main{min-width:0;background:white;border:1px solid var(--line);border-radius:12px;padding:44px 48px}h1{font-size:32px;line-height:1.4;margin:0 0 20px}h2{font-size:24px;line-height:1.5;border-top:1px solid var(--line);padding-top:28px;margin-top:44px;scroll-margin-top:24px}h3{font-size:19px}p{margin:14px 0}li{margin:8px 0}pre{background:#f0f5f3;border-left:3px solid #8bb6a9;padding:18px 20px;white-space:pre-wrap;overflow-wrap:anywhere}code{font-family:Consolas,'Malgun Gothic',monospace;font-size:.92em}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:580px;font-size:14px;line-height:1.7}td,th{border:1px solid var(--line);text-align:left;padding:12px;vertical-align:top}th{background:#eaf1ee}small,footer{color:var(--muted);font-size:12px}footer{margin-top:30px}
@media(max-width:800px){.layout{display:block;padding:14px}aside{position:static;max-height:none;margin:0 0 24px}nav{display:flex;flex-wrap:wrap;gap:6px 18px}nav a{padding:3px 0}main{padding:24px 20px}h1{font-size:27px}h2{font-size:22px}}
@media print{body{background:white;font-size:10pt}.layout{display:block;padding:0}aside,.skip{display:none}main{border:0;padding:0}h1{font-size:22pt}h2{font-size:16pt;break-after:avoid}h3{break-after:avoid}table{min-width:0;font-size:9pt}thead{display:table-header-group}tr,pre{break-inside:avoid}.table-wrap{overflow:visible}a{color:inherit}@page{size:A4;margin:18mm}}
</style></head><body><a class="skip" href="#content">본문으로 이동</a><div class="layout"><aside><strong>Company Agent</strong><p>사용자가 이해하고 함께 다듬는 업무 도구</p><nav class="books" aria-label="안내서 선택"><a href="Company-Agent-Handbook.html">기능·스킬·후크 핸드북</a><a href="Company-Agent-Onboarding.html">처음부터 따라 하기</a><a href="Company-Agent-Cua-Pilot.html">Cua Driver 시험 안내</a></nav><p>찾기: Ctrl+F · 인쇄/PDF: Ctrl+P<br>문서 열기는 AI 호출이나 작업 실행이 아닙니다.</p><nav aria-label="목차">${headings.map((h,i)=>`<a href="#section-${i+1}">${esc(h)}</a>`).join('')}</nav></aside><main id="content">${body}<footer>수정용 원본: ${source} · HTML은 자동 생성됩니다. 기본 문서 열기에 외부 요청·스크립트 실행이 없습니다. 외부 링크는 직접 선택했을 때만 이동합니다.</footer></main></div></body></html>
`;
  // One authored source, also available after the installer ZIP is removed.
  // These are offline reading assets, never automatically injected into hooks.
  for(const folder of ['docs','company-agent-plugin/resources/manuals']){
    const dest=path.join(root,folder,output);
    if(process.argv.includes('--check')){
      if(!fs.existsSync(dest)||fs.readFileSync(dest,'utf8')!==html)throw Error('Manual needs rebuilding: '+folder+'/'+output);
    }else{fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest,html,'utf8');}
  }
  console.log(`${output}: ${headings.length} chapters, ${Buffer.byteLength(html)} bytes`);
}
