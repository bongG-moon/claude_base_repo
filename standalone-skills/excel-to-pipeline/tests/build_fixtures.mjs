// Synthetic regression workbooks. Never reads or changes a user's workbook.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../../..');
const out = path.join(root, 'outputs/excel-to-pipeline-test');
const previews = path.join(out, 'previews');
const python = process.env.FIXTURE_PYTHON || 'python';
await fs.mkdir(previews, { recursive: true });
const theme = { ink: '#23374D', header: '#2E5077', pale: '#EDF3F8', muted: '#52687C' };
function style(sheet, range = 'A1:K22') {
  sheet.showGridLines = false;
  const r = sheet.getRange(range);
  r.format.font = { name: 'Noto Sans KR', size: 10, color: theme.ink };
  r.format.columnWidth = 15;
  r.format.rowHeight = 25;
  r.format.verticalAlignment = 'center';
  sheet.getRange('A1:A22').format.columnWidth = 3;
}
function title(s, address, text) {
  s.getRange(address).values = [[text]];
  s.getRange(address).format.font = { name: 'Noto Sans KR', size: 15, bold: true, color: theme.ink };
}
function header(s, range) {
  s.getRange(range).format.fill = theme.header;
  s.getRange(range).format.font = { name: 'Noto Sans KR', size: 10, color: '#FFFFFF', bold: true };
  s.getRange(range).format.horizontalAlignment = 'center';
}
const records = [
  ['00101','김하나','개발','C01',1,'승인',0,null],
  ['00102','이둘','생산','C02',2,'승인',0.1,'단체 신청'],
  ['00103','박셋','개발','C03',1,'대기',0,null],
  ['00104','최넷','품질','C01',1,'승인',0.05,null],
  ['00105','정다섯','생산','C02',0,'취소',0,'수량 0 보존'],
  ['00106','문여섯','품질','C03',1,'승인',0,null],
  ['00107','한일곱','개발','C02',1,'승인',0.2,null],
  ['00108','오여덟','생산','C01',3,'승인',0,null],
  ['00109','윤아홉','품질','C03',1,'대기',0.1,null],
  ['00110','강열','개발','C01',1,'승인',0,null],
];
async function save(wb, filename, ranges, expected) {
  wb.recalculate();
  const errors = await wb.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!', options: {useRegex: true, maxResults: 25}, maxChars: 2000 });
  console.log(filename, 'formula scan', errors.ndjson);
  for (const [key,value] of Object.entries(expected)) {
    const split = key.lastIndexOf('!');
    const got = wb.worksheets.getItem(key.slice(0,split)).getRange(key.slice(split+1)).values[0][0];
    if (got !== value) throw new Error(`${filename}: ${key} expected ${value}, got ${got}`);
  }
  for (const [sheetName, range] of Object.entries(ranges)) {
    const preview = await wb.render({ sheetName, range, scale: 1.5, format:'png' });
    await fs.writeFile(path.join(previews, `${filename.replace('.xlsx','')}-${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
  const xlsx = await SpreadsheetFile.exportXlsx(wb);
  await xlsx.save(path.join(out,filename));
}
async function buildComplex(next=false) {
  const wb=Workbook.create();
  for(const n of ['집계','정산','신청','기준표','실적']) style(wb.worksheets.add(n));
  const s=Object.fromEntries(['집계','정산','신청','기준표','실적'].map(n=>[n,wb.worksheets.getItem(n)]));
  const data=records.map(x=>[...x]);
  if(next) { data[0][4]=2; data[2][5]='승인'; data.push(['00111','서열하나','생산','C03',2,'승인',0.1,'신규']); }
  title(s['신청'],'B2',`${next?'11':'10'}월 교육 신청 (가상 자료)`);
  s['신청'].getRange('B5:J5').values=[['사번','성명','부서','과정코드','신청일','수량','상태','감면율','메모']];
  header(s['신청'],'B5:J5');
  const sourceRows=[];
  let r=6;
  data.forEach((x,i)=>{
    if(i===5)r++;
    sourceRows.push(r);
    s['신청'].getRange(`B${r}:J${r}`).values=[[...x.slice(0,4), new Date(Date.UTC(2026,next?10:9,1+i)),...x.slice(4)]];
    r++;
  });
  s['신청'].getRange(`B6:B${r-1}`).setNumberFormat('@');
  s['신청'].getRange(`F6:F${r-1}`).setNumberFormat('yyyy-mm-dd');
  s['신청'].getRange(`I6:I${r-1}`).setNumberFormat('0.0%');
  s['신청'].getRange('F5:F22').format.columnWidth=18;
  s['신청'].getRange('J5:J22').format.columnWidth=23;
  s['신청'].tables.add(`B5:J${r-1}`,true,'Applicants');
  s['신청'].freezePanes.freezeRows(5);

  title(s['기준표'],'B2','과정과 부서 기준 (가상 자료)');
  s['기준표'].getRange('B4:E7').values=[['과정코드','과정명','단가','시간'],['C01','AI 기초',100000,4],['C02','Python 실습',next?160000:150000,8],['C03','데이터 분석',200000,12]];
  s['기준표'].getRange('G4:I7').values=[['부서','예산','담당'],['개발',700000,'가상 담당1'],['생산',1000000,'가상 담당2'],['품질',400000,'가상 담당3']];
  s['기준표'].getRange('B11:D14').values=[['회차','시작일','정원'],['A',new Date('2026-10-20T00:00:00Z'),20],['B',new Date('2026-11-03T00:00:00Z'),25],['C',new Date('2026-11-17T00:00:00Z'),30]];
  for(const rg of ['B4:E4','G4:I4','B11:D11'])header(s['기준표'],rg);
  s['기준표'].getRange('C4:C14').format.columnWidth=22;
  s['기준표'].getRange('D5:D7').setNumberFormat('#,##0');
  s['기준표'].getRange('H5:H7').setNumberFormat('#,##0');
  s['기준표'].getRange('C12:C14').setNumberFormat('yyyy-mm-dd');
  s['기준표'].getRange('F1:F20').format.columnWidth=4;

  title(s['정산'],'B2','신청별 예상 정산 (원)');
  s['정산'].getRange('B5:H5').values=[['사번','부서','상태','단가','수량','감면율','청구액']];
  header(s['정산'],'B5:H5');
  sourceRows.forEach((src,i)=>{
    const d=i+6;
    s['정산'].getRange(`B${d}:H${d}`).formulas=[[
      `='신청'!B${src}`, `='신청'!D${src}`, `='신청'!H${src}`,
      `=VLOOKUP('신청'!E${src},'기준표'!$B$5:$E$7,3,FALSE)`,
      `='신청'!G${src}`,`='신청'!I${src}`,
      `=IF(D${d}="승인",ROUND(E${d}*F${d}*(1-G${d}),0),0)`
    ]];
  });
  const total=6+data.length;
  s['정산'].getRange(`B${total}`).values=[['합계']];
  s['정산'].getRange(`H${total}`).formulas=[[`=SUM(H6:H${total-1})`]];
  s['정산'].getRange(`B${total}:H${total}`).format.fill=theme.pale;
  s['정산'].getRange(`B${total}:H${total}`).format.font={bold:true};
  s['정산'].getRange(`E6:F${total}`).setNumberFormat('#,##0');
  s['정산'].getRange(`H6:H${total}`).setNumberFormat('#,##0');
  s['정산'].getRange(`G6:G${total-1}`).setNumberFormat('0.0%');
  s['정산'].getRange('B6:B22').setNumberFormat('@');

  title(s['집계'],'B2',`${next?'11':'10'}월 부서별 승인 현황`);
  s['집계'].getRange('B4:E7').values=[['부서','승인인원','승인금액','평균금액'],['개발',null,null,null],['생산',null,null,null],['품질',null,null,null]];
  header(s['집계'],'B4:E4');
  for(let d=5;d<=7;d++)s['집계'].getRange(`C${d}:E${d}`).formulas=[[
    `=COUNTIFS('정산'!$C$6:$C$${total-1},B${d},'정산'!$D$6:$D$${total-1},"승인")`,
    `=SUMIFS('정산'!$H$6:$H$${total-1},'정산'!$C$6:$C$${total-1},B${d},'정산'!$D$6:$D$${total-1},"승인")`,
    `=IF(C${d}=0,0,ROUND(D${d}/C${d},0))`
  ]];
  s['집계'].getRange('B8').values=[['합계']];
  s['집계'].getRange('C8:D8').formulas=[['=SUM(C5:C7)','=SUM(D5:D7)']];
  s['집계'].getRange('B8:E8').format.fill=theme.pale;
  s['집계'].getRange('D5:E8').setNumberFormat('#,##0');
  s['집계'].getRange('B4:E8').format.columnWidth=20;

  title(s['실적'],'B2','병합 머리글 실적 예시');
  s['실적'].mergeCells('B4:B5'); s['실적'].mergeCells('C4:C5'); s['실적'].mergeCells('D4:E4'); s['실적'].mergeCells('F4:G4');
  s['실적'].getRange('B4:G4').values=[['부서','월','교육',null,'성과',null]];
  s['실적'].getRange('D5:G5').values=[['신청','수료','만족도','달성률']];
  s['실적'].getRange('B6:G9').values=[['개발','2026-09',12,10,4.4,0.8333],['생산','2026-09',15,13,4.1,0.8667],['품질','2026-09',8,8,4.8,1],['개발','2026-10',10,0,null,0]];
  header(s['실적'],'B4:G5');
  s['실적'].getRange('F6:F9').setNumberFormat('0.0');
  s['실적'].getRange('G6:G9').setNumberFormat('0.0%');
  const name=next?'variant_next_month.xlsx':'complex_workbook.xlsx';
  await save(wb,name,{'집계':'A1:F10','정산':`A1:I${total+1}`,'신청':`A1:K${r}`,'기준표':'A1:J16','실적':'A1:H11'},next?{'집계!C8':9,'집계!D8':1871000,'집계!D5':628000}:{'집계!C8':7,'집계!D8':1185000,'집계!D5':320000});
}
async function buildAmbiguous(){
  const wb=Workbook.create();
  const a=wb.worksheets.add('경계모호');style(a);
  title(a,'B2','자동 확정하면 안 되는 표 (가상 자료)');
  a.getRange('B4:E10').values=[['항목','값',null,'메모'],['A',10,null,'빈 열이 구분자인지 불명확'],['B',20,null,null],['소계',30,null,null],['항목','값',null,'메모'],['C',0,null,'반복 머리글, 표 구분선 없음'],['D',null,null,'누락 값']];
  header(a,'B4:E4');header(a,'B8:E8');
  a.getRange('E4:E10').format.columnWidth=42;
  const f=wb.worksheets.add('수식예외');style(f,'A1:D15');
  title(f,'B2','변환 보류를 확인하는 예외 수식');
  f.getRange('B4:D12').values=[['사례','결과','의도'],['동적 참조','삽입 예정','INDIRECT 미지원 표시'],['외부 파일','삽입 예정','외부 링크 실행 금지'],['순환 A','삽입 예정','순환 탐지'],['순환 B','삽입 예정','순환 탐지'],['0으로 나눔','삽입 예정','오류 보존'],['조회 실패','삽입 예정','오류 보존'],['일반 수식',10,'다른 정상 결과 보존'],['캐시 없는 수식','삽입 예정','캐시 없음을 0으로 오인 금지']];
  header(f,'B4:D4');f.getRange('B4:D12').format.columnWidth=32;
  await save(wb,'ambiguous_cases.xlsx',{'경계모호':'A1:F12','수식예외':'A1:E14'},{});
  // Intentional bad-formula fixture patch: no formulas are evaluated, and no external data is opened.
  // stdlib OOXML preserves the Artifact Tool-authored workbook's layout and other features.
  const patch=String.raw`import sys,zipfile,xml.etree.ElementTree as E,os
p=sys.argv[1]
ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
with zipfile.ZipFile(p) as z: parts={i.filename:z.read(i.filename) for i in z.infolist()}
root=E.fromstring(parts['xl/worksheets/sheet2.xml'])
cases={'C5':('INDIRECT("경계모호!C5")',None),'C6':("'[missing.xlsx]Sheet1'!A1",None),'C7':('C8+1',None),'C8':('C7+1',None),'C9':('1/0','#DIV/0!'),'C10':('VLOOKUP("없음",경계모호!B5:C6,2,FALSE)','#N/A'),'C12':('10+20',None)}
for address,(formula,value) in cases.items():
 cell=root.find('.//s:c[@r="'+address+'"]',ns)
 if cell is None: raise RuntimeError(address+' missing')
 for child in list(cell): cell.remove(child)
 cell.attrib.pop('t',None)
 E.SubElement(cell,'{'+ns['s']+'}f').text=formula
 if value is not None:
  cell.set('t','e');E.SubElement(cell,'{'+ns['s']+'}v').text=value
parts['xl/worksheets/sheet2.xml']=E.tostring(root,encoding='utf-8',xml_declaration=True)
tmp=p+'.fixture.tmp'
with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
 for name,data in parts.items():z.writestr(name,data)
os.replace(tmp,p)
print('Intentional unsupported/cycle/error formulas patched; no recalculation performed.')
`;
  console.log(execFileSync(python,['-X','utf8','-c',patch,path.join(out,'ambiguous_cases.xlsx')],{encoding:'utf8'}));
}
await buildComplex(false);
await buildComplex(true);
await buildAmbiguous();
console.log(JSON.stringify({fixtureDirectory:out,previewsDirectory:previews,workbooks:3}));
