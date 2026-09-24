"use client";
import { useId, useState } from 'react';
import type { Bar } from '@/lib/quant';
export function Sparkline({values,color='#4c88ff'}:{values:number[];color?:string}) {
  const min=Math.min(...values),range=Math.max(...values)-min||1;
  return <svg className="sparkline" viewBox="0 0 100 32" aria-hidden="true"><path d={values.map((x,i)=>`${i?'L':'M'}${i/(values.length-1)*100},${29-(x-min)/range*26}`).join(' ')} fill="none" stroke={color} strokeWidth="1.7" /></svg>;
}
export function EquityChart({data,drawdown=false}:{data:{date:string;value:number;benchmark?:number}[];drawdown?:boolean}) {
  const id=useId().replaceAll(':',''), [hover,setHover]=useState<number|null>(null);
  const values=data.flatMap(d=>d.benchmark===undefined?[d.value]:[d.value,d.benchmark]);
  const min=Math.min(...values),max=Math.max(...values),range=max-min||1;
  const x=(i:number)=>i/Math.max(1,data.length-1)*880+8, y=(n:number)=>230-(n-min)/range*195;
  const path=(benchmark=false)=>data.map((d,i)=>`${i?'L':'M'}${x(i)},${y(benchmark?(d.benchmark??d.value):d.value)}`).join(' ');
  const focus=hover===null?null:data[hover];
  return <div className="equity-chart" onMouseLeave={()=>setHover(null)}>
    {focus&&<div className="chart-tooltip">{focus.date}<strong>{drawdown?'Drawdown':'Strategy'}: {drawdown?`${(focus.value*100).toFixed(2)}%`:focus.value.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</strong>{!drawdown&&focus.benchmark!==undefined&&Number.isFinite(focus.benchmark)&&<strong>Benchmark · buy & hold: {focus.benchmark.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</strong>}</div>}
    <svg viewBox="0 0 960 274" role="img" aria-label={drawdown?'Strategy drawdown chart':'Strategy equity curve and buy-and-hold benchmark'} onMouseMove={e=>{const rect=e.currentTarget.getBoundingClientRect();setHover(Math.max(0,Math.min(data.length-1,Math.round(((e.clientX-rect.left)/rect.width*960-8)/880*(data.length-1)))));}}>
      <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={drawdown?'#ec737e':'#2376ff'} stopOpacity=".28"/><stop offset="100%" stopColor="#176bff" stopOpacity="0"/></linearGradient></defs>
      {[0,.25,.5,.75,1].map(t=><g key={t}><line x1="8" x2="895" y1={35+t*195} y2={35+t*195} stroke="#1a2332" strokeDasharray="3 5"/><text x="909" y={39+t*195} fill="#788499" fontSize="12">{drawdown?`${((max-t*range)*100).toFixed(0)}%`:`${((max-t*range)/1000).toFixed(1)}k`}</text></g>)}
      <path d={`${path()} L${x(data.length-1)},235 L8,235 Z`} fill={`url(#${id})`}/>
      {data[0]?.benchmark!==undefined&&<path d={path(true)} fill="none" stroke="#626e83" strokeWidth="1.5" strokeDasharray="5 5"/>}
      <path d={path()} fill="none" stroke={drawdown?'#ec737e':'#3c83ff'} strokeWidth="2.6" strokeLinejoin="round"/>
      {[0,.2,.4,.6,.8,1].map(t=>{const i=Math.round(t*(data.length-1));return <text key={t} x={x(i)} y="262" textAnchor={t===0?'start':t===1?'end':'middle'} fill="#788499" fontSize="12">{data[i]?.date.slice(0,7)}</text>;})}
      {hover!==null&&focus&&<g><line x1={x(hover)} x2={x(hover)} y1="25" y2="237" stroke="#5f7291" strokeDasharray="3 3"/><circle cx={x(hover)} cy={y(focus.value)} r="4" fill="#75a8ff" stroke="#0b1018" strokeWidth="2"/>{!drawdown&&focus.benchmark!==undefined&&Number.isFinite(focus.benchmark)&&<circle cx={x(hover)} cy={y(focus.benchmark)} r="4" fill="#626e83" stroke="#0b1018" strokeWidth="2"/>}</g>}
    </svg>
  </div>;
}
export function CandleChart({bars}:{bars:Bar[]}) {
  const data=bars.slice(-70), low=Math.min(...data.map(b=>b.low)),high=Math.max(...data.map(b=>b.high)),range=high-low||1;
  const y=(v:number)=>250-(v-low)/range*220;
  return <svg className="candle-chart" viewBox="0 0 900 320" role="img" aria-label="Historical daily candlestick chart">
    {[0,.25,.5,.75,1].map(t=><g key={t}><line x1="10" x2="822" y1={30+t*220} y2={30+t*220} stroke="#1b2433" strokeDasharray="3 5"/><text x="832" y={34+t*220} fill="#7c879a" fontSize="12">{(high-t*range).toFixed(2)}</text></g>)}
    {data.map((b,i)=>{const color=b.close>=b.open?'#4cad91':'#df6f7b';return <g key={b.date}><title>{b.date} · O {b.open.toFixed(2)} H {b.high.toFixed(2)} L {b.low.toFixed(2)} C {b.close.toFixed(2)}</title><line x1={i*11.5+14} x2={i*11.5+14} y1={y(b.high)} y2={y(b.low)} stroke={color}/><rect x={i*11.5+10.5} y={Math.min(y(b.open),y(b.close))} width="7" height={Math.max(1,Math.abs(y(b.open)-y(b.close)))} fill={color}/><rect x={i*11.5+10.5} y={295-b.volume/20000000*28} height={b.volume/20000000*28} width="7" fill={color} opacity=".3"/></g>;})}
    {[0,14,28,42,56,69].map(i=><text key={i} x={i*11.5+10} y="315" fill="#7c879a" fontSize="12" textAnchor={i===69?'end':'start'}>{data[i]?.date.slice(5)}</text>)}
  </svg>;
}
