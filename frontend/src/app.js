import { SyntheticAdapter, scenarios, filteredTasks, handoffText } from './synthetic-adapter.js';
import { ReaderRecords, readerKey, snapMode } from './reader-state.js';
import { installUX } from './ux.js';
import { connectLocal, installLocalUI } from './local-ui.js';
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Local SVG pixel assets derived from docs/ui/reference; decorative only.
function icon(name){
 const paper='<path fill="#10265b" d="M6 0h11v2h3v3h2v17h-2v2H3v-2H1V5h2V2h3z"/><path fill="#2366b9" d="M3 6h2v15h15v1H3z"/><path fill="#89c9fa" d="M5 3h11v4h4v13H5z"/><path fill="#fff" d="M7 2h8v6h5v11H7z"/><path fill="#466ab3" d="M15 2h2v3h3v2h-5z"/><path fill="#789cdb" d="M9 10h8v2H9zm0 4h8v2H9z"/><path fill="#e2f5ff" d="M4 6h1v13H4zm2 14h13v1H6z"/>';
 const glyphs={file:paper,navfile:paper.replaceAll('#466ab3','#e8b83f'),greenfile:paper.replaceAll('#10265b','#00623c').replaceAll('#2366b9','#00945a').replaceAll('#89c9fa','#b4f4d1').replaceAll('#466ab3','#008a50').replaceAll('#789cdb','#20b76c'),
 success:'<path fill="#005c34" d="M6 0h12v3h3v3h3v12h-3v3h-3v3H6v-3H3v-3H0V6h3V3h3z"/><path fill="#00a657" d="M7 3h10v2h3v14h-3v2H7v-2H4V5h3z"/><path fill="#56e6a1" d="M7 4h9v2H7zm-2 3h2v8H5z"/><path fill="#fff" d="M5 10h3v3h3v-3h3V7h4v4h-3v3h-3v4H9v-3H6z"/>',
 progress:'<circle cx="12" cy="12" r="9" fill="#fff" stroke="#005bff" stroke-width="4"/>',
 pending:'<circle cx="12" cy="12" r="9" fill="#fff" stroke="#4c6395" stroke-width="4"/>',
 home:'<path fill="#10265b" d="M10 0h4v2h2v2h2v2h2v2h2v3h2v4h-4v9H4v-9H0v-4h2V8h2V6h2V4h2V2h2z"/><path fill="#0877ee" d="M10 3h4v2h2v2h2v2h2v2h1v2h-3V11H6v2H3v-2h1V9h2V7h2V5h2z"/><path fill="#14ca8c" d="M11 4h2v2h2v2h2v2H7V8h2V6h2z"/><path fill="#ffdb76" d="M6 12h12v10h-4v-7H9v7H6z"/><path fill="#ffad40" d="M6 13h3v9H6zm8 7h4v2h-4z"/><path fill="#f3ffff" d="M10 16h2v6h-2z"/>',
 folder:'<path fill="#10265b" d="M3 1h9v2h9v2h2v17H1V5h2z"/><path fill="#ffda63" d="M5 3h6v3h9v3H4V6h1z"/><path fill="#ffbd4d" d="M3 9h17v11H3z"/><path fill="#ffe797" d="M4 10h15v2H6v6H4z"/><path fill="#f29b37" d="M6 18h14v2H4v-2z"/><path fill="#488fd4" d="M1 8h2v13h17v1H1z"/>',
 review:'<path fill="#10265b" d="M7 1h10v2h4v3h2v16H1V6h2V3h4z"/><path fill="#ffd165" d="M4 7h16v13H4z"/><path fill="#fff0ab" d="M5 8h14v3l-7 5-7-5z"/><path fill="#2b71d0" d="M7 3h10v7h-3v3h-4v-3H7z"/><path fill="#ffdc71" d="M10 5h4v3h-1v2h-2V8h-1z"/><path fill="#548fd2" d="M2 8h2v12h16v2H2z"/>',
 handoff:'<path fill="#10265b" d="M5 4h10V0h3v3h3v3h3v3h-3v3h-3v3h-3v-4H5zM19 20H9v4H6v-3H3v-3H0v-3h3v-3h3V9h3v4h10z"/><path fill="#087bdc" d="M6 6h10V4h2v2h2v2h-2v2h-2V9H6zM18 18H8v2H6v-2H4v-2h2v-2h2v1h10z"/><path fill="#88ddff" d="M6 6h10v1H6zm2 9h10v1H8z"/>',
 grass:'<path fill="#006a40" d="M1 19h22v3H1zM5 10h3v10H5zm6-6h3v16h-3zm7 7h3v9h-3z"/><path fill="#00b84d" d="M2 9h3v5h3v5H5v-3H2zM9 4H6V1h3zm5-3h4v3h-4zm0 4h2v3h-2zm4 3h3v3h-3zm2 5h3v3h-3z"/><path fill="#68e99a" d="M6 16h2v3H6zm6-8h2v9h-2zm7 7h2v4h-2z"/>',
 info:'<path fill="#005bff" d="M4 1h16v2h2v18h-2v2H3v-2H1V4h3z"/><path fill="#75caff" d="M4 2h15v1H4zM2 5h1v14H2z"/><path fill="#fff" d="M10 5h4v4h-4zm0 6h4v8h-4z"/>',
 warning:'<path fill="#ec7600" d="M10 1h4v3h2v4h2v4h2v4h2v5H1v-5h2v-4h2V8h2V4h3z"/><path fill="#fff4b2" d="M10 5h4v4h2v4h2v5h2v1H3v-1h2v-5h2V9h2V5z"/><path fill="#ed5b00" d="M10 8h3v6h-3zm0 8h3v3h-3z"/>',
 source:'<path fill="#1134a6" d="M3 3h8v3h10v2h2v13H1V5h2z"/><path fill="#e1f7ff" d="M4 7h6v2h10v9H4z"/><path fill="#005bff" d="M7 10h3v2h4v-2h3v4h-3v2h-4v-2H7z"/>',
 history:'<path fill="#0734bd" d="M7 1h10v2h3v3h3v12h-3v3h-3v2H7v-2H4v-3H1V6h3V3h3z"/><path fill="#effaff" d="M8 5h8v2h3v10h-3v2H8v-2H5V7h3z"/><path fill="#005bff" d="M10 7h3v6h4v3h-6v-2h-1z"/>',
 plus:'<path fill="currentColor" d="M10 2h4v8h8v4h-8v8h-4v-8H2v-4h8z"/>',copy:paper,
 play:'<path fill="currentColor" d="M5 2h3v2h3v2h3v2h3v2h3v4h-3v2h-3v2h-3v2H8v2H5z"/>',
 check:'<path fill="currentColor" d="M3 11h3v3h3v-3h3V8h3V5h4v4h-3v3h-3v3h-3v4H7v-3H4v-2H3z"/>'};
 return `<svg class="icon pixel-icon" aria-hidden="true" viewBox="0 0 24 24">${glyphs[name]||paper}</svg>`;
}
// Wordmark silhouette traced from project-overview.png, bounds (39,91)-(192,118).
function brandMark(){return `<svg class="brand-mark" role="img" aria-label="NextRelay" viewBox="0 0 154 28"><path fill="#0b1044" d="M0 0h5v1h-5zM13 0h5v1h-5zM72 0h14v1h-14zM111 0h5v1h-5zM0 1h6v1h-6zM13 1h5v1h-5zM72 1h15v1h-15zM111 1h5v1h-5zM0 2h6v1h-6zM13 2h5v1h-5zM61 2h4v1h-4zM72 2h16v1h-16zM111 2h5v1h-5zM0 3h7v1h-7zM12 3h6v1h-6zM61 3h4v1h-4zM72 3h17v1h-17zM111 3h5v1h-5zM0 4h8v1h-8zM12 4h6v1h-6zM61 4h4v1h-4zM72 4h6v1h-6zM83 4h6v1h-6zM111 4h5v1h-5zM0 5h9v1h-9zM12 5h6v1h-6zM60 5h5v1h-5zM72 5h5v1h-5zM84 5h5v1h-5zM111 5h5v1h-5zM0 6h9v1h-9zM12 6h6v1h-6zM25 6h3v1h-3zM29 6h2v1h-2zM41 6h4v1h-4zM50 6h4v1h-4zM58 6h10v1h-10zM72 6h5v1h-5zM84 6h5v1h-5zM96 6h8v1h-8zM111 6h5v1h-5zM123 6h9v1h-9zM140 6h4v1h-4zM149 6h2v1h-2zM152 6h1v1h-1zM0 7h10v1h-10zM12 7h6v1h-6zM24 7h10v1h-10zM40 7h5v1h-5zM50 7h4v1h-4zM58 7h10v1h-10zM72 7h5v1h-5zM83 7h6v1h-6zM95 7h10v1h-10zM111 7h5v1h-5zM122 7h11v1h-11zM139 7h5v1h-5zM149 7h5v1h-5zM0 8h11v1h-11zM13 8h5v1h-5zM23 8h12v1h-12zM40 8h5v1h-5zM49 8h5v1h-5zM58 8h10v1h-10zM72 8h5v1h-5zM83 8h6v1h-6zM94 8h12v1h-12zM111 8h5v1h-5zM122 8h12v1h-12zM139 8h5v1h-5zM149 8h5v1h-5zM0 9h11v1h-11zM13 9h5v1h-5zM22 9h14v1h-14zM40 9h7v1h-7zM48 9h7v1h-7zM58 9h10v1h-10zM72 9h6v1h-6zM82 9h7v1h-7zM93 9h14v1h-14zM111 9h5v1h-5zM122 9h13v1h-13zM139 9h5v1h-5zM149 9h5v1h-5zM0 10h18v1h-18zM22 10h6v1h-6zM32 10h5v1h-5zM41 10h13v1h-13zM60 10h6v1h-6zM72 10h16v1h-16zM92 10h6v1h-6zM102 10h5v1h-5zM111 10h5v1h-5zM130 10h5v1h-5zM139 10h5v1h-5zM149 10h5v1h-5zM0 11h5v1h-5zM6 11h12v1h-12zM22 11h5v1h-5zM32 11h5v1h-5zM42 11h11v1h-11zM61 11h4v1h-4zM72 11h15v1h-15zM92 11h6v1h-6zM102 11h5v1h-5zM111 11h5v1h-5zM130 11h5v1h-5zM139 11h5v1h-5zM149 11h5v1h-5zM0 12h5v1h-5zM7 12h11v1h-11zM22 12h6v1h-6zM32 12h5v1h-5zM43 12h9v1h-9zM60 12h5v1h-5zM72 12h14v1h-14zM92 12h6v1h-6zM102 12h5v1h-5zM111 12h5v1h-5zM129 12h6v1h-6zM139 12h5v1h-5zM149 12h5v1h-5zM0 13h5v1h-5zM7 13h11v1h-11zM22 13h15v1h-15zM44 13h7v1h-7zM60 13h5v1h-5zM72 13h13v1h-13zM92 13h15v1h-15zM111 13h5v1h-5zM123 13h12v1h-12zM139 13h5v1h-5zM149 13h5v1h-5zM0 14h5v1h-5zM8 14h10v1h-10zM22 14h15v1h-15zM44 14h7v1h-7zM61 14h4v1h-4zM72 14h5v1h-5zM79 14h6v1h-6zM92 14h15v1h-15zM111 14h5v1h-5zM122 14h13v1h-13zM139 14h5v1h-5zM149 14h5v1h-5zM0 15h5v1h-5zM9 15h9v1h-9zM22 15h15v1h-15zM43 15h9v1h-9zM61 15h4v1h-4zM72 15h5v1h-5zM80 15h6v1h-6zM92 15h15v1h-15zM111 15h5v1h-5zM121 15h14v1h-14zM139 15h6v1h-6zM149 15h5v1h-5zM0 16h5v1h-5zM9 16h9v1h-9zM22 16h6v1h-6zM42 16h11v1h-11zM61 16h5v1h-5zM72 16h5v1h-5zM80 16h7v1h-7zM92 16h6v1h-6zM111 16h5v1h-5zM120 16h6v1h-6zM130 16h5v1h-5zM140 16h14v1h-14zM0 17h5v1h-5zM10 17h8v1h-8zM22 17h6v1h-6zM42 17h11v1h-11zM60 17h8v1h-8zM72 17h5v1h-5zM81 17h6v1h-6zM92 17h6v1h-6zM111 17h6v1h-6zM121 17h4v1h-4zM130 17h5v1h-5zM141 17h13v1h-13zM0 18h5v1h-5zM11 18h7v1h-7zM22 18h13v1h-13zM40 18h7v1h-7zM48 18h7v1h-7zM60 18h8v1h-8zM72 18h5v1h-5zM82 18h6v1h-6zM92 18h13v1h-13zM111 18h7v1h-7zM120 18h15v1h-15zM142 18h12v1h-12zM0 19h5v1h-5zM11 19h7v1h-7zM23 19h12v1h-12zM40 19h6v1h-6zM49 19h5v1h-5zM61 19h7v1h-7zM72 19h5v1h-5zM82 19h7v1h-7zM93 19h13v1h-13zM112 19h6v1h-6zM121 19h14v1h-14zM142 19h12v1h-12zM0 20h5v1h-5zM12 20h6v1h-6zM24 20h11v1h-11zM40 20h5v1h-5zM50 20h4v1h-4zM62 20h6v1h-6zM72 20h5v1h-5zM83 20h7v1h-7zM94 20h12v1h-12zM113 20h5v1h-5zM122 20h13v1h-13zM148 20h6v1h-6zM0 21h5v1h-5zM13 21h5v1h-5zM25 21h10v1h-10zM40 21h5v1h-5zM50 21h4v1h-4zM63 21h5v1h-5zM73 21h4v1h-4zM83 21h6v1h-6zM95 21h11v1h-11zM114 21h4v1h-4zM123 21h12v1h-12zM149 21h5v1h-5zM149 22h5v1h-5zM141 23h13v1h-13zM140 24h13v1h-13zM140 25h12v1h-12zM140 26h11v1h-11zM140 27h10v1h-10z"/></svg>`;}
const navs=[['overview','项目概览','home'],['tasks','任务','navfile'],['imports','资料与成果','folder'],['review','待确认','review'],['handoff','上下文交接','handoff']];
const names=Object.fromEntries(navs.map(n=>[n[0],n[1]]));
const records=new ReaderRecords();
const ui={page:'overview',project:'demo',scenario:'normal',task:null,filter:'全部',view:'list',mode:'half',doc:null,version:null,listTop:0,graph:{x:0,y:0,z:.8,initialized:false},selected:new Set(),locationChoices:{}};
const projects=new Map();
const root=$('#app');
const mode=new URLSearchParams(location.search).get('mode')||document.querySelector('meta[name="nextrelay-mode"]')?.content||'synthetic';
const connected=mode==='local'?await connectLocal(root):null;
let adapter=connected?.adapter||new SyntheticAdapter(),data=connected?.data||await adapter.read(),generation=0,readerObserver,noticeTimer,localUX;
if(connected)ui.project=data.projectId;
function toast(message){clearTimeout(noticeTimer);$('#notice').textContent=message;noticeTimer=setTimeout(()=>$('#notice').textContent='',6500);}
function badge(text,kind=''){const tone=kind||({'已验收':'green','已确认':'green','适用':'green','进行中':'blue','待验收':'amber','待复核':'amber','阻塞':'red'}[text]||'');return `<span class="badge ${tone}">${esc(text)}</span>`;}
function taskFilename(t){return data.documents.find(d=>d.id===t.document&&d.version===t.version)?.filename||`${t.document} · 引用未载入`;}
function life(t){return badge(t.lifecycle,{'已验收':'green','待验收':'amber','进行中':'blue'}[t.lifecycle]);}
function reminder(t){return `${t.blocking.map(r=>badge(`阻塞 · ${r}`,'red')).join('')}${t.review.map(r=>badge(`待复核 · ${r}`,'amber')).join('')}`||'<span class="muted">无独立提醒</span>';}
function button(action,text,cls='',attrs=''){const glyph=({copy:'copy','authorize-batch':'play','confirm-candidates':'check','create-batch':'plus'})[action]||(action==='navigate'&&attrs.includes('imports')&&cls.includes('primary')?'plus':null);return `<button class="${cls}" data-action="${action}" ${attrs}>${glyph?icon(glyph):''}${text}</button>`;}
function blank(title,text,action='imports',label='前往资料与成果'){return `<div class="empty pixel"><h2>${esc(title)}</h2><p>${esc(text)}</p>${button('navigate',label,'primary',`data-page="${action}"`)}</div>`;}
function saveReading(){const el=$('#reader-scroll');if(el&&el.getClientRects().length&&el.dataset.key)records.capture(el.dataset.key,el);if($('#task-list'))ui.listTop=$('#task-list').scrollTop;}
function shell(){
  root.innerHTML=`<aside class="sidebar pixel"><div class="brand">${brandMark()}<small>续程</small></div><label class="project-label">当前示例项目<select id="project" aria-label="选择示例项目"><option value="demo">NextRelay MVP · 示例</option><option value="lab">续程实验室 · 示例</option></select></label><nav aria-label="主导航">${navs.map(([id,label,i])=>`<button data-page="${id}" data-action="navigate" aria-current="${ui.page===id?'page':'false'}">${icon(i)}<span>${label}</span>${id==='review'?`<span class="nav-count">${data.candidates.filter(c=>c.state==='pending').length}</span>`:''}</button>`).join('')}</nav><div class="sidebar-foot">${icon('grass')}<strong>示例数据 / 模拟操作</strong><p>资料依据截至<br>${esc(data.sourceTime)}</p><p>业务后端未接入<br>不会读取或发送真实资料</p><label>演示场景<select id="scenario" aria-label="演示场景">${Object.entries(scenarios).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label>${button('reset','重置示例状态','quiet')}</div></aside><main id="main"><div class="mode-banner"><span>合成数据沙盒</span><span>所有保存、解析、审批均为模拟</span><code>快照 v${data.snapshotVersion}</code></div><div id="page"></div></main>`;
  $('#project').value=ui.project;$('#scenario').value=ui.scenario;
  $('#project').onchange=e=>switchProject(e.target.value);
  $('#scenario').onchange=e=>changeScenario(e.target.value);
  renderPage();localUX?.decorate();
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
let renderOverview,renderTasks,renderTaskArea,renderImports,renderReview,renderHandoff,mutate;
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
  const detailRows=[['source','原始来源',d.source+(data.mode==='local'?'；来源归属以服务端记录为准；不推断 Session 或 Attempt':'；原件与会话标识均为合成，未读取本地文件')],['evidence','证据与缺口',d.evidence.join('；')||'无证据记录；格式解析不等于验收'],['versions','版本历史',d.versions.join('；')]];
  scroll.innerHTML=`<article><div data-anchor="intro">
    <div class="document-controls"><label>文档与版本<select id="document-picker" aria-label="选择文档与版本">${options}</select></label>
    ${button('mode',ui.mode==='full'?'收回半屏':'展开阅读','primary',`data-mode="${ui.mode==='full'?'half':'full'}" id="expand-reader"`)}</div>
    <p class="eyebrow">${esc(d.filename)} / ${esc(d.version)} / 合成资料</p><h2>${icon('file')}${esc(d.title)}</h2>
    <p class="info">${icon('info')}${data.mode==='local'?'服务端精确版本正文；格式解析不代表任务已验收。':'仅为示例文档；已解析不代表任务已验收。'}</p><h3>摘要</h3><p>${esc(d.summary)}</p></div>${body}
    ${detailRows.map(([id,title,text])=>`<details data-detail="${id}" data-anchor="detail-${id}"><summary>${icon(id==='source'?'source':id==='versions'?'history':'file')}${title}</summary><p>${esc(text)}</p></details>`).join('')}</article>`;
  $('#document-picker').value=`${d.id}|${d.version}`;wireDocumentPicker();restoreReading();
}
function wireDocumentPicker(){const picker=$('#document-picker');if(picker)picker.onchange=e=>{saveReading();const [id,version]=e.target.value.split('|');ui.doc=id;ui.version=version;renderDocument();};}
function restoreReading(){const scroller=$('#reader-scroll');if(scroller?.dataset.key)requestAnimationFrame(()=>{if(scroller.isConnected&&scroller.getClientRects().length)records.restore(scroller.dataset.key,scroller);});}
function applyMode(){
  const work=$('.task-work');if(!work)return;const scroller=$('#reader-scroll');scroller.dataset.restoring='true';work.dataset.readerMode=ui.mode;work.style.removeProperty('--drag-height');
  $('#reader-handle').setAttribute('aria-valuenow',String(['collapsed','half','full'].indexOf(ui.mode)));
  $('#reader-handle').setAttribute('aria-valuetext',{collapsed:'收起',half:'半屏',full:'全屏'}[ui.mode]);
  document.querySelectorAll('[data-action="mode"]').forEach(b=>{b.classList.toggle('active',b.dataset.mode===ui.mode);b.setAttribute('aria-pressed',String(b.dataset.mode===ui.mode));});
  const expand=$('#expand-reader');if(expand){expand.textContent=ui.mode==='full'?'收回半屏':'展开阅读';expand.dataset.mode=ui.mode==='full'?'half':'full';}if(scroller.dataset.key&&scroller.getClientRects().length)records.restore(scroller.dataset.key,scroller);restoreReading();requestAnimationFrame(()=>requestAnimationFrame(()=>{if(scroller.isConnected)scroller.dataset.restoring='false';}));
}
function setMode(mode,preserve=false){if(!preserve)saveReading();ui.mode=mode;if(ui.page==='tasks')ui.taskMode=mode;applyMode();}
function wireHandle(){
  const h=$('#reader-handle'),work=$('.task-work'),panel=$('.reader'),scroller=$('#reader-scroll');let drag;
  const finish=mode=>{
    if(!drag)return;const id=drag.pointerId;drag=null;
    delete work.dataset.readerDragging;h.classList.remove('dragging');
    if(h.hasPointerCapture(id))h.releasePointerCapture(id);
    if(mode)setMode(mode,true);else applyMode();
  };
  h.onpointerdown=e=>{
    if(e.button!==0||!e.isPrimary||drag)return;
    saveReading();scroller.dataset.restoring='true';
    const style=getComputedStyle(work),total=work.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom);
    const minimum=h.getBoundingClientRect().height+$('.reader-bar').getBoundingClientRect().height+panel.offsetHeight-panel.clientHeight;
    drag={pointerId:e.pointerId,y:e.clientY,height:panel.getBoundingClientRect().height,total,minimum:Math.min(minimum,total),moved:false};
    h.setPointerCapture(e.pointerId);e.preventDefault();
  };
  h.onpointermove=e=>{
    if(!drag||e.pointerId!==drag.pointerId)return;
    const delta=drag.y-e.clientY;if(!drag.moved&&Math.abs(delta)<4)return;
    const first=!drag.moved;drag.moved=true;
    work.style.setProperty('--drag-height',`${Math.max(drag.minimum,Math.min(drag.total,drag.height+delta))}px`);
    // Preview both regions so the reader stays anchored to the bottom, even from full/collapsed.
    work.dataset.readerDragging='true';h.classList.add('dragging');
    if(first&&scroller.dataset.key)records.restore(scroller.dataset.key,scroller);
  };
  h.onpointerup=e=>{if(drag&&e.pointerId===drag.pointerId)finish(drag.moved?snapMode(drag.height+drag.y-e.clientY,drag.total):null);};
  h.onpointercancel=e=>{if(drag&&e.pointerId===drag.pointerId)finish();};
  h.onlostpointercapture=e=>{if(drag&&e.pointerId===drag.pointerId)finish();};
  h.onkeydown=e=>{if(e.key==='Escape'&&drag){e.preventDefault();finish();return;}const modes=['collapsed','half','full'],i=modes.indexOf(ui.mode);let mode;if(e.key==='ArrowUp')mode=modes[Math.min(2,i+1)];if(e.key==='ArrowDown')mode=modes[Math.max(0,i-1)];if(e.key==='Home')mode='collapsed';if(e.key==='End')mode='full';if(mode){e.preventDefault();if(drag)finish();setMode(mode);}};
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
async function switchProject(project){
  generation++;const ticket=generation;saveReading();projects.set(ui.project,{adapter,ui:{...ui,graph:{...ui.graph},selected:new Set(ui.selected)}});
  const stored=projects.get(project);if(stored){adapter=stored.adapter;Object.assign(ui,stored.ui);}else{adapter=new SyntheticAdapter('normal',project);Object.assign(ui,{project,scenario:'normal',task:null,filter:'全部',view:'list',mode:'half',doc:null,version:null,listTop:0,graph:{x:0,y:0,z:.8,initialized:false},selected:new Set(),locationChoices:{}});}
  const view=await adapter.read();if(ticket!==generation)return false;data=view;shell();toast('已切换隔离示例项目；阅读状态按项目独立保存');return true;
}
async function changeScenario(scenario){generation++;saveReading();adapter=new SyntheticAdapter(scenario,ui.project);data=await adapter.read();Object.assign(ui,{scenario,task:'task-2',doc:'report',version:'v2',filter:'全部',selected:new Set(),locationChoices:{},listTop:0});shell();toast(`已进入“${scenarios[scenario]}”合成场景`);}
async function reset(){generation++;saveReading();records.records.clear();projects.clear();adapter=new SyntheticAdapter('normal',ui.project);data=await adapter.read();Object.assign(ui,{scenario:'normal',page:'overview',task:'task-2',filter:'全部',view:'list',mode:'half',doc:'report',version:'v2',listTop:0,graph:{x:0,y:0,z:.8,initialized:false},selected:new Set(),locationChoices:{}});shell();toast('示例状态已重置；没有写入真实项目');}
root.onchange=e=>{const field=e.target;if(field.matches('input[type=radio]')&&field.name.startsWith('location-'))ui.locationChoices[field.name.slice(9)]=field.value;};
root.onclick=async e=>{
  const b=e.target.closest('button[data-action]');if(!b||b.disabled)return;const a=b.dataset.action;
  if(a==='recover')await changeScenario('normal');
  if(a==='reset')await reset();
  if(a==='mode'){setMode(b.dataset.mode);ui.taskMode=ui.mode;}
  if(a==='zoom-in')zoom(.1);if(a==='zoom-out')zoom(-.1);if(a==='center')centerTask();
  if(a==='retry-document')await mutate({type:'retry-document',id:ui.doc,version:ui.version});
};
const ux=installUX({ui,root,$,esc,icon,badge,button,blank,life,reminder,records,readerKey,saveReading,restoreReading,shell,header,renderDocument,applyMode,wireHandle,wireGraph,centerTask,transformGraph,toast,getData:()=>data,getAdapter:()=>adapter,getGeneration:()=>generation,setData:value=>data=value,renderTasks,renderTaskArea,mutate,switchProject,changeScenario,reset});
renderOverview=ux.renderOverview;renderTasks=ux.renderTasks;renderTaskArea=ux.renderTaskArea;renderDocument=ux.renderDocument;renderImports=ux.renderImports;renderReview=ux.renderReview;renderHandoff=ux.renderHandoff;mutate=ux.mutate;switchProject=ux.switchProject;changeScenario=ux.changeScenario;reset=ux.reset;root.onclick=ux.onclick;
if(mode==='local'){
  localUX=installLocalUI({ui,root,$,esc,button,header,shell,toast,getData:()=>data,getAdapter:()=>adapter,setData:v=>data=v},ux);
  ({renderOverview,renderTasks,renderTaskArea,renderImports,renderReview,renderHandoff}=localUX);root.onclick=localUX.onclick;
}
shell();
