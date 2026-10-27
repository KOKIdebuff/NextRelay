"""Batch-scoped consent -> one bounded external call/item -> reviewed candidates.

No payload or raw response spool. Only manifests, digests, bounded derived proposals
and append-only state survive a process exit. An uncertain send is NEVER resent.
"""
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import uuid4
from .auth import AccessError
from .changes import ChangeError, Changes, canonical, digest, exact, integer
from .formats import ImportFailure, encoded
from .model_protocol import (TEMPLATE, PROTOCOL, SYSTEM, SCHEMA, MAX_REQUEST, MAX_TEXT,
                             MAX_CANDIDATES, strict_json, bounded_text, wire)
from .model_protocol import PROTOCOL_V2, THREAD_OPERATIONS, configuration
from .model_provider import ModelConfig, ResponsesAdapter, ProviderFailure
from .native import Native, PROCESSOR
from .store import unit_of_work

PURPOSE = 'Prepare traceable unverified task/version candidates for independent human review'


def raw_sha(data):return hashlib.sha256(data).hexdigest()


def core(request):
    return {k:request.get(k) for k in ('operation','target_id','target_version_id','payload')}


def event(s,project,batch,state,code='',job=None,metadata=None):
    seq=s._connection.execute('SELECT coalesce(max(sequence),0)+1 FROM model_events WHERE project_id=? AND batch_id=?',(project,batch)).fetchone()[0]
    return s._insert(project,'model_events',batch_id=batch,job_id=job,sequence=seq,
                     state=state,code=code,metadata_json=canonical(metadata or {}))


def events(s,project,batch):
    s.get(project,'model_batches',batch)
    return [dict(r) for r in s._connection.execute('SELECT * FROM model_events WHERE project_id=? AND batch_id=? ORDER BY sequence',(project,batch))]


def decision(s,project,batch):
    return next((e['state'] for e in reversed(events(s,project,batch)) if e['job_id'] is None),'prepared')


def job_state(s,project,job):
    r=s._connection.execute('SELECT state FROM model_events WHERE project_id=? AND job_id=? ORDER BY sequence DESC LIMIT 1',(project,job)).fetchone()
    return r[0] if r else 'pending'


def database_guard(s,project,selection):
    """Conservative metadata-only freshness identity; never sent to the model.

    Native/source corrections and non-revision base-record changes must invalidate
    approvals too. Unrelated edits may conservatively require a fresh preview.
    """
    p=s.project(project);c=s._connection
    parts=[p['revision'],selection]
    queries=(
        'SELECT id,content_sha256,artifact_id FROM artifact_versions WHERE project_id=? ORDER BY id',
        'SELECT id FROM source_attributions WHERE project_id=? ORDER BY id',
        'SELECT id FROM native_runs WHERE project_id=? ORDER BY id',
        'SELECT id FROM native_documents WHERE project_id=? ORDER BY id',
        'SELECT id FROM native_decisions WHERE project_id=? ORDER BY id',
        'SELECT id FROM native_relations WHERE project_id=? ORDER BY id',
        'SELECT * FROM tasks WHERE project_id=? ORDER BY id',
        'SELECT * FROM sessions WHERE project_id=? ORDER BY id',
        'SELECT * FROM attempts WHERE project_id=? ORDER BY id',
        'SELECT * FROM task_sessions WHERE project_id=? ORDER BY task_id,session_id',
        'SELECT * FROM attempt_sessions WHERE project_id=? ORDER BY attempt_id,session_id',
        'SELECT id FROM evidence WHERE project_id=? ORDER BY id',
    )
    for query in queries:
        rows=c.execute(query,(project,)).fetchmany(2001)
        if len(rows)>2000:raise ChangeError('model_project_metadata_limit')
        parts.append(digest([dict(r) for r in rows]))
    if selection.get('protocol')==PROTOCOL_V2:
        for table in ('thread_duties','task_participation','task_leads','thread_successions','contribution_duties','version_sources','artifact_version_tasks','sources'):
            rows=c.execute(f'SELECT * FROM {table} WHERE project_id=? ORDER BY rowid',(project,)).fetchmany(2001)
            if len(rows)>2000:raise ChangeError('model_project_metadata_limit')
            parts.append([table,digest([dict(r) for r in rows])])
    for item in selection['item_ids']:
        i=s.get(project,'ingest_items',item)
        if i['batch_id']!=selection['import_batch_id']:raise ChangeError('model_wrong_import_batch')
        parts.append([dict(r) for r in c.execute('SELECT id,input_id,source_id,parse_status,result_sha256 FROM ingest_attempts WHERE project_id=? AND item_id=? ORDER BY ordinal DESC LIMIT 1',(project,item))])
    return digest(parts)


