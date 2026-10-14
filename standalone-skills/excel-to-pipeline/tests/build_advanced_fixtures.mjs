// Deterministic, synthetic workbooks. No user data and no executable VBA.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../../..');
const out = path.join(root, 'outputs/excel-macro-migration-test');
const fixtures = path.join(out, 'fixtures');
const previews = path.join(out, 'previews');
const python = process.env.FIXTURE_PYTHON || 'python';
await fs.mkdir(fixtures, { recursive: true });
await fs.mkdir(previews, { recursive: true });
const colors = { ink: '#24374B', header: '#314E72', pale: '#EDF2F8', warning: '#FFF0D6' };
const departments = ['개발', '생산', '품질', '기획', '영업', '지원'];
const employeeRows = Array.from({ length: 160 }, (_, i) => [String(i + 1).padStart(6, '0'), `가상사원${i + 1}`, departments[i % 6], ['사원', '선임', '책임'][i % 3], i % 17 === 0 ? 0 : 1]);
const courseRows = Array.from({ length: 12 }, (_, i) => [`C${String(i + 1).padStart(2, '0')}`, `가상 AI 과정 ${i + 1}`, 100005 + i * 17501, 6 + i % 3 * 3, 60 + i % 3 * 10]);
const applicationHeaders = ['신청ID','사번','부서','과정코드','교육일','수량','상태','할인율','수동금액','갱신순번','메모','회차'];
const applications = Array.from({ length: 480 }, (_, i) => {
  const employee = employeeRows[i % employeeRows.length];
  return [`APP${String(i + 1).padStart(6, '0')}`, employee[0], employee[2], courseRows[i * 7 % 12][0], new Date(Date.UTC(2026, 9, 1 + i % 28)), i % 6, i % 11 === 0 ? '취소' : i % 7 === 0 ? '대기' : '승인', [0, 0.05, 0.1, 0.125][i % 4], i % 53 === 0 ? 0 : i % 79 === 0 ? 12345 : null, 1, i % 53 === 0 ? '0원 수동금액 유지' : null, ['A','B','C'][Math.floor(i / 160)]];
});
const attendance = applications.flatMap((a, i) => [1,2,3].map(session => [a[0], session, (i % 9 === 0 && session === 3) || (i % 13 === 0 && session === 2) ? 0 : 1, 2]));
const evaluations = applications.map((a, i) => [a[0], 50 + i * 7 % 51, i % 19 === 0 ? 0 : 1]);
const extra = (id, patch = {}) => {
  const row = [`EX${String(id).padStart(6,'0')}`, employeeRows[id % 160][0], employeeRows[id % 160][2], 'C03', new Date('2026-10-22T00:00:00Z'), 2, '승인', 0.1, null, 1, `예외 시험 ${id}`, 'D'];
  for (const [k,v] of Object.entries(patch)) row[Number(k)] = v;
  return row;
};
const exceptions = [
  [...applications[9].slice(0,5),3,'승인',0,0,2,'중복 첫 갱신','A'],
  [...applications[9].slice(0,5),4,'승인',0,45000,2,'같은 순번 뒤 행 우선','A'],
  [...applications[20].slice(0,5),99,'승인',0,null,0,'이전 갱신 버림','A'],
  extra(1,{1:null}), extra(2,{3:'UNKNOWN'}), extra(3,{5:-1}), extra(4,{4:'2026-99-99'}),
  extra(5,{7:1.2}), extra(6,{8:0}), extra(7,{3:' c03 '}), extra(8,{5:1.5}),
  extra(9,{8:-5}), extra(10,{6:'대기'}), extra(11,{1:'999999'}), extra(12,{4:'2026-11-01'})
];

