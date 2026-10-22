"""Run with python -m examples.t05_synthetic. All decisions here are synthetic inputs."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from nextrelay.auth import Principal
from nextrelay.changes import Changes
from nextrelay.db import initialize
from nextrelay.store import unit_of_work


def main():
    with TemporaryDirectory(prefix='nextrelay-t05-example-') as folder:
        database = Path(folder)/'synthetic.sqlite3'
        initialize(database)
        owner = Principal('dev-example')
        with unit_of_work(database,owner,write=True) as s:
            project=s.create_project('Synthetic T05 example')['id']

        def effect(operation, payload, task=None, version=None):
            with unit_of_work(database,owner,write=True) as s:
                request=dict(base_revision=s.project(project)['revision'],operation=operation,payload=payload)
                if task:request['target_id']=task
                if version:request['target_version_id']=version
                c=s.save_candidate(project,request)
                review=dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint'])],
                            decision='approve',mode='explicit' if c['risk']!='ordinary' else 'ordinary',
                            basis='Synthetic demonstration input, not real business approval',input_origin='synthetic-test')
                if review['mode']=='explicit':review['authorization']=Changes(s).authorization(c)
                r=s.review_candidates(project,review)[0]
                s.commit_candidates(project,dict(request_key=str(uuid4()),base_revision=c['spec']['base_revision'],
                    selection=[dict(candidate_id=c['candidate_id'],review_id=r['id'])]))
                return c['target_id']

        task=effect('task.create',dict(title='Synthetic report',completion_conditions='JSON field status equals ok'))
        with unit_of_work(database,owner,write=True) as s:
            artifact=s.create_artifact(project,'report.json')['id']
            version=s.create_version(project,artifact,'{"status":"ok"}',reason='synthetic initial result',task_ids=(task,))['id']
        effect('version.confirm',{},task,version)
        effect('task.submit',dict(basis='Synthetic external result, no invented start event'),task,version)
        config=dict(protocol='builtin-v1',type='json-object',rules=dict(required=['status'],equals=dict(status='ok')))
        effect('check.authorize',dict(config=config,expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
            scope='accept-exact-version',basis='Synthetic authorization for these declared JSON constraints only'),task,version)
        with unit_of_work(database,owner,write=True) as s:
            grant=s.formal_state(project)['authorizations'][0]
            execution=s.run_check(project,task,version,config)
        with unit_of_work(database,owner,write=True) as s:
            request=dict(request_key='synthetic-auto-example',base_revision=s.project(project)['revision'],
                         task_id=task,version_id=version,check_id=execution['id'],authorization_id=grant['id'])
            result=s.accept_pre_authorized(project,request)
        with unit_of_work(database,owner,write=True) as s:
            assert s.accept_pre_authorized(project,request)==result
        with unit_of_work(database,owner) as s:
            state=s.formal_state(project)
            current=state['derived']['tasks'][0]
            assert current['lifecycle']=='accepted' and current['validity']=='applicable'
            assert [e['event'] for e in state['events']]==['submit','accept']
            print('Synthetic T05 example verified; schema v4; revision',state['project']['revision'])
            print('Check scope: declared JSON fields only; readiness:',state['readiness'])


if __name__=='__main__':main()
