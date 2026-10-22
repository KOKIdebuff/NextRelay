"""Actual local HTTP services, isolated SQLite and synthetic browser upload bytes."""
import base64
from dataclasses import replace
import http.client
import json
from pathlib import Path
import secrets
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4
from wsgiref.simple_server import make_server, WSGIRequestHandler

from nextrelay.app import create_app
from nextrelay.auth import Principal
from nextrelay.changes import Changes
from nextrelay.config import Settings
from nextrelay.db import initialize,connect,transaction,verify_schema,_version_catalog
from nextrelay.schema import MIGRATIONS
from nextrelay.store import unit_of_work


class Quiet(WSGIRequestHandler):
    def log_message(self,*args):pass


class BusinessHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nextrelay-t11-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.storage=self.root/'originals';self.storage.mkdir()
        self.db=self.root/'demo.sqlite3';initialize(self.db)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        self.settings=Settings(self.db,secrets.token_urlsafe(32),subject='dev-t11-test',port=port,local_root=self.storage)
        self.start();self.addCleanup(self.stop)
        self.pid=self.call('/api/projects',{'title':'Synthetic HTTP project'})[1]['id']
        with unit_of_work(self.db,Principal('dev-other-user'),write=True) as s:self.foreign=s.create_project('foreign')['id']
        with unit_of_work(self.db,Principal(self.settings.subject),write=True) as s:self.other=s.create_project('other')['id']

    def start(self):
        self.server=make_server('127.0.0.1',self.settings.port,create_app(self.settings),handler_class=Quiet)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def stop(self):
        if self.server:self.server.shutdown();self.thread.join();self.server.server_close();self.server=None

    def call(self,path,body=None,*,key=None,token=True,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.settings.port,timeout=10)
        hs={'Content-Type':'application/json','Idempotency-Key':key or str(uuid4()),**(headers or {})}
        if token:hs['Authorization']='Bearer '+self.settings.token
        conn.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body),headers=hs)
        res=conn.getresponse();raw=res.read();status=res.status;conn.close()
        return status,json.loads(raw) if res.getheader('Content-Type','').startswith('application/json') else raw

    def path(self,x,project=None):return '/api/projects/'+(project or self.pid)+'/'+x
    def post(self,x,body,**kw):
        status,value=self.call(self.path(x),body,**kw);self.assertEqual(status,200,value);return value
    def candidate(self,op='task.create',payload=None,**kwargs):
        rev=self.call(self.path('formal'))[1]['project']['revision']
        return self.post('candidates',dict(operation=op,base_revision=rev,payload={'title':'Synthetic task','goal':'test','completion_conditions':'human verifies exact version'} if payload is None else payload,**kwargs))
    def review(self,c,decision='approve'):
        return self.post('reviews',dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint'])],decision=decision,mode='explicit' if c['risk']!='ordinary' else 'ordinary',basis='Synthetic HTTP review',input_origin='synthetic-test',**({'authorization':c['authorization']} if c['risk']!='ordinary' and decision=='approve' else {})))['reviews'][0]
    def commit(self,c,r,key=None):
        key=key or str(uuid4());body=dict(request_key=key,base_revision=c['spec']['base_revision'],selection=[dict(candidate_id=c['candidate_id'],review_id=r['id'])])
        return self.post('commits',body,key=key),body
    @staticmethod
    def file(name,data):return {'name':name,'base64':base64.b64encode(data).decode()}
    def upload(self,files,key=None):return self.post('imports',{'storage_choice':'configured-local','parse':True,'files':files},key=key)

    def test_auth_host_origin_and_object_scope_cover_reads_writes_uploads(self):
        for resource in ('formal','snapshot','imports','candidates','history','sources'):
            self.assertEqual(self.call(self.path(resource),token=False)[0],401)
            self.assertEqual(self.call(self.path(resource,self.foreign))[0],404)
        for resource,body in [('candidates',{}),('reviews',{}),('commits',{}),('imports',{})]:
            self.assertEqual(self.call(self.path(resource,self.foreign),body)[0],404)
        self.assertEqual(self.call(self.path('formal'),headers={'Origin':'http://evil.invalid'})[0],403)
        self.assertEqual(self.call('/api/projects',{'title':'x','subject':'dev-other-user'})[0],409)
        self.assertEqual(self.call('/api/projects',token=False,headers={'X-User-ID':self.settings.subject})[0],401)
        self.assertEqual(self.call('/api/projects',headers={'Host':'attacker.invalid'})[0],400)
        self.assertEqual(self.call('/src/../nextrelay/config.py')[0],404)

    def test_three_independent_steps_receipts_stale_and_conflicting_replay(self):
        k=str(uuid4());body={'title':'exact replay'}
        first=self.call('/api/projects',body,key=k);self.assertEqual(first,self.call('/api/projects',body,key=k))
        self.assertEqual(self.call('/api/projects',{'title':'different'},key=k)[0],409)
        c=self.candidate();self.assertEqual(len(self.call(self.path('formal'))[1]['tasks']),0)
        r=self.review(c);self.assertEqual(len(self.call(self.path('formal'))[1]['tasks']),0)
        stale=self.candidate(payload={'title':'stale'})
        result,body=self.commit(c,r);self.assertEqual(result['revision'],1)
        self.assertEqual(self.post('commits',body,key=body['request_key']),result)
        self.assertEqual(self.call(self.path('commits'),dict(body,base_revision=0,selection=[]),key=body['request_key'])[0],409)
        self.assertEqual(self.call(self.path('reviews'),dict(selection=[dict(candidate_id=stale['candidate_id'],fingerprint=stale['fingerprint'])],decision='approve',mode='ordinary',basis='stale',input_origin='synthetic-test'))[0],409)
        with unit_of_work(self.db,Principal(self.settings.subject)) as s:self.assertEqual(s.formal_state(self.pid),self.call(self.path('formal'))[1])

    def test_upload_actual_bytes_partial_failure_replacement_scope_and_reopen(self):
        k=str(uuid4());files=[self.file('notes.md',b'# Synthetic\nExact browser-selected bytes'),self.file('broken.json',b'{}'),self.file('unsupported.zip',b'synthetic zip')]
        b=self.upload(files,k);self.assertEqual(b['summary'],{'complete':1,'incomplete':2,'total':3})
        self.assertEqual(self.upload(files,k)['id'],b['id'])
        self.assertEqual(len(self.call(self.path('imports'))[1]['batches']),1)
        item=b['items'][0];self.assertEqual(base64.b64decode(self.call(self.path('items/'+item['id']+'/original'))[1]['base64']),b'# Synthetic\nExact browser-selected bytes')
        self.assertIn('Exact browser-selected bytes',self.call(self.path('items/'+item['id']+'/parsed'))[1]['text'])
        failed=b['items'][1]['id'];fixed=json.dumps({'protocol':'nextrelay.import','version':1,'documents':[{'id':'s1','title':'Synthetic replacement','text':'new exact text'}]}).encode()
        key=str(uuid4());replacement={'replacement':self.file('fixed.json',fixed)}
        r=self.post('items/'+failed+'/retry',replacement,key=key);self.assertEqual(r['parse_status'],'parsed')
        self.assertEqual(r,self.post('items/'+failed+'/retry',replacement,key=key))
        self.assertEqual(self.call(self.path('items/'+failed+'/parsed',self.other))[0],404)
        self.assertEqual(self.call(self.path('items/'+failed+'/retry',self.other),replacement)[0],404)
        self.assertEqual(self.call(self.path('items/'+item['id']+'/retry'),{'use_original':True})[0],409)
        self.assertEqual(self.call(self.path('imports'),{'storage_choice':'configured-local','parse':True,'files':[{'path':'C:/secret','name':'secret.txt','base64':''}]})[0],409)
        self.assertFalse(list(self.storage.glob('upload-*.input')))
        self.assertFalse(list(self.storage.glob('upload-*.stage')))
        self.stop();self.start()
        reread=self.call(self.path('imports/'+b['id']))[1]
        self.assertEqual(len(reread['items'][0]['attempts']),1)
        self.assertEqual(len(reread['items'][1]['attempts']),2)
        self.assertEqual(self.call(self.path('items/'+failed+'/parsed'))[1]['protocol']['documents'][0]['text'],'new exact text')

    def test_task_lifecycle_human_acceptance_dependency_and_single_reversal(self):
        c=self.candidate();r=self.review(c);created,_=self.commit(c,r);tid=created['changes'][0]['target_id']
        a=self.post('artifacts',{'title':'Synthetic exact report'})
        v=self.post('artifacts/'+a['id']+'/versions',{'content':'SYNTHETIC report full body','reason':'synthetic fixture'})
        c=self.candidate('version.confirm',{},target_id=tid,target_version_id=v['id']);self.commit(c,self.review(c))
        for op,payload in [('task.start',{'basis':'synthetic start'}),('task.submit',{'basis':'synthetic submit'}),('acceptance.human',{'decision':'accept','basis':'synthetic human checks exact report'})]:
            c=self.candidate(op,payload,target_id=tid,**({'target_version_id':v['id']} if op!='task.start' else {}));result,_=self.commit(c,self.review(c))
        f=self.call(self.path('formal'))[1];self.assertEqual(f['derived']['tasks'][0]['validity'],'applicable')
        version=self.call(self.path('versions/'+v['id']))[1];self.assertEqual(version['version']['content'],'SYNTHETIC report full body');self.assertEqual(version['provenance']['source_status'],'pending')
        self.assertEqual(self.call(self.path('versions/'+v['id'],self.other))[0],404)
        original=result['changes'][0]['change_id'];p=self.post('reversal-previews',{'change_id':original});plan=json.loads(p['preview_json']);self.assertEqual(plan['conflicts'],[])
        c=self.candidate('change.revoke',{'preview_id':p['id']},target_id=original);self.commit(c,self.review(c))
        f=self.call(self.path('formal'))[1];self.assertEqual(f['tasks'][0]['lifecycle'],'awaiting-acceptance');self.assertEqual(len(f['corrections']),1)
        self.assertEqual(self.call(self.path('versions/'+v['id']))[1]['version']['content'],'SYNTHETIC report full body')

    def test_transaction_failure_does_not_leave_receipt_or_partial_state(self):
        from nextrelay.lifecycle import Lifecycle
        k=str(uuid4())
        with patch.object(Lifecycle,'sync',side_effect=RuntimeError('synthetic transaction fault')):
            self.assertEqual(self.call('/api/projects',{'title':'rollback'},key=k)[0],503)
        with connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM http_receipts WHERE request_key=?',(k,)).fetchone()[0],0)
            self.assertEqual(c.execute("SELECT count(*) FROM projects WHERE title='rollback'").fetchone()[0],0)
        self.assertEqual(self.call('/api/projects',{'title':'rollback'},key=k)[0],200)

    def test_request_recovery_survives_reauthentication_and_keeps_owner_checks(self):
        key=str(uuid4());body={'title':'Synthetic response-loss recovery'}
        status,p=self.call('/api/projects',body,key=key);self.assertEqual(status,200)
        recovered=self.call('/api/requests/'+key)[1]
        self.assertEqual(recovered,{'state':'committed','result':p})
        self.assertEqual(self.call('/api/requests/'+key,token=False)[0],401)
        k=str(uuid4());b=self.upload([self.file('s.md',b'SYNTHETIC')],k)
        self.assertEqual(self.call('/api/requests/'+k)[1]['result']['id'],b['id'])
        self.stop();self.start()
        self.assertEqual(self.call('/api/requests/'+key)[1],recovered)

    def test_bounded_file_fields_cannot_request_cloud_or_server_paths(self):
        body={'storage_choice':'cloud-requested','parse':True,'files':[self.file('s.md',b'synthetic')]}
        self.assertEqual(self.call(self.path('imports'),body)[0],409)
        body['storage_choice']='configured-local';body['files'][0]['base64']='%%%'
        self.assertEqual(self.call(self.path('imports'),body)[0],400)
        body['files']=[self.file('../outside.md',b'synthetic')]
        self.assertEqual(self.call(self.path('imports'),body)[0],409)
        body['files']=[self.file('big.md',b'x'*(5*1024*1024+1))]
        self.assertEqual(self.call(self.path('imports'),body)[0],413)
        self.assertEqual(self.call(self.path('imports'))[1]['batches'],[])

    def test_upload_never_adopts_or_deletes_an_unknown_generated_slot(self):
        from nextrelay.http_api import upload_path,upload_marker,cleanup_uploads
        key=str(uuid4());p=upload_path(self.storage,self.pid,key,0)
        p.write_bytes(b'UNKNOWN existing content; preserve')
        body={'storage_choice':'configured-local','parse':True,'files':[self.file('s.md',b'SYNTHETIC')]}
        self.assertEqual(self.call(self.path('imports'),body,key=key)[0],409)
        self.assertEqual(p.read_bytes(),b'UNKNOWN existing content; preserve')
        with connect(self.db) as c:self.assertEqual(c.execute('SELECT count(*) FROM browser_uploads WHERE request_key=?',(key,)).fetchone()[0],0)
        key2=str(uuid4());self.upload([self.file('known.md',b'SYNTHETIC')],key2)
        owned=upload_path(self.storage,self.pid,key2,0);self.assertTrue(upload_marker(owned).exists())
        owned.write_bytes(b'UNKNOWN replacement at old slot; preserve')
        cleanup_uploads(self.settings)
        self.assertEqual(owned.read_bytes(),b'UNKNOWN replacement at old slot; preserve')

    def test_builtin_check_pre_authorization_is_independent_of_actual_pass(self):
        c=self.candidate();created,_=self.commit(c,self.review(c));tid=created['changes'][0]['target_id']
        a=self.post('artifacts',{'title':'Synthetic checked report'})
        v=self.post('artifacts/'+a['id']+'/versions',{'content':'SYNTHETIC complete report','reason':'synthetic fixture'})
        c=self.candidate('version.confirm',{},target_id=tid,target_version_id=v['id']);self.commit(c,self.review(c))
        c=self.candidate('task.submit',{'basis':'Synthetic submit'},target_id=tid,target_version_id=v['id']);self.commit(c,self.review(c))
        config={'protocol':'builtin-v1','type':'content-assertions','rules':{'required':['SYNTHETIC']}}
        from datetime import datetime,timedelta,timezone
        c=self.candidate('check.authorize',{'config':config,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'scope':'accept-exact-version','basis':'Synthetic exact authorization'},target_id=tid,target_version_id=v['id'])
        self.commit(c,self.review(c))
        state=self.call(self.path('formal'))[1];self.assertEqual(state['tasks'][0]['lifecycle'],'awaiting-acceptance')
        grant=state['current_authorizations'][0]
        run=self.post('checks',{'task_id':tid,'version_id':v['id'],'configuration':config});self.assertEqual(run['result'],'pass')
        key=str(uuid4());body=dict(request_key=key,base_revision=state['project']['revision'],task_id=tid,version_id=v['id'],check_id=run['id'],authorization_id=grant['id'])
        result=self.post('auto-accept',body,key=key)
        self.assertEqual(self.post('auto-accept',body,key=key),result)
        self.assertEqual(self.call(self.path('tasks/'+tid))[1]['derived']['validity'],'applicable')

    def test_v6_migration_retains_existing_business_rows_and_receipts_append_only(self):
        old=self.root/'old-v6.sqlite3'
        with connect(old) as c:
            with transaction(c):
                for v in range(1,7):
                    for sql in MIGRATIONS[v]:c.execute(sql)
                c.execute('PRAGMA user_version=6')
                c.execute("INSERT INTO foundation_scopes VALUES ('kept','dev-old','synthetic-access-fixture')")
        initialize(old);initialize(old)
        with connect(old) as c:
            verify_schema(c);self.assertEqual(c.execute('SELECT label FROM foundation_scopes').fetchone()[0],'synthetic-access-fixture')
            c.execute("INSERT INTO http_receipts VALUES ('dev-old','synthetic-key','/api/projects','hash','{}','synthetic-time')")
            with self.assertRaises(Exception):c.execute('DELETE FROM http_receipts')
