"use strict";
// All source/model/memory text is rendered as text, never interpreted as HTML.
(() => {
  let view = 'guide', data = {}, sid = null, generation = 0;
  const tabs = {guide:'따라 하기', memory:'개인 기억', knowledge:'회사·개인 지식', brief:'폴더 업무 지침', usage:'사용 현황', checks:'준비·결과 확인'};
  const content = $('companion-content');
  const labels = {active:'사용 중',draft:'초안',inactive:'사용 안 함',deprecated:'사용 중단',ready:'확인됨',check:'확인 필요',unverified:'미검증',passed:'통과',failed:'실패',cancelled:'중지',blocked:'차단'};
  const message = text => $('companion-message').textContent = text || '';
  const button = (text, fn, cls='quiet-button') => {const b=el('button',text,cls);b.type='button';b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){message(e.message);}finally{b.disabled=false;}};return b;};
  const note = text => el('p',text,'companion-note');
  const card = (title, text) => {const c=el('section',null,'companion-card');c.append(el('h3',title));if(text)c.append(note(text));return c;};
  const actions = (...buttons) => {const n=el('div',null,'companion-actions');n.append(...buttons);return n;};
  function field(parent, label, value='', type='textarea') {
    const wrap=el('label',null,'companion-field'), n=el(type==='select'?'select':type==='textarea'?'textarea':'input');
    wrap.append(el('span',label));if(type!=='textarea'&&type!=='select')n.type=type;
    n.value=value;n.setAttribute('aria-label',label);if(type==='textarea'){n.rows=3;n.maxLength=6000;}wrap.append(n);parent.append(wrap);return n;
  }
  function select(parent,label,items,value) {const n=field(parent,label,'','select');for(const [v,t] of items){const o=el('option',t);o.value=v;n.append(o);}n.value=value;return n;}
  function checkbox(parent,label,checked=false){const wrap=el('label',null,'companion-check'),n=el('input');n.type='checkbox';n.checked=checked;wrap.append(n,el('span',label));parent.append(wrap);return n;}
  async function action(value){if(!sid||active?.id!==sid)throw new Error('작업 폴더가 바뀌었습니다. 도우미를 다시 열어 주세요.');return api('/api/companion',{id:sid,...value});}
  async function load(){
    const ticket=++generation;
    message('로컬 정보를 확인하고 있어요. AI 호출은 하지 않습니다.');
    const next= sid ? await api('/api/companion?id='+encodeURIComponent(sid)+'&view='+encodeURIComponent(view)) : {course:await api('/api/course')};
    if(ticket!==generation)return;
    data=next;message('');render();
  }
  async function open(which){
    view=which;sid=active?.trusted?active.id:null;data={};
    $('companion-dialog').showModal();content.replaceChildren();
    await load();
  }
  function requireHarness(){if(data.harness)return true;content.append(note(data.unavailable || '먼저 신뢰할 수 있는 작업 폴더를 선택하세요. 기존 Claude 로그인·개인 설정은 그대로 유지합니다.'));return false;}
  async function hydrate(category,item){
    if(typeof item.body==='string')return item;
    return Object.assign(item,await action({action:'detail',category,entryKey:item.entryKey}));
  }
  function bodyDetails(category,item){
    const d=el('details'), body=el('pre');d.append(el('summary','내용·출처 보기'),body);
    d.ontoggle=async()=>{if(!d.open||d.dataset.loading)return;d.dataset.loading='yes';body.textContent='선택한 내용만 읽고 있어요.';
      try{const fresh=await hydrate(category,item);body.textContent=fresh.body;}catch(e){body.textContent=e.message;delete d.dataset.loading;}};
    return d;
  }
  function more(category,list){
    if(!list.nextCursor)return;
    content.append(button('다음 항목 보기',async()=>{
      const ticket=generation, result=await action({action:'list',category,cursor:list.nextCursor});
      if(ticket!==generation)return;
      list.items.push(...result.items);list.nextCursor=result.nextCursor;list.limited=result.limited;
      list.warnings=[...new Set([...(list.warnings||[]),...(result.warnings||[])])];render();
    }));
  }
  function compose(prompt){$('companion-dialog').close();if($('prompt').value.trim()&&!confirm('작성 중인 요청을 예문으로 바꿀까요?'))return;$('prompt').value=prompt;$('prompt').focus();toast('입력창에 넣었습니다. 내용을 확인하고 보내기를 눌러 주세요.');}
  async function preview(change){
    const result=await action({action:'plan',data:change});
    const block=card('저장 전 확인','아래 내용만 저장합니다. 실제 다음 업무에 적용됐는지는 별도로 확인해야 합니다.');
    const names={title:'제목',body:'내용',status:'사용 상태',goal:'목표',inputs:'입력 자료',outputs:'결과물',checks:'완료 확인 기준'};
    for(const [k,title]of Object.entries(names))if(result.preview.spec[k])block.append(el('h4',title),el('pre',labels[result.preview.spec[k]]||result.preview.spec[k]));
    if(result.preview.spec.metadata?.workspace_review)block.append(note('출처: '+result.preview.spec.metadata.workspace_review.reference));
    block.append(actions(button('취소',()=>block.remove()),button('확인하고 저장',async()=>{const saved=await action({action:'apply',token:result.token,confirmed:true});await load();message('저장했습니다. 다음 업무의 적용 여부는 아직 확인하지 않았습니다.');if(saved.path){const d=el('details');d.append(el('summary','저장 위치 확인'),note(saved.path));content.prepend(d);}},'send-button')));
    content.prepend(block);block.scrollIntoView({block:'start'});
  }
  function guide(){
    content.append(note(data.course?.intro||''));
    for(const step of data.course?.steps||[]){
      const c=card(step.title,step.concept);c.append(el('pre',step.prompt),note('확인할 것 · '+step.check));
      c.append(actions(button('입력창에 넣기',()=>compose(step.prompt)),...(step.alternativePrompt?[button(step.id==='read'?'파일 없이 텍스트로 연습':'PPT로 연습',()=>compose(step.alternativePrompt))]:[])));
      c.append(note('잘 안될 때 · '+step.recovery));
      if(sid){const check=checkbox(c,'직접 확인했어요 · 업무 성공 자동 판정이 아닙니다',!!data.records?.steps?.[step.id]?.checked);check.onchange=async()=>{check.disabled=true;try{await action({action:'progress',step:step.id,checked:check.checked});}catch(e){check.checked=!check.checked;message(e.message);}finally{check.disabled=false;}};}
      content.append(c);
    }
    if(!sid)content.append(note('확인한 단계를 저장하려면 먼저 작업 폴더를 선택하세요.'));
  }
  function memoryForm(item=null, version=null){
    const c=card(version?'이전 내용 복원':item?'기억 수정':'짧은 선호 하나 저장','문서 본문·계정 정보 대신 앞으로 필요한 선호만 적으세요.');
    const title=field(c,'기억 제목',version?.title||item?.title||'','text');title.maxLength=200;
    const body=field(c,'기억할 내용',version?.body||item?.body||'');body.maxLength=2000;
    const kind=select(c,'기억 종류',[['preference','표현 선호'],['work_context','업무 맥락'],['convention','업무 관례']],version?.kind||item?.kind||'preference');
    const status=select(c,'사용 상태',[['active','사용'],['draft','초안'],['inactive','사용 안 함']],item?.status==='deprecated'?'inactive':item?.status||'active');
    c.append(actions(button('취소',()=>c.remove()),button('변경안 확인',()=>preview({kind:'memory',itemId:item?.id,expectedSha256:item?.sha256,title:title.value,body:body.value,memoryKind:kind.value,status:status.value}),'send-button')));
    content.prepend(c);title.focus();
  }
  function memories(){
    if(!requireHarness())return;
    const mem=data.harness.memory;
    content.append(note('이 화면은 Company Agent가 관리하는 개인 기억입니다. Claude 자체 자동 기억 파일은 덮어쓰거나 합치지 않습니다.'),button('＋ 개인 기억 추가',()=>memoryForm()));
    for(const item of mem.items){
      const source={explicit_workspace_request:'이 화면에서 직접 저장',explicit_user_feedback:'직접 요청',self_learning:'업무 중 학습'}[item.source]||'기존 저장 기록';
      const c=card(item.title,`${labels[item.status]||item.status} · ${source}`);c.append(bodyDetails('memory',item));
      c.append(actions(button('수정',async()=>memoryForm(await hydrate('memory',item))),button(item.status==='active'?'사용 안 함':'다시 사용',async()=>{const fresh=await hydrate('memory',item);return preview({kind:'memory',itemId:fresh.id,expectedSha256:fresh.sha256,title:fresh.title,body:fresh.body,memoryKind:fresh.kind,status:fresh.status==='active'?'inactive':'active'});}),button('이전 내용 보기',async()=>{
        const result=await action({action:'versions',itemId:item.id}), box=card('이전 내용',result.notice);
        if(!result.versions.length)box.append(note('이전 저장본이 없습니다.'));
        for(const v of result.versions){const detail=el('details');detail.append(el('summary',v.version),el('pre',v.body),button('이 내용으로 복원안 보기',()=>memoryForm(item,v)));box.append(detail);}c.append(box);
      })));
      content.append(c);
    }
    if(!mem.items.length)content.append(note('아직 저장한 개인 기억이 없습니다.'));
    more('memory',mem);
    (mem.warnings||[]).forEach(x=>content.append(note(x)));if(mem.limited)content.append(note('표시 한도에 도달했습니다. 전체 항목이 아닐 수 있습니다.'));
    const learn=data.harness.learning, c=card('업무 중 학습 관리','끄더라도 기존 기억과 스킬은 지우지 않습니다. 자동 학습 후보가 모두 적용되는 것은 아닙니다.');
    if(typeof learn.enabled==='boolean')c.append(button(learn.enabled?'자동 학습 끄기':'자동 학습 켜기',async()=>{if(!confirm('기존 자료를 보존하고 자동 학습을 '+(learn.enabled?'끌까요?':'켤까요?')))return;await action({action:'learning',enabled:!learn.enabled,confirmed:true});await load();}));
    else c.append(note(learn.notice||'학습 상태 미확인'));
    for(const change of learn.recentChanges||[]){const row=el('div',null,'companion-row');row.append(note(`${change.id} · ${change.status||'기록됨'}`),button('이 변경 되돌리기',async()=>{if(!confirm('선택한 학습 변경을 되돌릴까요? 이후 직접 편집한 내용은 보존합니다.'))return;await action({action:'rollback',changeId:change.id,confirmed:true});await load();}));c.append(row);}content.append(c);
    for(const candidate of learn.recentCandidates||[]){const d=el('details');d.append(el('summary','학습 후보 · '+candidate.title+' · '+candidate.status),el('pre',candidate.body),note('후보 기록만으로 업무에 적용된 것은 아닙니다.'));c.append(d);}
  }
  function knowledgeForm(item=null){
    const c=card(item?'개인 지식 검토·수정':'개인 지식 초안 만들기','회사 지식을 수정하지 않습니다. 개인 내용도 공유 전 검토가 필요합니다.');
    const title=field(c,'지식 제목',item?.title||'','text'), body=field(c,'확인한 업무 지식',item?.body||''), reference=field(c,'출처·확인 근거',item?.review?.reference||'','text');
    const date=field(c,'다음 확인일 (선택)',item?.review?.reviewAfter||'','date');
    const status=select(c,'적용 상태',[['draft','초안 · 업무에 미적용'],['active','검토 후 개인 업무에 사용'],['deprecated','사용 중단']],item?.status||'draft');
    c.append(actions(button('취소',()=>c.remove()),button('저장 내용 확인',()=>preview({kind:'knowledge',itemId:item?.id,expectedSha256:item?.sha256,title:title.value,body:body.value,reference:reference.value,reviewAfter:date.value,status:status.value}),'send-button')));content.prepend(c);title.focus();
  }
  function knowledge(){
    if(!requireHarness())return;
    content.append(note('관리 주체는 회사와 개인입니다. 부서 업무 기준도 회사 영역에 포함되며, 프로젝트는 적용 범위입니다.'),button('＋ 개인 지식 초안',()=>knowledgeForm()));
    const policy=card('회사 업무 기준 · 읽기 전용','지식 문서와 회사 필수 정책은 다릅니다. 이 화면에서 회사 기준을 수정하지 않습니다.');
    const rules=data.harness.policy;policy.append(note('조회 상태: '+({available:'확인됨','not-configured':'업무 기준 항목 미설정 · 회사 보안 정책이 없다는 뜻은 아닙니다.',unavailable:'확인 필요 · 없는 것으로 처리하지 않습니다.'}[rules.status]||'미확인')));
    for(const rule of rules.rules||[])policy.append(note((rule.level==='required'?'필수':'기본값')+' · '+rule.text));content.append(policy);
    const selected=new Set();
    const share=button('선택한 개인 지식을 공유 후보로 내보내기',async()=>{if(!selected.size)return message('공유할 개인 지식을 선택하세요.');if(!confirm('선택한 지식을 로컬 ZIP 후보로 만들까요? 외부 전송·회사 반영은 하지 않습니다. 공유 전 민감 내용을 직접 검토하세요.'))return;const r=await action({action:'share',itemIds:[...selected],confirmed:true});message(r.notice+' '+r.path);});content.append(share);
    for(const item of data.harness.knowledge.items){
      const c=card(item.title,`${item.ownership==='company'?'회사 · 읽기 전용':'개인'} · ${labels[item.status]||item.status}`);
      const d=bodyDetails('knowledge',item);d.append(note(`출처: ${item.review?.reference||item.source||'미확인'} / 확인: ${item.review?.reviewedAt||'미확인'} / 다음 확인: ${item.review?.reviewAfter||'미지정'}`));c.append(d);
      if(item.ownership==='personal'){
        const cb=checkbox(c,'공유 후보에 포함');cb.onchange=()=>cb.checked?selected.add(item.id):selected.delete(item.id);
        if(item.kind==='term'&&!item.extends)c.append(button('검토·수정',async()=>knowledgeForm(await hydrate('knowledge',item))));
      }content.append(c);
    }
    if(!data.harness.knowledge.items.length)content.append(note('표시할 지식이 없습니다. 이 표시는 회사 정책이나 실제 검색 적용 여부를 보장하지 않습니다.'));
    more('knowledge',data.harness.knowledge);
    (data.harness.knowledge.warnings||[]).forEach(x=>content.append(note(x)));
    if(data.harness.knowledge.limited)content.append(note('일부 항목만 표시합니다. 전체 목록이 아닙니다.'));
  }
  function brief(){
    if(!requireHarness())return;
    const item=data.harness.brief;content.append(note(item.notice),note(item.path));
    if(item.sha256){const d=el('details');d.append(el('summary','현재 업무 지침'),el('pre',item.body||'(빈 파일)'));content.append(d);if(!item.owned)return content.append(note('기존 또는 직접 수정한 파일입니다. 이 화면에서 덮어쓰지 않습니다.'));}
    const c=card('이 폴더에서 할 일만 짧게','회사 정책·전역 CLAUDE.md·개인 설정은 그대로 둡니다. 저장 후 새 대화에서 적용을 확인하세요.');
    const fields={};for(const[k,label]of Object.entries({goal:'업무 목표',inputs:'입력 자료',outputs:'원하는 결과물',checks:'완료 확인 기준'})){fields[k]=field(c,label);fields[k].maxLength=600;}
    c.append(button('업무 지침 미리보기',()=>preview({kind:'brief',expectedSha256:item.sha256,...Object.fromEntries(Object.entries(fields).map(([k,n])=>[k,n.value]))}),'send-button'));content.append(c);
  }
  function metricsPanel(title, value, tokenKey='tokens'){
    const c=card(title,value.notice);const values=value[tokenKey]||{};
    const grid=el('dl',null,'metric-grid');for(const[k,t]of Object.entries({input_tokens:'입력',output_tokens:'출력',cache_read_input_tokens:'캐시 재사용',cache_creation_input_tokens:'캐시 작성'})){const box=el('div');box.append(el('dt',t),el('dd',values[k]===null||values[k]===undefined?'미제공':values[k].toLocaleString()));grid.append(box);}c.append(grid);
    return c;
  }
  function usage(){
    const t=data.telemetry||{notice:'업무 시작 후 현재 요청의 CLI 보고값을 표시합니다.'};content.append(metricsPanel('현재 요청 · 관찰된 값',t));
    const p=t.phaseMs||{};const times=card('어디에서 기다렸나요?','앱이 관찰한 구간입니다. 모델 추론·후크·도구 내부 시간을 임의로 나누지 않습니다.');
    const fmt=x=>x===undefined||x===null?'미확인':(x/1000).toFixed(1)+'초';
    times.append(note(`전체 경과 ${fmt(t.wallMs)} / 실행 구간 ${fmt((p.starting||0)+(p.running||0))} / 사용자 승인 대기 ${fmt(p.approval)} / 질문 응답 대기 ${fmt(p.question)}`),note('CLI 보고 비용: '+(t.cliReportedCostUsd==null?'미제공 · 사내 단가를 추정하지 않습니다.':'$'+t.cliReportedCostUsd+' (CLI 보고값, 청구액 검증 아님)')),note('관찰한 스킬 호출: '+(t.skills?.join(', ')||'미관찰 · 목록 부재를 뜻하지 않음')));content.append(times);
    if(t.budgetWarning)times.append(note(t.budgetWarning));
    const budget=field(times,'다음 요청부터 토큰 알림 기준 (빈칸은 해제)','','number');budget.min=1;
    times.append(button('이 대화에만 알림 설정',async()=>{const r=await action({action:'budget',tokenAlert:budget.value===''?null:Number(budget.value)});message(r.notice);}));
    const c=card('선택한 기록만 분석','과거 기록은 자동 검색하지 않습니다. 직접 고른 JSONL만 최대 8개 읽고 원문·경로를 분석 결과에 저장하지 않습니다. 현재 요청 값과 합산하지 않습니다.');
    const paths=field(c,'분석할 JSONL 절대 경로 (한 줄에 하나)'), office=field(c,'Office 결과 JSON 절대 경로 (선택)','','text');
    c.append(button('선택한 로컬 기록 분석',async()=>{const result=await action({action:'usage',paths:paths.value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean),officeResult:office.value.trim()||undefined});const out=metricsPanel('선택 로그 · 별도 분석',result);out.append(note(`상태: ${result.status} / 같은 범위 재읽기: ${result.sameRangeReads??'미확인'} / 고유 메시지: ${result.uniqueUsageMessages??'미확인'}`),note(`관찰한 도구 오류 ${result.observedToolErrors??'미확인'} / 재시도 ${result.retryCount??'미확인'}`),note(result.costReason));for(const model of result.byModel||[])out.append(metricsPanel('모델 · '+model.model,model));if(result.officeTiming)out.append(el('pre',JSON.stringify(result.officeTiming,null,2)));c.append(out);}));if(data.unavailable) c.append(note(data.unavailable));content.append(c);
  }
  function checks(){
    const c=card('준비 상태와 실제 결과는 다릅니다','파일·목록이 있다는 사실만으로 모델 성능이나 Office 읽기 성공을 판정하지 않습니다.');
    for(const check of data.harness?.checks||[])c.append(note(check.label+' · '+(labels[check.status]||check.status)+(check.count!==undefined?' ('+check.count+')':'')));
    if(!data.harness)c.append(note(data.unavailable||'작업 폴더 선택 후 확인할 수 있습니다.'));
    if(data.harness){c.append(note(`스킬 이름 충돌: ${data.harness.skillConflicts} / 목록에 표시된 스킬: ${data.harness.skills.length}`));const d=el('details');d.append(el('summary','발견한 스킬 · 실제 실행과 별개'));for(const s of data.harness.skills)d.append(note(`${s.invocation||s.name} · ${s.source} · ${s.description}`));c.append(d);}content.append(c);
    const a=data.assessment||{total:0,counts:{}};content.append(note(`직접 평가한 기록 ${a.total}건 · ${Object.entries(labels).filter(([k])=>['passed','failed','unverified','cancelled','blocked'].includes(k)).map(([k,v])=>v+' '+(a.counts[k]||0)).join(' / ')}`),note(a.notice||'평가하지 않은 업무를 성공으로 계산하지 않습니다.'));
    const workflowLabels={read:'자료 읽기',report:'결과 만들기',revise:'수정',remember:'기억 저장',reuse:'기억 재사용'};
    for(const group of a.groups||[])content.append(note(`${group.demo?'체험':'앱 대화 관찰'} / ${workflowLabels[group.workflow]||group.workflow} / ${group.model||'모델 미확인'} / 평가 시 설치 ${group.coreVersionAtReview||'미확인'} · ${group.total}건 · 수정 횟수를 답한 ${group.repairsReported}건의 수정 합계 ${group.reportedRepairs}회`));
    if(sid)content.append(actions(button('원문 없는 확인 기록 내려받기',async()=>{const r=await action({action:'records-export',confirmed:true});const url=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:'application/json'}));const link=el('a');link.href=url;link.download='workspace-self-check-'+Date.now()+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}),button('이 폴더의 확인 기록만 비우기',async()=>{if(!confirm('따라 하기와 자기 확인 기록만 비울까요? 이 기록은 되돌릴 수 없습니다. 대화·기억·결과 파일은 그대로 남습니다.'))return;const r=await action({action:'records-clear',confirmed:true});await load();message(r.notice);} )));
    if(!data.telemetry?.requestId)return content.append(note('업무를 한 번 실행하고 결과를 직접 확인하면 평가를 남길 수 있습니다.'));
    const f=card('이번 결과 직접 확인','대화에 “완료”가 나와도 수치·파일을 직접 확인하세요. 실패·중지·미확인도 남길 수 있습니다.');
    const workflow=select(f,'확인한 업무',[['read','자료 읽기'],['report','결과 만들기'],['revise','수정'],['remember','기억 저장'],['reuse','기억 재사용']],'read');
    const status=select(f,'결과 판정',[['unverified','아직 미확인'],['passed','직접 확인 통과'],['failed','실패'],['cancelled','중지'],['blocked','차단']],'unverified');
    const checks={};for(const[k,text]of Object.entries({content:'내용·수치를 원자료와 대조했어요',scope:'확인 범위와 미확인 부분을 구분했어요',artifact:'결과 파일을 열어 직접 확인했어요',noOverwrite:'기존 파일이 보존됐는지 확인했어요'}))checks[k]=checkbox(f,text);
    const repairs=field(f,'내가 요청한 수정 횟수 (미확인이면 빈칸)','','number');repairs.min=0;repairs.max=100;
    f.append(button('내 확인 결과 저장',async()=>{await action({action:'outcome',confirmed:true,requestId:data.telemetry.requestId,workflow:workflow.value,status:status.value,checks:Object.entries(checks).filter(([,n])=>n.checked).map(([k])=>k),repairs:repairs.value===''?null:Number(repairs.value)});await load();},'send-button'));content.append(f);
  }
  function render(){
    content.replaceChildren();$('companion-tabs').replaceChildren();
    $('companion-scope').textContent=(data.demo?'체험 모드 · 가상 결과 / ':'')+(data.harness?data.harness.scope.label+' · '+(active?.workspace||''):'회사 기준 + 개인 업무 · 별도 로그인 없음');
    for(const[k,title]of Object.entries(tabs)){const b=button(title,async()=>{view=k;message('');await load();});b.setAttribute('aria-current',k===view?'page':'false');$('companion-tabs').append(b);}
    $('companion-tabs').append(button('새로고침',load));
    ({guide,memory:memories,knowledge,brief,usage,checks}[view])();
    $('companion-dialog').scrollTop=0;
  }
  $('learn-open').onclick=()=>open('guide').catch(e=>message(e.message));
  $('memory-open').onclick=()=>open('memory').catch(e=>message(e.message));
  $('usage-open').onclick=()=>open('usage').catch(e=>message(e.message));
  $('companion-close').onclick=()=>{$('companion-dialog').close();generation++;};
})();
