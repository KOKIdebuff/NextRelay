"""Persistent candidate/review/commit protocol. No external IO or model authority."""
import hashlib
import json
from uuid import uuid4



class ChangeError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def exact(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ChangeError('invalid_fields')


def integer(value):
    if type(value) is not int or value < 0:
        raise ChangeError('invalid_revision')
    return value


def content(value, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > 100000:
        raise ChangeError('invalid_text')
    return value


def selection(value, keys):
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise ChangeError('invalid_selection')
    seen = set()
    for item in value:
        exact(item, keys)
        for key in keys:
            content(item[key])
        if item['candidate_id'] in seen:
            raise ChangeError('duplicate_candidate')
        seen.add(item['candidate_id'])
    return sorted(value, key=lambda item: item['candidate_id'])


class Changes:
    def __init__(self, store):
        self.s = store
        self.c = store._connection

    def rows(self, project, table):
        return self.s.records(project, table)

    def latest_task(self, project, target):
        self.s._get(project, 'tasks', target)
        from .reversals import Reversals
        row = next((r for r in Reversals(self.s).tasks(project) if r['task_id'] == target), None)
        if row is None:
            raise ChangeError('task_not_formal')
        return dict(row)

    def baseline(self, project):
        from .reversals import Reversals
        row = max(Reversals(self.s).active_rows(project, 'baseline_history'), key=lambda r: r['revision'], default=None)
        return dict(row) if row else None

    def active(self, project, candidate):
        obj = self.s._get(project, 'candidate_changes', candidate)
        if self.c.execute('SELECT 1 FROM candidate_supersessions WHERE project_id=? AND old_candidate_id=?', (project,candidate)).fetchone():
            raise ChangeError('candidate_superseded')
        if self.c.execute('SELECT 1 FROM applied_changes WHERE project_id=? AND candidate_id=?', (project,candidate)).fetchone():
            raise ChangeError('candidate_already_applied')
        return obj

    def spec(self, project, candidate):
        self.s._get(project, 'candidate_changes', candidate)
        row = self.c.execute('SELECT * FROM candidate_specs WHERE project_id=? AND candidate_id=?', (project,candidate)).fetchone()
        if row is None:
            raise ChangeError('reserved_candidate_not_supported')
        result = dict(row)
        result['spec'] = json.loads(result['spec_json'])
        # Processing status is derived from durable records, never an input phase flag.
        applied = self.c.execute('SELECT id FROM applied_changes WHERE project_id=? AND candidate_id=?',(project,candidate)).fetchone()
        superseded = self.c.execute('SELECT id FROM candidate_supersessions WHERE project_id=? AND old_candidate_id=?',(project,candidate)).fetchone()
        review = self.c.execute('SELECT id,decision FROM change_reviews WHERE project_id=? AND candidate_id=? ORDER BY sequence DESC LIMIT 1',(project,candidate)).fetchone()
        result['processing'] = 'applied' if applied else ('superseded' if superseded else (review['decision'] if review else 'pending'))
        result['latest_review_id'] = review['id'] if review else None
        return result

    def preconditions(self, project, spec):
        op, target, version = spec['operation'], spec['target_id'], spec['target_version_id']
        result = {'sources':[], 'evidence':[]}
        if spec.get('model_context'):
            from .model import ModelContext
            result['model'] = ModelContext(self.s).check(project,spec)
        if spec.get('native_context'):
            from .native import Native
            native=Native(self.s)
            result['native'] = native.context(project,spec['native_context'])
            doc=native.document(project,spec['native_context']['document_id'])
            if spec['source_ids']!=[doc['locator']['source_id']]:
                raise ChangeError('native_source_mismatch')
            if op=='version.confirm' and (version!=doc['version_id'] or target not in doc['decision']['matches']['tasks'] or doc['decision']['matches']['pending']):
                raise ChangeError('native_target_mismatch')
            if op in ('thread.duty.suggest','task.participation.set','task.lead.set'):
                suggestion=result['native'].get('suggestion')
                if not suggestion or not suggestion['actionable'] or any(spec[k]!=suggestion[k] for k in ('operation','target_id','payload')):raise ChangeError('native_suggestion_mismatch')
            if op=='task.create':
                import re
                f=doc['findings']
                titles=[v['value'] for v in f['declarations']['tasks']]
                titles.append(re.sub(r'^(?:task|任务)\s+','',doc['title'],flags=re.I))
                if spec['payload']['title'] not in titles or spec['payload']['goal']!=f['goal'] or spec['payload']['completion_conditions']!=f['completion_conditions']:
                    raise ChangeError('native_target_mismatch')
        if op=='version.confirm':
            from .native import Native
            safety=Native(self.s).requirements(project,version_id=version,target_id=target)
            if safety['conflicts']:result['native_safety']=safety
        if op == 'task.create':
            if self.c.execute('SELECT 1 FROM tasks WHERE project_id=? AND id=?', (project,target)).fetchone():
                raise ChangeError('target_exists')
            # Exact current content equality is a duplicate creation, not similarity matching.
            for task in self.state(project)['tasks']:
                if all(task[k] == v for k,v in spec['payload'].items()):
                    raise ChangeError('duplicate_formal_task')
        elif op in ('task.update','version.confirm'):
            result['task'] = self.latest_task(project,target)
            result['task_record'] = self.s._get(project,'tasks',target)
            if op == 'task.update' and all(result['task'][k] == v for k,v in spec['payload'].items()):
                raise ChangeError('no_business_change')
        elif op == 'baseline.set':
            self.s._get(project,'artifacts',target)
            result['baseline'] = self.baseline(project)
        elif op.startswith('thread.') or op in ('task.participation.set','task.lead.set'):
            from .threads import Threads
            result['thread'] = Threads(self.s).preconditions(project,spec)
        elif op == 'change.revoke':
            from .reversals import Reversals
            result['reversal'] = Reversals(self.s).validate(project,spec)
        else:
            from .lifecycle import Lifecycle
            result['t05'] = Lifecycle(self.s).preconditions(project,spec)
        if version is not None:
            result['version'] = self.s._get(project,'artifact_versions',version)
            if op == 'baseline.set' and result['version']['artifact_id'] != target:
                raise ChangeError('wrong_artifact_version')
            result['version_sources'] = [dict(r) for r in self.c.execute(
                'SELECT * FROM version_sources WHERE project_id=? AND version_id=? ORDER BY source_id',(project,version))]
        if op == 'version.confirm':
            from .reversals import Reversals
            if any(r['task_id']==target and r['version_id']==version for r in Reversals(self.s).active_rows(project,'confirmed_version_links')):
                raise ChangeError('version_already_confirmed')
        if op == 'baseline.set' and result['baseline'] and result['baseline']['version_id'] == version:
            raise ChangeError('baseline_already_current')
        for source in spec['source_ids']:
            result['sources'].append(self.s._get(project,'sources',source))
            result.setdefault('attributions',[]).append(self.s.attribution(project,source))
        for evidence in spec['evidence_ids']:
            e = self.s._get(project,'evidence',evidence)
            expected_task = target if op not in ('baseline.set','task.create') else None
            if version is None or e['version_id'] != version or e['task_id'] != expected_task:
                raise ChangeError('inapplicable_evidence')
            if expected_task and e['conditions_version'] != self.s._get(project,'tasks',target)['conditions_version']:
                raise ChangeError('stale_evidence_conditions')
            result['evidence'].append(e)
        return result

    def save(self, project, request):
        p = self.s._project(project)
        exact(request, ('base_revision','operation','payload'),
              ('target_id','target_version_id','source_ids','evidence_ids','risk','conflicts','impact','supersedes_id','native_context','model_context'))
        base = integer(request['base_revision'])
        if p['revision'] != base:
            raise ChangeError('revision_conflict')
        op = request['operation']
        from .schema_t05 import OPERATIONS as T05_OPERATIONS
        from .schema_t19 import OPERATIONS as T19_OPERATIONS
        OPERATIONS = T05_OPERATIONS + T19_OPERATIONS
        if op not in OPERATIONS + ('change.revoke',):
            raise ChangeError('unsupported_operation')
        payload = request['payload']
        if op == 'task.create':
            exact(payload, ('title',), ('goal','completion_conditions'))
            payload = dict(title=content(payload['title']), goal=content(payload.get('goal',''),empty=True),
                           completion_conditions=content(payload.get('completion_conditions',''),empty=True))
            if 'target_id' in request or 'target_version_id' in request:
                raise ChangeError('unexpected_target')
            target = str(uuid4())
        elif op == 'task.update':
            exact(payload, (), ('title','goal'))
            if not payload or 'target_version_id' in request:
                raise ChangeError('unsupported_task_update')
            payload = {k:content(v,empty=k=='goal') for k,v in payload.items()}
            target = content(request.get('target_id'))
        elif op in ('version.confirm','baseline.set'):
            exact(payload, ())
            target = content(request.get('target_id'))
            content(request.get('target_version_id'))
        elif op in T19_OPERATIONS:
            from .threads import Threads
            payload = Threads(self.s).normalize(op,payload)
            target = content(request.get('target_id'))
            if 'target_version_id' in request or request.get('evidence_ids'):
                raise ChangeError('unexpected_thread_input')
        elif op == 'change.revoke':
            exact(payload, ('preview_id',))
            content(payload['preview_id'])
            target = content(request.get('target_id'))
            if 'target_version_id' in request or request.get('source_ids') or request.get('evidence_ids'):
                raise ChangeError('unexpected_reversal_input')
        else:
            from .lifecycle import Lifecycle
            payload = Lifecycle(self.s).normalize(op,payload)
            target = content(request.get('target_id'))
            if op in ('task.submit','check.authorize','acceptance.human','acceptance.auto'):
                content(request.get('target_version_id'))
        version = request.get('target_version_id')
        source_ids, evidence_ids = [], []
        for key, dest in (('source_ids',source_ids),('evidence_ids',evidence_ids)):
            values = request.get(key,[])
            if not isinstance(values,list) or len(values)>100 or any(not isinstance(v,str) for v in values) or len(set(values)) != len(values):
                raise ChangeError('invalid_references')
            dest.extend(sorted(values))
        risk = request.get('risk','ordinary')
        if risk not in ('ordinary','high','conflict'):
            raise ChangeError('invalid_risk')
        conflicts = request.get('conflicts',[])
        if not isinstance(conflicts,list) or len(conflicts)>100:
            raise ChangeError('invalid_conflicts')
        conflicts = [content(v) for v in conflicts]
        risk = 'conflict' if conflicts or risk=='conflict' else ('high' if op in ('baseline.set','check.authorize','acceptance.human','acceptance.auto','recheck.resolve','change.revoke') else risk)
        if op=='thread.duty.confirm':
            from .native_threads import duty_confirmation_context
            lineage=duty_confirmation_context(self.s,project,payload['suggestion_id'])
            if lineage:
                source_ids=sorted(set(source_ids+lineage['source_ids']))
                conflicts=sorted(set(conflicts+lineage['conflicts']))
                if len(source_ids)>100 or len(conflicts)>100:raise ChangeError('native_conflict_limit')
                risk='conflict' if conflicts or risk=='conflict' or lineage['risk']=='conflict' else 'high' if risk=='high' or lineage['risk']=='high' else 'ordinary'
        impact = content(request.get('impact',''),empty=True)
        if not impact.strip():
            impact = {
                'task.create': 'Create one formal todo task; no acceptance or dependency release.',
                'task.update': 'Append a formal title/goal snapshot and a pending recheck; preserve history.',
                'version.confirm': 'Confirm this exact task/version relation; no acceptance or authority inheritance.',
                'baseline.set': 'Switch the single requirements baseline to this exact version and record a pending recheck; readiness is not evaluated.',
                'thread.duty.set': 'Assign this Thread duty version; preserve historical contributions and task acceptance.',
                'thread.duty.suggest': 'Record an explicit pending duty suggestion; keep confirmed duties unchanged.',
                'thread.duty.confirm': 'Confirm this exact explicit duty suggestion; grant no authentication or acceptance authority.',
                'task.participation.set': 'Assign current participation independently of historical contributions; preserve task lifecycle and acceptance.',
                'task.lead.set': 'Set or clear the optional lead among current participants; preserve task lifecycle and acceptance.',
                'thread.succession.set': 'Correct this Thread succession relation; retain both identities and all task assignments and history.',
            }.get(op,'Apply this exact T05 operation; retain lifecycle, evidence and authorization history.')
        spec = dict(operation=op,target_id=target,target_version_id=version,payload=payload,
                    base_revision=base,source_ids=source_ids,evidence_ids=evidence_ids,
                    risk=risk,conflicts=conflicts,impact=impact)
        if 'native_context' in request:
            if op not in ('task.create','version.confirm','thread.duty.suggest','task.participation.set','task.lead.set'):
                raise ChangeError('unsupported_native_operation')
            spec['native_context'] = request['native_context']
        if op=='version.confirm' or spec.get('native_context'):
            from .native import Native
            required=Native(self.s).requirements(project,
                document_id=spec.get('native_context',{}).get('document_id'),
                version_id=version if op=='version.confirm' else None,
                target_id=target if op=='version.confirm' else None)
            spec['conflicts']=sorted(set(conflicts+required['conflicts']))
            if len(spec['conflicts'])>100:raise ChangeError('native_conflict_limit')
            if spec['conflicts']:spec['risk']='conflict'
            risk=spec['risk']
        from .model import ModelContext
        model=ModelContext(self.s)
        if 'model_context' in request:
            if op not in ('task.create','task.update','version.confirm','thread.duty.suggest','thread.duty.confirm','task.participation.set','task.lead.set'):
                raise ChangeError('unsupported_model_operation')
            spec['model_context']=request['model_context']
            spec['conflicts']=sorted(set(spec['conflicts']+model.minimum_conflicts(project,spec['model_context'])))
            model.check(project,spec)
            spec['risk']='conflict' if spec['conflicts'] else 'high'
            risk=spec['risk']
        elif model.matching(project,spec):
            raise ChangeError('model_context_required')
        spec['preconditions'] = self.preconditions(project,spec)
        supersedes = request.get('supersedes_id')
        if supersedes is not None:
            self.active(project,supersedes)
        shell = self.s._insert(project,'candidate_changes',base_revision=base,
                               task_id=target if op in ('task.update','version.confirm') else None,
                               version_id=version,source_id=source_ids[0] if source_ids else None)
        entry = self.s._insert(project,'candidate_specs',candidate_id=shell['id'],operation=op,
                               target_id=target,target_version_id=version,spec_json=canonical(spec),fingerprint=digest(spec),risk=risk)
        if supersedes is not None:
            self.s._insert(project,'candidate_supersessions',old_candidate_id=supersedes,new_candidate_id=shell['id'])
        return self.spec(project,entry['candidate_id'])

    def authorization(self, candidate):
        spec = candidate['spec']
        return dict(candidate_id=candidate['candidate_id'],fingerprint=candidate['fingerprint'],
                    target_id=spec['target_id'],target_version_id=spec['target_version_id'],
                    base_revision=spec['base_revision'],preconditions_sha256=digest(spec['preconditions']))

    def validate(self, project, candidate):
        self.active(project,candidate['candidate_id'])
        spec = candidate['spec']
        if self.s._project(project)['revision'] != spec['base_revision']:
            raise ChangeError('revision_conflict')
        if digest(spec) != candidate['fingerprint'] or self.preconditions(project,spec) != spec['preconditions']:
            raise ChangeError('preconditions_changed')

    def review(self, project, request):
        self.s._project(project)
        exact(request, ('selection','decision','mode','basis','input_origin'), ('authorization',))
        selected = selection(request['selection'],('candidate_id','fingerprint'))
        decision,mode = request['decision'],request['mode']
        if decision not in ('approve','reject','defer') or mode not in ('ordinary','explicit'):
            raise ChangeError('invalid_review')
        if request['input_origin'] not in ('local-user','synthetic-test'):
            raise ChangeError('invalid_review_origin')
        basis = content(request['basis'])
        if mode == 'explicit' and len(selected) != 1:
            raise ChangeError('explicit_review_is_single')
        results = []
        for item in selected:
            candidate = self.spec(project,item['candidate_id'])
            self.active(project,item['candidate_id'])
            if candidate['fingerprint'] != item['fingerprint']:
                raise ChangeError('candidate_content_mismatch')
            if decision == 'approve':
                if candidate['operation']=='acceptance.auto':
                    raise ChangeError('use_pre_authorized_acceptance_service')
                self.validate(project,candidate)
                if candidate['risk'] != 'ordinary' and mode != 'explicit':
                    raise ChangeError('explicit_authorization_required')
                if mode == 'explicit' and request.get('authorization') != self.authorization(candidate):
                    raise ChangeError('authorization_mismatch')
            elif 'authorization' in request:
                raise ChangeError('unexpected_authorization')
            if mode == 'ordinary' and 'authorization' in request:
                raise ChangeError('unexpected_authorization')
            results.append(self.s._insert(project,'change_reviews',candidate_id=item['candidate_id'],
                fingerprint=item['fingerprint'],decision=decision,mode=mode,basis=basis,
                sequence=self.c.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM change_reviews WHERE project_id=? AND candidate_id=?',(project,item['candidate_id'])).fetchone()[0],
                input_origin=request['input_origin'],authorization_json=canonical(request.get('authorization',{}))))
        return results

    def result(self, project, key):
        self.s._project(project)  # Ownership before looking up ANY idempotency result.
        row = self.c.execute("SELECT * FROM change_commits WHERE project_id=? AND action='commit-candidates' AND request_key=?", (project,content(key))).fetchone()
        return dict(row) if row else None

    def commit(self, project, request):
        self.s._project(project)
        exact(request, ('request_key','base_revision','selection'))
        key = content(request['request_key'])
        base = integer(request['base_revision'])
        selected = selection(request['selection'],('candidate_id','review_id'))
        normalized = dict(action='commit-candidates',project_id=project,base_revision=base,selection=selected)
        fingerprint = digest(normalized)
        prior = self.result(project,key)
        if prior:
            if prior['request_fingerprint'] != fingerprint:
                raise ChangeError('idempotency_key_reused')
            return json.loads(prior['result_json'])
        if self.s._project(project)['revision'] != base:
            raise ChangeError('revision_conflict')
        candidates = []
        targets = set()
        creations = set()
        for item in selected:
            candidate = self.spec(project,item['candidate_id'])
            self.validate(project,candidate)
            review = self.s._get(project,'change_reviews',item['review_id'])
            latest = self.c.execute('SELECT id FROM change_reviews WHERE project_id=? AND candidate_id=? ORDER BY sequence DESC LIMIT 1',
                                    (project,item['candidate_id'])).fetchone()
            if review['candidate_id'] != item['candidate_id'] or review['decision'] != 'approve' or latest['id'] != review['id'] or review['fingerprint'] != candidate['fingerprint']:
                raise ChangeError('matching_approval_required')
            if candidate['risk'] != 'ordinary' and (review['mode'] != 'explicit' or json.loads(review['authorization_json']) != self.authorization(candidate)):
                raise ChangeError('explicit_authorization_required')
            spec = candidate['spec']
            if spec['operation'] == 'task.create':
                payload_hash = digest(spec['payload'])
                if payload_hash in creations:
                    raise ChangeError('duplicate_formal_task')
                creations.add(payload_hash)
            from .threads import effect_key
            target_key = effect_key(spec)
            if target_key in targets:
                raise ChangeError('overlapping_effects')
            targets.add(target_key)
            candidates.append((candidate,review))
        if any(c['risk']!='ordinary' for c,r in candidates) and len(candidates)!=1:
            raise ChangeError('explicit_commit_is_single')
        from .threads import Threads
        threads = Threads(self.s)
        if threads.available():
            threads.validate_batch(project,[c['spec'] for c,r in candidates])
        revision = base+1
        # Result identities are allocated once, then stored in the SAME transaction as effects.
        planned = [(c,r,str(uuid4()),str(uuid4())) for c,r in candidates]
        result = dict(project_id=project,base_revision=base,revision=revision,
                      changes=[dict(candidate_id=c['candidate_id'],effective_change_id=eid,change_id=aid,
                                    operation=c['operation'],target_id=c['target_id'],target_version_id=c['target_version_id'])
                               for c,r,eid,aid in planned])
        commit = self.s._insert(project,'change_commits',action='commit-candidates',request_key=key,
            request_fingerprint=fingerprint,request_json=canonical(normalized),result_json=canonical(result),
            base_revision=base,revision=revision)
        for candidate,review,eid,aid in sorted(planned,key=lambda p:threads.apply_order(p[0]['spec'])):
            self.insert_fixed(project,'effective_changes',eid,dict(candidate_id=candidate['candidate_id']))
            self.insert_fixed(project,'applied_changes',aid,dict(effective_change_id=eid,candidate_id=candidate['candidate_id'],
                review_id=review['id'],commit_id=commit['id'],effect_json=canonical(candidate['spec'])))
            self.apply(project,candidate['spec'],revision,aid,review)
        changed = self.c.execute('UPDATE projects SET revision=? WHERE id=? AND revision=?', (revision,project,base)).rowcount
        if changed != 1:
            raise ChangeError('revision_conflict')
        from .lifecycle import Lifecycle
        Lifecycle(self.s).sync(project,revision)
        return result

    def insert_fixed(self, project, table, identity, values):
        self.s._projection_cache.clear()
        # Fixed table/columns from trusted code only; caller data are SQL parameters.
        from datetime import datetime, timezone
        values = dict(id=identity,project_id=project,created_at=datetime.now(timezone.utc).isoformat(),created_by=self.s._principal.subject,**values)
        if table not in ('tasks','effective_changes','applied_changes'):
            raise ChangeError('invalid_internal_table')
        statements = {
            'tasks': ('INSERT INTO tasks(id,project_id,created_at,created_by,title,goal,completion_conditions) VALUES (?,?,?,?,?,?,?)',
                      ('id','project_id','created_at','created_by','title','goal','completion_conditions')),
            'effective_changes': ('INSERT INTO effective_changes(id,project_id,created_at,created_by,candidate_id) VALUES (?,?,?,?,?)',
                                  ('id','project_id','created_at','created_by','candidate_id')),
            'applied_changes': ('INSERT INTO applied_changes(id,project_id,created_at,created_by,effective_change_id,candidate_id,review_id,commit_id,effect_json) VALUES (?,?,?,?,?,?,?,?,?)',
                                ('id','project_id','created_at','created_by','effective_change_id','candidate_id','review_id','commit_id','effect_json')),
        }
        sql,columns = statements[table]
        if values.keys() != set(columns):
            raise ChangeError('invalid_internal_fields')
        self.c.execute(sql,tuple(values[k] for k in columns))

    def apply(self, project, spec, revision, change_id, review=None):
        op,target,version = spec['operation'],spec['target_id'],spec['target_version_id']
        if op == 'task.create':
            values = spec['payload']
            self.insert_fixed(project,'tasks',target,values)
            self.s._insert(project,'formal_task_states',task_id=target,revision=revision,change_id=change_id,**values)
        elif op == 'task.update':
            old = spec['preconditions']['task']
            values = {k:old[k] for k in ('title','goal','completion_conditions')}
            values.update(spec['payload'])
            self.s._insert(project,'formal_task_states',task_id=target,revision=revision,change_id=change_id,lifecycle=old['lifecycle'],**values)
        elif op == 'version.confirm':
            self.s.link_version_task(project,version,target)
            self.s._insert(project,'confirmed_version_links',task_id=target,version_id=version,change_id=change_id)
            if spec.get('native_context'):
                from .native import Native
                Native(self.s).apply_associations(project,spec)
        elif op == 'baseline.set':
            old = spec['preconditions']['baseline']
            self.s._insert(project,'baseline_history',version_id=version,previous_version_id=old['version_id'] if old else None,
                           revision=revision,change_id=change_id)
        elif op.startswith('thread.') or op in ('task.participation.set','task.lead.set'):
            from .threads import Threads
            Threads(self.s).apply(project,spec,revision,change_id)
        elif op == 'change.revoke':
            from .reversals import Reversals
            Reversals(self.s).apply(project,spec,revision,change_id)
        else:
            from .lifecycle import Lifecycle
            Lifecycle(self.s).apply(project,spec,revision,change_id,review)
        if op in ('baseline.set','task.update'):
            self.s._insert(project,'recheck_requests',revision=revision,change_id=change_id,
                           reason='baseline-changed' if op=='baseline.set' else 'task-content-changed')
        elif op in ('version.confirm','dependency.add','recheck.resolve'):
            from .lifecycle import Lifecycle
            Lifecycle(self.s).propagate(project,spec,revision,change_id)

    def state(self, project):
        p = self.s._project(project)
        from .reversals import Reversals
        effects = Reversals(self.s)
        tasks = effects.tasks(project)
        row = self.c.execute('SELECT state_json FROM derived_snapshots WHERE project_id=? AND revision=?',(project,p['revision'])).fetchone()
        derived = json.loads(row[0]) if row else None
        processed = {r['request_id'] for r in self.rows(project,'recheck_processing')}
        from .threads import Threads
        return dict(project=p,tasks=tasks,thread_state=Threads(self.s).state(project),confirmed_versions=effects.active_rows(project,'confirmed_version_links'),
                    baseline=self.baseline(project),pending_rechecks=[r for r in self.rows(project,'recheck_requests') if r['id'] not in processed],
                    readiness='not-evaluated',acceptance='exact-version-dual-path',derived_state='current' if derived else 'not-computed',
                    derived=derived,acceptances=self.rows(project,'acceptances'),events=sorted(self.rows(project,'task_events'),key=lambda e:(e['revision'],e['id'])),
                    check_executions=self.rows(project,'check_executions'),authorizations=self.rows(project,'check_authorizations'),
                    review_reasons=self.rows(project,'review_reasons'),review_resolutions=self.rows(project,'review_resolutions'),
                    current_authorizations=effects.active_rows(project,'check_authorizations'),
                    effective_acceptances=effects.acceptances(project),
                    current_review_resolutions=effects.active_rows(project,'review_resolutions'),
                    current_dependencies=[r for r in effects.active_rows(project,'dependencies') if r['phase']=='formal'],
                    historical_confirmed_versions=self.rows(project,'confirmed_version_links'),
                    corrections=self.rows(project,'effect_corrections'),
                    change_effects=[dict(change_id=a['id'],effective_change_id=a['effective_change_id'],
                                         active=a['id'] not in effects.revoked(project)) for a in effects.changes(project)])
