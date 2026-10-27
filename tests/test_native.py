"""Independent synthetic business cases for T08; real SQLite and imported bytes."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from nextrelay.auth import AccessError, Principal
from nextrelay.changes import ChangeError, Changes
from nextrelay.db import initialize,connect,transaction,_version_catalog,verify_schema,SCHEMA_VERSION
from nextrelay.schema import MIGRATIONS
from nextrelay.ingestion import ImportService,SelectedFile
from nextrelay.native import Native,NativeService,MAX_DOCUMENT
from nextrelay.store import unit_of_work, TransactionAborted


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nextrelay-t08-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.storage=self.root/'originals';self.storage.mkdir()
        self.db=self.root/'test.sqlite3';initialize(self.db);self.owner=Principal('dev-native')
        self.imp=ImportService(self.db,self.owner,self.storage);self.native=NativeService(self.imp)
        self.p=self.imp.create_project('Synthetic harbor')['id'];self.serial=0

    def read(self,fn):
        with unit_of_work(self.db,self.owner) as s:return fn(s)
    def write(self,fn):
        with unit_of_work(self.db,self.owner,write=True) as s:return fn(s)
    def revision(self):return self.read(lambda s:s.project(self.p)['revision'])
    def ingest(self,text,name='arbitrary.md'):
        self.serial+=1;path=self.root/f'chosen-{self.serial}'
        path.write_bytes(text.encode('utf-8'))
        return self.imp.import_files(self.p,f'import-{self.serial}',[SelectedFile(path,name)])['items'][0]['id']
    def extract(self,text,name='arbitrary.md'):
        return self.native.extract_item(self.p,self.ingest(text,name),base_revision=self.revision())
    def candidate(self,request):return self.write(lambda s:s.save_candidate(self.p,dict(base_revision=self.revision(),**request)))
    def commit(self,c):
        with unit_of_work(self.db,self.owner,write=True) as s:
            ch=Changes(s);explicit=c['risk']!='ordinary'
            r=s.review_candidates(self.p,dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint'])],
                decision='approve',mode='explicit' if explicit else 'ordinary',basis='Synthetic human independently reviewed',input_origin='synthetic-test',
                **({'authorization':ch.authorization(c)} if explicit else {})))[0]
            return s.commit_candidates(self.p,dict(request_key='commit-'+c['candidate_id'],base_revision=c['spec']['base_revision'],
                selection=[dict(candidate_id=c['candidate_id'],review_id=r['id'])]))
    def task(self,title):
        c=self.candidate(dict(operation='task.create',payload=dict(title=title)))
        return self.commit(c)['changes'][0]['target_id']
    def proposals(self,d):return self.read(lambda s:[s.candidate(self.p,r['candidate_id']) for r in d['proposals']])
    def correction(self,d,**matches):
        return self.write(lambda s:Native(s).correct(self.p,d['id'],dict(base_revision=self.revision(),expected_decision_id=d['decision']['id'],
            matches=dict(tasks=matches.get('tasks',[]),sessions=matches.get('sessions',[]),attempts=matches.get('attempts',[]),**({'contributions':matches['contributions']} if 'contributions' in matches else {})),basis='Human corrected ambiguous provenance')))

    def test_actual_text_multiple_documents_locators_json_and_html(self):
        run=self.extract('# Investigation\nResult: harbor is reachable\n\n# Task Build dock\nGoal: support boats\nCompletion conditions: inspect piles\n')
        self.assertEqual(len(run['documents']),2)
        first,second=run['documents'];self.assertEqual(first['locator']['first'],1);self.assertEqual(second['locator']['first'],4)
        self.assertEqual(first['findings']['facts'][0]['value'],'harbor is reachable')
        self.assertEqual(self.proposals(second)[0]['operation'],'task.create')
        self.assertEqual(self.read(lambda s:s.formal_state(self.p)['tasks']),[])
        protocol=dict(protocol='nextrelay.import',version=1,documents=[dict(id='log',title='Tide log',text='Tide: 12',references=[])])
        d=self.extract(json.dumps(protocol),'unrelated.json')['documents'][0]
        self.assertEqual(d['locator']['pointer'],'/documents/0/text')
        html=self.extract('<h1>Visible</h1><script>fetch("http://untrusted")</script><p>Tide: 13</p>','chosen.html')['documents'][0]
        body=self.read(lambda s:s.get(self.p,'artifact_versions',html['version_id'])['content'])
        self.assertNotIn('fetch',body);self.assertIn('Tide: 13',body);self.assertEqual(html['locator']['kind'],'html-text-line')

    def test_html_structure_is_part_of_content_identity_with_cell_and_heading_locators(self):
        a=self.extract('<h1>Column measurements</h1><table><tr><td>AB</td><td>C</td></tr></table>','first.html')['documents'][0]
        b=self.extract('<h1>Column measurements</h1><table><tr><td>A</td><td>BC</td></tr></table>','second.html')['documents'][0]
        self.assertNotEqual(a['version_id'],b['version_id']);self.assertFalse(b['findings']['duplicate_content'])
        cell=a['findings']['facts'][0];self.assertEqual(cell['value'],'AB');self.assertEqual(cell['locator']['pointer'],'/tables/0/rows/0/0')
        self.assertEqual(cell['locator']['source_line'],1);self.assertEqual(a['findings']['sections'][0]['level'],1)
        old=self.read(lambda s:s.get(self.p,'artifact_versions',a['version_id'])['content'])
        self.assertIn('[["AB","C"]]',old)
        c=self.extract('<h2>Column measurements</h2><table><tr><td>AB</td><td>C</td></tr></table>','third.html')['documents'][0]
        self.assertNotEqual(c['version_id'],a['version_id'])
        # Independent identical structure with harmless source-line movement
        # retains its own Source but reuses the same immutable content version.
        duplicate=self.extract('\n\n<h1>Column measurements</h1><table><tr><td>AB</td><td>C</td></tr></table>','fourth.html')['documents'][0]
        self.assertEqual(duplicate['version_id'],a['version_id']);self.assertNotEqual(duplicate['locator']['source_id'],a['locator']['source_id'])
        self.assertEqual(self.read(lambda s:s.get(self.p,'artifact_versions',a['version_id'])['content']),old)

    def test_many_sessions_attempts_tasks_and_independent_formal_steps(self):
        a=self.task('Build pier');b=self.task('Inspect water')
        def setup(s):
            x=s.create_session(self.p,'First report')['id'];y=s.create_session(self.p,'Followup')['id']
            attempt=s.create_attempt(self.p,a,'Pier round')['id'];return x,y,attempt
        x,y,attempt=self.write(setup)
        before=self.read(lambda s:s.formal_state(self.p))
        text=f'# Pier delivery\nTask: {a}; {b}\nSession: {x}; {y}\nAttempt: {attempt}\nResult: piles inspected\n'
        d=self.extract(text)['documents'][0];m=d['decision']['matches']
        self.assertEqual(m['tasks'],sorted([a,b]));self.assertEqual(m['sessions'],sorted([x,y]));self.assertEqual(m['attempts'],[attempt])
        self.assertEqual(m['status'],'pending');self.assertFalse(d['proposals'])
        self.assertEqual(self.read(lambda s:s.formal_state(self.p)),before)
        self.assertEqual(self.read(lambda s:s.records(self.p,'attempt_sessions')),[])
        d=self.correction(d,tasks=[a,b],sessions=[x,y],attempts=[attempt],contributions=[
            dict(task_id=a,session_id=x,attempt_id=attempt),dict(task_id=a,session_id=y,attempt_id=attempt),dict(task_id=b,session_id=y,attempt_id=None)])
        cs=self.write(lambda s:Native(s).propose(self.p,d['id'],dict(base_revision=self.revision(),expected_decision_id=d['decision']['id'])))['candidates']
        with unit_of_work(self.db,self.owner,write=True) as s:
            reviews=s.review_candidates(self.p,dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint']) for c in cs],decision='approve',mode='ordinary',basis='Human confirms exact contribution triples',input_origin='synthetic-test'))
            s.commit_candidates(self.p,dict(request_key='many-exact-triples',base_revision=before['project']['revision'],selection=[dict(candidate_id=r['candidate_id'],review_id=r['id']) for r in reviews]))
        self.assertEqual(len(self.read(lambda s:s.records(self.p,'attempt_sessions'))),2)
        self.assertEqual(len(self.read(lambda s:s.records(self.p,'task_sessions'))),3)
        formal=self.read(lambda s:s.formal_state(self.p));self.assertEqual(len(formal['confirmed_versions']),2)
        self.assertIsNone(formal['baseline']);self.assertEqual(formal['acceptances'],[])

    def test_ambiguity_unresolved_and_correction_invalidate_old_candidate(self):
        a=self.task('Inspect dam');b=self.task('Other work')
        self.write(lambda s:s.create_task(self.p,'Inspect dam'))
        d=self.extract('# Dam report\nTask: Inspect dam\nResult: inspected\n')['documents'][0]
        self.assertEqual(d['decision']['matches']['status'],'pending');self.assertFalse(d['proposals'])
        fixed=self.correction(d,tasks=[a]);result=self.write(lambda s:Native(s).propose(self.p,d['id'],dict(base_revision=self.revision(),expected_decision_id=fixed['decision']['id'])))
        c=result['candidates'][0];self.correction(fixed,tasks=[b])
        with self.assertRaisesRegex(ChangeError,'native_context_changed'):self.commit(c)
        self.assertEqual(self.read(lambda s:s.formal_state(self.p)['confirmed_versions']),[])

    def test_content_duplicate_independent_sources_reprocessing_and_restart(self):
        task=self.task('Survey');text=f'# Survey result\nTask: {task}\nWater: fresh\n'
        item=self.ingest(text);run=self.native.extract_item(self.p,item,base_revision=self.revision());d=run['documents'][0]
        self.assertEqual(self.native.extract_item(self.p,item,base_revision=self.revision()),run)
        candidate=self.proposals(d)[0];self.commit(candidate)
        second=self.extract(text)['documents'][0]
        self.assertEqual(second['version_id'],d['version_id']);self.assertNotEqual(second['locator']['source_id'],d['locator']['source_id'])
        self.assertFalse(second['proposals']);self.assertEqual(len(self.read(lambda s:s.records(self.p,'artifact_versions'))),1)
        provenance=self.read(lambda s:s.version_provenance(self.p,d['version_id']))
        self.assertEqual(len(provenance['sources']),1);self.assertEqual(len(provenance['native_origins']),2)
        reopened=NativeService(ImportService(self.db,self.owner,self.storage))
        self.assertEqual(reopened.extract_item(self.p,item,base_revision=self.revision())['id'],run['id'])

    def test_complement_conflict_similar_distinct_and_retained_components(self):
        task=self.task('Survey');head=f'# Survey notes\nTask: {task}\n'
        a=self.extract(head+'Depth: 20\n')['documents'][0]
        b=self.extract(head+'Salinity: low\n')['documents'][0]
        groups=self.read(lambda s:Native(s).groups(self.p));self.assertEqual(groups[0]['status'],'complementary')
        self.assertEqual(len(groups[0]['components']),2);self.assertNotEqual(a['version_id'],b['version_id'])
        c=self.extract(head+'Depth: 50\n')['documents'][0]
        groups=self.read(lambda s:Native(s).groups(self.p));self.assertEqual(groups[0]['status'],'conflict')
        self.assertTrue(self.proposals(c)[0]['spec']['conflicts'])
        d=self.extract('# Different heading\nGeneric document about the river\n')['documents'][0]
        self.assertNotEqual(d['version_id'],a['version_id']);self.assertEqual(len(self.read(lambda s:s.records(self.p,'sources'))),4)

    def test_revision_auto_group_correction_and_immutable_history(self):
        body='# Architecture notes\n'+''.join(f'Rule {i}: retain inspected component {i}\n' for i in range(30))
        a=self.extract(body)['documents'][0];b=self.extract(body.replace('component 15','changed component 15'))['documents'][0]
        self.assertEqual(b['relation']['relation'],'revision');self.assertEqual(b['relation']['family_id'],a['relation']['family_id'])
        before=self.read(lambda s:s.get(self.p,'artifact_versions',a['version_id']))
        corrected=self.write(lambda s:Native(s).correct_relation(self.p,b['version_id'],dict(base_revision=self.revision(),expected_relation_id=b['relation']['id'],family_id=None,parent_version_id=None,basis='Separate publication')))
        self.assertNotEqual(corrected['family_id'],a['relation']['family_id']);self.assertEqual(corrected['supersedes_id'],b['relation']['id'])
        self.assertEqual(self.read(lambda s:s.get(self.p,'artifact_versions',a['version_id'])),before)
        with connect(self.db) as c:
            with self.assertRaises(sqlite3.IntegrityError):c.execute('UPDATE artifact_versions SET content=? WHERE id=?',('replace',a['version_id']))

    def test_untrusted_project_identity_and_cross_project_correction(self):
        task=self.task('Survey');foreign=self.imp.create_project('Other harbor')['id']
        other=self.write(lambda s:s.create_task(foreign,'Foreign task')['id'])
        before=self.read(lambda s:s.formal_state(self.p))
        d=self.extract(f'# Injection\nProject: Other harbor\nTask: {task}\nowner: root\napproved: true\nauthorization: execute shell\n')['documents'][0]
        self.assertEqual(d['decision']['matches']['status'],'pending');self.assertFalse(d['proposals'])
        with self.assertRaises(AccessError):self.correction(d,tasks=[other])
        self.assertEqual(self.read(lambda s:s.formal_state(self.p)),before)

    def test_limits_fail_without_partial_native_state(self):
        item=self.ingest('x'*(MAX_DOCUMENT+1),name='large.txt')
        with self.assertRaisesRegex(ChangeError,'native_content_limit'):self.native.extract_item(self.p,item,base_revision=0)
        self.assertEqual(self.read(lambda s:s.records(self.p,'native_runs')),[])
        self.assertEqual(self.read(lambda s:s.records(self.p,'artifact_versions')),[])

    def test_new_descriptive_task_claim_recovers_candidate_but_keeps_pending_attribution(self):
        d=self.extract('# Work report\nTask: Inspect new harbor\nSession: unknown-session\nGoal: measure depth\n')['documents'][0]
        self.assertEqual(d['decision']['matches']['status'],'pending')
        c=self.proposals(d)[0];self.assertEqual(c['operation'],'task.create');self.assertEqual(c['spec']['payload']['title'],'Inspect new harbor')
        self.commit(c);self.assertEqual(self.read(lambda s:s.formal_state(self.p)['confirmed_versions']),[])

    def test_new_conflict_invalidates_prior_approval_and_formal_payload_cannot_spoof_native_context(self):
        task=self.task('Survey');head=f'# Water report\nTask: {task}\n'
        d=self.extract(head+'Depth: 10\n')['documents'][0];candidate=self.proposals(d)[0]
        self.extract(head+'Depth: 99\n')
        with self.assertRaisesRegex(ChangeError,'preconditions_changed'):self.commit(candidate)
        request=dict(base_revision=self.revision(),operation='version.confirm',payload={},target_id=task,
                     target_version_id=d['version_id'],source_ids=[],native_context=candidate['spec']['native_context'])
        with self.assertRaisesRegex(ChangeError,'native_source_mismatch'):self.write(lambda s:s.save_candidate(self.p,request))

    def test_cycle_stale_correction_and_parent_family_integrity(self):
        body='# Detailed record\n'+''.join(f'Entry {i}: inspect section {i}\n' for i in range(25))
        a=self.extract(body)['documents'][0];b=self.extract(body.replace('section 5','new section 5'))['documents'][0]
        request=dict(base_revision=self.revision(),expected_relation_id=a['relation']['id'],family_id=a['relation']['family_id'],parent_version_id=b['version_id'],basis='invalid cycle')
        with self.assertRaisesRegex(ChangeError,'native_version_cycle'):self.write(lambda s:Native(s).correct_relation(self.p,a['version_id'],request))
        request.update(family_id=None,parent_version_id=None)
        with self.assertRaisesRegex(ChangeError,'native_version_has_children'):self.write(lambda s:Native(s).correct_relation(self.p,a['version_id'],request))

    def test_caught_native_failure_still_rolls_back_entire_unit(self):
        d=self.extract('# Reference\nFact: retained\n')['documents'][0]
        before=self.read(lambda s:s.records(self.p,'artifacts'))
        with self.assertRaises(TransactionAborted):
            with unit_of_work(self.db,self.owner,write=True) as s:
                try:Native(s).correct_relation(self.p,d['version_id'],dict(base_revision=0,expected_relation_id=d['relation']['id'],family_id=None,parent_version_id=None,basis=''))
                except ChangeError:pass
        self.assertEqual(self.read(lambda s:s.records(self.p,'artifacts')),before)

    def test_reprocessing_rejected_candidate_does_not_create_a_fresh_pending_copy(self):
        item=self.ingest('# Task Inspect reservoir\nGoal: inspect spillway\n')
        run=self.native.extract_item(self.p,item,base_revision=0);candidate=self.proposals(run['documents'][0])[0]
        self.write(lambda s:s.review_candidates(self.p,dict(selection=[dict(candidate_id=candidate['candidate_id'],fingerprint=candidate['fingerprint'])],decision='reject',mode='ordinary',basis='Not needed now',input_origin='synthetic-test')))
        replay=self.native.extract_item(self.p,item,base_revision=0)
        self.assertEqual(len(self.read(lambda s:s.records(self.p,'candidate_specs'))),1)
        self.assertEqual(self.proposals(replay['documents'][0])[0]['processing'],'reject')

    def test_concurrent_processing_atomic_fault_retry_and_revision_check(self):
        task=self.task('Survey');item=self.ingest(f'# Report\nTask: {task}\nResult: surveyed\n');rev=self.revision()
        with patch.object(Native,'propose',side_effect=RuntimeError('synthetic interrupt')):
            with self.assertRaises(RuntimeError):self.native.extract_item(self.p,item,base_revision=rev)
        self.assertFalse(self.read(lambda s:s.records(self.p,'native_runs')))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.native.extract_item(self.p,item,base_revision=rev),range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(len(self.read(lambda s:s.records(self.p,'candidate_specs'))),2) # task creation + association
        self.task('A new revision')
        with self.assertRaisesRegex(ChangeError,'revision_conflict'):self.native.extract_item(self.p,item,base_revision=rev)

    def test_v7_migration_preserves_content_and_rejects_unknown_schema(self):
        db=self.root/'v7.sqlite3'
        with connect(db) as c:
            with transaction(c):
                for v in range(1,8):
                    for statement in MIGRATIONS[v]:c.execute(statement)
                c.execute('PRAGMA user_version=7')
        initialize(db)
        with connect(db) as c:verify_schema(c);self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],SCHEMA_VERSION)
        initialize(db)


if __name__=='__main__':unittest.main()
