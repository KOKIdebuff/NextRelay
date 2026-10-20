"""T04 behavior against real SQLite files; review inputs are explicitly synthetic."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from nextrelay.auth import AccessError, Principal
from nextrelay.changes import ChangeError, Changes, digest
from nextrelay.db import SchemaError, connect, initialize, transaction, verify_schema
from nextrelay.schema import ENTITY_TABLES, RELATION_TABLES
from nextrelay.store import TransactionAborted, unit_of_work


class ChangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nextrelay-t04-')
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name)/'changes.sqlite3'
        initialize(self.db)
        self.owner = Principal('dev-t04')
        with self.work() as s:
            self.p = s.create_project('synthetic T04')['id']
            self.q = s.create_project('other project')['id']
            self.source = s.create_source(self.p,reference='synthetic://user-already-approved',metadata={'risk':'low','approved':True})['id']
            self.artifact = s.create_artifact(self.p,'requirements')['id']
            self.v = s.create_version(self.p,self.artifact,'original',reason='synthetic')['id']
            self.v2 = s.create_version(self.p,self.artifact,'revision',reason='synthetic')['id']
            self.qsource = s.create_source(self.q,reference='synthetic://foreign')['id']
            qa = s.create_artifact(self.q,'foreign')['id']
            self.qv = s.create_version(self.q,qa,'foreign',reason='synthetic')['id']
            self.e = s.record_evidence(self.p,self.v,mechanism='synthetic observation',subject='synthetic-test',result='claim only',configuration_version='test')['id']

    def work(self, *, owner=None, write=True):
        return unit_of_work(self.db,owner or self.owner,write=write)

    def save(self, op='task.create', *, base=None, **values):
        with self.work() as s:
            revision = s.project(self.p)['revision'] if base is None else base
            request = dict(base_revision=revision,operation=op,payload={'title':'synthetic formal task'} if op=='task.create' else {})
            request.update(values)
            return s.save_candidate(self.p,request)

    def review_request(self, candidates, decision='approve', explicit=False):
        request = dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint']) for c in candidates],
                       decision=decision,mode='explicit' if explicit else 'ordinary',basis='Synthetic test input; no real business approval',input_origin='synthetic-test')
        if explicit and decision=='approve':
            c=candidates[0];spec=c['spec']
            request['authorization'] = dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint'],
                target_id=spec['target_id'],target_version_id=spec['target_version_id'],base_revision=spec['base_revision'],
                preconditions_sha256=digest(spec['preconditions']))
        return request

    def review(self, *candidates, decision='approve', explicit=False):
        with self.work() as s:
            return s.review_candidates(self.p,self.review_request(candidates,decision,explicit))

    def request(self, candidates, reviews, key='synthetic-request'):
        return dict(request_key=key,base_revision=candidates[0]['spec']['base_revision'],
                    selection=[dict(candidate_id=c['candidate_id'],review_id=r['id']) for c,r in zip(candidates,reviews)])

    def commit(self, candidates, reviews, key='synthetic-request'):
        request = self.request(candidates,reviews,key)
        with self.work() as s:
            return s.commit_candidates(self.p,request)

    def state(self):
        with self.work(write=False) as s:
            return s.formal_state(self.p)

    def snapshot(self):
        with connect(self.db) as c:
            return {table:[tuple(r) for r in c.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                    for table in ('projects',)+ENTITY_TABLES+RELATION_TABLES}

    def make_task(self):
        c=self.save();r=self.review(c);self.commit([c],r,key=c['candidate_id']);return c['target_id']

    def test_full_path_real_effect_revision_audit_and_reopened_result(self):
        c=self.save(source_ids=[self.source],payload={'title':"safe ' SQL --",'goal':'observable'})
        self.assertEqual(self.state()['tasks'],[])
        r=self.review(c);self.assertEqual(self.state()['project']['revision'],0)
        result=self.commit([c],r)
        state=self.state();self.assertEqual(state['tasks'][0]['title'],"safe ' SQL --")
        self.assertEqual(state['tasks'][0]['goal'],'observable');self.assertEqual(state['project']['revision'],1)
        with self.work(write=False) as s:
            self.assertEqual(s.commit_result(self.p,'synthetic-request'),result)
            audit=s.records(self.p,'applied_changes');self.assertEqual(len(audit),1)
            self.assertEqual(audit[0]['review_id'],r[0]['id'])
            self.assertEqual(json.loads(audit[0]['effect_json'])['source_ids'],[self.source])
            self.assertEqual(s.records(self.p,'acceptances'),[])

    def test_partial_selection_reject_defer_and_unreviewed_never_apply(self):
        items=[self.save(payload={'title':str(i)}) for i in range(4)]
        approved=self.review(items[0]);self.review(items[1],decision='reject');self.review(items[2],decision='defer')
        self.assertEqual(self.state()['tasks'],[])
        self.commit([items[0]],approved)
        self.assertEqual([t['task_id'] for t in self.state()['tasks']],[items[0]['target_id']])
        for i in range(1,4):
            with self.assertRaises(ChangeError):
                with self.work() as s:
                    s.commit_candidates(self.p,dict(request_key=f'refused-{i}',base_revision=0,
                        selection=[dict(candidate_id=items[i]['candidate_id'],review_id=approved[0]['id'])]))

    def test_matching_approval_and_latest_decision_required(self):
        a,b=self.save(),self.save();ra=self.review(a)
        with self.assertRaisesRegex(ChangeError,'matching_approval'):
            self.commit([b],ra)
        self.review(a,decision='defer')
        with self.assertRaisesRegex(ChangeError,'matching_approval'):
            self.commit([a],ra)
        with self.work(write=False) as s:
            self.assertEqual(len(s.records(self.p,'change_reviews')),2)
        self.assertEqual(self.state()['tasks'],[])

    def test_high_conflict_and_baseline_cannot_enter_ordinary_batch(self):
        ordinary=self.save()
        special=[self.save(risk='high'),self.save(conflicts=['synthetic conflict']),
                 self.save('baseline.set',target_id=self.artifact,target_version_id=self.v,risk='ordinary',source_ids=[self.source])]
        for c in special:
            before=self.snapshot()
            with self.subTest(risk=c['risk']),self.assertRaisesRegex(ChangeError,'explicit_authorization'):
                self.review(ordinary,c)
            self.assertEqual(before,self.snapshot())
        self.assertEqual(special[-1]['risk'],'high')

    def test_explicit_authorization_must_match_exact_content_target_and_revision(self):
        c=self.save('baseline.set',target_id=self.artifact,target_version_id=self.v,evidence_ids=[self.e])
        original=self.review_request([c],explicit=True)
        for key in ('candidate_id','fingerprint','target_id','target_version_id','base_revision','preconditions_sha256'):
            request=deepcopy(original);request['authorization'][key]='wrong'
            with self.subTest(key=key),self.assertRaisesRegex(ChangeError,'authorization_mismatch'):
                with self.work() as s:s.review_candidates(self.p,request)
        missing=deepcopy(original);missing.pop('authorization')
        with self.assertRaises(ChangeError):
            with self.work() as s:s.review_candidates(self.p,missing)
        self.assertIsNone(self.state()['baseline'])
        r=self.review(c,explicit=True);self.commit([c],r)
        self.assertEqual(self.state()['baseline']['version_id'],self.v)
        self.assertEqual(self.state()['readiness'],'not-evaluated')

    def test_high_risk_approved_items_still_require_single_commit(self):
        a=self.save();b=self.save(risk='high',payload={'title':'distinct high-risk task'});ra=self.review(a);rb=self.review(b,explicit=True)
        with self.assertRaisesRegex(ChangeError,'explicit_commit_is_single'):
            self.commit([a,b],ra+rb)
        self.assertEqual(self.state()['project']['revision'],0)

    def test_baseline_switch_preserves_source_version_evidence_and_history(self):
        a=self.save('baseline.set',target_id=self.artifact,target_version_id=self.v,source_ids=[self.source],evidence_ids=[self.e])
        self.commit([a],self.review(a,explicit=True),key='first')
        b=self.save('baseline.set',target_id=self.artifact,target_version_id=self.v2)
        self.commit([b],self.review(b,explicit=True),key='second')
        with self.work(write=False) as s:
            self.assertEqual(s.formal_state(self.p)['baseline']['version_id'],self.v2)
            self.assertEqual([x['version_id'] for x in sorted(s.records(self.p,'baseline_history'),key=lambda x:x['revision'])],[self.v,self.v2])
            self.assertEqual(s.get(self.p,'artifact_versions',self.v)['content'],'original')
            self.assertEqual(s.get(self.p,'sources',self.source)['reference'],'synthetic://user-already-approved')
            self.assertEqual(s.get(self.p,'evidence',self.e)['result'],'claim only')
            self.assertEqual(len(s.records(self.p,'candidate_specs')),2)
            self.assertEqual(len(s.records(self.p,'recheck_requests')),2)
            self.assertEqual(s.records(self.p,'document_confirmations'),[])
            self.assertEqual(s.records(self.p,'acceptances'),[])

    def test_task_update_and_version_confirmation_have_observable_effects(self):
        task=self.make_task()
        c=self.save('task.update',target_id=task,payload={'title':'changed','goal':'new goal'})
        self.commit([c],self.review(c),key='edit')
        self.assertEqual(self.state()['tasks'][0]['title'],'changed')
        with self.work() as s:
            s.link_version_task(self.p,self.v,task)
            evidence=s.record_evidence(self.p,self.v,task_id=task,conditions_version=1,
                mechanism='synthetic',subject='synthetic-test',result='pass is only input',configuration_version='test')['id']
        c=self.save('version.confirm',target_id=task,target_version_id=self.v,evidence_ids=[evidence])
        self.commit([c],self.review(c),key='confirm')
        self.assertEqual(self.state()['confirmed_versions'][0]['version_id'],self.v)
        self.assertEqual(self.state()['confirmed_versions'][0]['task_id'],task)
        with self.work(write=False) as s:
            self.assertEqual(s.evidence_for(self.p,task,self.v2),[])
            self.assertEqual(s.records(self.p,'acceptances'),[])
        with self.assertRaisesRegex(ChangeError,'version_already_confirmed'):
            self.save('version.confirm',target_id=task,target_version_id=self.v)

    def test_t03_storage_is_not_formal_and_cannot_modify_formal_snapshot(self):
        with self.work() as s:
            raw=s.create_task(self.p,'unreviewed')['id'];s.link_version_task(self.p,self.v,raw)
            s.record_check(self.p,self.e,mechanism='synthetic',subject='synthetic',configuration_version='test',result='pass')
        self.assertEqual(self.state()['tasks'],[]);self.assertEqual(self.state()['confirmed_versions'],[])
        self.assertIsNone(self.state()['baseline'])
        with self.assertRaisesRegex(ChangeError,'task_not_formal'):
            self.save('task.update',target_id=raw,payload={'title':'bypass'})
        task=self.make_task()
        with connect(self.db) as c:c.execute('UPDATE tasks SET title=? WHERE id=?',('base-record-only',task))
        self.assertEqual(self.state()['tasks'][0]['title'],'synthetic formal task')

    def test_unknown_operations_fields_and_untrusted_claims_do_not_grant_authority(self):
        for op in ('dependency.add','task.accept','task.delete','task.start','document.confirm'):
            with self.subTest(op=op),self.assertRaisesRegex(ChangeError,'unsupported_operation'):self.save(op)
        for extra in ({'approved':True},{'subject':'dev-t04'},{'checks_passed':True},{'preconditions':{}}):
            with self.subTest(extra=extra),self.assertRaises(ChangeError):self.save(**extra)
        with self.assertRaises(ChangeError):self.save(payload={'title':'x','approved':True})
        self.assertEqual(self.state()['project']['revision'],0)

    def test_missing_identity_and_foreign_project_reads_writes_results_are_denied(self):
        for identity in (None,'dev-t04',Principal('')):
            with self.assertRaises(AccessError):
                with unit_of_work(self.db,identity):pass
        stranger=Principal('dev-stranger')
        calls=[lambda s:s.save_candidate(self.p,{}),lambda s:s.review_candidates(self.p,{}),
               lambda s:s.commit_candidates(self.p,{}),lambda s:s.commit_result(self.p,'synthetic-request'),
               lambda s:s.formal_state(self.p),lambda s:s.candidate(self.p,'missing')]
        for call in calls:
            with self.assertRaises(AccessError):
                with self.work(owner=stranger) as s:call(s)

    def test_cross_project_missing_wrong_version_and_inapplicable_evidence_rejected(self):
        for source in (self.qsource,'missing'):
            with self.assertRaises(AccessError):self.save(source_ids=[source])
        for version in (self.qv,'missing'):
            with self.assertRaises(AccessError):self.save('baseline.set',target_id=self.artifact,target_version_id=version)
        with self.work() as s:other=s.create_artifact(self.p,'other artifact')['id']
        with self.assertRaisesRegex(ChangeError,'wrong_artifact_version'):
            self.save('baseline.set',target_id=other,target_version_id=self.v)
        with self.assertRaisesRegex(ChangeError,'inapplicable_evidence'):
            self.save('baseline.set',target_id=self.artifact,target_version_id=self.v2,evidence_ids=[self.e])
        task=self.make_task()
        with self.assertRaisesRegex(ChangeError,'inapplicable_evidence'):
            self.save('version.confirm',target_id=task,target_version_id=self.v,evidence_ids=[self.e])

    def test_stale_project_revision_never_replays_approval(self):
        a,b=self.save(),self.save();ra,rb=self.review(a),self.review(b)
        self.commit([a],ra)
        with self.assertRaisesRegex(ChangeError,'revision_conflict'):self.commit([b],rb,key='stale')
        with self.assertRaisesRegex(ChangeError,'revision_conflict'):self.save(base=0)
        with self.assertRaisesRegex(ChangeError,'revision_conflict'):self.review(b)
        self.assertEqual(len(self.state()['tasks']),1)

    def test_changed_source_attribution_invalidates_prior_review(self):
        a=self.save(source_ids=[self.source]);ra=self.review(a)
        with self.work() as s:
            old=s.attribution(self.p,self.source);s.attribute_source(self.p,self.source,supersedes_id=old['id'],reason='changed important basis')
        with self.assertRaisesRegex(ChangeError,'preconditions_changed'):self.commit([a],ra)
        self.assertEqual(self.state()['tasks'],[])

    def test_changed_version_provenance_invalidates_prior_review(self):
        a=self.save('baseline.set',target_id=self.artifact,target_version_id=self.v);ra=self.review(a,explicit=True)
        with self.work() as s:s.link_version_source(self.p,self.v,self.source)
        with self.assertRaisesRegex(ChangeError,'preconditions_changed'):self.commit([a],ra)

    def test_revised_candidate_preserves_history_and_cannot_use_old_review(self):
        a=self.save();ra=self.review(a)
        b=self.save(payload={'title':'revised content'},supersedes_id=a['candidate_id'])
        with self.assertRaisesRegex(ChangeError,'candidate_superseded'):self.commit([a],ra)
        with self.assertRaisesRegex(ChangeError,'matching_approval'):self.commit([b],ra)
        wrong=self.review_request([b]);wrong['selection'][0]['fingerprint']=a['fingerprint']
        with self.assertRaisesRegex(ChangeError,'candidate_content_mismatch'):
            with self.work() as s:s.review_candidates(self.p,wrong)
        self.commit([b],self.review(b))
        self.assertEqual(self.state()['tasks'][0]['title'],'revised content')

    def test_same_key_same_request_after_later_revision_returns_original_no_extra_rows(self):
        a=self.save();ra=self.review(a);request=self.request([a],ra)
        first=self.commit([a],ra)
        b=self.save(payload={'title':'later independent task'});self.commit([b],self.review(b),key='later')
        before=self.snapshot()
        with self.work() as s:self.assertEqual(s.commit_candidates(self.p,request),first)
        self.assertEqual(before,self.snapshot())

    def test_same_key_different_request_is_rejected(self):
        a=self.save();ra=self.review(a);self.commit([a],ra)
        request=self.request([a],ra);request['base_revision']=1
        with self.assertRaisesRegex(ChangeError,'idempotency_key_reused'):
            with self.work() as s:s.commit_candidates(self.p,request)
        self.assertEqual(self.state()['project']['revision'],1)

    def test_different_key_batch_single_and_duplicate_selection_cannot_reapply(self):
        a,b=self.save(),self.save(payload={'title':'independent batch task'});r=self.review(a,b);byid={x['candidate_id']:x for x in r};ra,rb=byid[a['candidate_id']],byid[b['candidate_id']]
        request=self.request([a,b],[ra,rb]);duplicate=deepcopy(request);duplicate['selection'].append(duplicate['selection'][0])
        with self.assertRaisesRegex(ChangeError,'duplicate_candidate'):
            with self.work() as s:s.commit_candidates(self.p,duplicate)
        self.commit([a,b],[ra,rb])
        with self.assertRaises(ChangeError):self.commit([a],[ra],key='new-key')
        self.assertEqual(len(self.state()['tasks']),2);self.assertEqual(self.state()['project']['revision'],1)
        # Reordering the same explicit selection is the same normalized request.
        request['selection'].reverse()
        with self.work() as s:self.assertEqual(s.commit_candidates(self.p,request)['revision'],1)

    def test_reusing_applied_candidate_at_current_revision_is_rejected(self):
        a=self.save();ra=self.review(a);self.commit([a],ra)
        request=self.request([a],ra,key='new');request['base_revision']=1
        with self.assertRaisesRegex(ChangeError,'candidate_already_applied'):
            with self.work() as s:s.commit_candidates(self.p,request)

    def test_real_independent_connection_revision_race_has_one_winner(self):
        a,b=self.save(),self.save();ra,rb=self.review(a),self.review(b)
        barrier=threading.Barrier(2)
        def worker(c,r):
            barrier.wait(timeout=10)
            try:return self.commit([c],r,key=c['candidate_id'])
            except ChangeError as e:return e.code
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda pair:worker(*pair),[(a,ra),(b,rb)]))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1);self.assertIn('revision_conflict',results)
        with self.work(write=False) as s:
            self.assertEqual(len(s.records(self.p,'applied_changes')),1)
            self.assertEqual(len(s.records(self.p,'change_commits')),1)
        self.assertEqual(len(self.state()['tasks']),1)

    def test_real_duplicate_request_race_returns_one_durable_result(self):
        a=self.save();r=self.review(a);barrier=threading.Barrier(2)
        def worker(_):
            barrier.wait(timeout=10);return self.commit([a],r)
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(worker,range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(self.state()['project']['revision'],1)
        self.assertEqual(len(self.state()['tasks']),1)

    def test_database_failures_at_each_stage_roll_back_everything_and_retry(self):
        a=self.save();r=self.review(a);request=self.request([a],r)
        before=self.snapshot()
        for action,table in ((sqlite3.SQLITE_INSERT,'change_commits'),(sqlite3.SQLITE_INSERT,'effective_changes'),
                             (sqlite3.SQLITE_INSERT,'applied_changes'),(sqlite3.SQLITE_INSERT,'tasks'),
                             (sqlite3.SQLITE_INSERT,'formal_task_states'),(sqlite3.SQLITE_UPDATE,'projects')):
            with self.subTest(table=table),self.assertRaises(sqlite3.DatabaseError):
                with self.work() as s:
                    s._connection.set_authorizer(lambda code,arg,*rest:sqlite3.SQLITE_DENY if code==action and arg==table else sqlite3.SQLITE_OK)
                    s.commit_candidates(self.p,request)
            self.assertEqual(before,self.snapshot())
        self.commit([a],r);self.assertEqual(len(self.state()['tasks']),1)

    def test_multicandidate_partial_business_failure_and_caught_error_abort_whole_unit(self):
        a,b=self.save(),self.save(payload={'title':'independent batch task'});r=self.review(a,b);byid={x['candidate_id']:x for x in r};request=self.request([a,b],[byid[a['candidate_id']],byid[b['candidate_id']]])
        original=Changes.apply;count=0
        def fail_second(service,*args):
            nonlocal count
            original(service,*args);count+=1
            if count==2:raise RuntimeError('synthetic failure after second effect')
        before=self.snapshot()
        with patch.object(Changes,'apply',fail_second),self.assertRaises(TransactionAborted):
            with self.work() as s:
                try:s.commit_candidates(self.p,request)
                except RuntimeError:pass
        self.assertEqual(before,self.snapshot())

    def test_process_exit_inside_formal_transaction_rolls_back_real_file(self):
        a=self.save();r=self.review(a);request=self.request([a],r)
        before=self.snapshot()
        code='''
import json,os,sys
from pathlib import Path
from nextrelay.auth import Principal
from nextrelay.store import unit_of_work
from nextrelay.changes import Changes
original=Changes.apply
def crash(self,*args):
    original(self,*args)
    os._exit(37)
Changes.apply=crash
with unit_of_work(Path(sys.argv[1]),Principal('dev-t04'),write=True) as s:
    s.commit_candidates(sys.argv[2],json.loads(sys.argv[3]))
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.db),self.p,json.dumps(request)],capture_output=True,timeout=15)
        self.assertEqual(result.returncode,37);self.assertEqual(before,self.snapshot())
        self.commit([a],r)

    def test_process_exit_after_commit_before_response_recovers_original_result(self):
        a=self.save();r=self.review(a);request=self.request([a],r)
        code='''
import json,os,sys
from pathlib import Path
from nextrelay.auth import Principal
from nextrelay.store import unit_of_work
with unit_of_work(Path(sys.argv[1]),Principal('dev-t04'),write=True) as s:
    s.commit_candidates(sys.argv[2],json.loads(sys.argv[3]))
os._exit(38)
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.db),self.p,json.dumps(request)],capture_output=True,timeout=15)
        self.assertEqual(result.returncode,38);self.assertEqual(result.stdout,b'')
        state=self.state();self.assertEqual(len(state['tasks']),1);self.assertEqual(state['project']['revision'],1)
        before=self.snapshot()
        with self.work() as s:
            durable=s.commit_result(self.p,request['request_key']);self.assertEqual(s.commit_candidates(self.p,request),durable)
        self.assertEqual(before,self.snapshot())

    def test_target_record_version_and_mismatched_review_target_are_rechecked(self):
        task=self.make_task()
        a=self.save('task.update',target_id=task,payload={'title':'reviewed'})
        r=self.review(a)
        with connect(self.db) as c:c.execute('UPDATE tasks SET goal=? WHERE id=?',('changed foundation target',task))
        with self.assertRaisesRegex(ChangeError,'preconditions_changed'):self.commit([a],r,key='changed-target')
        self.assertEqual(self.state()['tasks'][0]['title'],'synthetic formal task')

    def test_baseline_failure_after_history_write_rolls_back_pointer_and_audit(self):
        a=self.save('baseline.set',target_id=self.artifact,target_version_id=self.v)
        r=self.review(a,explicit=True);request=self.request([a],r);before=self.snapshot()
        with self.assertRaises(sqlite3.DatabaseError):
            with self.work() as s:
                s._connection.set_authorizer(lambda code,arg,*rest:sqlite3.SQLITE_DENY if code==sqlite3.SQLITE_INSERT and arg=='recheck_requests' else sqlite3.SQLITE_OK)
                s.commit_candidates(self.p,request)
        self.assertEqual(before,self.snapshot());self.assertIsNone(self.state()['baseline'])
        self.commit([a],r)

    def test_new_version_does_not_replace_reviewed_version_or_inherit_confirmation(self):
        a=self.save('baseline.set',target_id=self.artifact,target_version_id=self.v)
        r=self.review(a,explicit=True)
        with self.work() as s:new=s.create_version(self.p,self.artifact,'newest',reason='synthetic newer version')['id']
        self.commit([a],r)
        self.assertEqual(self.state()['baseline']['version_id'],self.v)
        self.assertNotEqual(new,self.v)
        self.assertEqual(self.state()['confirmed_versions'],[])

    def test_t04_uniqueness_and_same_project_foreign_keys_are_enforced(self):
        a=self.save();self.commit([a],self.review(a))
        with connect(self.db) as c:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO applied_changes SELECT 'duplicate',project_id,created_at,created_by,effective_change_id,candidate_id,review_id,commit_id,effect_json FROM applied_changes")
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO baseline_history VALUES ('cross',?,'time','dev-t04',?,NULL,1,?)",(self.p,self.qv,'missing-change'))
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO change_commits SELECT 'duplicate',project_id,created_at,created_by,action,request_key,request_fingerprint,request_json,result_json,base_revision,revision FROM change_commits")

    def test_exact_duplicate_creation_and_same_target_batch_are_rejected_atomically(self):
        a,b=self.save(),self.save();r=self.review(a,b);byid={x['candidate_id']:x for x in r}
        before=self.snapshot()
        with self.assertRaisesRegex(ChangeError,'duplicate_formal_task'):
            self.commit([a,b],[byid[a['candidate_id']],byid[b['candidate_id']]])
        self.assertEqual(before,self.snapshot())
        self.commit([a],[byid[a['candidate_id']]])
        with self.assertRaisesRegex(ChangeError,'duplicate_formal_task'):self.save()
        task=a['target_id']
        c=self.save('task.update',target_id=task,payload={'goal':'first proposal'})
        d=self.save('task.update',target_id=task,payload={'goal':'other proposal'})
        reviews=self.review(c,d);indexed={x['candidate_id']:x for x in reviews}
        with self.assertRaisesRegex(ChangeError,'overlapping_effects'):
            self.commit([c,d],[indexed[c['candidate_id']],indexed[d['candidate_id']]],key='overlap')
        self.assertEqual(self.state()['tasks'][0]['goal'],'')
        with self.assertRaisesRegex(ChangeError,'no_business_change'):
            self.save('task.update',target_id=task,payload={'goal':''})

    def test_t04_history_and_protections_are_immutable_and_schema_checked(self):
        a=self.save();self.commit([a],self.review(a))
        with connect(self.db) as c:
            for table in ('candidate_changes','candidate_specs','change_reviews','change_commits','applied_changes','formal_task_states'):
                for statement in (f'DELETE FROM {table}',f'UPDATE {table} SET created_by=created_by'):
                    with self.subTest(statement=statement),self.assertRaises(sqlite3.IntegrityError):c.execute(statement)
            c.execute('DROP TRIGGER change_commits_t04_no_update')
            with self.assertRaises(SchemaError):verify_schema(c)


class V2MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nextrelay-t04-migration-');self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'real-v2.sqlite3'
        with connect(self.db) as c:
            c.executescript((Path(__file__).parent/'fixtures'/'schema_v2.sql').read_text(encoding='utf-8'))
            c.execute("INSERT INTO projects VALUES ('p','dev-original','old project',0,'old time')")
            c.execute("INSERT INTO tasks(id,project_id,created_at,created_by,title,goal,completion_conditions) VALUES ('t','p','time','dev-original','title','goal','conditions')")
            c.execute("INSERT INTO sessions(id,project_id,created_at,created_by,title) VALUES ('s','p','time','dev-original','session')")
            c.execute("INSERT INTO task_sessions VALUES ('p','t','s','dev-original')")
            c.execute("INSERT INTO sources(id,project_id,created_at,created_by,reference,fingerprint,storage_choice,availability,read_result,metadata_json) VALUES ('src','p','time','dev-original','synthetic://old','fingerprint','reference-only','unknown','not-read','{}')")
            c.execute("INSERT INTO source_attributions(id,project_id,created_at,created_by,source_id,reason) VALUES ('attr','p','time','dev-original','src','unresolved')")
            c.execute("INSERT INTO artifacts(id,project_id,created_at,created_by,title) VALUES ('a','p','time','dev-original','artifact')")
            c.execute("INSERT INTO artifact_versions VALUES ('v','p','time','dev-original','a',1,'old body',?,'text/plain','old reason')",('f'*64,))
            c.execute("INSERT INTO artifact_tasks VALUES ('p','a','t','dev-original')")
            c.execute("INSERT INTO artifact_version_tasks VALUES ('p','a','v','t','dev-original')")
            c.execute("INSERT INTO version_sources VALUES ('p','v','src','dev-original')")
            c.execute("INSERT INTO evidence VALUES ('e','p','time','dev-original','t','v','src','observation','synthetic','synthetic-test','observed',1,'config-old')")
            c.execute("INSERT INTO candidate_changes(id,project_id,created_at,created_by,base_revision,task_id,version_id,source_id) VALUES ('reserved','p','time','dev-original',0,'t','v','src')")
        self.tables=None
        with connect(self.db) as c:
            self.tables=[r[0] for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table'")]
        self.before=self.data()

    def data(self):
        with connect(self.db) as c:return {t:[tuple(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in self.tables}

    def test_real_v2_file_upgrade_preserves_every_old_row_and_repeat_is_noop(self):
        initialize(self.db);initialize(self.db)
        self.assertEqual(self.data(),self.before)
        with connect(self.db) as c:
            verify_schema(c);self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],3)
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
        with unit_of_work(self.db,Principal('dev-original')) as s:
            self.assertEqual(s.formal_state('p')['tasks'],[])
        with self.assertRaisesRegex(ChangeError,'reserved_candidate_not_supported'):
            with unit_of_work(self.db,Principal('dev-original')) as s:s.candidate('p','reserved')

    def test_migration_failure_rolls_back_partial_ddl_version_and_keeps_old_data(self):
        with patch('nextrelay.db.verify_schema',side_effect=SchemaError('synthetic final migration failure')):
            with self.assertRaises(SchemaError):initialize(self.db)
        self.assertEqual(self.data(),self.before)
        with connect(self.db) as c:
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],2)
            self.assertIsNone(c.execute("SELECT name FROM sqlite_schema WHERE name='candidate_specs'").fetchone())
        initialize(self.db)

    def test_mid_migration_conflict_and_missing_constraint_are_rejected(self):
        with connect(self.db) as c:c.execute('CREATE TABLE change_reviews(untouched TEXT)')
        with self.assertRaises(sqlite3.OperationalError):initialize(self.db)
        with connect(self.db) as c:
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],2)
            self.assertIsNone(c.execute("SELECT name FROM sqlite_schema WHERE name='candidate_specs'").fetchone())
            c.execute('DROP TABLE change_reviews')
        initialize(self.db)
        with connect(self.db) as c:
            c.execute('DROP INDEX reviews_candidate_order')
            with self.assertRaises(SchemaError):verify_schema(c)
        self.assertEqual(self.data(),self.before)


if __name__=='__main__':unittest.main()
