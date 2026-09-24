import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { CodexGateway } from './codex.mjs';
import { AngelOneAdapter, IbkrAdapter } from './brokers.mjs';
import { MarketDataService } from './market-data.mjs';
import { EngineBridge } from './engine.mjs';
import { quantPool } from './quant-pool.mjs';
import {timingSafeEqual} from 'node:crypto';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const port=Number(process.env.Q21_GATEWAY_PORT||5174),webPort=Number(process.env.Q21_WEB_PORT||5173);
export function allowedRequest(req,configuredWebPort=webPort,configuredPort=port) {
  if(!['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress))return false;
  const hosts=new Set([`localhost:${configuredWebPort}`,`127.0.0.1:${configuredWebPort}`,`localhost:${configuredPort}`,`127.0.0.1:${configuredPort}`]);
  if(!hosts.has(req.headers.host))return false;
  const origin=req.headers.origin;
  if(origin&&![`http://localhost:${configuredWebPort}`,`http://127.0.0.1:${configuredWebPort}`].includes(origin))return false;
  if(req.headers['sec-fetch-site']==='cross-site')return false;
  if(req.method!=='GET'&&(!origin||!req.headers['content-type']?.startsWith('application/json')))return false;
  return true;
}
async function readBody(req,limit=40000){let text='';for await(const chunk of req){text+=chunk;if(text.length>limit)throw new Error('Request is too large.');}return JSON.parse(text||'{}');}
function json(res,status,data){res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(JSON.stringify(data));}
export function createGateway({codex=new CodexGateway({cwd:root}),angel=new AngelOneAdapter(),ibkr=new IbkrAdapter(),market=new MarketDataService(),engine=new EngineBridge()}={}) {
  market.alternateHistory=(symbol,source)=>engine.history(symbol,source);
  const server=createServer(async(req,res)=>{
    if(!allowedRequest(req,webPort,server.address()?.port||port))return json(res,403,{error:'Q21 integrations accept only same-origin local requests.'});
    const route=new URL(req.url,'http://localhost').pathname.replace(/^\/integrations/,'');
    const params=new URL(req.url,'http://localhost').searchParams;
    try{
      engine.marketGatewayUrl=`http://127.0.0.1:${server.address()?.port||port}`;
      if(req.method==='GET'&&route==='/internal/market-history'){
        const supplied=Buffer.from(req.headers['x-q-engine-token']||''),expected=Buffer.from(engine.token||'');
        if(!expected.length||supplied.length!==expected.length||!timingSafeEqual(supplied,expected))return json(res,403,{error:'Internal research access only.'});
        return json(res,200,await market.history(params.get('symbol'),false,'massive'));
      }
      if(route.startsWith('/engine/'))return await engine.forward(req,res,route.slice('/engine'.length)+(params.size?'?'+params.toString():''));
      if(req.method==='GET'&&route==='/flagship/status')return json(res,200,{engine:engine.status(),liveOrderSubmission:false});
      if(req.method==='POST'&&route==='/massive/connect')return json(res,200,await market.massive.connect(await readBody(req)));
      if(req.method==='POST'&&route==='/massive/disconnect')return json(res,200,market.massive.disconnect());
      if(req.method==='GET'&&route==='/market/catalogue')return json(res,200,await market.catalogue(params.get('refresh')==='1'));
      if(req.method==='GET'&&route==='/market/history')return json(res,200,await market.history(params.get('symbol'),params.get('refresh')==='1',params.get('source')||'massive'));
      if(req.method==='POST'&&route==='/market/import')return json(res,200,await market.importCsv(await readBody(req,5000000)));
      if(req.method==='POST'&&route==='/backtests'){const body=await readBody(req);return json(res,200,await market.run(body.strategy?body:{strategy:body}));}
      if(req.method==='GET'&&route==='/status'){const [c,a,i]=await Promise.all([codex.status(),angel.status(),ibkr.status()]);return json(res,200,{gateway:true,codex:c,angel:a,ibkr:i,massive:market.massive.status(),liveOrderSubmission:false});}
      if(req.method==='POST'&&route==='/codex/login')return json(res,200,await codex.login());
      if(req.method==='POST'&&route==='/codex/new'){await codex.newConversation();return json(res,200,{ok:true});}
      if(req.method==='GET'&&route==='/codex/projects')return json(res,200,await codex.projects());
      if(req.method==='POST'&&route==='/codex/projects')return json(res,200,await codex.createProject((await readBody(req)).name));
      if(req.method==='POST'&&route==='/codex/project/select')return json(res,200,await codex.selectProject((await readBody(req)).id));
      if(req.method==='GET'&&route==='/codex/project/file')return json(res,200,{text:await codex.development.read(params.get('id'),params.get('path'))});
      if(req.method==='GET'&&route==='/codex/project/snapshot')return json(res,200,await codex.development.exportSnapshot(params.get('id'),params.get('version')));
      if(req.method==='POST'&&route==='/codex/project/parameters'){const body=await readBody(req);return json(res,200,await codex.mutate(()=>codex.development.parameters(body.id,body.parameters)));}
      if(req.method==='POST'&&route==='/codex/project/dataset'){
        const body=await readBody(req);return json(res,200,await codex.mutate(async()=>{await codex.development.metadata(body.id);const dataset=await market.history(body.symbol,false,body.source);return codex.development.attach(body.id,dataset);}));
      }
      if(req.method==='POST'&&route==='/codex/chat'){
        const body=await readBody(req);if(typeof body.text!=='string'||!body.text.trim()||body.text.length>12000)return json(res,400,{error:'Enter a message under 12,000 characters.'});
        // Accept explicit research fields only. Broker credentials/accounts are never sent to Codex.
        const input=body.context||{};const context={page:input.page,symbol:input.symbol,dataSource:input.dataSource||'No dataset selected; do not invent prices or results.',asOf:input.asOf,datasetId:input.datasetId,strategy:input.strategy,researchNote:input.researchNote,metrics:input.metrics,tradeCount:input.tradeCount};
        res.writeHead(200,{'Content-Type':'application/x-ndjson','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.flushHeaders();
        const controller=new AbortController();res.on('close',()=>controller.abort());const emit=e=>{if(!res.destroyed)res.write(JSON.stringify(e)+'\n');};
        const heartbeat=setInterval(()=>emit({type:'heartbeat'}),15000);
        try{await codex.chat(body.text,context,emit,controller.signal);}catch(e){emit({type:'error',message:e.message});}finally{clearInterval(heartbeat);res.end();}return;
      }
      if(req.method==='POST'&&route==='/angel/login')return json(res,200,await angel.login(await readBody(req)));
      if(req.method==='POST'&&route==='/angel/disconnect')return json(res,200,angel.disconnect());
      if(req.method==='GET'&&route==='/angel/account')return json(res,200,await angel.snapshot());
      if(req.method==='GET'&&route==='/ibkr/account')return json(res,200,await ibkr.snapshot());
      return json(res,404,{error:'Integration endpoint not available. Live order submission is disabled.'});
    }catch(e){if(res.headersSent){res.destroy();return;}return json(res,400,{error:e.message||'Connection failed.'});}
  });
  server.on('close',()=>{codex.stop();engine.stop();quantPool.close();});return server;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const server=createGateway();server.listen(port,'127.0.0.1',()=>console.log(`Q21 integration gateway: http://127.0.0.1:${port} (read-only broker access)`));
  server.on('error',error=>{console.error(error.code==='EADDRINUSE'?'Q21 gateway is already running on this port.':'Q21 gateway could not start.');process.exitCode=1;});
  process.on('SIGINT',()=>server.close());process.on('SIGTERM',()=>server.close());
}
