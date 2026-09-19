"use strict";
const $ = (id) => document.getElementById(id);
const key = new URLSearchParams(location.hash.slice(1)).get("token");
if (key) { sessionStorage.setItem("workspaceToken", key); history.replaceState(null, "", "/"); }
const token = sessionStorage.getItem("workspaceToken") || "";
let active = null, sessions = [], attachments = [], pollController = null, boot = {}, started = null, previewPath = null;
const busyStates = new Set(["starting", "running", "approval", "question"]);
const statusLabels = {idle:"원하는 업무를 입력해 주세요", starting:"기존 Claude 설정을 연결하고 있어요", running:"요청을 처리하고 있어요", approval:"진행하려면 실행 내용을 확인해 주세요", question:"아래 질문에 답해 주세요", done:"이번 요청을 마쳤어요 · 후속 요청을 이어갈 수 있어요", error:"확인이 필요해요 · 안내 내용을 확인해 주세요", stopped:"중지했어요 · 이미 만들어진 파일은 유지됩니다"};

function el(tag, text, cls) { const node = document.createElement(tag); if (text != null) node.textContent = text; if (cls) node.className = cls; return node; }
function toast(text) { $("toast").textContent = text; $("toast").hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $("toast").hidden = true, 6000); }
function error(text) { $("error-banner").textContent = text; $("error-banner").hidden = !text; }
async function api(path, data, signal) {
  const options = {headers:{Authorization:`Bearer ${token}`}, signal};
  if (data !== undefined) { options.method = "POST"; options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(data); }
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "연결을 확인해 주세요.");
  return value;
}
function setStatus(state, label) {
  if (active) active.state = state;
  const busy = busyStates.has(state);
  const running = state === "starting" || state === "running";
  $("status-text").textContent = label || statusLabels[state] || "진행 상태를 확인하고 있어요";
  $("status").classList.toggle("busy", running);
  $("send").disabled = busy || !!boot.error;
  $("stop").hidden = !busy;
  if (running && !started) started = Date.now();
  if (!running) started = null;
}
setInterval(() => { $("elapsed").textContent = ["question", "approval"].includes(active?.state) ? "응답 대기" : started ? `${Math.floor((Date.now()-started)/1000)}초` : ""; }, 1000);
function renderSessions() {
  $("sessions").replaceChildren();
  for (const item of sessions) {
    const button = el("button", `▱  ${item.title}`, "session" + (item.id === active?.id ? " active" : ""));
    button.title = item.title; button.onclick = () => selectSession(item.id).catch(e => error(e.message));
    $("sessions").append(button);
  }
}
function renderMessage(message) {
  const article = el("article", null, `message ${message.role}`);
  article.append(el("div", message.role === "user" ? "나" : "COMPANY AGENT", "message-label"));
  // Model/tool output is untrusted. Never interpret it as HTML or event handlers.
  article.append(el("div", message.text, "message-body"));
  if (message.files?.length) article.append(el("div", message.files.map(p=>"▱ " + p.split(/[\\/]/).pop()).join(" · "), "message-files"));
  $("conversation").append(article);
}
function renderConnection(info) {
  const shared = boot.runtime ? `기존 Claude Code 로그인·설정을 그대로 사용합니다.\n실행: ${boot.runtime.entry}\n상속한 설정 위치: ${boot.runtime.configRoot}\n` : "";
  if (!info) { $("diagnostics").textContent = shared + "업무 시작 후 실제 CLI가 보고한 연결 정보를 표시합니다. 설치 확인은 로그인 성공을 뜻하지 않습니다."; return; }
  const names = list => (Array.isArray(list) ? list : []).map(x => typeof x === "string" ? x : x?.name || x?.id || "(이름 미제공)").join(", ");
  $("diagnostics").textContent = shared + `모델: ${info.model || "CLI에서 미제공"}\n스킬: ${names(info.skills) || "CLI가 목록을 보고하지 않음"}\n플러그인: ${names(info.plugins) || "CLI가 목록을 보고하지 않음"}\nMCP: ${(info.mcp||[]).map(x=>`${x.name}: ${x.status}`).join(", ") || "CLI가 목록을 보고하지 않음"}\n목록 노출은 실제 스킬 실행 성공을 뜻하지 않습니다.`;
}
async function selectSession(id) {
  if (pollController) pollController.abort();
  active = await api(`/api/session?id=${encodeURIComponent(id)}`);
  started = null;
  $("conversation").replaceChildren(); $("requests").replaceChildren(); $("activity").replaceChildren();
  active.messages.forEach(renderMessage);
  (active.requests || []).forEach(renderRequest);
  $("welcome").hidden = active.messages.length > 0;
  $("conversation").hidden = !active.messages.length;
  $("chat-title").textContent = active.title;
  $("folder-name").textContent = active.workspace.split(/[\\/]/).pop() || active.workspace;
  $("folder-path").textContent = active.workspace;
  renderConnection(active.connection);
  setStatus(active.state); renderSessions(); refreshFiles();
  pollController = new AbortController();
  poll(id, active.seq || 0, pollController.signal);
}
async function poll(id, after, signal) {
  while (!signal.aborted && active?.id === id) {
    try {
      const result = await api(`/api/events?id=${encodeURIComponent(id)}&after=${after}`, undefined, signal);
      for (const event of result.events) { handleEvent(event); after = event.seq; }
    } catch (e) {
      if (e.name === "AbortError") return;
      error("대화 연결을 확인할 수 없습니다. 새로고침하면 저장된 대화를 다시 불러옵니다.");
      setStatus("error"); return;
    }
  }
}
function handleEvent(event) {
  const d = event.data;
  const nearBottom = $("work-area").scrollHeight - $("work-area").scrollTop - $("work-area").clientHeight < 100;
  if (event.type === "assistant") { renderMessage({role:"assistant",text:d.text}); }
  if (event.type === "status") setStatus(d.state, d.label);
  if (event.type === "connected") { renderConnection(d); active.sessionId = d.sessionId; }
  if (event.type === "request") { renderRequest(d); setStatus(d.tool === "AskUserQuestion" ? "question" : "approval"); }
  if (event.type === "request_closed") {
    for (const node of $("requests").children) if (node.dataset.requestId === d.id) node.remove();
    if(d.state)setStatus(d.state);
    else if (!$("requests").children.length && busyStates.has(active?.state)) setStatus("running");
  }
  if (event.type === "activity") {
    const labels = {Skill:"스킬 불러오기",Read:"자료 확인",Bash:"업무 실행",Write:"파일 작성",Edit:"파일 수정",Agent:"담당 작업자 처리",Task:"담당 작업자 처리",AskUserQuestion:"질문 준비"};
    $("activity").append(el("li", (labels[d.tool] || d.tool || "작업") + (d.skill ? " · " + d.skill : "")));
    while ($("activity").children.length > 60) $("activity").firstChild.remove();
  }
  if (event.type === "result") { setStatus("done"); refreshFiles(); if(d.budgetWarning)toast(d.budgetWarning); }
  if (event.type === "error") { error(d.message); setStatus("error"); if ("resumeSessionId" in d) active.sessionId = d.resumeSessionId; $("requests").replaceChildren(); }
  if (event.type === "notice") toast(d.message);
  if (nearBottom || event.type === "request") requestAnimationFrame(() => {$("work-area").scrollTop=$("work-area").scrollHeight;});
}
function renderRequest(request) {
  if ([...$("requests").children].some(n => n.dataset.requestId === request.id)) return;
  const card = el("section", null, "request"); card.dataset.requestId = request.id;
  const questions = request.tool === "AskUserQuestion" ? request.input.questions : null;
  card.append(el("h3", questions ? "잠깐, 선택이 필요해요" : "이 작업을 실행해도 될까요?"));
  const fields = [];
  if (Array.isArray(questions) && questions.length) {
    for (const [i,q] of questions.entries()) {
      const field = el("fieldset"); field.append(el("legend", q.question));
      const inputs = [];
      for (const option of q.options || []) {
        const label = el("label", null, "option");
        const input = el("input"); input.type = q.multiSelect ? "checkbox" : "radio"; input.name = `${request.id}-${i}`; input.value = option.label;
        const body = el("span", option.label); if (option.description) body.append(el("small", option.description));
        label.append(input, body); field.append(label); inputs.push(input);
      }
      const custom = el("input"); custom.type = "text"; custom.placeholder = "직접 입력해도 좋아요"; custom.setAttribute("aria-label", q.question + " 직접 입력");
      field.append(custom); fields.push({q,inputs,custom}); card.append(field);
    }
  } else {
    card.append(el("p", `${request.title || request.tool} · 이번 요청에만 적용됩니다.`));
    if (request.description) card.append(el("p", request.description));
    card.append(el("pre", JSON.stringify(request.input, null, 2)));
  }
  const actions = el("div", null, "request-actions");
  const deny = el("button", questions ? "답변하지 않기" : "거절", "quiet-button");
  const allow = el("button", questions ? "선택 전달" : "이번만 승인", "send-button");
  async function answer(yes) {
    const answers = {};
    if (yes && questions) {
      for (const field of fields) {
        const values = field.inputs.filter(n => n.checked).map(n=>n.value);
        if (field.custom.value.trim()) { if (!field.q.multiSelect) values.length=0; values.push(field.custom.value.trim()); }
        if (!values.length) return toast("모든 질문에 답변을 선택하거나 입력해 주세요.");
        answers[field.q.question] = values.join(", ");
      }
    }
    allow.disabled = deny.disabled = true;
    try { await api("/api/respond", {id:active.id, requestId:request.id, allow:yes, answers}); }
    catch (e) { error(e.message); allow.disabled = deny.disabled = false; }
  }
  deny.onclick = () => answer(false); allow.onclick = () => answer(true); actions.append(deny,allow); card.append(actions); $("requests").append(card);
}
function renderAttachments() {
  $("attachments").replaceChildren();
  for (const path of attachments) {
    const chip = el("span", "▱ " + path.split(/[\\/]/).pop(), "attachment"); chip.title = path;
    const remove = el("button", "×"); remove.type="button"; remove.setAttribute("aria-label", path.split(/[\\/]/).pop() + " 첨부 취소");
    remove.onclick = () => { attachments=attachments.filter(p=>p!==path);renderAttachments(); };
    chip.append(remove); $("attachments").append(chip);
  }
}
async function refreshFiles() {
  if (!active) return;
  const id = active.id;
  try {
    const result = await api(`/api/files?id=${encodeURIComponent(id)}`);
    if (active?.id !== id) return;
    $("files").replaceChildren(); $("file-count").textContent = result.files.length;
    if (!result.files.length) $("files").append(el("p", "표시할 문서가 아직 없어요.", "composer-note"));
    for (const file of result.files) {
      const button=el("button", null, "file"); button.append(el("span","▱"),el("div",file.name)); button.title=file.path;
      button.onclick=()=>preview(file.path).catch(e=>error(e.message)); $("files").append(button);
    }
  } catch(e) { toast(e.message); }
}
async function preview(path) {
  const data = await api(`/api/preview?id=${encodeURIComponent(active.id)}&path=${encodeURIComponent(path)}`);
  previewPath=path; $("preview-title").textContent=data.name; $("preview-content").replaceChildren();
  if (data.kind === "image") { const img=el("img");img.src=data.data;img.alt=data.name;$("preview-content").append(img); }
  else if (data.kind === "html") {
    const frame=el('iframe');frame.title=data.name;frame.className='html-preview';
    frame.setAttribute('sandbox','');frame.setAttribute('referrerpolicy','no-referrer');frame.srcdoc=data.html;
    $("preview-content").append(el('p',data.message,'composer-note'),frame);
  }
  else if (data.kind === "text") $("preview-content").append(el("pre",data.text));
  else $("preview-content").append(el("p",data.message));
  $("open-file").hidden=/\.html?$/i.test(path) || boot.demo; $("preview-dialog").showModal();
}
function chooseFolder(resume=false) {
  $("folder-input").value = active?.workspace || boot.defaultWorkspace || "";
  $("trust").checked = false;
  $("folder-input").readOnly = resume;
  $("browse-folder").disabled = resume;
  $("folder-form").dataset.resume=resume ? "yes" : "no";
  $("folder-dialog").showModal();
}
async function submit() {
  if (!$("prompt").value.trim()) return $("prompt").focus();
  if (!active) return chooseFolder();
  if (!active.trusted) return chooseFolder(true);
  const text = $("prompt").value.trim();
  $("send").disabled = true; error("");
  try {
    await api("/api/send", {id:active.id,text,attachments,trusted:active.trusted});
    $("prompt").value=""; attachments=[];renderAttachments();
    const id=active.id;
    const updated=await api(`/api/session?id=${encodeURIComponent(id)}`);
    sessions=sessions.map(s=>s.id===id ? updated : s);
    await selectSession(id);
  } catch(e) {error(e.message);setStatus(active.state || "idle");}
}
$("composer").onsubmit=e=>{e.preventDefault();submit();};
$("prompt").onkeydown=e=>{if(e.key==="Enter" && (e.ctrlKey||e.metaKey)){e.preventDefault();submit();}};
$("folder-form").onsubmit=async e=>{
  if(e.submitter?.value !== "ok") return;
  e.preventDefault();
  if(!$("trust").checked) return;
  try{
    if($("folder-form").dataset.resume==="yes") {await api('/api/trust',{id:active.id,trusted:true});active.trusted=true;}
    else { const item=await api("/api/create",{workspace:$("folder-input").value,trusted:true});sessions.unshift(item);await selectSession(item.id); }
    $("folder-dialog").close(); if($("prompt").value.trim()) await submit();
  }catch(e){toast(e.message);}
};
$("browse-folder").onclick=async()=>{try{toast("폴더 선택 창을 열고 있어요.");const d=await api("/api/pick",{kind:"folder"});if(d.paths.length)$("folder-input").value=d.paths[0];}catch(e){toast(e.message);}};
$("attach").onclick=async()=>{try{toast("파일 선택 창을 열고 있어요.");const d=await api("/api/pick",{kind:"files"});attachments=[...new Set([...attachments,...d.paths])].slice(0,12);renderAttachments();}catch(e){toast(e.message);}};
$("attach-path").onclick=()=>$("path-dialog").showModal();
$("path-form").onsubmit=e=>{if(e.submitter?.value!=="ok")return;const p=$("path-input").value.trim().replace(/^"|"$/g,"");if(p)attachments=[...new Set([...attachments,p])].slice(0,12);renderAttachments();$("path-input").value="";};
$("new-chat").onclick=()=>{if(pollController)pollController.abort();active=null;attachments=[];started=null;renderAttachments();renderSessions();$("welcome").hidden=false;$("conversation").hidden=true;$("requests").replaceChildren();$("activity").replaceChildren();$("chat-title").textContent="나의 업무 공간";$("prompt").value="";$("folder-name").textContent="폴더를 선택해 주세요";$("folder-path").textContent="업무별 폴더로 자료와 결과를 함께 관리하세요.";$("files").replaceChildren();$("file-count").textContent="0";renderConnection(null);error("");setStatus("idle");};
$("choose-folder").onclick=()=>chooseFolder(); $("workspace-button").onclick=()=>chooseFolder();
document.querySelectorAll(".task-card").forEach(button=>button.onclick=()=>{$("prompt").value=button.dataset.prompt;$("prompt").focus();});
$("stop").onclick=async()=>{try{await api("/api/stop",{id:active.id});toast("중지 요청을 보냈어요.");}catch(e){error(e.message);}};
$("refresh-files").onclick=refreshFiles;
$("materials-button").onclick=()=>document.querySelector(".inspector").classList.add("open");
$("close-materials").onclick=()=>document.querySelector(".inspector").classList.remove("open");
$("close-preview").onclick=()=>$("preview-dialog").close();
$("open-file").onclick=async()=>{try{await api("/api/open",{id:active.id,path:previewPath});}catch(e){toast(e.message);}};
$("help").onclick=()=>$("help-dialog").showModal();$("close-help").onclick=()=>$("help-dialog").close();
$("native").onclick=async()=>{if(!active)return toast("먼저 작업 폴더를 선택해 주세요.");try{await api("/api/native",{id:active.id});toast("원본 Claude Code 창을 열었어요.");}catch(e){toast(e.message);}};
$("quit").onclick=async()=>{if(!confirm("연결된 모든 작업을 중지하고 앱을 종료할까요? 이미 생성한 파일은 유지됩니다."))return;try{await api("/api/quit",{});if(pollController)pollController.abort();error("앱을 종료했습니다. 이 창을 닫아도 됩니다.");$("send").disabled=true;}catch(e){error(e.message);}};
async function init(){try{boot=await api("/api/bootstrap");sessions=boot.sessions;$("demo-banner").hidden=!boot.demo;$("connection-badge").textContent=boot.demo?"체험 모드":boot.error?"연결 확인 필요":"기존 Claude 사용";renderConnection(null);renderSessions();if(boot.historyWarning)error(boot.historyWarning);if(boot.error){error(boot.error);$("send").disabled=true;}}catch(e){error(e.message);$("send").disabled=true;}}
document.querySelectorAll('button[value="cancel"]').forEach(button=>button.setAttribute("formnovalidate",""));
init();
