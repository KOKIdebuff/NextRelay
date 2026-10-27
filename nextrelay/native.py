"""Bounded native organization of inert T07 output. Never reviews or commits.

Rules are deliberately inspectable. Arbitrary prose remains a sourced document;
labelled declarations, headings and key/value facts provide stronger signals.
Imported identities and instructions are claims, never execution authority.
"""
import hashlib
import json
import re
from functools import wraps

from .auth import AccessError
from .changes import ChangeError, Changes, canonical, exact, integer, content
from .formats import encoded
from .store import unit_of_work, TransactionAborted

PROCESSOR = 'nextrelay-native/3'
MAX_DOCUMENT = 256 * 1024
MAX_TOTAL = 2 * 1024 * 1024
MAX_DOCUMENTS = 100
MAX_HISTORY = 200
MAX_FACTS = 500
MAX_MATCHES = 100
LABELS = {
    'task':'tasks', 'tasks':'tasks', '任务':'tasks',
    'thread':'threads', 'threads':'threads', '线程':'threads',
    'session':'sessions', 'sessions':'sessions', '会话':'sessions',
    'attempt':'attempts', 'attempts':'attempts', '回合':'attempts',
    'goal':'goal', '目标':'goal', 'completion conditions':'conditions', '完成条件':'conditions',
    'result':'result', '成果':'result', '结论':'result', 'decision':'decision', '决策':'decision',
    'risk':'risk', '风险':'risk', 'gap':'gap', '缺口':'gap',
    'project':'project', '项目':'project', 'revision':'revision', '修订':'revision',
}


def native_write(function):
    @wraps(function)
    def call(self,*args,**kwargs):
        try:
            if self.s._failed or not self.s._write:raise TransactionAborted('Native writes require an active writable unit')
            return function(self,*args,**kwargs)
        except BaseException:
            self.s._failed=True
            raise
    return call


def norm(value):
    return re.sub(r'\s+', ' ', value).strip().casefold()


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def split_documents(parsed):
    """JSON documents and Markdown level-one sections; no filename semantics."""
    if parsed['format'] == 'json':
        return [dict(title=d['title'],text=d['text'],locator={'kind':'json-pointer',
                    'pointer':f'/documents/{i}/text','document_id':d['id'],
                    'references':d.get('references',[])}) for i,d in enumerate(parsed['protocol']['documents'])]
    text = parsed['text']
    lines = text.splitlines(keepends=True)
    starts = [i for i,line in enumerate(lines) if re.match(r'^#\s+\S',line)] if parsed['format']=='markdown' else []
    if not starts or starts[0] != 0:
        starts.insert(0,0)
    docs=[]
    for i,start in enumerate(starts):
        end=starts[i+1] if i+1<len(starts) else len(lines)
        body=''.join(lines[start:end])
        title=re.sub(r'^#+\s*','',lines[start]).strip() if start<len(lines) else 'Untitled'
        raw_text=body
        if parsed['format']=='html':
            # Visible text alone is lossy: [AB,C] and [A,BC] both become ABC.
            # Preserve meaningful heading/cell boundaries in the immutable body
            # and hence the dedup/version identity. Source lines stay locators,
            # so harmless source-line movement does not alter content identity.
            structure=dict(headings=[dict(level=h['level'],text=h['text']) for h in parsed['headings']],
                           tables=[t['rows'] for t in parsed['tables']])
            body+='\n\n[Native HTML structure/1]\n'+canonical(structure)
        # Plain text first line is a content title, not a filesystem identity.
        docs.append(dict(title=title[:512] or 'Untitled',text=body,scan_text=raw_text,
                         html_headings=parsed.get('headings',[]),html_tables=parsed.get('tables',[]),
                         locator={'kind':'html-text-line' if parsed['format']=='html' else 'line',
                                  'first':start+1,'last':end,
                                  'source_headings':parsed.get('headings',[]) if parsed['format']=='html' else []}))
    return docs


