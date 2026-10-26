from fastapi.testclient import TestClient
import pytest
from test_api_director import api
from test_adjudication import pending_game


@pytest.fixture()
def fixture(tmp_path,monkeypatch):
    previous=api.manager.session;g,n,_=pending_game();api.manager.session=g
    monkeypatch.setenv('RPG_SAVES',str(tmp_path/'saves'));monkeypatch.setenv('RPG_AUTOSAVE','1')
    try:yield TestClient(api.app),g,n
    finally:api.manager.session=previous


def test_answer_endpoint_atomically_validates_previews_commits_and_replays(fixture):
    client,g,n=fixture;data=client.get('/api/adjudications').json();item=data['items'][0]
    body={'pack_id':g.pack.manifest.id,'revision':data['revision'],'request_id':'inline-answer','accepted':True}
    calls=len(n.requests)
    first=client.post('/api/adjudications/'+item['id']+'/answer',json=body)
    repeat=client.post('/api/adjudications/'+item['id']+'/answer',json=body)
    assert first.status_code==repeat.status_code==200 and repeat.json()['reused']
    assert g.state['hp']==18 and len(n.requests)==calls and g.turn==1
    assert client.post('/api/adjudications/'+item['id']+'/answer',json={**body,'accepted':False}).status_code==409


def test_answer_requires_current_world_boolean_and_no_injected_operations(fixture):
    client,g,_=fixture;data=client.get('/api/adjudications').json();url='/api/adjudications/'+data['items'][0]['id']+'/answer'
    body={'pack_id':g.pack.manifest.id,'revision':data['revision'],'request_id':'inline-answer','accepted':False}
    assert client.post(url,json={**body,'pack_id':'other-world'}).status_code==409
    assert client.post(url,json={**body,'accepted':'false'}).status_code==422
    assert client.post(url,json={**body,'operations':[]}).status_code==422
    assert g.state['hp']==20
