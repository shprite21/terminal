import https from 'node:https';
import { networkInterfaces } from 'node:os';
import { isIP } from 'node:net';

export function requestJson(url,{method='GET',headers={},body,localSelfSigned=false}={}) {
  const target=new URL(url);
  if(target.protocol!=='https:')throw new Error('HTTPS is required.');
  if(localSelfSigned&&!['localhost','127.0.0.1','[::1]'].includes(target.hostname))throw new Error('Local certificate exception is limited to loopback.');
  return new Promise((resolve,reject)=>{
    const request=https.request(target,{method,headers:{Accept:'application/json',...headers},rejectUnauthorized:!localSelfSigned,timeout:12000},response=>{
      let data='';response.setEncoding('utf8');response.on('data',chunk=>{data+=chunk;if(data.length>2000000){request.destroy();reject(new Error('Broker response exceeded the size limit.'));}});
      response.on('end',()=>{if(response.statusCode<200||response.statusCode>=300){const error=new Error(`Broker returned HTTP ${response.statusCode}. Sign in again if the session expired.`);error.status=response.statusCode;reject(error);return;}try{resolve(JSON.parse(data));}catch{reject(new Error('Broker returned an unexpected response.'));}});
    });request.on('timeout',()=>request.destroy(new Error('Broker connection timed out.')));request.on('error',()=>reject(new Error('Broker endpoint is unavailable. Check the local gateway or network connection.')));if(body)request.write(JSON.stringify(body));request.end();
  });
}
const mask=value=>typeof value==='string'?`••••${value.slice(-4)}`:null;
const clean=value=>typeof value==='number'&&Number.isFinite(value)?value:typeof value==='string'?value.slice(0,200):null;
export class AngelOneAdapter {
  constructor({request=requestJson}={}){this.request=request;this.session=null;this.checkedAt=null;}
  async login({apiKey,clientCode,pin,totp,publicIp}) {
    if(![apiKey,clientCode,pin,totp].every(v=>typeof v==='string'&&v.length>0&&v.length<512)||!/^\d{6}$/.test(totp))throw new Error('Enter the SmartAPI key, client code, PIN, and a current six-digit TOTP.');
    if(publicIp&&!isIP(publicIp))throw new Error('Public IP must be a valid IP address.');
    const adapter=Object.values(networkInterfaces()).flat().find(n=>n&&!n.internal&&n.family==='IPv4');
    // Discover only the IP; no account data is sent to this service.
    const ip=publicIp||(await this.request('https://api.ipify.org?format=json')).ip;
    if(!isIP(ip))throw new Error('Could not determine the public IP. Enter it in advanced settings.');
    const headers={'Content-Type':'application/json','X-PrivateKey':apiKey,'X-UserType':'USER','X-SourceID':'WEB','X-ClientLocalIP':adapter?.address||'127.0.0.1','X-ClientPublicIP':ip,'X-MACAddress':adapter?.mac||'00:00:00:00:00:00'};
    const result=await this.request('https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword',{method:'POST',headers,body:{clientcode:clientCode,password:pin,totp}});
    if(!result.status||!result.data?.jwtToken)throw new Error('Angel One sign-in failed. Check the SmartAPI key, PIN, and current TOTP.');
    // PIN and TOTP are not retained. The API key and access token live only in this process.
    this.session={headers:{...headers,Authorization:`Bearer ${result.data.jwtToken}`},clientCode};
    try{return await this.status();}catch{this.session=null;throw new Error('Angel One could not verify the new session.');}
  }
  async get(endpoint){if(!this.session)throw new Error('Sign in to Angel One first.');const result=await this.request(`https://apiconnect.angelone.in${endpoint}`,{headers:this.session.headers});if(!result.status){this.session=null;throw new Error('Angel One session expired or the request was rejected. Sign in again.');}return result.data;}
  async status(){if(!this.session)return {connected:false,state:'login_required',mode:'read-only'};try{const profile=await this.get('/rest/secure/angelbroking/user/v1/getProfile');this.checkedAt=new Date().toISOString();return {connected:true,state:'connected',account:mask(profile?.clientcode||this.session.clientCode),mode:'read-only',checkedAt:this.checkedAt};}catch{return {connected:false,state:'login_required',mode:'read-only'};}}
  async snapshot(){const [holdings,positions,funds]=await Promise.all([this.get('/rest/secure/angelbroking/portfolio/v1/getHolding'),this.get('/rest/secure/angelbroking/order/v1/getPosition'),this.get('/rest/secure/angelbroking/user/v1/getRMS')]);return {source:'Angel One',mode:'read-only',asOf:new Date().toISOString(),holdings:(holdings||[]).map(p=>({symbol:clean(p.tradingsymbol),quantity:clean(p.quantity),averagePrice:clean(p.averageprice),lastPrice:clean(p.ltp),pnl:clean(p.profitandloss)})),positions:(positions||[]).map(p=>({symbol:clean(p.tradingsymbol),quantity:clean(p.netqty),pnl:clean(p.pnl)})),funds:{currency:'INR',availableCash:clean(funds?.availablecash),net:clean(funds?.net)}};}
  disconnect(){this.session=null;return {connected:false,state:'login_required'};}
}
export class IbkrAdapter {
  constructor({request=requestJson,baseUrl=process.env.Q21_IBKR_URL||'https://localhost:5000',allowSelfSigned=true}={}){const url=new URL(baseUrl);if(!['localhost','127.0.0.1','[::1]'].includes(url.hostname)||url.protocol!=='https:')throw new Error('IBKR gateway must be an HTTPS loopback address.');this.base=url.origin;this.request=request;this.allowSelfSigned=allowSelfSigned;}
  get(path,method='GET'){return this.request(`${this.base}/v1/api${path}`,{method,localSelfSigned:this.allowSelfSigned});}
  async status(){try{const result=await this.get('/iserver/auth/status','POST');return {connected:result.authenticated===true&&result.connected===true,state:result.authenticated&&result.connected?'connected':'login_required',gatewayAvailable:true,mode:'read-only',loginUrl:this.base,checkedAt:new Date().toISOString()};}catch(error){const reachable=[401,403].includes(error.status);return {connected:false,state:reachable?'login_required':'gateway_unavailable',gatewayAvailable:reachable,mode:'read-only',loginUrl:this.base};}}
  async snapshot(){if(!(await this.status()).connected)throw new Error('Complete IBKR gateway login first.');const accounts=await this.get('/portfolio/accounts');if(!Array.isArray(accounts))throw new Error('IBKR returned no readable accounts.');const data=[];for(const a of accounts.slice(0,10)){const id=a.accountId||a.id;if(typeof id!=='string'||!/^\w+$/.test(id))continue;const positions=await this.get(`/portfolio/${encodeURIComponent(id)}/positions/0`);data.push({account:mask(id),positions:(Array.isArray(positions)?positions:[]).map(p=>({symbol:clean(p.contractDesc||p.ticker),quantity:clean(p.position),currency:clean(p.currency),marketValue:clean(p.mktValue),unrealizedPnl:clean(p.unrealizedPnl)}))});}return {source:'IBKR',mode:'read-only',asOf:new Date().toISOString(),accounts:data,note:'First page of positions per account (up to 100 positions).'};}
}