def findings(document):
    declarations={k:[] for k in ('tasks','sessions','threads','attempts','project','revision')}
    facts=[]; sections=[]; goals=[]; conditions=[]; flags=[]
    for i,line in enumerate(document.get('scan_text',document['text']).splitlines(),1):
        clean=re.sub(r'^\s*(?:[-*+]\s+|#+\s*)','',line).strip()
        heading=re.match(r'^\s*(#{1,6})\s+(.+)',line)
        if heading:sections.append(dict(title=heading[2],line=i))
        pair=re.match(r'^([^:：=]{1,100})\s*[:：=]\s*(\S.*)$',clean)
        if not pair:continue
        key,value=norm(pair[1]),pair[2].strip()
        label=LABELS.get(key)
        fact=dict(key=key,value=value,line=i,kind=label or 'fact')
        facts.append(fact)
        if label in declarations:
            declarations[label].extend(dict(value=v.strip(),line=i) for v in re.split(r'[;；]',value) if v.strip())
        if label=='goal':goals.append(value)
        if label=='conditions':conditions.append(value)
        if label in ('risk','gap'):flags.append(f'{label}: {value}')
    for i,h in enumerate(document.get('html_headings',[])):
        sections.append(dict(title=h['text'],level=h['level'],source_line=h['line'],pointer=f'/headings/{i}'))
    for i,table in enumerate(document.get('html_tables',[])):
        for row,cells in enumerate(table['rows']):
            for column,value in enumerate(cells):
                if len(facts)>=MAX_FACTS:raise ChangeError('native_structure_limit')
                facts.append(dict(key=f'html.table[{i}].row[{row}].column[{column}]',value=value,kind='fact',
                    locator=dict(pointer=f'/tables/{i}/rows/{row}/{column}',source_line=table['line'],table=i,row=row,column=column)))
    if len(facts)>MAX_FACTS or len(sections)>MAX_FACTS or any(len(v)>MAX_MATCHES for v in declarations.values()):
        raise ChangeError('native_structure_limit')
    return dict(declarations=declarations,facts=facts,sections=sections,goal='\n'.join(goals),
                completion_conditions='\n'.join(conditions),flags=flags,
                evidence_status='unverified-imported-claims')


def signatures(text):
    # Fixed-size linear scan, bounded document size; no quadratic edit-distance.
    tokens=re.findall(r'[\w]+|[^\w\s]',norm(text))
    if len(tokens)>40000:raise ChangeError('native_token_limit')
    return {tuple(tokens[i:i+3]) for i in range(max(1,len(tokens)-2))}


def similarity(a,b):
    return len(a&b)/len(a|b) if a|b else 1.0


def fact_conflicts(left,right):
    ignored={'tasks','sessions','attempts','project','revision','goal','conditions','risk','gap'}
    a={};b={}
    for rows,dest in ((left,a),(right,b)):
        for f in rows:
            if f['kind'] not in ignored:dest.setdefault(f['key'],set()).add(norm(f['value']))
    return [dict(key=k,left=sorted(a[k]),right=sorted(b[k])) for k in sorted(a.keys()&b.keys()) if a[k]!=b[k]]


def ambiguous_pairs(matches):
    return len(matches['sessions'])>1 and (len(matches['tasks'])>1 or len(matches['attempts'])>1)


