"""Same-origin transport for existing services. No client-supplied Principal."""
import base64
import binascii
from datetime import datetime, timezone
import json
import re
import hashlib
import os

from .auth import AccessError
from .changes import ChangeError, Changes, canonical, digest, exact
from .formats import ImportFailure, MAX_FILE, MAX_BATCH, MAX_FILES, display_name
from .ingestion import ImportService, SelectedFile
from . import localfiles
from .store import unit_of_work

MAX_REQUEST = (MAX_BATCH * 4 // 3) + 128 * 1024
HISTORY = ('change_commits','applied_changes','baseline_history','effect_corrections','reversal_previews')


def upload_path(root,project,key,index):
    return root/('upload-'+digest([project,key,index])+'.input')


def upload_marker(path):
    return path.with_suffix('.upload-owner')


def claim_upload(path):
    marker=upload_marker(path)
    if marker.exists():
        if localfiles.inspect(marker)!=b'':raise ChangeError('upload_storage_conflict')
        return
    if path.exists() or path.with_suffix(path.suffix+'.stage').exists():
        raise ChangeError('upload_storage_conflict')
    # An exclusively created empty marker cannot tear into a partial payload.
    # It authorizes cleanup only for this immutable, DB-registered slot.
    with localfiles.opened(marker,create=True) as stream:
        stream.flush();os.fsync(stream.fileno())


def cleanup_upload(path,expected_sha):
    marker=upload_marker(path)
    try:
        if not marker.exists():
            return not (path.exists() or path.with_suffix(path.suffix+'.stage').exists())
        if localfiles.inspect(marker)!=b'':return False
        if path.exists() and hashlib.sha256(localfiles.inspect(path)).hexdigest()!=expected_sha:
            return False  # Never delete an unknown/tampered occupant.
        return all([localfiles.remove_owned(path),localfiles.remove_owned(path.with_suffix(path.suffix+'.stage'))])
    except (ImportFailure,OSError):
        return False


def read_json(env):
    if env.get('CONTENT_TYPE','').split(';')[0] != 'application/json':
        raise AccessError(415,'json_required')
    try:
        size = int(env.get('CONTENT_LENGTH','0'))
    except ValueError:
        raise AccessError(400,'invalid_content_length') from None
    if not 0 < size <= MAX_REQUEST:
        raise AccessError(413,'request_size_limit')
    raw = env['wsgi.input'].read(size)
    if len(raw) != size:
        raise AccessError(400,'incomplete_request')
    def pairs(items):
        result = {}
        for k,v in items:
            if k in result:
                raise ValueError('duplicate')
            result[k] = v
        return result
    try:
        value = json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError,UnicodeError,RecursionError):
        raise AccessError(400,'invalid_json') from None
    if not isinstance(value,dict):
        raise AccessError(400,'json_object_required')
    return value


def request_key(env):
    value = env.get('HTTP_IDEMPOTENCY_KEY','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',value):
        raise AccessError(400,'idempotency_key_required')
    return value


