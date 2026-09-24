import { mkdir, readFile, writeFile, readdir, lstat, realpath, rename } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID, createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';

const idPattern = /^[a-f0-9-]{36}$/;
const extensions = new Set(['.md','.json','.py','.mjs','.js','.ts','.csv','.txt','.yaml','.yml','.toml']);
const instructions = `# Q strategy development
This is an isolated Q research project, not a production deployment.
Develop the strategy discussed with the user. You may create and edit code, tests, specifications, and custom parameters here and run local tests/scripts.
The built-in Q strategy forms are optional examples, NOT a constraint. Use arbitrary named JSON parameters, new indicators, entry/exit logic, sizing, universes, or a custom Python/JavaScript implementation as needed.
Keep the intended rules and assumptions in spec.md; parameters.json holds arbitrary user-defined JSON settings. Save executable implementation and independent tests, and explain how to run them. Never present a scaffold as finished.
reference/quant.ts is Q's current daily long-only accounting engine for reference. Copy/extend it locally if suitable; other strategy structures may use their own tested research engine. Do not claim that a custom strategy runs in Q's built-in template backtester unless it actually does.
data/*.json contains explicitly attached immutable-source datasets. Retain source, dataset id, UTC dates and price basis in outputs. Never invent market data or results. Synthetic fixtures must be clearly labeled, seeded and reproducible.
Signals may see only past/available bars; fills occur no earlier than the next eligible bar. Model transaction costs, available cash and whole-share rounding. Test causality, costs, cash conservation and edge cases independently. Production sessions need explicit exchange calendars.
Write reports/results as files for review. Edits never change saved snapshots or a running deployment. Live execution is disabled. Do not access brokers, credentials, account files, the network or other project directories. Do not change sandbox or security settings. All work stays here.
`;

