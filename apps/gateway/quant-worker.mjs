import {parentPort} from 'node:worker_threads';
import {backtest} from '../web/lib/quant.ts';
parentPort.on('message',({id,strategy,bars,version})=>{
  try{parentPort.postMessage({id,result:backtest(strategy,bars,version)});}
  catch(error){parentPort.postMessage({id,error:error.message});}
});
