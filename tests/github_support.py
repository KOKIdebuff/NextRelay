"""Actual HTTP fixture for T10. Synthetic Git objects, no credentials."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import hashlib
import json
import threading
from urllib.parse import unquote
from nextrelay.github_http import GitHubConfig

C1='1'*40;C2='2'*40
T1='a'*40;T2='b'*40;SUB='c'*40

def blob(data):return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
def entry(path,data=b'# Synthetic\n',mode='100644',kind='blob',sha=None):
    return dict(path=path,mode=mode,type=kind,sha=sha or blob(data),size=len(data))

class Remote:
    def __init__(self):
        self.requests=[];self.headers=[];self.commit=C1;self.behavior=None;self.lock=threading.Lock()
        self.data={blob(b'# README\nhttps://example.invalid/no-fetch\n'):b'# README\nhttps://example.invalid/no-fetch\n',blob(b'# Doc\nSynthetic measurement\n'):b'# Doc\nSynthetic measurement\n',blob(b'# New\n'):b'# New\n'}
        self.trees={T1:[entry('README.md',next(iter(self.data.values()))),entry('docs',kind='tree',mode='040000',sha=SUB),entry('other.md',b'# New\n')],
            T2:[entry('README.md',b'# New\n')],SUB:[entry('note.md',b'# Doc\nSynthetic measurement\n')]}
        self.refs={'main':C1,'feature/docs':C1,C1:C1,C2:C2}
    def respond(self,path):
        base='/repos/test/repo'
        if path==base:return 200,dict(private=False,visibility='public',full_name='test/repo',default_branch='main')
        if path.startswith(base+'/commits/'):
            ref=unquote(path.removeprefix(base+'/commits/'))
            commit=self.commit if ref=='main' else self.refs.get(ref)
            if not commit:return 404,{}
            return 200,dict(sha=commit,commit=dict(tree=dict(sha=T1 if commit==C1 else T2)))
        if path.startswith(base+'/git/commits/'):
            sha=path.rsplit('/',1)[-1]
            if sha not in (C1,C2):return 404,{}
            return 200,dict(sha=sha,tree=dict(sha=T1 if sha==C1 else T2))
        if path.startswith(base+'/git/trees/'):
            sha=path.rsplit('/',1)[-1]
            return (200,dict(sha=sha,truncated=False,tree=self.trees[sha])) if sha in self.trees else (404,{})
        if path.startswith(base+'/git/blobs/'):
            sha=path.rsplit('/',1)[-1]
            return (200,self.data[sha]) if sha in self.data else (404,{})
        return 404,{}

@contextmanager
def github_server():
    state=Remote()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            with state.lock:state.requests.append(self.path);state.headers.append(dict(self.headers))
            response=state.behavior(self.path) if state.behavior else None
            if response is None:response=state.respond(self.path)
            if response=='drop':self.connection.shutdown(2);return
            status,body,*extra=response
            headers=extra[0] if extra else {}
            if self.headers.get('Accept')=='application/vnd.github.sha' and '/commits/' in self.path and '/git/commits/' not in self.path and status==200 and isinstance(body,dict):
                body=str(body.get('sha','')).encode()
            data=body if isinstance(body,bytes) else json.dumps(body).encode()
            self.send_response(status)
            for k,v in {'Content-Type':'application/octet-stream' if isinstance(body,bytes) else 'application/json','Content-Length':str(len(data)),**headers}.items():self.send_header(k,v)
            self.end_headers()
            try:self.wfile.write(data)
            except OSError:pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
    state.config=GitHubConfig(_test_endpoint=f'http://127.0.0.1:{server.server_port}')
    try:yield state
    finally:server.shutdown();server.server_close();t.join()
