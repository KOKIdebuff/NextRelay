"""Explicit synthetic fixture through existing services; NEVER file extraction."""
import argparse
import json
from uuid import uuid4

from nextrelay.auth import Principal
from nextrelay.changes import Changes
from nextrelay.config import load_settings
from nextrelay.store import unit_of_work


def seed_fixture(database, principal, project):
    def apply(operation,payload,**targets):
        with unit_of_work(database,principal,write=True) as s:
            c=s.save_candidate(project,dict(operation=operation,payload=payload,base_revision=s.project(project)['revision'],**targets))
        with unit_of_work(database,principal,write=True) as s:
            request=dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint'])],
                         decision='approve',mode='explicit' if c['risk']!='ordinary' else 'ordinary',
                         basis='SYNTHETIC FIXTURE ONLY; not parsed from files',input_origin='synthetic-test')
            if c['risk']!='ordinary':request['authorization']=Changes(s).authorization(c)
            r=s.review_candidates(project,request)[0]
        with unit_of_work(database,principal,write=True) as s:
            result=s.commit_candidates(project,dict(request_key='synthetic-'+str(uuid4()),base_revision=c['spec']['base_revision'],selection=[dict(candidate_id=c['candidate_id'],review_id=r['id'])]))
        return result['changes'][0]['target_id']
    with unit_of_work(database,principal) as s:
        p=s.project(project)
        if p['revision']!=0 or s.records(project,'sources') or s.records(project,'ingest_batches'):
            raise ValueError('Fixture requires a newly created empty synthetic project; never overwrite existing data')
    first=apply('task.create',{'title':'合成夹具 A · 精确版本已验收','goal':'验证真实适配器状态映射','completion_conditions':'人工核对合成成果精确版本'})
    second=apply('task.create',{'title':'合成夹具 B · 待人工验收','goal':'验证依赖与人工验收','completion_conditions':'核对来源、版本及依赖状态'})
    versions=[]
    for tid,label in ((first,'A'),(second,'B')):
        with unit_of_work(database,principal,write=True) as s:
            source=s.create_source(project,reference='synthetic://t11-fixture/'+label,fingerprint='synthetic-fixture-'+label,
                metadata={'synthetic':True,'origin':'explicit fixture; NOT file parsing'})
            a=s.create_artifact(project,'合成夹具成果 '+label+'.md')
            v=s.create_version(project,a['id'],f'# SYNTHETIC FIXTURE {label}\n此候选与成果由测试服务明确创建，非真实文件解析。\n\n精确版本正文。\n'+('\n合成长文阅读验证。'*60),reason='SYNTHETIC FIXTURE ONLY',source_ids=[source['id']])
            s.attribute_source(project,source['id'],task_id=tid,supersedes_id=s.attribution(project,source['id'])['id'],reason='Synthetic task attribution; Session/Attempt unknown')
        versions.append(v['id'])
        apply('version.confirm',{},target_id=tid,target_version_id=v['id'])
    apply('task.start',{'basis':'synthetic start'},target_id=first)
    apply('task.submit',{'basis':'synthetic submit'},target_id=first,target_version_id=versions[0])
    apply('acceptance.human',{'decision':'accept','basis':'synthetic fixture human decision'},target_id=first,target_version_id=versions[0])
    apply('dependency.add',{'predecessor_id':first,'basis':'synthetic dependency'},target_id=second)
    with unit_of_work(database,principal) as s:
        reasons=next(t for t in s.formal_state(project)['derived']['tasks'] if t['task_id']==second)['review_reasons']
    for reason in reasons:
        apply('recheck.resolve',{'reason_id':reason['id'],'decision':'continue','basis':'synthetic review of added dependency'},target_id=second,target_version_id=reason['version_id'])
    apply('task.start',{'basis':'synthetic start'},target_id=second)
    apply('task.submit',{'basis':'synthetic submit'},target_id=second,target_version_id=versions[1])
    with unit_of_work(database,principal,write=True) as s:
        pending=s.save_candidate(project,dict(operation='task.create',base_revision=s.project(project)['revision'],
            payload={'title':'合成候选 C · 非文件提取','goal':'验证独立审查与正式提交','completion_conditions':'明确人工确认'},
            impact='SYNTHETIC FIXTURE ONLY; not derived from uploaded files'))
    return dict(project_id=project,first=first,second=second,versions=versions,candidate_id=pending['candidate_id'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True,help='New empty synthetic project ID, created from the page')
    args=parser.parse_args();settings=load_settings()
    print(json.dumps(seed_fixture(settings.database,Principal(settings.subject),args.project),ensure_ascii=False))
