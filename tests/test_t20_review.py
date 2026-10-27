"""Regressions for independent T20 findings, all through actual local HTTP."""
import json
import unittest
from uuid import uuid4
import test_t20 as t20
from model_support import proposal


class ReviewedT20HTTPTests(unittest.TestCase):
    for name,value in t20.T20HTTPTests.__dict__.items():
        if not name.startswith('__') and not name.startswith('test_'):locals()[name]=value

    def selected_commit(self,c,r):
        key=str(uuid4())
        return self.call(self.path('commits'),dict(request_key=key,base_revision=self.revision(),
            selection=[dict(candidate_id=c['candidate_id'],review_id=r['id'])]),key=key)

    def test_no_task_different_title_new_thread_risk_invalidates_old_approval(self):
        _,d=self.extract(f'# Long term duty\nThread: {self.a}\nMain duty: Review\n')
        c=next(c for c in self.candidates_for(d) if c['operation']=='thread.duty.suggest');r=self.review(c);revision=self.revision()
        _,risk=self.extract(f'# Independent differently titled report\nThread: {self.a}\nMain duty: Review\nRisk: This duty assignment has conflicting authorization\n')
        self.assertEqual(self.revision(),revision);self.assertEqual(self.selected_commit(c,r)[0],409)
        self.assertEqual(self.get('threads')['current']['suggestions'],[])
        fresh=next(c for c in self.candidates_for(risk) if c['operation']=='thread.duty.suggest')
        self.assertEqual(fresh['risk'],'conflict');self.assertIn('risk: This duty assignment has conflicting authorization',fresh['spec']['conflicts'])

    def test_suggested_to_confirm_retains_sources_and_dynamic_risk(self):
        _,d=self.extract(f'# Original responsibility\nThread: {self.a}\nTask: {self.task}\nMain duty: Review\n')
        c=next(c for c in self.candidates_for(d) if c['operation']=='thread.duty.suggest');self.commit(c,self.review(c))
        sid=self.get('threads')['current']['suggestions'][0]['id']
        old=self.candidate('thread.duty.confirm',dict(suggestion_id=sid,basis='Independent confirmation'),target_id=self.a);r=self.review(old)
        self.assertIn(d['locator']['source_id'],old['spec']['source_ids']);revision=self.revision()
        _,risk=self.extract(f'# New report\nThread: {self.a}\nTask: {self.task}\nMain duty: Review\nRisk: Ownership is contested\n')
        self.assertEqual(self.revision(),revision);self.assertEqual(self.selected_commit(old,r)[0],409)
        self.assertEqual(self.get('threads')['current']['duties'],[])
        self.assertEqual(self.call(self.path('reviews'),dict(selection=[dict(candidate_id=old['candidate_id'],fingerprint=old['fingerprint'])],decision='approve',mode='ordinary',basis='Old ordinary approval must fail',input_origin='synthetic-test'))[0],409)
        fresh=self.candidate('thread.duty.confirm',dict(suggestion_id=sid,basis='Fresh independent risk review'),target_id=self.a)
        self.assertEqual(fresh['risk'],'conflict');self.assertIn('risk: Ownership is contested',fresh['spec']['conflicts'])
        self.assertEqual(set(fresh['spec']['source_ids']),{d['locator']['source_id'],risk['locator']['source_id']})
        self.commit(fresh,self.review(fresh));self.assertEqual(self.get('threads')['current']['duties'][0]['status'],'confirmed')

    def test_explicit_historical_duty_commit_and_no_unknown_backfill(self):
        c=self.candidate('thread.duty.set',dict(main='Historical explicit',basis='Synthetic historical version'),target_id=self.a);self.commit(c,self.review(c))
        duty=self.get('threads')['current']['duties'][0]['id']
        _,d=self.extract(f'# Historical work\nThread: {self.a}\nTask: {self.task}\nResult: historic sourced work\n')
        fixed=self.post('native/documents/'+d['id']+'/correct',dict(base_revision=self.revision(),expected_decision_id=d['decision']['id'],
            matches=dict(tasks=[self.task],threads=[self.a],attempts=[],contributions=[dict(task_id=self.task,thread_id=self.a,attempt_id=None,duty_version_id=duty)]),basis='Explicit historical duty, no time inference'))
        self.post('native/documents/'+d['id']+'/candidates',dict(base_revision=self.revision(),expected_decision_id=fixed['decision']['id']))
        c=next(c for c in self.candidates_for(self.get('native/documents/'+d['id'])) if c['operation']=='version.confirm' and c['spec']['native_context']['decision_id']==fixed['decision']['id'])
        review=self.review(c);result,body=self.commit(c,review);self.assertEqual(self.post('commits',body,key=body['request_key']),result)
        state=self.get('threads');self.assertEqual(state['historical_contributions']['task_sessions'][0]['duty_version_id'],duty)
        source=self.get('sources/'+d['locator']['source_id'])['attribution']
        binding=next(r for r in state['history']['contribution_duties'] if r['relation_key']=='source:'+source['id'])
        self.assertEqual(binding['duty_id'],duty)
        self.stop();self.start();self.assertEqual(self.get('threads'),state)

    def test_bad_duty_version_types_rejected_before_storage(self):
        _,d=self.extract();revision=self.revision()
        for bad in ([],{},[1],{'id':'fake'},True,17):
            body=dict(base_revision=revision,expected_decision_id=d['decision']['id'],matches=dict(tasks=[self.task],threads=[self.a],attempts=[],
                contributions=[dict(task_id=self.task,thread_id=self.a,attempt_id=None,duty_version_id=bad)]),basis='Invalid type probe')
            self.assertEqual(self.call(self.path('native/documents/'+d['id']+'/correct'),body)[0],409)
        self.assertEqual(self.revision(),revision);self.assertEqual(self.get('native/documents/'+d['id'])['decision']['id'],d['decision']['id'])

    def test_different_manifests_keep_independent_model_risks_and_sources(self):
        for v2 in (True,False):
            with self.subTest(protocol=2 if v2 else 1):
                a,da=self.extract(f'# Source A {v2}\nThread: {self.a}\nMain duty: Review\n')
                b,db=self.extract(f'# Source B {v2}\nThread: {self.a}\nMain duty: Review\n')
                results=[]
                for batch,risk in ((a,'source A concern'),(b,'source B concern')):
                    model=self.prepare(batch) if v2 else self.post('model-batches',dict(import_batch_id=batch['id']))
                    self.approve(model)
                    def response(p,i):
                        c=self.proposal(p) if v2 else proposal(p,title='Same legacy decision')['candidates'][0]
                        c['risks']=[risk]
                        return self.response(p,[c],protocol='nextrelay.model/2' if v2 else 'nextrelay.model/1')
                    self.sup.behavior=response;r=self.execute(model);self.assertEqual(r['jobs'][0]['state'],'saved')
                    cid=json.loads(r['jobs'][0]['events'][-1]['metadata_json'])['candidate_ids'][0];c=self.get('candidates/'+cid)
                    results.append(c)
                    if len(results)==1:self.review(c)
                old=self.get('candidates/'+results[0]['candidate_id']);new=results[1]
                self.assertEqual(old['processing'],'approve');self.assertNotEqual(old['candidate_id'],new['candidate_id'])
                self.assertIn('source A concern',old['spec']['conflicts']);self.assertIn('source B concern',new['spec']['conflicts'])
                self.assertEqual(old['spec']['source_ids'],[da['locator']['source_id']]);self.assertEqual(new['spec']['source_ids'],[db['locator']['source_id']])

    def test_model_confirmation_keeps_original_source_and_rejects_correction(self):
        batch,d=self.extract();c=next(c for c in self.candidates_for(d) if c['operation']=='thread.duty.suggest');self.commit(c,self.review(c))
        sid=self.get('threads')['current']['suggestions'][0]['id']
        incoming,_=self.extract(f'# Confirm request\nThread: {self.a}\nResult: related sourced follow-up\n')
        b=self.prepare(incoming);self.approve(b)
        self.sup.behavior=lambda p,i:self.response(p,[self.proposal(p,'thread.duty.confirm',body=dict(suggestion_id=sid,basis='Model proposes independent confirmation'))])
        r=self.execute(b);self.assertEqual(r['jobs'][0]['state'],'saved')
        cid=json.loads(r['jobs'][0]['events'][-1]['metadata_json'])['candidate_ids'][0];c=self.get('candidates/'+cid)
        self.assertIn(d['locator']['source_id'],c['spec']['source_ids']);self.assertEqual(c['risk'],'high')
        self.correction(d,self.b)
        self.assertEqual(self.call(self.path('candidates'),dict(base_revision=self.revision(),operation='thread.duty.confirm',target_id=self.a,payload=dict(suggestion_id=sid,basis='Old source corrected')))[0],409)


    def test_no_task_conflicting_duty_declaration_invalidates_old_approval(self):
        _,d=self.extract(f'# First duty\nThread: {self.a}\nMain duty: Review\n')
        c=next(c for c in self.candidates_for(d) if c['operation']=='thread.duty.suggest');r=self.review(c)
        self.extract(f'# Conflicting independent duty\nThread: {self.a}\nMain duty: Implement\n')
        self.assertEqual(self.selected_commit(c,r)[0],409)
        self.assertEqual(self.get('threads')['current']['suggestions'],[])


    def model_only_suggestion(self,text=None):
        text=text or f'# Raw model source\nThread: {self.a}\nMain duty: Model review\n'
        imported=self.upload([self.file('model-only.md',text.encode())])
        model=self.prepare(imported,thread_ids=[self.a]);preview=self.get('model-batches/'+model['id']+'/preview')
        self.assertFalse(any(e['kind']=='native' for e in model['manifest']['jobs'][0]['entries']))
        self.approve(model);self.sup.behavior=lambda p,i:self.response(p,[self.proposal(p)])
        result=self.execute(model);self.assertEqual(result['jobs'][0]['state'],'saved')
        self.assertEqual(self.sup.requests[-1]['body'],preview['requests'][0]['body'].encode())
        cid=json.loads(result['jobs'][0]['events'][-1]['metadata_json'])['candidate_ids'][0]
        candidate=self.get('candidates/'+cid);self.commit(candidate,self.review(candidate))
        suggestion=self.get('threads')['current']['suggestions'][0]['id']
        return imported,candidate,suggestion

    def test_model_without_native_entries_confirm_tracks_later_thread_risk(self):
        imported,c,sid=self.model_only_suggestion()
        old=self.candidate('thread.duty.confirm',dict(suggestion_id=sid,basis='Independent confirm before risk'),target_id=self.a);review=self.review(old)
        _,unrelated=self.extract(f'# Different Thread risk\nThread: {self.b}\nRisk: Separate evidence\n')
        still_current=self.candidate('thread.duty.confirm',dict(suggestion_id=sid,basis='Still no related risk'),target_id=self.a)
        self.assertEqual(still_current['spec']['conflicts'],[])
        revision=self.revision()
        _,risk=self.extract(f'# Later Thread risk with unknown Task\nThread: {self.a}\nTask: T01\nMain duty: Model review\nRisk: Ownership challenged\n')
        self.assertTrue(risk['decision']['matches']['pending'])
        self.assertEqual(self.revision(),revision);self.assertEqual(self.selected_commit(old,review)[0],409)
        self.assertEqual(self.get('threads')['current']['duties'],[])
        fresh=self.candidate('thread.duty.confirm',dict(suggestion_id=sid,basis='Review current related evidence'),target_id=self.a)
        self.assertEqual(fresh['risk'],'conflict');self.assertIn('risk: Ownership challenged',fresh['spec']['conflicts'])
        self.assertEqual(set(fresh['spec']['source_ids']),set(c['spec']['source_ids'])|{risk['locator']['source_id']})
        self.assertNotIn(unrelated['locator']['source_id'],fresh['spec']['source_ids'])
        self.commit(fresh,self.review(fresh));self.assertEqual(self.get('threads')['current']['duties'][0]['status'],'confirmed')

    def test_model_without_native_entries_model_confirm_inherits_later_risk(self):
        imported,c,sid=self.model_only_suggestion()
        _,risk=self.extract(f'# New risk source\nThread: {self.a}\nMain duty: Model review\nRisk: Confirm ownership before assignment\n')
        model=self.prepare(imported,thread_ids=[self.a]);self.approve(model)
        self.sup.behavior=lambda p,i:self.response(p,[self.proposal(p,'thread.duty.confirm',body=dict(suggestion_id=sid,basis='Unverified model confirmation proposal'))])
        result=self.execute(model);self.assertEqual(result['jobs'][0]['state'],'saved')
        cid=json.loads(result['jobs'][0]['events'][-1]['metadata_json'])['candidate_ids'][0];confirm=self.get('candidates/'+cid)
        self.assertEqual(confirm['risk'],'conflict');self.assertIn('risk: Confirm ownership before assignment',confirm['spec']['conflicts'])
        self.assertEqual(set(confirm['spec']['source_ids']),set(c['spec']['source_ids'])|{risk['locator']['source_id']})
        self.assertEqual(self.get('threads')['current']['duties'],[])
        self.commit(confirm,self.review(confirm));self.assertEqual(self.get('threads')['current']['duties'][0]['session_id'],self.a)

    def test_model_only_original_source_later_corrected_invalidates_confirmation(self):
        imported,c,sid=self.model_only_suggestion()
        old=self.candidate('thread.duty.confirm',dict(suggestion_id=sid,basis='Original source before extraction'),target_id=self.a);review=self.review(old)
        doc=self.post('items/'+imported['items'][0]['id']+'/extract',dict(base_revision=self.revision()))['documents'][0]
        self.assertEqual(self.selected_commit(old,review)[0],409)
        fresh=self.candidate('thread.duty.confirm',dict(suggestion_id=sid,basis='Reviewed extracted original source'),target_id=self.a);review=self.review(fresh)
        self.correction(doc,self.b)
        self.assertEqual(self.selected_commit(fresh,review)[0],409)
        status,_=self.call(self.path('candidates'),dict(base_revision=self.revision(),operation='thread.duty.confirm',target_id=self.a,payload=dict(suggestion_id=sid,basis='Corrected source cannot confirm old target')))
        self.assertEqual(status,409);self.assertEqual(self.get('threads')['current']['duties'],[])
        self.assertEqual(self.get('threads')['current']['suggestions'][0]['session_id'],self.a)

    def test_model_only_confirmation_preserves_duplicate_and_multi_thread_sources(self):
        text=f'# Thread A source\nThread: {self.a}\nMain duty: Model review\n\n# Thread B source\nThread: {self.b}\nMain duty: Other duty\n'
        imported,c,sid=self.model_only_suggestion(text)
        self.post('items/'+imported['items'][0]['id']+'/extract',dict(base_revision=self.revision()))
        confirm=self.candidate('thread.duty.confirm',dict(suggestion_id=sid,basis='Multi-document source with both identities'),target_id=self.a);review=self.review(confirm)
        self.extract(f'# Independent duplicate without risk\nThread: {self.a}\nMain duty: Model review\n')
        self.assertEqual(self.selected_commit(confirm,review)[0],200)
        self.assertEqual([r['session_id'] for r in self.get('threads')['current']['duties']],[self.a])


    def check_manual_version_thread_risk(self,unresolved):
        declaration='Task: T777' if unresolved=='task' else f'Task: {self.task}'
        if unresolved=='attempt':declaration+='\nAttempt: unknown-round'
        _,doc=self.extract(f'# Original manual version\nThread: {self.a}\n{declaration}\nResult: sourced historical work\n')
        matches=doc['decision']['matches'];self.assertEqual(matches['sessions'],[self.a])
        self.assertEqual(bool(matches['pending']),unresolved is not None)
        request=dict(target_id=self.task,target_version_id=doc['version_id'],source_ids=[doc['locator']['source_id']])
        old=self.candidate('version.confirm',{},**request);self.assertNotIn('native_context',old['spec']);self.assertEqual(old['risk'],'ordinary')
        review=self.review(old);revision=self.revision()
        self.extract(f'# Independent ownership risk\nThread: {self.a}\nRisk: This source ownership is disputed\n')
        self.assertEqual(self.revision(),revision)
        fresh=self.candidate('version.confirm',{},**request)
        self.assertEqual(fresh['risk'],'conflict');self.assertIn('risk: This source ownership is disputed',fresh['spec']['conflicts'])
        self.assertEqual(self.selected_commit(old,review)[0],409);self.assertEqual(self.get('formal')['confirmed_versions'],[])
        self.assertEqual(self.call(self.path('reviews'),dict(selection=[dict(candidate_id=fresh['candidate_id'],fingerprint=fresh['fingerprint'])],
            decision='approve',mode='ordinary',basis='Must not bypass source risk',input_origin='synthetic-test'))[0],409)
        self.commit(fresh,self.review(fresh))
        self.assertEqual(self.get('formal')['confirmed_versions'][0]['version_id'],doc['version_id'])
        self.assertEqual(self.get('native/documents/'+doc['id'])['decision']['matches'],matches)
        state=self.get('threads');self.assertEqual(state['historical_contributions']['task_sessions'],[])
        self.assertEqual(state['current']['participation'],[]);self.assertEqual(self.get('formal')['acceptances'],[])

    def test_manual_version_confirmation_unknown_task_retains_thread_risk(self):
        self.check_manual_version_thread_risk('task')

    def test_manual_version_confirmation_unknown_attempt_retains_thread_risk(self):
        self.check_manual_version_thread_risk('attempt')

    def test_manual_version_confirmation_resolved_control_retains_thread_risk(self):
        self.check_manual_version_thread_risk(None)
