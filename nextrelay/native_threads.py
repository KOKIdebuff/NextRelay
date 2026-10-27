"""T20 explicit aliases and inspectable declarations; no natural-language inference."""
import json
from .changes import ChangeError, canonical, digest, exact


def compatible_matches(value):
    if not isinstance(value,dict):raise ChangeError('invalid_native_matches')
    m=dict(value)
    if 'threads' in m:
        if 'sessions' in m and m['sessions']!=m['threads']:raise ChangeError('thread_session_conflict')
        m['sessions']=m.pop('threads')
    if 'contributions' in m:
        pairs=[]
        if not isinstance(m['contributions'],list):raise ChangeError('invalid_native_contributions')
        for pair in m['contributions']:
            if not isinstance(pair,dict):raise ChangeError('invalid_native_contributions')
            pair=dict(pair)
            if 'thread_id' in pair:
                if 'session_id' in pair and pair['session_id']!=pair['thread_id']:raise ChangeError('thread_session_conflict')
                pair['session_id']=pair.pop('thread_id')
            pairs.append(pair)
        m['contributions']=pairs
    return m


def naming_conflict(s,project,f):
    old=f['declarations']['sessions'];new=f['declarations'].get('threads',[])
    if not old or not new:return False
    rows=s.records(project,'sessions')
    def identities(claims):
        return {next((r['id'] for r in rows if c['value']==r['id'] or
            (r['namespace'] and c['value']==r['namespace']+'::'+r['external_id'])),c['value']) for c in claims}
    return identities(old)!=identities(new)


def establish_identities(s,project,f):
    # Only explicitly namespaced identities may create base identity records.
    # They convey no duty, participation, permission or historical contribution.
    if naming_conflict(s,project,f):return
    for claim in f['declarations']['sessions']+f['declarations'].get('threads',[]):
        value=claim['value']
        if value.count('::')!=1:continue
        namespace,external_id=value.split('::')
        if not namespace.strip() or not external_id.strip():continue
        if not any(r['namespace']==namespace and r['external_id']==external_id for r in s.records(project,'sessions')):
            s.create_session(project,value,namespace=namespace,external_id=external_id)


LABELS={'main duty':'main','主职责':'main','auxiliary duty':'auxiliary','辅助职责':'auxiliary',
        'participation':'active','当前参与':'active','assignment':'description','分工':'description',
        'lead':'lead','主负责':'lead'}


def suggestions(n,project,d,decision):
    f=json.loads(d['findings_json']);m=json.loads(decision['matches_json'])
    claims={};locations=[];out=[]
    for fact in f['facts']:
        key=LABELS.get(fact['key'])
        if key:
            claims.setdefault(key,[]).append(fact['value']);locations.append(fact)
    if not claims:return out
    # Ambiguity is preserved in the document, never guessed as an assignment.
    uncertain=['Imported declaration; human review required']
    if m['pending'] or len(m['sessions'])!=1:uncertain.append('Thread identity unresolved or ambiguous')
    if any(len(v)>1 for v in claims.values()):uncertain.append('Repeated declaration requires correction')
    thread=m['sessions'][0] if len(m['sessions'])==1 and not m['pending'] else None
    task=m['tasks'][0] if len(m['tasks'])==1 and not m['pending'] else None
    basis='Imported declaration from document '+d['id']
    def add(op,target,payload,problem=None):
        errors=uncertain+([problem] if problem else [])
        ready=target is not None and len(errors)==1
        spec=dict(operation=op,target_id=target,payload=payload)
        identity=digest(dict(document_id=d['id'],decision_id=decision['id'],spec=spec,locations=locations))
        out.append(dict(id=identity,**spec,actionable=ready,uncertainties=errors,
            document_id=d['id'],version_id=d['version_id'],locator=json.loads(d['locator_json']),
            citations=locations,identity_basis=m['basis'],decision_id=decision['id']))
    if 'main' in claims:
        auxiliary=[v.strip() for v in claims.get('auxiliary',[''])[0].replace('；',';').split(';') if v.strip()]
        add('thread.duty.suggest',thread,dict(main=claims['main'][0],auxiliary=auxiliary,basis=basis))
    if 'active' in claims:
        value=claims['active'][0].casefold()
        active=True if value in ('active','true','参与') else False if value in ('inactive','false','退出') else None
        add('task.participation.set',task,dict(thread_id=thread,active=active,
            description=claims.get('description',[''])[0],basis=basis),None if active is not None and thread else 'Explicit active/inactive and one Thread required')
    if 'lead' in claims:
        value=claims['lead'][0].casefold()
        if value in ('true','false'):
            add('task.lead.set',task,dict(thread_id=thread if value=='true' else None,basis=basis),None if thread else 'One Thread required')
        else:add('task.lead.set',None,dict(thread_id=None,basis=basis),'Explicit true/false required')
    return out


