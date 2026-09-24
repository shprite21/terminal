import {spawn} from 'node:child_process';
import {randomBytes} from 'node:crypto';
import {existsSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');

export class EngineBridge {
  constructor({python=process.env.Q_ENGINE_PYTHON||path.join(root,'apps/engine/.venv/Scripts/python.exe'),cwd=path.join(root,'apps/engine')}={}) {
    this.python=python;this.cwd=cwd;this.child=null;this.pending=null;this.url=null;
    this.token=randomBytes(32).toString('hex');this.failure=null;
  }
  status(){return {state:this.url?'ready':this.pending?'starting':'idle',message:this.failure,workers:1};}
  async start(){
    if(this.url)return this.url;
    if(this.pending)return this.pending;
    if(!existsSync(this.python))throw new Error('Set up the research engine with setup-flagship.ps1, then reconnect.');
    this.failure=null;
    this.pending=new Promise((resolve,reject)=>{
      const child=spawn(this.python,['-u','serve.py'],{cwd:this.cwd,windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,Q_ENGINE_TOKEN:this.token,Q_MARKET_GATEWAY_URL:this.marketGatewayUrl||''}});
      this.child=child;let buffer='',settled=false;
      const timer=setTimeout(()=>fail('Research engine startup timed out. Check setup-flagship.ps1.'),60000);
      const fail=message=>{this.failure=message;if(!settled){settled=true;clearTimeout(timer);reject(new Error(message));}this.url=null;child.kill();};
      // Raw subprocess logs stay out of browser payloads and connection credentials.
      child.stderr.on('data',()=>{});
      child.on('error',()=>fail('The research engine could not start. Check the Python environment.'));
      child.on('exit',()=>{if(this.child===child){this.child=null;this.url=null;}if(!settled)fail('Research engine exited during startup. Run setup-flagship.ps1.');});
      child.stdout.on('data',chunk=>{
        buffer+=chunk.toString();if(buffer.length>65536)return fail('Invalid research startup response.');
        const lines=buffer.split('\n');buffer=lines.pop()||'';
        for(const line of lines){
          let message;try{message=JSON.parse(line);}catch{continue;}
          const port=message.q_engine_port;
          if(!settled&&Number.isInteger(port)&&port>0&&port<65536){
            settled=true;clearTimeout(timer);this.runtimePid=message.q_engine_pid;this.url=`http://127.0.0.1:${port}`;resolve(this.url);
          }
        }
      });
    });
    try{return await this.pending;}finally{this.pending=null;}
  }
  async forward(req,res,route){
    if(!/^\/api\/(research|portfolio|evidence|health)(\/|$)/.test(route))throw new Error('Unknown research route.');
    const url=await this.start();
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),route.startsWith('/api/portfolio/analyze')?30*60*1000:180000);
    res.once('close',()=>controller.abort());
    try{
      const chunks=[];let bytes=0;
      for await(const chunk of req){bytes+=chunk.length;if(bytes>5_000_000)throw new Error('Research request exceeds 5 MB.');chunks.push(chunk);}
      const response=await fetch(url+route,{method:req.method,headers:{'x-q-engine-token':this.token,...(req.method==='GET'?{}:{'Content-Type':'application/json'})},body:req.method==='GET'?undefined:Buffer.concat(chunks),signal:controller.signal,redirect:'error'});
      const headers={'Content-Type':response.headers.get('content-type')||'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
      if(response.headers.has('content-disposition'))headers['Content-Disposition']=response.headers.get('content-disposition');
      res.writeHead(response.status,headers);
      if(response.body)for await(const chunk of response.body){if(!res.write(chunk))await new Promise((resolve,reject)=>{const clean=()=>{res.off('drain',drain);res.off('close',close);};const drain=()=>{clean();resolve();};const close=()=>{clean();reject(new Error('Client disconnected'));};res.once('drain',drain);res.once('close',close);});}
      res.end();
    }finally{clearTimeout(timeout);}
  }
  async history(symbol,source){
    const url=await this.start();
    const response=await fetch(url+'/api/research/market-history?'+new URLSearchParams({symbol,source}),{headers:{'x-q-engine-token':this.token},signal:AbortSignal.timeout(60000)});
    const body=await response.json();
    if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'Research history unavailable.');
    return body;
  }
  stop(){const child=this.child;if(child){child.stdin.end();const timer=setTimeout(()=>child.kill(),6500);timer.unref();child.once('exit',()=>clearTimeout(timer));}this.child=null;this.url=null;this.runtimePid=null;}
}
