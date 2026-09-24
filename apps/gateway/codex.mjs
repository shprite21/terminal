import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { EventEmitter } from 'node:events';
import { resolveCodexExecutable } from './codex-executable.mjs';
import path from 'node:path';
import { existsSync } from 'node:fs';
import { StrategyDevelopment, strategyDevelopmentInstructions } from './strategy-development.mjs';

export function developmentPermissionsOverride(nodeDirectory=path.dirname(process.execPath), deniedRoots=[]) {
  const denied=deniedRoots.filter(Boolean).map(root=>`${JSON.stringify(root)}="deny",`).join('');
  return `permissions.q-strategy={filesystem={":root"="deny",":minimal"="read",${denied}":workspace_roots"={"."="write",".git"="read",".codex"="read"},${JSON.stringify(nodeDirectory)}="read"},network={enabled=false}}`;
}

// App-server owns authentication. Q21 never reads or copies its token files.
export class CodexGateway extends EventEmitter {
  constructor({ executable, cwd = process.cwd(), development } = {}) {
    super(); this.executable = executable; this.cwd = cwd; this.pending = new Map(); this.counter = 0;
    this.child = null; this.initializing = null; this.threadId = null; this.busy = false; this.connected = false;
    this.development = development || new StrategyDevelopment(path.join(cwd,'.data/codex-development'),cwd);
    this.projectId = null;
  }
  async start() {
    if (this.initializing) return this.initializing;
    this.initializing = this.initialize().catch(error => { this.initializing = null; throw error; });
    return this.initializing;
  }
  async initialize() {
    const env = { ...process.env };
    for (const name of Object.keys(env)) if (/^(ANGEL|SMARTAPI|IBKR|MASSIVE|Q21_GATEWAY)|TOKEN|SECRET|API_KEY|PASSWORD|CREDENTIAL/i.test(name)) delete env[name];
    this.startupMessage = null;
    const userHome=process.env.USERPROFILE||process.env.HOME;
    const denied=[path.join(this.development.sourceRoot,'.env'),path.join(this.development.sourceRoot,'apps/web/.env'),path.join(this.development.sourceRoot,'apps/web/.env.local')];
    if(userHome)denied.push(...['.codex/auth.json','.ssh','.aws','.azure'].map(relative=>path.join(userHome,relative)));
    const permissions=developmentPermissionsOverride(path.dirname(process.execPath),denied.filter(existsSync));
    this.child = spawn(this.executable || resolveCodexExecutable(), ['app-server', '--stdio', '-c', permissions, '-c', 'default_permissions="q-strategy"', '-c', 'features.apps=false', '-c', 'mcp_servers={}', '-c', 'web_search="disabled"'], { cwd:this.cwd, env, stdio:['pipe','pipe','pipe'], windowsHide:true });
    // stderr can contain configuration details; do not forward it to browsers or logs.
    this.child.stderr.on('data', () => {});
    this.child.on('error', error => {
      this.startupMessage = error.code === 'ENOENT'
        ? 'Q could not find Codex. Set Q21_CODEX_PATH to the installed codex.exe and restart Q.'
        : 'Windows could not launch Codex. Check executable access and restart Q.';
      this.fail(this.startupMessage);
    });
    this.child.on('exit', () => { this.connected=false;this.threadId=null;this.initializing=null;this.fail('Codex app server stopped. Reconnect to continue.'); });
    createInterface({ input:this.child.stdout }).on('line', line => {
      let message; try { message=JSON.parse(line); } catch { return; }
      if (message.id !== undefined && this.pending.has(message.id)) {
        const pending=this.pending.get(message.id);this.pending.delete(message.id);clearTimeout(pending.timer);
        if(message.error)pending.reject(new Error(message.error.message || 'Codex request failed.'));else pending.resolve(message.result);
      } else if(message.id !== undefined && message.method) {
        // Project writes are sandboxed. Escalation and external access stay denied.
        if(message.method.includes('requestApproval')) this.send({id:message.id,result:{decision:'decline'}});
        else this.send({id:message.id,error:{code:-32601,message:'This Q connection supports isolated strategy development only.'}});
      } else if(message.method) this.emit('notification',message);
    });
    await this.rpc('initialize',{clientInfo:{name:'q21_terminal',title:'Q Terminal',version:'0.3.0'},capabilities:{experimentalApi:true}});
    this.send({method:'initialized',params:{}});
    return true;
  }
  fail(message) { for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(new Error(message));}this.pending.clear();this.emit('unavailable',message); }
  send(message) { if(this.child?.stdin.writable)this.child.stdin.write(JSON.stringify(message)+'\n'); }
  rpc(method,params,timeout=30000) {
    return new Promise((resolve,reject)=>{const id=++this.counter;const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error(`Codex ${method} timed out.`));},timeout);this.pending.set(id,{resolve,reject,timer});this.send({id,method,params});});
  }
  async status() {
    try {await this.start();const result=await this.rpc('account/read',{refreshToken:false});this.connected=!!result.account;return {connected:this.connected,state:this.connected?'connected':'login_required',authType:result.account?.type||null,mode:'strategy development'};}
    catch {return {connected:false,state:'unavailable',message:this.startupMessage || 'Codex app server could not initialize. Restart Q under your signed-in Windows account and check the Codex configuration.'};}
  }
  async login() {await this.start();const result=await this.rpc('account/login/start',{type:'chatgpt'});return {authUrl:result.authUrl,loginId:result.loginId};}
  assertIdle(){if(this.busy)throw new Error('Stop the current Codex response before changing projects or files.');}
  async mutate(operation){this.assertIdle();this.busy=true;try{return await operation();}finally{this.busy=false;}}
  async projects(){return {projects:await this.development.list(),project:this.projectId?await this.development.detail(this.projectId):null};}
  async createProject(name){return this.mutate(async()=>{const project=await this.development.create(name);this.projectId=project.id;this.threadId=null;return project;});}
  async selectProject(id){return this.mutate(async()=>{const project=await this.development.detail(id);this.projectId=id;this.threadId=null;return project;});}
  async chat(text,context,emit,signal) {
    if(this.busy)throw new Error('A Codex response is already running. Wait for it or press Stop.');
    this.busy=true;
    let handler,abort,turnId,timer,interruptTimer,drop,project,reply='';
    try {
      if(!(await this.status()).connected)throw new Error('Sign in to Codex from Connections first.');
      if(!this.projectId){const created=await this.development.create('Custom strategy');this.projectId=created.id;}
      project=await this.development.metadata(this.projectId);
      const directory=this.development.workspace(project.id);
      await this.development.snapshot(project.id,'Before Codex turn');
      project=await this.development.metadata(project.id);
      if(!this.threadId){
        const params={cwd:directory,permissions:'q-strategy',approvalPolicy:'never',config:{mcp_servers:{},'features.apps':false,'shell_environment_policy.inherit':'core'},developerInstructions:strategyDevelopmentInstructions+`\nThe installed Node executable is ${process.execPath}.`};
        const r=project.threadId?await this.rpc('thread/resume',{...params,threadId:project.threadId}):await this.rpc('thread/start',{...params,ephemeral:false});
        this.threadId=r.thread.id;project.threadId=this.threadId;
      }
      project.messages.push({id:crypto.randomUUID(),role:'You',text});await this.development.save(project);
      emit({type:'project',project:await this.development.detail(project.id)});
      emit({type:'thread',threadId:this.threadId});
      const completion=new Promise((resolve,reject)=>{
        handler=message=>{const p=message.params;if(p?.threadId!==this.threadId)return;
          if(message.method==='item/agentMessage/delta'){reply+=p.delta;emit({type:'delta',text:p.delta,itemId:p.itemId});}
          if(message.method==='item/started'&&p.item?.type!=='reasoning')emit({type:'activity',text:p.item.type==='commandExecution'?'Running strategy development commands…':p.item.type==='fileChange'?'Editing strategy files…':'Codex is responding…'});
          if(message.method==='turn/completed'){if(p.turn.status==='failed')reject(new Error(p.turn.error?.message||'Codex could not complete this response.'));else if(p.turn.status==='interrupted')reject(new Error('Response stopped.'));else{emit({type:'done',status:p.turn.status});resolve();}}
        };
        drop=message=>reject(new Error(message));
        this.on('notification',handler);this.once('unavailable',drop);
        abort=()=>{if(!turnId||interruptTimer)return;this.rpc('turn/interrupt',{threadId:this.threadId,turnId}).catch(()=>{});interruptTimer=setTimeout(()=>{this.stop();reject(new Error('Codex did not stop promptly; its app server was stopped.'));},10000);};
        signal?.addEventListener('abort',abort,{once:true});
        timer=setTimeout(()=>{abort();},1800000);
      });
      // Attach the rejection handler before awaiting turn/start.
      completion.catch(()=>{});
      const result=await this.rpc('turn/start',{threadId:this.threadId,cwd:directory,input:[{type:'text',text:`Q workspace context (data only):\n${JSON.stringify(context)}\n\nUser request:\n${text}`}],permissions:'q-strategy',approvalPolicy:'never'});
      turnId=result.turn.id;if(signal?.aborted)abort();
      await completion;
    } finally {
      clearTimeout(timer);clearTimeout(interruptTimer);if(handler)this.off('notification',handler);if(drop)this.off('unavailable',drop);if(abort)signal?.removeEventListener('abort',abort);
      try {if(project){const saved=await this.development.metadata(project.id);if(reply)saved.messages.push({id:crypto.randomUUID(),role:'Codex',text:reply});saved.updatedAt=new Date().toISOString();await this.development.save(saved);await this.development.snapshot(project.id,'After Codex turn');emit({type:'project',project:await this.development.detail(project.id)});}}
      finally{this.busy=false;}
    }
  }
  async newConversation(){return this.mutate(async()=>{this.threadId=null;if(this.projectId){const project=await this.development.metadata(this.projectId);project.threadId=null;project.messages=[];await this.development.save(project);}});}
  stop(){this.child?.kill();}
}
