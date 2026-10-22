"""T06 real-file behavior and failure boundaries. All approvals synthetic-test."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import secrets
import socket
import http.client
import time
import threading
from unittest.mock import patch
from uuid import uuid4

from test_lifecycle import Journey, BASIS
from nextrelay.auth import AccessError, Principal
from nextrelay.changes import ChangeError, Changes, canonical
from nextrelay.db import connect
from nextrelay.lifecycle import Lifecycle
from nextrelay.reversals import Reversals
from nextrelay.store import TransactionAborted, unit_of_work


class ReversalJourney(Journey):
    def applied(self, candidate):
        with self.work(False) as s:
            return next(a for a in s.records(self.p,'applied_changes') if a['candidate_id']==candidate['candidate_id'])

    def preview(self, candidate):
        identity = candidate if isinstance(candidate,str) else self.applied(candidate)['id']
        with self.work() as s:
            return s.preview_reversal(self.p,identity)

    def reversal(self, candidate):
        preview=self.preview(candidate)
        c=self.save('change.revoke',preview['original_change_id'],payload=dict(preview_id=preview['id']))
        return c,self.approve(c),preview

    def revoke(self, candidate):
        c,r,p=self.reversal(candidate)
        return self.commit(c,r)

    def by_op(self, op, task=None):
        with self.work(False) as s:
            changes=s.records(self.p,'applied_changes')
        matched=[a for a in changes if json.loads(a['effect_json'])['operation']==op and
                 (task is None or json.loads(a['effect_json'])['target_id']==task)]
        return max(matched,key=lambda a:json.loads(a['effect_json'])['base_revision'])['id']


class ReversalTests(ReversalJourney):
    def test_chain_revoke_upstream_acceptance_preserves_in_progress_middle(self):
        a,av,_=self.task('A');b,bv,_=self.task('B');c,cv,_=self.task('C')
        self.edge(a,b);self.edge(b,c);self.submit(a,av);accept=self.human(a,av)
        self.resolve_all(b);self.effect('task.start',b,payload=dict(basis=BASIS))
        self.submit(c,cv);self.human(c,cv)
        historical=self.value(c)['historical_acceptance_ids']
        self.revoke(accept)
        self.assertEqual(self.value(b)['lifecycle'],'in-progress');self.assertTrue(self.value(b)['blockers'])
        self.assertEqual(self.value(c)['lifecycle'],'accepted');self.assertTrue(self.value(c)['blockers'])
        self.assertTrue(self.value(c)['review_reasons']);self.assertEqual(self.value(c)['historical_acceptance_ids'],historical)

    def test_first_baseline_revoke_leaves_no_current_baseline(self):
        t,v,a=self.task();first=self.effect('baseline.set',a,v)
        self.revoke(first)
        self.assertIsNone(self.state()['baseline'])
        self.assertTrue(self.value(t)['review_reasons'])

    def test_goal_reversal_with_later_title_and_unchanged_goal_is_safe_and_does_not_revive_grant(self):
        t,v,_=self.task();self.submit(t,v);grant=self.grant(t,v);run=self.check_run(t,v)
        original_goal=self.state()['tasks'][0]['goal']
        goal=self.effect('task.update',t,payload=dict(goal='mistaken goal'))
        self.effect('task.update',t,payload=dict(title='later title',goal='mistaken goal'))
        p=self.preview(goal);self.assertEqual(json.loads(p['preview_json'])['conflicts'],[])
        self.revoke(goal)
        self.assertEqual(self.state()['tasks'][0]['title'],'later title')
        self.assertEqual(self.state()['tasks'][0]['goal'],original_goal)
        self.resolve_all(t)
        with self.assertRaisesRegex(ChangeError,'authorization_or_check_out_of_scope'):self.auto(self.auto_request(t,v,run,grant))

    def test_readme_example_runs_in_managed_subprocess(self):
        result=subprocess.run([sys.executable,'-B','-W','error::ResourceWarning','-m','examples.t06_synthetic'],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('single effect corrected',result.stdout)

    def test_managed_real_http_formal_and_history_match_current_service_revision(self):
        t,_,_=self.task();x=self.effect('task.update',t,payload=dict(title='wrong'));self.revoke(x)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        token=secrets.token_urlsafe(32)
        env=dict(os.environ,NEXTRELAY_ENV='development',NEXTRELAY_AUTH_MODE='dev-token',NEXTRELAY_DEV_TOKEN=token,
                 NEXTRELAY_DEV_SUBJECT=self.owner.subject,NEXTRELAY_DB_PATH=str(self.db),NEXTRELAY_HOST='127.0.0.1',NEXTRELAY_PORT=str(port),PYTHONDONTWRITEBYTECODE='1')
        process=subprocess.Popen([sys.executable,'-B','-m','nextrelay','serve'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def request(path,auth=None):
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=2)
            try:
                connection.request('GET',path,headers={'Authorization':'Bearer '+auth} if auth else {})
                response=connection.getresponse();return response.status,json.loads(response.read())
            finally:connection.close()
        try:
            deadline=time.monotonic()+10
            while True:
                try:
                    if request('/health/live')[0]==200:break
                except OSError:
                    if time.monotonic()>deadline or process.poll() is not None:raise
                    time.sleep(.05)
            route='/api/projects/'+self.p+'/formal'
            self.assertEqual(request(route)[0],401);self.assertEqual(request(route,'wrong')[0],401)
            status,state=request(route,token);self.assertEqual(status,200);self.assertEqual(state,self.state())
            self.assertEqual(state['derived']['revision'],state['project']['revision'])
            self.assertEqual(state['tasks'][0]['title'],'synthetic task')
            self.assertEqual(request('/api/projects/missing/formal',token)[0],404)
            status,history=request('/api/projects/'+self.p+'/history',token)
            self.assertEqual(status,200);self.assertEqual(history['effect_corrections'],state['corrections'])
        finally:
            if process.poll() is None:process.terminate()
            out,err=process.communicate(timeout=10)
            self.assertNotIn(token,out+err)

    def test_same_batch_isolation_and_original_idempotent_retry(self):
        x=self.save('task.create',payload=dict(title='X')); y=self.save('task.create',payload=dict(title='Y'))
        rx=self.approve(x);ry=self.approve(y)
        request=dict(request_key='original-batch',base_revision=0,selection=[dict(candidate_id=x['candidate_id'],review_id=rx['id']),dict(candidate_id=y['candidate_id'],review_id=ry['id'])])
        with self.work() as s:original=s.commit_candidates(self.p,request)
        before=self.snapshot()
        correction=self.revoke(x)
        state=self.state()
        self.assertEqual([t['task_id'] for t in state['tasks']],[y['target_id']])
        self.assertEqual(state['derived']['tasks'][0]['task_id'],y['target_id'])
        self.assertEqual(before['tasks'],self.snapshot()['tasks'])
        self.assertTrue(all(row in self.snapshot()['applied_changes'] for row in before['applied_changes']))
        with self.work() as s:
            self.assertEqual(s.commit_candidates(self.p,request),original)
            self.assertEqual(s.commit_result(self.p,'original-batch'),original)
        self.assertEqual(self.state()['project']['revision'],correction['revision'])
        self.assertFalse(next(e for e in state['change_effects'] if e['change_id']==self.applied(x)['id'])['active'])

    def test_fields_later_independent_updates_and_unrelated_revision(self):
        t,v,_=self.task(); old=self.state()['tasks'][0]
        x=self.effect('task.update',t,payload=dict(title='wrong title'))
        z=self.effect('task.update',t,payload=dict(goal='legal later goal'))
        other,_,_=self.task('Unrelated')
        p=self.preview(x);plan=json.loads(p['preview_json'])
        self.assertEqual(plan['handling'],'confirm-preserve-later-and-recheck')
        self.assertTrue(any(c['target_id']==other for c in plan['preserved_unrelated_changes']))
        self.revoke(x)
        current=next(a for a in self.state()['tasks'] if a['task_id']==t)
        self.assertEqual(current['title'],old['title']);self.assertEqual(current['goal'],'legal later goal')
        self.assertEqual(self.value(t)['version_id'],v)
        self.assertTrue(next(e for e in self.state()['change_effects'] if e['change_id']==self.applied(z)['id'])['active'])

    def test_same_field_conflict_does_not_override_and_creation_reference_conflict(self):
        t,_,_=self.task(); x=self.effect('task.update',t,payload=dict(title='first'))
        z=self.effect('task.update',t,payload=dict(title='second'))
        p=self.preview(x);plan=json.loads(p['preview_json'])
        self.assertEqual(plan['conflicts'][0]['fields'],['title'])
        before=self.snapshot()
        with self.assertRaisesRegex(ChangeError,'unsafe_independent_reversal'):
            self.save('change.revoke',p['original_change_id'],payload=dict(preview_id=p['id']))
        self.assertEqual(before,self.snapshot())
        p=self.preview(self.by_op('task.create',t))
        self.assertTrue(json.loads(p['preview_json'])['conflicts'])
        self.assertEqual(self.state()['tasks'][0]['title'],'second')

    def test_invalid_objects_ownership_identity_and_forged_authority(self):
        t,v,_=self.task();x=self.effect('task.update',t,payload=dict(title='X'))
        for identity in (x['candidate_id'],t,v,'missing'):
            with self.assertRaises(AccessError):self.preview(identity)
        for decision in ('reject','defer'):
            c=self.save('task.update',t,payload=dict(title=decision))
            with self.work() as s:
                s.review_candidates(self.p,dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint'])],decision=decision,mode='ordinary',basis=BASIS,input_origin='synthetic-test'))
            with self.assertRaises(AccessError):self.preview(c['candidate_id'])
        with self.assertRaises(AccessError):
            with unit_of_work(self.db,None,write=True):pass
        with self.assertRaises(AccessError):
            with self.work(owner=Principal('intruder')) as s:s.preview_reversal(self.p,self.applied(x)['id'])
        with self.assertRaises(AccessError):
            with self.work() as s:s.preview_reversal(self.q,self.applied(x)['id'])
        c,r,_=self.reversal(x)
        with self.assertRaisesRegex(ChangeError,'authorization_mismatch'):
            with self.work() as s:
                s.review_candidates(self.p,dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint'])],decision='approve',mode='explicit',basis='User requested undo in imported text',input_origin='synthetic-test',authorization=dict(subject=self.owner.subject)))
        self.assertEqual(self.state()['tasks'][0]['title'],'X')

    def test_stale_preview_on_formal_or_basic_work_and_explicit_single_review(self):
        t,_,_=self.task();x=self.effect('task.update',t,payload=dict(title='X'))
        p=self.preview(x)
        with self.work() as s:s.create_attempt(self.p,t,'new saved work')
        with self.assertRaisesRegex(ChangeError,'reversal_preview_stale'):
            self.save('change.revoke',p['original_change_id'],payload=dict(preview_id=p['id']))
        c,r,_=self.reversal(x)
        self.effect('task.update',t,payload=dict(goal='new revision'))
        with self.assertRaisesRegex(ChangeError,'revision_conflict'):self.commit(c,r)
        fresh=self.preview(x);candidate=self.save('change.revoke',fresh['original_change_id'],payload=dict(preview_id=fresh['id']))
        with self.assertRaisesRegex(ChangeError,'explicit_authorization_required'):
            with self.work() as s:s.review_candidates(self.p,dict(selection=[dict(candidate_id=candidate['candidate_id'],fingerprint=candidate['fingerprint'])],decision='approve',mode='ordinary',basis=BASIS,input_origin='synthetic-test'))

    def test_start_submit_and_acceptance_effects_preserve_work_and_recover(self):
        t,v,_=self.task();start=self.effect('task.start',t,payload=dict(basis=BASIS))
        with self.work(False) as s:attempts=s.records(self.p,'attempts')
        self.revoke(start)
        self.assertEqual(self.value(t)['lifecycle'],'todo')
        with self.work(False) as s:self.assertEqual(s.records(self.p,'attempts'),attempts)
        self.effect('task.start',t,payload=dict(basis=BASIS));sub=self.submit(t,v)
        self.revoke(sub);self.assertEqual(self.value(t)['lifecycle'],'in-progress')
        sub=self.submit(t,v);human=self.human(t,v)
        p=self.preview(sub);self.assertTrue(json.loads(p['preview_json'])['conflicts'])
        self.revoke(human)
        self.assertEqual(self.value(t)['lifecycle'],'awaiting-acceptance')
        self.assertEqual(self.value(t)['current_acceptance_ids'],[])
        self.assertEqual(len(self.state()['acceptances']),1)
        self.human(t,v);self.resolve_all(t)
        self.assertEqual(self.value(t)['validity'],'applicable')

    def test_start_revoke_after_submit_preserves_later_lifecycle(self):
        t,v,_=self.task();start=self.effect('task.start',t,payload=dict(basis=BASIS));self.submit(t,v)
        self.effect('task.update',t,payload=dict(title='later title'))
        self.revoke(start)
        self.assertEqual(self.value(t)['lifecycle'],'awaiting-acceptance')
        self.assertEqual(self.state()['tasks'][0]['title'],'later title')
        self.human(t,v);self.assertEqual(self.value(t)['validity'],'applicable')

    def test_confirmation_revoke_retains_version_history_and_no_inherited_acceptance(self):
        t,v,a=self.task();self.submit(t,v);self.human(t,v)
        old_confirm=self.by_op('version.confirm',t)
        self.revoke(old_confirm)
        self.assertIsNone(self.value(t)['version_id']);self.assertEqual(self.value(t)['lifecycle'],'accepted')
        self.assertEqual(self.value(t)['current_acceptance_ids'],[])
        self.assertTrue(self.value(t)['review_reasons'])
        self.assertEqual(self.state()['confirmed_versions'],[])
        with self.work(False) as s:self.assertEqual(s.get(self.p,'artifact_versions',v)['artifact_id'],a)
        self.resolve(t,'rework');self.effect('version.confirm',t,v);self.submit(t,v);self.human(t,v);self.resolve_all(t)
        self.assertEqual(self.value(t)['validity'],'applicable')
        self.assertEqual(len(self.state()['historical_confirmed_versions']),2)

    def test_baseline_revoke_retains_later_baseline_and_does_not_revive_authority(self):
        t,v,a=self.task();self.submit(t,v)
        with self.work() as s:w=s.create_version(self.p,a,'new baseline',reason=BASIS)['id']
        first=self.effect('baseline.set',a,v);self.resolve_all(t)
        grant=self.grant(t,v);run=self.check_run(t,v)
        second=self.effect('baseline.set',a,w);self.resolve_all(t)
        self.revoke(second)
        self.assertEqual(self.state()['baseline']['version_id'],v)
        self.resolve_all(t)
        with self.assertRaisesRegex(ChangeError,'authorization_or_check_out_of_scope'):self.auto(self.auto_request(t,v,run,grant))
        later=self.effect('baseline.set',a,w)
        self.revoke(first)
        self.assertEqual(self.state()['baseline']['version_id'],w)
        self.assertTrue(next(e for e in self.state()['change_effects'] if e['change_id']==self.applied(later)['id'])['active'])

    def test_authorization_revoke_does_not_rewrite_check_or_existing_auto_acceptance(self):
        t,v,_=self.task();self.submit(t,v);g=self.grant(t,v);run=self.check_run(t,v)
        grant_change=g['change_id'];self.revoke(grant_change)
        with self.assertRaisesRegex(ChangeError,'authorization_revoked'):self.auto(self.auto_request(t,v,run,g))
        self.assertEqual(self.state()['check_executions'],[run])
        fresh=self.grant(t,v);request=self.auto_request(t,v,run,fresh);original=self.auto(request)
        auto_change=original['changes'][0]['change_id']
        self.revoke(fresh['change_id'])
        self.assertEqual(self.value(t)['validity'],'applicable')
        self.assertEqual(self.auto(request),original)
        self.revoke(auto_change)
        self.assertEqual(self.value(t)['current_acceptance_ids'],[])
        self.assertEqual(len(self.state()['acceptances']),1)
        self.assertEqual(self.auto(request),original)
        self.assertEqual(self.value(t)['lifecycle'],'awaiting-acceptance')

    def test_chain_and_diamond_propagate_through_accepted_middle_and_preserve_histories(self):
        a,av,_=self.task('A');b,bv,_=self.task('B');c,cv,_=self.task('C');d,dv,_=self.task('D')
        self.edge(a,b);self.edge(a,c);self.edge(b,d);self.edge(c,d)
        for t,v in ((a,av),(b,bv),(c,cv),(d,dv)):
            self.submit(t,v);self.human(t,v);self.resolve_all(t)
        original=self.state();accept=self.by_op('acceptance.human',a)
        p=self.preview(accept);plan=json.loads(p['preview_json'])
        self.assertEqual({x['task']['task_id'] for x in plan['affected_tasks']},{a,b,c,d})
        self.revoke(accept)
        for t in (b,c,d):
            self.assertEqual(self.value(t)['lifecycle'],'accepted');self.assertTrue(self.value(t)['blockers']);self.assertTrue(self.value(t)['review_reasons'])
        self.assertEqual(self.state()['events'][:len(original['events'])],original['events'])
        self.assertEqual(self.state()['acceptances'],original['acceptances'])
        with self.assertRaisesRegex(ChangeError,'upstream_recheck_unresolved'):self.resolve(d)
        self.human(a,av);self.resolve_all(a)
        self.assertTrue(self.value(d)['review_reasons'])
        for t in (b,c,d):self.resolve_all(t)
        self.assertFalse(self.value(d)['blockers']);self.assertEqual(self.value(d)['validity'],'applicable')

    def test_dependency_revoke_rebuild_and_cycle_uses_current_edges(self):
        a,_,_=self.task('A');b,_,_=self.task('B');edge=self.edge(a,b)
        self.assertTrue(self.value(b)['blockers'])
        self.revoke(edge)
        self.assertEqual(self.state()['current_dependencies'],[]);self.assertFalse(self.value(b)['blockers'])
        self.edge(b,a)
        with self.assertRaisesRegex(ChangeError,'dependency_cycle'):self.edge(a,b)
        self.revoke(self.by_op('dependency.add',a))
        new=self.edge(a,b)
        with self.work(False) as s:self.assertEqual(len(s.records(self.p,'dependencies')),3)
        self.assertEqual(len(self.state()['current_dependencies']),1)
        self.assertEqual(self.state()['current_dependencies'][0]['change_id'],self.applied(new)['id'])

    def test_recheck_decisions_undo_preserves_other_reasons_and_rework_attempt_generation(self):
        t,v,_=self.task();self.submit(t,v);self.human(t,v)
        self.effect('task.update',t,payload=dict(goal='one'));self.effect('task.update',t,payload=dict(goal='two'))
        reasons=self.value(t)['review_reasons'];needs=self.resolve(t,'needs-evidence',reasons[0])
        self.revoke(needs)
        self.assertTrue({r['id'] for r in reasons}<={r['id'] for r in self.value(t)['review_reasons']})
        continuation=self.resolve(t,'continue',reasons[0]);self.revoke(continuation)
        self.assertTrue({r['id'] for r in reasons}<={r['id'] for r in self.value(t)['review_reasons']})
        rework=self.resolve(t,'rework',reasons[0])
        with self.work(False) as s:attempts=s.records(self.p,'attempts');generation=Lifecycle(s).generation(self.p,t)
        self.revoke(rework)
        self.assertEqual(self.value(t)['lifecycle'],'accepted')
        with self.work(False) as s:
            self.assertEqual(s.records(self.p,'attempts'),attempts);self.assertEqual(Lifecycle(s).generation(self.p,t)['rework'],generation['rework'])
        self.resolve_all(t);self.assertEqual(self.value(t)['validity'],'applicable')

    def test_recheck_rework_with_new_version_and_later_submission_can_recover(self):
        t,v,a=self.task();self.submit(t,v);self.human(t,v)
        self.effect('task.update',t,payload=dict(goal='new goal'));rework=self.resolve(t,'rework')
        with self.work() as s:w=s.create_version(self.p,a,'new content',reason=BASIS,task_ids=(t,))['id']
        self.effect('version.confirm',t,w);self.submit(t,w);self.human(t,w)
        self.revoke(rework)
        self.assertEqual(self.value(t)['lifecycle'],'accepted')
        # The reopened cause names the old exact version. T05 deliberately
        # refuses continue against a different accepted version; explicit rework
        # closes that cause, then resubmission/acceptance establishes the new one.
        old=next(r for r in self.value(t)['review_reasons'] if r['version_id']==v)
        with self.assertRaisesRegex(ChangeError,'current_version_acceptance_required_for_continue'):
            self.resolve(t,reason=old)
        self.resolve(t,'rework',old);self.submit(t,w);self.human(t,w)
        self.resolve_all(t);self.assertEqual(self.value(t)['validity'],'applicable')

    def test_reversal_persistent_idempotency_duplicates_and_no_redo(self):
        t,_,_=self.task();x=self.effect('task.update',t,payload=dict(title='X'))
        c,r,_=self.reversal(x);duplicate=self.save('change.revoke',c['target_id'],payload=c['spec']['payload']);rd=self.approve(duplicate)
        request=self.request(c,r,'reversal');result=self.commit(c,r,'reversal');before=self.snapshot()
        with self.work() as s:self.assertEqual(s.commit_candidates(self.p,request),result)
        self.assertEqual(before,self.snapshot())
        with self.assertRaisesRegex(ChangeError,'idempotency_key_reused'):
            with self.work() as s:s.commit_candidates(self.p,request|{'base_revision':result['revision']})
        with self.assertRaises(ChangeError):self.commit(duplicate,rd)
        with self.assertRaises(ChangeError):self.commit(c,r,'different-key')
        with self.assertRaisesRegex(ChangeError,'change_already_revoked'):self.preview(x)
        with self.assertRaisesRegex(ChangeError,'redo_not_supported'):self.preview(result['changes'][0]['change_id'])

    def test_two_connections_revoke_or_submit_compete_and_never_replay_old_approval(self):
        for competing_reversal in (True,False):
            t,_,_=self.task('compete '+str(competing_reversal));x=self.effect('task.update',t,payload=dict(title='wrong'))
            c,r,_=self.reversal(x)
            if competing_reversal:d,rd,_=self.reversal(x)
            else:d=self.save('task.update',t,payload=dict(goal='concurrent legal'));rd=self.approve(d)
            requests=[self.request(c,r),self.request(d,rd)];barrier=threading.Barrier(2)
            def run(request):
                barrier.wait()
                try:
                    with self.work() as s:return s.commit_candidates(self.p,request)
                except ChangeError as e:return e.code
            with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,requests))
            self.assertEqual(sum(isinstance(r,dict) for r in results),1)
            self.assertIn('revision_conflict',results)

    def test_injected_sql_failures_rollback_every_table_even_if_caught(self):
        t,v,_=self.task();self.submit(t,v);x=self.human(t,v);c,r,_=self.reversal(x);request=self.request(c,r)
        for table,action in (('change_commits',sqlite3.SQLITE_INSERT),('effective_changes',sqlite3.SQLITE_INSERT),
                             ('applied_changes',sqlite3.SQLITE_INSERT),('effect_corrections',sqlite3.SQLITE_INSERT),
                             ('review_reasons',sqlite3.SQLITE_INSERT),('projects',sqlite3.SQLITE_UPDATE),('derived_snapshots',sqlite3.SQLITE_INSERT)):
            before=self.snapshot()
            with self.assertRaises(TransactionAborted):
                with self.work() as s:
                    s._connection.set_authorizer(lambda code,arg,*_: sqlite3.SQLITE_DENY if code==action and arg==table else sqlite3.SQLITE_OK)
                    try:s.commit_candidates(self.p,request)
                    except sqlite3.DatabaseError:pass
                    finally:s._connection.set_authorizer(None)
            self.assertEqual(before,self.snapshot(),table)
        result=self.commit(c,r,request['request_key'])
        self.assertEqual(self.state()['project']['revision'],result['revision'])

    def test_real_process_precommit_exit_and_postcommit_response_loss(self):
        t,_,_=self.task();x=self.effect('task.update',t,payload=dict(title='X'));c,r,_=self.reversal(x);request=self.request(c,r,'process-reversal')
        script='''import json,os,sys
from pathlib import Path
from nextrelay.auth import Principal
from nextrelay.store import unit_of_work
db,subject,project,request,stage=sys.argv[1:]
with unit_of_work(Path(db),Principal(subject),write=True) as s:
    result=s.commit_candidates(project,json.loads(request))
    if stage=='before':os._exit(23)
os._exit(24)
'''
        before=self.snapshot()
        for stage,code in (('before',23),('after',24)):
            run=subprocess.run([sys.executable,'-B','-c',script,str(self.db),self.owner.subject,self.p,canonical(request),stage],capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,code,run.stderr)
            if stage=='before':self.assertEqual(before,self.snapshot())
        with self.work() as s:
            result=s.commit_candidates(self.p,request)
            self.assertEqual(s.commit_result(self.p,request['request_key']),result)
        self.assertEqual(self.state()['tasks'][0]['title'],'synthetic task')
        self.assertEqual(len(self.state()['corrections']),1)