class Native:
    """SQLite-only candidate preparation and append-only human corrections."""
    def __init__(self,store):
        self.s=store;self.c=store._connection

    def head(self,project,table,key,value):
        self.s.project(project)
        if (table,key) not in (('native_relations','version_id'),('native_decisions','document_id')):
            raise ChangeError('invalid_native_chain')
        row=self.c.execute(f'''SELECT o.* FROM {table} o WHERE o.project_id=? AND o.{key}=?
            AND NOT EXISTS(SELECT 1 FROM {table} n WHERE n.project_id=o.project_id AND n.supersedes_id=o.id)''',
            (project,value)).fetchone()
        return dict(row) if row else None

    def relation(self,project,version):
        return self.head(project,'native_relations','version_id',version)

    def decision(self,project,document):
        return self.head(project,'native_decisions','document_id',document)

    def match(self,project,title,f):
        p=self.s.project(project)
        result={k:[] for k in ('tasks','sessions','attempts')};pending=[];basis=[]
        for claim in f['declarations']['project']:
            if norm(claim['value']) not in (norm(p['id']),norm(p['title'])):
                pending.append(dict(kind='project',claim=claim,reason='different-project-claim'))
        for kind in result:
            rows=self.s.records(project,kind)
            if kind=='tasks':
                # Formal titles can change; base records are immutable identity only.
                current={t['task_id']:t for t in self.s.formal_state(project)['tasks']}
                rows=[dict(r,title=current.get(r['id'],r)['title']) for r in rows]
            claims=f['declarations'][kind]
            if kind=='sessions':claims=claims+f['declarations'].get('threads',[])
            if kind=='tasks' and not claims:
                claims=[dict(value=re.sub(r'^(?:task|任务)\s+','',title,flags=re.I),line=1,implicit=True)]
            for claim in claims:
                value=claim['value'];matches=[r for r in rows if value==r['id'] or
                    (r['namespace'] is not None and value==r['namespace']+'::'+r['external_id']) or (kind=='tasks' and not re.fullmatch(r'[A-Za-z]+[-_]?\d+',value) and norm(value)==norm(r['title']))]
                if len(matches)==1:
                    result[kind].append(matches[0]['id']);basis.append(dict(kind=kind,id=matches[0]['id'],claim=claim,
                        rule='project-scoped-stable-identity' if kind!='tasks' or value==matches[0]['id'] or '::' in value else 'task-title-suggestion'))
                elif not claim.get('implicit') or len(matches)>1:
                    pending.append(dict(kind=kind,claim=claim,reason='ambiguous' if matches else 'unresolved',options=[m['id'] for m in matches]))
            result[kind]=sorted(set(result[kind]))
        from .native_threads import naming_conflict
        if naming_conflict(self.s,project,f):pending.append(dict(kind='sessions',reason='thread-session-naming-conflict'))
        for attempt_id in result['attempts']:
            a=self.s.get(project,'attempts',attempt_id)
            if a['task_id'] not in result['tasks']:
                pending.append(dict(kind='attempts',id=attempt_id,reason='attempt-task-not-matched'))
        if ambiguous_pairs(result):
            pending.append(dict(kind='contributions',reason='contribution-pairs-ambiguous'))
        # Explicit declarations are a unit: partial attribution of a conflicting
        # report is unsafe. Keep all suggestions inspectable but do not propose effects.
        return dict(**result,contributions=[] if pending else self.pairs(project,result),pending=pending,basis=basis,status='pending' if pending else ('matched' if result['tasks'] else 'project-reference'))

    def pairs(self,project,matches):
        pairs=[]
        if not any(matches[k] for k in ('tasks','sessions','attempts')):return pairs
        for task in matches['tasks'] or [None]:
            attempts=[a for a in matches['attempts'] if self.s.get(project,'attempts',a)['task_id']==task] or [None]
            for attempt in attempts:
                for session in matches['sessions'] or [None]:
                    pairs.append(dict(task_id=task,session_id=session,attempt_id=attempt))
        return pairs

    def validate_matches(self,project,matches):
        from .native_threads import compatible_matches
        matches=compatible_matches(matches)
        exact(matches,('tasks','sessions','attempts'),('contributions',))
        for kind in ('tasks','sessions','attempts'):
            ids=matches[kind]
            if not isinstance(ids,list) or len(ids)>MAX_MATCHES or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):
                raise ChangeError('invalid_native_matches')
            for identity in ids:self.s.get(project,kind,identity)
        for identity in matches['attempts']:
            if self.s.get(project,'attempts',identity)['task_id'] not in matches['tasks']:
                raise ChangeError('attempt_task_mismatch')
        pairs=matches.get('contributions')
        if pairs is None or pairs==[]:
            if ambiguous_pairs(matches):raise ChangeError('native_contribution_pairs_required')
            pairs=self.pairs(project,matches)
        if not isinstance(pairs,list) or len(pairs)>2*MAX_MATCHES:raise ChangeError('invalid_native_contributions')
        seen=set()
        for pair in pairs:
            exact(pair,('task_id','session_id','attempt_id'),('duty_version_id',))
            if any(v is not None and not isinstance(v,str) for v in pair.values()):raise ChangeError('invalid_native_contributions')
            if pair.get('duty_version_id') is not None:
                duty=self.s.get(project,'thread_duties',pair['duty_version_id'])
                if duty['session_id']!=pair['session_id'] or duty['status']!='confirmed':raise ChangeError('inapplicable_contribution_duty')
            if any(v is not None and not isinstance(v,str) for v in pair.values()):raise ChangeError('invalid_native_contributions')
            if (pair['task_id'] is not None and pair['task_id'] not in matches['tasks']) or (pair['task_id'] is None and matches['tasks']) or (pair['session_id'] is not None and pair['session_id'] not in matches['sessions']) or (pair['attempt_id'] is not None and pair['attempt_id'] not in matches['attempts']):
                raise ChangeError('native_contribution_outside_selection')
            if pair['attempt_id'] is not None and self.s.get(project,'attempts',pair['attempt_id'])['task_id']!=pair['task_id']:
                raise ChangeError('attempt_task_mismatch')
            key=canonical(pair)
            if key in seen:raise ChangeError('duplicate_native_contribution')
            seen.add(key)
        for key,kind in (('task_id','tasks'),('session_id','sessions'),('attempt_id','attempts')):
            if set(matches[kind])-{p[key] for p in pairs}:raise ChangeError('native_contribution_selection_incomplete')
        return dict(**{k:sorted(matches[k]) for k in ('tasks','sessions','attempts')},contributions=sorted(pairs,key=canonical),
                    pending=[],basis=[],status='matched' if matches['tasks'] else 'project-reference')

    @native_write
    def extract(self,project,item,input_row,attempt,parsed):
        old=self.c.execute('''SELECT id FROM native_runs WHERE project_id=? AND input_id=?
            AND processor=? AND parsed_sha256=?''',(project,input_row['id'],PROCESSOR,attempt['result_sha256'])).fetchone()
        if old:return self.run(project,old[0])
        docs=split_documents(parsed)
        if not 1<=len(docs)<=MAX_DOCUMENTS:raise ChangeError('native_document_count_limit')
        sizes=[len(d['text'].encode('utf-8')) for d in docs]
        if max(sizes)>MAX_DOCUMENT or sum(sizes)>MAX_TOTAL:raise ChangeError('native_content_limit')
        # Bound all comparison bodies before loading them into Python.
        history=self.c.execute('''SELECT id,length(CAST(content AS BLOB)) AS size FROM artifact_versions
            WHERE project_id=? ORDER BY created_at,id''',(project,)).fetchall()
        if len(history)+len(docs)>MAX_HISTORY:raise ChangeError('native_history_limit')
        if any(r['size']>MAX_DOCUMENT for r in history):raise ChangeError('native_comparison_content_limit')
        pool=self.s.records(project,'artifact_versions')
        cache={v['id']:signatures(v['content']) for v in pool}
        titles={a['id']:a['title'] for a in self.s.records(project,'artifacts')}
        previous_findings={}
        for d in self.s.records(project,'native_documents'):
            previous_findings.setdefault(d['version_id'],json.loads(d['findings_json']))
        run=self.s._insert(project,'native_runs',item_id=item,input_id=input_row['id'],source_id=attempt['source_id'],
            processor=PROCESSOR,parsed_sha256=attempt['result_sha256'])
        for position,d in enumerate(docs):
            f=findings(d);sig=signatures(d['text']);fingerprint=sha(d['text'])
            duplicate=next((v for v in pool if v['content_sha256']==fingerprint),None)
            related=[];revisions=[]
            for v in pool:
                score=similarity(sig,cache[v['id']]);same_title=norm(titles[v['artifact_id']])==norm(d['title'])
                vf=previous_findings.get(v['id'])
                if vf is None:vf=findings(dict(text=v['content']))
                conflict=fact_conflicts(f['facts'],vf['facts'])
                if same_title or score>=.35:
                    related.append(dict(version_id=v['id'],similarity=round(score,4),same_title=same_title,
                        kind='same-content' if fingerprint==v['content_sha256'] else 'conflict' if conflict else
                             'complementary' if same_title and f['facts'] and vf['facts'] and score<.8 else 'similar',
                        conflicts=conflict))
                if same_title and score>=.8 and len(sig)>=8 and fingerprint!=v['content_sha256']:
                    revisions.append((score,v))
            if duplicate:
                version=duplicate
            else:
                revisions.sort(key=lambda x:(-x[0],x[1]['created_at'],x[1]['ordinal']))
                families={self.relation(project,v['id'])['family_id'] if self.relation(project,v['id']) else v['artifact_id'] for score,v in revisions}
                parent=revisions[0][1] if revisions and len(families)==1 else None
                family=(self.relation(project,parent['id']) or {}).get('family_id',parent['artifact_id']) if parent else None
                # Physical artifact identity is immutable. Native family correction
                # is an overlay, never an UPDATE of a version's body or artifact_id.
                artifact=self.s.get(project,'artifacts',family) if family else self.s.create_artifact(project,d['title'])
                titles[artifact['id']]=artifact['title']
                version=self.s.create_version(project,artifact['id'],d['text'],reason=PROCESSOR+' sourced extraction',source_ids=[attempt['source_id']])
                self.s._insert(project,'native_relations',version_id=version['id'],family_id=artifact['id'],
                    parent_version_id=parent['id'] if parent else None,relation='revision' if parent else 'initial',supersedes_id=None,
                    basis_json=canonical(dict(rule='same-title-trigram-jaccard>=0.80; unique-family' if parent else 'new-or-ambiguous-family',
                                              comparisons=related)))
                pool.append(version);cache[version['id']]=sig
                previous_findings[version['id']]=f
            f['related']=related
            f['duplicate_content']=duplicate is not None
            locator=dict(d['locator'],input_id=input_row['id'],input_sha256=input_row['fingerprint'],
                         parsed_sha256=attempt['result_sha256'],content_sha256=fingerprint,source_id=attempt['source_id'])
            doc=self.s._insert(project,'native_documents',run_id=run['id'],position=position,version_id=version['id'],title=d['title'],
                               locator_json=canonical(locator),findings_json=canonical(f))
            from .native_threads import establish_identities
            establish_identities(self.s,project,f)
            matches=self.match(project,d['title'],f)
            self.s._insert(project,'native_decisions',document_id=doc['id'],base_revision=self.s.project(project)['revision'],
                           matches_json=canonical(matches),basis='Automatic rules; imported claims are unverified.',supersedes_id=None)
        return self.run(project,run['id'])

    def document(self,project,identity):
        d=self.s.get(project,'native_documents',identity)
        decision=self.decision(project,identity)
        from .native_threads import suggestions
        return dict(d,suggestions=suggestions(self,project,d,decision),locator=json.loads(d['locator_json']),findings=json.loads(d['findings_json']),
                    decision=dict(decision,matches=json.loads(decision['matches_json'])),
                    relation=self.relation(project,d['version_id']),
                    proposals=sorted([r for r in self.s.records(project,'native_proposals') if r['document_id']==identity],key=lambda r:(r['created_at'],r['id'])))

    def run(self,project,identity):
        run=self.s.get(project,'native_runs',identity)
        return dict(run,documents=[self.document(project,d['id']) for d in sorted(self.s.records(project,'native_documents'),key=lambda d:d['position']) if d['run_id']==identity])

    def listing(self,project):
        return dict(processor=PROCESSOR,runs=[self.run(project,r['id']) for r in sorted(self.s.records(project,'native_runs'),key=lambda r:(r['created_at'],r['id']))],
                    groups=self.groups(project),relations=self.s.records(project,'native_relations'),
                    decisions=self.s.records(project,'native_decisions'))

    def groups(self,project):
        # Aggregated display retains every component and independent source.
        groups={}
        for d in self.s.records(project,'native_documents'):
            view=self.document(project,d['id']);m=view['decision']['matches'];r=view['relation']
            key=('tasks',tuple(m['tasks'])) if m['tasks'] and not m['pending'] else ('title',norm(d['title']))
            g=groups.setdefault(key,dict(components=[],facts=[],conflicts=[],status='complementary'))
            g['components'].append(dict(document_id=d['id'],version_id=d['version_id'],locator=view['locator'],
                                       family_id=r['family_id'] if r else self.s.get(project,'artifact_versions',d['version_id'])['artifact_id']))
            for fact in view['findings']['facts']:g['facts'].append(dict(fact,document_id=d['id'],source_id=view['locator']['source_id']))
        for g in groups.values():
            facts=g['facts']
            values={}
            for f in facts:
                if f['kind'] in ('fact','result','decision'):values.setdefault(f['key'],{}).setdefault(norm(f['value']),[]).append(f['document_id'])
            g['conflicts']=[dict(key=k,values=v) for k,v in values.items() if len(v)>1]
            versions={c['version_id'] for c in g['components']}
            meaningful=any(f['kind'] in ('fact','result','decision') for f in facts)
            g['status']='conflict' if g['conflicts'] else ('single' if len(g['components'])==1 else
                'same-content' if len(versions)==1 else 'complementary' if meaningful else 'related-unmerged')
        return list(groups.values())

    def context(self,project,context):
        exact(context,('document_id','decision_id','relation_id'),('suggestion_id',))
        d=self.document(project,context['document_id'])
        if d['decision']['id']!=context['decision_id'] or (d['relation'] or {}).get('id')!=context['relation_id']:
            raise ChangeError('native_context_changed')
        result=dict(decision=d['decision'],relation=d['relation'],safety=self.requirements(project,document_id=d['id']))
        if 'suggestion_id' in context:
            suggestion=next((v for v in d['suggestions'] if v['id']==context['suggestion_id']),None)
            if suggestion is None:raise ChangeError('native_suggestion_stale')
            result['suggestion']=suggestion
        return result

    def requirements(self,project,*,document_id=None,version_id=None,target_id=None,thread_id=None,duty=None):
        """Server-derived minimum review risk, also for manual native-version candidates.

        A caller may add concerns, but cannot suppress known conflicts by
        omitting native_context or supplying an ordinary risk label.
        """
        docs=[self.document(project,d['id']) for d in self.s.records(project,'native_documents')
              if d['id']==document_id or d['version_id']==version_id]
        ids={d['id'] for d in docs};fact_conflicts={};flags=set();constraints=[]
        # Safety dependencies follow stable identity, independently of display
        # grouping. Long-lived Thread duties need not belong to any Task/title.
        threads={t for d in docs for t in d['decision']['matches']['sessions']}
        if thread_id is not None:
            self.s.get(project,'sessions',thread_id)
            threads.add(thread_id)
        from .native_threads import LABELS as DUTY_LABELS
        def duty_value(key,value):
            if key=='auxiliary':return tuple(sorted(norm(v) for v in re.split(r'[;；]',value) if v.strip()))
            return norm(value)
        duty_claims={}
        for doc in docs:
            for fact in doc['findings']['facts']:
                key=DUTY_LABELS.get(fact['key'])
                if key in ('main','auxiliary'):duty_claims.setdefault(key,set()).add(duty_value(key,fact['value']))
        if duty is not None:
            if duty['main'] is not None:duty_claims.setdefault('main',set()).add(duty_value('main',duty['main']))
            duty_claims.setdefault('auxiliary',set()).add(tuple(sorted(norm(v) for v in duty['auxiliary'])))
        dependencies=[]
        for row in self.s.records(project,'native_documents') if threads else []:
            matched=self.decision(project,row['id']);matches=json.loads(matched['matches_json'])
            # Unresolved Task/Attempt attribution does not erase a known Thread
            # risk claim. Ambiguous claims remain unverified, conservatively.
            if not threads.intersection(matches['sessions']):continue
            related=json.loads(row['findings_json']);locator=json.loads(row['locator_json'])
            relevant_flags=set(related['flags'])
            for fact in related['facts']:
                key=DUTY_LABELS.get(fact['key'])
                if key in duty_claims and duty_value(key,fact['value']) not in duty_claims[key]:relevant_flags.add('Conflicting Thread declaration: '+key)
            flags.update(relevant_flags)
            if not relevant_flags:continue
            dependencies.append(dict(document_id=row['id'],decision_id=matched['id'],version_id=row['version_id'],
                source_id=locator['source_id'],flags=sorted(relevant_flags)))
        dependencies.sort(key=lambda v:v['document_id'])
        for g in self.groups(project) if docs else []:
            if any(c['document_id'] in ids for c in g['components']):
                for c in g['conflicts']:fact_conflicts.setdefault(c['key'],set()).update(c['values'])
                for component in g['components']:
                    related=self.s.get(project,'native_documents',component['document_id'])
                    flags.update(json.loads(related['findings_json'])['flags'])
        tasks={t['task_id']:t for t in self.s.formal_state(project)['tasks']} if docs else {}
        for d in docs:
            f=d['findings'];flags.update(f['flags'])
            targets=set(d['decision']['matches']['tasks'])
            if target_id:targets.add(target_id)
            for task in sorted(targets):
                if task not in tasks:continue
                for field,key in (('goal','goal'),('completion_conditions','completion_conditions')):
                    if f[key].strip() and norm(f[key])!=norm(tasks[task][field]):
                        entry=dict(task_id=task,field=field,imported=f[key],formal=tasks[task][field])
                        if entry not in constraints:constraints.append(entry)
        facts=[dict(key=k,values=sorted(v)) for k,v in sorted(fact_conflicts.items())]
        constraints.sort(key=lambda c:(c['task_id'],c['field'],c['imported']))
        conflicts=sorted(flags|{'Conflicting fact: '+f['key'] for f in facts}|
                         {'Imported '+c['field']+' differs from formal task '+c['task_id'] for c in constraints})
        result=dict(conflicts=conflicts,facts=facts,constraints=constraints)
        if threads:result['thread_risk_dependencies']=dependencies
        return result

    @native_write
    def correct(self,project,identity,request):
        exact(request,('base_revision','expected_decision_id','matches','basis'))
        if self.s.project(project)['revision']!=integer(request['base_revision']):raise ChangeError('revision_conflict')
        d=self.document(project,identity)
        if d['decision']['id']!=request['expected_decision_id']:raise ChangeError('native_context_changed')
        m=self.validate_matches(project,request['matches'])
        self.s._insert(project,'native_decisions',document_id=identity,base_revision=request['base_revision'],
                       matches_json=canonical(m),basis=content(request['basis']),supersedes_id=d['decision']['id'])
        return self.document(project,identity)

    @native_write
    def rematch(self,project,identity,request):
        exact(request,('base_revision','expected_decision_id'))
        d=self.document(project,identity)
        if self.s.project(project)['revision']!=integer(request['base_revision']):raise ChangeError('revision_conflict')
        if d['decision']['id']!=request['expected_decision_id']:raise ChangeError('native_context_changed')
        m=self.match(project,d['title'],d['findings'])
        self.s._insert(project,'native_decisions',document_id=identity,base_revision=request['base_revision'],
                       matches_json=canonical(m),basis='Explicit refresh of automatic matching.',supersedes_id=d['decision']['id'])
        return self.document(project,identity)

    @native_write
    def correct_relation(self,project,version,request):
        exact(request,('base_revision','expected_relation_id','family_id','parent_version_id','basis'))
        if self.s.project(project)['revision']!=integer(request['base_revision']):raise ChangeError('revision_conflict')
        v=self.s.get(project,'artifact_versions',version);old=self.relation(project,version)
        if not old or old['id']!=request['expected_relation_id']:raise ChangeError('native_context_changed')
        family=request['family_id'];parent=request['parent_version_id']
        if family is not None:content(family)
        if parent is not None:content(parent)
        if family is None:
            if parent is not None:raise ChangeError('native_parent_without_family')
            family=self.s.create_artifact(project,self.s.get(project,'artifacts',v['artifact_id'])['title'])['id']
        else:self.s.get(project,'artifacts',family)
        if parent is not None:
            pv=self.s.get(project,'artifact_versions',parent);pr=self.relation(project,parent)
            if (pr['family_id'] if pr else pv['artifact_id'])!=family:raise ChangeError('native_parent_family_mismatch')
            seen={version};cursor=parent
            while cursor:
                if cursor in seen:raise ChangeError('native_version_cycle')
                seen.add(cursor);cr=self.relation(project,cursor);cursor=cr['parent_version_id'] if cr else None
        if family!=old['family_id'] and any(r['parent_version_id']==version and
                (self.relation(project,r['version_id']) or {}).get('id')==r['id'] for r in self.s.records(project,'native_relations')):
            raise ChangeError('native_version_has_children')
        self.s._insert(project,'native_relations',version_id=version,family_id=family,parent_version_id=parent,
                       relation='revision' if parent else 'separate',basis_json=canonical({'human_basis':content(request['basis'])}),supersedes_id=old['id'])
        return self.relation(project,version)

    @native_write
    def apply_associations(self,project,spec):
        """Historical contribution links are written only by the reviewed commit.

        These T03 provenance links are not lifecycle/acceptance and are retained
        even when a formal version confirmation is later compensated.
        """
        context=spec.get('native_context')
        if not context:return
        d=self.document(project,context['document_id']);m=d['decision']['matches'];task=spec['target_id']
        if m['pending'] or task not in m['tasks']:raise ChangeError('native_attribution_unresolved')
        for pair in m['contributions']:
            if pair['task_id']!=task or pair['session_id'] is None:continue
            self.s.link_task_session(project,task,pair['session_id'],duty_version_id=pair.get('duty_version_id'))
            if pair['attempt_id'] is not None:self.s.link_attempt_session(project,pair['attempt_id'],pair['session_id'],duty_version_id=pair.get('duty_version_id'))
        same_source=self.c.execute('''SELECT count(*) FROM native_documents d JOIN native_runs r
            ON r.project_id=d.project_id AND r.id=d.run_id WHERE d.project_id=? AND r.source_id=?''',
            (project,d['locator']['source_id'])).fetchone()[0]
        if same_source==1 and len(m['tasks'])==1 and len(m['contributions'])==1:
            source=d['locator']['source_id'];old=self.s.attribution(project,source)
            selected=m['contributions'][0]
            if any(old[k]!=selected[k] for k in ('task_id','session_id','attempt_id')):
                self.s.attribute_source(project,source,**selected,supersedes_id=old['id'],reason='Reviewed native candidate '+context['document_id'])
            elif selected.get('duty_version_id') is not None:
                binding=self.c.execute('SELECT duty_id FROM contribution_duties WHERE project_id=? AND relation_key=?',
                    (project,'source:'+old['id'])).fetchone()
                if not binding or binding['duty_id']!=selected['duty_version_id']:raise ChangeError('contribution_duty_conflict')

    @native_write
    def propose(self,project,identity,request):
        exact(request,('base_revision','expected_decision_id'))
        d=self.document(project,identity);base=integer(request['base_revision'])
        if self.s.project(project)['revision']!=base:raise ChangeError('revision_conflict')
        decision=d['decision'];m=decision['matches'];f=d['findings']
        if decision['id']!=request['expected_decision_id']:raise ChangeError('native_context_changed')
        context=dict(document_id=identity,decision_id=decision['id'],relation_id=(d['relation'] or {}).get('id'))
        initial_conflicts=self.requirements(project,document_id=identity)['conflicts']
        formal=self.s.formal_state(project)
        formal_ids={t['task_id'] for t in formal['tasks']}
        specs=[]
        for task in m['tasks'] if not m['pending'] else []:
            if task not in formal_ids:continue
            if any(r['task_id']==task and r['version_id']==d['version_id'] for r in formal['confirmed_versions']):continue
            specs.append(dict(operation='version.confirm',payload={},target_id=task,target_version_id=d['version_id']))
        # Unmatched explicit task declarations are recovered as minimal candidates
        # only. The saved document is already available even with no task at all.
        # Unknown/ambiguous declarations stay pending until a user chooses a title.
        titles=[]
        if not m['tasks'] and not f['declarations']['tasks'] and re.match(r'^(?:task|任务)\s+\S',d['title'],re.I):
            titles.append(re.sub(r'^(?:task|任务)\s+','',d['title'],flags=re.I))
        # Unknown descriptive task names can form task.create proposals while
        # their source attribution remains unresolved. Opaque IDs never do.
        for pending in m['pending']:
            if pending.get('kind')=='tasks' and pending.get('reason')=='unresolved':
                title=pending['claim']['value']
                if (' ' in title or re.search(r'[\u3400-\u9fff]',title)) and '::' not in title and len(title)<=512:
                    titles.append(title)
        for title in dict.fromkeys(titles):
            payload=dict(title=title,goal=f['goal'],completion_conditions=f['completion_conditions'])
            if not any(all(t[k]==v for k,v in payload.items()) for t in formal['tasks']):specs.append(dict(operation='task.create',payload=payload))
        from .native_threads import actionable
        specs.extend(actionable(self,project,d))
        out=[]
        for spec in specs:
            candidate_context=spec.pop('_context',context)
            required=self.requirements(project,document_id=identity,
                version_id=spec.get('target_version_id'),target_id=spec.get('target_id'))
            conflicts=sorted(set(initial_conflicts+required['conflicts']))
            existing=None
            for row in self.s.records(project,'candidate_specs'):
                c=Changes(self.s).spec(project,row['candidate_id'])
                if spec['operation'] not in ('task.create','version.confirm') and c['spec'].get('native_context')!=candidate_context:continue
                if c['processing'] not in ('superseded','applied') and c['spec'].get('native_context') and c['spec']['base_revision']==base and all(c['spec'].get(k)==v for k,v in spec.items()):
                    # Changed native context or conflict evidence must get a new
                    # reviewed candidate; never recycle a stale approval.
                    if c['spec'].get('conflicts')==conflicts:
                        try:
                            prior=self.context(project,c['spec']['native_context'])
                            if prior!=c['spec']['preconditions']['native']:continue
                            if any(prior['decision']['matches'][k]!=m[k] for k in ('tasks','sessions','attempts','contributions','pending')):continue
                        except ChangeError:continue
                        existing=c;break
            candidate=existing or self.s.save_candidate(project,dict(base_revision=base,source_ids=[d['locator']['source_id']],
                    conflicts=conflicts,impact='Native sourced proposal; confirm exact version and declared Task/Session/Attempt contributions. No authority, applicability or acceptance. Historical contributions remain if confirmation is revoked.',
                    native_context=candidate_context,**spec))
            old=self.c.execute('SELECT 1 FROM native_proposals WHERE project_id=? AND document_id=? AND decision_id=? AND candidate_id=?',
                               (project,identity,decision['id'],candidate['candidate_id'])).fetchone()
            if not old:self.s._insert(project,'native_proposals',document_id=identity,decision_id=decision['id'],candidate_id=candidate['candidate_id'])
            out.append(candidate)
        return dict(status='saved' if out else 'pending-attribution' if m['pending'] else 'reference-or-already-confirmed',candidates=out,pending=m['pending'])


