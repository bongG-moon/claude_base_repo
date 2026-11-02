"""Temporary, loopback-only query catalog UI. No database connections are made."""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import time
from urllib.parse import urlsplit
import uuid
import webbrowser

MAX_BODY = 65_536
IDLE_TIMEOUT = 15 * 60
MAX_LIFETIME = 60 * 60
DETACH_GRACE = 5
ENGINE_NAMES = {'oracle': 'Oracle', 'datalake': 'Datalake', 'ehub': 'E-Hub'}

HTML = r'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>데이터 조회 관리</title><style nonce="__NONCE__">
:root{font-family:"Noto Sans KR","Malgun Gothic",sans-serif;color:#172a43;background:#f3f6fb;font-synthesis:none;line-height:1.55}*{box-sizing:border-box}body{margin:0}button,input,textarea{font:inherit}button{cursor:pointer}button:disabled{cursor:wait;opacity:.6}button:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid #a8c5ff;outline-offset:2px}.shell{max-width:1440px;margin:auto;padding:34px 40px 48px}.mast{display:flex;justify-content:space-between;align-items:center;gap:20px}.brand{display:flex;align-items:center;gap:12px;font-size:15px;font-weight:800;letter-spacing:.02em}.mark{background:#315cf5;color:white;border-radius:12px;width:38px;height:38px;display:grid;place-items:center;font-size:21px}.local{font-size:12px;color:#47637d;border:1px solid #dce5ef;background:#fff;padding:5px 11px;border-radius:30px}.subtle{border:1px solid #d6e0eb;background:#fff;color:#3a516b;padding:9px 15px;border-radius:9px}.hero{display:flex;align-items:center;justify-content:space-between;gap:24px;margin:36px 0 25px}h1{font-size:31px;letter-spacing:-1px;margin:0 0 6px}p{margin:0;color:#6a7d94;font-size:14px}.primary{border:0;background:#315cf5;color:#fff;border-radius:9px;padding:12px 19px;font-weight:700;white-space:nowrap}.stats{display:flex;gap:14px;margin-bottom:25px}.stat{background:#fff;border:1px solid #e1e8f1;border-radius:13px;padding:15px 21px;min-width:180px;display:flex;justify-content:space-between;align-items:center;gap:35px;color:#63758c;font-size:13px}.stat strong{font-size:26px;color:#233952}.workspace{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:22px;align-items:start}.panel{background:#fff;border:1px solid #e0e7f0;border-radius:15px;box-shadow:0 3px 13px #283d5c04;overflow:hidden}.toolbar{padding:20px 22px 16px;border-bottom:1px solid #edf1f7}.tabs{display:flex;gap:22px;border-bottom:1px solid #edf1f7;margin-bottom:18px}.tab{border:0;border-bottom:3px solid transparent;background:none;padding:0 1px 13px;color:#75859a;font-weight:700}.tab[aria-selected=true]{color:#315cf5;border-color:#315cf5}.count{font-size:11px;margin-left:6px;background:#eef2fa;padding:2px 7px;border-radius:9px}.search{width:100%;border:1px solid #dce4ef;border-radius:9px;padding:10px 13px;background:#f9fbfd;color:#263b55}.results{display:flex;justify-content:space-between;font-size:12px;color:#7c8ba0;padding:15px 23px 10px}.table-scroll{overflow:auto;max-height:495px;min-height:260px}table{width:100%;border-collapse:collapse;text-align:left;font-size:13px;table-layout:fixed}th{position:sticky;top:0;background:#f8fafd;color:#8190a4;font-size:11px;font-weight:600;padding:12px 22px;border-bottom:1px solid #e9eef5}td{padding:15px 22px;border-bottom:1px solid #f0f3f8;overflow-wrap:anywhere}tbody tr{cursor:pointer}tbody tr:hover,tbody tr.selected{background:#f1f5ff}tbody tr:focus-visible{outline:2px solid #315cf5;outline-offset:-2px}td:first-child{font-weight:700;color:#2f4560}.pill{font-size:10px;color:#496bc1;background:#edf3ff;padding:4px 8px;border-radius:6px;display:inline-block}.empty{padding:65px 24px;text-align:center;color:#8897a9;font-size:14px}.detail{padding:24px}.eyebrow{font-size:10px;font-weight:800;letter-spacing:1.5px;color:#8495ac;margin-bottom:7px}.detail h2{font-size:20px;letter-spacing:-.4px;margin:0 0 6px}.detail>p{font-size:12px;margin-bottom:24px}.field{margin-bottom:17px}label{display:block;font-size:12px;font-weight:700;color:#52657e;margin-bottom:7px}input,textarea{width:100%;border:1px solid #d9e2ed;border-radius:8px;background:#fff;padding:10px 11px;font-size:13px;color:#263b55}input::placeholder,textarea::placeholder{color:#a3afbf}textarea{min-height:135px;resize:vertical;line-height:1.6;font-family:Consolas,"Malgun Gothic",monospace}.hint{font-size:11px;color:#8796a9;margin-top:6px}.form-actions{display:flex;gap:9px;margin-top:22px}.form-actions .primary{flex:1}.privacy{font-size:11px;color:#8b98a9;line-height:1.7;border-top:1px solid #edf1f7;margin-top:21px;padding-top:16px}.notice{min-height:22px;margin-top:12px;color:#345db8;font-size:12px;white-space:pre-wrap}.notice.error{color:#b73b4e}.code{white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto;background:#f6f8fc;border:1px solid #e5ebf4;border-radius:9px;padding:14px;color:#39516c;font-size:12px;line-height:1.8;font-family:Consolas,"Malgun Gothic",monospace}.detail-label{font-size:11px;color:#7e8fa5;font-weight:700;margin-top:22px}.hidden,[hidden]{display:none!important}.footer{color:#95a1b2;font-size:11px;text-align:center;margin-top:25px}.closed{padding:80px 20px;text-align:center}.closed h1{font-size:25px}@media(max-width:1050px){.shell{padding:24px}.workspace{grid-template-columns:minmax(0,1fr) 340px}.local{display:none}td,th{padding-left:15px;padding-right:15px}}@media(max-width:760px){.shell{padding:20px 16px}.workspace{grid-template-columns:1fr}.hero{margin-top:26px;align-items:flex-start}h1{font-size:25px}.hero .primary{font-size:12px;padding:10px}.stats{gap:10px}.stat{min-width:0;flex:1;padding:12px 15px;gap:12px}.table-scroll{max-height:320px;min-height:160px}.detail{padding:21px}.brand{font-size:13px}}
fieldset{border:0;padding:0;margin:0;min-width:0}.check{display:flex;gap:9px;align-items:flex-start;font-size:12px;font-weight:400;margin:13px 0}.check input{width:16px;height:16px;margin:2px 0;flex:0 0 auto}
select{font:inherit;width:100%;padding:9px;border:1px solid #d9e2ed;border-radius:8px;background:#fff;color:#263b55}.key-help{background:#f4f7ff;border-radius:9px;padding:13px;margin:5px 0 18px}.key-help a{color:#315cf5;font-size:12px;font-weight:700;text-decoration:none}.key-help p{font-size:11px;margin-top:7px}details{margin:16px 0}summary{font-size:12px;color:#6a7d94;cursor:pointer;margin-bottom:13px}
</style></head><body><main class="shell" id="app">
<header class="mast"><div class="brand"><span class="mark" id="engineMark" aria-hidden="true">O</span><span id="engineBrand">DATA MANAGER</span> <span class="local">내 PC의 개인 저장소</span></div><button class="subtle" id="close">닫기</button></header>
<section class="hero"><div><h1 id="heroTitle">내 데이터 연결</h1><p id="heroDescription">DB 연결을 관리하고 저장한 조회를 한곳에서 확인하세요.</p></div><button class="primary" id="add">＋ DB 추가</button></section>
<div class="stats"><div class="stat"><span id="profileStatLabel">등록된 DB</span><strong id="profileCount">0</strong></div><div class="stat">저장된 쿼리<strong id="queryCount">0</strong></div></div>
<div class="workspace"><section class="panel" aria-label="저장 목록"><div class="toolbar"><div class="tabs" role="tablist" aria-label="목록 선택"><button class="tab" id="profilesTab" role="tab" aria-selected="true"><span id="profileTabLabel">DB 연결</span><span class="count" id="profileTabCount">0</span></button><button class="tab" id="queriesTab" role="tab" aria-selected="false">저장 쿼리<span class="count" id="queryTabCount">0</span></button></div><input class="search" id="search" type="search" aria-label="목록 검색" placeholder="DB 이름으로 검색"></div><div class="results"><span id="found">전체 0개</span><span>선택하여 상세 보기</span></div><div class="table-scroll"><table><thead id="columns"></thead><tbody id="rows"></tbody></table><div class="empty" id="empty">아직 등록된 DB가 없습니다.</div></div></section>
<aside class="panel detail"><section id="editor"><div class="eyebrow" id="editorEyebrow">CONNECTION</div><h2 id="formTitle">새 DB 연결</h2><p id="editorDescription">설정을 저장하며, DB에는 접속하지 않습니다.</p>
<form id="profileForm" autocomplete="off"><div class="field" id="nameField"><label for="name" id="nameLabel">DB 이름</label><input id="name" maxlength="80" required placeholder="예: 생산 DB"></div>
<fieldset id="oracleFields"><div class="field"><label for="user">사용자 아이디</label><input id="user" maxlength="16000" required placeholder="예: report_reader" autocomplete="off" autocapitalize="none" spellcheck="false"></div><div class="field"><label for="password">비밀번호</label><input id="password" type="password" maxlength="16000" autocomplete="new-password" spellcheck="false"><div class="hint" id="passwordHint">새 연결의 비밀번호를 입력하세요.</div></div><div class="field"><label for="dsn">DSN 접속 정보</label><textarea id="dsn" required maxlength="16000" spellcheck="false" placeholder="db.example.internal:1521/PROD&#10;&#10;또는 TNS 접속 정보&#10;(DESCRIPTION=&#10;  (ADDRESS=(PROTOCOL=TCP)(HOST=db.example.internal)(PORT=1521))&#10;  (CONNECT_DATA=(SERVICE_NAME=PROD))&#10;)"></textarea><div class="hint">host:port/service 또는 여러 줄 TNS 정보를 붙여 넣으세요.</div></div></fieldset>
<fieldset id="lakeFields" hidden disabled><div class="field"><label for="user_id">사번</label><input id="user_id" maxlength="16000" required placeholder="예: 12345678" autocomplete="off" spellcheck="false"></div><div class="field"><label for="token" id="tokenLabel">개인 토큰</label><input id="token" type="password" maxlength="16000" autocomplete="new-password" spellcheck="false"><div class="hint" id="tokenHint">새 연결의 개인 토큰을 입력하세요.</div></div>
<fieldset id="sdkFields" hidden disabled><div class="field"><label for="s3_access_key">S3 Access Key</label><input id="s3_access_key" type="password" maxlength="16000" autocomplete="new-password" spellcheck="false"><div class="hint" id="s3AccessHint">S3 Access Key를 입력하세요.</div></div><div class="field"><label for="s3_secret_key">S3 Secret Key</label><input id="s3_secret_key" type="password" maxlength="16000" autocomplete="new-password" spellcheck="false"><div class="hint" id="s3SecretHint">S3 Secret Key를 입력하세요.</div></div><div class="key-help"><a id="myKeyLink" href="https://lake.skhynix.com/myprofile/mykey" target="_blank" rel="noopener noreferrer">JWT와 S3 키가 없나요? MyKey에서 발급하기 ↗</a><p>SSO 로그인 후 MyKey에서 사번, JWT, S3 Access Key와 S3 Secret Key를 확인해 이 창에 입력하세요.</p></div><details id="sdkAdvanced"><summary>고급 설정과 연결 별칭</summary><div class="field"><label for="lake_type">환경</label><select id="lake_type"><option value="prod">운영 (prod)</option><option value="dev">개발 (dev)</option></select></div><div id="aliasSlot"></div></details></fieldset>
<fieldset id="directFields"><div class="field"><label for="api_base">회사 API 주소</label><input id="api_base" type="url" required maxlength="16000" placeholder="https://lake.example.internal" spellcheck="false"></div><div class="field"><label for="cluster">클러스터 이름 (선택)</label><input id="cluster" maxlength="16000" placeholder="예: reporting" spellcheck="false"></div><div class="field"><label for="tls_ca">인증서 파일 (선택)</label><input id="tls_ca" maxlength="16000" placeholder="예: C:/certificates/company-ca.pem" spellcheck="false"></div><label class="check"><input id="allow_cluster_start" type="checkbox"><span>조회할 때 내 클러스터 준비와 기동을 허용합니다.</span></label><label class="check"><input id="allow_http" type="checkbox"><span>회사에서 지정한 HTTP 주소 사용을 확인했습니다.</span></label><div class="hint">두 항목은 필요한 경우에만 직접 선택합니다. 저장만으로 클러스터를 기동하지 않습니다.</div></fieldset></fieldset>
<div class="form-actions"><button type="button" class="subtle" id="clearForm">새로 입력</button><button class="primary" type="submit" id="save">연결 저장</button></div></form><div class="privacy">입력값은 이 PC의 개인 설정 파일에 평문으로 저장됩니다. 인증정보를 채팅에 보내거나 설정 파일을 공유하지 마세요.</div></section>
<section id="queryDetail" hidden><div class="eyebrow">SAVED QUERY</div><h2 id="queryTitle">저장 쿼리 상세</h2><p id="querySource">목록에서 쿼리를 선택하세요.</p><p id="queryDescription"></p><div id="queryBody" hidden><div class="detail-label">SQL (읽기 전용)</div><pre class="code" id="sql"></pre><div class="detail-label">조회 조건 (읽기 전용)</div><pre class="code" id="parameters"></pre><div class="privacy">저장된 SQL과 조건 정의만 표시합니다. 이 창에서 조회를 실행하지 않습니다.</div></div></section><div class="notice" id="notice" role="status" aria-live="polite"></div></aside></div><div class="footer" id="footerDescription">로컬 관리 화면: 저장만으로 DB에 연결하거나 쿼리를 실행하지 않습니다.</div>
</main><script nonce="__NONCE__">
'use strict';
const config=__CONFIG__, $=id=>document.getElementById(id), isOracle=config.engine==='oracle', isSDK=config.engine==='datalake';
document.title=config.engineLabel+' 데이터 관리';$('engineBrand').textContent=config.engineLabel.toUpperCase()+' DATA MANAGER';$('engineMark').textContent=config.engineLabel[0];$('oracleFields').hidden=!isOracle;$('lakeFields').hidden=isOracle;$('api_base').placeholder=config.apiPlaceholder;$('sdkFields').hidden=!isSDK;$('directFields').hidden=isOracle||isSDK;if(isSDK){$('tokenLabel').textContent='JWT';$('aliasSlot').append($('nameField'));$('nameLabel').textContent='연결 별칭 (선택)';$('name').required=false;$('tokenHint').textContent='JWT를 입력하세요.';for(const [field,label] of [['token','JWT'],['s3_access_key','S3 Access Key'],['s3_secret_key','S3 Secret Key']])$(field).placeholder='발급받은 '+label+' 붙여 넣기';}
if(isSDK){document.title='Data Lake 인증정보와 저장 쿼리';$('heroTitle').textContent='Data Lake 인증정보';$('heroDescription').textContent='인증정보는 한 번 설정하고, 테이블 경로로 조회 대상을 정합니다.';$('profileStatLabel').textContent='인증 설정';$('profileTabLabel').textContent='인증정보';$('editorEyebrow').textContent='AUTHENTICATION';$('editorDescription').textContent='사번과 개인 키를 저장합니다. 이 창에서 조회를 실행하지 않습니다.';$('footerDescription').textContent='테이블은 SQL의 lake_catalog.스키마.테이블 경로로 지정합니다. DB를 별도로 등록하지 않습니다.';$('nameLabel').textContent='인증정보 별칭 (선택)';$('name').placeholder='예: 내 Data Lake 계정';$('sdkAdvanced').querySelector('summary').textContent='고급 설정과 인증정보 별칭';$('add').hidden=true;$('clearForm').hidden=true;}
let catalog={profiles:[],queries:[]}, view=config.startView, selected=null, editing=null, selectionRequest=0, busy=false, sessionClosed=false;
function notice(text,error=false){$('notice').textContent=text;$('notice').classList.toggle('error',error);}
async function api(action,values={}){const response=await fetch(config.endpoint,{method:'POST',credentials:'omit',cache:'no-store',headers:{'Content-Type':'application/json','X-Query-Token':config.token},body:JSON.stringify({action,...values})});const result=await response.json();if(!response.ok||!result.ok)throw Error(result.message||'요청을 완료하지 못했습니다.');return result;}
function showError(error){notice(error instanceof TypeError?'관리 창의 연결이 종료되었습니다. 필요하면 다시 열어주세요.':error.message,true);}
function clearSecrets(){for(const key of ['password','token','s3_access_key','s3_secret_key'])$(key).value='';}
function setFormBusy(value){for(const el of $('profileForm').elements)el.disabled=value;$('oracleFields').disabled=value||!isOracle;$('lakeFields').disabled=value||isOracle;$('sdkFields').disabled=value||!isSDK;$('directFields').disabled=value||isOracle||isSDK;}
function secretState(saved,accessSaved=false,secretSaved=false){const key=isOracle?'password':'token';$(key).required=!saved;$(key+'Hint').textContent=saved?(isOracle?'비워 두면 저장된 비밀번호를 유지합니다. 변경할 때만 입력하세요.':isSDK?'비워 두면 저장된 JWT를 유지합니다.':'비워 두면 저장된 토큰을 유지합니다. 변경할 때만 입력하세요.'):(isOracle?'새 연결의 비밀번호를 입력하세요.':isSDK?'JWT를 입력하세요.':'새 연결의 개인 토큰을 입력하세요.');if(isSDK){for(const [field,hint,ready,label] of [['s3_access_key','s3AccessHint',accessSaved,'S3 Access Key'],['s3_secret_key','s3SecretHint',secretSaved,'S3 Secret Key']]){$(field).required=!ready;$(hint).textContent=ready?'비워 두면 저장된 '+label+'를 유지합니다.':label+'를 입력하세요.';}}}
function formValues(){return isOracle?{user:$('user').value,password:$('password').value,dsn:$('dsn').value}:isSDK?{user_id:$('user_id').value,token:$('token').value,s3_access_key:$('s3_access_key').value,s3_secret_key:$('s3_secret_key').value,lake_type:$('lake_type').value}:{user_id:$('user_id').value,token:$('token').value,api_base:$('api_base').value,cluster:$('cluster').value,tls_ca:$('tls_ca').value,allow_cluster_start:$('allow_cluster_start').checked,allow_http:$('allow_http').checked};}
function finish(message){sessionClosed=true;clearSecrets();$('app').replaceChildren();const end=document.createElement('section');end.className='closed';const title=document.createElement('h1');title.textContent=message;const text=document.createElement('p');text.textContent='이 브라우저 탭을 닫아도 됩니다.';end.append(title,text);$('app').append(end);}
function cell(row,value,cls){const el=document.createElement('td');if(cls){const span=document.createElement('span');span.className=cls;span.textContent=value;el.append(span);}else el.textContent=value;row.append(el);}
function render(){for(const [key,id] of [['profiles','profile'],['queries','query']]){$(id+'Count').textContent=catalog[key].length;$(id+'TabCount').textContent=catalog[key].length;}
 $('profilesTab').setAttribute('aria-selected',view==='profiles');$('queriesTab').setAttribute('aria-selected',view==='queries');$('editor').hidden=view!=='profiles';$('queryDetail').hidden=view!=='queries';$('search').placeholder=view==='profiles'?(isSDK?'인증정보 별칭으로 검색':'DB 이름으로 검색'):(isSDK?'쿼리 이름이나 인증정보 별칭으로 검색':'쿼리 이름이나 DB 이름으로 검색');
 $('columns').replaceChildren();const head=document.createElement('tr');for(const title of view==='profiles'?(isSDK?['인증정보','종류']:['DB 이름','종류']):(isSDK?['쿼리 이름','사용할 인증정보']:['쿼리 이름','연결 DB'])){const th=document.createElement('th');th.textContent=title;head.append(th);}$('columns').append(head);
 const needle=$('search').value.trim().toLocaleLowerCase();const items=catalog[view].filter(item=>(item.name+' '+(item.sourceName||'')).toLocaleLowerCase().includes(needle));$('found').textContent=needle?`${items.length}개 검색, 전체 ${catalog[view].length}개`:`전체 ${items.length}개`;$('rows').replaceChildren();
 for(const item of items){const row=document.createElement('tr');row.tabIndex=0;row.setAttribute('aria-label',item.name);row.classList.toggle('selected',selected===item.id);cell(row,item.name);cell(row,view==='profiles'?config.engineLabel:item.sourceName,view==='profiles'?'pill':null);row.onclick=()=>select(item);row.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(item);}};$('rows').append(row);}
 $('empty').hidden=items.length>0;$('empty').textContent=needle?'검색 결과가 없습니다.':view==='profiles'?(isSDK?'인증정보를 입력하면 테이블 경로로 조회할 수 있습니다.':'아직 등록된 DB가 없습니다. 오른쪽에서 첫 연결을 추가하세요.'):'아직 저장된 쿼리가 없습니다.';}
