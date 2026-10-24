import json
import pytest
from fastapi.testclient import TestClient
from test_api_director import api
from test_corrections import game,response,body
from rpg_core.saves import read_save

@pytest.fixture()
def fixture(tmp_path,monkeypatch):
    previous=api.manager.session
    g,p=game(response([{'field':'hp','value':18,'evidence':'体力'}]));api.manager.session=g
    monkeypatch.setenv('RPG_SAVES',str(tmp_path/'saves'));monkeypatch.setenv('RPG_AUTOSAVE','1')
    try:yield TestClient(api.app),g,p
    finally:api.manager.session=previous

def test_api_correction_is_saved_repeated_once_and_reversible(fixture):
    c,g,p=fixture;request=body(g).model_dump(mode='json')
    a=c.post('/api/corrections',json=request);assert a.status_code==200,a.text
    result=a.json();assert result['status']['state']['hp']==18 and result['status']['turn']==0
    b=c.post('/api/corrections',json=request);assert b.status_code==200 and b.json()['reused']
    assert len(p.requests)==1 and read_save('auto')['state']['hp']==18
    undo=c.post('/api/corrections/undo',json={'pack_id':g.pack.manifest.id,'receipt_id':result['receipt_id']})
    assert undo.status_code==200 and undo.json()['status']['state']['hp']==20
    assert c.post('/api/corrections',json=request).status_code==409

def test_stream_transmits_final_authoritative_status(fixture):
    c,g,_=fixture
    r=c.post('/api/corrections/stream',json=body(g).model_dump(mode='json'))
    assert r.status_code==200 and 'event: result' in r.text
    results=[json.loads(part.split('data: ',1)[1]) for part in r.text.split('\n\n') if part.startswith('event: result')]
    assert results[0]['status']['state']['hp']==18 and results[0]['status']['correction_revision']

def test_stale_wrong_world_and_invalid_contract_are_safe(fixture):
    c,g,p=fixture;request=body(g).model_dump(mode='json')
    assert c.post('/api/corrections',json={**request,'pack_id':'other'}).status_code==409
    assert c.post('/api/corrections',json={**request,'revision':'old'}).status_code==409
    assert c.post('/api/corrections',json={**request,'mode':'anything'}).status_code==422
    assert c.post('/api/corrections',json={**request,'instruction':' '}).status_code==400
    assert not p.requests and g.state['hp']==20
