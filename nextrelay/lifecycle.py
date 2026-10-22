"""T05 formal state engine, evaluated synchronously in the caller's transaction."""
from datetime import datetime, timezone
import json

from .changes import ChangeError, canonical, content, digest, exact
from . import checks


class Lifecycle:
    def __init__(self, store):
        self.s = store
        self.c = store._connection
        from .changes import Changes
        self.ch = Changes(store)

    def rows(self, project, table):
        return self.s.records(project, table)

    def tasks(self, project):
        from .reversals import Reversals
        return Reversals(self.s).tasks(project)

    def active_rows(self, project, table):
        from .reversals import Reversals
        return Reversals(self.s).active_rows(project,table)

    def edges(self, project):
        return [r for r in self.active_rows(project, 'dependencies') if r['phase'] == 'formal']

    def current_version(self, project, task):
        from .reversals import Reversals
        effects = Reversals(self.s)
        order = {a['id']: a['revision'] for a in effects.changes(project)}
        row = max((r for r in effects.active_rows(project,'confirmed_version_links') if r['task_id']==task),
                  key=lambda r: order[r['change_id']], default=None)
        return row['version_id'] if row else None

    def open_reasons(self, project, task):
        closed = {r['reason_id'] for r in self.active_rows(project,'review_resolutions') if r['decision'] in ('continue','rework')}
        return sorted((r for r in self.rows(project,'review_reasons') if r['task_id']==task and r['id'] not in closed),
                      key=lambda r:(r['trigger_revision'],r['id']))

    def generation(self, project, task):
        """Permanent influence/rework identities survive resolution and values returning to old values."""
        influence = self.c.execute('''SELECT trigger_change_id FROM review_reasons WHERE project_id=? AND task_id=?
            ORDER BY trigger_revision DESC,rowid DESC LIMIT 1''',(project,task)).fetchone()
        rework = self.c.execute("SELECT change_id FROM task_events WHERE project_id=? AND task_id=? AND event='rework' ORDER BY revision DESC LIMIT 1",
                                (project,task)).fetchone()
        return dict(influence=influence[0] if influence else None,rework=rework[0] if rework else None)

    def context(self, project, task, version, *, resolving=None):
        state = self.ch.latest_task(project, task)
        baseline = self.ch.baseline(project)
        # All incoming edges and all unresolved upstream reasons participate. No narrow artifact filter.
        incoming = []
        for edge in sorted(self.edges(project), key=lambda e: e['id']):
            if edge['successor_id'] == task:
                upstream = edge['predecessor_id']
                upstream_state = self.ch.latest_task(project,upstream)
                incoming.append(dict(edge=edge['id'], goal=upstream_state['goal'],conditions=upstream_state['completion_conditions'],
                                     generation=self.generation(project,upstream),
                                     version=self.current_version(project, upstream),
                                     reasons=self.open_reasons(project, upstream)))
        return digest(dict(task_id=task, version_id=version, goal=state['goal'],generation=self.generation(project,task),
                           completion_conditions=state['completion_conditions'],
                           conditions_version=self.s._get(project,'tasks',task)['conditions_version'],
                           baseline=baseline, incoming=incoming,
                           sources=[dict(r) for r in self.c.execute('SELECT * FROM version_sources WHERE project_id=? AND version_id=? ORDER BY source_id',(project,version))],
                           reasons=[r for r in self.open_reasons(project, task) if r['id'] != resolving]))

    def exact_version(self, project, task, version):
        state = self.ch.latest_task(project, task)
        self.s._require_version(project, version)
        if not any(r['task_id']==task and r['version_id']==version for r in self.active_rows(project,'confirmed_version_links')):
            raise ChangeError('confirmed_attribution_required')
        if self.current_version(project, task) != version:
            raise ChangeError('not_current_version')
        return state

    def submission(self, project, task, version):
        row = max((r for r in self.active_rows(project,'task_events') if r['task_id']==task),key=lambda r:r['revision'],default=None)
        if row is None or row['event'] != 'submit' or row['version_id'] != version:
            raise ChangeError('matching_submission_required')
        return dict(row)

    def dag(self, project, predecessor, successor):
        self.ch.latest_task(project, predecessor)
        self.ch.latest_task(project, successor)
        if predecessor == successor:
            raise ChangeError('dependency_self_loop')
        edges = self.edges(project)
        if any(e['predecessor_id']==predecessor and e['successor_id']==successor for e in edges):
            raise ChangeError('duplicate_dependency')
        reached = self.reachable(edges, successor)
        if predecessor in reached:
            raise ChangeError('dependency_cycle')

    @staticmethod
    def reachable(edges, root):
        adjacency = {}
        for e in edges:
            adjacency.setdefault(e['predecessor_id'], []).append(e['successor_id'])
        seen, queue = set(), [root]
        while queue:
            item = queue.pop()
            if item in seen:
                continue
            seen.add(item)
            queue.extend(adjacency.get(item, ()))
        return seen

    def normalize(self, op, payload):
        required = {
            'task.start': ('basis',), 'task.submit': ('basis',),
            'acceptance.human': ('decision','basis'),
            'acceptance.auto': ('check_id','authorization_id'),
            'check.authorize': ('config','expires_at','scope','basis'),
            'dependency.add': ('predecessor_id','basis'),
            'recheck.resolve': ('reason_id','decision','basis'),
        }
        exact(payload, required[op])
        for key, value in payload.items():
            if key != 'config':
                content(value)
        if op == 'acceptance.human' and payload['decision'] != 'accept':
            raise ChangeError('explicit_accept_decision_required')
        if op == 'check.authorize':
            checks.config(payload['config'])
            if payload['scope'] != 'accept-exact-version':
                raise ChangeError('invalid_authorization_scope')
            self.expiry(payload['expires_at'])
        if op == 'recheck.resolve' and payload['decision'] not in ('continue','needs-evidence','rework'):
            raise ChangeError('invalid_recheck_decision')
        return payload

    @staticmethod
    def expiry(value):
        try:
            expires = datetime.fromisoformat(value)
            if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
                raise ValueError()
        except (TypeError, ValueError):
            raise ChangeError('authorization_expired_or_invalid') from None

    def preconditions(self, project, spec):
        op, task, version, payload = (spec[k] for k in ('operation','target_id','target_version_id','payload'))
        state = self.ch.latest_task(project, task)
        result = dict(task=state, context=self.context(project,task,version))
        if op in ('task.submit','check.authorize','acceptance.human','acceptance.auto'):
            self.exact_version(project,task,version)
        elif op != 'recheck.resolve' and version is not None:
            raise ChangeError('unexpected_version')
        if op == 'task.start' and state['lifecycle'] != 'todo':
            raise ChangeError('illegal_lifecycle_transition')
        if op == 'task.start':
            current = next(t for t in self.derive(project,self.s._project(project)['revision'])['tasks'] if t['task_id']==task)
            if current['blockers'] or current['review_reasons']:
                raise ChangeError('task_not_executable')
        if op == 'task.submit' and state['lifecycle'] not in ('todo','in-progress'):
            raise ChangeError('illegal_lifecycle_transition')
        if op.startswith('acceptance.'):
            if state['lifecycle'] != 'awaiting-acceptance':
                raise ChangeError('illegal_lifecycle_transition')
            result['submission'] = self.submission(project,task,version)
        if op == 'dependency.add':
            self.dag(project,payload['predecessor_id'],task)
            result['edges'] = self.edges(project)
        if op == 'check.authorize':
            self.expiry(payload['expires_at'])
        if op == 'acceptance.auto':
            run = self.s._get(project,'check_executions',payload['check_id'])
            grant = self.s._get(project,'check_authorizations',payload['authorization_id'])
            if grant['id'] not in {g['id'] for g in self.active_rows(project,'check_authorizations')}:
                raise ChangeError('authorization_revoked')
            self.expiry(grant['expires_at'])
            for key, expected in (('task_id',task),('version_id',version),
                                  ('conditions_version',self.s._get(project,'tasks',task)['conditions_version']),
                                  ('context_sha256',result['context'])):
                if run[key] != expected or grant[key] != expected:
                    raise ChangeError('authorization_or_check_out_of_scope')
            if run['result'] != 'pass' or run['config_sha256'] != grant['config_sha256'] or run['config_json'] != grant['config_json']:
                raise ChangeError('actual_matching_pass_required')
            if grant['created_by'] != self.s._principal.subject:
                raise ChangeError('authorization_subject_mismatch')
            result.update(check=run, authorization=grant)
        if op == 'recheck.resolve':
            reason = self.s._get(project,'review_reasons',payload['reason_id'])
            if reason['task_id'] != task or reason['version_id'] != version:
                raise ChangeError('recheck_object_version_mismatch')
            if reason['id'] not in {r['id'] for r in self.open_reasons(project,task)}:
                raise ChangeError('recheck_already_resolved')
            if payload['decision']=='continue':
                # Never close the last actionable cause against unsettled upstream context.
                edges=self.edges(project)
                ancestors={t['task_id'] for t in self.tasks(project) if t['task_id']!=task and task in self.reachable(edges,t['task_id'])}
                if any(self.open_reasons(project,ancestor) for ancestor in ancestors):
                    raise ChangeError('upstream_recheck_unresolved')
                if state['lifecycle']=='accepted':
                    current=self.current_version(project,task)
                    from .reversals import Reversals
                    submitted=max((r for r in self.active_rows(project,'task_events') if r['task_id']==task and r['event']=='submit'),key=lambda r:r['revision'],default=None)
                    existing=any(a['task_id']==task and a['version_id']==current and submitted and a['submission_id']==submitted['id'] for a in Reversals(self.s).acceptances(project))
                    if version!=current or not existing:
                        raise ChangeError('current_version_acceptance_required_for_continue')
            if payload['decision']=='rework' and state['lifecycle'] not in ('accepted','awaiting-acceptance','in-progress'):
                raise ChangeError('illegal_rework_transition')
            result['reason'] = reason
        return result

    def snapshot_task(self, project, task, revision, change, lifecycle):
        old = self.ch.latest_task(project,task)
        self.s._insert(project,'formal_task_states',task_id=task,revision=revision,change_id=change,
                       lifecycle=lifecycle,**{k:old[k] for k in ('title','goal','completion_conditions')})

    def apply(self, project, spec, revision, change, review):
        op, task, version, payload = (spec[k] for k in ('operation','target_id','target_version_id','payload'))
        basis = payload.get('basis', 'Executed builtin-v1 under exact preauthorization')
        if op == 'dependency.add':
            self.dag(project,payload['predecessor_id'],task)  # Check union of the actual submitted batch.
            self.s._insert(project,'dependencies',predecessor_id=payload['predecessor_id'],successor_id=task,
                           phase='formal',change_id=change)
        elif op == 'check.authorize':
            self.s._insert(project,'check_authorizations',task_id=task,version_id=version,
                           conditions_version=self.s._get(project,'tasks',task)['conditions_version'],
                           config_json=canonical(payload['config']),config_sha256=digest(payload['config']),
                           context_sha256=self.context(project,task,version),expires_at=payload['expires_at'],
                           scope=payload['scope'],basis=basis,input_origin=review['input_origin'],change_id=change)
        elif op == 'recheck.resolve':
            self.s._insert(project,'review_resolutions',reason_id=payload['reason_id'],task_id=task,version_id=version,
                           decision=payload['decision'],revision=revision,change_id=change,basis=basis,
                           context_sha256=self.context(project,task,version,resolving=payload['reason_id'] if payload['decision']!='needs-evidence' else None))
            if payload['decision']=='rework':
                self.snapshot_task(project,task,revision,change,'in-progress')
                attempt = self.s.create_attempt(project,task,'Explicit rework: '+basis[:256])
                self.s._insert(project,'task_events',task_id=task,version_id=version,attempt_id=attempt['id'],revision=revision,event='rework',change_id=change,basis=basis)
        else:
            if op == 'task.start':
                lifecycle, event = 'in-progress','start'
            elif op == 'task.submit':
                lifecycle, event = 'awaiting-acceptance','submit'
            else:
                lifecycle, event = 'accepted','accept'
                submission = self.submission(project,task,version)
                if op == 'acceptance.auto':
                    run = spec['preconditions']['t05']['check']
                    evidence, check_id, grant_id, mode = run['evidence_id'],run['id'],payload['authorization_id'],'check'
                else:
                    evidence = self.s.record_evidence(project,version,task_id=task,kind='human-basis',
                        mechanism='explicit-human-decision',subject=self.s._principal.subject,result=basis,
                        conditions_version=self.s._get(project,'tasks',task)['conditions_version'],configuration_version='human-v1')['id']
                    check_id, grant_id, mode = None,None,'human'
                applied = self.s._get(project,'applied_changes',change)
                self.s._insert(project,'acceptances',task_id=task,version_id=version,effective_change_id=applied['effective_change_id'],
                    evidence_id=evidence,phase='formal',mode=mode,conditions_version=self.s._get(project,'tasks',task)['conditions_version'],
                    context_sha256=self.context(project,task,version),submission_id=submission['id'],check_id=check_id,
                    authorization_id=grant_id,basis=basis)
            self.snapshot_task(project,task,revision,change,lifecycle)
            attempt = self.s.create_attempt(project,task,'Approved start: '+basis[:256]) if event=='start' else None
            self.s._insert(project,'task_events',task_id=task,version_id=version,attempt_id=attempt['id'] if attempt else None,
                           revision=revision,event=event,change_id=change,basis=basis)

    def propagate(self, project, spec, revision, change, request_id=None):
        op, root = spec['operation'], spec['target_id']
        significant = op in ('baseline.set','version.confirm','dependency.add') or (
            op=='task.update' and 'goal' in spec['payload'] and spec['payload']['goal']!=spec['preconditions']['task']['goal']) or (
            op=='recheck.resolve' and spec['payload']['decision']=='rework')
        if not significant:
            return
        tasks = self.tasks(project)
        targets = {t['task_id'] for t in tasks} if op=='baseline.set' else self.reachable(self.edges(project),root)
        for task in sorted(targets):
            if op=='recheck.resolve' and task==root:
                continue  # Rework invalidates the root explicitly; retain only other independent root causes.
            # Initial version attribution does not invalidate the as-yet unsubmitted root.
            if op=='version.confirm' and task==root and self.ch.latest_task(project,task)['lifecycle']=='todo':
                continue
            if self.c.execute('SELECT 1 FROM review_reasons WHERE project_id=? AND task_id=? AND trigger_change_id=?',
                              (project,task,change)).fetchone():
                continue
            self.s._insert(project,'review_reasons',task_id=task,version_id=self.current_version(project,task),
                trigger_revision=revision,trigger_change_id=change,reason=op,root_task_id=None if op=='baseline.set' else root,request_id=request_id)

    def sync(self, project, revision):
        # Consume legacy T04 pending facts with their original target/version. Never rewrite them.
        for request in self.rows(project,'recheck_requests'):
            if self.c.execute('SELECT 1 FROM recheck_processing WHERE project_id=? AND request_id=?',(project,request['id'])).fetchone():
                continue
            change = self.s._get(project,'applied_changes',request['change_id'])
            spec = json.loads(change['effect_json'])
            self.propagate(project,spec,request['revision'],change['id'],request['id'])
            self.s._insert(project,'recheck_processing',request_id=request['id'],target_revision=request['revision'],processed_revision=revision)
        state = self.derive(project,revision)
        self.s._insert(project,'derived_snapshots',revision=revision,state_json=canonical(state))

    def derive(self, project, revision):
        tasks, edges = self.tasks(project), self.edges(project)
        from .reversals import Reversals
        acceptances = Reversals(self.s).acceptances(project)
        events = self.active_rows(project,'task_events')
        values = {}
        for t in tasks:
            task = t['task_id']; version = self.current_version(project,task)
            reasons = self.open_reasons(project,task)
            last = sorted((e for e in events if e['task_id']==task),key=lambda e:e['revision'])
            submissions = [e for e in last if e['event']=='submit']
            latest_submission = submissions[-1]['id'] if submissions else None
            accepted = [a for a in acceptances if a['task_id']==task and a['version_id']==version and a['submission_id']==latest_submission]
            valid_acceptances = [a for a in accepted if a['context_sha256']==self.context(project,task,version)]
            continuations = [r for r in self.active_rows(project,'review_resolutions') if r['task_id']==task and r['version_id']==version
                             and r['decision']=='continue' and r['context_sha256']==self.context(project,task,version)]
            if not reasons and continuations:
                latest_continue = max(r['revision'] for r in continuations)
                valid_acceptances += [a for a in accepted if a not in valid_acceptances and any(e['event']=='accept' and e['task_id']==task
                    and e['version_id']==version and e['revision']<latest_continue for e in events)]
            applicable = bool(valid_acceptances) and t['lifecycle']=='accepted'
            validity = 'pending-review' if reasons else ('applicable' if applicable else (
                'inapplicable' if last and last[-1]['event']=='rework' else 'unknown'))
            values[task] = dict(task_id=task,version_id=version,lifecycle=t['lifecycle'],validity=validity,
                               review_reasons=reasons,current_acceptance_ids=[a['id'] for a in valid_acceptances] if applicable else [],
                               historical_acceptance_ids=[a['id'] for a in self.rows(project,'acceptances') if a['task_id']==task and a['phase']=='formal'],blockers=[])
        # DAG ordered evaluation: an accepted middle node cannot mask a blocked ancestor.
        remaining = set(values)
        while remaining:
            ready = [t for t in remaining if all(e['predecessor_id'] not in remaining for e in edges if e['successor_id']==t)]
            if not ready:
                raise ChangeError('stored_dependency_cycle')
            for task in ready:
                value = values[task]
                for edge in edges:
                    if edge['successor_id'] != task:
                        continue
                    upper = values[edge['predecessor_id']]
                    if upper['lifecycle']!='accepted' or upper['validity']!='applicable' or upper['blockers']:
                        value['blockers'].append(dict(dependency_id=edge['id'],task_id=upper['task_id'],version_id=upper['version_id'],
                            lifecycle=upper['lifecycle'],validity=upper['validity'],review_reason_ids=[r['id'] for r in upper['review_reasons']],
                            reason='upstream-not-currently-accepted-and-valid',upstream_blocker_ids=[b['dependency_id'] for b in upper['blockers']]))
                value['executable'] = not value['blockers'] and not value['review_reasons'] and value['lifecycle'] in ('todo','in-progress')
                value['revision'] = revision
                remaining.remove(task)
        versions = self.active_rows(project,'confirmed_version_links')
        for value in values.values():
            value['related_versions'] = [dict(version_id=v['version_id'], validity=value['validity'] if v['version_id']==value['version_id'] else 'unknown')
                                         for v in versions if v['task_id']==value['task_id']]
        return dict(revision=revision,tasks=list(values.values()),dependencies=edges,
                    sources=[dict(source_id=s['id'],availability=s['availability'],read_result=s['read_result']) for s in self.rows(project,'sources')])

    def run(self, project, task, version, configuration):
        self.s._project(project)
        self.exact_version(project,task,version)
        conditions = self.s._get(project,'tasks',task)['conditions_version']
        # Invalid configs are traceable errors as long as they fit the resource envelope.
        checks.bounded(configuration,max_bytes=checks.MAX_CONFIG)
        if len(canonical(configuration).encode('utf-8')) > checks.MAX_CONFIG:
            raise ChangeError('check_config_limit')
        # SQLite only returns the body if its UTF-8 byte size fits. Neither attribution
        # validation nor evidence creation loads the full body before this envelope.
        bounded_body = self.c.execute('''SELECT CASE WHEN length(CAST(content AS BLOB))<=? THEN content END
            FROM artifact_versions WHERE project_id=? AND id=?''',(checks.MAX_CONTENT,project,version)).fetchone()[0]
        if bounded_body is None:
            result, details = 'error','content exceeds 262144 UTF-8 bytes'
        else:
            result, details = checks.execute(bounded_body,configuration)
        evidence = self.s.record_evidence(project,version,task_id=task,kind='observation',mechanism='builtin-v1',
            subject='local-builtin-executor',result=result,conditions_version=conditions,configuration_version=digest(configuration))
        check = self.s.record_check(project,evidence['id'],mechanism='builtin-v1',subject='local-builtin-executor',
            configuration_version=digest(configuration),result=result if result!='missing' else 'unknown',details=details)
        return self.s._insert(project,'check_executions',task_id=task,version_id=version,conditions_version=conditions,
            config_json=canonical(configuration),config_sha256=digest(configuration),context_sha256=self.context(project,task,version),
            revision=self.s._project(project)['revision'],mechanism='builtin-v1',result=result,details=details,
            evidence_id=evidence['id'],check_result_id=check['id'])

    def auto_accept(self, project, request):
        self.s._project(project)
        exact(request, ('request_key','base_revision','task_id','version_id','check_id','authorization_id'))
        fingerprint = digest(request)
        prior = self.c.execute('SELECT * FROM auto_requests WHERE project_id=? AND request_key=?',
                              (project,content(request['request_key']))).fetchone()
        if prior:
            if prior['fingerprint'] != fingerprint:
                raise ChangeError('idempotency_key_reused')
            return json.loads(prior['result_json'])
        candidate = self.ch.save(project,dict(base_revision=request['base_revision'],operation='acceptance.auto',
            target_id=request['task_id'],target_version_id=request['version_id'],
            payload=dict(check_id=request['check_id'],authorization_id=request['authorization_id'])))
        # This is a mechanical grant reference, not a fabricated human decision.
        grant = self.s._get(project,'check_authorizations',request['authorization_id'])
        review = self.s._insert(project,'change_reviews',candidate_id=candidate['candidate_id'],fingerprint=candidate['fingerprint'],
            decision='approve',mode='explicit',basis='Mechanical application of recorded preauthorization '+grant['id'],sequence=1,
            input_origin=grant['input_origin'],authorization_json=canonical(self.ch.authorization(candidate)))
        result = self.ch.commit(project,dict(request_key='auto:'+candidate['candidate_id'],base_revision=request['base_revision'],
            selection=[dict(candidate_id=candidate['candidate_id'],review_id=review['id'])]))
        self.s._insert(project,'auto_requests',request_key=request['request_key'],fingerprint=fingerprint,result_json=canonical(result))
        return result
