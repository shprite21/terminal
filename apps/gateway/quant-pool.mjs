import {Worker} from 'node:worker_threads';

/** One lazy worker; bounded admission keeps bulk research away from connection I/O. */
export class QuantPool {
  constructor(){this.worker=null;this.jobs=new Map();this.sequence=0;}
  run(strategy,bars,version){
    if(this.jobs.size>=3)return Promise.reject(new Error('Three Q backtests are already queued or running.'));
    if(!this.worker){
      const worker=new Worker(new URL('./quant-worker.mjs',import.meta.url));this.worker=worker;
      worker.on('message',message=>{const job=this.jobs.get(message.id);if(!job)return;this.jobs.delete(message.id);message.error?job.reject(new Error(message.error)):job.resolve(message.result);if(!this.jobs.size)worker.unref();});
      const fail=()=>{for(const job of this.jobs.values())job.reject(new Error('Backtest worker stopped. Retry from the saved dataset.'));this.jobs.clear();if(this.worker===worker)this.worker=null;};
      worker.on('error',fail);worker.on('exit',fail);worker.unref();
    }
    const id=++this.sequence;this.worker.ref();
    return new Promise((resolve,reject)=>{this.jobs.set(id,{resolve,reject});this.worker.postMessage({id,strategy,bars,version});});
  }
  close(){this.worker?.terminate();}
}
export const quantPool=new QuantPool();
