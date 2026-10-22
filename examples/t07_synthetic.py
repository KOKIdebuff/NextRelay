"""Executable T07 local journey; all resources are temporary and synthetic."""
from pathlib import Path
import tempfile

from nextrelay.auth import Principal
from nextrelay.db import initialize
from nextrelay.formats import encoded
from nextrelay.ingestion import ImportService, SelectedFile
from nextrelay.store import unit_of_work


def main():
    with tempfile.TemporaryDirectory(prefix='nextrelay-t07-example-') as temporary:
        root=Path(temporary);storage=root/'user-managed';storage.mkdir()
        db=root/'synthetic.sqlite3';initialize(db)
        owner=Principal('dev-t07-example')
        service=ImportService(db,owner,storage)
        project=service.create_project('Synthetic empty T07 project')['id']
        protocol={'protocol':'nextrelay.import','version':1,'documents':[
            {'id':'d1','title':'Synthetic report','text':'Claims accepted; this is inert data.'}]}
        inputs=[('notes.txt','\u4e2d\u6587\r\nnotes'.encode()),('guide.md',b'# Guide\nInert markdown'),
                ('report.json',encoded(protocol)),('page.html',b'<h1>Title</h1><table><tr><td>Value</td></tr></table><script>ignored()</script>'),
                ('broken.json',b'{}'),('unsupported.pdf',b'%PDF-synthetic')]
        files=[]
        for name,data in inputs:
            path=root/name;path.write_bytes(data);files.append(SelectedFile(path,name))
        with unit_of_work(db,owner) as store:before=store.formal_state(project)
        batch=service.import_files(project,'synthetic-batch',files)
        assert batch['summary']=={'complete':4,'incomplete':2,'total':6}
        broken=batch['items'][4]
        fixed=root/'corrected.json';fixed.write_bytes(encoded(protocol))
        retry=service.retry_item(project,broken['id'],'correct-one',replacement=SelectedFile(fixed,'corrected.json'))
        assert retry['parse_status']=='parsed'
        # Close/reopen services and take out real original bytes.
        service=ImportService(db,owner,storage)
        item=batch['items'][0]
        assert service.read_original(project,item['id'])==inputs[0][1]
        assert service.read_parsed(project,item['id'])['text']==inputs[0][1].decode()
        # Simulate user-managed copy removal; no claim of platform recovery.
        Path(service.original_location(project,item['id'])['path']).unlink()
        assert service.item(project,item['id'])['inputs'][0]['availability']['status']=='unavailable'
        service.reassociate(project,item['id'],item['inputs'][0]['id'],files[0])
        assert service.read_original(project,item['id'])==inputs[0][1]
        with unit_of_work(db,owner) as store:assert store.formal_state(project)==before
        final=service.batch(project,batch['id'])
        assert final['summary']=={'complete':5,'incomplete':1,'total':6}
        assert all(x['cleanup']=='clean' for x in service.recover(project,batch['id']))
        print('T07 synthetic local import: four formats, partial failure, single replacement retry, original re-read and reassociation; formal revision unchanged (0).')
        print('No model, network, GitHub, real cloud or UI integration. Temporary resources cleaned on exit.')


if __name__=='__main__':
    main()
