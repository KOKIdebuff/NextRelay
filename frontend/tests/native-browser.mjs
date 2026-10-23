/** T08 actual browser -> same-origin API -> SQLite, independently authored synthetic files. */
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {mkdtemp,mkdir,writeFile,readFile,readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createServer} from 'node:net';
import {randomBytes,createHash} from 'node:crypto';

const args=Object.fromEntries(Array.from({length:(process.argv.length-2)/2},(_,i)=>[process.argv[2+i*2],process.argv[3+i*2]]));
if(!args['--python']||!args['--playwright'])throw Error('Supply --python <3.14 executable> --playwright <index.js> [--browser <executable>]');
const pw=await import(pathToFileURL(args['--playwright']).href),{chromium}=pw.default||pw;
const repo=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
const root=await mkdtemp(resolve(tmpdir(),'nextrelay-t08-browser-')),originals=resolve(root,'originals');await mkdir(originals);
const listener=createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
const token=randomBytes(32).toString('base64url'),url=`http://127.0.0.1:${port}`;
const env={...process.env,NEXTRELAY_ENV:'development',NEXTRELAY_AUTH_MODE:'dev-token',NEXTRELAY_DEV_TOKEN:token,NEXTRELAY_DEV_SUBJECT:'dev-t08-browser',NEXTRELAY_DB_PATH:resolve(root,'test.sqlite3'),NEXTRELAY_LOCAL_ROOT:originals,NEXTRELAY_PORT:String(port)};
const init=spawnSync(args['--python'],['-B','-m','nextrelay','init-db'],{env,cwd:repo,encoding:'utf8',windowsHide:true});assert.equal(init.status,0,init.stderr);
let server,browser;const results=[];
const pass=name=>{results.push(name);console.log('PASS '+name);};
async function start(){server=spawn(args['--python'],['-B','-m','nextrelay','serve'],{env,cwd:repo,windowsHide:true,stdio:['ignore','pipe','pipe']});let err='';server.stderr.on('data',x=>err+=x);await new Promise((ok,fail)=>{server.stdout.once('data',ok);server.once('exit',()=>fail(Error(err)));});}
async function stop(){if(server){const owned=server;server=null;const stopped=new Promise(r=>owned.once('exit',r));owned.kill();await stopped;}}
try{
 await start();browser=await chromium.launch({headless:true,...(args['--browser']?{executablePath:args['--browser']}:{})});
 const page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const login=async()=>{await page.locator('#local-token').fill(token);await page.locator('#local-login button').click();await page.locator('.sidebar').waitFor();};
 const click=async selector=>{await page.locator(selector).click();await page.waitForFunction(()=>!document.querySelector('#app[aria-busy="true"]'));};
 const nav=async name=>{await page.locator(`nav [data-page="${name}"]`).click();};
 const api=async resource=>{const res=await fetch(url+resource,{headers:{Authorization:'Bearer '+token}});assert.equal(res.status,200);return res.json();};
 await page.goto(url);await login();await page.locator('#new-project-title').fill('Synthetic estuary field work');await click('[data-action="local-project"]');
 const project=await page.locator('#project').inputValue(),path=r=>`/api/projects/${project}/${r}`;
 const upload=async(name,text)=>{await nav('imports');const file=resolve(root,name);await writeFile(file,text);await page.locator('#local-files').setInputFiles(file);await page.locator('#storage-confirm').check();await click('[data-action="local-upload"]');const batches=(await api(path('imports'))).batches;return batches.at(-1).items[0].id;};
 const extract=async item=>{await click(`[data-action="local-extract"][data-id="${item}"]`);const state=await api(path('native'));return state.runs.find(r=>r.item_id===item).documents[0];};
 const commit=async cid=>{await nav('review');await page.locator('#local-review-basis').fill('人工核对自写合成资料与精确版本，独立决定');await click(`[data-action="local-review"][data-id="${cid}"][data-decision="approve"]`);await click(`[data-action="local-commit"][data-id="${cid}"]`);};
 const text='# Task Inspect estuary pier\nGoal: inspect load record\nCompletion conditions: human verifies measurements\n';
 const item=await upload('field-notes.md',text),d=await extract(item);
 assert.equal((await api(path('formal'))).tasks.length,0);await page.locator(`[data-native-document="${d.id}"] details`).first().locator('summary').click();assert((await page.locator(`[data-native-document="${d.id}"]`).innerText()).includes('input_sha256'));
 await commit(d.proposals[0].candidate_id);let formal=await api(path('formal'));assert.equal(formal.tasks.length,1);const task=formal.tasks[0].task_id;
 assert.equal(formal.acceptances.length,0);assert.equal(formal.baseline,null);pass('实际上传提取、来源定位、独立审查提交，创建任务无自动验收');
 await nav('imports');await click(`[data-action="local-native-rematch"][data-id="${d.id}"]`);await click(`[data-action="local-native-candidates"][data-id="${d.id}"]`);
 let fresh=(await api(path('native'))).runs[0].documents[0];await commit(fresh.proposals.at(-1).candidate_id);
 formal=await api(path('formal'));assert.equal(formal.confirmed_versions[0].version_id,d.version_id);assert.equal(formal.acceptances.length,0);pass('当前任务重新匹配并通过候选确认精确版本，正式结果读回');
 const duplicateItem=await upload('independent-source.md',text),duplicate=await extract(duplicateItem);
 assert.equal(duplicate.version_id,d.version_id);assert.notEqual(duplicate.locator.source_id,d.locator.source_id);assert.equal(duplicate.proposals.length,0);
 const count=(await api(path('native'))).runs.length;await extract(duplicateItem);assert.equal((await api(path('native'))).runs.length,count);pass('同正文独立来源保留，重复处理没有重复成果或正式效果');
 const unknown=await upload('unresolved.md','# Field measurement\nTask: unknown-id\nDepth: 7\n<script>throw 42</script>\n'),pending=await extract(unknown);
 assert.equal(pending.decision.matches.status,'pending');assert.equal(pending.proposals.length,0);
 await page.locator(`[data-native-matches="${pending.id}"]`).fill(JSON.stringify({tasks:[task],sessions:[],attempts:[]}));await page.locator(`[data-native-basis="${pending.id}"]`).fill('人工核对测量属于该任务');await click(`[data-action="local-native-correct"][data-id="${pending.id}"]`);await click(`[data-action="local-native-candidates"][data-id="${pending.id}"]`);
 fresh=(await api(path('native'))).runs.find(r=>r.item_id===unknown).documents[0];assert.equal(fresh.decision.matches.tasks[0],task);assert.equal(fresh.proposals.length,1);assert.equal(errors.length,0);pass('歧义暂存，真实 UI 纠正后保存候选，不执行导入脚本');
 const body='# Navigation specification\n'+Array.from({length:30},(_,i)=>`Constraint ${i}: retain inspected beacon ${i}\n`).join('');
 const initial=await extract(await upload('initial.md',body)),revision=await extract(await upload('revision.md',body.replace('beacon 12','replacement beacon 12')));
 assert.equal(revision.relation.relation,'revision');assert.equal(revision.relation.family_id,initial.relation.family_id);
 await page.locator(`[data-native-version="${revision.id}"]`).evaluate(e=>e.closest('details').open=true);
 await page.locator(`[data-native-version="${revision.id}"]`).fill(JSON.stringify({family_id:null,parent_version_id:null,basis:'人工判断为独立成果'}));await click(`[data-action="local-native-version-correct"][data-id="${revision.id}"]`);
 fresh=(await api(path('native'))).runs.flatMap(r=>r.documents).find(x=>x.id===revision.id);assert.notEqual(fresh.relation.family_id,initial.relation.family_id);assert.equal((await api(path('versions/'+initial.version_id))).version.content,body);pass('自动修订归入及真实 UI 纠正，旧正文不可变，关系不授予权威');
 const lossItem=await upload('response-loss.md','# Reference\nResult: inert record\n');let posts=0;
 await page.route(`**/items/${lossItem}/extract`,async route=>{posts++;await route.fetch();await route.abort('failed');});await click(`[data-action="local-extract"][data-id="${lossItem}"]`);
 assert((await page.locator('.mode-banner').innerText()).includes('结果待确认'));await page.unroute(`**/items/${lossItem}/extract`);await click('[data-action="local-resume"]');assert.equal(posts,1);assert.equal((await api(path('native'))).runs.filter(r=>r.item_id===lossItem).length,1);pass('提取响应丢失后查询持久收据恢复，未重复执行');
 await page.screenshot({path:resolve(root,'native-results.png'),fullPage:true});const before=await api(path('native'));await stop();await start();await page.reload();await login();assert.deepEqual(await api(path('native')),before);assert.equal(errors.length,0);pass('重启与重新认证后提取、来源、纠正及候选记录持久读回');
 const files=[...(await readdir(resolve(repo,'nextrelay'))).filter(x=>x.endsWith('.py')).map(x=>'nextrelay/'+x),'frontend/src/local-adapter.js','frontend/src/local-ui.js','frontend/tests/native-browser.mjs'];
 const hashes=Object.fromEntries(await Promise.all(files.sort().map(async f=>[f,createHash('sha256').update(await readFile(resolve(repo,f))).digest('hex')])));
 await writeFile(resolve(root,'result.json'),JSON.stringify({results,passed:results.length,browser:args['--browser']||'chromium',database:env.NEXTRELAY_DB_PATH,sourceHashes:hashes},null,2));console.log('EVIDENCE '+root);
}finally{if(browser)await browser.close();await stop();}
