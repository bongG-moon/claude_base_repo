/* Shipped layout reader. Source HTML scripts are removed before this executes. */
(() => {
  'use strict';
  const options = __COMPANY_OPTIONS__;
  const result = {pages: [], warnings: []};
  const fail = message => { throw new Error(message); };
  const warning = text => { if (!result.warnings.includes(text)) result.warnings.push(text); };
  const rgb = value => {
    const match = value.match(/^rgba?\(([^)]+)\)$/);
    if (!match) return {color: '000000', opacity: 0};
    const values = match[1].split(',').map(Number);
    return {color: values.slice(0, 3).map(v => Math.round(v).toString(16).padStart(2, '0')).join('').toUpperCase(), opacity: values[3] ?? 1};
  };
  const capture = () => {
    const slides = [...document.querySelectorAll(options.selector)];
    if (!slides.length || slides.length > 60) fail('슬라이드 선택자로 1~60장을 찾을 수 없습니다.');
    if (slides.some(s => slides.some(other => other !== s && other.contains(s)))) fail('슬라이드 선택자는 중첩되지 않아야 합니다.');
    for (const slide of slides) {
      slide.hidden = false;
      slide.style.setProperty('display', 'block', 'important');
      slide.style.setProperty('visibility', 'visible', 'important');
      slide.style.setProperty('transform', 'none', 'important');
    }
    const first = slides[0].getBoundingClientRect();
    if (first.width < 600 || first.height < 300) fail('고정 크기의 HTML 슬라이드가 필요합니다.');
    const scale = 960 / first.width;
    result.width = 960;
    result.height = first.height * scale;
    let totalChars = 0;
    for (const [index, slide] of slides.entries()) {
      const frame = slide.getBoundingClientRect();
      if (Math.abs(frame.width - first.width) > 1 || Math.abs(frame.height - first.height) > 1) fail('HTML 페이지 크기가 서로 다릅니다.');
      const page = {elements: [], title: (slide.querySelector('h1,h2')?.textContent || `${index + 1}장`).trim().slice(0, 90), background: 'FFFFFF'};
      result.pages.push(page);
      const box = rect => ({x: (rect.left - frame.left) * scale, y: (rect.top - frame.top) * scale, w: rect.width * scale, h: rect.height * scale});
      const push = e => {
        if (e.w < .01 || e.h < .01) return;
        if (e.x < -.5 || e.y < -.5 || e.x + e.w > result.width + .5 || e.y + e.h > result.height + .5) fail(`${index + 1}장에 잘리거나 화면 밖인 요소가 있습니다.`);
        e.x = Math.max(0, e.x); e.y = Math.max(0, e.y);
        e.w = Math.min(e.w, result.width - e.x); e.h = Math.min(e.h, result.height - e.y);
        page.elements.push(e);
        if (page.elements.length > 1200) fail('한 장의 개체 수가 1200개를 넘습니다.');
      };
      const text = (node, style) => {
        if (!node.textContent.trim()) return;
        if ((totalChars += node.length) > 200000) fail('HTML 본문이 너무 큽니다.');
        if (style.textTransform !== 'none' || parseFloat(style.letterSpacing)) warning('자간·대소문자 효과는 PowerPoint에서 재확인이 필요합니다.');
        const lines = [];
        const range = document.createRange();
        for (let start = 0; start < node.length;) {
          const length = node.codePointAt?.(start) > 65535 ? 2 : (node.textContent.codePointAt(start) > 65535 ? 2 : 1);
          range.setStart(node, start); range.setEnd(node, start + length);
          const rect = range.getBoundingClientRect(), value = node.textContent.slice(start, start + length);
          start += length;
          if (!rect.width || !rect.height) continue;
          let line = lines.at(-1);
          if (!line || Math.abs(line.top - rect.top) > 2) {
            line = {top:rect.top,left:rect.left,right:rect.right,bottom:rect.bottom,value:''}; lines.push(line);
          }
          line.value += value;
          line.left = Math.min(line.left, rect.left); line.right = Math.max(line.right, rect.right); line.bottom = Math.max(line.bottom, rect.bottom);
        }
        for (const line of lines) {
          if (!line.value.trim()) continue;
          const b = box({left:line.left,top:line.top,width:line.right-line.left,height:line.bottom-line.top});
          // Small width tolerance avoids clipping a final glyph; no font shrinking.
          b.w = Math.min(b.w + 1.5, result.width - b.x);
          push({kind:'text', ...b, text:line.value, size:parseFloat(style.fontSize)*scale,
                color:rgb(style.color).color, bold:parseInt(style.fontWeight) >= 600,
                italic:style.fontStyle === 'italic', underline:style.textDecorationLine.includes('underline'),
                font:style.fontFamily.split(',')[0].trim().replace(/^['"]|['"]$/g,''), wrap:false, lineSpacing:1});
        }
      };
      const visit = (node, inheritedOpacity=1) => {
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        const style = getComputedStyle(node), opacity = inheritedOpacity * Number(style.opacity);
        if (style.display === 'none' || style.visibility === 'hidden' || opacity === 0) return;
        const rect = node.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        if (['SCRIPT','STYLE','META','LINK','HEAD','TITLE'].includes(node.tagName)) return;
        if (['SVG','CANVAS','VIDEO','IFRAME','OBJECT','EMBED'].includes(node.tagName)) fail(`${node.tagName} 요소는 네이티브 변환 대상이 아닙니다. 승인된 개별 그림 또는 native chart로 지정해 주세요.`);
        if (style.transform !== 'none' || style.filter !== 'none' || style.clipPath !== 'none' || style.backgroundImage !== 'none') fail('변환하지 못하는 회전·필터·클립·배경 이미지/그라디언트가 있습니다. 단순화하거나 개별 그림 사용을 확인해 주세요.');
        for (const pseudo of ['::before','::after']) {
          const content = getComputedStyle(node,pseudo).content;
          if (content && !['none','normal','""'].includes(content)) fail('CSS 가상 요소의 내용을 실제 HTML 요소로 바꿔 주세요.');
        }
        const fill = rgb(style.backgroundColor), border = rgb(style.borderTopColor);
        const borderWidth = parseFloat(style.borderTopWidth);
        const uniform = ['Right','Bottom','Left'].every(side => style[`border${side}Width`] === style.borderTopWidth && style[`border${side}Color`] === style.borderTopColor);
        const radius = parseFloat(style.borderTopLeftRadius) * scale;
        let shadow;
        if (style.boxShadow !== 'none') {
          const match = style.boxShadow.match(/^(rgba?\([^)]+\))\s+([-\d.]+)px\s+([-\d.]+)px\s+([\d.]+)px\s+([-\d.]+)px$/);
          if (!match || Number(match[5]) !== 0) fail('다중/안쪽/확장 그림자는 단일 외부 그림자로 바꿔 주세요.');
          const ink = rgb(match[1]);
          shadow = {color:ink.color,opacity:ink.opacity*opacity,x:Number(match[2])*scale,y:Number(match[3])*scale,blur:Number(match[4])*scale};
        }
        if (node === slide && fill.opacity) page.background = fill.color;
        if (node !== slide && (fill.opacity || (uniform && borderWidth) || shadow)) {
          const b = box(rect);
          push({kind:'shape',...b,shape:radius?'roundRect':'rect',radius:Math.min(radius,b.w/2,b.h/2),
                fill:fill.opacity?fill.color:null,opacity:fill.opacity*opacity,
                border:uniform?border.color:null,borderWidth:uniform?borderWidth*scale:0,shadow});
        }
        if (!uniform) {
          for (const side of ['Top','Right','Bottom','Left']) {
            const thickness=parseFloat(style[`border${side}Width`]), ink=rgb(style[`border${side}Color`]);
            if (!thickness || !ink.opacity) continue;
            const b=box(rect), t=thickness*scale;
            if (side==='Top'||side==='Bottom') { if(side==='Bottom') b.y+=b.h-t; b.h=t; }
            else { if(side==='Right') b.x+=b.w-t; b.w=t; }
            push({kind:'shape',...b,shape:'rect',fill:ink.color,opacity:ink.opacity*opacity});
          }
        }
        if (node.tagName === 'IMG') {
          const match = node.src.match(/^data:(image\/(?:png|jpeg));base64,(.+)$/);
          if (!match || !node.naturalWidth) fail('이미지 로딩을 완료하지 못했습니다. 로컬 PNG/JPEG인지 확인해 주세요.');
          if (style.objectPosition !== '50% 50%') fail('그림 위치는 중앙 맞춤만 지원합니다.');
          push({kind:'image',...box(rect),image:{mime:match[1],data:match[2],alt:node.alt},fit:style.objectFit==='cover'?'cover':style.objectFit==='fill'?'stretch':'contain'});
          return;
        }
        if (node.tagName === 'TABLE') {
          const rows=[...node.rows].map(r=>[...r.cells]);
          if (!rows.length || rows.some(r=>r.length!==rows[0].length || r.some(c=>c.colSpan!==1 || c.rowSpan!==1))) fail('병합 표는 분리된 셀 또는 명시적 PPT 표로 작성해 주세요.');
          if (rows.some(r=>r.some(c=>c.querySelector('img,svg,table')))) fail('그림/중첩 표가 있는 셀은 별도 개체로 작성해 주세요.');
          push({kind:'table',...box(rect),table:{headers:rows[0].map(c=>c.innerText),rows:rows.slice(1).map(r=>r.map(c=>c.innerText))},
                columnWidths:rows[0].map(c=>c.getBoundingClientRect().width*scale),rowHeights:[...node.rows].map(r=>r.getBoundingClientRect().height*scale),size:parseFloat(style.fontSize)*scale});
          warning('HTML 표는 편집 가능한 PPT 표로 변환하며 셀 색상·테두리는 PPT 테마를 사용합니다.');
          return;
        }
        if (node.tagName === 'LI') warning('목록 기호는 텍스트에 직접 포함했는지 확인해 주세요.');
        const children=[...node.childNodes];
        if (children.some(n=>n.nodeType===1 && getComputedStyle(n).zIndex!=='auto')) fail('겹치는 z-index 배치는 DOM 순서의 단순 배치로 바꿔 주세요.');
        for (const child of children) {
          if(child.nodeType===Node.TEXT_NODE) text(child,style);
          else visit(child,opacity);
        }
      };
      visit(slide);
      if (!page.elements.length) fail('내용이 없는 HTML 장이 있습니다.');
    }
  };
  window.addEventListener('load', () => {
    try { capture(); } catch (error) { result.error=String(error.message).slice(0,300); }
    const output=document.createElement('pre'); output.id=options.outputId;
    output.textContent=JSON.stringify(result); document.body.append(output);
  }, {once:true});
})();
