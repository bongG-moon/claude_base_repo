"""Self-contained report tables. Browser-only controls, with no remote resources."""
from __future__ import annotations

import html


def render(headers, rows, caption="", *, options=None):
    options = options or {}
    esc = lambda value: html.escape(str(value), quote=True)
    interactive = options.get("interactive", True)
    kind_rows = options.get("cellKinds", [])
    numeric_rows = options.get("cellNumbers", [])
    body = []
    for i, row in enumerate(rows):
        kinds = kind_rows[i] if i < len(kind_rows) else []
        numeric_values = numeric_rows[i] if i < len(numeric_rows) else []
        cells = []
        for j, value in enumerate(row):
            number = (kinds[j] == "number" if j < len(kinds) else
                      isinstance(value, (int, float)) and not isinstance(value, bool))
            attr = ' data-kind="number" class="numeric"' if number else ''
            if number and j < len(numeric_values) and numeric_values[j] is not None:
                attr += f' data-number="{esc(numeric_values[j])}"'
            cells.append(f'<td{attr}>{esc(value)}</td>')
        body.append('<tr>' + ''.join(cells) + '</tr>')
    return ('<div class="report-data-table" data-report-table="' + ('interactive' if interactive else 'static') + '">'
            '<div class="table-wrap" tabindex="0" role="region" aria-label="' + esc(caption or '보고서 데이터') + ' 표, 가로와 세로 스크롤">'
            f'<table style="--columns:{len(headers)}">' + (f'<caption>{esc(caption)}</caption>' if caption else '') +
            '<thead><tr>' + ''.join(f'<th scope="col">{esc(v)}</th>' for v in headers) + '</tr></thead><tbody>' +
            ''.join(body) + '</tbody></table></div>' +
            ('<p class="table-empty-source">데이터가 없습니다. 원자료의 조회 범위를 확인해 주세요.</p>' if not rows else '') + '</div>')


CSS = r"""
.report-data-table{min-width:0;margin:24px 0;border:1px solid var(--line);border-radius:12px;background:var(--paper);overflow:hidden}
.report-data-table [hidden]{display:none!important}
.report-data-table .table-wrap{margin:0;max-height:560px;overscroll-behavior:contain;scrollbar-gutter:stable}
.report-data-table table{border-collapse:separate;border-spacing:0;margin:0}
.report-data-table thead th{position:sticky;top:0;z-index:1;background:var(--paper);box-shadow:0 1px var(--line);color:var(--ink)}
.report-data-table :is(td,th){min-width:7rem;max-width:28rem;padding:12px 16px;word-break:keep-all;overflow-wrap:anywhere;white-space:pre-line;line-height:1.6}
.report-data-table tbody tr:hover{background:var(--bg)}
.report-data-table caption{text-align:left;font-weight:650;padding:12px 16px;color:var(--ink)}
.table-tools,.table-footer{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;padding:14px 16px;background:var(--paper)}
.table-tools{border-bottom:1px solid var(--line)}.table-footer{border-top:1px solid var(--line)}
.table-search-group,.table-actions,.table-pages{display:flex;align-items:center;flex-wrap:wrap;gap:8px;min-width:0}
.table-search-group{flex:1}.table-search-group label{font-size:13px;color:var(--muted)}
.report-data-table :is(button,input,select){font:inherit;font-size:14px;line-height:1.4;min-height:44px;border:1px solid var(--line);border-radius:7px;color:var(--ink);background:var(--paper);padding:9px 12px;max-width:100%}
.report-data-table input[type=search]{width:min(260px,100%);min-width:0}.report-data-table select{max-width:180px}
.report-data-table button:hover:not(:disabled){background:var(--bg);border-color:var(--accent)}
.report-data-table button:disabled{cursor:default;opacity:.45}.report-data-table .table-sort{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;text-align:left;min-height:44px;padding:0;border:0;background:none;font-weight:650}
.table-sort-indicator{color:var(--muted);font-size:12px}.table-count,.table-page-label,.table-empty-source{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}.table-count{margin:0}.table-empty-source{margin:16px}
.report-data-table :is(button,input,select):focus-visible{outline:3px solid var(--accent);outline-offset:2px}.report-data-table .table-no-match{text-align:center;padding:36px 16px;color:var(--muted)}
@media(max-width:760px){.table-tools,.table-footer{align-items:flex-start;padding:12px;gap:10px}.table-search-group{flex-basis:100%}.report-data-table input[type=search]{width:100%;flex-basis:100%;font-size:16px}.table-actions{width:100%}.table-actions button{flex:1}.table-footer{flex-direction:column}.report-data-table :is(td,th){padding:10px 12px}.table-pages{width:100%;justify-content:space-between}}
@media print{.report-data-table{overflow:visible;border-color:#bbb;break-inside:auto}.report-data-table .table-wrap{overflow:visible;max-height:none}.report-data-table table{min-width:0;width:100%;table-layout:fixed}.report-data-table thead{display:table-header-group}.report-data-table thead th{position:static}.report-data-table :is(td,th){min-width:0;max-width:none;font-size:10px;padding:6px}.table-tools,.table-pages{display:none!important}.table-footer{padding:6px}.report-data-table .table-sort{padding:0;min-height:0;font-size:inherit}.table-sort-indicator{display:none}}
"""

