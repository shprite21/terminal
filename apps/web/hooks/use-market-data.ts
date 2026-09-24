"use client";

import {useCallback,useEffect,useRef,useState} from 'react';

import {rsi} from '@/lib/quant';

import type {Catalogue,Dataset,Quote} from '@/lib/market-types';

import {integrationRequest} from './use-integrations';



export function quoteFromDataset(dataset:Dataset):Quote{

  const bars=dataset.chartBars,last=bars.at(-1)!,prev=bars.at(-2)!;

  return {...dataset.instrument,price:last.close,change:last.close/prev.close-1,volume:last.volume,rsi:bars.length>14?rsi(bars.map(b=>b.close)):null,momentum:bars.length>=127?last.close/bars.at(-127)!.close-1:null,bars,dataset};

}

const initial:Catalogue={instruments:[],sources:[],fetchedAt:''};

export type HistorySource='massive'|'yahoo'|'synthetic'|'csv';

export function useMarketData(symbol:string){

  const [source,setSourceState]=useState<HistorySource>('massive');

  const activeSource=useRef(source);

  activeSource.current=source;

  const [catalogue,setCatalogue]=useState(initial),[quotes,setQuotes]=useState<Quote[]>([]),[errors,setErrors]=useState<Record<string,string>>({}),[loading,setLoading]=useState<Record<string,boolean>>({});

  const pending=useRef(new Map<string,Promise<Dataset|null>>()),loaded=useRef(new Set<string>());

  const accept=useCallback((dataset:Dataset)=>{if(dataset.source.startsWith('CSV')&&activeSource.current!=='csv'){activeSource.current='csv';setSourceState('csv');loaded.current.clear();setQuotes([]);}loaded.current.add(dataset.instrument.symbol);setQuotes(old=>[...old.filter(q=>q.symbol!==dataset.instrument.symbol),quoteFromDataset(dataset)]);setErrors(old=>({...old,[dataset.instrument.symbol]:''}));},[]);

  const setSource=useCallback((next:HistorySource)=>{activeSource.current=next;setSourceState(next);setQuotes([]);setErrors({});setLoading({});loaded.current.clear();},[]);

  const load=useCallback((ticker:string,refresh=false)=>{

    const key=source+':'+ticker;

    const existing=pending.current.get(key);if(existing)return existing;

    setLoading(old=>({...old,[ticker]:true}));

    const promise=(async()=>{try{const data=await integrationRequest(`/market/history?symbol=${encodeURIComponent(ticker)}&source=${source}${refresh?'&refresh=1':''}`) as unknown as Dataset;if(activeSource.current===source)accept(data);return data;}catch(e){if(activeSource.current===source)setErrors(old=>({...old,[ticker]:(e as Error).message}));return null;}finally{if(activeSource.current===source)setLoading(old=>({...old,[ticker]:false}));pending.current.delete(key);}})();

    pending.current.set(key,promise);return promise;

  },[accept,source]);

  const refreshCatalogue=useCallback(async(refresh=false)=>{setLoading(old=>({...old,catalogue:true}));try{const data=await integrationRequest(`/market/catalogue${refresh?'?refresh=1':''}`) as unknown as Catalogue;setCatalogue(data);setErrors(old=>({...old,catalogue:''}));return data;}catch(e){setErrors(old=>({...old,catalogue:(e as Error).message}));return initial;}finally{setLoading(old=>({...old,catalogue:false}));}},[]);

  useEffect(()=>{const timer=setTimeout(()=>void refreshCatalogue(),0);return()=>clearTimeout(timer);},[refreshCatalogue]);

  useEffect(()=>{const connected=()=>{loaded.current.delete(symbol);void load(symbol,true);};window.addEventListener('q21-market-connected',connected);return()=>window.removeEventListener('q21-market-connected',connected);},[symbol,load]);

  useEffect(()=>{if((source==='synthetic'||catalogue.instruments.some(i=>i.symbol===symbol))&&!loaded.current.has(symbol)){const timer=setTimeout(()=>void load(symbol),0);return()=>clearTimeout(timer);}},[symbol,catalogue,load,source]);

  return {source,setSource,catalogue,quotes,errors,loading,load,refreshCatalogue,accept};

}

