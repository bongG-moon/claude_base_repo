/* Standalone HTML deck editor. Original implementation; no runtime dependencies. */
(() => {
  'use strict';
  function initialize() {
    const deck = document.querySelector('main#deck');
    if (!deck || window.htmlDeck) return;
    const slides = () => Array.from(deck.children).filter(node => node.matches('section.slide'));
    if (!slides().length) return;
    let index = 0, editing = false, selectedText = null, selectedObject = null;
    let scale = 1, history = [], historyIndex = -1, inputTimer = null, drag = null;
    let savedHTML = '', sequence = 0;
    const uid = () => `hd-copy-${Date.now().toString(36)}-${++sequence}`;
    slides().forEach((slide, i) => { if (!slide.id) slide.id = `slide-${i + 1}`; });
    const create = (tag, className, text) => {
      const element = document.createElement(tag);
      if (className) element.className = className;
      if (text !== undefined) element.textContent = text;
      return element;
    };
    const button = (text, action, title) => {
      const element = create('button', 'hd-button', text);
      element.type = 'button'; element.dataset.hdAction = action;
      if (title) element.title = title;
      return element;
    };
    const root = create('div', 'hd-ui'); root.id = 'hd-editor'; root.dataset.hdUi = '';
    const toolbar = create('header', 'hd-toolbar'); toolbar.setAttribute('aria-label', '발표와 편집 도구');
    const nav = create('div', 'hd-row');
    nav.append(button('이전', 'previous', '이전 슬라이드'), button('다음', 'next', '다음 슬라이드'));
    const counter = create('output', 'hd-counter'); counter.setAttribute('aria-live', 'polite'); nav.append(counter);
    nav.append(button('전체 장표', 'overview'), button('메모', 'notes'), button('편집', 'edit'));
    const editButton = nav.querySelector('[data-hd-action="edit"]'); editButton.setAttribute('aria-pressed', 'false');
    nav.append(button('수정본 HTML 저장', 'save'), button('인쇄', 'print'), button('전체화면', 'fullscreen'));
    toolbar.append(nav);
    const editTools = create('div', 'hd-row hd-edit-tools'); editTools.hidden = true;
    const controls = {};
    const field = (label, control) => {
      const wrapper = create('label', 'hd-field'); wrapper.append(create('span', '', label), control);
      editTools.append(wrapper); return control;
    };
    controls.font = create('input', 'hd-input'); controls.font.type = 'text'; controls.font.placeholder = '기존 글꼴 유지';
    controls.font.setAttribute('aria-label', '선택 텍스트 글꼴');
    controls.font.setAttribute('list', 'hd-font-list'); field('글꼴', controls.font);
    const fontList = create('datalist'); fontList.id = 'hd-font-list';
    ['Pretendard', '맑은 고딕', 'Noto Sans KR', 'Arial', 'Georgia', 'sans-serif', 'serif'].forEach(value => {
      const option = create('option'); option.value = value; fontList.append(option);
    }); root.append(fontList);
    controls.size = create('input', 'hd-input hd-size'); controls.size.type = 'number'; controls.size.min = '6'; controls.size.max = '300'; controls.size.step = '1';
    controls.size.setAttribute('aria-label', '선택 텍스트 크기'); field('크기 px', controls.size);
    controls.bold = button('굵게', 'bold'); controls.bold.setAttribute('aria-pressed', 'false'); editTools.append(controls.bold);
    controls.color = create('input', 'hd-color'); controls.color.type = 'color'; controls.color.setAttribute('aria-label', '선택 텍스트 색'); field('색', controls.color);
    controls.align = create('select', 'hd-input'); controls.align.setAttribute('aria-label', '선택 텍스트 정렬');
    [['start', '기본'], ['left', '왼쪽'], ['center', '가운데'], ['right', '오른쪽'], ['justify', '양쪽']].forEach(([value, text]) => {
      const option = create('option', '', text); option.value = value; controls.align.append(option);
    }); field('정렬', controls.align);
    editTools.append(button('실행 취소', 'undo'), button('다시 실행', 'redo'), button('순서 앞', 'move-before'), button('순서 뒤', 'move-after'), button('복제', 'duplicate'), button('삭제', 'delete'));
    toolbar.append(editTools); root.append(toolbar);
    const statusBar = create('footer', 'hd-status');
    const status = create('span', '', '편집을 켜면 텍스트와 블록을 선택할 수 있습니다.'); status.setAttribute('role', 'status');
    const dirty = create('span', 'hd-dirty', '저장된 상태'); statusBar.append(status, dirty); root.append(statusBar);
    const viewport = create('div', 'hd-viewport'); viewport.id = 'hd-viewport';
    const canvas = create('div', 'hd-canvas'); canvas.id = 'hd-canvas';
    deck.replaceWith(viewport); viewport.append(canvas); canvas.append(deck);
    const outline = create('div', 'hd-selection'); outline.hidden = true; outline.dataset.hdUi = '';
    const moveHandle = button('이동', 'drag'); moveHandle.classList.add('hd-move-handle'); moveHandle.setAttribute('aria-label', '선택 블록 이동: 드래그 또는 방향키');
    const resizeHandle = button('↘', 'resize'); resizeHandle.classList.add('hd-resize-handle'); resizeHandle.setAttribute('aria-label', '선택 블록 크기 조절: 드래그 또는 방향키');
    outline.append(moveHandle, resizeHandle); canvas.append(outline);
    const overview = create('dialog', 'hd-dialog hd-overview'); overview.setAttribute('aria-label', '전체 장표');
    const overviewTop = create('div', 'hd-dialog-heading'); overviewTop.append(create('h2', '', '전체 장표'), button('닫기', 'close-overview'));
    const thumbnails = create('div', 'hd-thumbnails'); overview.append(overviewTop, thumbnails); root.append(overview);
    const notes = create('dialog', 'hd-dialog hd-notes'); notes.setAttribute('aria-label', '발표 메모');
    const notesTop = create('div', 'hd-dialog-heading'); notesTop.append(create('h2', '', '발표 메모'), button('닫기', 'close-notes'));
    const noteContent = create('div', 'hd-note-content'); notes.append(notesTop, noteContent); root.append(notes);
    document.body.append(root); document.body.classList.add('hd-ready');

    function message(text) { status.textContent = text; }
    function clearEmptyClass(node) { if (!node.className) node.removeAttribute('class'); }
    function cleanDeck(node) {
      Array.from(node.children).forEach(slide => {
        slide.classList.remove('hd-current', 'hd-hidden'); clearEmptyClass(slide);
      });
      node.querySelectorAll('[data-hd-editable]').forEach(element => {
        const previous = JSON.parse(element.getAttribute('data-hd-editable'));
        if (previous === null) element.removeAttribute('contenteditable');
        else element.setAttribute('contenteditable', previous);
        element.removeAttribute('data-hd-editable');
      });
      return node;
    }
    function snapshot() { return cleanDeck(deck.cloneNode(true)).innerHTML; }
    function record() {
      clearTimeout(inputTimer); inputTimer = null;
      const html = snapshot();
      if (history[historyIndex]?.html !== html) {
        history = history.slice(0, historyIndex + 1);
        history.push({ html, index });
        if (history.length > 80) history.shift();
        historyIndex = history.length - 1;
      }
      updateControls();
    }
    function updateControls() {
      const all = slides(); counter.value = `${index + 1} / ${all.length}`; counter.textContent = counter.value;
      root.querySelector('[data-hd-action="previous"]').disabled = index === 0;
      root.querySelector('[data-hd-action="next"]').disabled = index === all.length - 1;
      root.querySelector('[data-hd-action="move-before"]').disabled = index === 0;
      root.querySelector('[data-hd-action="move-after"]').disabled = index === all.length - 1;
      root.querySelector('[data-hd-action="delete"]').disabled = all.length < 2;
      root.querySelector('[data-hd-action="undo"]').disabled = historyIndex <= 0;
      root.querySelector('[data-hd-action="redo"]').disabled = historyIndex >= history.length - 1;
      Object.values(controls).forEach(control => { control.disabled = !selectedText; });
      dirty.textContent = snapshot() === savedHTML ? '저장된 상태' : '저장하지 않은 변경';
    }
    function size() {
      const style = getComputedStyle(document.documentElement);
      return { width: parseFloat(style.getPropertyValue('--slide-width')) || 1280, height: parseFloat(style.getPropertyValue('--slide-height')) || 720 };
    }
    function fit() {
      document.documentElement.style.setProperty('--hd-toolbar-height', `${toolbar.getBoundingClientRect().height}px`);
      const { width, height } = size();
      scale = Math.max(0.05, Math.min((viewport.clientWidth - 24) / width, (viewport.clientHeight - 24) / height));
      canvas.style.width = `${width}px`; canvas.style.height = `${height}px`;
      canvas.style.transform = `scale(${scale})`;
      canvas.style.left = `${Math.max(0, (viewport.clientWidth - width * scale) / 2)}px`;
      canvas.style.top = `${Math.max(0, (viewport.clientHeight - height * scale) / 2)}px`;
      canvas.style.setProperty('--hd-inverse-scale', String(1 / scale));
      updateOutline();
    }
    function updateOutline() {
      if (!editing || !selectedObject || !selectedObject.isConnected) { outline.hidden = true; return; }
      const box = selectedObject.getBoundingClientRect(), base = canvas.getBoundingClientRect();
      Object.assign(outline.style, { left: `${(box.left - base.left) / scale}px`, top: `${(box.top - base.top) / scale}px`, width: `${box.width / scale}px`, height: `${box.height / scale}px` });
      outline.hidden = false;
    }
    function setEditable() {
      deck.querySelectorAll('[data-edit]').forEach(element => {
        if (editing) {
          if (!element.hasAttribute('data-hd-editable')) element.setAttribute('data-hd-editable', JSON.stringify(element.getAttribute('contenteditable')));
          element.setAttribute('contenteditable', 'plaintext-only');
        } else if (element.hasAttribute('data-hd-editable')) {
          const original = JSON.parse(element.getAttribute('data-hd-editable'));
          if (original === null) element.removeAttribute('contenteditable'); else element.setAttribute('contenteditable', original);
          element.removeAttribute('data-hd-editable');
        }
      });
    }
    function deselect() { selectedText = null; selectedObject = null; outline.hidden = true; }
    function show(next) {
      record();
      const all = slides(); index = Math.max(0, Math.min(all.length - 1, Number(next) || 0));
      all.forEach((slide, i) => { slide.classList.toggle('hd-current', i === index); slide.classList.toggle('hd-hidden', i !== index); });
      deselect(); setEditable(); updateControls(); fit();
      if (notes.open) updateNotes();
      return index;
    }
    function select(target) {
      selectedText = target.closest('[data-edit]'); selectedObject = target.closest('[data-object]');
      if (selectedText && !slides()[index].contains(selectedText)) selectedText = null;
      if (selectedObject && !slides()[index].contains(selectedObject)) selectedObject = null;
      if (selectedText) {
        const style = getComputedStyle(selectedText);
        controls.font.value = style.fontFamily; controls.size.value = String(Math.round(parseFloat(style.fontSize) * 10) / 10);
        controls.bold.setAttribute('aria-pressed', String(style.fontWeight === 'bold' || Number(style.fontWeight) >= 600));
        const rgb = style.color.match(/\d+(?:\.\d+)?/g);
        if (rgb?.length >= 3) controls.color.value = `#${rgb.slice(0, 3).map(n => Math.round(Number(n)).toString(16).padStart(2, '0')).join('')}`;
        controls.align.value = ['left', 'center', 'right', 'justify'].includes(style.textAlign) ? style.textAlign : 'start';
      }
      updateControls(); updateOutline();
      message(selectedObject ? '텍스트를 입력하거나 이동 / 모서리 핸들을 사용하세요.' : selectedText ? '선택한 텍스트 요소에 서식을 적용합니다.' : '편집할 텍스트 또는 블록을 선택하세요.');
    }
    function format(property, value) {
      if (!selectedText || !editing) return;
      record(); selectedText.style[property] = value; record(); updateOutline();
    }
    controls.font.addEventListener('change', () => { if (controls.font.value.trim()) format('fontFamily', controls.font.value.trim()); });
    controls.size.addEventListener('change', () => { const value = Number(controls.size.value); if (value >= 6 && value <= 300) format('fontSize', `${value}px`); });
    controls.color.addEventListener('change', () => format('color', controls.color.value));
    controls.align.addEventListener('change', () => format('textAlign', controls.align.value));
    function restore(direction) {
      record(); const next = historyIndex + direction;
      if (next < 0 || next >= history.length) return;
      historyIndex = next;
      // Only a prior local DOM snapshot is restored; user text is never parsed as HTML.
      deck.innerHTML = history[next].html;
      index = Math.min(history[next].index, slides().length - 1);
      deselect(); setEditable();
      slides().forEach((slide, i) => { slide.classList.toggle('hd-current', i === index); slide.classList.toggle('hd-hidden', i !== index); });
      updateControls(); fit(); message(direction < 0 ? '실행을 취소했습니다.' : '다시 실행했습니다.');
    }
    function duplicate() {
      record(); const current = slides()[index], clone = cleanDeck(deck.cloneNode(false));
      clone.append(current.cloneNode(true)); cleanDeck(clone);
      const copy = clone.firstElementChild, suffix = uid(), ids = new Map();
      [copy, ...copy.querySelectorAll('[id]')].forEach(node => { if (node.id) { ids.set(node.id, `${node.id}-${suffix}`); node.id = ids.get(node.id); } });
      [copy, ...copy.querySelectorAll('*')].forEach(node => {
        ['href', 'xlink:href', 'fill', 'stroke', 'filter', 'clip-path', 'mask', 'style', 'aria-labelledby', 'aria-describedby', 'for'].forEach(attribute => {
          let value = node.getAttribute(attribute); if (value === null) return;
          ids.forEach((replacement, id) => {
            value = value.replaceAll(`url(#${id})`, `url(#${replacement})`);
            if (value === `#${id}`) value = `#${replacement}`;
            if (['for', 'aria-labelledby', 'aria-describedby'].includes(attribute)) value = value.split(/\s+/).map(part => part === id ? replacement : part).join(' ');
          }); node.setAttribute(attribute, value);
        });
      });
      current.after(copy); index += 1; record(); show(index); message('현재 슬라이드를 복제했습니다.');
    }
    function reorder(direction) {
      record(); const all = slides(), target = index + direction;
      if (target < 0 || target >= all.length) return;
      if (direction < 0) all[target].before(all[index]); else all[target].after(all[index]);
      index = target; record(); show(index);
    }
    function removeSlide() {
      if (slides().length < 2) { message('마지막 슬라이드는 삭제할 수 없습니다.'); return; }
      record(); slides()[index].remove(); index = Math.min(index, slides().length - 1); record(); show(index); message('슬라이드를 삭제했습니다. 실행 취소로 복구할 수 있습니다.');
    }
    function updateNotes() {
      const slide = slides()[index], element = slide.querySelector('aside.notes, .speaker-notes, [data-notes]');
      noteContent.textContent = element?.textContent.trim() || slide.getAttribute('data-notes') || '이 슬라이드에는 발표 메모가 없습니다.';
    }
    function openOverview() {
      thumbnails.replaceChildren();
      slides().forEach((slide, i) => {
        const item = button('', 'choose-slide'); item.dataset.hdIndex = String(i); item.classList.add('hd-thumbnail');
        if (i === index) item.setAttribute('aria-current', 'true');
        const title = slide.querySelector('h1,h2,h3,[data-edit]')?.textContent.trim() || slide.getAttribute('aria-label') || '슬라이드';
        item.append(create('span', 'hd-thumbnail-number', String(i + 1)), create('span', 'hd-thumbnail-title', title));
        const excerpt = Array.from(slide.querySelectorAll('[data-edit]')).slice(1, 4).map(node => node.textContent.trim()).join(' / ');
        if (excerpt) item.append(create('span', 'hd-thumbnail-excerpt', excerpt));
        thumbnails.append(item);
      });
      overview.showModal();
    }
    function exportHTML() {
      record(); const copy = document.documentElement.cloneNode(true), copyDeck = copy.querySelector('main#deck');
      cleanDeck(copyDeck);
      copy.querySelector('#hd-viewport').replaceWith(copyDeck);
      copy.querySelectorAll('[data-hd-ui]').forEach(element => element.remove());
      copy.querySelector('body').classList.remove('hd-ready', 'hd-editing'); clearEmptyClass(copy.querySelector('body'));
      copy.style.removeProperty('--hd-toolbar-height'); if (!copy.getAttribute('style')) copy.removeAttribute('style');
      return '<!DOCTYPE html>\n' + copy.outerHTML;
    }
    function save() {
      const html = exportHTML(), filename = `${(document.title || '발표본').replace(/[\\/:*?"<>|]/g, '_')}-수정본.html`;
      const blob = new Blob([html], { type: 'text/html;charset=utf-8' }), url = URL.createObjectURL(blob);
      const link = create('a'); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      savedHTML = snapshot(); updateControls(); message('수정본 HTML 다운로드를 시작했습니다. 새 파일을 열면 편집을 이어갈 수 있습니다.');
      return { html, filename };
    }
    function action(name, target) {
      if (name === 'previous') show(index - 1);
      else if (name === 'next') show(index + 1);
      else if (name === 'edit') {
        record(); editing = !editing; document.body.classList.toggle('hd-editing', editing);
        editButton.setAttribute('aria-pressed', String(editing)); editButton.textContent = editing ? '편집 마침' : '편집';
        editTools.hidden = !editing; deselect(); setEditable(); updateControls(); fit();
        message(editing ? '텍스트를 선택해 입력하거나, 블록을 선택해 이동 / 크기를 바꾸세요.' : '발표 모드입니다. 변경 사항은 수정본 HTML 저장으로 보관하세요.');
      } else if (name === 'save') save();
      else if (name === 'overview') openOverview();
      else if (name === 'close-overview') overview.close();
      else if (name === 'choose-slide') { overview.close(); show(Number(target.dataset.hdIndex)); }
      else if (name === 'notes') { updateNotes(); notes.showModal(); }
      else if (name === 'close-notes') notes.close();
      else if (name === 'print') window.print();
      else if (name === 'fullscreen') {
        const promise = document.fullscreenElement ? document.exitFullscreen?.() : document.documentElement.requestFullscreen?.();
        promise?.catch(() => message('이 브라우저에서는 전체화면을 시작할 수 없습니다.'));
      } else if (editing) {
        if (name === 'bold' && selectedText) { const next = controls.bold.getAttribute('aria-pressed') !== 'true'; format('fontWeight', next ? '700' : '400'); controls.bold.setAttribute('aria-pressed', String(next)); }
        else if (name === 'undo') restore(-1);
        else if (name === 'redo') restore(1);
        else if (name === 'duplicate') duplicate();
        else if (name === 'delete') removeSlide();
        else if (name === 'move-before') reorder(-1);
        else if (name === 'move-after') reorder(1);
      }
    }
    root.addEventListener('click', event => { const target = event.target.closest('[data-hd-action]'); if (target && !target.disabled) action(target.dataset.hdAction, target); });
    deck.addEventListener('click', event => {
      if (!editing) return;
      if (event.target.closest('a')) event.preventDefault();
      select(event.target);
    });
    deck.addEventListener('focusin', event => { if (editing && event.target.closest('[data-edit]')) select(event.target); });
    deck.addEventListener('input', event => {
      if (!editing || !event.target.closest('[data-edit]')) return;
      clearTimeout(inputTimer); inputTimer = setTimeout(record, 350); updateOutline(); dirty.textContent = '저장하지 않은 변경';
    });
    deck.addEventListener('focusout', () => { if (editing) record(); });
    function insertPlainText(text, target) {
      const selection = window.getSelection();
      if (!selection?.rangeCount || !target.contains(selection.anchorNode)) return;
      const range = selection.getRangeAt(0); range.deleteContents();
      const fragment = document.createDocumentFragment();
      text.replace(/\r\n?/g, '\n').split('\n').forEach((line, i) => { if (i) fragment.append(document.createElement('br')); fragment.append(document.createTextNode(line)); });
      const last = fragment.lastChild; range.insertNode(fragment);
      if (last) { range.setStartAfter(last); range.collapse(true); selection.removeAllRanges(); selection.addRange(range); }
      record(); updateOutline();
    }
    deck.addEventListener('paste', event => {
      const target = event.target.closest('[data-edit]'); if (!editing || !target) return;
      event.preventDefault(); record(); insertPlainText(event.clipboardData?.getData('text/plain') || '', target);
    });
    deck.addEventListener('drop', event => { if (editing && event.target.closest('[data-edit]')) { event.preventDefault(); message('외부 서식이나 파일은 삽입하지 않습니다. 텍스트를 붙여 넣으세요.'); } });
    function translation(node) {
      const value = getComputedStyle(node).translate;
      if (!value || value === 'none') return [0, 0];
      const parts = value.split(/\s+/);
      return [0, 1].map(i => (parseFloat(parts[i]) || 0) * (parts[i]?.endsWith('%') ? (i ? node.offsetHeight : node.offsetWidth) / 100 : 1));
    }
    function inverseLinearTransform(node) {
      // Pointer deltas must pass through every author transform as well as the editor scale.
      let matrix = new DOMMatrix();
      for (let element = node; element; element = element.parentElement) {
        const style = getComputedStyle(element);
        let local = new DOMMatrix(style.transform === 'none' ? undefined : style.transform);
        const scales = style.scale?.split(/\s+/).map(Number);
        if (scales?.length && scales.every(Number.isFinite)) local = new DOMMatrix().scale(scales[0], scales[1] ?? scales[0]).multiply(local);
        if (style.rotate && style.rotate !== 'none' && /^-?[\d.]+(?:deg|rad|grad|turn)$/.test(style.rotate)) {
          let angle = parseFloat(style.rotate);
          if (style.rotate.endsWith('rad') && !style.rotate.endsWith('grad')) angle *= 180 / Math.PI;
          else if (style.rotate.endsWith('grad')) angle *= .9;
          else if (style.rotate.endsWith('turn')) angle *= 360;
          local = new DOMMatrix().rotate(angle).multiply(local);
        }
        matrix = local.multiply(matrix);
      }
      return new DOMMatrix([matrix.a, matrix.b, matrix.c, matrix.d, 0, 0]).inverse();
    }
    outline.addEventListener('pointerdown', event => {
      const handle = event.target.closest('[data-hd-action]');
      if (!editing || !selectedObject || !handle || event.button !== 0) return;
      event.preventDefault(); record();
      const computed = getComputedStyle(selectedObject);
      const mode = handle.dataset.hdAction;
      drag = { id: event.pointerId, node: selectedObject, mode, x: event.clientX, y: event.clientY, translate: translation(selectedObject), width: parseFloat(computed.width), height: parseFloat(computed.height), inverse: inverseLinearTransform(mode === 'drag' ? selectedObject.parentElement : selectedObject) };
      handle.setPointerCapture(event.pointerId);
    });
    outline.addEventListener('pointermove', event => {
      if (!drag || drag.id !== event.pointerId) return;
      const delta = drag.inverse.transformPoint(new DOMPoint(event.clientX - drag.x, event.clientY - drag.y));
      const x = delta.x, y = delta.y;
      if (drag.mode === 'drag') drag.node.style.translate = `${drag.translate[0] + x}px ${drag.translate[1] + y}px`;
      else { drag.node.style.width = `${Math.max(20, drag.width + x)}px`; drag.node.style.height = `${Math.max(20, drag.height + y)}px`; }
      updateOutline();
    });
    const endDrag = event => { if (drag?.id === event.pointerId) { drag = null; record(); } };
    outline.addEventListener('pointerup', endDrag); outline.addEventListener('pointercancel', endDrag);
    outline.addEventListener('keydown', event => {
      if (!selectedObject || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
      event.preventDefault(); event.stopPropagation(); record();
      const amount = event.shiftKey ? 10 : 1, dx = event.key === 'ArrowLeft' ? -amount : event.key === 'ArrowRight' ? amount : 0, dy = event.key === 'ArrowUp' ? -amount : event.key === 'ArrowDown' ? amount : 0;
      if (event.target === resizeHandle) { const style = getComputedStyle(selectedObject); selectedObject.style.width = `${Math.max(20, parseFloat(style.width) + dx)}px`; selectedObject.style.height = `${Math.max(20, parseFloat(style.height) + dy)}px`; }
      else { const [x, y] = translation(selectedObject); selectedObject.style.translate = `${x + dx}px ${y + dy}px`; }
      record(); updateOutline();
    });
    document.addEventListener('keydown', event => {
      if (overview.open || notes.open) return;
      const input = event.target.closest('input,textarea,select,[contenteditable="true"],[contenteditable="plaintext-only"]');
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); save(); return; }
      if (editing && (event.ctrlKey || event.metaKey) && !event.target.closest('input,textarea,select')) {
        if (event.key.toLowerCase() === 'z') { event.preventDefault(); restore(event.shiftKey ? 1 : -1); return; }
        if (event.key.toLowerCase() === 'y') { event.preventDefault(); restore(1); return; }
      }
      if (input || event.ctrlKey || event.metaKey || event.altKey || (event.key === ' ' && event.target.closest('button,a'))) return;
      if (['ArrowRight', 'PageDown', ' '].includes(event.key)) { event.preventDefault(); show(index + 1); }
      if (['ArrowLeft', 'PageUp'].includes(event.key)) { event.preventDefault(); show(index - 1); }
      if (event.key === 'Home') { event.preventDefault(); show(0); }
      if (event.key === 'End') { event.preventDefault(); show(slides().length - 1); }
    });
    window.addEventListener('resize', fit);
    if (window.ResizeObserver) new ResizeObserver(fit).observe(toolbar);
    document.fonts?.ready.then(fit);
    function checkLayout() {
      const slide = slides()[index], bounds = slide.getBoundingClientRect();
      return { slideId: slide.id, index, width: size().width, height: size().height, scope: 'current-slide', overflow: Array.from(slide.querySelectorAll('[data-object],[data-edit]')).filter(node => {
        const box = node.getBoundingClientRect(); return box.width && box.height && (box.left < bounds.left - 1 || box.top < bounds.top - 1 || box.right > bounds.right + 1 || box.bottom > bounds.bottom + 1 || node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1);
      }).map(node => ({ tag: node.tagName.toLowerCase(), id: node.id || null })) };
    }
    savedHTML = snapshot(); record(); show(0);
    window.htmlDeck = { show, get current() { return index; }, save, exportHTML, checkLayout };
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, { once: true }); else initialize();
})();
