"""T05 real-file behavioral tests; every business decision is synthetic-test input."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from nextrelay.auth import AccessError, Principal
from nextrelay.changes import ChangeError, Changes, canonical, digest
from nextrelay.db import SCHEMA_VERSION, SchemaError, connect, initialize, transaction, verify_schema
from nextrelay.lifecycle import Lifecycle
from nextrelay.schema import ENTITY_TABLES, RELATION_TABLES, MIGRATIONS
from nextrelay.store import Store, TransactionAborted, unit_of_work
from nextrelay import checks

JSON_CONFIG = dict(protocol='builtin-v1',type='json-object',rules=dict(required=['status'],equals=dict(status='ok')))
BASIS = 'Synthetic test input only; no real business approval'


class Journey(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nextrelay-t05-')
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name)/'synthetic.sqlite3'
        initialize(self.db)
        self.owner = Principal('dev-t05')
        with self.work() as s:
            self.p = s.create_project('Synthetic T05')['id']
            self.q = s.create_project('Synthetic other project')['id']

    def work(self, write=True, owner=None):
        return unit_of_work(self.db,owner or self.owner,write=write)

    def state(self):
        with self.work(False) as s:
            return s.formal_state(self.p)

    def value(self, task):
        return next(v for v in self.state()['derived']['tasks'] if v['task_id']==task)

    def save(self, operation, task=None, version=None, payload=None, project=None):
        with self.work() as s:
            project = project or self.p
            request = dict(base_revision=s.project(project)['revision'],operation=operation,payload=payload or {})
            if task is not None:
                request['target_id'] = task
            if version is not None:
                request['target_version_id'] = version
            return s.save_candidate(project,request)

    def approve(self, candidate):
        with self.work() as s:
            req = dict(selection=[dict(candidate_id=candidate['candidate_id'],fingerprint=candidate['fingerprint'])],
                       decision='approve',mode='explicit' if candidate['risk']!='ordinary' else 'ordinary',basis=BASIS,input_origin='synthetic-test')
            if req['mode']=='explicit':
                req['authorization'] = Changes(s).authorization(candidate)
            return s.review_candidates(candidate['project_id'],req)[0]

    def request(self, candidate, review, key=None):
        return dict(request_key=key or str(uuid4()),base_revision=candidate['spec']['base_revision'],
                    selection=[dict(candidate_id=candidate['candidate_id'],review_id=review['id'])])

    def commit(self, candidate, review, key=None):
        request = self.request(candidate,review,key)
        with self.work() as s:
            return s.commit_candidates(candidate['project_id'],request)

    def effect(self, operation, task=None, version=None, payload=None, project=None):
        candidate = self.save(operation,task,version,payload,project)
        self.commit(candidate,self.approve(candidate))
        return candidate

    def task(self, title='synthetic task', body='{"status":"ok"}', project=None):
        project = project or self.p
        candidate = self.effect('task.create',payload=dict(title=title,goal='Synthetic goal '+title,completion_conditions='Declared status equals ok'),project=project)
        task = candidate['target_id']
        with self.work() as s:
            artifact = s.create_artifact(project,title)['id']
            version = s.create_version(project,artifact,body,reason=BASIS,task_ids=(task,))['id']
        self.effect('version.confirm',task,version,project=project)
        return task, version, artifact

    def submit(self, task, version):
        return self.effect('task.submit',task,version,dict(basis=BASIS))

    def human(self, task, version):
        return self.effect('acceptance.human',task,version,dict(decision='accept',basis=BASIS))

    def resolve(self, task, decision='continue', reason=None):
        reason = reason or self.value(task)['review_reasons'][0]
        return self.effect('recheck.resolve',task,reason['version_id'],dict(reason_id=reason['id'],decision=decision,basis=BASIS))

    def resolve_all(self, task):
        for reason in self.value(task)['review_reasons']:
            self.resolve(task,reason=reason)

    def edge(self, predecessor, successor):
        return self.effect('dependency.add',successor,payload=dict(predecessor_id=predecessor,basis=BASIS))

    def check_run(self, task, version, config=JSON_CONFIG):
        with self.work() as s:
            return s.run_check(self.p,task,version,config)

    def grant(self, task, version, config=JSON_CONFIG, expiry=None):
        previous={a['id'] for a in self.state()['authorizations']}
        self.effect('check.authorize',task,version,dict(config=config,expires_at=expiry or (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),scope='accept-exact-version',basis=BASIS))
        created=[a for a in self.state()['authorizations'] if a['id'] not in previous]
        self.assertEqual(len(created),1)
        return created[0]

    def auto_request(self, task, version, run, grant):
        return dict(request_key=str(uuid4()),base_revision=self.state()['project']['revision'],task_id=task,
                    version_id=version,check_id=run['id'],authorization_id=grant['id'])

    def auto(self, request):
        with self.work() as s:
            return s.accept_pre_authorized(self.p,request)

    def snapshot(self):
        with connect(self.db) as c:
            return {table:[tuple(r) for r in c.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                    for table in ('projects',)+ENTITY_TABLES+RELATION_TABLES}


class LifecycleTests(Journey):
    def test_oversized_config_is_rejected_before_canonical_or_execute_allocation(self):
        t,v,_=self.task()
        for configuration in ({'unused':'x'*(8*1024*1024)}, {'a':'x'*9000,'b':'x'*9000},{'unused':'界'*6000}):
            before=self.snapshot()
            with patch('nextrelay.lifecycle.canonical',side_effect=AssertionError('oversized config reached canonical')):
                with self.assertRaisesRegex(ChangeError,'check_config_limit'):self.check_run(t,v,configuration)
            with patch('nextrelay.checks.canonical',side_effect=AssertionError('oversized config reached canonical')):
                with self.assertRaisesRegex(ChangeError,'check_config_limit'):checks.config(configuration)
            self.assertEqual(before,self.snapshot())

    def test_goal_returning_to_old_value_does_not_revive_old_automatic_authority(self):
        t,v,_=self.task();self.submit(t,v);grant=self.grant(t,v);run=self.check_run(t,v)
        for goal in ('changed goal','Synthetic goal synthetic task'):
            self.effect('task.update',t,payload=dict(goal=goal));self.resolve_all(t)
        with self.assertRaisesRegex(ChangeError,'authorization_or_check_out_of_scope'):self.auto(self.auto_request(t,v,run,grant))
        fresh_grant=self.grant(t,v)
        with self.assertRaises(ChangeError):self.auto(self.auto_request(t,v,run,fresh_grant))
        fresh_run=self.check_run(t,v)
        with self.assertRaises(ChangeError):self.auto(self.auto_request(t,v,fresh_run,grant))
        self.auto(self.auto_request(t,v,fresh_run,fresh_grant))
        self.assertEqual(self.value(t)['validity'],'applicable')

    def test_rework_same_version_does_not_revive_old_check_or_grant(self):
        t,v,_=self.task();self.submit(t,v);grant=self.grant(t,v);run=self.check_run(t,v)
        for goal in ('changed goal','Synthetic goal synthetic task'):self.effect('task.update',t,payload=dict(goal=goal))
        self.resolve(t);self.resolve(t,'rework');self.submit(t,v)
        with self.assertRaisesRegex(ChangeError,'authorization_or_check_out_of_scope'):self.auto(self.auto_request(t,v,run,grant))
        self.assertEqual(self.value(t)['lifecycle'],'awaiting-acceptance')
        self.assertEqual(self.state()['acceptances'],[])

    def test_oversized_body_is_not_loaded_or_sent_to_executor_before_size_gate(self):
        t,v,_=self.task('oversized','x'*(8*1024*1024))
        original=Store._get
        def guard(store,project,kind,identity):
            if kind=='artifact_versions':self.fail('unbounded artifact row loaded before size gate')
            return original(store,project,kind,identity)
        with patch.object(Store,'_get',guard),patch.object(checks,'execute',side_effect=AssertionError('oversized body reached executor')):
            run=self.check_run(t,v)
        self.assertEqual(run['result'],'error')
        with self.work(False) as s:self.assertEqual(s.get(self.p,'evidence',run['evidence_id'])['result'],'error')
        for index,body in enumerate(('x'*262144,'界'*87381,'界'*87382)):
            task,version,_=self.task('byte boundary '+str(index),body)
            config=dict(protocol='builtin-v1',type='content-assertions',rules=dict(required=[body[0]]))
            self.assertEqual(self.check_run(task,version,config)['result'],'error' if len(body.encode('utf-8'))>262144 else 'pass')

    def test_real_expiry_and_invalid_scope_do_not_authorize_acceptance(self):
        t,v,_=self.task();self.submit(t,v)
        for scope,expiry in [('any-state',(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()),
                             ('accept-exact-version',(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()),
                             ('accept-exact-version','2030-01-01')]:
            with self.assertRaises(ChangeError):self.save('check.authorize',t,v,dict(config=JSON_CONFIG,expires_at=expiry,scope=scope,basis=BASIS))
        grant=self.grant(t,v,expiry=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat())
        run=self.check_run(t,v)
        time.sleep(1.05)
        with self.assertRaisesRegex(ChangeError,'authorization_expired'):self.auto(self.auto_request(t,v,run,grant))
        self.assertEqual(self.value(t)['lifecycle'],'awaiting-acceptance')

    def test_full_path_shortcut_and_audited_exact_human_decision(self):
        a,av,_ = self.task('normal')
        self.effect('task.start',a,payload=dict(basis=BASIS))
        self.submit(a,av); self.human(a,av)
        self.assertEqual(self.value(a)['lifecycle'],'accepted')
        self.assertEqual(self.value(a)['validity'],'applicable')
        b,bv,_ = self.task('restored external work')
        self.submit(b,bv); self.human(b,bv)
        state = self.state()
        events = [e for e in state['events'] if e['task_id']==b]
        self.assertEqual([e['event'] for e in events],['submit','accept'])
        acceptance = next(a for a in state['acceptances'] if a['task_id']==b)
        self.assertEqual((acceptance['version_id'],acceptance['conditions_version'],acceptance['created_by'],acceptance['mode']),
                         (bv,1,'dev-t05','human'))
        self.assertIsNone(acceptance['check_id'])
        self.assertEqual(state['readiness'],'not-evaluated')
        with self.work(False) as s:
            self.assertEqual(s.get(self.p,'artifact_versions',bv)['content'],'{"status":"ok"}')
            self.assertTrue(any(a['operation']=='acceptance.human' for a in [json.loads(r['effect_json']) for r in s.records(self.p,'applied_changes')]))

    def test_illegal_lifecycle_and_forged_or_missing_decisions_rejected(self):
        t,v,_ = self.task()
        before = self.snapshot()
        for op,payload in [('acceptance.human',dict(decision='accept',basis=BASIS)),('task.submit',dict(basis=BASIS,subject='user'))]:
            with self.assertRaises(ChangeError):self.save(op,t,v,payload)
        self.assertEqual(self.snapshot(),before)
        self.submit(t,v)
        for payload in (dict(basis=BASIS),dict(decision='claimed-accepted',basis=BASIS),dict(decision='accept',basis=''),dict(decision='accept',basis=BASIS,subject='owner')):
            with self.assertRaises(ChangeError):self.save('acceptance.human',t,v,payload)
        for op in ('task.start','task.submit'):
            with self.assertRaises(ChangeError):self.save(op,t,v if op=='task.submit' else None,dict(basis=BASIS))
        self.human(t,v)
        with self.assertRaises(ChangeError):self.save('task.submit',t,v,dict(basis=BASIS))

    def test_real_checks_success_failure_missing_malformed_and_unsupported(self):
        cases = [('{"status":"ok"}',JSON_CONFIG,'pass'),('{"status":"bad"}',JSON_CONFIG,'fail'),
                 ('{}',JSON_CONFIG,'missing'),('',JSON_CONFIG,'missing'),('[]',JSON_CONFIG,'fail'),
                 ('{"status":',JSON_CONFIG,'error'),('{"status":"ok","status":"ok"}',JSON_CONFIG,'error'),
                 ('{"status":NaN}',JSON_CONFIG,'error'),('x',dict(protocol='builtin-v1',type='shell',rules={}), 'error'),
                 ('# Required\nbody',dict(protocol='builtin-v1',type='document-sections',rules=dict(required=['Required'])),'pass'),
                 ('```\n# Required\n```',dict(protocol='builtin-v1',type='document-sections',rules=dict(required=['Required'])),'missing'),
                 ('literal payload',dict(protocol='builtin-v1',type='content-assertions',rules=dict(required=['payload'])),'pass'),
                 ('literal payload',dict(protocol='builtin-v1',type='content-assertions',rules=dict(required=['absent'])),'missing')]
        for i,(body,config,expected) in enumerate(cases):
            with self.subTest(i=i):
                t,v,_ = self.task(str(i),body)
                self.submit(t,v)
                revision = self.state()['project']['revision']
                run = self.check_run(t,v,config)
                self.assertEqual(run['result'],expected)
                self.assertTrue(run['details'])
                self.assertEqual(self.value(t)['lifecycle'],'awaiting-acceptance')
                self.assertEqual(self.state()['project']['revision'],revision)
                with self.work(False) as s:
                    self.assertEqual(s.get(self.p,'check_results',run['check_result_id'])['configuration_version'],digest(config))
        self.assertEqual(self.state()['acceptances'],[])

    def test_checker_limits_and_inert_content(self):
        for label,body in [('bytes','x'*262145),('nesting','['*40+'0'+']'*40),('nodes','['+','.join('0' for _ in range(4097))+']')]:
            t,v,_ = self.task(label,body)
            self.assertEqual(self.check_run(t,v)['result'],'error')
        t,v,_ = self.task('injection','{"status":"ok", "command":"__import__(os).system(delete)","approved":true}')
        self.assertEqual(self.check_run(t,v)['result'],'pass')
        self.assertEqual(self.value(t)['lifecycle'],'todo')
        for config in (dict(protocol='builtin-v1',type='content-assertions',rules=dict(required=['x']*65)),dict(protocol='builtin-v1',type='json-object',rules=dict(required=['status'],equals=dict(status='ok'),command='bad'))):
            self.assertEqual(self.check_run(t,v,config)['result'],'error')
        with self.assertRaises(ChangeError):self.check_run(t,v,{'large':'x'*17000})
        deep = {}; cur=deep
        for _ in range(34):cur['nested']={};cur=cur['nested']
        with self.assertRaises(ChangeError):self.check_run(t,v,deep)

    def test_pre_authorization_accepts_actual_pass_without_second_human_decision(self):
        t,v,_ = self.task();self.submit(t,v)
        grant = self.grant(t,v);run = self.check_run(t,v)
        request = self.auto_request(t,v,run,grant)
        result = self.auto(request)
        self.assertEqual(self.value(t)['validity'],'applicable')
        self.assertEqual(self.value(t)['lifecycle'],'accepted')
        acceptance = self.state()['acceptances'][0]
        self.assertEqual((acceptance['check_id'],acceptance['authorization_id'],acceptance['mode']), (run['id'],grant['id'],'check'))
        before = self.snapshot()
        self.assertEqual(self.auto(request),result)
        self.assertEqual(self.snapshot(),before)
        with self.assertRaisesRegex(ChangeError,'idempotency_key_reused'):self.auto(dict(request,version_id='wrong'))
        with self.assertRaises(ChangeError):self.auto(dict(request,request_key='changed-key'))
        self.assertEqual(self.snapshot(),before)

    def test_no_grant_wrong_task_wrong_config_stale_context_and_expiry(self):
        t,v,_ = self.task();self.submit(t,v)
        grant = self.grant(t,v);run = self.check_run(t,v)
        request = self.auto_request(t,v,run,grant)
        with self.assertRaises(AccessError):self.auto(dict(request,authorization_id=str(uuid4())))
        other,ov,_ = self.task('other');self.submit(other,ov)
        wrongrun = self.check_run(other,ov)
        with self.assertRaises(ChangeError):self.auto(dict(request,base_revision=self.state()['project']['revision'],check_id=wrongrun['id']))
        alternate = self.check_run(t,v,dict(protocol='builtin-v1',type='content-assertions',rules=dict(required=['ok'])))
        with self.assertRaises(ChangeError):self.auto(dict(request,base_revision=self.state()['project']['revision'],check_id=alternate['id']))
        with patch.object(Lifecycle,'expiry',side_effect=ChangeError('authorization_expired_or_invalid')):
            with self.assertRaisesRegex(ChangeError,'expired'):self.auto(dict(request,base_revision=self.state()['project']['revision']))
        self.effect('task.update',t,payload=dict(goal='Changed business requirement'))
        with self.assertRaises(ChangeError):self.auto(dict(request,base_revision=self.state()['project']['revision']))
        self.assertEqual(self.state()['acceptances'],[])
        self.assertEqual(self.value(t)['lifecycle'],'awaiting-acceptance')

    def test_actual_failure_does_not_auto_accept_but_human_path_remains(self):
        t,v,_ = self.task(body='{"status":"bad"}');self.submit(t,v)
        grant=self.grant(t,v);run=self.check_run(t,v)
        with self.assertRaisesRegex(ChangeError,'actual_matching_pass_required'):self.auto(self.auto_request(t,v,run,grant))
        self.assertEqual(self.value(t)['lifecycle'],'awaiting-acceptance')
        self.human(t,v)
        self.assertEqual(self.value(t)['validity'],'applicable')
        self.assertEqual(self.state()['acceptances'][0]['mode'],'human')

    def test_new_version_and_other_task_do_not_inherit_check_or_acceptance(self):
        t,v,artifact = self.task();self.submit(t,v);grant=self.grant(t,v);run=self.check_run(t,v)
        self.auto(self.auto_request(t,v,run,grant))
        with self.work() as s:
            new = s.create_version(self.p,artifact,'{"status":"ok"}',reason=BASIS,task_ids=(t,))['id']
        self.effect('version.confirm',t,new)
        value=self.value(t)
        self.assertEqual(value['lifecycle'],'accepted')
        self.assertEqual(value['version_id'],new)
        self.assertEqual(value['validity'],'pending-review')
        self.assertEqual(value['current_acceptance_ids'],[])
        self.assertEqual(len(value['historical_acceptance_ids']),1)
        other = self.effect('task.create',payload=dict(title='other version reuse'))['target_id']
        self.effect('version.confirm',other,new)
        self.assertEqual(self.value(other)['validity'],'unknown')
        self.assertEqual(self.value(other)['historical_acceptance_ids'],[])
        with self.assertRaises(ChangeError):self.check_run(t,v)

    def test_conditions_frozen_and_legacy_claims_cannot_forge_execution(self):
        t,v,_=self.task();self.submit(t,v);grant=self.grant(t,v)
        with self.work() as s:
            evidence = s.record_evidence(self.p,v,task_id=t,kind='human-basis',mechanism='builtin-v1',subject='user',
                result='pass',conditions_version=1,configuration_version=digest(JSON_CONFIG))
            fake = s.record_check(self.p,evidence['id'],mechanism='builtin-v1',subject='user',configuration_version=digest(JSON_CONFIG),result='pass')
        with self.assertRaises(AccessError):self.auto(self.auto_request(t,v,fake,grant))
        with self.assertRaises(ChangeError):self.save('task.update',t,payload=dict(completion_conditions='changed'))
        for field in ('conditions_version','completion_conditions'):
            with connect(self.db) as c,self.assertRaises(sqlite3.IntegrityError):
                c.execute(f'UPDATE tasks SET {field}=? WHERE id=?',(2 if field=='conditions_version' else 'changed',t))
        self.assertEqual(self.state()['acceptances'],[])

    def test_display_title_preserves_lifecycle_and_business_validity(self):
        t,v,_=self.task();self.submit(t,v);self.human(t,v)
        old=self.value(t)
        self.effect('task.update',t,payload=dict(title='display only'))
        now=self.value(t)
        self.assertEqual((now['lifecycle'],now['validity'],now['current_acceptance_ids']),
                         (old['lifecycle'],old['validity'],old['current_acceptance_ids']))
        self.assertEqual(now['review_reasons'],[])
        self.effect('task.update',t,payload=dict(title='display plus unchanged goal',goal='Synthetic goal synthetic task'))
        current=self.value(t)
        self.assertEqual((current['lifecycle'],current['validity'],current['current_acceptance_ids']),
                         (old['lifecycle'],old['validity'],old['current_acceptance_ids']))
        self.assertEqual(current['review_reasons'],[])


class DependencyTests(Journey):
    def test_reverse_continue_retains_actionable_causes_then_topological_recovery(self):
        a,av,_=self.task('A');b,bv,_=self.task('B');c,cv,_=self.task('C')
        self.edge(a,b);self.edge(b,c);self.resolve_all(b);self.resolve_all(c)
        for task,version in ((a,av),(b,bv),(c,cv)):self.submit(task,version);self.human(task,version)
        self.effect('task.update',a,payload=dict(goal='Re-evaluate chain'))
        for task in (c,b):
            before=self.snapshot()
            with self.assertRaisesRegex(ChangeError,'upstream_recheck_unresolved'):self.resolve(task)
            self.assertEqual(before,self.snapshot())
            self.assertTrue(self.value(task)['review_reasons'])
        for task in (a,b,c):
            self.resolve_all(task)
            self.assertEqual(self.value(task)['validity'],'applicable')
        self.assertFalse(self.value(c)['blockers'])

    def test_new_version_continue_cannot_close_its_only_actionable_reason_without_acceptance(self):
        task,version,artifact=self.task();self.submit(task,version);self.human(task,version)
        with self.work() as s:new=s.create_version(self.p,artifact,'new body',reason=BASIS,task_ids=(task,))['id']
        self.effect('version.confirm',task,new)
        with self.assertRaisesRegex(ChangeError,'current_version_acceptance_required_for_continue'):self.resolve(task)
        self.assertTrue(self.value(task)['review_reasons'])
        self.resolve(task,'rework');self.submit(task,new);self.human(task,new)
        self.assertEqual(self.value(task)['validity'],'applicable')

    def test_ancestor_returning_to_old_value_cannot_revive_downstream_check_or_grant(self):
        a,av,_=self.task('A');b,bv,_=self.task('B');c,cv,_=self.task('C')
        self.edge(a,b);self.edge(b,c);self.resolve_all(b);self.resolve_all(c)
        for task,version in ((a,av),(b,bv)):self.submit(task,version);self.human(task,version)
        self.submit(c,cv);grant=self.grant(c,cv);run=self.check_run(c,cv)
        for goal in ('different A','Synthetic goal A'):
            self.effect('task.update',a,payload=dict(goal=goal))
            for task in (a,b,c):self.resolve_all(task)
        with self.assertRaisesRegex(ChangeError,'authorization_or_check_out_of_scope'):self.auto(self.auto_request(c,cv,run,grant))
        self.assertEqual(self.value(a)['validity'],'applicable')
        self.assertEqual(self.value(b)['validity'],'applicable')

    def test_metadata_with_redundant_goal_does_not_invalidate_downstream_or_actual_check(self):
        a,av,_=self.task('A');b,bv,_=self.task('B')
        self.edge(a,b);self.resolve_all(b);self.submit(a,av);self.human(a,av)
        self.submit(b,bv);grant=self.grant(b,bv);run=self.check_run(b,bv)
        self.effect('task.update',a,payload=dict(title='new display',goal='Synthetic goal A'))
        self.assertEqual(self.value(a)['validity'],'applicable')
        self.assertEqual(self.value(b)['review_reasons'],[])
        self.auto(self.auto_request(b,bv,run,grant))
        self.assertEqual(self.value(b)['validity'],'applicable')

    def test_single_cause_rework_invalidates_root_and_propagates_without_reset(self):
        a,av,_=self.task('A');b,bv,_=self.task('B')
        self.edge(a,b);self.resolve_all(b)
        for t,v in ((a,av),(b,bv)):self.submit(t,v);self.human(t,v)
        self.effect('task.update',a,payload=dict(goal='Requires rework'))
        self.resolve(a,'rework')
        self.assertEqual(self.value(a)['lifecycle'],'in-progress')
        self.assertEqual(self.value(a)['validity'],'inapplicable')
        self.assertEqual(self.value(a)['review_reasons'],[])
        self.assertEqual(self.value(b)['lifecycle'],'accepted')
        self.assertTrue(self.value(b)['blockers'])
        event=next(e for e in self.state()['events'] if e['event']=='rework')
        with self.work(False) as s:self.assertEqual(s.get(self.p,'attempts',event['attempt_id'])['task_id'],a)
        self.submit(a,av);self.human(a,av)
        self.assertEqual(self.value(a)['validity'],'applicable')
        self.assertEqual(len(self.value(a)['current_acceptance_ids']),1)
        self.assertEqual(len(self.value(a)['historical_acceptance_ids']),2)
        self.assertTrue(self.value(b)['review_reasons'])

    def test_any_confirmed_related_artifact_change_reaches_all_downstream(self):
        a,av,artifact=self.task('A');b,_,_=self.task('B');c,_,_=self.task('C')
        self.edge(a,b);self.edge(b,c);self.resolve_all(b);self.resolve_all(c)
        self.submit(a,av);self.human(a,av)
        with self.work() as s:
            another=s.create_artifact(self.p,'second related artifact')['id']
            second=s.create_version(self.p,another,'ancillary but relevant result',reason=BASIS,task_ids=(a,))['id']
        self.effect('version.confirm',a,second)
        self.assertTrue(self.value(c)['review_reasons'])
        self.resolve(a,'rework');self.submit(a,second);self.human(a,second)
        self.resolve_all(b);self.resolve_all(c)
        with self.work() as s:
            revised=s.create_version(self.p,artifact,'changed original related artifact',reason=BASIS,task_ids=(a,))['id']
        self.effect('version.confirm',a,revised)
        self.assertTrue(self.value(c)['review_reasons'])
        self.assertEqual(self.value(a)['current_acceptance_ids'],[])

    def test_diamond_all_hard_predecessors_and_manual_acceptance_does_not_bypass(self):
        a,av,_=self.task('A');b,bv,_=self.task('B');c,cv,_=self.task('C');d,dv,_=self.task('D')
        for x,y in ((a,b),(a,c),(b,d),(c,d)):self.edge(x,y)
        for t in (b,c,d):self.resolve_all(t)
        self.assertEqual(len(self.value(d)['blockers']),2)
        self.submit(b,bv);self.human(b,bv)
        self.assertTrue(self.value(b)['blockers'])
        self.assertEqual(len(self.value(d)['blockers']),2)
        self.submit(a,av);self.human(a,av)
        self.assertFalse(self.value(b)['blockers'])
        self.assertEqual(len(self.value(d)['blockers']),1)
        self.submit(c,cv);self.human(c,cv)
        self.assertFalse(self.value(d)['blockers'])
        self.assertTrue(self.value(d)['executable'])
        with self.work() as s:
            artifact=s.create_artifact(self.p,'baseline')['id']
            baseline=s.create_version(self.p,artifact,'synthetic changed baseline',reason=BASIS)['id']
        self.effect('baseline.set',artifact,baseline)
        self.assertTrue(self.value(d)['blockers'])
        self.assertEqual(self.value(a)['lifecycle'],'accepted')
        self.assertEqual(self.value(a)['validity'],'pending-review')

    def test_self_cross_project_dangling_duplicate_and_indirect_cycles(self):
        a,_,_=self.task('A');b,_,_=self.task('B');c,_,_=self.task('C');foreign,_,_=self.task('foreign',project=self.q)
        for x,y in ((a,a),(foreign,a),(str(uuid4()),a)):
            with self.assertRaises((ChangeError,AccessError)):self.edge(x,y)
        self.edge(a,b);self.edge(b,c)
        for x,y in ((a,b),(b,a),(c,a)):
            with self.assertRaises(ChangeError):self.edge(x,y)
        self.assertEqual(len(self.state()['derived']['dependencies']),2)

    def test_batch_union_and_two_independent_connections_cannot_create_cycle(self):
        a,_,_=self.task('A');b,_,_=self.task('B')
        candidates=[self.save('dependency.add',y,payload=dict(predecessor_id=x,basis=BASIS)) for x,y in ((a,b),(b,a))]
        reviews=[self.approve(c) for c in candidates]
        base=candidates[0]['spec']['base_revision']
        request=dict(request_key='batch-cycle',base_revision=base,selection=[dict(candidate_id=c['candidate_id'],review_id=r['id']) for c,r in zip(candidates,reviews)])
        before=self.snapshot()
        with self.assertRaisesRegex(ChangeError,'dependency_cycle'):
            with self.work() as s:s.commit_candidates(self.p,request)
        self.assertEqual(self.snapshot(),before)
        barrier=threading.Barrier(2)
        def commit(i):
            barrier.wait(timeout=10)
            try:
                with self.work() as s:s.commit_candidates(self.p,self.request(candidates[i],reviews[i],str(i)))
                return 'committed'
            except ChangeError as e:return e.code
        with ThreadPoolExecutor(2) as executor:results=list(executor.map(commit,range(2)))
        self.assertCountEqual(results,['committed','revision_conflict'])
        self.assertEqual(len(self.state()['derived']['dependencies']),1)
        with self.assertRaises(ChangeError):self.edge(b,a) if self.state()['derived']['dependencies'][0]['predecessor_id']==a else self.edge(a,b)

    def test_chain_propagates_through_accepted_middle_and_keeps_history(self):
        a,av,_=self.task('A');b,bv,_=self.task('B');c,cv,_=self.task('C')
        self.edge(a,b);self.edge(b,c)
        self.resolve_all(b);self.resolve_all(c)
        for t,v in ((a,av),(b,bv),(c,cv)):self.submit(t,v);self.human(t,v)
        before=self.state()
        self.effect('task.update',a,payload=dict(goal='impact downstream'))
        for t in (a,b,c):
            self.assertEqual(self.value(t)['lifecycle'],'accepted')
            self.assertEqual(self.value(t)['validity'],'pending-review')
        self.assertEqual(self.state()['acceptances'],before['acceptances'])
        self.assertEqual(self.state()['events'],before['events'])
        self.assertTrue(self.value(c)['blockers'])
        self.resolve(a)
        self.assertEqual(self.value(a)['validity'],'applicable')
        self.assertTrue(self.value(c)['review_reasons'])
        self.assertTrue(self.value(c)['blockers'])
        self.resolve(b)
        self.assertEqual(self.value(b)['validity'],'applicable')
        self.assertTrue(self.value(c)['review_reasons'])
        self.resolve(c)
        self.assertEqual(self.value(c)['validity'],'applicable')
        self.assertFalse(self.value(c)['blockers'])

    def test_chain_in_progress_and_multiple_reasons_evidence_and_rework(self):
        a,av,_=self.task('A');b,bv,_=self.task('B');c,_,_=self.task('C')
        self.edge(a,b);self.edge(b,c);self.resolve_all(b);self.resolve_all(c)
        self.submit(a,av);self.human(a,av)
        self.effect('task.start',b,payload=dict(basis=BASIS))
        self.effect('task.update',a,payload=dict(goal='first change'))
        self.effect('task.update',a,payload=dict(goal='second change'))
        self.assertEqual(self.value(b)['lifecycle'],'in-progress')
        self.assertEqual(len(self.value(c)['review_reasons']),2)
        self.resolve(c,'needs-evidence')
        self.assertEqual(len(self.value(c)['review_reasons']),2)
        with self.assertRaisesRegex(ChangeError,'upstream_recheck_unresolved'):self.resolve(c)
        self.resolve_all(a)
        # Resolve one independent B cause after its upstream is settled, then explicitly rework the other.
        self.resolve(b)
        self.assertEqual(len(self.value(b)['review_reasons']),1)
        self.submit(b,bv);self.human(b,bv)
        self.assertEqual(self.value(b)['validity'],'pending-review')
        self.resolve(b,'rework')
        self.assertEqual(self.value(b)['lifecycle'],'in-progress')
        self.assertEqual(len(self.value(b)['historical_acceptance_ids']),1)
        self.assertTrue(self.value(c)['review_reasons'])
        self.resolve(c)
        self.assertEqual(len(self.value(c)['review_reasons']),2)

    def test_same_revision_derived_read_and_blocked_start(self):
        a,_,_=self.task('A');b,_,_=self.task('B');self.edge(a,b)
        with self.assertRaisesRegex(ChangeError,'task_not_executable'):self.save('task.start',b,payload=dict(basis=BASIS))
        state=self.state()
        self.assertEqual(state['derived_state'],'current')
        self.assertEqual(state['derived']['revision'],state['project']['revision'])
        self.assertTrue(all(t['revision']==state['project']['revision'] for t in state['derived']['tasks']))
        with connect(self.db) as c:
            stored=json.loads(c.execute('SELECT state_json FROM derived_snapshots WHERE project_id=? AND revision=?',(self.p,state['project']['revision'])).fetchone()[0])
        self.assertEqual(stored,state['derived'])


class ReliabilityTests(Journey):
    def test_base_provenance_append_cannot_silently_stale_current_formal_snapshot(self):
        t,v,_=self.task();self.submit(t,v);self.human(t,v)
        before=self.state()
        with self.work() as s:source=s.create_source(self.p,reference='synthetic://new-unreviewed-source')['id']
        with self.assertRaises(sqlite3.IntegrityError):
            with self.work() as s:s.link_version_source(self.p,v,source)
        self.assertEqual(before,self.state())

    def test_runnable_readme_example(self):
        result=subprocess.run([sys.executable,'-m','examples.t05_synthetic'],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Synthetic T05 example verified; schema v4',result.stdout)
    def test_new_entry_ownership_and_identity_all_enforced(self):
        t,v,_=self.task()
        calls=[lambda s:s.run_check(self.p,t,v,JSON_CONFIG),lambda s:s.accept_pre_authorized(self.p,{}),
               lambda s:s.formal_state(self.p),lambda s:s.save_candidate(self.p,dict(base_revision=2,operation='task.start',target_id=t,payload=dict(basis=BASIS)))]
        for call in calls:
            with self.assertRaises(AccessError):
                with self.work(owner=Principal('dev-other')) as s:call(s)
        with self.assertRaises(AccessError):
            with unit_of_work(self.db,None,write=True):pass

    def test_faults_in_acceptance_dependency_propagation_revision_audit_idempotency_and_derived_rollback(self):
        a,av,_=self.task('A');b,_,_=self.task('B');self.submit(a,av)
        candidates=[self.save('acceptance.human',a,av,dict(decision='accept',basis=BASIS)),
                    self.save('dependency.add',b,payload=dict(predecessor_id=a,basis=BASIS))]
        for candidate in candidates:
            review=self.approve(candidate);request=self.request(candidate,review)
            for action,table in [(sqlite3.SQLITE_INSERT,t) for t in ('change_commits','effective_changes','applied_changes','derived_snapshots')]+[(sqlite3.SQLITE_UPDATE,'projects')]+[(sqlite3.SQLITE_INSERT,t) for t in
                (('acceptances','formal_task_states','task_events','evidence') if candidate['operation']=='acceptance.human' else ('dependencies','review_reasons'))]:
                before=self.snapshot()
                with self.subTest(table=table,operation=candidate['operation']),self.assertRaises(sqlite3.DatabaseError):
                    with self.work() as s:
                        s._connection.set_authorizer(lambda code,arg,*_:sqlite3.SQLITE_DENY if code==action and arg==table else sqlite3.SQLITE_OK)
                        s.commit_candidates(self.p,request)
                self.assertEqual(self.snapshot(),before)

    def test_auto_accept_last_step_failure_rolls_back_every_formal_effect(self):
        t,v,_=self.task();self.submit(t,v);grant=self.grant(t,v);run=self.check_run(t,v)
        request=self.auto_request(t,v,run,grant);before=self.snapshot()
        with self.assertRaises(sqlite3.DatabaseError):
            with self.work() as s:
                s._connection.set_authorizer(lambda code,arg,*_:sqlite3.SQLITE_DENY if code==sqlite3.SQLITE_INSERT and arg=='auto_requests' else sqlite3.SQLITE_OK)
                s.accept_pre_authorized(self.p,request)
        self.assertEqual(self.snapshot(),before)
        self.auto(request)
        self.assertEqual(self.value(t)['lifecycle'],'accepted')

    def test_failure_during_check_execution_rolls_back_partial_evidence(self):
        t,v,_=self.task();before=self.snapshot()
        with self.assertRaises(sqlite3.DatabaseError):
            with self.work() as s:
                s._connection.set_authorizer(lambda code,arg,*_:sqlite3.SQLITE_DENY if code==sqlite3.SQLITE_INSERT and arg=='check_executions' else sqlite3.SQLITE_OK)
                s.run_check(self.p,t,v,JSON_CONFIG)
        self.assertEqual(before,self.snapshot())

    def test_dependency_and_acceptance_commit_retry_and_changed_key_cannot_reapply(self):
        a,av,_=self.task('A');b,_,_=self.task('B')
        for op,t,v,payload in [('dependency.add',b,None,dict(predecessor_id=a,basis=BASIS)),('task.submit',a,av,dict(basis=BASIS)),('acceptance.human',a,av,dict(decision='accept',basis=BASIS))]:
            c=self.save(op,t,v,payload);r=self.approve(c);req=self.request(c,r)
            with self.work() as s:result=s.commit_candidates(self.p,req)
            before=self.snapshot()
            with self.work() as s:self.assertEqual(s.commit_candidates(self.p,req),result)
            with self.assertRaises(ChangeError):
                with self.work() as s:s.commit_candidates(self.p,dict(req,request_key='changed-key'))
            self.assertEqual(self.snapshot(),before)

    def test_real_process_interruption_before_commit_and_lost_response_after_commit(self):
        t,v,_=self.task();self.submit(t,v)
        candidate=self.save('acceptance.human',t,v,dict(decision='accept',basis=BASIS));review=self.approve(candidate)
        request=self.request(candidate,review)
        script='''
import json,os,sys
from pathlib import Path
from nextrelay.auth import Principal
from nextrelay.store import unit_of_work
from nextrelay.lifecycle import Lifecycle
if sys.argv[4]=='before':
    original=Lifecycle.sync
    def crash(self,*args):
        original(self,*args)
        os._exit(51)
    Lifecycle.sync=crash
with unit_of_work(Path(sys.argv[1]),Principal('dev-t05'),write=True) as s:
    s.commit_candidates(sys.argv[2],json.loads(sys.argv[3]))
os._exit(52)
'''
        before=self.snapshot()
        result=subprocess.run([sys.executable,'-c',script,str(self.db),self.p,json.dumps(request),'before'],capture_output=True,timeout=20)
        self.assertEqual(result.returncode,51,result.stderr)
        self.assertEqual(before,self.snapshot())
        result=subprocess.run([sys.executable,'-c',script,str(self.db),self.p,json.dumps(request),'after'],capture_output=True,timeout=20)
        self.assertEqual(result.returncode,52,result.stderr)
        committed=self.snapshot()
        with self.work() as s:self.assertEqual(s.commit_candidates(self.p,request),s.commit_result(self.p,request['request_key']))
        self.assertEqual(committed,self.snapshot())
        self.assertEqual(self.value(t)['validity'],'applicable')

    def test_caught_error_dooms_unit_and_all_new_records_are_append_only(self):
        t,v,_=self.task();self.submit(t,v);self.human(t,v)
        for table in ('task_events','acceptances','derived_snapshots'):
            with connect(self.db) as c,self.assertRaises(sqlite3.IntegrityError):c.execute(f'DELETE FROM {table}')
        before=self.snapshot()
        with self.assertRaises(TransactionAborted):
            with self.work() as s:
                s.create_source(self.p,reference='synthetic://must-rollback')
                try:s.accept_pre_authorized(self.p,{})
                except ChangeError:pass
        self.assertEqual(before,self.snapshot())


if __name__=='__main__':
    unittest.main()
