import test_business_api as harness
from test_model_api import CompleteRequestConnection
from dataclasses import replace
import http.client
import json
import unittest
from uuid import uuid4
from github_support import github_server

class GitHubHTTPTests(unittest.TestCase):
    for _name in ('start','stop','path','post'):
        locals()[_name]=getattr(harness.BusinessHTTPTests,_name)
    def call(self,path,body=None,*,key=None,token=True,headers=None):
        c=CompleteRequestConnection('127.0.0.1',self.settings.port,timeout=15)
        hs={'Content-Type':'application/json','Idempotency-Key':key or str(uuid4()),**(headers or {})}
        if token:hs['Authorization']='Bearer '+self.settings.token
        try:
            c.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body),headers=hs);c.flush_request()
            r=c.getresponse();return r.status,json.loads(r.read())
        finally:c.close()
    def setUp(self):
        self.remote=self.enterContext(github_server())
        harness.BusinessHTTPTests.setUp(self);self.stop();self.settings=replace(self.settings,github=self.remote.config);self.start()
    def test_actual_api_identity_scope_receipt_and_native_model_separation(self):
        body={'url':'https://github.com/test/repo','storage_choice':'configured-local'};key=str(uuid4())
        self.assertEqual(self.call(self.path('github'),body,token=False)[0],401)
        self.assertEqual(self.call(self.path('github',self.foreign),body)[0],404);self.assertEqual(self.remote.requests,[])
        b=self.post('github',body,key=key);self.assertEqual(self.call('/api/requests/'+key)[1]['result']['snapshot_id'],b['id'])
        self.assertEqual(self.call(self.path('github/'+b['id'],self.other))[0],404)
        self.assertEqual(self.call(self.path('github/'+b['id']+'/read',self.other),{})[0],404)
        self.assertEqual(self.call(self.path('github/'+b['id']+'/read'),{'confirmed':True})[0],409)
        b=self.post('github/'+b['id']+'/read',{});item=next(e['item_id'] for e in b['entries'] if e['item_id'])
        self.assertEqual(self.call(self.path('items/'+item+'/parsed'))[0],200)
        self.assertEqual(self.call(self.path('model-batches'))[1]['batches'],[])
        self.assertEqual(self.call(self.path('formal'))[1]['tasks'],[])
        self.assertEqual(self.call(self.path('candidates'),{},key=key)[0],409)
        self.assertTrue(all('/repos/test/repo' in p for p in self.remote.requests))
    def test_failed_action_replay_keeps_http_error_and_receipt(self):
        b=self.post('github',{'url':'https://github.com/test/repo','storage_choice':'configured-local'})
        key=str(uuid4());body={'scope_id':'missing','fingerprint':'forged'}
        first=self.call(self.path('github/'+b['id']+'/confirm'),body,key=key)
        second=self.call(self.path('github/'+b['id']+'/confirm'),body,key=key)
        self.assertEqual(first,second);self.assertEqual(first[0],404)
        receipt=self.call('/api/requests/'+key)[1];self.assertEqual(receipt['state'],'failed');self.assertEqual(receipt['error']['http_status'],404)

    def test_source_reference_api_error_and_prepare_replay(self):
        key=str(uuid4());body={'url':'https://example.invalid/unsupported','storage_choice':'configured-local'}
        b=self.post('github',body,key=key);self.assertEqual(b['state'],'reference-only');self.assertEqual(self.remote.requests,[])
        self.assertEqual(self.post('github',body,key=key)['id'],b['id'])
        self.assertEqual(self.call(self.path('github'),{**body,'url':'https://other.invalid'},key=key)[0],409)
        self.assertEqual(self.call(self.path('github/'+b['id']+'/read'),{})[0],409)

if __name__=='__main__':unittest.main()
