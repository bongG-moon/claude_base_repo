// 한국어 엑셀 구조 분석 실습용 자료를 만듭니다. 모든 원본 행은 가상 데이터입니다.
// 작성 라이브러리는 Codex가 제공한 번들만 사용하며 개인 업무 파일을 읽지 않습니다.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const root = process.cwd();
const work = path.join(root, '.smoke/excel-training-20261105');
const output = path.join(root, 'outputs/excel-html-improvements-20261105/실습자료');
await fs.mkdir(output, {recursive:true});
const runtimeRequire = createRequire(path.join(work, 'package.json'));
const {Workbook, SpreadsheetFile} = await import(pathToFileURL(runtimeRequire.resolve('@oai/artifact-tool')).href);
const workbook = Workbook.create();
const names = ['최종현황','기준정보','제품집계','공정계산','생산원본','품질원본','설비원본','검증표'];
const sheets = Object.fromEntries(names.map(n => [n, workbook.worksheets.add(n)]));
const c = {ink:'#243447', navy:'#213D5B', blue:'#315B81', soft:'#EDF3F8', line:'#CBD6E1', amber:'#FFF1CE'};
const sites = ['이천','청주','패키지'];
const products = Array.from({length:12},(_,i)=>[`P${String(i+1).padStart(3,'0')}`,`가상제품 ${i+1}`,['DRAM','NAND','SSD'][i%3],3500+i*250,0.92+(i%4)*0.01,12+(i%5)*3,1+(i%3)*0.1,1000+i*50]);
const start = new Date(Date.UTC(2026,9,1));
const dateAt = i=>new Date(start.getTime()+i*86400000);
const serial = date => (date.getTime()-Date.UTC(1899,11,30))/86400000;
const round=(value,digits=0)=>Math.round((value+Number.EPSILON)*10**digits)/10**digits;
const col = n => {let s='';for(;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
const write=(sheet,cell,values)=>sheets[sheet].getRange(cell).writeValues(values);
const formula=(sheet,cell,formulas)=>sheets[sheet].getRange(cell).write({formulas});
function base(name,title,description,rows,cols=12){
  const s=sheets[name]; s.showGridLines=false;
  s.getRange(`A1:${col(cols)}${rows}`).format={font:{name:'Malgun Gothic',size:10,color:c.ink},rowHeight:21,verticalAlignment:'center',columnWidth:14};
  s.getRange('A2').values=[[title]]; s.getRange('A2').format.font={name:'Malgun Gothic',size:16,bold:true,color:c.navy};
  s.getRange(`A3:${col(cols)}3`).format.borders={bottom:{style:'thin',color:c.line}};
  s.getRange('A4').values=[[description]]; s.getRange('A4').format.font={italic:true,color:'#627389',size:10};
  if(rows>30){s.freezePanes.freezeRows(5);s.freezePanes.freezeColumns(2);}
  return s;
}
function table(name,headers,rows,tableName){
  const s=sheets[name]; const last=rows.length+5;
  write(name,'A5',[headers,...rows]);
  const t=s.tables.add(`A5:${col(headers.length)}${last}`,true,tableName);t.style='TableStyleMedium2';
  s.getRange(`A5:${col(headers.length)}5`).format={fill:c.navy,font:{name:'Malgun Gothic',size:10,bold:true,color:'#FFFFFF'},rowHeight:34,wrapText:true,horizontalAlignment:'center'};
  s.getRange(`A6:${col(headers.length)}${last}`).format.font={name:'Malgun Gothic',size:10,color:c.ink};
  return last;
}
const prodHeaders=['LOT번호','생산일','사업장','제품코드','설비코드','공정','투입수량','양품수량','가동시간','대기시간','계획수량','Recipe','우선순위','상태','작업조','작업자ID','자재코드','공급사','웨이퍼규격','패키지','온도','습도','고객군','공정차수','재작업','샘플수','측정값','규격하한','규격상한','라인코드','작업메모','갱신차수'];
const productions=Array.from({length:360},(_,i)=>{
  const qty=900+(i*37)%700,good=qty-(i*11)%70;
  return [`L${String(i+1).padStart(6,'0')}`,dateAt(i%60),sites[Math.floor(i/12)%3],products[i%12][0],`EQ${String(i%10+1).padStart(2,'0')}`,['조립','검사','포장'][i%3],qty,good,(8+(i%35))/24,(i%19)/24,qty+100,`rcp${i%2?'B':'a'}${String(i%7).padStart(2,'0')}`,i%4+1,i%23===0?'보류':'완료',['A','B','C'][i%3],String(3000+i%40).padStart(7,'0'),`MAT${i%8+1}`,`가상협력사${i%5+1}`,i%2?300:200,['BGA','TSV','MCP'][i%3],21+i%6,40+i%15,['모바일','서버','소비자'][i%3],i%4+1,i%17===0?'Y':'N',10+i%11,round(10+(i%13)*0.1,2),9.5,12.0,`line${i%5+1}`,i%31===0?'샘플 점검':null,i%3+1];
});
const qualHeaders=['검사번호','LOT번호','검사일','검사단계','검사수량','불량수량','재작업수량','불량유형','검사자ID','사업장','제품코드','검사설비','Recipe','샘플A','샘플B','샘플C','측정온도','측정습도','보류여부','분석완료','점검시간','수동보정','판정','메모','검사차수','추적코드'];
const qualities=Array.from({length:480},(_,i)=>{
  const p=productions[i%360];
  return [`Q${String(i+1).padStart(6,'0')}`,p[0],p[1],i<360?'최종':'추가',150+i%120,i%8,i%4,['외관','전기','치수'][i%3],String(5000+i%15).padStart(7,'0'),p[2],p[3],`QA${i%6+1}`,p[11],round(10+i%17*0.1,2),round(11+i%13*0.1,2),round(12+i%11*0.1,2),23+i%4,45+i%8,i%37===0?'Y':'N',i%11===0?'대기':'완료',(0.25+i%5*0.1)/24,i%41===0?0:null,i%8===7?'재검':'정상',null,i<360?1:2,`qa${i%2?'B':'a'}${i%9}`];
});
const eqHeaders=['설비일키','설비코드','기준일','사업장','계획가동시간','실제가동시간','정지시간','정비시간','전력사용량','계획UPH','담당자ID','설비모델','설치년도','라인','공정','알람건수','정비차수','치공구','소모품','온도','습도','점검상태','상태코드','비고','계획시간','가동일수','추적문자','갱신순번'];
const equipment=Array.from({length:300},(_,i)=>{const eq=i%10,day=Math.floor(i/10)*2;
  return [`E${String(i+1).padStart(5,'0')}`,`EQ${String(eq+1).padStart(2,'0')}`,dateAt(day),sites[eq%3],24,16+(i%7),1+(i%3)*0.5,(i%4)*0.25,300+i%120,50+(eq%5)*5,String(7000+eq).padStart(7,'0'),`가상모델${eq%3+1}`,2018+eq%6,`line${eq%5+1}`,['조립','검사','포장'][eq%3],i%5,i%4+1,`JIG${i%7+1}`,`PART${i%9+1}`,22+i%5,45+i%9,i%23===0?'점검':'정상',i%2?'aReady':'BReady',null,(26+i%12)/24,1,`MixCase${i%6}`,i%3+1];});

base('생산원본','생산 원본','가상 데이터 360행. 가동시간과 대기시간은 누적 시간이며 앞자리 0과 대소문자를 보존합니다.',365,32);
base('품질원본','품질 검사 원본','가상 데이터 480행. 일부 LOT은 최종 검사와 추가 검사를 모두 받아 조건 합산이 필요합니다.',485,26);
base('설비원본','설비 일별 원본','가상 데이터 300행. 설비별 실제 가동시간, 전력과 계획 UPH를 관리합니다.',305,28);
table('생산원본',prodHeaders,productions,'ProductionSource');
table('품질원본',qualHeaders,qualities,'QualitySource');
table('설비원본',eqHeaders,equipment,'EquipmentSource');
sheets.생산원본.getRange('B6:B365').setNumberFormat('yyyy-mm-dd');
sheets.생산원본.getRange('B:B').format.columnWidth=17;
sheets.생산원본.getRange('I6:J365').setNumberFormat('[h]:mm');
sheets.생산원본.getRange('A6:A365').setNumberFormat('@');
sheets.품질원본.getRange('C6:C485').setNumberFormat('yyyy-mm-dd');
sheets.품질원본.getRange('C:C').format.columnWidth=17;
sheets.품질원본.getRange('U6:U485').setNumberFormat('[h]:mm');
sheets.설비원본.getRange('C6:C305').setNumberFormat('yyyy-mm-dd');
sheets.설비원본.getRange('C:C').format.columnWidth=17;
sheets.설비원본.getRange('Y6:Y305').setNumberFormat('[h]:mm');

base('기준정보','보고 기준과 제품 정보','노란 셀의 보고 기간 또는 제품 단가를 바꾸면 계산 시트와 최종 결과가 함께 바뀝니다.',26,12);
write('기준정보','A5',[['보고 시작일',dateAt(0)],['보고 종료일',dateAt(30)],['전력 단가',150],['재작업 비용',800],['수율 경고 기준',0.95]]);
sheets.기준정보.getRange('B5:B9').format.fill=c.amber;
sheets.기준정보.getRange('B5:B6').setNumberFormat('yyyy-mm-dd');
sheets.기준정보.getRange('B9').setNumberFormat('0.0%');
write('기준정보','A13',[['제품코드','제품명','제품군','단가','목표수율','목표시간','보정계수','기준수량'],...products]);
sheets.기준정보.getRange('A13:H13').format={fill:c.navy,font:{bold:true,color:'#FFFFFF'},rowHeight:30};
sheets.기준정보.getRange('D14:H25').format.fill=c.amber;
sheets.기준정보.getRange('E14:E25').setNumberFormat('0.0%');
sheets.기준정보.tabColor=c.blue;

base('공정계산','LOT별 생산과 품질 계산','생산 원본과 품질 원본을 LOT로 합치고 기준정보의 단가와 목표를 적용합니다.',365,30);
const calcHeaders=['LOT번호','생산일','사업장','제품코드','투입수량','양품수량','가동시간(h)','대기시간(h)','검사수량','불량수량','재작업수량','검사건수','생산수율','검사불량률','종합수율','단가','생산금액','재작업비용','목표수율','목표시간','시간차이','수율상태','기간포함','완료여부','유효생산금액','실제UPH','품질판정','제품명','Recipe','설비코드'];
table('공정계산',calcHeaders,Array.from({length:360},()=>Array(30).fill(null)),'LotCalculation');
const calc=productions.map((p,i)=>{const r=i+6;return [
`='생산원본'!A${r}`,`='생산원본'!B${r}`,`='생산원본'!C${r}`,`='생산원본'!D${r}`,`='생산원본'!G${r}`,`='생산원본'!H${r}`,
`=ROUND('생산원본'!I${r}*24,2)`,`=ROUND('생산원본'!J${r}*24,2)`,
`=SUMIF('품질원본'!$B$6:$B$485,A${r},'품질원본'!$E$6:$E$485)`,
`=SUMIF('품질원본'!$B$6:$B$485,A${r},'품질원본'!$F$6:$F$485)`,
`=SUMIFS('품질원본'!$G$6:$G$485,'품질원본'!$B$6:$B$485,A${r},'품질원본'!$T$6:$T$485,"완료")`,
`=COUNTIF('품질원본'!$B$6:$B$485,A${r})`,`=IF(E${r}=0,"분모 없음",ROUND(F${r}/E${r},6))`,
`=IF(I${r}=0,"검사 없음",ROUND(J${r}/I${r},6))`,`=IF(OR(E${r}=0,I${r}=0),"확인 필요",ROUND(M${r}*(1-N${r}),6))`,
`=VLOOKUP(D${r},'기준정보'!$A$14:$H$25,4,FALSE)`,`=ROUND(F${r}*P${r},0)`,`=ROUND(K${r}*'기준정보'!$B$8,0)`,
`=VLOOKUP(D${r},'기준정보'!$A$14:$H$25,5,FALSE)`,`=VLOOKUP(D${r},'기준정보'!$A$14:$H$25,6,FALSE)`,
`=ROUND(G${r}+H${r}-T${r},2)`,`=IF(AND(M${r}>=S${r},M${r}>='기준정보'!$B$9),"정상","수율 확인")`,
`=IF(AND(B${r}>='기준정보'!$B$5,B${r}<='기준정보'!$B$6),1,0)`,`=IF('생산원본'!N${r}="완료",1,0)`,
`=IF(AND(W${r}=1,X${r}=1),Q${r}-R${r},0)`,`=IF(G${r}=0,"시간 없음",ROUND(F${r}/G${r},2))`,
`=IF(OR(J${r}>8,K${r}>3),"재검토","통과")`,`=IFERROR(VLOOKUP(D${r},'기준정보'!$A$14:$H$25,2,FALSE),"제품코드 확인")`,
`='생산원본'!L${r}`,`='생산원본'!E${r}`];});
formula('공정계산','A6',calc);
sheets.공정계산.getRange('B6:B365').setNumberFormat('yyyy-mm-dd');
sheets.공정계산.getRange('B:B').format.columnWidth=17;
sheets.공정계산.getRange('M6:O365').setNumberFormat('0.00%');sheets.공정계산.getRange('S6:S365').setNumberFormat('0.0%');
sheets.공정계산.getRange('Q6:R365').setNumberFormat('#,##0');sheets.공정계산.getRange('Y6:Y365').setNumberFormat('#,##0');
sheets.공정계산.getRange('V6:V365').conditionalFormats.add('containsText',{text:'확인',format:{fill:'#FCE8E6',font:{color:'#9B1C24'}}});

base('제품집계','사업장과 제품별 집계','보고 기간 내 완료 LOT만 집계합니다. 비율은 수량 합계의 비율로 계산하며 단순 평균으로 바꾸지 않습니다.',42,20);
const groups=sites.flatMap(site=>products.map(p=>[site,p[0]]));
const groupHeaders=['사업장','제품코드','제품명','완료LOT','투입수량','양품수량','가동시간(h)','생산수율','검사수량','불량수량','검사불량률','재작업수량','재작업비용','유효생산금액','실제UPH','수율확인LOT','목표수율','수율차이','품질판정','금액비중'];
table('제품집계',groupHeaders,groups.map(g=>[...g,...Array(18).fill(null)]),'ProductSummary');
const sumMetric=(r,column)=>`SUMIFS('공정계산'!$${column}$6:$${column}$365,'공정계산'!$C$6:$C$365,A${r},'공정계산'!$D$6:$D$365,B${r},'공정계산'!$W$6:$W$365,1,'공정계산'!$X$6:$X$365,1)`;
groups.forEach((g,i)=>{const r=i+6;formula('제품집계',`C${r}`,[ [
`=VLOOKUP(B${r},'기준정보'!$A$14:$H$25,2,FALSE)`,
`=COUNTIFS('공정계산'!$C$6:$C$365,A${r},'공정계산'!$D$6:$D$365,B${r},'공정계산'!$W$6:$W$365,1,'공정계산'!$X$6:$X$365,1)`,
`=${sumMetric(r,'E')}`,`=${sumMetric(r,'F')}`,`=${sumMetric(r,'G')}`,`=IF(E${r}=0,"대상 없음",ROUND(F${r}/E${r},6))`,
`=${sumMetric(r,'I')}`,`=${sumMetric(r,'J')}`,`=IF(I${r}=0,"대상 없음",ROUND(J${r}/I${r},6))`,
`=${sumMetric(r,'K')}`,`=${sumMetric(r,'R')}`,`=${sumMetric(r,'Y')}`,`=IF(G${r}=0,"대상 없음",ROUND(F${r}/G${r},2))`,
`=COUNTIFS('공정계산'!$C$6:$C$365,A${r},'공정계산'!$D$6:$D$365,B${r},'공정계산'!$W$6:$W$365,1,'공정계산'!$X$6:$X$365,1,'공정계산'!$V$6:$V$365,"수율 확인")`,
`=VLOOKUP(B${r},'기준정보'!$A$14:$H$25,5,FALSE)`,`=IF(E${r}=0,"대상 없음",ROUND(H${r}-Q${r},6))`,
`=IF(D${r}=0,"대상 없음",IF(P${r}>0,"확인 필요","정상"))`,`=IF(SUM($N$6:$N$41)=0,"대상 없음",N${r}/SUM($N$6:$N$41))`
] ]);});
for(const a of ['H','K','Q','R','T'])sheets.제품집계.getRange(`${a}6:${a}41`).setNumberFormat('0.00%');
sheets.제품집계.getRange('M6:N41').setNumberFormat('#,##0');

base('최종현황','생산과 품질 월간 현황','구조 분석 실습용 가상 데이터입니다. 기준정보의 기간을 변경해 결과 변화를 확인할 수 있습니다.',34,14);
sheets.최종현황.tabColor=c.navy;
write('최종현황','A6',[['지표','값','단위'],['완료 LOT',null,'건'],['투입수량',null,'개'],['양품수량',null,'개'],['생산수율',null,null],['유효생산금액',null,'원'],['재작업비용',null,'원'],['설비 전력비',null,'원']]);
formula('최종현황','B7',[['=SUM(\'제품집계\'!D6:D41)'],['=SUM(\'제품집계\'!E6:E41)'],['=SUM(\'제품집계\'!F6:F41)'],['=IF(B8=0,"대상 없음",ROUND(B9/B8,6))'],['=SUM(\'제품집계\'!N6:N41)'],['=SUM(\'제품집계\'!M6:M41)'],['=SUMIFS(\'설비원본\'!$I$6:$I$305,\'설비원본\'!$C$6:$C$305,">="&\'기준정보\'!$B$5,\'설비원본\'!$C$6:$C$305,"<="&\'기준정보\'!$B$6)*\'기준정보\'!$B$7']]);
write('최종현황','A17',[['사업장','완료LOT','양품수량','생산수율','유효생산금액','수율확인LOT'],...sites.map(s=>[s,null,null,null,null,null])]);
sites.forEach((s,i)=>{let r=18+i;formula('최종현황',`B${r}`,[[`=SUMIF('제품집계'!$A$6:$A$41,A${r},'제품집계'!$D$6:$D$41)`,`=SUMIF('제품집계'!$A$6:$A$41,A${r},'제품집계'!$F$6:$F$41)`,`=IF(B${r}=0,"대상 없음",C${r}/SUMIF('제품집계'!$A$6:$A$41,A${r},'제품집계'!$E$6:$E$41))`,`=SUMIF('제품집계'!$A$6:$A$41,A${r},'제품집계'!$N$6:$N$41)`,`=SUMIF('제품집계'!$A$6:$A$41,A${r},'제품집계'!$P$6:$P$41)`]]);});
write('최종현황','A24',[['실습 순서'],['1. 원본 3개 시트의 표와 열 의미를 확인합니다.'],['2. 공정계산에서 합산 조건과 제품 기준의 참조를 확인합니다.'],['3. 제품집계와 최종현황에 필요한 입력과 수식만 분리합니다.'],['4. 기준정보의 기간 또는 원본 수량을 바꾸고 결과를 비교합니다.'],['5. 검증표에서 원본 합계와 계산 결과의 차이를 확인합니다.']]);
for(const a of ['A6:C6','A17:F17'])sheets.최종현황.getRange(a).format={fill:c.navy,font:{bold:true,color:'#FFFFFF'},rowHeight:30};
sheets.최종현황.getRange('A:A').format.columnWidth=23;sheets.최종현황.getRange('B:B').format.columnWidth=20;
sheets.최종현황.getRange('B7:B13').setNumberFormat('#,##0');sheets.최종현황.getRange('B10').setNumberFormat('0.00%');
sheets.최종현황.getRange('D18:D20').setNumberFormat('0.00%');sheets.최종현황.getRange('E18:E20').setNumberFormat('#,##0');
sheets.최종현황.getRange('C18:C20').setNumberFormat('#,##0');
const chart=sheets.최종현황.charts.add('bar',[sheets.최종현황.getRange('A17:A20'),sheets.최종현황.getRange('C17:C20')]);
chart.setPosition('H6','N20');chart.title='사업장별 양품수량';chart.titleTextStyle.typeface='Malgun Gothic';chart.titleTextStyle.fontSize=13;
chart.hasLegend=false;chart.series.items[0].fill=c.blue;chart.xAxis={axisType:'textAxis',textStyle:{typeface:'Malgun Gothic',fontSize:10}};chart.yAxis={numberFormatCode:'#,##0',numberFormatSourceLinked:false,textStyle:{typeface:'Malgun Gothic',fontSize:10}};

base('검증표','계산 연결 확인','원본과 계산 결과의 독립 합계를 대조합니다. 이 시트는 업무 계산의 입력으로 사용하지 않습니다.',22,8);
write('검증표','A5',[['확인 항목','원본 기준','계산 결과','차이','상태'],['생산 원본 행 수',360,null,null,null],['품질 검사 행 수',480,null,null,null],['설비 원본 행 수',300,null,null,null],['투입수량',null,null,null,null],['양품수량',null,null,null,null],['검사수량',null,null,null,null],['불량수량',null,null,null,null],['기간 완료 LOT',null,null,null,null]]);
formula('검증표','C6',[['=COUNTA(\'생산원본\'!A6:A365)'],['=COUNTA(\'품질원본\'!A6:A485)'],['=COUNTA(\'설비원본\'!A6:A305)']]);
formula('검증표','B9',[['=SUM(\'생산원본\'!G6:G365)','=SUM(\'공정계산\'!E6:E365)'],['=SUM(\'생산원본\'!H6:H365)','=SUM(\'공정계산\'!F6:F365)'],['=SUM(\'품질원본\'!E6:E485)','=SUM(\'공정계산\'!I6:I365)'],['=SUM(\'품질원본\'!F6:F485)','=SUM(\'공정계산\'!J6:J365)'],['=COUNTIFS(\'생산원본\'!B6:B365,">="&\'기준정보\'!B5,\'생산원본\'!B6:B365,"<="&\'기준정보\'!B6,\'생산원본\'!N6:N365,"완료")','=SUM(\'제품집계\'!D6:D41)']]);
formula('검증표','D6',Array.from({length:8},(_,i)=>[`=C${i+6}-B${i+6}`,`=IF(D${i+6}=0,"일치","확인 필요")`]));
sheets.검증표.getRange('A:A').format.columnWidth=25;
sheets.검증표.getRange('A5:E5').format={fill:c.navy,font:{bold:true,color:'#FFFFFF'},rowHeight:30};
sheets.검증표.getRange('B6:D13').setNumberFormat('#,##0');
sheets.검증표.getRange('E6:E13').conditionalFormats.add('containsText',{text:'확인',format:{fill:'#FCE8E6',font:{color:'#9B1C24'}}});

// 기대값은 수식 엔진을 사용하지 않고 원본 배열의 조건 필터와 합산으로 계산합니다.
const selected=productions.map((p,i)=>({p,i})).filter(({p})=>p[1]>=dateAt(0)&&p[1]<=dateAt(30)&&p[13]==='완료');
const sum=(rows,fn)=>rows.reduce((total,row)=>total+fn(row),0);
const qByLot=lot=>qualities.filter(q=>q[1]===lot);
const expected={sheets:8,sourceRows:{생산원본:360,품질원본:480,설비원본:300},sourceColumns:{생산원본:32,품질원본:26,설비원본:28},
  headline:{B7:selected.length,B8:sum(selected,({p})=>p[6]),B9:sum(selected,({p})=>p[7]),B11:sum(selected,({p})=>p[7]*products.find(x=>x[0]===p[3])[3]-sum(qByLot(p[0]).filter(q=>q[19]==='완료'),q=>q[6])*800),B12:sum(selected,({p})=>sum(qByLot(p[0]).filter(q=>q[19]==='완료'),q=>q[6])*800),B13:sum(equipment.filter(e=>e[2]>=dateAt(0)&&e[2]<=dateAt(30)),e=>e[8])*150}};
expected.headline.B10=round(expected.headline.B9/expected.headline.B8,6);
await fs.writeFile(path.join(work,'expected.json'),JSON.stringify(expected,null,2));
workbook.recalculate();
const inspection=await workbook.inspect({kind:'table',range:'최종현황!A6:C13',include:'values,formulas',tableMaxRows:8,tableMaxCols:3,maxChars:5000});
await fs.writeFile(path.join(work,'headline-inspect.ndjson'),inspection.ndjson);
for(const [cell,want] of Object.entries(expected.headline)){
  const value=sheets.최종현황.getRange(cell).values[0][0];
  if(typeof value!=='number'||Math.abs(value-want)>Math.max(0.000001,Math.abs(want)*1e-10))throw new Error(`${cell} expected ${want}, actual ${JSON.stringify(value)}`);
}
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:40},maxChars:5000,summary:'final formula error scan'});
await fs.writeFile(path.join(work,'formula-error-scan.ndjson'),errors.ndjson);
for(const name of names){
  const png=await workbook.render({sheetName:name,range:name==='최종현황'?'A1:N31':'A1:H17',scale:1.5,format:'png'});
  await fs.writeFile(path.join(work,`${name}.png`),new Uint8Array(await png.arrayBuffer()));
}
const result=await SpreadsheetFile.exportXlsx(workbook);
const filename=path.join(output,'생산품질_8시트_복합수식_실습.xlsx');await result.save(filename);
await fs.writeFile(path.join(work,'build-result.json'),JSON.stringify({file:filename,expected,artifactHeadlinesMatch:true,source:'Deterministic synthetic data only'},null,2));
console.log(JSON.stringify({file:filename,headline:expected.headline,sheets:8,sourceRows:1140}));
