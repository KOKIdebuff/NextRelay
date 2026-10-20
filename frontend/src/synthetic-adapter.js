import { WorkspaceAdapter } from './workspace-adapter.js';
export const scenarios = { normal:'正常项目', empty:'空项目', noArtifacts:'无成果', loading:'加载中', failure:'加载失败', stale:'过期预览' };
const sections = [
  ['文件分类与来源记录','按需求、方案、验证与会话报告分类。来源不明时明确记录未知，不把导入批次当作 Session；一个任务可以关联多个会话，一个会话也能贡献给多个任务。'],
  ['导入执行与结果校验','逐项检查格式和完整性。成功项保留独立结果；失败项展示具体原因，修正后单独重试。已解析只是来源处理事实，不能据此判定任务已验收。'],
  ['独立失败处理与重试','失败不会回滚同批成功项。重试沿用对应文件身份，新的发送范围必须重新授权。不得把摘要作为全文，来源不可读时保留受限提示。'],
  ['版本关系与证据','内容更新形成独立版本。证据绑定成果版本，v1 的验证不能无条件沿用到 v2。版本归并不提升权威性，不替代人工确认。'],
  ['任务与硬依赖','四种生命周期与阻塞、待复核原因分别呈现。前置成果待复核时，历史验收记录仍保留，但不能直接释放其下游依赖。'],
  ['候选与正式状态','报告中的完成声明只形成候选依据。普通项按实际选择确认；冲突单独处理。拒绝和暂缓均不生效，旧预览必须刷新后重新选择。'],
  ['保存与处理授权','本地原件由用户管理。保存位置和本批模型处理许可互不替代；发送清单包括所选文件以及实际附带的旧基线、摘要和证据。'],
  ['复用与上下文交接','有效正文仅收录当前适用约束和可复用成果。待复核、冲突和候选放入独立提醒；折叠来源不应减少复制文本中的必要约束。'],
  ['异常与边界','资料缺失、载入失败和访问受限有不同原因。不得用模糊成功消息掩盖全文缺失；所有模拟操作只更新隔离示例，不写真实项目。'],
  ['下一步验证','补齐版本匹配、文件隔离和授权拒绝的真实证据，再判断成果适用性。本节是全文末段，摘要没有包含这些执行细节。']
];
function document(id, version, title, status='available') {
  return { id, version, title, filename: id==='report'?'session-report.md':id==='baseline'?'requirements.md':`${id}.md`, summary:'梳理导入、来源记录与独立失败处理方案；验证记录仍需补充。', status,
    reason: { missing:'只有摘要；本地原件尚未重新关联', denied:'当前示例主体无权读取原件', failed:'正文载入失败，请重试', unavailable:'原始来源不可用' }[status],
    outcome:'形成逐文件处理与候选审查方案，方案说明不代表实现或验收已完成。', pending:['补充 v2 对应验证记录','核对格式错误、缺少字段和独立重试'],
    source:'合成 Session 04 · 2026-10-19', evidence:[`${version}：仅有合成方案声明，尚无真实执行证据`,'验证缺口：格式隔离与版本匹配'], versions:['v1：初始方案','v2：补充失败隔离说明'],
    body:status==='available'?sections.map(([heading,text],i)=>({id:`section-${i}`,heading,text:`${text} ${version==='v1'?'本版本为早期草案，不包含后续补充的验证结论。':'本版本保留独立来源及待核验说明。'} ${text}`})):null };
}
export function createFixture(scenario='normal', projectId='demo') {
  const documents=[document('report','v2','导入流程工作报告'),document('report','v1','导入流程工作报告'),document('baseline','v1','需求主基线'),document('notes','v1','交接说明'),document('missing','v1','未关联原件','missing'),document('denied','v1','受限证据','denied'),document('failed','v1','载入失败示例','failed'),document('unavailable','v1','离线来源','unavailable')];
  const tasks=[
    {id:'task-1',title:'确认需求主基线',lifecycle:'已验收',blocking:[],review:[],validity:'适用',document:'baseline',version:'v1',x:320,y:30},
    {id:'task-2',title:'整理会话成果',lifecycle:'待验收',blocking:[],review:['验证记录待补充','成果版本需要复核'],validity:'待复核',document:'report',version:'v2',x:100,y:240},
    {id:'task-3',title:'补齐验证记录',lifecycle:'进行中',blocking:[],review:[],validity:'适用',document:'failed',version:'v1',x:550,y:240},
    {id:'task-4',title:'检查成果适用性',lifecycle:'待办',blocking:['整理会话成果尚未验收','补齐验证记录尚未验收'],review:[],validity:'适用',document:'notes',version:'v1',x:320,y:455},
    {id:'task-5',title:'核对未知来源',lifecycle:'待办',blocking:[],review:['来源需要重新关联'],validity:'待复核',document:'missing',version:'v1',x:780,y:455},
    {id:'task-6',title:'准备下轮交接',lifecycle:'待办',blocking:['检查成果适用性尚未验收'],review:[],validity:'适用',document:null,version:null,x:320,y:665}
  ];
  const candidates=[
    {id:'c1',title:'新增任务：核对导入清单',current:'当前没有该任务',proposed:'新增待办任务：核对导入清单',impact:'增加一项待办；不会自动执行',kind:'ordinary',state:'pending',base:7},
    {id:'c2',title:'状态建议：补齐验证记录',current:'进行中',proposed:'待验收',impact:'只提交待验收，不代表已验收；下游硬依赖保持',kind:'ordinary',state:'pending',base:7},
    {id:'c3',title:'需求约束冲突：验证范围与交付时间',current:'全部关键路径必须有验证证据',proposed:'提前交付并略过部分验证',impact:'涉及已确认约束，需要单独明确取舍；批量操作不包含此项',kind:'conflict',state:'pending',base:7}
  ];
  return {mode:'synthetic',projectId,scenario,snapshotVersion:scenario==='stale'?8:7,sourceTime:'2026-10-19 18:30（合成快照）',
    title:projectId==='demo'?'NextRelay MVP · 示例':'续程实验室 · 示例',
    tasks:scenario==='empty'?[]:tasks,edges:scenario==='empty'?[]:[['task-1','task-2'],['task-1','task-3'],['task-2','task-4'],['task-3','task-4'],['task-4','task-6']],
    documents:['empty','noArtifacts'].includes(scenario)?[]:documents,candidates:scenario==='empty'?[]:candidates,
    batches:[],intentLog:[],handoff:{body:'任务目标：评估成果适用性。\n下一步：先补齐验证记录并完成前置任务验收，再判断成果适用性。',constraints:['候选变更须确认后生效。','验收证据必须匹配适用版本。','不自动发送或运行外部 AI。'],reusable:['requirements.md · v1 · 当前适用的需求主基线'],reminders:['导入报告 v2 待复核，不可直接作为可复用成果。','扩大读取范围的方案尚未确认。','前置任务尚未验收；当前任务受阻塞。'],sources:['合成 Session 04 · session-report.md v2','合成主基线 · requirements.md v1']} };
}
export class SyntheticAdapter extends WorkspaceAdapter {
  constructor(scenario='normal',projectId='demo'){super();this.state=createFixture(scenario,projectId);}
  async read(){return structuredClone(this.state);}
  async submit(intent){
    const s=this.state;
    if(intent.type==='retry-document'){
      const d=s.documents.find(d=>d.id===intent.id&&d.version===intent.version);
      if(d?.status!=='failed')throw Error('仅载入失败可重试；来源权限不能由重试绕过');
      Object.assign(d,document(d.id,d.version,d.title));
    }else if(intent.type==='refresh-preview'){
      s.candidates.filter(c=>c.state==='pending').forEach(c=>c.base=s.snapshotVersion);
    }else if(intent.type==='candidate'){
      const items=s.candidates.filter(c=>intent.ids.includes(c.id));
      if(!items.length||items.length!==new Set(intent.ids).size||items.some(c=>c.state!=='pending'))throw Error('选择已失效，请重新选择');
      if(items.some(c=>c.base!==s.snapshotVersion))throw Error('预览版本已过期，请刷新并重新选择');
      if(!['confirm','reject','defer'].includes(intent.action))throw Error('未知审查动作');
      if(items.some(c=>c.kind!=='ordinary')&&(items.length!==1||!intent.separate))throw Error('冲突必须单独处理');
      if(items.some(c=>c.kind==='conflict')&&intent.action==='confirm'&&!intent.resolution)throw Error('请选择冲突解决方向');
      items.forEach(c=>{c.state=intent.action;c.resolution=intent.resolution;});
      if(intent.action==='confirm'){
        if(items.some(c=>c.id==='c1'))s.tasks.push({id:'task-7',title:'核对导入清单',lifecycle:'待办',blocking:[],review:[],validity:'适用',document:'report',version:'v2',x:780,y:665});
        if(items.some(c=>c.id==='c2'))s.tasks.find(t=>t.id==='task-3').lifecycle='待验收';
        s.snapshotVersion++;
      }
    }else if(intent.type==='create-batch'){
      const count=s.batches.length+1;
      s.batches.push({id:`batch-${count}`,saved:false,saveLocation:'local',authorization:'pending',items:[{id:'report',name:'session-report.md',status:'待处理',attempts:0},{id:'review',name:'review.json',status:'待处理',attempts:0},{id:'unsupported',name:'archive.zip',status:'不支持',reason:'本示例不支持压缩包',attempts:0}],manifest:['session-report.md 全文（合成）','review.json 全文（合成）','requirements.md v1 有效约束（合成）','当前项目摘要与关联证据（合成）']});
    }else if(intent.type==='save-batch'){
      const b=s.batches.find(b=>b.id===intent.batchId);if(!b)throw Error('批次不存在');
      b.saved=true;b.saveLocation=intent.location==='cloud'?'cloud':'local';
      if(b.authorization==='pending')b.authorization='denied';
      b.items.filter(i=>i.status==='待处理').forEach(i=>i.status='仅保存，未授权解析');
    }else if(intent.type==='authorize-batch'){
      const b=s.batches.find(b=>b.id===intent.batchId);if(!b)throw Error('批次不存在');
      b.authorization='granted';
      b.items.filter(i=>i.status==='待处理'||i.status==='仅保存，未授权解析').forEach(i=>{i.attempts++;i.status=i.id==='review'?'失败':'已解析';i.reason=i.id==='review'?'合成 JSON 缺少字段；可模拟修正后重试':undefined;});
    }else if(intent.type==='retry-item'){
      const b=s.batches.find(b=>b.id===intent.batchId),i=b?.items.find(i=>i.id===intent.id);
      if(!i||i.status!=='失败'||b.authorization!=='granted')throw Error('只允许重试本批获授权失败项');
      i.attempts++;i.status='已解析';i.reason=undefined;
    }else throw Error('未知操作意图');
    s.intentLog.push(structuredClone(intent));
    return {message:'模拟操作已完成；仅更新隔离示例，无真实授权、审批或审计',view:await this.read()};
  }
}
export function filteredTasks(tasks,filter){return tasks.filter(t=>filter==='全部'||filter==='可执行'&&t.lifecycle!=='已验收'&&!t.blocking.length||filter==='阻塞'&&t.blocking.length||filter==='待复核'&&t.review.length||t.lifecycle===filter);}
export function handoffText(view){const h=view.handoff;return [`NextRelay · 示例交接 · ${view.projectId} · 快照 v${view.snapshotVersion}`,view.sourceTime,h.body,'必要有效约束',...h.constraints,'可直接复用',...(view.documents.length?h.reusable:['暂无可直接复用的成果；请先导入资料并核实适用性。']),'关键未决提醒（不作为正式约束）',...h.reminders,'来源附录',...(view.documents.length?h.sources:['当前场景没有可读取来源'])].join('\n');}
