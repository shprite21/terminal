export type PaperOrder = { id:string; symbol:string; side:'BUY'|'SELL'; quantity:number; price:number; fee:number; date:string };
export type PaperAccount = { cash:number; unsettled:number; positions:Record<string,{quantity:number;cost:number}>; orders:PaperOrder[]; halted:boolean };
export const initialAccount: PaperAccount = {cash:100000,unsettled:0,positions:{},orders:[],halted:false};
export function placePaperOrder(account:PaperAccount, symbol:string, side:'BUY'|'SELL', quantity:number, price:number):PaperAccount {
  if(account.halted) throw new Error('The kill switch is active. Resume paper execution first.');
  if(!['BUY','SELL'].includes(side)||!Number.isSafeInteger(quantity)||quantity<1||!Number.isFinite(price)||price<=0) throw new Error('Enter a valid positive whole-share quantity.');
  const position=account.positions[symbol]??{quantity:0,cost:0}, gross=quantity*price, fee=gross*.001;
  if(side==='BUY'&&gross+fee>account.cash) throw new Error('Insufficient settled cash. Unsettled proceeds cannot fund this purchase.');
  if(side==='SELL'&&quantity>position.quantity) throw new Error('Short selling is disabled. Sell no more than your held shares.');
  if(side==='BUY'&&gross>20000) throw new Error('Paper order exceeds the $20,000 per-order risk limit.');
  const next={...account,positions:{...account.positions},orders:[...account.orders,{id:crypto.randomUUID(),symbol,side,quantity,price,fee,date:new Date().toISOString()}]};
  if(side==='BUY') {next.cash-=gross+fee;next.positions[symbol]={quantity:position.quantity+quantity,cost:position.cost+gross+fee};}
  else {next.unsettled+=gross-fee;next.positions[symbol]={quantity:position.quantity-quantity,cost:position.cost*(1-quantity/position.quantity)};}
  return next;
}
