/** T10 actual browser, local API, SQLite, and captured real controlled HTTP. */
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {mkdtemp,mkdir,writeFile,readFile,readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createServer} from 'node:net';
import {randomBytes,createHash} from 'node:crypto';
const args=Object.fromEntries(Array.from({length:(process.argv.length-2)/2},(_,i)=>[process.argv[2+i*2],process.argv[3+i*2]]));
if(!args['--python']||!args['--playwright'])throw Error('--python 3.14 --playwright path [--browser executable] required');
const pw=await import(pathToFileURL(args['--playwright']).href),{chromium}=pw.default||pw;
const repo=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
const root=await mkdtemp(resolve(tmpdir(),'nextrelay-t10-browser-')),originals=resolve(root,'originals');await mkdir(originals);
const capture=resolve(root,'capture.json'),mode=resolve(root,'mode.txt');
const listener=createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
const token=randomBytes(32).toString('base64url'),url=`http://127.0.0.1:${port}`;
const env={...process.env,NEXTRELAY_ENV:'development',NEXTRELAY_AUTH_MODE:'dev-token',NEXTRELAY_DEV_TOKEN:token,NEXTRELAY_DEV_SUBJECT:'dev-t10-browser',NEXTRELAY_DB_PATH:resolve(root,'test.sqlite3'),NEXTRELAY_LOCAL_ROOT:originals,NEXTRELAY_PORT:String(port),NEXTRELAY_MODEL_PROVIDER:'disabled',NEXTRELAY_MODEL_API_KEY:'',NEXTRELAY_MODEL_NAME:''};
const init=spawnSync(args['--python'],['-B','-m','nextrelay','init-db'],{env,cwd:repo,encoding:'utf8',windowsHide:true});assert.equal(init.status,0,init.stderr);
let server,browser;const results=[];const pass=x=>{results.push(x);console.log('PASS '+x);};
const captures=async()=>{try{return JSON.parse(await readFile(capture,'utf8'));}catch(e){if(e.code==='ENOENT')return [];throw e;}};
const bodies=async()=>(await captures()).filter(x=>x.path.includes('/git/blobs/'));
async function start(){server=spawn(args['--python'],['-B','examples/t10_loopback.py','--capture',capture,'--mode',mode],{env,cwd:repo,windowsHide:true,stdio:['ignore','pipe','pipe']});let err='';server.stderr.on('data',x=>err+=x);await new Promise((ok,fail)=>{server.stdout.once('data',ok);server.once('exit',()=>fail(Error(err)));});}
async function stop(){if(server){const owned=server;server=null;const closed=new Promise(r=>owned.once('exit',r));owned.kill();await closed;}}
try{
 await start();browser=await chromium.launch({headless:true,...(args['--browser']?{executablePath:args['--browser']}:{})});
 const page=await browser.newPage({viewport:{width:1366,height:1000}}),errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith(url))external.push(r.url());});
 const login=async()=>{await page.locator('#local-token').fill(token);await page.locator('#local-login button').click();await page.locator('.sidebar').waitFor();};
 const click=async selector=>{await page.locator(selector).click();await page.waitForFunction(()=>!document.querySelector('#app[aria-busy="true"]'));};
 const nav=async()=>page.locator('nav [data-page="imports"]').click();
 const api=async (path,body,key=randomBytes(16).toString('hex'),auth=true)=>{const res=await fetch(url+path,{method:body===undefined?'GET':'POST',headers:{...(auth?{Authorization:'Bearer '+token}:{}),...(body===undefined?{}:{'Content-Type':'application/json','Idempotency-Key':key})},body:body===undefined?undefined:JSON.stringify(body)});return {status:res.status,body:await res.json()};};
 await page.goto(url);await login();await page.locator('#new-project-title').fill('Synthetic source basin');await click('[data-action="local-project"]');const project=await page.locator('#project').inputValue(),path=r=>`/api/projects/${project}/${r}`;
 const list=async()=>(await api(path('github'))).body.snapshots;
 const prepare=async input=>{await nav();await page.locator('#github-url').fill(input);await page.locator('#github-storage').check();await click('[data-action="local-github-prepare"]');return (await list()).at(-1);};
 const op=async(b,action)=>click(`[data-action="local-github"][data-id="${b.id}"][data-op="${action}"]`);
 let b=await prepare('https://github.com/test/repo');assert.equal(b.git_commit,'1'.repeat(40));assert.equal((await bodies()).length,0);const metadata=await captures();assert(metadata.some(r=>r.path.endsWith('/git/commits/'+'1'.repeat(40))));for(const r of metadata.filter(r=>r.path.includes('/commits/')&&!r.path.includes('/git/commits/')))assert.equal(r.headers.Accept,'application/vnd.github.sha');assert.deepEqual(b.scopes[0].paths,['README.md']);pass('仓库URL预览固定commit及实际路径，元数据读取没有正文请求');
 await op(b,'read');b=(await list()).at(-1);assert.equal(b.state,'read');assert.equal((await bodies()).length,1);assert.equal((await api(path('model-batches'))).body.batches.length,0);assert.equal((await api(path('formal'))).body.tasks.length,0);pass('真实API保存及解析公开内容，无模型发送／正式任务');
 await page.locator(`[data-github-paths="${b.id}"]`).fill('docs/note.md');await op(b,'expand');let current=(await list()).at(-1),scope=current.scopes.at(-1);await op(b,'read');assert.equal((await bodies()).length,1);
 const forged=await api(path(`github/${b.id}/confirm`),{scope_id:scope.id,fingerprint:'forged'});assert.equal(forged.status,409);
 await op(b,'confirm');await op(b,'read');assert.equal((await bodies()).length,2);current=(await list()).at(-1);assert.equal(current.entries.find(e=>e.path==='other.md').read_status,'not-selected');pass('扩读预览零额外读取，伪造确认拒绝，明确确认后仅读新增路径');
 let n=(await captures()).length;const reference=await prepare('https://example.invalid/no-read');assert.equal(reference.state,'reference-only');assert.equal((await captures()).length,n);assert((await page.locator(`[data-github="${reference.id}"]`).innerText()).includes('unsupported_url'));pass('普通URL仅存引用并真实显示未读取，零网络抓取');
 await writeFile(mode,'fail');let partial=await prepare('https://github.com/test/repo/tree/main/docs');await op(partial,'read');partial=(await list()).at(-1);assert.equal(partial.state,'partial');assert.equal(partial.entries.filter(e=>e.read_status==='read').length,1);assert((await page.locator(`[data-github="${partial.id}"]`).innerText()).includes('partial'));
 n=(await bodies()).length;await writeFile(mode,'new');await op(partial,'retry');current=(await list()).at(-1);assert.equal(current.git_commit,'1'.repeat(40));assert.equal(current.state,'read');assert.equal((await bodies()).length,n+1);
 await op(partial,'update');let updated=(await list()).at(-1);assert.equal(updated.git_commit,'2'.repeat(40));assert.equal(updated.parent_id,partial.id);pass('单项500保留成功项；原commit只重试失败文件，主动更新新快照保留旧链');
 await page.screenshot({path:resolve(root,'github-source-manifest.png'),fullPage:true});
 const item=current.entries.find(e=>e.path==='docs/note.md').item_id;await click(`[data-action="local-extract"][data-id="${item}"]`);assert((await api(path('native'))).body.runs.length>0);assert.equal((await api(path('formal'))).body.tasks.length,0);pass('远端内容接入T08真实原生提取与来源版本，未自动提交');
 assert.equal((await api(path('github'),undefined,undefined,false)).status,401);const other=(await api('/api/projects',{title:'Other synthetic'})).body;
 assert.equal((await api(`/api/projects/${other.id}/github/${b.id}`)).status,404);pass('真实API认证及跨项目对象隔离');
 await stop();await start();await page.reload();await login();await nav();assert.equal((await list()).length,4);assert.equal((await api(path('github/'+b.id))).body.git_commit,'1'.repeat(40));assert.equal((await bodies()).length,n+1);assert.equal(errors.length,0);assert.deepEqual(external,[]);pass('重启后来源／快照／成功项持久保留；浏览器无外部资源加载或脚本错误');
 const files=[...(await readdir(resolve(repo,'nextrelay'))).filter(x=>x.endsWith('.py')).map(x=>'nextrelay/'+x),'frontend/src/local-adapter.js','frontend/src/local-ui.js','frontend/src/github-ui.js','frontend/src/style.css','frontend/tests/github-browser.mjs'];
 const hashes=Object.fromEntries(await Promise.all(files.sort().map(async f=>[f,createHash('sha256').update(await readFile(resolve(repo,f))).digest('hex')])));
 await writeFile(resolve(root,'result.json'),JSON.stringify({results,passed:results.length,sourceHashes:hashes,database:env.NEXTRELAY_DB_PATH},null,2));console.log('EVIDENCE '+root);
}finally{if(browser)await browser.close();await stop();}
