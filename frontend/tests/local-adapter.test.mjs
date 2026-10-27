import { githubPanel } from '../src/github-ui.js';
import test from 'node:test';
import assert from 'node:assert/strict';
import { LocalAdapter, encodeFile } from '../src/local-adapter.js';
const storage={getItem(){return null;},setItem(){}};
const response=(status,value)=>({ok:status<400,status,async json(){return value;}});
test('network loss never resolves success; same request key is recovered after querying commit result',async()=>{
  const calls=[];let lost=true;
  const a=new LocalAdapter('temporary-test-token',{storage,fetchImpl:async(path,options)=>{
    calls.push({path,...options});
    if(options.method==='GET')return response(200,{result:lost?null:{revision:1}});
    lost=false;throw Error('response lost after commit');
  }});a.projectId='p';
  await assert.rejects(a.post('commits',{base_revision:0,selection:[{candidate_id:'c',review_id:'r'}]}),/结果尚未确认/);
  assert(a.pending);await assert.rejects(a.post('commits',{}),/结果未确认/);
  const result=await a.resume();assert.equal(result.revision,1);assert.equal(calls.filter(c=>c.method==='POST').length,1);assert.equal(a.pending,null);
  assert(!JSON.stringify(storage).includes('temporary-test-token'));
});
test('read failure remains local and does not return synthetic view; rejection never succeeds',async()=>{
  const a=new LocalAdapter('synthetic-credential',{storage,fetchImpl:async()=>response(401,{error:'authentication_required'})});
  await assert.rejects(a.read(),/authentication_required/);assert.equal(a.view.tasks.length,0);
  await assert.rejects(a.post('/api/projects',{title:'x'}),/authentication_required/);assert.equal(a.pending,null);
});
test('actual File bytes are encoded, not a server filesystem path',async()=>{
  const f=new File(['合成资料\nactual bytes'],'synthetic.md',{type:'text/markdown'});
  const value=await encodeFile(f);assert.equal(Buffer.from(value.base64,'base64').toString(),'合成资料\nactual bytes');assert.equal(value.name,'synthetic.md');assert(!('path' in value));
});
test('reauthenticated page recovers only request metadata; body and credentials never enter session storage',async()=>{
  const values=new Map();const store={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
  const a=new LocalAdapter('private-token',{storage:store,fetchImpl:async()=>{throw Error('lost');}});
  await assert.rejects(a.post('/api/projects',{title:'synthetic private body'}));
  const saved=values.get('nextrelay.pending');assert(!saved.includes('private-token'));assert(!saved.includes('private body'));
  const b=new LocalAdapter('private-token',{storage:store,fetchImpl:async path=>{assert(path.startsWith('/api/requests/'));return response(200,{state:'committed',result:{id:'project'}});}});
  assert.equal((await b.resume()).result.id,'project');assert.equal(values.has('nextrelay.pending'),false);
});
test('a truncated successful response keeps original request pending for recovery',async()=>{
  const a=new LocalAdapter('test-token',{storage,fetchImpl:async()=>({ok:true,status:200,async json(){throw Error('truncated');}})});
  await assert.rejects(a.post('/api/projects',{title:'synthetic'}),/结果尚未确认/);assert(a.pending);
  await assert.rejects(a.post('/api/projects',{title:'synthetic'}),/结果未确认/);
});
test('browser recovery metadata cannot inject a request body or remote credential destination',async()=>{
  const store={getItem(){return JSON.stringify({requestKey:'synthetic-key',path:'/api/projects',body:{subject:'forged'}});}};
  const a=new LocalAdapter('private',{storage:store,fetchImpl:async(path,options)=>{assert.equal(path,'/api/requests/synthetic-key');assert.equal(options.method,'GET');return response(200,{state:'not-committed',result:null});}});
  assert.equal(a.pending.body,undefined);await a.resume();
  await assert.rejects(a.request('https://evil.invalid/api/'),/同源/);
});


test('model consent needs actual preview and uses a distinct server-bound decision route',async()=>{
  const calls=[];const a=new LocalAdapter('temporary',{storage,fetchImpl:async(path,options)=>{calls.push({path,...options});return response(200,{requests:[{body:'synthetic request preview'}]});}});
  a.projectId='p';a.view={modelBatches:[{id:'b',fingerprint:'exact-manifest'}]};a.read=async()=>a.view;
  await assert.rejects(a.submit({type:'model-decision',id:'b',decision:'approved'}),/预览/);assert.equal(calls.length,0);
  await a.submit({type:'model-preview',id:'b'});assert.equal(calls[0].method,'GET');
  await a.submit({type:'model-decision',id:'b',decision:'approved'});
  assert.equal(calls[1].path,'/api/projects/p/model-batches/b/decision');assert.deepEqual(JSON.parse(calls[1].body),{fingerprint:'exact-manifest',decision:'approved'});
  assert(!calls.some(c=>c.path.endsWith('/execute')||c.path.endsWith('/reviews')||c.path.endsWith('/commits')));
  await a.submit({type:'model-decision',id:'b',decision:'denied'});assert.equal(a.modelPreviews.has('b'),false);
});

test('GitHub UI intents use exact preview confirmation and never imply model or formal approval',async()=>{
  const calls=[];const a=new LocalAdapter('temporary',{storage,fetchImpl:async(path,options)=>{calls.push({path,...options});return response(200,{});}});
  a.projectId='p';a.read=async()=>({githubSnapshots:[]});
  await a.submit({type:'github-prepare',url:'https://github.com/a/b',ref:'feature/docs'});
  assert.deepEqual(JSON.parse(calls[0].body),{url:'https://github.com/a/b',storage_choice:'configured-local',ref:'feature/docs'});
  await a.submit({type:'github-action',id:'snapshot',action:'confirm',body:{scope_id:'scope',fingerprint:'exact'}});
  assert.equal(calls[1].path,'/api/projects/p/github/snapshot/confirm');assert.deepEqual(JSON.parse(calls[1].body),{scope_id:'scope',fingerprint:'exact'});
  assert(!calls.some(c=>/model-batches|reviews|commits/.test(c.path)));
});


test('interrupted pinned preparation exposes original-commit retry while unpinned failure only updates',()=>{
  const snapshot={id:'snapshot',state:'failed',git_commit:'a'.repeat(40),input:{url:'https://github.com/a/b'},repo:'a/b',scopes:[],entries:[],unknown_ranges:[],content_reads:0,content_bytes:0,content_reserved:0,metadata_bytes:0,metadata_reserved:0};
  const render=b=>githubPanel({capabilities:{local_storage:{directory:'synthetic'}},githubSnapshots:[b]},x=>String(x??''),(action,label,kind,attrs)=>`<button data-action="${action}" ${attrs}>${label}</button>`);
  const pinned=render(snapshot);assert(pinned.includes('data-op="retry"'));assert(!pinned.includes('data-op="read"'));assert(!pinned.includes('data-op="expand"'));
  const unpinned=render({...snapshot,git_commit:null});assert(!unpinned.includes('data-op="retry"'));assert(unpinned.includes('data-op="update"'));
});


test('new UI preparations explicitly select model/2 while approvals remain fingerprint bound',async()=>{
  const calls=[];const a=new LocalAdapter('synthetic-token',{fetchImpl:async(path,options={})=>{calls.push({path,...options});return {ok:true,json:async()=>({})};},storage:null});
  a.projectId='p';a.read=async()=>({});
  await a.submit({type:'model-prepare',importBatchId:'synthetic-import'});
  assert.deepEqual(JSON.parse(calls[0].body),{import_batch_id:'synthetic-import',protocol:'nextrelay.model/2'});
});
