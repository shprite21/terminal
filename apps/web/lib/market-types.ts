import type {Bar} from './quant';
export type Instrument={symbol:string;name:string;market:'US'|'IN';exchange:string;type:string;currency:string;isin?:string;sector:string};
export type Dataset={id:string;instrument:Instrument;source:string;provider?:string;synthetic?:boolean;seed?:number;fetchedAt:string;asOf:string;interval:'1d';bars:Bar[];chartBars:Bar[];warnings:string[];cached?:boolean;stale?:boolean;priceBasis:string};
export type Quote=Instrument & {price:number;change:number;volume:number;rsi:number|null;momentum:number|null;bars:Bar[];dataset:Dataset};
export type Catalogue={instruments:Instrument[];sources:{name:string;count:number;asOf:string|null;status:string;error?:string}[];fetchedAt:string};