function blank(){selectionRequest++;editing=null;selected=null;HTMLFormElement.prototype.reset.call($('profileForm'));setFormBusy(false);if(isSDK)$('name').value='Datalake';$('formTitle').textContent=isSDK?'Data Lake 인증정보':'새 DB 연결';$('save').textContent=isSDK?'인증정보 저장':'연결 저장';secretState(false);notice('');render();}
function switchView(next){if(busy)return;selectionRequest++;view=next;selected=null;$('search').value='';notice('');render();}
async function select(item){if(busy)return;const request=++selectionRequest;try{const data=await api(view==='profiles'?'profile':'query',{id:item.id});if(request!==selectionRequest)return;selected=item.id;
 if(view==='profiles'){editing=data.profile.id;$('name').value=data.profile.name;if(isOracle){$('user').value=data.profile.user;$('dsn').value=data.profile.dsn;}else if(isSDK){$('user_id').value=data.profile.user_id;$('lake_type').value=data.profile.lake_type||'prod';}else{for(const key of ['user_id','api_base','cluster','tls_ca'])$(key).value=data.profile[key]||'';for(const key of ['allow_cluster_start','allow_http'])$(key).checked=data.profile[key]===true;}clearSecrets();secretState(isOracle?data.profile.passwordSaved:data.profile.tokenSaved,data.profile.s3AccessKeySaved,data.profile.s3SecretKeySaved);$('formTitle').textContent=isSDK?'Data Lake 인증정보':'DB 연결 수정';$('save').textContent='변경 저장';}
 else{$('queryTitle').textContent=data.query.name;$('querySource').textContent=data.sourceName;$('queryDescription').textContent=data.query.description||'';$('sql').textContent=data.query.sql;$('parameters').textContent=JSON.stringify(data.query.parameters||{},null,2);$('queryBody').hidden=false;}notice('');render();}catch(error){if(request===selectionRequest)showError(error);}}
