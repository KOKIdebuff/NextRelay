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
        row = self.c.execute('SELECT * FROM formal_task_states WHERE project_id=? AND task_id=? ORDER BY revision DESC LIMIT 1',
                             (project,target)).fetchone()
        if row is None:
            raise ChangeError('task_not_formal')
        return dict(row)

    def baseline(self, project):
        row = self.c.execute('SELECT * FROM baseline_history WHERE project_id=? ORDER BY revision DESC LIMIT 1', (project,)).fetchone()
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
        if version is not None:
            result['version'] = self.s._get(project,'artifact_versions',version)
            if op == 'baseline.set' and result['version']['artifact_id'] != target:
                raise ChangeError('wrong_artifact_version')
            result['version_sources'] = [dict(r) for r in self.c.execute(
                'SELECT * FROM version_sources WHERE project_id=? AND version_id=? ORDER BY source_id',(project,version))]
        if op == 'version.confirm' and self.c.execute('SELECT 1 FROM confirmed_version_links WHERE project_id=? AND task_id=? AND version_id=?',
                                                     (project,target,version)).fetchone():
            raise ChangeError('version_already_confirmed')
        if op == 'baseline.set' and result['baseline'] and result['baseline']['version_id'] == version:
            raise ChangeError('baseline_already_current')
        for source in spec['source_ids']:
            result['sources'].append(self.s._get(project,'sources',source))
            result.setdefault('attributions',[]).append(self.s.attribution(project,source))
        for evidence in spec['evidence_ids']:
            e = self.s._get(project,'evidence',evidence)
            expected_task = target if op == 'version.confirm' else None
            if version is None or e['version_id'] != version or e['task_id'] != expected_task:
                raise ChangeError('inapplicable_evidence')
            if expected_task and e['conditions_version'] != self.s._get(project,'tasks',target)['conditions_version']:
                raise ChangeError('stale_evidence_conditions')
            result['evidence'].append(e)
        return result

    def save(self, project, request):
        p = self.s._project(project)
        exact(request, ('base_revision','operation','payload'),
              ('target_id','target_version_id','source_ids','evidence_ids','risk','conflicts','impact','supersedes_id'))
        base = integer(request['base_revision'])
        if p['revision'] != base:
            raise ChangeError('revision_conflict')
        op = request['operation']
        if op not in ('task.create','task.update','version.confirm','baseline.set'):
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
        else:
            exact(payload, ())
            target = content(request.get('target_id'))
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
        risk = 'conflict' if conflicts or risk=='conflict' else ('high' if op=='baseline.set' else risk)
        impact = content(request.get('impact',''),empty=True)
        if not impact.strip():
            impact = {
                'task.create': 'Create one formal todo task; no acceptance or dependency release.',
                'task.update': 'Append a formal title/goal snapshot and a pending recheck; preserve history.',
                'version.confirm': 'Confirm this exact task/version relation; no acceptance or authority inheritance.',
                'baseline.set': 'Switch the single requirements baseline to this exact version and record a pending recheck; readiness is not evaluated.',
            }[op]
        spec = dict(operation=op,target_id=target,target_version_id=version,payload=payload,
                    base_revision=base,source_ids=source_ids,evidence_ids=evidence_ids,
                    risk=risk,conflicts=conflicts,impact=impact)
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
            target_key = ('baseline' if spec['operation']=='baseline.set' else 'task',spec['target_id'])
            if target_key in targets:
                raise ChangeError('overlapping_effects')
            targets.add(target_key)
            candidates.append((candidate,review))
        if any(c['risk']!='ordinary' for c,r in candidates) and len(candidates)!=1:
            raise ChangeError('explicit_commit_is_single')
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
        for candidate,review,eid,aid in planned:
            self.insert_fixed(project,'effective_changes',eid,dict(candidate_id=candidate['candidate_id']))
            self.insert_fixed(project,'applied_changes',aid,dict(effective_change_id=eid,candidate_id=candidate['candidate_id'],
                review_id=review['id'],commit_id=commit['id'],effect_json=canonical(candidate['spec'])))
            self.apply(project,candidate['spec'],revision,aid)
        changed = self.c.execute('UPDATE projects SET revision=? WHERE id=? AND revision=?', (revision,project,base)).rowcount
        if changed != 1:
            raise ChangeError('revision_conflict')
        return result

    def insert_fixed(self, project, table, identity, values):
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

    def apply(self, project, spec, revision, change_id):
        op,target,version = spec['operation'],spec['target_id'],spec['target_version_id']
        if op == 'task.create':
            values = spec['payload']
            self.insert_fixed(project,'tasks',target,values)
            self.s._insert(project,'formal_task_states',task_id=target,revision=revision,change_id=change_id,**values)
        elif op == 'task.update':
            old = spec['preconditions']['task']
            values = {k:old[k] for k in ('title','goal','completion_conditions')}
            values.update(spec['payload'])
            self.s._insert(project,'formal_task_states',task_id=target,revision=revision,change_id=change_id,**values)
        elif op == 'version.confirm':
            self.s.link_version_task(project,version,target)
            self.s._insert(project,'confirmed_version_links',task_id=target,version_id=version,change_id=change_id)
        elif op == 'baseline.set':
            old = spec['preconditions']['baseline']
            self.s._insert(project,'baseline_history',version_id=version,previous_version_id=old['version_id'] if old else None,
                           revision=revision,change_id=change_id)
        else:
            raise ChangeError('unsupported_operation')
        if op in ('baseline.set','task.update'):
            self.s._insert(project,'recheck_requests',revision=revision,change_id=change_id,
                           reason='baseline-changed' if op=='baseline.set' else 'task-content-changed')

    def state(self, project):
        p = self.s._project(project)
        tasks = [dict(r) for r in self.c.execute('''SELECT s.* FROM formal_task_states s WHERE s.project_id=?
            AND NOT EXISTS (SELECT 1 FROM formal_task_states n WHERE n.project_id=s.project_id AND n.task_id=s.task_id AND n.revision>s.revision)
            ORDER BY s.task_id''',(project,))]
        return dict(project=p,tasks=tasks,confirmed_versions=self.rows(project,'confirmed_version_links'),
                    baseline=self.baseline(project),pending_rechecks=self.rows(project,'recheck_requests'),
                    readiness='not-evaluated',acceptance='not-implemented',derived_state='not-computed')
