"""T19 revision invalidates T09 approval; zero calls to controlled supplier."""
import unittest
from uuid import uuid4
import test_model as model_tests

from nextrelay.changes import ChangeError, Changes


class ThreadModelFreshnessTests(unittest.TestCase):
    setUp=model_tests.ModelTests.setUp
    read=model_tests.ModelTests.read
    write=model_tests.ModelTests.write
    import_batch=model_tests.ModelTests.import_batch
    prepare=model_tests.ModelTests.prepare
    approve=model_tests.ModelTests.approve

    def effect(self,op,target,payload):
        def apply(s):
            request=dict(operation=op,base_revision=s.project(self.p)['revision'],payload=payload)
            if target is not None:request['target_id']=target
            c=s.save_candidate(self.p,request)
            review=s.review_candidates(self.p,dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint'])],decision='approve',mode='ordinary',basis='Synthetic revision test',input_origin='synthetic-test'))[0]
            s.commit_candidates(self.p,dict(request_key=str(uuid4()),base_revision=c['spec']['base_revision'],selection=[dict(candidate_id=c['candidate_id'],review_id=review['id'])]))
            return c
        return self.write(apply)

    def test_each_new_formal_operation_invalidates_prepared_and_approved_batch(self):
        a,b=self.write(lambda s:[s.create_session(self.p,title)['id'] for title in ('A','B')])
        task=self.effect('task.create',None,dict(title='Synthetic old task'))['target_id']
        operations=[('thread.duty.set',a,dict(main='Implementation',basis='Synthetic')),
                    ('task.participation.set',task,dict(thread_id=a,active=True,basis='Synthetic')),
                    ('task.lead.set',task,dict(thread_id=a,basis='Synthetic')),
                    ('thread.succession.set',a,dict(successor_id=b,active=True,basis='Synthetic')),
                    ('thread.duty.suggest',b,dict(main='Review',basis='Synthetic'))]
        for op,target,payload in operations:
            with self.subTest(op=op):
                batch=self.prepare();self.approve(batch)
                self.effect(op,target,payload)
                with self.assertRaises(ChangeError):self.model.execute(self.p,batch['id'])
                self.assertEqual(self.sup.requests,[])
                unapproved=self.prepare()
                # A new formal update invalidates a preview even before approval.
                self.effect('thread.duty.set',a,dict(main=op,basis='Synthetic'))
                with self.assertRaises(ChangeError):self.approve(unapproved)
                self.assertEqual(self.sup.requests,[])
        suggestion=self.read(lambda s:s.thread_state(self.p,thread_id=b)['history']['thread_duties'][0]['id'])
        batch=self.prepare();self.approve(batch)
        self.effect('thread.duty.confirm',b,dict(suggestion_id=suggestion,basis='Synthetic'))
        with self.assertRaises(ChangeError):self.model.execute(self.p,batch['id'])
        self.assertEqual(self.sup.requests,[])
