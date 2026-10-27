"""Synthetic HTTP walkthrough, always a new temporary DB; no external requests.

Run from the repository: python -B -m examples.t19_synthetic
The server is an owned child process. It is restarted before the final API read.
"""
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

from nextrelay.db import initialize


def main():
    with TemporaryDirectory(prefix='nextrelay-t19-example-') as folder:
        root=Path(folder);database=root/'synthetic.sqlite3';originals=root/'originals';originals.mkdir()
        initialize(database)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        token=secrets.token_urlsafe(32)
        env=dict(os.environ,NEXTRELAY_DB_PATH=str(database),NEXTRELAY_LOCAL_ROOT=str(originals),
                 NEXTRELAY_ENV='development',NEXTRELAY_AUTH_MODE='dev-token',NEXTRELAY_DEV_TOKEN=token,
                 NEXTRELAY_DEV_SUBJECT='dev-t19-example',NEXTRELAY_HOST='127.0.0.1',NEXTRELAY_PORT=str(port),
                 NEXTRELAY_MODEL_PROVIDER='disabled')
        process=None

        def call(path,body=None,key=None):
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            try:
                headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Idempotency-Key':key or str(uuid4())}
                connection.request('GET' if body is None else 'POST',path,
                    body=None if body is None else json.dumps(body),headers=headers)
                response=connection.getresponse();value=json.loads(response.read())
                if response.status!=200:raise RuntimeError((response.status,value))
                return value
            finally:connection.close()

        def start():
            nonlocal process
            process=subprocess.Popen([sys.executable,'-B','-m','nextrelay','serve'],env=env,
                cwd=Path(__file__).resolve().parents[1],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for _ in range(100):
                if process.poll() is not None:raise RuntimeError('Synthetic server failed')
                try:call('/health/live');return
                except (ConnectionError,OSError):time.sleep(.05)
            raise RuntimeError('Synthetic server startup timeout')

        def stop():
            nonlocal process
            if process is not None:
                process.terminate();process.wait(timeout=10);process=None

        try:
            start()
            project=call('/api/projects',dict(title='SYNTHETIC T19 example'))['id']
            prefix='/api/projects/'+project+'/'
            def api(tail,body=None,key=None):return call(prefix+tail,body,key)
            def commit(*candidates):
                selected=[]
                for c in candidates:
                    explicit=c['risk']!='ordinary'
                    request=dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint'])],
                        decision='approve',mode='explicit' if explicit else 'ordinary',
                        basis='Synthetic demonstration, not a real business approval',input_origin='synthetic-test')
                    if explicit:request['authorization']=c['authorization']
                    review=api('reviews',request)['reviews'][0]
                    selected.append(dict(candidate_id=c['candidate_id'],review_id=review['id']))
                key=str(uuid4())
                return api('commits',dict(request_key=key,base_revision=candidates[0]['spec']['base_revision'],selection=selected),key)
            def candidate(op,target,payload):
                request=dict(operation=op,base_revision=api('formal')['project']['revision'],payload=payload)
                if target is not None:request['target_id']=target
                return api('candidates',request)
            def effect(op,target,payload):
                c=candidate(op,target,payload);commit(c);return c
            a=api('sessions',dict(title='Synthetic implementation',namespace='synthetic',external_id='A'))['id']
            b=api('sessions',dict(title='Synthetic review',namespace='synthetic',external_id='B'))['id']
            task=effect('task.create',None,dict(title='Synthetic shared task'))['target_id']
            duty=effect('thread.duty.set',a,dict(main='Implementation',auxiliary=['Tests'],basis='Synthetic direct assignment'))
            effect('thread.duty.suggest',b,dict(main='Review',basis='Explicit synthetic suggestion'))
            suggestion=api('threads/'+b)['current']['suggestions'][0]['id']
            effect('thread.duty.confirm',b,dict(suggestion_id=suggestion,basis='Synthetic confirmation'))
            commit(*[candidate('task.participation.set',task,dict(thread_id=t,active=True,basis='Synthetic shared work')) for t in (a,b)])
            effect('task.lead.set',task,dict(thread_id=a,basis='Synthetic optional lead'))
            commit(candidate('task.participation.set',task,dict(thread_id=a,active=False,basis='Synthetic exit')),
                   candidate('task.lead.set',task,dict(thread_id=b,basis='Explicit same-transaction reassignment')))
            effect('thread.succession.set',a,dict(successor_id=b,active=True,basis='Synthetic successor, no task transfer'))
            change=next(r['id'] for r in api('history')['applied_changes'] if r['candidate_id']==duty['candidate_id'])
            preview=api('reversal-previews',dict(change_id=change))
            effect('change.revoke',change,dict(preview_id=preview['id']))
            before=api('threads');history=api('history')
            stop();start()
            assert api('threads')==before and api('history')==history
            assert api('sessions')['sessions']==before['threads']
            print(json.dumps(dict(data='synthetic-only',schema=11,revision=before['revision'],
                shared_task_id=task,thread_ids=[a,b],process_restart_readback=True,
                corrections=len(history['effect_corrections']),current=before['current']),ensure_ascii=False,indent=2))
        finally:stop()


if __name__=='__main__':main()