export class StrategyDevelopment {
  constructor(root, sourceRoot) { this.root = path.resolve(root); this.sourceRoot = sourceRoot; }
  async init() { await mkdir(this.root, {recursive:true}); }
  directory(id) { if(!idPattern.test(id || '')) throw new Error('Invalid strategy project.'); return path.join(this.root,id); }
  workspace(id) { return path.join(this.directory(id),'workspace'); }
  async metadata(id) { return JSON.parse(await readFile(path.join(this.directory(id),'project.json'),'utf8')); }
  async save(project) {
    const file = path.join(this.directory(project.id),'project.json');
    await writeFile(file+'.tmp',JSON.stringify(project,null,2)); await rename(file+'.tmp',file);
  }
  async list() {
    await this.init(); const projects=[];
    for(const entry of await readdir(this.root,{withFileTypes:true})) if(entry.isDirectory()&&idPattern.test(entry.name)) projects.push(await this.metadata(entry.name));
    return projects.sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt)).map(({messages,threadId,...project})=>project);
  }
  async create(name='Custom strategy') {
    if(typeof name!=='string'||!name.trim()||name.length>100) throw new Error('Use a project name of 1–100 characters.');
    await this.init(); const id=randomUUID(), directory=this.workspace(id);
    await mkdir(path.join(directory,'reference'),{recursive:true});
    // A separate Git repository prevents discovery of Q's parent repository.
    execFileSync('git',['init','-b','codex/strategy',directory],{windowsHide:true,stdio:'pipe'});
    await writeFile(path.join(directory,'AGENTS.md'),instructions);
    await writeFile(path.join(directory,'spec.md'),`# ${name.trim()}\n\nDraft: discuss the hypothesis, data, rules, sizing, costs and validation with Codex.\n`);
    await writeFile(path.join(directory,'parameters.json'),'{}\n');
    await writeFile(path.join(directory,'reference','quant.ts'),await readFile(path.join(this.sourceRoot,'apps/web/lib/quant.ts')));
    const now=new Date().toISOString(), project={id,name:name.trim(),createdAt:now,updatedAt:now,threadId:null,messages:[],snapshots:[]};
    await this.save(project);return this.detail(id);
  }
  async files(id) {
    const base=await realpath(this.workspace(id)), files=[];let bytes=0;
    const walk=async(relative='',depth=0)=>{
      if(depth>8)throw new Error('Strategy file nesting exceeds the review limit.');
      for(const entry of await readdir(path.join(base,relative),{withFileTypes:true})) {
        if(entry.name.startsWith('.')||['node_modules','__pycache__'].includes(entry.name))continue;
        const name=relative?`${relative}/${entry.name}`:entry.name, full=path.join(base,name), stat=await lstat(full);
        if(stat.isSymbolicLink())continue;
        if(stat.isDirectory()){await walk(name,depth+1);continue;}
        if(!stat.isFile()||!extensions.has(path.extname(name)))continue;
        // Refuse oversized review snapshots rather than silently losing code.
        bytes+=stat.size;if(stat.size>8_000_000||bytes>24_000_000||files.length>=300)throw new Error('Project review exceeds 300 files or 24 MB. Reduce generated output files.');
        files.push({path:name,bytes:stat.size});
      }
    };await walk();return files.sort((a,b)=>a.path.localeCompare(b.path));
  }
  async read(id,name) {
    if(typeof name!=='string'||!(await this.files(id)).some(file=>file.path===name))throw new Error('Select a project file.');
    const base=await realpath(this.workspace(id)), target=await realpath(path.join(base,name));
    if(!target.startsWith(base+path.sep))throw new Error('File must remain inside the strategy project.');
    const stat=await lstat(target);if(stat.nlink>1)throw new Error('Linked files cannot be exported.');
    return readFile(target,'utf8');
  }
  async detail(id) {const {threadId,...project}=await this.metadata(id);return {...project,files:await this.files(id)};}
  async snapshot(id,label) {
    const files={};for(const file of await this.files(id))files[file.path]=await this.read(id,file.path);
    const version=createHash('sha256').update(JSON.stringify(files)).digest('hex'), project=await this.metadata(id);
    if(!project.snapshots.some(s=>s.id===version)){
      const snapshot={id:version,createdAt:new Date().toISOString(),label,files};
      await mkdir(path.join(this.directory(id),'snapshots'),{recursive:true});
      await writeFile(path.join(this.directory(id),'snapshots',version+'.json'),JSON.stringify(snapshot),{flag:'wx'});
      project.snapshots.push({id:version,createdAt:snapshot.createdAt,label});project.updatedAt=snapshot.createdAt;await this.save(project);
    }
    return version;
  }
  async exportSnapshot(id,version) {
    if(!/^[a-f0-9]{64}$/.test(version||''))throw new Error('Invalid strategy version.');
    return JSON.parse(await readFile(path.join(this.directory(id),'snapshots',version+'.json'),'utf8'));
  }
  async parameters(id,value) {
    if(!value||typeof value!=='object'||Array.isArray(value)||JSON.stringify(value).length>30000)throw new Error('Parameters must be a JSON object under 30,000 characters.');
    await this.snapshot(id,'Before parameter edit');
    // Replace rather than follow a possible symlink in the editable workspace.
    const directory=this.workspace(id), temporary=path.join(directory,randomUUID()+'.json');
    await writeFile(temporary,JSON.stringify(value,null,2)+'\n',{flag:'wx'});await rename(temporary,path.join(directory,'parameters.json'));
    await this.snapshot(id,'Parameters saved');return this.detail(id);
  }
  async attach(id,dataset) {
    await this.snapshot(id,'Before dataset attachment');
    // Avoid traversing agent-created directories when writing from the gateway.
    const directory=this.workspace(id), file=`dataset-${dataset.id}.json`;
    if(!/^[a-f0-9]{64}$/.test(dataset.id||''))throw new Error('Dataset has no immutable identifier.');
    await writeFile(path.join(directory,file),JSON.stringify(dataset,null,2),{flag:'wx'}).catch(error=>{if(error.code!=='EEXIST')throw error;});
    await this.snapshot(id,'Dataset attached');return this.detail(id);
  }
}

export const strategyDevelopmentInstructions = instructions + '\nAttached datasets are named dataset-<id>.json in the project root. Read these files and parameters.json when developing or testing. Keep user-facing explanations concise and show the implementation, validation evidence and any remaining limits.';
