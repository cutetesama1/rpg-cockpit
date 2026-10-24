import base64,json,copy
import pytest
from test_api_library import client,manager
from test_character_cards import card,encoded
from rpg_core.personality_npcs import roster_for
from rpg_core.dynamic_worldbook import entries_for

def prepare(client):
    result=client.post('/api/library/clone',json={'source':'night-convenience-store','id':'personality-world'})
    assert result.status_code==200,result.text
    a=card();a['data'].update(name='莉瑟',likes=['茶'],personality='沉静，喜欢书籍',system_prompt='DO_NOT_IMPORT_PROMPT')
    b=card();b['data'].update(name='船长',personality='开朗，好奇')
    files=[{'filename':name,'data_base64':base64.b64encode(encoded(value)).decode()} for name,value in [('a.json',a),('b.json',b)]]
    preview=client.post('/api/personality-npcs/preview',json={'pack_id':manager.active_pack,'files':files});assert preview.status_code==200,preview.text
    p=preview.json()
    return {'files':files,'pack_id':p['pack_id'],'request_id':'npc-batch','preview_token':p['preview_token'],'revision':p['revision'],'npcs':[item['npc'] for item in p['items']]}

def test_multi_import_keeps_current_world_progress_prompts_and_exact_sources(client):
    body=prepare(client);session=manager.session;prompts=copy.deepcopy(session.pack.prompts)
    result=client.post('/api/personality-npcs/import',json=body);assert result.status_code==200,result.text
    assert len(result.json()['roster']['npcs'])==2 and result.json()['director_required']
    assert manager.session is session and manager.session.pack.prompts==prompts
    assert client.get('/api/director').json()['config']['enabled']
    npc_id=body['npcs'][0]['id'];source=client.get(f'/api/personality-npcs/source/{npc_id}?pack_id={manager.active_pack}')
    assert source.status_code==200 and source.json()['data']['system_prompt']=='DO_NOT_IMPORT_PROMPT'
    assert (manager.pack_dir/'personality-cards'/npc_id/'source.bin').read_bytes()==base64.b64decode(body['files'][0]['data_base64'])
    retry=client.post('/api/personality-npcs/import',json=body);assert retry.status_code==200 and retry.json()['reused']
    assert len(roster_for(manager.session).npcs)==2

def test_selected_subset_and_custom_personality_are_honored(client):
    body=prepare(client);body['npcs']=body['npcs'][:1];body['npcs'][0].update(min_turn=8,min_progress=3,entrance_hint='旅馆中出场',personality='谨慎，善于观察')
    result=client.post('/api/personality-npcs/import',json=body);assert result.status_code==200,result.text
    assert len(result.json()['roster']['npcs'])==1 and result.json()['roster']['npcs'][0]['min_turn']==8

def test_stale_revision_source_tampering_and_duplicate_sources_rejected(client):
    body=prepare(client);bad=copy.deepcopy(body);bad['npcs'][0]['source_hash']='0'*64
    assert client.post('/api/personality-npcs/import',json=bad).status_code==400
    bad=copy.deepcopy(body);bad['preview_token']='0'*64
    assert client.post('/api/personality-npcs/import',json=bad).status_code==409
    bad=copy.deepcopy(body);bad['revision']='stale'
    assert client.post('/api/personality-npcs/import',json=bad).status_code==409
    preview={'pack_id':body['pack_id'],'files':[body['files'][0]]*2}
    assert client.post('/api/personality-npcs/preview',json=preview).status_code==400
    assert not roster_for(manager.session).npcs

def test_director_cannot_be_disabled_before_personality_mode(client):
    body=prepare(client);assert client.post('/api/personality-npcs/import',json=body).status_code==200
    config=client.get('/api/director').json()['config'];config['enabled']=False
    assert client.put('/api/director',json={'pack_id':body['pack_id'],'config':config}).status_code==400
    view=client.get('/api/personality-npcs').json();view['roster']['enabled']=False
    edit={'pack_id':view['pack_id'],'request_id':'disable-mode','revision':view['revision'],'roster':view['roster']}
    assert client.put('/api/personality-npcs',json=edit).status_code==200
    assert client.put('/api/director',json={'pack_id':body['pack_id'],'config':config}).status_code==200

def test_builtin_import_returns_friendly_error_without_writes(client):
    p=client.get('/api/personality-npcs').json()
    result=client.put('/api/personality-npcs',json={'pack_id':p['pack_id'],'request_id':'readonly','revision':p['revision'],'roster':{'enabled':True,'npcs':[]}})
    assert result.status_code==400 and not manager.user_dir.exists()

def test_dynamic_manual_change_uses_adjudication_preview_confirm_and_undo(client):
    body={'pack_id':manager.active_pack,'request_id':'memory-manual','reason':'守港人承诺帮你寻找旧船票。',
          'change':{'id':'keeper_promise','kind':'fact','title':'守港人的承诺','content':'守港人承诺帮你寻找旧船票。'}}
    response=client.post('/api/world/dynamic/propose',json=body);assert response.status_code==200,response.text
    assert not entries_for(manager.session)
    retry=client.post('/api/world/dynamic/propose',json=body);assert retry.json()['reused']
    data=client.get('/api/adjudications').json();item=next(i for i in data['items'] if i['origin']=='world_builder')
    decision={'request_id':'confirm-worldbook','revision':data['revision'],'action':'confirm'}
    params={'pack_id':manager.active_pack,'decision':decision}
    preview=client.post('/api/adjudications/'+item['id']+'/preview',json=params);assert preview.status_code==200,preview.text
    assert any(c['domain']=='worldbook' for c in preview.json()['changes'])
    decision['preview_token']=preview.json()['preview_token']
    commit=client.post('/api/adjudications/'+item['id']+'/decide',json=params);assert commit.status_code==200,commit.text
    assert entries_for(manager.session)['keeper_promise']['version']==1
    undo={'pack_id':manager.active_pack,'decision':{'request_id':'undo-worldbook','revision':commit.json()['revision'],'action':'undo'}}
    response=client.post('/api/adjudications/'+item['id']+'/decide',json=undo);assert response.status_code==200,response.text
    assert not entries_for(manager.session)

def test_dynamic_secret_proposal_is_only_in_internal_adjudications(client):
    body={'pack_id':manager.active_pack,'request_id':'secret','reason':'幕后约定已发生。','change':{'id':'hidden_pact','kind':'secret','title':'幕后约定','content':'PRIVATE_HIDDEN_PACT'}}
    assert client.post('/api/world/dynamic/propose',json=body).status_code==200
    assert not client.get('/api/adjudications').json()['items']
    assert client.get('/api/adjudications?include_internal=true').json()['items']
    assert 'PRIVATE_HIDDEN_PACT' not in json.dumps(client.get('/api/world/dynamic').json())

def test_all_files_roll_back_if_archive_validation_fails(client,monkeypatch):
    body=prepare(client);before=manager.session
    import rpg_content.library as library
    def reject(*args,**kw):raise ValueError('invalid archive')
    monkeypatch.setattr(library,'load_pack',reject)
    response=client.post('/api/personality-npcs/import',json=body)
    assert response.status_code==400
    assert manager.session is before and not roster_for(manager.session).npcs
    assert not (manager.pack_dir/'personality-npcs.json').exists()
    assert not list((manager.pack_dir/'personality-cards').rglob('source.bin'))
