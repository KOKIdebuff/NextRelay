"""Project-owned, bounded, manually driven public GitHub snapshots.

All network runs outside DB transactions. Snapshot lease + fencing token protects
short per-file commits. A restart waits for lease expiry; retries keep the pin.
"""
import hashlib
import json
import re
import sqlite3
import time
from uuid import uuid4
from .auth import AccessError
from .changes import canonical, digest, exact, ChangeError
from .formats import ImportFailure, MAX_FILE, display_name
from .store import unit_of_work
from .github_http import (GitHubHTTP, SHA, MAX_FILES, MAX_CONTENT, MAX_ENTRIES,
    MAX_METADATA, MAX_REQUESTS, OP_SECONDS, fail, parse_url, path_value, segment)

LEASE=150
SCOPE_SECONDS=1800
MAX_ATTEMPTS=3


def rows(s,p,snapshot,table):
    return [dict(r) for r in s._connection.execute(f'SELECT * FROM {table} WHERE project_id=? AND snapshot_id=? ORDER BY created_at,id',(p,snapshot))]


class GitHubService:
    def __init__(self,importer,config=None):
        self.imp=importer;self.db=importer.database;self.principal=importer.principal;self.http=GitHubHTTP(config)

    def unit(self,write=False):return unit_of_work(self.db,self.principal,write=write)

    def get(self,p,identity):
        with self.unit() as s:
            b=s.get(p,'github_snapshots',identity)
            b['input']=json.loads(b.pop('input_json'));b['unknown_ranges']=json.loads(b.pop('unknown_json'))
            b['entries']=rows(s,p,identity,'github_entries');b['scopes']=rows(s,p,identity,'github_scopes')
            for scope in b['scopes']:scope['paths']=json.loads(scope.pop('paths_json'))
            b['events']=rows(s,p,identity,'github_events')
            b.pop('lease',None)
        for entry in b['entries']:
            if entry['item_id']:
                item=self.imp.item(p,entry['item_id'])
                exact_input=next(x for x in item['inputs'] if x['id']==entry['input_id'])
                attempts=[x for x in item['attempts'] if x['input_id']==entry['input_id']]
                latest=attempts[-1] if attempts else None
                with self.unit() as s:
                    extracted=s._connection.execute('SELECT 1 FROM native_runs WHERE project_id=? AND item_id=? AND input_id=?',(p,entry['item_id'],entry['input_id'])).fetchone() is not None
                entry['processing']=dict(input_id=entry['input_id'],fingerprint=exact_input['fingerprint'],
                    save=latest['save_status'] if latest else 'pending',parse=latest['parse_status'] if latest else 'not-run',
                    semantic='extracted' if extracted else 'not-performed',reason=latest['reason'] if latest else None,
                    source_id=latest['source_id'] if latest else None,availability=exact_input['availability'],batch_id=item['batch_id'])
                # A legal local replacement remains available in T07, but can
                # never relabel processing of this immutable remote input.
                entry['local_replacement_input_id']=item['current_input_id'] if item['current_input_id']!=entry['input_id'] else None
        return b

    def listing(self,p):
        with self.unit() as s:
            s.project(p)
            ids=[r['id'] for r in s._connection.execute('SELECT id FROM github_snapshots WHERE project_id=? ORDER BY created_at,id',(p,))]
        return [self.get(p,i) for i in ids]

    def action(self,p,key,action,body,identity=None):
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',key):fail('invalid_request_key')
        allowed={'prepare','read','expand','confirm','retry','update','recover'}
        if action not in allowed or (action=='prepare')!=(identity is None):fail('invalid_action')
        if action=='prepare':exact(body,('url','storage_choice'),('ref',))
        elif action=='expand':exact(body,('paths',))
        elif action=='confirm':exact(body,('scope_id','fingerprint'))
        else:exact(body,())
        fp=digest([action,identity,body])
        with self.unit(True) as s:
            s.project(p)
            if identity:s.get(p,'github_snapshots',identity)
            old=s._connection.execute('SELECT * FROM github_requests WHERE created_by=? AND request_key=?',(self.principal.subject,key)).fetchone()
            if old:
                if old['project_id']!=p or old['fingerprint']!=fp:fail('idempotency_conflict')
                target=old['snapshot_id'];request_id=old['id'];fresh=False
            else:
                # A key cannot alias any existing local/model receipt.
                for table,subject in (('http_receipts','subject'),('model_requests','created_by')):
                    if s._connection.execute(f'SELECT 1 FROM {table} WHERE {subject}=? AND request_key=?',(self.principal.subject,key)).fetchone():fail('idempotency_conflict')
                for table in ('model_batches','ingest_batches','ingest_requests'):
                    if s._connection.execute(f'SELECT 1 FROM {table} r JOIN projects p ON p.id=r.project_id WHERE p.owner_subject=? AND r.request_key=?',(self.principal.subject,key)).fetchone():fail('idempotency_conflict')
                if action in ('prepare','update'):
                    if action=='update':
                        parent=s.get(p,'github_snapshots',identity)
                        if parent['state'] in ('new','preparing','reading'):fail('busy')
                        selection=json.loads(parent['input_json'])
                    else:
                        if body['storage_choice']!='configured-local':fail('explicit_storage_required')
                        target_url=parse_url(body['url'])
                        if 'ref' in body:path_value(body['ref'])
                        selection=body
                    target=s._insert(p,'github_snapshots',input_json=canonical(selection),parent_id=identity if action=='update' else None)['id']
                else:target=identity
                request_id=s._insert(p,'github_requests',snapshot_id=target,request_key=key,action=action,fingerprint=fp)['id']
                fresh=True
        if fresh:
            try:
                if action in ('prepare','update'):self.prepare(p,target)
                elif action in ('read','retry'):self.read(p,target,retry=action=='retry')
                elif action=='expand':self.expand(p,target,body['paths'])
                elif action=='confirm':self.confirm(p,target,body)
                elif action=='recover':self.recover(p,target)
            except (ImportFailure,AccessError,ChangeError) as e:
                with self.unit(True) as s:
                    s._insert(p,'github_request_results',request_id=request_id,state='failed',code=e.code,
                        http_status=e.status if isinstance(e,AccessError) else 409,
                        error_kind='access' if isinstance(e,AccessError) else 'import' if isinstance(e,ImportFailure) else 'change')
                raise
            with self.unit(True) as s:
                s._insert(p,'github_request_results',request_id=request_id,state='done',code='',http_status=200,error_kind='')
        with self.unit() as s:
            outcome=s._connection.execute('SELECT * FROM github_request_results WHERE project_id=? AND request_id=?',(p,request_id)).fetchone()
        if outcome and outcome['state']=='failed':
            if outcome['error_kind']=='access':raise AccessError(outcome['http_status'],outcome['code'])
            if outcome['error_kind']=='change':raise ChangeError(outcome['code'])
            raise ImportFailure(outcome['code'],'remote')
        result=self.get(p,target)
        result['request_state']=outcome['state'] if outcome else 'registered'
        return result

    def event(self,s,p,b,state,code='',entry=None):
        s._insert(p,'github_events',snapshot_id=b,entry_id=entry,state=state,code=code)

    def claim(self,p,identity,state,*,retry=False):
        token=str(uuid4())
        with self.unit(True) as s:
            b=s.get(p,'github_snapshots',identity)
            if b['lease'] and b['lease_until']>time.time():fail('busy')
            if state=='preparing' and b['state']!='new':fail('prepare_requires_new_update')
            if state=='reading' and (not b['git_commit'] or b['state'] in ('reference-only','new','preparing') or (b['state']=='failed' and not retry)):fail('snapshot_unreadable')
            s._connection.execute('UPDATE github_snapshots SET state=?,lease=?,lease_until=? WHERE id=?',(state,token,time.time()+LEASE,identity))
            self.event(s,p,identity,state)
        return token

    def fenced(self,s,p,identity,token):
        b=s.get(p,'github_snapshots',identity)
        if b['lease']!=token or b['lease_until']<time.time():fail('lease_lost')
        return b

    def request(self,p,identity,token,path,limit,*,raw=False,metadata=False,end=None,sha_only=False):
        with self.unit(True) as s:
            b=self.fenced(s,p,identity,token)
            if b['request_count']>=MAX_REQUESTS:fail('request_budget')
            col='metadata' if metadata else 'content' if raw else None
            if col:
                cap=MAX_METADATA if metadata else MAX_CONTENT
                if limit<0 or limit>cap-b[col+'_bytes']-b[col+'_reserved']:fail(col+'_budget')
                s._connection.execute(f'UPDATE github_snapshots SET {col}_reserved={col}_reserved+? WHERE id=?',(limit,identity))
            s._connection.execute('UPDATE github_snapshots SET request_count=request_count+1 WHERE id=?',(identity,))
        used=0
        def charge(n):
            nonlocal used
            used+=n
        try:return self.http.get(path,limit,raw=raw,deadline=end,charge=charge,sha_only=sha_only)
        finally:
            if col:
                with self.unit(True) as s:
                    self.fenced(s,p,identity,token)
                    s._connection.execute(f'UPDATE github_snapshots SET {col}_bytes={col}_bytes+?,{col}_reserved={col}_reserved-? WHERE id=?',(used,limit,identity))

    def prepare(self,p,identity):
        token=self.claim(p,identity,'preparing');end=time.monotonic()+OP_SECONDS
        try:
            with self.unit() as s:b=s.get(p,'github_snapshots',identity)
            selection=json.loads(b['input_json']);u=parse_url(selection['url'])
            if u['kind']=='reference':
                with self.unit(True) as s:
                    self.fenced(s,p,identity,token)
                    source=s.create_source(p,reference=u['url'],read_result='not-read-unsupported-upload-content')['id']
                    s._connection.execute("UPDATE github_snapshots SET source_id=?,state='reference-only',code='unsupported_url_upload_content',lease=NULL,lease_until=NULL WHERE id=?",(source,identity))
                return
            base='/repos/'+segment(u['owner'])+'/'+segment(u['repo'])
            def req(path,limit=128*1024):return self.request(p,identity,token,base+path,limit,end=end)
            repo=req('')
            if not isinstance(repo,dict) or repo.get('private') is not False or repo.get('visibility')!='public' or not isinstance(repo.get('full_name'),str) or repo.get('full_name').lower()!=(u['owner']+'/'+u['repo']).lower():fail('public_repository_unconfirmed')
            # Explicit ref disambiguates slash-containing refs. Without it every
            # possible URL split is resolved; multiple valid splits are refused.
            if u['kind']=='repository':
                ref=selection.get('ref',repo.get('default_branch'));path_value(ref);candidates=[(ref,'')]
            elif 'ref' in selection:
                ref=selection['ref'];tail=u['tail']
                if tail==ref and u['kind']=='tree':candidates=[(ref,'')]
                elif tail.startswith(ref+'/'):candidates=[(ref,tail[len(ref)+1:])]
                else:fail('ref_url_mismatch')
            else:
                parts=u['tail'].split('/')
                if len(parts)>16:fail('explicit_ref_required')
                candidates=[('/'.join(parts[:i]),'/'.join(parts[i:])) for i in range(1,len(parts)+1) if u['kind']=='tree' or i<len(parts)]
            resolved=[]
            for ref,path in candidates:
                path_value(ref);path_value(path,empty=True)
                try:commit=self.request(p,identity,token,base+'/commits/'+segment(ref),64,sha_only=True,end=end)
                except ImportFailure as e:
                    if e.code in ('github_http_404','github_http_422'):continue
                    raise
                if not isinstance(commit,str) or not SHA.fullmatch(commit):fail('commit_unpinned')
                resolved.append((commit,path))
            if len(resolved)!=1:fail('ambiguous_ref_path' if resolved else 'commit_unpinned')
            commit,path=resolved[0]
            # General commit JSON may include files[].patch. Only the SHA media
            # representation may resolve refs; Git database commit metadata has
            # no file bodies and is then fetched by that immutable SHA.
            detail=req('/git/commits/'+commit)
            if not isinstance(detail,dict) or detail.get('sha')!=commit or not isinstance(detail.get('tree'),dict):fail('invalid_response')
            tree=detail['tree'].get('sha')
            if not isinstance(tree,str) or not SHA.fullmatch(tree):fail('commit_unpinned')
            with self.unit(True) as s:
                self.fenced(s,p,identity,token)
                source=s.create_source(p,namespace='github',reference=selection['url'],git_commit=commit,source_path=path,
                    read_result='metadata-only-see-github-manifest',metadata={'snapshot_id':identity,'parent_id':b['parent_id'],'input':selection})['id']
                s._connection.execute('UPDATE github_snapshots SET repo=?,git_commit=?,root_tree=?,selection_path=?,link_kind=?,source_id=? WHERE id=?',
                    (u['owner']+'/'+u['repo'],commit,tree,path,u['kind'],source,identity))
            unknown=self.enumerate_trees(p,identity,token,base,[('',tree)],end)
            with self.unit(True) as s:
                self.fenced(s,p,identity,token)
                entries=rows(s,p,identity,'github_entries')
                self.retain_pending_ranges(entries,unknown)
                match=next((e for e in entries if e['path']==path),None)
                if u['kind']=='blob' and (not match or match['kind']!='blob'):unknown.append({'path':path,'reason':'selected_file_not_enumerated'})
                if u['kind']=='tree' and path and (not match or match['kind']!='tree'):unknown.append({'path':path,'reason':'selected_directory_not_enumerated'})
                paths=self.expected_paths(entries,u['kind'],path)
                self.scope(s,p,identity,commit,paths,'initial',approved=True)
                s._connection.execute("UPDATE github_snapshots SET state='ready',complete=?,unknown_json=?,code=?,lease=NULL,lease_until=NULL WHERE id=?",
                    (int(not unknown),canonical(unknown),'metadata_incomplete' if unknown else '',identity))
                self.event(s,p,identity,'ready','metadata_incomplete' if unknown else '')
        except (ImportFailure,ValueError,TypeError,KeyError,RecursionError) as e:
            code=e.code if isinstance(e,ImportFailure) else 'github_invalid_response'
            with self.unit(True) as s:
                self.fenced(s,p,identity,token)
                s._connection.execute("UPDATE github_snapshots SET state='failed',code=?,complete=0,unknown_json=?,lease=NULL,lease_until=NULL WHERE id=?",(code,canonical([{'path':'','reason':code}]),identity))
                self.event(s,p,identity,'failed',code)

    def expected_paths(self,entries,kind,path):
        return [e['path'] for e in entries if e['mode'] in ('100644','100755') and (
            ('/' not in e['path'] and re.fullmatch(r'README(?:\.[A-Za-z0-9_-]+)?',e['path'],re.I)) or
            (kind=='blob' and e['path']==path) or (kind=='tree' and bool(path) and e['path'].startswith(path+'/')))]

    def enumerate_trees(self,p,identity,token,base,pending,end,*,resume=False):
        pending=list(pending);queued={path for path,sha in pending};unknown=[]
        while pending:
            prefix,tree_sha=pending.pop(0)
            try:
                with self.unit() as s:
                    b=self.fenced(s,p,identity,token)
                    known={e['path']:e for e in rows(s,p,identity,'github_entries')}
                count=len(known)
                if count>=MAX_ENTRIES or b['metadata_bytes']+b['metadata_reserved']>=MAX_METADATA:fail('metadata_budget')
                result=self.request(p,identity,token,base+'/git/trees/'+tree_sha,MAX_METADATA-b['metadata_bytes']-b['metadata_reserved'],metadata=True,end=end)
                if not isinstance(result,dict) or result.get('sha')!=tree_sha or type(result.get('truncated')) is not bool or not isinstance(result.get('tree'),list):fail('invalid_tree')
                node_complete=not result['truncated']
                if result['truncated']:unknown.append({'path':prefix,'reason':'github_tree_truncated'})
                seen=set()
                for item in result['tree']:
                    if not isinstance(item,dict):fail('invalid_tree')
                    name=path_value(item.get('path'))
                    if '/' in name:fail('invalid_tree_path')
                    if name in seen:fail('duplicate_tree_path')
                    seen.add(name)
                    full=prefix+'/'+name if prefix else name;path_value(full)
                    mode=item.get('mode');kind=item.get('type');sha=item.get('sha');size=item.get('size')
                    if (mode,kind) not in (('100644','blob'),('100755','blob'),('040000','tree'),('120000','blob'),('160000','commit')) or not isinstance(sha,str) or not SHA.fullmatch(sha) or (size is not None and (type(size)is not int or not 0<=size<2**63)):fail('invalid_tree')
                    old=known.get(full)
                    if old:
                        if any(old[k]!=value for k,value in (('mode',mode),('kind',kind),('object_sha',sha))) or (size is not None and old['byte_size'] is not None and size!=old['byte_size']):fail('tree_identity_mismatch')
                    else:
                        if count>=MAX_ENTRIES:
                            unknown.append({'path':prefix,'reason':'github_entry_budget'});node_complete=False;break
                        reason='symlink_not_followed' if mode=='120000' else 'submodule_not_followed' if mode=='160000' else ''
                        with self.unit(True) as s:
                            self.fenced(s,p,identity,token)
                            row=s._insert(p,'github_entries',snapshot_id=identity,path=full,kind=kind,mode=mode,object_sha=sha,byte_size=size,
                                metadata_status='read',children_status='pending' if kind=='tree' else 'not-applicable',read_status='skipped' if reason else 'metadata-only' if kind=='tree' else 'not-selected',code=reason)
                        known[full]=row;count+=1
                        if kind=='tree':self.imp.fault('github_after_directory_entry')
                    if kind=='tree' and full not in queued and (not resume or old is None or old['children_status']!='complete'):
                        pending.append((full,sha));queued.add(full)
                if node_complete:
                    expected={name.rsplit('/',1)[-1] for name in known if name.rpartition('/')[0]==prefix}
                    if expected!=seen:fail('tree_identity_mismatch')
                if prefix:
                    with self.unit(True) as s:
                        self.fenced(s,p,identity,token)
                        s._connection.execute('UPDATE github_entries SET children_status=? WHERE snapshot_id=? AND path=?',('complete' if node_complete else 'incomplete',identity,prefix))
            except (ImportFailure,sqlite3.IntegrityError) as e:
                code=e.code if isinstance(e,ImportFailure) else 'github_duplicate_tree_path'
                unknown.append({'path':prefix,'reason':code})
                if prefix:
                    with self.unit(True) as s:
                        self.fenced(s,p,identity,token)
                        s._connection.execute("UPDATE github_entries SET children_status='incomplete' WHERE snapshot_id=? AND path=?",(identity,prefix))
                if code in ('github_request_budget','github_metadata_budget','github_stream_limit','github_transport_or_timeout','github_timeout','github_rate_limited_manual_retry'):
                    unknown.extend({'path':x[0],'reason':'not_enumerated_after_limit'} for x in pending);pending=[]
        return unknown

    def retain_pending_ranges(self,entries,unknown):
        # Listing a directory's immediate children does not prove that every
        # descendant tree was visited. Keep each durable unfinished tree visible.
        gaps={x['path'] for x in unknown}
        for entry in entries:
            if entry['kind']=='tree' and entry['children_status']!='complete' and entry['path'] not in gaps:
                unknown.append({'path':entry['path'],'reason':'subtree_not_enumerated'})
                gaps.add(entry['path'])

    def retry_metadata(self,p,identity,token,end):
        with self.unit() as s:
            b=self.fenced(s,p,identity,token)
            entries=rows(s,p,identity,'github_entries');known={e['path']:e for e in entries}
            unfinished={e['path']:e['object_sha'] for e in entries if e['kind']=='tree' and e['children_status']!='complete'}
            if b['complete'] and not unfinished:return
        # Pending descendants are independent recovery roots even when an
        # ancestor's immediate child listing is already complete.
        pending=dict(unfinished)
        for gap in json.loads(b['unknown_json']) or [{'path':''}]:
            prefix=gap['path']
            while prefix and (prefix not in known or known[prefix]['kind']!='tree'):
                prefix=prefix.rpartition('/')[0]
            pending[prefix]=known[prefix]['object_sha'] if prefix else b['root_tree']
        base='/repos/'+'/'.join(segment(x) for x in b['repo'].split('/'))
        unknown=self.enumerate_trees(p,identity,token,base,sorted(pending.items()),end,resume=True)
        with self.unit(True) as s:
            self.fenced(s,p,identity,token);entries=rows(s,p,identity,'github_entries')
            self.retain_pending_ranges(entries,unknown)
            path=b['selection_path'];kind=b['link_kind'];match=next((e for e in entries if e['path']==path),None)
            if kind=='blob' and (not match or match['kind']!='blob'):unknown.append({'path':path,'reason':'selected_file_not_enumerated'})
            if kind=='tree' and path and (not match or match['kind']!='tree'):unknown.append({'path':path,'reason':'selected_directory_not_enumerated'})
            previewed=set(x for scope in rows(s,p,identity,'github_scopes') for x in json.loads(scope['paths_json']))
            new=sorted(set(self.expected_paths(entries,kind,path))-previewed)
            # Recovered metadata is not authorization for newly found bodies.
            for start in range(0,len(new),MAX_FILES):self.scope(s,p,identity,b['git_commit'],new[start:start+MAX_FILES],'expansion')
            s._connection.execute('UPDATE github_snapshots SET complete=?,unknown_json=?,code=? WHERE id=?',
                (int(not unknown),canonical(unknown),'metadata_incomplete' if unknown else '',identity))
            self.event(s,p,identity,'metadata-retried','new_paths_require_confirmation' if new else '')

    def scope(self,s,p,b,commit,paths,kind,approved=False):
        paths=sorted(set(paths));now=time.time()
        fp=digest([p,b,commit,paths,kind,now+SCOPE_SECONDS])
        scope=s._insert(p,'github_scopes',snapshot_id=b,paths_json=canonical(paths),fingerprint=fp,
            expires=now+SCOPE_SECONDS,approved_at=now if approved else None,kind=kind)
        return scope

    def approved_paths(self,s,p,b):
        return set(x for scope in rows(s,p,b,'github_scopes') if scope['approved_at'] is not None for x in json.loads(scope['paths_json']))

    def expand(self,p,identity,paths):
        if not isinstance(paths,list) or not 1<=len(paths)<=MAX_FILES or any(not isinstance(x,str) for x in paths):fail('invalid_expansion')
        for x in paths:path_value(x)
        with self.unit(True) as s:
            b=s.get(p,'github_snapshots',identity)
            if b['state'] not in ('ready','partial','read'):fail('snapshot_unreadable')
            known={e['path']:e for e in rows(s,p,identity,'github_entries')}
            if any(x not in known or known[x]['mode'] not in ('100644','100755') for x in paths):fail('expansion_unenumerated_or_unsafe')
            paths=set(paths)-self.approved_paths(s,p,identity)
            if not paths:fail('no_new_paths')
            self.scope(s,p,identity,b['git_commit'],paths,'expansion')
            self.event(s,p,identity,'scope-preview')

    def confirm(self,p,identity,body):
        with self.unit(True) as s:
            b=s.get(p,'github_snapshots',identity);scope=s.get(p,'github_scopes',body['scope_id'])
            if scope['snapshot_id']!=identity or scope['kind']!='expansion' or scope['fingerprint']!=body['fingerprint'] or scope['expires']<time.time():fail('scope_confirmation_invalid_or_expired')
            if b['state'] not in ('ready','partial','read'):fail('busy')
            if scope['approved_at'] is None:
                s._connection.execute('UPDATE github_scopes SET approved_at=? WHERE id=?',(time.time(),scope['id']))
                self.event(s,p,identity,'scope-approved')

    def recover(self,p,identity):
        with self.unit(True) as s:
            b=s.get(p,'github_snapshots',identity)
            if b['lease'] and b['lease_until']>time.time():fail('busy')
            if b['state'] in ('new','preparing'):
                s._connection.execute("UPDATE github_snapshots SET state='failed',code='interrupted_prepare_start_new_update',complete=0,unknown_json=?,lease=NULL,lease_until=NULL WHERE id=?",(canonical([{'path':'','reason':'interrupted_prepare_unknown_remaining'}]),identity))
            elif b['state']=='reading':
                s._connection.execute("UPDATE github_entries SET read_status='failed',code='interrupted_read_retry_same_commit' WHERE snapshot_id=? AND read_status='reading'",(identity,))
                s._connection.execute("UPDATE github_snapshots SET state='partial',code='interrupted_read_retry_same_commit',lease=NULL,lease_until=NULL WHERE id=?",(identity,))
            for entry in rows(s,p,identity,'github_entries'):
                if entry['item_id']:
                    inp=s.get(p,'ingest_inputs',entry['input_id'])
                    if not self.imp._cleanup(dict(inp),finals=self.imp._link(s,p,inp) is None):
                        s._connection.execute("UPDATE github_entries SET code='github_cleanup_pending' WHERE id=?",(entry['id'],))
            self.event(s,p,identity,'recovered')

    def read(self,p,identity,retry=False):
        token=self.claim(p,identity,'reading',retry=retry);end=time.monotonic()+OP_SECONDS
        try:
            if retry:self.retry_metadata(p,identity,token,end)
            with self.unit() as s:
                b=self.fenced(s,p,identity,token);approved=self.approved_paths(s,p,identity)
                entries=rows(s,p,identity,'github_entries')
            for entry in entries:
                if entry['path'] not in approved or entry['read_status'] in ('read','skipped'):continue
                if entry['read_status'] in ('failed','reading') and not retry:continue
                if entry['attempts']>=MAX_ATTEMPTS:continue
                try:
                    with self.unit(True) as s:
                        b=self.fenced(s,p,identity,token)
                        if entry['path'] not in self.approved_paths(s,p,identity):fail('scope_changed')
                        if b['content_reads']>=MAX_FILES or b['content_bytes']+b['content_reserved']>=MAX_CONTENT:fail('content_budget')
                        if time.monotonic()>=end:fail('operation_deadline')
                        if entry['byte_size'] is not None and entry['byte_size']>min(MAX_FILE,MAX_CONTENT-b['content_bytes']-b['content_reserved']):fail('file_or_content_budget')
                        try:display_name(entry['path'].rsplit('/',1)[-1])
                        except ImportFailure:fail('unsupported_display_name_upload_instead')
                        s._connection.execute("UPDATE github_entries SET read_status='reading',attempts=attempts+1,code='' WHERE id=?",(entry['id'],))
                        s._connection.execute('UPDATE github_snapshots SET content_reads=content_reads+1 WHERE id=?',(identity,))
                    limit=min(MAX_FILE,MAX_CONTENT-b['content_bytes']-b['content_reserved'])
                    base='/repos/'+'/'.join(segment(x) for x in b['repo'].split('/'))
                    data=self.request(p,identity,token,base+'/git/blobs/'+entry['object_sha'],limit,raw=True,end=end)
                    sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
                    if sha!=entry['object_sha'] or (entry['byte_size'] is not None and entry['byte_size']!=len(data)):fail('blob_identity_mismatch')
                    code=''
                    if data.startswith(b'version https://git-lfs.github.com/spec/v1'):code='lfs_pointer_not_followed'
                    elif b'\0' in data[:8192]:code='binary_not_parsed'
                    if code:
                        with self.unit(True) as s:
                            self.fenced(s,p,identity,token)
                            s._connection.execute("UPDATE github_entries SET read_status='skipped',code=?,sha256=? WHERE id=?",(code,hashlib.sha256(data).hexdigest(),entry['id']))
                        continue
                    # Register input identities durably BEFORE filesystem mutation.
                    # A killed process leaves only DB-owned recoverable file slots.
                    with self.unit(True) as s:
                        b=self.fenced(s,p,identity,token)
                        item=self.imp.save_github(s,p,b,entry,data,register_only=True)
                        inp=s._connection.execute('SELECT id FROM ingest_inputs WHERE project_id=? AND item_id=? ORDER BY ordinal LIMIT 1',(p,item)).fetchone()[0]
                        s._connection.execute('UPDATE github_entries SET item_id=?,input_id=?,sha256=? WHERE id=?',(item,inp,hashlib.sha256(data).hexdigest(),entry['id']))
                    # Per-file source/result/link commits atomically, outside HTTP.
                    with self.unit(True) as s:
                        b=self.fenced(s,p,identity,token)
                        item=self.imp.save_github(s,p,b,entry,data)
                        latest=s._connection.execute('SELECT * FROM ingest_attempts WHERE project_id=? AND item_id=? AND input_id=? ORDER BY ordinal DESC LIMIT 1',(p,item,inp)).fetchone()
                        saved=latest['save_status']=='saved'
                        s._connection.execute("UPDATE github_entries SET read_status=?,sha256=?,item_id=?,code=? WHERE id=?",('read' if saved else 'failed',hashlib.sha256(data).hexdigest(),item,'' if saved else latest['reason'],entry['id']))
                        self.event(s,p,identity,'body-read-saved',entry=entry['id'])
                except (ImportFailure,sqlite3.Error,OSError) as e:
                    code=e.code if isinstance(e,ImportFailure) else 'github_save_transaction_failed_retry'
                    with self.unit(True) as s:
                        self.fenced(s,p,identity,token)
                        s._connection.execute("UPDATE github_entries SET read_status='failed',code=? WHERE id=?",(code,entry['id']))
                        self.event(s,p,identity,'failed',code,entry['id'])
            with self.unit(True) as s:
                b=self.fenced(s,p,identity,token);approved=self.approved_paths(s,p,identity)
                incomplete=not b['complete'] or any(e['path'] in approved and e['read_status'] not in ('read','skipped') for e in rows(s,p,identity,'github_entries'))
                s._connection.execute('UPDATE github_snapshots SET state=?,lease=NULL,lease_until=NULL WHERE id=?',('partial' if incomplete else 'read',identity))
                self.event(s,p,identity,'partial' if incomplete else 'read')
        finally:
            # Unexpected process death leaves a lease for explicit recovery;
            # normal exceptions release it but preserve unfinished per-file state.
            with self.unit(True) as s:
                b=s.get(p,'github_snapshots',identity)
                if b['lease']==token:
                    s._connection.execute("UPDATE github_snapshots SET state='partial',code='interrupted_read_retry_same_commit',lease=NULL,lease_until=NULL WHERE id=?",(identity,))
