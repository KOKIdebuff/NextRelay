"""T19 real SQLite services, independent connections, and atomic compensation."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import threading
from unittest.mock import patch
from uuid import uuid4

from test_reversals import ReversalJourney
from test_lifecycle import BASIS
from nextrelay.auth import AccessError
from nextrelay.changes import ChangeError, Changes
from nextrelay.db import connect
from nextrelay.store import Store, TransactionAborted


class ThreadJourney(ReversalJourney):
    def setUp(self):
        super().setUp()
        self.t,self.v,self.artifact=self.task('Thread collaboration task')
        with self.work() as s:
            self.a=s.create_session(self.p,'Same title',namespace='synthetic',external_id='A')['id']
            self.b=s.create_session(self.p,'Same title',namespace='synthetic',external_id='B')['id']
            self.c=s.create_session(self.p,'Third')['id']
            self.foreign=s.create_session(self.q,'Foreign')['id']

    def duty(self,thread=None,main='Implementation'):
        return self.effect('thread.duty.set',thread or self.a,payload=dict(main=main,auxiliary=['Review'],basis=BASIS))

    def participate(self,thread=None,active=True,description='Implementation'):
        return self.effect('task.participation.set',self.t,payload=dict(thread_id=thread or self.a,active=active,description=description,basis=BASIS))

    def lead(self,thread):
        return self.effect('task.lead.set',self.t,payload=dict(thread_id=thread,basis=BASIS))

    def succession(self,a,b,active=True):
        return self.effect('thread.succession.set',a,payload=dict(successor_id=b,active=active,basis=BASIS))

    def threads(self):
        with self.work(False) as s:return s.thread_state(self.p)

    def batch(self,*candidates):
        reviews=[self.approve(c) for c in candidates]
        with self.work() as s:
            return s.commit_candidates(self.p,dict(request_key=str(uuid4()),base_revision=candidates[0]['spec']['base_revision'],
                selection=[dict(candidate_id=c['candidate_id'],review_id=r['id']) for c,r in zip(candidates,reviews)]))

    def snapshot(self):
        with connect(self.db) as c:
            return {r[0]:[tuple(v) for v in c.execute(f'SELECT * FROM {r[0]} ORDER BY rowid')]
                    for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table'")}

    def behavior(self, task):
        return {k:v for k,v in self.value(task).items() if k!='revision'}


class ThreadTests(ThreadJourney):
    def test_shared_participation_no_lead_and_exit_preserves_work_and_acceptance(self):
        with self.work() as s:
            attempt=s.create_attempt(self.p,self.t,'Historical')['id']
            s.link_attempt_session(self.p,attempt,self.a)
        self.assertEqual(self.threads()['current']['participation'],[])
        self.submit(self.t,self.v);self.human(self.t,self.v)
        before=self.behavior(self.t)
        self.participate();self.participate(self.b)
        self.assertEqual(len(self.threads()['current']['participation']),2)
        self.assertEqual(self.threads()['current']['leads'],[])
        self.participate(active=False)
        self.assertEqual(len(self.threads()['historical_contributions']['attempt_sessions']),1)
        self.assertEqual(self.behavior(self.t),before)

    def test_lead_requires_participant_and_cross_project_rejected(self):
        c=self.save('task.lead.set',self.t,payload=dict(thread_id=self.a,basis=BASIS));r=self.approve(c)
        with self.assertRaisesRegex(ChangeError,'lead_requires_current_participant'):self.commit(c,r)
        with self.assertRaises(AccessError):self.lead(self.foreign)
        self.participate();self.participate(self.b);self.lead(self.a);self.lead(self.b);self.lead(None)
        self.assertIsNone(self.threads()['current']['leads'][0]['session_id'])

    def test_lead_exit_requires_explicit_same_transaction_clear_or_reassign(self):
        self.participate();self.lead(self.a)
        exit=self.save('task.participation.set',self.t,payload=dict(thread_id=self.a,active=False,basis=BASIS))
        review=self.approve(exit);before=self.snapshot()
        with self.assertRaisesRegex(ChangeError,'lead_exit_requires_explicit'):self.commit(exit,review)
        self.assertEqual(self.snapshot(),before)
        add=self.save('task.participation.set',self.t,payload=dict(thread_id=self.b,active=True,basis=BASIS))
        lead=self.save('task.lead.set',self.t,payload=dict(thread_id=self.b,basis=BASIS))
        result=self.batch(exit,lead,add)
        self.assertEqual(len(result['changes']),3)
        self.assertEqual(self.threads()['current']['leads'][0]['session_id'],self.b)
        exit=self.save('task.participation.set',self.t,payload=dict(thread_id=self.b,active=False,basis=BASIS))
        clear=self.save('task.lead.set',self.t,payload=dict(thread_id=None,basis=BASIS));self.batch(clear,exit)
        self.assertIsNone(self.threads()['current']['leads'][0]['session_id'])

    def test_duty_suggestion_confirmation_reject_defer_history_and_versions(self):
        for decision in ('reject','defer'):
            c=self.save('thread.duty.set',self.a,payload=dict(main='Claim: approved',basis=BASIS))
            with self.work() as s:
                s.review_candidates(self.p,dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint'])],decision=decision,mode='ordinary',basis=BASIS,input_origin='synthetic-test'))
            self.assertEqual(self.threads()['current']['duties'],[])
            with self.assertRaises(ChangeError):self.commit(c,dict(id=c['latest_review_id']))
        with self.work() as s:
            s.link_task_session(self.p,self.t,self.a)
        suggestion=self.effect('thread.duty.suggest',self.a,payload=dict(main='Suggested',auxiliary=['Assist'],basis=BASIS))
        self.assertEqual(self.threads()['current']['duties'],[])
        row=self.threads()['history']['thread_duties'][0]
        confirmation=self.effect('thread.duty.confirm',self.a,payload=dict(suggestion_id=row['id'],basis=BASIS))
        duty=self.threads()['current']['duties'][0]
        with self.work() as s:
            attempt=s.create_attempt(self.p,self.t,'After confirmation')['id'];s.link_attempt_session(self.p,attempt,self.a,duty_version_id=duty['id'])
            source=s.create_source(self.p,reference='synthetic://duty')['id']
            old=s.attribution(self.p,source)
            s.attribute_source(self.p,source,task_id=self.t,session_id=self.a,attempt_id=attempt,supersedes_id=old['id'],reason=BASIS,duty_version_id=duty['id'])
        self.duty(main='Changed')
        facts=self.threads()['historical_contributions']
        self.assertIsNone(facts['task_sessions'][0]['duty_version_id'])
        self.assertEqual(facts['attempt_sessions'][0]['duty_version_id'],duty['id'])
        self.assertIn(duty['id'],[r['duty_version_id'] for r in facts['source_attributions']])
        with self.assertRaisesRegex(ChangeError,'unsafe_independent_reversal'):
            c,_,_=self.reversal(suggestion)
        self.assertEqual(len(self.threads()['history']['thread_duties']),3)

    def test_clear_duty_and_unknown_has_no_authority(self):
        self.duty()
        self.effect('thread.duty.set',self.a,payload=dict(main=None,basis=BASIS))
        self.assertEqual(self.threads()['current']['duties'][0]['status'],'unspecified')
        self.assertEqual(self.value(self.t)['lifecycle'],'todo')
        with self.assertRaises(AccessError):self.effect('task.start',self.a,payload=dict(basis=BASIS))
        with self.assertRaises(AccessError):self.effect('dependency.add',self.a,payload=dict(predecessor_id=self.t,basis=BASIS))

    def test_late_import_never_binds_current_duty_without_explicit_historical_version(self):
        self.duty();old=self.threads()['current']['duties'][0]['id'];self.duty(main='New duty')
        with self.work() as s:
            unknown=s.create_attempt(self.p,self.t,'Late old report')['id'];s.link_attempt_session(self.p,unknown,self.a)
            explicit=s.create_attempt(self.p,self.t,'Known historical duty')['id'];s.link_attempt_session(self.p,explicit,self.a,duty_version_id=old)
        rows=self.threads()['historical_contributions']['attempt_sessions']
        self.assertIsNone(next(r for r in rows if r['attempt_id']==unknown)['duty_version_id'])
        self.assertEqual(next(r for r in rows if r['attempt_id']==explicit)['duty_version_id'],old)
        with self.assertRaisesRegex(ChangeError,'contribution_duty_conflict'):
            with self.work() as s:s.link_attempt_session(self.p,unknown,self.a,duty_version_id=old)
        with self.assertRaisesRegex(ChangeError,'inapplicable_contribution_duty'):
            with self.work() as s:s.link_attempt_session(self.p,explicit,self.b,duty_version_id=old)

    def test_cleared_lead_is_not_a_current_participation_dependency(self):
        participant=self.participate();self.lead(self.a);self.lead(None)
        self.assertEqual(json.loads(self.preview(participant)['preview_json'])['conflicts'],[])
        self.revoke(participant)

    def test_description_reversal_keeps_existing_participation_and_later_lead(self):
        self.participate(description='Original description')
        adjustment=self.participate(description='New description');self.lead(self.a)
        plan=json.loads(self.preview(adjustment)['preview_json'])
        self.assertEqual(plan['conflicts'],[])
        self.revoke(adjustment)
        current=self.threads()['current']
        self.assertEqual(current['participation'][0]['description'],'Original description')
        self.assertEqual(current['participation'][0]['active'],1)
        self.assertEqual(current['leads'][0]['session_id'],self.a)

    def test_related_succession_conflict_not_classified_as_unrelated(self):
        first=self.succession(self.a,self.b);later=self.succession(self.b,self.c)
        identity=self.applied(later)['id'];plan=json.loads(self.preview(first)['preview_json'])
        self.assertIn(identity,[r['change_id'] for r in plan['conflicts']])
        self.assertIn(identity,[r['change_id'] for r in plan['subsequent_changes']])
        self.assertNotIn(identity,[r['change_id'] for r in plan['preserved_unrelated_changes']])
        self.assertEqual(plan['target_type'],'thread')

    def test_payload_and_object_validation_fail_closed(self):
        invalid=[('thread.duty.set',self.a,dict(main='X',basis=BASIS,approved=True)),
                 ('thread.duty.set',self.t,dict(main='X',basis=BASIS)),
                 ('thread.duty.set',self.a,dict(main='X',auxiliary='bad',basis=BASIS)),
                 ('thread.duty.set',self.a,dict(main=None,auxiliary=['bad'],basis=BASIS)),
                 ('task.participation.set',self.t,dict(thread_id=self.a,active=1,basis=BASIS)),
                 ('task.participation.set',self.t,dict(thread_id=self.foreign,active=True,basis=BASIS)),
                 ('thread.succession.set',self.a,dict(successor_id=self.foreign,active=True,basis=BASIS)),
                 ('thread.succession.set',self.a,dict(successor_id=self.a,active=True,basis=BASIS)),
                 ('thread.duty.confirm',self.b,dict(suggestion_id=self.a,basis=BASIS))]
        for op,target,payload in invalid:
            with self.subTest(op=op,payload=payload):
                before=self.snapshot()
                with self.assertRaises((ChangeError,AccessError)):self.save(op,target,payload=payload)
                self.assertEqual(self.snapshot(),before)
        with self.assertRaises(AccessError):
            with self.work() as s:
                s.save_candidate(self.p,dict(operation='thread.duty.set',base_revision=s.project(self.p)['revision'],target_id=self.a,payload=dict(main='X',basis=BASIS),source_ids=[s.create_source(self.q,reference='synthetic://foreign')['id']]))

    def test_succession_fan_in_out_correction_and_cycles_without_task_transfer(self):
        self.participate();before=self.behavior(self.t)
        self.succession(self.a,self.b);self.succession(self.a,self.c);self.succession(self.b,self.c)
        self.assertEqual(len(self.threads()['current']['successions']),3)
        c=self.save('thread.succession.set',self.c,payload=dict(successor_id=self.a,active=True,basis=BASIS));r=self.approve(c)
        with self.assertRaisesRegex(ChangeError,'succession_cycle'):self.commit(c,r)
        self.succession(self.b,self.c,False)
        self.assertEqual(self.behavior(self.t),before)
        self.assertEqual([r['session_id'] for r in self.threads()['current']['participation']],[self.a])

    def test_concurrent_reverse_edges_independent_connections(self):
        candidates=[self.save('thread.succession.set',a,payload=dict(successor_id=b,active=True,basis=BASIS)) for a,b in ((self.a,self.b),(self.b,self.a))]
        reviews=[self.approve(c) for c in candidates];barrier=threading.Barrier(2)
        def commit(i):
            barrier.wait()
            try:self.commit(candidates[i],reviews[i]);return 'ok'
            except ChangeError as error:return error.code
        with ThreadPoolExecutor(2) as pool:result=list(pool.map(commit,range(2)))
        self.assertCountEqual(result,['ok','revision_conflict'])
        self.assertEqual(len(self.threads()['current']['successions']),1)

    def test_every_operation_commit_read_reverse_and_duplicate_reversal(self):
        operations=[]
        operations.append(self.duty())
        operations.append(self.participate())
        operations.append(self.lead(self.a))
        operations.append(self.succession(self.a,self.b))
        # Revoke in dependency order; each is the actual T06 candidate/review path.
        for original in reversed(operations):
            with self.subTest(op=original['operation']):
                candidate,review,preview=self.reversal(original)
                self.assertEqual(json.loads(preview['preview_json'])['conflicts'],[])
                request=self.request(candidate,review)
                with self.work() as s:first=s.commit_candidates(self.p,request)
                snapshot=self.snapshot()
                with self.work() as s:self.assertEqual(s.commit_candidates(self.p,request),first)
                self.assertEqual(self.snapshot(),snapshot)
                with self.assertRaisesRegex(ChangeError,'change_already_revoked'):self.preview(original)
        self.assertEqual(self.threads()['current']['duties'],[])
        self.assertEqual(self.threads()['current']['participation'],[])
        self.assertEqual(self.threads()['current']['leads'],[])
        self.assertEqual(self.threads()['current']['successions'],[])
        suggestion=self.effect('thread.duty.suggest',self.a,payload=dict(main='Explicit suggestion',basis=BASIS))
        sid=next(r['id'] for r in self.threads()['history']['thread_duties'] if r['change_id']==self.applied(suggestion)['id'])
        confirm=self.effect('thread.duty.confirm',self.a,payload=dict(suggestion_id=sid,basis=BASIS))
        self.revoke(confirm);self.revoke(suggestion)

    def test_same_field_reversal_conflicts_for_duty_participation_lead_succession(self):
        pairs=[(self.duty(),lambda:self.duty(main='New duty'))]
        pairs.append((self.participate(),lambda:self.participate(description='New description')))
        self.participate(self.b)
        pairs.append((self.lead(self.a),lambda:self.lead(self.b)))
        pairs.append((self.succession(self.a,self.b),lambda:self.succession(self.a,self.b,False)))
        for original,later in pairs:
            later();plan=json.loads(self.preview(original)['preview_json'])
            self.assertTrue(any(c['reason']=='later-thread-field-assignment' for c in plan['conflicts']))
            with self.assertRaisesRegex(ChangeError,'unsafe_independent_reversal'):self.reversal(original)

    def test_relation_dependencies_and_restored_cycle_are_specific(self):
        participant=self.participate();lead=self.lead(self.a)
        self.assertTrue(any(c['reason']=='participation-has-lead-reference' for c in json.loads(self.preview(participant)['preview_json'])['conflicts']))
        self.revoke(lead);self.revoke(participant)
        first=self.succession(self.a,self.b);self.succession(self.b,self.c)
        self.assertTrue(json.loads(self.preview(first)['preview_json'])['conflicts'])
        remove=self.succession(self.a,self.b,False);self.succession(self.c,self.a)
        self.assertTrue(any(c['reason']=='reversal-restores-succession-cycle' for c in json.loads(self.preview(remove)['preview_json'])['conflicts']))

    def test_unrelated_work_acceptance_and_contributions_preserved_on_reversal(self):
        duty=self.duty();participant=self.participate();edge=self.succession(self.a,self.b)
        other,version,_=self.task('Unrelated');self.submit(other,version);self.human(other,version)
        self.participate(self.b)
        with self.work() as s:s.link_task_session(self.p,self.t,self.a)
        before=self.behavior(other)
        self.revoke(duty);self.revoke(edge);self.revoke(participant)
        self.assertEqual(self.behavior(other),before)
        self.assertEqual(len(self.threads()['historical_contributions']['task_sessions']),1)
        self.assertEqual(self.threads()['current']['participation'][0]['session_id'],self.b)

    def test_revisions_invalidate_old_candidates_and_previews(self):
        old=self.save('task.update',self.t,payload=dict(title='Old approval'));review=self.approve(old)
        duty=self.duty()
        with self.assertRaisesRegex(ChangeError,'revision_conflict'):self.commit(old,review)
        preview=self.preview(duty)
        self.participate()
        with self.assertRaisesRegex(ChangeError,'reversal_preview_stale'):
            self.save('change.revoke',preview['original_change_id'],payload=dict(preview_id=preview['id']))

    def test_atomic_fault_after_effects_leaves_no_audit_revision_or_projection(self):
        c=self.save('thread.duty.set',self.a,payload=dict(main='X',basis=BASIS));r=self.approve(c)
        before=self.snapshot();original=Store._insert
        def failure(store,project,table,**values):
            row=original(store,project,table,**values)
            if table=='thread_duties':raise sqlite3.OperationalError('synthetic after actual write')
            return row
        with patch.object(Store,'_insert',failure):
            with self.assertRaises(sqlite3.OperationalError):self.commit(c,r)
        self.assertEqual(self.snapshot(),before)
        self.commit(c,r)
        preview=self.preview(c);reversal=self.save('change.revoke',preview['original_change_id'],payload=dict(preview_id=preview['id']));review=self.approve(reversal)
        before=self.snapshot()
        def fail_correction(store,project,table,**values):
            row=original(store,project,table,**values)
            if table=='effect_corrections':raise sqlite3.OperationalError('synthetic correction failure')
            return row
        with patch.object(Store,'_insert',fail_correction):
            with self.assertRaises(sqlite3.OperationalError):self.commit(reversal,review)
        self.assertEqual(self.snapshot(),before);self.commit(reversal,review)

    def test_commit_idempotency_key_content_and_batch_overlap(self):
        c=self.save('thread.duty.set',self.a,payload=dict(main='X',basis=BASIS));r=self.approve(c);req=self.request(c,r)
        with self.work() as s:result=s.commit_candidates(self.p,req)
        with self.work() as s:self.assertEqual(s.commit_candidates(self.p,req),result)
        with self.assertRaisesRegex(ChangeError,'idempotency_key_reused'):
            with self.work() as s:s.commit_candidates(self.p,dict(req,base_revision=req['base_revision']+1))
        c=self.save('thread.duty.set',self.a,payload=dict(main='Y',basis=BASIS));d=self.save('thread.duty.set',self.a,payload=dict(main='Z',basis=BASIS))
        with self.assertRaisesRegex(ChangeError,'overlapping_effects'):self.batch(c,d)

    def test_task_creation_reversal_recognizes_participation_but_not_thread_id(self):
        with self.work(False) as s:
            create=next(c for c in s.records(self.p,'candidate_specs') if c['operation']=='task.create')['candidate_id']
            candidate=s.candidate(self.p,create)
        self.participate()
        self.assertTrue(json.loads(self.preview(candidate)['preview_json'])['conflicts'])
