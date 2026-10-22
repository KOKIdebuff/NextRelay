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
