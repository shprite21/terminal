'use client';
import {useEffect,useState} from 'react';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {NativeSelect as Select,NativeSelectOption as Option} from '@/components/ui/native-select';
type Value=Record<string,unknown>;
type Property={type?:string;enum?:string[];minimum?:number;maximum?:number;default?:unknown;format?:string};
export type InputSchema={properties:Record<string,Property>};
const title=(value:string)=>value.replaceAll('_',' ');
const base='/integrations/engine/api/evidence/artifacts/';

function ArtifactPicker({kind,value,onChange}:{kind:string;value:string;onChange:(v:string)=>void}){
  const [page,setPage]=useState(0),[items,setItems]=useState<{id:string;name:string}[]>([]),[total,setTotal]=useState(0),[error,setError]=useState('');
  useEffect(()=>{const controller=new AbortController();fetch(`${base}${kind}?offset=${page*50}`,{signal:controller.signal}).then(async r=>{if(!r.ok)throw new Error('Could not load saved '+kind);return await r.json() as {items:{id:string;name:string}[];total:number};}).then(r=>{setItems(r.items);setTotal(r.total);setError('');}).catch(e=>{if(!controller.signal.aborted)setError(e.message);});return()=>controller.abort();},[kind,page]);
  return <div><Select aria-label={'Saved '+title(kind)} value={value} onChange={e=>onChange(e.target.value)}><Option value="">Select saved {title(kind)}…</Option>{value&&!items.some(i=>i.id===value)&&<Option value={value}>{value}</Option>}{items.map(i=><Option key={i.id} value={i.id}>{i.name} · {i.id.slice(0,12)}</Option>)}</Select>{total>50&&<div><Button variant="ghost" disabled={!page} onClick={()=>setPage(page-1)}>Previous</Button><span>Page {page+1}</span><Button variant="ghost" disabled={(page+1)*50>=total} onClick={()=>setPage(page+1)}>Next</Button></div>}{error&&<span role="alert">{error}</span>}</div>;
}

export function GuidedInputs({value,change,schema,action}:{value:Value;change:(v:Value)=>void;schema?:InputSchema;action:string}){
  const properties={...schema?.properties,...Object.fromEntries(Object.keys(value).map(k=>[k,schema?.properties[k]||{}]))};
  const idKinds:Record<string,string>={history_id:'quant_dataset',source_result_id:'quant_result',strategy_id:'strategy',dataset_id:'dataset',hypothesis_id:'hypothesis',report_id:'report',download_id:'download',...(action==='transition'?{id:'hypothesis'}:{}),...(action==='search-master'?{version:'instrument_master'}:{})};
  return <div className="flagship-fields">{Object.entries(properties).map(([key,property])=>{
    const current=value[key]??property.default;
    if(current===undefined)return null; // Optional controls remain available in the complete JSON contract.
    const update=(next:unknown)=>change({...value,[key]:next});
    const options=property.enum||(key==='partition'?['training','validation','holdout']:key==='state'?['draft','specified','testing','rejected','inconclusive','candidate for forward testing']:undefined);
    return <div key={key}><label className="block">{title(key)}{idKinds[key]?<ArtifactPicker kind={idKinds[key]} value={String(current)} onChange={update}/>:options?<Select value={String(current)} onChange={e=>update(e.target.value)}>{options.map(v=><Option key={v}>{v}</Option>)}</Select>:typeof current==='boolean'?<input type="checkbox" checked={current} onChange={e=>update(e.target.checked)}/>:typeof current==='number'?<Input type="number" step={property.type==='integer'?1:'any'} min={property.minimum} max={property.maximum} value={current} onChange={e=>update(Number(e.target.value))}/>:typeof current==='string'?<Input type={property.format==='date'||/^(train|validation|holdout)_(start|end)$/.test(key)?'date':'text'} value={current} onChange={e=>update(e.target.value)}/>:<span className="text-sm text-muted-foreground"> Edit the {Array.isArray(current)?'list':'structured fields'} in the complete specification below.</span>}</label></div>;
  })}</div>;
}
