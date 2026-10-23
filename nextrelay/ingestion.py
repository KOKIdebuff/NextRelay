"""T07 trusted, project-owned, item-isolated persistent import service.

The caller supplies a server-authenticated Principal and explicit SelectedFile
objects. Never expose this API by deserializing arbitrary client paths/subjects.
Every filesystem mutation runs inside a separate BEGIN IMMEDIATE unit for one
item. SQLite serializes competitors; filesystem recovery uses registered input
identities plus exclusive ownership markers, not a pretend shared transaction.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time

from .auth import AccessError
from .formats import (ImportFailure, MAX_FILE, MAX_FILES, MAX_BATCH, MAX_OUTPUT,
                      PROCESSOR, digest, display_name, encoded, parse)
from . import localfiles
from .store import unit_of_work


@dataclass(frozen=True)
class SelectedFile:
    path: Path
    name: str
    media_type: str | None = None
    storage_choice: str = 'user-local'
    parse: bool = True


def _key(key):
    if not isinstance(key,str) or not key.strip() or len(key)>128:
        raise ImportFailure('invalid_request_key','request')
    return key


def _same_replacement_request(previous,current):
    a,b=previous['replacement'],current['replacement']
    if a is None or b is None:
        return a is b
    # Resource decisions belong to attempts, not request identity. An unread
    # over-budget selection cannot supply a content hash; replay returns only
    # the immutable original result and never processes its changed bytes.
    return (a['selection_json']==b['selection_json'] and
            (a['byte_size']==b['byte_size'] or b['preflight_error']=='local_file_unavailable') and
            (a['fingerprint'] is None or b['fingerprint'] is None or a['fingerprint']==b['fingerprint']))


class ImportService:
    def __init__(self, database, principal, local_root, *, fault=None):
        self.database=Path(database)
        self.principal=principal
        # This path is trusted application configuration, never a file field.
        self.root=localfiles.absolute(local_root)
        self.fault=fault or (lambda stage:None)

    def create_project(self, title):
        with unit_of_work(self.database,self.principal,write=True) as s:
            return s.create_project(title)

    def _authorize(self, project):
        with unit_of_work(self.database,self.principal) as s:
            return s.project(project)

    def _selection(self, selected, *, budget):
        if not isinstance(selected,SelectedFile) or type(selected.parse) is not bool:
            raise ImportFailure('explicit_selection_required','selection')
        name=display_name(selected.name)
        if selected.media_type is not None and (not isinstance(selected.media_type,str) or len(selected.media_type)>128):
            raise ImportFailure('invalid_media_type','selection')
        if selected.storage_choice not in ('user-local','cloud-requested'):
            raise ImportFailure('invalid_storage_choice','selection')
        p=localfiles.absolute(selected.path)
        selection={'path':str(p),'name':name,'media_type':selected.media_type,
                   'storage_choice':selected.storage_choice,'parse':selected.parse,'local_root':str(self.root)}
        sha=size=error=None
        try:
            # stat and budget enforcement precede read/allocation, including the
            # batch total. Do not charge failed oversized items to later items.
            with localfiles.opened(p) as stream:
                size=os.fstat(stream.fileno()).st_size
                if size>MAX_FILE:
                    raise ImportFailure('file_size_limit','read')
                if size>budget:
                    raise ImportFailure('batch_size_limit','read')
                data=stream.read(min(MAX_FILE,budget)+1)
                if len(data)>MAX_FILE or len(data)>budget:
                    raise ImportFailure('input_grew_limit','read')
                if len(data)!=size:
                    raise ImportFailure('input_changed','read')
                sha=digest(data)
        except ImportFailure as e:
            error=e.code
        except OSError:
            error='local_file_unavailable'
        return dict(selection_json=encoded(selection).decode(),fingerprint=sha,byte_size=size,preflight_error=error)

    def create_batch(self, project, request_key, files):
        self._authorize(project)
        _key(request_key)
        if not isinstance(files,(tuple,list)) or not 1<=len(files)<=MAX_FILES:
            raise ImportFailure('batch_file_count_limit','request')
        budget=MAX_BATCH;prepared=[]
        for f in files:
            item=self._selection(f,budget=budget)
            if item['preflight_error'] is None:
                budget-=item['byte_size']
            prepared.append(item)
        manifest=encoded({'processor':PROCESSOR,'inputs':prepared}).decode()
        with unit_of_work(self.database,self.principal,write=True) as s:
            s.project(project)
            old=s._connection.execute('SELECT * FROM ingest_batches WHERE project_id=? AND request_key=?',(project,request_key)).fetchone()
            if old is not None:
                if old['manifest_json']!=manifest:
                    previous=json.loads(old['manifest_json'])['inputs']
                    # A persistent request identifies its original selection.
                    # Losing/moving that selected path after a response loss
                    # does not invalidate an already registered request. If the
                    # path is readable and changed, reject rather than relabel.
                    same=(len(previous)==len(prepared) and all(
                        a['selection_json']==b['selection_json'] and
                        (a==b or (a['fingerprint'] is not None and b['preflight_error']=='local_file_unavailable'))
                        for a,b in zip(previous,prepared)))
                    if not same:
                        raise ImportFailure('idempotency_conflict','request')
                return dict(old)
            batch=s._insert(project,'ingest_batches',request_key=request_key,manifest_json=manifest,
                            fingerprint=digest(manifest.encode()),processing_version=PROCESSOR)
            for index,values in enumerate(prepared):
                item=s._insert(project,'ingest_items',batch_id=batch['id'],position=index)
                s._insert(project,'ingest_inputs',item_id=item['id'],ordinal=1,**values)
            return batch

    def import_files(self, project, request_key, files):
        batch=self.create_batch(project,request_key,files)
        return self.process_batch(project,batch['id'])

    def _item(self, s, project, item):
        row=s.get(project,'ingest_items',item)
        return row

    def _latest(self,s,table,project,item):
        # Table identifiers are internal constants at every call site.
        if table not in ('ingest_inputs','ingest_attempts'):
            raise ValueError('Unknown processing history')
        return s._connection.execute(f'SELECT * FROM {table} WHERE project_id=? AND item_id=? ORDER BY ordinal DESC LIMIT 1',
                                     (project,item)).fetchone()

    def _paths(self, input_row):
        selected=json.loads(input_row['selection_json'])
        if selected['local_root']!=str(self.root):
            raise ImportFailure('storage_root_mismatch','save')
        # UUIDs come from immutable DB identities, not display names or input.
        identity=input_row['id']
        from uuid import UUID
        if str(UUID(identity))!=identity:
            raise ImportFailure('invalid_storage_identity','save')
        return {kind:self.root/(identity+suffix) for kind,suffix in
                (('original','.original'),('parsed','.parsed.json'),('marker','.owner'))}

    def _claim(self,input_row):
        paths=self._paths(input_row)
        # An exclusively created *empty* marker is the ownership token. Its
        # unpredictable immutable input UUID is DB-registered. No multi-byte
        # marker write can tear and permanently strand an interrupted input.
        marker=b''
        with localfiles.parents(paths['marker']):
            if paths['marker'].exists():
                if localfiles.inspect(paths['marker'])!=marker:
                    raise ImportFailure('storage_ownership_conflict','save')
                return paths
            # Refuse pre-existing unknown objects; never overwrite/adopt them.
            if any(p.exists() or p.with_suffix(p.suffix+'.stage').exists() for p in paths.values()):
                raise ImportFailure('storage_ownership_conflict','save')
            with localfiles.opened(paths['marker'],create=True) as f:
                f.flush();os.fsync(f.fileno())
        return paths

    def _cleanup(self,input_row,*,finals=False):
        try:
            paths=self._paths(input_row)
            marker=paths['marker']
            if not marker.exists():
                # No marker means no deletion authority. Be honest if a known
                # generated slot is occupied: retain it and report unresolved.
                pending=any(p.with_suffix(p.suffix+'.stage').exists() for k,p in paths.items() if k!='marker')
                orphan=finals and any(paths[k].exists() for k in ('original','parsed'))
                return not (pending or orphan)
            expected=b''
            if localfiles.inspect(marker)!=expected:
                return False
            targets=[p.with_suffix(p.suffix+'.stage') for k,p in paths.items() if k!='marker']
            if finals:
                targets += [paths['original'],paths['parsed']]
            return all([localfiles.remove_owned(p) for p in targets])
        except (OSError,ImportFailure):
            return False

    def _expired_stage(self,input_row):
        paths=self._paths(input_row)
        if not paths['marker'].exists() or localfiles.inspect(paths['marker'])!=b'':
            return False
        for kind,p in paths.items():
            if kind=='marker':
                continue
            stage=p.with_suffix(p.suffix+'.stage')
            try:
                with localfiles.parents(stage):
                    info=stage.lstat()
                    if time.time()-info.st_mtime>=24*3600:
                        return True
            except FileNotFoundError:
                pass
        return False

    def _link(self,s,project,input_row):
        return s._connection.execute('''SELECT l.* FROM original_links l WHERE l.project_id=? AND l.input_id=?
            AND NOT EXISTS(SELECT 1 FROM original_links n WHERE n.project_id=l.project_id AND n.supersedes_id=l.id)''',
            (project,input_row['id'])).fetchone()

    def _attempt(self,s,project,item,input_row):
        selected=json.loads(input_row['selection_json'])
        old=self._latest(s,'ingest_attempts',project,item)
        ordinal=1 if old is None else old['ordinal']+1
        save_status='failed';parse_status='not-run';reason=stage=source=result_sha=None
        try:
            if input_row['preflight_error']:
                raise ImportFailure(input_row['preflight_error'],'preflight')
            if selected['storage_choice']=='cloud-requested':
                raise ImportFailure('real_cloud_storage_not_connected','save')
            existing=self._link(s,project,input_row)
            data=localfiles.inspect(existing['location'] if existing else selected['path'])
            if digest(data)!=input_row['fingerprint'] or len(data)!=input_row['byte_size']:
                raise ImportFailure('input_changed_select_new_version','read')
            paths=self._claim(input_row)
            self.fault('before_stage')
            if existing is None:
                if not self._cleanup(input_row,finals=True):
                    raise ImportFailure('cleanup_pending','cleanup')
                localfiles.persist(paths['original'],data)
                self.fault('after_original')
                if localfiles.inspect(paths['original'])!=data:
                    raise ImportFailure('saved_content_mismatch','save')
                self.fault('before_link')
                source=s.create_source(project,reference='local-import:'+input_row['id'],
                    fingerprint=input_row['fingerprint'],storage_choice='user-local',
                    availability='unknown',read_result='saved-see-import-availability',
                    metadata={'import_input_id':input_row['id'],'byte_size':len(data),'display_name':selected['name']})['id']
                s._insert(project,'original_links',input_id=input_row['id'],location=str(paths['original']),
                          result_location=str(paths['parsed']) if selected['parse'] else None,supersedes_id=None)
            else:
                source=s._connection.execute('SELECT source_id FROM ingest_attempts WHERE project_id=? AND input_id=? AND source_id IS NOT NULL ORDER BY ordinal LIMIT 1',
                                            (project,input_row['id'])).fetchone()[0]
                if localfiles.inspect(existing['location'])!=data:
                    raise ImportFailure('original_unavailable_reassociate','save')
            save_status='saved'
            if selected['parse']:
                try:
                    result,payload=parse(data,selected['name'],selected['media_type'])
                    result_sha=digest(payload)
                    # Retry parsing keeps the same Source/original. A failed
                    # partial parsed output is cleaned only under its marker.
                    if paths['parsed'].exists():
                        if localfiles.inspect(paths['parsed'],limit=MAX_OUTPUT)!=payload:
                            raise ImportFailure('parsed_output_conflict','save')
                    else:
                        localfiles.persist(paths['parsed'],payload)
                    parse_status='parsed'
                except ImportFailure as e:
                    parse_status='unsupported' if e.code=='unsupported_format' else 'failed'
                    reason,stage=e.code,e.stage
            else:
                parse_status='not-requested'
        except ImportFailure as e:
            reason,stage=e.code,e.stage
            save_status='rejected' if stage=='preflight' else 'failed'
        except OSError:
            reason,stage='local_storage_unavailable','save'
        # Fixed codes only; no original text or source path in errors/logs.
        self.fault('before_result')
        attempt=s._insert(project,'ingest_attempts',item_id=item,input_id=input_row['id'],ordinal=ordinal,
            source_id=source,save_status=save_status,parse_status=parse_status,
            failure_stage=stage,reason=reason,result_sha256=result_sha,processor=PROCESSOR)
        self.fault('after_result')
        return attempt

    def process_batch(self, project, batch):
        with unit_of_work(self.database,self.principal) as s:
            s.get(project,'ingest_batches',batch)
            items=[dict(r) for r in s._connection.execute('SELECT * FROM ingest_items WHERE project_id=? AND batch_id=? ORDER BY position',(project,batch))]
        for item in items:
            try:
                self._process(project,item['id'])
            except (sqlite3.Error,OSError,ImportFailure):
                # The failed file's Store is closed/rolled back. Record the
                # failure in a *fresh* unit, then continue independent files.
                with unit_of_work(self.database,self.principal,write=True) as s:
                    self._item(s,project,item['id'])
                    old=self._latest(s,'ingest_attempts',project,item['id'])
                    if old is None:
                        inp=self._latest(s,'ingest_inputs',project,item['id'])
                        s._insert(project,'ingest_attempts',item_id=item['id'],input_id=inp['id'],ordinal=1,
                            source_id=None,save_status='failed',parse_status='not-run',failure_stage='transaction',
                            reason='item_transaction_failed_retry',result_sha256=None,processor=PROCESSOR)
        return self.batch(project,batch)

    def _process(self,project,item,*,request_key=None,replacement=None):
        # One fresh unit per file. A failed Store is never caught and reused.
        input_row=None
        try:
            with unit_of_work(self.database,self.principal,write=True) as s:
                self._item(s,project,item)
                latest=self._latest(s,'ingest_attempts',project,item)
                if request_key is None:
                    if latest is not None:
                        return dict(latest)
                    input_row=dict(self._latest(s,'ingest_inputs',project,item))
                else:
                    _key(request_key)
                    req=encoded({'replacement':replacement}).decode()
                    old=s._connection.execute('SELECT * FROM ingest_requests WHERE project_id=? AND item_id=? AND request_key=?',(project,item,request_key)).fetchone()
                    if old is not None:
                        if not _same_replacement_request(json.loads(old['request_json']),json.loads(req)):
                            raise ImportFailure('idempotency_conflict','request')
                        return s.get(project,'ingest_attempts',old['attempt_id'])
                    if latest is None:
                        raise ImportFailure('process_pending_item_first','retry')
                    if latest['save_status']=='saved' and latest['parse_status'] in ('parsed','not-requested'):
                        raise ImportFailure('successful_item_not_retryable','retry')
                    plan=s._connection.execute('SELECT * FROM ingest_retry_plans WHERE project_id=? AND item_id=? AND request_key=?',
                                               (project,item,request_key)).fetchone()
                    if plan is None or not _same_replacement_request(json.loads(plan['request_json']),json.loads(req)):
                        raise ImportFailure('retry_plan_mismatch','retry')
                    input_row=s.get(project,'ingest_inputs',plan['input_id'])
                # Any interrupted attempt for this input is cleaned under its
                # exclusive marker before new work. A persisted link is kept.
                expired=self._expired_stage(input_row)
                if not self._cleanup(input_row,finals=self._link(s,project,input_row) is None):
                    raise ImportFailure('cleanup_pending','cleanup')
                if expired:
                    retained_link=self._link(s,project,input_row)
                    retained_source=s._connection.execute('SELECT source_id FROM ingest_attempts WHERE project_id=? AND input_id=? AND source_id IS NOT NULL ORDER BY ordinal LIMIT 1',
                        (project,input_row['id'])).fetchone() if retained_link else None
                    attempt=s._insert(project,'ingest_attempts',item_id=item,input_id=input_row['id'],
                        ordinal=1 if latest is None else latest['ordinal']+1,source_id=retained_source[0] if retained_source else None,
                        save_status='saved' if retained_source else 'failed',parse_status='not-run',failure_stage='cleanup',
                        reason='temporary_expired_retry_required',result_sha256=None,processor=PROCESSOR)
                else:
                    attempt=self._attempt(s,project,item,input_row)
                if request_key is not None:
                    s._insert(project,'ingest_requests',item_id=item,request_key=request_key,request_json=req,attempt_id=attempt['id'])
                self.fault('before_commit')
            self.fault('after_commit')
            self._safe_cleanup(project,input_row)
            return attempt
        except (sqlite3.Error,OSError,ImportFailure) as error:
            # Filesystem writes may have outlived the rolled back DB operation.
            # Cleanup is retriable by recover(); don't pretend atomicity.
            if input_row is not None:
                self._safe_cleanup(project,input_row)
                # Record operational failure after the failed Store has fully
                # rolled back. The replacement identity and request binding
                # survive; the same request returns this exact failed result.
                if not isinstance(error,ImportFailure) or error.stage=='cleanup':
                    with unit_of_work(self.database,self.principal,write=True) as s:
                        self._item(s,project,item)
                        latest=self._latest(s,'ingest_attempts',project,item)
                        committed=s._connection.execute('SELECT 1 FROM ingest_attempts WHERE project_id=? AND input_id=? AND ordinal=?',
                            (project,input_row['id'],attempt['ordinal'] if 'attempt' in locals() else (latest['ordinal']+1 if latest else 1))).fetchone()
                        # after_commit means the result already exists; don't
                        # invent another failure after a lost response.
                        if not committed:
                            s.get(project,'ingest_inputs',input_row['id'])
                            link=self._link(s,project,input_row)
                            attempt=s._insert(project,'ingest_attempts',item_id=item,input_id=input_row['id'],
                                ordinal=1 if latest is None else latest['ordinal']+1,
                                source_id=latest['source_id'] if link and latest else None,
                                save_status='saved' if link else 'failed',parse_status='not-run',
                                failure_stage=error.stage if isinstance(error,ImportFailure) else 'transaction',
                                reason=error.code if isinstance(error,ImportFailure) else 'item_transaction_failed_retry',result_sha256=None,processor=PROCESSOR)
                            if request_key is not None:
                                s._insert(project,'ingest_requests',item_id=item,request_key=request_key,request_json=req,attempt_id=attempt['id'])
                            return attempt
            raise

    def _retry_budget(self,s,project,item,replacement):
        # Recheck under the writer lock: concurrent different-item retries
        # cannot each spend the same remaining batch bytes.
        batch=self._item(s,project,item)['batch_id']
        sizes=s._connection.execute('''SELECT i.byte_size,i.preflight_error FROM ingest_inputs i JOIN ingest_items t ON t.id=i.item_id AND t.project_id=i.project_id
            WHERE t.project_id=? AND t.batch_id=? AND t.id<>? AND i.ordinal=(SELECT MAX(n.ordinal) FROM ingest_inputs n WHERE n.project_id=i.project_id AND n.item_id=i.item_id)''',(project,batch,item)).fetchall()
        budget=MAX_BATCH-sum(r['byte_size'] or 0 for r in sizes if r['preflight_error'] is None)
        if replacement['preflight_error'] is None and replacement['byte_size']>budget:
            replacement['preflight_error']='batch_size_limit'

    def _safe_cleanup(self,project,input_row):
        with unit_of_work(self.database,self.principal,write=True) as s:
            s.project(project)
            return self._cleanup(input_row,finals=self._link(s,project,input_row) is None)

    def retry_item(self,project,item,request_key,*,use_original=False,replacement=None):
        self._authorize(project)
        with unit_of_work(self.database,self.principal) as s:
            self._item(s,project,item)
        if type(use_original) is not bool or use_original == (replacement is not None):
            raise ImportFailure('choose_original_or_replacement','retry')
        prepared=None
        if replacement is not None:
            # Retry budgets include latest inputs of *all* other batch items.
            with unit_of_work(self.database,self.principal) as s:
                batch=self._item(s,project,item)['batch_id']
                sizes=s._connection.execute('''SELECT i.byte_size,i.preflight_error FROM ingest_inputs i JOIN ingest_items t ON t.id=i.item_id AND t.project_id=i.project_id
                    WHERE t.project_id=? AND t.batch_id=? AND t.id<>? AND i.ordinal=(SELECT MAX(n.ordinal) FROM ingest_inputs n WHERE n.project_id=i.project_id AND n.item_id=i.item_id)''',(project,batch,item)).fetchall()
            budget=MAX_BATCH-sum(r['byte_size'] or 0 for r in sizes if r['preflight_error'] is None)
            prepared=self._selection(replacement,budget=budget)
        # Persist the operation and replacement identity BEFORE any file writes.
        # A process exit cannot erase the journal needed to clean/retry its files.
        _key(request_key)
        req=encoded({'replacement':prepared}).decode()
        with unit_of_work(self.database,self.principal,write=True) as s:
            self._item(s,project,item)
            existing=s._connection.execute('SELECT * FROM ingest_retry_plans WHERE project_id=? AND item_id=? AND request_key=?',
                                          (project,item,request_key)).fetchone()
            if existing is not None:
                if not _same_replacement_request(json.loads(existing['request_json']),json.loads(req)):
                    raise ImportFailure('idempotency_conflict','request')
            else:
                pending=s._connection.execute('''SELECT 1 FROM ingest_retry_plans p WHERE p.project_id=? AND p.item_id=?
                    AND NOT EXISTS(SELECT 1 FROM ingest_requests r WHERE r.project_id=p.project_id AND r.item_id=p.item_id AND r.request_key=p.request_key)''',
                    (project,item)).fetchone()
                if pending:
                    raise ImportFailure('retry_in_progress_resume_original_key','retry')
                latest=self._latest(s,'ingest_attempts',project,item)
                if latest is None:
                    raise ImportFailure('process_pending_item_first','retry')
                if latest['save_status']=='saved' and latest['parse_status'] in ('parsed','not-requested'):
                    raise ImportFailure('successful_item_not_retryable','retry')
                if prepared is not None:
                    values=dict(prepared)
                    self._retry_budget(s,project,item,values)
                    current=self._latest(s,'ingest_inputs',project,item)
                    inp=s._insert(project,'ingest_inputs',item_id=item,ordinal=current['ordinal']+1,**values)
                else:
                    inp=s.get(project,'ingest_inputs',latest['input_id'])
                s._insert(project,'ingest_retry_plans',item_id=item,input_id=inp['id'],request_key=request_key,request_json=req)
        return self._process(project,item,request_key=request_key,replacement=prepared)

    def _availability(self,input_row,link):
        if link is None:
            return {'status':'not-saved','action':'retry_selected_input'}
        try:
            data=localfiles.inspect(link['location'])
            if len(data)!=input_row['byte_size'] or digest(data)!=input_row['fingerprint']:
                return {'status':'changed','action':'reselect_matching_original'}
            return {'status':'available','action':None}
        except ImportFailure:
            return {'status':'unavailable','action':'reselect_matching_original'}

    def item(self,project,item):
        with unit_of_work(self.database,self.principal) as s:
            value=self._item(s,project,item)
            inputs=[]
            for row in s._connection.execute('SELECT * FROM ingest_inputs WHERE project_id=? AND item_id=? ORDER BY ordinal',(project,item)):
                row=dict(row);selection=json.loads(row['selection_json'])
                link=self._link(s,project,row)
                row.update(name=selection['name'],media_type=selection['media_type'],storage_choice=selection['storage_choice'],
                    parse_requested=selection['parse'],availability=self._availability(row,link))
                try:
                    paths=self._paths(row)
                    residue=any(p.with_suffix(p.suffix+'.stage').exists() for k,p in paths.items() if k!='marker')
                    orphan=link is None and any(paths[k].exists() for k in ('original','parsed'))
                    row['temporary_cleanup']='cleanup-pending' if residue or orphan else 'clean'
                except (ImportFailure,OSError):
                    row['temporary_cleanup']='cleanup-pending'
                row.pop('selection_json')
                inputs.append(row)
            attempts=[dict(r) for r in s._connection.execute('SELECT * FROM ingest_attempts WHERE project_id=? AND item_id=? ORDER BY ordinal',(project,item))]
            plans=[dict(r) for r in s._connection.execute('''SELECT p.id,p.input_id,p.request_key,p.created_at,r.attempt_id FROM ingest_retry_plans p
                LEFT JOIN ingest_requests r ON r.project_id=p.project_id AND r.item_id=p.item_id AND r.request_key=p.request_key
                WHERE p.project_id=? AND p.item_id=? ORDER BY p.created_at,p.id''',(project,item))]
            extracted=s._connection.execute('SELECT id FROM native_runs WHERE project_id=? AND item_id=? AND input_id=?',
                (project,item,attempts[-1]['input_id'] if attempts else inputs[-1]['id'])).fetchone()
            return dict(value,inputs=inputs,attempts=attempts,retry_requests=plans,
                        current_input_id=attempts[-1]['input_id'] if attempts else inputs[-1]['id'],latest=attempts[-1] if attempts else None,
                        semantic_status='extracted' if extracted else 'not-performed',attribution='see-native-decisions' if extracted else 'project-only',model_authorization='not-granted')

    def batch(self,project,batch):
        with unit_of_work(self.database,self.principal) as s:
            value=s.get(project,'ingest_batches',batch)
            value.pop('manifest_json')  # internal selected paths are not ordinary metadata output
            ids=[r[0] for r in s._connection.execute('SELECT id FROM ingest_items WHERE project_id=? AND batch_id=? ORDER BY position',(project,batch))]
        items=[self.item(project,i) for i in ids]
        complete=[i for i in items if i['latest'] and i['latest']['save_status']=='saved' and i['latest']['parse_status'] in ('parsed','not-requested')]
        missing=[{'item_id':i['id'],'name':i['inputs'][-1]['name'],
                  'reason':i['latest']['reason'] if i['latest'] else 'pending'} for i in items if i not in complete]
        return dict(value,items=items,summary={'complete':len(complete),'incomplete':len(missing),'total':len(items)},missing_materials=missing)

    def batches(self,project):
        with unit_of_work(self.database,self.principal) as s:
            s.project(project)
            return [dict(r) for r in s._connection.execute('SELECT id,created_at,processing_version,fingerprint FROM ingest_batches WHERE project_id=? ORDER BY created_at,id',(project,))]

    def read_original(self,project,item,*,input_id=None):
        with unit_of_work(self.database,self.principal) as s:
            self._item(s,project,item)
            current=self._latest(s,'ingest_attempts',project,item)
            row=(s.get(project,'ingest_inputs',current['input_id']) if current else dict(self._latest(s,'ingest_inputs',project,item))) if input_id is None else s.get(project,'ingest_inputs',input_id)
            if row['item_id']!=item:
                raise AccessError(404,'object_not_found')
            link=self._link(s,project,row)
            if self._availability(row,link)['status']!='available':
                raise ImportFailure('original_unavailable_reassociate','read')
            data=localfiles.inspect(link['location'])
            if digest(data)!=row['fingerprint']:
                raise ImportFailure('original_changed','read')
            return data

    def read_parsed(self,project,item):
        with unit_of_work(self.database,self.principal) as s:
            self._item(s,project,item)
            attempt=self._latest(s,'ingest_attempts',project,item)
            if attempt is None or attempt['parse_status']!='parsed':
                raise ImportFailure('parsed_result_unavailable','read')
            row=s.get(project,'ingest_inputs',attempt['input_id'])
            link=self._link(s,project,row)
            if link is None or not link['result_location']:
                raise ImportFailure('parsed_result_unavailable','read')
            try:
                data=localfiles.inspect(link['result_location'],limit=MAX_OUTPUT)
            except ImportFailure:
                raise ImportFailure('parsed_result_unavailable','read') from None
            if digest(data)!=attempt['result_sha256']:
                raise ImportFailure('parsed_result_changed','read')
            return json.loads(data)

    def original_location(self,project,item):
        """Explicit owner-only local takeout; no path in generic errors/listing."""
        with unit_of_work(self.database,self.principal) as s:
            self._item(s,project,item)
            current=self._latest(s,'ingest_attempts',project,item)
            row=s.get(project,'ingest_inputs',current['input_id']) if current else dict(self._latest(s,'ingest_inputs',project,item))
            link=self._link(s,project,row)
            if link is None:
                raise ImportFailure('original_not_saved','read')
            return {'path':link['location'],'availability':self._availability(row,link)}

    def reassociate(self,project,item,input_id,selected):
        with unit_of_work(self.database,self.principal,write=True) as s:
            self._item(s,project,item)
            row=s.get(project,'ingest_inputs',input_id)
            if row['item_id']!=item:
                raise AccessError(404,'object_not_found')
            if not isinstance(selected,SelectedFile):
                raise ImportFailure('explicit_selection_required','selection')
            link=self._link(s,project,row)
            if link is None:
                raise ImportFailure('original_not_saved','read')
            data=localfiles.inspect(selected.path)
            if len(data)!=row['byte_size'] or digest(data)!=row['fingerprint']:
                raise ImportFailure('original_identity_mismatch','selection')
            p=str(localfiles.absolute(selected.path))
            if p==link['location']:
                return dict(link)
            return s._insert(project,'original_links',input_id=input_id,location=p,
                result_location=link['result_location'],supersedes_id=link['id'])

    def recover(self,project,batch):
        """Owner-scoped deterministic cleanup/resume, never sweeps user files.

        A writer lock proves no active item owns a stage. All abandoned stages
        are removed immediately (stricter than 24h), never renewed. Failures are
        reported and retryable; process_batch resumes only uncompleted items.
        """
        results=[]
        with unit_of_work(self.database,self.principal,write=True) as s:
            s.get(project,'ingest_batches',batch)
            rows=s._connection.execute('''SELECT i.* FROM ingest_inputs i JOIN ingest_items t ON t.project_id=i.project_id AND t.id=i.item_id
                WHERE t.project_id=? AND t.batch_id=?''',(project,batch)).fetchall()
            for row in rows:
                results.append({'input_id':row['id'],'cleanup':'clean' if self._cleanup(dict(row),finals=self._link(s,project,row) is None) else 'cleanup-pending'})
        return results
