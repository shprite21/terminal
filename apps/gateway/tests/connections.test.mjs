import test from 'node:test';
import assert from 'node:assert/strict';
import {AngelOneAdapter,IbkrAdapter,requestJson} from '../brokers.mjs';
import {allowedRequest} from '../server.mjs';
const localRequest=(extra={})=>({method:'POST',socket:{remoteAddress:'127.0.0.1'},headers:{host:'localhost:5173',origin:'http://localhost:5173','content-type':'application/json'},...extra});
test('local mutation requires the exact Q21 origin, JSON, and loopback',()=>{
  assert.equal(allowedRequest(localRequest()),true);
  assert.equal(allowedRequest(localRequest({headers:{host:'localhost:5173',origin:'https://evil.example','content-type':'application/json'}})),false);
  assert.equal(allowedRequest(localRequest({headers:{host:'evil.example:5173',origin:'http://localhost:5173','content-type':'application/json'}})),false);
  assert.equal(allowedRequest(localRequest({headers:{host:'localhost:5173','content-type':'application/json'}})),false);
  assert.equal(allowedRequest(localRequest({socket:{remoteAddress:'192.168.1.2'}})),false);
});
test('IBKR cannot connect to an arbitrary remote URL or weaken its TLS',()=>{
  assert.throws(()=>new IbkrAdapter({baseUrl:'https://remote.example'}),/loopback/);
  assert.throws(()=>requestJson('https://remote.example',{localSelfSigned:true}),/loopback/);
});
test('IBKR reports login required separately from an unavailable gateway',async()=>{
  const pending=new IbkrAdapter({request:async()=>({authenticated:false,connected:true})});assert.equal((await pending.status()).state,'login_required');
  const unauthorized=new IbkrAdapter({request:async()=>{throw Object.assign(new Error(),{status:401});}});assert.equal((await unauthorized.status()).gatewayAvailable,true);
  const absent=new IbkrAdapter({request:async()=>{throw new Error('ECONNREFUSED');}});assert.equal((await absent.status()).gatewayAvailable,false);
});
test('Angel login retains no PIN or TOTP and returns no tokens',async()=>{
  const calls=[];const adapter=new AngelOneAdapter({request:async(url,options)=>{calls.push({url,options});if(url.endsWith('loginByPassword'))return {status:true,data:{jwtToken:'private-test-token',refreshToken:'never-retained'}};return {status:true,data:{clientcode:'A123456'}};}});
  const result=await adapter.login({apiKey:'private-key',clientCode:'A123456',pin:'0123',totp:'123456',publicIp:'203.0.113.1'});
  assert.equal(result.connected,true);assert.equal(result.account,'••••3456');
  assert.ok(!JSON.stringify(result).includes('private'));assert.ok(!JSON.stringify(adapter.session).includes('0123'));assert.equal(adapter.session.pin,undefined);assert.equal(adapter.session.totp,undefined);assert.ok(!JSON.stringify(adapter.session).includes('never-retained'));
  assert.equal(calls[0].options.headers['X-PrivateKey'],'private-key');assert.equal(calls[1].options.headers.Authorization,'Bearer private-test-token');
  adapter.disconnect();assert.equal(adapter.session,null);
});
test('failed Angel authentication does not create a session',async()=>{
  const adapter=new AngelOneAdapter({request:async()=>({status:false,message:'vendor error'})});await assert.rejects(adapter.login({apiKey:'key',clientCode:'A1',pin:'1234',totp:'123456',publicIp:'203.0.113.1'}),/sign-in failed/);assert.equal(adapter.session,null);
});
test('broker snapshots contain selected account fields, not credentials',async()=>{
  const adapter=new AngelOneAdapter({request:async(url)=>({status:true,data:url.endsWith('getRMS')?{availablecash:'100',net:'101',jwtToken:'secret'}:[{tradingsymbol:'INFY-EQ',quantity:2,averageprice:1500,ltp:1550,profitandloss:100,secret:'hidden'}]})});adapter.session={headers:{Authorization:'secret'},clientCode:'1234'};
  const snapshot=await adapter.snapshot();assert.equal(snapshot.source,'Angel One');assert.ok(!JSON.stringify(snapshot).includes('secret'));assert.ok(!JSON.stringify(snapshot).includes('hidden'));
});
