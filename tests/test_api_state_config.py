"""API regressions for editable resources, shared portraits and model-setting preservation."""
import json
from test_api_skill_library import client
import main as api
from rpg_gateway import LlmResponse
from rpg_core.contracts import NarratorOutput

def create(client,ident='state-world',pre='你是魔法学院的初学者。',state=None):
    draft={'title':'琉璃学院','prompts':{'pre':pre}}
    if state:draft['state']=state
    r=client.post('/api/world/builder/apply',json={'id':ident,'draft':draft});assert r.status_code==200,r.text
    return r.json()

def test_model_settings_and_prompts_preserve_live_progress(client):
    create(client)
    api.manager.session.debug_set_state({'hp':7})
    before=client.get('/api/state').json()
    assert client.post('/api/settings',json={}).status_code==200
    after=client.get('/api/state').json()
    assert after['state']==before['state'] and after['events']==before['events']
    assert client.put('/api/world/prompts',json={'narrator':'只写短篇叙述。'}).status_code==200
    assert client.get('/api/state').json()['state']==before['state']

def test_created_world_has_shared_portrait_and_pack_scoped_asset_key(client):
    create(client)
    sprite=client.get('/api/sprite').json()['sheet']
    assert sprite and sprite['asset_key'].startswith('state-world:')
    # Resolve the first static PNG path: actual shared image route, not merely metadata.
    layer=next(l for l in sprite['layers'] if '{' not in l['src'])
    image=client.get('/api/pack/asset/'+layer['src'])
    assert image.status_code==200 and image.content.startswith(b'\x89PNG')
    assert client.get('/api/pack/asset/../../../settings.json').status_code in (403,404)

def test_state_editor_endpoint_preserves_values_and_replays_schema(client):
    create(client)
    api.manager.session.debug_set_state({'hp':57})
    world=client.get('/api/world').json();data=world['state']
    field=next(f for f in data['fields'] if f['id']=='hp');field.update(label='气血',default=200,max=200)
    r=client.put('/api/world/state',json={'state':data});assert r.status_code==200,r.text
    assert r.json()['status']['state']['hp']==57
    assert next(f for f in r.json()['status']['fields'] if f['id']=='hp')['max']==200
    assert client.post('/api/saves',json={'slot':'fields'}).status_code==200
    assert client.post('/api/saves/load',json={'slot':'fields'}).status_code==200
    assert client.post('/api/undo',json={}).json()['state']['hp']==57
    assert next(f for f in client.get('/api/state').json()['fields'] if f['id']=='hp')['max']==100

def test_powerful_zero_mastery_model_result_is_repaired_from_background(client,monkeypatch):
    client.post('/api/skill-libraries/install-standard',json={})
    class Selector:
        name='selector'
        def complete(self,request):
            refs=[e['ref'] for e in request['candidates'] if e['kind']=='magic' and e['school']!='空间']
            return LlmResponse(narrator=NarratorOutput(narrative=json.dumps({'world_tags':['magic'],'skill_refs':refs,'initial_refs':[]})))
    from rpg_gateway import LlmRouter
    from conftest import roles
    router=LlmRouter(roles('selector'),{'selector':Selector()})
    monkeypatch.setattr(api,'build_router',lambda settings:router)
    create(client,pre='你是一名十分强大的大法师，已经精通多种魔法。')
    pool=client.get('/api/world/skill-catalog').json()
    assert len(pool['skills'])==135 and sum(s['known'] for s in pool['skills'])==135

def test_custom_mana_field_binds_presets_without_legacy_focus(client):
    client.post('/api/skill-libraries/install-standard',json={})
    state={'fields':[{'id':'crystal','label':'琉璃魔力','type':'int','min':0,'max':240,'default':240,'display':'bar'}],'resource_bindings':{'mana':'crystal'}}
    create(client,state=state)
    pool=client.get('/api/world/skill-catalog').json()['skills']
    assert pool and all(set(e['skill']['cost'])<={'crystal'} for e in pool)
    assert 'focus' not in client.get('/api/state').json()['state']


def test_matching_library_after_numeric_edit_retains_new_catalog(client):
    create(client)
    data=client.get('/api/world').json()['state']
    next(f for f in data['fields'] if f['id']=='hp').update(default=200,max=200)
    assert client.put('/api/world/state',json={'state':data}).status_code==200
    assert client.post('/api/skill-libraries/install-standard',json={}).status_code==200
    result=client.post('/api/world/skill-catalog/match',json={})
    assert result.status_code==200,result.text
    assert len(client.get('/api/world/skill-catalog').json()['skills'])==135
    assert next(f for f in client.get('/api/state').json()['fields'] if f['id']=='hp')['max']==200
    assert client.get('/api/replay/verify').json()['equal']