# These pure functions are also exercised independently of a browser. Data is
# kept separate from the DOM so exporting never loses rows on another page.
CORE_JS = r"""
function reportTableNumberCompare(left,right) {
  // Compare decimal magnitudes as strings: converting an Excel identifier or
  // large integer through Number would silently round beyond 2^53.
  function parts(value){const m=String(value).match(/^([+-]?)(\d+)(?:\.(\d*))?(?:e([+-]?\d+))?$/i);if(!m)return null;
    const digits=(m[2]+(m[3]||'')).replace(/^0+/,'')||'0';
    return {digits,sign:digits==='0'?0:m[1]==='-'?-1:1,order:digits.length+Number(m[4]||0)-(m[3]||'').length};}
  const a=parts(left),b=parts(right);if(!a||!b)return String(left).localeCompare(String(right),'ko-KR',{numeric:true});
  if(a.sign!==b.sign)return a.sign-b.sign;if(!a.sign)return 0;
  if(a.order!==b.order)return (a.order-b.order)*a.sign;
  const length=Math.max(a.digits.length,b.digits.length),x=a.digits.padEnd(length,'0'),y=b.digits.padEnd(length,'0');
  return (x<y?-1:x>y?1:0)*a.sign;
}
function reportTableRows(rows, state) {
  const query=String(state.query||'').trim().toLocaleLowerCase('ko-KR');
  let found=rows.filter(row=>(!query||row.values.some(v=>v.toLocaleLowerCase('ko-KR').includes(query)))&&
    (state.filterColumn<0||state.filterValue===null||row.values[state.filterColumn]===state.filterValue));
  if(state.sortColumn>=0){const col=state.sortColumn, direction=state.direction;
    found=found.slice().sort((a,b)=>{const x=a.values[col],y=b.values[col];
      const numeric=a.kinds[col]==='number'&&b.kinds[col]==='number';
      const order=numeric?reportTableNumberCompare(a.numbers?.[col]??x,b.numbers?.[col]??y):x.localeCompare(y,'ko-KR',{numeric:true});
      return order?order*direction:a.index-b.index;});}
  return found;
}
function reportTableCanFilter(values,rowCount) {
  return values.size>1&&values.size<rowCount&&values.size<=30&&[...values].every(v=>v.length<=80);
}
function reportTableCsv(headers, rows) {
  function cell(value,kind){let text=String(value);if(kind!=='number'&&/^[\s\uFEFF]*[=+\-@]/u.test(text))text="'"+text;
    return '"'+text.replaceAll('"','""')+'"';}
  return '\uFEFF'+[headers.map(v=>cell(v,'text')).join(','),...rows.map(row=>row.values.map((v,i)=>cell(row.kinds[i]==='number'?(row.numbers?.[i]??v):v,row.kinds[i])).join(','))].join('\r\n');
}
"""

