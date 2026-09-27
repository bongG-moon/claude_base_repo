'use strict';
// Local VM/DOM test double only. This file cannot start a browser or a server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const scenario = process.argv[2];

class Events {
  constructor() { this.listeners = new Map(); }
  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(listener);
  }
  async fire(name) { await Promise.all((this.listeners.get(name) || []).map(fn => fn({type: name}))); }
}
class Style {
  setProperty(name, value) { this[name] = value; }
  getPropertyValue(name) { return this[name] || ''; }
}
function matches(node, selector) {
  if (selector === '*') return true;
  const tag = selector.match(/^[a-z][a-z0-9-]*/i)?.[0];
  if (tag && node.tag !== tag) return false;
  for (const match of selector.matchAll(/\.([a-z0-9_-]+)/gi)) {
    if (!node.classList.contains(match[1])) return false;
  }
  for (const match of selector.matchAll(/\[([a-z0-9_-]+)(?:="([^"]*)")?\]/gi)) {
    if (!(match[1] in node.attrs) || (match[2] !== undefined && node.attrs[match[1]] !== match[2])) return false;
  }
  return true;
}
class Element extends Events {
  constructor(tag, env, attrs = {}, text = '') {
    super(); this.tag = tag; this.env = env; this.attrs = {...attrs}; this.children = [];
    this.parent = null; this.style = new Style(); this.ownText = text;
    this.hidden = 'hidden' in attrs; this.disabled = 'disabled' in attrs;
    this.dataset = Object.fromEntries(Object.entries(attrs).filter(([key]) => key.startsWith('data-'))
      .map(([key, value]) => [key.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()), value]));
    this.classList = {
      contains: value => (this.attrs.class || '').split(/\s+/).includes(value),
      toggle: (value, include) => {
        const classes = new Set((this.attrs.class || '').split(/\s+/).filter(Boolean));
        if (include) classes.add(value); else classes.delete(value);
        this.attrs.class = [...classes].join(' ');
      },
    };
  }
  get textContent() { return this.ownText + this.children.map(node => node.textContent).join(''); }
  set textContent(value) { this.ownText = String(value); this.children = []; }
  appendChild(node) { node.parent = this; this.children.push(node); return node; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this); this.parent = null; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] ?? null; }
  removeAttribute(name) { delete this.attrs[name]; }
  querySelectorAll(selector) {
    const parts = selector.split(/\s+/);
    const all = [];
    const visit = node => {
      for (const child of node.children) {
        if (matches(child, parts.at(-1))) {
          let ancestor = child.parent; let index = parts.length - 2;
          while (index >= 0 && ancestor) {
            if (matches(ancestor, parts[index])) index--;
            ancestor = ancestor.parent;
          }
          if (index < 0) all.push(child);
        }
        visit(child);
      }
    };
    visit(this); return all;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  cloneNode(deep) {
    const clone = new Element(this.tag, this.env, this.attrs, this.ownText);
    Object.assign(clone.style, this.style);
    if (deep) this.children.forEach(child => clone.appendChild(child.cloneNode(true)));
    return clone;
  }
  click() {
    if (this.disabled) return Promise.resolve();
    if (this.tag === 'a') {
      if (this.env.options.failClick) throw new Error('simulated download rejection');
      this.env.downloads.push({name: this.download, url: this.href});
      return;
    }
    return this.fire('click');
  }
}
function environment(options = {}) {
  const env = {options, timers: new Map(), serial: 0, downloads: [], urls: new Map(),
    revoked: [], pictures: [], canvases: [], serialized: [], networkCalls: 0};
  const build = raw => {
    const element = new Element(raw.tag, env, raw.attrs, raw.text || '');
    raw.children.forEach(child => element.appendChild(build(child)));
    return element;
  };
  const document = new Events(); document.body = build(payload.tree); document.hidden = false;
  document.querySelectorAll = selector => document.body.querySelectorAll(selector);
  document.getElementById = id => document.body.querySelectorAll('*').find(node => node.attrs.id === id) || null;
  document.createElement = tag => {
    const element = new Element(tag, env);
    if (tag === 'canvas') {
      env.canvases.push(element);
      element.draws = [];
      element.getContext = () => options.noCanvas ? null : {
        fillRect: (...args) => element.draws.push(['background', ...args]),
        drawImage: (...args) => element.draws.push(['image', ...args]),
      };
      element.toBlob = callback => {
        if (options.throwBlob) throw new Error('simulated canvas export failure');
        callback(options.nullBlob ? null : new Blob(['PNG'], {type: 'image/png'}));
      };
    }
    return element;
  };
  const window = new Events();
  window.setTimeout = (callback, delay) => { const id = ++env.serial; env.timers.set(id, {callback, delay}); return id; };
  window.clearTimeout = id => env.timers.delete(id);
  const media = new Events(); media.matches = !!options.reduced; window.matchMedia = () => media;
  window.getComputedStyle = node => ({getPropertyValue: name => {
    if (name === 'fill') return node.parent?.classList.contains('is-highlighted') ? '#dbeafe' : '#fff';
    return ({stroke: '#64748b', 'stroke-width': '2', 'font-family': 'system-ui', 'font-size': '18px',
      'font-weight': '400', 'text-anchor': 'start'})[name] || '';
  }});
  class Picture {
    constructor() { env.pictures.push(this); this.onload = null; this.onerror = null; }
    set src(value) {
      this.source = value; assert.ok(value.startsWith('data:image/svg+xml;'), 'PNG must use an inline local SVG');
      if (options.imageMode === 'manual' || options.imageMode === 'timeout') return;
      queueMicrotask(() => options.imageMode === 'error' ? this.onerror?.() : this.onload?.());
    }
  }
  const URL = {
    createObjectURL: blob => {
      if (options.failURL) throw new Error('simulated URL failure');
      const url = 'blob:test-' + (++env.serial); env.urls.set(url, blob); return url;
    },
    revokeObjectURL: url => { assert.ok(env.urls.has(url), 'revoke only allocated URLs'); env.urls.delete(url); env.revoked.push(url); },
  };
  if (options.noURL) delete URL.createObjectURL;
  const serialize = node => {
    const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;');
    const attrs = {...node.attrs};
    if (Object.keys(node.style).length) attrs.style = Object.entries(node.style).map(([name, value]) => `${name}:${value}`).join(';');
    return `<${node.tag}${Object.entries(attrs).map(([name, value]) => ` ${name}="${escape(value ?? '')}"`).join('')}>`
      + escape(node.ownText) + node.children.map(serialize).join('') + `</${node.tag}>`;
  };
  class Serializer {
    serializeToString(node) {
      if (options.failSerialize) throw new Error('simulated serialization failure');
      env.serialized.push(node); return serialize(node);
    }
  }
  const context = vm.createContext({window, document, Blob, URL, Image: Picture,
    XMLSerializer: options.noSerializer ? undefined : Serializer,
    fetch: () => { env.networkCalls++; throw new Error('network forbidden'); }});
  Object.assign(env, {window, document, media});
  env.figure = index => document.getElementById('explanation-' + index);
  env.panel = index => document.querySelectorAll('.diagram-export')[index];
  env.button = (index, action) => env.figure(index).querySelector(`button[data-diagram-action="${action}"]`);
  env.exportButton = (index, format) => env.panel(index).querySelector(`button[data-export-format="${format}"]`);
  env.highlighted = index => env.figure(index).querySelectorAll('.diagram-node')
    .filter(node => node.classList.contains('is-highlighted')).map(node => node.dataset.nodeId);
  env.tick = delay => {
    const found = [...env.timers].find(([, entry]) => entry.delay === delay);
    assert.ok(found, `Expected a ${delay}ms timer`);
    env.timers.delete(found[0]); found[1].callback();
  };
  env.load = () => {
    vm.runInContext(payload.engine, context, {timeout: 1000});
    vm.runInContext(payload.exporter, context, {timeout: 1000});
  };
  if (options.missingSource) env.figure(0).querySelector('.explanation-svg').remove();
  env.load(); return env;
}
function noDownload(env) { assert.equal(env.downloads.length, 0); assert.equal(env.urls.size, 0); }
function enabledExports(env) { env.panel(0).querySelectorAll('button').forEach(button => assert.equal(button.disabled, false)); }
function failureVisible(env) {
  assert.match(env.panel(0).querySelector('.diagram-export-status').textContent, /완료하지 못했습니다/);
  assert.equal(env.figure(0).querySelectorAll('.diagram-node').length, 3); enabledExports(env); noDownload(env);
}
function sameEvidence(env, original) {
  assert.equal(env.figure(0).querySelector('.diagram-details').textContent, original);
  assert.equal(env.figure(0).querySelectorAll('.diagram-node').length, 3);
}
async function run() {
  if (scenario === 'initial') {
    const env = environment(); noDownload(env); assert.equal(env.timers.size, 0); assert.equal(env.pictures.length, 0);
    assert.deepEqual(env.highlighted(0), []); assert.equal(env.figure(2).querySelector('.diagram-motion'), null);
    assert.equal(env.figure(0).querySelector('.diagram-motion').hidden, false);
    assert.equal(env.panel(0).hidden, false); assert.equal(env.networkCalls, 0);
  } else if (scenario === 'playback') {
    const env = environment(); await env.button(0, 'play').click(); assert.deepEqual(env.highlighted(0), ['a']);
    assert.equal(env.timers.size, 1); await env.button(0, 'play').fire('click'); assert.equal(env.timers.size, 1);
    await env.button(1, 'play').click(); assert.equal(env.timers.size, 1); assert.equal(env.button(0, 'pause').disabled, true);
    env.tick(1600); assert.deepEqual(env.highlighted(1), ['b']); assert.equal(env.timers.size, 1);
    env.tick(1600); assert.deepEqual(env.highlighted(1), ['c']); assert.equal(env.timers.size, 0);
    assert.equal(env.button(1, 'step').disabled, true); assert.equal(env.button(1, 'play').disabled, false);
    assert.match(env.figure(1).querySelector('.diagram-playback-status').textContent, /설명 완료/); noDownload(env);
  } else if (scenario === 'manual') {
    const env = environment(); const evidence = env.figure(0).querySelector('.diagram-details').textContent;
    await env.button(0, 'step').click(); assert.deepEqual(env.highlighted(0), ['a']); assert.equal(env.timers.size, 0);
    await env.button(0, 'play').click(); assert.deepEqual(env.highlighted(0), ['b']); assert.equal(env.timers.size, 1);
    await env.button(0, 'pause').click(); assert.equal(env.timers.size, 0); assert.deepEqual(env.highlighted(0), ['b']);
    await env.button(0, 'reset').click(); assert.deepEqual(env.highlighted(0), []); assert.equal(env.timers.size, 0);
    for (let step = 0; step < 5; step++) await env.button(0, 'step').click();
    assert.deepEqual(env.highlighted(0), ['c']); assert.equal(env.timers.size, 0);
    await env.button(0, 'play').click(); assert.deepEqual(env.highlighted(0), ['a']);
    sameEvidence(env, evidence); noDownload(env);
  } else if (scenario === 'lifecycle') {
    const reduced = environment({reduced: true}); assert.equal(reduced.figure(0).querySelector('.diagram-motion').hidden, true);
    await reduced.button(0, 'play').click(); await reduced.button(0, 'step').click(); assert.equal(reduced.timers.size, 0);
    assert.deepEqual(reduced.highlighted(0), []);
    const env = environment();
    await env.button(0, 'play').click(); env.document.hidden = true; await env.document.fire('visibilitychange');
    assert.equal(env.timers.size, 0); env.document.hidden = false;
    await env.button(0, 'play').click(); await env.window.fire('beforeprint');
    assert.equal(env.timers.size, 0); assert.deepEqual(env.highlighted(0), []);
    await env.button(0, 'play').click(); await env.window.fire('pagehide'); assert.equal(env.timers.size, 0);
    await env.button(0, 'reset').click(); await env.button(0, 'play').click(); env.media.matches = true; await env.media.fire('change');
    assert.equal(env.timers.size, 0); assert.deepEqual(env.highlighted(0), []);
    assert.equal(env.figure(0).querySelector('.diagram-motion').hidden, true);
    env.media.matches = false; await env.media.fire('change'); assert.equal(env.timers.size, 0);
    assert.equal(env.figure(0).querySelector('.diagram-motion').hidden, false); noDownload(env);
  } else if (scenario === 'svg') {
    const env = environment(); await env.button(0, 'step').click(); noDownload(env);
    const evidence = env.figure(0).querySelector('.diagram-details').textContent;
    await env.exportButton(0, 'svg').click(); assert.equal(env.downloads.length, 1);
    assert.equal(env.downloads[0].name, 'explanation-0.svg');
    assert.match(env.urls.get(env.downloads[0].url).type, /^image\/svg\+xml/);
    const clone = env.serialized[0]; assert.equal(clone.getAttribute('xmlns'), 'http://www.w3.org/2000/svg');
    clone.querySelectorAll('g[data-node-id] rect').forEach(rect => { assert.equal(rect.style.fill, '#fff'); assert.equal(rect.style.stroke, '#64748b'); });
    assert.ok(clone.querySelectorAll('*').every(node => node.getAttribute('class') === null));
    assert.deepEqual(env.highlighted(0), ['a']); sameEvidence(env, evidence); enabledExports(env);
    assert.equal(env.document.querySelectorAll('a').length, 0); env.tick(1000);
    assert.equal(env.urls.size, 0); assert.equal(env.revoked.length, 1); assert.equal(env.timers.size, 0);
  } else if (scenario === 'png') {
    const env = environment({imageMode: 'manual'}); const svg = env.figure(0).querySelector('.explanation-svg');
    svg.setAttribute('width', '9000'); svg.setAttribute('height', '6000');
    const pending = env.exportButton(0, 'png').click(); assert.equal(env.pictures.length, 1);
    env.panel(0).querySelectorAll('button').forEach(button => assert.equal(button.disabled, true));
    await env.exportButton(0, 'svg').fire('click'); assert.equal(env.serialized.length, 1); noDownload(env);
    env.pictures[0].onload(); await pending; assert.equal(env.downloads.length, 1);
    assert.equal(env.downloads[0].name, 'explanation-0.png'); assert.equal(env.urls.get(env.downloads[0].url).type, 'image/png');
    const canvas = env.canvases[0]; assert.ok(canvas.width <= 4096 && canvas.height <= 4096);
    assert.ok(canvas.width * canvas.height <= 12000000 + 8192); assert.equal(canvas.draws.length, 2);
    assert.equal([...env.timers.values()].filter(timer => timer.delay === 8000).length, 0); enabledExports(env);
    env.tick(1000); assert.equal(env.urls.size, 0); assert.equal(env.timers.size, 0); assert.equal(env.document.querySelectorAll('a').length, 0);
  } else if (scenario === 'export-failures') {
    for (const options of [{noCanvas: true}, {nullBlob: true}, {throwBlob: true}, {imageMode: 'error'}, {failURL: true}, {failSerialize: true}]) {
      const env = environment(options); await env.exportButton(0, 'png').click(); failureVisible(env);
      assert.equal(env.timers.size, 0); assert.equal(env.document.querySelectorAll('a').length, 0);
    }
    const env = environment(); env.figure(0).querySelector('.explanation-svg').setAttribute('width', '0');
    await env.exportButton(0, 'png').click(); failureVisible(env); assert.equal(env.pictures.length, 0);
  } else if (scenario === 'cleanup-failures') {
    const timeout = environment({imageMode: 'timeout'}); const pending = timeout.exportButton(0, 'png').click();
    timeout.tick(8000); await pending; failureVisible(timeout); assert.equal(timeout.timers.size, 0);
    assert.equal(timeout.pictures[0].onload, null); assert.equal(timeout.pictures[0].onerror, null);
    for (const format of ['svg', 'png']) {
      const env = environment({failClick: true}); await env.exportButton(0, format).click();
      assert.match(env.panel(0).querySelector('.diagram-export-status').textContent, /완료하지 못했습니다/);
      enabledExports(env); assert.equal(env.downloads.length, 0);
      assert.equal(env.document.querySelectorAll('a').length, 0, 'failed download must remove temporary anchor');
      while ([...env.timers.values()].some(timer => timer.delay === 1000)) env.tick(1000);
      assert.equal(env.urls.size, 0, 'failed download must release its object URL');
    }
  } else if (scenario === 'unsupported') {
    for (const options of [{noSerializer: true}, {noURL: true}, {missingSource: true}]) {
      const env = environment(options); assert.equal(env.panel(0).hidden, true);
      await env.exportButton(0, 'svg').click(); noDownload(env); assert.equal(env.timers.size, 0);
    }
  } else throw new Error('Unknown scenario ' + scenario);
}
run().then(() => process.stdout.write(JSON.stringify({ok: true, case: scenario}))).catch(error => {
  process.stderr.write(error.stack + '\n'); process.exitCode = 1;
});
