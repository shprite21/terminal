import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm,symlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {StrategyDevelopment} from '../strategy-development.mjs';
import {CodexGateway,developmentPermissionsOverride} from '../codex.mjs';

test('custom projects preserve arbitrary parameters and immutable implementation versions',async t=>{
  const root=await mkdtemp(path.join(tmpdir(),'q-development-'));t.after(()=>rm(root,{recursive:true,force:true}));
  const store=new StrategyDevelopment(root,path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../..'));
  const project=await store.create('Volume breakout');
  const parameters={volumeMultiple:1.73,holdingDays:9,regimes:['calm','trending'],custom:{weighting:'inverse-risk'}};
  await store.parameters(project.id,parameters);
  await writeFile(path.join(store.workspace(project.id),'strategy.py'),'# first implementation\n');
  const original=await store.snapshot(project.id,'First');
  await writeFile(path.join(store.workspace(project.id),'strategy.py'),'# second implementation\n');
  await store.snapshot(project.id,'Second');
  assert.equal((await store.exportSnapshot(project.id,original)).files['strategy.py'],'# first implementation\n');
  assert.deepEqual(JSON.parse(await store.read(project.id,'parameters.json')),parameters);
  assert.equal((await store.list()).length,1);
  await assert.rejects(store.read(project.id,'../project.json'),/Select a project file/);
  assert.throws(()=>store.workspace('../outside'),/Invalid strategy/);
  await assert.rejects(store.parameters(project.id,[]),/JSON object/);
  const outside=path.join(root,'private.txt');await writeFile(outside,'private');
  try{await symlink(outside,path.join(store.workspace(project.id),'linked.txt'));assert.ok(!(await store.files(project.id)).some(f=>f.path==='linked.txt'));}catch(error){if(error.code!=='EPERM')throw error;}
});

test('gateway keeps writes scoped to the development project and denies network access',async()=>{
  const gateway=new CodexGateway();const policy=developmentPermissionsOverride();
  assert.match(policy,/network=\{enabled=false\}/);
  assert.match(policy,/":workspace_roots"=\{"\."="write","\.git"="read","\.codex"="read"\}/);
  assert.match(policy,/":minimal"="read"/);assert.match(policy,/":root"="deny"/);assert.ok(!policy.includes(':tmpdir'));
  gateway.busy=true;assert.throws(()=>gateway.assertIdle(),/Stop the current/);
});

test('repeated Codex turns retain snapshot metadata and persistent conversation',async t=>{
  const root=await mkdtemp(path.join(tmpdir(),'q-turns-'));t.after(()=>rm(root,{recursive:true,force:true}));
  const source=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../..');
  const development=new StrategyDevelopment(root,source);
  const gateway=new CodexGateway({cwd:source,development});
  gateway.status=async()=>({connected:true});
  let turn=0;
  gateway.rpc=async(method,params)=>{
    assert.equal(params.approvalPolicy,'never');
    assert.equal(params.permissions,'q-strategy');
    assert.equal(params.cwd,development.workspace(gateway.projectId));
    if(method==='thread/start')return {thread:{id:'test-thread'}};
    assert.equal(method,'turn/start');const number=++turn;
    setImmediate(async()=>{
      await writeFile(path.join(params.cwd,'strategy.mjs'),`export const version=${number};\n`);
      gateway.emit('notification',{method:'item/agentMessage/delta',params:{threadId:'test-thread',delta:`Version ${number} saved.`}});
      gateway.emit('notification',{method:'turn/completed',params:{threadId:'test-thread',turn:{status:'completed'}}});
    });
    return {turn:{id:String(number)}};
  };
  await gateway.createProject('Custom');
  await gateway.chat('Build it',{},()=>{});
  await gateway.chat('Revise it',{},()=>{});
  const project=await development.metadata(gateway.projectId);
  assert.equal(project.threadId,'test-thread');assert.equal(project.messages.length,4);assert.equal(project.snapshots.length,3);
  assert.equal((await development.exportSnapshot(project.id,project.snapshots[1].id)).files['strategy.mjs'],'export const version=1;\n');
});
