"""T20 real local HTTP, parsed reports and captured controlled model requests."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import threading
import unittest
from uuid import uuid4
from unittest.mock import patch
from nextrelay.auth import Principal
from nextrelay.changes import Changes
from nextrelay.store import unit_of_work
from nextrelay.native import Native
from nextrelay.model import ModelService
from nextrelay.model_protocol import PROTOCOL_V2
import test_business_api as business
import test_model_api as model_api
import test_threads_api as threads_api
from model_support import supplier


class T20HTTPTests(unittest.TestCase):
    for name in ('stop','path','post','candidate','review','commit','upload'):
        locals()[name]=getattr(business.BusinessHTTPTests,name)
    call=model_api.ModelHTTPTests.call
    start=threads_api.ThreadHTTPTests.start
    file=staticmethod(business.BusinessHTTPTests.file)

    def setUp(self):
        business.BusinessHTTPTests.setUp(self)
        self.stop();self.sup=self.enterContext(supplier());self.settings=replace(self.settings,model=self.sup.config);self.start()
        self.a=self.post('threads',dict(title='Identical title',namespace='synthetic.plan',external_id='A'))['id']
        self.b=self.post('sessions',dict(title='Identical title',namespace='synthetic.plan',external_id='B'))['id']
        c=self.candidate(payload=dict(title='Synthetic work'))
        self.commit(c,self.review(c));self.task=c['target_id']

    def get(self,tail):
        status,value=self.call(self.path(tail));self.assertEqual(status,200,value);return value
    def revision(self):return self.get('formal')['project']['revision']
    def extract(self,text=None):
        if text is None:text=f'# Sourced report\nThread: synthetic.plan::A\nTask: {self.task}\nMain duty: Review\nAuxiliary duty: Test; Explain\nParticipation: active\nAssignment: Inspect the gate\nLead: true\nResult: reported only\n'
        batch=self.upload([self.file('report.md',text.encode())]);item=batch['items'][0]['id']
        run=self.post('items/'+item+'/extract',dict(base_revision=self.revision()))
        return batch,run['documents'][0]
    def candidates_for(self,d):
        ids={p['candidate_id'] for p in d['proposals']}
        return [c for c in self.get('candidates')['candidates'] if c['candidate_id'] in ids]
    def correction(self,d,thread=None):
        return self.post('native/documents/'+d['id']+'/correct',dict(base_revision=self.revision(),expected_decision_id=d['decision']['id'],
            matches=dict(tasks=[self.task],threads=[thread or self.b],attempts=[]),basis='Synthetic human correction'))
    def prepare(self,batch,**kw):return self.post('model-batches',dict(import_batch_id=batch['id'],protocol=PROTOCOL_V2,**kw))
    def approve(self,b):return self.post('model-batches/'+b['id']+'/decision',dict(fingerprint=b['fingerprint'],decision='approved'))
    def execute(self,b):return self.post('model-batches/'+b['id']+'/execute',{})
    def response(self,payload,candidates,protocol=PROTOCOL_V2):
        return 200,dict(id='resp_t20',status='completed',model=payload['model'],output=[dict(type='message',role='assistant',
            content=[dict(type='output_text',text=json.dumps(dict(protocol=protocol,candidates=candidates)))])])
    def proposal(self,payload,op='thread.duty.suggest',target=None,body=None):
        entries=json.loads(payload['input'][1]['content'])['entries'];e=next(e for e in entries if e['kind']=='format')
        return dict(operation=op,target_id=target or self.a,target_version_id=None,
            payload=body or dict(main='Model review',auxiliary=[],basis='Unverified source interpretation'),rationale='Sourced synthetic declaration',
            citations=[dict(entry_id=e['id'],sha256=e['sha256'],start=0,end=20,quote=e['text'][:20])],risks=[],uncertainties=[])

    def test_continuous_import_legacy_alias_conflict_and_unknown(self):
        batch,a=self.extract(f'# Old\nSession: {self.a}\nTask: {self.task}\nResult: first\n')
        _,b=self.extract(f'# New\nThread: synthetic.plan::A\nTask: {self.task}\nResult: second\n')
        self.assertEqual(a['decision']['matches']['sessions'],b['decision']['matches']['sessions'])
        self.assertNotEqual(a['locator']['source_id'],b['locator']['source_id']);self.assertNotEqual(a['version_id'],b['version_id'])
        _,conflict=self.extract(f'# Conflict\nSession: {self.a}\nThread: {self.b}\nTask: {self.task}\nMain duty: Review\n')
        self.assertTrue(conflict['decision']['matches']['pending']);self.assertFalse(conflict['proposals'])
        _,unknown=self.extract('# Unknown\nThread: Identical title\nMain duty: Review\n')
        self.assertEqual(unknown['decision']['matches']['sessions'],[]);self.assertFalse(unknown['suggestions'][0]['actionable'])
        _,fresh=self.extract('# New stable\nThread: synthetic.other::A\nMain duty: Inspect\n')
        self.assertNotEqual(fresh['decision']['matches']['sessions'],[self.a])
        _,again=self.extract('# New stable second\nThread: synthetic.other::A\nResult: later\n')
        self.assertEqual(fresh['decision']['matches']['sessions'],again['decision']['matches']['sessions'])
        _,task=self.extract('# Numbered\nThread: synthetic.plan::A\nTask: T01\nResult: unknown task namespace\n')
        self.assertEqual(task['decision']['matches']['tasks'],[])
        self.assertEqual(self.get('threads')['current']['participation'],[])

    def test_native_real_parse_review_commit_suggest_confirm_and_reversal(self):
        self.stop();self.settings=replace(self.settings,model=None);self.start()
        _,d=self.extract();cs=self.candidates_for(d);self.assertEqual(len(d['suggestions']),3)
        self.assertEqual(self.get('threads')['history']['thread_duties'],[])
        duty=next(c for c in cs if c['operation']=='thread.duty.suggest');self.commit(duty,self.review(duty))
        state=self.get('threads');self.assertEqual(state['current']['duties'],[])
        suggested=state['current']['suggestions'][0];self.assertEqual(suggested['status'],'suggested')
        c=self.candidate('thread.duty.confirm',dict(suggestion_id=suggested['id'],basis='Human independently confirms'),target_id=self.a)
        self.commit(c,self.review(c));self.assertEqual(self.get('threads')['current']['duties'][0]['main'],'Review')
        history=self.get('history');change=next(v for v in history['applied_changes'] if v['candidate_id']==c['candidate_id'])
        preview=self.post('reversal-previews',dict(change_id=change['id']))
        revoke=self.candidate('change.revoke',dict(preview_id=preview['id']),target_id=change['id']);self.commit(revoke,self.review(revoke))
        self.assertEqual(self.get('threads')['current']['duties'],[])
        _,d=self.extract();cs=self.candidates_for(d)
        participation=next(c for c in cs if c['operation']=='task.participation.set');lead=next(c for c in cs if c['operation']=='task.lead.set')
        self.assertEqual(self.call(self.path('commits'),dict(request_key='illegal-lead-only',base_revision=self.revision(),selection=[dict(candidate_id=lead['candidate_id'],review_id=self.review(lead)['id'])]),key='illegal-lead-only')[0],409)
        rs=[self.review(c) for c in (participation,lead)];key=str(uuid4())
        body=dict(request_key=key,base_revision=self.revision(),selection=[dict(candidate_id=c['candidate_id'],review_id=r['id']) for c,r in zip((participation,lead),rs)])
        before=self.post('commits',body,key=key);self.assertEqual(self.post('commits',body,key=key),before)
        self.assertEqual(self.get('threads')['current']['leads'][0]['session_id'],self.a)
        self.assertEqual(self.get('threads')['historical_contributions']['task_sessions'],[])
        self.stop();self.start();self.assertEqual(self.get('threads')['current']['leads'][0]['session_id'],self.a)

    def test_correction_invalidates_review_and_preserves_applied_history(self):
        _,d=self.extract();duty=next(c for c in self.candidates_for(d) if c['operation']=='thread.duty.suggest');r=self.review(duty)
        fixed=self.correction(d);self.assertEqual(fixed['decision']['matches']['sessions'],[self.b])
        key=str(uuid4());body=dict(request_key=key,base_revision=self.revision(),selection=[dict(candidate_id=duty['candidate_id'],review_id=r['id'])])
        self.assertEqual(self.call(self.path('commits'),body,key=key)[0],409)
        self.assertEqual(self.get('threads')['current']['suggestions'],[])
        new=self.post('native/documents/'+d['id']+'/candidates',dict(base_revision=self.revision(),expected_decision_id=fixed['decision']['id']))
        c=next(c for c in self.get('candidates')['candidates'] if c['candidate_id'] in {v['candidate_id'] for v in new['candidates']} and c['operation']=='thread.duty.suggest')
        self.commit(c,self.review(c));self.assertEqual(self.get('threads')['current']['suggestions'][0]['session_id'],self.b)
        self.correction(fixed,self.a);self.assertEqual(self.get('threads')['current']['suggestions'][0]['session_id'],self.b)
        self.assertEqual(self.get('native/documents/'+d['id'])['locator'],d['locator'])

    def test_v2_captured_request_manifest_candidates_commit_and_old_protocol(self):
        batch,d=self.extract();b=self.prepare(batch)
        preview=self.get('model-batches/'+b['id']+'/preview');body=json.loads(preview['requests'][0]['body'])
        entries=json.loads(body['input'][1]['content'])['entries'];self.assertIn('thread-state',[e['kind'] for e in entries])
        for m,e in zip(b['manifest']['jobs'][0]['entries'],entries):self.assertEqual(m['sha256'],e['sha256']);self.assertEqual(m['utf8_bytes'],len(e['text'].encode()))
        self.sup.behavior=lambda p,i:self.response(p,[self.proposal(p)])
        self.approve(b);result=self.execute(b);self.assertEqual(result['jobs'][0]['state'],'saved')
        self.assertEqual(self.sup.requests[0]['body'],preview['requests'][0]['body'].encode())
        cid=result['jobs'][0]['events'][-1]['metadata_json'];cid=json.loads(cid)['candidate_ids'][0]
        c=self.get('candidates/'+cid);self.assertEqual(c['risk'],'high');self.assertEqual(self.get('threads')['current']['suggestions'],[])
        self.commit(c,self.review(c));self.assertEqual(self.get('threads')['current']['suggestions'][0]['main'],'Model review')
        self.sup.behavior=None
        old=self.post('model-batches',dict(import_batch_id=batch['id']));self.assertEqual(old['manifest']['protocol'],'nextrelay.model/1')
        self.approve(old);self.assertEqual(self.execute(old)['jobs'][0]['state'],'saved')
        self.assertEqual(self.execute(old)['jobs'][0]['state'],'saved');self.assertEqual(len(self.sup.requests),2)

    def test_stale_prepare_approve_send_response_review_commit_stages(self):
        batch,d=self.extract();b=self.prepare(batch);self.correction(d)
        self.assertEqual(self.call(self.path('model-batches/'+b['id']+'/decision'),dict(fingerprint=b['fingerprint'],decision='approved'))[0],409)
        b=self.prepare(batch);self.approve(b);d=self.get('native/documents/'+d['id']);self.correction(d,self.a)
        self.assertEqual(self.call(self.path('model-batches/'+b['id']+'/execute'),{})[0],409);self.assertEqual(self.sup.requests,[])
        b=self.prepare(batch);self.approve(b)
        def changed(p,i):
            with unit_of_work(self.db,Principal(self.settings.subject),write=True) as s:
                n=Native(s);doc=n.document(self.pid,d['id']);n.correct(self.pid,d['id'],dict(base_revision=s.project(self.pid)['revision'],expected_decision_id=doc['decision']['id'],matches=dict(tasks=[self.task],sessions=[self.b],attempts=[]),basis='Concurrent synthetic correction'))
            return self.response(p,[self.proposal(p)])
        self.sup.behavior=changed
        result=self.execute(b);self.assertEqual(result['jobs'][0]['state'],'invalid');self.assertTrue(result['stale']);self.assertEqual(len(self.sup.requests),1)
        self.assertEqual(self.execute(b)['jobs'][0]['state'],'invalid');self.assertEqual(len(self.sup.requests),1)
        self.sup.behavior=lambda p,i:self.response(p,[self.proposal(p,target=self.b)])
        b=self.prepare(batch);self.approve(b);result=self.execute(b);self.assertEqual(result['jobs'][0]['state'],'saved')
        cid=json.loads(result['jobs'][0]['events'][-1]['metadata_json'])['candidate_ids'][0];c=self.get('candidates/'+cid);r=self.review(c)
        doc=self.get('native/documents/'+d['id']);self.correction(doc,self.a)
        key=str(uuid4());self.assertEqual(self.call(self.path('commits'),dict(request_key=key,base_revision=self.revision(),selection=[dict(candidate_id=cid,review_id=r['id'])]),key=key)[0],409)
        self.assertEqual(self.get('threads')['current']['suggestions'],[])

    def test_formal_revision_and_nonrevision_new_suggestions_invalidate(self):
        batch,d=self.extract();b=self.prepare(batch);self.approve(b)
        c=self.candidate('thread.duty.set',dict(main='Human direct',basis='Synthetic direct assignment'),target_id=self.a);self.commit(c,self.review(c))
        self.assertEqual(self.call(self.path('model-batches/'+b['id']+'/execute'),{})[0],409)
        b=self.prepare(batch);self.approve(b);revision=self.revision()
        self.extract(f'# New source\nThread: {self.a}\nMain duty: Changed informal\n')
        self.assertEqual(self.revision(),revision);self.assertEqual(self.call(self.path('model-batches/'+b['id']+'/execute'),{})[0],409)
        self.assertEqual(self.sup.requests,[])

    def test_v2_invalid_version_object_unicode_and_fake_approval_atomic(self):
        batch,d=self.extract()
        variants=[lambda p:[dict(self.proposal(p),target_id=self.task)],
            lambda p:[dict(self.proposal(p),approved=True)],lambda p:[self.proposal(p,body=dict(main='Bad\ud800',auxiliary=[],basis='Synthetic'))],
            lambda p:[self.proposal(p,'thread.duty.confirm',body=dict(suggestion_id=d['id'],basis='Synthetic'))],
            lambda p:[self.proposal(p,'task.lead.set',self.task,dict(thread_id=self.a,basis='No current participant'))],
            lambda p:[self.proposal(p),dict(self.proposal(p),target_id='missing')]]
        for variant in variants:
            with self.subTest(variant=repr(variant)):
                before=len(self.get('candidates')['candidates']);b=self.prepare(batch);self.approve(b)
                self.sup.behavior=lambda p,i:self.response(p,variant(p))
                r=self.execute(b);self.assertEqual(r['jobs'][0]['state'],'invalid');self.assertEqual(len(self.get('candidates')['candidates']),before)
        b=self.prepare(batch);self.approve(b);self.sup.behavior=lambda p,i:self.response(p,[],protocol='nextrelay.model/999')
        self.assertEqual(self.execute(b)['jobs'][0]['state'],'invalid')
        self.assertEqual(self.call(self.path('model-batches'),dict(import_batch_id=batch['id'],protocol='nextrelay.model/999'))[0],409)

    def test_concurrent_execution_and_unknown_never_resend(self):
        batch,d=self.extract();b=self.prepare(batch);self.approve(b)
        self.sup.behavior=lambda p,i:self.response(p,[self.proposal(p)])
        with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:self.execute(b),range(2)))
        self.assertEqual(len(self.sup.requests),1)
        b=self.prepare(batch);self.approve(b);self.sup.behavior=lambda p,i:None
        r=self.execute(b);self.assertEqual(r['jobs'][0]['state'],'unknown')
        self.execute(b);self.assertEqual(len(self.sup.requests),2)
        self.stop();self.start();self.execute(b);self.assertEqual(len(self.sup.requests),2)

    def test_same_bytes_sources_replay_and_historical_duty_not_backfilled(self):
        text=f'# Repeated\nThread: {self.a}\nTask: {self.task}\nResult: historic contribution\n'
        batch,d=self.extract(text);_,other=self.extract(text)
        self.assertEqual(d['version_id'],other['version_id']);self.assertNotEqual(d['locator']['source_id'],other['locator']['source_id'])
        c=next(c for c in self.candidates_for(d) if c['operation']=='version.confirm');self.commit(c,self.review(c))
        rows=self.get('threads')['historical_contributions']['task_sessions'];self.assertIsNone(rows[0]['duty_version_id'])
        c=self.candidate('thread.duty.set',dict(main='Current duty',basis='Synthetic now'),target_id=self.a);self.commit(c,self.review(c))
        self.assertIsNone(self.get('threads')['historical_contributions']['task_sessions'][0]['duty_version_id'])
        self.assertEqual(self.get('threads')['current']['participation'],[])
        _,repeat=self.extract(text);self.assertFalse(repeat['proposals'])


    def test_new_risk_invalidates_native_approval_and_keeps_all_sources(self):
        _,d=self.extract();c=next(c for c in self.candidates_for(d) if c['operation']=='thread.duty.suggest');r=self.review(c)
        _,risk=self.extract(f'# Additional evidence\nThread: {self.a}\nTask: {self.task}\nRisk: Contradicting ownership evidence\nMain duty: Review\n')
        key=str(uuid4());status,value=self.call(self.path('commits'),dict(request_key=key,base_revision=self.revision(),selection=[dict(candidate_id=c['candidate_id'],review_id=r['id'])]),key=key)
        self.assertEqual(status,409,value);self.assertEqual(self.get('threads')['current']['suggestions'],[])
        self.assertNotEqual(risk['locator']['source_id'],d['locator']['source_id'])
        new=next(c for c in self.candidates_for(risk) if c['operation']=='thread.duty.suggest');self.assertEqual(new['risk'],'conflict')
        self.assertIn('risk: Contradicting ownership evidence',new['spec']['conflicts'])

    def test_preparation_and_approval_recheck_after_preview_race(self):
        batch,d=self.extract();service=ModelService
        gather=service._gather
        def mutate(obj,project,selection):
            value=gather(obj,project,selection)
            with unit_of_work(self.db,Principal(self.settings.subject),write=True) as s:
                n=Native(s);doc=n.document(self.pid,d['id']);n.correct(self.pid,d['id'],dict(base_revision=s.project(self.pid)['revision'],expected_decision_id=doc['decision']['id'],matches=dict(tasks=[self.task],sessions=[self.b],attempts=[]),basis='Synthetic after gather race'))
            return value
        with patch.object(service,'_gather',mutate):self.assertEqual(self.call(self.path('model-batches'),dict(import_batch_id=batch['id'],protocol=PROTOCOL_V2))[0],409)
        b=self.prepare(batch);preview=service.preview
        def mutate_preview(obj,project,identity):
            value=preview(obj,project,identity)
            doc=self.get('native/documents/'+d['id']);self.correction(doc,self.a)
            return value
        with patch.object(service,'preview',mutate_preview):self.assertEqual(self.call(self.path('model-batches/'+b['id']+'/decision'),dict(fingerprint=b['fingerprint'],decision='approved'))[0],409)
        self.assertEqual(self.sup.requests,[])

    def test_cross_project_reference_and_old_duty_cannot_follow_correction(self):
        _,d=self.extract();c=self.candidate('thread.duty.set',dict(main='Historical',basis='Synthetic explicit'),target_id=self.a);self.commit(c,self.review(c))
        duty=self.get('threads')['current']['duties'][0]['id'];d=self.get('native/documents/'+d['id'])
        body=dict(base_revision=self.revision(),expected_decision_id=d['decision']['id'],matches=dict(tasks=[self.task],threads=[self.b],attempts=[],contributions=[dict(task_id=self.task,thread_id=self.b,attempt_id=None,duty_version_id=duty)]),basis='Wrong history')
        self.assertEqual(self.call(self.path('native/documents/'+d['id']+'/correct'),body)[0],409)
        foreign=self.call(self.path('threads',self.other),dict(title='Other project'))[1]['id']
        body['matches']=dict(tasks=[self.task],threads=[foreign],attempts=[])
        self.assertEqual(self.call(self.path('native/documents/'+d['id']+'/correct'),body)[0],404)
        body['matches']=dict(tasks=[self.task],sessions=[self.a],threads=[self.b],attempts=[])
        self.assertEqual(self.call(self.path('native/documents/'+d['id']+'/correct'),body)[0],409)
        self.assertEqual(self.get('native/documents/'+d['id'])['decision']['id'],d['decision']['id'])
        batch,_=self.extract();b=self.prepare(batch);self.approve(b);self.sup.behavior=lambda p,i:self.response(p,[self.proposal(p,target=foreign)])
        self.assertEqual(self.execute(b)['jobs'][0]['state'],'invalid')

    def test_input_replacement_and_unknown_attempt_are_not_skipped(self):
        batch,d=self.extract(f'# History\nThread: {self.a}\nTask: {self.task}\nResult: unknown round\n')
        a=self.post('attempts',dict(task_id=self.task,title='First round'))['id'];b=self.post('attempts',dict(task_id=self.task,title='Second round'))['id']
        self.assertEqual(d['decision']['matches']['attempts'],[])
        failed=self.upload([self.file('broken.json',b'{}')]);item=failed['items'][0]['id'];old_input=failed['items'][0]['current_input_id'];text=f'# Changed\nThread: {self.a}\nTask: {self.task}\nAttempt: {b}\nMain duty: New input\n'
        self.post('items/'+item+'/retry',dict(replacement=self.file('changed.md',text.encode())))
        new=self.post('items/'+item+'/extract',dict(base_revision=self.revision()))['documents'][0]
        self.assertNotEqual(self.get('items/'+item)['current_input_id'],old_input)
        self.assertEqual(self.get('native/documents/'+d['id'])['version_id'],d['version_id'])
        self.assertNotEqual(new['id'],d['id']);self.assertEqual(new['decision']['matches']['attempts'],[b]);self.assertNotIn(a,new['decision']['matches']['attempts'])
        self.assertEqual(self.post('items/'+item+'/extract',dict(base_revision=self.revision()))['documents'][0],new)


    def test_existing_formal_duty_includes_precise_source_provenance(self):
        batch,d=self.extract();c=next(c for c in self.candidates_for(d) if c['operation']=='thread.duty.suggest');self.commit(c,self.review(c))
        suggestion=self.get('threads')['current']['suggestions'][0]['id']
        confirm=self.candidate('thread.duty.confirm',dict(suggestion_id=suggestion,basis='Synthetic confirms sourced version'),target_id=self.a);self.commit(confirm,self.review(confirm))
        imported,_=self.extract(f'# Follow-up\nThread: {self.a}\nResult: later independent material\n')
        b=self.prepare(imported);preview=self.get('model-batches/'+b['id']+'/preview')
        entries=json.loads(json.loads(preview['requests'][0]['body'])['input'][1]['content'])['entries']
        provenance=next(e for e in entries if e['kind']=='thread-provenance' and 'version_id' in json.loads(e['text']))
        self.assertEqual(json.loads(provenance['text'])['version_id'],d['version_id'])
        sources=[json.loads(e['text'])['source'] for e in entries if e['kind']=='thread-source']
        self.assertIn(d['locator']['source_id'],[s['id'] for s in sources]);self.assertTrue(sources[0]['fingerprint'])
        self.sup.behavior=lambda p,i:self.response(p,[self.proposal(p,body=dict(main='Review',auxiliary=['Test','Explain'],basis='Repeated source with another explanation'))])
        self.approve(b);self.assertEqual(self.execute(b)['jobs'][0]['state'],'invalid')
        self.assertEqual(len(self.get('threads')['current']['suggestions']),0)
        self.assertEqual(len(self.get('threads')['current']['duties']),1)
