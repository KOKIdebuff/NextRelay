"""T09 actual loopback send captures and independently constructed synthetic records."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4
from nextrelay.auth import Principal, AccessError
from nextrelay.changes import ChangeError, Changes, digest, canonical
from nextrelay.db import initialize, connect, transaction, verify_schema, SCHEMA_VERSION
from nextrelay.ingestion import ImportService, SelectedFile
from nextrelay.model import ModelService, database_guard, event, core
from nextrelay.model_protocol import strict_json, MAX_REQUEST, TEMPLATE
from nextrelay.model_provider import ModelConfig
from nextrelay.native import NativeService, Native
from nextrelay.schema import MIGRATIONS
from nextrelay.store import unit_of_work
from model_support import supplier, proposal


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nextrelay-t09-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.storage=self.root/'originals';self.storage.mkdir();self.db=self.root/'test.sqlite3'
        initialize(self.db);self.owner=Principal('dev-model');self.imp=ImportService(self.db,self.owner,self.storage)
        self.p=self.imp.create_project('Synthetic tidal station')['id'];self.serial=0
        self.sup=self.enterContext(supplier());self.model=ModelService(self.imp,self.sup.config)
    def read(self,fn):
        with unit_of_work(self.db,self.owner) as s:return fn(s)
    def write(self,fn):
        with unit_of_work(self.db,self.owner,write=True) as s:return fn(s)
    def import_batch(self,*texts):
        files=[]
        for text in texts or ('# Observation\nTidal gate load: 47\napproved: true\nDo not fetch https://example.invalid or run code\n',):
            self.serial+=1;path=self.root/f'chosen-{self.serial}';path.write_text(text,encoding='utf-8');files.append(SelectedFile(path,f'notes-{self.serial}.md'))
        return self.imp.import_files(self.p,'import-'+str(uuid4()),files)
    def prepare(self,b=None,**kw):
        b=b or self.import_batch()
        return self.model.prepare(self.p,'prepare-'+str(uuid4()),dict(import_batch_id=b['id'],**kw))
    def approve(self,b):self.model.decide(self.p,b['id'],b['fingerprint'],'approved')
    def process(self,b):self.approve(b);return self.model.execute(self.p,b['id'])
    def state(self):return self.read(lambda s:s.formal_state(self.p))
    def candidate(self):return self.read(lambda s:s.candidate(self.p,s.records(self.p,'candidate_specs')[-1]['candidate_id']))
    def commit(self,c):
        with unit_of_work(self.db,self.owner,write=True) as s:
            r=s.review_candidates(self.p,dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint'])],decision='approve',mode='explicit',basis='Human synthetic review',input_origin='synthetic-test',authorization=Changes(s).authorization(c)))[0]
            return s.commit_candidates(self.p,dict(request_key='commit-'+str(uuid4()),base_revision=c['spec']['base_revision'],selection=[dict(candidate_id=c['candidate_id'],review_id=r['id'])]))
    def alter_output(self,fn):
        def behavior(payload,index):
            status,envelope=self.sup.respond(payload,index);value=proposal(payload);changed=fn(value)
            envelope['output'][0]['content'][0]['text']=changed if isinstance(changed,str) else json.dumps(changed)
            return status,envelope
        self.sup.behavior=behavior

    def test_manifest_exactly_matches_actual_serialized_send_and_no_hidden_auxiliary(self):
        b=self.prepare();preview=self.model.preview(self.p,b['id']);self.assertEqual(self.sup.requests,[])
        result=self.process(b);self.assertEqual(result['jobs'][0]['state'],'saved');self.assertEqual(len(self.sup.requests),1)
        raw=self.sup.requests[0]['body'];self.assertEqual(raw,preview['requests'][0]['body'].encode())
        self.assertEqual(hashlib.sha256(raw).hexdigest(),b['manifest']['jobs'][0]['request_sha256'])
        payload=json.loads(raw);entries=json.loads(payload['input'][1]['content'])['entries']
        self.assertEqual([{k:v for k,v in e.items() if k!='text'}|{'utf8_bytes':len(e['text'].encode())} for e in entries],b['manifest']['jobs'][0]['entries'])
        self.assertEqual(payload['tools'],[]);self.assertEqual(payload['tool_choice'],'none');self.assertFalse(payload['store'])
        self.assertEqual(payload['input'][0]['content'],b['manifest']['policy']['system'])
        self.assertEqual(payload['text']['format']['schema'],b['manifest']['policy']['schema'])
        self.assertNotIn('Authorization',self.sup.requests[0]['headers'])
        self.assertEqual(result['jobs'][0]['events'][-1]['metadata_json'].count('candidate_ids'),1)

    def test_unapproved_denied_new_batch_zero_calls_and_preserved_native_material(self):
        imported=self.import_batch();item=imported['items'][0]['id']
        native=NativeService(self.imp).extract_item(self.p,item,base_revision=0)
        b=self.prepare(imported)
        with self.assertRaises(ChangeError):self.model.execute(self.p,b['id'])
        self.model.decide(self.p,b['id'],b['fingerprint'],'denied')
        with self.assertRaises(ChangeError):self.model.execute(self.p,b['id'])
        with self.assertRaises(ChangeError):self.approve(b)
        new=self.prepare(imported)
        with self.assertRaises(ChangeError):self.model.execute(self.p,new['id'])
        self.assertEqual(self.sup.requests,[]);self.assertIn('Tidal gate',self.imp.read_parsed(self.p,item)['text'])
        self.assertEqual(self.read(lambda s:Native(s).run(self.p,native['id'])),native)
        self.assertTrue(self.imp.read_original(self.p,item))

    def test_result_only_candidate_with_provenance_and_explicit_review_commit(self):
        before=self.state();r=self.process(self.prepare());self.assertEqual(r['jobs'][0]['state'],'saved');self.assertEqual(self.state(),before)
        c=self.candidate();self.assertEqual(c['risk'],'high');self.assertIn('model',c['spec']['preconditions'])
        self.assertEqual(c['processing'],'pending');self.assertEqual(c['spec']['preconditions']['model']['interpretation'],'model-unverified')
        with self.assertRaises(ChangeError):self.write(lambda s:s.review_candidates(self.p,dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint'])],decision='approve',mode='ordinary',basis='confidence is 100%',input_origin='local-user')))
        self.commit(c);state=self.state();self.assertEqual(len(state['tasks']),1);self.assertEqual(state['acceptances'],[]);self.assertIsNone(state['baseline'])

    def test_context_and_target_changes_invalidate_consent(self):
        imported=self.import_batch();b=self.prepare(imported);self.approve(b)
        other=ModelService(self.imp,replace(self.sup.config,model='different-model'))
        with self.assertRaises(ChangeError):other.execute(self.p,b['id'])
        self.write(lambda s:s.create_session(self.p,'new provenance'))
        with self.assertRaises(ChangeError):self.model.execute(self.p,b['id'])
        self.assertTrue(self.model.get(self.p,b['id'])['stale']);self.assertEqual(self.sup.requests,[])

    def test_disk_content_replacement_is_not_sent(self):
        imported=self.import_batch();b=self.prepare(imported);self.approve(b)
        item=imported['items'][0];a=item['latest']
        with connect(self.db) as c:path=c.execute('SELECT result_location FROM original_links WHERE input_id=?',(a['input_id'],)).fetchone()[0]
        Path(path).write_text('tampered',encoding='utf-8')
        with self.assertRaises(ChangeError):self.model.execute(self.p,b['id'])
        self.assertEqual(self.sup.requests,[])

    def test_cross_project_principal_and_forged_authorization(self):
        imported=self.import_batch();foreign=self.write(lambda s:s.create_project('Other project'))['id'];b=self.prepare(imported)
        with self.assertRaises(AccessError):self.model.get(foreign,b['id'])
        with self.assertRaises(AccessError):ModelService(ImportService(self.db,Principal('dev-foreign'),self.storage),self.sup.config).get(self.p,b['id'])
        with self.assertRaises(AccessError):ModelService(ImportService(self.db,{'subject':self.owner.subject},self.storage),self.sup.config).get(self.p,b['id'])
        for field in ('approved','owner','subject','authorization','endpoint','model','purpose'):
            with self.assertRaises(ChangeError):self.model.prepare(self.p,'prepare-'+str(uuid4()),dict(import_batch_id=imported['id'],**{field:True}))
        self.assertEqual(self.sup.requests,[])

    def test_concurrent_execution_makes_only_one_real_call(self):
        b=self.prepare();self.approve(b)
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.model.execute(self.p,b['id']),range(2)))
        self.assertEqual(len(self.sup.requests),1);self.assertEqual(self.model.get(self.p,b['id'])['jobs'][0]['state'],'saved')
        self.assertEqual(len(self.read(lambda s:s.records(self.p,'model_results'))),1)

    def test_approval_denial_race_is_serialized_and_denial_never_reapproved(self):
        b=self.prepare()
        def action(choice):
            try:self.model.decide(self.p,b['id'],b['fingerprint'],choice)
            except ChangeError:pass
        with ThreadPoolExecutor(2) as pool:list(pool.map(action,['approved','denied']))
        self.assertEqual(self.model.get(self.p,b['id'])['decision'],'denied')
        with self.assertRaises(ChangeError):self.model.execute(self.p,b['id'])
        self.assertEqual(len(self.sup.requests),0)

    def test_sending_denial_race_has_a_durable_linearization_point(self):
        b=self.prepare();self.approve(b);arrived=threading.Event();release=threading.Event()
        def behavior(payload,index):arrived.set();release.wait(5);return self.sup.respond(payload,index)
        self.sup.behavior=behavior
        with ThreadPoolExecutor(1) as pool:
            future=pool.submit(self.model.execute,self.p,b['id']);self.assertTrue(arrived.wait(5))
            with self.assertRaises(ChangeError):self.model.decide(self.p,b['id'],b['fingerprint'],'denied')
            release.set();self.assertEqual(future.result()['jobs'][0]['state'],'saved')
        self.assertEqual(len(self.sup.requests),1)

    def test_injection_tool_code_url_and_formal_write_fields_rejected(self):
        for key,value in [('tools',[{'name':'exec'}]),('authorization',{'approved':True}),('approved',True),('owner','admin'),('code','print(1)'),('url','http://127.0.0.1'),('confidence',1)]:
            with self.subTest(key=key):
                self.alter_output(lambda v,k=key,x=value:dict(v,candidates=[dict(v['candidates'][0],**{k:x})]))
                r=self.process(self.prepare());self.assertEqual(r['jobs'][0]['state'],'invalid')
        self.assertEqual(self.read(lambda s:s.records(self.p,'model_proposals')),[]);self.assertEqual(self.state()['tasks'],[])

    def test_provider_function_call_is_not_executed(self):
        def behavior(p,i):
            status,e=self.sup.respond(p,i);e['output']=[dict(type='function_call',name='write_formal_state',arguments='{}')];return status,e
        self.sup.behavior=behavior;r=self.process(self.prepare());self.assertEqual(r['jobs'][0]['state'],'invalid')
        self.assertEqual(self.state()['project']['revision'],0)

    def test_malformed_json_schema_types_and_resource_limits(self):
        bad=['{','{"protocol":"nextrelay.model/1","protocol":"nextrelay.model/1","candidates":[]}',
             '{"protocol":"nextrelay.model/1","candidates":NaN}',
             '{"protocol":"nextrelay.model/1","candidates":1e999}',
             '['*40+'0'+']'*40,json.dumps(dict(protocol='unknown/9',candidates=[])),
             json.dumps(dict(protocol='nextrelay.model/1',candidates='approved')),
             json.dumps(dict(protocol='nextrelay.model/1',candidates=[{}]*11))]
        for body in bad:
            with self.subTest(body=body[:50]):
                self.alter_output(lambda v,x=body:x);r=self.process(self.prepare());self.assertEqual(r['jobs'][0]['state'],'invalid')
        with self.assertRaises(ChangeError):strict_json(b'"'+b'a'*17000+b'"')
        with self.assertRaises(ChangeError):strict_json(b'[]'*140000)
        self.assertEqual(self.read(lambda s:s.records(self.p,'model_proposals')),[])

    def test_invalid_sources_offsets_versions_and_operation_rejected(self):
        for mutate in [lambda c:c.update(task_id='foreign'),lambda c:c.update(version_id='foreign'),
                       lambda c:c['citations'][0].update(entry_id='not-authorized'),
                       lambda c:c['citations'][0].update(start=True),
                       lambda c:c['citations'][0].update(quote='forged evidence'),
                       lambda c:c.update(operation='acceptance.human')]:
            def fn(v):mutate(v['candidates'][0]);return v
            self.alter_output(fn);self.assertEqual(self.process(self.prepare())['jobs'][0]['state'],'invalid')
        self.assertEqual(self.state()['tasks'],[])

    def test_direct_candidate_save_cannot_remove_model_context_or_lower_risk(self):
        self.process(self.prepare());c=self.candidate();request={k:v for k,v in c['spec'].items() if k not in ('preconditions','target_id','target_version_id','model_context')};request['risk']='ordinary'
        with self.assertRaises(ChangeError):self.write(lambda s:s.save_candidate(self.p,request))
        request['model_context']=c['spec']['model_context'];d=self.write(lambda s:s.save_candidate(self.p,request));self.assertEqual(d['risk'],'high')
        self.write(lambda s:s.create_session(self.p,'Corrected source identity'))
        with self.assertRaises(ChangeError):self.commit(c)

    def test_replay_restart_and_duplicate_response_no_duplicate_candidate(self):
        b=self.prepare();first=self.process(b);count=len(self.read(lambda s:s.records(self.p,'candidate_specs')))
        again=ModelService(self.imp,self.sup.config).execute(self.p,b['id']);self.assertEqual(first,again);self.assertEqual(len(self.sup.requests),1)
        b2=self.prepare(dict(id=b['manifest']['import_batch_id']));self.process(b2)
        self.assertEqual(len(self.sup.requests),2);self.assertEqual(len(self.read(lambda s:s.records(self.p,'candidate_specs'))),count)

    def test_partial_failure_only_newly_authorized_failed_item_is_sent(self):
        imported=self.import_batch('# A\nValue: first','# B\nValue: second');b=self.prepare(imported)
        self.sup.behavior=lambda p,i:(400,dict(error='synthetic')) if i==2 else self.sup.respond(p,i)
        r=self.process(b);self.assertEqual(sorted(j['state'] for j in r['jobs']),['failed','saved'])
        self.model.execute(self.p,b['id']);self.assertEqual(len(self.sup.requests),2)
        failed=[j['item_id'] for j in r['jobs'] if j['state']=='failed'];new=self.prepare(imported,item_ids=failed)
        with self.assertRaises(ChangeError):self.model.execute(self.p,new['id'])
        self.process(new);self.assertEqual(len(self.sup.requests),3)

    def test_response_lost_unknown_never_automatically_resent(self):
        self.sup.behavior=lambda p,i:None;b=self.prepare();r=self.process(b)
        self.assertEqual(r['jobs'][0]['state'],'unknown');self.assertEqual(len(self.sup.requests),1)
        ModelService(self.imp,self.sup.config).execute(self.p,b['id']);self.assertEqual(len(self.sup.requests),1)
        self.assertEqual(self.read(lambda s:s.records(self.p,'model_results')),[])

    def test_external_call_does_not_hold_sqlite_write_transaction(self):
        def behavior(payload,index):
            self.write(lambda s:s.create_project('Independent write while HTTP is in flight'))
            return self.sup.respond(payload,index)
        self.sup.behavior=behavior;self.assertEqual(self.process(self.prepare())['jobs'][0]['state'],'saved')

    def test_response_received_but_local_commit_failure_leaves_unknown_no_resend(self):
        b=self.prepare();self.approve(b)
        with patch('nextrelay.model.ModelService._validate',side_effect=sqlite3.OperationalError('synthetic commit failure')):
            with self.assertRaises(sqlite3.OperationalError):self.model.execute(self.p,b['id'])
        self.assertEqual(len(self.sup.requests),1);self.assertEqual(self.model.get(self.p,b['id'])['jobs'][0]['state'],'sending')
        self.model.execute(self.p,b['id']);self.assertEqual(len(self.sup.requests),1)
        self.assertEqual(self.read(lambda s:s.records(self.p,'model_results')),[])
        # Only the clock is injected; no journal content is edited.
        import nextrelay.model as module
        real=module.datetime
        class Future(real):
            @classmethod
            def now(cls,tz=None):return real.now(tz)+timedelta(seconds=30)
        with patch.object(module,'datetime',Future):r=self.model.recover(self.p,b['id'])
        self.assertEqual(r['jobs'][0]['state'],'unknown');self.assertEqual(len(self.sup.requests),1)

    def test_no_raw_payload_response_or_secret_in_persistent_journal(self):
        sentinel='RAW_IMPORT_SENTINEL_9831';b=self.prepare(self.import_batch('# Record\n'+sentinel));self.process(b)
        with connect(self.db) as c:
            for table in ('model_batches','model_events','model_results'):
                rows=[dict(r) for r in c.execute('SELECT * FROM '+table)]
                self.assertNotIn(sentinel,json.dumps(rows));self.assertNotIn('api_key',json.dumps(rows))
        self.assertEqual(list(self.root.glob('*.stage')),[]);self.assertIn('memory-only',self.model.get(self.p,b['id'])['temporary_content'])

    def test_config_refuses_arbitrary_endpoints_redirect_routes_and_env_test_mode(self):
        from nextrelay.config import load_settings,ConfigError
        for endpoint in ('http://127.0.0.1:1234/v1/responses','https://api.openai.com.evil/v1/responses','https://api.openai.com/v1/responses?redirect=1','https://user:pw@api.openai.com/v1/responses'):
            with self.assertRaises(ValueError):ModelConfig(provider='openai-responses',model='chosen',api_key='synthetic',endpoint=endpoint)
        with self.assertRaises(ValueError):ModelConfig(provider='test-loopback',model='test',endpoint='http://127.0.0.1:1234/v1/responses')
        with self.assertRaises(ConfigError):load_settings(dict(NEXTRELAY_MODEL_PROVIDER='test-loopback',NEXTRELAY_MODEL_NAME='chosen'))
        with self.assertRaises(ChangeError):ModelService(self.imp).prepare(self.p,'abcdefgh',dict(import_batch_id=self.import_batch()['id']))

    def test_v8_upgrade_preserves_history_and_append_only_guard(self):
        old=self.root/'old.sqlite3'
        with connect(old) as c:
            with transaction(c):
                for v in range(1,9):
                    for sql in MIGRATIONS[v]:c.execute(sql)
                c.execute('PRAGMA user_version=8');c.execute("INSERT INTO projects(id,owner_subject,title,created_at) VALUES ('historic','dev-model','History','2026-10-24')")
        initialize(old)
        with connect(old) as c:
            verify_schema(c);self.assertEqual(c.execute('SELECT title FROM projects').fetchone()[0],'History');self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],SCHEMA_VERSION)
        b=self.prepare()
        with connect(self.db) as c:
            with self.assertRaises(sqlite3.IntegrityError):c.execute('UPDATE model_batches SET fingerprint=? WHERE id=?',('fake',b['id']))


    def test_old_baseline_task_versions_evidence_native_conflicts_all_listed(self):
        c=self.write(lambda s:s.save_candidate(self.p,dict(base_revision=0,operation='task.create',payload=dict(title='Inspect lock',goal='Measure closure',completion_conditions='Read load record'))))
        self.commit(c);task=self.state()['tasks'][0]['task_id']
        def setup(s):
            source=s.create_source(self.p,reference='synthetic historic origin')['id']
            artifact=s.create_artifact(self.p,'Synthetic baseline')['id']
            version=s.create_version(self.p,artifact,'# Synthetic baseline\nConstraint: retain inspected geometry',source_ids=[source],task_ids=[task],reason='synthetic historic version')['id']
            s.record_evidence(self.p,version,task_id=task,source_id=source,kind='claim',mechanism='synthetic-test',subject='synthetic',configuration_version='v1',result='Synthetic claim only; unknown',conditions_version=1)
            return artifact,version
        # Use the actual existing service signature, not a parallel evidence model.
        artifact,version=self.write(setup)
        baseline=self.write(lambda s:s.save_candidate(self.p,dict(base_revision=1,operation='baseline.set',target_id=artifact,target_version_id=version,payload={})))
        self.commit(baseline)
        imported=self.import_batch(f'# Synthetic inspection\nTask: {task}\nResult: proposed measurement\nRisk: independently verify\n')
        NativeService(self.imp).extract_item(self.p,imported['items'][0]['id'],base_revision=2)
        b=self.prepare(imported);preview=self.model.preview(self.p,b['id']);kinds={e['kind'] for e in b['manifest']['jobs'][0]['entries']}
        self.assertTrue({'format','source','native','conflicts','task','baseline','version','evidence'}<=kinds)
        self.approve(b);self.model.execute(self.p,b['id']);self.assertEqual(self.sup.requests[0]['body'],preview['requests'][0]['body'].encode())
        self.assertEqual(self.state()['project']['revision'],2);self.assertEqual(self.state()['baseline']['version_id'],version)

    def test_real_process_exit_after_http_and_restart_preserves_claim_without_resend(self):
        b=self.prepare();self.approve(b)
        script="""import os,sys
