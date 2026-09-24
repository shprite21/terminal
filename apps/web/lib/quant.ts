// Pure research calculations. Callers must supply an explicit, validated dataset.
export type Bar = { date: string; open: number; high: number; low: number; close: number; volume: number; splitRatio?: number; dividend?: number };
export type StrategyKind = 'SMA crossover' | 'RSI mean reversion' | 'Bollinger mean reversion' | 'Breakout' | 'Time-series momentum';
export const kinds: StrategyKind[] = ['SMA crossover', 'RSI mean reversion', 'Bollinger mean reversion', 'Breakout', 'Time-series momentum'];
export type Strategy = { id: string; name: string; kind: StrategyKind; symbol: string; lookback: number; slow: number; capital: number; costBps: number; allocation: number; version: number };
export type Trade = { date: string; side: 'BUY' | 'SELL'; price: number; quantity: number; fee: number; pnl: number | null };
export type Result = { id: string; strategy: Strategy; fingerprint: string; dataVersion: string; createdAt: string; equity: { date: string; value: number; benchmark: number; drawdown: number }[]; trades: Trade[]; metrics: { totalReturn: number; cagr: number; sharpe: number; volatility: number; maxDrawdown: number; winRate: number; fees: number; exposure: number }; finalCash: number; finalQuantity: number; dividendReceivable: number; corporateActions: {date:string;type:string;amount:number}[]; source?: string; priceBasis?: string; dataWarnings?: string[] };
export function mean(a: number[]) { return a.reduce((s,x) => s+x,0) / (a.length || 1); }
export function std(a: number[]) { const m = mean(a); return Math.sqrt(mean(a.map(x => (x-m)**2))); }
export function rsi(closes: number[], period = 14) {
  if (closes.length <= period) return 50;
  const deltas = closes.slice(-period-1).slice(1).map((p,i) => p - closes[closes.length-period-1+i]);
  const up = mean(deltas.map(x => Math.max(x,0))), down = mean(deltas.map(x => Math.max(-x,0)));
  return down === 0 ? (up === 0 ? 50 : 100) : 100 - 100/(1+up/down);
}
export function signalAt(bars: Bar[], index: number, strategy: Strategy, holding: boolean) {
  const {lookback, slow, kind} = strategy;
  if (index < Math.max(lookback, kind === 'SMA crossover' ? slow : lookback)) return false;
  // Adjust only for splits known by this signal date.
  let splitFactor=1;
  const closes=bars.slice(0,index+1).map(b=>b.close);
  for(let j=index;j>=0;j--){closes[j]/=splitFactor;splitFactor*=bars[j].splitRatio??1;}
  const last = closes[index], window = closes.slice(-lookback);
  if (kind === 'SMA crossover') return mean(window) > mean(closes.slice(-slow));
  if (kind === 'RSI mean reversion') { const value = rsi(closes,lookback); return holding ? value < 55 : value < 30; }
  if (kind === 'Bollinger mean reversion') return holding ? last < mean(window) : last < mean(window) - 2*std(window);
  if (kind === 'Breakout') return holding ? last > mean(window) : last > Math.max(...closes.slice(index-lookback,index));
  return last > closes[index-lookback];
}
export function validateStrategy(s: Strategy) {
  if (!s || !kinds.includes(s.kind) || typeof s.symbol !== 'string' || !/^[A-Z0-9^][A-Z0-9.^&_-]{0,39}$/.test(s.symbol)) throw new Error('Choose a supported strategy and instrument.');
  if (!Number.isInteger(s.lookback) || s.lookback < 2 || s.lookback > 100) throw new Error('Lookback must be an integer from 2 to 100.');
  if (!Number.isInteger(s.slow) || s.slow < 3 || s.slow > 200 || (s.kind === 'SMA crossover' && s.slow <= s.lookback)) throw new Error('Slow window must exceed the fast window and be at most 200.');
  if (![s.capital,s.costBps,s.allocation].every(Number.isFinite) || s.capital < 1000 || s.capital > 100000000 || s.costBps < 0 || s.costBps > 200 || s.allocation <= 0 || s.allocation > 1) throw new Error('Check capital, costs, and allocation limits.');
  if (typeof s.name !== 'string' || !s.name.trim() || s.name.length > 100) throw new Error('Provide a strategy name of 1–100 characters.');
}
export function backtest(strategy: Strategy, bars: Bar[], dataVersion = "explicit-input"): Result {
  validateStrategy(strategy);
  validateBars(bars);
  if(bars.length < Math.max(strategy.lookback,strategy.kind==='SMA crossover'?strategy.slow:strategy.lookback)+2) throw new Error('Insufficient historical bars for this strategy.');
  let cash = strategy.capital, quantity = 0, basis = 0, peak = cash, fees = 0, exposed = 0;
  let dividendReceivable=0, benchmarkQuantity=strategy.capital/bars[0].close, benchmarkDividends=0;
  const corporateActions: Result['corporateActions']=[];
  const trades: Trade[] = [], equity: Result['equity'] = [];
  const rate = strategy.costBps / 10000;
  for (let i=0;i<bars.length;i++) {
    const bar = bars[i];
    if(i>0){
      const ratio=bar.splitRatio??1;
      if(ratio!==1){
        const exact=quantity*ratio, whole=Math.floor(exact+1e-9), fraction=Math.max(0,exact-whole);
        const amount=fraction*bar.open;
        cash+=amount;if(exact>0)basis*=whole/exact;quantity=whole;
        benchmarkQuantity*=ratio;
        corporateActions.push({date:bar.date,type:'Split; fractional shares paid at open',amount});
      }
      const dividend=bar.dividend??0;
      if(dividend>0){
        const amount=quantity*dividend;dividendReceivable+=amount;benchmarkDividends+=benchmarkQuantity*dividend;
        corporateActions.push({date:bar.date,type:'Dividend receivable; not available to reinvest',amount});
      }
    }
    // Use the preceding close only; execute at the following open, including costs.
    if (i > 0) {
      const buy = signalAt(bars,i-1,strategy,quantity>0);
      if (buy && quantity===0) {
        quantity = Math.floor(cash * strategy.allocation / (bar.open*(1+rate)));
        if (quantity>0) { const fee=quantity*bar.open*rate; basis=quantity*bar.open+fee; cash-=basis; fees+=fee; trades.push({date:bar.date,side:'BUY',price:bar.open,quantity,fee,pnl:null}); }
      } else if (!buy && quantity>0) {
        const fee=quantity*bar.open*rate, proceeds=quantity*bar.open-fee;
        trades.push({date:bar.date,side:'SELL',price:bar.open,quantity,fee,pnl:proceeds-basis});
        cash+=proceeds; fees+=fee; quantity=0; basis=0;
      }
    }
    if (quantity>0) exposed++;
    const value=cash+quantity*bar.close+dividendReceivable; peak=Math.max(peak,value);
    equity.push({date:bar.date,value,benchmark:benchmarkQuantity*bar.close+benchmarkDividends,drawdown:value/peak-1});
  }
  const returns=equity.slice(1).map((p,i)=>p.value/equity[i].value-1), deviation=std(returns), closed=trades.filter(t=>t.pnl!==null);
  const final=equity[equity.length-1].value;
  const canonical=JSON.stringify({strategy,dataVersion,bars});
  let hash=2166136261; for (const c of canonical) { hash^=c.charCodeAt(0); hash=Math.imul(hash,16777619); }
  return {id:`bt-${(hash>>>0).toString(16)}`,strategy:{...strategy},fingerprint:(hash>>>0).toString(16).padStart(8,'0'),dataVersion,createdAt:new Date().toISOString(),equity,trades,finalCash:cash,finalQuantity:quantity,dividendReceivable,corporateActions,metrics:{totalReturn:final/strategy.capital-1,cagr:(final/strategy.capital)**(365.25/((Date.parse(bars.at(-1)!.date)-Date.parse(bars[0].date))/86400000))-1,sharpe:deviation===0?0:mean(returns)/deviation*Math.sqrt(252),volatility:deviation*Math.sqrt(252),maxDrawdown:Math.min(...equity.map(p=>p.drawdown)),winRate:closed.length?closed.filter(t=>(t.pnl??0)>0).length/closed.length:0,fees,exposure:exposed/bars.length}};
}
export const starterStrategies: Strategy[] = [
  { id:'momentum', name:'US momentum',kind:'Time-series momentum',symbol:'QQQ',lookback:40,slow:80,capital:100000,costBps:10,allocation:.95,version:1 },
  { id:'breakout', name:'NVDA breakout',kind:'Breakout',symbol:'NVDA',lookback:20,slow:50,capital:100000,costBps:15,allocation:.75,version:1 },
  { id:'reversion', name:'Reliance mean reversion',kind:'RSI mean reversion',symbol:'RELIANCE.NS',lookback:14,slow:50,capital:1000000,costBps:15,allocation:.8,version:1 },
  { id:'trend', name:'Technology trend',kind:'SMA crossover',symbol:'QQQ',lookback:20,slow:50,capital:100000,costBps:10,allocation:.95,version:1 },
];

export function validateBars(bars: Bar[]) {
  if(!Array.isArray(bars)||bars.length<3||bars.length>20000) throw new Error('Provide 3–20,000 actual daily bars.');
  for(let i=0;i<bars.length;i++){
    const b=bars[i];
    if(!b||!/^\d{4}-\d{2}-\d{2}$/.test(b.date)||!Number.isFinite(Date.parse(b.date))||new Date(b.date).toISOString().slice(0,10)!==b.date||
      ![b.open,b.high,b.low,b.close,b.volume].every(Number.isFinite)||Math.min(b.open,b.high,b.low,b.close)<=0||b.volume<0||
      b.high<Math.max(b.open,b.close)||b.low>Math.min(b.open,b.close)||b.low>b.high||
      (i>0&&b.date<=bars[i-1].date)||(b.splitRatio!==undefined&&(!Number.isFinite(b.splitRatio)||b.splitRatio<=0))||
      (b.dividend!==undefined&&(!Number.isFinite(b.dividend)||b.dividend<0)))throw new Error('Bars must have valid ISO dates, OHLCV, corporate actions, and strictly increasing dates.');
  }
}
