"""T10 real HTTP + SQLite + original files, synthetic fixtures only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import subprocess
import sys
import os
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from nextrelay.auth import Principal,AccessError
from nextrelay.db import initialize,connect,transaction,SCHEMA_VERSION
from nextrelay.schema import MIGRATIONS
from nextrelay.formats import ImportFailure
from nextrelay.github import GitHubService
from nextrelay.github_http import GitHubHTTP,GitHubConfig,parse_url,addresses,MAX_METADATA
from nextrelay.ingestion import ImportService,SelectedFile
from nextrelay.store import unit_of_work,Store
from nextrelay.native import NativeService
from github_support import github_server,C1,C2,T1,T2,SUB,blob,entry

class GitHubTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='nextrelay-t10-test-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.storage=self.root/'originals';self.storage.mkdir();self.db=self.root/'db.sqlite3';initialize(self.db)
        self.owner=Principal('dev-github-test');self.imp=ImportService(self.db,self.owner,self.storage)
        self.p=self.imp.create_project('Synthetic GitHub')['id'];self.q=self.imp.create_project('Other')['id']
        self.remote=self.enterContext(github_server());self.s=GitHubService(self.imp,self.remote.config)
    def action(self,action='prepare',body=None,b=None,key=None):
        return self.s.action(self.p,key or str(uuid4()),action,body if body is not None else (dict(url='https://github.com/test/repo',storage_choice='configured-local') if action=='prepare' else {}),b)
    def prepare(self,url='https://github.com/test/repo',**kw):return self.action(body=dict(url=url,storage_choice='configured-local',**kw))
    def read(self,b):return self.action('read',b=b['id'])
    def bodies(self):return [p for p in self.remote.requests if '/git/blobs/' in p]
    def code(self,code,fn):
        with self.assertRaises(ImportFailure) as cm:fn()
        self.assertEqual(cm.exception.code,code)
    def test_repository_fixed_commit_metadata_vs_body_and_bridge(self):
        b=self.prepare();self.assertEqual(b['git_commit'],C1);self.assertEqual(self.bodies(),[])
        self.assertTrue(b['complete']);self.assertEqual(b['scopes'][0]['paths'],['README.md'])
        self.remote.commit=C2;b=self.read(b)
        self.assertEqual(b['git_commit'],C1);self.assertEqual(len(self.bodies()),1)
        read=next(e for e in b['entries'] if e['read_status']=='read');self.assertEqual(read['path'],'README.md');self.assertEqual(read['processing']['parse'],'parsed')
        self.assertEqual(self.imp.read_original(self.p,read['item_id']),next(iter(self.remote.data.values())))
        with unit_of_work(self.db,self.owner) as s:
            source=s.get(self.p,'sources',self.imp.item(self.p,read['item_id'])['latest']['source_id'])
            self.assertEqual((source['git_commit'],source['source_path']),(C1,'README.md'));self.assertEqual(s.records(self.p,'model_events'),[])
            self.assertEqual(s.formal_state(self.p)['tasks'],[])
        result=NativeService(self.imp).extract_item(self.p,read['item_id'],base_revision=0)
        self.assertIsNotNone(result)
        self.assertTrue(all('Authorization' not in h for h in self.remote.headers))
    def test_file_directory_and_slash_ref(self):
        for url,extra,expected in [('blob/main/docs/note.md',{},['README.md','docs/note.md']),('tree/main/docs',{},['README.md','docs/note.md']),('blob/feature/docs/docs/note.md',{'ref':'feature/docs'},['README.md','docs/note.md'])]:
            b=self.prepare('https://github.com/test/repo/'+url,**extra);self.assertEqual(b['scopes'][0]['paths'],expected)
            self.assertEqual(self.read(b)['state'],'read')
    def test_retry_cannot_claim_complete_when_known_child_is_omitted(self):
        original=self.remote.respond
        def truncated(path):
            if path.endswith('/git/trees/'+T1):
                status,body=original(path);return status,{**body,'truncated':True}
        self.remote.behavior=truncated;b=self.read(self.prepare());old=next(e for e in b['entries'] if e['item_id']);calls=len(self.bodies())
        def omitted(path):
            if path.endswith('/git/trees/'+T1):return 200,dict(sha=T1,truncated=False,tree=self.remote.trees[T1][1:])
        self.remote.behavior=omitted;b=self.action('retry',b=b['id'])
        self.assertFalse(b['complete']);self.assertTrue(any(x['reason']=='github_tree_identity_mismatch' for x in b['unknown_ranges']))
        self.assertEqual(len(self.bodies()),calls);self.assertEqual(next(e for e in b['entries'] if e['id']==old['id'])['input_id'],old['input_id'])

    def test_process_exit_before_deep_request_does_not_hide_pending_descendants(self):
        deep='d'*40
        self.remote.trees[SUB]=[entry('later',kind='tree',mode='040000',sha=deep)]
        self.remote.trees[deep]=[entry('hidden.md',b'# New\n')]
        script="""import sys,os