from pathlib import Path
from nextrelay.auth import Principal
from nextrelay.ingestion import ImportService
from nextrelay.model import ModelService
from nextrelay.model_provider import ModelConfig
imp=ImportService(Path(sys.argv[1]),Principal('dev-model'),Path(sys.argv[2]))
config=ModelConfig(provider='test-loopback',model='synthetic-inspector',endpoint=sys.argv[5],_loopback_test=True)
ModelService._validate=lambda *args:os._exit(73)
ModelService(imp,config).execute(sys.argv[3],sys.argv[4])
"""
        child=subprocess.run([sys.executable,'-B','-c',script,str(self.db),str(self.storage),self.p,b['id'],self.sup.config.endpoint],capture_output=True,timeout=20)
        self.assertEqual(child.returncode,73,child.stderr.decode());self.assertEqual(len(self.sup.requests),1)
        self.assertEqual(self.model.get(self.p,b['id'])['jobs'][0]['state'],'sending')
        self.assertEqual(self.read(lambda s:s.records(self.p,'model_results')),[])
        self.model.execute(self.p,b['id']);self.assertEqual(len(self.sup.requests),1)

    def test_redirect_not_followed_and_response_size_rejected_without_retry(self):
        self.sup.behavior=lambda p,i:(302,b'redirect must never be followed')
        r=self.process(self.prepare());self.assertEqual(r['jobs'][0]['state'],'failed');self.assertEqual(len(self.sup.requests),1)
        self.sup.behavior=lambda p,i:(200,b'a'*(256*1024+1))
        r=self.process(self.prepare());self.assertEqual(r['jobs'][0]['state'],'invalid');self.assertEqual(len(self.sup.requests),2)


    def test_native_risk_cannot_be_suppressed_by_empty_model_risks_or_direct_save(self):
        imported=self.import_batch('# Safety observation\nRisk: unknown load\nGap: missing inspection\n')
        NativeService(self.imp).extract_item(self.p,imported['items'][0]['id'],base_revision=0)
        result=self.process(self.prepare(imported));self.assertEqual(result['jobs'][0]['state'],'saved')
        candidate=self.candidate();self.assertEqual(candidate['risk'],'conflict');self.assertTrue(candidate['spec']['conflicts'])
        request={k:v for k,v in candidate['spec'].items() if k not in ('preconditions','target_id','target_version_id')}
        request['risk']='ordinary';request['conflicts']=[]
        saved=self.write(lambda s:s.save_candidate(self.p,request))
        self.assertEqual(saved['risk'],'conflict');self.assertTrue(set(candidate['spec']['conflicts'])<=set(saved['spec']['conflicts']))


    def test_dns_private_target_and_stalled_resolution_fail_before_http(self):
        from nextrelay.model_provider import ResponsesAdapter,ProviderFailure
        import time
        cfg=ModelConfig(provider='openai-responses',model='synthetic-exact',api_key='synthetic-not-real',timeout=.05)
        with patch('nextrelay.model_provider.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ProviderFailure) as e:ResponsesAdapter(cfg).send(b'{}','synthetic-request')
            self.assertEqual(e.exception.code,'model_target_denied')
        finished=threading.Event()
        def stalled(*args,**kwargs):finished.wait(.5);return []
        try:
            with patch('nextrelay.model_provider.socket.getaddrinfo',side_effect=stalled):
                started=time.monotonic()
                with self.assertRaises(ProviderFailure) as e:ResponsesAdapter(cfg).send(b'{}','synthetic-request')
                self.assertEqual(e.exception.code,'model_dns_timeout');self.assertLess(time.monotonic()-started,.4)
        finally:finished.set()
        self.assertEqual(self.sup.requests,[])


    def test_network_deadline_unknown_after_one_captured_request_no_retry(self):
        import time
        self.model=ModelService(self.imp,replace(self.sup.config,timeout=.05))
        def slow(payload,index):time.sleep(.15);return self.sup.respond(payload,index)
        self.sup.behavior=slow;b=self.prepare();started=time.monotonic();r=self.process(b)
        self.assertEqual(r['jobs'][0]['state'],'unknown');self.assertLess(time.monotonic()-started,1)
        self.model.execute(self.p,b['id']);self.assertEqual(len(self.sup.requests),1)


    def test_new_model_risks_supersede_old_candidate_and_invalidate_prior_approval(self):
        first=self.prepare();self.process(first);old=self.candidate()
        with unit_of_work(self.db,self.owner,write=True) as s:
            review=s.review_candidates(self.p,dict(selection=[dict(candidate_id=old['candidate_id'],fingerprint=old['fingerprint'])],decision='approve',mode='explicit',basis='First synthetic human decision',input_origin='synthetic-test',authorization=Changes(s).authorization(old)))[0]
        def add_risk(v):v['candidates'][0]['risks']=['New unresolved thermal verification'];return v
        self.alter_output(add_risk)
        second=self.prepare(dict(id=first['manifest']['import_batch_id']));result=self.process(second)
        new_id=json.loads(result['jobs'][0]['events'][-1]['metadata_json'])['candidate_ids'][0]
        new=self.read(lambda s:s.candidate(self.p,new_id))
        self.assertEqual(result['jobs'][0]['state'],'saved');self.assertNotEqual(old['candidate_id'],new['candidate_id'])
        self.assertEqual(new['risk'],'conflict');self.assertIn('New unresolved thermal verification',new['spec']['conflicts'])
        with self.assertRaises(ChangeError):
            self.write(lambda s:s.commit_candidates(self.p,dict(request_key='stale-approval-'+str(uuid4()),base_revision=0,selection=[dict(candidate_id=old['candidate_id'],review_id=review['id'])])))
        self.assertEqual(self.read(lambda s:s.candidate(self.p,old['candidate_id']))['processing'],'superseded')
        # Later omission cannot delete the accumulated concern or revive high risk.
        self.sup.behavior=None;third=self.prepare(dict(id=first['manifest']['import_batch_id']));third_result=self.process(third)
        self.assertEqual(json.loads(third_result['jobs'][0]['events'][-1]['metadata_json'])['candidate_ids'],[new['candidate_id']])
        self.assertEqual(self.read(lambda s:s.candidate(self.p,new['candidate_id']))['risk'],'conflict')
        # Direct save is also forced to the known union even when caller omits it.
        request={k:v for k,v in new['spec'].items() if k not in ('preconditions','target_id','target_version_id')}
        request['risk']='ordinary';request['conflicts']=[]
        saved=self.write(lambda s:s.save_candidate(self.p,request))
        self.assertEqual(saved['risk'],'conflict');self.assertIn('New unresolved thermal verification',saved['spec']['conflicts'])
        self.assertEqual(len(self.sup.requests),3);self.assertEqual(self.state()['tasks'],[])


    def test_isolated_unicode_surrogates_are_known_invalid_not_uncertain_send(self):
        for value in ('"\\ud800"','{"\\ud800":1}','["\\udfff"]'):
            with self.assertRaises(ChangeError):strict_json(value.encode('ascii'))
        def bad(v):v['candidates'][0]['title']=chr(0xd800);return v
        self.alter_output(bad);b=self.prepare();result=self.process(b)
        self.assertEqual(result['jobs'][0]['state'],'invalid');self.assertEqual(len(self.sup.requests),1)
        self.model.execute(self.p,b['id']);self.assertEqual(len(self.sup.requests),1);self.assertEqual(self.state()['tasks'],[])
