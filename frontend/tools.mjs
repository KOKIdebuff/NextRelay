import http from 'node:http';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
const root=dirname(fileURLToPath(import.meta.url));
const runtimeFiles=['index.html','src/app.js','src/style.css','src/workspace-adapter.js','src/synthetic-adapter.js','src/reader-state.js','src/ux.js','src/local-adapter.js','src/local-ui.js'];
const files=[...runtimeFiles,'verification.html','tests/browser.js'];
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8'};
export function createServer(){return http.createServer(async(req,res)=>{
  const path=new URL(req.url,'http://127.0.0.1').pathname;
  const file=path==='/'?'index.html':path.slice(1);
  if(req.method!=='GET'||!files.includes(file)){res.writeHead(404);res.end('Not found');return;}
  try{const body=await readFile(resolve(root,file));res.writeHead(200,{'Content-Type':mime[file.slice(file.lastIndexOf('.'))]||'text/plain','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"});res.end(body);}catch{res.writeHead(500);res.end('Preview unavailable');}
});}
if(process.argv[2]==='build'){
  const out=resolve(root,'dist');await mkdir(out,{recursive:true});
  for(const f of runtimeFiles){await mkdir(dirname(resolve(out,f)),{recursive:true});await writeFile(resolve(out,f),await readFile(resolve(root,f)));}
  console.log(`Built ${runtimeFiles.length} static runtime files to frontend/dist (local API runtime + separate synthetic preview).`);
}else if(process.argv[2]==='serve'){
  const args=process.argv.slice(3);let port=4173;
  if(args.length){if(args.length!==2||args[0]!=='--port'||!/^\d+$/.test(args[1]))throw Error('Usage: npm run dev -- --port 4173');port=Number(args[1]);if(port<1024||port>65535)throw Error('Invalid port');}
  createServer().listen(port,'127.0.0.1',()=>console.log(`T17 synthetic preview: http://127.0.0.1:${port}/ (loopback only)`));
}