from pathlib import Path
from nextrelay.ingestion import ImportService
from nextrelay.github import GitHubService
from nextrelay.github_http import GitHubConfig
from nextrelay.auth import Principal
class KillBeforeReserve(GitHubService):
 def request(self,p,identity,token,path,limit,**kwargs):
  if path.endswith('/git/trees/'+'d'*40):os._exit(75)
  return super().request(p,identity,token,path,limit,**kwargs)
imp=ImportService(Path(sys.argv[1]),Principal('dev-github-test'),Path(sys.argv[2]))
s=KillBeforeReserve(imp,GitHubConfig(_test_endpoint=sys.argv[4]));s.action(sys.argv[3],'crash-deep-prepare','prepare',{'url':'https://github.com/test/repo/tree/main/docs','storage_choice':'configured-local'})
"""
        proc=subprocess.run([sys.executable,'-B','-c',script,str(self.db),str(self.storage),self.p,self.remote.config._test_endpoint],capture_output=True,timeout=15)
        self.assertEqual(proc.returncode,75,proc.stderr.decode())
        with connect(self.db) as c:
            identity=c.execute("SELECT snapshot_id FROM github_requests WHERE request_key='crash-deep-prepare'").fetchone()[0]
            c.execute('UPDATE github_snapshots SET lease_until=? WHERE id=?',(time.time()-1,identity))
        before=self.s.get(self.p,identity);states={e['path']:e['children_status'] for e in before['entries']}
        self.assertEqual(states['docs'],'complete');self.assertEqual(states['docs/later'],'pending');self.assertEqual(before['metadata_reserved'],0)
        self.action('recover',b=identity);refs=sum('/commits/' in x for x in self.remote.requests);self.remote.commit=C2
        b=self.action('retry',b=identity)
        self.assertEqual(b['git_commit'],C1);self.assertTrue(b['complete']);self.assertEqual(b['unknown_ranges'],[])
        self.assertIn('docs/later/hidden.md',[e['path'] for e in b['entries']]);self.assertEqual(sum('/commits/' in x for x in self.remote.requests),refs)
        self.assertTrue(all(e['children_status']=='complete' for e in b['entries'] if e['kind']=='tree'))
        self.assertEqual(self.bodies(),[]);self.assertEqual(next(x for x in b['scopes'] if x['kind']=='expansion')['paths'],['README.md','docs/later/hidden.md'])

    def test_process_exit_during_directory_enumeration_resumes_unknown_children(self):
        script="""import sys,os