class NativeService:
    """Use T07's verified format output; disk IO outside the SQLite write lock."""
    def __init__(self,importer):
        self.importer=importer

    def extract_item(self,project,item,*,base_revision,finish=None):
        imp=self.importer
        # Snapshot exact input and output identity, then recheck under write lock.
        before=imp.item(project,item);a=before['latest']
        if not a or a['parse_status']!='parsed':raise ChangeError('parsed_result_unavailable')
        parsed=imp.read_parsed(project,item)
        if sha(encoded(parsed).decode('utf-8'))!=a['result_sha256']:raise ChangeError('parsed_result_changed')
        with unit_of_work(imp.database,imp.principal,write=True) as s:
            def operation():
                if s.project(project)['revision']!=integer(base_revision):raise ChangeError('revision_conflict')
                current=s._connection.execute('SELECT * FROM ingest_attempts WHERE project_id=? AND item_id=? ORDER BY ordinal DESC LIMIT 1',(project,item)).fetchone()
                if current['id']!=a['id']:raise ChangeError('native_input_changed')
                input_row=s.get(project,'ingest_inputs',a['input_id'])
                if parsed['source_sha256']!=input_row['fingerprint']:raise ChangeError('parsed_result_changed')
                native=Native(s);run=native.extract(project,item,input_row,a,parsed)
                for d in run['documents']:
                    native.propose(project,d['id'],dict(base_revision=base_revision,expected_decision_id=d['decision']['id']))
                return native.run(project,run['id'])
            result=finish(s,operation) if finish else operation()
        return result
