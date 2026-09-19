// Commands now live in the unified offline reader, not a second interactive UI.
import fs from 'node:fs';
import assert from 'node:assert/strict';
const html=fs.readFileSync(new URL('../docs/Company-Agent-Guide.html',import.meta.url),'utf8');
const legacy=fs.readFileSync(new URL('../docs/Claude-Code-필수-사용법.html',import.meta.url),'utf8');
assert.ok(legacy.includes('Company-Agent-Guide.html#commands'));
for(const command of ['/context','/compact','/init','/skills','/company-agent:skills','/company-agent:learning','/company-agent:business-check'])assert.ok(html.includes(command),command);
for(const key of ['Ctrl+J','Ctrl+O','Ctrl+R','Shift+Tab','Alt+V'])assert.ok(html.includes(key),key);
assert.ok(html.includes('없는 명령을 억지로 실행'));
assert.ok(html.includes('매 작업 후 강제'));
assert.ok(html.includes("script-src 'none'"));
assert.doesNotMatch(html,/<(?:script|img|iframe)\b|<link\b|@import|\bfetch\(|XMLHttpRequest|localStorage|sessionStorage/i);
console.log('Unified command guide: commands, keys, limits and offline contract passed.');
