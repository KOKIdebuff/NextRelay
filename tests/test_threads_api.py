"""T19 actual authenticated loopback HTTP; synthetic isolated files only."""
from concurrent.futures import ThreadPoolExecutor
from socketserver import ThreadingMixIn
import json
import threading
import unittest
from uuid import UUID, uuid4
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIServer

import test_business_api as business
from nextrelay.app import create_app
from nextrelay.db import connect


class ParallelServer(ThreadingMixIn, WSGIServer):
    daemon_threads=True


class ThreadHTTPTests(unittest.TestCase):
    setUp=business.BusinessHTTPTests.setUp
    stop=business.BusinessHTTPTests.stop
    call=business.BusinessHTTPTests.call
    path=business.BusinessHTTPTests.path
    post=business.BusinessHTTPTests.post
    candidate=business.BusinessHTTPTests.candidate
    review=business.BusinessHTTPTests.review
    commit=business.BusinessHTTPTests.commit

    def start(self):
        self.server=make_server('127.0.0.1',self.settings.port,create_app(self.settings),handler_class=business.Quiet,server_class=ParallelServer)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def effect(self,op,target=None,payload=None):
        c=self.candidate(op,payload=payload,**({'target_id':target} if target else {}));self.commit(c,self.review(c));return c

    def reversal(self,c):
        history=self.call(self.path('history'))[1]
        original=next(r['id'] for r in history['applied_changes'] if r['candidate_id']==c['candidate_id'])
        preview=self.post('reversal-previews',dict(change_id=original))
        return self.effect('change.revoke',original,dict(preview_id=preview['id']))

    def test_all_operations_history_reversal_restart_and_old_sessions(self):
        a=self.post('sessions',dict(title='Same title',namespace='synthetic',external_id='A'))['id']
        b=self.post('sessions',dict(title='Same title',namespace='synthetic',external_id='B'))['id']
        task=self.effect('task.create',payload=dict(title='Synthetic API task'))['target_id']
        operations=[]
        operations.append(self.effect('thread.duty.set',a,dict(main='Implementation',auxiliary=['Review'],basis='Synthetic manual input')))
        suggestion=self.effect('thread.duty.suggest',b,dict(main='Suggested review',basis='Explicit synthetic suggestion'))
        sid=self.call(self.path('threads/'+b))[1]['history']['thread_duties'][0]['id']
        confirm=self.effect('thread.duty.confirm',b,dict(suggestion_id=sid,basis='Synthetic confirmation'))
        operations.append(self.effect('task.participation.set',task,dict(thread_id=a,active=True,basis='Synthetic current work')))
        self.effect('task.participation.set',task,dict(thread_id=b,active=True,basis='Synthetic shared work'))
        operations.append(self.effect('task.lead.set',task,dict(thread_id=a,basis='Synthetic optional lead')))
        operations.append(self.effect('thread.succession.set',a,dict(successor_id=b,active=True,basis='Synthetic succession')))
        before=self.call(self.path('threads'))[1]
        self.assertEqual(self.call(self.path('sessions'))[1]['sessions'],before['threads'])
        self.assertEqual(len(self.call(self.path('tasks/'+task+'/participation'))[1]['current']['participation']),2)
        self.stop();self.start()
        self.assertEqual(self.call(self.path('threads'))[1],before)
        for c in reversed(operations):self.reversal(c)
        self.reversal(confirm);self.reversal(suggestion)
        state=self.call(self.path('threads'))[1]
        self.assertEqual(state['current']['duties'],[])
        self.assertEqual(state['current']['leads'],[])
        self.assertEqual(state['current']['successions'],[])
        self.assertEqual([r['session_id'] for r in state['current']['participation']],[b])
        self.assertEqual(len(self.call(self.path('history'))[1]['effect_corrections']),6)
        self.stop();self.start();self.assertEqual(self.call(self.path('threads'))[1],state)

    def test_auth_origin_scope_payload_budgets_and_transport_idempotency(self):
        a=self.post('sessions',dict(title='Synthetic'))['id']
        for tail in ('threads','threads/'+a,'tasks/'+a+'/participation','history'):
            self.assertEqual(self.call(self.path(tail),token=False)[0],401)
            self.assertEqual(self.call(self.path(tail,self.foreign))[0],404)
            self.assertEqual(self.call(self.path(tail),headers={'Origin':'https://invalid.example'})[0],403)
        self.assertEqual(self.call(self.path('threads/'+a,self.other))[0],404)
        rev=self.call(self.path('formal'))[1]['project']['revision']
        body=dict(base_revision=rev,operation='thread.duty.set',target_id=a,payload=dict(main='X',basis='Synthetic'))
        key=str(uuid4());first=self.post('candidates',body,key=key)
        self.assertEqual(self.post('candidates',body,key=key),first)
        self.assertEqual(self.call(self.path('candidates'),dict(body,payload=dict(main='Y',basis='Synthetic')),key=key)[0],409)
        self.assertEqual(self.call(self.path('candidates',self.other),body)[0],404)
        self.assertEqual(self.call(self.path('candidates'),dict(body,thread_id=a))[0],409)
        self.assertEqual(self.call(self.path('candidates'),dict(body,payload=dict(main='X'*100001,basis='Synthetic')))[0],409)
        rejected=self.review(first,'reject')
        key=str(uuid4())
        self.assertEqual(self.call(self.path('commits'),dict(request_key=key,base_revision=rev,selection=[dict(candidate_id=first['candidate_id'],review_id=rejected['id'])]),key=key)[0],409)
        self.assertEqual(self.call(self.path('threads'))[1]['current']['duties'],[])

    def test_concurrent_http_cycle_commits_one_revision_and_atomic_audit(self):
        a=self.post('sessions',dict(title='A'))['id'];b=self.post('sessions',dict(title='B'))['id']
        cs=[self.candidate('thread.succession.set',target_id=x,payload=dict(successor_id=y,active=True,basis='Synthetic')) for x,y in ((a,b),(b,a))]
        reviews=[self.review(c) for c in cs];barrier=threading.Barrier(2)
        def commit(i):
            key=str(uuid4());barrier.wait()
            return self.call(self.path('commits'),dict(request_key=key,base_revision=0,selection=[dict(candidate_id=cs[i]['candidate_id'],review_id=reviews[i]['id'])]),key=key)
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(commit,range(2)))
        self.assertCountEqual([r[0] for r in results],[200,409])
        self.assertEqual(next(r[1]['error'] for r in results if r[0]==409),'revision_conflict')
        with connect(self.db) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM applied_changes').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM change_commits').fetchone()[0],1)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_http_stale_approval_reversal_and_duplicate_correction(self):
        a=self.post('sessions',dict(title='A'))['id']
        c=self.effect('thread.duty.set',a,dict(main='X',basis='Synthetic'))
        history=self.call(self.path('history'))[1];original=next(r['id'] for r in history['applied_changes'] if r['candidate_id']==c['candidate_id'])
        p=self.post('reversal-previews',dict(change_id=original))
        revoke=self.candidate('change.revoke',target_id=original,payload=dict(preview_id=p['id']));review=self.review(revoke)
        unrelated=self.effect('task.create',payload=dict(title='Unrelated'))
        key=str(uuid4())
        self.assertEqual(self.call(self.path('commits'),dict(request_key=key,base_revision=revoke['spec']['base_revision'],selection=[dict(candidate_id=revoke['candidate_id'],review_id=review['id'])]),key=key)[0],409)
        p=self.post('reversal-previews',dict(change_id=original));revoke=self.candidate('change.revoke',target_id=original,payload=dict(preview_id=p['id']));review=self.review(revoke)
        result,body=self.commit(revoke,review)
        self.assertEqual(self.post('commits',body,key=body['request_key']),result)
        self.assertEqual(self.call(self.path('reversal-previews'),dict(change_id=original))[0],409)
        self.assertEqual(len(self.call(self.path('history'))[1]['effect_corrections']),1)
        self.assertEqual(self.call(self.path('tasks/'+unrelated['target_id']))[0],200)

    def test_same_batch_succession_correction_removes_edges_before_add_even_with_opposite_uuid_order(self):
        a=self.post('sessions',dict(title='A'))['id'];b=self.post('sessions',dict(title='B'))['id']
        self.effect('thread.succession.set',a,dict(successor_id=b,active=True,basis='Synthetic original'))
        # Control only fresh server-allocated identities, never effects, SQL or
        # responses. Actual HTTP must handle the formerly failing UUID order.
        with patch('nextrelay.store.uuid4',side_effect=[UUID('ffffffff-ffff-ffff-ffff-ffffffffffff'),uuid4()]):
            remove=self.candidate('thread.succession.set',target_id=a,payload=dict(successor_id=b,active=False,basis='Synthetic correction'))
        with patch('nextrelay.store.uuid4',side_effect=[UUID('00000000-0000-0000-0000-000000000001'),uuid4()]):
            add=self.candidate('thread.succession.set',target_id=b,payload=dict(successor_id=a,active=True,basis='Synthetic correction'))
        self.assertLess(add['candidate_id'],remove['candidate_id'])
        rs=[self.review(c) for c in (remove,add)];key=str(uuid4())
        self.post('commits',dict(request_key=key,base_revision=remove['spec']['base_revision'],selection=[dict(candidate_id=c['candidate_id'],review_id=r['id']) for c,r in zip((remove,add),rs)]),key=key)
        edges=self.call(self.path('threads'))[1]['current']['successions']
        self.assertEqual({(r['predecessor_id'],r['successor_id']) for r in edges if r['active']},{(b,a)})
