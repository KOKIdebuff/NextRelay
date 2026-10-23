import { WorkspaceAdapter } from './workspace-adapter.js';

export class APIError extends Error {
  constructor(code,status=0){super(status?`服务端拒绝（${status}）：${code}`:`连接中断，结果尚未确认：${code}`);this.status=status;this.code=code;}
}
const key=()=>crypto.randomUUID();
const empty=()=>({mode:'local',projectId:null,title:'请选择或创建项目',goal:'本地真实 API · 仅使用自行编写的合成资料',snapshotVersion:0,sourceTime:'尚未载入',tasks:[],edges:[],documents:[],relations:[],candidates:[],batches:[],changes:[],constraints:[],formal:null});
const life={todo:'待办','in-progress':'进行中','awaiting-acceptance':'待验收',accepted:'已验收'};
const validity={applicable:'适用','pending-review':'待复核',inapplicable:'不适用',unknown:'未知'};
const processing={applied:'confirm',approve:'approved',reject:'reject',defer:'defer',pending:'pending',superseded:'superseded'};
const pretty=v=>JSON.stringify(v,null,2);
const operationNames={'task.create':'创建任务','task.update':'修改任务目标／标题','version.confirm':'确认精确成果版本','baseline.set':'指定需求主基线','task.start':'开始任务','task.submit':'提交待验收','acceptance.human':'明确人工验收','acceptance.auto':'预授权检查验收','check.authorize':'授权精确版本检查验收','dependency.add':'添加硬依赖','recheck.resolve':'处理待复核事项','change.revoke':'单次撤销'};
export async function encodeFile(file){
  const bytes=new Uint8Array(await file.arrayBuffer());let text='';
  for(let i=0;i<bytes.length;i+=32768)text+=String.fromCharCode(...bytes.subarray(i,i+32768));
  return {name:file.name,media_type:file.type||null,base64:btoa(text)};
}