// Independent oracle: integer minor-unit arithmetic, not workbook formulas or migrated Python.
function expected(includeExceptions = false) {
  const sourced = applications.map((v,i)=>({v,source_sheet:'신청원본',source_row:i+6}));
  if(includeExceptions) sourced.push(...exceptions.map((v,i)=>({v,source_sheet:'예외신청',source_row:i+6})));
  const latest = new Map();
  sourced.forEach(s=>{const old=latest.get(s.v[0]); if(!old || s.v[9]>=old.v[9])latest.set(s.v[0],s);});
  const records=[], rejected=[], excluded=[];
  for(const s of latest.values()) {
    const v=s.v; if(v[6]!=='승인'){excluded.push(v[0]);continue;}
    const employee=employeeRows.find(e=>e[0]===String(v[1]??'').trim());
    const course=courseRows.find(c=>c[0]===String(v[3]??'').trim().toUpperCase());
    const date = v[4] instanceof Date ? v[4] : new Date(v[4]);
    let reason=null;
    if(!employee)reason='unknown_employee';
    else if(!course)reason='unknown_course';
    else if(employee[2]!==v[2])reason='department_mismatch';
    else if(!Number.isFinite(date.getTime()))reason='invalid_date';
    else if(!Number.isInteger(v[5])||v[5]<0)reason='invalid_quantity';
    else if(typeof v[7]!=='number'||v[7]<0||v[7]>1)reason='invalid_discount';
    else if(v[8]!==null&&(typeof v[8]!=='number'||v[8]<0))reason='invalid_manual_amount';
    if(reason){rejected.push({application_id:v[0],reason});continue;}
    const amount=v[8]!==null?v[8]:Number((BigInt(course[2])*BigInt(v[5])*BigInt(Math.round((1-v[7])*1000))+500n)/1000n);
    const attended_sessions=new Set(attendance.filter(a=>a[0]===v[0]&&a[2]===1).map(a=>a[1])).size;
    const exam=evaluations.filter(a=>a[0]===v[0]).at(-1); const exam_taken=exam?.[2]===1;
    const score=exam?.[1]??null; const completed=attended_sessions>=3&&exam_taken&&score>=course[4];
    records.push({application_id:v[0],employee_id:employee[0],department:v[2],course_code:course[0],training_date:date.toISOString().slice(0,10),quantity:v[5],discount:v[7],manual_amount:v[8],unit_price:course[2],amount,attended_sessions,exam_taken,score,completed,source_sheet:s.source_sheet,source_row:s.source_row});
  }
  const dep=departments.map(department=>{const rr=records.filter(r=>r.department===department);return{department,approved_count:rr.length,total_amount:rr.reduce((a,r)=>a+r.amount,0),completed_count:rr.filter(r=>r.completed).length};});
  return {input_rows:sourced.length,deduplicated_rows:latest.size,approved_count:records.length,excluded_count:excluded.length,rejected_count:rejected.length,total_amount:records.reduce((a,r)=>a+r.amount,0),completed_count:records.filter(r=>r.completed).length,departments:dep,records,rejected,excluded};
}
const baseExpected=expected(false), allExpected=expected(true);
const mixedSheets=['집계','수식처리','신청원본','출결원본','평가원본','사원기준','교육기준','정책','비정형','예외신청','오류수식','매크로출력'];
const rawSheets=['신청원본','출결원본','평가원본','사원기준','교육기준','정책','예외신청'];
function init(wb,names) {
  const sheets={};
  names.forEach(name=>{
    const s=wb.worksheets.add(name);sheets[name]=s;s.showGridLines=false;
    const rg=s.getRange('A1:P24');rg.format.font={name:'Noto Sans KR',size:10,color:colors.ink};rg.format.columnWidth=16;rg.format.rowHeight=24;rg.format.verticalAlignment='center';
    s.getRange('A1:A24').format.columnWidth=3;
    s.getRange('B2').values=[[name==='매크로출력'?'매크로 결과 입력 자리':`${name} (가상 시험 자료)`]];
    s.getRange('B2').format.font={name:'Noto Sans KR',size:15,bold:true,color:colors.ink};
  }); return sheets;
}
function header(s,range) {s.getRange(range).format.fill=colors.header;s.getRange(range).format.font={name:'Noto Sans KR',size:10,color:'#FFFFFF',bold:true};s.getRange(range).format.horizontalAlignment='center';}
function table(s,range,rows,name) {
  s.getRange(range).values=rows;
  const head=range.split(':')[0].match(/([A-Z]+)(\d+)/);const end=range.split(':')[1].match(/([A-Z]+)(\d+)/);
  header(s,`${head[1]}${head[2]}:${end[1]}${head[2]}`);
  s.getRange(range).format.font.name='Noto Sans KR';s.getRange(range).format.font.size=10;
  s.getRange(range).format.rowHeight=23;
  if(name)s.tables.add(range,true,name);
  s.freezePanes.freezeRows(Number(head[2]));
}
function fillRaw(s) {
  table(s['신청원본'],'B5:M485',[applicationHeaders,...applications],'RawApplications');
  s['신청원본'].getRange('B6:C485').setNumberFormat('@');s['신청원본'].getRange('F6:F485').setNumberFormat('yyyy-mm-dd');s['신청원본'].getRange('I6:I485').setNumberFormat('0.0%');
  s['신청원본'].getRange('J6:J485').setNumberFormat('#,##0');s['신청원본'].getRange('L5:L485').format.columnWidth=26;
  table(s['출결원본'],'B5:E1445',[['신청ID','차시','참석','시간'],...attendance],'RawAttendance');
  table(s['평가원본'],'B5:D485',[['신청ID','점수','응시'],...evaluations],'RawEvaluation');
  table(s['사원기준'],'B5:F165',[['사번','이름','부서','직급','활성'],...employeeRows],'EmployeeMaster');
  s['사원기준'].getRange('B6:B165').setNumberFormat('@');
  table(s['교육기준'],'B5:F17',[['과정코드','과정명','단가','교육시간','수료점수'],...courseRows],'CourseMaster');
  s['교육기준'].getRange('C5:C17').format.columnWidth=25;s['교육기준'].getRange('D6:D17').setNumberFormat('#,##0');s['교육기준'].getRange('G5:G17').format.columnWidth=4;
  table(s['교육기준'],'H5:J11',[['부서','예산','담당'],...departments.map((d,i)=>[d,20000000+i*2000000,`가상담당${i+1}`])],'DepartmentBudget');
  s['교육기준'].getRange('I6:I11').setNumberFormat('#,##0');
  table(s['정책'],'B5:C8',[['항목','값'],['필수참석차시',3],['기본수료점수',60],['금액소수자리',0]],'Policy');s['정책'].getRange('B5:B8').format.columnWidth=26;
  table(s['예외신청'],'B5:M20',[applicationHeaders,...exceptions],'ExceptionalApplications');
  s['예외신청'].getRange('B6:C20').setNumberFormat('@');s['예외신청'].getRange('F6:F20').setNumberFormat('yyyy-mm-dd');s['예외신청'].getRange('L5:L20').format.columnWidth=28;
}
function fillMixed(s) {
  const f=s['수식처리'];
  f.getRange('B5:O5').values=[['신청ID','사번','부서','과정코드','상태','단가','수량','할인율','금액','참석차시','점수','응시','수료점수','수료여부']];header(f,'B5:O5');
  const formulas=applications.map((_,i)=>{const r=i+6;return[
    `='신청원본'!B${r}`,`='신청원본'!C${r}`,`='신청원본'!D${r}`,`='신청원본'!E${r}`,`='신청원본'!H${r}`,
    `=VLOOKUP(E${r},'교육기준'!$B$6:$F$17,3,FALSE)`,`='신청원본'!G${r}`,`='신청원본'!I${r}`,
    `=IF(F${r}="승인",IF(COUNTA('신청원본'!J${r})=0,ROUND(G${r}*H${r}*(1-I${r}),'정책'!$C$8),'신청원본'!J${r}),0)`,
    `=SUMIFS('출결원본'!$D$6:$D$1445,'출결원본'!$B$6:$B$1445,B${r})`,
    `=VLOOKUP(B${r},'평가원본'!$B$6:$D$485,2,FALSE)`,`=VLOOKUP(B${r},'평가원본'!$B$6:$D$485,3,FALSE)`,
    `=VLOOKUP(E${r},'교육기준'!$B$6:$F$17,5,FALSE)`,
    `=IF(AND(F${r}="승인",K${r}>='정책'!$C$6,M${r}=1,L${r}>=N${r}),1,0)`
  ];});
  f.getRange('B6:O485').formulas=formulas;f.getRange('B6:C485').setNumberFormat('@');f.getRange('G6:J485').setNumberFormat('#,##0');f.getRange('I6:I485').setNumberFormat('0.0%');f.freezePanes.freezeRows(5);
  const a=s['집계']; a.getRange('B3').values=[['정상 원본 480건 기준. 예외신청 반영 결과는 Python 처리 결과에서 별도 확인.']];a.getRange('B3').format.font={size:10,color:'#53677B'};
  a.getRange('B5:F11').values=[['부서','승인건수','총액','수료건수','평균금액'],...departments.map(d=>[d,null,null,null,null])];header(a,'B5:F5');
  for(let r=6;r<=11;r++) a.getRange(`C${r}:F${r}`).formulas=[[
    `=COUNTIFS('수식처리'!$D$6:$D$485,B${r},'수식처리'!$F$6:$F$485,"승인")`,
    `=SUMIFS('수식처리'!$J$6:$J$485,'수식처리'!$D$6:$D$485,B${r})`,
    `=SUMIFS('수식처리'!$O$6:$O$485,'수식처리'!$D$6:$D$485,B${r})`,
    `=IF(C${r}=0,0,ROUND(D${r}/C${r},0))`]];
  a.getRange('B12').values=[['합계']];a.getRange('C12:E12').formulas=[['=SUM(C6:C11)','=SUM(D6:D11)','=SUM(E6:E11)']];a.getRange('B12:F12').format.fill=colors.pale;
  a.getRange('H5:K17').values=[['과정','승인건수','총액','수료건수'],...courseRows.map(c=>[c[0],null,null,null])];header(a,'H5:K5');
  for(let r=6;r<=17;r++)a.getRange(`I${r}:K${r}`).formulas=[[
    `=COUNTIFS('수식처리'!$E$6:$E$485,H${r},'수식처리'!$F$6:$F$485,"승인")`,
    `=SUMIFS('수식처리'!$J$6:$J$485,'수식처리'!$E$6:$E$485,H${r})`,
    `=SUMIFS('수식처리'!$O$6:$O$485,'수식처리'!$E$6:$E$485,H${r})`]];
  a.getRange('B16:D19').values=[['상태','건수','수량'],['승인',null,null],['대기',null,null],['취소',null,null]];header(a,'B16:D16');
  for(let r=17;r<=19;r++)a.getRange(`C${r}:D${r}`).formulas=[[
    `=COUNTIFS('수식처리'!$F$6:$F$485,B${r})`,`=SUMIFS('수식처리'!$H$6:$H$485,'수식처리'!$F$6:$F$485,B${r})`]];
  a.getRange('D6:F12').setNumberFormat('#,##0');a.getRange('J6:J17').setNumberFormat('#,##0');a.getRange('G5:G19').format.columnWidth=4;a.getRange('D5:D12').format.columnWidth=21;
  const n=s['비정형'];
  n.mergeCells('B5:B7');n.mergeCells('C5:F5');n.mergeCells('C6:D6');n.mergeCells('E6:F6');
  n.getRange('B5:F5').values=[['부서','교육 성과',null,null,null]];n.getRange('C6:F6').values=[['참여',null,'평가',null]];n.getRange('C7:F7').values=[['신청','수료','평균점수','응시율']];header(n,'B5:F7');
  n.getRange('B8:F13').values=departments.map((d,i)=>[d,80,40+i,72+i,0.75+i*0.025]);n.getRange('F8:F13').setNumberFormat('0.0%');
  table(n,'H5:J10',[['항목','금액','메모'],['A',0,'실제 0'],['B',null,'미입력'],['항목','금액','메모'],['C',1200,'반복 머리글'],['소계',1200,'소계 보존']],null);
  table(n,'B17:E23',[['분류','세부','값','설명'],['실습','1차',10,'빈 분류 다음 행'],[null,'2차',20,null],['검토','1차',30,'빈 행 다음 구역'],[null,null,null,null],['검토','2차',0,'0 보존'],['합계',null,60,'소계 보존']], 'RaggedNativeTable');n.getRange('G5:G23').format.columnWidth=4;n.getRange('J5:J10').format.columnWidth=25;
  const e=s['오류수식'];table(e,'B5:D14',[['사례','결과','기대 처리'],['동적 참조','미지원 수식 예정','INDIRECT 보류'],['외부 통합문서','미지원 수식 예정','외부 파일 미실행'],['순환 A','오류 수식 예정','순환 참조 탐지'],['순환 B','오류 수식 예정','순환 참조 탐지'],['0으로 나눔','오류 수식 예정','오류 보존'],['조회 실패','오류 수식 예정','오류 보존'],['캐시 없는 정상','수식 예정','30으로 재계산'],['구조화 참조','미지원 수식 예정','미지원 보류'],['배열 함수','미지원 수식 예정','미지원 보류']],null);e.getRange('B5:D14').format.columnWidth=28;
  s['매크로출력'].getRange('B4').values=[['미실행. 매크로 원문은 별도 .bas 예제로 제공하며, 이 .xlsx에는 VBA가 없습니다.']];
  s['매크로출력'].getRange('B6:E6').values=[['부서','승인건수','총액','수료건수']];header(s['매크로출력'],'B6:E6');
}

