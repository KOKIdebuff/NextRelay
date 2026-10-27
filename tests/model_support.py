"""Managed, credential-free loopback supplier; receives actual HTTP bytes."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from nextrelay.model_provider import ModelConfig
from nextrelay.model_protocol import PROTOCOL


def proposal(payload,title='Inspect synthetic tidal gate'):
    entries=json.loads(payload['input'][1]['content'])['entries']
    e=next(e for e in entries if e['kind']=='format')
    start=0;end=min(80,len(e['text']))
    value=dict(protocol=PROTOCOL,candidates=[dict(operation='task.create',task_id=None,version_id=None,
        title=title,goal='Record the proposed inspection',completion_conditions='Human checks source measurements',
        rationale='Interpretation of the supplied synthetic record; no claim was independently verified',
        citations=[dict(entry_id=e['id'],sha256=e['sha256'],start=start,end=end,quote=e['text'][start:end])],risks=[],uncertainties=[])])
    if payload['text']['format']['name']=='nextrelay_candidates_v2':
        c=value['candidates'][0]
        value=dict(protocol='nextrelay.model/2',candidates=[dict(operation=c['operation'],target_id=c['task_id'],target_version_id=c['version_id'],payload={k:c[k] for k in ('title','goal','completion_conditions')},**{k:c[k] for k in ('rationale','citations','risks','uncertainties')})])
    return value


class Supplier:
    def __init__(self):self.requests=[];self.behavior=None;self.lock=threading.Lock()
    def respond(self,payload,index):
        return 200,dict(id='resp_synthetic_'+str(index),model=payload['model'],status='completed',
            output=[dict(type='message',role='assistant',content=[dict(type='output_text',text=json.dumps(proposal(payload)))])],
            usage=dict(input_tokens=120,output_tokens=80,total_tokens=200))


@contextmanager
def supplier():
    state=Supplier()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            data=self.rfile.read(int(self.headers.get('Content-Length','0')))
            with state.lock:
                state.requests.append(dict(path=self.path,body=data,headers=dict(self.headers)))
                index=len(state.requests)
            payload=json.loads(data)
            response=state.behavior(payload,index) if state.behavior else state.respond(payload,index)
            if response is None:
                self.connection.shutdown(2);self.connection.close();return
            status,body=response
            data=body if isinstance(body,bytes) else json.dumps(body).encode()
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers()
            try:self.wfile.write(data)
            except OSError:pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    state.config=ModelConfig(provider='test-loopback',model='synthetic-inspector',endpoint=f'http://127.0.0.1:{server.server_port}/v1/responses',_loopback_test=True)
    try:yield state
    finally:server.shutdown();server.server_close();thread.join()