async function refresh(){const data=await api('catalog');catalog=data;render();}
$('profilesTab').onclick=()=>switchView('profiles');$('queriesTab').onclick=()=>switchView('queries');$('search').oninput=render;
$('add').onclick=()=>{if(!busy){view='profiles';$('search').value='';blank();$(isSDK?'user_id':'name').focus();}};$('clearForm').onclick=()=>{if(!busy)blank();};
$('profileForm').onsubmit=async event=>{event.preventDefault();if(busy)return;busy=true;selectionRequest++;setFormBusy(true);$('save').textContent='저장 중…';try{const data=await api('save',{id:editing,name:$('name').value,...formValues()});editing=data.profile.id;selected=editing;clearSecrets();if(config.closeOnSave){finish(isSDK?'인증정보를 저장했습니다.':'연결 설정을 저장했습니다.');return;}secretState(true,true,true);$('formTitle').textContent=isSDK?'Data Lake 인증정보':'DB 연결 수정';await refresh();notice(isSDK?'인증정보를 저장했습니다. 조회는 실행하지 않았습니다.':'연결 설정을 저장했습니다. DB 접속은 실행하지 않았습니다.');}catch(error){showError(error);}finally{busy=false;if(!sessionClosed){setFormBusy(false);$('save').textContent=editing?'변경 저장':isSDK?'인증정보 저장':'연결 저장';}}};
$('close').onclick=async()=>{if(busy)return;$('close').disabled=true;try{await api('close');finish('관리 창을 닫았습니다.');}catch(error){showError(error);$('close').disabled=false;}};
window.addEventListener('pagehide',()=>{if(!sessionClosed)fetch(config.endpoint,{method:'POST',credentials:'omit',keepalive:true,headers:{'Content-Type':'application/json','X-Query-Token':config.token},body:JSON.stringify({action:'detach'})}).catch(()=>{});});
setFormBusy(false);secretState(false);(async()=>{try{await refresh();if(config.profileId){view='profiles';render();await select({id:config.profileId});}else if(view==='profiles'){blank();if(isSDK&&catalog.profiles.length>1)notice('이전에 저장한 인증정보가 여러 개입니다. 사용할 항목을 목록에서 선택하세요.');}}catch(error){showError(error);}})();
</script></body></html>'''


class InputError(ValueError):
    pass


class ManagerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, store, engine='oracle', profile_id=None, start_view='profiles'):
        if engine not in ENGINE_NAMES or store.demo:
            raise ValueError('이 관리 창은 Oracle, Datalake 또는 E-Hub 연결 설정에 사용합니다.')
        if start_view not in {'profiles', 'queries', 'connection'}:
            raise ValueError('DB 연결 또는 저장 쿼리 화면을 선택해 주세요.')
        if profile_id is not None and store.profile(profile_id).get('engine') != engine:
            raise ValueError('다른 조회 스킬의 연결은 이 창에서 수정하지 않습니다.')
        # Data Lake의 profile은 DB 목적지가 아니라 재사용하는 개인 인증정보다.
        # 기존 인증정보가 하나면 바로 수정하고, 여러 개인 경우에만 선택을 남긴다.
        if engine == 'datalake' and profile_id is None:
            saved = store.profiles(engine)
            if len(saved) == 1:
                profile_id = saved[0]['id']
        self.store, self.engine = store, engine
        self.token = secrets.token_urlsafe(32)
        self.nonce = secrets.token_urlsafe(24)
        self.prefix = '/' + self.token + '/'
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.started = self.last_activity = time.monotonic()
        self.saved_count = 0
        self.saved_profile = None
        self.exit_on_save = start_view == 'connection'
        self.detached_at = None
        super().__init__(('127.0.0.1', 0), Handler)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)
        self.url = self.origin + self.prefix
        config = {'token': self.token, 'endpoint': self.prefix + 'api', 'profileId': profile_id,
                  'startView': 'profiles' if self.exit_on_save else start_view, 'closeOnSave': self.exit_on_save,
                  'engine': engine, 'engineLabel': ENGINE_NAMES[engine],
                  'apiPlaceholder': 'https://ehub.example.internal' if engine == 'ehub' else 'https://lake.example.internal'}
        self.page = HTML.replace('__NONCE__', self.nonce).replace('__CONFIG__', json.dumps(config)).encode('utf-8')

    def handle_error(self, request, client_address):
        pass  # Never log request paths, bodies or exception values.

    def dispatch(self, data):
        action = data.get('action')
        save_fields = ({'id', 'name', 'user', 'password', 'dsn'} if self.engine == 'oracle' else
                       {'id', 'name', 'user_id', 'token', 's3_access_key', 's3_secret_key', 'lake_type'}
                       if self.engine == 'datalake' else
                       {'id', 'name', 'user_id', 'token', 'api_base', 'cluster', 'tls_ca', 'allow_cluster_start', 'allow_http'})
        fields = {'catalog': set(), 'profile': {'id'}, 'query': {'id'},
                  'save': save_fields, 'close': set(), 'detach': set()}
        if not isinstance(action, str) or action not in fields or set(data) - {'action'} != fields[action]:
            raise InputError('지원하는 관리 동작만 요청해 주세요.')
        if action == 'catalog':
            return {'profiles': self.store.profiles(self.engine), 'queries': self.store.queries(self.engine)}
        if action in {'profile', 'query'}:
            if action == 'query':
                if type(data['id']) is not int or data['id'] < 1:
                    raise InputError('저장된 쿼리를 선택해 주세요.')
                query = self.store.query(data['id'], self.engine)
                return {'query': query, 'sourceName': self.store.profile(query['profile'])['name'], 'executed': False}
            profile = self._profile(data['id'])
            credentials = self.store.secrets(profile['id'])
            info = {'id': profile['id'], 'name': profile['name']}
            if self.engine == 'oracle':
                info.update(user=credentials.get('user', ''), dsn=credentials.get('dsn', ''),
                            passwordSaved=bool(credentials.get('password')))
            elif self.engine == 'datalake':
                info.update(user_id=credentials.get('user_id', ''), tokenSaved=bool(credentials.get('token')),
                            s3AccessKeySaved=bool(credentials.get('s3_access_key')),
                            s3SecretKeySaved=bool(credentials.get('s3_secret_key')), lake_type=profile.get('lake_type', 'prod'))
            else:
                info.update(user_id=credentials.get('user_id', ''), tokenSaved=bool(credentials.get('token')),
                            **{key: profile.get(key, '') for key in ('api_base', 'cluster', 'tls_ca')},
                            **{key: profile.get(key) is True for key in ('allow_cluster_start', 'allow_http')})
            return {'profile': info}
        if action == 'close':
            return {'status': 'closed'}
        if action == 'detach':
            self.detached_at = time.monotonic()
            return {'status': 'detached'}
        current = self._profile(data['id']) if data['id'] is not None else None
        if self.engine == 'datalake' and current is None:
            saved = self.store.profiles('datalake')
            if len(saved) > 1:
                raise InputError('저장된 Data Lake 인증정보가 여러 개입니다. 수정할 항목을 목록에서 선택해 주세요.')
            if saved:
                current = self._profile(saved[0]['id'])
        text_fields = (('name', 'user', 'password', 'dsn') if self.engine == 'oracle' else
                       ('name', 'user_id', 'token', 's3_access_key', 's3_secret_key', 'lake_type') if self.engine == 'datalake'
                       else ('name', 'user_id', 'token', 'api_base', 'cluster', 'tls_ca'))
        for key in text_fields:
            if not isinstance(data[key], str) or len(data[key]) > (80 if key == 'name' else 16000):
                raise InputError('입력값의 형식과 길이를 확인해 주세요.')
        profile = dict(current) if current else {'id': 'db_' + uuid.uuid4().hex[:12], 'engine': self.engine}
        profile['name'] = data['name'].strip()
        secret_key = 'password' if self.engine == 'oracle' else 'token'
        secret = data[secret_key]
        if current and not secret:
            secret = self.store.secrets(current['id']).get(secret_key, '')
        if self.engine == 'oracle':
            if not all((profile['name'], data['user'].strip(), secret, data['dsn'].strip())):
                raise InputError('DB 이름, 아이디, 비밀번호와 DSN을 모두 입력해 주세요.')
            credentials = {'user': data['user'].strip(), 'password': secret, 'dsn': data['dsn'].strip()}
        elif self.engine == 'datalake':
            if data['lake_type'] not in ('prod', 'dev'):
                raise InputError('Datalake 환경은 prod 또는 dev로 선택해 주세요.')
            credentials = dict(self.store.secrets(current['id'])) if current else {}
            for key in ('user_id', 'token', 's3_access_key', 's3_secret_key'):
                value = data[key].strip() if key == 'user_id' else data[key]
                if value:
                    credentials[key] = value
            if not all(credentials.get(key, '').strip() for key in ('user_id', 'token', 's3_access_key', 's3_secret_key')):
                raise InputError('사번, JWT, S3 Access Key와 S3 Secret Key 4개 값을 로컬 설정창에 입력해 주세요. 기존 설정은 유지했습니다.')
            profile['name'] = profile['name'] or (current['name'] if current else 'Datalake')
            profile['lake_type'] = data['lake_type']
        else:
            if not all((profile['name'], data['user_id'].strip(), secret)):
                raise InputError('DB 이름, 사번, 개인 토큰과 API 주소를 모두 입력해 주세요.')
            for key in ('allow_cluster_start', 'allow_http'):
                if type(data[key]) is not bool:
                    raise InputError('연결 동의 항목은 선택 또는 해제로 지정해 주세요.')
            base = data['api_base'].strip().rstrip('/')
            try:
                parsed = urlsplit(base)
                port = parsed.port  # Validate malformed or out-of-range ports without making a connection.
                valid = (parsed.scheme in {'http', 'https'} and parsed.hostname and
                         parsed.username is None and parsed.password is None and
                         not any(c.isspace() or ord(c) < 32 for c in base) and
                         not any(c in base for c in ('?', '#', '\\')))
            except ValueError:
                valid = False
            if not valid:
                raise InputError('아이디나 토큰, 조회 조건이 없는 올바른 회사 API 주소를 입력해 주세요.')
            if parsed.scheme == 'http' and not data['allow_http']:
                raise InputError('회사에서 지정한 HTTP 주소 사용 여부를 선택해 주세요. 주소를 임의로 바꾸지 않습니다.')
            profile.update(api_base=base, cluster=data['cluster'].strip(), tls_ca=data['tls_ca'].strip(),
                           allow_http=data['allow_http'], allow_cluster_start=data['allow_cluster_start'])
            credentials = {'user_id': data['user_id'].strip(), 'token': secret}
        info = self.store.save_profile(profile, credentials, replace=current is not None)
        self.saved_count += 1
        self.saved_profile = info
        return {'profile': info, 'connected': False}

    def _profile(self, profile_id):
        if not isinstance(profile_id, str):
            raise InputError('수정할 인증정보를 선택해 주세요.' if self.engine == 'datalake' else '수정할 DB 연결을 선택해 주세요.')
        profile = self.store.profile(profile_id)
        if profile.get('engine') != self.engine:
            raise InputError('다른 조회 스킬의 연결은 수정하지 않습니다.')
        return profile


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {'ok': False, 'message': '허용되지 않은 관리 요청입니다.'})

    def reply(self, status, value, *, page=False):
        raw = value if page else json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if page else 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'nonce-" + self.server.nonce +
                         "'; style-src 'nonce-" + self.server.nonce + "'; connect-src " + self.server.origin +
                         "; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def boundary(self, *, api=False):
        try:
            parsed = urlsplit(self.path)
        except ValueError:
            return False
        expected = self.server.prefix + ('api' if api else '')
        if (self.client_address[0] != '127.0.0.1' or self.server.closed.is_set() or
            parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or self.path != expected):
            return False
        if self.headers.get_all('Host', []) != [self.server.origin.removeprefix('http://')]:
            return False
        origins = self.headers.get_all('Origin', [])
        if origins != [self.server.origin] and (api or origins):
            return False
        if self.headers.get('Sec-Fetch-Site', 'none') not in {'none', 'same-origin'}:
            return False
        if any(self.headers.get(name) for name in ('Forwarded', 'X-Forwarded-Host', 'X-Forwarded-Proto')):
            return False
        if api:
            tokens = self.headers.get_all('X-Query-Token', [])
            if len(tokens) != 1 or not hmac.compare_digest(tokens[0].encode('utf-8'), self.server.token.encode('utf-8')):
                return False
        return True

    def do_GET(self):
        if not self.boundary():
            self.send_error(403)
            return
        with self.server.lock:
            self.server.detached_at = None
            self.server.last_activity = time.monotonic()
        self.reply(200, self.server.page, page=True)

    def do_POST(self):
        if not self.boundary(api=True):
            self.send_error(403)
            return
        lengths = self.headers.get_all('Content-Length', [])
        types = self.headers.get_all('Content-Type', [])
        if self.headers.get('Transfer-Encoding') or len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            self.send_error(400)
            return
        size = int(lengths[0])
        if size < 1 or size > MAX_BODY:
            self.send_error(413)
            return
        if len(types) != 1 or types[0].split(';')[0].strip().lower() != 'application/json':
            self.send_error(415)
            return
        try:
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise InputError('요청을 다시 확인해 주세요.')
            data = json.loads(raw.decode('utf-8'))
            if not isinstance(data, dict):
                raise InputError('올바른 관리 요청을 사용해 주세요.')
            with self.server.lock:
                if self.server.closed.is_set():
                    raise InputError('관리 창이 종료되었습니다.')
                result = self.server.dispatch(data)
                self.server.last_activity = time.monotonic()
            self.reply(200, dict(ok=True, **result))
            if data['action'] == 'close' or (data['action'] == 'save' and self.server.exit_on_save):
                self.server.closed.set()
        except InputError as error:
            self.reply(400, {'ok': False, 'message': str(error)})
        except Exception:
            message = ('인증정보를 확인하지 못했습니다. 입력값, 인증정보 별칭과 개인 저장소를 확인해 주세요.'
                       if self.server.engine == 'datalake' else
                       '설정을 확인하지 못했습니다. 입력값, 같은 DB 이름의 등록 여부와 개인 저장소를 확인해 주세요.')
            self.reply(400, {'ok': False, 'message': message})


def show(store, engine, profile_id=None, start_view='profiles'):
    server = ManagerServer(store, engine, profile_id, start_view)
    worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
    worker.start()
    status = 'closed'
    try:
        if not webbrowser.open(server.url, new=1, autoraise=True):
            raise ValueError('기본 브라우저를 열지 못했습니다. 브라우저 설정을 확인한 뒤 다시 실행해 주세요.')
        while not server.closed.wait(.25):
            now = time.monotonic()
            if server.detached_at is not None and now - server.detached_at >= DETACH_GRACE:
                break
            if now - server.last_activity > IDLE_TIMEOUT or now - server.started > MAX_LIFETIME:
                status = 'expired'
                break
    finally:
        server.closed.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
    if server.exit_on_save and server.saved_profile:
        return {'ok': True, 'status': 'saved', 'profile': server.saved_profile, 'connected': False,
                'message': '인증정보를 저장했습니다. 조회는 아직 실행하지 않았습니다.' if engine == 'datalake' else
                           '연결 설정을 저장했습니다. 실제 접속은 아직 하지 않았습니다.'}
    return {'ok': True, 'status': status, 'savedCount': server.saved_count, 'connected': False, 'executed': False,
            'message': '관리 창을 닫았습니다.' if status == 'closed' else '사용 시간이 지나 관리 창을 종료했습니다. 필요하면 다시 열어주세요.'}
