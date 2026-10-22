"""Executable T06 example. Synthetic decisions only; uses a fresh temporary DB."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from nextrelay.auth import Principal
from nextrelay.changes import Changes
from nextrelay.db import initialize
from nextrelay.store import unit_of_work


def main():
    with TemporaryDirectory(prefix='nextrelay-t06-example-') as folder:
        database=Path(folder)/'synthetic.sqlite3'
        initialize(database)
        owner=Principal('dev-t06-example')
        with unit_of_work(database,owner,write=True) as s:
            project=s.create_project('Synthetic single compensation example')['id']

        def prepare(operation,payload,target=None):
            with unit_of_work(database,owner,write=True) as s:
                request=dict(base_revision=s.project(project)['revision'],operation=operation,payload=payload)
                if target is not None:request['target_id']=target
                return s.save_candidate(project,request)

        def commit(candidates,key):
            selected=[]
            for c in candidates:
                # Synthetic input is not a real user's business approval.
                with unit_of_work(database,owner,write=True) as s:
                    request=dict(selection=[dict(candidate_id=c['candidate_id'],fingerprint=c['fingerprint'])],
                                 decision='approve',mode='explicit' if c['risk']!='ordinary' else 'ordinary',
                                 basis='Synthetic protocol demonstration only',input_origin='synthetic-test')
                    if request['mode']=='explicit':request['authorization']=Changes(s).authorization(c)
                    r=s.review_candidates(project,request)[0]
                    selected.append(dict(candidate_id=c['candidate_id'],review_id=r['id']))
            request=dict(request_key=key,base_revision=candidates[0]['spec']['base_revision'],selection=selected)
            with unit_of_work(database,owner,write=True) as s:result=s.commit_candidates(project,request)
            return request,result

        x=prepare('task.create',dict(title='Synthetic X',goal='Original goal'))
        y=prepare('task.create',dict(title='Synthetic Y'))
        original_request,original=commit([x,y],'synthetic-batch')
        update=prepare('task.update',dict(title='Mistaken title'),x['target_id'])
        _,updated=commit([update],'synthetic-title')
        # A later independent field must survive the single title correction.
        goal=prepare('task.update',dict(goal='Later approved synthetic goal'),x['target_id'])
        commit([goal],'synthetic-goal')
        with unit_of_work(database,owner,write=True) as s:
            preview=s.preview_reversal(project,updated['changes'][0]['change_id'])
        reversal=prepare('change.revoke',dict(preview_id=preview['id']),preview['original_change_id'])
        request,result=commit([reversal],'synthetic-reversal')
        with unit_of_work(database,owner,write=True) as s:
            assert s.commit_candidates(project,request)==result
            assert s.commit_candidates(project,original_request)==original
            state=s.formal_state(project)
            by_id={t['task_id']:t for t in state['tasks']}
            assert by_id[x['target_id']]['title']=='Synthetic X'
            assert by_id[x['target_id']]['goal']=='Later approved synthetic goal'
            assert by_id[y['target_id']]['title']=='Synthetic Y'
            assert len(state['corrections'])==1
            assert state['project']['revision']==state['derived']['revision']==result['revision']
            print('Synthetic T06 verified: single effect corrected, Y/later goal/history preserved; revision:',result['revision'])
            print('Readiness:',state['readiness'],'; no real business approval, T11 or T12 integration.')


if __name__=='__main__':
    main()