export class LocalAdapter extends WorkspaceAdapter {
  constructor(token,{fetchImpl=globalThis.fetch?.bind(globalThis),storage=globalThis.sessionStorage}={}){
    super();this.token=token;this.fetch=fetchImpl;this.storage=storage;this.projectId=null;this.pending=null;this.view=empty();this.bodyCache=new Map();
    try{const p=JSON.parse(storage?.getItem('nextrelay.pending')||'null');if(p&&/^[A-Za-z0-9_-]{8,128}$/.test(p.requestKey)&&typeof p.path==='string'&&p.path.startsWith('/api/'))this.pending={path:p.path,requestKey:p.requestKey};}catch{/* invalid local UI metadata grants no authority */}
  }
  async request(path,{body,requestKey}={}){
    if(typeof path!=='string'||!path.startsWith('/api/')||path.includes('\\')||path.includes('#'))throw Error('仅允许当前服务的同源 API 地址');
    let response;
    try{response=await this.fetch(path,{method:body===undefined?'GET':'POST',headers:{Authorization:`Bearer ${this.token}`,...(body===undefined?{}:{'Content-Type':'application/json','Idempotency-Key':requestKey})},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store',credentials:'omit'});}
    catch{throw new APIError('network_unavailable');}
    let result;try{result=await response.json();}catch{throw new APIError('invalid_response',response.ok?0:response.status);}
    if(!response.ok)throw new APIError(result.error||'request_failed',response.status);
    return result;
  }
  path(resource=''){if(!this.projectId)throw Error('请先选择或创建项目');return `/api/projects/${encodeURIComponent(this.projectId)}${resource?'/'+resource:''}`;}
  async read(){
    const [caps,projects]=await Promise.all([this.request('/api/workspace'),this.request('/api/projects')]);
    this.capabilities=caps;this.projects=projects.projects;
    if(!this.projects.some(p=>p.id===this.projectId))this.projectId=this.projects.find(p=>p.id===this.storage?.getItem('nextrelay.project'))?.id||this.projects[0]?.id||null;
    if(!this.projectId){this.view={...empty(),projects:this.projects,capabilities:caps};return this.view;}
    const pid=this.projectId;
    const [raw,imports]=await Promise.all([this.request(this.path('snapshot')),caps.local_storage.directory?this.request(this.path('imports')):Promise.resolve({batches:[]})]);
    const documents=await Promise.all(raw.versions.map(async v=>{
      const id=v.native_relation?.family_id||v.artifact_id,a=raw.artifacts.find(a=>a.id===id);
      if(!this.bodyCache.has(v.id)){const full=await this.request(`/api/projects/${pid}/versions/${v.id}`);this.bodyCache.set(v.id,full.version.content);}
      return {id,version:v.id,ordinal:v.ordinal,title:a.title,filename:a.title,status:'available',summary:'精确成果版本 · '+v.content_sha256,outcome:v.revision_reason,pending:[],body:[{id:'body',heading:'版本正文',text:this.bodyCache.get(v.id)}],source:v.provenance.sources.map(s=>s.reference||s.id).join('；')||'来源待关联',evidence:raw.evidence.filter(e=>e.version_id===v.id).map(pretty),versions:raw.versions.filter(r=>(r.native_relation?.family_id||r.artifact_id)===id).map(r=>`v${r.ordinal} · ${r.id} · ${r.content_sha256}`),authority:raw.formal.baseline?.version_id===v.id,provenance:v.provenance};
    }));
    const batches=await Promise.all(imports.batches.map(async b=>{
      const items=await Promise.all(b.items.map(async item=>{
        const input=item.inputs.find(i=>i.id===item.current_input_id)||item.inputs.at(-1),latest=item.latest;
        const status=latest?.save_status==='saved'?(latest.parse_status==='parsed'?'已解析':latest.parse_status==='not-requested'?'仅保存':latest.parse_status==='unsupported'?'不支持':'失败'):'失败';
        if(latest?.parse_status==='parsed'){
          const parsed=await this.request(`/api/projects/${pid}/items/${item.id}/parsed`);
          const text=parsed.text??parsed.protocol?.documents.map(d=>`${d.title}\n${d.text}`).join('\n\n')??pretty(parsed);
          documents.push({id:'import-'+item.id,version:latest.result_sha256,title:input.name,filename:input.name,status:'available',summary:item.semantic_status==='extracted'?'已原生提取；归属与候选见下方':'本地格式解析；可执行原生提取',outcome:'原件已保存',pending:[],body:[{id:'body',heading:'完整格式正文',text}],source:latest.source_id+' · '+input.fingerprint,evidence:[],versions:item.attempts.map(a=>`尝试 ${a.ordinal} · ${a.parse_status} · ${a.result_sha256||a.reason}`),batchId:b.id,importItem:item.id});
        }
        return {id:item.id,name:input.name,status,reason:latest?.reason||(!latest?'pending':''),attempts:item.attempts.length,raw:item};
      }));
      return {...b,items,candidateIds:[],resultDocs:documents.filter(d=>d.batchId===b.id).map(d=>`${d.id}|${d.version}`)};
    }));
    const f=raw.formal,derived=f.derived?.tasks||[];
    const candidates=raw.candidates.map(c=>({id:c.candidate_id,raw:c,title:(operationNames[c.operation]||c.operation)+(c.spec.payload.title?'：'+c.spec.payload.title:''),base:c.spec.base_revision,kind:c.risk,state:processing[c.processing]||c.processing,taskId:c.target_id,batchId:'',current:pretty(c.spec.preconditions.task||c.spec.preconditions),proposed:pretty(c.spec.payload),basis:c.spec.source_ids.join('；')||'未提供来源；请核对创建依据，不视为文件自动提取结果',impact:c.spec.impact,history:raw.reviews.filter(r=>r.candidate_id===c.candidate_id).map(r=>`${r.decision} · ${r.basis}`)}));
    const tasks=f.tasks.map((t,i)=>{
      const d=derived.find(d=>d.task_id===t.task_id);
      if(!d)throw Error('服务端状态缺少派生快照，不能计算替代状态');
      const version=raw.versions.find(v=>v.id===d.version_id);
      return {id:t.task_id,title:t.title,goal:t.goal,conditions:[t.completion_conditions],lifecycle:life[d.lifecycle]||d.lifecycle,validity:validity[d.validity]||d.validity,blocking:d.blockers.map(b=>`${b.task_id} · ${b.reason}`),review:d.review_reasons.map(r=>`${r.id} · ${r.reason}`),executable:d.executable,decisions:candidates.filter(c=>c.taskId===t.task_id&&['pending','approved','defer'].includes(c.state)).length,document:version?(version.native_relation?.family_id||version.artifact_id):null,version:d.version_id||null,x:40+(i%3)*350,y:40+Math.floor(i/3)*220,acceptance:d.current_acceptance_ids.join('；'),raw:t,derived:d};
    });
    const changes=raw.history.applied_changes.map(a=>{const spec=JSON.parse(a.effect_json);return {id:a.id,title:spec.operation,taskId:spec.target_id,version:raw.history.change_commits.find(c=>c.id===a.commit_id)?.revision,active:f.change_effects.find(e=>e.change_id===a.id)?.active,dependsOn:[],group:a.commit_id,basis:raw.reviews.find(r=>r.id===a.review_id)?.basis||'',raw:a};});
    this.storage?.setItem('nextrelay.project',pid);
    this.view={mode:'local',projectId:pid,title:f.project.title,goal:'真实本地业务 API · 原生提取与独立审查 · Context Sync 尚未接通',snapshotVersion:f.project.revision,sourceTime:'读取于 '+new Date().toLocaleString('zh-CN')+'；来源时间见记录',projects:this.projects,capabilities:caps,tasks,edges:f.current_dependencies.map(d=>[d.predecessor_id,d.successor_id]),documents,relations:f.confirmed_versions.map(r=>({taskId:r.task_id,document:(raw.versions.find(v=>v.id===r.version_id)?.native_relation?.family_id||raw.versions.find(v=>v.id===r.version_id)?.artifact_id),version:r.version_id,state:'confirmed'})),candidates,batches,changes,constraints:[],formal:f,raw};
    return this.view;
  }
  async post(resource,body){
    if(this.pending)throw Error('有结果未确认的请求，请先查询或恢复原请求');
    const path=resource.startsWith('/api/')?resource:this.path(resource);
    const requestKey=key();if(['commits','auto-accept'].includes(resource))body={...body,request_key:requestKey};
    // No credential/body in persistent browser storage. Keep exact request in memory for recovery.
    this.pending={path,body,requestKey};this.storage?.setItem('nextrelay.pending',JSON.stringify({path,requestKey}));return this.resume();
  }
  clearPending(){this.pending=null;this.storage?.removeItem?.('nextrelay.pending');}
  async resume(){
    const p=this.pending;if(!p)throw Error('没有待恢复请求');
    try{
      if(p.body===undefined){
        const prior=await this.request('/api/requests/'+encodeURIComponent(p.requestKey));
        this.clearPending();return prior;
      }
      if(p.path.endsWith('/commits')){
        const prior=await this.request(p.path+'/'+p.requestKey);
        if(prior.result){this.clearPending();return prior.result;}
      }
      const result=await this.request(p.path,{body:p.body,requestKey:p.requestKey});this.clearPending();return result;
    }catch(e){if(e.status&&e.status<500)this.clearPending();throw e;}
  }
  async submit(intent){
    let message='服务端事务已确认；已重新读取当前状态。';
    if(intent.type==='resume-request'){const result=await this.resume();if(result?.state==='not-committed')message='服务端未提交此请求；可核对后重新操作。';else message='已查询原请求记录，请核对当前状态及逐项结果。';}
    else if(intent.type==='refresh'){/* authoritative reload */}
    else if(intent.type==='create-project'){
      const p=await this.post('/api/projects',{title:intent.title});this.projectId=p.id;
    }else if(intent.type==='upload'){
      const caps=this.capabilities.limits,files=[...intent.files];
      if(!files.length||files.length>caps.files||files.some(f=>f.size>caps.file_bytes)||files.reduce((n,f)=>n+f.size,0)>caps.batch_bytes)throw Error('文件超出 20 项／单项 5 MiB／批次 25 MiB 限额');
      await this.post('imports',{storage_choice:'configured-local',parse:intent.parse,files:await Promise.all(files.map(encodeFile))});message='导入请求已确认，请核对逐项结果；失败项没有被标记为成功。';
    }else if(intent.type==='retry-item'){
      if(intent.file&&intent.file.size>this.capabilities.limits.file_bytes)throw Error('替换文件超过单项 5 MiB 限额');
      await this.post(`items/${intent.id}/retry`,intent.file?{replacement:await encodeFile(intent.file)}:{use_original:true});message='单项重试请求已确认，请查看该项保存与解析结果。';
    }else if(intent.type==='process-batch'){
      await this.post(`imports/${intent.id}/process`,{});message='已恢复尚未处理项；请查看逐项结果。';
    }else if(intent.type==='extract-item'){
      await this.post(`items/${intent.id}/extract`,{base_revision:this.view.snapshotVersion});message='原生提取已保存；候选尚未审查或正式提交。';
    }else if(intent.type==='native-correct'||intent.type==='native-rematch'||intent.type==='native-candidates'){
      const doc=this.view.raw.native.runs.flatMap(r=>r.documents).find(d=>d.id===intent.id);
      if(!doc)throw Error('提取结果不存在，请刷新');
      await this.post(`native/documents/${intent.id}/${intent.type.slice(7)}`,{base_revision:this.view.snapshotVersion,expected_decision_id:doc.decision.id,...(intent.type==='native-correct'?{matches:intent.matches,basis:intent.basis}:{})});message='原生归属／候选记录已保存；正式状态须独立审查提交。';
    }else if(intent.type==='native-version-correct'){
      const doc=this.view.raw.native.runs.flatMap(r=>r.documents).find(d=>d.id===intent.id);
      if(!doc?.relation)throw Error('此版本没有原生版本关系');
      await this.post(`native/versions/${doc.version_id}/correct`,{base_revision:this.view.snapshotVersion,expected_relation_id:doc.relation.id,...intent.request});message='版本关系纠正已追加保存；旧版本正文、权威及验收保持独立。';
    }else if(intent.type==='run-check'){
      await this.post('checks',{task_id:intent.taskId,version_id:intent.versionId,configuration:intent.configuration});message='本地内置检查已执行；查看服务端真实结果。检查通过仍不等于验收。';
    }else if(intent.type==='auto-accept'){
      await this.post('auto-accept',{base_revision:this.view.snapshotVersion,task_id:intent.taskId,version_id:intent.versionId,check_id:intent.checkId,authorization_id:intent.authorizationId});
    }else if(intent.type==='save-candidate'){
      await this.post('candidates',intent.request);message='候选已保存；尚未审查或正式提交。';
    }else if(intent.type==='review'){
      const cs=intent.ids.map(id=>this.view.candidates.find(c=>c.id===id)?.raw);
      if(cs.some(c=>!c)||!cs.length)throw Error('候选选择无效');
      const explicit=cs.some(c=>c.risk!=='ordinary');
      if(explicit&&cs.length!==1)throw Error('高风险候选必须单独审查');
      await this.post('reviews',{selection:cs.map(c=>({candidate_id:c.candidate_id,fingerprint:c.fingerprint})),decision:intent.decision,mode:explicit?'explicit':'ordinary',basis:intent.basis,input_origin:'local-user',...(intent.decision==='approve'&&explicit?{authorization:cs[0].authorization}:{})});message='审查已持久保存；正式状态尚未提交。';
    }else if(intent.type==='commit'){
      const cs=intent.ids.map(id=>this.view.candidates.find(c=>c.id===id)?.raw);
      if(!cs.length||cs.some(c=>!c||c.processing!=='approve'))throw Error('请选择已批准且未提交的候选');
      await this.post('commits',{base_revision:this.view.snapshotVersion,selection:cs.map(c=>({candidate_id:c.candidate_id,review_id:c.latest_review_id}))});
    }else if(intent.type==='reversal-preview'){
      this.reversal=await this.post('reversal-previews',{change_id:intent.id});message='撤销预览已保存；尚未撤销。';
    }else throw Error('此能力尚未接通，未执行任何模拟成功操作');
    try{return {message,view:await this.read()};}catch(e){throw Error(`操作响应已收到，但状态重新读取失败；请刷新核对。${e.message}`);}
  }
}
