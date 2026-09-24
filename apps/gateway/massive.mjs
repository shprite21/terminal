import {setTimeout as pause} from 'node:timers/promises';
import {validateBars} from '../web/lib/quant.ts';

const day=(ms)=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(ms));
export function parseMassive(aggregate,splits,dividends,instrument,now=Date.now()){
  if(aggregate.ticker!==instrument.symbol||aggregate.adjusted!==false||!Array.isArray(aggregate.results)||!aggregate.results.length)throw new Error('Massive returned no matching unadjusted history.');
  const today=day(now),bars=aggregate.results.filter(r=>day(r.t)<today).map(r=>({date:day(r.t),open:r.o,high:r.h,low:r.l,close:r.c,volume:r.v,splitRatio:1,dividend:0}));
  validateBars(bars);
  const byDate=new Map(bars.map(b=>[b.date,b]));
  for(const split of splits){
    if(split.ticker!==instrument.symbol)throw new Error('Split ticker mismatch.');
    const ratio=split.split_to/split.split_from;
    if(!Number.isFinite(ratio)||ratio<=0)throw new Error('Missing or invalid split ratio.');
    const bar=byDate.get(split.execution_date);
    if(bar)bar.splitRatio*=ratio;
    else if(split.execution_date>=bars[0].date&&split.execution_date<=bars.at(-1).date)throw new Error('Split event has no matching daily bar.');
  }
  for(const dividend of dividends){
    if(dividend.ticker!==instrument.symbol||dividend.currency!==instrument.currency||!Number.isFinite(dividend.cash_amount)||dividend.cash_amount<0)throw new Error('Dividend currency or amount could not be validated.');
    const bar=byDate.get(dividend.ex_dividend_date);
    if(bar)bar.dividend+=dividend.cash_amount;
    else if(dividend.ex_dividend_date>=bars[0].date&&dividend.ex_dividend_date<=bars.at(-1).date)throw new Error('Dividend event has no matching daily bar.');
  }
  validateBars(bars);
  const chartBars=bars.map(b=>({...b}));let factor=1;
  for(let i=bars.length-1;i>=0;i--){const b=bars[i];chartBars[i]={...b,open:b.open/factor,high:b.high/factor,low:b.low/factor,close:b.close/factor,volume:b.volume*factor};factor*=b.splitRatio;}
  return {instrument,source:'Massive · US daily aggregates',fetchedAt:new Date(now).toISOString(),asOf:bars.at(-1).date,interval:'1d',bars,chartBars,priceBasis:'Unadjusted historical share prices; split-adjusted chart',warnings:['Completed daily aggregates only; not executable real-time quotes.','Current listing universe; historical constituents and delisted coverage are not loaded.','Dividends accrue on ex-date as non-reinvestable receivables; pay dates, tax withholding, and special corporate actions are not modeled.']};
}
export class MassiveAdapter{
  constructor({apiKey=process.env.MASSIVE_API_KEY||'',request=fetch,now=()=>Date.now(),sleep=pause}={}){this.apiKey=apiKey;this.request=request;this.now=now;this.sleep=sleep;this.verified=false;this.checkedAt=null;this.nextSlot=0;this.error=null;}
  status(){return {connected:!!this.apiKey&&this.verified,state:this.verified?'connected':this.apiKey?'verification_required':'api_key_required',mode:'US daily history · 2-year window',checkedAt:this.checkedAt,message:this.error,configured:!!this.apiKey};}
  async get(endpoint,key=this.apiKey){
    if(!key)throw new Error('Connect Massive in Connections using your API key.');
    const url=new URL(endpoint,'https://api.massive.com');
    if(url.origin!=='https://api.massive.com'||url.username||url.password||!/^\/(v2\/aggs\/ticker\/|v3\/reference\/tickers|stocks\/v1\/(splits|dividends))/.test(url.pathname))throw new Error('Unexpected Massive pagination URL.');
    url.searchParams.delete('apiKey');
    const wait=Math.max(0,this.nextSlot-this.now());
    if(wait>90000)throw new Error('Massive request queue is full. Wait for the current history request to finish.');
    this.nextSlot=Math.max(this.now(),this.nextSlot)+12500;
    if(wait)await this.sleep(wait);
    if(key!==this.apiKey)throw new Error('Massive session changed. Retry the request.');
    let response;
    try{response=await this.request(url,{headers:{Accept:'application/json',Authorization:`Bearer ${key}`},redirect:'error',signal:AbortSignal.timeout(20000)});}catch{throw new Error('Massive is unreachable. Check your network connection.');}
    if(!response.ok){
      const message=response.status===401?'Massive rejected the API key. Reconnect in Connections.':response.status===403?'Your Massive plan does not include this dataset or date range.':response.status===429?'Massive rate limit reached. Wait one minute and retry.':`Massive returned HTTP ${response.status}.`;
      if(response.status===401){this.verified=false;this.error=message;}if(response.status===429)this.nextSlot=Math.max(this.nextSlot,this.now()+60000);
      throw new Error(message);
    }
    // Never return provider error bodies: they may echo credentials or request URLs.
    if(Number(response.headers.get('content-length'))>6000000)throw new Error('Massive response exceeds the size limit.');
    const reader=response.body.getReader(),parts=[];let size=0;
    while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>6000000){await reader.cancel();throw new Error('Massive response exceeds the size limit.');}parts.push(Buffer.from(value));}
    let data;try{data=JSON.parse(Buffer.concat(parts).toString('utf8'));}catch{throw new Error('Massive returned an invalid response.');}
    if(!['OK','DELAYED'].includes(data.status))throw new Error('Massive did not return a successful data response.');
    if(key!==this.apiKey)throw new Error('Massive session changed. Retry the request.');
    this.verified=true;this.checkedAt=new Date(this.now()).toISOString();this.error=null;return data;
  }
  async connect({apiKey}){
    if(typeof apiKey!=='string'||! /^[A-Za-z0-9_-]{8,200}$/.test(apiKey.trim()))throw new Error('Enter your Massive API key.');
    const key=apiKey.trim();this.apiKey=key;this.verified=false;
    try{await this.get('/v3/reference/tickers?ticker=NVDA&market=stocks&active=true&limit=1');return this.status();}catch(e){if(this.apiKey===key){this.apiKey='';this.verified=false;this.error=e.message;}throw e;}
  }
  disconnect(){this.apiKey='';this.verified=false;this.error=null;return this.status();}
  async pages(endpoint){let result,first;const results=[],seen=new Set();
    for(let page=0;endpoint&&page<30;page++){
      if(seen.has(endpoint))throw new Error('Repeated Massive pagination cursor.');seen.add(endpoint);
      result=await this.get(endpoint);first??=result;if(!Array.isArray(result.results)){
        if(result.resultsCount===0||result.count===0)return {...first,results};
        throw new Error('Massive results are missing.');
      }
      results.push(...result.results);if(results.length>20000)throw new Error('Massive dataset is too large.');endpoint=result.next_url;
    }
    if(endpoint)throw new Error('Massive pagination limit reached; partial history was not accepted.');return {...first,results};
  }
  async history(instrument){
    if(instrument.market!=='US')throw new Error('Massive covers US stocks only. Import real NSE history from CSV under Data.');
    if(!this.apiKey)throw new Error('Connect Massive in Connections using your API key.');
    const end=day(this.now()-86400000),start=day(this.now()-729*86400000),ticker=encodeURIComponent(instrument.symbol);
    const aggregate=await this.pages(`/v2/aggs/ticker/${ticker}/range/1/day/${start}/${end}?adjusted=false&sort=asc&limit=50000`);
    const splits=await this.pages(`/stocks/v1/splits?ticker=${ticker}&execution_date.gte=${start}&execution_date.lte=${end}&sort=execution_date.asc&limit=5000`);
    const dividends=await this.pages(`/stocks/v1/dividends?ticker=${ticker}&ex_dividend_date.gte=${start}&ex_dividend_date.lte=${end}&sort=ex_dividend_date.asc&limit=5000`);
    return parseMassive(aggregate,splits.results,dividends.results,instrument,this.now());
  }
}
