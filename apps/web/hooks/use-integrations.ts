"use client";
import {useCallback,useEffect,useRef,useState} from 'react';
export type Connection={connected:boolean;state:string;message?:string;mode?:string;authType?:string;account?:string;loginUrl?:string;gatewayAvailable?:boolean;checkedAt?:string};
export type IntegrationStatus={gateway:boolean;codex:Connection;angel:Connection;ibkr:Connection;massive?:Connection;liveOrderSubmission:boolean};
const offline:Connection={connected:false,state:'unavailable'};
export const offlineStatus:IntegrationStatus={gateway:false,codex:offline,angel:offline,ibkr:offline,liveOrderSubmission:false};
export type CodexMessage={id:string;role:string;text:string};
export type DevelopmentProject={id:string;name:string;updatedAt:string;messages?:CodexMessage[];files?:{path:string;bytes:number}[];snapshots:{id:string;createdAt:string;label:string}[]};
export async function integrationRequest(path:string,body?:unknown){const response=await fetch(`/integrations${path}`,{method:body===undefined?'GET':'POST',headers:body===undefined?undefined:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});let result;try{result=await response.json() as Record<string,unknown>;}catch{throw new Error('The local integration gateway is unavailable. Start Q21 using start-q21.ps1.');}if(!response.ok)throw new Error(typeof result.error==='string'?result.error:'Connection request failed.');return result;}
export function useIntegrations(){
  const [status,setStatus]=useState(offlineStatus),[messages,setMessages]=useState<CodexMessage[]>([]),[busy,setBusy]=useState(false),[activity,setActivity]=useState(''),[threadId,setThreadId]=useState<string|null>(null);
  const abort=useRef<AbortController|null>(null);
  const [projects,setProjects]=useState<DevelopmentProject[]>([]),[project,setProject]=useState<DevelopmentProject|null>(null);
  const refreshProjects=useCallback(async()=>{const result=await integrationRequest('/codex/projects');setProjects(result.projects as DevelopmentProject[]);setProject(result.project as DevelopmentProject|null);return result;},[]);
  useEffect(()=>{void refreshProjects().then(result=>{if(result.project)setMessages((result.project as DevelopmentProject).messages||[]);}).catch(()=>{});},[refreshProjects]);
  const chooseProject=async(id:string)=>{if(abort.current)throw new Error('Stop the current reply first.');const next=await integrationRequest('/codex/project/select',{id}) as DevelopmentProject;setProject(next);setMessages(next.messages||[]);setThreadId(null);};
  const createProject=async(name:string)=>{if(abort.current)throw new Error('Stop the current reply first.');const next=await integrationRequest('/codex/projects',{name}) as DevelopmentProject;setProject(next);setMessages([]);setThreadId(null);await refreshProjects();};
  const refresh=useCallback(async()=>{try{const response=await fetch('/integrations/status');if(!response.ok)throw new Error();const data=await response.json() as IntegrationStatus;if(data.gateway!==true)throw new Error();setStatus(data);return data;}catch{setStatus(offlineStatus);return offlineStatus;}},[]);
  useEffect(()=>{const startup=setTimeout(()=>void refresh(),0);const timer=setInterval(()=>void refresh(),30000);return()=>{clearTimeout(startup);clearInterval(timer);abort.current?.abort();};},[refresh]);
  const send=async(text:string,context:unknown)=>{
    if(abort.current)throw new Error('Wait for the current reply or press Stop.');
    if(!status.codex.connected)throw new Error('Connect Codex in the Connections page first.');
    const id=crypto.randomUUID(),controller=new AbortController();abort.current=controller;
    setMessages(old=>[...old,{id:crypto.randomUUID(),role:'You',text},{id,role:'Codex',text:''}]);setBusy(true);setActivity('Connecting to Codex…');
    try{
      const response=await fetch('/integrations/codex/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,context}),signal:controller.signal});
      if(!response.ok||!response.body)throw new Error('Codex connection failed. Try refreshing Connections.');
      const reader=response.body.getReader(),decoder=new TextDecoder();let pending='';
      const consume=(line:string)=>{if(!line.trim())return;const event=JSON.parse(line) as {type:string;text?:string;message?:string;threadId?:string;status?:string;project?:DevelopmentProject};
        if(event.type==='project'&&event.project)setProject(event.project);
        if(event.type==='delta')setMessages(old=>old.map(m=>m.id===id?{...m,text:m.text+(event.text||'')}:m));
        if(event.type==='activity')setActivity(event.text||'Codex is working…');
        if(event.type==='thread')setThreadId(event.threadId||null);
        if(event.type==='error')throw new Error(event.message||'Codex response failed.');
      };
      while(true){const {done,value}=await reader.read();if(done)break;pending+=decoder.decode(value,{stream:true});const lines=pending.split('\n');pending=lines.pop()||'';for(const line of lines)consume(line);}pending+=decoder.decode();if(pending.trim())consume(pending);
    }catch(error){const message=controller.signal.aborted?'Response stopped.':error instanceof Error?error.message:'Codex request failed.';setMessages(old=>old.map(m=>m.id===id?{...m,text:m.text?`${m.text}\n\n${message}`:message}:m));}
    finally{abort.current=null;setBusy(false);setActivity('');void refreshProjects().catch(()=>{});}
  };
  const newConversation=async()=>{await integrationRequest('/codex/new',{});setMessages([]);setThreadId(null);};
  return {status,refresh,messages,busy,activity,threadId,send,stop:()=>abort.current?.abort(),newConversation,projects,project,refreshProjects,chooseProject,createProject};
}