class ModelContext:
    def __init__(self,s):self.s=s

    def proposal(self,project,context):
        exact(context,('proposal_id',))
        return self.s.get(project,'model_proposals',context['proposal_id'])

    def batch_guard(self,project,context):
        proposal=self.proposal(project,context)
        result=self.s.get(project,'model_results',proposal['result_id'])
        job=self.s.get(project,'model_jobs',result['job_id'])
        return self.s.get(project,'model_batches',job['batch_id'])['guard_sha256']

    def minimum_conflicts(self,project,context):
        proposal=self.proposal(project,context)
        rows=self.s._connection.execute('''SELECT p.request_json FROM model_proposals p
            JOIN model_results r ON r.project_id=p.project_id AND r.id=p.result_id
            JOIN model_jobs j ON j.project_id=r.project_id AND j.id=r.job_id
            JOIN model_batches b ON b.project_id=j.project_id AND b.id=j.batch_id
            WHERE p.project_id=? AND p.core_sha256=? AND b.guard_sha256=(
                SELECT b2.guard_sha256 FROM model_results r2
                JOIN model_jobs j2 ON j2.project_id=r2.project_id AND j2.id=r2.job_id
                JOIN model_batches b2 ON b2.project_id=j2.project_id AND b2.id=j2.batch_id
                WHERE r2.project_id=? AND r2.id=?) LIMIT 2001''',
            (project,proposal['core_sha256'],project,proposal['result_id'])).fetchall()
        if len(rows)>2000:raise ChangeError('model_proposal_history_limit')
        flags=sorted({flag for row in rows for flag in json.loads(row[0])['conflicts']})
        if len(flags)>100:raise ChangeError('model_conflict_limit')
        return flags

    def check(self,project,spec):
        proposal=self.proposal(project,spec['model_context']);expected=json.loads(proposal['request_json'])
        actual=core(spec)
        if spec['operation']=='task.create':actual['target_id']=None
        if (actual!=core(expected) or spec['source_ids']!=expected['source_ids'] or spec['evidence_ids']!=expected.get('evidence_ids',[])
            or spec.get('native_context')!=expected.get('native_context') or not set(expected['conflicts'])<=set(spec['conflicts'])):
            raise ChangeError('model_proposal_mismatch')
        known_conflicts=self.minimum_conflicts(project,spec['model_context'])
        if not set(known_conflicts)<=set(spec['conflicts']):raise ChangeError('model_known_conflicts_changed')
        result=self.s.get(project,'model_results',proposal['result_id'])
        job=self.s.get(project,'model_jobs',result['job_id']);batch=self.s.get(project,'model_batches',job['batch_id'])
        selection=json.loads(batch['selection_json'])
        if database_guard(self.s,project,selection)!=batch['guard_sha256']:raise ChangeError('model_context_stale')
        return dict(proposal_id=proposal['id'],result_id=result['id'],response_sha256=result['response_sha256'],
            batch_id=batch['id'],manifest_sha256=batch['fingerprint'],guard_sha256=batch['guard_sha256'],
            processor=json.loads(batch['manifest_json'])['template'],citations=json.loads(proposal['citations_json']),rationale=proposal['rationale'],
            interpretation='model-unverified',minimum_risk='conflict' if known_conflicts else 'high',known_conflicts=known_conflicts)

    def matching(self,project,spec):
        # Source/risk omissions cannot turn an already stored model proposal into
        # an ordinary direct-save candidate. Historical schema fixtures omit T09.
        if not self.s._connection.execute("SELECT 1 FROM sqlite_schema WHERE name='model_proposals'").fetchone():return False
        value=core(spec)
        if spec['operation']=='task.create':value['target_id']=None
        return self.s._connection.execute('SELECT 1 FROM model_proposals WHERE project_id=? AND core_sha256=?',(project,digest(value))).fetchone() is not None


