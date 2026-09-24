import {createHash} from 'node:crypto';
import {mkdir,readFile,writeFile,rename} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {validateBars,validateStrategy} from '../web/lib/quant.ts';
import {MassiveAdapter} from './massive.mjs';
import {quantPool} from './quant-pool.mjs';

const directory=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../.data/market');
const sources=[
  {name:'Nasdaq directory',url:'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt',market:'US',delimiter:'|',type:'Equity'},
  {name:'NSE equities',url:'https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv',market:'IN',type:'Equity'},
  {name:'NSE ETFs',url:'https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv',market:'IN',type:'ETF'},
  {name:'NSE SME',url:'https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv',market:'IN',type:'SME'},
];
export function parseDelimited(text,delimiter=','){
  const rows=[];let row=[],field='',quoted=false;
  for(let i=0;i<text.length;i++){
    const c=text[i];
    if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}
    else if(c===delimiter&&!quoted){row.push(field.trim());field='';}
    else if(c==='\n'&&!quoted){row.push(field.trim());if(row.some(Boolean))rows.push(row);row=[];field='';}
    else if(c!=='\r')field+=c;
  }
  if(quoted)throw new Error('Unclosed CSV quote.');
  if(field||row.length){row.push(field.trim());rows.push(row);}
  const header=rows.shift()?.map(h=>h.replace(/^\uFEFF/,'').trim().toUpperCase());
  if(!header)throw new Error('The data file is empty.');
  return rows.map(r=>Object.fromEntries(header.map((h,i)=>[h,r[i]??''])));
}
export function parseCatalogue(text,source){
  const rows=parseDelimited(text,source.delimiter),items=[];
  for(const row of rows){
    const ticker=row.SYMBOL;
    if(!ticker||! /^[A-Z0-9][A-Z0-9.&_-]{0,29}$/.test(ticker)||row['TEST ISSUE']==='Y')continue;
    const name=row['SECURITY NAME']||row['NAME OF COMPANY']||row['NAME_OF_COMPANY']||row['SECURITYNAME']||row['NAME OF THE COMPANY']||row['SECURITY']||row['NAME OF SECURITY'];
    if(!name)continue;
    items.push({symbol:source.market==='IN'?ticker+'.NS':ticker,name,market:source.market,exchange:source.market==='IN'?'NSE':'NASDAQ',currency:source.market==='IN'?'INR':'USD',type:row.ETF==='Y'?'ETF':source.market==='US'?'Listed security':source.type,isin:row['ISIN NUMBER']||row.ISIN_NUMBER||row.ISINNUMBER||row.ISIN||undefined,sector:'Not supplied'});
  }
  if(!items.length)throw new Error('Exchange directory format was not recognized.');
  return items;
}
export async function fetchText(url,maxBytes=6000000){
  const response=await fetch(url,{signal:AbortSignal.timeout(20000),redirect:'error',headers:{Accept:'application/json,text/csv,text/plain'}});
  if(!response.ok)throw new Error(`Data source returned HTTP ${response.status}.`);
  if(Number(response.headers.get('content-length'))>maxBytes)throw new Error('Source file exceeds the size limit.');
  const reader=response.body.getReader();const chunks=[];let size=0;
  while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>maxBytes){await reader.cancel();throw new Error('Source file exceeds the size limit.');}chunks.push(Buffer.from(value));}
  return Buffer.concat(chunks).toString('utf8');
}
const dateAt=(time,zone)=>new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(time*1000));
export function parseHistoryCsv(csv,instrument,source,now=Date.now()){
  if(typeof csv!=='string'||csv.length>4000000)throw new Error('CSV must be under 4 MB.');
  if(typeof source!=='string'||!source.trim()||source.length>150)throw new Error('Name the actual data source.');
  const number=(row,key,optional=false)=>{if(!row[key]?.trim()){if(optional)return undefined;throw new Error(`CSV is missing ${key}.`);}const value=Number(row[key]);if(!Number.isFinite(value))throw new Error(`CSV has invalid ${key}.`);return value;};
  const bars=parseDelimited(csv).map(row=>({date:row.DATE,open:number(row,'OPEN'),high:number(row,'HIGH'),low:number(row,'LOW'),close:number(row,'CLOSE'),volume:number(row,'VOLUME'),splitRatio:number(row,'SPLIT_RATIO',true),dividend:number(row,'DIVIDEND',true)}));
  validateBars(bars);
  if(bars.at(-1).date>=dateAt(now/1000,instrument.market==='IN'?'Asia/Kolkata':'America/New_York'))throw new Error('Import completed historical dates only; today and future dates are not accepted.');
  let factor=1;const chartBars=bars.map(b=>({...b}));
  for(let i=bars.length-1;i>=0;i--){const b=bars[i];chartBars[i]={...b,open:b.open/factor,high:b.high/factor,low:b.low/factor,close:b.close/factor,volume:b.volume*factor};factor*=b.splitRatio??1;}
  return {instrument,source:`CSV · ${source.trim()}`,fetchedAt:new Date(now).toISOString(),asOf:bars.at(-1).date,interval:'1d',bars,chartBars,priceBasis:'User-declared unadjusted OHLC with optional split_ratio and dividend',warnings:['User-provided historical data; provenance and corporate-action completeness have not been independently verified.','Dividends are non-reinvestable receivables; payment dates are not modeled.']};
}
export class MarketDataService{
  constructor({root=directory,request=fetchText,now=()=>Date.now(),massive=new MassiveAdapter()}={}){this.massive=massive;this.root=root;this.request=request;this.now=now;this.pending=new Map();}
  async read(name){try{return JSON.parse(await readFile(path.join(this.root,name+'.json'),'utf8'));}catch{return null;}}
  async write(name,value){await mkdir(this.root,{recursive:true});const target=path.join(this.root,name+'.json'),temp=target+'.'+crypto.randomUUID()+'.tmp';await writeFile(temp,JSON.stringify(value));await rename(temp,target);}
  async once(key,fn){if(this.pending.has(key))return this.pending.get(key);const p=fn().finally(()=>this.pending.delete(key));this.pending.set(key,p);return p;}
  catalogue(refresh=false){return this.once('catalogue',async()=>{
    const all=[],statuses=[];
    for(const source of sources){
      let cached=await this.read('directory-'+source.name.replaceAll(' ','-'));
      if(refresh||!cached||this.now()-Date.parse(cached.fetchedAt)>86400000){
        try{const instruments=parseCatalogue(await this.request(source.url),source);cached={instruments,fetchedAt:new Date(this.now()).toISOString()};await this.write('directory-'+source.name.replaceAll(' ','-'),cached);statuses.push({name:source.name,count:instruments.length,asOf:cached.fetchedAt,status:'current'});}
        catch(e){statuses.push({name:source.name,count:cached?.instruments.length||0,asOf:cached?.fetchedAt||null,status:cached?'cached':'unavailable',error:e.message});}
      }else statuses.push({name:source.name,count:cached.instruments.length,asOf:cached.fetchedAt,status:'cached'});
      if(cached)all.push(...cached.instruments);
    }
    return {instruments:[...new Map(all.map(i=>[i.symbol,i])).values()].sort((a,b)=>a.symbol.localeCompare(b.symbol)),sources:statuses,fetchedAt:new Date(this.now()).toISOString()};
  });}
  async resolve(symbol,allowUnlisted=false,synthetic=false){
    if(typeof symbol!=='string'||! /^[A-Z0-9][A-Z0-9.^&_-]{0,39}$/.test(symbol))throw new Error('Choose a catalogue instrument.');
    if(synthetic)return {symbol,name:`SYNTHETIC · ${symbol} scenario`,market:symbol.endsWith('.NS')?'IN':'US',currency:symbol.endsWith('.NS')?'INR':'USD',exchange:'Modeled weekdays',type:'Synthetic scenario',sector:'Not applicable'};
    const instrument=(await this.catalogue()).instruments.find(i=>i.symbol===symbol);
    if(!instrument&&allowUnlisted)return {symbol,name:symbol,market:symbol.endsWith('.NS')?'IN':'US',currency:symbol.endsWith('.NS')?'INR':'USD',exchange:'Provider history',type:'Requested symbol',sector:'Not supplied'};
    if(!instrument)throw new Error('Instrument is not in the available Nasdaq/NSE catalogue. Refresh Data sources.');
    return instrument;
  }
  async saveDataset(data){
    const id=createHash('sha256').update(JSON.stringify({instrument:data.instrument,source:data.source,priceBasis:data.priceBasis,bars:data.bars})).digest('hex');
    const existing=await this.read('dataset-'+id);if(existing)return existing;
    const snapshot={...data,id};await this.write('dataset-'+id,snapshot);return snapshot;
  }
  history(symbol,refresh=false,source='massive'){
    if(!['massive','yahoo','synthetic','csv'].includes(source))throw new Error('Select Massive, Yahoo, Synthetic or imported CSV.');
    return this.once('history-'+source+'-'+symbol,async()=>{
    const instrument=await this.resolve(symbol,true,source==='synthetic'),suffix=createHash('sha256').update(symbol).digest('hex'),key='latest-'+source+'-'+suffix;
    const pointer=await this.read(key)||(['massive','csv'].includes(source)?await this.read('latest-'+suffix):null),snapshot=pointer&&await this.read('dataset-'+pointer.id),cached=(source==='massive'?snapshot?.source?.startsWith('Massive'):source==='csv'?snapshot?.source?.startsWith('CSV'):snapshot?.provider===source)?snapshot:null;
    if(source==='csv'){if(cached)return {...cached,cached:true};throw new Error('No imported CSV for this symbol. Import it under Data.');}
    if(cached&&!refresh&&(cached.source.startsWith('CSV')||this.now()-Date.parse(pointer.checkedAt||cached.fetchedAt)<4*3600000))return {...cached,cached:true};
    try{
      let fetched;
      if(source==='massive')fetched=await this.massive.history(instrument);
      else {
        if(!this.alternateHistory)throw new Error('Research engine provider bridge unavailable.');
        fetched=await this.alternateHistory(symbol,source);
        validateBars(fetched.bars);
        if(fetched.currency!==instrument.currency)throw new Error('Provider currency does not match the catalogue instrument.');
        fetched={...fetched,instrument,interval:'1d',asOf:fetched.bars.at(-1).date,fetchedAt:new Date(this.now()).toISOString()};
      }
      const data=await this.saveDataset({...fetched,provider:source,synthetic:source==='synthetic'});await this.write(key,{id:data.id,checkedAt:new Date(this.now()).toISOString()});return data;
    }catch(e){if(cached)return {...cached,cached:true,stale:true,warnings:[...cached.warnings,`Refresh failed: ${e.message}`]};throw new Error(`History unavailable for ${symbol}: ${e.message}`);}
  });}
  async importCsv({symbol,csv,source,unadjustedConfirmed}){if(unadjustedConfirmed!==true)throw new Error('Confirm the CSV contains real unadjusted historical prices.');const data=await this.saveDataset(parseHistoryCsv(csv,await this.resolve(symbol),source,this.now()));await this.write('latest-csv-'+createHash('sha256').update(symbol).digest('hex'),{id:data.id});return data;}
  async run({strategy,datasetId,source='massive'}){
    validateStrategy(strategy);let dataset;
    if(datasetId){if(!/^[a-f0-9]{64}$/.test(datasetId))throw new Error('Invalid dataset version.');dataset=await this.read('dataset-'+datasetId);if(!dataset)throw new Error('Dataset snapshot is unavailable.');}
    else dataset=await this.history(strategy.symbol,false,source);
    if(dataset.instrument.symbol!==strategy.symbol)throw new Error('Dataset does not match the strategy instrument.');
    const result=await quantPool.run(strategy,dataset.bars,dataset.id);result.source=dataset.source;
    result.dataWarnings=dataset.warnings;result.priceBasis=dataset.priceBasis;
    const id=createHash('sha256').update(JSON.stringify({strategy,datasetId:dataset.id,engine:'q21-corporate-actions-v1'})).digest('hex');result.id='bt-'+id;result.fingerprint=id;
    await this.write(result.id,{...result,datasetId:dataset.id});return result;
  }
}