from pathlib import Path
from nextrelay.ingestion import ImportService
from nextrelay.github import GitHubService
from nextrelay.github_http import GitHubConfig
from nextrelay.auth import Principal
imp=ImportService(Path(sys.argv[1]),Principal('dev-github-test'),Path(sys.argv[2]),fault=lambda stage:os._exit(74) if stage=='github_after_directory_entry' else None)
s=GitHubService(imp,GitHubConfig(_test_endpoint=sys.argv[4]));s.action(sys.argv[3],'crash-tree-prepare','prepare',{'url':'https://github.com/test/repo/tree/main/docs','storage_choice':'configured-local'})
"""
        proc=subprocess.run([sys.executable,'-B','-c',script,str(self.db),str(self.storage),self.p,self.remote.config._test_endpoint],capture_output=True,timeout=15)
        self.assertEqual(proc.returncode,74,proc.stderr.decode())
        with connect(self.db) as c:
            identity=c.execute("SELECT snapshot_id FROM github_requests WHERE request_key='crash-tree-prepare'").fetchone()[0]
            c.execute('UPDATE github_snapshots SET lease_until=? WHERE id=?',(time.time()-1,identity))
        self.action('recover',b=identity);refs=sum('/commits/' in x for x in self.remote.requests)
        self.remote.commit=C2;b=self.action('retry',b=identity)
        self.assertEqual(b['git_commit'],C1);self.assertTrue(b['complete']);self.assertEqual(sum('/commits/' in x for x in self.remote.requests),refs)
        self.assertEqual(next(e for e in b['entries'] if e['path']=='docs')['children_status'],'complete')
        self.assertIn('docs/note.md',[e['path'] for e in b['entries']]);self.assertEqual(self.bodies(),[])
        self.assertEqual(next(x for x in b['scopes'] if x['kind']=='expansion')['paths'],['README.md','docs/note.md'])

    def test_retry_metadata_keeps_pin_new_paths_need_confirmation(self):
        self.remote.behavior=lambda path:(500,{}) if path.endswith('/git/trees/'+T1) else None
        b=self.prepare();self.assertFalse(b['complete']);identity=b['id'];self.assertEqual(b['git_commit'],C1)
        self.remote.behavior=None;self.remote.commit=C2;refs=sum('/commits/' in p for p in self.remote.requests)
        b=self.action('retry',b=identity)
        self.assertEqual(b['id'],identity);self.assertEqual(b['git_commit'],C1);self.assertTrue(b['complete'])
        self.assertEqual(sum('/commits/' in p for p in self.remote.requests),refs);self.assertEqual(self.bodies(),[])
        scope=next(s for s in b['scopes'] if s['kind']=='expansion')
        self.assertEqual(scope['paths'],['README.md']);self.assertIsNone(scope['approved_at'])
        self.action('confirm',{'scope_id':scope['id'],'fingerprint':scope['fingerprint']},identity)
        b=self.read(b);self.assertEqual(len(self.bodies()),1);self.assertEqual(b['state'],'read')
        self.assertTrue(self.bodies()[0].endswith(blob(next(iter(self.remote.data.values())))))

    def test_retry_child_metadata_preserves_successful_body_and_scopes(self):
        self.remote.behavior=lambda path:(500,{}) if path.endswith('/git/trees/'+SUB) else None
        b=self.read(self.prepare('https://github.com/test/repo/tree/main/docs'));n=len(self.bodies())
        self.assertEqual(n,1);self.remote.behavior=None
        root_reads=self.remote.requests.count('/repos/test/repo/git/trees/'+T1)
        b=self.action('retry',b=b['id']);self.assertTrue(b['complete']);self.assertEqual(len(self.bodies()),n)
        self.assertEqual(self.remote.requests.count('/repos/test/repo/git/trees/'+T1),root_reads)
        scope=next(s for s in b['scopes'] if s['kind']=='expansion');self.assertEqual(scope['paths'],['docs/note.md'])
        self.action('confirm',{'scope_id':scope['id'],'fingerprint':scope['fingerprint']},b['id'])
        self.read(b);self.assertEqual(len(self.bodies()),n+1)

    def test_metadata_retry_cannot_reset_exhausted_budget(self):
        self.remote.behavior=lambda path:(200,b'x'*(MAX_METADATA+2),{'Content-Type':'application/json'}) if '/git/trees/' in path else None
        b=self.prepare();requests=len(self.remote.requests);self.assertEqual(b['metadata_bytes'],MAX_METADATA+1)
        self.remote.behavior=None;b=self.action('retry',b=b['id'])
        self.assertEqual(len(self.remote.requests),requests);self.assertEqual(b['metadata_bytes'],MAX_METADATA+1);self.assertFalse(b['complete'])

    def test_prepare_uses_sha_only_ref_and_fixed_git_metadata_without_patches(self):
        b=self.prepare();self.assertEqual(b['git_commit'],C1);self.assertEqual(self.bodies(),[])
        paths=self.remote.requests;headers=self.remote.headers
        self.assertIn('/repos/test/repo/git/commits/'+C1,paths)
        for path,head in zip(paths,headers):
            if '/commits/' in path and '/git/commits/' not in path:self.assertEqual(head['Accept'],'application/vnd.github.sha')
            if '/git/commits/' in path:self.assertEqual(path.rsplit('/',1)[-1],C1)
        # If a server ignores the SHA representation and returns patch JSON,
        # reject it; no parser or candidate receives those bytes.
        self.remote.behavior=lambda path:(200,b'{"sha":"'+C1.encode()+b'","files":[{"patch":"unread"}]}') if '/commits/' in path and '/git/' not in path else None
        self.assertEqual(self.prepare()['state'],'failed')

    def test_branch_root_link_does_not_default_to_whole_repository(self):
        b=self.prepare('https://github.com/test/repo/tree/main')
        self.assertEqual(b['scopes'][0]['paths'],['README.md'])
        b=self.read(b);self.assertEqual(len(self.bodies()),1)
        self.assertEqual(next(e for e in b['entries'] if e['path']=='docs/note.md')['read_status'],'not-selected')

    def test_ambiguous_ref_requires_explicit_and_mismatch(self):
        self.remote.refs['main/docs']=C2
        b=self.prepare('https://github.com/test/repo/blob/main/docs/note.md');self.assertEqual(b['code'],'github_ambiguous_ref_path');self.assertEqual(self.bodies(),[])
        self.assertEqual(self.prepare('https://github.com/test/repo/blob/main/docs/note.md',ref='wrong')['code'],'github_ref_url_mismatch')
    def test_expansion_zero_reads_forged_expired_and_exact_paths(self):
        b=self.read(self.prepare());n=len(self.bodies());b=self.action('expand',{'paths':['docs/note.md']},b['id']);scope=b['scopes'][-1]
        self.read(b);self.assertEqual(len(self.bodies()),n)
        self.code('github_scope_confirmation_invalid_or_expired',lambda:self.action('confirm',{'scope_id':scope['id'],'fingerprint':'forged'},b['id']))
        with connect(self.db) as c:c.execute('UPDATE github_scopes SET approved_at=NULL WHERE id=?',(scope['id'],))
        self.action('confirm',{'scope_id':scope['id'],'fingerprint':scope['fingerprint']},b['id']);b=self.read(b)
        self.assertEqual(len(self.bodies()),n+1);self.assertEqual(next(e for e in b['entries'] if e['path']=='other.md')['read_status'],'not-selected')
        b=self.action('expand',{'paths':['other.md']},b['id']);scope=b['scopes'][-1]
        with patch('nextrelay.github.time.time',return_value=time.time()+2000):
            self.code('github_scope_confirmation_invalid_or_expired',lambda:self.action('confirm',{'scope_id':scope['id'],'fingerprint':scope['fingerprint']},b['id']))
    def test_partial_failure_retry_same_commit_update_new_snapshot(self):
        b=self.prepare('https://github.com/test/repo/tree/main/docs');sha=blob(b'# Doc\nSynthetic measurement\n')
        self.remote.behavior=lambda path:(500,{}) if path.endswith('/git/blobs/'+sha) else None
        b=self.read(b);self.assertEqual(b['state'],'partial');self.assertEqual(sum(e['read_status']=='read' for e in b['entries']),1)
        self.remote.commit=C2;self.remote.behavior=None;old_calls=len(self.bodies());b=self.action('retry',b=b['id'])
        self.assertEqual(b['git_commit'],C1);self.assertEqual(b['state'],'read');self.assertEqual(len(self.bodies()),old_calls+1)
        new=self.action('update',b=b['id']);self.assertEqual(new['git_commit'],C2);self.assertEqual(new['parent_id'],b['id']);self.assertEqual(self.s.get(self.p,b['id'])['git_commit'],C1)
    def test_idempotency_concurrent_read_and_no_write_lock_during_network(self):
        key=str(uuid4());body=dict(url='https://github.com/test/repo',storage_choice='configured-local')
        b=self.action(body=body,key=key);n=len(self.remote.requests);self.assertEqual(self.action(body=body,key=key)['id'],b['id']);self.assertEqual(len(self.remote.requests),n)
        self.code('github_idempotency_conflict',lambda:self.action(body={**body,'url':'https://example.com'},key=key))
        entered=threading.Event();release=threading.Event()
        def behavior(path):
            if '/git/blobs/' in path:entered.set();release.wait(3)
        self.remote.behavior=behavior
        with ThreadPoolExecutor(2) as pool:
            f=pool.submit(self.read,b);self.assertTrue(entered.wait(3))
            self.imp.create_project('Network does not lock DB')
            self.code('github_busy',lambda:self.read(b));release.set();self.assertEqual(f.result()['state'],'read')
        self.assertEqual(len(self.bodies()),1)
    def test_cross_project_and_principal_rejected_before_network(self):
        b=self.prepare();n=len(self.remote.requests)
        with self.assertRaises(AccessError):self.s.action(self.q,str(uuid4()),'read',{},b['id'])
        foreign=GitHubService(ImportService(self.db,Principal('dev-foreign'),self.storage),self.remote.config)
        with self.assertRaises(AccessError):foreign.get(self.p,b['id'])
        self.assertEqual(len(self.remote.requests),n)
    def test_ordinary_url_no_fetch_private_and_unconfirmed_fail(self):
        b=self.prepare('https://example.com/notes');self.assertEqual(b['state'],'reference-only');self.assertEqual(self.remote.requests,[])
        for metadata in [dict(private=True,visibility='private',full_name='test/repo'),dict(private=False,full_name='test/repo')]:
            self.remote.behavior=lambda path,m=metadata:(200,m)
            b=self.prepare();self.assertEqual(b['code'],'github_public_repository_unconfirmed');self.assertEqual(self.bodies(),[])
    def test_url_path_and_endpoint_attacks(self):
        for url in ['http://github.com/a/b','https://u:p@github.com/a/b','https://github.com:443/a/b','https://github.com/a/b/blob/main/%2e%2e/key','https://github.com/a/b/blob/main/%252e%252e/key','https://github.com/a/b/blob/main/a%5cb','https://github.com/a/b?x=1','https://github.com/a/b/blob/main/a%00b']:
            with self.assertRaises(ImportFailure,msg=url):parse_url(url)
        for target in ['https://evil.example','http://localhost:1234','http://127.0.0.1:1234/path']:
            with self.assertRaises(ValueError):GitHubConfig(_test_endpoint=target)
        with self.assertRaises(ImportFailure):self.s.http.get('https://127.0.0.1/',10)
    def test_dns_denies_mixed_private_and_pins_public(self):
        for ip in ['127.0.0.1','10.1.2.3','169.254.169.254','::1','fc00::1','100.64.0.1','224.0.0.1','239.255.255.250','ff02::1','ff0e::1','fec0::1','::ffff:224.0.0.1']:
            with patch('nextrelay.github_http.socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))]):
                self.code('github_target_denied',lambda:addresses(time.monotonic()+1))
        with patch('nextrelay.github_http.socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]):self.assertEqual(addresses(time.monotonic()+1)[0][4][0],'8.8.8.8')
    def test_redirect_does_not_follow_and_rate_limit_has_no_retry(self):
        for status,code in [(302,'github_redirect_denied'),(429,'github_rate_limited_manual_retry'),(403,'github_rate_limited_manual_retry')]:
            self.remote.behavior=lambda path,st=status:(st,b'',{'Location':'http://169.254.169.254/latest','Retry-After':'60'})
            n=len(self.remote.requests);b=self.prepare();self.assertEqual(b['code'],code);self.assertEqual(len(self.remote.requests),n+1)
    def test_tree_truncated_unknown_ranges_and_malicious_entry(self):
        orig=self.remote.respond
        def truncated(path):
            if path.endswith(T1):
                status,body=orig(path);return status,{**body,'truncated':True}
        self.remote.behavior=truncated;b=self.prepare();self.assertFalse(b['complete']);self.assertTrue(b['unknown_ranges']);self.assertEqual(self.read(b)['state'],'partial')
        self.remote.trees[T1]=[entry('../escape')];self.remote.behavior=None;b=self.prepare();self.assertFalse(b['complete']);self.assertEqual(b['entries'],[])
    def test_stream_limit_not_parsed_and_actual_bytes_charged(self):
        b=self.prepare();self.remote.behavior=lambda path:(200,b'x'*20000) if '/git/blobs/' in path else None
        with patch('nextrelay.github.MAX_CONTENT',100):b=self.read(b)
        self.assertEqual(b['content_bytes'],101);self.assertEqual(b['entries'][0]['code'],'github_stream_limit')
        self.assertFalse(any(e['item_id'] for e in b['entries']))
    def test_directory_entry_budget_preserves_known_and_unknown(self):
        with patch('nextrelay.github.MAX_ENTRIES',2):b=self.prepare()
        self.assertEqual(len(b['entries']),2);self.assertFalse(b['complete']);self.assertTrue(b['unknown_ranges'])
    def test_directory_byte_budget_and_invalid_json(self):
        self.remote.behavior=lambda p:(200,b'x'*(MAX_METADATA+500),{'Content-Type':'application/json'}) if '/git/trees/' in p else None
        b=self.prepare();self.assertFalse(b['complete']);self.assertEqual(b['metadata_bytes'],MAX_METADATA+1);self.assertTrue(b['unknown_ranges'])
        self.remote.behavior=lambda p:(200,b'{"private":false,"private":false}',{'Content-Type':'application/json'})
        self.assertEqual(self.prepare()['code'],'github_invalid_response')
    def test_content_file_count_budget_and_more_than_upload_20(self):
        content=b'notes';sha=blob(content);self.remote.data[sha]=content
        self.remote.trees[SUB]=[entry(f'd{i}.txt',content) for i in range(23)]
        b=self.read(self.prepare('https://github.com/test/repo/tree/main/docs'));self.assertEqual(sum(e['item_id'] is not None for e in b['entries']),24)
        with patch('nextrelay.github.MAX_FILES',1):b=self.read(self.prepare('https://github.com/test/repo/tree/main/docs'))
        self.assertEqual(b['content_reads'],1);self.assertEqual(b['state'],'partial')
    def test_symlink_submodule_lfs_binary_unsupported_not_followed(self):
        lfs=b'version https://git-lfs.github.com/spec/v1\noid sha256:000\n';binary=b'abc\x00def'
        for data in (lfs,binary):self.remote.data[blob(data)]=data
        self.remote.trees[SUB]=[entry('link.md',mode='120000'),entry('sub',mode='160000',kind='commit'),entry('lfs.txt',lfs),entry('image.bin',binary),entry('code.py',b'# New\n')]
        b=self.read(self.prepare('https://github.com/test/repo/tree/main/docs'));status={e['path']:e for e in b['entries']}
        self.assertEqual(status['docs/link.md']['code'],'symlink_not_followed');self.assertEqual(status['docs/sub']['code'],'submodule_not_followed')
        self.assertEqual(status['docs/lfs.txt']['code'],'lfs_pointer_not_followed');self.assertEqual(status['docs/image.bin']['code'],'binary_not_parsed')
        self.assertEqual(status['docs/code.py']['processing']['parse'],'unsupported')
        self.assertEqual(len(self.bodies()),4)
    def test_blob_hash_mismatch_no_import(self):
        b=self.prepare();self.remote.behavior=lambda path:(200,b'forged') if '/git/blobs/' in path else None
        b=self.read(b);self.assertEqual(next(e for e in b['entries'] if e['read_status']=='failed')['code'],'github_blob_identity_mismatch');self.assertFalse(any(e['item_id'] for e in b['entries']))
    def test_timeout_and_retry_bound(self):
        b=self.prepare()
        def slow(path):
            if '/git/blobs/' in path:time.sleep(.1)
        self.remote.behavior=slow;self.s.http=GitHubHTTP(replace(self.remote.config,timeout=.03))
        b=self.read(b);self.assertEqual(b['state'],'partial')
        for _ in range(4):b=self.action('retry',b=b['id'])
        self.assertEqual(len(self.bodies()),3)
    def test_recover_expired_lease_and_success_never_reimported(self):
        b=self.read(self.prepare());count=len(self.bodies());e=next(x for x in b['entries'] if x['item_id'])
        with connect(self.db) as c:c.execute("UPDATE github_snapshots SET state='reading',lease='dead',lease_until=? WHERE id=?",(time.time()-1,b['id']))
        self.action('recover',b=b['id']);b=self.action('retry',b=b['id']);self.assertEqual(len(self.bodies()),count);self.assertEqual(next(x for x in b['entries'] if x['item_id'])['item_id'],e['item_id'])
    def test_malformed_nested_metadata_fails_without_stuck_lease(self):
        original=self.remote.respond
        for fullname in (None,17,[]):
            self.remote.behavior=lambda path,value=fullname:(200,dict(private=False,visibility='public',full_name=value))
            b=self.prepare();self.assertEqual(b['state'],'failed');self.assertIsNone(b['lease_until'])
        for detail in (None,[],{'tree':None},{'tree':[]}):
            self.remote.behavior=lambda path,value=detail:(200,dict(sha=C1,**value) if isinstance(value,dict) else value) if '/git/commits/' in path else None
            b=self.prepare();self.assertEqual(b['state'],'failed');self.assertIsNone(b['lease_until'])
        self.remote.behavior=None;self.remote.trees[T1]=[entry('huge',sha='f'*40)]
        self.remote.trees[T1][0]['size']=2**100
        b=self.prepare();self.assertFalse(b['complete']);self.assertNotEqual(b['state'],'preparing')

    def test_local_replacement_does_not_relabel_remote_input_processing(self):
        data=b'{}';self.remote.data[blob(data)]=data;self.remote.trees[SUB]=[entry('broken.json',data)]
        b=self.read(self.prepare('https://github.com/test/repo/tree/main/docs'));e=next(e for e in b['entries'] if e['path']=='docs/broken.json')
        self.assertEqual(e['processing']['parse'],'failed');original=e['input_id']
        replacement=self.root/'replacement';replacement.write_bytes(b'# Local replacement\n')
        self.imp.retry_item(self.p,e['item_id'],'replacement-request',replacement=SelectedFile(replacement,'replacement.md'))
        NativeService(self.imp).extract_item(self.p,e['item_id'],base_revision=0)
        after=next(x for x in self.s.get(self.p,b['id'])['entries'] if x['id']==e['id'])
        self.assertEqual(after['input_id'],original);self.assertEqual(after['processing']['input_id'],original)
        self.assertEqual(after['processing']['parse'],'failed');self.assertEqual(after['processing']['semantic'],'not-performed')
        self.assertEqual(after['processing']['fingerprint'],e['sha256']);self.assertNotEqual(after['local_replacement_input_id'],original)

    def test_failed_confirmation_replay_retains_exact_failure(self):
        b=self.prepare();key=str(uuid4());body={'scope_id':'missing','fingerprint':'wrong'}
        for _ in range(2):
            with self.assertRaises(AccessError) as cm:self.action('confirm',body,b['id'],key=key)
            self.assertEqual((cm.exception.status,cm.exception.code),(404,'object_not_found'))
        b=self.action('expand',{'paths':['docs/note.md']},b['id']);scope=b['scopes'][-1];key=str(uuid4())
        for _ in range(2):self.code('github_scope_confirmation_invalid_or_expired',lambda:self.action('confirm',{'scope_id':scope['id'],'fingerprint':'wrong'},b['id'],key=key))
        self.assertEqual(self.bodies(),[])

    def test_extensionless_readme_is_utf8_text_without_changing_source_path(self):
        self.remote.trees[T1]=[entry('README',b'# New\n')]
        b=self.read(self.prepare());e=b['entries'][0]
        self.assertEqual(e['path'],'README');self.assertEqual(e['processing']['parse'],'parsed')
        self.assertEqual(self.imp.item(self.p,e['item_id'])['inputs'][0]['name'],'README')

    def test_request_and_metadata_work_bounds(self):
        with patch('nextrelay.github.MAX_REQUESTS',1):b=self.prepare()
        self.assertEqual(b['state'],'failed');self.assertEqual(b['code'],'github_request_budget');self.assertEqual(b['request_count'],1)
        self.assertEqual(len(self.remote.requests),1)

    def test_process_exit_preserves_budget_pin_and_no_duplicate_persistence(self):
        b=self.prepare();before=len(self.bodies())
        script="""import sys,os
