"""Single-effect compensation. History is immutable; current projections exclude corrections.

All IO is local SQLite in the caller's unit of work. Preview is data, never
authority: only an explicitly reviewed change.revoke candidate can apply it.
"""
import json

from .changes import ChangeError, canonical, content, digest


def assigned_fields(spec):
    if spec['operation'] == 'task.update':
        return {k:v for k,v in spec['payload'].items() if spec['preconditions']['task'][k] != v}
    return spec['payload']


class Reversals:
    def __init__(self, store):
        self.s = store
        self.c = store._connection

    def cached(self, project, name, build):
        self.s._project(project)
        key = (project, name)
        if key not in self.s._projection_cache:
            self.s._projection_cache[key] = build()
        return self.s._projection_cache[key]

    def revoked(self, project):
        return self.cached(project, 'revoked', lambda: {r['original_change_id'] for r in self.s.records(project, 'effect_corrections')})

    def active_rows(self, project, table, *, key='change_id'):
        revoked = self.revoked(project)
        return self.cached(project, ('active',table,key), lambda: [r for r in self.s.records(project, table) if r[key] not in revoked])

    def changes(self, project):
        return self.cached(project, 'changes', lambda: [dict(r) for r in self.c.execute('''SELECT a.*, c.revision FROM applied_changes a
            JOIN change_commits c ON c.project_id=a.project_id AND c.id=a.commit_id
            WHERE a.project_id=? ORDER BY c.revision,a.id''', (project,))])

    def tasks(self, project):
        return self.cached(project, 'tasks', lambda: self._tasks(project))

    def _tasks(self, project):
        # Fold field assignments only, never replay historical business operations
        # or restore a whole snapshot. Later independent fields stay intact.
        active = {a['id']: json.loads(a['effect_json']) for a in self.changes(project)
                  if a['id'] not in self.revoked(project)}
        values = {}
        for row in self.c.execute('SELECT * FROM formal_task_states WHERE project_id=? ORDER BY revision,task_id', (project,)):
            spec = active.get(row['change_id'])
            if not spec:
                continue
            task = row['task_id']
            if spec['operation'] == 'task.create':
                values[task] = dict(row)
            elif task in values:
                old = values[task]
                fields = {k: old[k] for k in ('title', 'goal', 'completion_conditions', 'lifecycle')}
                if spec['operation'] == 'task.update':
                    fields.update(assigned_fields(spec))
                else:
                    fields['lifecycle'] = row['lifecycle']
                values[task] = dict(row) | fields
        # task.update copied lifecycle at commit time: it must never resurrect a
        # revoked transition. Events determine current lifecycle independently.
        events = sorted(self.active_rows(project, 'task_events'), key=lambda e: (e['revision'], e['id']))
        for task, value in values.items():
            value['lifecycle'] = 'todo'
            for event in events:
                if event['task_id'] == task:
                    value['lifecycle'] = {'start': 'in-progress', 'rework': 'in-progress',
                                          'submit': 'awaiting-acceptance', 'accept': 'accepted'}[event['event']]
        return sorted(values.values(), key=lambda t: t['task_id'])

    def acceptances(self, project):
        revoked_effects = {a['effective_change_id'] for a in self.changes(project) if a['id'] in self.revoked(project)}
        return [a for a in self.s.records(project, 'acceptances') if a['phase'] == 'formal' and a['effective_change_id'] not in revoked_effects]

    def plan(self, project, original_id):
        from .lifecycle import Lifecycle
        life = Lifecycle(self.s)
        original = self.s._get(project, 'applied_changes', content(original_id))
        spec = json.loads(original['effect_json'])
        if spec['operation'] == 'change.revoke':
            raise ChangeError('redo_not_supported')
        if original_id in self.revoked(project):
            raise ChangeError('change_already_revoked')
        history = self.changes(project)
        original_revision = next(a['revision'] for a in history if a['id'] == original_id)
        root, op = spec['target_id'], spec['operation']
        from .threads import Threads, target_kind
        from .schema_t19 import OPERATIONS as T19_OPERATIONS
        root_kind = target_kind(op)
        all_tasks = life.tasks(project)
        affected = set()
        significant = op in ('version.confirm', 'baseline.set', 'dependency.add', 'acceptance.human', 'acceptance.auto', 'recheck.resolve') or (
            op == 'task.update' and 'goal' in spec['payload'] and spec['payload']['goal'] != spec['preconditions']['task']['goal'])
        if significant:
            affected = {t['task_id'] for t in all_tasks} if op == 'baseline.set' else life.reachable(life.edges(project), root)
        later, conflicts, unrelated = [], [], []
        for change in history:
            if change['revision'] <= original_revision or change['id'] in self.revoked(project):
                continue
            other = json.loads(change['effect_json'])
            related = (target_kind(other['operation'])==root_kind and other['target_id'] == root) or (target_kind(other['operation'])=='task' and other['target_id'] in affected) or (
                root_kind=='task' and other['operation'] == 'dependency.add' and other['payload']['predecessor_id'] == root) or (
                op == 'baseline.set' and other['operation'] == 'baseline.set')
            item = dict(change_id=change['id'], effective_change_id=change['effective_change_id'],
                        candidate_id=change['candidate_id'], review_id=change['review_id'], commit_id=change['commit_id'],
                        revision=change['revision'], operation=other['operation'], target_id=other['target_id'],
                        target_type=target_kind(other['operation']),target_version_id=other['target_version_id'], payload=other['payload'])
            (later if related else unrelated).append(item)
            if op == 'task.create' and related and other['operation'] != 'change.revoke':
                conflicts.append(dict(change_id=change['id'], reason='creation-has-formal-references; review dependent corrections first'))
            if op == 'task.update' and other['operation'] == 'task.update' and other['target_id'] == root:
                overlap = sorted(assigned_fields(spec).keys() & assigned_fields(other).keys())
                if overlap:
                    conflicts.append(dict(change_id=change['id'], fields=overlap, reason='later-field-assignment; review a new targeted update'))
            if op == 'task.submit' and other['target_id'] == root and other['operation'].startswith('acceptance.'):
                # Removing a submission under a current acceptance requires a
                # separately reviewed acceptance correction, never a cascade.
                conflicts.append(dict(change_id=change['id'], reason='submission-has-acceptance; correct acceptance first'))
        # Same-batch relations are impossible today but still check the actual
        # current references rather than assuming commit ordering is sufficient.
        if op == 'task.create':
            refs = [a['id'] for a in history if a['id'] != original_id and a['id'] not in self.revoked(project)
                    and ((target_kind(json.loads(a['effect_json'])['operation'])=='task' and json.loads(a['effect_json'])['target_id'] == root) or
                         (json.loads(a['effect_json'])['operation'] == 'dependency.add' and json.loads(a['effect_json'])['payload']['predecessor_id'] == root))
                    and json.loads(a['effect_json'])['operation'] != 'change.revoke']
            known = {c['change_id'] for c in conflicts}
            conflicts.extend(dict(change_id=c, reason='creation-has-formal-references') for c in refs if c not in known)
        if op in T19_OPERATIONS:
            original_with_revision=dict(original,revision=original_revision)
            conflicts.extend(Threads(self.s).reversal_conflicts(project,original_with_revision,spec,history,self.revoked(project)))
            # Relationship conflicts may reference a successor rather than the
            # original target. Such changes must not be labelled unrelated.
            related_ids={c['change_id'] for c in conflicts if 'change_id' in c}
            related_ids.update(identity for c in conflicts for identity in c.get('change_ids',[]))
            later.extend(item for item in unrelated if item['change_id'] in related_ids)
            unrelated=[item for item in unrelated if item['change_id'] not in related_ids]
            later.sort(key=lambda item:(item['revision'],item['change_id']))
        current = self.s.formal_state(project)
        work_tables = ('attempts','artifact_version_tasks','artifact_tasks','version_sources','evidence','check_results',
                       'task_sessions','attempt_sessions','source_attributions')
        if Threads(self.s).available():
            work_tables += ('contribution_duties',)
        work = {table: self.s.records(project, table) for table in work_tables}
        return dict(project_id=project, base_revision=current['project']['revision'],
                    original=original, original_revision=original_revision, operation=op, target_id=root,
                    target_type=root_kind,
                    target_version_id=spec['target_version_id'], fields=assigned_fields(spec),
                    subsequent_changes=later, preserved_unrelated_changes=unrelated,
                    affected_tasks=[dict(task=t, derived=next(v for v in current['derived']['tasks'] if v['task_id'] == t['task_id']))
                                    for t in all_tasks if t['task_id'] in affected],
                    conflicts=conflicts, handling='refuse-and-review-targeted-corrections' if conflicts else (
                        'confirm-preserve-later-and-recheck' if later else 'independent-compensation'),
                    treatment=dict(revoke_only=original_id, preserve_other_changes=True, preserve_history=True,
                                   mark_review_tasks=sorted(affected), delete_external=False),
                    preserved_work=work,
                    preconditions=dict(state_sha256=digest(current), history_sha256=digest(history), work_sha256=digest(work)))

    def preview(self, project, original_id):
        plan = self.plan(project, original_id)
        return self.s._insert(project, 'reversal_previews', original_change_id=original_id,
                              base_revision=plan['base_revision'], preview_json=canonical(plan), fingerprint=digest(plan))

    def validate(self, project, spec):
        preview = self.s._get(project, 'reversal_previews', spec['payload']['preview_id'])
        if spec['target_id'] != preview['original_change_id'] or spec['target_version_id'] is not None:
            raise ChangeError('reversal_target_mismatch')
        if preview['created_by'] != self.s._principal.subject:
            raise ChangeError('reversal_subject_mismatch')
        plan = self.plan(project, preview['original_change_id'])
        if plan['base_revision'] != preview['base_revision'] or canonical(plan) != preview['preview_json'] or digest(plan) != preview['fingerprint']:
            raise ChangeError('reversal_preview_stale')
        if plan['conflicts']:
            raise ChangeError('unsafe_independent_reversal')
        return dict(preview=preview)

    def apply(self, project, spec, revision, change):
        from .lifecycle import Lifecycle
        preview = self.s._get(project, 'reversal_previews', spec['payload']['preview_id'])
        plan = json.loads(preview['preview_json'])
        self.s._insert(project, 'effect_corrections', original_change_id=spec['target_id'], change_id=change,
                       preview_id=preview['id'], revision=revision)
        life = Lifecycle(self.s)
        # Monotonic correction generation. Even restoration of the same business
        # value cannot reuse old grants/checks/continuations.
        for task in plan['treatment']['mark_review_tasks']:
            self.s._insert(project, 'review_reasons', task_id=task, version_id=life.current_version(project, task),
                           trigger_revision=revision, trigger_change_id=change, reason='change.revoke:'+plan['operation'],
                           root_task_id=None if plan['operation'] == 'baseline.set' else plan['target_id'])
