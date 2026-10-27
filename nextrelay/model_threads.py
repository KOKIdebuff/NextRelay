"""Version two typed candidates, reusing version one's bounded citation validation."""
import json
from .changes import ChangeError, canonical, exact, digest
from .model_protocol import (PROTOCOL,PROTOCOL_V2,SCHEMA_V2,THREAD_OPERATIONS,MAX_CANDIDATES,strict_json)
from .threads import Threads


def validate_v2(service,s,project,job,raw):
    value=strict_json(raw,128*1024);exact(value,('protocol','candidates'))
    if value['protocol']!=PROTOCOL_V2:raise ChangeError('model_unknown_protocol')
    candidates=value['candidates']
    if not isinstance(candidates,list) or len(candidates)>MAX_CANDIDATES:raise ChangeError('model_candidate_limit')
    out=[];seen=set()
    for candidate in candidates:
        exact(candidate,tuple(SCHEMA_V2['properties']['candidates']['items']['properties']))
        op,target,version,payload=(candidate[k] for k in ('operation','target_id','target_version_id','payload'))
        if not isinstance(op,str) or op not in ('task.create','task.update','version.confirm',*THREAD_OPERATIONS):raise ChangeError('model_operation_denied')
        if any(v is not None and not isinstance(v,str) for v in (target,version)):raise ChangeError('model_invalid_reference')
        # Reuse the v1 citation/risk/text validator, without weakening its schema.
        # The temporary task.create is never stored; its only role is validating
        # exact supplied offsets, bounded strings and current-input support.
        legacy={k:candidate[k] for k in ('rationale','citations','risks','uncertainties')}
        if op in THREAD_OPERATIONS:
            legacy.update(operation='task.create',task_id=None,version_id=None,title='citation validation',goal='',completion_conditions='')
        else:
            if op=='task.create':exact(payload,('title','goal','completion_conditions'))
            elif op=='task.update':exact(payload,('title','goal'))
            else:exact(payload,())
            legacy.update(operation=op,task_id=target,version_id=version,
                title=payload.get('title',''),goal=payload.get('goal',''),completion_conditions=payload.get('completion_conditions',''))
        validated=service._validate(s,project,dict(job,protocol=PROTOCOL),canonical(dict(protocol=PROTOCOL,candidates=[legacy])).encode('utf-8'))[0]
        request,rationale,citations=validated
        if op in THREAD_OPERATIONS:
            if version is not None:raise ChangeError('unexpected_thread_input')
            payload=Threads(s).normalize(op,payload)
            if op.startswith('thread.'):
                if target not in job['threads']:raise ChangeError('model_thread_outside_manifest')
                s.get(project,'sessions',target)
                if op=='thread.duty.confirm' and not any(r['id']==payload['suggestion_id'] and r['session_id']==target for r in job['duty_suggestions']):raise ChangeError('model_suggestion_outside_manifest')
            else:
                if target not in job['tasks']:raise ChangeError('model_task_outside_manifest')
                s.get(project,'tasks',target)
                if payload['thread_id'] is not None and payload['thread_id'] not in job['threads']:raise ChangeError('model_thread_outside_manifest')
            request.update(operation=op,target_id=target,payload=payload)
            if op=='thread.duty.confirm':
                from .native_threads import duty_confirmation_context
                lineage=duty_confirmation_context(s,project,payload['suggestion_id'])
                if lineage:
                    request['source_ids']=sorted(set(request['source_ids']+lineage['source_ids']))
                    request['conflicts']=sorted(set(request['conflicts']+lineage['conflicts']))
            if op=='thread.duty.suggest':
                state=Threads(s).state(project)
                if any(r['session_id']==target and r['main']==payload['main'] and json.loads(r['auxiliary_json'])==payload['auxiliary'] for r in state['duties']+state['suggestions']):raise ChangeError('no_business_change')
            spec=dict(request,target_version_id=None)
            Threads(s).preconditions(project,spec)
            # Check each proposed effect in the actual batch at commit too.
            # No implicit participation or reassignment is ever appended.
        key=digest({k:request.get(k) for k in ('operation','target_id','target_version_id','payload')})
        if key in seen:raise ChangeError('model_duplicate_proposal')
        seen.add(key);out.append((request,rationale,citations))
    Threads(s).validate_batch(project,[dict(r,target_version_id=r.get('target_version_id'),target_id=r.get('target_id')) for r,_,_ in out])
    return out
