import json
import pytest
from fastapi.testclient import TestClient
from test_api_director import api
from test_adjudication import pending_game
from rpg_core.saves import read_save


@pytest.fixture()
def fixture(tmp_path,monkeypatch):
    previous=api.manager.session
    g,n,_=pending_game();api.manager.session=g
    monkeypatch.setenv('RPG_SAVES',str(tmp_path/'saves'));monkeypatch.setenv('RPG_AUTOSAVE','1')
    try:yield TestClient(api.app),g,n
    finally:api.manager.session=previous


def body(client,g,action='confirm',**extra):
    data=client.get('/api/adjudications').json();key=data['items'][0]['id']
    return key,{'pack_id':g.pack.manifest.id,'decision':{'request_id':'api-request-'+action,'revision':data['revision'],'action':action,**extra}}


def test_preview_no_writes_confirmation_persists_and_repeat_is_safe(fixture):
    c,g,n=fixture;key,data=body(c,g);before=g.ledger.to_dicts();calls=len(n.requests)
    p=c.post(f'/api/adjudications/{key}/preview',json=data)
    assert p.status_code==200 and before==g.ledger.to_dicts()
    assert c.post(f'/api/adjudications/{key}/decide',json=data).status_code==409
    data['decision']['preview_token']=p.json()['preview_token']
    a=c.post(f'/api/adjudications/{key}/decide',json=data)
    b=c.post(f'/api/adjudications/{key}/decide',json=data)
    assert a.status_code==b.status_code==200 and b.json()['reused'] and g.state['hp']==18
    assert len(n.requests)==calls and g.turn==1
    saved=read_save('auto');assert saved['state']['hp']==18
    assert any(e['kind']=='adjudication.decided' for e in saved['events'])


def test_world_revision_conflicts_and_injected_operations_are_rejected(fixture):
    c,g,_=fixture;key,data=body(c,g)
    wrong={**data,'pack_id':'other-world'}
    assert c.post(f'/api/adjudications/{key}/preview',json=wrong).status_code==409
    assert c.post(f'/api/adjudications/{key}/decide',json=wrong).status_code==409
    data['decision']['operations']=[]
    assert c.post(f'/api/adjudications/{key}/preview',json=data).status_code==400
    data['decision']['action']='defer';data['decision']['request_id']='deferral'
    assert c.post(f'/api/adjudications/{key}/decide',json=data).status_code==400
    del data['decision']['operations']
    assert c.post(f'/api/adjudications/{key}/decide',json=data).status_code==200
    data['decision']['action']='resume';data['decision']['request_id']='new-request'
    assert c.post(f'/api/adjudications/{key}/decide',json=data).status_code==409


@pytest.mark.parametrize('operations',[[{'name':'not-a-tool','args':{},'evidence':'x'}],[{'name':'damage','args':{'amount':-1},'evidence':'x'}],[{'name':'set_stat','args':{'field':'missing','value':3},'evidence':'x'}]])
def test_bad_modification_returns_readable_error_without_partial_change(fixture,operations):
    c,g,_=fixture;key,data=body(c,g,'modify',reason='玩家裁定',operations=operations)
    before=g.ledger.to_dicts();response=c.post(f'/api/adjudications/{key}/preview',json=data)
    assert response.status_code==400 and response.json()['detail']
    assert before==g.ledger.to_dicts()


def test_internal_mode_is_explicit_and_secret_is_absent_from_public_endpoints(fixture):
    c,_,_=fixture;g,n,_=pending_game(visibility='internal');api.manager.session=g
    assert c.get('/api/adjudications').json()['items']==[]
    internal=c.get('/api/adjudications?include_internal=true').json();key=internal['items'][0]['id']
    data={'pack_id':g.pack.manifest.id,'decision':{'action':'confirm','request_id':'secret-confirm','revision':internal['revision']}}
    assert c.post(f'/api/adjudications/{key}/preview',json=data).status_code==404
    data['include_internal']=True
    p=c.post(f'/api/adjudications/{key}/preview',json=data);assert p.status_code==200
    data['decision']['preview_token']=p.json()['preview_token']
    assert c.post(f'/api/adjudications/{key}/decide',json=data).status_code==200
    for endpoint in ['/api/state','/api/adjudications','/api/log/export','/api/debug/catalog']:
        text=c.get(endpoint).text
        assert '伤势需要裁定' not in text and 'adjudication.decided' not in text


def test_missing_or_non_object_operation_fails_request_contract(fixture):
    c,g,_=fixture;key,data=body(c,g,'modify',reason='玩家裁定',operations=[None])
    assert c.post(f'/api/adjudications/{key}/preview',json=data).status_code==422
