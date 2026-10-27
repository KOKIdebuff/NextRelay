"""Thread collaboration facts. Duties describe work, never authentication roles."""
import json

from .changes import ChangeError, canonical, content, exact
from .schema_t19 import OPERATIONS, T19_TABLES


def target_kind(op):
    if op.startswith('thread.'):
        return 'thread'
    if op=='baseline.set':
        return 'artifact'
    if op=='change.revoke':
        return 'change'
    return 'task'


def effect_key(spec):
    op, target, payload = spec['operation'], spec['target_id'], spec['payload']
    if op=='task.participation.set':
        return ('participation',target,payload['thread_id'])
    if op=='task.lead.set':
        return ('lead',target)
    if op=='thread.succession.set':
        return ('succession',target,payload['successor_id'])
    if op in OPERATIONS:
        return ('suggestion' if op=='thread.duty.suggest' else 'duty',target)
    return (target_kind(op),target)


class Threads:
    def __init__(self, store):
        self.s, self.c = store, store._connection

    def available(self):
        # Historical migration fixtures intentionally run older real schemas.
        return self.c.execute('PRAGMA user_version').fetchone()[0]>=11

    def rows(self, project, table):
        self.s._project(project)
        if not self.available():
            return []
        return self.s.records(project,table)

    def current(self, project, table):
        self.s._project(project)
        if not self.available():
            return []
        if table not in T19_TABLES[:4]:
            raise ChangeError('invalid_thread_projection')
        return [dict(r) for r in self.c.execute(f'SELECT * FROM current_{table} WHERE project_id=? ORDER BY id',(project,))]

    def normalize(self, op, payload):
        if op in ('thread.duty.set','thread.duty.suggest'):
            exact(payload,('main','basis'),('auxiliary',))
            main=payload['main']
            if main is not None:
                main=content(main)
            if main is None and op=='thread.duty.suggest':
                raise ChangeError('suggestion_requires_duty')
            auxiliary=payload.get('auxiliary',[])
            if not isinstance(auxiliary,list) or len(auxiliary)>100:
                raise ChangeError('invalid_auxiliary_duties')
            auxiliary=[content(v) for v in auxiliary]
            if len(set(auxiliary))!=len(auxiliary) or (main is None and auxiliary):
                raise ChangeError('invalid_auxiliary_duties')
            return dict(main=main,auxiliary=auxiliary,basis=content(payload['basis']))
        if op=='thread.duty.confirm':
            exact(payload,('suggestion_id','basis'))
            return dict(suggestion_id=content(payload['suggestion_id']),basis=content(payload['basis']))
        if op=='task.participation.set':
            exact(payload,('thread_id','active','basis'),('description',))
            if type(payload['active']) is not bool:
                raise ChangeError('invalid_participation')
            return dict(thread_id=content(payload['thread_id']),active=payload['active'],
                        description=content(payload.get('description',''),empty=True),basis=content(payload['basis']))
        if op=='task.lead.set':
            exact(payload,('thread_id','basis'))
            return dict(thread_id=None if payload['thread_id'] is None else content(payload['thread_id']),basis=content(payload['basis']))
        exact(payload,('successor_id','active','basis'))
        if type(payload['active']) is not bool:
            raise ChangeError('invalid_succession')
        return dict(successor_id=content(payload['successor_id']),active=payload['active'],basis=content(payload['basis']))

    def preconditions(self, project, spec):
        op, target, payload=spec['operation'],spec['target_id'],spec['payload']
        if spec['target_version_id'] is not None:
            raise ChangeError('unexpected_target_version')
        kind='sessions' if target_kind(op)=='thread' else 'tasks'
        result={'target':self.s._get(project,kind,target)}
        if kind=='tasks':
            from .changes import Changes
            result['task']=Changes(self.s).latest_task(project,target)
        if op.startswith('thread.duty.'):
            current=next((r for r in self.current(project,'thread_duties') if r['session_id']==target),None)
            result['current']=current
            if op=='thread.duty.confirm':
                suggestion=self.s._get(project,'thread_duties',payload['suggestion_id'])
                from .reversals import Reversals
                if suggestion['session_id']!=target or suggestion['status']!='suggested' or suggestion['change_id'] in Reversals(self.s).revoked(project):
                    raise ChangeError('invalid_duty_suggestion')
                if current and current['main']==suggestion['main'] and current['auxiliary_json']==suggestion['auxiliary_json']:
                    raise ChangeError('no_business_change')
                result['suggestion']=suggestion
                from .native_threads import duty_confirmation_context
                context=duty_confirmation_context(self.s,project,suggestion['id'])
                if context:result['suggestion_context']=context
            elif op=='thread.duty.set' and current and current['main']==payload['main'] and json.loads(current['auxiliary_json'])==payload['auxiliary']:
                raise ChangeError('no_business_change')
        elif op in ('task.participation.set','task.lead.set'):
            thread=payload['thread_id']
            if thread is not None:
                result['thread']=self.s._get(project,'sessions',thread)
            result['participants']=[r for r in self.current(project,'task_participation') if r['task_id']==target]
            result['lead']=next((r for r in self.current(project,'task_leads') if r['task_id']==target),None)
            if op=='task.participation.set':
                old=next((r for r in result['participants'] if r['session_id']==thread),None)
                if old and bool(old['active'])==payload['active'] and old['description']==payload['description']:
                    raise ChangeError('no_business_change')
                if not payload['active'] and (not old or not old['active']):
                    raise ChangeError('not_current_participant')
            elif (result['lead']['session_id'] if result['lead'] else None)==thread:
                raise ChangeError('no_business_change')
        else:
            result['successor']=self.s._get(project,'sessions',payload['successor_id'])
            if target==payload['successor_id']:
                raise ChangeError('succession_self_cycle')
            result['relations']=self.current(project,'thread_successions')
            old=next((r for r in result['relations'] if r['predecessor_id']==target and r['successor_id']==payload['successor_id']),None)
            if (not old and not payload['active']) or (old and bool(old['active'])==payload['active'] and old['basis']==payload['basis']):
                raise ChangeError('no_business_change')
        return result

    def validate_batch(self, project, specs):
        participation={(r['task_id'],r['session_id']):bool(r['active']) for r in self.current(project,'task_participation')}
        leads={r['task_id']:r['session_id'] for r in self.current(project,'task_leads')}
        edges={(r['predecessor_id'],r['successor_id']) for r in self.current(project,'thread_successions') if r['active']}
        explicit_leads={s['target_id'] for s in specs if s['operation']=='task.lead.set'}
        for spec in specs:
            op,target,p=spec['operation'],spec['target_id'],spec['payload']
            if op=='task.participation.set':
                if not p['active'] and leads.get(target)==p['thread_id'] and target not in explicit_leads:
                    raise ChangeError('lead_exit_requires_explicit_reassignment')
                participation[(target,p['thread_id'])]=p['active']
            elif op=='task.lead.set':
                leads[target]=p['thread_id']
            elif op=='thread.succession.set':
                edge=(target,p['successor_id'])
                edges.add(edge) if p['active'] else edges.discard(edge)
        for task,thread in leads.items():
            if thread is not None and not participation.get((task,thread),False):
                raise ChangeError('lead_requires_current_participant')
        self.check_graph(edges)

    @staticmethod
    def check_graph(edges):
        adjacency={}
        indegree={}
        for a,b in edges:
            adjacency.setdefault(a,[]).append(b)
            indegree.setdefault(a,0);indegree[b]=indegree.get(b,0)+1
        pending=[n for n,d in indegree.items() if not d]
        visited=0
        while pending:
            a=pending.pop();visited+=1
            for b in adjacency.get(a,[]):
                indegree[b]-=1
                if not indegree[b]:pending.append(b)
        if visited!=len(indegree):
            raise ChangeError('succession_cycle')

    @staticmethod
    def apply_order(spec):
        if spec['operation']=='thread.succession.set':
            # Validate the final graph, then remove old edges before adding new
            # ones so SQL guards never see a transient cycle during correction.
            return 3 if spec['payload']['active'] else -1
        if spec['operation']=='task.participation.set':
            return 0 if spec['payload']['active'] else 2
        return 1

    def apply(self, project, spec, revision, change):
        op,target,p=spec['operation'],spec['target_id'],spec['payload']
        common=dict(revision=revision,change_id=change,basis=p['basis'])
        if op.startswith('thread.duty.'):
            ordinal=self.c.execute('SELECT COALESCE(MAX(ordinal),0)+1 FROM thread_duties WHERE project_id=? AND session_id=?',(project,target)).fetchone()[0]
            suggestion=spec['preconditions']['thread'].get('suggestion')
            main=suggestion['main'] if suggestion else p['main']
            auxiliary=suggestion['auxiliary_json'] if suggestion else canonical(p['auxiliary'])
            self.s._insert(project,'thread_duties',session_id=target,ordinal=ordinal,main=main,auxiliary_json=auxiliary,
                status='suggested' if op=='thread.duty.suggest' else ('unspecified' if main is None else 'confirmed'),
                suggestion_id=suggestion['id'] if suggestion else None,**common)
        elif op=='task.participation.set':
            self.s._insert(project,'task_participation',task_id=target,session_id=p['thread_id'],active=int(p['active']),description=p['description'],**common)
        elif op=='task.lead.set':
            self.s._insert(project,'task_leads',task_id=target,session_id=p['thread_id'],**common)
        else:
            self.s._insert(project,'thread_successions',predecessor_id=target,successor_id=p['successor_id'],active=int(p['active']),**common)

    def capture(self, project, thread, relation_key, *, duty_version_id=None, existing=False, **references):
        if not self.available() or thread is None:
            return
        duty=None
        if duty_version_id is not None:
            duty=self.s._get(project,'thread_duties',content(duty_version_id))
            if duty['session_id']!=thread or duty['status']!='confirmed':
                raise ChangeError('inapplicable_contribution_duty')
        prior=self.c.execute('SELECT duty_id FROM contribution_duties WHERE project_id=? AND relation_key=?',(project,relation_key)).fetchone()
        if prior or existing:
            if duty_version_id is not None and (prior is None or prior['duty_id']!=duty_version_id):
                raise ChangeError('contribution_duty_conflict')
            return
        # Import/recording time does not establish when external work happened.
        # Only an explicitly supplied historical version can bind a contribution.
        self.s._insert(project,'contribution_duties',session_id=thread,duty_id=duty['id'] if duty else None,relation_key=relation_key,**references)

    def state(self, project):
        self.s._project(project)
        from .reversals import Reversals
        revoked=Reversals(self.s).revoked(project)
        history=[r for r in self.rows(project,'thread_duties') if r['change_id'] not in revoked]
        confirmed={r['suggestion_id'] for r in history if r['suggestion_id']}
        return dict(duties=self.current(project,'thread_duties'),
                    suggestions=[r for r in history if r['status']=='suggested' and r['id'] not in confirmed],
                    participation=self.current(project,'task_participation'),leads=self.current(project,'task_leads'),
                    successions=self.current(project,'thread_successions'))

    def listing(self, project, thread=None, task=None):
        self.s._project(project)
        if thread is not None:self.s._get(project,'sessions',thread)
        if task is not None:self.s._get(project,'tasks',task)
        def relevant(row):
            return (thread is None or thread in (row.get('session_id'),row.get('predecessor_id'),row.get('successor_id'))) and (task is None or row.get('task_id')==task)
        history={t:[r for r in self.rows(project,t) if relevant(r)] for t in T19_TABLES}
        bindings={r['relation_key']:r for r in self.rows(project,'contribution_duties')}
        contributions={}
        for table in ('task_sessions','attempt_sessions','source_attributions'):
            items=[]
            for r in self.s.records(project,table):
                if not relevant(r):continue
                key=('task:'+r['task_id']+':'+r['session_id']) if table=='task_sessions' else (
                    'attempt:'+r['attempt_id']+':'+r['session_id'] if table=='attempt_sessions' else 'source:'+r['id'])
                items.append(dict(r,duty_version_id=(bindings.get(key) or {}).get('duty_id')))
            contributions[table]=items
        state={k:[r for r in rows if relevant(r)] for k,rows in self.state(project).items()}
        return dict(project_id=project,revision=self.s._project(project)['revision'],
                    threads=[r for r in self.s.records(project,'sessions') if thread is None or r['id']==thread],
                    current=state,history=history,historical_contributions=contributions)

    def reversal_conflicts(self, project, original, spec, history, revoked):
        """Specific assignments/dependencies plus integrity of the proposed projection."""
        conflicts=[]
        key=effect_key(spec)
        op=spec['operation']
        current_edges={r['change_id'] for r in self.current(project,'thread_successions') if r['active']}
        for other in history:
            if other['id']==original['id'] or other['id'] in revoked:continue
            value=json.loads(other['effect_json']);p=value['payload']
            reason=None
            if other['revision']>original['revision'] and effect_key(value)==key:
                reason='later-thread-field-assignment'
            if op=='thread.duty.suggest' and value['operation']=='thread.duty.confirm' and p['suggestion_id'] in {
                    r['id'] for r in self.rows(project,'thread_duties') if r['change_id']==original['id']}:
                reason='suggestion-has-confirmation'
            if op=='thread.succession.set' and value['operation']=='thread.succession.set' and other['id'] in current_edges and other['revision']>original['revision']:
                if spec['payload']['successor_id']==value['target_id'] or p['successor_id']==spec['target_id']:
                    reason='later-related-succession; correct dependent relation first'
            if reason:conflicts.append(dict(change_id=other['id'],operation=value['operation'],target_id=value['target_id'],reason=reason))
        # A compensation can reveal an older lead/edge; inspect the actual state
        # with just this effect excluded, including same-transaction relations.
        active={}
        from .reversals import Reversals
        effects=Reversals(self.s)
        for table,fields in (('task_participation',('task_id','session_id')),('task_leads',('task_id',)),('thread_successions',('predecessor_id','successor_id'))):
            rows=[r for r in effects.active_rows(project,table) if r['change_id']!=original['id']]
            values={}
            for r in sorted(rows,key=lambda r:r['revision']):values[tuple(r[f] for f in fields)]=r
            active[table]=values
        for (task,),lead in active['task_leads'].items():
            if lead['session_id'] and not active['task_participation'].get((task,lead['session_id']),{}).get('active'):
                reason='participation-has-lead-reference' if op=='task.participation.set' else 'reversal-leaves-lead-without-participation'
                conflicts.append(dict(change_id=lead['change_id'],task_id=task,thread_id=lead['session_id'],reason=reason))
        try:
            self.check_graph({key for key,r in active['thread_successions'].items() if r['active']})
        except ChangeError:
            conflicts.append(dict(reason='reversal-restores-succession-cycle',change_ids=[r['change_id'] for r in active['thread_successions'].values() if r['active']]))
        return conflicts