async function build(mixed) {
  const wb=Workbook.create();const s=init(wb,mixed?mixedSheets:rawSheets);fillRaw(s);if(mixed)fillMixed(s);
  wb.recalculate();
  if(mixed){
    let mismatch=0;
    for(let i=0;i<applications.length;i++) {
      const rec=baseExpected.records.find(r=>r.application_id===applications[i][0]);
      const actual=s['수식처리'].getRange(`J${i+6}`).values[0][0];
      const completed=s['수식처리'].getRange(`O${i+6}`).values[0][0];
      if(actual!==(rec?.amount??0)||completed!==Number(rec?.completed??false))mismatch++;
    }
    if(mismatch)throw new Error(`Independent row controls failed in ${mismatch} rows`);
    for(const [address,expected] of [['C12',baseExpected.approved_count],['D12',baseExpected.total_amount],['E12',baseExpected.completed_count]]) {
      const actual=s['집계'].getRange(address).values[0][0];if(actual!==expected)throw new Error(`Unexpected calculation 집계!${address}: ${actual} expected ${expected}`);
    }
    const scan=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!',options:{useRegex:true,maxResults:10},maxChars:1500});console.log('Formula error scan before intentional exception insertion:',scan.ndjson);
    console.log((await wb.inspect({kind:'table',range:'집계!B5:F12',include:'values,formulas',tableMaxRows:8,tableMaxCols:5,maxChars:2000})).ndjson);
  }
  const basename=mixed?'고급_수식매크로_혼합':'매크로전용_입력';
  for(const name of mixed?mixedSheets:rawSheets){
    const range=name==='집계'?'A1:L21':name==='비정형'?'A1:K25':name==='수식처리'?'A1:P15':name==='매크로출력'?'A1:K10':name==='오류수식'?'A1:E16':name==='예외신청'?'A1:N22':name==='신청원본'?'A1:N15':name==='교육기준'?'A1:K19':name==='정책'?'A1:D11':'A1:G16';
    const image=await wb.render({sheetName:name,range,scale:1.2,format:'png'});await fs.writeFile(path.join(previews,`${basename}-${name}.png`),new Uint8Array(await image.arrayBuffer()));
  }
  const xlsx=await SpreadsheetFile.exportXlsx(wb);await xlsx.save(path.join(fixtures,`${basename}.xlsx`));
  // Missing public authoring controls (hidden metadata, names), cache-less test and intentional
  // failing formulas are inserted through OOXML only, without Excel or macro execution.
  const patch=String.raw`import sys,zipfile,xml.etree.ElementTree as E,os,json
p,mixed=sys.argv[1],sys.argv[2]=='1'
n='http://schemas.openxmlformats.org/spreadsheetml/2006/main';ns={'s':n}
with zipfile.ZipFile(p) as z: parts={i.filename:z.read(i.filename) for i in z.infolist()}
w=E.fromstring(parts['xl/workbook.xml']);sheets=w.find('s:sheets',ns)
names=[x.attrib['name'] for x in sheets]
for x in sheets:
 if x.attrib['name']=='정책': x.set('state','hidden')
dn=w.find('s:definedNames',ns)
if dn is None: dn=E.SubElement(w,'{'+n+'}definedNames')
E.SubElement(dn,'{'+n+'}definedName',{'name':'RequiredAttendance'}).text="'정책'!$C$6"
parts['xl/workbook.xml']=E.tostring(w,encoding='utf-8',xml_declaration=True)
for name in ['신청원본','사원기준']:
 part='xl/worksheets/sheet'+str(names.index(name)+1)+'.xml';root=E.fromstring(parts[part])
 row=root.find('.//s:row[@r="12"]',ns)
 if row is not None: row.set('hidden','1')
 if name=='신청원본':
  cols=root.find('s:cols',ns)
  if cols is None:
   cols=E.Element('{'+n+'}cols');root.insert(list(root).index(root.find('s:sheetData',ns)),cols)
  E.SubElement(cols,'{'+n+'}col',{'min':'12','max':'12','hidden':'1','width':'26','customWidth':'1'})
 parts[part]=E.tostring(root,encoding='utf-8',xml_declaration=True)
if mixed:
 part='xl/worksheets/sheet'+str(names.index('수식처리')+1)+'.xml';root=E.fromstring(parts[part])
 for addr in ['O6','O245','O485']:
  f=root.find('.//s:c[@r="'+addr+'"]'+'/s:f',ns);f.text=f.text.replace("'정책'!$C$6",'RequiredAttendance')
 for addr in ['J6','J245','J485']:
  c=root.find('.//s:c[@r="'+addr+'"]',ns)
  for v in c.findall('s:v',ns):c.remove(v)
 parts[part]=E.tostring(root,encoding='utf-8',xml_declaration=True)
 part='xl/worksheets/sheet'+str(names.index('오류수식')+1)+'.xml';root=E.fromstring(parts[part])
 cases={'C6':('INDIRECT("신청원본!G6")',None),'C7':("'[missing.xlsx]Sheet1'!A1",None),'C8':('C9+1',None),'C9':('C8+1',None),'C10':('1/0','#DIV/0!'),'C11':('VLOOKUP("UNKNOWN",교육기준!B6:F17,3,FALSE)','#N/A'),'C12':('10+20',None),'C13':('SUM(RawApplications[수량])',None),'C14':('_xlfn.FILTER(신청원본!B6:B485,신청원본!H6:H485="승인")',None)}
 for addr,(formula,value) in cases.items():
  c=root.find('.//s:c[@r="'+addr+'"]',ns)
  for child in list(c):c.remove(child)
  c.attrib.pop('t',None);E.SubElement(c,'{'+n+'}f').text=formula
  if value is not None:c.set('t','e');E.SubElement(c,'{'+n+'}v').text=value
 parts[part]=E.tostring(root,encoding='utf-8',xml_declaration=True)
tmp=p+'.tmp'
with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
 for name,data in parts.items():z.writestr(name,data)
os.replace(tmp,p)
print(json.dumps({'file':os.path.basename(p),'sheet_count':len(names),'macro_code_embedded':False}))
`;
  console.log(execFileSync(python,['-X','utf8','-c',patch,path.join(fixtures,`${basename}.xlsx`),mixed?'1':'0'],{encoding:'utf8'}));
}
try { await build(true);await build(false); } catch(error) { console.error(error.message); process.exit(2); }
const manifest={schema_version:1,synthetic:true,description:'실제 회사자료가 아닌 독립 Excel→Python 업무이관 시험. 원본 VBA 실행 동등성은 미검증.',files:{mixed:'fixtures/고급_수식매크로_혼합.xlsx',macro_only:'fixtures/매크로전용_입력.xlsx'},input_counts:{applications:480,attendance:1440,evaluations:480,employees:160,courses:12,exceptions:15,departments:6},sheet_names:{mixed:mixedSheets,macro_only:rawSheets},base_expected:baseExpected,all_expected:allExpected,expected_tables:[{sheet:'신청원본',range:'B5:M485',header_rows:1},{sheet:'출결원본',range:'B5:E1445',header_rows:1},{sheet:'평가원본',range:'B5:D485',header_rows:1},{sheet:'사원기준',range:'B5:F165',header_rows:1},{sheet:'교육기준',range:'B5:F17',header_rows:1},{sheet:'교육기준',range:'H5:J11',header_rows:1},{sheet:'정책',range:'B5:C8',header_rows:1},{sheet:'예외신청',range:'B5:M20',header_rows:1},{sheet:'수식처리',range:'B5:O485',header_rows:1},{sheet:'비정형',range:'B5:F13',header_rows:3}],features:{mixed_formula_count_before_intentional_exceptions:6789,intentional_exception_formula_count:9,hidden_sheet:'정책',hidden_rows:{신청원본:[12],사원기준:[12]},hidden_columns:{신청원본:['L']},named_range:{RequiredAttendance:"'정책'!$C$6"},cacheless_cells:['수식처리!J6','수식처리!J245','수식처리!J485','오류수식!C12'],repeated_header:'비정형!H8:J8',merged_header:'비정형!B5:F7'},oracle_method:'Node JS integer rounding independently from formula evaluator and migrated Python. Expected records retained to compare identifiers, types and values, not only totals.',limitations:['No actual VBA embedded or executed. Separate .bas examples are supplied by the migration prototype.','No native Excel recalculation performed. Artifact calculation and saved OOXML independently checked.','Exception previews show explicit placeholders before intentional exception formulas are inserted.','Excel serial dates are legitimate input; JSON expected dates are ISO day strings.']};
await fs.writeFile(path.join(out,'advanced-manifest.json'),JSON.stringify(manifest,null,2),'utf8');
console.log(JSON.stringify({status:'created',fixtures,base_total:baseExpected.total_amount,all_total:allExpected.total_amount,base_approved:baseExpected.approved_count,all_approved:allExpected.approved_count}));
