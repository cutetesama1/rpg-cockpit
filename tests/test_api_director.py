import json
import pytest
from fastapi.testclient import TestClient
from conftest import ROOT
import sys
if str(ROOT/'api') not in sys.path:sys.path.insert(0,str(ROOT/'api'))
import main as api
from test_director_dice import game,candidate
from rpg_core.saves import read_save

@pytest.fixture()
def fixture(tmp_path,monkeypatch):
    old=api.manager.session
    g,p=game([candidate()]);api.manager.session=g
    monkeypatch.setenv('RPG_SAVES',str(tmp_path/'saves'))
    monkeypatch.setenv('RPG_AUTOSAVE','1')
    try:yield TestClient(api.app),g,p
    finally:api.manager.session=old

def test_config_is_opt_in_game_scoped_persisted_and_requires_current_pack(fixture):
    client,g,p=fixture
    data=client.get('/api/director').json()
    assert data['config']['enabled'] is False and 'audit' not in data
    config={**data['config'],'enabled':True}
    assert client.put('/api/director',json={'pack_id':'wrong-world','config':config}).status_code==409
    assert client.post('/api/director/request',json={'pack_id':g.pack.manifest.id}).status_code==400
    response=client.put('/api/director',json={'pack_id':g.pack.manifest.id,'config':config})
    assert response.status_code==200 and response.json()['config']['enabled']
    saved=read_save('auto')
    assert any(e['kind']=='director.configured' for e in saved['events'])
    assert any(e['kind']=='dice.seeded' for e in saved['events'])
    assert not p.requests

def test_manual_dice_record_retry_and_conflict_have_no_model_calls(fixture):
    client,g,p=fixture
    body={'pack_id':g.pack.manifest.id,'event_id':'click-one','check':{'kind':'dice','dice':'2d20kh1','target':10}}
    a=client.post('/api/dice/roll',json=body)
    b=client.post('/api/dice/roll',json=body)
    assert a.status_code==b.status_code==200
    assert a.json()['result']==b.json()['result'] and b.json()['reused'] and not a.json()['reused']
    assert len([e for e in g.ledger.events if e.kind=='roll.resolved'])==1
    body['check']['dice']='1d6'
    assert client.post('/api/dice/roll',json=body).status_code==409
    assert not p.requests
    assert not any(e['kind'].startswith('dice.') for e in client.get('/api/state').json()['events'])
    assert any(e['kind']=='dice.resolved' for e in read_save('auto')['events'])

@pytest.mark.parametrize('namespace',['director:test','settlement:test'])
def test_manual_tool_cannot_impersonate_system_events(fixture,namespace):
    client,g,_=fixture
    assert client.post('/api/dice/roll',json={'pack_id':g.pack.manifest.id,'event_id':namespace,'check':{'dice':'1d20'}}).status_code==400
    assert not any(e.kind=='dice.resolved' for e in g.ledger.events)

def test_candidate_and_entropy_are_hidden_from_all_default_player_views(fixture):
    client,g,p=fixture
    p.candidates=[candidate(chance=0,success='UNFIRED_PLOT_SECRET')]
    cfg=client.get('/api/director').json()['config'];cfg['enabled']=True
    assert client.put('/api/director',json={'pack_id':g.pack.manifest.id,'config':cfg}).status_code==200
    result=client.post('/api/action',json={'action':{'text':'观察'}})
    assert result.status_code==200 and result.json()['ok']
    for endpoint in ['/api/director','/api/state','/api/debug/catalog','/api/log/export']:
        response=client.get(endpoint)
        assert response.status_code==200
        assert 'UNFIRED_PLOT_SECRET' not in response.text and 'dice.seeded' not in response.text
    audit=client.get('/api/director?include_internal=true').json()
    assert 'UNFIRED_PLOT_SECRET' in json.dumps(audit,ensure_ascii=False)
    assert 'dice.seeded' not in json.dumps(audit)

def test_failed_turn_keeps_audited_results_in_autosave(fixture):
    client,g,p=fixture
    cfg=client.get('/api/director').json()['config'];cfg['enabled']=True
    client.put('/api/director',json={'pack_id':g.pack.manifest.id,'config':cfg})
    p.fail_narrator=1
    response=client.post('/api/action',json={'action':{'text':'观察'}})
    assert response.status_code==200 and not response.json()['ok']
    saved=read_save('auto')
    assert saved['state']==g.state
    assert any(e['kind']=='dice.resolved' for e in saved['events'])
    assert any(e['kind']=='turn.rolled_back' for e in saved['events'])

def test_clue_edit_is_idempotent_and_internal_data_stays_private(fixture):
    client,g,_=fixture
    clue={'id':'secret','title':'幕后线索','summary':'PRIVATE_THREAD','status':'open','visibility':'internal'}
    body={'pack_id':g.pack.manifest.id,'clue':clue}
    assert client.put('/api/director/clues',json=body).status_code==200
    assert client.put('/api/director/clues',json=body).status_code==200
    assert len([e for e in g.ledger.events if e.kind=='plot.clue.updated'])==1
    assert not client.get('/api/director').json()['clues']
    assert len(client.get('/api/director?include_internal=true').json()['clues'])==1

def test_stream_broadcast_does_not_publish_raw_candidates(fixture):
    client,g,p=fixture
    p.candidates=[candidate(chance=0,success='RAW_STREAM_CANDIDATE')]
    cfg=client.get('/api/director').json()['config'];cfg['enabled']=True
    client.put('/api/director',json={'pack_id':g.pack.manifest.id,'config':cfg})
    response=client.post('/api/action/stream',json={'action':{'text':'观察'}})
    assert response.status_code==200 and 'event: result' in response.text
    assert 'RAW_STREAM_CANDIDATE' not in response.text and 'dice.seeded' not in response.text and 'director.proposed' not in response.text