class ModelService:
    def __init__(self,importer,config=None):
        self.imp=importer;self.config=config or ModelConfig()
        self.db=importer.database;self.principal=importer.principal

    def _enabled(self):
        if self.config.provider=='disabled':raise ChangeError('model_not_configured')

    def _batch(self,s,project,batch):return s.get(project,'model_batches',batch)

    def _select(self,s,project,request):
        exact(request,('import_batch_id',),('item_ids','task_ids','thread_ids','protocol'))
        imp=request['import_batch_id'];s.get(project,'ingest_batches',imp)
        items=request.get('item_ids')
        if items is None:items=[r[0] for r in s._connection.execute('SELECT id FROM ingest_items WHERE project_id=? AND batch_id=? ORDER BY position',(project,imp))]
        tasks=request.get('task_ids',[])
        for values in (items,tasks):
            if not isinstance(values,list) or len(values)>20 or any(not isinstance(i,str) for i in values) or len(set(values))!=len(values):raise ChangeError('model_invalid_selection')
        if not items:raise ChangeError('model_empty_selection')
        for i in items:
            if s.get(project,'ingest_items',i)['batch_id']!=imp:raise ChangeError('model_wrong_import_batch')
        for t in tasks:s.get(project,'tasks',t)
        protocol=request.get('protocol',PROTOCOL);configuration(protocol)
        threads=request.get('thread_ids',[])
        if not isinstance(threads,list) or len(threads)>20 or any(not isinstance(i,str) for i in threads) or len(set(threads))!=len(threads):raise ChangeError('model_invalid_selection')
        if threads and protocol!=PROTOCOL_V2:raise ChangeError('model_thread_protocol_required')
        for t in threads:s.get(project,'sessions',t)
        result=dict(import_batch_id=imp,item_ids=sorted(items),task_ids=sorted(tasks))
        if protocol==PROTOCOL_V2:result.update(protocol=protocol,thread_ids=sorted(threads))
        return result

    def _gather(self,project,selection):
        parsed={};states=[]
        for item in selection['item_ids']:
            value=self.imp.item(project,item);a=value['latest'];state='pending'
            if a:
                state='read' if a['parse_status']=='parsed' else a['parse_status']
                if a['parse_status']=='parsed':
                    try:
                        body=self.imp.read_parsed(project,item)
                        if raw_sha(encoded(body))!=a['result_sha256']:raise ImportFailure('parsed_result_changed')
                        parsed[item]=(a,body)
                    except ImportFailure as error:state='unavailable:'+error.code
            states.append(dict(item_id=item,input_id=value['current_input_id'],state=state,included=item in parsed))
        with unit_of_work(self.db,self.principal) as s:
            return self._build(s,project,selection,parsed,states)

    def _build(self,s,project,selection,parsed,states):
        c=s._connection;p=s.project(project);n=Native(s);guard=database_guard(s,project,selection)
        formal=s.formal_state(project);formal_tasks={t['task_id']:t for t in formal['tasks']}
        protocol=selection.get('protocol',PROTOCOL);template,system,schema=configuration(protocol)
        jobs=[]
        for item,(attempt,body) in sorted(parsed.items()):
            latest=c.execute('SELECT * FROM ingest_attempts WHERE project_id=? AND item_id=? ORDER BY ordinal DESC LIMIT 1',(project,item)).fetchone()
            if not latest or latest['id']!=attempt['id']:raise ChangeError('model_input_changed')
            inp=s.get(project,'ingest_inputs',attempt['input_id'])
            if body['source_sha256']!=inp['fingerprint']:raise ChangeError('model_input_changed')
            entries=[];seen=set()
            def add(kind,identity,value,version=None,sources=()):
                key=kind+':'+identity
                if key in seen:return
                seen.add(key);text=value if isinstance(value,str) else canonical(value)
                if len(text.encode('utf-8'))>MAX_TEXT:raise ChangeError('model_context_entry_limit')
                entries.append(dict(id=key,kind=kind,object_id=identity,version=version,
                    source_ids=sorted(set(sources)),text=text,sha256=raw_sha(text.encode('utf-8'))))
            source=attempt['source_id']
            add('format',inp['id'],body,attempt['result_sha256'],[source])
            src=s.get(project,'sources',source)
            add('source',source,dict(source=src,attribution=s.attribution(project,source)),inp['fingerprint'],[source])
            docs=[];task_ids=set(selection['task_ids']);sessions=set(selection.get('thread_ids',[]));attempts=set();version_ids=set()
            runs=c.execute('SELECT id FROM native_runs WHERE project_id=? AND input_id=? AND processor=? AND parsed_sha256=?',(project,inp['id'],PROCESSOR,attempt['result_sha256'])).fetchall()
            for run in runs:
                for d in n.run(project,run[0])['documents']:
                    docs.append(d);m=d['decision']['matches'];task_ids.update(m['tasks']);sessions.update(m['sessions']);attempts.update(m['attempts'])
                    add('native',d['id'],dict(locator=d['locator'],findings=d['findings'],decision=d['decision'],relation=d['relation'],
                        **({'suggestions':d['suggestions']} if protocol==PROTOCOL_V2 else {})),PROCESSOR,[source])
                    version_ids.add(d['version_id'])
                    add('conflicts',d['id'],n.requirements(project,document_id=d['id']),d['decision']['id'],[source])
            for task in sorted(task_ids):
                add('task',task,dict(record=s.get(project,'tasks',task),formal=formal_tasks.get(task),
                    derived=next((d for d in formal['derived']['tasks'] if d['task_id']==task),None)),str(p['revision']))
                for link in formal['confirmed_versions']:
                    if link['task_id']==task:version_ids.add(link['version_id'])
            duty_suggestions=[]
            if protocol==PROTOCOL_V2:
                from .threads import Threads
                thread_state=Threads(s).state(project)
                relevant_tasks=set(task_ids)
                sessions.update(r['session_id'] for r in thread_state['participation'] if r['task_id'] in relevant_tasks)
                sessions.update(r['session_id'] for r in thread_state['leads'] if r['task_id'] in relevant_tasks and r['session_id'])
                related_edges=[r for r in thread_state['successions'] if r['predecessor_id'] in sessions or r['successor_id'] in sessions]
                for edge in related_edges:sessions.update((edge['predecessor_id'],edge['successor_id']))
                relevant=dict(duties=[r for r in thread_state['duties'] if r['session_id'] in sessions],
                    suggestions=[r for r in thread_state['suggestions'] if r['session_id'] in sessions],
                    participation=[r for r in thread_state['participation'] if r['task_id'] in relevant_tasks],
                    leads=[r for r in thread_state['leads'] if r['task_id'] in relevant_tasks],successions=related_edges)
                duty_suggestions=relevant['suggestions']
                add('thread-state',project,relevant,str(p['revision']))
                # Formal facts retain their exact reviewed source chain. Include
                # minimal metadata and version fingerprints, not whole history.
                changes={r['change_id'] for rows in relevant.values() for r in rows}
                for duty in relevant['duties']:
                    if duty['suggestion_id']:
                        original_suggestion=s.get(project,'thread_duties',duty['suggestion_id'])
                        changes.add(original_suggestion['change_id'])
                for change in sorted(changes):
                    applied=s.get(project,'applied_changes',change)
                    effect=json.loads(applied['effect_json']);source_ids=effect.get('source_ids',[])
                    provenance=dict(operation=effect['operation'],target_id=effect['target_id'],source_ids=source_ids)
                    context=effect.get('native_context')
                    if context:
                        original=s.get(project,'native_documents',context['document_id'])
                        version=s.get(project,'artifact_versions',original['version_id'])
                        provenance.update(document_id=original['id'],version_id=version['id'],
                            content_sha256=version['content_sha256'],locator=json.loads(original['locator_json']),
                            decision_id=context['decision_id'])
                    add('thread-provenance',change,provenance,change,source_ids)
                    for sid in source_ids:
                        add('thread-source',sid,dict(source=s.get(project,'sources',sid),
                            attribution=s.attribution(project,sid)),s.get(project,'sources',sid)['fingerprint'],[sid])
            for kind,ids in (('sessions',sessions),('attempts',attempts)):
                for identity in sorted(ids):add(kind,identity,s.get(project,kind,identity))
            baseline=Changes(s).baseline(project)
            if baseline:
                add('baseline',baseline['version_id'],baseline,str(baseline['revision']))
                version_ids.add(baseline['version_id'])
            for vid in sorted(version_ids):
                v=s.get(project,'artifact_versions',vid)
                sources=[r[0] for r in c.execute('SELECT source_id FROM version_sources WHERE project_id=? AND version_id=?',(project,vid))]
                if any(d['version_id']==vid for d in docs):sources.append(source)
                add('version',vid,v['content'],v['content_sha256'],sources)
                add('version-metadata',vid,dict(artifact_id=v['artifact_id'],ordinal=v['ordinal'],relation=n.relation(project,vid)),v['content_sha256'],sources)
                for e in c.execute('SELECT * FROM evidence WHERE project_id=? AND version_id=? ORDER BY id',(project,vid)):
                    e=dict(e);add('evidence',e['id'],e,vid,[e['source_id']] if e['source_id'] else [])
            payload=canonical(wire(self.config.model,entries,protocol)).encode('utf-8')
            if len(payload)>MAX_REQUEST or len(entries)>200:raise ChangeError('model_context_limit')
            jobs.append(dict(item_id=item,input_id=inp['id'],entries=entries,payload=payload,
                sha256=raw_sha(payload),bytes=len(payload),docs=docs,tasks=sorted(task_ids),versions=sorted(version_ids),protocol=protocol,threads=sorted(sessions),duty_suggestions=duty_suggestions))
        if sum(j['bytes'] for j in jobs)>2*1024*1024:raise ChangeError('model_batch_context_limit')
        # All envelope material is explicit: instructions/schema/config plus item entries.
        manifest=dict(protocol=protocol,template=template,purpose=PURPOSE,project_id=project,
            import_batch_id=selection['import_batch_id'],base_revision=p['revision'],target=self.config.public(),
            policy=dict(system=system,schema=schema),selection=selection,items=states,
            not_included=['unselected inputs','unrelated task history','original binary bytes','adjacent files','external URLs'],
            calls=len(jobs),total_request_bytes=sum(j['bytes'] for j in jobs),
            budget=dict(per_request_bytes=MAX_REQUEST,response_bytes=256*1024,timeout_seconds=self.config.timeout,
                        retries=0,calls_per_item=1,cost='unverified; no monetary estimate'),
            jobs=[dict(item_id=j['item_id'],input_id=j['input_id'],request_sha256=j['sha256'],request_bytes=j['bytes'],
                entries=[{k:v for k,v in e.items() if k!='text'}|{'utf8_bytes':len(e['text'].encode('utf-8'))} for e in j['entries']]) for j in jobs])
        return manifest,jobs,guard

    def prepare(self,project,key,request):
        self._enabled()
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',key):raise ChangeError('idempotency_key_required')
        with unit_of_work(self.db,self.principal) as s:
            selection=self._select(s,project,request)
            old=s._connection.execute('SELECT * FROM model_batches WHERE project_id=? AND request_key=?',(project,key)).fetchone()
            if old:
                if json.loads(old['selection_json'])!=selection:raise ChangeError('idempotency_key_reused')
                identity=old['id']
            else:identity=None
        if identity:return self.get(project,identity)
        manifest,jobs,guard=self._gather(project,selection)
        with unit_of_work(self.db,self.principal,write=True) as s:
            if database_guard(s,project,selection)!=guard:raise ChangeError('model_context_changed')
            old=s._connection.execute('SELECT id,selection_json FROM model_batches WHERE project_id=? AND request_key=?',(project,key)).fetchone()
            if old:
                if json.loads(old['selection_json'])!=selection:raise ChangeError('idempotency_key_reused')
                identity=old['id']
            else:
                batch=s._insert(project,'model_batches',import_batch_id=selection['import_batch_id'],request_key=key,
                    selection_json=canonical(selection),manifest_json=canonical(manifest),fingerprint=digest(manifest),guard_sha256=guard)
                identity=batch['id']
                for job in jobs:s._insert(project,'model_jobs',batch_id=identity,item_id=job['item_id'],input_id=job['input_id'],request_sha256=job['sha256'])
                event(s,project,identity,'prepared')
        return self.get(project,identity)

    def get(self,project,identity):
        with unit_of_work(self.db,self.principal) as s:
            b=self._batch(s,project,identity);history=events(s,project,identity);d=decision(s,project,identity)
            jobs=[]
            for j in s._connection.execute('SELECT * FROM model_jobs WHERE project_id=? AND batch_id=? ORDER BY item_id',(project,identity)):
                j=dict(j);j['state']=job_state(s,project,j['id']);j['events']=[e for e in history if e['job_id']==j['id']]
                results=[dict(r) for r in s._connection.execute('SELECT * FROM model_results WHERE project_id=? AND job_id=?',(project,j['id']))]
                j['results']=results;jobs.append(j)
            manifest=json.loads(b['manifest_json'])
            stale=database_guard(s,project,json.loads(b['selection_json']))!=b['guard_sha256'] or manifest['target']!=self.config.public()
            states=[j['state'] for j in jobs]
            processing=('denied' if d=='denied' else 'unavailable' if not jobs else
                'completed' if all(v=='saved' for v in states) else 'unknown' if 'unknown' in states else
                'sending' if 'sending' in states else 'partial-failure' if any(v in ('failed','invalid') for v in states) else 'pending')
            return dict(id=identity,manifest=manifest,fingerprint=b['fingerprint'],decision=d,processing=processing,stale=stale,jobs=jobs,
                history=history,temporary_content='memory-only; no raw spool; no residual disk copies',
                recovery='Resume pending independent items only. Unknown/sending calls are never resent. Use request IDs for provider investigation; prepare a new explicit batch only after considering possible prior disclosure/cost.')

    def listing(self,project):
        with unit_of_work(self.db,self.principal) as s:
            s.project(project);ids=[r[0] for r in s._connection.execute('SELECT id FROM model_batches WHERE project_id=? ORDER BY created_at,id',(project,))]
        return [self.get(project,i) for i in ids]

    def preview(self,project,identity):
        with unit_of_work(self.db,self.principal) as s:b=self._batch(s,project,identity)
        manifest,jobs,guard=self._gather(project,json.loads(b['selection_json']))
        if guard!=b['guard_sha256'] or digest(manifest)!=b['fingerprint']:raise ChangeError('model_preview_stale_prepare_again')
        return dict(batch=self.get(project,identity),requests=[dict(item_id=j['item_id'],request_sha256=j['sha256'],body=j['payload'].decode('utf-8')) for j in jobs])

    def decide(self,project,identity,fingerprint,choice):
        if choice not in ('approved','denied'):raise ChangeError('model_invalid_decision')
        # Refusal never requires model configuration, available originals or disk reads.
        if choice=='approved':self.preview(project,identity)
        with unit_of_work(self.db,self.principal,write=True) as s:
            b=self._batch(s,project,identity)
            if b['fingerprint']!=fingerprint:raise ChangeError('model_manifest_mismatch')
            old=decision(s,project,identity)
            if old==choice:return None
            if old=='denied':raise ChangeError('model_batch_denied_prepare_again')
            if s._connection.execute("SELECT 1 FROM model_events WHERE project_id=? AND batch_id=? AND state='sending'",(project,identity)).fetchone():raise ChangeError('model_send_already_started')
            if choice=='approved':
                if old!='prepared' or database_guard(s,project,json.loads(b['selection_json']))!=b['guard_sha256']:raise ChangeError('model_context_changed')
                if json.loads(b['manifest_json'])['target']!=self.config.public():raise ChangeError('model_target_changed')
            event(s,project,identity,choice,metadata=dict(manifest_sha256=fingerprint,principal=self.principal.subject))
        return None

    def _validate(self,s,project,job,raw):
        if job.get('protocol')==PROTOCOL_V2:
            from .model_threads import validate_v2
            return validate_v2(self,s,project,job,raw)
        value=strict_json(raw,128*1024);exact(value,('protocol','candidates'))
        if value['protocol']!=PROTOCOL:raise ChangeError('model_unknown_protocol')
        cs=value['candidates']
        if not isinstance(cs,list) or len(cs)>MAX_CANDIDATES:raise ChangeError('model_candidate_limit')
        by_entry={e['id']:e for e in job['entries']};out=[];seen=set()
        for candidate in cs:
            exact(candidate,tuple(SCHEMA['properties']['candidates']['items']['properties']))
            op=candidate['operation'];task=candidate['task_id'];version=candidate['version_id']
            if op not in ('task.create','task.update','version.confirm'):raise ChangeError('model_operation_denied')
            if any(v is not None and not isinstance(v,str) for v in (task,version)):raise ChangeError('model_invalid_reference')
            if task is not None and task not in job['tasks']:raise ChangeError('model_task_outside_manifest')
            if version is not None and version not in job['versions']:raise ChangeError('model_version_outside_manifest')
            for field in ('title','goal','completion_conditions'):bounded_text(candidate[field],512 if field=='title' else 2048,empty=True)
            bounded_text(candidate['rationale'],1024)
            for field in ('risks','uncertainties'):
                vals=candidate[field]
                if not isinstance(vals,list) or len(vals)>10:raise ChangeError('model_invalid_risks')
                for v in vals:bounded_text(v,256)
            citations=candidate['citations']
            if not isinstance(citations,list) or not 1<=len(citations)<=10:raise ChangeError('model_citations_required')
            sources=set();support=False
            for cite in citations:
                exact(cite,('entry_id','sha256','start','end','quote'))
                if not isinstance(cite['entry_id'],str):raise ChangeError('model_invalid_citation')
                entry=by_entry.get(cite['entry_id'])
                if not entry or cite['sha256']!=entry['sha256']:raise ChangeError('model_citation_outside_manifest')
                start,end=cite['start'],cite['end'];quote=bounded_text(cite['quote'],512)
                if type(start) is not int or type(end) is not int or not 0<=start<end<=len(entry['text']) or entry['text'][start:end]!=quote:raise ChangeError('model_unsupported_citation')
                sources.update(entry['source_ids'])
                if (entry['kind']=='format' and entry['object_id']==job['input_id']) or entry['kind']=='native':support=True
                if entry['kind']=='version' and any(d['version_id']==entry['object_id'] for d in job['docs']):support=True
            if not support:raise ChangeError('model_current_input_evidence_required')
            native_conflicts=[]
            for d in job['docs']:
                native_conflicts.extend(Native(s).requirements(project,document_id=d['id'],target_id=task)['conflicts'])
            request=dict(operation=op,payload={},source_ids=sorted(sources),evidence_ids=[],risk='high',
                conflicts=sorted(set(candidate['risks']+candidate['uncertainties']+native_conflicts)),
                impact='Unverified model interpretation; independently review cited input, proposed fields and relationships. No acceptance, authority or verified test result.')
            if op=='task.create':
                if task is not None or version is not None or not candidate['title'].strip():raise ChangeError('model_invalid_create')
                request['payload']={k:candidate[k] for k in ('title','goal','completion_conditions')}
            elif op=='task.update':
                if task is None or version is not None or candidate['completion_conditions'] or not candidate['title'].strip():raise ChangeError('model_invalid_update')
                request.update(target_id=task,payload={k:candidate[k] for k in ('title','goal')})
            else:
                if task is None or version is None or any(candidate[k] for k in ('title','goal','completion_conditions')):raise ChangeError('model_invalid_confirm')
                doc=next((d for d in job['docs'] if d['version_id']==version and task in d['decision']['matches']['tasks'] and not d['decision']['matches']['pending']),None)
                if doc is None:raise ChangeError('model_native_relationship_required')
                if not any((by_entry[c['entry_id']]['kind']=='version' and by_entry[c['entry_id']]['object_id']==version) or
                           (by_entry[c['entry_id']]['kind']=='native' and by_entry[c['entry_id']]['object_id']==doc['id']) for c in citations):
                    raise ChangeError('model_exact_version_citation_required')
                request.update(target_id=task,target_version_id=version,native_context=dict(document_id=doc['id'],decision_id=doc['decision']['id'],relation_id=(doc['relation'] or {}).get('id')))
                request['source_ids']=[doc['locator']['source_id']]
            key=digest(core(request))
            if key in seen:raise ChangeError('model_duplicate_proposal')
            seen.add(key);out.append((request,candidate['rationale'],citations))
        return out

    def execute(self,project,identity):
        self._enabled()
        with unit_of_work(self.db,self.principal) as s:
            b=self._batch(s,project,identity)
            if decision(s,project,identity)!='approved':raise ChangeError('model_send_not_approved')
            pending=[dict(j) for j in s._connection.execute('SELECT * FROM model_jobs WHERE project_id=? AND batch_id=? ORDER BY item_id',(project,identity)) if job_state(s,project,j['id'])=='pending']
        # Replays of consumed calls only read their journal, even if sources change.
        if not pending:return self.get(project,identity)
        manifest,jobs,guard=self._gather(project,json.loads(b['selection_json']))
        if digest(manifest)!=b['fingerprint'] or guard!=b['guard_sha256']:raise ChangeError('model_preview_stale_prepare_again')
        by_item={j['item_id']:j for j in jobs}
        for row in pending:
            j=by_item[row['item_id']]
            with unit_of_work(self.db,self.principal,write=True) as s:
                self._batch(s,project,identity)
                if decision(s,project,identity)!='approved':raise ChangeError('model_send_not_approved')
                if job_state(s,project,row['id'])!='pending':continue
                if database_guard(s,project,json.loads(b['selection_json']))!=guard:raise ChangeError('model_context_changed')
                if j['sha256']!=row['request_sha256']:raise ChangeError('model_request_changed')
                event(s,project,identity,'sending',job=row['id'],metadata=dict(client_request_id=row['id'],request_sha256=j['sha256'],max_calls=1))
            # This is intentionally OUTSIDE every SQLite transaction.
            raw=None;provider_id=None;usage={}
            try:
                raw,provider_id,usage=ResponsesAdapter(self.config).send(j['payload'],row['id'])
                with unit_of_work(self.db,self.principal,write=True) as s:
                    if job_state(s,project,row['id'])!='sending':raise ChangeError('model_result_not_claimed')
                    if database_guard(s,project,json.loads(b['selection_json']))!=guard:raise ChangeError('model_context_changed_after_send')
                    proposed=self._validate(s,project,j,raw)
                    result=s._insert(project,'model_results',job_id=row['id'],response_sha256=raw_sha(raw),provider_request_id=provider_id,usage_json=canonical(usage))
                    candidate_ids=[]
                    for position,(request,rationale,citations) in enumerate(proposed):
                        request['base_revision']=manifest['base_revision']
                        proposal=s._insert(project,'model_proposals',result_id=result['id'],position=position,
                            core_sha256=digest(core(request)),request_json=canonical(request),rationale=rationale,citations_json=canonical(citations))
                        # Same semantic proposal at the same snapshot reuses its existing
                        # candidate; never duplicates a formal effect on another send.
                        existing=None;supersedes=None
                        for old in s.records(project,'candidate_specs'):
                            old_spec=json.loads(old['spec_json']);old_core=core(old_spec)
                            if old_spec['operation']=='task.create':old_core['target_id']=None
                            if digest(old_core)==proposal['core_sha256'] and old_spec['base_revision']==request['base_revision'] and old_spec.get('model_context'):
                                if ModelContext(s).batch_guard(project,old_spec['model_context'])!=guard:continue
                                current=s.candidate(project,old['candidate_id'])
                                if current['processing'] in ('superseded','applied'):continue
                                try:Changes(s).validate(project,current)
                                except ChangeError as error:
                                    if error.code in ('model_known_conflicts_changed','preconditions_changed'):supersedes=old['candidate_id']
                                    continue
                                # A model may add concerns but cannot remove a
                                # prior validated concern at the same snapshot.
                                if not set(request['conflicts'])<=set(old_spec['conflicts']):
                                    supersedes=old['candidate_id'];continue
                                existing=current;break
                        if supersedes and not existing:request['supersedes_id']=supersedes
                        candidate=existing or s.save_candidate(project,dict(request,model_context=dict(proposal_id=proposal['id'])))
                        candidate_ids.append(candidate['candidate_id'])
                    event(s,project,identity,'saved',job=row['id'],metadata=dict(result_id=result['id'],candidate_ids=candidate_ids,usage=usage))
            except ProviderFailure as error:
                with unit_of_work(self.db,self.principal,write=True) as s:
                    if job_state(s,project,row['id'])=='sending':event(s,project,identity,'unknown' if error.unknown else 'failed',error.code,job=row['id'])
            except ChangeError as error:
                with unit_of_work(self.db,self.principal,write=True) as s:
                    if job_state(s,project,row['id'])=='sending':event(s,project,identity,'invalid',error.code,job=row['id'],metadata=dict(provider_request_id=provider_id,usage=usage,response_sha256=raw_sha(raw) if raw is not None else None))
            # Other DB/process failures leave the durable sending claim. Recovery
            # marks it unknown and never repeats the HTTP call. Raw buffers die here.
        return self.get(project,identity)

    def recover(self,project,identity):
        with unit_of_work(self.db,self.principal,write=True) as s:
            self._batch(s,project,identity)
            rows=s._connection.execute('SELECT id FROM model_jobs WHERE project_id=? AND batch_id=?',(project,identity)).fetchall()
            for row in rows:
                if job_state(s,project,row[0])!='sending':continue
                sent=next(e for e in reversed(events(s,project,identity)) if e['job_id']==row[0] and e['state']=='sending')
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(sent['created_at'])).total_seconds()
                # A concurrent recovery cannot take over a live bounded request.
                if age<25:continue
                event(s,project,identity,'unknown','model_interrupted_no_automatic_resend',job=row[0])
        return self.get(project,identity)