from pathlib import Path
from nextrelay.ingestion import ImportService,SelectedFile
from nextrelay.github import GitHubService
from nextrelay.github_http import GitHubConfig
from nextrelay.auth import Principal
imp=ImportService(Path(sys.argv[1]),Principal('dev-github-test'),Path(sys.argv[2]),fault=lambda stage:os._exit(73) if stage=='before_result' else None)
s=GitHubService(imp,GitHubConfig(_test_endpoint=sys.argv[5]));s.action(sys.argv[3],'crash-request-key','read',{},sys.argv[4])
"""
        proc=subprocess.run([sys.executable,'-B','-c',script,str(self.db),str(self.storage),self.p,b['id'],self.remote.config._test_endpoint],capture_output=True,timeout=15)
        self.assertEqual(proc.returncode,73,proc.stderr.decode());self.assertEqual(len(self.bodies()),before+1)
        with connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM ingest_items').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM ingest_attempts').fetchone()[0],0)
            c.execute('UPDATE github_snapshots SET lease_until=? WHERE id=?',(time.time()-1,b['id']))
        after=GitHubService(self.imp,self.remote.config);after.action(self.p,'recover-crash-key','recover',{},b['id'])
        out=after.action(self.p,'retry-crash-key','retry',{},b['id']);self.assertEqual(out['git_commit'],C1)
        self.assertEqual(sum(e['item_id'] is not None for e in out['entries']),1)
        # Replaying the crashed request is a status lookup, never a new GET.
        count=len(self.bodies());after.action(self.p,'crash-request-key','read',{},b['id']);self.assertEqual(len(self.bodies()),count)
        with connect(self.db) as c:self.assertEqual(c.execute('SELECT count(*) FROM ingest_items').fetchone()[0],1)

    def test_unsettled_interrupted_reservation_cannot_reset_budget(self):
        b=self.prepare()
        # Simulate process death after reserving the response and before accounting.
        with connect(self.db) as c:
            c.execute("UPDATE github_snapshots SET state='reading',lease='dead',lease_until=?,content_reserved=? WHERE id=?",(time.time()-1,10*1024*1024,b['id']))
        self.action('recover',b=b['id']);b=self.action('retry',b=b['id'])
        self.assertEqual(self.bodies(),[]);self.assertEqual(b['content_reserved'],10*1024*1024)
        self.assertEqual(b['state'],'partial')

    def test_v9_upgrade_preserves_relationships(self):
        db=self.root/'v9.sqlite3'
        with connect(db) as c:
            for i in range(1,10):
                for ddl in MIGRATIONS[i]:c.execute(ddl)
            c.execute('PRAGMA user_version=9')
        with connect(db) as c, transaction(c):
            s=Store(c,self.owner,True)
            p=s.create_project('Historical')['id'];source=s.create_source(p,reference='synthetic')['id'];artifact=s.create_artifact(p,'Historical')['id'];v=s.create_version(p,artifact,content='synthetic',reason='historical',source_ids=[source])['id']
        initialize(db);initialize(db)
        with connect(db) as c:self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],SCHEMA_VERSION);self.assertIsNone(c.execute('PRAGMA foreign_key_check').fetchone())
        with unit_of_work(db,self.owner) as s:self.assertEqual(s.get(p,'artifact_versions',v)['content'],'synthetic');self.assertEqual(s.version_provenance(p,v)['sources'][0]['id'],source)

if __name__=='__main__':unittest.main()
