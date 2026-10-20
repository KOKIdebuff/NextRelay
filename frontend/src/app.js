import { SyntheticAdapter, scenarios, filteredTasks, handoffText } from './synthetic-adapter.js';
import { ReaderRecords, readerKey, snapMode } from './reader-state.js';
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths={home:'M2 7h2V5h2V3h4v2h2v2h2v7H9v-4H7v4H2z',file:'M3 1h7v2h3v12H3z M5 5h6M5 8h6M5 11h5',folder:'M1 4h5V2h5v2h4v10H1z',review:'M3 3h3V1h4v2h3v12H3z M5 8l2 2 4-4',handoff:'M2 3h9V1l4 4-4 4V7H2z M14 13H5v2l-4-4 4-4v2h9z'};
function icon(name){return `<svg class="icon" aria-hidden="true" viewBox="0 0 16 16"><path d="${paths[name]||paths.file}"/></svg>`;}
const navs=[['overview','项目概览','home'],['tasks','任务','file'],['imports','资料与成果','folder'],['review','待确认','review'],['handoff','上下文交接','handoff']];
const names=Object.fromEntries(navs.map(n=>[n[0],n[1]]));
const records=new ReaderRecords();
const ui={page:'overview',project:'demo',scenario:'normal',task:'task-2',filter:'全部',view:'list',mode:'half',doc:'report',version:'v2',listTop:0,graph:{x:0,y:0,z:.8,initialized:false},selected:new Set(),locationChoices:{}};
const projects=new Map();
let adapter=new SyntheticAdapter(),data=await adapter.read(),generation=0,readerObserver,noticeTimer;
const root=$('#app');
function toast(message){clearTimeout(noticeTimer);$('#notice').textContent=message;noticeTimer=setTimeout(()=>$('#notice').textContent='',6500);}
function badge(text,kind=''){return `<span class="badge ${kind}">${esc(text)}</span>`;}
function taskFilename(t){return data.documents.find(d=>d.id===t.document&&d.version===t.version)?.filename||`${t.document} · 引用未载入`;}
function life(t){return badge(t.lifecycle,{'已验收':'green','待验收':'amber','进行中':'blue'}[t.lifecycle]);}
function reminder(t){return `${t.blocking.map(r=>badge(`阻塞 · ${r}`,'red')).join('')}${t.review.map(r=>badge(`待复核 · ${r}`,'amber')).join('')}`||'<span class="muted">无独立提醒</span>';}
function button(action,text,cls='',attrs=''){return `<button class="${cls}" data-action="${action}" ${attrs}>${text}</button>`;}
function blank(title,text,action='imports',label='前往资料与成果'){return `<div class="empty pixel"><h2>${esc(title)}</h2><p>${esc(text)}</p>${button('navigate',label,'primary',`data-page="${action}"`)}</div>`;}
function saveReading(){const el=$('#reader-scroll');if(el&&el.getClientRects().length&&el.dataset.key)records.capture(el.dataset.key,el);if($('#task-list'))ui.listTop=$('#task-list').scrollTop;}
function shell(){
  root.innerHTML=`<aside class="sidebar"><div class="brand">NextRelay<small>续程</small></div><label class="project-label">当前示例项目<select id="project" aria-label="选择示例项目"><option value="demo">NextRelay MVP · 示例</option><option value="lab">续程实验室 · 示例</option></select></label><nav aria-label="主导航">${navs.map(([id,label,i])=>`<button data-page="${id}" data-action="navigate" aria-current="${ui.page===id?'page':'false'}">${icon(i)}<span>${label}</span>${id==='review'?`<span class="nav-count">${data.candidates.filter(c=>c.state==='pending').length}</span>`:''}</button>`).join('')}</nav><div class="sidebar-foot"><strong>示例数据 / 模拟操作</strong><p>资料依据截至<br>${esc(data.sourceTime)}</p><p>业务后端未接入<br>不会读取或发送真实资料</p><label>演示场景<select id="scenario" aria-label="演示场景">${Object.entries(scenarios).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label>${button('reset','重置示例状态','quiet')}</div></aside><main id="main"><div class="mode-banner"><span>合成数据沙盒</span><span>所有保存、解析、审批均为模拟</span><code>快照 v${data.snapshotVersion}</code></div><div id="page"></div></main>`;
  $('#project').value=ui.project;$('#scenario').value=ui.scenario;
  $('#project').onchange=e=>switchProject(e.target.value);
  $('#scenario').onchange=e=>changeScenario(e.target.value);
  renderPage();
}
function header(title,subtitle,actions=''){return `<header class="page-header"><div class="title-icon">${icon(ui.page==='imports'?'folder':'file')}</div><div><p class="eyebrow">NEXTRELAY / ${esc(names[ui.page])}</p><h1>${title}</h1><p>${subtitle}</p></div><div class="header-actions">${actions}</div></header>`;}
function renderPage(){
  readerObserver?.disconnect();const page=$('#page');page.className=ui.page==='tasks'?'task-page':'';
  if(ui.scenario==='loading'){page.innerHTML=header(names[ui.page],'合成场景 · 正在载入')+blank('正在载入示例快照','此场景保持加载以供检查；点击下方完成模拟。','overview','完成模拟加载');page.querySelector('[data-action="navigate"]').dataset.action='recover';return;}
  if(ui.scenario==='failure'){page.innerHTML=header(names[ui.page],'合成场景 · 载入失败')+blank('示例快照载入失败','没有读取任何真实服务。可重试返回正常示例。','overview','重试载入');page.querySelector('[data-action="navigate"]').dataset.action='recover';return;}
  if(ui.page==='overview')renderOverview();
  if(ui.page==='tasks')renderTasks();
  if(ui.page==='imports')renderImports();
  if(ui.page==='review')renderReview();
  if(ui.page==='handoff')renderHandoff();
}
function renderOverview(){
  const empty=!data.tasks.length;
  $('#page').innerHTML=header('项目概览','把分散的会话成果，接成可以继续推进的项目。',button('navigate','导入成果','primary','data-page="imports"'))+`<div class="page-content"><div class="overview-intro"><div><span class="eyebrow">当前工作空间</span><h2>${esc(data.title)}</h2><p>先看当前事项，再把下一段工作接好。</p></div>${badge('示例项目 · 非实时状态','blue')}</div><section class="pixel"><div class="section-heading"><h2>${icon('file')}开发准备</h2>${badge(empty?'文档待完善':'依据示例记录 · 待核对','amber')}</div><p>准备判断来自文档版本与确认记录，不能靠文件数量自动判定。</p><div class="rows">${['需求主基线','架构方案','实施计划'].map((s,i)=>`<div class="info-row"><strong>${s}</strong><code>${['requirements.md · v1','architecture.md · v1','plan.md · v1'][i]}</code>${badge(empty?'尚未导入':i===2?'具体版本待确认':'示例确认记录',i===2||empty?'amber':'green')}</div>`).join('')}</div><p class="info">准备任务可以先完成，资料导入不受此检查点限制。</p></section><section class="pixel"><div class="section-heading"><h2>${icon('review')}接下来做什么</h2><span class="muted">依据合成快照</span></div>${empty?'<p>项目还没有任务，可以先导入示例成果。</p>':`<div class="action-row"><div><strong>审查候选变更</strong><p>${data.candidates.filter(c=>c.state==='pending').length} 项待处理，冲突独立审查</p></div>${button('navigate','进入审查','link','data-page="review"')}</div><div class="action-row"><div><strong>补齐验证记录</strong><p>生命周期与独立提醒分别记录</p></div>${button('navigate','查看任务','link','data-page="tasks"')}</div><div class="action-row"><div><strong>检查成果适用性</strong><p>前置任务尚未验收，依赖未解除</p></div>${button('dependency','查看依赖','link','data-task="task-4"')}</div>`}</section><section class="pixel"><div class="section-heading"><h2>${icon('folder')}最近导入的成果</h2>${button('navigate','查看全部资料','link','data-page="imports"')}</div>${data.documents.length?`<div class="info-row"><strong>session-report.md</strong><code>v2 · 2026-10-19</code>${badge('合成已解析','green')}${button('open-document','阅读成果','quiet','data-doc="report" data-version="v2"')}</div><p class="info">解析完成不代表任务已验收。来源时间不代表实时监控。</p>`:'<p>暂无成果。可以模拟选择合成文件，不需要上传真实资料。</p>'}</section></div>`;
}
function taskToolbar(){return `<div class="task-toolbar"><div class="filters" aria-label="任务筛选">${['全部','可执行','阻塞','待验收','待复核'].map(f=>button('filter',f,ui.filter===f?'active':'',`data-filter="${f}" aria-pressed="${ui.filter===f}"`)).join('')}</div><span id="task-count" class="muted"></span></div>`;}
function renderTasks(){
  $('#page').innerHTML=`<div class="task-work" data-reader-mode="${ui.mode}"><div class="task-top">${header('任务','先看当前事项，再按需展开依赖与依据。',`<div class="segments">${button('view','列表',ui.view==='list'?'active':'','data-view="list"')}${button('view','任务图',ui.view==='graph'?'active':'','data-view="graph"')}</div>`)}${taskToolbar()}<div id="task-area"></div></div><section class="reader pixel" aria-label="文档阅读面板"><div id="reader-handle" tabindex="0" role="separator" aria-label="调整文档面板高度" aria-orientation="horizontal" aria-valuemin="0" aria-valuemax="2"><span></span></div><div class="reader-bar"><div class="reader-identity"></div><div class="segments">${['collapsed','half','full'].map((m,i)=>button('mode',['收起','半屏','全屏'][i],'',`data-mode="${m}"`)).join('')}</div></div><div id="reader-scroll" tabindex="0" aria-label="文档正文"></div></section></div>`;
  renderTaskArea();renderDocument();applyMode();wireHandle();
  const scroller=$('#reader-scroll');
  scroller.addEventListener('scroll',()=>{if(scroller.dataset.key&&scroller.getClientRects().length)records.capture(scroller.dataset.key,scroller);},{passive:true});
  scroller.addEventListener('toggle',()=>{if(scroller.dataset.key)records.capture(scroller.dataset.key,scroller);},true);
  let width=scroller.clientWidth;
  readerObserver=new ResizeObserver(()=>{if(scroller.clientWidth!==width){width=scroller.clientWidth;restoreReading();}});readerObserver.observe(scroller);
}
function renderTaskArea(){
  const tasks=filteredTasks(data.tasks,ui.filter);$('#task-count').textContent=`${tasks.length} 项任务 · 同一快照`;
  if(!tasks.length){$('#task-area').innerHTML=blank('当前没有匹配任务',data.tasks.length?'请切换筛选查看其他任务。':'先导入资料，再恢复任务。');return;}
  if(ui.view==='list'){
    $('#task-area').innerHTML=`<div id="task-list" tabindex="0" aria-label="任务列表滚动区"><table><thead><tr><th>任务 / 关联成果</th><th>生命周期</th><th>独立提醒</th><th>操作</th></tr></thead><tbody>${tasks.map(t=>`<tr class="${ui.task===t.id?'selected':''}" data-task-row="${t.id}"><td><button class="task-select" data-action="select-task" data-task="${t.id}" aria-pressed="${ui.task===t.id}">${icon('file')}<span><strong>${esc(t.title)}</strong><small>${esc(t.document?`${taskFilename(t)} · ${t.version}`:'暂无关联文件')}</small></span></button></td><td>${life(t)}</td><td class="reminders">${reminder(t)}</td><td>${button('dependency','查看依赖','quiet',`data-task="${t.id}"`)}</td></tr>`).join('')}</tbody></table></div>`;
    $('#task-list').scrollTop=ui.listTop;
  }else{
    const visible=new Set(tasks.map(t=>t.id));
    $('#task-area').innerHTML=`<div id="graph" tabindex="0" aria-label="任务依赖图，可用方向键平移，加减键缩放"><div id="graph-world"><svg class="edges" viewBox="0 0 1160 860" aria-label="硬依赖连线"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0 0L6 3L0 6"/></marker></defs>${data.edges.filter(([a,b])=>visible.has(a)&&visible.has(b)).map(([a,b])=>{const x=data.tasks.find(t=>t.id===a),y=data.tasks.find(t=>t.id===b);return `<path d="M${x.x+145} ${x.y+145} V${(x.y+145+y.y)/2} H${y.x+145} V${y.y}" marker-end="url(#arrow)"/>`;}).join('')}</svg>${tasks.map(t=>`<button class="graph-card pixel ${ui.task===t.id?'selected':''}" data-action="select-task" data-task="${t.id}" aria-pressed="${ui.task===t.id}" style="left:${t.x}px;top:${t.y}px"><span class="card-title">${icon('file')}<strong>${esc(t.title)}</strong></span>${life(t)}<span class="card-meta">${esc(t.document?`${taskFilename(t)} · ${t.version}`:'暂无关联文件')}</span><span class="card-meta">${t.blocking.length?'阻塞 · '+t.blocking.length+' 项前置':t.review.length?'待复核 · '+t.review.length+' 项原因':'无独立提醒'}</span></button>`).join('')}</div></div><div class="graph-controls">${button('zoom-out','−','', 'aria-label="缩小任务图"')}<output id="zoom"></output>${button('zoom-in','+','','aria-label="放大任务图"')}${button('center','定位选中','','aria-label="定位选中任务"')}</div><div class="graph-help">拖动画布平移 · 滚轮缩放 · 方向键 / + −<br>仅 Task 节点；筛选后只显示范围内连线</div>`;
    if(!ui.graph.initialized)centerTask();else transformGraph();wireGraph();
  }
}
function currentDocument(){return data.documents.find(d=>d.id===ui.doc&&d.version===ui.version);}
function renderDocument(){
  const d=currentDocument(),scroll=$('#reader-scroll');
  const options=data.documents.map(d=>`<option value="${d.id}|${d.version}">${esc(d.title)} · ${d.version}${d.status!=='available'?' · 受限':''}</option>`).join('');
  $('.reader-identity').innerHTML=`${icon('file')}<div><strong>${esc(d?.title||'暂无关联文件')}</strong><small>${esc(d?`${d.filename} · ${d.version} · ${d.source}`:'当前任务尚未关联成果')}</small></div>`;
  if(!d){scroll.dataset.key='';scroll.innerHTML=`<article><h2>暂无可读成果</h2><p>当前任务或场景没有完整文档；不会用其他文档的正文补位。</p>${data.documents.length?`<label>选择项目内文档<select id="document-picker" aria-label="选择文档与版本"><option value="">请选择</option>${options}</select></label>`:button('navigate','导入示例资料','primary','data-page="imports"')}</article>`;wireDocumentPicker();return;}
  scroll.dataset.key=readerKey(ui.project,d.id,d.version);
  const unavailableAction=d.status==='failed'
    ?button('retry-document','重试载入示例正文','primary')
    :`<p>${d.status==='denied'?'真实权限须由后端校验，前端不能自行授权。':'请在真实接入后重新关联原件或核实来源。'}</p>${button('navigate','查看资料与限制','quiet','data-page="imports"')}`;
  const body=d.body
    ?`<section data-anchor="outcome"><h3>本次成果</h3><p>${esc(d.outcome)}</p></section>
      <section data-anchor="pending"><h3>待核验事项</h3><ul>${d.pending.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></section>
      <p class="document-divider">完整正文 · ${d.body.length} 节</p>
      ${d.body.map((s,i)=>`<section data-anchor="${s.id}"><h3><span class="step">${i+1}</span>${esc(s.heading)}</h3><p>${esc(s.text)}</p></section>`).join('')}`
    :`<div class="restricted" role="status"><h3>全文暂不可读取</h3><p>${esc(d.reason)}</p><p>当前仅显示已有摘要，不代表已取得全文。</p>${unavailableAction}</div>`;
  const detailRows=[['source','原始来源',d.source+'；原件与会话标识均为合成，未读取本地文件'],['evidence','证据与缺口',d.evidence.join('；')],['versions','版本历史',d.versions.join('；')]];
  scroll.innerHTML=`<article><div data-anchor="intro">
    <div class="document-controls"><label>文档与版本<select id="document-picker" aria-label="选择文档与版本">${options}</select></label>
    ${button('mode',ui.mode==='full'?'收回半屏':'展开阅读','primary',`data-mode="${ui.mode==='full'?'half':'full'}" id="expand-reader"`)}</div>
    <p class="eyebrow">${esc(d.filename)} / ${esc(d.version)} / 合成资料</p><h2>${esc(d.title)}</h2>
    <p class="info">仅为示例文档；已解析不代表任务已验收。</p><h3>摘要</h3><p>${esc(d.summary)}</p></div>${body}
    ${detailRows.map(([id,title,text])=>`<details data-detail="${id}" data-anchor="detail-${id}"><summary>${icon('file')}${title}</summary><p>${esc(text)}</p></details>`).join('')}</article>`;
  $('#document-picker').value=`${d.id}|${d.version}`;wireDocumentPicker();restoreReading();
}
function wireDocumentPicker(){const picker=$('#document-picker');if(picker)picker.onchange=e=>{saveReading();const [id,version]=e.target.value.split('|');ui.doc=id;ui.version=version;renderDocument();};}
function restoreReading(){const scroller=$('#reader-scroll');if(scroller?.dataset.key)requestAnimationFrame(()=>{if(scroller.isConnected&&scroller.getClientRects().length)records.restore(scroller.dataset.key,scroller);});}
function applyMode(){
  const work=$('.task-work');if(!work)return;work.dataset.readerMode=ui.mode;work.style.removeProperty('--drag-height');
  $('#reader-handle').setAttribute('aria-valuenow',String(['collapsed','half','full'].indexOf(ui.mode)));
  $('#reader-handle').setAttribute('aria-valuetext',{collapsed:'收起',half:'半屏',full:'全屏'}[ui.mode]);
  document.querySelectorAll('[data-action="mode"]').forEach(b=>{b.classList.toggle('active',b.dataset.mode===ui.mode);b.setAttribute('aria-pressed',String(b.dataset.mode===ui.mode));});
  const expand=$('#expand-reader');if(expand){expand.textContent=ui.mode==='full'?'收回半屏':'展开阅读';expand.dataset.mode=ui.mode==='full'?'half':'full';}restoreReading();
}
function setMode(mode){saveReading();ui.mode=mode;applyMode();}
function wireHandle(){
  const h=$('#reader-handle');let drag;
  h.onpointerdown=e=>{if(e.button!==0)return;saveReading();drag={y:e.clientY,height:$('.reader').getBoundingClientRect().height,total:$('.task-work').clientHeight};h.setPointerCapture(e.pointerId);h.classList.add('dragging');e.preventDefault();};
  h.onpointermove=e=>{if(!drag)return;const height=Math.max(76,Math.min(drag.total,drag.height+drag.y-e.clientY));$('.task-work').style.setProperty('--drag-height',`${height}px`);};
  h.onpointerup=e=>{if(!drag)return;const mode=snapMode(drag.height+drag.y-e.clientY,drag.total);drag=null;h.classList.remove('dragging');setMode(mode);};
  h.onpointercancel=()=>{drag=null;h.classList.remove('dragging');applyMode();};
  h.onkeydown=e=>{const modes=['collapsed','half','full'],i=modes.indexOf(ui.mode);let mode;if(e.key==='ArrowUp')mode=modes[Math.min(2,i+1)];if(e.key==='ArrowDown')mode=modes[Math.max(0,i-1)];if(e.key==='Home')mode='collapsed';if(e.key==='End')mode='full';if(mode){e.preventDefault();setMode(mode);}};
}
function transformGraph(){if(!$('#graph-world'))return;$('#graph-world').style.transform=`translate(${ui.graph.x}px,${ui.graph.y}px) scale(${ui.graph.z})`;$('#zoom').value=`${Math.round(ui.graph.z*100)}%`;}
function centerTask(){const t=data.tasks.find(t=>t.id===ui.task),g=$('#graph');if(t&&g){ui.graph.initialized=true;ui.graph.x=g.clientWidth/2-(t.x+145)*ui.graph.z;ui.graph.y=g.clientHeight/2-(t.y+75)*ui.graph.z;transformGraph();}}
function zoom(delta){ui.graph.z=Math.max(.35,Math.min(1.6,ui.graph.z+delta));transformGraph();}
function wireGraph(){
  const g=$('#graph');let drag;
  g.onpointerdown=e=>{if(e.target.closest('button')||e.button!==0)return;drag={x:e.clientX,y:e.clientY,px:ui.graph.x,py:ui.graph.y};g.setPointerCapture(e.pointerId);};
  g.onpointermove=e=>{if(drag){ui.graph.x=drag.px+e.clientX-drag.x;ui.graph.y=drag.py+e.clientY-drag.y;transformGraph();}};
  g.onpointerup=g.onpointercancel=()=>drag=null;
  g.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?-.05:.05);},{passive:false});
  g.onkeydown=e=>{if(e.target!==g)return;const moves={ArrowLeft:[30,0],ArrowRight:[-30,0],ArrowUp:[0,30],ArrowDown:[0,-30]};if(moves[e.key]){e.preventDefault();ui.graph.x+=moves[e.key][0];ui.graph.y+=moves[e.key][1];transformGraph();}if(['+','=','-'].includes(e.key)){e.preventDefault();zoom(e.key==='-'?-.1:.1);}};
}
function renderImports(){
  $('#page').innerHTML=header('资料与成果','带回一段工作，保留来源，再审查候选。',button('create-batch','选择合成文件','primary'))+`<div class="page-content"><div class="info">示例模式不提供真实文件上传或 GitHub 读取。选择仅添加预置合成文件。</div><section class="pixel"><div class="section-heading"><h2>1. 选择并添加文件</h2>${badge('仅合成来源','blue')}</div><div class="dropzone"><h3>${icon('folder')}选择合成文件，体验逐项处理</h3><p>Markdown / JSON 示例，以及一个不支持的压缩包</p>${button('create-batch','添加一批示例文件','primary')}</div><p>公开 GitHub：真实读取尚未接入，本原型没有 URL 输入或网络读取入口。</p></section>${data.batches.map(b=>`<section class="pixel" data-batch="${b.id}"><div class="section-heading"><h2>2. ${b.id} · 处理与授权</h2>${badge(b.saved?'模拟已保存':'尚未保存',b.saved?'green':'')}</div><div class="rows">${b.items.map(i=>`<div class="info-row" data-item="${i.id}"><div><strong>${esc(i.name)}</strong><small>${esc(i.reason||'预置的合成文件；不会读取磁盘')}</small></div>${badge(i.status,i.status==='失败'?'red':i.status==='已解析'?'green':'')}<span>尝试 ${i.attempts}</span>${i.status==='失败'?button('retry-item','仅重试此项','quiet',`data-batch="${b.id}" data-item="${i.id}"`):''}</div>`).join('')}</div><div class="consent-grid"><div><h3>原件保存选择（模拟）</h3><label><input type="radio" name="location-${b.id}" value="local" ${(ui.locationChoices[b.id]||b.saveLocation)==='local'?'checked':''} ${b.saved?'disabled':''}> 本地 · 由你管理</label><label><input type="radio" name="location-${b.id}" value="cloud" ${(ui.locationChoices[b.id]||b.saveLocation)==='cloud'?'checked':''} ${b.saved?'disabled':''}> 云端 · 仅演示选择</label><p>本地原件需用户自行保管。本原型不创建本地或云端原件副本。</p>${button('save-batch',b.authorization==='granted'?'模拟保存原件':'仅保存，暂不解析','',`data-batch="${b.id}" ${b.saved?'disabled':''}`)}</div><div><h3>本批模型处理授权（模拟）</h3><p>授权状态：<strong>${{pending:'未授权',granted:'本批模拟已授权',denied:'已拒绝解析，保存选择保留'}[b.authorization]}</strong></p><details><summary>查看完整发送范围与用途</summary><ul>${b.manifest.map(m=>`<li>${esc(m)}</li>`).join('')}</ul><p>archive.zip 不支持，不纳入发送清单。用途：提取任务、整理成果、形成候选。本批范围固定，单项重试沿用该范围。</p></details><p>授权仅限本批；下一批重新选择。保存不授予处理许可。</p>${button('authorize-batch','模拟授权并解析本批','primary',`data-batch="${b.id}" ${b.authorization==='granted'?'disabled':''}`)}</div></div></section>`).join('')}<section class="pixel"><h2>项目内成果与版本</h2><p>版本关系为预置合成示例；来源声明不提升成果权威性。</p>${data.documents.length?data.documents.map(d=>`<div class="info-row"><div><strong>${esc(d.filename)}</strong><small>${esc(d.title)} · ${esc(d.source)}</small></div><code>${d.version}</code>${badge(d.status==='available'?'正文可读':'全文受限',d.status==='available'?'green':'amber')}${button('open-document','阅读','quiet',`data-doc="${d.id}" data-version="${d.version}"`)}</div>`).join(''):blank('尚无成果','可以添加合成批次体验保存、拒绝解析和部分失败。')}</section></div>`;
}
function renderReview(){
  const ordinary=data.candidates.filter(c=>c.kind==='ordinary'&&c.state==='pending'),conflict=data.candidates.filter(c=>c.kind==='conflict'&&c.state==='pending');
  const stale=data.candidates.some(c=>c.state==='pending'&&c.base!==data.snapshotVersion);
  $('#page').innerHTML=header('审查候选变更','来源截至 '+esc(data.sourceTime),badge('模拟预览 · 尚未正式生效','amber'))+`<div class="page-content">${stale?`<div class="restricted" role="alert"><strong>预览版本已过期</strong><p>项目示例版本变化，旧选择不能继续。刷新预览后重新选择。</p>${button('refresh-preview','刷新预览','primary')}</div>`:''}<section class="pixel"><div class="section-heading"><h2>普通变更（${ordinary.length}）</h2><label><input id="select-all" type="checkbox" ${ordinary.length&&ordinary.every(c=>ui.selected.has(c.id))?'checked':''} ${!ordinary.length||stale?'disabled':''}> 全选普通项</label></div>${ordinary.length?ordinary.map(c=>candidateCard(c,stale)).join(''):'<p>没有待处理的普通候选。</p>'}<div class="review-actions">${button('confirm-candidates',`确认已选变更（${ui.selected.size}）`,'primary',`${!ui.selected.size||stale?'disabled':''}`)}${button('defer-candidates','暂缓','',`${!ui.selected.size||stale?'disabled':''}`)}${button('reject-candidates','拒绝','danger',`${!ui.selected.size||stale?'disabled':''}`)}<small>冲突不包含在批量确认中</small></div></section><section class="pixel conflict"><h2>约束冲突（${conflict.length}）· 单独处理</h2>${conflict.map(c=>`<article data-candidate="${c.id}"><h3>${esc(c.title)}</h3><div class="comparison"><div><small>当前有效约束</small><p>${esc(c.current)}</p></div><div><small>冲突建议</small><p>${esc(c.proposed)}</p></div></div><p>${esc(c.impact)}</p><p>来源：session-report.md · v2 · 合成 Session 04</p><label><input type="checkbox" id="resolve-${c.id}"> 保留当前约束，排除“略过验证”的建议</label><div class="review-actions">${button('resolve-conflict','单独确认保留当前约束','',`data-id="${c.id}" disabled`)}${button('reject-conflict','单独拒绝建议','danger',`data-id="${c.id}" ${stale?'disabled':''}`)}${button('defer-conflict','单独暂缓','',`data-id="${c.id}" ${stale?'disabled':''}`)}</div></article>`).join('')||'<p>没有待处理的冲突。</p>'}</section>${data.candidates.filter(c=>c.state!=='pending').map(c=>`<div class="info">${esc(c.title)} · 模拟${{confirm:'已确认',reject:'已拒绝',defer:'已暂缓'}[c.state]}；未产生真实项目审批或审计</div>`).join('')}</div>`;
  $('#select-all').onchange=e=>{ui.selected=new Set(e.target.checked?ordinary.map(c=>c.id):[]);renderReview();$('#select-all').focus({preventScroll:true});};
  document.querySelectorAll('[data-candidate-check]').forEach(el=>el.onchange=e=>{e.target.checked?ui.selected.add(el.dataset.candidateCheck):ui.selected.delete(el.dataset.candidateCheck);renderReview();$(`[data-candidate-check="${el.dataset.candidateCheck}"]`).focus({preventScroll:true});});
  conflict.forEach(c=>{const cb=$(`#resolve-${c.id}`);if(cb)cb.onchange=e=>{$(`[data-action="resolve-conflict"][data-id="${c.id}"]`).disabled=!e.target.checked||stale;};});
}
function candidateCard(c,stale){return `<article class="candidate ${ui.selected.has(c.id)?'chosen':''}"><label><input type="checkbox" data-candidate-check="${c.id}" ${ui.selected.has(c.id)?'checked':''} ${stale?'disabled':''}><strong>${esc(c.title)}</strong></label><p>来源：session-report.md · v2 · 合成 Session 04 · 基于快照 v${c.base}</p><div class="comparison"><div><small>当前有效状态</small><p>${esc(c.current)}</p></div><div><small>建议状态</small><p>${esc(c.proposed)}</p></div></div><details><summary>来源依据与影响范围</summary><p>合成报告第 12 行：“验证记录仍需补充。”</p><p>${esc(c.impact)}</p><p>声明只形成候选；不直接证明任务完成。</p></details></article>`;}
function renderHandoff(){
  $('#page').innerHTML=header('接续下一段工作','复制当前有效上下文，带到你使用的外部工具。',button('copy','复制完整交接文本','primary'))+`<div class="page-content">${!data.tasks.length?blank('尚无任务交接','空项目没有可复用成果。可先导入示例资料。'):`<section class="pixel"><div class="section-heading"><h2>检查成果适用性</h2>${badge('待办')}${badge('阻塞','red')}</div><p class="info">先补齐验证记录并完成前置任务验收，再判断成果适用性。</p><p>依据截至 ${esc(data.sourceTime)} · 快照 v${data.snapshotVersion}</p></section><section class="pixel"><div class="section-heading"><h2>交接文本预览</h2>${badge('有效正文','green')}</div><h3>任务目标与下一步</h3><p class="preline">${esc(data.handoff.body)}</p><h3>必要有效约束</h3><ul>${data.handoff.constraints.map(c=>`<li>${esc(c)}</li>`).join('')}</ul><h3>可直接复用</h3><ul>${(data.documents.length?data.handoff.reusable:['暂无可直接复用的成果；请先导入资料并核实适用性。']).map(c=>`<li>${esc(c)}</li>`).join('')}</ul><div class="restricted"><h3>关键未决提醒 · 不作为正式约束</h3><ul>${data.handoff.reminders.map(c=>`<li>${esc(c)}</li>`).join('')}</ul></div><details id="handoff-sources"><summary>详细成果与来源</summary><ul>${(data.documents.length?data.handoff.sources:['当前场景没有可读取来源']).map(c=>`<li>${esc(c)}</li>`).join('')}</ul></details><details><summary>相关历史与失效内容</summary><p>报告 v1 已被后续版本补充；待复核的报告 v2 不进入可直接复用成果。</p></details><p class="info">复制包含必要约束、关键提醒与来源附录；折叠不减少文本。</p><label>完整文本（可键盘选中复制）<textarea id="copy-text" readonly aria-label="完整交接文本">${esc(handoffText(data))}</textarea></label></section>`}</div>`;
  if(!data.tasks.length)$('[data-action="copy"]').disabled=true;
}
async function mutate(intent){try{const result=await adapter.submit(intent);data=result.view;saveReading();shell();toast(result.message);}catch(error){toast(error.message);}}
async function switchProject(project){
  generation++;saveReading();projects.set(ui.project,{adapter,ui:{...ui,graph:{...ui.graph},selected:new Set(ui.selected)}});
  const stored=projects.get(project);if(stored){adapter=stored.adapter;Object.assign(ui,stored.ui);}else{adapter=new SyntheticAdapter('normal',project);Object.assign(ui,{project,scenario:'normal',task:'task-2',filter:'全部',view:'list',mode:'half',doc:'report',version:'v2',listTop:0,graph:{x:0,y:0,z:.8,initialized:false},selected:new Set(),locationChoices:{}});}
  data=await adapter.read();shell();toast('已切换隔离示例项目；阅读状态按项目独立保存');
}
async function changeScenario(scenario){generation++;saveReading();adapter=new SyntheticAdapter(scenario,ui.project);data=await adapter.read();Object.assign(ui,{scenario,task:'task-2',doc:'report',version:'v2',filter:'全部',selected:new Set(),locationChoices:{},listTop:0});shell();toast(`已进入“${scenarios[scenario]}”合成场景`);}
async function reset(){generation++;saveReading();records.records.clear();projects.clear();adapter=new SyntheticAdapter('normal',ui.project);data=await adapter.read();Object.assign(ui,{scenario:'normal',page:'overview',task:'task-2',filter:'全部',view:'list',mode:'half',doc:'report',version:'v2',listTop:0,graph:{x:0,y:0,z:.8,initialized:false},selected:new Set(),locationChoices:{}});shell();toast('示例状态已重置；没有写入真实项目');}
function selectTask(id){saveReading();ui.task=id;const t=data.tasks.find(t=>t.id===id);ui.doc=t?.document;ui.version=t?.version;renderTaskArea();renderDocument();$(`[data-action="select-task"][data-task="${id}"]`)?.focus({preventScroll:true});}
root.onchange=e=>{const field=e.target;if(field.matches('input[type=radio]')&&field.name.startsWith('location-'))ui.locationChoices[field.name.slice(9)]=field.value;};
root.onclick=async e=>{
  const b=e.target.closest('button[data-action]');if(!b||b.disabled)return;const a=b.dataset.action;
  if(a==='navigate'){saveReading();ui.page=b.dataset.page;shell();}
  if(a==='recover')await changeScenario('normal');
  if(a==='reset')await reset();
  if(a==='view'){saveReading();ui.view=b.dataset.view;renderTasks();}
  if(a==='filter'){saveReading();ui.filter=b.dataset.filter;renderTasks();}
  if(a==='select-task')selectTask(b.dataset.task);
  if(a==='dependency'){saveReading();ui.page='tasks';ui.view='graph';ui.task=b.dataset.task;const task=data.tasks.find(t=>t.id===ui.task);ui.doc=task?.document;ui.version=task?.version;const hidden=!filteredTasks(data.tasks,ui.filter).some(t=>t.id===ui.task);if(hidden)ui.filter='全部';shell();centerTask();if(hidden)toast('已切换“全部”筛选以显示依赖目标；列表和图使用同一筛选。');}
  if(a==='mode')setMode(b.dataset.mode);
  if(a==='zoom-in')zoom(.1);if(a==='zoom-out')zoom(-.1);if(a==='center')centerTask();
  if(a==='open-document'){saveReading();ui.doc=b.dataset.doc;ui.version=b.dataset.version;ui.page='tasks';shell();}
  if(a==='retry-document')await mutate({type:'retry-document',id:ui.doc,version:ui.version});
  if(a==='create-batch')await mutate({type:'create-batch'});
  if(a==='save-batch')await mutate({type:'save-batch',batchId:b.dataset.batch,location:$(`input[name="location-${b.dataset.batch}"]:checked`).value});
  if(a==='authorize-batch')await mutate({type:'authorize-batch',batchId:b.dataset.batch});
  if(a==='retry-item')await mutate({type:'retry-item',batchId:b.dataset.batch,id:b.dataset.item});
  if(a==='refresh-preview'){ui.selected.clear();await mutate({type:'refresh-preview'});}
  if(a.endsWith('-candidates')){const action=a.split('-')[0];const ids=[...ui.selected];ui.selected.clear();await mutate({type:'candidate',action,ids});}
  if(a.endsWith('-conflict'))await mutate({type:'candidate',action:a==='resolve-conflict'?'confirm':a==='reject-conflict'?'reject':'defer',ids:[b.dataset.id],separate:true,resolution:a==='resolve-conflict'?'保留当前约束':undefined});
  if(a==='copy'){
    const text=handoffText(data),ticket=generation;
    try{await navigator.clipboard.writeText(text);if(ticket===generation)toast('已复制完整交接文本，包含必要约束与关键提醒（示例）');}
    catch{const field=$('#copy-text');if(field){field.focus();field.select();}toast('剪贴板不可用：完整文本已选中，请按 Ctrl+C / Command+C');}
  }
};
shell();