class BusinessAPI:
    def __init__(self, settings, principal):
        self.settings,self.principal = settings,principal

    def importer(self):
        if self.settings.local_root is None:
            raise AccessError(409,'local_storage_not_configured')
        return ImportService(self.settings.database,self.principal,self.settings.local_root)

    def receipt(self, store, key, route, body, operation):
        fingerprint = digest(body)
        c = store._connection
        old = c.execute('SELECT * FROM http_receipts WHERE subject=? AND request_key=?',
                        (self.principal.subject,key)).fetchone()
        if old:
            if old['route'] != route or old['fingerprint'] != fingerprint:
                raise ChangeError('idempotency_key_reused')
            return json.loads(old['result_json'])
        result = operation()
        c.execute('INSERT INTO http_receipts VALUES (?,?,?,?,?,?)',
                  (self.principal.subject,key,route,fingerprint,canonical(result),datetime.now(timezone.utc).isoformat()))
        return result

    def candidates(self, s, project):
        return {'candidates':[dict(s.candidate(project,r['candidate_id']),
                        authorization=Changes(s).authorization(s.candidate(project,r['candidate_id'])))
                        for r in s.records(project,'candidate_specs')],
                'reviews':s.records(project,'change_reviews'),
                'supersessions':s.records(project,'candidate_supersessions')}

    def snapshot(self, s, project):
        state=s.formal_state(project)
        versions=s.records(project,'artifact_versions')
        for v in versions:
            v.pop('content')
            v['provenance']=s.version_provenance(project,v['id'])
        return dict(formal=state,**self.candidates(s,project),
            artifacts=s.records(project,'artifacts'),versions=versions,
            sources=s.records(project,'sources'),attributions=s.records(project,'source_attributions'),
            evidence=s.records(project,'evidence'),version_sources=s.records(project,'version_sources'),
            history={k:s.records(project,k) for k in HISTORY})

    def handle(self, env, path, method):
        if path.startswith('/api/requests/') and method=='GET':
            key=path.removeprefix('/api/requests/')
            with unit_of_work(self.settings.database,self.principal) as s:
                old=s._connection.execute('SELECT * FROM http_receipts WHERE subject=? AND request_key=?',(self.principal.subject,key)).fetchone()
                if old:
                    route=old['route'].strip('/').split('/')
                    if len(route)>2:s.project(route[2])
                    return {'state':'committed','result':json.loads(old['result_json'])}
                # Uploads have their own durable T07 registration/attempt journal.
                row=s._connection.execute('''SELECT b.id,b.project_id FROM ingest_batches b JOIN projects p ON p.id=b.project_id
                    WHERE p.owner_subject=? AND b.request_key=?''',(self.principal.subject,key)).fetchone()
                if row:return {'state':'registered','result':dict(row)}
                row=s._connection.execute('''SELECT r.attempt_id,r.project_id FROM ingest_requests r JOIN projects p ON p.id=r.project_id
                    WHERE p.owner_subject=? AND r.request_key=?''',(self.principal.subject,key)).fetchone()
                if row:return {'state':'committed','result':dict(row)}
                return {'state':'not-committed','result':None}
        if path == '/api/workspace' and method == 'GET':
            return dict(mode='local',data='synthetic-only',
                local_storage={'choice':'configured-local','directory':str(self.settings.local_root) if self.settings.local_root else None},
                limits={'files':MAX_FILES,'file_bytes':MAX_FILE,'batch_bytes':MAX_BATCH},
                capabilities={'format_parse':True,'semantic_extraction':False,'context_sync':False,'cloud_storage':False})
        parts=path.strip('/').split('/')
        if parts[:2]!=['api','projects']:
            raise AccessError(404,'route_not_found')
        if len(parts)==2:
            if method=='GET':
                with unit_of_work(self.settings.database,self.principal) as s:
                    return {'projects':s.projects(),'data':'synthetic-only'}
            if method=='POST':
                body=read_json(env);exact(body,('title',));key=request_key(env)
                with unit_of_work(self.settings.database,self.principal,write=True) as s:
                    result=self.receipt(s,key,path,body,lambda:s.create_project(body['title']))
                return result
            raise AccessError(405,'method_not_allowed')
        project=parts[2];tail=parts[3:]
        # Authorization precedes body parsing, replay lookup, disk reads and writes.
        with unit_of_work(self.settings.database,self.principal) as s:
            s.project(project)
        if method=='GET':
            if tail and tail[0]=='imports':
                imp=self.importer()
                if len(tail)==1:
                    return {'batches':[imp.batch(project,b['id']) for b in imp.batches(project)]}
                if len(tail)==2:
                    return imp.batch(project,tail[1])
            if len(tail)>=2 and tail[0]=='items':
                imp=self.importer()
                if len(tail)==2:
                    return imp.item(project,tail[1])
                if len(tail)==3 and tail[2]=='parsed':
                    return imp.read_parsed(project,tail[1])
                if len(tail)==3 and tail[2]=='original':
                    return {'base64':base64.b64encode(imp.read_original(project,tail[1])).decode('ascii')}
            with unit_of_work(self.settings.database,self.principal) as s:
                if not tail:return s.project(project)
                if tail==['snapshot']:return self.snapshot(s,project)
                if tail==['formal']:return s.formal_state(project)
                if tail==['candidates']:return self.candidates(s,project)
                if tail==['history']:return {k:s.records(project,k) for k in HISTORY}
                if len(tail)==2 and tail[0]=='candidates':return dict(s.candidate(project,tail[1]),authorization=Changes(s).authorization(s.candidate(project,tail[1])))
                if len(tail)==2 and tail[0]=='commits':return {'result':s.commit_result(project,tail[1])}
                if tail==['artifacts']:return {'artifacts':s.records(project,'artifacts')}
                if tail==['sources']:return {'sources':[dict(r,attribution=s.attribution(project,r['id'])) for r in s.records(project,'sources')]}
                if len(tail)==2 and tail[0]=='tasks':
                    s.get(project,'tasks',tail[1]);state=s.formal_state(project)
                    task=next((t for t in state['tasks'] if t['task_id']==tail[1]),None)
                    if task is None:raise AccessError(404,'object_not_found')
                    return {'task':task,'project_revision':state['project']['revision'],
                            'derived':next(t for t in state['derived']['tasks'] if t['task_id']==tail[1]),
                            'evidence':[e for e in s.records(project,'evidence') if e['task_id']==tail[1]],
                            'events':[e for e in state['events'] if e['task_id']==tail[1]]}
                if len(tail)==2 and tail[0]=='sources':return dict(s.get(project,'sources',tail[1]),attribution=s.attribution(project,tail[1]))
                if len(tail)==2 and tail[0]=='versions':
                    return dict(version=s.get(project,'artifact_versions',tail[1]),provenance=s.version_provenance(project,tail[1]),
                                evidence=[e for e in s.records(project,'evidence') if e['version_id']==tail[1]])
                if len(tail)==3 and tail[0]=='artifacts' and tail[2]=='versions':
                    s.get(project,'artifacts',tail[1])
                    return {'versions':[{k:v for k,v in r.items() if k!='content'} for r in s.records(project,'artifact_versions') if r['artifact_id']==tail[1]]}
            raise AccessError(404,'route_not_found')
        if method!='POST':raise AccessError(405,'method_not_allowed')
        body=read_json(env);key=request_key(env)
        if tail==['imports']:
            return self.upload(project,key,body)
        if len(tail)==3 and tail[0]=='imports' and tail[2]=='process':
            exact(body,())
            return self.importer().process_batch(project,tail[1])
        if len(tail)==3 and tail[0]=='items' and tail[2]=='retry':
            exact(body,(),('use_original','replacement'))
            imp=self.importer()
            # Check item before staging replacement bytes.
            imp.item(project,tail[1])
            if 'replacement' in body:
                exact(body,('replacement',))
                return self.upload(project,key,{'storage_choice':'configured-local','parse':True,'files':[body['replacement']]},item=tail[1])
            exact(body,('use_original',))
            return imp.retry_item(project,tail[1],key,use_original=body['use_original'])
        with unit_of_work(self.settings.database,self.principal,write=True) as s:
            s.project(project)
            def operation():
                if tail==['candidates']:
                    c=s.save_candidate(project,body)
                    return dict(c,authorization=Changes(s).authorization(c))
                if tail==['reviews']:return {'reviews':s.review_candidates(project,body)}
                if tail==['commits']:
                    exact(body,('request_key','base_revision','selection'))
                    if body['request_key']!=key:raise ChangeError('request_key_mismatch')
                    return s.commit_candidates(project,body)
                if tail==['reversal-previews']:
                    exact(body,('change_id',));return s.preview_reversal(project,body['change_id'])
                if tail==['checks']:
                    exact(body,('task_id','version_id','configuration'))
                    return s.run_check(project,body['task_id'],body['version_id'],body['configuration'])
                if tail==['auto-accept']:return s.accept_pre_authorized(project,body)
                if tail==['artifacts']:
                    exact(body,('title',));return s.create_artifact(project,body['title'])
                if len(tail)==3 and tail[0]=='artifacts' and tail[2]=='versions':
                    exact(body,('content','reason'),('media_type','task_ids','source_ids'))
                    return s.create_version(project,tail[1],**body)
                raise AccessError(404,'route_not_found')
            result=self.receipt(s,key,path,body,operation)
        return result  # Only after COMMIT, never from inside the context manager.

    def upload(self, project, key, body, *, item=None):
        exact(body,('storage_choice','parse','files'))
        if body['storage_choice']!='configured-local' or type(body['parse']) is not bool:
            raise ChangeError('explicit_local_storage_choice_required')
        files=body['files']
        if not isinstance(files,list) or not 1<=len(files)<=MAX_FILES:
            raise AccessError(413,'batch_file_count_limit')
        decoded=[];total=0;manifest=[]
        for f in files:
            exact(f,('name','base64'),('media_type',))
            name=display_name(f['name'])
            if not isinstance(f['base64'],str) or len(f['base64'])>4*((MAX_FILE+2)//3):
                raise AccessError(413,'file_size_limit')
            try:data=base64.b64decode(f['base64'],validate=True)
            except (ValueError,binascii.Error):raise AccessError(400,'invalid_file_encoding') from None
            total+=len(data)
            if len(data)>MAX_FILE or total>MAX_BATCH:raise AccessError(413,'batch_size_limit')
            media=f.get('media_type') or None
            if media is not None and (not isinstance(media,str) or len(media)>128):raise ChangeError('invalid_media_type')
            decoded.append(data)
            manifest.append(dict(name=name,media_type=media,sha256=hashlib.sha256(data).hexdigest(),size=len(data)))
        imp=self.importer()
        record=canonical(dict(files=manifest,parse=body['parse'],item=item,storage_root=str(imp.root)))
        paths=[upload_path(imp.root,project,key,i) for i in range(len(decoded))]
        with unit_of_work(self.settings.database,self.principal,write=True) as s:
            s.project(project)
            old=s._connection.execute('SELECT manifest_json FROM browser_uploads WHERE project_id=? AND request_key=?',(project,key)).fetchone()
            if old and old[0]!=record:raise ChangeError('idempotency_key_reused')
            if not old:
                # Registration cannot adopt a pre-existing unrelated file/marker.
                if any(p.exists() or p.with_suffix(p.suffix+'.stage').exists() or upload_marker(p).exists() for p in paths):
                    raise ChangeError('upload_storage_conflict')
                s._connection.execute('INSERT INTO browser_uploads VALUES (?,?,?,?)',(project,key,record,datetime.now(timezone.utc).isoformat()))
        # Generated, journaled filenames; names/paths in uploaded content never select disk paths.
        claimed=[]
        try:
            for p,data,meta in zip(paths,decoded,manifest):
                claim_upload(p);claimed.append((p,meta['sha256']))
                if p.exists():
                    if localfiles.inspect(p)!=data:raise ChangeError('upload_content_changed')
                else:localfiles.persist(p,data)
            selected=[SelectedFile(p,f['name'],f['media_type'],parse=body['parse']) for p,f in zip(paths,manifest)]
            if item:return imp.retry_item(project,item,key,replacement=selected[0])
            return imp.import_files(project,key,selected)
        finally:
            cleaned=[cleanup_upload(p,sha) for p,sha in claimed]
            if not all(cleaned):raise AccessError(503,'upload_cleanup_pending')


def cleanup_uploads(settings):
    """Startup cleanup of exact journaled spool slots, including interrupted uploads."""
    if settings.local_root is None:return
    from .db import connect
    with connect(settings.database) as c:
        for r in c.execute('''SELECT u.* FROM browser_uploads u JOIN projects p ON p.id=u.project_id
                              WHERE p.owner_subject=?''',(settings.subject,)):
            m=json.loads(r['manifest_json'])
            if m['storage_root']!=str(settings.local_root):continue
            for i,meta in enumerate(m['files']):
                p=upload_path(settings.local_root,r['project_id'],r['request_key'],i)
                cleanup_upload(p,meta['sha256'])