JS = """'use strict';(()=>{\n""" + CORE_JS + r"""
document.querySelectorAll('[data-report-table="interactive"]').forEach((root,tableIndex)=>{
 const table=root.querySelector('table'),body=table.tBodies[0],headerCells=[...table.tHead.rows[0].cells];
 const headers=headerCells.map(c=>c.textContent), rows=[...body.rows].map((node,index)=>({node,index,values:[...node.cells].map(c=>c.textContent),kinds:[...node.cells].map(c=>c.dataset.kind||'text'),numbers:[...node.cells].map(c=>c.dataset.number??null)}));
 if(!rows.length)return;
 const state={query:'',filterColumn:-1,filterValue:null,sortColumn:-1,direction:1,page:0,size:25};
 const make=(tag,text,cls)=>{const el=document.createElement(tag);if(text)el.textContent=text;if(cls)el.className=cls;return el};
 const button=(text,action,cls)=>{const el=make('button',text,cls);el.type='button';el.addEventListener('click',action);return el};
 const tools=make('div','','table-tools'),actions=make('div','','table-actions'),footer=make('div','','table-footer'),count=make('p','','table-count');count.setAttribute('aria-live','polite');
 let found=rows,search,filterColumn,filterValue;
 const pages=make('div','','table-pages'),pageLabel=make('span','','table-page-label');
 const previous=button('이전',()=>{state.page--;draw()}),next=button('다음',()=>{state.page++;draw()});
 const size=make('select');size.setAttribute('aria-label','한 페이지에 표시할 행 수');
 [25,50,100].forEach(n=>{const o=make('option',n+'행씩');o.value=String(n);size.append(o)});
 size.addEventListener('change',()=>{state.size=Number(size.value);state.page=0;draw()});pages.append(size,previous,pageLabel,next);
 function draw(printing=false){found=reportTableRows(rows,state);const totalPages=Math.max(1,Math.ceil(found.length/state.size));state.page=Math.max(0,Math.min(state.page,totalPages-1));
   const visible=printing?found:found.slice(state.page*state.size,(state.page+1)*state.size);body.replaceChildren(...visible.map(r=>r.node));
   if(!found.length){const tr=make('tr'),td=make('td','조건에 맞는 데이터가 없습니다. 검색어나 필터를 바꾸어 주세요.','table-no-match');td.colSpan=headers.length;tr.append(td);body.append(tr)}
   count.textContent='전체 '+rows.length.toLocaleString('ko-KR')+'건 중 '+found.length.toLocaleString('ko-KR')+'건'+(found.length?' / '+(printing?'인쇄: 검색 결과 전체':(state.page*state.size+1)+'–'+Math.min(found.length,(state.page+1)*state.size)+'건 표시'):'');
   previous.disabled=state.page===0;next.disabled=state.page>=totalPages-1;pageLabel.textContent=(state.page+1)+' / '+totalPages;pages.hidden=rows.length<=25;currentDownload.disabled=!found.length;
   root.querySelector('.table-wrap').scrollTop=0;
 }
 function download(selected,label){const blob=new Blob([reportTableCsv(headers,selected)],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');
   a.href=url;a.download='보고서-표-'+(tableIndex+1)+'-'+label+'.csv';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 const currentDownload=button(rows.length>12?'검색 결과 CSV':'데이터 CSV',()=>download(found,'검색결과'));
 actions.append(currentDownload);
 if(rows.length>12){
   const group=make('div','','table-search-group');search=make('input');search.type='search';search.placeholder='표 안에서 검색';search.setAttribute('aria-label','표 안에서 검색');search.addEventListener('input',()=>{state.query=search.value;state.page=0;draw()});
   filterColumn=make('select');filterColumn.setAttribute('aria-label','필터 열 선택');let option=make('option','필터 열 선택');option.value='-1';filterColumn.append(option);
   headers.forEach((h,i)=>{const values=new Set(rows.map(r=>r.values[i]));if(reportTableCanFilter(values,rows.length)){const o=make('option',h);o.value=String(i);filterColumn.append(o)}});
   filterValue=make('select');filterValue.setAttribute('aria-label','필터 값 선택');filterValue.hidden=true;
   filterColumn.addEventListener('change',()=>{state.filterColumn=Number(filterColumn.value);state.filterValue=null;state.page=0;filterValue.replaceChildren();const all=make('option','모든 값');all.value='';filterValue.append(all);
     if(state.filterColumn>=0){[...new Set(rows.map(r=>r.values[state.filterColumn]))].sort((a,b)=>a.localeCompare(b,'ko-KR',{numeric:true})).forEach((v,i)=>{const o=make('option',v||'(빈 값)');o.value=String(i);o.dataset.filterValue=v;filterValue.append(o)})}
     filterValue.hidden=state.filterColumn<0;draw();});
   filterValue.addEventListener('change',()=>{state.filterValue=filterValue.value===''?null:filterValue.selectedOptions[0].dataset.filterValue;state.page=0;draw()});
   const reset=button('초기화',()=>{state.query='';state.filterColumn=-1;state.filterValue=null;state.sortColumn=-1;state.page=0;search.value='';filterColumn.value='-1';filterValue.hidden=true;headerCells.forEach(c=>c.removeAttribute('aria-sort'));headerCells.forEach(c=>{const indicator=c.querySelector('.table-sort-indicator');if(indicator)indicator.textContent='↕'});draw()});
   group.append(search);if(filterColumn.options.length>1)group.append(filterColumn,filterValue);group.append(reset);tools.append(group);
   actions.append(button('전체 CSV',()=>download(rows,'전체')));
 }
 headerCells.forEach((cell,col)=>{const title=headers[col],sort=button('',()=>{state.direction=state.sortColumn===col?-state.direction:1;state.sortColumn=col;state.page=0;
   headerCells.forEach((c,i)=>{c.removeAttribute('aria-sort');const indicator=c.querySelector('.table-sort-indicator');if(indicator)indicator.textContent=i===col?(state.direction===1?'↑':'↓'):'↕'});cell.setAttribute('aria-sort',state.direction===1?'ascending':'descending');draw()},'table-sort');
   sort.setAttribute('aria-label',title+' 정렬');sort.append(make('span',title),make('span','↕','table-sort-indicator'));cell.replaceChildren(sort)});
 tools.append(actions);footer.append(count,pages);root.prepend(tools);root.append(footer);draw();
 window.addEventListener('beforeprint',()=>draw(true));window.addEventListener('afterprint',()=>draw());
});
})();
"""
