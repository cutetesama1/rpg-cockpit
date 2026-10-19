from __future__ import annotations
import base64,json,sys
from types import SimpleNamespace
from conftest import ROOT,roles,say
import pytest
from fastapi.testclient import TestClient
if str(ROOT/'api') not in sys.path:sys.path.insert(0,str(ROOT/'api'))
import main as api
from rpg_gateway import LlmRouter,LlmResponse,ScriptedProvider
from rpg_gateway.settings import default_settings
from rpg_core.contracts import NarratorOutput,ToolCall
from rpg_core.saves import save_session,read_save,restore_session

@pytest.fixture()
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('RPG_USER_PACKS',str(tmp_path/'packs'))
    monkeypatch.setenv('RPG_LIBRARY',str(tmp_path/'library.json'))
    monkeypatch.setenv('RPG_SKILL_LIBRARIES',str(tmp_path/'skill-libraries'))
    monkeypatch.setenv('RPG_SAVES',str(tmp_path/'saves'))
    saved=(api.manager.user_dir,api.manager.pack_dir,api.manager.session,dict(api.manager.library),api.manager.settings)
    api.manager.user_dir=tmp_path/'packs';api.manager.settings=default_settings();api.manager.library={}
    api.manager.select('night-convenience-store')
    yield TestClient(api.app)
    api.manager.user_dir,api.manager.pack_dir,api.manager.session,api.manager.library,api.manager.settings=saved


def install(client):
    r=client.post('/api/skill-libraries/install-standard',json={})
    assert r.status_code==200,r.text
    return r.json()


def test_import_list_template_and_duplicate_without_switching_world(client):
    before=client.get('/api/state').json()['pack']['id']
    assert client.get('/api/skill-libraries').json()['total_skills']==0
    assert install(client)['library']['count']==300
    assert client.get('/api/state').json()['pack']['id']==before
    data=client.get('/api/skill-libraries/standard-martial-magic').json()
    assert len(data['skills'])==300
    r=client.get('/api/skill-libraries/template.zip')
    assert r.status_code==200 and r.content.startswith(b'PK')
    imported=client.post('/api/skill-libraries/import',json={'filename':'custom.zip','data_base64':base64.b64encode(r.content).decode()})
    assert imported.status_code==200 and imported.json()['total_skills']==301
    assert client.post('/api/skill-libraries/install-standard',json={}).status_code==400
    assert client.get('/api/skill-libraries/missing').status_code==404


def test_invalid_zip_and_readonly_world_do_not_mutate(client):
    assert client.post('/api/skill-libraries/import',json={'data_base64':'invalid'}).status_code==400
    assert client.post('/api/skill-libraries/import',json={'data_base64':base64.b64encode(b'not zip').decode()}).status_code==400
    assert client.post('/api/world/skill-catalog/match',json={}).status_code==400
    assert client.get('/api/skill-libraries').json()['total_skills']==0


class SelectorProvider:
    name='selector'
    def __init__(self,strong=False):self.strong=strong;self.requests=[]
    def complete(self,request):
        self.requests.append(request)
        if request.get('phase')=='skill_selection':
            refs=[e['ref'] for e in request['candidates'] if e['kind']=='magic' and e['school']!='空间']
            initial=refs if self.strong else [ref for ref in refs if ref.endswith('low_01')][:2]
            return LlmResponse(narrator=NarratorOutput(narrative=json.dumps({'world_tags':['magic'],'skill_refs':refs,'initial_refs':initial,'reason':'强大法师' if self.strong else '学徒背景'})),model='offline-selector')
        return say('你继续沿着走廊前进。')


@pytest.mark.parametrize('strong',[False,True])
def test_builder_creation_configures_initial_mastery_from_background(client,monkeypatch,strong):
    install(client);p=SelectorProvider(strong);router=LlmRouter(roles(p.name),{p.name:p})
    monkeypatch.setattr(api,'build_router',lambda settings:router)
    pre='你是一名十分强大的法师，精通众多魔法。' if strong else '你是一名刚入门的魔法学徒。'
    response=client.post('/api/world/builder/apply',json={'id':'role-world','draft':{'title':'角色世界','prompts':{'pre':pre}}})
    assert response.status_code==200,response.text
    pool=client.get('/api/world/skill-catalog').json()
    assert len(pool['skills'])==135
    assert sum(e['known'] for e in pool['skills'])==(135 if strong else 2)
    assert sum(e['tier']=='high' and e['known'] for e in pool['skills'])==(45 if strong else 0)
    status=client.get('/api/state').json()
    assert len(status['skills'])==(136 if strong else 3)
    assert any(r.get('phase')=='skill_selection' for r in p.requests)
    assert api.manager.session.pack.skill_selection['method']=='llm'


def test_match_existing_world_preserves_events_mastery_and_save(client,monkeypatch,tmp_path):
    r=client.post('/api/world/builder/apply',json={'id':'existing-world','draft':{'title':'已有世界','prompts':{'pre':'你是一名魔法学徒。'}}})
    assert r.status_code==200
    before_skills=[s.id for s in api.manager.session.all_skills()]
    api.manager.session.debug_set_state({'focus':7})
    events=[e.model_dump(mode='json') for e in api.manager.session.ledger.events]
    install(client);p=SelectorProvider();router=LlmRouter(roles(p.name),{p.name:p})
    monkeypatch.setattr(api,'build_router',lambda settings:router)
    matched=client.post('/api/world/skill-catalog/match',json={})
    assert matched.status_code==200,matched.text
    assert [e.model_dump(mode='json') for e in api.manager.session.ledger.events]==events
    assert api.manager.session.state['focus']==7
    assert [s.id for s in api.manager.session.all_skills()]==before_skills
    assert len(client.get('/api/world/skill-catalog').json()['skills'])==135
    assert client.get('/api/replay/verify').json()['equal']
    saved=client.post('/api/saves',json={'slot':'catalog-progress','label':'技能库匹配后'})
    assert saved.status_code==200
    loaded=client.post('/api/saves/load',json={'slot':'catalog-progress'})
    assert loaded.status_code==200 and loaded.json()['status']['state']['focus']==7
