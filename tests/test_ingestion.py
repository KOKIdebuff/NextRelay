"""T07 actual SQLite/files/process integration; synthetic inputs only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

from nextrelay.auth import AccessError, Principal
from nextrelay.db import connect, initialize
from nextrelay.formats import (ImportFailure, MAX_FILE, MAX_BATCH, MAX_OUTPUT, digest,
                               encoded, parse, formal_json)
from nextrelay.ingestion import ImportService, SelectedFile
from nextrelay import localfiles
from nextrelay.store import TransactionAborted, unit_of_work


PROTOCOL={'protocol':'nextrelay.import','version':1,'documents':[
    {'id':'d1','title':'\u4e2d\u6587','text':'Project: other; Task/Session/Attempt/Version: foreign; approved accepted owner subject authorization checks_passed=true', 'references':['d2']},
    {'id':'d2','title':'Reference','text':'Untrusted claim, no authority'}]}


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nextrelay-t07-test-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.storage=self.root/'user-owned';self.storage.mkdir()
        self.db=self.root/'test.sqlite3';initialize(self.db)
        self.owner=Principal('dev-t07-test')
        self.service=ImportService(self.db,self.owner,self.storage)
        self.p=self.service.create_project('Synthetic empty project')['id']
        self.q=self.service.create_project('Other project')['id']

    def file(self,name,data=b'synthetic',**kwargs):
        path=self.root/('input-'+str(len(list(self.root.glob('input-*')))))
        path.write_bytes(data)
        return SelectedFile(path,name,**kwargs)

    def run_batch(self,*files,key='initial'):
        return self.service.import_files(self.p,key,list(files))

    def state(self):
        with unit_of_work(self.db,self.owner) as s:return s.formal_state(self.p)

    def counts(self):
        with connect(self.db) as c:
            return {t:c.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in
                    ('sources','ingest_batches','ingest_items','ingest_inputs','ingest_attempts','original_links')}

    def assert_code(self,code,call):
        with self.assertRaises(ImportFailure) as result:call()
        self.assertEqual(result.exception.code,code)

    def test_empty_project_selected_project_and_restart_content(self):
        before=self.state();data='\u4e2d\u6587\r\nsecond\n'.encode()
        b=self.run_batch(self.file('\u4e2d\u6587.txt',data),self.file('protocol.json',encoded(PROTOCOL)))
        self.assertEqual(b['summary'],{'complete':2,'incomplete':0,'total':2})
        self.assertEqual(self.state(),before)
        service=ImportService(self.db,self.owner,self.storage)
        self.assertEqual(len(service.batches(self.p)),1)
        self.assertEqual(service.batch(self.p,b['id'])['items'],b['items'])
        for item in b['items']:
            self.assertEqual(item['attribution'],'project-only')
            self.assertEqual(item['semantic_status'],'not-performed')
            self.assertEqual(item['inputs'][0]['project_id'],self.p)
        self.assertEqual(service.read_original(self.p,b['items'][0]['id']),data)
        self.assertEqual(service.read_parsed(self.p,b['items'][0]['id'])['text'],data.decode())
        self.assertEqual(service.read_parsed(self.p,b['items'][1]['id'])['protocol'],PROTOCOL)
        with unit_of_work(self.db,self.owner) as s:
            for source in s.records(self.p,'sources'):
                self.assertIsNone(s.attribution(self.p,source['id'])['task_id'])
            for table in ('tasks','sessions','attempts','artifacts','artifact_versions','candidate_specs','change_commits'):
                self.assertEqual(s.records(self.p,table),[])

    def test_same_name_different_bytes_and_unrelated_existing_file_preserved(self):
        unknown=self.storage/'unknown.txt';unknown.write_bytes(b'do not touch')
        b=self.run_batch(self.file('same.txt',b'A'),self.file('same.txt',b'B'))
        paths=[self.service.original_location(self.p,i['id'])['path'] for i in b['items']]
        self.assertNotEqual(*paths)
        self.assertEqual([Path(p).read_bytes() for p in paths],[b'A',b'B'])
        self.assertEqual(unknown.read_bytes(),b'do not touch')

    def test_availability_missing_changed_unreadable_and_reassociate(self):
        selected=self.file('a.txt',b'identity')
        b=self.run_batch(selected);i=b['items'][0];identity=i['inputs'][0]['id']
        path=Path(self.service.original_location(self.p,i['id'])['path']);path.unlink()
        self.assertEqual(self.service.item(self.p,i['id'])['inputs'][0]['availability']['status'],'unavailable')
        self.assert_code('original_unavailable_reassociate',lambda:self.service.read_original(self.p,i['id']))
        wrong=self.file('wrong.txt',b'wrong')
        self.assert_code('original_identity_mismatch',lambda:self.service.reassociate(self.p,i['id'],identity,wrong))
        with self.assertRaises(AccessError):self.service.reassociate(self.q,i['id'],identity,selected)
        self.service.reassociate(self.p,i['id'],identity,selected)
        self.assertEqual(self.service.read_original(self.p,i['id']),b'identity')
        selected.path.write_bytes(b'changed')
        self.assertEqual(self.service.item(self.p,i['id'])['inputs'][0]['availability']['status'],'changed')
        with patch('nextrelay.localfiles.opened',side_effect=PermissionError('synthetic')):
            self.assertEqual(self.service.item(self.p,i['id'])['inputs'][0]['availability']['status'],'unavailable')

    def test_text_markdown_bom_empty_invalid_and_encoding(self):
        files=[self.file('a.txt','\u4e2d\u6587\r\n\n'.encode()),self.file('a.md',b'\xef\xbb\xbf# heading\n`inert`'),
               self.file('empty.txt',b''),self.file('invalid.txt',b'\xffsecret-body'),
               self.file('utf16.txt','\u4e2d'.encode('utf-16')),self.file('nullbyte.txt',b'a\x00b')]
        b=self.run_batch(*files)
        self.assertEqual(b['summary']['complete'],3)
        self.assertEqual(self.service.read_parsed(self.p,b['items'][1]['id'])['text'],'# heading\n`inert`')
        self.assertEqual(self.service.read_parsed(self.p,b['items'][2]['id'])['text'],'')
        for i in b['items'][3:]:
            self.assertEqual(i['latest']['save_status'],'saved')
            self.assertNotIn('secret-body',json.dumps(i))

    def test_json_actual_protocol_validation_and_preallocation_limits(self):
        good=encoded(PROTOCOL)
        self.assertEqual(parse(good,'a.json')[0]['protocol'],PROTOCOL)
        invalid=[(b'{"protocol":"nextrelay.import","version":2,"documents":[]}', 'json_protocol_version'),
                 (b'{}','json_protocol_fields'),(b'{"protocol":"nextrelay.import","version":true,"documents":[]}','json_protocol_version'),
                 (b'{"protocol":"nextrelay.import","version":1,"documents":[],"approved":true}','json_protocol_fields'),
                 (b'{"a":1,"a":2}','json_duplicate_key'),(b'{"n":NaN}','json_nonfinite'),
                 (b'{"n":Infinity}','json_nonfinite'),(b'{"n":1e9999}','json_nonfinite'),
                 (b'{broken','json_malformed'),(b'['*33+b'0'+b']'*33,'json_depth_limit'),
                 (b'['+b'0,'*20001+b'0]','json_node_limit')]
        for data,code in invalid:
            with self.subTest(code=code):self.assert_code(code,lambda:parse(data,'x.json'))
        for document,code in [({'id':'x','title':7,'text':''},'json_document_type'),
                              ({'id':'x','text':''},'json_document_fields'),
                              ({'id':'x','title':'a','text':'','references':['missing']},'json_reference_missing')]:
            v=dict(PROTOCOL,documents=[document])
            self.assert_code(code,lambda:parse(encoded(v),'x.json'))
        for text in ('['*33+'0'+']'*33,'['+'0,'*20001+'0]'):
            with patch('nextrelay.formats.json.loads',side_effect=AssertionError('must reject before json.loads')):
                with self.assertRaises(ImportFailure):formal_json(text)

    def test_html_inert_text_headings_tables_hidden_and_malformed(self):
        html=b'''<html><head><style>badcss</style><link href="http://invalid/"></head><body>
        <h1 onclick="steal()">Visible</h1><p>Words</p><script>secret-script</script>
        <div hidden>secret-hidden</div><p style="display: none">hidden-css</p>
        <div aria-hidden="true">aria-secret</div><iframe src="file:///secret">iframe-secret</iframe>
        <img src="http://127.0.0.1:1/no"><a href="javascript:steal()">Link text</a>
        <a href="data:text/html,evil">Data link</a><table><tr><th>Key</th><td>Value</td></tr></table></body></html>'''
        b=self.run_batch(self.file('a.html',html))
        result=self.service.read_parsed(self.p,b['items'][0]['id'])
        self.assertIn('Words',result['text']);self.assertIn('Link text',result['text'])
        self.assertEqual(result['headings'][0]['text'],'Visible')
        self.assertEqual(result['tables'][0]['rows'],[['Key','Value']])
        for secret in ('secret-script','secret-hidden','hidden-css','aria-secret','iframe-secret','steal','http://','file:///'):
            self.assertNotIn(secret,json.dumps(result))
        result,_=parse(b'<h1>Open<p>unfinished','a.html')
        self.assertTrue(result['warnings']);self.assertIn('unfinished',result['text'])

    def test_unsupported_and_disguised_formats_isolated_with_bytes_saved(self):
        files=[self.file('a.pdf',b'%PDF-test'),self.file('a.docx',b'PK\x03\x04test'),
               self.file('a.png',b'\x89PNGtest'),self.file('a.zip',b'PK\x03\x04test'),
               self.file('fake.txt',b'%PDF-test'),self.file('wrong.txt',b'plain',media_type='application/json'),
               self.file('script.txt',b'<script>evil</script>'),self.file('valid.txt',b'valid')]
        b=self.run_batch(*files)
        self.assertEqual(b['summary'],{'complete':1,'incomplete':7,'total':8})
        for i,f in zip(b['items'],files):self.assertEqual(self.service.read_original(self.p,i['id']),f.path.read_bytes())
        for i in b['items'][:4]:self.assertEqual(i['latest']['parse_status'],'unsupported')
        self.assertEqual(self.service.read_parsed(self.p,b['items'][-1]['id'])['text'],'valid')

    def test_count_20_and_21_boundaries(self):
        f=self.file('a.txt')
        b=self.run_batch(*([f]*20));self.assertEqual(b['summary']['complete'],20)
        before=self.counts()
        self.assert_code('batch_file_count_limit',lambda:self.run_batch(*([f]*21),key='21'))
        self.assertEqual(self.counts(),before)

    def test_file_and_total_byte_boundaries_before_read_and_unicode_bytes(self):
        exact=self.file('exact.txt',b'a'*MAX_FILE,parse=False)
        large=self.file('large.txt',b'b'*(MAX_FILE+1))
        with patch('nextrelay.ingestion.localfiles.opened',wraps=localfiles.opened) as opened:
            b=self.run_batch(*([exact]*5),large,exact)
        self.assertTrue(opened.called)
        self.assertEqual(b['summary']['complete'],5)
        self.assertEqual([i['latest']['reason'] for i in b['items'][5:]],['file_size_limit','batch_size_limit'])
        self.assertEqual([self.service.read_original(self.p,i['id']) for i in b['items'][:5]],[b'a'*MAX_FILE]*5)
        text='\u754c'*(MAX_FILE//3+1)
        f=self.file('unicode.txt',text.encode())
        # Oversized input must not reach read() at all, even during preflight.
        real_open=localfiles.opened
        from contextlib import contextmanager
        @contextmanager
        def guarded(path,**kw):
            with real_open(path,**kw) as stream:
                if Path(path)==f.path:
                    class NoRead:
                        def fileno(self):return stream.fileno()
                        def read(self,*a):raise AssertionError('over-limit file read')
                    yield NoRead()
                else:yield stream
        with patch('nextrelay.ingestion.localfiles.opened',guarded):
            b=self.run_batch(f,key='unicode')
        self.assertEqual(b['items'][0]['latest']['reason'],'file_size_limit')

    def test_output_and_html_structure_limits_are_failures_not_truncated_success(self):
        # Escaping increases output without increasing raw byte budget.
        self.assert_code('output_limit',lambda:parse(b'\x01'*(MAX_FILE//2),'a.txt'))
        self.assert_code('html_depth_limit',lambda:parse(b'<div>'*129+b'x','a.html'))
        self.assert_code('html_table_limit',lambda:parse(b'<table></table>'*101,'a.html'))
        self.assert_code('html_cell_limit',lambda:parse(b'<table><tr>'+b'<td>x</td>'*10001+b'</tr></table>','a.html'))

    def test_mixed_batch_save_failure_retains_independent_success_and_failure_details(self):
        files=[self.file('normal.txt'),self.file('invalid.txt',b'\xff'),self.file('large.txt',b'x'*(MAX_FILE+1)),
               self.file('a.pdf',b'%PDF-test'),self.file('save.txt'),self.file('later.txt',b'later')]
        batch=self.service.create_batch(self.p,'mixed',files)
        real=localfiles.persist;seen=0
        def fail(path,data):
            nonlocal seen
            if str(path).endswith('.original'):
                seen+=1
                if seen==4:raise ImportFailure('local_save_failed','save')
            return real(path,data)
        with patch('nextrelay.ingestion.localfiles.persist',side_effect=fail):
            b=self.service.process_batch(self.p,batch['id'])
        self.assertEqual(b['summary'],{'complete':2,'incomplete':4,'total':6})
        self.assertEqual(self.service.read_original(self.p,b['items'][-1]['id']),b'later')
        self.assertEqual(b['items'][4]['latest']['failure_stage'],'save')

    def test_retry_original_replacement_restart_history_and_success_untouched(self):
        bad=self.file('bad.json',b'{}');good=self.file('good.txt',b'unchanged')
        b=self.run_batch(bad,good);failed,ok=b['items'];counts=self.counts()
        self.assert_code('successful_item_not_retryable',lambda:self.service.retry_item(self.p,ok['id'],'no',use_original=True))
        # Original bytes are the saved input, even if user's selected source is removed.
        bad.path.unlink()
        original=self.service.retry_item(self.p,failed['id'],'same-input',use_original=True)
        self.assertEqual(original['input_id'],failed['inputs'][0]['id'])
        self.assertEqual(original['source_id'],failed['latest']['source_id'])
        self.assertEqual(self.counts()['sources'],counts['sources'])
        replacement=self.file('fixed.json',encoded(PROTOCOL))
        service=ImportService(self.db,self.owner,self.storage)
        result=service.retry_item(self.p,failed['id'],'fixed',replacement=replacement)
        self.assertEqual(result['parse_status'],'parsed')
        self.assertNotEqual(result['input_id'],original['input_id'])
        self.assertEqual(service.read_parsed(self.p,failed['id'])['protocol'],PROTOCOL)
        item=service.item(self.p,failed['id'])
        self.assertEqual(len(item['inputs']),2);self.assertEqual(len(item['attempts']),3)
        self.assertEqual(service.read_original(self.p,failed['id'],input_id=original['input_id']),b'{}')
        self.assertEqual(service.item(self.p,ok['id']),ok)
        before=self.counts()
        self.assertEqual(service.retry_item(self.p,failed['id'],'fixed',replacement=replacement),result)
        self.assertEqual(self.counts(),before)
        self.assert_code('idempotency_conflict',lambda:service.retry_item(self.p,failed['id'],'fixed',use_original=True))

    def test_idempotency_response_loss_independent_sources_and_changed_input(self):
        f=self.file('same.txt',b'one')
        first=self.run_batch(f);counts=self.counts()
        self.assertEqual(self.run_batch(f),first);self.assertEqual(counts,self.counts())
        original=f.path.read_bytes();f.path.unlink()
        self.assertEqual(self.run_batch(f),first);self.assertEqual(counts,self.counts())
        f.path.write_bytes(original)
        second=self.run_batch(f,key='independent')
        self.assertNotEqual(first['items'][0]['latest']['source_id'],second['items'][0]['latest']['source_id'])
        f.path.write_bytes(b'changed')
        self.assert_code('idempotency_conflict',lambda:self.run_batch(f))
        pending=self.service.create_batch(self.p,'pending',[f]);f.path.write_bytes(b'changed again')
        b=self.service.process_batch(self.p,pending['id'])
        self.assertEqual(b['items'][0]['latest']['reason'],'input_changed_select_new_version')

    def test_all_entries_auth_project_object_and_forged_selection(self):
        f=self.file('a.txt');b=self.run_batch(f);i=b['items'][0]
        intruder=ImportService(self.db,Principal('dev-other'),self.storage)
        anonymous=ImportService(self.db,None,self.storage)
        calls=[lambda s:s.create_batch(self.p,'x',[f]),lambda s:s.process_batch(self.p,b['id']),
               lambda s:s.batch(self.p,b['id']),lambda s:s.batches(self.p),lambda s:s.item(self.p,i['id']),
               lambda s:s.read_original(self.p,i['id']),lambda s:s.read_parsed(self.p,i['id']),
               lambda s:s.original_location(self.p,i['id']),lambda s:s.retry_item(self.p,i['id'],'x',use_original=True),
               lambda s:s.reassociate(self.p,i['id'],i['inputs'][0]['id'],f),lambda s:s.recover(self.p,b['id'])]
        for s in (intruder,anonymous):
            for call in calls:
                with self.subTest(call=call,s=s):
                    with self.assertRaises(AccessError) as error:call(s)
                    self.assertEqual(error.exception.status,401 if s is anonymous else 404)
        with self.assertRaises(AccessError):anonymous.create_project('x')
        for call in (lambda:self.service.batch(self.q,b['id']),lambda:self.service.item(self.q,i['id']),
                     lambda:self.service.read_original(self.q,i['id']),lambda:self.service.recover(self.q,b['id'])):
            with self.assertRaises(AccessError):call()
        self.assert_code('explicit_selection_required',lambda:self.run_batch({'path':str(f.path),'owner':'dev-t07','authorized':True},key='forged'))

    def test_display_names_and_paths_cannot_escape_or_select_neighbors(self):
        f=self.file('good.txt');unknown=self.root/'neighbor';unknown.write_bytes(b'private-neighbor')
        for name in ('../x.txt','C:\\x.txt','\\\\server\\x','NUL.txt','CON','a.txt:ads','a.','a/b.txt','..'):
            with self.subTest(name=name):self.assert_code('invalid_display_name',lambda:self.run_batch(replace(f,name=name),key=name))
        for path in ('relative.txt',self.root/'..'/'outside',r'\\server\share\file'):
            with self.subTest(path=path):self.assert_code('invalid_local_path',lambda:self.run_batch(replace(f,path=Path(path)),key='badpath'))
        # Merely mentioning neighboring file paths/URLs never reads them.
        doc=self.file('inert.md',f'file: {unknown}\nhttp://127.0.0.1:1/no'.encode())
        b=self.run_batch(doc,key='inert');self.assertEqual(self.service.read_original(self.p,b['items'][0]['id']),doc.path.read_bytes())
        self.assertEqual(unknown.read_bytes(),b'private-neighbor')

    def test_links_and_junction_escape_rejected_without_writing_outside(self):
        outside=self.root/'outside';outside.mkdir();target=outside/'target';target.write_bytes(b'outside')
        link=self.root/'link'
        if os.name=='nt':
            # Junction creation works without Windows symlink privilege.
            result=subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.addCleanup(lambda:os.rmdir(link) if link.exists() else None)
        else:link.symlink_to(outside,target_is_directory=True)
        b=self.run_batch(SelectedFile(link/'target','x.txt'))
        self.assertEqual(b['items'][0]['latest']['reason'],'unsafe_local_path')
        unsafe=ImportService(self.db,self.owner,link)
        b=unsafe.import_files(self.p,'unsafe-root',[self.file('x.txt')])
        self.assertNotEqual(b['items'][0]['latest']['save_status'],'saved')
        self.assertEqual(list(outside.iterdir()),[target])

    def test_no_network_model_cloud_and_save_only_without_authorization(self):
        f=self.file('save.txt',b'only save',parse=False)
        import socket
        with patch.object(socket,'socket',side_effect=AssertionError('no network allowed')):
            b=self.run_batch(f,self.file('cloud.txt',storage_choice='cloud-requested'),
                             self.file('a.html',b'<p>safe<img src="http://example.invalid/x"></p>'))
        self.assertEqual(b['items'][0]['latest']['parse_status'],'not-requested')
        self.assertEqual(self.service.read_original(self.p,b['items'][0]['id']),b'only save')
        self.assertEqual(b['items'][1]['latest']['reason'],'real_cloud_storage_not_connected')
        self.assertEqual(b['items'][1]['inputs'][0]['availability']['status'],'not-saved')
        self.assertEqual(b['items'][2]['semantic_status'],'not-performed')

    def test_failure_stages_preserve_files_database_truth_and_other_items(self):
        for stage in ('before_stage','after_original','before_link','before_result','after_result','before_commit'):
            with self.subTest(stage=stage):
                f=self.file('a.txt',b'first');g=self.file('b.txt',b'other')
                batch=self.service.create_batch(self.p,stage,[f,g]);fired=False
                def failure(at):
                    nonlocal fired
                    if at==stage and not fired:
                        fired=True;raise sqlite3.OperationalError('synthetic secret must not leak')
                broken=ImportService(self.db,self.owner,self.storage,fault=failure)
                b=broken.process_batch(self.p,batch['id'])
                self.assertTrue(fired);self.assertEqual(b['summary'],{'complete':1,'incomplete':1,'total':2})
                self.assertEqual(b['items'][0]['latest']['save_status'],'failed')
                self.assertEqual(self.service.read_original(self.p,b['items'][1]['id']),b'other')
                self.assertNotIn('synthetic secret',json.dumps(b))
                result=self.service.retry_item(self.p,b['items'][0]['id'],'repair',use_original=True)
                self.assertEqual(result['save_status'],'saved')
                self.assertEqual(self.service.read_original(self.p,b['items'][0]['id']),b'first')
                self.assertFalse(list(self.storage.glob('*.stage')))

    def test_real_staging_write_rename_db_association_and_cleanup_failures(self):
        f=self.file('a.txt');batch=self.service.create_batch(self.p,'staging',[f])
        real=localfiles.persist
        def partial(path,data):
            stage=Path(path).with_suffix(Path(path).suffix+'.stage')
            with localfiles.opened(stage,create=True) as out:out.write(data[:2])
            raise ImportFailure('synthetic_stage_failure','save')
        with patch('nextrelay.ingestion.localfiles.persist',side_effect=partial):
            b=self.service.process_batch(self.p,batch['id'])
        self.assertEqual(b['items'][0]['latest']['reason'],'synthetic_stage_failure')
        self.assertFalse(list(self.storage.glob('*.stage')))
        self.assert_code('original_unavailable_reassociate',lambda:self.service.read_original(self.p,b['items'][0]['id']))
        self.service.retry_item(self.p,b['items'][0]['id'],'retry',use_original=True)
        # Cleanup failures remain visible/retryable, never delete unknown files.
        owned=next(self.storage.glob('*.owner'));stage=owned.with_suffix('.original.stage');stage.write_bytes(b'stale')
        unknown=self.storage/'unrelated.stage';unknown.write_bytes(b'unknown')
        with patch('nextrelay.ingestion.localfiles.remove_owned',return_value=False):
            result=self.service.recover(self.p,batch['id'])
        self.assertEqual(result[0]['cleanup'],'cleanup-pending')
        self.assertEqual(self.service.recover(self.p,batch['id'])[0]['cleanup'],'clean')
        self.assertEqual(unknown.read_bytes(),b'unknown')

    def test_unit_of_work_remains_fail_closed(self):
        before=self.counts()
        with self.assertRaises(TransactionAborted):
            with unit_of_work(self.db,self.owner,write=True) as s:
                s.create_source(self.p,reference='synthetic://before-error')
                try:s.get(self.q,'sources','missing')
                except AccessError:pass
        self.assertEqual(self.counts(),before)

    def test_real_process_interrupts_recover_and_response_loss(self):
        for stage in ('before_stage','after_original','before_link','after_result','before_commit','after_commit'):
            with self.subTest(stage=stage):
                f=self.file('process.txt',b'process original')
                batch=self.service.create_batch(self.p,'process-'+stage,[f])
                code='''import os,sys
from nextrelay.auth import Principal
from nextrelay.ingestion import ImportService
def fault(stage):
    if stage==sys.argv[5]:os._exit(23)
s=ImportService(sys.argv[1],Principal(sys.argv[2]),sys.argv[3],fault=fault)
s.process_batch(sys.argv[4],sys.argv[6])
'''
                result=subprocess.run([sys.executable,'-B','-c',code,str(self.db),self.owner.subject,str(self.storage),self.p,stage,batch['id']],capture_output=True,timeout=30)
                self.assertEqual(result.returncode,23,result.stderr)
                results=self.service.recover(self.p,batch['id'])
                self.assertTrue(all(r['cleanup']=='clean' for r in results))
                value=self.service.process_batch(self.p,batch['id']);item=value['items'][0]
                self.assertEqual(self.service.read_original(self.p,item['id']),b'process original')
                self.assertEqual(self.service.read_parsed(self.p,item['id'])['text'],'process original')
                self.assertEqual(len(item['attempts']),1)
                self.assertFalse(list(self.storage.glob('*.stage')))
                with connect(self.db) as c:
                    self.assertEqual(c.execute('SELECT count(*) FROM original_links WHERE input_id=?',(item['inputs'][0]['id'],)).fetchone()[0],1)

    def test_two_actual_connections_same_request_and_failed_item_retry(self):
        f=self.file('a.txt',b'same');barrier=threading.Barrier(2)
        def run(_):
            service=ImportService(self.db,self.owner,self.storage)
            barrier.wait(timeout=10)
            return service.import_files(self.p,'compete',[f])
        with ThreadPoolExecutor(2) as pool:a,b=list(pool.map(run,range(2)))
        self.assertEqual(a,b);self.assertEqual(self.counts()['sources'],1)
        failed=self.run_batch(self.file('bad.json',b'{}'),key='bad')['items'][0]
        fixed=self.file('fixed.json',encoded(PROTOCOL));barrier=threading.Barrier(2)
        def retry(_):
            service=ImportService(self.db,self.owner,self.storage)
            barrier.wait(timeout=10)
            return service.retry_item(self.p,failed['id'],'race-retry',replacement=fixed)
        with ThreadPoolExecutor(2) as pool:a,b=list(pool.map(retry,range(2)))
        self.assertEqual(a,b)
        item=self.service.item(self.p,failed['id']);self.assertEqual(len(item['attempts']),2)
        self.assertEqual(len(item['inputs']),2)
        self.assertEqual(self.service.read_parsed(self.p,failed['id'])['protocol'],PROTOCOL)

    def test_concurrent_different_item_retries_cannot_spend_same_batch_budget(self):
        files=[self.file('saved.txt',b'x'*(3*1024*1024),parse=False) for _ in range(6)]
        files += [self.file('failed.txt',b'\xff'),self.file('failed.txt',b'\xff')]
        b=self.run_batch(*files);ids=[i['id'] for i in b['items'][-2:]]
        fixed=[self.file('fixed.txt',b'y'*MAX_FILE,parse=False) for _ in range(2)]
        barrier=threading.Barrier(2)
        def race(index):
            s=ImportService(self.db,self.owner,self.storage);real=s._selection
            def synchronized(*args,**kwargs):
                value=real(*args,**kwargs);barrier.wait(timeout=15);return value
            s._selection=synchronized
            return s.retry_item(self.p,ids[index],'budget-race',replacement=fixed[index])
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(race,range(2)))
        self.assertEqual(sorted(r['save_status'] for r in results),['rejected','saved'])
        b=self.service.batch(self.p,b['id'])
        accepted=[i['inputs'][-1] for i in b['items'] if i['inputs'][-1]['preflight_error'] is None]
        self.assertLessEqual(sum(i['byte_size'] for i in accepted),MAX_BATCH)
        self.assertEqual(self.service.read_original(self.p,b['items'][0]['id']),b'x'*(3*1024*1024))
        for index,result in enumerate(results):
            self.assertEqual(self.service.retry_item(self.p,ids[index],'budget-race',replacement=fixed[index]),result)

    def test_retry_database_failure_is_persistent_and_same_request_returns_it(self):
        failed=self.run_batch(self.file('bad.json',b'{}'))['items'][0]
        replacement=self.file('fixed.txt',b'fixed')
        def fault(stage):
            if stage=='before_commit':raise sqlite3.OperationalError('synthetic')
        service=ImportService(self.db,self.owner,self.storage,fault=fault)
        result=service.retry_item(self.p,failed['id'],'failed-operation',replacement=replacement)
        self.assertEqual(result['failure_stage'],'transaction')
        self.assertEqual(result['save_status'],'failed')
        self.assertEqual(self.service.retry_item(self.p,failed['id'],'failed-operation',replacement=replacement),result)
        item=self.service.item(self.p,failed['id'])
        self.assertEqual(len(item['inputs']),2);self.assertEqual(len(item['attempts']),2)
        self.assertNotEqual(item['inputs'][0]['fingerprint'],item['inputs'][1]['fingerprint'])
        result=self.service.retry_item(self.p,failed['id'],'new-operation',use_original=True)
        self.assertEqual(result['save_status'],'saved')
        self.assertEqual(self.service.read_original(self.p,failed['id']),b'fixed')

    def test_json_output_limit_is_enforced_before_string_encoder_allocation(self):
        with patch('nextrelay.formats.json.JSONEncoder.iterencode',side_effect=AssertionError('oversized output reached encoder')):
            self.assert_code('output_limit',lambda:parse(b'\x01'*(MAX_FILE//2),'x.txt'))

    def test_replacement_retry_real_process_exit_keeps_registered_identity_and_recovery(self):
        for stage in ('before_stage','after_original','before_link','before_commit','after_commit'):
            with self.subTest(stage=stage):
                old=self.file('bad.json',b'{}');item=self.run_batch(old,key='retry-exit-'+stage)['items'][0]
                new=self.file('new.txt',b'replacement bytes')
                code='''import os,sys
from nextrelay.auth import Principal
from nextrelay.ingestion import ImportService,SelectedFile
from pathlib import Path
def fault(stage):
    if stage==sys.argv[6]:os._exit(31)
s=ImportService(sys.argv[1],Principal(sys.argv[2]),sys.argv[3],fault=fault)
s.retry_item(sys.argv[4],sys.argv[5],'replace-request',replacement=SelectedFile(Path(sys.argv[7]),'new.txt'))
'''
                result=subprocess.run([sys.executable,'-B','-c',code,str(self.db),self.owner.subject,str(self.storage),self.p,item['id'],stage,str(new.path)],capture_output=True,timeout=30)
                self.assertEqual(result.returncode,31,result.stderr)
                registered=self.service.item(self.p,item['id'])
                self.assertEqual(len(registered['inputs']),2)
                with connect(self.db) as c:
                    self.assertEqual(c.execute('SELECT count(*) FROM ingest_retry_plans WHERE item_id=?',(item['id'],)).fetchone()[0],1)
                self.assertTrue(all(r['cleanup']=='clean' for r in self.service.recover(self.p,item['batch_id'])))
                final=self.service.retry_item(self.p,item['id'],'replace-request',replacement=new)
                self.assertEqual(final['parse_status'],'parsed')
                self.assertEqual(self.service.read_original(self.p,item['id']),b'replacement bytes')
                self.assertEqual(self.service.read_original(self.p,item['id'],input_id=item['inputs'][0]['id']),b'{}')
                self.assertEqual(len(self.service.item(self.p,item['id'])['attempts']),2)
                self.assertFalse(list(self.storage.glob('*.stage')))

    def test_marker_creation_immediate_process_exit_can_recover(self):
        f=self.file('a.txt',b'marker interrupted');b=self.service.create_batch(self.p,'marker',[f])
        code='''import os,sys
from contextlib import contextmanager
from nextrelay import localfiles
from nextrelay.auth import Principal
from nextrelay.ingestion import ImportService
real=localfiles.opened
@contextmanager
def opened(path,**kwargs):
    with real(path,**kwargs) as f:
        if kwargs.get('create') and str(path).endswith('.owner'):os._exit(32)
        yield f
localfiles.opened=opened
ImportService(sys.argv[1],Principal(sys.argv[2]),sys.argv[3]).process_batch(sys.argv[4],sys.argv[5])
'''
        result=subprocess.run([sys.executable,'-B','-c',code,str(self.db),self.owner.subject,str(self.storage),self.p,b['id']],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,32,result.stderr)
        self.assertEqual(self.service.recover(self.p,b['id'])[0]['cleanup'],'clean')
        value=self.service.process_batch(self.p,b['id']);item=value['items'][0]
        self.assertEqual(self.service.read_original(self.p,item['id']),b'marker interrupted')

    def test_actual_sql_denial_rolls_back_item_without_poisoning_next(self):
        from contextlib import contextmanager
        from nextrelay import ingestion
        real=ingestion.unit_of_work
        for table in ('sources','original_links','ingest_attempts'):
            fired=False
            @contextmanager
            def guarded(*args,**kwargs):
                nonlocal fired
                with real(*args,**kwargs) as s:
                    def authorizer(action,name,*unused):
                        nonlocal fired
                        if action==sqlite3.SQLITE_INSERT and name==table and not fired:
                            fired=True;return sqlite3.SQLITE_DENY
                        return sqlite3.SQLITE_OK
                    s._connection.set_authorizer(authorizer)
                    yield s
            b=self.service.create_batch(self.p,'deny-'+table,[self.file('first.txt',b'first'),self.file('next.txt',b'next')])
            with patch('nextrelay.ingestion.unit_of_work',guarded):result=self.service.process_batch(self.p,b['id'])
            self.assertTrue(fired);self.assertEqual(result['summary']['complete'],1)
            self.assertEqual(result['items'][0]['latest']['save_status'],'failed')
            self.assertEqual(self.service.read_original(self.p,result['items'][1]['id']),b'next')
            self.assertFalse(list(self.storage.glob('*.stage')))

    def test_atomic_rename_failure_does_not_fake_saved_original(self):
        f=self.file('a.txt');b=self.service.create_batch(self.p,'rename',[f])
        function='os.rename' if os.name=='nt' else 'os.link'
        with patch('nextrelay.localfiles.'+function,side_effect=OSError('synthetic rename denied')):
            value=self.service.process_batch(self.p,b['id'])
        item=value['items'][0]
        self.assertEqual(item['latest']['save_status'],'failed')
        self.assertEqual(item['inputs'][0]['availability']['status'],'not-saved')
        self.assertFalse(list(self.storage.glob('*.stage')))
        self.assertEqual(self.service.retry_item(self.p,item['id'],'retry',use_original=True)['save_status'],'saved')

    def test_expired_24h_stage_fails_without_reusing_or_extending_and_explicit_retry_works(self):
        b=self.service.create_batch(self.p,'expired',[self.file('a.txt',b'fresh original')])
        with unit_of_work(self.db,self.owner) as s:inp=s.records(self.p,'ingest_inputs')[0]
        paths=self.service._claim(inp)
        stage=paths['original'].with_suffix('.original.stage');stage.write_bytes(b'expired incomplete data')
        past=time.time()-24*3600-1;os.utime(stage,(past,past))
        b=self.service.process_batch(self.p,b['id']);item=b['items'][0]
        self.assertEqual(item['latest']['reason'],'temporary_expired_retry_required')
        self.assertFalse(stage.exists())
        self.assertEqual(self.service.retry_item(self.p,item['id'],'explicit-retry',use_original=True)['save_status'],'saved')
        self.assertEqual(self.service.read_original(self.p,item['id']),b'fresh original')

    def test_pending_same_item_different_key_is_rejected_without_registering_phantom_input(self):
        item=self.run_batch(self.file('bad.json',b'{}'))['items'][0]
        fixed=self.file('fixed.txt',b'first replacement')
        # Reserve the first request but pause before processing, as after a
        # process exit. A second connection cannot register another input.
        with patch.object(self.service,'_process',return_value={'reserved':True}):
            self.service.retry_item(self.p,item['id'],'first-key',replacement=fixed)
        other=ImportService(self.db,self.owner,self.storage)
        self.assert_code('retry_in_progress_resume_original_key',lambda:other.retry_item(self.p,item['id'],'second-key',replacement=self.file('other.txt',b'second replacement')))
        pending=other.item(self.p,item['id'])
        self.assertEqual(len(pending['inputs']),2)
        self.assertEqual(pending['retry_requests'][0]['request_key'],'first-key')
        self.assertIsNone(pending['retry_requests'][0]['attempt_id'])
        self.assertEqual(other.read_original(self.p,item['id']),b'{}')
        result=other.retry_item(self.p,item['id'],'first-key',replacement=fixed)
        self.assertEqual(result['parse_status'],'parsed')
        self.assertEqual(other.read_original(self.p,item['id']),b'first replacement')
        self.assertEqual(other.item(self.p,item['id'])['current_input_id'],result['input_id'])

    def test_missing_marker_retains_unknown_stage_and_reports_unresolved_not_clean(self):
        b=self.service.create_batch(self.p,'missing-marker',[self.file('a.txt')])
        item=self.service.batch(self.p,b['id'])['items'][0]
        stage=self.storage/(item['inputs'][0]['id']+'.original.stage')
        stage.write_bytes(b'unknown ownership must survive')
        self.assertEqual(self.service.recover(self.p,b['id'])[0]['cleanup'],'cleanup-pending')
        self.assertEqual(stage.read_bytes(),b'unknown ownership must survive')
        self.assertEqual(self.service.item(self.p,item['id'])['inputs'][0]['temporary_cleanup'],'cleanup-pending')
        value=self.service.process_batch(self.p,b['id'])['items'][0]
        self.assertEqual(value['latest']['failure_stage'],'cleanup')
        self.assertEqual(value['latest']['reason'],'cleanup_pending')

    def test_expired_parse_stage_retains_actual_saved_original_and_source(self):
        item=self.run_batch(self.file('bad.json',b'{}'))['items'][0]
        stage=self.storage/(item['inputs'][0]['id']+'.parsed.json.stage');stage.write_bytes(b'expired parse')
        past=time.time()-24*3600-1;os.utime(stage,(past,past))
        result=self.service.retry_item(self.p,item['id'],'expired-parse',use_original=True)
        self.assertEqual(result['reason'],'temporary_expired_retry_required')
        self.assertEqual(result['failure_stage'],'cleanup')
        self.assertEqual(result['save_status'],'saved')
        self.assertEqual(result['source_id'],item['latest']['source_id'])
        self.assertEqual(self.service.read_original(self.p,item['id']),b'{}')
        self.assertFalse(stage.exists())

    def test_readme_synthetic_example_real_process(self):
        result=subprocess.run([sys.executable,'-B','-W','error::ResourceWarning','-m','examples.t07_synthetic'],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(b'formal revision unchanged',result.stdout)
