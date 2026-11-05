// Measure actual text and surface colors, including the reference-style cascade.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve('.smoke/html-contrast-20261105');
// The reproducer is test data, never a personal path in the checked-in script.
const original = process.argv[2] || path.join(root, 'original.html');
const cases = [
  ['original', original],
  ['fixed', path.join(root, '개선-지표형.html')],
  ['dark', path.join(root, 'control-dark.html')],
  ['default', path.join(root, 'control-default.html')],
];
const channel = value => {const x=value/255; return x<=0.04045 ? x/12.92 : ((x+0.055)/1.055)**2.4};
const luminance = c => c.slice(0,3).reduce((sum,v,i)=>sum+channel(v)*[.2126,.7152,.0722][i],0);
const rgb = s => (s.match(/[\d.]+/g)||[]).map(Number);
const contrast = (a,b) => {a=luminance(rgb(a)); b=luminance(rgb(b)); return (Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_TEST_BROWSER});
 const casesOut=[];
 try {
  for (const [name,file] of cases) for (const width of [1440,390]) {
   const page=await browser.newPage({viewport:{width,height:900}});
   const errors=[];page.on('pageerror',e=>errors.push(String(e)));
   await page.setContent(fs.readFileSync(file,'utf8'));
   await page.evaluate(()=>document.fonts.ready);
   const data=await page.locator('.kpi').evaluateAll(cards=>cards.map(card=>({
    bg:getComputedStyle(card).backgroundColor,
    label:getComputedStyle(card.querySelector('.kpi-label')).color,
    note:card.querySelector('.kpi-note')?getComputedStyle(card.querySelector('.kpi-note')).color:null,
    value:getComputedStyle(card.querySelector('.kpi-value')).color,
   })));
   assert.ok(data.length>=4);
   const first=data[0]; const labelRatio=contrast(first.label,first.bg);
   const noteRatio=first.note?contrast(first.note,first.bg):null;
   if(name==='original') assert.ok(labelRatio<4.5,'original reproduces low contrast');
   else {
    for (const [i,card] of data.entries()) {
     assert.ok(contrast(card.label,card.bg)>=4.5,`${name} card ${i+1} label`);
     assert.ok(card.note===null||contrast(card.note,card.bg)>=4.5,`${name} card ${i+1} note`);
     assert.ok(contrast(card.value,card.bg)>=3,`${name} card ${i+1} value`);
    }
   }
   if(name==='default') assert.equal(first.bg,'rgb(32, 51, 79)','default dark lead retained');
   if(name==='dark') assert.equal(first.bg,'rgb(32, 51, 79)','observed dark surface retained');
   assert.deepEqual(errors,[]);
   if(name==='fixed')await page.screenshot({path:path.join(root,`fixed-${width}.png`)});
   casesOut.push({name,width,...first,labelRatio:+labelRatio.toFixed(3),noteRatio:noteRatio===null?null:+noteRatio.toFixed(3)});
   await page.close();
  }
  fs.writeFileSync(path.join(root,'browser-results.json'),JSON.stringify({pass:true,cases:casesOut},null,2));
  console.log(JSON.stringify({pass:true,cases:casesOut},null,2));
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