def actionable(n,project,d):
    from .threads import Threads
    from .changes import Changes
    state=Threads(n.s).state(project);out=[]
    for suggestion in d['suggestions']:
        if not suggestion['actionable']:continue
        op,target,p=suggestion['operation'],suggestion['target_id'],suggestion['payload']
        if op=='thread.duty.suggest' and any(r['session_id']==target and r['main']==p['main'] and
            json.loads(r['auxiliary_json'])==p['auxiliary'] for r in state['suggestions']+state['duties']):continue
        spec=dict(operation=op,target_id=target,payload=p)
        try:Threads(n.s).preconditions(project,dict(spec,target_version_id=None))
        except ChangeError as error:
            if error.code in ('no_business_change','not_current_participant'):continue
            raise
        out.append(dict(spec,_context=dict(document_id=d['id'],decision_id=d['decision']['id'],
            relation_id=(d['relation'] or {}).get('id'),suggestion_id=suggestion['id'])))
    return out



def duty_confirmation_context(s,project,suggestion_id):
    """Carry a sourced suggested fact through its independent confirmation.

    A formal suggestion is retained, but its old approval is not authority to
    ignore later source corrections or newly imported relevant risks.
    """
    from .native import Native
    from .model import ModelContext
    suggestion=s.get(project,'thread_duties',suggestion_id)
    applied=s.get(project,'applied_changes',suggestion['change_id'])
    effect=json.loads(applied['effect_json'])
    sources=set(effect['source_ids']);conflicts=set(effect['conflicts']);snapshot={}
    n=Native(s)
    # Current Thread safety is independent of how the original suggestion was
    # produced, including model batches with no native entries at all.
    safety=n.requirements(project,thread_id=suggestion['session_id'],
        duty=dict(main=suggestion['main'],auxiliary=json.loads(suggestion['auxiliary_json'])))
    conflicts.update(safety['conflicts'])
    sources.update(r['source_id'] for r in safety.get('thread_risk_dependencies',[]) if r['flags'])
    if safety['conflicts']:snapshot['thread_safety']=safety
    if effect.get('native_context'):
        context=n.context(project,effect['native_context'])
        snapshot['native']=context
        conflicts.update(context['safety']['conflicts'])
        sources.update(r['source_id'] for r in context['safety'].get('thread_risk_dependencies',[]) if r['flags'])
    if effect.get('model_context'):
        model=ModelContext(s);proposal=model.proposal(project,effect['model_context'])
        conflicts.update(model.minimum_conflicts(project,effect['model_context']))
        result=s.get(project,'model_results',proposal['result_id']);job=s.get(project,'model_jobs',result['job_id'])
        batch=s.get(project,'model_batches',job['batch_id']);manifest=json.loads(batch['manifest_json'])
        native_entries=[e for j in manifest['jobs'] for e in j['entries'] if e['kind']=='native' and set(e['source_ids'])&sources]
        refs=[]
        for entry in native_entries:
            doc=n.document(project,entry['object_id'])
            body=dict(locator=doc['locator'],findings=doc['findings'],decision=doc['decision'],relation=doc['relation'])
            if manifest['protocol']=='nextrelay.model/2':body['suggestions']=doc['suggestions']
            if digest(body)!=entry['sha256']:raise ChangeError('duty_suggestion_source_changed')
            safety=n.requirements(project,document_id=doc['id']);conflicts.update(safety['conflicts'])
            sources.update(r['source_id'] for r in safety.get('thread_risk_dependencies',[]) if r['flags'])
            refs.append(dict(document_id=doc['id'],sha256=entry['sha256'],safety=safety))
        # Later extraction/correction of the model's original source is also
        # relevant, even when that source had no native entry at send time.
        source_decisions=[]
        original_sources=set(effect['source_ids']);source_threads=set()
        for row in s.records(project,'native_documents'):
            locator=json.loads(row['locator_json'])
            if locator['source_id'] not in original_sources:continue
            doc=n.document(project,row['id']);matched=doc['decision']['matches']['sessions']
            source_threads.update(matched)
            source_decisions.append(dict(document_id=doc['id'],decision_id=doc['decision']['id'],
                relation_id=(doc['relation'] or {}).get('id'),version_id=doc['version_id']))
        if source_threads and suggestion['session_id'] not in source_threads:
            raise ChangeError('duty_suggestion_source_changed')
        source_decisions.sort(key=lambda d:d['document_id'])
        snapshot['model']=dict(proposal_id=proposal['id'],native_dependencies=refs,source_decisions=source_decisions)
    if not sources and not conflicts and not snapshot and effect['risk']=='ordinary':return None
    source_ids=sorted(sources)
    if len(source_ids)>100:raise ChangeError('native_conflict_limit')
    snapshot.update(source_ids=source_ids,sources=[s.get(project,'sources',v) for v in source_ids],
        attributions=[s.attribution(project,v) for v in source_ids],conflicts=sorted(conflicts))
    return dict(source_ids=source_ids,conflicts=sorted(conflicts),risk='conflict' if conflicts or effect['risk']=='conflict' else
        'high' if effect.get('model_context') or effect['risk']=='high' else 'ordinary',snapshot=snapshot)
