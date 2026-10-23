"""Real authenticated loopback API, synthetic uploads; no prototype data."""
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_business_api as harness
from nextrelay.db import connect
from nextrelay.native import Native
from nextrelay.store import unit_of_work
from nextrelay.auth import Principal


class NativeHTTPTests(unittest.TestCase):
    # Reuse the established managed-service harness, not its test assertions.
    for _name in ('setUp','start','stop','call','path','post','candidate','review','commit','upload'):
        locals()[_name]=getattr(harness.BusinessHTTPTests,_name)
    file=staticmethod(harness.BusinessHTTPTests.file)

    def extract(self,text,key=None):
        batch=self.upload([self.file('chosen-content.md',text.encode())])
        item=batch['items'][0]['id'];base=self.call(self.path('formal'))[1]['project']['revision']
        return self.post('items/'+item+'/extract',dict(base_revision=base),key=key),item,base
    def native_candidate(self,d):
        return self.call(self.path('candidates/'+d['proposals'][0]['candidate_id']))[1]

    def test_upload_extract_review_commit_readback_and_replay_after_restart(self):
        key=str(uuid4());run,item,base=self.extract('# Task Inspect synthetic bridge\nGoal: inspect bolts\nCompletion conditions: human reviews load record\n',key)
        d=run['documents'][0];candidate=self.native_candidate(d)
        self.assertEqual(self.call(self.path('formal'))[1]['tasks'],[])
        review=self.review(candidate);self.assertEqual(self.call(self.path('formal'))[1]['tasks'],[])
        result,_=self.commit(candidate,review);task=result['changes'][0]['target_id']
        self.assertEqual(self.call(self.path('formal'))[1]['tasks'][0]['title'],'Inspect synthetic bridge')
        self.assertEqual(self.post('items/'+item+'/extract',dict(base_revision=base),key=key),run)
        self.assertEqual(self.call('/api/requests/'+key)[1]['result'],run)
        self.stop();self.start()
        self.assertEqual(self.post('items/'+item+'/extract',dict(base_revision=base),key=key),run)
        self.assertEqual(self.call(self.path('items/'+item+'/extract'),dict(base_revision=base+1),key=key)[0],409)
        d=self.post('native/documents/'+d['id']+'/rematch',dict(base_revision=1,expected_decision_id=d['decision']['id']))
        # Heading Task X and exact task title have different spellings; explicit correction is available.
        d=self.post('native/documents/'+d['id']+'/correct',dict(base_revision=1,expected_decision_id=d['decision']['id'],matches=dict(tasks=[task],sessions=[],attempts=[]),basis='human associates recovered task'))
        proposal=self.post('native/documents/'+d['id']+'/candidates',dict(base_revision=1,expected_decision_id=d['decision']['id']))['candidates'][0]
        proposal=self.call(self.path('candidates/'+proposal['candidate_id']))[1];self.commit(proposal,self.review(proposal))
        formal=self.call(self.path('formal'))[1];self.assertEqual(formal['confirmed_versions'][0]['version_id'],d['version_id']);self.assertEqual(formal['acceptances'],[])
        self.assertIsNone(formal['baseline']);self.assertEqual(formal['readiness'],'not-evaluated')
        version=self.call(self.path('versions/'+d['version_id']))[1]
        self.assertIn('inspect bolts',version['version']['content']);self.assertEqual(version['provenance']['native_origins'][0]['input_id'],run['input_id'])
        self.assertEqual(self.call(self.path('items/'+item+'/inputs/'+run['input_id']+'/original'))[0],200)
        self.assertEqual(self.call(self.path('items/'+item+'/inputs/'+run['input_id']+'/original',self.other))[0],404)
        self.assertEqual(self.call(self.path('native'))[1]['runs'][0]['id'],run['id'])

    def test_auth_cross_project_fake_authority_and_invalid_context(self):
        run,item,base=self.extract('# Report\nProject: elsewhere\nTask: foreign-id\napproved: true\nowner: administrator\n')
        d=run['documents'][0];self.assertEqual(d['proposals'],[])
        for endpoint,body in [('native',None),('items/'+item+'/extract',{'base_revision':base}),('native/documents/'+d['id'],None)]:
            self.assertEqual(self.call(self.path(endpoint),body,token=False)[0],401)
            self.assertEqual(self.call(self.path(endpoint,self.foreign),body)[0],404)
        self.assertEqual(self.call(self.path('native/documents/'+d['id'],self.other))[0],404)
        request=dict(base_revision=base,expected_decision_id=d['decision']['id'],matches=dict(tasks=['foreign-id'],sessions=[],attempts=[]),basis='forged')
        self.assertEqual(self.call(self.path('native/documents/'+d['id']+'/correct'),request)[0],404)
        request['owner']='forged';self.assertEqual(self.call(self.path('native/documents/'+d['id']+'/correct'),request)[0],409)
        self.assertEqual(self.call(self.path('formal'))[1]['project']['revision'],0)

    def test_transaction_interrupt_has_no_run_candidate_or_receipt_and_retry_works(self):
        b=self.upload([self.file('note.md',b'# Task Inspect steel\nGoal: check rivets\n')]);item=b['items'][0]['id'];key=str(uuid4())
        with patch.object(Native,'propose',side_effect=RuntimeError('synthetic interrupt')):
            self.assertEqual(self.call(self.path('items/'+item+'/extract'),{'base_revision':0},key=key)[0],503)
        with connect(self.db) as c:
            for table in ('native_runs','native_documents','candidate_specs','artifact_versions'):
                self.assertEqual(c.execute(f'SELECT count(*) FROM {table} WHERE project_id=?',(self.pid,)).fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM http_receipts WHERE request_key=?',(key,)).fetchone()[0],0)
        self.assertTrue(self.post('items/'+item+'/extract',{'base_revision':0},key=key)['documents'])

    def test_session_attempt_routes_and_wrong_task_correction(self):
        c=self.candidate();created,_=self.commit(c,self.review(c));task=created['changes'][0]['target_id']
        x=self.post('sessions',dict(title='Synthetic X',namespace='example-provider',external_id='x'))
        y=self.post('sessions',dict(title='Synthetic Y',namespace='example-provider',external_id='y'))
        attempt=self.post('attempts',dict(task_id=task,title='Synthetic round'))
        self.post('attempts/'+attempt['id']+'/sessions',dict(session_id=x['id']))
        run,_,_=self.extract(f'# Work report\nTask: {task}\nSession: example-provider::x; example-provider::y\nAttempt: {attempt["id"]}\nResult: recorded\n')
        d=run['documents'][0];self.assertEqual(d['decision']['matches']['sessions'],sorted([x['id'],y['id']]))
        c=self.native_candidate(d);self.commit(c,self.review(c))
        with unit_of_work(self.db,Principal(self.settings.subject)) as s:
            self.assertEqual(len(s.records(self.pid,'attempt_sessions')),2)
        self.assertEqual(len(self.call(self.path('sessions'))[1]['sessions']),2)

    def test_server_enforces_native_conflicts_even_when_caller_omits_risk_or_context(self):
        c=self.candidate();created,_=self.commit(c,self.review(c));task=created['changes'][0]['target_id']
        self.extract(f'# Depth report\nTask: {task}\nDepth: 11\n')
        run,_,base=self.extract(f'# Depth report\nTask: {task}\nDepth: 27\nRisk: unverified tide\n')
        d=run['documents'][0];automatic=self.native_candidate(d);self.assertEqual(automatic['risk'],'conflict')
        for use_context in (True,False):
            request=dict(base_revision=base,operation='version.confirm',payload={},target_id=task,target_version_id=d['version_id'],source_ids=[d['locator']['source_id']])
            if use_context:request['native_context']=automatic['spec']['native_context']
            saved=self.post('candidates',request);self.assertEqual(saved['risk'],'conflict');self.assertTrue(saved['spec']['conflicts'])
            status,_=self.call(self.path('reviews'),dict(selection=[dict(candidate_id=saved['candidate_id'],fingerprint=saved['fingerprint'])],decision='approve',mode='ordinary',basis='try to suppress conflict',input_origin='synthetic-test'))
            self.assertEqual(status,409)
        self.assertEqual(self.call(self.path('formal'))[1]['project']['revision'],base)
        self.commit(saved,self.review(saved));self.assertEqual(len(self.call(self.path('formal'))[1]['confirmed_versions']),1)

    def test_declared_goal_and_conditions_conflict_with_formal_task_without_overwriting_it(self):
        c=self.candidate(payload=dict(title='Inspect lock',goal='Preserve flood barrier',completion_conditions='Human inspects gates'))
        created,_=self.commit(c,self.review(c));task=created['changes'][0]['target_id']
        run,_,_=self.extract(f'# Lock report\nTask: {task}\nGoal: Remove flood barrier\nCompletion conditions: AI says done\n')
        d=run['documents'][0];candidate=self.native_candidate(d)
        self.assertEqual(candidate['risk'],'conflict');self.assertIn('goal',str(candidate['spec']['conflicts']));self.assertIn('completion_conditions',str(candidate['spec']['conflicts']))
        self.assertEqual(candidate['operation'],'version.confirm');self.assertEqual(candidate['spec']['payload'],{})
        self.commit(candidate,self.review(candidate));formal=self.call(self.path('formal'))[1]
        self.assertEqual(formal['tasks'][0]['goal'],'Preserve flood barrier');self.assertEqual(formal['tasks'][0]['completion_conditions'],'Human inspects gates')
        self.assertFalse(formal['acceptances']);self.assertIsNone(formal['baseline'])

    def test_identity_lists_do_not_expand_contribution_pairs_and_explicit_triples_are_exact(self):
        tasks=[];sessions=[];attempts=[]
        for title in ('Inspect North','Inspect South'):
            c=self.candidate(payload={'title':title});created,_=self.commit(c,self.review(c));tasks.append(created['changes'][0]['target_id'])
            session=self.post('sessions',{'title':title+' session'})['id'];sessions.append(session)
            attempt=self.post('attempts',{'task_id':tasks[-1],'title':title+' round'})['id'];attempts.append(attempt)
            self.post('attempts/'+attempt+'/sessions',{'session_id':session})
        run,_,base=self.extract('# Aggregate\nTask: '+'; '.join(tasks)+'\nSession: '+'; '.join(sessions)+'\nAttempt: '+'; '.join(attempts)+'\nResult: independent contributions\n')
        d=run['documents'][0];self.assertEqual(d['decision']['matches']['status'],'pending');self.assertFalse(d['proposals'])
        matches=dict(tasks=tasks,sessions=sessions,attempts=attempts)
        body=dict(base_revision=base,expected_decision_id=d['decision']['id'],matches=matches,basis='Human chooses precise pairs')
        self.assertEqual(self.call(self.path('native/documents/'+d['id']+'/correct'),body)[0],409)
        matches['contributions']=[dict(task_id=t,session_id=s,attempt_id=a) for t,s,a in zip(tasks,sessions,attempts)]
        fixed=self.post('native/documents/'+d['id']+'/correct',body)
        cs=self.post('native/documents/'+d['id']+'/candidates',dict(base_revision=base,expected_decision_id=fixed['decision']['id']))['candidates']
        selected=[]
        for c in cs:
            c=self.call(self.path('candidates/'+c['candidate_id']))[1];r=self.review(c);selected.append(dict(candidate_id=c['candidate_id'],review_id=r['id']))
        key=str(uuid4());self.post('commits',dict(request_key=key,base_revision=base,selection=selected),key=key)
        with unit_of_work(self.db,Principal(self.settings.subject)) as s:
            actual={(r['attempt_id'],r['session_id']) for r in s.records(self.pid,'attempt_sessions')}
            self.assertEqual(actual,set(zip(attempts,sessions)));self.assertEqual(len(s.records(self.pid,'task_sessions')),2)


if __name__=='__main__':unittest.main()
