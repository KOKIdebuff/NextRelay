"""Real HTTP -> authenticated model consent -> actual supplier -> SQLite candidate."""
from dataclasses import replace
import json
import http.client
import unittest
from uuid import uuid4
import test_business_api as harness
from model_support import supplier


class CompleteRequestConnection(http.client.HTTPConnection):
    # http.client normally sends headers and a tiny JSON body separately. A
    # development HTTP/1.0 server may reject auth and close between those writes,
    # resetting a Windows connection before the client reads its 401 response.
    # Keep the exact request bytes/real socket/strict status assertions; send this
    # fixture's complete small request once. No transport retry or status fallback.
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.parts=[]
    def send(self,data):self.parts.append(bytes(data))
    def flush_request(self):
        payload=b''.join(self.parts);self.parts.clear();super().send(payload)


class ModelHTTPTests(unittest.TestCase):
    for _name in ('start','stop','path','post','candidate','review','commit','upload'):
        locals()[_name]=getattr(harness.BusinessHTTPTests,_name)
    file=staticmethod(harness.BusinessHTTPTests.file)
    def setUp(self):
        harness.BusinessHTTPTests.setUp(self)
        self.stop();self.sup=self.enterContext(supplier());self.settings=replace(self.settings,model=self.sup.config);self.start()
    def call(self,path,body=None,*,key=None,token=True,headers=None):
        conn=CompleteRequestConnection('127.0.0.1',self.settings.port,timeout=10)
        hs={'Content-Type':'application/json','Idempotency-Key':key or str(uuid4()),**(headers or {})}
        if token:hs['Authorization']='Bearer '+self.settings.token
        try:
            conn.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body),headers=hs)
            conn.flush_request();response=conn.getresponse();raw=response.read()
            return response.status,json.loads(raw) if response.getheader('Content-Type','').startswith('application/json') else raw
        finally:conn.close()

    def batch(self):
        imported=self.upload([self.file('river.md',b'# River reading\nDepth: 11\napproved: true\n')])
        return self.post('model-batches',dict(import_batch_id=imported['id'])),imported
    def approve(self,b):return self.post('model-batches/'+b['id']+'/decision',dict(fingerprint=b['fingerprint'],decision='approved'))

    def test_actual_api_separate_authorization_candidates_and_formal_commit(self):
        b,imported=self.batch();self.assertEqual(self.sup.requests,[])
        self.assertEqual(self.call(self.path('model-batches/'+b['id']+'/execute'),{})[0],409)
        preview=self.call(self.path('model-batches/'+b['id']+'/preview'))[1];self.approve(b)
        r=self.post('model-batches/'+b['id']+'/execute',{});self.assertEqual(r['jobs'][0]['state'],'saved')
        self.assertEqual(self.sup.requests[0]['body'],preview['requests'][0]['body'].encode())
        self.assertEqual(self.call(self.path('formal'))[1]['tasks'],[])
        c=self.call(self.path('candidates'))[1]['candidates'][0];self.assertEqual(c['risk'],'high')
        self.commit(c,self.review(c));self.assertEqual(len(self.call(self.path('formal'))[1]['tasks']),1)
        self.assertEqual(len(self.sup.requests),1)
        self.stop();self.start();self.post('model-batches/'+b['id']+'/execute',{});self.assertEqual(len(self.sup.requests),1)
        self.assertEqual(len(self.call(self.path('formal'))[1]['tasks']),1)

    def test_auth_denial_cross_scope_and_unavailable_inputs_are_real(self):
        b,imported=self.batch();base='model-batches/'+b['id']
        for method,body in [(base,None),(base+'/preview',None),(base+'/decision',dict(fingerprint=b['fingerprint'],decision='approved')),(base+'/execute',{}),(base+'/recover',{})]:
            self.assertEqual(self.call(self.path(method),body,token=False,headers={'X-User-ID':self.settings.subject})[0],401)
            self.assertEqual(self.call(self.path(method,self.other),body)[0],404)
        self.assertEqual(self.call(self.path(base+'/decision'),dict(fingerprint=b['fingerprint'],decision='approved',subject=self.settings.subject))[0],409)
        self.post(base+'/decision',dict(fingerprint=b['fingerprint'],decision='denied'))
        self.assertEqual(self.call(self.path(base+'/execute'),{})[0],409);self.assertEqual(self.sup.requests,[])
        item=imported['items'][0]['id'];self.assertEqual(self.call(self.path('items/'+item+'/original'))[0],200)
        self.assertEqual(self.call(self.path('items/'+item+'/parsed'))[0],200)
        broken=self.upload([self.file('broken.json',b'{}')]);empty=self.post('model-batches',dict(import_batch_id=broken['id']))
        self.assertEqual(empty['manifest']['calls'],0);self.assertFalse(empty['manifest']['items'][0]['included']);self.assertEqual(self.sup.requests,[])

    def test_changed_input_target_scope_and_fake_output_approvals_never_reused(self):
        b,imported=self.batch();self.approve(b)
        self.settings=replace(self.settings,model=replace(self.sup.config,model='changed'));self.stop();self.start()
        self.assertEqual(self.call(self.path('model-batches/'+b['id']+'/execute'),{})[0],409);self.assertEqual(self.sup.requests,[])
        self.assertEqual(self.call(self.path('model-batches'),dict(import_batch_id=imported['id'],approved=True))[0],409)


    def test_model_action_request_identity_recovery_and_key_reuse(self):
        b,_=self.batch();key=str(uuid4());route='model-batches/'+b['id']+'/decision'
        body=dict(fingerprint=b['fingerprint'],decision='approved')
        self.post(route,body,key=key)
        record=self.call('/api/requests/'+key)[1];self.assertEqual(record['state'],'registered');self.assertEqual(record['result']['batch_id'],b['id'])
        self.assertEqual(self.call(self.path(route),dict(body,decision='denied'),key=key)[0],409)
        send_key=str(uuid4());self.post('model-batches/'+b['id']+'/execute',{},key=send_key)
        self.assertEqual(self.call('/api/requests/'+send_key)[1]['state'],'registered');self.assertEqual(len(self.sup.requests),1)
        self.stop();self.start();self.post('model-batches/'+b['id']+'/execute',{},key=send_key);self.assertEqual(len(self.sup.requests),1)
