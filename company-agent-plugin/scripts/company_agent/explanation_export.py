"""User-triggered export of generated diagrams; never runs work or fetches assets."""


def controls(index: int) -> str:
    return (f'<div class="diagram-export" data-diagram-target="explanation-{index}" hidden>'
            '<button type="button" data-export-format="svg">도표 SVG 저장</button> '
            '<button type="button" data-export-format="png">도표 PNG 저장</button>'
            '<p>그림만 저장합니다. 상세 설명·근거는 HTML에 남습니다. 글꼴은 PC에 따라 달라질 수 있습니다.</p>'
            '<p class="diagram-export-status" aria-live="polite"></p></div>')


CSS = """
.diagram-export{margin:12px 0 24px}.diagram-export[hidden]{display:none!important}
.diagram-export p{font-size:13px;color:var(--muted);margin:6px 0}.diagram-export button{font-size:14px}
@media print{.diagram-export{display:none!important}}
"""

# Export generated SVG only. Inline presentation properties keep standalone SVG
# independent of the HTML stylesheet. No HTML, remote styles, or images are copied.
JS = """'use strict';(()=>{
const properties=['fill','stroke','stroke-width','font-family','font-size','font-weight','text-anchor'];
function snapshot(source){
 const clone=source.cloneNode(true);clone.setAttribute('xmlns','http://www.w3.org/2000/svg');
 const originals=[source,...source.querySelectorAll('*')];const copies=[clone,...clone.querySelectorAll('*')];
 originals.forEach((node,index)=>{const style=window.getComputedStyle(node);properties.forEach(name=>{const value=style.getPropertyValue(name);if(value)copies[index].style.setProperty(name,value)});copies[index].removeAttribute('class')});
 // Always export the full, unhighlighted diagram, even during playback.
 clone.querySelectorAll('g[data-node-id] rect').forEach(rect=>{rect.style.fill='#fff';rect.style.stroke='#64748b';rect.style.strokeWidth='2'});
 return new XMLSerializer().serializeToString(clone);
}
function save(blob,name){const link=document.createElement('a');const url=URL.createObjectURL(blob);try{link.href=url;link.download=name;document.body.appendChild(link);link.click()}finally{try{link.remove()}finally{window.setTimeout(()=>URL.revokeObjectURL(url),1000)}}}
document.querySelectorAll('.diagram-export').forEach(panel=>{
 const source=document.getElementById(panel.dataset.diagramTarget)?.querySelector('.explanation-svg');
 const status=panel.querySelector('.diagram-export-status');const buttons=[...panel.querySelectorAll('button[data-export-format]')];
 if(!source||!status||typeof XMLSerializer==='undefined'||typeof URL.createObjectURL!=='function')return;
 panel.hidden=false;let busy=false;
 buttons.forEach(button=>button.addEventListener('click',async()=>{
  if(busy)return;busy=true;buttons.forEach(item=>item.disabled=true);status.textContent='도표를 준비하고 있습니다.';
  try{
   const svg=snapshot(source),name=panel.dataset.diagramTarget;
   if(button.dataset.exportFormat==='svg'){save(new Blob([svg],{type:'image/svg+xml;charset=utf-8'}),name+'.svg')}
   else{
    const width=Number(source.getAttribute('width')),height=Number(source.getAttribute('height'));
    if(!(width>0&&height>0&&Number.isFinite(width*height)))throw new Error('invalid size');
    const scale=Math.min(2,4096/Math.max(width,height),Math.sqrt(12000000/(width*height)));
    const canvas=document.createElement('canvas');canvas.width=Math.ceil(width*scale);canvas.height=Math.ceil(height*scale);
    const context=canvas.getContext('2d');if(!context)throw new Error('canvas unavailable');
    const picture=new Image();
    await new Promise((resolve,reject)=>{const timer=window.setTimeout(()=>{picture.onload=null;picture.onerror=null;reject(new Error('image timeout'))},8000);picture.onload=()=>{window.clearTimeout(timer);resolve()};picture.onerror=()=>{window.clearTimeout(timer);reject(new Error('image unavailable'))};picture.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg)});
    context.fillStyle='#fff';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(picture,0,0,canvas.width,canvas.height);
    const blob=await new Promise((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(new Error('PNG unavailable')),'image/png'));
    save(blob,name+'.png');
   }
   status.textContent='저장을 요청했습니다. 브라우저의 다운로드 결과를 확인하세요.';
  }catch(error){status.textContent='이미지 저장을 완료하지 못했습니다. HTML은 그대로 사용할 수 있습니다. SVG 저장 또는 인쇄를 이용하세요.'}
  finally{busy=false;buttons.forEach(item=>item.disabled=false)}
 }));
});
})();"""
